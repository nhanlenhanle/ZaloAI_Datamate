"""Sổ lạ từ bộ tự sinh gen_hl: cột thời gian tên CamelCase / gạch dưới trộn serial Excel có giờ."""
import datetime as dt

from datamate.loader.parsers import parse_column, parse_date

TRON = ["45916.809722", "2026-07-03 09:16:00", "01/05/2026 16:31", "46113.685417", "13/08/2025 16:07"] * 4


def test_serial_co_gio_dang_chu():
    d = parse_date("45916.809722", allow_serial=True)
    assert d.date() == dt.date(2025, 9, 16) and (d.hour, d.minute) == (19, 26)
    assert parse_date("45916.809722") is None                          # không gợi ý ngày thì không nhận số


def test_ten_cot_camel_va_gach_duoi_goi_y_ngay():
    for name in ("ThoiGian", "thoi_gian", "Thời gian"):
        assert parse_column(name, TRON)["kind"] == "datetime", name
    assert parse_column("MaSo", ["45916.809722"] * 5)["kind"] == "number"


def test_quy_doi_dang_gon_lay_don_vi_co_ban_cung_dong():
    from datamate.loader.build import _conv_rows_from_text
    assert _conv_rows_from_text("bao=25", "kg") == [("bao", 25.0, "kg")]
    assert _conv_rows_from_text("cặp=2;đàn=10", "con") == [("cặp", 2.0, "con"), ("đàn", 10.0, "con")]
    assert _conv_rows_from_text("1 thùng = 4 lốc; 1 lốc = 6 lon", "lon") == [("thùng", 4.0, "lốc"), ("lốc", 6.0, "lon")]
    assert _conv_rows_from_text("bao=25") == []                        # không biết đơn vị cơ bản thì không đoán


def test_nhom_trong_danh_muc_hang_la_nhom_hang():
    from datamate.loader.mapping import ColumnMap, _resolve_context
    def m(col, canon):
        return ColumnMap(table="danhmuc", column=col, canonical=canon, source="name_dict", description=None, note=None)
    maps = [m("Mã hàng", "product_id"), m("Tên hàng", "product_name"), m("Nhóm", "customer_group")]
    _resolve_context(maps)
    assert maps[2].canonical == "category"
    maps = [m("Mã KH", "customer_id"), m("Tên khách", "customer_name"), m("Nhóm", "customer_group")]
    _resolve_context(maps)
    assert maps[2].canonical == "customer_group"
