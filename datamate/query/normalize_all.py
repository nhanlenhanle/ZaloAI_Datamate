"""Chuẩn hóa câu hỏi hàng loạt qua model qwen_norm (Mask <ENT_X> từ DuckDB -> LLM -> Guardrail -> Unmask).

Hỗ trợ chạy độc lập cho mọi tập dữ liệu (bộ đề, examples_train, examples_luat)
chỉ dựa vào DuckDB của shop, có lưu cache từng câu để resume tức thì.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
import time
import unicodedata
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import duckdb

from datamate.loader.parsers import fold
from datamate.query.compose import asks_yes_no, near_rules

NORM_SYSTEM_PROMPT = (
    "Bạn là chuyên gia chuẩn hóa câu hỏi tiếng Việt cho bài toán Text-to-SQL quản lý bán hàng.\n"
    "Nhiệm vụ: Sửa lỗi chính tả, teencode, viết tắt, thêm dấu và chuẩn hóa câu hỏi rõ ràng về hình thức và kiểu trả về (bảng, danh sách, %).\n"
    "Nếu có mục \"Luật liên quan:\", PHẢI giữ nguyên đúng tên thuật ngữ trong luật, không tự ý đổi sang chỉ số khác và không tự chèn giải thích dài trong ngoặc.\n"
    "TUYỆT ĐỐI GIỮ NGUYÊN các thẻ placeholder <ENT_X>. Chỉ trả về đúng 1 câu chuẩn hóa."
)

# Regex bắt các thực thể cú pháp (chuỗi trong ngoặc, ngày/tháng, mã SKU/đơn, số tiền có dấu chấm)
_QUOTE_RE = re.compile(r'("[^"]+"|\'[^\']+\')')
# Ngày DD/MM/YYYY hoặc Tháng M/YYYY, M/YY, M-YYYY (không bắt phần số sau chữ Q/quý)
_DATE_RE = re.compile(
    r"(?<![\d/.-])(?:\d{1,2}[/-]\d{1,2}[/-](?:20\d\d|\d\d)|(?:1[0-2]|0?[1-9])[/-](?:20\d\d|[23]\d))(?![\d/.-])"
)
_SKU_RE = re.compile(r"\b(?:[A-Za-z]{1,5}[-_]\d+[A-Za-z0-9]*|(?!Q[1-4]\b|T\d{1,2}\b|L\d+\b)[A-Za-z]{2,5}\d{2,}[A-Za-z0-9]*)\b")
_MONEY_DOT_RE = re.compile(r"\b\d{1,3}(?:\.\d{3})+\b")

# Các từ chung không được coi là tên thực thể đơn lẻ nếu quá ngắn
_GENERIC_ENT_STOP = {
    "tra", "banh", "keo", "sua", "nuoc", "thuoc", "hang", "don", "khach", "khach le", "khach vang lai",
    " tiền mặt", "tien mat", "chuyen khoan", "tai quay", "dien thoai", "zalo", "shopee", "grab",
    "hoan thanh", "da giao", "huy", "tra hang", "dang giao", "cod", "ghi no", "vi", "the",
}

_shop_ent_cache: dict[str, list[str]] = {}
_shop_rule_cache: dict[str, str] = {}
_shop_ent_lock = threading.Lock()
_FOREIGN_RE = re.compile(r"[\u0400-\u04FF\u4E00-\u9FFF]")
_PAREN_RE = re.compile(r"\(([^()]{2,80})\)")


def load_shop_rules(db_path: str) -> str:
    """Đọc toàn bộ _rulebook từ DuckDB của shop."""
    with _shop_ent_lock:
        if db_path in _shop_rule_cache:
            return _shop_rule_cache[db_path]
    if not db_path or not os.path.exists(db_path):
        return ""
    txt = ""
    try:
        con = duckdb.connect(db_path, read_only=True)
        rows = con.execute("SELECT text FROM _rulebook ORDER BY seq").fetchall()
        con.close()
        txt = "\n".join(r[0] or "" for r in rows)
    except Exception:
        pass
    with _shop_ent_lock:
        _shop_rule_cache[db_path] = txt
    return txt


def _strip_accents(s: str) -> str:
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.replace("đ", "d").replace("Đ", "D")


def load_shop_entities(db_path: str) -> list[str]:
    """Đọc toàn bộ danh mục tên mặt hàng, nhóm hàng, nhóm khách, hoạt chất, khách hàng, nhân viên, NCC từ DuckDB của shop."""
    with _shop_ent_lock:
        if db_path in _shop_ent_cache:
            return _shop_ent_cache[db_path]
    if not db_path or not os.path.exists(db_path):
        return []
    ents: set[str] = set()
    try:
        con = duckdb.connect(db_path, read_only=True)
        tables = con.execute("SELECT table_name, role FROM _meta_tables").fetchall()
        target_canons = {
            "product_name", "category", "active_ingredient", "brand",
            "customer_name", "customer_group", "supplier_name", "staff_name",
            "driver_name", "expense_category", "vehicle", "service_desc",
            "pet_name", "branch", "warehouse",
        }
        _plate_suffix_re = re.compile(r"\s+\d{2}[A-Za-z]\d[-.\s]\d+.*$")
        for t, _ in tables:
            cols = con.execute(
                "SELECT column_name, canonical FROM _meta_columns WHERE table_name = ?", [t]
            ).fetchall()
            for col, canon in cols:
                if canon in target_canons:
                    try:
                        vals = con.execute(
                            f'SELECT DISTINCT CAST("{col}" AS VARCHAR) FROM "{t}" WHERE "{col}" IS NOT NULL LIMIT 3000'
                        ).fetchall()
                        for (v,) in vals:
                            v = str(v).strip()
                            if len(v) >= 4 and fold(v) not in _GENERIC_ENT_STOP and not v.isdigit():
                                ents.add(v)
                            if canon == "vehicle":
                                prefix = _plate_suffix_re.sub("", v).strip()
                                if len(prefix) >= 4 and fold(prefix) not in _GENERIC_ENT_STOP:
                                    ents.add(prefix)
                    except Exception:
                        pass
        # Bổ sung _product_aliases nếu có
        try:
            for a, p in con.execute("SELECT alias, product_name FROM _product_aliases").fetchall():
                for v in (a, p):
                    if v and len(str(v).strip()) >= 4:
                        ents.add(str(v).strip())
        except Exception:
            pass
        con.close()
    except Exception:
        pass
    out = sorted(ents, key=len, reverse=True)
    with _shop_ent_lock:
        _shop_ent_cache[db_path] = out
    return out


def extract_and_mask(raw_q: str, shop_ents: list[str], known_ents: list[str] | None = None) -> tuple[str, dict[str, str]]:
    """Thay thế các thực thể trong câu hỏi bằng <ENT_0>, <ENT_1>... theo thứ tự độ dài giảm dần."""
    candidates: list[str] = []
    if known_ents:
        candidates.extend([e for e in known_ents if e and e in raw_q])
    else:
        # 1. Chuỗi trong ngoặc
        for m in _QUOTE_RE.finditer(raw_q):
            candidates.append(m.group(0))
        # 2. Thực thể từ DB của shop (so khớp cả có dấu và không dấu ở ranh giới từ)
        raw_low = raw_q.lower()
        raw_strip = _strip_accents(raw_low)
        for ent in shop_ents:
            ent_strip = _strip_accents(ent.lower())
            if len(ent_strip) < 4:
                continue
            idx = raw_strip.find(ent_strip)
            if idx != -1:
                end = idx + len(ent_strip)
                before_ok = (idx == 0 or not raw_strip[idx - 1].isalnum())
                after_ok = (end == len(raw_strip) or not raw_strip[end].isalnum())
                if before_ok and after_ok and len(raw_q[idx:end]) == len(ent):
                    candidates.append(raw_q[idx:end])
        # 3. Ngày tháng / Tháng năm
        for m in _DATE_RE.finditer(raw_q):
            # Không cắt nếu trước đó là chữ "quý" / "q"
            prefix = fold(raw_q[:m.start()])
            if not re.search(r"\b(?:quy|q)\s*$", prefix):
                candidates.append(m.group(0))
        # 4. Mã SKU / Mã NV / Mã KH
        for m in _SKU_RE.finditer(raw_q):
            candidates.append(m.group(0))
        # 5. Số tiền có dấu chấm
        for m in _MONEY_DOT_RE.finditer(raw_q):
            candidates.append(m.group(0))

    # Khử trùng lặp và sắp xếp theo độ dài giảm dần (đúng chuẩn full_gold_norm_chatml.jsonl)
    unique_ents = []
    seen = set()
    for c in sorted(candidates, key=len, reverse=True):
        if c and c not in seen:
            seen.add(c)
            unique_ents.append(c)

    masked = raw_q
    ent_map: dict[str, str] = {}
    ent_idx = 0
    for ent in unique_ents:
        if ent in masked:
            # Không thay thế vào bên trong thẻ <ENT_...> đã tạo
            parts = re.split(r"(<ENT_\d+>)", masked)
            replaced = False
            for k in range(0, len(parts), 2):
                if ent in parts[k]:
                    tag = f"<ENT_{ent_idx}>"
                    parts[k] = parts[k].replace(ent, tag)
                    ent_map[tag] = ent
                    replaced = True
            if replaced:
                masked = "".join(parts)
                ent_idx += 1
    return masked, ent_map


# Regex cắt cụm "là bao nhiêu " bị thừa trước "dưới dạng danh sách" ở các câu hỏi tên/liệt kê
_REDUNDANT_BAO_NHIEU_LIST = re.compile(
    r"((?:là\s+những\s+[^?]+|là\s+gì|là\s+ai|những\s+[^?]+\s+nào|liệt\s+kê\s+[^?]+?))\s+là\s+bao\s+nhiêu\s+(dưới\s+dạng\s+danh\s+sách)",
    re.IGNORECASE,
)
# Câu bắt đầu bằng "Cho tôi <N> mặt hàng/khách..." hoặc "Liệt kê <N>..." mà cuối câu gắn "là bao nhiêu dưới dạng danh sách"
_IMPERATIVE_LIST_BAO_NHIEU = re.compile(
    r"^((?:cho\s+tôi|cho\s+mình|giúp\s+mình\s+liệt\s+kê|liệt\s+kê)\s+\d+\s+(?:mặt\s+hàng|món|sản\s+phẩm|hàng|khách|khách\s+hàng)[^?]*?)\s+là\s+bao\s+nhiêu\s+(dưới\s+dạng\s+danh\s+sách)",
    re.IGNORECASE,
)


# Tiền viết tắt: "3tr1" -> "3,1 triệu", "3tr" -> "3 triệu", "54k" -> "54.000 đồng". Chạy trên câu ĐÃ che thực thể.
_PRE_MONEY_TR_DEC = re.compile(r"(?<![\d.,])(\d+)\s*tr(\d)(?!\d)\b", re.IGNORECASE)
_PRE_MONEY_TR = re.compile(r"(?<![\d.,])(\d+)\s*tr\b", re.IGNORECASE)
_PRE_MONEY_K = re.compile(r"(?<![\d.,])(\d+)\s*k\b", re.IGNORECASE)
_FAKE_TABLE_RE = re.compile(r"\s*,?\s*dưới\s+dạng\s+bảng\b", re.IGNORECASE)


def _pre_norm_money(text: str) -> str:
    t = _PRE_MONEY_TR_DEC.sub(r"\1,\2 triệu", text)
    t = _PRE_MONEY_TR.sub(r"\1 triệu", t)
    return _PRE_MONEY_K.sub(r"\1.000 đồng", t)


def _unmask(text: str, ent_map: dict[str, str]) -> str:
    for tag, orig in sorted(ent_map.items(), key=lambda x: len(x[0]), reverse=True):
        text = text.replace(tag, orig)
    return text


def postprocess_and_validate(raw_q: str, pred_masked: str, ent_map: dict[str, str]) -> tuple[str, bool]:
    """Kiểm tra Guardrail 3 lớp và Unmask trả về câu hỏi chuẩn hóa an toàn."""
    if not pred_masked or not pred_masked.strip():
        return raw_q, False

    pred = pred_masked.strip().strip('"').strip("'")
    if "Câu chuẩn hóa:" in pred:
        pred = pred.split("Câu chuẩn hóa:")[-1].strip()

    # Lớp 1: Kiểm tra bảo toàn 100% thẻ <ENT_k> và không lọt chữ ngoại ngữ
    if _FOREIGN_RE.search(pred):
        return raw_q, False
    expected_tags = set(ent_map.keys())
    found_tags = set(re.findall(r"<ENT_\d+>", pred))
    if expected_tags != found_tags:
        return raw_q, False

    # Chặn lỗi 4B tự thêm "Tháng " trước <ENT_k> khi <ENT_k> là tên người/thực thể không phải tháng/năm
    _month_ent_re = re.compile(r"^(?:0?[1-9]|1[0-2])[/-](?:20)?\d{2}$")
    m_thang = re.match(r"^(Tháng)\s+(<ENT_\d+>)(?!\w)", pred)
    if m_thang:
        tag = m_thang.group(2)
        orig_val = ent_map.get(tag, "")
        if not _month_ent_re.match(orig_val) and not re.search(rf"\b(?:tháng|th|t)\s*{re.escape(orig_val)}", raw_q, re.I):
            pred = pred[len(m_thang.group(1)):].lstrip()

    # Unmask
    unmasked = pred
    for tag, orig in sorted(ent_map.items(), key=lambda x: len(x[0]), reverse=True):
        unmasked = unmasked.replace(tag, orig)

    # Xóa ngoặc giải thích dài tự chèn (chỉ giữ (%) và các ngoặc vốn có trong raw_q)
    def _clean_paren(m: re.Match) -> str:
        inner = m.group(1).strip()
        if inner == "%" or m.group(0) in raw_q:
            return m.group(0)
        return ""

    unmasked = _PAREN_RE.sub(_clean_paren, unmasked)

    # Dọn khoảng trắng thừa quanh dấu gạch chéo tháng/năm nếu có
    unmasked = re.sub(r"\s+", " ", unmasked).strip()

    # Lớp 2: Bảo toàn tính chất câu hỏi Có/Không (Boolean), Quý (Q1..Q4) & hỏi số tiền
    if asks_yes_no(raw_q) and not asks_yes_no(unmasked):
        return raw_q, False
    m_quy = re.search(r"\bQ([1-4])\s*[/-]\s*(?:20)?\d{2}\b", raw_q, re.I)
    if m_quy and not re.search(rf"\b(?:qu[yý]\s*{m_quy.group(1)}|Q{m_quy.group(1)})\b", unmasked, re.I):
        return raw_q, False
    if re.search(r"(?:bao\s*nhi[eê]u|bn|nhi[eê]u)\s*ti[eề]n", raw_q, re.I):
        if re.search(r"\bbao\s+nhiêu\s+(?:khách|đơn|mặt\s+hàng|sản\s+phẩm|món|nhân\s+viên|thợ)\b", unmasked, re.I) and not re.search(r"tiền|doanh\s+thu|giá\s+trị|tổng\s+nợ|công\s+nợ", unmasked, re.I):
            return raw_q, False

    # Lớp 3: Dọn cụm "là bao nhiêu " bị thừa trước "dưới dạng danh sách" ở câu hỏi tên đối tượng
    unmasked = _REDUNDANT_BAO_NHIEU_LIST.sub(r"\1 \2", unmasked)
    unmasked = _IMPERATIVE_LIST_BAO_NHIEU.sub(r"\1 \2", unmasked)

    # Lớp 4: Dọn lỗi lặp từ, "nhiêu" đứng lẻ và thêm "Tháng " trước M/YY đầu câu
    unmasked = re.sub(r"\b([Gg]iá trị)\s+giá trị\b", r"\1", unmasked)
    unmasked = re.sub(r"\b(đơn hàng)\s+hàng\b", r"\1", unmasked, flags=re.I)
    unmasked = re.sub(r"\b([Dd]oanh thu)\s+doanh thu\b", r"\1", unmasked)
    unmasked = re.sub(r"\b([Tt]ổng)\s+tổng\b", r"\1", unmasked)
    unmasked = re.sub(r"\bbnhiu\b", "bao nhiêu", unmasked, flags=re.I)
    unmasked = re.sub(r"(?<!bao\s)(?<!bao)\bnhiêu\b", "bao nhiêu", unmasked, flags=re.I)
    unmasked = re.sub(r"^((?:0?[1-9]|1[0-2])[/-](?:25|26|2025|2026))\b", r"Tháng \1", unmasked)
    unmasked = re.sub(r"\b(trong|của|ở|vào|so sánh|xét)\s+((?:0?[1-9]|1[0-2])[/-](?:25|26|2025|2026))\b", r"\1 tháng \2", unmasked, flags=re.I)
    unmasked = re.sub(r"\s+", " ", unmasked).strip()

    # Lớp 4b: 4B tự thêm "dưới dạng bảng" khi câu gốc không nhắc bảng (§9: bảng chỉ khi câu đòi)
    if "bảng" not in raw_q.lower() and "bang" not in raw_q.lower():
        unmasked = _FAKE_TABLE_RE.sub("", unmasked)
        unmasked = re.sub(r"\s+([?!.])", r"\1", unmasked)

    # Lớp 4c: 4B làm rơi dấu phân cách của số ("3,1 triệu" -> "31 triệu"): quay về câu đầu vào
    raw_nums = re.findall(r"\d+(?:[.,]\d+)?", raw_q)
    pred_nums = re.findall(r"\d+(?:[.,]\d+)?", unmasked)
    if len(raw_nums) == len(pred_nums):
        for rn, pn in zip(raw_nums, pred_nums):
            if ("," in rn or "." in rn) and rn != pn and "," not in pn and "." not in pn \
                    and re.sub(r"[.,]", "", rn) == pn:
                return raw_q, False

    return unmasked, True


def call_norm_llm(url: str, key: str, model: str, masked_q: str, tries: int = 3) -> str:
    body = {
        "model": model,
        "temperature": 0.0,
        "max_tokens": 180,
        "messages": [
            {"role": "system", "content": NORM_SYSTEM_PROMPT},
            {"role": "user", "content": masked_q},
        ],
        "chat_template_kwargs": {"enable_thinking": False},
    }
    data = json.dumps(body).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {key}",
        "User-Agent": "Mozilla/5.0",
    }
    for k in range(tries):
        try:
            req = urllib.request.Request(f"{url.rstrip('/')}/v1/chat/completions", data=data, headers=headers)
            with urllib.request.urlopen(req, timeout=45) as r:
                resp = json.loads(r.read().decode("utf-8"))
                return resp["choices"][0]["message"]["content"].strip()
        except Exception as e:
            if k == tries - 1:
                raise RuntimeError(f"Lỗi gọi qwen_norm: {e}") from e
            time.sleep(1.5 * (k + 1))
    return masked_q


def normalize_records(
    records: list[dict],
    db_root: str,
    url: str,
    key: str,
    model: str,
    cache_path: str,
    known_entities_map: dict[str, list[str]] | None = None,
    workers: int = 24,
) -> list[dict]:
    """Chuẩn hóa danh sách bản ghi câu hỏi với bộ nhớ đệm persistent (chạy lại tốn 0s cho câu đã có)."""
    cache: dict[str, str] = {}
    if cache_path and os.path.exists(cache_path):
        with open(cache_path, encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    r = json.loads(line)
                    cache[r["k"]] = r["v"]

    cache_lock = threading.Lock()
    t0 = time.time()
    done_cnt = 0
    guardrail_revert_cnt = 0

    loi: list = []      # câu gọi 4B lỗi (giữ câu gốc)

    def process_one(rec: dict) -> dict:
        nonlocal done_cnt, guardrail_revert_cnt
        t_q0 = time.time()
        qid = rec.get("id", "")
        shop = rec.get("business_id") or rec.get("shop") or ""
        raw_q = rec.get("goc") or rec["question"]
        db_path = os.path.join(db_root, shop, f"{shop}.duckdb") if db_root and shop else ""
        shop_ents = load_shop_entities(db_path) if db_path else []
        shop_rules = load_shop_rules(db_path) if db_path else ""
        known_ents = known_entities_map.get(qid) if known_entities_map else None

        masked_q, ent_map = extract_and_mask(raw_q, shop_ents, known_ents)
        masked_q = _pre_norm_money(masked_q)        # sau khi che: tên hàng trong <ENT_x> không bị đổi
        prep_q = _unmask(masked_q, ent_map)         # câu đầu vào an toàn (dùng khi 4B hỏng / bị chặn)
        near = near_rules(shop_rules, raw_q, k=3) if shop_rules else []
        if near:
            user_content = "Luật liên quan:\n" + "\n".join(x.strip() for x in near if x.strip()) + f"\n\nCâu hỏi: {masked_q}"
        else:
            user_content = f"Câu hỏi: {masked_q}"
        ckey = f"v2||{model}||{user_content}"

        with cache_lock:
            pred_masked = cache.get(ckey)

        if pred_masked is None:
            try:
                pred_masked = call_norm_llm(url, key, model, user_content)
            except RuntimeError as e:       # 4B lỗi ở MỘT câu (quá giờ, quá dài): câu đó giữ câu gốc, các câu khác vẫn làm sạch
                print(f"  [Norm] câu {qid} gọi 4B lỗi, giữ câu gốc: {str(e)[:120]}", flush=True)
                loi.append(qid)
                return {**rec, "question": raw_q, "goc": raw_q}
            with cache_lock:
                cache[ckey] = pred_masked
                if cache_path:
                    with open(cache_path, "a", encoding="utf-8") as cf:
                        cf.write(json.dumps({"k": ckey, "v": pred_masked}, ensure_ascii=False) + "\n")

        norm_q, ok = postprocess_and_validate(prep_q, pred_masked, ent_map)
        with cache_lock:
            done_cnt += 1
            if not ok:
                guardrail_revert_cnt += 1
            if done_cnt % 100 == 0 or done_cnt == len(records):
                elapsed = time.time() - t0
                print(
                    f"  [Norm] {done_cnt}/{len(records)} câu ({elapsed:.1f}s, "
                    f"guardrail_fallback={guardrail_revert_cnt})",
                    flush=True,
                )

        out = dict(rec)
        out["goc"] = raw_q
        out["question"] = norm_q
        out["_norm_ms"] = max(0, int((time.time() - t_q0) * 1000))
        return out

    with ThreadPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(process_one, records))
    if len(loi) > 0.2 * len(records):   # 4B hỏng hẳn: báo lỗi để run.sh dùng câu gốc + kho ví dụ gốc + sửa Telex cho cả đề
        raise RuntimeError(f"{len(loi)}/{len(records)} câu gọi 4B lỗi")
    return results


def main():
    ap = argparse.ArgumentParser(description="Sinh bộ câu hỏi chuẩn hóa qua model qwen_norm")
    ap.add_argument("--input", required=True, help="File JSONL đầu vào (questions.jsonl hoặc examples_*.jsonl)")
    ap.add_argument("--output", required=True, help="File JSONL đầu ra đã normalize")
    ap.add_argument("--db-root", default="", help="Thư mục chứa các shop DuckDB (vd: work/db/<bộ đề>)")
    ap.add_argument("--url", default=os.environ.get("DATAMATE_NORM_URL", "http://127.0.0.1:8001"))
    ap.add_argument("--key", default=os.environ.get("DATAMATE_NORM_KEY", ""))
    ap.add_argument("--model", default=os.environ.get("DATAMATE_NORM_MODEL", "qwen_norm"))
    ap.add_argument("--cache", default="data/norm_cache_qwen_norm_4b_v2.jsonl", help="File lưu cache kết quả gọi qwen_norm")
    ap.add_argument("--workers", type=int, default=24)
    a = ap.parse_args()

    os.makedirs(os.path.dirname(os.path.abspath(a.output)), exist_ok=True)
    if a.cache:
        os.makedirs(os.path.dirname(os.path.abspath(a.cache)), exist_ok=True)

    known_entities_map: dict[str, list[str]] = {}

    with open(a.input, encoding="utf-8-sig") as f:
        records = [json.loads(line) for line in f if line.strip()]

    print(
        f">>> Bắt đầu Normalize {len(records)} câu từ {a.input} -> {a.output} "
        f"(workers={a.workers}, model={a.model})",
        flush=True,
    )
    norm_recs = normalize_records(
        records=records,
        db_root=a.db_root,
        url=a.url,
        key=a.key,
        model=a.model,
        cache_path=a.cache,
        known_entities_map=known_entities_map or None,
        workers=a.workers,
    )

    with open(a.output, "w", encoding="utf-8") as out_f:
        for r in norm_recs:
            out_f.write(json.dumps(r, ensure_ascii=False) + "\n")

    changed = sum(1 for r in norm_recs if r["question"] != r["goc"])
    print(
        f">>> HOÀN TẤT: {a.output} | Đã chuẩn hóa thay đổi: {changed}/{len(norm_recs)} câu ({changed*100.0/max(len(norm_recs),1):.1f}%)",
        flush=True,
    )


if __name__ == "__main__":
    main()
