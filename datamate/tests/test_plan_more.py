"""Phần mở rộng ngôn ngữ kế hoạch (bảng gốc, điều kiện hai tầng, gộp hai tầng, phép trên tập) và các chốt theo câu hỏi."""
import datetime as dt
import types

import duckdb
import pytest

from datamate.query.compose import _attempt, _mismatch, _unwrap, clean_plan, naturalize, raw_catalog
from datamate.query.facts import Facts
from datamate.query.plan import MissingData, PlanError, Runner, normalize, resolve_period

T = dt.date(2026, 3, 18)
K = {"loai": "thang", "thang": 3, "nam": 2026}
K2 = {"loai": "thang", "thang": 2, "nam": 2026}


@pytest.fixture
def run():
    return Runner(_db(), T, None).run


def _db():
    con = duckdb.connect()
    con.execute("""CREATE TABLE lines AS SELECT * FROM (VALUES
        ('D0', DATE '2026-02-10', 'hoan_thanh', 50000, 'hang', 'SP1', 'sp a', 'SP A', 1.0, 'K1', 'k1', 'An', FALSE, 'zalo'),
        ('D1', DATE '2026-03-01', 'hoan_thanh', 100000, 'hang', 'SP1', 'sp a', 'SP A', 2.0, 'K1', 'k1', 'An', FALSE, 'zalo'),
        ('D1', DATE '2026-03-01', 'hoan_thanh', 300000, 'hang', 'SP3', 'sp c', 'SP C', 1.0, 'K1', 'k1', 'An', FALSE, 'zalo'),
        ('D2', DATE '2026-03-02', 'huy', 900000, 'hang', 'SP1', 'sp a', 'SP A', 9.0, 'K2', 'k2', 'Bình', FALSE, 'zalo'),
        ('D3', DATE '2026-03-03', 'hoan_thanh', 200000, 'hang', 'SP2', 'sp b', 'SP B', 4.0, 'K3', 'k3', 'Cúc', FALSE, 'tai_quay')
        ) t(order_id, order_date, status_norm, line_amount, line_type, product_id, product_key, product_name, qty_base,
            customer_id, customer_key, customer_name, is_walk_in, channel_norm)""")
    con.execute("""CREATE TABLE giao AS SELECT * FROM (VALUES ('Ông Hương', DATE '2026-03-05'), ('Ông Hương', DATE '2026-03-06'),
        ('Châu Giang', DATE '2026-03-07'), ('Châu Giang', DATE '2026-02-07')) t(driver, delivery_date)""")
    con.execute("""CREATE TABLE ban AS SELECT * FROM (VALUES ('D1', 'Sân vườn', 4), ('D2', 'Sân vườn', 9), ('D3', 'Trong nhà', 2)) t(order_id, area, guests)""")
    con.execute("""CREATE TABLE khach AS SELECT * FROM (VALUES ('K1', '1990-03-05'), ('K2', '1985-07-01'), ('K3', '2000-03-20')) t(customer_id, ngay_sinh)""")
    con.execute("""CREATE TABLE chi AS SELECT * FROM (VALUES (DATE '2026-03-02', 500000, 'lương'), (DATE '2026-03-03', 200000, 'điện'),
        (DATE '2026-03-04', 400000, 'điện'), (DATE '2026-02-04', 900000, 'lương')) t(expense_date, expense_amount, expense_item)""")
    con.execute("""CREATE TABLE _meta_tables AS SELECT * FROM (VALUES ('lines', 'sales_lines', 4), ('giao', 'deliveries', 4),
        ('ban', 'order_info', 3), ('khach', 'customers', 3), ('chi', 'expenses', 4)) t(table_name, "role", n_rows)""")
    con.execute("CREATE TABLE _product_aliases (alias VARCHAR, product_name VARCHAR)")
    con.execute("CREATE TABLE _tet_periods (tet_year INT, start_date DATE, end_date DATE)")
    return con


def test_ky_tu_ngay_gom_ca_ngay_dau_va_ky_truoc_dung_n_ngay():
    base = {"loai": "tu_ngay", "tu": "2026-03-01", "n": 7}
    assert resolve_period(base, T) == (dt.date(2026, 3, 1), dt.date(2026, 3, 7))
    # D là ngày 1 không được hiểu thành "cả tháng trước"
    assert resolve_period({"loai": "ky_truoc", "cua": base}, T) == (dt.date(2026, 2, 22), dt.date(2026, 2, 28))


def test_bang_goc_nhom_va_loc_ky(run):
    p = {"nguon": "giao", "phep": "dem", "cot_ngay": "delivery_date", "ky": K, "nhom": "driver", "xep": {"chieu": "giam", "lay": 1}}
    assert run(p)["names"] == ["Ông Hương"]


def test_bang_goc_so_chu_khong_dau(run):
    p = {"nguon": "giao", "phep": "dem", "cot_ngay": "delivery_date", "ky": K, "loc": [{"cot": "driver", "op": "=", "gt": "ong huong"}]}
    assert run(p) == 2


def test_bang_goc_co_ma_don_kem_tinh_hop_le_va_doanh_thu(run):
    ok = [{"cot": "hop_le", "op": "=", "gt": True}]
    p = {"nguon": "ban", "phep": "tong", "cot": "doanh_thu_don", "cot_ngay": "ngay_don", "ky": K, "loc": ok, "nhom": "area", "xep": {"chieu": "giam", "lay": 1}}
    assert run(p)["names"] == ["Sân vườn"]       # đơn huỷ D2 (900.000) không tính
    assert run({"nguon": "ban", "phep": "tb", "cot": "guests", "cot_ngay": "ngay_don", "ky": K, "loc": ok}) == 3


def test_bang_goc_thang_cua_cot_ngay(run):
    assert run({"nguon": "khach", "phep": "dem", "loc": [{"cot": "ngay_sinh", "op": "thang_la", "gt": 3}]}) == 2


def test_bang_goc_sai_ten_cot_bao_cac_cot_co(run):
    with pytest.raises(PlanError, match="driver"):
        run({"nguon": "giao", "phep": "dem", "loc": [{"cot": "tai_xe", "op": "=", "gt": "x"}]})


def test_nguon_la_van_bi_tu_choi(run):
    with pytest.raises(PlanError, match="nguồn lạ"):
        run({"nguon": "khong_co", "phep": "dem"})


def test_doi_tuong_moi_lan_dau_roi_vao_ky(run):
    p = {"nguon": "dong_ban", "phep": "dem_nhom", "nhom": "khach", "co_dieu_kien": {"do": "min", "cot": "ngay", "op": "trong_ky", "ky": K}}
    assert run(p) == 1          # K1 mua từ tháng 2; K2 chỉ có đơn huỷ; K3 mới


def test_doi_tuong_nhieu_dieu_kien_va_so_do_khac(run):
    p = {"nguon": "dong_ban", "phep": "dem_nhom", "nhom": "don", "cot": "hang", "ky": K, "co_dieu_kien": {"op": ">=", "gt": 2}}
    assert run(p) == 1
    p = {"nguon": "dong_ban", "phep": "dem_nhom", "nhom": "khach", "ky": K,
         "co_dieu_kien": [{"do": "dem_khac", "cot": "hang", "op": ">=", "gt": 2}, {"do": "tong", "cot": "tien", "op": ">=", "gt": 400000}]}
    assert run(p) == 1


def test_nguong_theo_phan_tram_tong(run):
    p = {"nguon": "dong_ban", "phep": "dem_nhom", "nhom": "hang", "cot": "tien", "do": "tong", "ky": K, "co_dieu_kien": {"op": ">=", "phan_tram_tong": 40}}
    assert run(p) == 1          # tổng 600.000; chỉ SP3 đạt 240.000


def test_gop_hai_tang(run):
    rev = {"nguon": "dong_ban", "phep": "tong", "cot": "tien", "ky": K}
    assert run({**rev, "nhom": "don", "ngoai": "max"}) == 400000
    assert run({**rev, "nhom": "don", "co_dieu_kien": {"op": ">=", "gt": 300000}, "ngoai": "tong"}) == 400000
    assert run({"ghep": "ti_le", "cac": [{**rev, "nhom": "don", "co_dieu_kien": {"op": ">=", "gt": 300000}, "ngoai": "tong"}, rev]}) == 66.67
    with pytest.raises(PlanError):
        run({**rev, "nhom": "don", "ngoai": "la"})


def test_giao_hieu_hai_tap(run):
    a = {"nguon": "dong_ban", "nhom": "khach", "ky": K}
    b = {"nguon": "dong_ban", "nhom": "khach", "ky": K2}
    assert run({"ghep": "dem_giao", "cac": [a, b]}) == 1
    assert run({"ghep": "dem_hieu", "cac": [a, b]}) == 1


def test_tap_tren_cot_shop_khong_ghi_khong_ra_0(run):
    a = {"nguon": "dong_ban", "nhom": "nhan_vien", "ky": K}
    with pytest.raises(MissingData):
        run({"ghep": "dem_giao", "cac": [a, {**a, "ky": K2}]})


def test_so_ngay_cua_ky(run):
    assert run({"ghep": "hieu", "cac": [{"phep": "so_ngay", "ky": K}, {"nguon": "dong_ban", "phep": "dem_khac", "cot": "ngay", "ky": K}]}) == 29


def test_cong_cot_ma_la_dem(run):
    assert run({"nguon": "dong_ban", "phep": "tong", "cot": "don", "ky": K}) == 2


def test_nguong_tien_viet_thanh_loc_dong_doi_thanh_tong_doi_tuong():
    p = normalize({"nguon": "dong_ban", "phep": "dem_nhom", "nhom": "ngay", "cot": "tien", "loc": [{"cot": "tien", "op": ">=", "gt": 44}]})
    assert p["co_dieu_kien"] == {"op": ">=", "gt": 44} and p["loc"] == [] and p["do"] == "tong"
    p = normalize({"nguon": "dong_ban", "phep": "dem_nhom", "nhom": "don", "cot": "don", "co_dieu_kien": {"op": ">=", "gt": 93000}})
    assert p["cot"] == "tien" and p["do"] == "tong"


def test_clean_plan_bo_phan_cau_khong_hoi():
    rev = {"nguon": "dong_ban", "phep": "tong", "cot": "tien", "loc": [{"cot": "la_mat_hang", "op": "=", "gt": True},
                                                                      {"cot": "trang_thai", "op": "=", "gt": "hoan_thanh"},
                                                                      {"cot": "ke_don", "op": "=", "gt": True}]}
    assert clean_plan(rev, "doanh thu tháng 3")["loc"] == []
    assert len(clean_plan(rev, "doanh thu thuốc kê đơn của đơn hoàn thành")["loc"]) == 2


def test_clean_plan_dem_don_bo_moi_trang_thai_tru_khi_cau_noi():
    p = {"nguon": "don", "phep": "dem", "moi_trang_thai": True}
    assert "moi_trang_thai" not in clean_plan(p, "tháng 3 có bao nhiêu đơn")
    assert clean_plan(p, "tháng 3 có bao nhiêu đơn tính cả đơn huỷ").get("moi_trang_thai")
    # mẫu số của tỉ lệ vẫn giữ
    g = {"ghep": "ti_le", "cac": [{**p, "loc": [{"cot": "trang_thai", "gt": "huy"}]}, p]}
    assert clean_plan(g, "tỉ lệ huỷ")["cac"][1].get("moi_trang_thai")


def test_clean_plan_hang_e_hoi_so_luong_thanh_dem():
    assert clean_plan({"nguon": "dong_ban", "phep": "hang_e"}, "bao nhiêu mặt hàng bị ế")["phep"] == "dem_e"
    assert clean_plan({"nguon": "dong_ban", "phep": "hang_e"}, "có bn hàng ế tuần này")["phep"] == "dem_e"
    assert clean_plan({"nguon": "dong_ban", "phep": "hang_e"}, "liệt kê các hàng ế")["phep"] == "hang_e"


def test_mismatch_cac_chot():
    leaf = {"nguon": "dong_ban", "phep": "tong", "cot": "tien"}
    assert _mismatch(leaf, 0, "doanh thu nhóm x")               # không có dữ liệu không phải 0
    assert _mismatch({"nguon": "dong_ban", "phep": "dem_e"}, 0, "có bn hàng ế") is None
    assert _mismatch(leaf, False, "có tăng không") is None
    assert _mismatch(leaf, "2026-03-01", "tuần rồi bán được bn tiền")
    assert _mismatch(leaf, "2026-03-01", "ngày naof dthu cao nhất") is None
    huy = {**leaf, "loc": [{"cot": "trang_thai", "op": "=", "gt": "huy"}]}
    assert _mismatch(huy, 5, "có bn khách mua từ 4 đơn")
    assert _mismatch(huy, 5, "có bn đơn bị huỷ") is None
    assert _mismatch(leaf, 5, "thuốc có hoạt chất X bán được bn tiền")


def test_unwrap_ke_hoach_la_mang():
    assert _unwrap({"ke_hoach": [{"nguon": "don"}]})["ke_hoach"] == {"nguon": "don"}
    assert _unwrap({"ke_hoach": [{"nguon": "don"}, {"nguon": "don"}]})["ke_hoach"]["ghep"] == "danh_sach"


def test_naturalize_hai_khoang_lien_nhau_thanh_tu_ngay():
    c = [{"nguon": "dong_ban", "ky": {"loai": "khoang", "tu": "2026-03-10", "den": "2026-03-16"}},
         {"nguon": "dong_ban", "ky": {"loai": "khoang", "tu": "2026-03-03", "den": "2026-03-09"}}]
    out = naturalize({"ghep": "tang_truong", "cac": c}, "so 7 ngày kể từ ngày tăng giá", dt.date(2026, 5, 1))
    assert out["cac"][0]["ky"] == {"loai": "tu_ngay", "tu": "2026-03-10", "n": 7}
    assert out["cac"][1]["ky"]["loai"] == "ky_truoc"
    a = resolve_period(out["cac"][1]["ky"], dt.date(2026, 5, 1))
    assert a == (dt.date(2026, 3, 3), dt.date(2026, 3, 9))


def test_nguong_doanh_thu_don_tinh_tren_bang_don(run):
    # tháng 3: D1 = 100.000 + 300.000, D3 = 200.000, D2 huỷ
    p = {"nguon": "dong_ban", "phep": "dem_khac", "cot": "don", "ky": K, "loc": [{"cot": "doanh_thu", "op": ">=", "gt": 300000}]}
    assert run(p) == 1
    rev = {"nguon": "dong_ban", "phep": "tong", "cot": "tien", "ky": K, "loc": [{"cot": "doanh_thu", "op": ">=", "gt": 300000}]}
    assert run(rev) == 400000
    with pytest.raises(PlanError, match="ngưỡng doanh thu"):
        run({**rev, "loc": rev["loc"] + [{"cot": "hang", "op": "=", "gt": "SP A"}]})


def test_dem_mat_hang_khac_nhau_chi_dong_la_mat_hang():
    hang = {"cot": "la_mat_hang", "op": "=", "gt": True}
    assert hang in normalize({"nguon": "dong_ban", "phep": "dem_khac", "cot": "hang"})["loc"]
    assert hang in normalize({"nguon": "dong_ban", "phep": "dem_nhom", "nhom": "don", "cot": "hang", "co_dieu_kien": {"op": ">=", "gt": 3}})["loc"]
    assert normalize({"nguon": "dong_ban", "phep": "dem_khac", "cot": "don"})["loc"] == []


def test_phan_tram_tong_viet_thanh_ti_le(run):
    p = {"nguon": "dong_ban", "phep": "dem_nhom", "nhom": "hang", "cot": "tien", "do": "tong", "ky": K,
         "co_dieu_kien": {"op": ">=", "gt": 0.4, "phan_tram_tong": True}}
    assert run(p) == 1
    with pytest.raises(PlanError, match="phan_tram_tong"):
        run({**p, "co_dieu_kien": {"op": ">=", "phan_tram_tong": "nam"}})


def test_loc_cot_ngay_trong_ky(run):
    assert run({"nguon": "giao", "phep": "dem", "loc": [{"cot": "delivery_date", "op": "trong_ky", "ky": K}]}) == 3
    assert run({"nguon": "dong_ban", "phep": "dem_khac", "cot": "don", "loc": [{"cot": "ngay", "op": "trong_ky", "ky": K2}]}) == 1


def test_ten_bang_goc_viet_lech_van_nhan(run):
    assert run({"nguon": "GIAO", "phep": "dem", "cot_ngay": "delivery_date", "ky": K}) == 3


def test_phep_ghep_la_va_trong_ky_thieu_do_bao_cach_viet(run):
    with pytest.raises(PlanError, match="phép ghép lạ"):
        run({"ghep": "dem_nhom", "cac": []})
    with pytest.raises(PlanError, match="trong_ky"):
        run({"nguon": "dong_ban", "phep": "dem_nhom", "nhom": "khach", "co_dieu_kien": {"op": "trong_ky", "ky": K}})


def test_bang_chuan_dot_giao_va_khoan_chi_co_them_cot(run):
    top = {"xep": {"chieu": "giam", "lay": 1}}
    assert run({"nguon": "dot_giao", "phep": "dem", "ky": K, "nhom": "tai_xe", **top})["names"] == ["Ông Hương"]
    assert run({"nguon": "dot_giao", "phep": "dem", "ky": K}) == 3
    assert run({"nguon": "khoan_chi", "phep": "tong", "cot": "tien", "ky": K, "nhom": "khoan_muc", **top})["names"] == ["điện"]


def test_clean_plan_bo_moi_cach_loc_lay_don_hop_le():
    for c in ({"cot": "trang_thai", "op": "!=", "gt": "huy"}, {"cot": "trang_thai", "op": "in", "gt": ["hoan_thanh", "dang_giao"]}):
        assert clean_plan({"nguon": "dong_ban", "phep": "tong", "cot": "tien", "loc": [c]}, "doanh thu tháng 3")["loc"] == []
    keep = {"cot": "trang_thai", "op": "=", "gt": "dang_giao"}
    assert clean_plan({"nguon": "don", "phep": "dem", "loc": [keep]}, "bao nhiêu đơn tháng 3")["loc"] == [keep]


def test_clean_plan_ti_le_bo_moi_trang_thai_khi_khong_ve_nao_loc_trang_thai():
    a = {"nguon": "dong_ban", "phep": "dem_khac", "cot": "don", "moi_trang_thai": True, "loc": [{"cot": "khach_le", "op": "=", "gt": True}]}
    b = {"nguon": "dong_ban", "phep": "dem_khac", "cot": "don", "moi_trang_thai": True}
    out = clean_plan({"ghep": "ti_le", "cac": [a, b]}, "tỉ lệ khách vãng lai tháng 3")
    assert not any(x.get("moi_trang_thai") for x in out["cac"])
    gia = {"nguon": "dong_ban", "phep": "gia_duy_nhat", "cot": "gia_1_dv", "moi_trang_thai": True}
    assert clean_plan({"ghep": "hieu", "cac": [gia, gia]}, "giá bán ngày 1 hơn ngày 2 bao nhiêu")["cac"][0]["moi_trang_thai"]


def test_mismatch_hai_ve_giong_nhau_ky_ca_nam_va_nham_doi_tuong():
    leaf = {"nguon": "dong_ban", "phep": "dem_khac", "cot": "don", "ky": K}
    assert _mismatch({"ghep": "ti_le", "cac": [leaf, leaf]}, 100.0, "tỉ lệ ghi nợ tháng 3/2026")
    y = {"nguon": "dong_ban", "phep": "tong", "cot": "tien", "ky": {"loai": "nam", "nam": 2025}}
    assert '"thang": 12' in _mismatch(y, 5, "tháng 12 năm 2025 doanh thu bao nhiêu")
    assert _mismatch(y, 5, "năm 2025 doanh thu bao nhiêu") is None
    g = {"nguon": "dong_ban", "phep": "dem_khac", "cot": "don", "nhom": "khach", "xep": {"chieu": "giam", "lay": 1}}
    assert _mismatch(g, {"names": ["A"], "id": "A"}, "nhân viên nhiều đơn nhất là ai")
    assert _mismatch(g, {"names": ["A"], "id": "A"}, "khách nhiều đơn nhất là ai") is None


def test_phep_tinh_tren_ve_xep_hang_lay_so_do(run):
    by_day = {"nguon": "dong_ban", "phep": "tong", "cot": "tien", "ky": K, "nhom": "ngay"}
    top, low = {**by_day, "xep": {"chieu": "giam", "lay": 1}}, {**by_day, "xep": {"chieu": "tang", "lay": 1}}
    assert run({"ghep": "hieu", "cac": [top, low]}) == 200000        # 400.000 (1/3) - 200.000 (3/3)


def test_cong_cot_chu_va_dieu_kien_cot_la_bao_cach_viet(run):
    with pytest.raises(PlanError, match="không phải số"):
        run({"nguon": "dong_ban", "phep": "tong", "cot": "kenh", "ky": K})
    with pytest.raises(PlanError, match="không có cột ngay_sinh"):
        run({"nguon": "dong_ban", "phep": "dem_nhom", "nhom": "khach", "co_dieu_kien": {"do": "min", "cot": "ngay_sinh", "op": ">=", "gt": 1}})


def test_hoi_mot_so_ma_ke_hoach_tra_doi_tuong_dau_thi_lay_so_do():
    con = _db()
    ctx = types.SimpleNamespace(con=con, facts=Facts(con))
    out = {"ke_hoach": {"nguon": "dong_ban", "phep": "tong", "cot": "tien", "ky": K, "nhom": "don", "xep": {"chieu": "giam", "lay": 1}}, "ra": "number"}
    kind, _, plan, v = _attempt(ctx, out, T, "đơn lớn nhất tháng 3/2026 trị giá bao nhiêu")
    assert (kind, v, plan["cot_ra"]) == ("tra_loi", 400000, "gia_tri")


def test_raw_catalog_uu_tien_bang_lien_quan_cau_hoi():
    con = duckdb.connect()
    con.execute("CREATE TABLE giao (driver VARCHAR, delivery_date DATE)")
    con.execute("CREATE TABLE khac (ghi_chu VARCHAR)")
    con.execute("INSERT INTO giao VALUES ('Ông Hương', DATE '2026-03-05')")
    con.execute("""CREATE TABLE _meta_tables AS SELECT * FROM (VALUES ('khac', 'other'), ('giao', 'deliveries')) t(table_name, "role")""")
    con.execute("""CREATE TABLE _meta_columns AS SELECT * FROM (VALUES ('giao', 'driver', 'tài xế', 'text', 'driver', NULL),
        ('giao', 'delivery_date', 'ngày giao', 'date', 'Ngày giao', NULL), ('khac', 'ghi_chu', NULL, 'text', NULL, NULL))
        t(table_name, column_name, description, kind, original_name, note)""")
    text = raw_catalog(con, "tài xế chăm nhất là ai", top=1)
    assert text.startswith("- giao (deliveries): driver: tài xế {Ông Hương}") and "Bảng khác: khac" in text
    assert "delivery_date (gốc 'Ngày giao'): ngày giao" in raw_catalog(con, "ngày giao", top=1)


def test_bang_chuan_gio_toan_0h_la_khong_ghi_va_cot_giam_gia():
    con = _db()
    t = Facts(con).table("dong_ban")
    assert con.execute(f'SELECT COUNT(gio), COUNT(ca), COUNT(giam_dong) FROM "{t}"').fetchone() == (0, 0, 0)
    con.execute("ALTER TABLE lines ADD COLUMN order_time TIMESTAMP")
    con.execute("UPDATE lines SET order_time = CAST(order_date AS TIMESTAMP) + INTERVAL 9 HOUR")
    con.execute("ALTER TABLE lines ADD COLUMN line_discount INTEGER")
    con.execute("UPDATE lines SET line_discount = 1000")
    con.execute("""CREATE TABLE hd AS SELECT * FROM (VALUES ('D1', DATE '2026-03-01', 'hoan_thanh', 5000),
        ('D3', DATE '2026-03-03', 'hoan_thanh', 0)) t(order_id, order_date, status_norm, order_discount)""")
    con.execute("INSERT INTO _meta_tables VALUES ('hd', 'orders', 2)")
    f = Facts(con)
    t = f.table("dong_ban")
    assert con.execute(f"SELECT MIN(gio), MIN(ca), SUM(giam_dong) FROM \"{t}\" WHERE thang = '2026-03'").fetchone() == (9, "sang", 4000)
    assert con.execute(f"SELECT giam_don FROM \"{f.table('don')}\" WHERE don = 'D1'").fetchone()[0] == 5000
