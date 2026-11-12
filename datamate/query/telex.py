"""Sửa lỗi gõ Telex trong câu hỏi ("thangs" -> "tháng", "naof" -> "nào", "ddown" -> "đơn").

Chỉ nhận khi kết quả là một âm tiết tiếng Việt có thật (am_tiet_viet.txt, rút từ danh sách từ công khai Viet74K),
nên tên riêng, mã hàng, từ tiếng Anh không bị đổi. Tiếng Việt không dấu không có âm tiết tận cùng bằng s/f/r/x/j,
nên câu gõ không dấu bình thường giữ nguyên. Cách làm theo bộ giải Telex của kietda / phongnh (cùng đội).
Tắt: DATAMATE_TELEX=0.
"""
from __future__ import annotations

import os
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

ON = os.environ.get("DATAMATE_TELEX", "1") != "0"

_DAU = {"s": "́", "f": "̀", "r": "̉", "x": "̃", "j": "̣"}   # sắc huyền hỏi ngã nặng
_NGUYEN_AM = set("aăâeêioôơuưy")
_TIENG_ANH = {"bus", "gas", "plus", "yes", "kids", "ads", "items", "orders", "sales", "bills", "ships", "sells", "products",
              "shops", "has", "was", "is", "its", "this", "us", "tips", "tax", "max", "box", "mix", "fix", "six",
              "sex", "fax", "lux", "pax", "vs", "pcs", "kgs", "ms", "mr", "dr", "jr", "sr"}
# có trong danh sách Viet74K (từ vay mượn) nhưng khi chủ shop nhắn tin gần như luôn là lỗi gõ
_LUON_GIAI = {"cos": "có", "as": "á"}
_BIEN = [("uwow", "ươ"), ("uow", "ươ"), ("uwo", "ươ"), ("aa", "â"), ("aw", "ă"), ("ee", "ê"), ("oo", "ô"),
         ("ow", "ơ"), ("uw", "ư"), ("dd", "đ")]


@lru_cache(maxsize=1)
def _am_tiet() -> frozenset:
    with open(Path(__file__).with_name("am_tiet_viet.txt"), encoding="utf-8") as fh:
        return frozenset(x.strip() for x in fh if x.strip() and not x.startswith("#"))


def _them_dau(goc: str, dau: str) -> str | None:
    at = _am_tiet()
    if not dau:
        return goc if goc in at else None
    # nguyên âm có mũ / móc trước, rồi từ phải sang trái ("quys" -> "quý")
    for i in sorted((i for i, ch in enumerate(goc) if ch in _NGUYEN_AM), key=lambda i: (goc[i] not in "ăâêôơư", -i)):
        ung = unicodedata.normalize("NFC", goc[:i + 1] + _DAU[dau] + goc[i + 1:])
        if ung in at:
            return ung
    return None


def giai_telex(tu: str) -> str:
    w = tu.lower()
    if w in _LUON_GIAI and not tu.isupper():
        kq = _LUON_GIAI[w]
        return kq.capitalize() if tu[0].isupper() else kq
    if len(w) < 2 or not w.isascii() or not w.isalpha() or w in _TIENG_ANH or w in _am_tiet():
        return tu
    if tu.isupper():                       # viết hoa cả từ: viết tắt / mã ("AA", "COD")
        return tu
    dau = w[-1] if w[-1] in _DAU else ""
    goc = w[:-1] if dau else w
    bien = any(a in goc for a, _ in _BIEN)
    if not dau and not bien:
        return tu
    if tu[0].isupper() and not bien:       # tên riêng / tiếng Anh viết hoa đầu: cần dấu hiệu Telex rõ
        return tu
    if not dau and len(w) <= 2:            # "ee", "aa" đứng riêng: không đủ chắc
        return tu
    for a, b in _BIEN:
        goc = goc.replace(a, b)
    kq = _them_dau(goc, dau)
    if kq is None:
        return tu
    return kq.capitalize() if tu[0].isupper() else kq


def sua_cau(cau: str) -> str:
    if not ON:
        return cau
    t = unicodedata.normalize("NFC", str(cau))
    return re.sub(r"[A-Za-z]+", lambda m: giai_telex(m[0]), t)


def sua_q(q: dict) -> dict:
    """Câu hỏi đã sửa Telex (giữ câu gốc ở 'goc_telex' khi có đổi)."""
    t = sua_cau(q["question"])
    return q if t == q["question"] else {**q, "question": t, "goc_telex": q["question"]}
