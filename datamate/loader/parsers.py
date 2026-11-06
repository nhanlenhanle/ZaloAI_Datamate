"""Parse giá trị ô: số / tiền, ngày, trạng thái đơn, khách lẻ, tên kèm SĐT.

Mọi hàm nhận một ô thô (str / int / float / datetime / None) và trả None khi
không parse được, không đoán bừa. Các dạng dưới đây đều lấy từ data thật.

Số, tiền (khảo sát 44 shop: sau dấu , hoặc . luôn đúng 3 chữ số => phân cách nghìn;
dấu thập phân chỉ gặp cùng 'tr' hoặc đuôi '.0000'):
    "560,000"  "25.000đ"  "1.039.500đ"  "25,000.0000"  "129 000"  "-49.000đ"
    "25k"  "1168k"  "1tr440"  "15tr738"  "16,56tr"  "3,3225tr"  "1tr"  "3 chai"
Ngày:
    datetime/date của Excel, số serial Excel 45689.0, "01/02/2025",
    "2025-01-01 06:03:59", "1 thg 6 2025", "1/1" (không có năm -> lấy năm của sheet)
"""
from __future__ import annotations

import datetime as dt
import math
import re
import unicodedata

# ---------------------------------------------------------------- tiện ích chữ


def fold(s: str) -> str:
    """Chữ thường, bỏ dấu, đ -> d, gộp khoảng trắng: 'Đã Hủy  đơn' -> 'da huy don'."""
    s = unicodedata.normalize("NFD", str(s).lower()).replace("đ", "d")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s).strip()


# ---------------------------------------------------------------- số, tiền

_ERROR_CELLS = {"#value!", "#n/a", "#ref!", "#div/0!", "#name?", "#num!", "#null!", "-", "--", "—", "n/a"}
_SCALE = {"k": 1e3, "nghìn": 1e3, "ngàn": 1e3, "tr": 1e6, "triệu": 1e6, "tỷ": 1e9, "tỉ": 1e9}
_NUM_RE = re.compile(
    r"(?P<sign>[-+])?\s*"
    r"(?P<num>\d[\d.,\s]*?)\s*"
    r"(?:(?P<scale>k|nghìn|ngàn|tr|triệu|tỷ|tỉ)\s*(?P<tail>\d+)?)?\s*"
    r"(?P<cur>đ|vnđ|vnd|đồng)?"
    # đơn vị: từ đầu bắt đầu bằng chữ; các từ sau có thể có số ("bao 25kg", "hộp 30", "xe 4m3")
    r"(?:\s+(?P<unit>[^\W\d_][\w/]*(?:\s[\w/]+){0,2}))?",
    re.IGNORECASE,
)


def _to_number(x: float):
    """float nguyên -> int (tiền VND, số lượng); còn lại giữ float."""
    x = round(x, 6)
    return int(x) if float(x).is_integer() else x


def _plain_number(s: str, decimal_if_single_sep: bool) -> float | None:
    s = re.sub(r"\s+", "", s)
    seps = re.findall(r"[.,]", s)
    if not seps:
        return float(s)
    if "," in s and "." in s:
        # dạng "25,000.0000": dấu xuất hiện sau cùng là dấu thập phân
        dec = "." if s.rfind(".") > s.rfind(",") else ","
        thou = "," if dec == "." else "."
        return float(s.replace(thou, "").replace(dec, "."))
    sep = seps[0]
    parts = s.split(sep)
    if len(parts) == 2 and decimal_if_single_sep:
        return float(parts[0] + "." + parts[1])
    if all(len(p) == 3 for p in parts[1:]) and parts[0]:
        return float("".join(parts))          # phân cách nghìn
    if len(parts) == 2:
        return float(parts[0] + "." + parts[1])  # "1,5", "0.0000"
    return None                                 # "1.2.3" lộn xộn: không đoán


def parse_number_unit(v) -> tuple[float | int | None, str | None]:
    """Trả (giá trị, chữ đơn vị đi kèm nếu có). Vd "3 chai" -> (3, "chai")."""
    if v is None or isinstance(v, bool):
        return None, None
    if isinstance(v, (int, float)):
        return (None, None) if isinstance(v, float) and math.isnan(v) else (_to_number(float(v)), None)
    if isinstance(v, (dt.date, dt.datetime)):
        return None, None
    s = str(v).strip()
    if s.lower() in _ERROR_CELLS or not s:
        return None, None
    # ký hiệu tiền: "45,000₫", "VND 45,000"
    s = re.sub(r"^(?:vnd|vnđ)\s*", "", s.replace("₫", "đ"), flags=re.I)
    neg = False
    if s.startswith("(") and s.endswith(")"):    # kế toán: (1,000) là số âm
        neg, s = True, s[1:-1].strip()
    if s.endswith("%"):
        # "10%", "-5 %": giữ con số phần trăm, đơn vị "%" (build đánh dấu ô nào là phần trăm)
        val, unit = parse_number_unit(s[:-1].strip())
        if val is None or unit:
            return None, None
        return (-val if neg else val), "%"
    m = _NUM_RE.fullmatch(s)
    # đơn vị luôn viết thường ("chai", "bao 25kg"); "452 Tân Kỳ Tân Quý" là địa chỉ, không phải số
    if not m or (m["unit"] and not m["unit"][0].islower()):
        return None, None
    scale = (m["scale"] or "").lower()
    if scale and m["tail"]:
        # "1tr440" = 1,440 triệu; "15tr738" = 15,738 triệu
        base = float(re.sub(r"[.,\s]", "", m["num"]) + "." + m["tail"])
    else:
        base = _plain_number(m["num"], decimal_if_single_sep=scale in ("tr", "triệu", "tỷ", "tỉ"))
        if base is None:
            return None, None
    val = base * _SCALE.get(scale, 1)
    if m["sign"] == "-" or neg:
        val = -val
    return _to_number(val), m["unit"]


def parse_number(v):
    return parse_number_unit(v)[0]


def looks_like_code(v) -> bool:
    """Chuỗi toàn số nhưng là mã: SĐT/MST có số 0 đầu, barcode, IMEI, CCCD (>= 12 số)."""
    if not isinstance(v, str):
        return False
    s = v.replace(" ", "")
    return s.isdigit() and ((len(s) > 1 and s[0] == "0") or len(s) >= 12)


# ---------------------------------------------------------------- ngày

_EXCEL_EPOCH = dt.datetime(1899, 12, 30)
_TIME = r"(?:[ T,]+(\d{1,2}):(\d{2})(?::(\d{2}))?)?"
_D_ISO = re.compile(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})" + _TIME)    # năm trước: 2025-03-05, 2025/03/05
_D_DMY = re.compile(r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4}|\d{2})" + _TIME)
_D_THG = re.compile(r"(\d{1,2})\s*(?:thg|tháng)\s*(\d{1,2})\s*,?\s*(?:năm\s*)?(\d{4})" + _TIME, re.I)
_D_NGAY = re.compile(r"ngày\s*(\d{1,2})\s*tháng\s*(\d{1,2})\s*(?:năm\s*)?(\d{4})" + _TIME, re.I)
_D_NOYEAR = re.compile(r"(\d{1,2})/(\d{1,2})")
YEAR_RE = re.compile(r"(?<!\d)(20\d{2})(?!\d)")


def _mk(y, mo, d, hh=None, mi=None, ss=None) -> dt.datetime | None:
    try:
        y = int(y)
        y = y + 2000 if y < 100 else y
        return dt.datetime(y, int(mo), int(d), int(hh or 0), int(mi or 0), int(ss or 0))
    except (ValueError, TypeError):
        return None


def excel_serial(x: float) -> dt.datetime | None:
    """Số serial Excel (45689 = 2025-02-01). Chỉ nhận khoảng 1954..2119 cho an toàn."""
    if 20000 <= x <= 80000:
        # tròn tới giây: phần lẻ lưu 6 chữ số ra 19:25:59.98 thay vì 19:26 (câu theo khung giờ xếp nhầm giờ trước)
        return _EXCEL_EPOCH + dt.timedelta(seconds=round(float(x) * 86400))
    return None


def parse_date(v, default_year: int | None = None, allow_serial: bool = False,
               month_first: bool = False) -> dt.datetime | None:
    """Ô -> datetime (giờ = 0 nếu không có giờ). Mặc định ngày trước tháng (dd/mm)."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, dt.datetime):
        return v
    if isinstance(v, dt.date):
        return dt.datetime(v.year, v.month, v.day)
    if isinstance(v, (int, float)):
        return excel_serial(v) if allow_serial and not math.isnan(v) else None
    s = str(v).strip()
    if m := _D_ISO.fullmatch(s):
        return _mk(m[1], m[2], m[3], m[4], m[5], m[6])
    if m := _D_DMY.fullmatch(s):
        d, mo = (m[2], m[1]) if month_first else (m[1], m[2])
        # cột trộn hai kiểu: đọc theo kiểu của cột ra ngày không hợp lệ ("12/31/2025") thì đọc đảo lại
        return _mk(m[3], mo, d, m[4], m[5], m[6]) or _mk(m[3], d, mo, m[4], m[5], m[6])
    if m := (_D_THG.fullmatch(s) or _D_NGAY.fullmatch(s)):
        return _mk(m[3], m[2], m[1], m[4], m[5], m[6])
    if default_year and (m := _D_NOYEAR.fullmatch(s)):
        d, mo = (m[2], m[1]) if month_first else (m[1], m[2])
        return _mk(default_year, mo, d) or _mk(default_year, d, mo)
    if allow_serial and re.fullmatch(r"\d{5}(\.\d+)?", s):     # phần lẻ = giờ trong ngày ("45916.809722")
        return excel_serial(float(s))
    return None


def year_from_text(*texts) -> int | None:
    """Năm trong tên sheet / tên file: 'Tháng 01-2025' -> 2025."""
    for t in texts:
        if t and (m := YEAR_RE.search(str(t))):
            return int(m[1])
    return None


# ---------------------------------------------------------------- trạng thái đơn

# Mã ASCII để SQL không vướng "huỷ" / "hủy" (hai cách bỏ dấu khác nhau).
STATUS_DONE, STATUS_CANCEL, STATUS_RETURN, STATUS_SHIPPING = "hoan_thanh", "huy", "tra_hang", "dang_giao"


def norm_status(v) -> str | None:
    """Trạng thái đơn -> 1 trong 4 mã của rulebook §8, None nếu không nhận ra.

    Nhóm đang giao và 'Không giao được' suy ra từ phân bố trong data train
    (mỗi shop: nhóm lớn = hoàn thành, ~1-3% = huỷ, nhỏ = trả, vài chục = đang giao).
    """
    if v is None:
        return None
    f = fold(v)
    # huỷ: kể cả giao thất bại / bom hàng ("không giao được" là huỷ dù có chữ "không")
    if re.search(r"\bhuy\b|khong giao duoc|giao (that bai|khong thanh cong)|^that bai$|\bbom\b|cancel|fail", f) \
            and not re.search(r"\b(khong|chua) huy\b", f):
        return STATUS_CANCEL
    # trả HÀNG. Chữ "trả" đứng một mình không đủ: trả tiền, trả góp, trả trước, trả sau là chuyện thanh toán
    if re.search(r"tra (lai )?hang|hang tra (lai|ve)|\btra lai\b|\btra ve\b|mang (ve )?tra|khach tra\s*$|doi tra|"
                 r"hoan (hang|tra|tien)|return|refund", f) \
            and not re.search(r"tra (tien|gop|truoc|sau|no|du|het|coc)", f):
        return STATUS_RETURN
    neg = re.search(r"\b(khong|chua)\b", f)
    if re.search(r"\bdang\b|cho (giao|lay|xac nhan|xu ly)|chua giao|shipping|ship|van chuyen|delivering|pending|"
                 r"processing", f):
        return STATUS_SHIPPING
    # phủ định ("chưa hoàn thành", "không thành công"): không kết luận hoàn thành, để lớp sau (LLM) quyết
    if not neg and re.search(r"hoan thanh|\bxong\b|da lay|thanh cong|^ok$|complete|da giao|done|success|"
                             r"delivered", f):
        return STATUS_DONE
    return None


# ---------------------------------------------------------------- khách

_WALK_IN = {"khach le", "kl", "le", "khach vang lai", "vang lai", "khach", "walk-in", "walk in", "guest", "k/l"}


_WALK_IN_PREFIX = re.compile(r"^(khach le|khach vang lai|vang lai|kl|k/l|walk[- ]?in|guest)(?![a-z])")


def is_walk_in(v) -> bool:
    """Ô tên khách ghi rõ là khách lẻ, kể cả có đuôi: 'Khách lẻ - 0901...', 'Khách lẻ 1', 'Khách vãng lai (A Tú)'.
    Ô trống KHÔNG tính ở đây (có thể là ô gộp nhóm dòng)."""
    if v is None:
        return False
    f = fold(v).strip(" .")
    if f == "le":       # bỏ dấu thì "Lê" (họ) cũng là "le": so có dấu
        return str(v).strip(" .").lower() == "lẻ"
    return f in _WALK_IN or bool(_WALK_IN_PREFIX.match(f))


_PHONE_RE = re.compile(r"[\s\-–(]*\(?((?:\+?84|0)(?:[\s.]?\d){8,10})\)?\s*$")


def split_name_phone(v) -> tuple[str | None, str | None]:
    """'Đào Dương Giang - 0912 365 003' -> ('Đào Dương Giang', '0912365003')."""
    if v is None:
        return None, None
    s = str(v).strip()
    m = _PHONE_RE.search(s)
    if not m or m.start() == 0:
        return s, None
    phone = re.sub(r"\D", "", m[1])
    if phone.startswith("84"):
        phone = "0" + phone[2:]
    return s[:m.start()].strip(" -–,"), phone


# ---------------------------------------------------------------- bool

_TRUE = {"true", "1", "co", "x", "yes", "dung", "v"}
_FALSE = {"false", "0", "khong", "no", "sai"}


def parse_bool(v) -> bool | None:
    if isinstance(v, bool):
        return v
    if v is None:
        return None
    f = fold(v)
    if f in ("1.0",):
        return True
    if f in ("0.0",):
        return False
    return True if f in _TRUE else False if f in _FALSE else None


# ---------------------------------------------------------------- áp dụng cho cả cột

def split_name(col) -> str:
    """Tên cột thành các từ, giữ dấu: 'TênSảnPhẩm' / 'ten_san_pham' -> 'tên sản phẩm' / 'ten san pham'."""
    s = str(col).replace("_", " ")
    # tách CamelCase: chèn cách trước chữ HOA đứng sau chữ thường / số (isupper đúng cả với chữ có dấu)
    out = [c if not (i and c.isupper() and (s[i - 1].islower() or s[i - 1].isdigit())) else " " + c
           for i, c in enumerate(s)]
    return re.sub(r"\s+", " ", "".join(out).lower()).strip()


_DATE_HINT = re.compile(r"ngay|thoi gian|thoi diem|date|time|\bhan\b|hsd|han dung|han su dung|sinh nhat|\bgio\b|ngay lap")
_DMY_PARTS = re.compile(r"(\d{1,2})[/.\-](\d{1,2})(?:[/.\-]\d{2,4})?")


def _month_first(values) -> bool:
    """Cột ngày ghi tháng trước (mm/dd)? Chỉ True khi có bằng chứng: phần đầu <= 12 và phần sau > 12."""
    first_big = second_big = False
    for v in values:
        if isinstance(v, str) and (m := _DMY_PARTS.match(v)) and not _D_ISO.match(v):
            first_big |= int(m[1]) > 12
            second_big |= int(m[2]) > 12
    return second_big and not first_big


def _as_text(v):
    if v is None or isinstance(v, str):
        return v
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, float):
        return str(int(v)) if v.is_integer() else repr(v)
    if isinstance(v, dt.datetime):
        return v.isoformat(sep=" ")
    if isinstance(v, dt.date):
        return v.isoformat()
    return str(v)


def parse_column(name: str, values: list, years: list[int | None] | None = None) -> dict:
    """Suy kiểu và parse một cột.

    Trả dict: kind ('number' | 'datetime' | 'bool' | 'text' | 'empty'), values (đã parse),
    n (số ô có giá trị), n_fail, fail_examples, units (chữ đơn vị gặp trong ô số),
    month_first, had_text (cột gốc có ô dạng chuỗi -> nên giữ bản _raw).
    """
    present = [v for v in values if v is not None]
    out = {"kind": "empty", "values": values, "n": len(present), "n_fail": 0,
           "fail_examples": [], "units": {}, "month_first": False,
           "had_text": any(isinstance(v, str) for v in present)}
    if not present:
        return out
    years = years or [None] * len(values)

    def finish(kind, parsed):
        fails = [v for v, p in zip(values, parsed) if v is not None and p is None]
        out.update(kind=kind, values=parsed, n_fail=len(fails),
                   fail_examples=list(dict.fromkeys(map(str, fails)))[:5])
        return out

    # bool: toàn True/False
    if all(isinstance(v, bool) or (isinstance(v, str) and fold(v) in ("true", "false")) for v in present):
        return finish("bool", [parse_bool(v) for v in values])

    # ngày: chuỗi dạng ngày / datetime; số serial chỉ nhận khi tên cột gợi ý ngày
    hint = bool(_DATE_HINT.search(fold(split_name(name))))
    mf = _month_first(present)
    dates = [parse_date(v, y, allow_serial=hint, month_first=mf) for v, y in zip(values, years)]
    ok = sum(d is not None for d in dates)
    non_numeric = any(not isinstance(v, (int, float)) for v in present)
    if ok >= 0.9 * len(present) and (hint or non_numeric):
        out["month_first"] = mf
        return finish("datetime", dates)

    # số: không nhận cột có mã dạng số (SĐT 0..., barcode, IMEI)
    if not any(looks_like_code(v) for v in present):
        pairs = [parse_number_unit(v) for v in values]
        ok = sum(p[0] is not None for p, v in zip(pairs, values) if v is not None)
        units = {}
        for _, unit in pairs:
            if unit:
                units[unit] = units.get(unit, 0) + 1
        # quá nhiều "đơn vị" khác nhau => chữ đi sau số là nội dung (địa chỉ, tên), không phải đơn vị
        if ok >= 0.95 * len(present) and len(units) <= 30:
            out["units"] = units
            return finish("number", [p[0] for p in pairs])

    out.update(kind="text", values=[_as_text(v) for v in values])
    return out
