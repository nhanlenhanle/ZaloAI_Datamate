"""Kế hoạch trả lời (JSON) -> đáp án. LLM (hoặc bộ dịch dạng câu) ghép kế hoạch; code tính kỳ theo §2, khớp tên trong
dữ liệu, chạy SQL trên bảng chuẩn (query/facts.py) và định dạng theo §9. Không đủ dữ liệu -> PlanError, phía trên bỏ trống.

Kế hoạch lá:
  {"nguon": "dong_ban", "phep": "tong|dem|dem_khac|tb|min|max|dem_nhom|gia_duy_nhat|chan_le", "cot": "tien",
   "loc": [{"cot": "kenh", "op": "=", "gt": "zalo"}], "ky": {...}, "den_het": {...}, "moi_trang_thai": false,
   "nhom": "hang", "co_dieu_kien": {"op": ">=", "gt": 3}, "xep": {"chieu": "giam", "lay": 5}, "cot_ra": "ten|gia_tri|ca_hai"}
Kế hoạch ghép: {"ghep": "ti_le|tang_truong|hieu|thuong|danh_sach|lon_hon|tang_lien_tuc|giam_lien_tuc", "cac": [kế hoạch, ...]}.
Kỳ ("ky"): {"loai": "ngay", "ngay": "2026-05-01"} | hom_nay | hom_qua | tuan_nay | tuan_truoc | thang (thang, nam?) |
  thang_nay | thang_truoc | quy (quy, nam?) | nam (nam) | tu_dau_nam | n_ngay (n) | khoang (tu, den) | tet (nam) |
  truoc_tet (nam) | ky_truoc (cua) | cung_ky_nam_truoc (cua).
"""
from __future__ import annotations

import datetime as dt
import difflib
import json
import math

import duckdb

from datamate.loader.parsers import fold
from datamate.query import alias
from datamate.query.facts import AT_DATE, BY_RANGE, FIELDS, HAS_VALID, MONEY, Facts, NoSource
from datamate.tests.verify_answers import (_cols, _month_end, _no_year, _tables, customer_ids_by_name, names_by_id,
                                           text_key)


class PlanError(Exception):
    """Kế hoạch sai hoặc không chạy được trên shop này."""


class MissingData(PlanError):
    """Kế hoạch đúng nhưng shop không có dữ liệu cần (§7), khác với kế hoạch viết sai."""


def _money(v):
    return None if v is None else int(math.floor(v + 0.5))


def _d(s) -> dt.date:
    if isinstance(s, dt.date):
        return s
    try:
        return dt.date.fromisoformat(str(s)[:10])
    except ValueError as e:
        raise PlanError(f"ngày lạ {s}") from e


# ---------------------------------------------------------------- kỳ (§2)

def resolve_period(k: dict, today: dt.date, con=None) -> tuple[dt.date, dt.date]:
    if not isinstance(k, dict):
        raise PlanError("kỳ phải là object")
    t = k.get("loai")
    if t == "ngay":
        d = _d(k.get("ngay"))
        return d, d
    if t == "hom_nay":
        return today, today
    if t == "hom_qua":
        d = today - dt.timedelta(days=1)
        return d, d
    if t == "tuan_nay":
        return today - dt.timedelta(days=today.weekday()), today
    if t == "tuan_truoc":
        a = today - dt.timedelta(days=today.weekday() + 7)
        return a, a + dt.timedelta(days=6)
    if t == "thang":
        m = int(k["thang"])
        y = int(k.get("nam") or _no_year(m, today))
        return dt.date(y, m, 1), _month_end(y, m)
    if t == "thang_nay":
        return today.replace(day=1), today
    if t == "thang_truoc":
        if k.get("cua"):        # "tháng liền trước của tháng M"
            return resolve_period({"loai": "ky_truoc", "cua": k["cua"]}, today, con)
        e = today.replace(day=1) - dt.timedelta(days=1)
        return e.replace(day=1), e
    if t == "quy":
        q = int(k["quy"])
        first = 3 * (q - 1) + 1
        y = int(k.get("nam") or (today.year if dt.date(today.year, first, 1) <= today else today.year - 1))
        return dt.date(y, first, 1), _month_end(y, first + 2)
    if t == "nam":
        y = int(k["nam"])
        return dt.date(y, 1, 1), dt.date(y, 12, 31)
    if t == "tu_dau_nam":
        return dt.date(today.year, 1, 1), today
    if t == "n_ngay":
        n = int(k["n"])
        return today - dt.timedelta(days=n - 1), today
    if t == "khoang":
        return _d(k["tu"]), _d(k["den"])
    if t == "tu_ngay":          # N ngày kể từ ngày D, tính cả D
        a = _d(k["tu"])
        return a, a + dt.timedelta(days=int(k["n"]) - 1)
    if t in ("tet", "truoc_tet"):
        if con is None:
            raise PlanError("cần DB để tra kỳ Tết")
        r = con.execute("SELECT CAST(start_date AS DATE), CAST(end_date AS DATE) FROM _tet_periods WHERE tet_year = ?",
                        [int(k["nam"])]).fetchone()
        if not r:
            raise PlanError("không có kỳ Tết")
        a, b = r[0], min(r[1], today)
        if t == "tet":
            return a, b
        n = (r[1] - r[0]).days + 1
        return a - dt.timedelta(days=n), a - dt.timedelta(days=1)
    if t == "ky_truoc":
        a, b = resolve_period(k["cua"], today, con)
        if k["cua"].get("loai") == "tu_ngay":                       # N ngày ngay trước D, kể cả khi D là ngày 1
            return a - dt.timedelta(days=(b - a).days + 1), a - dt.timedelta(days=1)
        if a.day == 1 and (b + dt.timedelta(days=1)).day == 1:      # trọn tháng: cả tháng trước
            e = a - dt.timedelta(days=1)
            return e.replace(day=1), e
        if a.day == 1 and a.year == b.year and a.month == b.month:  # tháng này đến hôm nay: cùng số ngày (§2)
            e = a - dt.timedelta(days=1)
            return e.replace(day=1), e.replace(day=min(b.day, e.day))
        n = (b - a).days + 1
        return a - dt.timedelta(days=n), a - dt.timedelta(days=1)
    if t == "cung_ky_nam_truoc":
        a, b = resolve_period(k["cua"], today, con)
        try:
            return a.replace(year=a.year - 1), b.replace(year=b.year - 1)
        except ValueError:                                           # 29/2
            return a.replace(year=a.year - 1, day=28), b.replace(year=b.year - 1, day=28)
    raise PlanError(f"loại kỳ lạ: {t}")


# ---------------------------------------------------------------- khớp tên trong câu với dữ liệu

def _product_index(con) -> dict[str, tuple]:
    """khoá tên -> (mã, khoá, tên); có mã thì ưu tiên. Gồm cách gọi khác (_product_aliases)."""
    out: dict[str, tuple] = {}
    for role in ("products", "stock", "batches", "purchase_lines", "sales_lines"):
        for t in _tables(con, role):
            c = _cols(con, t)
            if "product_name" not in c:
                continue
            idc = "CAST(product_id AS VARCHAR)" if "product_id" in c else "NULL"
            for pid, nm in con.execute(f'SELECT DISTINCT {idc}, product_name FROM "{t}" '
                                       f'WHERE product_name IS NOT NULL').fetchall():
                k = text_key(nm)
                if k and (k not in out or (pid is not None and out[k][0] is None)):
                    out[k] = (pid, k, nm)
    try:
        for al, nm in con.execute("SELECT alias, product_name FROM _product_aliases").fetchall():
            k = text_key(al)
            if k and k not in out and text_key(nm) in out:
                out[k] = out[text_key(nm)]
    except duckdb.Error:
        pass
    return out


def match_product(con, text: str, cache: dict) -> tuple:
    if "hang" not in cache:
        cache["hang"] = _product_index(con)
    idx = cache["hang"]
    k = text_key(text)
    if k in idx:
        return idx[k]
    near = difflib.get_close_matches(k, list(idx), n=2, cutoff=0.88)
    # gõ sai một chút: chỉ nhận khi gần đúng một tên (hai tên gần nhau thì không đoán: "Sting dâu" / "Sting dứa")
    if len(near) == 1:
        return idx[near[0]]
    raise PlanError(f"không thấy mặt hàng '{text}'")


def _staff_values(con, table: str, text: str) -> list[str]:
    """Giá trị cột nhan_vien ứng với tên / mã trong câu (đơn có thể chỉ ghi mã: tra bảng nhân viên)."""
    k = text_key(text)
    want = {str(text).lower(), k}
    for t in _tables(con, "staff"):
        c = _cols(con, t)
        if {"staff_id", "staff_name"} <= c:
            want |= {str(i).lower() for i, nm in con.execute(f'SELECT staff_id, staff_name FROM "{t}"').fetchall()
                     if text_key(nm) == k}
    vals = [v for v, in con.execute(f'SELECT DISTINCT nhan_vien FROM "{table}" WHERE nhan_vien IS NOT NULL').fetchall()]
    hit = [v for v in vals if str(v).lower() in want or text_key(v) in want]
    if not hit:
        raise PlanError(f"không thấy nhân viên '{text}'")
    return hit


def _q(v) -> str:
    return "'" + str(v).replace("'", "''") + "'"


def _in_period(col_sql: str, f: dict, today: dt.date | None, con) -> str:
    """Lọc cột ngày rơi vào một kỳ: {"cot": <cột ngày>, "op": "trong_ky", "ky": <kỳ>}."""
    k = f.get("ky") if isinstance(f.get("ky"), dict) else f.get("gt")
    if not isinstance(k, dict) or today is None:
        raise PlanError('op "trong_ky" cần "ky": <kỳ>')
    a, b = resolve_period(k, today, con)
    return f"TRY_CAST({col_sql} AS DATE) BETWEEN DATE {_q(a)} AND DATE {_q(b)}"


def _condition(con, table: str, fact: str, f: dict, cache: dict, today: dt.date | None = None) -> str:
    col, op, val = f.get("cot"), f.get("op", "="), f.get("gt")
    if col not in FIELDS[fact] and col not in ("ma_hang", "khoa_hang"):
        raise PlanError(f"bảng {fact} không có cột {col}")
    if op == "trong_ky":
        return _in_period(f'"{col}"', f, today, con)
    if col == "hang" and op == "=":
        pid, key, _ = match_product(con, str(val), cache)
        have = {r[0] for r in con.execute(f'DESCRIBE "{table}"').fetchall()}
        conds = []
        if pid is not None and "ma_hang" in have:
            conds.append(f"ma_hang = {_q(pid)}")
        if "khoa_hang" in have:
            conds.append(f"khoa_hang = {_q(key)}")
        if not conds:
            raise PlanError("không khớp được mặt hàng")
        return "(" + " OR ".join(conds) + ")"
    if col == "khach" and op == "=":
        ids = customer_ids_by_name(con, str(val))
        if not ids:
            ids = [str(val)]
        if len(ids) != 1:
            raise PlanError(f"tên khách '{val}' khớp {len(ids)} mã")
        return f"khach = {_q(ids[0])}"
    if col == "nhan_vien" and op == "=":
        return "nhan_vien IN (" + ", ".join(_q(v) for v in _staff_values(con, table, str(val))) + ")"
    if col in ("nhom_hang", "nhom_khach", "hoat_chat", "don_vi_co_ban", "nha_cung_cap") and op == "=":
        # đúng tên (§3, §6): so bỏ dấu / hoa thường; không gộp tên khác
        vals = [v for v, in con.execute(f'SELECT DISTINCT "{col}" FROM "{table}" WHERE "{col}" IS NOT NULL').fetchall()]
        hit = [v for v in vals if text_key(v) == text_key(str(val).replace("_", " "))]
        if not hit:
            raise PlanError(f"không thấy {col} '{val}'")
        return f'"{col}" IN (' + ", ".join(_q(v) for v in hit) + ")"
    if op == "ket_thuc":
        names = (f"lower(COALESCE(ten_hang, ''))" if col == "ten_hang" else f'lower(COALESCE(CAST("{col}" AS VARCHAR), \'\'))')
        return f"ends_with(trim({names}), {_q(str(val).lower())})"
    if op == "rong":
        return f'"{col}" IS NULL'
    if op == "khong_rong":
        return f'"{col}" IS NOT NULL'
    if op == "in":
        if not isinstance(val, list) or not val:
            raise PlanError("op in cần danh sách")
        return f'"{col}" IN (' + ", ".join(_lit(v) for v in val) + ")"
    if op in ("=", "!=", ">", ">=", "<", "<="):
        return f'"{col}" {op} {_lit(val)}'
    raise PlanError(f"op lạ {op}")


def _lit(v) -> str:
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (int, float)):
        return str(v)
    if v is None:
        raise PlanError("giá trị lọc trống")
    s = str(v)
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        return f"DATE {_q(s)}"
    return _q(s)


# ---------------------------------------------------------------- chạy kế hoạch

def _text_key(col: str) -> str:
    """Biểu thức SQL so chữ không phân biệt dấu, hoa thường; phải khớp với loader.parsers.fold."""
    return f"regexp_replace(strip_accents(replace(lower(trim(CAST({col} AS VARCHAR))), 'đ', 'd')), '\\s+', ' ', 'g')"


def _is_date(s: str) -> bool:
    return len(s) == 10 and s[4] == "-" and s[7] == "-"


_AGG = {"tong": "SUM", "tb": "AVG", "min": "MIN", "max": "MAX"}
_GHEP = ("ti_le", "tang_truong", "hieu", "thuong", "danh_sach", "lon_hon", "tang_lien_tuc", "giam_lien_tuc", "dem_giao", "dem_hieu")
# cách gọi thường gặp của cột dòng bán: cùng nghĩa, không phải thông tin thiếu
_ALIAS = {"dong_ban": {"doanh_thu": "tien", "thanh_tien": "tien", "so_tien": "tien", "lai_gop": "lai",
                       "so_luong": "sl_co_ban"}}
_ID_COLS = {"don", "khach", "hang", "phieu", "nhan_vien", "nha_cung_cap"}
# cột tiền ở bảng gốc của shop (tên chuẩn của lớp data): tổng, trung bình của tiền làm tròn về đồng (§9)
_RAW_MONEY = {"unit_price", "line_amount", "line_discount", "unit_cost", "price", "new_price", "old_price", "order_subtotal",
              "order_discount", "discount", "purchase_total", "order_total", "shipping_fee", "paid", "debt", "payment_amount",
              "money", "expense_amount", "doanh_thu_don"}
_OUTER = {"tong": "SUM", "tb": "AVG", "min": "MIN", "max": "MAX", "dem": "COUNT"}
_HAVING_AGG = {"tong": 'SUM("{c}")', "tb": 'AVG("{c}")', "min": 'MIN("{c}")', "max": 'MAX("{c}")', "dem_khac": 'COUNT(DISTINCT "{c}")',
               "dem": "COUNT(*)"}


def _is_part(a: dict, b: dict) -> bool:
    """a là b lọc thêm điều kiện (mọi thứ khác giống nhau)."""
    def base(x):
        return {k: v for k, v in x.items() if k not in ("loc", "moi_trang_thai") and v is not None}

    def conds(x):
        return [json.dumps(f, sort_keys=True, ensure_ascii=False) for f in x.get("loc") or []]
    ca, cb = conds(a), conds(b)
    return base(a) == base(b) and len(ca) > len(cb) and set(cb) <= set(ca)


_CMP = (">", ">=", "<", "<=")
_ORDER_LEVEL = {"dem": ("dem_khac", "don"), "dem_khac": ("dem_khac", "don"), "tong": ("tong", "doanh_thu"), "tb": ("tb", "doanh_thu")}


def _order_threshold(p: dict) -> dict:
    """Ngưỡng trên doanh thu của đơn viết thành lọc dòng bán ("doanh_thu" >= X): doanh thu là của cả đơn (§1), nên tính
    trên bảng don. Không chuyển được (lọc, nhóm theo cột chỉ dòng bán có) thì báo cách viết đúng."""
    loc = p.get("loc") or []
    if p.get("nguon") != "dong_ban" or not isinstance(loc, list) \
            or not any(isinstance(f, dict) and f.get("cot") == "doanh_thu" and f.get("op") in _CMP for f in loc):
        return p
    op, col = p.get("phep"), p.get("cot")
    fit = op in _ORDER_LEVEL and col in (None, "don", "tien", "doanh_thu") and (op in ("dem", "dem_khac")) == (col in (None, "don")) \
        and all(isinstance(f, dict) and f.get("cot") in FIELDS["don"] for f in loc) and p.get("nhom") in (None, *FIELDS["don"])
    if not fit:
        raise PlanError('ngưỡng doanh thu của đơn: dùng "nguon": "don" với cột doanh_thu, hoặc "phep": "dem_nhom", "nhom": "don", '
                        '"cot": "tien", "do": "tong", "co_dieu_kien": {...}')
    new_op, new_col = _ORDER_LEVEL[op]
    return {**p, "nguon": "don", "phep": new_op, "cot": new_col}


def normalize(plan: dict) -> dict:
    """Sửa chỗ kế hoạch viết lệch mà nghĩa đã rõ, không đoán thêm gì."""
    p = _order_threshold(dict(plan))
    if "ghep" in p:
        parts = p.get("cac") or []
        # tiền chia cho số đếm vẫn là tiền (§9 làm tròn đồng)
        if p["ghep"] == "thuong" and len(parts) == 2 and all(isinstance(x, dict) for x in parts) \
                and parts[0].get("cot") in MONEY and parts[1].get("cot") not in MONEY:
            p["tien"] = True
        # tỉ lệ là phần / tổng: A không lọc mà B lọc thêm thì hai vế bị đảo
        if p["ghep"] == "ti_le" and len(parts) == 2 and all(isinstance(x, dict) for x in parts) and _is_part(parts[1], parts[0]):
            p["cac"] = parts = [parts[1], parts[0]]
        pair = len(parts) == 2 and all(isinstance(x, dict) for x in parts)
        # tỉ lệ theo trạng thái: mẫu số là mọi đơn, cả đơn huỷ / trả (§1)
        if p["ghep"] == "ti_le" and pair and _is_part(parts[0], parts[1]) \
                and any(f.get("cot") == "trang_thai" for f in parts[0].get("loc") or []):
            p["cac"] = parts = [parts[0], {**parts[1], "moi_trang_thai": True}]
        # tháng này so với tháng trước: lấy cùng số ngày của tháng trước (§2)
        if p["ghep"] in ("tang_truong", "ti_le", "hieu", "lon_hon") and pair \
                and (parts[0].get("ky") or {}).get("loai") == "thang_nay" and parts[1].get("ky") == {"loai": "thang_truoc"}:
            p["cac"] = [parts[0], {**parts[1], "ky": {"loai": "ky_truoc", "cua": {"loai": "thang_nay"}}}]
        return p
    fact = p.get("nguon")
    alias = _ALIAS.get(fact, {})
    for key in ("cot", "nhom"):
        p[key] = alias.get(p.get(key), p.get(key))
    loc = p.get("loc") or []
    if not isinstance(loc, list) or any(not isinstance(f, dict) for f in loc):
        raise PlanError("loc phải là danh sách điều kiện")
    p["loc"] = [{**f, "cot": alias.get(f.get("cot"), f.get("cot"))} for f in loc]
    p["loc"] = [{**f, "op": "="} if f.get("op") == "in" and not isinstance(f.get("gt"), list) else f for f in p["loc"]]
    # cộng cột không phải số (mã đơn, khách...) nghĩa là đếm chúng
    if p.get("phep") == "tong" and p.get("cot") in _ID_COLS:
        p["phep"] = "dem_khac"
    # đếm đối tượng theo ngưỡng tiền: ngưỡng so với tổng tiền của mỗi đối tượng
    if p.get("phep") == "dem_nhom":
        if p.get("nhom") in MONEY and p.get("cot") == "don":
            p["nhom"], p["cot"] = "don", p["nhom"]
        # đếm đơn trong mỗi đơn luôn ra 1: ngưỡng lớn là ngưỡng tiền của đơn
        if fact == "dong_ban" and p.get("nhom") == p.get("cot") == "don":
            p["cot"] = "tien"
        # ngưỡng tiền viết thành lọc từng dòng: tiền của một dòng không phải tiền của cả đối tượng
        money = [f for f in p["loc"] if f["cot"] in MONEY and f.get("op") in (">", ">=", "<", "<=")]
        if len(money) == 1 and not p.get("co_dieu_kien") and p.get("nhom") not in MONEY:
            p["co_dieu_kien"] = {"op": money[0]["op"], "gt": money[0].get("gt")}
            p["cot"] = money[0]["cot"]
            p["loc"] = [f for f in p["loc"] if f is not money[0]]
        if p.get("cot") in MONEY:
            p["do"] = "tong"
        if p.get("nhom") == "don" and not p.get("cot"):
            raise PlanError("dem_nhom theo đơn cần \"cot\": \"tien\", \"do\": \"tong\" để so ngưỡng với tiền của đơn")
    # doanh thu luôn chỉ tính đơn hợp lệ (§1), trừ khi câu lọc theo trạng thái
    if fact in HAS_VALID and p.get("phep") == "tong" and p.get("cot") in MONEY \
            and not any(f["cot"] == "trang_thai" for f in p["loc"]):
        p.pop("moi_trang_thai", None)
    # đếm đơn gồm mọi trạng thái: đơn không có dòng hàng vẫn là đơn, nên đếm trên bảng đơn
    if fact == "dong_ban" and p.get("moi_trang_thai") and p.get("phep") in ("dem", "dem_khac") and p.get("cot") in (None, "don") \
            and not p.get("nhom") and all(f["cot"] in FIELDS["don"] for f in p["loc"]):
        fact = p["nguon"] = "don"
        p["phep"], p["cot"] = "dem_khac", "don"
    # đã lọc theo trạng thái thì không áp thêm "chỉ đơn hợp lệ" (nếu không, đếm đơn huỷ luôn ra 0)
    if fact in HAS_VALID and any(f["cot"] == "trang_thai" for f in p["loc"]):
        p["moi_trang_thai"] = True
    # đếm mặt hàng khác nhau: dòng phí phục vụ... không phải mặt hàng, không đếm (§3)
    if fact == "dong_ban" and p.get("cot") == "hang" and p.get("phep") in ("dem_khac", "dem_nhom") \
            and not any(f["cot"] == "la_mat_hang" for f in p["loc"]):
        p["loc"] = p["loc"] + [{"cot": "la_mat_hang", "op": "=", "gt": True}]
    # bảng dòng bán: một đơn nhiều dòng, đếm dòng không phải đếm đơn
    if fact == "dong_ban" and p.get("phep") == "dem":
        p["phep"], p["cot"] = "dem_khac", "don"
    elif p.get("phep") == "dem" and p.get("cot") and (fact not in FIELDS or p["cot"] in FIELDS[fact]):   # đếm theo cột nào là đếm đối tượng khác nhau
        p["phep"] = "dem_khac"
    # bảng tình trạng không có ngày: kỳ nghĩa là tính đến hết kỳ đó
    if fact in AT_DATE and p.get("ky") and "ngay" not in FIELDS[fact] and not p.get("den_het"):
        p["den_het"] = p.pop("ky")
    # mã hàng đã chuẩn hoá mất đuôi tên: so đuôi trên tên gốc
    p["loc"] = [{**f, "cot": "ten_hang"} if f["cot"] == "hang" and f.get("op") == "ket_thuc" else f for f in p["loc"]]
    if p.get("phep") == "dem_nhom" and p.get("xep"):
        raise PlanError("dem_nhom trả một số, không đi với xep; muốn xếp hạng thì dùng tong / dem_khac cùng nhom và xep")
    return p
_DATE_COLS = {"ngay", "han_dung"}


class Runner:
    def __init__(self, con, today: dt.date, facts: Facts | None = None):
        self.con, self.today = con, today
        self.facts = facts or Facts(con)
        self.cache: dict = {}

    def run(self, plan: dict):
        """-> giá trị: số, chuỗi ngày, {"names": [...], "id": ...}, list, hoặc {"bang": [...]}."""
        if not isinstance(plan, dict):
            raise PlanError("kế hoạch phải là object")
        if "ghep" in plan:
            return self._combine(plan)
        return self._leaf(plan)

    def _combine(self, plan: dict):
        plan = normalize(plan)
        kind, parts = plan["ghep"], plan.get("cac") or []
        if kind not in _GHEP:
            raise PlanError(f"phép ghép lạ {kind}: \"ghep\" chỉ nhận {', '.join(_GHEP)}")
        if kind in ("dem_giao", "dem_hieu"):
            if len(parts) != 2:
                raise PlanError(f"{kind} cần đúng 2 tập đối tượng")
            a, b = self._keys(parts[0]), self._keys(parts[1])
            return len(a & b) if kind == "dem_giao" else len(a - b)
        if kind not in ("danh_sach", "dem_giao", "dem_hieu"):
            # phép tính trên số: vế xếp hạng lấy 1 đối tượng là lấy số đo của đối tượng đó (vd ngày cao nhất trừ ngày thấp nhất)
            parts = [{**p, "cot_ra": "gia_tri"} if isinstance(p, dict) and p.get("nhom") and not p.get("cot_ra")
                     and (p.get("xep") or {}).get("lay") == 1 else p for p in parts]
        if kind == "danh_sach" and len(parts) >= 2 and all(isinstance(p, dict) and p.get("nhom") and "ghep" not in p for p in parts)                 and len({p["nhom"] for p in parts}) == 1 and not any((p.get("xep") or {}).get("lay") for p in parts)                 and all(p.get("cot_ra") in (None, "ten", "ca_hai") for p in parts):
            # nhiều số đo theo cùng một đối tượng ("doanh thu và số đơn của từng nhân viên"): một bảng, mỗi số đo một cột.
            # Từng vế chạy riêng thì chỉ ra danh sách tên, mất số (không kế hoạch train nào có dạng này)
            cols = [self.run({**p, "cot_ra": "ca_hai"})["bang"] for p in parts]
            keys = {}
            for i, rows in enumerate(cols):
                for obj, v in rows:
                    k = json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)
                    keys.setdefault(k, [obj] + [None] * len(cols))[1 + i] = v
            return {"bang": list(keys.values())}
        vals = [self.run(p) for p in parts]
        if kind == "danh_sach":
            return vals[0] if len(vals) == 1 else vals
        if kind in ("tang_lien_tuc", "giam_lien_tuc"):
            if len(vals) < 2 or any(not isinstance(v, (int, float)) for v in vals):
                raise PlanError(f"{kind} cần ít nhất 2 số: mỗi phần tử trong \"cac\" là kế hoạch của MỘT kỳ, ra một số, theo thứ tự thời gian")
            return all(a < b if kind == "tang_lien_tuc" else a > b for a, b in zip(vals, vals[1:]))
        if len(vals) != 2 or any(not isinstance(v, (int, float)) for v in vals):
            raise PlanError(f"{kind} cần đúng 2 số")
        x, y = vals
        if kind == "hieu":
            return x - y
        if kind == "lon_hon":
            return x > y
        if not y:
            raise PlanError("mẫu số bằng 0")
        if kind == "ti_le":
            return round(100 * x / y, 2)
        if kind == "tang_truong":
            return round(100 * (x - y) / y, 2)
        if kind == "thuong":
            return _money(x / y) if plan.get("tien") else round(x / y, 2)
        raise PlanError(f"phép ghép lạ {kind}")

    def _raw_tables(self) -> set[str]:
        if "raw_tables" not in self.cache:
            self.cache["raw_tables"] = {t for t, in self.con.execute("SELECT table_name FROM _meta_tables").fetchall()}
        return self.cache["raw_tables"]

    def _fields(self, fact: str, table: str) -> set[str]:
        if fact in FIELDS:
            return set(FIELDS[fact])
        return {r[0] for r in self.con.execute(f'DESCRIBE "{table}"').fetchall()}

    def _raw_view(self, name: str) -> str:
        """Bảng gốc của shop; có mã đơn thì kèm ngày, tính hợp lệ, doanh thu của đơn đó."""
        view = f"_g_{name}"
        if view in self.cache:
            return view
        cols = _cols(self.con, name)
        join, extra = "", ""
        if "order_id" in cols:
            try:
                d = self.facts.table("don")
                extra = ", d.ngay AS ngay_don, d.hop_le AS hop_le, d.doanh_thu AS doanh_thu_don"
                join = f' LEFT JOIN "{d}" d ON CAST(t.order_id AS VARCHAR) = d.don'
            except NoSource:
                pass
        self.con.execute(f'CREATE OR REPLACE TEMP VIEW "{view}" AS SELECT t.*{extra} FROM "{name}" t{join}')
        self.cache[view] = True
        return view

    def _date_col(self, fact: str, cols: set[str]) -> str | None:
        try:
            r = self.con.execute("SELECT date_column FROM _meta_tables WHERE table_name = ?", [fact]).fetchone()
            if r and r[0] in cols:
                return r[0]
        except duckdb.Error:
            pass
        return "ngay_don" if "ngay_don" in cols else None

    def _raw_cond(self, cols: set[str], f: dict, table: str = "") -> str:
        col, op, val = f.get("cot"), f.get("op", "="), f.get("gt")
        if col not in cols and (alt := alias.resolve(self.con, table, col, cols)):
            col = f["cot"] = alt          # tên cột gốc (README) -> tên trong DB
        if col not in cols:
            raise PlanError(f"bảng không có cột {col}; các cột có: {', '.join(sorted(cols))[:400]}")
        c = f'"{col}"'
        if op == "thang_la":
            return f"month(TRY_CAST({c} AS DATE)) = {int(val)}"
        if op == "trong_ky":
            return _in_period(c, f, self.today, self.con)
        if op == "rong":
            return f"{c} IS NULL"
        if op == "khong_rong":
            return f"{c} IS NOT NULL"
        if op == "ket_thuc":
            return f"ends_with(trim(lower(CAST({c} AS VARCHAR))), {_q(str(val).lower())})"
        if op == "in" and isinstance(val, list) and val:
            return f"{_text_key(c)} IN (" + ", ".join(_q(fold(str(v))) for v in val) + ")"
        if op in ("=", "!=") and isinstance(val, str) and not _is_date(val):
            return f"{_text_key(c)} {op} {_q(fold(val))}"
        if op not in ("=", "!=", ">", ">=", "<", "<="):
            raise PlanError(f"op lạ {op}")
        if isinstance(val, bool):
            return f"{c} {op} {_lit(val)}"
        if isinstance(val, (int, float)):
            return f"TRY_CAST({c} AS DOUBLE) {op} {val}"
        return f"TRY_CAST({c} AS DATE) {op} {_lit(val)}"

    def _raw_source(self, plan: dict) -> tuple[str, str, list[str]]:
        fact = plan["nguon"]
        table = self._raw_view(fact)
        cols = self._fields(fact, table)
        where: list[str] = []
        if plan.get("ky"):
            c = plan.get("cot_ngay") or self._date_col(fact, cols)
            if c not in cols and (alt := alias.resolve(self.con, fact, c, cols)):
                c = plan["cot_ngay"] = alt
            if c not in cols:
                raise PlanError(f"bảng {fact} cần \"cot_ngay\" là cột ngày để lọc kỳ; các cột có: {', '.join(sorted(cols))[:400]}")
            a, b = resolve_period(plan["ky"], self.today, self.con)
            where.append(f'TRY_CAST("{c}" AS DATE) BETWEEN DATE {_q(a)} AND DATE {_q(b)}')
        for f in plan.get("loc") or []:
            where.append(self._raw_cond(cols, f, fact))
        return fact, table, where

    def _source(self, plan: dict) -> tuple[str, str, list[str]]:
        fact = plan.get("nguon")
        if fact not in FIELDS:
            if fact in self._raw_tables():
                return self._raw_source(plan)
            if real := self._raw_name(fact):
                return self._raw_source({**plan, "nguon": real})
            raise PlanError(f"nguồn lạ {fact}: \"nguon\" phải là một trong {', '.join(FIELDS)} hoặc một bảng gốc; phép ghép thì dùng \"ghep\" và \"cac\"")
        where: list[str] = []
        try:
            if fact in AT_DATE:
                at = resolve_period(plan["den_het"], self.today, self.con)[1] if plan.get("den_het") else self.today
                table = self.facts.table(fact, at=at)
                self.at = at
            elif fact in BY_RANGE:
                table = self.facts.table(fact, rng=resolve_period(plan.get("ky") or {}, self.today, self.con))
            else:
                table = self.facts.table(fact)
        except NoSource as e:
            raise MissingData(str(e)) from e
        if fact in HAS_VALID and not plan.get("moi_trang_thai"):
            where.append("hop_le")
        if plan.get("ky") and fact not in BY_RANGE:
            a, b = resolve_period(plan["ky"], self.today, self.con)
            where.append(f"ngay BETWEEN DATE {_q(a)} AND DATE {_q(b)}")
        for f in plan.get("loc") or []:
            if f.get("cot") in FIELDS[fact] and f.get("cot") != "hang":
                self._require(table, f["cot"], plan)        # shop không ghi cột đang lọc: không ra 0
            where.append(_condition(self.con, table, fact, f, self.cache, self.today))
        return fact, table, where

    def _raw_name(self, name) -> str | None:
        """Tên bảng gốc viết lệch (bỏ gạch dưới, sai hoa thường): nhận khi chỉ khớp đúng một bảng."""
        key = "".join(ch for ch in fold(str(name)) if ch.isalnum())
        hit = [t for t in self._raw_tables() if "".join(ch for ch in fold(t) if ch.isalnum()) == key]
        return hit[0] if len(hit) == 1 else None

    def _require(self, table: str, col: str, plan: dict) -> None:
        """Cột cả bảng không có giá trị thì không tính được (không trả 0)."""
        n = self.con.execute(f'SELECT COUNT("{col}") FROM "{table}"').fetchone()[0]
        if not n:
            raise MissingData(f"shop không ghi {col}")

    def _measure(self, plan: dict, fact: str, table: str, where: str) -> tuple[str, str | None]:
        op, col = plan.get("phep"), plan.get("cot")
        if op in ("tong", "tb", "min", "max", "dem_khac", "gia_duy_nhat", "chan_le"):
            fields = self._fields(fact, table)
            if col not in fields and fact not in FIELDS and (alt := alias.resolve(self.con, fact, col, fields)):
                col = plan["cot"] = alt
            if col not in fields:
                raise PlanError(f"bảng {fact} không có cột {col}; các cột có: {', '.join(sorted(fields))[:400]}")
            self._require(table, "gia_von" if col == "lai" else col, plan)
        if fact not in FIELDS and op in ("tong", "tb"):      # bảng gốc: cột số có thể đang ở dạng chữ
            return f'{_AGG[op]}(TRY_CAST("{col}" AS DOUBLE))', col
        if op in ("tong", "tb") and col != "lai":
            kind = {r[0]: str(r[1]).upper() for r in self.con.execute(f'DESCRIBE "{table}"').fetchall()}.get(col, "")
            if "CHAR" in kind or "BOOL" in kind:
                raise PlanError(f"cột {col} không phải số, không cộng / lấy trung bình được; đếm đối tượng khác nhau thì dùng \"phep\": \"dem_khac\"")
        if col == "lai":
            if not self.con.execute(f'SELECT COUNT(gia_von) FROM "{table}" WHERE {where}').fetchone()[0]:
                raise PlanError("dòng bán không ghi giá vốn")
            # có giá vốn mà thiếu số lượng: không coi giá vốn = 0 (lãi thành doanh thu)
            bad = self.con.execute(f'SELECT COUNT(*) FROM "{table}" WHERE {where} AND la_mat_hang '
                                   f'AND gia_von IS NOT NULL AND sl IS NULL').fetchone()[0]
            if bad:
                raise PlanError("dòng bán có giá vốn nhưng thiếu số lượng")
            return "SUM(COALESCE(lai, tien))", col
        if op in _AGG:
            return f'{_AGG[op]}("{col}")', col
        if op == "dem":
            return "COUNT(*)", None
        if op == "dem_khac":
            return f'COUNT(DISTINCT "{col}")', None
        raise PlanError(f"phép lạ {op}: tỉ lệ, tăng trưởng, thương, hiệu là kế hoạch ghép {{\"ghep\": ..., \"cac\": [A, B]}}")

    def _unsold(self, plan: dict):
        """Mặt hàng ế trong kỳ: đã có đơn hợp lệ trước kỳ, trong kỳ không có đơn hợp lệ nào."""
        if not plan.get("ky") or plan.get("nguon") != "dong_ban":
            raise PlanError(f"{plan.get('phep')} cần \"nguon\": \"dong_ban\" và \"ky\"")
        a, b = resolve_period(plan["ky"], self.today, self.con)
        _, table, conds = self._source({**plan, "ky": None})
        where = " AND ".join(conds + ["la_mat_hang", "hang IS NOT NULL"])
        keys = [k for k, in self.con.execute(
            f'SELECT hang FROM "{table}" WHERE {where} GROUP BY hang HAVING MIN(ngay) < DATE {_q(a)} '
            f'AND COUNT(*) FILTER (WHERE ngay BETWEEN DATE {_q(a)} AND DATE {_q(b)}) = 0 ORDER BY hang').fetchall()]
        return len(keys) if plan["phep"] == "dem_e" else [self._names("hang", k, table) for k in keys]

    def _leaf(self, plan: dict):
        plan = normalize(plan)
        if plan.get("phep") == "so_ngay":       # số ngày dương lịch của kỳ
            a, b = resolve_period(plan.get("ky") or {}, self.today, self.con)
            return (b - a).days + 1
        if plan.get("phep") in ("hang_e", "dem_e"):
            return self._unsold(plan)
        fact, table, conds = self._source(plan)
        where = " AND ".join(conds) or "TRUE"
        op = plan.get("phep")
        if op == "gia_duy_nhat":
            col = plan.get("cot")
            self._require(table, col, plan)
            vals = sorted({round(v, 2) for v, in self.con.execute(f'SELECT "{col}" FROM "{table}" WHERE {where}').fetchall()
                           if v is not None})
            if len(vals) != 1:
                raise PlanError(f"không có đúng một giá trị: {vals[:5]}")
            return _num(vals[0])
        if op == "chan_le":
            return self._split_units(plan, table, where)
        if plan.get("nhom"):
            return self._grouped(plan, fact, table, where)
        expr, col = self._measure(plan, fact, table, where)
        v = self.con.execute(f'SELECT {expr} FROM "{table}" WHERE {where}').fetchone()[0]
        return self._fmt_value(v, col, op)

    def _fmt_value(self, v, col, op):
        if isinstance(v, (dt.date, dt.datetime)):
            return v.strftime("%Y-%m-%d")
        if v is None:
            v = 0 if op in ("tong", "dem", "dem_khac", "dem_nhom") else None
            if v is None:
                raise PlanError("không có dữ liệu trong kỳ")
        if col in MONEY or col in _RAW_MONEY:
            return _money(float(v))
        if op == "tb" and col != "tien":
            return round(float(v), 2)
        return _num(float(v) if not isinstance(v, int) else v)

    def _names(self, group: str, key, table: str) -> dict:
        """Mọi cách viết của đối tượng + mã (§9 nhận mọi cách viết trong file, hoặc mã)."""
        names: list = []
        have = {r[0] for r in self.con.execute(f'DESCRIBE "{table}"').fetchall()}
        if group == "hang":
            if "ten_hang" in have:
                names += [n for n, in self.con.execute(f'SELECT DISTINCT ten_hang FROM "{table}" WHERE hang = ? '
                                                       f'AND ten_hang IS NOT NULL', [key]).fetchall()]
            names += names_by_id(self.con, "products", "product_id", "product_name", key)
        elif group == "khach":
            if "ten_khach" in have:
                names += [n for n, in self.con.execute(f'SELECT DISTINCT ten_khach FROM "{table}" WHERE khach = ? '
                                                       f'AND ten_khach IS NOT NULL', [key]).fetchall()]
            names += names_by_id(self.con, "customers", "customer_id", "customer_name", key)
        elif group in ("kenh", "thanh_toan"):
            names += [self.facts.code_labels().get(str(key))]
            names.append(key)
        elif group == "nhan_vien":
            names.append(key)
            names += names_by_id(self.con, "staff", "staff_id", "staff_name", key)
        else:
            names.append(key)
        return {"names": [n for n in names if n], "id": str(key)}

    def _grouped(self, plan: dict, fact: str, table: str, where: str):
        g = plan["nhom"]
        fields = self._fields(fact, table)
        if g not in fields and fact not in FIELDS and (alt := alias.resolve(self.con, fact, g, fields)):
            g = plan["nhom"] = alt
        if g not in fields:
            raise PlanError(f"bảng {fact} không có cột nhóm {g}; các cột có: {', '.join(sorted(fields))[:400]}")
        self._require(table, g, plan)
        base = where
        if g == "hang" and fact == "dong_ban":
            where += " AND la_mat_hang"         # §3: phí phục vụ... không phải mặt hàng, không xếp hạng
        op = plan.get("phep")
        if op == "dem_nhom":                    # đếm số đối tượng thoả điều kiện; "cot": đếm khác nhau trong mỗi đối tượng
            if plan.get("do") == "tong":        # ngưỡng trên tổng của mỗi đối tượng (vd đơn có tiền hàng từ X)
                if plan.get("cot") not in fields:
                    raise PlanError(f"bảng {fact} không có cột {plan.get('cot')}")
                expr, col = f'SUM("{plan["cot"]}")', None
            else:
                expr, col = (f'COUNT(DISTINCT "{plan["cot"]}")' if plan.get("cot") else "COUNT(*)"), None
        else:
            expr, col = self._measure(plan, fact, table, where)
        having = self._having(plan, expr, table, base)
        sql = f'SELECT "{g}" k, {expr} v FROM "{table}" WHERE {where} AND "{g}" IS NOT NULL GROUP BY 1{having}'
        if op == "dem_nhom":
            return self.con.execute(f"SELECT COUNT(*) FROM ({sql})").fetchone()[0]
        if outer := plan.get("ngoai"):          # gộp hai tầng: tổng theo từng đối tượng rồi lấy max, tổng, trung bình...
            if outer not in _OUTER:
                raise PlanError(f"\"ngoai\" lạ {outer}: chỉ nhận {', '.join(_OUTER)}")
            v = self.con.execute(f"SELECT {_OUTER[outer]}(v) FROM ({sql})").fetchone()[0]
            return self._fmt_value(v, col, outer)
        xep = plan.get("xep") or {}
        order = "v ASC" if xep.get("chieu") == "tang" else "v DESC"
        lim = xep.get("lay")
        rows = self.con.execute(f"{sql} ORDER BY {order}, k" + (f" LIMIT {int(lim)}" if lim else "")).fetchall()
        if not rows:
            raise PlanError("không có dòng nào trong kỳ")
        out = plan.get("cot_ra", "ten")

        def key_val(k):
            if isinstance(k, (dt.date, dt.datetime)):
                return k.strftime("%Y-%m-%d")
            return k if isinstance(k, (int, float)) and not isinstance(k, bool) else None
        if out == "gia_tri":
            vals = [self._fmt_value(v, col, op) for _, v in rows]
            return vals[0] if lim == 1 else vals
        if out == "ca_hai":
            return {"bang": [[self._names(g, k, table), self._fmt_value(v, col, op)] for k, v in rows]}
        items = []
        for k, _ in rows:
            kv = key_val(k)
            items.append(kv if kv is not None else (str(k) if g in ("thang", "ca") else self._names(g, k, table)))
        return items[0] if lim == 1 else items

    def _having(self, plan: dict, expr: str, table: str, where: str) -> str:
        """co_dieu_kien: một điều kiện hoặc danh sách. Mặc định so số đo của nhóm; "do" + "cot" so số đo khác của nhóm;
        "trong_ky" so ngày (vd lần đầu mua rơi vào kỳ); "phan_tram_tong" so với phần trăm của tổng cả bảng cùng điều kiện."""
        hv = plan.get("co_dieu_kien")
        if not hv:
            return ""
        parts = []
        for h in hv if isinstance(hv, list) else [hv]:
            if not isinstance(h, dict):
                raise PlanError("co_dieu_kien lạ")
            e = expr
            if h.get("do"):
                if h["do"] not in _HAVING_AGG:
                    raise PlanError(f"co_dieu_kien \"do\" lạ {h['do']}")
                fields = {r[0] for r in self.con.execute(f'DESCRIBE "{table}"').fetchall()}
                if h["do"] != "dem" and h.get("cot") not in fields:
                    raise PlanError(f"co_dieu_kien: bảng không có cột {h.get('cot')}; các cột có: {', '.join(sorted(fields))[:400]}")
                e = _HAVING_AGG[h["do"]].format(c=h.get("cot"))
            if h.get("op") == "trong_ky":
                if h.get("do") not in ("min", "max") or not h.get("cot"):
                    raise PlanError('co_dieu_kien "trong_ky" cần "do": "min" (lần đầu) hoặc "max" (lần cuối) và "cot": cột ngày')
                a, b = resolve_period(h.get("ky") or {}, self.today, self.con)
                parts.append(f"{e} BETWEEN DATE {_q(a)} AND DATE {_q(b)}")
                continue
            if h.get("op") not in ("=", "!=", ">", ">=", "<", "<="):
                raise PlanError("co_dieu_kien lạ")
            pct = h.get("phan_tram_tong")
            if pct is True and isinstance(h.get("gt"), (int, float)):     # viết {"gt": 0.05, "phan_tram_tong": true}: 5%
                pct = h["gt"] * 100 if h["gt"] <= 1 else h["gt"]
            if pct is not None:
                if isinstance(pct, bool) or not isinstance(pct, (int, float)):
                    raise PlanError('"phan_tram_tong" là số phần trăm, vd 5 nghĩa là 5% tổng')
                total = self.con.execute(f'SELECT {e} FROM "{table}" WHERE {where}').fetchone()[0] or 0
                parts.append(f"{e} {h['op']} {float(pct) * float(total) / 100}")
            else:
                parts.append(f"{e} {h['op']} {float(h['gt'])}")
        return " HAVING " + " AND ".join(parts)

    def _keys(self, plan: dict) -> set:
        """Tập đối tượng của một kế hoạch có "nhom", cho phép giao, phép hiệu giữa hai tập."""
        if not isinstance(plan, dict) or not plan.get("nhom"):
            raise PlanError("phép trên tập cần mỗi vế có \"nhom\"")
        plan = normalize(plan)
        fact, table, conds = self._source(plan)
        g = plan["nhom"]
        if g not in self._fields(fact, table):
            raise PlanError(f"bảng {fact} không có cột nhóm {g}")
        self._require(table, g, plan)           # shop không ghi cột này: không trả tập rỗng thành số 0
        where = " AND ".join(conds) or "TRUE"
        base = where
        if g == "hang" and fact == "dong_ban":
            where += " AND la_mat_hang"
        having = self._having(plan, f'COUNT(DISTINCT "{plan["cot"]}")' if plan.get("cot") else "COUNT(*)", table, base)
        return {k for k, in self.con.execute(f'SELECT "{g}" FROM "{table}" WHERE {where} AND "{g}" IS NOT NULL GROUP BY 1{having}').fetchall()}

    def _split_units(self, plan: dict, table: str, where: str):
        """Tồn theo đơn vị lớn: [số đơn vị lớn nguyên, số đơn vị cơ bản lẻ] (§5). plan['don_vi']: đơn vị câu hỏi nêu."""
        r = self.con.execute(f'SELECT ma_hang, khoa_hang, SUM("{plan.get("cot")}") FROM "{table}" WHERE {where} '
                             f'GROUP BY 1, 2').fetchall()
        if len(r) != 1 or r[0][2] is None:
            raise PlanError("cần đúng một mặt hàng")
        pid, key, q = r[0]
        conv = self.con.execute("SELECT unit, factor FROM _unit_conversions WHERE CAST(product_id AS VARCHAR) = ? OR "
                                "CAST(product_key AS VARCHAR) = ? ORDER BY factor DESC", [pid, key]).fetchall()
        want = text_key(plan.get("don_vi") or "")
        fa = next((f for u, f in conv if text_key(u) == want), conv[0][1] if conv else None)
        if not fa:
            raise MissingData("không có quy đổi")
        return [int(q // fa), int(q % fa)]


def _num(v):
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


# ---------------------------------------------------------------- định dạng §9

def to_record(qid: str, value, want: str | None = None) -> dict:
    """Giá trị -> dòng nộp. want: type kế hoạch yêu cầu (percent / number...)."""
    def name(v):
        if "names" not in v:        # vd danh_sach ghép các vế ra bảng: không có dạng đáp án §9 nào tương ứng
            raise PlanError("kết quả không định dạng được: mỗi phần tử phải là một đối tượng hoặc một giá trị, không phải bảng")
        n = ([n for n in v["names"] if n] or [v["id"]])[0]
        # đối tượng không tên cũng không mã (khoá nối hụt): không bao giờ nộp chuỗi "None" / "nan" / rỗng
        if n is None or str(n).strip().lower() in ("", "none", "nan", "null"):
            raise PlanError("kết quả có đối tượng không tên, không mã: khoá nối giữa các bảng không khớp")
        return str(n)

    def number(x):
        if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
            raise PlanError("kết quả không phải một số (NaN): phép tính chia cho 0 hoặc thiếu dữ liệu")
        return x
    if isinstance(value, float):
        number(value)
    if isinstance(value, list):
        for x in value:
            number(x)
    if isinstance(value, dict) and "bang" in value:
        rows = [[name(r[0]) if isinstance(r[0], dict) else r[0], *r[1:]] for r in value["bang"]]
        cols = ["doi_tuong"] + (["gia_tri"] if all(len(r) == 2 for r in rows) else [f"gia_tri_{i}" for i in range(1, len(rows[0]))] if rows else [])
        return {"id": qid, "type": "table", "answer": {"columns": cols, "rows": rows}}
    if isinstance(value, dict):
        return {"id": qid, "type": "string", "answer": name(value)}
    if isinstance(value, list):
        return {"id": qid, "type": "list", "answer": [name(v) if isinstance(v, dict) else v for v in value]}
    if isinstance(value, bool):
        return {"id": qid, "type": "boolean", "answer": value}
    if isinstance(value, str):
        import re
        return {"id": qid, "type": "date" if re.fullmatch(r"\d{4}-\d{2}(-\d{2})?", value) else "string", "answer": value}
    if want == "percent":
        return {"id": qid, "type": "percent", "answer": round(float(value), 2)}
    return {"id": qid, "type": "number", "answer": value}
