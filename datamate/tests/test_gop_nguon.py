"""Gộp sổ bán nhiều nguồn: gộp nguồn bán thật (kể cả cùng đánh số đơn 1..N), không gộp sổ phụ ghi lại đơn đã có."""
import pandas as pd

from datamate.loader.build import Built, _ghi_lai_don, _union_sales_sources


def _so(tep, n, ngay0, khach, ma_dau=1, co_sl=True):
    rows = []
    for i in range(n):
        r = {"_src_file": tep, "_src_sheet": None, "order_id": str(ma_dau + i),
             "order_date": pd.Timestamp(ngay0) + pd.Timedelta(days=i % 20), "customer_name": f"{khach} {i}",
             "line_amount": 100000.0 + i}
        if co_sl:
            r["qty"] = 1
        rows.append(r)
    return pd.DataFrame(rows)


def _b(df, ten):
    return Built(ten, ten, "sales_lines", df, [{"column": c, "kind": "text"} for c in df.columns], [ten])


def test_hai_nguon_that_cung_danh_so_1_n_van_gop():
    quay = _so("quay.xlsx", 40, "2025-01-01", "Khách quầy")
    online = _so("online.xlsx", 30, "2025-02-03", "Khách online")      # cùng mã 1..30, khác ngày và khách
    assert not _ghi_lai_don(online.df if hasattr(online, "df") else online, quay)
    out = _union_sales_sources([_b(quay, "quay"), _b(online, "online")])
    ban = [b for b in out if b.role == "sales_lines"]
    assert len(ban) == 1 and len(ban[0].df) == 70


def test_so_phu_ghi_lai_don_khong_gop_ke_ca_co_so_luong():
    chinh = _so("so_ban.xlsx", 40, "2025-01-01", "Khách")
    phu = chinh.iloc[:25].copy()                                       # cùng mã, ngày, khách: sổ góp / sổ giao
    phu["_src_file"] = "so_gop.xlsx"
    assert _ghi_lai_don(phu, chinh)
    out = _union_sales_sources([_b(chinh, "so_ban"), _b(phu, "so_gop")])
    assert sorted(len(b.df) for b in out if b.role == "sales_lines") == [25, 40]     # sổ phụ giữ nguyên, không gộp


def test_so_khong_co_so_luong_khong_gop():
    chinh = _so("so_ban.xlsx", 40, "2025-01-01", "Khách")
    tra_gop = _so("so_gop.xlsx", 20, "2025-03-01", "Khách góp", co_sl=False)
    out = _union_sales_sources([_b(chinh, "so_ban"), _b(tra_gop, "so_gop")])
    assert sorted(len(b.df) for b in out if b.role == "sales_lines") == [20, 40]


def test_khong_co_ngay_lan_khach_de_so_thi_coi_la_nguon_rieng():
    a = _so("a.xlsx", 10, "2025-01-01", "K").drop(columns=["order_date", "customer_name"])
    b = _so("b.xlsx", 10, "2025-01-01", "K").drop(columns=["order_date", "customer_name"])
    assert not _ghi_lai_don(b, a)
