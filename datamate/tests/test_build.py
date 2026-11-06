"""Test bước build: các luật rulebook §8, §10 trên bảng nhỏ mô phỏng data thật."""
import pandas as pd

from datamate.loader.build import (_conv_rows_from_text, _merged_label, add_qty_base, add_status_norm,
                                   collect_conversions, drop_dup_lines, fill_order_groups, line_type,
                                   table_role, text_key, Built, ORDER_LEVEL)
from datamate.loader.readme import ReadmeInfo, UnitConversion


def test_gop_o_dien_xuong_trong_don():
    # biz_103: dòng sau của đơn để trống mã, ngày, khách, trạng thái
    df = pd.DataFrame({"order_id": ["ORD1", None, "ORD2", None],
                       "order_date": ["2025-01-01", None, "2025-01-02", None],
                       "status": ["Huỷ", None, "Hoàn thành", None],
                       "product_name": ["A", "B", "A", "C"]})
    fill_order_groups(df, "order_id", ORDER_LEVEL)
    assert df.order_id.tolist() == ["ORD1", "ORD1", "ORD2", "ORD2"]
    assert df.status.tolist() == ["Huỷ", "Huỷ", "Hoàn thành", "Hoàn thành"]


def test_khong_dien_ma_khach_le():
    # dev_003: có mã đơn mọi dòng, mã khách trống = khách lẻ -> không lấy mã của đơn khác
    df = pd.DataFrame({"order_id": ["ORD1", "ORD2", "ORD2"], "customer_id": ["KH1", None, None]})
    fill_order_groups(df, "order_id", ORDER_LEVEL)
    assert df.customer_id.tolist() == ["KH1", None, None]


def test_dong_trong_ma_nhung_khac_ngay_la_don_moi():
    df = pd.DataFrame({"order_id": ["1", None, None], "customer_name": ["An", None, None],
                       "order_date": ["2025-01-01", "2025-01-01", "2025-01-02"]})
    fill_order_groups(df, "order_id", ORDER_LEVEL)
    assert df.customer_name.tolist()[:2] == ["An", "An"] and pd.isna(df.customer_name[2])


def test_khong_dien_tran_qua_sheet():
    df = pd.DataFrame({"_src_file": ["a.xlsx"] * 3, "_src_sheet": ["T1", "T1", "T2"],
                       "order_id": ["O9", None, None], "customer_name": ["An", None, None]})
    fill_order_groups(df, "order_id", ORDER_LEVEL)
    assert df.order_id.tolist()[:2] == ["O9", "O9"] and pd.isna(df.order_id[2])


def test_bo_dong_trung_cung_don_giu_dong_trung_khac_don():
    df = pd.DataFrame({"_src_row": [2, 3, 4, 5], "order_id": ["O1", "O1", "O2", "O2"],
                       "product_name": ["A", "A", "A", "B"], "qty": [1, 1, 1, 1]})
    # O1 có hai dòng giống hệt (lỗi xuất file); dòng A của O2 giống O1 nhưng khác đơn -> giữ
    kept, dups = drop_dup_lines(df, "order_id")
    assert kept._src_row.tolist() == [2, 4, 5] and dups._src_row.tolist() == [3]


def test_trang_thai_tu_ghi_chu_va_theo_don():
    # dev_013: không có cột trạng thái, ghi chú của đơn ghi Huỷ / chưa giao; trống = hoàn thành
    df = pd.DataFrame({"order_id": ["O1", "O1", "O2", "O3"], "order_note": [None, "Huỷ", None, "chưa giao"]})
    info = add_status_norm(df)
    assert info["status_source"] == "order_note"
    assert df.status_norm.tolist() == ["huy", "huy", "hoan_thanh", "dang_giao"]


def test_tra_mot_phan_la_don_tra():
    df = pd.DataFrame({"order_id": ["O1", "O1"], "status": ["Hoàn thành", "Trả hàng"]})
    add_status_norm(df)
    assert df.status_norm.tolist() == ["tra_hang", "tra_hang"]


def test_loai_dong():
    assert line_type("Phí phục vụ") == "phi_phuc_vu"
    assert line_type("Voucher") == "voucher"
    assert line_type("Dùng 50 điểm") == "dung_diem"
    assert line_type("Phí ship") == "phi_giao"
    assert line_type("Thép cuộn phi 6 Hòa Phát") == "hang"     # 'phi' trong tên hàng
    assert line_type("Phi lê cá basa") == "hang"
    assert line_type("Phí dịch vụ") == "phi_khac"
    for v, t in [("Giảm giá", "giam_gia"), ("Chiết khấu 5%", "giam_gia"), ("Khuyến mãi", "giam_gia"),
                 ("Thuế VAT", "thue"), ("VAT 8%", "thue"), ("Phụ thu", "phi_khac"), ("Phí đóng gói", "phi_khac"),
                 ("Ship", "phi_giao"), ("Tiền ship", "phi_giao"), ("Phí vận chuyển", "phi_giao"),
                 ("Cước giao hàng", "phi_giao")]:
        assert line_type(v) == t, v
    for v in ["Shipper bag", "Thuốc ho Bảo Thanh", "Vật tư", "Thuê xe máy", "Thuê bàn"]:
        assert line_type(v) == "hang", v


def test_khoa_ten():
    assert text_key("Thép  Cuộn Phi 6 Hòa Phát") == text_key("Thep cuon phi 6 Hoa Phat")
    assert text_key("Chị Lan - 0909") != text_key("Chị Lan - 0908")


def test_ten_bang_gop():
    assert _merged_label(["BanHang_T1_2025", "BanHang_T12_2025", "BanHang_T2_2026"]) == "BanHang"
    assert _merged_label(["BanHang_Thang01_2025", "BanHang_Thang10_2025"]) == "BanHang"
    assert _merged_label(["SoBanHang_1", "SoBanHang_2026"]) == "SoBanHang"
    assert _merged_label(["BanHang_TongHop_2025__BanHang", "BanHang_TongHop_2026"]) == "BanHang_TongHop"


def test_vai_tro_bang():
    assert table_role({"order_id", "order_date", "product_name", "qty", "line_amount"}) == "sales_lines"
    assert table_role({"order_id", "order_date", "order_total", "paid"}) == "orders"
    assert table_role({"order_id", "batch_id", "qty_base"}) == "sales_batches"
    assert table_role({"purchase_id", "product_id", "qty", "unit_price"}) == "purchase_lines"
    assert table_role({"product_name", "big_unit", "conv_factor", "base_unit"}) == "unit_conversions"
    assert table_role({"product_id", "product_name", "category", "price"}) == "products"


def test_quy_doi_dang_chu():
    assert _conv_rows_from_text("1 lốc = 4 gói; 1 thùng = 24 gói") == [("lốc", 4.0, "gói"), ("thùng", 24.0, "gói")]


def test_qty_base_tu_quy_doi():
    conv_t = Built("dsqd", "DanhSachQuyDoi", "unit_conversions",
                   pd.DataFrame({"product_name": ["Coca"], "big_unit": ["thùng"], "conv_factor": [24],
                                 "base_unit": ["lon"]}),
                   [{"column": c, "kind": k} for c, k in [("product_name", "text"), ("big_unit", "text"),
                                                         ("conv_factor", "number"), ("base_unit", "text")]], [])
    readme = ReadmeInfo("x", unit_conversions=[UnitConversion("Bia", "két", 20, "chai")])
    conv = collect_conversions([conv_t], readme)
    lines = pd.DataFrame({"product_name": ["Coca", "coca", "Bia", "Bánh"], "unit": ["thùng", "lon", "két", "cái"],
                          "qty": [2, 3, 1, 5]})
    add_qty_base(lines, conv, {}, {})
    assert lines.qty_base.tolist() == [48, 3, 20, 5]
    assert lines.qty_base_src.tolist() == ["quy_doi", "co_ban", "quy_doi", "mac_dinh"]
    # hàng có quy đổi mà đơn vị dòng lạ ("th"): không lặng lẽ coi hệ số 1
    odd = pd.DataFrame({"product_name": ["Coca"], "unit": ["th"], "qty": [2]})
    add_qty_base(odd, conv, {}, {})
    assert odd.qty_base_src.tolist() == ["khong_khop"] and pd.isna(odd.qty_base[0])
    assert lines.base_unit.tolist() == ["lon", "lon", "chai", "cái"]


def test_quy_doi_nhieu_cap():
    t = Built("q", "Q", "products", pd.DataFrame({"product_name": ["Khăn"] * 3,
                                                  "Quy đổi": ["1 thùng = 6 lốc", "1 lốc = 4 gói", "1 lốc = 4 gói"]}),
              [{"column": "product_name", "kind": "text"}, {"column": "Quy đổi", "kind": "text"}], [])
    conv = collect_conversions([t], None)
    thung = conv[conv.unit == "thùng"].iloc[0]
    assert (thung.factor, thung.base_unit) == (24, "gói")


def test_dich_vu_bien_so_nguoi_lam_bao_hanh():
    from datamate.loader.build import add_service_cols, person_key, plate_of
    assert plate_of("wave alpha 50K2-994.07") == plate_of("Wave Alpha 50K2 99407") == "50K2-99407"
    assert plate_of("Vision 59-H1 123.45") is None or plate_of("Vision 59H1-123.45") == "59H1-12345"
    assert plate_of("xe đạp") is None
    assert person_key("A.Đức") == person_key("a Đức") == person_key("anh Đức") == person_key("Nguyễn Văn Đức") == "duc"
    df = pd.DataFrame({"vehicle": ["Ex 59E1-603.87", "Vario 50F1-334.29"], "staff_name": ["a Tú", "Tú"],
                       "note": [None, "bảo hành phiếu 12/7"], "order_total": [65000, 0]})
    add_service_cols(df)
    assert df.plate.tolist() == ["59E1-60387", "50F1-33429"] and df.staff_key.tolist() == ["tu", "tu"]
    assert df.is_warranty.tolist() == [False, True]


def test_so_phieu_khong_ma_la_orders():
    assert table_role({"order_date", "order_total", "vehicle", "staff_name"}) == "orders"
    assert table_role({"staff_name", "start_date", "commission_pct"}) == "staff"
    assert table_role({"order_date", "customer_name", "debt", "paid"}) == "debts"     # sổ nợ vẫn là sổ nợ


def _b(name, role, data, kinds):
    return Built(name, name, role, pd.DataFrame(data), [{"column": c, "kind": kinds.get(c, "text")} for c in data], [])


def test_nhan_bang_ghi_tat_va_tra_ten_day_du():
    from datamate.loader.build import apply_abbreviations, collect_aliases, find_abbreviations
    sales = _b("so", "sales_lines", {"product_name": ["CL 9D", "Sạc 20W", "CL 9D", "IP15", "Phí phục vụ"],
                                    "line_type": ["hang", "hang", "hang", "hang", "phi_phuc_vu"]}, {})
    look = _b("tra", "other", {"Kí hiệu": ["CL 9D", "Sạc 20W", "IP15"],
                               "Tên": ["Kính cường lực 9D", "Củ sạc nhanh 20W", "iPhone 15 128GB"],
                               "Loại": ["phụ kiện", "phụ kiện", "máy mới"]}, {})
    ab = find_abbreviations([sales, look])
    assert ab and (ab["alias_col"], ab["full_col"], ab["group_col"]) == ("Kí hiệu", "Tên", "Loại")
    apply_abbreviations([sales, look], ab)
    assert sales.df.product_full.tolist() == ["Kính cường lực 9D", "Củ sạc nhanh 20W", "Kính cường lực 9D",
                                              "iPhone 15 128GB", "Phí phục vụ"]
    assert sales.df.category.tolist()[:4] == ["phụ kiện", "phụ kiện", "phụ kiện", "máy mới"]
    assert len(collect_aliases([sales, look], ab)) == 3


def test_khong_nhan_nham_khi_danh_muc_da_du_ten():
    from datamate.loader.build import find_abbreviations
    sales = _b("so", "sales_lines", {"product_name": ["Trà đào", "Cà phê sữa"]}, {})
    cat = _b("dm", "products", {"product_name": ["Trà đào", "Cà phê sữa"], "Mô tả dài": ["trà đào cam sả tươi",
                                                                                         "cà phê sữa đá phin"]}, {})
    assert find_abbreviations([sales, cat]) is None


def test_ten_goi_khac_vao_aliases():
    from datamate.loader.build import collect_aliases
    cat = Built("dm", "dm", "products", pd.DataFrame({"product_name": ["Sữa Similac 5G số 1 900g"],
                                                      "Tên gọi khác": ["similac 1, similac số 1"]}),
                [{"column": "product_name", "kind": "text"},
                 {"column": "Tên gọi khác", "original": "Tên gọi khác", "kind": "text"}], [])
    al = collect_aliases([cat], None)
    assert sorted(al.alias) == ["similac 1", "similac số 1"]


# ---- trạng thái cuối của đơn: lịch sử theo thời điểm, trả hàng ghi ở bảng khác ----
from datamate.loader.build import reconcile_status


def _st(rows, cols=("order_id", "product_name", "status", "updated_at")):
    df = pd.DataFrame(rows, columns=list(cols))
    if "updated_at" in df.columns:
        df["updated_at"] = pd.to_datetime(df["updated_at"], format="mixed")
    add_status_norm(df)
    return df.groupby("order_id")["status_norm"].first().to_dict()


def test_lich_su_trang_thai_lay_lan_muon_nhat():
    got = _st([
        ("A", "Xi măng", "Đang giao", "2025-01-01 08:00"),    # đang giao rồi hoàn thành -> hoàn thành
        ("A", "Xi măng", "Hoàn thành", "2025-01-03 09:00"),
        ("B", "Cát", "Hoàn thành", "2025-01-05 10:00"),       # thứ tự dòng không quan trọng
        ("B", "Cát", "Đang giao", "2025-01-04 10:00"),
        ("C", "Đá", "Đang giao", "2025-01-01"),               # đang giao rồi trả -> trả
        ("C", "Đá", "Trả hàng", "2025-01-02"),
        ("D", "Gạch", "Huỷ", "2025-01-01"),                   # huỷ là kết thúc: dòng sau ghi gì vẫn huỷ
        ("D", "Gạch", "Hoàn thành", "2025-01-02"),
    ])
    assert got == {"A": "hoan_thanh", "B": "hoan_thanh", "C": "tra_hang", "D": "huy"}


def test_mat_hang_khac_nhau_van_theo_uu_tien():
    got = _st([
        ("E", "Xi măng", "Hoàn thành", "2025-01-03"),         # giao một phần: còn hàng chưa giao -> đang giao
        ("E", "Cát", "Đang giao", "2025-01-01"),
        ("F", "Xi măng", "Hoàn thành", "2025-01-01"),         # trả một phần -> cả đơn trả (§1)
        ("F", "Cát", "Trả hàng", "2025-01-01"),
        ("G", "Xi măng", "Đang giao", "2025-01-01"),          # cùng thời điểm: không biết lần nào sau -> ưu tiên
        ("G", "Xi măng", "Hoàn thành", "2025-01-01"),
    ])
    assert got == {"E": "dang_giao", "F": "tra_hang", "G": "dang_giao"}


def test_khong_co_cot_thoi_diem_giu_uu_tien():
    got = _st([("H", "Xi măng", "Đang giao"), ("H", "Xi măng", "Hoàn thành")],
              cols=("order_id", "product_name", "status"))
    assert got == {"H": "dang_giao"}


def test_tra_hang_ghi_o_bang_khac():
    lines = Built("ct", "ct", "sales_lines", pd.DataFrame({
        "order_id": ["O1", "O2", "O3", "O4"], "product_name": ["a", "b", "c", "d"],
        "status": ["Hoàn thành", "Đã huỷ", "Hoàn thành", "Hoàn thành"]}), [], [])
    add_status_norm(lines.df)
    lot = Built("lo", "lo", "sales_batches", pd.DataFrame({
        "order_id": ["O1", "O2", "O3"], "batch_id": ["L1", "L2", "L3"],
        "qty_returned_base": [2, 1, 0]}), [], [])
    ret = Built("tra", "tra", "other", pd.DataFrame({"return_id": ["PT1"], "order_id": ["O4"]}), [], [])
    nhap = Built("nh", "nh", "purchase_lines", pd.DataFrame({          # trả NCC: không liên quan đơn bán
        "purchase_id": ["PN1"], "order_id": ["O3"], "qty_returned": [5]}), [], [])
    st = reconcile_status([lines, lot, ret, nhap])
    assert lines.df["status_norm"].tolist() == ["tra_hang", "huy", "hoan_thanh", "tra_hang"]
    assert st["orders_returned_elsewhere"] == 2


def test_bang_don_va_bang_dong_ghi_khac_nhau():
    orders = Built("hd", "hd", "orders", pd.DataFrame({"order_id": ["O1", "O2"], "status": ["Đã huỷ", "Hoàn thành"],
                                                      "order_total": [1, 2]}), [], [])
    lines = Built("ct", "ct", "sales_lines", pd.DataFrame({"order_id": ["O1", "O2", "O2"], "product_name": ["a", "b", "c"],
                                                          "status": ["Hoàn thành", "Hoàn thành", "Trả hàng"]}), [], [])
    for b in (orders, lines):
        add_status_norm(b.df)
    reconcile_status([orders, lines])
    assert orders.df["status_norm"].tolist() == ["huy", "tra_hang"]
    assert lines.df["status_norm"].tolist() == ["huy", "tra_hang", "tra_hang"]


def test_tach_so_dien_thoai_khoi_ten_khach():
    from datamate.loader.build import add_customer_cols, add_phone_cols, split_phone
    assert split_phone("Trần Châu Huy (0919220158)") == ("Trần Châu Huy", "0919220158")
    assert split_phone("Lê Hải Hà - 0327 210 166") == ("Lê Hải Hà", "0327210166")
    assert split_phone("0901.234.567 - Chị Lan") == ("Chị Lan", "0901234567")
    assert split_phone("Anh Ba +84 912 345 678") == ("Anh Ba", "0912345678")
    assert split_phone("Cửa hàng 123") == ("Cửa hàng 123", None)        # không phải SĐT
    df = pd.DataFrame({"customer_name": ["Vương Anh Huy 0915778868", "Vương Anh Huy 0988000111", "Lan"]})
    add_customer_cols(df)
    assert add_phone_cols(df) == 2
    assert df["customer_name_clean"].tolist() == ["Vương Anh Huy", "Vương Anh Huy", "Lan"]
    # khoá khách vẫn theo tên đầy đủ: cùng tên khác số là hai khách (rulebook §3)
    assert df["customer_key"].nunique() == 3


def test_co_dong_muon_nhat_chi_o_bang_lich_su():
    df = pd.DataFrame([
        ("A", "Xi măng", "Đang giao", "2025-01-01 08:00"),    # lịch sử: chỉ dòng sau là dòng thật
        ("A", "Xi măng", "Hoàn thành", "2025-01-03 09:00"),
        ("A", "Cát", "Hoàn thành", "2025-01-01 08:00"),
        ("B", "Cà phê", "Hoàn thành", "2025-01-01 08:00"),    # gọi thêm cùng món: hai lần bán thật
        ("B", "Cà phê", "Hoàn thành", "2025-01-01 09:00"),
        ("C", "Đá", "Đang giao", "2025-01-02"),               # cùng thời điểm: không biết lần nào sau -> giữ cả
        ("C", "Đá", "Hoàn thành", "2025-01-02"),
    ], columns=["order_id", "product_name", "status", "updated_at"])
    df["updated_at"] = pd.to_datetime(df["updated_at"], format="mixed")
    info = add_status_norm(df)
    assert df["is_latest_row"].tolist() == [False, True, True, True, True, True, True]
    assert info["history_rows"] == 1


def test_khong_co_lich_su_thi_khong_them_cot():
    df = pd.DataFrame({"order_id": ["A", "A"], "product_name": ["x", "y"], "status": ["Hoàn thành", "Đã huỷ"],
                       "updated_at": pd.to_datetime(["2025-01-01", "2025-01-02"])})
    add_status_norm(df)
    assert "is_latest_row" not in df.columns


def test_ma_chung_thanh_toan_va_kenh():
    from datamate.loader.build import add_code_norms
    df = pd.DataFrame({"payment_method": ["cash", "Tiền mặt", "TM", "transfer", "CK", "Ví điện tử", "ewallet", "MoMo",
                                          "cod", "Thu hộ (COD)", "Ghi nợ", "debt", "Quẹt thẻ", None],
                       "channel": ["store", "Tại quầy", "zalo_oa", "Zalo OA", "phone", "Điện thoại", "Shopee",
                                   "GrabFood", "Website", "Facebook", "lạ", "Tại quán", "TikTok Shop", None]})
    add_code_norms(df)
    assert df["payment_norm"].tolist() == ["tien_mat", "tien_mat", "tien_mat", "chuyen_khoan", "chuyen_khoan", "vi",
                                           "vi", "vi", "cod", "cod", "ghi_no", "ghi_no", "the", None]
    assert df["channel_norm"].tolist() == ["tai_quay", "tai_quay", "zalo", "zalo", "dien_thoai", "dien_thoai",
                                           "shopee", "grab", "website", "facebook", "khac", "tai_quay", "tiktok", None]


def test_so_trung_coi_o_trong_dong_sau_nhu_dong_dau():
    # §8: mã cửa hàng (cột luật chưa biết) chỉ ghi ở dòng đầu đơn; dòng 2 trùng dòng 1 vẫn là dòng trùng
    df = pd.DataFrame({"order_id": ["1", "1", "1"], "IDCuaHang": ["CH1", None, None],
                       "product_name": ["A", "A", "B"], "qty": [1, 1, 1], "line_amount": [10, 10, 5]})
    out, dups = drop_dup_lines(df, "order_id")
    assert len(out) == 2 and out.IDCuaHang.tolist() == ["CH1", None]      # không ghi đè dữ liệu
    # cột cấp dòng không điền: số lượng trống là khác
    df = pd.DataFrame({"order_id": ["1", "1"], "product_name": ["A", "A"], "qty": [1, None]})
    assert len(drop_dup_lines(df, "order_id")[0]) == 2
