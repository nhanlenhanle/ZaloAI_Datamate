"""Dịch dạng câu của bộ mẫu regex (tests/verify_answers.parse_question) sang kế hoạch.

Hai việc: kiểm bộ chạy kế hoạch bằng đáp án train (mọi dạng đã biết phải ra đúng như SQL cũ) và tạo kho ví dụ
câu hỏi -> kế hoạch cho LLM. Không phải phần trả lời lúc thi.
"""
from __future__ import annotations

import datetime as dt
import re

from datamate.loader.parsers import fold
from datamate.tests.verify_answers import (_D, _PLAIN_WORDS, _month_end, _period, _prev_period, find_product, g5_filters,
                                           group_maps, pick_group, sales_sql, text_key)

_ORDERS_Q = r"\b(so don|(bao nhieu|bao nhiu|bnhiu|bn|may|nhieu) don|don hang)\b"
REV = {"phep": "tong", "cot": "tien"}
QTY = {"phep": "tong", "cot": "sl_co_ban"}
N_ORDERS = {"phep": "dem_khac", "cot": "don"}


def K(a, b) -> dict:
    return {"loai": "khoang", "tu": a.isoformat(), "den": b.isoformat()}


def B(**kw) -> dict:
    return {"nguon": "dong_ban", **kw}


def _gfilters(con, s, text):
    """g5_filters -> điều kiện dạng kế hoạch, giữ thứ tự trong câu; None nếu gặp dòng không phải mặt hàng."""
    out = []
    for _, label, cond in g5_filters(con, s, text):
        if cond == "FALSE":
            return None
        if m := re.match(r"ch = '(\w+)'", cond):
            out.append({"cot": "kenh", "op": "=", "gt": m[1]})
        elif m := re.match(r"pm = '(\w+)'", cond):
            out.append({"cot": "thanh_toan", "op": "=", "gt": m[1]})
        elif label.startswith("ca "):
            out.append({"cot": "ca", "op": "=", "gt": label[3:]})
        elif label.startswith("nv "):
            out.append({"cot": "nhan_vien", "op": "=", "gt": label[3:]})
        else:
            out.append({"cot": "hang", "op": "=", "gt": label})
    return out


def _tet(con, a, b):
    r = con.execute("SELECT CAST(start_date AS DATE), CAST(end_date AS DATE) FROM _tet_periods WHERE tet_year = ?",
                    [a[1]]).fetchone()
    return (r[0], min(r[1], b)) if r else None


def _rev_filter(con, lo, hi):
    (a, b), text = lo, hi
    f = fold(text)
    s = sales_sql(con)
    if s is None:
        return None
    orders = bool(re.search(_ORDERS_Q, f)) and not re.search(r"\b(doanh thu|dthu|tien)\b", f)
    meas = N_ORDERS if orders else REV
    if isinstance(a, tuple):
        r = _tet(con, a, b)
        if not r:
            return None
        a, b = r
    k = K(a, b)
    fl = _gfilters(con, s, text)
    if fl is None:
        return None
    if not fl:
        pm_ = _period(f, b)
        rest = set((f[:pm_[2].start()] + " " + f[pm_[2].end():]).split()) if pm_ else set(f.split())
        if not rest <= _PLAIN_WORDS:
            return None
        if re.search(r"\bhuy\b", f):
            h = B(phep="dem_khac", cot="don", ky=k, moi_trang_thai=True, loc=[{"cot": "trang_thai", "gt": "huy"}])
            if re.search(r"phan tram|%|\b(ti|ty) le\b", f):
                return {"ghep": "ti_le", "cac": [h, B(phep="dem_khac", cot="don", ky=k, moi_trang_thai=True)]}, "percent"
            return h, None
        return B(**meas, ky=k), None
    share = re.search(r"phan tram|%|\bchiem\b|\b(ti|ty) trong\b", f)
    same_col = len({x["cot"] for x in fl}) < len(fl)
    if len(fl) >= 2 and (same_col or re.search(r"\b(lan luot|moi loai|moi ben)\b", f)) and not share:
        return {"ghep": "danh_sach", "cac": [B(**meas, ky=k, loc=[x]) for x in fl]}, None
    p = B(**meas, ky=k, loc=fl)
    if share:
        return {"ghep": "ti_le", "cac": [p, B(**meas, ky=k)]}, "percent"
    return p, None


def _growth(con, lo, hi):
    (a, b), text = lo, hi
    f = fold(text)
    s = sales_sql(con)
    if s is None:
        return None
    orders = bool(re.search(_ORDERS_Q, f)) and not re.search(r"\b(doanh thu|dthu|tien)\b", f)
    meas = N_ORDERS if orders else REV
    if isinstance(a, tuple):
        r = _tet(con, a, b)
        if not r:
            return None
        a, b = r
    fl = _gfilters(con, s, text)
    if fl is None:
        return None
    if len(fl) >= 2 and all(x["cot"] == "ca" for x in fl[:2]):
        other = next(x for x in fl if x["gt"] != "sang")
        base = next(x for x in fl if x["gt"] == "sang")
        return {"ghep": "tang_truong", "cac": [B(**meas, ky=K(a, b), loc=[other]),
                                               B(**meas, ky=K(a, b), loc=[base])]}, "percent"
    cond = fl[:1]
    if "truoc tet" in f:
        n = (b - a).days + 1
        pa, pb = a - dt.timedelta(days=n), a - dt.timedelta(days=1)
    elif (sv := re.search(r"\bso (?:voi|vs) (.*)", f)) and (p2 := _period(sv[1], b + dt.timedelta(days=366))) \
            and not isinstance(p2[0], tuple) and (p2[0], p2[1]) != (a, b) and re.search(r"\d{4}", p2[2][0]):
        pa, pb = p2[0], p2[1]
    else:
        pa, pb = _prev_period(f, a, b)
    return {"ghep": "tang_truong", "cac": [B(**meas, ky=K(a, b), loc=cond), B(**meas, ky=K(pa, pb), loc=cond)]}, "percent"


def to_plan(con, kind: str, lo, hi):
    """-> (kế hoạch, type mong muốn) hoặc None (dạng này chưa dịch)."""
    if kind == "rev_filter":
        return _rev_filter(con, lo, hi)
    if kind == "growth":
        return _growth(con, lo, hi)
    if kind in ("revenue", "orders", "top_product", "top_customer", "cancel_count", "cancel_rate", "deliveries",
                "purchase_total"):
        k = K(lo, hi)
        if kind == "revenue":
            return B(**REV, ky=k), None
        if kind == "orders":
            return B(**N_ORDERS, ky=k), None
        if kind == "top_product":
            return B(**QTY, ky=k, nhom="hang", xep={"lay": 1}), None
        if kind == "top_customer":
            return B(**REV, ky=k, nhom="khach", xep={"lay": 1}), None
        h = {"nguon": "don", "phep": "dem", "ky": k, "moi_trang_thai": True, "loc": [{"cot": "trang_thai", "gt": "huy"}]}
        if kind == "cancel_count":
            return h, None
        if kind == "cancel_rate":
            return {"ghep": "ti_le", "cac": [h, {"nguon": "don", "phep": "dem", "ky": k, "moi_trang_thai": True}]}, "percent"
        if kind == "deliveries":
            return {"nguon": "dot_giao", "phep": "dem", "ky": k}, None
        return {"nguon": "phieu_nhap", "phep": "tong", "cot": "tong_tien", "ky": k}, None
    if kind == "cust_min_orders":
        ((a, b), n), _ = lo, hi
        c = B(phep="dem_nhom", cot="don", ky=K(a, b), nhom="khach")
        return {"ghep": "ti_le", "cac": [{**c, "co_dieu_kien": {"op": ">=", "gt": n}}, c]}, "percent"
    if kind == "best_staff":
        (a, b), _ = lo, hi
        return B(**REV, ky=K(a, b), nhom="nhan_vien", xep={"lay": 1}), None
    if kind == "best_month":
        par, _ = lo, hi
        y1, m1 = par[0]
        y2, m2 = par[-1]
        return B(**REV, ky=K(dt.date(y1, m1, 1), _month_end(y2, m2)), nhom="thang", xep={"lay": 1}), None
    if kind == "price_effect":
        (d, n), text = lo, hi
        p = find_product(con, text)
        if p is None:
            return None
        fl = [{"cot": "hang", "op": "=", "gt": p[2]}]
        return {"ghep": "tang_truong", "cac": [B(**QTY, ky=K(d, d + dt.timedelta(days=n - 1)), loc=fl),
                                               B(**QTY, ky=K(d - dt.timedelta(days=n), d - dt.timedelta(days=1)), loc=fl)]}, "percent"
    if kind in ("avg_order_value", "best_day", "group_revenue", "group_share", "group_avg_order", "group_top_product",
                "qty_sold", "price_on_day"):
        (a, b), text = lo, hi
        k = K(a, b)
        f = fold(text)
        if kind == "avg_order_value":
            return {"ghep": "thuong", "tien": True, "cac": [B(**REV, ky=k), B(**N_ORDERS, ky=k)]}, None
        if kind == "best_day":
            return B(**REV, ky=k, nhom="ngay", xep={"lay": 1}), None
        if kind.startswith("group_"):
            cust = bool(re.search(r"\bkhach\b[^.]*\bnhom\b|\bnhom khach\b", f))
            if kind == "group_top_product" and cust:
                return None
            g = pick_group(group_maps(con, cust), text)
            if g is None:
                return None
            fl = [{"cot": "nhom_khach" if cust else "nhom_hang", "op": "=", "gt": g}]
            if not cust:
                fl.append({"cot": "la_mat_hang", "op": "=", "gt": True})
            if kind == "group_revenue":
                return B(**REV, ky=k, loc=fl), None
            if kind == "group_share":
                return {"ghep": "ti_le", "cac": [B(**REV, ky=k, loc=fl), B(**REV, ky=k)]}, "percent"
            if kind == "group_avg_order":
                return {"ghep": "thuong", "tien": True, "cac": [B(**REV, ky=k, loc=fl), B(**N_ORDERS, ky=k, loc=fl)]}, None
            by_money = bool(re.search(r"\b(tien|doanh thu|dthu)\b", f))
            return B(**(REV if by_money else QTY), ky=k, loc=fl, nhom="hang", xep={"lay": 1}), None
        if kind == "price_on_day":
            m = re.search(rf"\bngay {_D}", f)
            p = find_product(con, text)
            if p is None or not m:
                return None
            d = dt.date(int(m[3]), int(m[2]), int(m[1]))
            return B(phep="gia_duy_nhat", cot="gia_1_dv", ky=K(d, d), moi_trang_thai=True,
                     loc=[{"cot": "hang", "op": "=", "gt": p[2]}]), None
        p = find_product(con, text)
        if p is not None:
            return B(**QTY, ky=k, loc=[{"cot": "hang", "op": "=", "gt": p[2]}]), None
        item = {"cot": "la_mat_hang", "op": "=", "gt": True}
        if sz := re.search(r"\bsize ([ml])\b", f):
            return B(**QTY, ky=k, loc=[item, {"cot": "ten_hang", "op": "ket_thuc", "gt": f"({sz[1]})"}]), None
        u = re.search(r"\b(?:bao nhieu|bao nhiu|bnhiu|bn|may) (\w+)", f)
        if not u:
            return None
        return B(**QTY, ky=k, loc=[item, {"cot": "don_vi_co_ban", "op": "=", "gt": u[1]}]), None
    if kind == "avg_purchase_price":
        (a, b), text = lo, hi
        p = find_product(con, text)
        if p is None:
            return None
        n = {"nguon": "dong_nhap", "ky": K(a, b), "loc": [{"cot": "hang", "op": "=", "gt": p[2]}]}
        return {"ghep": "thuong", "tien": True, "cac": [{**n, "phep": "tong", "cot": "tien"},
                                                        {**n, "phep": "tong", "cot": "sl"}]}, None
    if kind == "inventory_value":
        (x, _), _ = lo, hi
        return {"nguon": "ton", "phep": "tong", "cot": "gia_tri", "den_het": K(x, x)}, None
    if kind in ("gross_profit", "top_profit_product", "net_profit", "rx_revenue", "non_rx_revenue", "rx_rate"):
        (a, b), _ = lo, hi
        k = K(a, b)
        if kind == "gross_profit":
            return B(phep="tong", cot="lai", ky=k), None
        if kind == "top_profit_product":
            return B(phep="tong", cot="lai", ky=k, nhom="hang", xep={"lay": 1}), None
        if kind == "net_profit":
            return {"ghep": "hieu", "cac": [B(phep="tong", cot="lai", ky=k),
                                            {"nguon": "khoan_chi", "phep": "tong", "cot": "tien", "ky": k}]}, None
        rx = B(**REV, ky=k, loc=[{"cot": "ke_don", "op": "=", "gt": True}])
        if kind == "rx_revenue":
            return rx, None
        if kind == "non_rx_revenue":
            return {"ghep": "hieu", "cac": [B(**REV, ky=k), rx]}, None
        return {"ghep": "ti_le", "cac": [rx, B(**REV, ky=k)]}, "percent"
    if kind.startswith("lot_"):
        (d, until), text = lo, hi
        at = K(d, d)
        left = {"cot": "con_ton", "op": ">", "gt": 0}
        if kind == "lot_nearest":
            p = find_product(con, text)
            if p is None:
                return None
            return {"nguon": "lo_hang", "phep": "min", "cot": "han_dung", "den_het": at,
                    "loc": [{"cot": "hang", "op": "=", "gt": p[2]}, left,
                            {"cot": "han_dung", "op": ">=", "gt": d.isoformat()}]}, None
        fl = [left, {"cot": "han_dung", "op": ">=", "gt": d.isoformat()},
              {"cot": "han_dung", "op": "<=", "gt": until.isoformat()}]
        base = {"nguon": "lo_hang", "den_het": at, "loc": fl}
        if kind == "lot_value":
            return {**base, "phep": "tong", "cot": "gia_tri_con"}, None
        if kind == "lot_count":
            return {**base, "phep": "dem"}, None
        if kind == "lot_products_count":
            return {**base, "phep": "dem_khac", "cot": "hang"}, None
        return {**base, "phep": "min", "cot": "han_dung", "nhom": "hang", "xep": {"chieu": "tang"}}, None
    if kind == "stockout_count":
        (d, _), _ = lo, hi
        return {"nguon": "ton", "phep": "dem", "den_het": K(d, d), "loc": [{"cot": "ton", "op": "=", "gt": 0}]}, None
    if kind in ("stock", "stock_split"):
        p = find_product(con, hi)
        if p is None:
            return None
        base = {"nguon": "ton", "cot": "ton", "den_het": K(lo, lo), "loc": [{"cot": "hang", "op": "=", "gt": p[2]}]}
        if kind == "stock":
            return {**base, "phep": "tong"}, None
        conv = con.execute("SELECT unit FROM _unit_conversions WHERE CAST(product_id AS VARCHAR) = ? OR "
                           "CAST(product_key AS VARCHAR) = ?", [p[0], p[1]]).fetchall()
        fq = f" {text_key(hi)} ".replace(f" {p[1]} ", " ")
        u = next((x for x, in conv if f" {text_key(x)} " in fq), None)
        return {**base, "phep": "chan_le", "don_vi": u}, None
    if kind == "debt_collected":
        (a, b), _ = lo, hi
        return {"nguon": "dong_tien_no", "phep": "tong", "cot": "tra_no", "ky": K(a, b)}, None
    if kind == "debt_customer_month":
        (a, b), name = lo, hi
        fl = [{"cot": "khach", "op": "=", "gt": name}]
        return {"ghep": "danh_sach", "cac": [{"nguon": "dong_tien_no", "phep": "tong", "cot": c, "ky": K(a, b), "loc": fl}
                                             for c in ("no_them", "tra_no")]}, None
    if kind == "debt_buckets":
        n = {"nguon": "cong_no", "phep": "tong", "cot": "con_no", "den_het": K(lo, lo)}
        return {"ghep": "danh_sach", "cac": [
            {**n, "loc": [{"cot": "tuoi_no", "op": "<=", "gt": 7}]},
            {**n, "loc": [{"cot": "tuoi_no", "op": ">=", "gt": 8}, {"cot": "tuoi_no", "op": "<=", "gt": 15}]},
            {**n, "loc": [{"cot": "tuoi_no", "op": ">", "gt": 15}]}]}, None
    if kind.startswith("debt_"):
        x, n = lo, hi
        base = {"nguon": "cong_no", "den_het": K(x, x)}
        if kind == "debt_total":
            return {**base, "phep": "tong", "cot": "con_no"}, None
        if kind == "debt_aging":
            return {**base, "phep": "tong", "cot": "con_no", "loc": [{"cot": "tuoi_no", "op": ">", "gt": n}]}, None
        if kind == "debt_customers":
            return {**base, "phep": "dem_khac", "cot": "khach"}, None
        return {**base, "phep": "tong", "cot": "con_no", "nhom": "khach", "xep": {"lay": n}, "cot_ra": "ca_hai"}, None
    return None
