"""Nhãn luật không nhận ra -> mã chung, bằng LLM (rulebook §8: 4 trạng thái đơn; §1, §3: thanh toán, khách lẻ).

Luật chạy trước (parsers.norm_status, build._PAYMENT_NORM, parsers.is_walk_in...). Phần còn lại gom theo
GIÁ TRỊ KHÁC NHAU kèm số dòng (cột 50 nghìn dòng thường chỉ vài nhãn), gửi LLM cùng định nghĩa mã.
LLM trả mã hoặc 'khong_ro'; code chỉ nhận mã hợp lệ. Không chắc thì để trống: lớp sau thấy là không rõ,
không âm thầm coi là hoàn thành / tiền mặt. ENABLED = False (mặc định): mọi hàm trả rỗng, như chỉ có luật.
"""
from __future__ import annotations

import json
import re

from . import llm
from .parsers import fold

ENABLED = False
UNKNOWN = "khong_ro"
MAX_VALUES = 60

_STATUS = {
    "hoan_thanh": "đơn đã xong: đã giao, khách đã nhận, đã thanh toán, đã chốt xong",
    "huy": "đơn không thành: huỷ, khách bom hàng, giao không được, khách không lấy",
    "tra_hang": "khách trả lại hàng sau khi mua (cả đơn hoặc một phần), hoàn hàng, đổi trả",
    "dang_giao": "đơn chưa xong: đang giao, đang vận chuyển, chờ giao, đã gửi đi mà khách chưa nhận",
}
CODESETS = {
    "status": _STATUS,
    # ghi chú tự do: chỉ xếp khi ghi chú nói rõ trạng thái cuối của đơn, còn lại là không nhắc
    "note_status": {**{k: v for k, v in _STATUS.items() if k != "hoan_thanh"},
                    "khong_nhac": "ghi chú không nói đơn bị huỷ, trả hàng hay đang giao (ghi chú việc khác)"},
    "payment": {
        "tien_mat": "tiền mặt",
        "chuyen_khoan": "chuyển khoản ngân hàng, quét mã QR ngân hàng",
        "the": "quẹt thẻ (ATM, Visa, Master, máy POS)",
        "vi": "ví điện tử (MoMo, ZaloPay, VNPay, ShopeePay...)",
        "cod": "giao hàng thu tiền (COD, thu hộ, ship thu tiền)",
        "ghi_no": "ghi nợ, mua chịu, trả sau",
    },
    "channel": {
        "tai_quay": "khách mua trực tiếp tại cửa hàng",
        "dien_thoai": "đặt qua gọi điện thoại, hotline",
        "zalo": "đặt qua Zalo",
        "facebook": "đặt qua Facebook, Messenger, fanpage",
        "shopee": "sàn Shopee",
        "lazada": "sàn Lazada",
        "tiktok": "TikTok Shop",
        "grab": "app giao đồ ăn (GrabFood, ShopeeFood, Baemin, Be...)",
        "website": "website, đặt online của shop",
    },
}

_SYSTEM = """Bạn xếp các nhãn ghi trong sổ bán hàng của cửa hàng nhỏ ở Việt Nam vào bộ mã cho trước.
Mỗi nhãn chọn đúng một mã theo NGHĨA của nhãn (nhãn có thể viết tắt, không dấu, tiếng Anh, văn nói).
Nhãn không thuộc mã nào, hoặc không chắc, ghi "khong_ro".
Chỉ trả về một JSON object: {"<nhãn y như đề>": "<mã>"}."""


def _ask(system: str, user: str, n: int) -> dict:
    text = llm.chat(system, user, max_tokens=60 + 25 * n)
    m = re.search(r"\{.*\}", text, re.S)
    try:
        out = json.loads(m.group(0)) if m else {}
    except json.JSONDecodeError:
        return {}
    return out if isinstance(out, dict) else {}


def _match_keys(out: dict, values: list[str]) -> dict:
    """Khoá LLM trả có thể lệch dấu / hoa thường so với nhãn gốc: khớp lại theo fold."""
    by_fold = {fold(v): v for v in values}
    res = {}
    for k, v in out.items():
        orig = k if k in values else by_fold.get(fold(str(k)))
        if orig is not None:
            res[orig] = v
    return res


def label_prompt(kind: str, counts: dict[str, int], column: str = "") -> tuple[str, str, list]:
    """(system, user, các nhãn đã gửi) — dùng chung cho pipeline và dữ liệu fine-tune (datamate/finetune)."""
    codes = CODESETS[kind]
    top = sorted(counts.items(), key=lambda x: -x[1])[:MAX_VALUES]
    user = "\n".join([f"Cột: {column}" if column else "Cột nhãn",
                      "Mã:", *[f"- {c}: {d}" for c, d in codes.items()],
                      "Nhãn (số dòng):", *[f'- "{v}" ({n})' for v, n in top]])
    return _SYSTEM, user, top


def classify(kind: str, counts: dict[str, int], column: str = "", total: int | None = None) -> dict[str, str]:
    """{nhãn: số dòng} (các nhãn luật không nhận ra) -> {nhãn: mã}. Chỉ giữ mã hợp lệ; không chắc thì bỏ."""
    if not ENABLED or not counts or not llm.available():
        return {}
    codes = CODESETS[kind]
    system, user, top = label_prompt(kind, counts, column)
    try:
        out = _match_keys(_ask(system, user, len(top)), [v for v, _ in top])
    except Exception:                 # mạng / server lỗi: giữ kết quả luật
        return {}
    res = {v: c for v, c in out.items() if c in codes}
    if kind == "status" and total:
        # nhãn chiếm quá nửa số dòng mà LLM xếp huỷ / trả / đang giao: không tin (shop bán được là chính)
        res = {v: c for v, c in res.items() if c == "hoan_thanh" or counts.get(v, 0) <= 0.5 * total}
    return res


_WALK_SYSTEM = """Các giá trị dưới đây xuất hiện nhiều nhất ở cột tên khách của sổ bán hàng một cửa hàng ở Việt Nam.
Giá trị nào là NHÃN chỉ khách lẻ / khách vãng lai / khách không xưng tên (không phải tên một người, một cơ quan,
một khách quen cụ thể)? Không chắc thì false.
Chỉ trả về một JSON object: {"<giá trị y như đề>": true hoặc false}."""


def walk_in_prompt(counts: dict[str, int], total: int, top_n: int = 12) -> tuple[str, str, list]:
    """(system, user, các tên đã gửi): các tên xuất hiện nhiều nhất (từ 2 dòng)."""
    top = [(v, n) for v, n in sorted(counts.items(), key=lambda x: -x[1])[:top_n] if n >= 2]
    user = "\n".join([f"Tổng số dòng: {total}", "Giá trị (số dòng):", *[f'- "{v}" ({n})' for v, n in top]])
    return _WALK_SYSTEM, user, top


def walk_in_markers(counts: dict[str, int], total: int, top_n: int = 12) -> set[str]:
    """Nhãn khách lẻ riêng của shop trong các tên xuất hiện nhiều nhất (luật parsers.is_walk_in chưa biết)."""
    if not ENABLED or not counts or not llm.available():
        return set()
    system, user, top = walk_in_prompt(counts, total, top_n)
    if not top:
        return set()
    try:
        out = _match_keys(_ask(system, user, len(top)), [v for v, _ in top])
    except Exception:
        return set()
    return {v for v, flag in out.items() if flag is True}
