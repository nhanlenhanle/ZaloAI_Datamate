from datamate.query.telex import giai_telex, sua_cau, sua_q


def test_giai_loi_go_telex():
    assert sua_cau("doanh thu thangs 5 tawng/giamr mấy %") == "doanh thu tháng 5 tăng/giảm mấy %"
    assert sua_cau("mặt hàng naof bán chạy, soos ddown hoom nay") == "mặt hàng nào bán chạy, số đơn hôm nay"
    assert sua_cau("tháng này cos bao nhiêu đơn as") == "tháng này có bao nhiêu đơn á"
    assert sua_cau("cuwar hàng nhập từ nhaf cung cấp nào") == "cửa hàng nhập từ nhà cung cấp nào"


def test_khong_doi_cau_khong_dau_ten_rieng_tieng_anh():
    s = "thang 4 co bao nhieu don Panasonic Wide, COD, iphones, Cat6, gas, items"
    assert sua_cau(s) == s
    assert giai_telex("Air") == "Air"
    assert giai_telex("ee") == "ee"


def test_sua_q_giu_cau_goc():
    q = {"id": "x", "question": "bans dc bao nhieu", "as_of_date": "2026-01-01"}
    r = sua_q(q)
    assert r["question"] == "bán dc bao nhieu" and r["goc_telex"] == q["question"]
    same = {"id": "y", "question": "ban dc bao nhieu", "as_of_date": "2026-01-01"}
    assert sua_q(same) is same
