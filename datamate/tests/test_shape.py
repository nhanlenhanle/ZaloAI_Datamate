from datamate.query.compose import shape


def _t(rows):
    return {"id": "q", "type": "table", "answer": {"columns": ["doi_tuong", "gia_tri"], "rows": rows}}


def _q(text, today="2026-10-01"):
    return {"question": text, "as_of_date": today}


def test_lan_luot_cac_thang_theo_thu_tu_cau_hoi():
    rec = _t([["2026-02", 10], ["2026-03", 20], ["2026-04", 30]])
    q = _q("Cho xin doanh thu từng th 2-2026, tháng 4/2026, tháng 3 năm 2026 theo đúng thứ tự.")
    assert shape(q, rec) == {"id": "q", "type": "list", "answer": [10, 30, 20]}


def test_lan_luot_thieu_thang_thi_giu_nguyen():
    rec = _t([["2026-02", 10], ["2026-03", 20]])
    assert shape(_q("Doanh thu tháng 2/2026, 3/2026, 4/2026 lần lượt bao nhiêu?"), rec) is rec


def test_top_k_ra_danh_sach_ten():
    rec = _t([["An", 5], ["Bình", 3], ["Chi", 1]])
    assert shape(_q("Top 3 khách chi nhiều tiền nhất 07/2025?"), rec) == {"id": "q", "type": "list", "answer": ["An", "Bình", "Chi"]}
    assert shape(_q("top 1 khách chi nhiều tiền nhất?"), _t([["An", 5]]))["type"] == "string"


def test_cau_doi_bang_hoac_kem_so_do_giu_bang():
    rec = _t([["An", 5], ["Bình", 3]])
    assert shape(_q("Lập bảng top 2 khách chi nhiều nhất"), rec) is rec
    assert shape(_q("Top 2 khách kèm số tiền chi"), rec) is rec
    assert shape(_q("Doanh thu theo kênh tháng 5"), rec) is rec
    lst = {"id": "q", "type": "list", "answer": ["An"]}
    assert shape(_q("Top 3 khách?"), lst) is lst
