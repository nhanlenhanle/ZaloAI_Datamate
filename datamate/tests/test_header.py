"""Test bước 1 bằng các lưới nhỏ mô phỏng pattern gặp trong data thật.

    python -m pytest datamate/tests -q
"""
from datamate.loader.header import classify_row, detect_header, extract_table, merge_sheets
from datamate.loader.read_files import RawSheet, fix_filename

N = None


def test_header_dong_dau():
    rows = [["Mã", "Tên", "SL"], ["A1", "Coca", 2.0]]
    assert detect_header(rows) == (0, None)


def test_header_sau_tieu_de_va_bo_loc():
    # biz_112: tiêu đề, dòng bộ lọc, dòng trống rồi mới tới header
    rows = [["SỔ CHI TIẾT BÁN HÀNG", N, N, N],
            ["Kỳ báo cáo: toàn bộ", "Kênh bán: Tất cả", N, N],
            [N, N, N, N],
            ["Ngày", "Mã đơn hàng", "Tên hàng hóa", "Số lượng"],
            ["01/04/2025", "ORD000001", "Trà đào", "1 ly"]]
    assert detect_header(rows) == (3, None)


def test_header_hai_tang():
    # biz_105: dòng nhóm thưa phía trên header thật
    rows = [["Hàng", N, N, "Tiền", N, N, "Đơn", N],
            ["Hàng", "so_luong", "Unit", "Trị giá", "Status", "Giá lẻ", "Giờ", "Mã"],
            ["Cà phê", 1.0, "ly", "25.000đ", "xong", "25k", N, "ORD1"]]
    raw = RawSheet("SoBanHang.xlsx", "Thang 02 2025", "xlsx", rows)
    t = extract_table(raw)
    assert t.columns[1] == "so_luong"
    assert t.groups["Unit"] == "Hàng" and t.groups["Giá lẻ"] == "Tiền" and t.groups["Mã"] == "Đơn"
    assert len(t.rows) == 1


def test_bang_toan_chu_khong_nham_dong_data_la_header():
    # dev_014 "Ghi tắt": mọi ô đều là chữ, header vẫn là dòng 0
    rows = [["Ghi tắt", "Tên hàng", "Loại"], ["Cáp C", "Cáp Type-C 1m", "phụ kiện"]]
    assert detect_header(rows) == (0, None)


def test_dong_tong_o_cot_bat_ky():
    header = ["Tien hang", "TongTien", "Mã bill", "Bên mua", "Ngày"]
    assert classify_row(["4,501,000", "4,566,000", N, "Cộng ngày 03/07/2026", N], header) == "summary"
    assert classify_row([N, N, N, "Tổng ngày 02/06", "7,164,500"], header) == "summary"
    assert classify_row(["TỔNG THÁNG", N, N, N, "511.837.000đ"], header) == "summary"
    assert classify_row(["31231000", "tổng 01/05", N, N, N], header) == "summary"
    assert classify_row(["Tổng cộng", N, N, N, "1.480.338.000đ"], header) == "summary"


def test_ten_hang_bat_dau_bang_tong_khong_bi_bo():
    header = ["Tên", "SL"]
    assert classify_row(["Tổng hợp vitamin C", 2.0], header) is None


def test_ghi_chu_va_header_lap_lai():
    header = ["Mã bill", "Cộng", "CK"]
    assert classify_row(["Ghi chú: số liệu ghi tay", N, N], header) == "note"
    # dev_010: cột tên "Cộng" -> dòng header lặp phải là repeat_header, không phải summary
    assert classify_row(["Mã bill", "Cộng", "CK"], header) == "repeat_header"


def test_dong_trong_o_giua_nhom_van_la_data():
    # biz_103: dòng sau của cùng đơn để trống mã đơn -> vẫn là data (forward-fill ở bước sau)
    header = ["Mã đơn", "Ngày", "Tên SP", "SL"]
    assert classify_row([N, N, "Bánh Chocopie", 3.0], header) is None


def test_gop_sheet_cung_cot_khac_thu_tu():
    a = extract_table(RawSheet("f.xlsx", "T01", "xlsx", [["A", "B"], [1.0, 2.0]]))
    b = extract_table(RawSheet("f.xlsx", "T02", "xlsx", [["B", "A"], [4.0, 3.0]]))
    c = extract_table(RawSheet("f.xlsx", "DanhMuc", "xlsx", [["X", "Y", "Z"], ["x", "y", "z"]]))
    out = merge_sheets([a, b, c])
    assert [t.name for t in out] == ["f", "f__DanhMuc"]
    assert out[0].rows == [[1.0, 2.0], [3.0, 4.0]]
    assert out[0].src == [("T01", 2), ("T02", 2)]


def test_sua_ten_file_loi_ma():
    assert fix_filename("Danh s├ích h├áng h├│a.xlsx") == "Danh sách hàng hóa.xlsx"
    assert fix_filename("Danh sách hàng hóa.xlsx") == "Danh sách hàng hóa.xlsx"
    assert fix_filename("ban_hang.csv") == "ban_hang.csv"


def test_dong_tong_khong_nhan():
    # dòng cuối chỉ có con số = tổng cột phía trên, không có chữ "Tổng": bỏ
    rows = [["Ngày", "Hàng", "SL", "Tiền"],
            ["01/01/2025", "A", 1.0, "10.000"], ["01/01/2025", "B", 2.0, "20.000"],
            ["02/01/2025", "C", 1.0, "15.000"], [N, N, 4.0, "45.000"]]
    t = extract_table(RawSheet("f.xlsx", "S", "xlsx", rows))
    assert len(t.rows) == 3 and t.dropped[0][2] == "summary_no_label"


def test_dong_cuoi_that_khong_bi_bo():
    # dòng cuối là dòng bán thật (đủ ô) hoặc số không bằng tổng: giữ
    rows = [["Ngày", "Hàng", "SL", "Tiền"],
            ["01/01/2025", "A", 1.0, "10.000"], ["01/01/2025", "B", 2.0, "20.000"],
            ["02/01/2025", "C", 1.0, "30.000"], [N, N, N, "30.000"]]
    t = extract_table(RawSheet("f.xlsx", "S", "xlsx", rows))
    assert len(t.rows) == 4


def test_csv_dau_cham_phay(tmp_path):
    from datamate.loader.read_files import read_csv
    p = tmp_path / "ban.csv"
    p.write_text("Ngày;Hàng;Tiền\n01/01/2025;Cà phê, sữa;25.000\n02/01/2025;Trà;20.000\n", encoding="utf-8")
    assert read_csv(str(p))[0].rows[1] == ["01/01/2025", "Cà phê, sữa", "25.000"]
    p.write_text("Ngày,Hàng,Tiền\n01/01/2025,\"Cà phê; sữa\",25000\n", encoding="utf-8")
    assert read_csv(str(p))[0].rows[1] == ["01/01/2025", "Cà phê; sữa", "25000"]


def test_header_co_o_nam():
    # bảng theo năm: header có ô số năm
    rows = [["Mặt hàng", "ĐVT", 2024.0, 2025.0], ["Coca", "lon", 120.0, 150.0], ["Pepsi", "lon", 80.0, 95.0]]
    t = extract_table(RawSheet("f.xlsx", "S", "xlsx", rows))
    assert t.columns == ["Mặt hàng", "ĐVT", "2024", "2025"] and len(t.rows) == 2


def test_dong_data_toan_so_khong_thanh_header():
    rows = [[2024.0, 2025.0, 2026.0], ["Coca", 1.0, 2.0]]
    assert detect_header(rows)[0] != 0
