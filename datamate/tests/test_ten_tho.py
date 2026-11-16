"""Tên gọi người làm -> họ tên theo danh sách nhân viên: chỉ khi khớp đúng một người và danh sách phủ đủ cột."""
import pandas as pd

from datamate.loader.build import Built, staff_full_names


def _b(role, ten, **cot):
    df = pd.DataFrame(cot)
    return Built(ten, ten, role, df, [{"column": c, "kind": "text"} for c in df.columns], [ten])


def test_doi_ten_goi_khi_khop_dung_mot_nguoi():
    ds = _b("staff", "ds", staff_name=["Ngô Minh An", "Lý Quốc Bình"])
    so = _b("orders", "so", staff_name=["A.An", "a Bình", "An", "Bình"])
    staff_full_names([ds, so])
    assert list(so.df["staff_name"]) == ["Ngô Minh An", "Lý Quốc Bình", "Ngô Minh An", "Lý Quốc Bình"]
    assert list(so.df["staff_name_goc"]) == ["A.An", "a Bình", "An", "Bình"]


def test_hai_nguoi_cung_ten_thi_khong_doi():
    ds = _b("staff", "ds", staff_name=["Ngô Minh An", "Trần Văn An", "Lý Quốc Bình"])
    so = _b("orders", "so", staff_name=["A.An", "a Bình"])
    staff_full_names([ds, so])
    assert list(so.df["staff_name"])[0] == "A.An"          # "An" khớp hai người: giữ nguyên


def test_danh_sach_khong_phu_cot_thi_giu_nguyen_ca_cot():
    ds = _b("staff", "ds", staff_name=["Ngô Minh An"])
    so = _b("orders", "so", staff_name=["A.An", "a Tú", "Hùng", "chị Mai"])   # chỉ 1/4 cách ghi có trong danh sách
    staff_full_names([ds, so])
    assert list(so.df["staff_name"]) == ["A.An", "a Tú", "Hùng", "chị Mai"]
    assert "staff_name_goc" not in so.df.columns
