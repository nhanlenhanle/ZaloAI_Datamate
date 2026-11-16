"""Chỗ nối LLM cho lớp data (model dự kiến: Qwen3.5-9B, dùng chung với phía query).

Nguyên tắc: luật chạy trước; LLM chỉ nhận phần luật KHÔNG nhận ra, dưới dạng tóm tắt nhỏ
(không bao giờ cả bảng). Kết quả LLM phải qua kiểm tra trước khi dùng. Chưa nối model thì
mọi hàm trả rỗng và pipeline vẫn chạy như chỉ có luật.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import os
import threading
import time
import urllib.error
import urllib.request

# Server chuẩn OpenAI (vLLM). Lúc thi: vLLM trong Docker, mỗi GPU một server.
# Không đặt DATAMATE_LLM_URL -> available() = False, pipeline chỉ chạy luật. Nhiều server: các URL cách nhau dấu phẩy.
_URLS = [u.strip().rstrip("/") for u in os.environ.get("DATAMATE_LLM_URL", "").split(",") if u.strip()]
_URL = _URLS[0] if _URLS else ""
_turn = itertools.count()
_KEYS = [k.strip() for k in os.environ.get("DATAMATE_LLM_KEY", "").split(",") if k.strip()]
_KEY = _KEYS[0] if _KEYS else ""
_MODEL = os.environ.get("DATAMATE_LLM_MODEL", "")
# DATAMATE_LLM_EXTRA='{"reasoning_effort": "none"}': trường gửi thêm mỗi request. ollama bản mới tự bật chế độ suy nghĩ của
# Qwen3.5 (bỏ qua template), chỉ tắt được bằng trường này; vLLM tắt bằng chat_template_kwargs nên không cần.
_EXTRA = json.loads(os.environ.get("DATAMATE_LLM_EXTRA") or "{}")
# DATAMATE_LLM_CACHE=<file.jsonl>: lưu câu trả lời theo (model, prompt) -> chạy lại không hỏi lại, tái lập được
_CACHE_PATH = os.environ.get("DATAMATE_LLM_CACHE", "")
_HAN_CHOT = float(os.environ.get("DATAMATE_HAN_CHOT") or 0)
_cache: dict | None = None
_lock = threading.Lock()


def _cache_key(body: dict) -> str:
    return hashlib.sha1(json.dumps(body, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _cache_load() -> dict:
    global _cache
    if _cache is None:
        _cache = {}
        if _CACHE_PATH and os.path.exists(_CACHE_PATH):
            with open(_CACHE_PATH, encoding="utf-8") as fh:
                for line in fh:
                    r = json.loads(line)
                    _cache[r["k"]] = r["v"]
    return _cache


def _post(path: str, body: dict | None, timeout: float, tries: int = 3) -> dict:
    """Gửi lần lượt cho các server; lỗi mạng hay server bận thì thử lại (server khác nếu có), hết lượt mới báo lỗi."""
    for k in range(tries):
        if _HAN_CHOT:       # run.sh đặt DATAMATE_HAN_CHOT: sát hạn thì cắt thời gian chờ, quá hạn thì không gọi nữa
            con = _HAN_CHOT - time.time()
            if con <= 5:
                raise TimeoutError("hết giờ thi (DATAMATE_HAN_CHOT)")
            timeout = min(timeout, con)
        idx = next(_turn) % len(_URLS) if _URLS else 0
        url = _URLS[idx] if _URLS else _URL
        key = _KEYS[idx] if idx < len(_KEYS) else _KEY      # mỗi URL một key (DATAMATE_LLM_KEY cách nhau dấu phẩy)
        req = urllib.request.Request(url + path, data=None if body is None else json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode())
        except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
            if k == tries - 1 or (isinstance(e, urllib.error.HTTPError) and e.code < 500):
                raise
            time.sleep(2 * (k + 1))
    raise RuntimeError("không gọi được LLM")


def available() -> bool:
    return bool(_URL)


def model_name() -> str:
    global _MODEL
    if not _MODEL:
        _MODEL = _post("/v1/models", None, 30)["data"][0]["id"]
    return _MODEL


def _chat_raw(system: str, user: str, max_tokens: int = 512, timeout: float = 120, temperature: float = 0,
              n: int = 1, top_p: float | None = None, seed: int = 2026) -> list[str]:
    """Gọi /v1/chat/completions; n >= 1 lấy n mẫu trong một request (vLLM dùng chung phần prompt)."""
    body = {"model": model_name(), "temperature": temperature, "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "chat_template_kwargs": {"enable_thinking": False}}
    if temperature:             # cố định để chạy lại ra cùng kết quả (thể lệ: hai lần chạy lệch tối đa 0.03)
        body["seed"] = seed
    body.update(_EXTRA)
    if n > 1:
        body["n"] = n
    if top_p is not None:       # sau _EXTRA: top_p riêng (vd 0.9 khi lấy nhiều mẫu) không bị top_p chung đè
        body["top_p"] = top_p
    key = _cache_key(body) if _CACHE_PATH else None
    if key:
        with _lock:
            hit = _cache_load().get(key)
        if hit is not None:
            return hit if isinstance(hit, list) else [hit]
    texts = [c["message"]["content"] for c in _post("/v1/chat/completions", body, timeout)["choices"]]
    if key:
        val = texts[0] if n == 1 else texts
        with _lock:
            _cache_load()[key] = val
            with open(_CACHE_PATH, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"k": key, "v": val}, ensure_ascii=False) + "\n")
    return texts


def chat_n(system: str, user: str, max_tokens: int = 512, timeout: float = 120, temperature: float = 0.7,
           n: int = 4, top_p: float | None = 0.9, seed: int = 2026) -> list[str]:
    """n mẫu một request (DPC: 4 ứng viên SQL nhiệt độ 0.7)."""
    return _chat_raw(system, user, max_tokens=max_tokens, timeout=timeout, temperature=temperature, n=n, top_p=top_p,
                     seed=seed)


def chat(system: str, user: str, max_tokens: int = 512, timeout: float = 120, temperature: float = 0) -> str:
    """Một lượt hỏi, mặc định nhiệt độ 0, tắt chế độ suy nghĩ (Qwen3.5 mặc định bật -> chậm, dài)."""
    return _chat_raw(system, user, max_tokens=max_tokens, timeout=timeout, temperature=temperature, n=1)[0]
