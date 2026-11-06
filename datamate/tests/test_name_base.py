from datamate.loader.mapping import NameDict, _syllables, accent_clash, with_base


def test_nen_chi_bo_sung_ten_chua_gap():
    names = NameDict({"ma hang": "product_id"}, forms={"ma hang": {_syllables("Mã hàng")}, "gia": {_syllables("Giá")}})
    base = NameDict({"ma hang": "order_id", "gia": "unit_price", "trang thai": "status"},
                    forms={"trang thai": {_syllables("Trạng thái")}})
    out = with_base(names, base)
    assert out["ma hang"] == "product_id"          # tên bộ đang dựng đã có: nền không đè
    assert "gia" not in out                        # bộ đang dựng có mô tả nhưng không thống nhất: nền không quyết thay
    assert out["trang thai"] == "status"
    assert not accent_clash("Trạng thái", "trang thai", out)
    assert accent_clash("Trang thải", "trang thai", out)     # dấu khác cách viết của nền: chữ khác
    assert "trang thai" not in names               # không sửa từ điển gốc


def test_nen_trung_tu_dien_thi_khong_doi():
    d = NameDict({"ma don": "order_id"}, forms={"ma don": {_syllables("Mã đơn")}})
    assert with_base(d, d) == d and with_base(d, d).forms == d.forms
    assert with_base(NameDict(), NameDict()) == {}
