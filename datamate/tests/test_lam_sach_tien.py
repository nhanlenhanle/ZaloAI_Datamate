"""Làm sạch câu: tiền viết tắt, "dưới dạng bảng" tự thêm, 4B làm rơi dấu số."""
from datamate.query.normalize_all import _pre_norm_money, extract_and_mask, postprocess_and_validate


def test_tien_viet_tat():
    assert _pre_norm_money("doanh thu từ 3tr1 trở lên") == "doanh thu từ 3,1 triệu trở lên"
    assert _pre_norm_money("đơn từ 54k") == "đơn từ 54.000 đồng"
    assert _pre_norm_money("trên 2tr") == "trên 2 triệu"
    assert _pre_norm_money("trên 3tr 5 khách") == "trên 3 triệu 5 khách"     # có cách: không phải 3,5 triệu
    assert _pre_norm_money("2tr50") == "2tr50"                                # mơ hồ: để nguyên
    assert _pre_norm_money("1.5k") == "1.5k"


def test_ten_hang_da_che_khong_bi_doi():
    m, ent = extract_and_mask("Card 50k tháng 9 bán bao nhiêu, từ 3tr2?", ["Card 50k"])
    assert "Card 50k" in ent.values()
    out = _pre_norm_money(m)
    assert "3,2 triệu" in out and "50.000" not in out


def test_bang_tu_them_bi_bo():
    q, ok = postprocess_and_validate("top 3 khách mua nhiều nhất tháng 5", "Top 3 khách mua nhiều nhất tháng 5 dưới dạng bảng?", {})
    assert ok and "bảng" not in q
    q, ok = postprocess_and_validate("lập bảng top 3 khách", "Lập bảng top 3 khách dưới dạng bảng", {})
    assert "bảng" in q


def test_roi_dau_so_quay_ve_cau_dau_vao():
    q, ok = postprocess_and_validate("có mấy ngày doanh thu từ 3,1 triệu trở lên", "Có bao nhiêu ngày doanh thu từ 31 triệu trở lên?", {})
    assert not ok and q == "có mấy ngày doanh thu từ 3,1 triệu trở lên"
