"""Lời giải mẫu (kế hoạch JSON của pipeline ALL_IN_ONE) cho từng câu bộ sinh tạo ra.

Khi một họ câu của qgen tính đáp án, nó gọi các hàm tính trong engine (rev, nord, top_items, debt_total...) với đúng
tham số của câu: kỳ, mặt hàng, nhóm, kênh, thanh toán, ca, nhân viên, k, ngưỡng. `ghi_vet` bọc các hàm đó để ghi lại
lời gọi ngoài cùng; `ke_hoach` ráp các lời gọi thành kế hoạch theo ngôn ngữ của datamate/query/plan.py.
Không dùng thêm số ngẫu nhiên nào, nên bật ghi vết không đổi câu hỏi / đáp án sinh ra.
"""
import datetime as D

KENH = {"store": "tai_quay", "zalo": "zalo", "facebook": "facebook", "shopee": "shopee", "grab": "grab"}
THANH_TOAN = {"cash": "tien_mat", "transfer": "chuyen_khoan", "ewallet": "vi", "cod": "cod", "debt": "ghi_no"}
CA = {"s": "sang", "c": "chieu"}
HAM = ["rev", "nord", "nord_item", "aov", "cancels", "crate", "pct", "qty", "units_of", "top_items", "items_in_n",
       "n_cust_ge", "pct_cust_ge", "top_cust", "best_day", "busy_day", "days_ge", "ord_ge", "peak_hour", "debt_total",
       "n_debtors", "top_debtors", "aged", "aged_over", "repay", "new_debt", "purch", "top_sup", "stock_at",
       "stock_value", "hike"]


class Vet:
    """Ghi lời gọi ngoài cùng tới các hàm tính của engine (lời gọi lồng bên trong không ghi)."""

    def __init__(self, E):
        self.goi, self.sau = [], 0
        for ten in HAM:
            setattr(E, ten, self._boc(ten, getattr(E, ten)))

    def _boc(self, ten, f):
        def g(*a, **k):
            if self.sau == 0:
                self.goi.append((ten, a[1:] if ten != "pct" else a, k))   # bỏ S (tham số đầu) trừ pct(a, b)
            self.sau += 1
            try:
                return f(*a, **k)
            finally:
                self.sau -= 1
        return g

    def moi(self):
        self.goi = []


def _iso(d):
    return d.isoformat() if isinstance(d, (D.date, D.datetime)) else d


def _ky(p, t):
    a, b = p
    return {"loai": "khoang", "tu": _iso(a), "den": _iso(min(b, t))}


def _den_het(X):
    return {"loai": "khoang", "tu": _iso(X), "den": _iso(X)}


def _loc(S, f):
    out = []
    for k, v in f.items():
        if k == "item":
            out.append({"cot": "hang", "op": "=", "gt": S["imap"][v]["name"]})
        elif k == "group":
            out.append({"cot": "nhom_hang", "op": "=", "gt": v})
        elif k == "chan":
            if v not in KENH:
                raise KeyError(f"kênh {v}")
            out.append({"cot": "kenh", "op": "=", "gt": KENH[v]})
        elif k == "pay":
            out.append({"cot": "thanh_toan", "op": "=", "gt": THANH_TOAN[v]})
        elif k == "cgroup":
            out.append({"cot": "nhom_khach", "op": "=", "gt": v})
        elif k == "shift":
            out.append({"cot": "ca", "op": "=", "gt": CA[v]})
        elif k == "staff":
            out.append({"cot": "nhan_vien", "op": "=", "gt": v})
        elif k == "cust":
            out.append({"cot": "khach", "op": "=", "gt": S["cmap"][v]["name"]})
        else:
            raise KeyError(f"lọc {k}")
    return out


def _ban(S, t, p, f, phep, cot, **them):
    k = {"nguon": "dong_ban", "phep": phep, "cot": cot, "ky": _ky(p, t)}
    loc = _loc(S, f)
    if loc:
        k["loc"] = loc
    k.update(them)
    return k


def _don_huy(t, p):
    return {"nguon": "don", "phep": "dem", "ky": _ky(p, t), "moi_trang_thai": True, "loc": [{"cot": "trang_thai", "gt": "huy"}]}


def _mot(S, t, ten, a, k):
    """Một lời gọi engine -> một kế hoạch lá (hoặc ghép nhỏ)."""
    if ten == "rev":
        return _ban(S, t, a[1], k, "tong", "tien")
    if ten in ("nord", "nord_item"):
        return _ban(S, t, a[1], k, "dem_khac", "don")
    if ten == "qty":
        return _ban(S, t, a[1], k, "tong", "sl_co_ban")
    if ten == "units_of":
        return {"nguon": "dong_ban", "phep": "tong", "cot": "sl_co_ban", "ky": _ky(a[1], t),
                "loc": [{"cot": "don_vi_co_ban", "op": "=", "gt": a[2]}]}
    if ten == "aov":
        return {"ghep": "thuong", "tien": True, "cac": [_ban(S, t, a[1], k, "tong", "tien"), _ban(S, t, a[1], k, "dem_khac", "don")]}
    if ten == "cancels":
        return _don_huy(t, a[1])
    if ten == "crate":
        return {"ghep": "ti_le", "cac": [_don_huy(t, a[1]), {"nguon": "don", "phep": "dem", "ky": _ky(a[1], t), "moi_trang_thai": True}]}
    if ten == "best_day":
        return _ban(S, t, a[1], {}, "tong", "tien", nhom="ngay", xep={"lay": 1})
    if ten == "busy_day":
        return _ban(S, t, a[1], {}, "dem_khac", "don", nhom="ngay", xep={"lay": 1})
    if ten == "days_ge":
        return _ban(S, t, a[1], {}, "dem_nhom", "tien", nhom="ngay", do="tong", co_dieu_kien={"op": ">=", "gt": a[2]})
    if ten == "ord_ge":
        return {"nguon": "don", "phep": "dem", "ky": _ky(a[1], t), "loc": [{"cot": "doanh_thu", "op": ">=", "gt": a[2]}]}
    if ten == "peak_hour":
        return _ban(S, t, a[1], {}, "dem_khac", "don", nhom="gio", xep={"lay": 1})
    if ten == "top_items":
        kk = a[2] if len(a) > 2 else k.pop("k", None)
        by = a[3] if len(a) > 3 else k.pop("by", "qty")
        k = {x: y for x, y in k.items() if x not in ("k", "by")}
        phep, cot = {"qty": ("tong", "sl_co_ban"), "rev": ("tong", "tien"), "ord": ("dem_khac", "don"),
                     "margin": ("tong", "lai")}[by]
        return _ban(S, t, a[1], k, phep, cot, nhom="hang", xep={"lay": kk or 1})
    if ten == "items_in_n":
        return _ban(S, t, a[1], {}, "dem_nhom", "don", nhom="hang", co_dieu_kien={"op": ">=", "gt": a[2]})
    if ten == "n_cust_ge":
        return _ban(S, t, a[1], {}, "dem_nhom", "don", nhom="khach", co_dieu_kien={"op": ">=", "gt": a[2]})
    if ten == "pct_cust_ge":
        return {"ghep": "ti_le", "cac": [_ban(S, t, a[1], {}, "dem_nhom", "don", nhom="khach", co_dieu_kien={"op": ">=", "gt": a[2]}),
                                         _ban(S, t, a[1], {}, "dem_nhom", "don", nhom="khach")]}
    if ten == "top_cust":
        by = a[2] if len(a) > 2 else k.get("by", "ord")
        kk = a[3] if len(a) > 3 else k.get("k")
        p, xep = a[1], {"lay": kk or 1}
        if by == "ord":
            return _ban(S, t, p, {}, "dem_khac", "don", nhom="khach", xep=xep)
        if by == "rev":
            return _ban(S, t, p, {}, "tong", "tien", nhom="khach", xep=xep)
        if by == "days":
            return _ban(S, t, p, {}, "dem_khac", "ngay", nhom="khach", xep=xep)
        if by == "sop":
            return {"nguon": "don", "phep": "tb", "cot": "doanh_thu", "ky": _ky(p, t), "nhom": "khach",
                    "co_dieu_kien": {"do": "dem", "op": ">=", "gt": 3}, "xep": xep}
        if by == "cancel":
            return {**_don_huy(t, p), "nhom": "khach", "xep": xep}
    if ten == "debt_total":
        return {"nguon": "cong_no", "den_het": _den_het(a[0]), "phep": "tong", "cot": "con_no"}
    if ten == "n_debtors":
        return {"nguon": "cong_no", "den_het": _den_het(a[0]), "phep": "dem_khac", "cot": "khach"}
    if ten == "top_debtors":
        return {"nguon": "cong_no", "den_het": _den_het(a[0]), "phep": "tong", "cot": "con_no", "nhom": "khach",
                "xep": {"lay": a[1]}, "cot_ra": "ca_hai"}
    if ten == "aged":
        def b(loc): return {"nguon": "cong_no", "phep": "tong", "cot": "con_no", "den_het": _den_het(a[0]), "loc": loc}
        return {"ghep": "danh_sach", "cac": [b([{"cot": "tuoi_no", "op": "<=", "gt": 7}]),
                                              b([{"cot": "tuoi_no", "op": ">", "gt": 7}, {"cot": "tuoi_no", "op": "<=", "gt": 15}]),
                                              b([{"cot": "tuoi_no", "op": ">", "gt": 15}])]}
    if ten == "aged_over":
        return {"nguon": "cong_no", "den_het": _den_het(a[0]), "phep": "tong", "cot": "con_no",
                "loc": [{"cot": "tuoi_no", "op": ">", "gt": a[1]}]}
    if ten in ("repay", "new_debt"):
        cust = a[2] if len(a) > 2 else k.get("cust")
        p = {"nguon": "dong_tien_no", "phep": "tong", "cot": "tra_no" if ten == "repay" else "no_them", "ky": _ky(a[1], t)}
        if cust:
            p["loc"] = [{"cot": "khach", "op": "=", "gt": S["cmap"][cust]["name"]}]
        return p
    if ten == "purch":
        return {"nguon": "phieu_nhap", "phep": "tong", "cot": "tong_tien", "ky": _ky(a[1], t)}
    if ten == "top_sup":
        by = a[2] if len(a) > 2 else k.get("by", "amt")
        if by == "amt":
            return {"nguon": "phieu_nhap", "phep": "tong", "cot": "tong_tien", "ky": _ky(a[1], t), "nhom": "nha_cung_cap", "xep": {"lay": 1}}
        return {"nguon": "phieu_nhap", "phep": "dem_khac", "cot": "phieu", "ky": _ky(a[1], t), "nhom": "nha_cung_cap", "xep": {"lay": 1}}
    if ten == "stock_at":
        return {"nguon": "ton", "phep": "tong", "cot": "ton", "den_het": _den_het(a[0]),
                "loc": [{"cot": "hang", "op": "=", "gt": S["imap"][a[1]]["name"]}]}
    if ten == "stock_value":
        return {"nguon": "ton", "phep": "tong", "cot": "gia_tri", "den_het": _den_het(a[0])}
    if ten == "hike":
        code, d0, n = a[1], a[2], a[3]
        def q(x, y): return _ban(S, t, (x, y), {"item": code}, "tong", "sl_co_ban")
        return {"ghep": "tang_truong", "cac": [q(d0, d0 + D.timedelta(days=n - 1)), q(d0 - D.timedelta(days=n), d0 - D.timedelta(days=1))]}
    raise KeyError(f"hàm {ten}")


def ke_hoach(ho, goi, S, t, typ):
    """-> (kế hoạch hoặc None, ghi chú). goi: các lời gọi engine ngoài cùng của câu, theo thứ tự."""
    if typ == "unanswerable":
        return None, "không trả lời được: không có phép tính"
    if ho == "table":
        return None, "bảng nhiều số đo: ngôn ngữ kế hoạch chưa có cách viết"
    if ho == "hike":
        goi = goi[-1:]                                   # các lần thử ngày tăng giá trước đó bị bỏ (Unans)
    goi = [g for g in goi if g[0] != "pct"] + ([("pct", (), {})] if any(g[0] == "pct" for g in goi) else [])
    try:
        la = [_mot(S, t, ten, a, dict(k)) for ten, a, k in goi if ten != "pct"]
    except KeyError as e:
        return None, f"chưa dịch được: {e}"
    if not la:
        return None, "không có lời gọi tính"
    if any(g[0] == "pct" for g in goi):
        return {"ghep": "tang_truong", "cac": la[-2:]}, ""
    if ho == "three":
        if typ == "list":
            return {"ghep": "danh_sach", "cac": la}, ""
        if typ == "boolean":
            return {"ghep": "tang_lien_tuc", "cac": la}, ""
        if typ == "date":
            return {**la[0], "ky": {"loai": "khoang", "tu": la[0]["ky"]["tu"], "den": la[-1]["ky"]["den"]},
                    "nhom": "thang", "xep": {"lay": 1}}, ""
    if ho == "staff" and typ == "string":
        return {**la[0], "loc": [], "nhom": "nhan_vien", "xep": {"lay": 1}}, ""
    if typ == "percent" and len(la) == 2 and ho in ("group", "chan", "cgroup"):
        return {"ghep": "ti_le", "cac": la}, ""
    if typ == "list" and len(la) >= 2:
        return {"ghep": "danh_sach", "cac": la}, ""
    if len(la) == 1:
        p = la[0]
        if typ in ("string", "date") and isinstance(p, dict) and p.get("xep"):
            return p, ""
        if typ == "list" and isinstance(p, dict) and p.get("xep"):
            return p, ""
        return p, ""
    return None, f"chưa ráp được {len(la)} lời gọi cho họ {ho}"
