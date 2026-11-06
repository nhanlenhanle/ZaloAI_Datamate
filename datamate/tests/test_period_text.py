import datetime as dt

from datamate.query.compose import period_text
from datamate.query.sql_tier import _asked_periods, periods

TODAY = dt.date(2026, 5, 16)


def _labels(q):
    return [p[0] for p in _asked_periods(q, TODAY)]


def test_nam_hai_chu_so():
    assert "th11/2025" in period_text("doanh thu th11/25")
    assert "1/2026" in period_text("th1/26 ban bao nhieu")
    assert "7-2025" in period_text("dthu 7-25")
    assert period_text("ngay 5/3/25") == "ngay 5/3/25"            # ngày đủ: không đổi
    assert period_text("thang 12/2025") == "thang 12/2025"        # năm 4 chữ số: không đổi
    assert period_text("ngay 25/12") == "ngay 25/12"              # ngày / tháng không năm


def test_nhieu_thang_nam_hai_chu_so():
    q = "trong th11/25, tháng 12/2025, th1/26, tháng nào dthu cao nhất?"
    assert _labels(q) == ["tháng 11/2025", "tháng 12/2025", "tháng 1/2026"]


def test_quy_viet_tat_khong_thanh_thang():
    assert _labels("Q2/2025 doanh thu bao nhiêu") == ["quý 2/2025"]
    assert _labels("doanh thu q3/25") == ["quý 3/2025"]
    assert _labels("doanh thu quý 2/2025") == ["quý 2/2025"]
    assert "tháng 2/2025" not in periods(TODAY, "Q2/2025 doanh thu")
