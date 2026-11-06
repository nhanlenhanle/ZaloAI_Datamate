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

# Server chuẩn OpenAI (vLLM). Lúc phát triển: Colab + tunnel; lúc thi: vLLM trong Docker, mỗi GPU một server.
# Không đặt DATAMATE_LLM_URL -> available() = False, pipeline chỉ chạy luật. Nhiều server: các URL cách nhau dấu phẩy.
_URLS = [u.strip().rstrip("/") for u in os.environ.get("DATAMATE_LLM_URL", "").split(",") if u.strip()]
_URL = _URLS[0] if _URLS else ""
_turn = itertools.count()
_KEY = os.environ.get("DATAMATE_LLM_KEY", "")
_MODEL = os.environ.get("DATAMATE_LLM_MODEL", "")
# DATAMATE_LLM_EXTRA='{"reasoning_effort": "none"}': trường gửi thêm mỗi request. ollama bản mới tự bật chế độ suy nghĩ của
# Qwen3.5 (bỏ qua template), chỉ tắt được bằng trường này; vLLM tắt bằng chat_template_kwargs nên không cần.
_EXTRA = json.loads(os.environ.get("DATAMATE_LLM_EXTRA") or "{}")
# DATAMATE_LLM_CACHE=<file.jsonl>: lưu câu trả lời theo (model, prompt) -> chạy lại không hỏi lại, tái lập được
_CACHE_PATH = os.environ.get("DATAMATE_LLM_CACHE", "")
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
        url = _URLS[next(_turn) % len(_URLS)] if _URLS else _URL
        req = urllib.request.Request(url + path, data=None if body is None else json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json", "Authorization": f"Bearer {_KEY}"})
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


def chat(system: str, user: str, max_tokens: int = 512, timeout: float = 120, temperature: float = 0) -> str:
    """Một lượt hỏi, mặc định nhiệt độ 0, tắt chế độ suy nghĩ (Qwen3.5 mặc định bật -> chậm, dài)."""
    body = {"model": model_name(), "temperature": temperature, "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "chat_template_kwargs": {"enable_thinking": False}}
    if temperature:             # cố định để chạy lại ra cùng kết quả (thể lệ: hai lần chạy lệch tối đa 0.03)
        body["seed"] = 2026
    body.update(_EXTRA)
    key = _cache_key(body) if _CACHE_PATH else None
    if key:
        with _lock:
            hit = _cache_load().get(key)
        if hit is not None:
            return hit
    text = _post("/v1/chat/completions", body, timeout)["choices"][0]["message"]["content"]
    if key:
        with _lock:
            _cache_load()[key] = text
            with open(_CACHE_PATH, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"k": key, "v": text}, ensure_ascii=False) + "\n")
    return text
