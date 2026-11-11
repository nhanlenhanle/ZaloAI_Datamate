from datamate.loader.mapping import _NV4_NAMES as BUILTIN_NAMES, name_key, _kind_ok   # NV4 tắt mặc định: kiểm bảng riêng


def test_builtin_names_added():
    assert name_key("ĐV cơ bản") in BUILTIN_NAMES
    assert BUILTIN_NAMES[name_key("ĐV cơ bản")] == "base_unit"
    assert BUILTIN_NAMES[name_key("ĐVT cơ bản")] == "base_unit"
    assert BUILTIN_NAMES[name_key("Đơn vị cơ bản")] == "base_unit"
    assert BUILTIN_NAMES[name_key("Tổng đơn")] == "order_total"
    assert BUILTIN_NAMES[name_key("Tổng phải trả")] == "order_total"
    assert BUILTIN_NAMES[name_key("Mã HV")] == "customer_id"
    assert BUILTIN_NAMES[name_key("Mã hội viên")] == "customer_id"
    assert BUILTIN_NAMES[name_key("Thanh toán")] == "payment_method"
    assert BUILTIN_NAMES[name_key("Hình thức thanh toán")] == "payment_method"
    assert BUILTIN_NAMES[name_key("HTTT")] == "payment_method"
    assert BUILTIN_NAMES[name_key("Hình thức TT")] == "payment_method"


def test_kind_ok_payment_method():
    assert _kind_ok("payment_method", "number") is False
    assert _kind_ok("payment_method", "text") is True

