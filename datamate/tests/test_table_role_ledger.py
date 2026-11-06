from datamate.loader.build import table_role


def test_so_dich_vu_khong_ten_hang_la_dong_ban():
    assert table_role({"customer_name", "qty", "unit_price", "line_amount", "order_note"}) == "sales_lines"
    assert table_role({"order_date", "customer_name", "service_desc", "line_amount"}) == "sales_lines"


def test_danh_sach_khach_van_la_khach():
    assert table_role({"customer_id", "customer_name", "phone"}) == "customers"


def test_ma_thanh_toan_tren_so_don():
    assert table_role({"order_id", "payment_id", "order_date", "status"}) == "orders"
    assert table_role({"payment_id", "order_id", "payment_amount", "payment_method"}) == "payments"
