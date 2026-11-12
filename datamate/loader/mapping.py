"""Map cột gốc -> tên chuẩn (xem schema.md).

Thứ tự nguồn bằng chứng (tin cậy giảm dần):
  1. readme_col   : mô tả ở mục "Cột trong `file`" của README shop này
  2. readme_hint  : câu "**Cột** là <ý nghĩa>" ở mục Quy ước
  3. name_dict    : tên cột (bỏ dấu) từng được README của shop khác mô tả rõ
  4. value_pattern: giá trị trông như mã (ORD..., SP..., KH..., PN..., PAY..., NCC...)
  5. value_rule   : cột còn trống mà giá trị cho biết vai trò: toàn trạng thái đơn, có "Khách lẻ",
                    toàn đơn vị tính, = SL x đơn giá trên từng dòng, trùng tên hàng ở bảng khác
  6. llm          : cột luật để trống (map_shop(use_llm=True), hàm `llm_map`)
Mỗi kết quả đều được kiểm lại bằng kiểu giá trị (cột tiền phải là số, cột ngày phải là ngày).
Không chắc thì GIỮ TÊN GỐC: tên sai còn tệ hơn tên lạ.
"""
from __future__ import annotations

import json
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass

from .parsers import fold, parse_number, split_name

# (regex trên mô tả đã bỏ dấu, tên chuẩn). Cụ thể đứng trước, chung đứng sau.
DESC_RULES: list[tuple[str, str | None]] = [
    (r"cot trong, khong co du lieu", None),
    # cụm cụ thể đổi nghĩa chữ chung phía sau ("mã đơn NHẬP", "số lượng KHÁCH", "ngày nhập DỮ LIỆU"):
    # phải đứng trước luật chung, cùng loại lỗi với "tổng tiền cả phiếu" != tiền phiếu nhập
    (r"^ma (don|phieu) nhap", "purchase_id"),
    (r"^ma (don|phieu) tra", "return_id"),
    (r"tong tien (cua )?(ca )?(don|phieu) nhap", "purchase_total"),
    (r"trang thai (cua )?(don|phieu) nhap", "purchase_status"),
    (r"^so luong khach\b(?! (tra|mua|dat))", "guests"),      # không phải "số lượng khách trả lại / mua"
    (r"^so luong (ton|con lai)", "stock_qty"),
    (r"^so luong (khach )?tra lai\b(?!.*co ban)", "qty_returned"),
    (r"thanh tien (cua )?ca (don|hoa don|phieu)", "money"),
    (r"^ngay nhap (du lieu|vao (phan mem|he thong|may))", "created_date"),
    (r"^ngay (khach )?tra hang|^ngay tra\b", "return_date"),
    # dịch vụ (sửa chữa, làm đẹp...): mỗi dòng sổ là một phiếu; người làm, hoa hồng, xe / biển số
    (r"^ngay (sua|lam|thuc hien|lam dich vu|nhan xe)\b", "order_date"),
    (r"^ho ten (tho|nhan vien)|^(tho|nhan vien) (lam|ban|phu trach|thuc hien)|^tho\b", "staff_name"),
    (r"hoa hong", "commission_pct"),
    (r"^ngay vao lam", "start_date"),
    (r"^dong xe va bien so|^xe va bien so", "vehicle"),
    (r"^(cac )?viec (da )?lam|^noi dung (sua|cong viec|dich vu)|^cong viec\b", "service_desc"),
    # mã
    (r"^ma don|^so hoa don|so thu tu don\b", "order_id"),   # \b: không khớp "số thứ tự dòng"
    (r"so thu tu dong", "line_no"),
    (r"^ma phieu nhap|^ma don nhap", "purchase_id"),
    (r"^ma phieu thu", "payment_id"),
    (r"^ma hang|^ma san pham|^ma sku", "product_id"),
    (r"^ma khach", "customer_id"),
    (r"^ma nha cung cap|^ma ncc", "supplier_id"),
    (r"^ma nhan vien", "staff_id"),
    (r"^ma ca", "shift_id"),
    (r"^ma khuyen mai", "promo_id"),
    (r"^so lo|^ma lo", "batch_id"),
    (r"^imei", "imei"),
    # tên
    (r"^ten hang|^hang ban|^ten san pham", "product_name"),
    (r"^ten khach", "customer_name"),
    (r"^nha cung cap$|^ten nha cung cap", "supplier_name"),
    (r"^ten$", "name"),
    (r"^nhom hang", "category"),
    (r"^nhom khach", "customer_group"),
    # đơn vị, quy đổi
    (r"^don vi tinh", "unit"),
    (r"^don vi co ban", "base_unit"),
    (r"^don vi lon", "big_unit"),
    (r"^don vi nhap", "unit"),
    (r"^he so|quy doi don vi lon", "conv_factor"),
    # số lượng
    (r"so luong khach tra lai", "qty_returned_base"),
    (r"so luong ban lay tu lo", "qty_base"),
    (r"so luong (da doi ra |nhap \()don vi co ban|so luong .*\(don vi co ban\)", "qty_base"),
    (r"^ton kho|^ton cuoi", "stock_qty"),
    (r"^ton sau lan", "stock_after"),
    (r"^so luong", "qty"),
    # tiền đơn đứng trước tiền dòng: "tổng tiền hàng của đơn (cộng thành tiền các dòng)" có chữ "thành tiền"
    (r"tong tien hang|tien hang cua don", "order_subtotal"),
    # tiền dòng
    (r"^don gia|gia nhap mot don vi", "unit_price"),
    (r"thanh tien|tien nhap cua ca dong|^tien ban", "line_amount"),
    (r"tien giam cua ca dong", "line_discount"),
    (r"^gia von", "unit_cost"),
    (r"gia ban hien tai", "price"),
    (r"gia ban ap dung tu ngay", "new_price"),
    (r"gia truoc lan doi", "old_price"),
    # tiền đơn
    (r"giam gia cua ca don|tien bot cho ca don", "order_discount"),
    (r"^giam gia$", "discount"),
    (r"tong tien (cua ca )?phieu nhap", "purchase_total"),
    # "phiếu" không nói rõ (phiếu bán, phiếu sửa, phiếu thu...): tiền chung, ngữ cảnh bảng quyết
    (r"tong tien (cua )?(ca )?phieu", "money"),
    (r"tong tien don|phai tra cho ca don|can tra cho ca don", "order_total"),
    (r"phi giao", "shipping_fee"),
    (r"^da thanh toan|khach da tra cho ca don|so tien khach tra cho ca don", "paid"),
    (r"con no", "debt"),
    (r"so tien tra lan do|^so tien$", "payment_amount"),
    # ngày giờ
    (r"^ngay ban", "order_date"),
    # rulebook §2: ca sáng / chiều theo giờ tạo đơn
    (r"thoi diem (dat|tao) don|gio (dat|tao) don", "order_time"),
    (r"^ngay tao", "created_date"),
    (r"^ngay nhap", "purchase_date"),
    (r"thoi diem thu", "payment_date"),
    (r"han su dung", "expiry_date"),
    (r"^ngay giao", "delivery_date"),
    (r"han thanh toan", "due_date"),
    (r"ngay bat dau ap dung gia", "price_from"),
    # trạng thái, phân loại
    (r"^trang thai don", "status"),
    (r"trang thai phieu nhap", "purchase_status"),
    (r"hinh thuc thanh toan", "payment_method"),
    (r"kenh ban", "channel"),
    (r"hoat chat", "active_ingredient"),
    (r"thuoc ke don", "is_prescription"),
    (r"con kinh doanh", "active"),
    # giao hàng, công nợ
    (r"dot giao", "delivery_round"),
    (r"tai xe", "driver"),
    (r"bien so xe", "plate"),
    (r"so ngay duoc no", "credit_days"),
    # nhà hàng
    (r"^ban$", "table_no"),
    (r"khu vuc cua ban", "area"),
    (r"so khach cua don", "guests"),
    # liên hệ, ghi chú
    (r"so dien thoai", "phone"),
    (r"^dia chi", "address"),
    (r"^ghi chu cua don", "order_note"),
    (r"^ghi chu", "note"),
]
_DESC_RULES = [(re.compile(p), c) for p, c in DESC_RULES]

NUMBER = {"qty", "qty_base", "qty_returned_base", "stock_qty", "unit_price", "line_amount", "line_discount",
          "unit_cost", "price", "new_price", "old_price", "order_subtotal", "order_discount", "discount",
          "purchase_total", "order_total", "shipping_fee", "paid", "debt", "payment_amount",
          "conv_factor", "delivery_round", "credit_days", "guests", "stock_after", "money", "qty_returned",
          "commission_pct", "expense_amount"}
DATE = {"order_date", "order_time", "created_date", "purchase_date", "payment_date", "expiry_date", "delivery_date",
        "due_date", "price_from", "return_date", "start_date", "expense_date"}
# mã thường dạng chuỗi; nhưng sqlite/Excel có thể lưu mã số -> chỉ cấm kiểu ngày
CODE_PREFIX = {"ORD": "order_id", "SP": "product_id", "KH": "customer_id", "PN": "purchase_id",
               "PAY": "payment_id", "NCC": "supplier_id", "NV": "staff_id"}

# Tên cột phổ thông của phần mềm bán hàng / sổ tay (khoá name_key), dùng khi từ điển từ README
# không có tên đó. Chỉ ghi tên đủ rõ nghĩa ở mọi bảng; tên mơ hồ để luật ngữ cảnh / LLM.
BUILTIN_NAMES = {
    "sl co ban": "qty_base", "sl (dv co ban)": "qty_base", "sl (dvt co ban)": "qty_base",
    "sl quy ra le": "qty_base", "sl nhap (dvt co ban)": "qty_base", "slnhap quy doi": "qty_base",
    "sl tra (dvt co ban)": "qty_returned_base", "sltra quy doi": "qty_returned_base",
    "he so quy doi": "conv_factor", "bang": "conv_factor",
    "hsd": "expiry_date", "han dung": "expiry_date",
    "con no": "debt", "cong no": "debt",
    "tien hang truoc giam": "order_subtotal",
    "gio tao don": "order_time", "ngay hd": "order_date",
    "ngay tt": "payment_date", "ngay gio thu": "payment_date", "ngay nhap kho": "purchase_date",
    "ke don": "is_prescription", "thuoc ke don": "is_prescription", "ban theo don": "is_prescription",
    "thanh phan chinh": "active_ingredient", "hoat chat": "active_ingredient", "hoat chat chinh": "active_ingredient",
    "ngay chi": "expense_date", "khoan chi": "expense_item", "muc chi": "expense_item", "tien chi": "expense_amount",
    "so tien chi": "expense_amount",
    "dong": "line_no",
    "so lo": "batch_id", "ma lo": "batch_id", "lo": "batch_id", "lo hang": "batch_id",
    # tên chung: là tên hàng / khách / NCC / nhân viên tuỳ mã của bảng (_resolve_context)
    "ten": "name", "ten goi": "name", "ho ten": "name", "ho va ten": "name",
    "gia von": "unit_cost", "gia von hang": "unit_cost", "gia von hien tai": "unit_cost",
    "so tien": "money",          # tiền chung: _resolve_context xếp thành tiền thu / tiền chi / thành tiền theo bảng
    "con kinh doanh": "active",
}
# NV4: tên cột phổ thông, tắt mặc định (bật DATAMATE_NV4=1)
_NV4_NAMES = {
    "dv co ban": "base_unit", "dvt co ban": "base_unit", "don vi co ban": "base_unit",
    "tong don": "order_total", "tong phai tra": "order_total",
    "ma hv": "customer_id", "ma hoi vien": "customer_id",
    "thanh toan": "payment_method", "hinh thuc thanh toan": "payment_method", "httt": "payment_method", "hinh thuc tt": "payment_method",
}
if os.environ.get("DATAMATE_NV4"):   # NV4 tắt mặc định (FX3d: đổi prompt LLM, biz_203 / 201 mất câu)
    BUILTIN_NAMES.update(_NV4_NAMES)

# chữ chỉ đối tượng trong tên cột "Tên ..." (khách xét trước: "khách hàng" có chữ "hàng")
_ENTITY_WORDS = [(re.compile(r"\bkhach\b|\bkh\b|customer"), "customer_name"),
                 (re.compile(r"nha cung cap|\bncc\b|supplier"), "supplier_name"),
                 (re.compile(r"\bhang\b|san pham|\bsp\b|\bmon\b|\bthuoc\b|product|item"), "product_name")]
_LINE_QTY = {"qty", "unit_price", "line_amount"}
_EXPENSE_TABLE = re.compile(r"\bchi ?phi\b|\bphieu chi\b|\bso chi\b|\bkhoan chi\b|\bexpense")


def desc_to_canonical(desc: str) -> tuple[bool, str | None]:
    """(có khớp luật, tên chuẩn). Khớp mà tên chuẩn None nghĩa là cột trống theo README."""
    f = fold(desc)
    for rx, canon in _DESC_RULES:
        if rx.search(f):
            return True, canon
    return False, None


@dataclass
class ColumnMap:
    table: str
    column: str
    canonical: str | None
    source: str | None          # readme_col | readme_hint | name_dict | value_pattern | llm
    description: str | None     # mô tả README dùng làm bằng chứng
    note: str = ""


def build_name_dict(readmes) -> dict[str, str]:
    """Từ điển tên cột (bỏ dấu) -> tên chuẩn, thu từ README của nhiều shop.

    Chỉ giữ tên mà >= 80% lần xuất hiện cùng một tên chuẩn (vd 'don gia' ở bảng bán và bảng nhập
    đều là unit_price -> giữ; 'giam gia' lúc của dòng lúc của đơn -> vẫn 'discount').
    """
    votes: dict[str, Counter] = defaultdict(Counter)
    forms: dict[str, set] = defaultdict(set)
    for info in readmes:
        for d in info.columns:
            ok, canon = desc_to_canonical(d.description)
            if ok and canon:
                # cùng họ thì gộp phiếu, để luật ngữ cảnh bảng quyết (giảm giá dòng/đơn,
                # "Thời gian" là ngày bán/ngày nhập/lúc thu, "Trạng thái" của đơn bán/phiếu nhập)
                canon = _FAMILY.get(canon, canon)
                votes[name_key(d.column)][canon] += 1
                forms[name_key(d.column)].add(_syllables(d.column))
    out = NameDict(forms=forms)
    for name, c in votes.items():
        # "tên" chung ủng hộ tên cụ thể đang chiếm đa số ('Tên hàng' ở danh mục README chỉ ghi "tên")
        specific = [k for k, _ in c.most_common() if k in _NAME_FAMILY]
        if "name" in c and specific:
            c = c.copy()
            c[specific[0]] += c.pop("name")
        canon, n = c.most_common(1)[0]
        if n >= 0.8 * sum(c.values()):
            out[name] = canon
    return out


class NameDict(dict):
    """Từ điển tên cột (khoá bỏ dấu) -> tên chuẩn, kèm các cách viết có dấu đã gặp của mỗi khoá."""

    def __init__(self, *a, forms=None, **k):
        super().__init__(*a, **k)
        self.forms = forms or {}


def with_base(names: NameDict, base: NameDict) -> NameDict:
    """Bổ sung vào từ điển của bộ đang dựng các tên mà README của bộ đó chưa từng mô tả, lấy từ từ điển nền (README train).
    Bộ đề có README không mô tả cột thì từ điển của nó gần như rỗng: cả "Mã hàng", "Trạng thái" cũng không map được.
    Tên README bộ đang dựng đã mô tả (kể cả tên bị bỏ vì các shop mô tả khác nhau) thì nền không đè."""
    forms = getattr(names, "forms", {})
    out = NameDict(names, forms=dict(forms))
    for k, v in base.items():
        if k not in names and k not in forms:
            out[k] = v
            out.forms[k] = getattr(base, "forms", {}).get(k, set())
    return out


_TONES = {"̀", "́", "̃", "̉", "̣"}     # huyền, sắc, ngã, hỏi, nặng


def _syllables(col: str) -> tuple:
    """Mỗi âm tiết -> (chữ gốc giữ ă â ê ô ơ ư đ, thanh). Vị trí đặt dấu không tính: 'hoá' = 'hóa'.
    Âm tiết không có dấu nào -> None (không dùng để so)."""
    import unicodedata
    out = []
    for w in name_key_raw(col).split():
        nfd = unicodedata.normalize("NFD", w)
        tone = next((c for c in nfd if c in _TONES), "")
        base = unicodedata.normalize("NFC", "".join(c for c in nfd if c not in _TONES))
        out.append((base, tone) if (tone or base != fold(base)) else None)
    return tuple(out)


def accent_clash(col: str, key: str, name_dict) -> bool:
    """Cột ghi có dấu mà dấu khác mọi cách viết của khoá trong từ điển: 'Hạng' (hạng khách) với 'Hàng',
    'Thuê' với 'Thuế'. Bỏ dấu thì trùng nhau nhưng là chữ khác. Âm tiết cột không dấu thì không so."""
    seen = getattr(name_dict, "forms", {}).get(key)
    mine = _syllables(col)
    if not seen or all(s is None for s in mine):
        return False

    def fits(form):
        return len(form) == len(mine) and all(a is None or b is None or a == b for a, b in zip(mine, form))
    accented = [f for f in seen if any(s is not None for s in f)]
    return bool(accented) and not any(fits(f) for f in accented)


_NAME_FAMILY = ("product_name", "customer_name", "supplier_name")
# Từ điển tên cột chỉ quyết HỌ khái niệm; tên cụ thể do ngữ cảnh bảng quyết (_resolve_context).
# Cùng chữ "ĐVT", "Giá", "Tổng tiền" mà ở danh mục / dòng bán / bảng đơn / sổ quỹ là các thứ khác nhau.
_FAMILY = {"line_discount": "discount", "order_discount": "discount",
           "purchase_date": "order_date", "payment_date": "order_date",
           "purchase_status": "status",
           "base_unit": "unit", "price": "unit_price",
           "line_amount": "money", "order_total": "money", "payment_amount": "money", "purchase_total": "money"}


def name_key_raw(col: str) -> str:
    """Như name_key nhưng giữ dấu: 'TênSảnPhẩm' -> 'tên sản phẩm'."""
    return split_name(col)


def name_key(col: str) -> str:
    """Khoá tra từ điển: 'TenSanPham' / 'ten_san_pham' / 'Tên sản phẩm' -> 'ten san pham'."""
    return fold(name_key_raw(col))


def _value_prefix(samples: list) -> str | None:
    """'ORD000123' x mọi giá trị -> 'ORD'."""
    vals = [v for v in samples if isinstance(v, str)]
    if len(vals) < 3:
        return None
    pref = Counter(m[1] for v in vals if (m := re.fullmatch(r"([A-Z]{2,4})\d{3,}", v)))
    if pref and pref.most_common(1)[0][1] >= 0.95 * len(vals):
        return pref.most_common(1)[0][0]
    return None


TIME_ONLY = re.compile(r"^\s*([01]?\d|2[0-3])\s*[:hg]\s*([0-5]\d)(\s*:\s*[0-5]\d)?\s*$", re.I)


def time_only(vals) -> bool:
    """Cột chỉ ghi giờ trong ngày ("18:51", "9h30"): ngày lấy ở cột ngày đơn."""
    vals = [str(v) for v in vals if v is not None and str(v).strip()]
    return len(vals) >= 5 and sum(bool(TIME_ONLY.match(v)) for v in vals) >= 0.95 * len(vals)


def _kind_ok(canon: str, kind: str, vals=()) -> bool:
    if canon == "payment_method" and kind == "number":
        return False
    if canon == "order_time" and kind == "text":
        return time_only(vals)
    if canon in NUMBER:
        return kind in ("number", "empty")
    if canon in DATE:
        return kind in ("datetime", "empty")
    return kind != "datetime"


def map_table(table: str, columns: list[str], kinds: dict[str, str], samples: dict[str, list],
              docs, name_dict: dict[str, str], parsed: dict[str, list] | None = None,
              unit_vocab: set[str] | None = None) -> list[ColumnMap]:
    """Map các cột của một bảng.

    docs: ColumnDoc của README áp cho bảng này. samples / parsed: giá trị gốc / đã parse của
    N dòng đầu, các cột cùng thứ tự dòng (để kiểm số học giữa cột). unit_vocab: các đơn vị đã biết.
    """
    by_name = {fold(d.column): d for d in docs}
    result: list[ColumnMap] = []
    for col in columns:
        f = fold(col)
        cand: list[tuple[str | None, str, str | None]] = []   # (canonical, source, description)
        d = by_name.get(f)
        # mô tả trong ngoặc ngay sau tên cột (README kiểu "**Tên** (ghi chú)") chỉ là ghi chú, có thể nhắc
        # tới cột khác ("= tổng thành tiền dòng − ..."): tên cột đã có trong từ điển thì tin tên trước
        if d is not None and d.source == "inline" and (
                (name_key(col) in name_dict and not accent_clash(col, name_key(col), name_dict))
                or name_key(col) in BUILTIN_NAMES):
            d = None
        if d is not None:
            ok, canon = desc_to_canonical(d.description)
            if ok:
                cand.append((canon, "readme_col" if d.source == "columns" else "readme_hint", d.description))
            else:
                result.append(ColumnMap(table, col, None, None, d.description, "mô tả README chưa có luật"))
                continue
        if not cand and (k := name_key(col)) in name_dict and not accent_clash(col, k, name_dict):
            cand.append((name_dict[k], "name_dict", None))
        if not cand and (k := name_key(col)) in BUILTIN_NAMES:
            cand.append((BUILTIN_NAMES[k], "builtin", None))
        if not cand and (p := _value_prefix(samples.get(col, []))) and p in CODE_PREFIX:
            cand.append((CODE_PREFIX[p], "value_pattern", None))
        if not cand:
            result.append(ColumnMap(table, col, None, None, None))
            continue
        canon, source, desc = cand[0]
        # cột mã: giá trị 'PAY...' mà tên gợi ý order_id -> tin giá trị (trừ khi README mô tả trực tiếp)
        pref = _value_prefix(samples.get(col, []))
        by_value = CODE_PREFIX.get(pref) if pref else None
        if by_value and canon in CODE_PREFIX.values() and canon != by_value and source != "readme_col":
            canon, source = by_value, "value_pattern"
        if canon is None:
            result.append(ColumnMap(table, col, None, source, desc, "README: cột trống"))
        elif not _kind_ok(canon, kinds.get(col, "text"), samples.get(col, [])):
            result.append(ColumnMap(table, col, None, source, desc,
                                    f"loại: {canon} cần kiểu khác, cột là {kinds.get(col)}"))
        else:
            result.append(ColumnMap(table, col, canon, source, desc))

    _resolve_context(result)
    _resolve_duplicates(result)
    _value_rules(result, kinds, samples, parsed or {}, unit_vocab or DEFAULT_UNITS)
    _resolve_context(result)
    _resolve_duplicates(result)
    return result


# Đơn vị gặp trong 44 shop; mỗi shop còn cộng thêm đơn vị trong README và trong cột đã map là đơn vị
DEFAULT_UNITS = {
    "cái", "chiếc", "ly", "cốc", "chai", "lon", "hộp", "gói", "kg", "g", "thùng", "lốc", "bao", "cây", "m",
    "m2", "m3", "bình", "cuộn", "viên", "vỉ", "ống", "lọ", "tuýp", "đĩa", "phần", "tô", "nồi", "con", "lần",
    "bộ", "quả", "bó", "tấm", "tấn", "xe", "bịch", "túi", "đôi", "lít", "ml", "suất", "bát", "chén", "set",
    "máy", "miếng", "hũ", "can", "khay", "vé", "giờ", "kệ", "cặp",
}


# bảng có các cột này là bảng bán (đơn hoặc dòng hàng), kể cả sổ ghi tay không có mã đơn
SALES_SIGNALS = {"order_id", "qty", "qty_base", "line_amount", "unit_price", "product_name", "order_date",
                 "order_total", "order_subtotal"}

_PAY_METHOD = re.compile(r"^(tien mat|chuyen khoan|ck|the|quet the|vi( dien tu)?|momo|zalopay|vnpay|cod|"
                         r"ghi no|no|cash|transfer|ewallet|card|debt|bank)\b")


# hạng / nhóm khách thường gặp ở phần mềm bán hàng và sổ tay
_TIER = re.compile(r"^(khach )?(le|si|ban si|ban le|than thiet|vip|thuong|moi|tiem nang|bac|vang|dong|kim cuong|"
                   r"bach kim|dai ly|ctv|cong tac vien|member|silver|gold|platinum|diamond|regular|wholesale|retail)"
                   r"( \d)?$")


def _distinct(vals) -> list:
    return list(dict.fromkeys(v for v in vals if v is not None))


def _value_rules(maps: list[ColumnMap], kinds, raw: dict[str, list], parsed: dict[str, list], units: set[str]):
    """Luật theo GIÁ TRỊ cho cột còn trống (không mô tả README, không có trong từ điển tên)."""
    from .parsers import is_walk_in, norm_status

    present = {m.canonical for m in maps if m.canonical}
    has_lines = bool(present & {"qty", "unit_price", "line_amount", "qty_base"})
    units_f = {fold(u) for u in units}
    for m in maps:
        if m.canonical or m.description:      # đã map, hoặc README đã nói về cột này
            continue
        kind, vals = kinds.get(m.column), [v for v in raw.get(m.column, []) if v is not None]
        if len(vals) < 5:
            continue
        uniq = _distinct(vals)
        if kind == "text":
            st = [norm_status(v) for v in vals]
            if present & SALES_SIGNALS and "purchase_id" not in present and len(uniq) <= 30 \
                    and sum(s is not None for s in st) >= 0.95 * len(vals) and len(set(st)) >= 2:
                m.canonical, m.source, m.note = "status", "value_rule", "giá trị là trạng thái đơn"
            elif (present & {"customer_id", "customer_name"} and "customer_group" not in present
                  and not present & {"product_id", "product_name", "qty", "qty_base"} and 2 <= len(uniq) <= 12
                  and sum(bool(_TIER.search(fold(v))) for v in uniq) >= 0.5 * len(uniq)):
                # cột hạng / loại khách mang giá trị "lẻ / sỉ / thân thiết / VIP": nhóm khách (rulebook §1),
                # bất kể tên cột ("Hạng", "LoaiKhachHang"); "Loại hình khách" = "Cá nhân" thì không
                m.canonical, m.source, m.note = "customer_group", "value_rule", "giá trị là hạng / nhóm khách"
                present.add("customer_group")
            elif len(uniq) <= 15 and sum(_PAY_METHOD.search(fold(v)) is not None for v in vals) >= 0.95 * len(vals):
                m.canonical, m.source, m.note = "payment_method", "value_rule", "giá trị là hình thức thanh toán"
            # tên khách: có "Khách lẻ" VÀ nhiều tên khác nhau (cột nhóm khách "lẻ / thân thiết" chỉ vài giá trị)
            elif sum(is_walk_in(v) for v in vals) >= 0.03 * len(vals) and len(uniq) >= 10:
                m.canonical, m.source, m.note = "customer_name", "value_rule", "có giá trị khách lẻ"
            elif len(uniq) <= 80 and sum(fold(v) in units_f for v in vals) >= 0.95 * len(vals):
                is_line = has_lines or present & {"order_id", "purchase_id"}
                m.canonical = "unit" if is_line else "base_unit"
                m.source, m.note = "value_rule", "giá trị là đơn vị tính"
        elif (kind == "datetime" and present & {"order_id", "order_date"} and "order_time" not in present
              and not present & {"purchase_id", "payment_id", "delivery_round", "expense_date", "return_id",
                                 "return_date", "qty_returned", "qty_returned_base"}
              and present & {"order_total", "order_subtotal", "line_amount", "qty", "paid", "status",
                             "customer_id", "customer_name", "channel"}):
            # bảng đơn / dòng bán: cột ngày giờ chưa map, gần như mọi ô có giờ trong ngày -> giờ tạo đơn
            # (ca sáng / ca chiều tính theo giờ tạo đơn, rulebook §2). Ngày đặt thường chỉ ghi ngày.
            ts = [v for v in parsed.get(m.column, []) if hasattr(v, "hour")]
            if len(ts) >= 5 and sum(v.hour or v.minute for v in ts) >= 0.9 * len(ts):
                m.canonical, m.source, m.note = "order_time", "value_rule", "ngày giờ có giờ trong ngày ở bảng đơn"
                present.add("order_time")
        elif kind == "number" and {"qty", "unit_price"} <= present and "line_amount" not in present:
            col_of = {mm.canonical: mm.column for mm in maps if mm.canonical}
            q, p, a = parsed.get(col_of["qty"], []), parsed.get(col_of["unit_price"], []), parsed.get(m.column, [])
            trip = [(x, y, z) for x, y, z in zip(q, p, a)
                    if isinstance(x, (int, float)) and isinstance(y, (int, float)) and isinstance(z, (int, float))]
            if len(trip) >= 20:
                exact = sum(abs(abs(z) - abs(x * y)) < 1 for x, y, z in trip)
                within = sum(0.5 * abs(x * y) - 1 <= abs(z) <= abs(x * y) + 1 for x, y, z in trip)
                if exact >= 0.7 * len(trip) and within >= 0.95 * len(trip):
                    m.canonical, m.source = "line_amount", "value_rule"
                    m.note = f"= SL x đơn giá ở {exact}/{len(trip)} dòng mẫu"


@dataclass
class TableInput:
    """Những gì mapping cần biết về một bảng (không cần toàn bộ dữ liệu)."""
    name: str
    file: str
    sheets: list
    columns: list[str]
    kinds: dict[str, str]
    raw: dict[str, list]       # N dòng đầu, giá trị gốc
    parsed: dict[str, list]    # cùng N dòng, giá trị đã parse

    @property
    def is_sqlite(self) -> bool:
        return self.file.lower().endswith((".sqlite", ".db", ".sqlite3"))


def shop_unit_vocab(readme) -> set[str]:
    """Đơn vị đã biết của shop: danh sách chung + đơn vị trong bảng quy đổi của README."""
    units = set(DEFAULT_UNITS)
    if readme is not None:
        for c in readme.unit_conversions:
            units.update({c.big_unit, c.base_unit})
    return units


def map_shop(tables: list[TableInput], readme, name_dict: dict[str, str], use_readme: bool = True,
             use_llm: bool = False) -> dict[str, list[ColumnMap]]:
    """Map mọi bảng của shop rồi chạy lượt liên bảng. use_readme=False để đo phần dự phòng.
    use_llm: cột luật để trống hỏi LLM (loader/llm.py), đặt sau cùng nên không ghi đè luật."""
    units = shop_unit_vocab(readme if use_readme else None)
    results = {}
    for t in tables:
        docs = readme.docs_for(t.file, t.sheets, table=t.name if t.is_sqlite else None) if use_readme else []
        results[t.name] = map_table(t.name, t.columns, t.kinds, t.raw, docs, name_dict, t.parsed, units)
    cross_table_names(results, {t.name: t.kinds for t in tables}, {t.name: t.raw for t in tables})
    for maps in results.values():
        _resolve_duplicates(maps)
    if use_llm:
        _llm_pass(tables, results, units)
        link_line_ids(tables, results)
    link_payment_books(tables, results)
    order_discount_names(tables, results)
    sale_ids_not_purchase(results)
    payment_method_values(tables, results)
    return results


def line_discount_values(tables: list[TableInput], results: dict[str, list[ColumnMap]]) -> None:
    """Cột số chưa map ở bảng dòng bán mà tỉ lệ với tiền dòng chỉ nhận vài mức (giảm thẻ 3% / 5%...) -> giảm giá dòng.
    Theo giá trị, không theo tên cột. sales_sql tự trừ khi sổ ghi tiền dòng TRƯỚC giảm (S5c)."""
    for t in tables:
        maps = results[t.name]
        present = {m.canonical for m in maps}
        if "line_discount" in present or "line_amount" not in present:
            continue
        amt_col = next(m.column for m in maps if m.canonical == "line_amount")
        amt = t.parsed.get(amt_col) or []
        for m in maps:
            if m.canonical is not None or t.kinds.get(m.column) != "number":
                continue
            vals = t.parsed.get(m.column) or []
            rs = []
            for x, a_ in zip(vals, amt):
                try:
                    x, a_ = float(x), float(a_)
                except (TypeError, ValueError):
                    continue
                if x == x and a_ == a_ and x > 0 and a_ > 0:
                    rs.append(round(x / a_, 3))
            if len(rs) < 8:
                continue
            top = sorted(((rs.count(r), r) for r in set(rs)), reverse=True)[:3]
            if sum(n for n, _ in top) >= 0.8 * len(rs) and all(0 < r < 0.5 for _, r in top):
                m.canonical, m.source = "line_discount", m.source or "value_rule"
                m.note = (m.note + " | " if m.note else "") + \
                    "tỉ lệ / tiền dòng gom vào " + ", ".join(f"{r:.0%}" for _, r in top) + ": giảm giá dòng"
                break


_PAY_COL = re.compile(r"thanh toan|hinh thuc|pttt|\btt\b|tra kieu|kieu tra|cach tra")


def payment_method_values(tables: list[TableInput], results: dict[str, list[ColumnMap]]) -> None:
    """Cột chữ "Thanh toán" chưa map (từ điển gán "đã trả" nhưng giá trị là chữ): >= 80% giá trị chuẩn hoá được thành
    hình thức thanh toán (TM, CK, ví, nợ...) -> payment_method."""
    from .build import _PAYMENT_NORM
    for t in tables:
        maps = results[t.name]
        present = {m.canonical for m in maps}
        if "payment_method" in present or not present & {"order_id", "order_date", "line_amount", "order_total"}:
            continue
        for m in maps:
            if m.canonical is not None or not _PAY_COL.search(name_key(m.column)):
                continue
            vs = [fold(str(v)).replace("_", " ") for v in t.raw.get(m.column, []) if v is not None and str(v).strip()]
            if len(vs) >= 20 and sum(any(rx.search(v) for rx, _ in _PAYMENT_NORM) for v in vs) >= 0.8 * len(vs):
                m.canonical, m.source = "payment_method", m.source or "value_rule"
                m.note = (m.note + " | " if m.note else "") + "giá trị là hình thức thanh toán"
                break


def sale_ids_not_purchase(results: dict[str, list[ColumnMap]]) -> None:
    """LLM gán mã giao dịch là mã phiếu nhập (purchase_id) ở bảng không có dấu hiệu nhập hàng (nhà cung cấp, ngày nhập,
    trạng thái phiếu nhập) mà có ngày / giờ bán hoặc hình thức khách trả: là mã đơn bán (vd phiên sạc xe, phiếu dịch vụ)."""
    for maps in results.values():
        present = {m.canonical for m in maps}
        if "order_id" in present or present & {"supplier_name", "supplier_id", "purchase_date", "purchase_status"}:
            continue
        if not present & {"order_date", "order_time", "payment_method"} or not present & {"order_total", "line_amount"}:
            continue
        for m in maps:
            if m.canonical == "purchase_id" and m.source == "llm":
                m.canonical = "order_id"
                m.note = (m.note + " | " if m.note else "") + "bảng không có dấu hiệu nhập hàng, có ngày bán / thanh toán: mã đơn"


_ORDER_DISC_NAME = re.compile(r"^(tien |giam )?voucher$|^giam (gia )?(ca )?(don|bill|hoa don)$|^chiet khau (ca )?(don|bill)$")


def order_discount_names(tables: list[TableInput], results: dict[str, list[ColumnMap]]) -> None:
    """Cột số "Voucher" / "Giảm giá đơn" chưa map ở bảng bán -> giảm giá cả đơn (rulebook: doanh thu không trừ, nợ thì trừ).
    Cột ghi mã voucher (chữ) không đụng. Chạy sau LLM nên prompt dựng DB không đổi."""
    for t in tables:
        maps = results[t.name]
        present = {m.canonical for m in maps}
        if "order_discount" in present or not present & {"order_id", "line_amount", "order_total"}:
            continue
        for m in maps:
            if m.canonical is None and _ORDER_DISC_NAME.search(name_key(m.column)) and t.kinds.get(m.column) == "number":
                m.canonical, m.source = "order_discount", m.source or "builtin"
                m.note = (m.note + " | " if m.note else "") + "tiền voucher / giảm cả đơn"
                break


def _shape(v) -> str:
    return re.sub(r"[A-Za-z]", "A", re.sub(r"\d", "9", str(v).strip()))


def link_payment_books(tables: list[TableInput], results: dict[str, list[ColumnMap]]) -> None:
    """Sổ thu nợ theo đợt ("Ngày trả", "Khách", "Hóa đơn", "Số tiền"): có ngày trả, không có mã đơn, không có dòng hàng.
    Cột chữ chưa map mà giá trị là mã đơn của bảng khác (trùng >= 50% hoặc cùng dạng >= 90%) -> order_id; tiền chung /
    tiền đơn của bảng đó -> tiền trả lần đó (payment_amount). Không có bước này bảng thành danh sách khách, nợ không tính."""
    raw = {t.name: t.raw for t in tables}
    ids, shapes = set(), set()
    for n, maps in results.items():
        for m in maps:
            if m.canonical == "order_id":
                vs = [v for v in raw[n].get(m.column, []) if v is not None and str(v).strip()]
                ids.update(fold(str(v)).strip() for v in vs)
                shapes.update(_shape(v) for v in vs)
    if len(ids) < 10:
        return
    for n, maps in results.items():
        canons = {m.canonical for m in maps}
        # biến thể: "Mã HĐ" bị LLM gán mã phiếu thu, "Ngày thu" gán ngày đơn (biz_209): ngày tên thu / trả / nộp / góp
        # ở bảng không có dòng hàng, có cột mang mã đơn của bảng khác -> ngày trả
        if "payment_date" not in canons and not canons & {"order_id", "product_name", "product_id", "qty", "qty_base",
                                                          "line_amount", "purchase_id"}:
            pay_day = [m for m in maps if m.canonical in ("order_date", "order_time") and m.source != "readme_col"
                       and re.search(r"\b(thu|tra|nop|gop)\b", name_key(m.column))]
            carrier = next((m for m in maps if m.canonical in (None, "payment_id")
                            and (m.canonical is None or m.source == "llm")
                            and (lambda vs: len(vs) >= 10 and (sum(fold(str(v)).strip() in ids for v in vs) >= 0.5 * len(vs) or sum(_shape(v) in shapes for v in vs) >= 0.9 * len(vs) and any(c.isalpha() for c in str(vs[0]))))(
                                [v for v in raw[n].get(m.column, []) if v is not None and str(v).strip()])), None)
            if pay_day and carrier:
                for m in pay_day:
                    m.canonical = "payment_date"
                    m.note = (m.note + " | " if m.note else "") + "ngày thu / trả của sổ thu nợ"
                canons = {m.canonical for m in maps}
        if "payment_date" not in canons or canons & {"order_id", "product_name", "product_id", "qty", "qty_base",
                                                      "line_amount", "order_date", "purchase_id"}:
            continue
        for m in maps:
            if m.canonical is not None and not (m.canonical == "payment_id" and m.source == "llm"):
                continue
            vs = [v for v in raw[n].get(m.column, []) if v is not None and str(v).strip()]
            if len(vs) < 10 or not all(isinstance(v, str) for v in vs):
                continue
            hit = sum(fold(v).strip() in ids for v in vs) / len(vs)
            same = sum(_shape(v) in shapes for v in vs) / len(vs)
            if hit >= 0.5 or same >= 0.9 and re.search(r"[A-Za-z]", vs[0]):
                m.canonical, m.source = "order_id", m.source or "value_pattern"
                m.note = (m.note + " | " if m.note else "") + f"giá trị là mã đơn bảng khác (trùng {hit:.0%}, cùng dạng {same:.0%})"
                if "payment_amount" not in canons:
                    for x in maps:
                        if x.canonical in ("order_total", "money") and x.source != "readme_col":
                            x.canonical = "payment_amount"
                            x.note = (x.note + " | " if x.note else "") + "tiền của sổ thu nợ: tiền trả lần đó"
                            break
                break


def cross_table_names(results: dict[str, list[ColumnMap]], kinds: dict[str, dict], raw: dict[str, dict]):
    """Lượt liên bảng: cột chữ chưa map mà giá trị nằm trong tập tên hàng / tên khách đã biết của shop."""
    known: dict[str, set] = {"product_name": set(), "customer_name": set()}
    for t, maps in results.items():
        for m in maps:
            if m.canonical in known:
                known[m.canonical].update(fold(v) for v in raw[t].get(m.column, []) if isinstance(v, str))
    for canon, names in known.items():
        if len(names) < 5:
            continue
        for t, maps in results.items():
            if canon in {m.canonical for m in maps}:
                continue
            for m in maps:
                if m.canonical or m.description or kinds[t].get(m.column) != "text":
                    continue
                uniq = {fold(v) for v in raw[t].get(m.column, []) if isinstance(v, str)}
                if len(uniq) >= 5 and len(uniq & names) >= 0.9 * len(uniq):
                    m.canonical, m.source = canon, "value_rule"
                    m.note = f"{len(uniq & names)}/{len(uniq)} giá trị trùng {canon} ở bảng khác"
                    break


def _resolve_context(maps: list[ColumnMap]):
    """Tên chung ('name', 'discount') -> tên cụ thể theo các cột khác trong bảng."""
    # lượt 1: chữ trong TÊN CỘT nói rõ ("Tên khách hàng", "Đơn vị cơ bản") -> tin tên cột
    for m in maps:
        if m.source == "readme_col":
            continue
        f = fold(m.column)
        if m.canonical in ("name",) + _NAME_FAMILY:
            hit = next((c for rx, c in _ENTITY_WORDS if rx.search(f)), None)
            if hit:
                m.canonical = hit
        elif m.canonical in ("unit", "base_unit") and re.search(r"co ban|\bgoc\b", f):
            m.canonical = "base_unit"
        elif m.canonical in ("unit", "base_unit") and re.search(r"quy doi|\blon\b", f):
            m.canonical = "big_unit"            # "Đơn vị quy đổi", "ĐV lớn"
        elif m.canonical == "status" and m.source != "value_rule" and re.search(
                r"thanh toan|hddt|hoa don dien tu|xuat hoa don|\b(khach|kh|ncc|tai khoan)\b", f):
            # trạng thái thanh toán / hoá đơn điện tử / khách: không phải trạng thái đơn.
            # Không dùng "TT" (thanh toán / trạng thái / thành tiền đều viết TT); giá trị là trạng thái đơn thì tin giá trị
            m.canonical, m.note = None, "trạng thái không phải của đơn (theo tên cột)"
    # phiếu thu ghi cả "Mã phiếu" lẫn "Mã đơn" (có ngày thu): "Mã phiếu" là mã phiếu thu. Từ điển train có "Mã phiếu" = mã đơn
    # (phiếu dịch vụ tiệm sửa) nên hai cột cùng thành order_id và cột "Mã đơn" thật bị bỏ khi khử trùng
    orders = [m for m in maps if m.canonical == "order_id"]
    if len(orders) >= 2 and any(name_key(m.column) == "ma don" for m in orders) \
            and any(m.canonical == "payment_date" for m in maps):
        for m in orders:
            if m.source != "readme_col" and re.fullmatch(r"ma phieu|so phieu", name_key(m.column)):
                m.canonical, m.note = "payment_id", "mã phiếu thu (bảng có cả mã đơn và ngày thu)"

    # NV3: Bảng phiếu thu không có cột mã phiếu. Tắt mặc định (bật DATAMATE_NV3=1): FX3e biz_205 lật 3 câu
    if maps and os.environ.get("DATAMATE_NV3") and re.search(r"\bphieu ?thu\b|\bthu ?tien\b|\bpayments?\b|\breceipts?\b", name_key(maps[0].table or "")):
        canons = {m.canonical for m in maps}
        if "order_id" in canons \
                and (canons & {"money", "order_total", "payment_amount"}) \
                and (canons & {"order_date", "order_time", "payment_date"}) \
                and not (canons & {"product_id", "product_name", "qty", "qty_base", "unit_price", "line_amount"}):
            for m in maps:
                if m.source != "readme_col":
                    if m.canonical in ("order_date", "order_time"):
                        m.canonical = "payment_date"
                        m.note = "phiếu thu (theo tên bảng)"
                    elif m.canonical in ("money", "order_total"):
                        m.canonical = "payment_amount"
                        m.note = "phiếu thu (theo tên bảng)"

    # lượt 2: ngữ cảnh bảng. Bảng dòng hàng = có số lượng / đơn giá / thành tiền, hoặc có hàng + đơn / ngày
    present = {m.canonical for m in maps}
    items = present & {"product_id", "product_name", "qty", "qty_base", "unit_price"}
    is_line = bool(present & _LINE_QTY) or bool(present & {"product_id", "product_name"}
                                                 and present & {"order_id", "purchase_id", "order_date"})
    # sổ chi phí (tên bảng / file nói "chi phí", "phiếu chi", "sổ chi", hoặc có ngày chi), không có dòng hàng:
    # tiền là tiền chi, ngày là ngày chi (rulebook §5 lãi ròng). Không thì tiền chung thành tiền đơn -> doanh thu
    if maps and not items and "order_id" not in present and (
            "expense_date" in present or _EXPENSE_TABLE.search(name_key(maps[0].table))):
        for m in maps:
            if m.canonical in ("money", "order_total", "payment_amount") and m.source != "readme_col":
                m.canonical = "expense_amount"
            elif m.canonical in ("order_date", "order_time", "payment_date") and m.source != "readme_col":
                m.canonical = "expense_date"
        present = {m.canonical for m in maps}
    for m in maps:
        if m.canonical == "money":     # cả khi README mô tả: "tổng tiền cả phiếu" chưa nói phiếu gì
            # tiền chung ("Tiền", "Tổng tiền"): sổ quỹ -> tiền thu; phiếu nhập -> tiền phiếu;
            # bảng có dòng hàng -> thành tiền dòng; bảng chỉ có đơn -> tiền cả đơn
            # mô tả nói "của cả phiếu / cả đơn" -> tiền cấp đơn, kể cả trong bảng có dòng hàng
            whole = bool(m.description and re.search(r"\bca (phieu|don|hoa don)\b", fold(m.description)))
            line = bool(items) and not whole
            m.canonical = ("payment_amount" if "payment_id" in present else
                           ("line_amount" if line else "purchase_total")
                           if "purchase_id" in present and "order_id" not in present else
                           "line_amount" if line else "order_total")
        elif m.source == "readme_col":
            pass                       # README mô tả rõ đơn vị / giá thì giữ
        elif (m.canonical == "unit" and "conv_factor" not in present and not present & _LINE_QTY
              and (not is_line or "qty_base" in present
                   and present & {"delivery_round", "delivery_date", "driver", "plate"})
              and not re.search(r"\bnhap\b|\bban\b", fold(m.column))):
            # đơn vị đi theo con số số lượng của bảng: danh mục / tồn kho không có số lượng dòng,
            # phiếu giao chỉ có SL cơ bản -> "ĐVT" là đơn vị cơ bản của hàng
            m.canonical = "base_unit"
        elif m.canonical == "unit_price" and not present & ({"qty", "line_amount", "qty_base"} |
                                                            {"order_id", "purchase_id"}):
            # "Giá" ở danh mục hàng: giá bán hiện tại, không phải đơn giá trên dòng
            m.canonical = "price"
        elif m.canonical == "price" and present & {"qty", "line_amount"} and present & {"order_id", "order_date"}:
            m.canonical = "unit_price"
        elif (m.canonical == "customer_group" and present & {"product_id", "product_name"}
              and not present & {"customer_id", "customer_name", "order_id"} and not re.search(r"khach|kh", fold(m.column))):
            # "Nhóm" trong danh mục hàng (không có khách, không có đơn): nhóm hàng. README train chỉ mô tả "Nhóm" ở bảng khách
            m.canonical = "category"
    for m in maps:
        if m.canonical == "name":
            m.canonical = ("product_name" if present & {"product_id", "qty", "unit_price", "line_amount"} else
                           "customer_name" if "customer_id" in present else
                           "supplier_name" if "supplier_id" in present else
                           "staff_name" if "staff_id" in present else "name")
        elif (m.canonical == "product_name" and m.source in ("name_dict", "builtin")
              and not _ENTITY_WORDS[2][0].search(fold(m.column))
              and present & {"order_total", "purchase_total", "order_subtotal", "paid", "money"}
              and not present & {"qty", "qty_base", "unit_price", "line_amount", "product_id"}):
            # cột chữ chung ("Diễn giải", "Nội dung") ở bảng đầu phiếu / đầu đơn (có tổng tiền, không có dòng
            # hàng): là ghi chú của phiếu, không phải tên hàng (biz_123 phieu_nhap.DienGiai = "nhập đầu kỳ")
            m.canonical, m.note = "note", "cột chữ chung ở bảng đầu phiếu: ghi chú, không phải tên hàng"
        elif m.canonical == "discount":
            # tên ghi rõ của đơn ("Giảm giá HĐ"), hoặc bảng không có dòng hàng -> giảm giá của đơn
            of_order = re.search(r"\b(hd|hoa don|don)\b", fold(m.column))
            m.canonical = ("order_discount" if of_order or not present & {"product_id", "product_name"}
                           else "line_discount")
        elif m.canonical in ("order_date", "order_time") and m.source != "readme_col":
            # "Thời gian" ở sổ quỹ là lúc thu, ở phiếu nhập là ngày nhập
            if "payment_id" in present:
                m.canonical = "payment_date"
            elif "purchase_id" in present and "order_id" not in present:
                m.canonical = "purchase_date"
        elif m.canonical == "status" and "purchase_id" in present and "order_id" not in present:
            m.canonical = "purchase_status"
        elif m.canonical == "status" and not present & SALES_SIGNALS:
            # vd trạng thái khách hàng "Đang hoạt động": không phải trạng thái đơn bán.
            # Sổ bán ghi tay có thể không có mã đơn, nên xét mọi dấu hiệu bảng bán chứ không chỉ order_id
            m.canonical, m.note = None, "trạng thái không thuộc bảng bán"
        elif (m.canonical == "qty" and m.source != "readme_col" and "batch_id" in present
              and "order_id" in present and not present & {"purchase_id", "unit", "unit_price", "line_amount"}):
            # bảng "đơn - lô - số lượng" (dev_005 DonHang_Lo): số lượng lấy từ lô tính theo đơn vị cơ bản.
            # Không áp cho bảng nhập: ở đó số lượng theo đơn vị nhập.
            m.canonical = "qty_base"
        elif m.canonical == "base_unit" and m.source != "readme_col" and present & {"qty", "line_amount"} \
                and present & {"order_id", "order_date", "purchase_id"}:
            # 'DonVi' ở danh mục là đơn vị cơ bản, nhưng ở dòng bán / nhập là đơn vị của dòng
            m.canonical = "unit"
        elif (m.canonical in ("unit", "base_unit") and m.source != "readme_col" and "conv_factor" in present
              and "big_unit" not in present and not present & {"qty", "order_id", "purchase_id"}
              and not re.search(r"co ban|\bgoc\b", fold(m.column))
              and sum(x.canonical in ("unit", "base_unit") for x in maps) == 1):
            # bảng đơn vị quy đổi (Đơn vị | Bằng | Mã hàng): đơn vị đi cùng hệ số là đơn vị lớn
            m.canonical = "big_unit"
            present.add("big_unit")


_SOURCE_RANK = {"readme_col": 0, "readme_hint": 1, "name_dict": 2, "builtin": 2, "value_pattern": 3,
                "value_rule": 4, "llm": 5}


def _resolve_duplicates(maps: list[ColumnMap]):
    """Hai cột cùng tên chuẩn: giữ cột có bằng chứng mạnh hơn (hoặc đứng trước), cột kia giữ tên gốc."""
    groups = defaultdict(list)
    for m in maps:
        if m.canonical:
            groups[m.canonical].append(m)
    for canon, ms in groups.items():
        if len(ms) < 2:
            continue
        ms.sort(key=lambda m: _SOURCE_RANK.get(m.source, 9))
        for m in ms[1:]:
            m.note = f"trùng {canon} với cột '{ms[0].column}'"
            m.canonical = None


_SCHEMA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "schema.md")


def canonical_vocab(path: str = _SCHEMA) -> dict[str, str]:
    """Tên chuẩn -> ý nghĩa, đọc từ các bảng 'Tên chuẩn | Ý nghĩa' của schema.md (một nguồn cho người và LLM)."""
    out, inside = {}, False
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("| Tên chuẩn |"):
                inside = True
            elif inside and line.startswith("|") and not line.startswith("|---"):
                names, meaning = line.strip().strip("|").split("|", 1)
                for n in re.findall(r"`([a-z_]+)`", names):
                    out[n] = meaning.strip()
            elif not line.startswith("|"):
                inside = False
    return out


_LLM_SYSTEM = """Bạn chuẩn hoá tên cột dữ liệu bán hàng của cửa hàng nhỏ ở Việt Nam.
Với mỗi cột cần map, dựa vào tên cột, giá trị mẫu, mô tả (nếu có) và các cột khác của bảng:
1. "nghia": cột này ghi gì (tối đa 12 chữ).
2. "ten": tên chuẩn trong danh sách dưới đây CHỈ KHI nghĩa của cột trùng đúng với mô tả của tên đó,
   tức là ai hỏi về tên chuẩn đó thì cột này là câu trả lời. Cột ghi thông tin khác, gần nghĩa,
   ngưỡng / giới hạn, thông tin phụ không có trong danh sách, hoặc không chắc -> null.
   Tên sai tệ hơn null. Không dùng lại tên chuẩn mà bảng đã có.
Chỉ trả về một JSON object: {"<tên cột>": {"nghia": "...", "ten": "<tên chuẩn>" hoặc null}}.

Tên chuẩn:
"""


def llm_map_prompt(table: str, unmapped: list[dict], known: list[tuple[str, str]], vocab: dict[str, str]
                   ) -> tuple[str, str]:
    """(system, user) — dùng chung cho pipeline và dữ liệu fine-tune (datamate/finetune)."""
    system = _LLM_SYSTEM + "\n".join(f"- {k}: {v}" for k, v in vocab.items())
    lines = [f"Bảng: {table}",
             "Cột đã biết: " + (", ".join(f'"{c}" = {k}' for c, k in known) or "(chưa có)"),
             "Cột cần map:"]
    for u in unmapped:
        smp = "; ".join(str(v)[:40] for v in u["samples"]) or "(trống)"
        desc = f", mô tả: {u['description']}" if u.get("description") else ""
        lines.append(f'- "{u["column"]}" (kiểu {u["kind"]}{desc}): {smp}')
    return system, "\n".join(lines)


def llm_map(table: str, unmapped: list[dict], known: list[tuple[str, str]], vocab: dict[str, str]
            ) -> dict[str, dict]:
    """Hỏi LLM tên chuẩn cho các cột chưa map của MỘT bảng. unmapped: column, kind, samples, description.
    Trả {cột: {"nghia": ..., "ten": tên chuẩn hoặc None}} như model trả; kiểm tra do người gọi làm."""
    from . import llm

    system, user = llm_map_prompt(table, unmapped, known, vocab)
    text = llm.chat(system, user, max_tokens=80 + 60 * len(unmapped))
    m = re.search(r"\{.*\}", text, re.S)
    try:
        out = json.loads(m.group(0)) if m else {}
    except json.JSONDecodeError:
        return {}
    return {k: v for k, v in out.items() if isinstance(v, dict)} if isinstance(out, dict) else {}


# LLM chỉ được đổi vai trò của bảng luật CHƯA nhận ra (other). Bảng luật đã nhận ra (bán, nhập, khách...) giữ
# nguyên: "Slg" -> conv_factor từng biến bảng chi tiết hoá đơn thành bảng quy đổi (mất cả bảng bán), "Tổng điểm"
# -> tồn kho biến danh sách khách thành bảng tồn. Bảng other thành bảng bán / nhập (cộng vào doanh thu, tiền nhập)
# chỉ khi đủ dấu hiệu đơn (>= 3 cột lõi) và tên bảng không phải sổ chi ("Ngày chi" -> order_date biến sổ chi
# phí thành bảng đơn).
_ROLE_GROUP = {"sales_lines": "ban", "orders": "ban", "order_info": "ban", "sales_batches": "ban",
               "deliveries": "ban", "payments": "ban",
               "purchases": "nhap", "purchase_lines": "nhap", "batches": "nhap"}
_PEOPLE = {"customers", "staff", "suppliers"}
_UNIT_NAMES = {"unit", "base_unit", "big_unit"}
_TX_CORE = {"order_id", "purchase_id", "product_name", "product_id", "qty", "qty_base", "unit_price", "line_amount",
            "order_total", "purchase_total", "order_date", "purchase_date"}


def _role_change_ok(old: str, new: str, cols: set[str] | None = None, table: str = "") -> bool:
    if old == new:
        return True
    g0, g1 = _ROLE_GROUP.get(old), _ROLE_GROUP.get(new)
    if g0 in ("ban", "nhap"):
        return g0 == g1          # tinh chỉnh trong nhóm (thông tin đơn + số lượng -> dòng hàng); không mất bảng bán
    if old in _PEOPLE:
        return False
    if g1 in ("ban", "nhap"):    # thành bảng bán / nhập (mã đơn + tên hàng trông như danh mục): đủ dấu hiệu đơn
        return len((cols or set()) & _TX_CORE) >= 3 and not _EXPENSE_TABLE.search(fold(table))
    return old == "other"


_ORDER_SIGNALS = {"order_id", "qty", "qty_base", "line_amount", "order_total", "order_subtotal"}


def _llm_family(props: list[tuple[ColumnMap, str]], used: set[str], sales: bool) -> None:
    """LLM chỉ đáng tin ở HỌ khái niệm; tên cụ thể trong họ do ngữ cảnh bảng quyết (như từ điển tên).
    - số lượng: bảng không có đơn vị của dòng -> số lượng theo đơn vị cơ bản (rulebook §10)
    - thời điểm: bảng nhóm bán (sales: không phải danh mục, thẻ kho) chưa có ngày đặt -> cột thời điểm
      đầu tiên là ngày đặt; thời điểm tạo của chính đơn là giờ đặt"""
    def present():
        return used | {c for _, c in props}
    for i, (m, c) in enumerate(props):
        if c in ("qty", "qty_returned") and "unit" not in present():
            props[i] = (m, c + "_base")
    for i, (m, c) in enumerate(props):
        cur = present() - {c}
        if not sales or not cur & _ORDER_SIGNALS:
            continue
        if c in ("order_time", "created_date") and "order_date" not in cur:
            props[i] = (m, "order_date")
        elif c == "created_date" and "order_id" in cur and "order_time" not in cur:
            props[i] = (m, "order_time")


_CLASS_NAMES = {"category", "customer_group", "channel", "payment_method"}


def _llm_values_ok(c: str, vals: list, units: set[str]) -> bool:
    """Giá trị phải hợp với tên LLM chọn: cột đơn vị toàn đơn vị tính; cột mã không mang tiền tố của mã khác;
    cột phân loại (nhóm hàng, kênh...) phải có từ 2 giá trị (một giá trị cho mọi dòng thì không phân loại gì)."""
    if c in _CLASS_NAMES and len(vals) >= 10 and len({fold(str(v)) for v in vals}) < 2:
        return False
    if c in _UNIT_NAMES:
        uniq = {fold(v) for v in vals if isinstance(v, str)}
        return bool(uniq) and len(uniq & {fold(u) for u in units}) >= 0.8 * len(uniq)
    if c.endswith("_id") and (p := _value_prefix(vals)) and CODE_PREFIX.get(p, c) != c:
        return False
    return True


def _resolve_qty_pair(props: list[tuple[ColumnMap, str]], t: TableInput) -> None:
    """Hai cột cùng là số lượng (ghi trên dòng / quy ra đơn vị cơ bản, LLM dễ gom về một tên): cột luôn >= cột kia
    là qty_base (hệ số quy đổi >= 1). Không phân định được thì giữ nguyên."""
    idx = [i for i, (_, c) in enumerate(props) if c in ("qty", "qty_base")]
    if len(idx) != 2:
        return
    a, b = (props[i][0] for i in idx)
    pairs = [(parse_number(x), parse_number(y)) for x, y in zip(t.parsed.get(a.column, []), t.parsed.get(b.column, []))]
    pairs = [(x, y) for x, y in pairs if x is not None and y is not None]
    if len(pairs) < 5:
        return
    if all(x <= y for x, y in pairs):
        props[idx[0]], props[idx[1]] = (a, "qty"), (b, "qty_base")
    elif all(x >= y for x, y in pairs):
        props[idx[0]], props[idx[1]] = (a, "qty_base"), (b, "qty")


def _resolve_llm_duplicates(props: list[tuple[ColumnMap, str]], t: TableInput) -> list[tuple[ColumnMap, str]]:
    """Nhiều cột cùng được LLM gán một tên chuẩn: không lấy cột đứng trước (biz_111: cột nhóm hàng 9 giá trị
    chiếm mất tên hàng của cột tên món 50 giá trị). Tên / mã (*_name, *_id): cột nhiều giá trị khác nhau nhất
    (tên hàng chi tiết hơn tên nhóm); tên chuẩn khác: bỏ cả, không chắc thì không map."""
    by: dict[str, list] = defaultdict(list)
    for m, c in props:
        by[c].append(m)
    out = []
    for m, c in props:
        group = by[c]
        if len(group) == 1:
            out.append((m, c))
        elif c.endswith(("_name", "_id")):
            card = {g.column: len({fold(str(v)) for v in t.raw.get(g.column, []) if v is not None}) for g in group}
            best = max(group, key=lambda g: card[g.column])
            if m is best and sorted(card.values())[-1] > sorted(card.values())[-2]:
                out.append((m, c))
    return out


HDR = os.environ.get("DATAMATE_HDR", "1") != "0"


def _header_ok(t: TableInput, maps: list[ColumnMap], cand: list[tuple[ColumnMap, str]]) -> bool:
    """Sổ đầu đơn (mỗi dòng một đơn: mã đơn + ngày đặt, dòng hàng ở bảng khác): mã đơn gần như không lặp."""
    col = next((m.column for m, c in cand if c == "order_id"), None) or next(
        (m.column for m in maps if m.canonical == "order_id"), None)
    # ngày đặt có thể đã do luật tên gán từ trước (nằm trong maps, không trong cand)
    if not col or not (any(c == "order_date" for _, c in cand) or any(m.canonical == "order_date" for m in maps)):
        return False
    vals = [fold(str(v)) for v in t.raw.get(col, []) if v is not None and str(v).strip()]
    return len(vals) >= 20 and len(set(vals)) >= 0.9 * len(vals)


def link_line_ids(tables: list[TableInput], results: dict[str, list[ColumnMap]]) -> None:
    """HDR: mã phiếu LLM gán purchase_id mà giá trị nằm trong mã đơn của bảng khác (chi tiết của sổ đầu đơn,
    nối qua mã phiếu) và không nằm trong mã phiếu nhập nào -> order_id."""
    if not HDR:
        return
    raw = {t.name: t.raw for t in tables}

    def vals(name, canon):
        return {fold(str(v)) for m in results[name] if m.canonical == canon
                for v in raw[name].get(m.column, []) if v is not None and str(v).strip()}
    orders = {n: vals(n, "order_id") for n in results}
    buys = {n: vals(n, "purchase_id") for n in results}
    for n, maps in results.items():
        if "order_id" in {m.canonical for m in maps}:
            continue
        for m in maps:
            if m.canonical != "purchase_id" or m.source != "llm":
                continue
            mine = buys[n]
            if len(mine) < 20 or any(len(mine & b) for k, b in buys.items() if k != n):
                continue
            if any(k != n and len(mine & o) >= 0.9 * len(mine) for k, o in orders.items()):
                m.canonical, m.note = "order_id", m.note + " | mã nằm trong mã đơn bảng khác (HDR)"


def _llm_pass(tables: list[TableInput], results: dict[str, list[ColumnMap]], units: set[str]):
    """Lượt cuối: cột luật để trống (không có bằng chứng, hoặc README mô tả mà chưa có luật) -> LLM.
    Chỉ nhận tên có trong schema, đúng kiểu và giá trị, chưa có trong bảng, không đưa bảng sang thực thể
    khác (_role_change_ok). Nghĩa LLM nêu ghi vào
    note kể cả khi không map, để phía query đọc được cột lạ."""
    from .build import table_role

    vocab = canonical_vocab()
    for t in tables:
        maps = results[t.name]
        todo = [m for m in maps if m.canonical is None and m.source is None
                and m.note in ("", "mô tả README chưa có luật") and t.kinds.get(m.column) != "empty"]
        if not todo:
            continue
        used = {m.canonical for m in maps if m.canonical}
        cols = [{"column": m.column, "kind": t.kinds.get(m.column), "description": m.description,
                 "samples": _distinct(t.raw.get(m.column, []))[:8]} for m in todo]
        try:
            res = llm_map(t.name, cols, [(m.column, m.canonical) for m in maps if m.canonical], vocab)
        except Exception as e:          # mạng / server lỗi: giữ kết quả luật
            for m in todo:
                m.note = f"LLM lỗi: {type(e).__name__}"
            continue
        props = []
        for m in todo:
            r = res.get(m.column, {})
            c, meaning = r.get("ten"), str(r.get("nghia") or "")[:80]
            if meaning:
                m.note = f"LLM: {meaning}"
            if c in vocab and _llm_values_ok(c, [v for v in t.raw.get(m.column, []) if v is not None], units):
                props.append((m, c))
        # LLM cho thấy đây là bảng dòng hàng: cột đơn vị luật theo giá trị gán base_unit là đơn vị của dòng
        if {c for _, c in props} & {"qty", "qty_base", "line_amount"} and "base_unit" in used and "unit" not in used:
            for m in maps:
                if m.canonical == "base_unit" and m.source == "value_rule":
                    m.canonical = "unit"
                    used = (used - {"base_unit"}) | {"unit"}
        r0 = table_role(used)
        # HDR: bảng có mã đơn nhưng luật đoán là khách / chưa rõ (sổ đầu đơn chưa có ngày) vẫn là bảng nhóm bán
        hdr_sales = HDR and r0 in ("customers", "other") and "order_id" in used | {c for _, c in props}
        _llm_family(props, used, _ROLE_GROUP.get(r0) == "ban" or hdr_sales)
        _resolve_qty_pair(props, t)
        props = _resolve_llm_duplicates(props, t)
        cand, seen = [], set(used)
        for m, c in props:
            if c not in seen and _kind_ok(c, t.kinds.get(m.column, "text")):
                cand.append((m, c))
                seen.add(c)
        # xét vai trò trên CẢ bộ cột đề xuất (bảng bán đổi hết tên cột chỉ đủ dấu hiệu khi gộp lại);
        # không được thì nhận từng cột không làm đổi vai trò bảng
        whole = _role_change_ok(r0, table_role(seen), seen, t.name) or (
            hdr_sales and table_role(seen) == "orders" and _header_ok(t, maps, cand))
        for m, c in cand:
            if whole or _role_change_ok(r0, table_role(used | {c}), used | {c}, t.name):
                m.canonical, m.source = c, "llm"
                used.add(c)
