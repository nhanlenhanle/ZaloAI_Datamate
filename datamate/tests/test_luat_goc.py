"""Rulebook bộ đề đổi nghĩa luật mặc định code đang tính (luat_goc): bắt được; rulebook thật (viết lại câu chữ) không bắt nhầm."""
import os
import types

from datamate.query.luat_goc import cham, luat_doi

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
BTC = """| Luật | Mặc định |
|---|---|
| Đơn tính vào doanh thu | đơn **không huỷ** và **không trả hàng**. Đơn có trả hàng, **kể cả chỉ trả một phần**, là đơn trả hàng: bỏ **cả đơn**. Đơn đang giao vẫn tính |
| Đơn thuộc kỳ nào | theo **ngày đặt**, không theo ngày giao hay ngày thu tiền |
| Số đơn | chỉ tính đơn không huỷ, không trả |
| Doanh thu một đơn | tổng **thành tiền các dòng hàng**. **Không** trừ giảm giá trên cả đơn, **không** cộng thuế VAT, **không** gồm phí giao hàng |
| Tỉ lệ đơn huỷ trong kỳ | phần trăm đơn huỷ trong **mọi đơn đặt trong kỳ** (**mọi trạng thái**) |
| Nợ một đơn tại ngày X | phần chưa trả của **tổng đơn** (đã trừ giảm giá trên cả đơn, **gồm phí giao**) |
"""
GEN = """| Đơn tính doanh thu | đơn **không huỷ** và **không trả hàng**; đơn có trả hàng, kể cả trả một phần, bỏ **cả đơn**. Đơn đang giao vẫn tính |
| Doanh thu một đơn | tổng **thành tiền các dòng hàng** (đã trừ giảm giá dòng). **Không** trừ giảm giá trên cả đơn, **không** gồm phí giao |
| Tỉ lệ đơn huỷ | phần trăm đơn huỷ trong **mọi đơn đặt trong kỳ** (mọi trạng thái) |
| Nợ một đơn tại ngày X | **tổng phải trả** của đơn (sau giảm giá đơn, gồm phí giao) trừ các khoản đã trả |
"""


def test_khong_bat_nham():
    assert luat_doi(BTC) == {} and luat_doi(GEN) == {} and luat_doi("") == {}
    for p in ("train/train/rulebook.md",):
        f = os.path.join(ROOT, p)
        if os.path.exists(f):
            assert luat_doi(open(f, encoding="utf-8").read()) == {}, p


def test_bat_luat_doi():
    for a, b, ma in [("**Không** trừ giảm giá trên cả đơn", "**Trừ** giảm giá trên cả đơn", "doanh_thu_mot_don"),
                     ("**không** gồm phí giao hàng", "**gồm** phí giao hàng", "doanh_thu_mot_don"),
                     ("bỏ **cả đơn**", "không bỏ cả đơn, chỉ trừ phần trả", "doanh_thu_hop_le"),
                     ("theo **ngày đặt**, không theo ngày giao hay ngày thu tiền", "theo **ngày giao**", "ky_ngay_dat"),
                     ("trong **mọi đơn đặt trong kỳ** (**mọi trạng thái**)", "so với đơn hoàn thành", "ti_le_huy"),
                     ("chỉ tính đơn không huỷ, không trả", "mọi đơn không huỷ, kể cả đơn trả", "so_don")]:
        assert a in BTC
        assert ma in luat_doi(BTC.replace(a, b)), (a, b)


def test_cham_chi_bo_cau_dung_nguon_chiu_luat():
    ctx = types.SimpleNamespace(rules=BTC.replace("**Không** trừ giảm giá trên cả đơn", "**Trừ** giảm giá trên cả đơn"))
    dt = {"loai": "tra_loi", "value": 1, "plan": {"nguon": "dong_ban", "phep": "tong", "cot": "tien"}}
    nhap = {"loai": "tra_loi", "value": 1, "plan": {"nguon": "phieu_nhap", "phep": "tong", "cot": "tong_tien"}}
    sql = {"loai": "tra_loi", "value": 1, "plan": "SELECT SUM(tien) FROM v_dong_ban WHERE hop_le"}
    assert cham(ctx, dt)["loai"] == "luat_doi" and cham(ctx, sql)["loai"] == "luat_doi"
    assert cham(ctx, nhap)["loai"] == "tra_loi"
    ctx2 = types.SimpleNamespace(rules=BTC.replace("trong **mọi đơn đặt trong kỳ** (**mọi trạng thái**)", "so với đơn xong"))
    assert cham(ctx2, dt)["loai"] == "tra_loi"                # luật tỉ lệ huỷ đổi: câu doanh thu không bị bỏ
    assert cham(ctx2, {"loai": "tra_loi", "plan": {"ghep": "ti_le", "cac": [{"nguon": "don", "moi_trang_thai": True}]}})["loai"] == "luat_doi"
