"""Test bộ chạy kế hoạch trên shop nhỏ dựng tay: tính kỳ theo §2, luật đơn hợp lệ, thiếu dữ liệu thì không ra 0."""
import datetime as dt

import duckdb
import pandas as pd
import pytest

from datamate.query.facts import Facts
from datamate.query.compose import _ratio_unasked, _unwrap, fix_years
from datamate.query.plan import MissingData, PlanError, Runner, normalize, resolve_period, to_record

T = dt.date(2026, 3, 18)     # thứ Tư


@pytest.mark.parametrize("spec,want", [
    ({"loai": "hom_qua"}, ("2026-03-17", "2026-03-17")),
    ({"loai": "tuan_nay"}, ("2026-03-16", "2026-03-18")),
    ({"loai": "tuan_truoc"}, ("2026-03-09", "2026-03-15")),
    ({"loai": "thang_nay"}, ("2026-03-01", "2026-03-18")),
    ({"loai": "thang", "thang": 8}, ("2025-08-01", "2025-08-31")),        # tháng sau hôm nay: năm trước (§2)
    ({"loai": "thang", "thang": 2}, ("2026-02-01", "2026-02-28")),
    ({"loai": "quy", "quy": 4}, ("2025-10-01", "2025-12-31")),
    ({"loai": "n_ngay", "n": 7}, ("2026-03-12", "2026-03-18")),
    ({"loai": "tu_dau_nam"}, ("2026-01-01", "2026-03-18")),
    ({"loai": "ky_truoc", "cua": {"loai": "thang_nay"}}, ("2026-02-01", "2026-02-18")),   # cùng số ngày (§2)
    ({"loai": "ky_truoc", "cua": {"loai": "thang", "thang": 3, "nam": 2026}}, ("2026-02-01", "2026-02-28")),
    ({"loai": "cung_ky_nam_truoc", "cua": {"loai": "thang", "thang": 2, "nam": 2026}}, ("2025-02-01", "2025-02-28")),
])
def test_ky_theo_rulebook(spec, want):
    a, b = resolve_period(spec, T)
    assert (a.isoformat(), b.isoformat()) == want


def test_ky_la_bi_tu_choi():
    with pytest.raises(PlanError):
        resolve_period({"loai": "mua_xuan"}, T)


@pytest.fixture
def run():
    con = duckdb.connect()
    con.execute("""CREATE TABLE lines AS SELECT * FROM (VALUES
        ('D1', DATE '2026-03-01', 'hoan_thanh', 100000, 'hang', 'SP1', 'sp a', 'SP A', 2.0, 'K1', 'k1', 'An', FALSE, 'zalo'),
        ('D1', DATE '2026-03-01', 'hoan_thanh', 5000, 'phi_phuc_vu', NULL, 'phi', 'Phí phục vụ', 1.0, 'K1', 'k1', 'An', FALSE, 'zalo'),
        ('D2', DATE '2026-03-02', 'huy', 900000, 'hang', 'SP1', 'sp a', 'SP A', 9.0, 'K2', 'k2', 'Bình', FALSE, 'zalo'),
        ('D3', DATE '2026-03-03', 'tra_hang', 700000, 'hang', 'SP2', 'sp b', 'SP B', 7.0, 'K2', 'k2', 'Bình', FALSE, 'tai_quay'),
        ('D4', DATE '2026-03-04', 'dang_giao', 200000, 'hang', 'SP2', 'sp b', 'SP B', 4.0, NULL, NULL, 'Khách lẻ', TRUE, 'tai_quay')
        ) t(order_id, order_date, status_norm, line_amount, line_type, product_id, product_key, product_name, qty_base,
            customer_id, customer_key, customer_name, is_walk_in, channel_norm)""")
    con.execute("""CREATE TABLE _meta_tables AS SELECT 'lines' AS table_name, 'sales_lines' AS "role", 5 AS n_rows""")
    con.execute("CREATE TABLE _product_aliases (alias VARCHAR, product_name VARCHAR)")
    con.execute("CREATE TABLE _tet_periods (tet_year INT, start_date DATE, end_date DATE)")
    r = Runner(con, T, Facts(con))
    return r.run


K = {"loai": "thang", "thang": 3, "nam": 2026}


def test_doanh_thu_bo_huy_tra_giu_dang_giao_va_phi_phuc_vu(run):
    assert run({"nguon": "dong_ban", "phep": "tong", "cot": "tien", "ky": K}) == 305000


def test_so_don_va_ti_le_huy_tren_moi_don(run):
    assert run({"nguon": "dong_ban", "phep": "dem_khac", "cot": "don", "ky": K}) == 2
    h = {"nguon": "dong_ban", "phep": "dem_khac", "cot": "don", "ky": K, "moi_trang_thai": True}
    assert run({"ghep": "ti_le", "cac": [{**h, "loc": [{"cot": "trang_thai", "gt": "huy"}]}, h]}) == 25.0


def test_ban_chay_khong_tinh_phi_phuc_vu_khach_le_khong_xep_hang(run):
    top = run({"nguon": "dong_ban", "phep": "tong", "cot": "sl_co_ban", "ky": K, "nhom": "hang", "xep": {"lay": 1}})
    assert top["id"] == "SP2"
    cust = run({"nguon": "dong_ban", "phep": "tong", "cot": "tien", "ky": K, "nhom": "khach", "xep": {"lay": 5}})
    assert [c["id"] for c in cust] == ["K1"]


def test_ten_hang_khop_khong_dau_va_sai_nhe(run):
    p = {"nguon": "dong_ban", "phep": "tong", "cot": "tien", "ky": K}
    assert run({**p, "loc": [{"cot": "hang", "gt": "sp a"}]}) == 100000
    with pytest.raises(PlanError):
        run({**p, "loc": [{"cot": "hang", "gt": "hàng không có"}]})


def test_thieu_nguon_thieu_cot_thi_khong_ra_so_0(run):
    with pytest.raises(PlanError):        # shop không có phiếu nhập
        run({"nguon": "phieu_nhap", "phep": "tong", "cot": "tong_tien", "ky": K})
    with pytest.raises(PlanError):        # shop không ghi nhân viên
        run({"nguon": "dong_ban", "phep": "tong", "cot": "tien", "ky": K, "nhom": "nhan_vien", "xep": {"lay": 1}})
    with pytest.raises(PlanError):        # shop không ghi hình thức thanh toán
        run({"nguon": "dong_ban", "phep": "tong", "cot": "tien", "ky": K, "loc": [{"cot": "thanh_toan", "gt": "cod"}]})


def test_mau_so_bang_0_khong_tra_loi(run):
    n = {"nguon": "dong_ban", "phep": "tong", "cot": "tien"}
    with pytest.raises(PlanError):
        run({"ghep": "ti_le", "cac": [{**n, "ky": K}, {**n, "ky": {"loai": "thang", "thang": 1, "nam": 2020}}]})


def test_dinh_dang_theo_muc_9():
    assert to_record("q", 12.345, "percent") == {"id": "q", "type": "percent", "answer": 12.35} or \
        to_record("q", 12.345, "percent")["answer"] in (12.34, 12.35)
    assert to_record("q", 5)["type"] == "number"
    assert to_record("q", "2026-03")["type"] == "date"
    assert to_record("q", {"names": ["SP A"], "id": "SP1"}) == {"id": "q", "type": "string", "answer": "SP A"}
    assert to_record("q", [{"names": ["SP A"], "id": "SP1"}])["answer"] == ["SP A"]
    t = to_record("q", {"bang": [[{"names": ["An"], "id": "K1"}, 5000]]})
    assert t["type"] == "table" and t["answer"]["rows"] == [["An", 5000]]


def test_nam_trong_cau_thang_ke_hoach_ghi_sai_hoac_bo():
    k = lambda **a: {"ky": {"loai": "thang", "thang": 5, **a}}
    assert fix_years(k(nam=2026), "Ca sáng tháng 5/2025 doanh thu")["ky"]["nam"] == 2025
    assert fix_years(k(), "nhóm ho cảm cúm tháng 5/2025")["ky"]["nam"] == 2025
    assert fix_years(k(), "tháng 5 năm 2025")["ky"]["nam"] == 2025
    # kỳ so sánh cùng tháng năm trước vẫn giữ: đã có một kỳ đúng tháng câu nêu
    p = {"cac": [k(nam=2025), k(nam=2024)]}
    assert fix_years(p, "tháng 5/2025 so với cùng kỳ năm trước")["cac"][1]["ky"]["nam"] == 2024
    assert "nam" not in fix_years(k(), "tháng 5 doanh thu")["ky"]


def test_ke_hoach_thieu_lop_boc():
    assert _unwrap({"nguon": "don", "phep": "dem", "ra": "number"}) == {"ke_hoach": {"nguon": "don", "phep": "dem"}, "ra": "number"}
    assert _unwrap({"ke_hoach": '{"nguon": "don"}', "ra": "number"})["ke_hoach"] == {"nguon": "don"}
    assert _unwrap({"khong_co": "x"}) == {"khong_co": "x"}


def test_doanh_thu_bo_moi_trang_thai_thua(run):
    assert run({"nguon": "dong_ban", "phep": "tong", "cot": "tien", "ky": K, "moi_trang_thai": True}) == 305000


def test_dem_don_vuot_nguong_tong(run):
    p = {"nguon": "dong_ban", "phep": "dem_nhom", "nhom": "don", "cot": "tien", "do": "tong", "ky": K}
    assert run({**p, "co_dieu_kien": {"op": ">=", "gt": 105000}}) == 2
    assert run({**p, "co_dieu_kien": {"op": ">=", "gt": 200000}}) == 1


def test_hang_e_da_ban_truoc_ky_trong_ky_khong_ban(run):
    # SP A bán 01/03 (D2 huỷ không tính), SP B bán 04/03 (D3 trả không tính)
    k = {"loai": "khoang", "tu": "2026-03-02", "den": "2026-03-10"}
    assert run({"nguon": "dong_ban", "phep": "dem_e", "ky": k}) == 1
    assert run({"nguon": "dong_ban", "phep": "hang_e", "ky": k})[0]["id"] == "SP1"
    assert run({"nguon": "dong_ban", "phep": "dem_e", "ky": {"loai": "ngay", "ngay": "2026-03-01"}}) == 0


def test_thieu_du_lieu_khac_voi_ke_hoach_sai(run):
    with pytest.raises(MissingData):
        run({"nguon": "phieu_nhap", "phep": "tong", "cot": "tong_tien", "ky": K})
    with pytest.raises(PlanError) as e:
        run({"nguon": "bang_la", "phep": "tong", "cot": "tien", "ky": K})
    assert not isinstance(e.value, MissingData)


def test_ti_le_huy_mau_so_gom_moi_trang_thai(run):
    d = {"nguon": "don", "phep": "dem", "ky": K}
    assert run({"ghep": "ti_le", "cac": [{**d, "moi_trang_thai": True, "loc": [{"cot": "trang_thai", "op": "=", "gt": "huy"}]}, d]}) == 25.0


def test_thang_nay_so_thang_truoc_cung_so_ngay():
    p = normalize({"ghep": "tang_truong", "cac": [{"nguon": "don", "ky": {"loai": "thang_nay"}}, {"nguon": "don", "ky": {"loai": "thang_truoc"}}]})
    assert p["cac"][1]["ky"]["loai"] == "ky_truoc"
    assert resolve_period({"loai": "thang_truoc", "cua": {"loai": "thang", "thang": 2, "nam": 2025}}, T)[0] == dt.date(2025, 1, 1)


def test_dem_nhom_viet_lech_ve_nguong_tien(run):
    p = {"nguon": "dong_ban", "phep": "dem_nhom", "ky": K, "co_dieu_kien": {"op": ">=", "gt": 200000}}
    assert run({**p, "nhom": "doanh_thu", "cot": "don"}) == 1
    assert run({**p, "nhom": "ngay", "cot": "tien"}) == 1
    with pytest.raises(PlanError):
        run({**p, "nhom": "don"})


def test_danh_sach_mot_vanh_tra_gia_tri(run):
    assert run({"ghep": "danh_sach", "cac": [{"nguon": "don", "phep": "dem", "ky": K}]}) == 2


def test_ti_le_khi_cau_khong_hoi():
    assert _ratio_unasked({"ghep": "ti_le"}, "Doanh thu thuốc hoạt chất Paracetamol tháng 9/2025 là bao nhiêu?")
    assert _ratio_unasked({"ghep": "thuong"}, "Doanh thu thuốc hoạt chất X tháng 2/2025 là bao nhiêu?")
    assert not _ratio_unasked({"ghep": "ti_le"}, "tháng 8 tỉ lệ đơn huỷ là bn %")
    assert not _ratio_unasked({"ghep": "thuong"}, "Trung bình mỗi đơn tuần trước")


def test_danh_sach_chua_bang_khong_dinh_dang_duoc():
    with pytest.raises(PlanError):
        to_record("q", [{"bang": [[{"names": ["An"], "id": "K1"}, 5000]]}])


def test_bang_tam_khong_che_bang_that_trung_ten():
    # biz_123 có bảng thật tên phieu_nhap: bảng tạm trùng tên từng làm SQL sau đọc nhầm
    con = duckdb.connect()
    con.execute("CREATE TABLE phieu_nhap AS SELECT 'P1' AS purchase_id, DATE '2026-03-01' AS purchase_date, 500 AS purchase_total")
    con.execute("""CREATE TABLE _meta_tables AS SELECT 'phieu_nhap' AS table_name, 'purchases' AS "role", 1 AS n_rows""")
    f = Facts(con)
    name = f.table("phieu_nhap")
    assert name != "phieu_nhap"
    assert con.execute("SELECT purchase_total FROM phieu_nhap").fetchone()[0] == 500
    assert con.execute(f'SELECT tong_tien FROM "{name}"').fetchone()[0] == 500


def test_doanh_thu_la_ten_khac_cua_tien(run):
    assert run({"nguon": "dong_ban", "phep": "tong", "cot": "doanh_thu", "ky": K}) == 305000


def test_loc_trang_thai_khong_bi_luat_don_hop_le_che(run):
    assert run({"nguon": "don", "phep": "dem", "ky": K, "loc": [{"cot": "trang_thai", "op": "=", "gt": "huy"}]}) == 1


def test_dem_tren_dong_ban_la_dem_don(run):
    assert run({"nguon": "dong_ban", "phep": "dem", "ky": K}) == 2


def test_thuong_tien_tren_so_don_lam_tron_dong(run):
    n = {"nguon": "dong_ban", "ky": K}
    v = run({"ghep": "thuong", "cac": [{**n, "phep": "tong", "cot": "tien"}, {**n, "phep": "dem_khac", "cot": "don"}]})
    assert v == 152500 and isinstance(v, int)


def test_dem_nhom_kem_xep_bi_tra_lai(run):
    with pytest.raises(PlanError):
        run({"nguon": "dong_ban", "phep": "dem_nhom", "nhom": "khach", "ky": K, "xep": {"lay": 3}})


def test_tang_lien_tuc_tra_dung_sai(run):
    a = {"nguon": "dong_ban", "phep": "tong", "cot": "tien"}
    m1, m2 = {"loai": "ngay", "ngay": "2026-03-01"}, {"loai": "ngay", "ngay": "2026-03-04"}
    assert run({"ghep": "tang_lien_tuc", "cac": [{**a, "ky": m1}, {**a, "ky": m2}]}) is True
    assert run({"ghep": "giam_lien_tuc", "cac": [{**a, "ky": m1}, {**a, "ky": m2}]}) is False


def test_ti_le_dao_ve_duoc_sua_ve_phan_tren_tong(run):
    h = {"nguon": "don", "phep": "dem", "ky": K, "moi_trang_thai": True}
    assert run({"ghep": "ti_le", "cac": [h, {**h, "loc": [{"cot": "trang_thai", "op": "=", "gt": "huy"}]}]}) == 25.0


def test_ti_le_hai_ve_khac_ky_khong_bi_dao(run):
    n = {"nguon": "dong_ban", "phep": "tong", "cot": "tien"}
    a, b = {**n, "ky": {"loai": "ngay", "ngay": "2026-03-01"}}, {**n, "ky": K}
    assert run({"ghep": "ti_le", "cac": [a, b]}) == round(100 * 105000 / 305000, 2)


def test_dem_theo_cot_la_dem_doi_tuong(run):
    assert run({"nguon": "don", "phep": "dem", "cot": "don", "ky": K}) == 2


def test_ket_thuc_tren_hang_so_voi_ten_goc(run):
    assert run({"nguon": "dong_ban", "phep": "tong", "cot": "tien", "ky": K, "loc": [{"cot": "hang", "op": "ket_thuc", "gt": "A"}]}) == 100000
