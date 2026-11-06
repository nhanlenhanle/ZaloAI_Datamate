"""Test parser với giá trị lấy nguyên từ data thật (shop ghi kèm)."""
import datetime as dt

import pytest

from datamate.loader.parsers import (
    is_walk_in, norm_status, parse_column, parse_date, parse_number, parse_number_unit,
    split_name_phone,
)


@pytest.mark.parametrize("raw, expected", [
    ("560,000", 560000),            # biz_101
    ("1,080,000", 1080000),
    ("25.000đ", 25000),             # biz_105
    ("1.039.500đ", 1039500),        # biz_117
    ("1.011.959.800đ", 1011959800),  # dev_004
    ("25,000.0000", 25000),         # biz_112
    ("2,760,000.0000", 2760000),
    ("0.0000", 0),
    ("129 000", 129000),            # dev_007
    ("1 856 000", 1856000),
    ("-49.000đ", -49000),           # biz_105 dòng đổi trả
    ("25k", 25000),
    ("1168k", 1168000),             # biz_117
    ("25000k", 25000000),           # biz_124
    ("-31k", -31000),
    ("1tr440", 1440000),            # biz_117
    ("15tr738", 15738000),          # dev_010
    ("1tr", 1000000),
    ("-1tr040", -1040000),
    ("16,56tr", 16560000),
    ("3,3225tr", 3322500),          # dev_010
    ("-1,27tr", -1270000),          # dev_004
    ("800đ", 800),
    ("10000", 10000),
    (45000.0, 45000),
    (18.6, 18.6),
    ("#VALUE!", None),              # dev_007
    ("ORD000001", None),
    ("61C-750.95", None),           # biển số xe không phải số
    ("Bàn 05", None),
])
def test_parse_number(raw, expected):
    assert parse_number(raw) == expected


def test_so_luong_kem_don_vi():
    assert parse_number_unit("3 chai") == (3, "chai")    # biz_103
    assert parse_number_unit("5 m3") == (5, "m3")        # biz_114
    assert parse_number_unit("1 đĩa") == (1, "đĩa")
    # đơn vị có số bên trong (biz_102, biz_114, biz_118)
    assert parse_number_unit("3 bao 25kg") == (3, "bao 25kg")
    assert parse_number_unit("2 hộp 30") == (2, "hộp 30")
    assert parse_number_unit("1 xe 4m3") == (1, "xe 4m3")
    assert parse_number_unit("1 cuộn 10m") == (1, "cuộn 10m")


@pytest.mark.parametrize("raw, kw, expected", [
    ("01/02/2025", {}, dt.datetime(2025, 2, 1)),
    ("19/02/2025", {}, dt.datetime(2025, 2, 19)),
    ("2025-01-01 06:03:59", {}, dt.datetime(2025, 1, 1, 6, 3, 59)),
    ("2021-08-15", {}, dt.datetime(2021, 8, 15)),
    ("1 thg 6 2025", {}, dt.datetime(2025, 6, 1)),         # biz_101
    ("24 thg 8 2026", {}, dt.datetime(2026, 8, 24)),
    ("1/1", {"default_year": 2025}, dt.datetime(2025, 1, 1)),  # biz_117, năm lấy từ sheet
    ("1/1", {}, None),                                     # không có năm thì không đoán
    (45689.0, {"allow_serial": True}, dt.datetime(2025, 2, 1)),
    (45689.0, {}, None),                                   # số thường không tự thành ngày
    (dt.date(2025, 8, 7), {}, dt.datetime(2025, 8, 7)),
    ("31/02/2025", {}, None),                              # ngày không tồn tại
])
def test_parse_date(raw, kw, expected):
    assert parse_date(raw, **kw) == expected


@pytest.mark.parametrize("raw, expected", [
    ("Đã hoàn thành", "hoan_thanh"), ("xong", "hoan_thanh"), ("đã lấy", "hoan_thanh"),
    ("Thành công", "hoan_thanh"), ("ok", "hoan_thanh"), ("completed", "hoan_thanh"),
    ("Đã giao", "hoan_thanh"),
    ("Đã hủy", "huy"), ("Đã huỷ", "huy"), ("hủy đơn", "huy"), ("khách hủy", "huy"),
    ("cancelled", "huy"), ("Không giao được", "huy"),
    ("Đã trả hàng", "tra_hang"), ("trả lại", "tra_hang"), ("Hoàn trả", "tra_hang"),
    ("Đổi trả", "tra_hang"), ("hàng trả về", "tra_hang"), ("Đã hoàn hàng", "tra_hang"),
    ("Khách trả", "tra_hang"), ("returned", "tra_hang"),
    ("Đang giao", "dang_giao"), ("Đang giao dịch", "dang_giao"), ("Đang xử lý", "dang_giao"),
    ("Chờ giao", "dang_giao"), ("đang gửi", "dang_giao"), ("đang ship", "dang_giao"),
    ("Đang vận chuyển", "dang_giao"), ("shipping", "dang_giao"),
    ("Đang hoạt động", "dang_giao"),  # cột trạng thái KHÁCH: mapping không được đưa vào đây
    ("pin yếu", None),
    # "trả" của thanh toán không phải trả hàng
    ("Đã trả tiền", None), ("Trả góp", None), ("trả trước 500k", None), ("khách trả tiền sau", None),
    ("Đã thanh toán", None),
    # phủ định không được thành "hoàn thành"
    ("Chưa hoàn thành", None), ("Không thành công", None), ("Không huỷ", None),
    # các cách ghi huỷ / trả / chờ khác
    ("Giao thất bại", "huy"), ("Khách bom hàng", "huy"), ("Hoàn tiền", "tra_hang"),
    ("khách mang trả", "tra_hang"), ("trả lại hàng", "tra_hang"), ("Chờ xác nhận", "dang_giao"),
    # nhập nhằng thật: để lớp LLM quyết
    ("Đổi hàng", None), ("Đã đặt cọc", None),
])
def test_norm_status(raw, expected):
    assert norm_status(raw) == expected


def test_trang_thai_train_khong_doi_nghia():
    """Mọi giá trị trạng thái có trong train giữ đúng mã đã kiểm bằng đáp án (tests/status_baseline_train.json)."""
    import json
    import os
    base = json.load(open(os.path.join(os.path.dirname(__file__), "status_baseline_train.json"), encoding="utf-8"))
    assert {k: norm_status(k.split("|", 1)[1]) for k in base} == base


def test_khach_le():
    for v in ["Khách lẻ", "khách lẻ", "kl", "lẻ", "KL", "Khách lẻ - 0901234567", "Khách lẻ 1",
              "Khách vãng lai (A Tú)", "KL 3", "Vãng lai"]:
        assert is_walk_in(v), v
    for v in [None, "Lê Văn Lẻ", "Chú Thanh", "Khách Lan", "Klara", "Lệ Hằng", "Lê"]:
        assert not is_walk_in(v), v


@pytest.mark.parametrize("raw, expected", [
    ("Đào Dương Giang - 0912 365 003", ("Đào Dương Giang", "0912365003")),
    ("Hồ Minh Dương (0933201672)", ("Hồ Minh Dương", "0933201672")),
    ("Tô Nam Long 0919331756", ("Tô Nam Long", "0919331756")),
    ("Triệu Linh An 0327988481", ("Triệu Linh An", "0327988481")),
    ("Nguyễn Phương An", ("Nguyễn Phương An", None)),
])
def test_ten_kem_sdt(raw, expected):
    assert split_name_phone(raw) == expected


def test_cot_ngay_tron_nhieu_dang():
    # biz_105 "Ngày giao dịch": chuỗi dd/mm/yyyy lẫn số serial Excel
    r = parse_column("Ngày giao dịch", ["01/02/2025", 45689.0, None])
    assert r["kind"] == "datetime" and r["values"][:2] == [dt.datetime(2025, 2, 1)] * 2


def test_cot_so_khong_ten_ngay_thi_khong_thanh_ngay():
    r = parse_column("Số lượng", [45689.0, 2.0, 3.0])
    assert r["kind"] == "number"


def test_dia_chi_khong_thanh_so():
    # biz_111 "Addr": từng bị hiểu thành số 452 + đơn vị "Tân Kỳ Tân"
    assert parse_number_unit("452 Tân Kỳ Tân Quý") == (None, None)
    assert parse_number_unit("40 Cách Mạng Tháng 8") == (None, None)
    r = parse_column("Addr", ["452 Tân Kỳ Tân Quý", "264 Lương Định Của", "12 lê lợi"])
    assert r["kind"] == "text"


def test_cot_sdt_giu_dang_chu():
    r = parse_column("Điện thoại", ["0932426380", "0912365003"])
    assert r["kind"] == "text" and r["values"][0] == "0932426380"


def test_cot_tien_bao_loi_o_khong_parse_duoc():
    r = parse_column("Giá vốn", ["15,044"] * 30 + ["#VALUE!"])
    # ô lỗi Excel thành None nhưng vẫn được đếm để hiện trong report
    assert r["kind"] == "number" and r["n_fail"] == 1 and r["fail_examples"] == ["#VALUE!"]


def test_ngay_khong_nam_lay_nam_cua_sheet():
    r = parse_column("Ngày lập", ["1/1", "01/01/2025", "2/1"], years=[2025, 2025, 2026])
    assert r["values"] == [dt.datetime(2025, 1, 1), dt.datetime(2025, 1, 1), dt.datetime(2026, 1, 2)]


def test_phan_tram():
    assert parse_number_unit("10%") == (10, "%")
    assert parse_number_unit("-5 %") == (-5, "%")
    assert parse_number_unit("2,5%") == (2.5, "%")
    assert parse_number_unit("abc%") == (None, None)


def test_cot_ngay_tron_hai_kieu():
    # 12/31/2025 không hợp lệ theo dd/mm -> đọc đảo; 05/06 hợp lệ cả hai -> theo kiểu chung của cột (dd/mm)
    r = parse_column("Ngày", ["31/12/2025", "12/30/2025", "05/06/2025"])
    assert r["n_fail"] == 0 and [v.month for v in r["values"]] == [12, 12, 6]
