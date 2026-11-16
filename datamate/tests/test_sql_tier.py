import datetime as dt
import types

import duckdb
import pandas as pd
import pytest

from datamate.loader.build import Built, _family, merge_split
from datamate.loader.header import Table, merge_sheets
from datamate.query.compose import ShopContext, asks_yes_no
from datamate.query.facts import Facts
from datamate.query.sql_tier import (_at_date, _attempt, _missing_code, _period_miss, _prepare, _soft_eq, _sql_mismatch,
                                     periods, to_value)
from datamate.tests.test_plan_more import _db


def test_to_value_tien_lam_tron_nua_dong_len():
    assert to_value([(1234.5,)], "tien") == 1235


def test_to_value_null_khong_thanh_0():
    with pytest.raises(ValueError):
        to_value([(None,)], "tien")


def test_to_value_sai_dang_bao_loi():
    with pytest.raises(ValueError):
        to_value([(1,), (2,)], "number")


def test_to_value_percent_list_table_date():
    assert to_value([(12.3456,)], "percent") == 12.35
    assert to_value([(dt.date(2026, 5, 1),)], "date") == "2026-05-01"
    assert to_value([(1, 2, 3)], "list") == [1, 2, 3]
    assert to_value([("A",), ("B",)], "list") == [{"names": ["A"], "id": "A"}, {"names": ["B"], "id": "B"}]
    assert to_value([("A", 5.0)], "table") == {"bang": [[{"names": ["A"], "id": "A"}, 5]]}


def test_at_date_lay_ngay_trong_cau():
    today = dt.date(2026, 5, 20)
    assert _at_date("tính đến hết ngày 14/06/2025 còn nợ", today) == dt.date(2025, 6, 14)
    assert _at_date("hôm nay còn nợ", today) == today


def test_at_date_het_thang_la_ngay_cuoi_thang():
    today = dt.date(2026, 5, 20)
    assert _at_date("Đến hết tháng 2/2026 có bao nhiêu đơn nợ lâu?", today) == dt.date(2026, 2, 28)
    assert _at_date("tinh den cuoi thang 12 nam 2025 con no bn", today) == dt.date(2025, 12, 31)
    assert _at_date("đến hết tháng 5/2026 còn nợ", today) == today        # tháng chưa hết: tính đến hôm nay


def test_periods_tuan_truoc_tinh_san():
    assert "tuần trước: 2026-05-11 đến 2026-05-17" in periods(dt.date(2026, 5, 20))


def test_khop_bo_dau_va_chu_d():
    con = duckdb.connect()

    class Ctx:
        pass
    ctx = Ctx()
    ctx.con = con
    _prepare(ctx)
    assert con.execute("SELECT khop('Đường Lê Lợi', 'duong le loi')").fetchone()[0]
    assert not con.execute("SELECT khop('Đường Lê Lợi', 'duong le lai')").fetchone()[0]


def _shop_db(tmp_path) -> str:
    p = str(tmp_path / "s.duckdb")
    con = duckdb.connect(p)
    con.execute("CREATE TABLE _meta_shop AS SELECT 'tap_hoa' industry")
    con.execute("CREATE TABLE _rulebook (seq INT, level INT, heading VARCHAR, text VARCHAR)")
    con.close()
    return p


def test_shop_context_mot_luong(tmp_path):
    # nhiều luồng: dòng hoà sau ORDER BY ... LIMIT và giá trị mẫu trong prompt đổi giữa các lần chạy
    ctx = ShopContext(_shop_db(tmp_path))
    assert ctx.con.execute("SELECT current_setting('threads')").fetchone()[0] == 1


def test_danh_muc_theo_tung_ngay(tmp_path, monkeypatch):
    # một shop hỏi ở nhiều ngày: danh mục của câu tính tại đúng ngày của câu, không lấy ngày của câu làm trước
    import datamate.query.compose as compose
    monkeypatch.setattr(compose, "catalog", lambda con, facts, today: f"danh mục {today}")
    ctx = ShopContext(_shop_db(tmp_path))
    a, b = dt.date(2026, 5, 1), dt.date(2026, 6, 1)
    assert (ctx.catalog(a), ctx.catalog(b), ctx.catalog(a)) == ("danh mục 2026-05-01", "danh mục 2026-06-01", "danh mục 2026-05-01")


def _built(label, cols, source="readme_col"):
    df = pd.DataFrame([{c: 1 for c in cols}])
    meta = [{"column": c, "original": c, "canonical": c, "map_source": source, "kind": "number"} for c in cols]
    return Built("", label, "", df, meta, [label])


CORE = ["order_id", "order_date", "product_name", "qty", "line_amount", "status"]


def test_family_bo_phan_thang_nam():
    assert _family("SoBan_1") == _family("SoBan_2026") == _family("SoBan__T07-2025") == "soban"
    assert _family("DanhSachHoaDon") != _family("DanhSachHoaDonChiTiet")


def test_merge_split_cung_ho_lech_cot_phu_van_gop():
    out, _ = merge_split([_built("SoBan_1", CORE + ["Điểm"]), _built("SoBan_2026", CORE + ["Số lần in"])])
    assert len(out) == 1 and len(out[0].df) == 2
    assert {"Điểm", "Số lần in"} <= {c["column"] for c in out[0].columns}


def test_merge_split_khac_ho_khong_gop_khi_lech_cot():
    out, _ = merge_split([_built("BanHang", CORE + ["Điểm"]), _built("TraHang", CORE + ["Số lần in"])])
    assert len(out) == 2


def test_merge_split_cot_llm_doan_o_mot_phan_tra_ve_ten_goc():
    a = _built("SoBan_1", CORE + ["Người nhập liệu"])
    b = _built("SoBan_2026", CORE + ["staff_name"])
    m = next(c for c in b.columns if c["column"] == "staff_name")
    m.update(original="Người nhập liệu", map_source="llm")
    out, _ = merge_split([a, b])
    assert len(out) == 1
    assert "staff_name" not in out[0].df.columns and out[0].df["Người nhập liệu"].notna().all()


def _table(sheet, cols, row):
    return Table(name="So", file="So.xlsx", sheets=[sheet], columns=list(cols), rows=[list(row)], src=[(sheet, 2)])


def test_merge_sheets_lech_cot_phu_de_trong_o_thieu():
    a = _table("T1", CORE + ["Điểm"], [1, 2, 3, 4, 5, 6, 7])
    b = _table("T2", CORE + ["In"], [1, 2, 3, 4, 5, 6, 8])
    out = merge_sheets([a, b])
    assert len(out) == 1 and out[0].columns == CORE + ["Điểm", "In"]
    assert out[0].rows == [[1, 2, 3, 4, 5, 6, 7, None], [1, 2, 3, 4, 5, 6, None, 8]]


def test_periods_ghi_san_thang_trong_cau():
    p = periods(dt.date(2026, 5, 20), "con no lon nhat den het thang 2/2026, so voi thang 1 nam 2026")
    assert "- tháng 2/2026: 2026-02-01 đến 2026-02-28" in p and "- tháng 1/2026: 2026-01-01 đến 2026-01-31" in p


def test_hoi_co_khong():
    for q in ("Tháng 2/2025 có phải là tháng tăng không?", "tháng 9 năm 2025 là tháng tăng đúng không",
              "dthu tháng sau có luôn cao hơn tháng trc k hả", "doanh thu có tăng liên tục hok vaayj", "đã có đơn nào bị huỷ chưa"):
        assert asks_yes_no(q), q
    for q in ("có bao nhiêu đơn không thành công", "doanh thu tháng 3 bao nhiêu", "Tỉ lệ đơn sáng tháng 4/2025 là bao nhiêu %?"):
        assert not asks_yes_no(q), q


def test_sql_mismatch_cac_chot():
    assert "boolean" in _sql_mismatch("SELECT 1", 5.2, "Tháng 2/2025 có phải là tháng tăng không?")
    assert _sql_mismatch("SELECT 1", True, "Tháng 2/2025 có phải là tháng tăng không?") is None
    lines = "SELECT COUNT(*) FROM (SELECT khach FROM v_dong_ban WHERE hop_le GROUP BY khach HAVING COUNT(*) = 1)"
    assert "DISTINCT don" in _sql_mismatch(lines, 14, "tháng 3 có mấy khách một lần")
    orders = "SELECT COUNT(*) FROM (SELECT khach FROM v_dong_ban WHERE hop_le GROUP BY khach HAVING COUNT(DISTINCT don) = 1)"
    assert _sql_mismatch(orders, 14, "tháng 3 có mấy khách một lần") is None
    assert _sql_mismatch("SELECT COUNT(*) FROM v_don WHERE hop_le", 5, "có bn khách có ít nhất 3 đơn") is None
    asc = "SELECT ANY_VALUE(ten_hang) FROM v_dong_ban GROUP BY hang ORDER BY MAX(don_gia) LIMIT 1"
    name = {"names": ["A"], "id": "A"}
    assert "DESC" in _sql_mismatch(asc, name, "hàng đắt nhất tháng 9 là gì")
    assert _sql_mismatch(asc, name, "hàng rẻ nhất tháng 9 là gì") is None
    assert _sql_mismatch("SELECT SUM(tien) FROM v_dong_ban", 0, "doanh thu tháng 3")


def test_sql_cot_shop_khong_ghi_la_khong_tra_loi_duoc_va_ma_doi_ra_ten():
    con = _db()
    ctx = types.SimpleNamespace(con=con, facts=Facts(con))
    today = dt.date(2026, 3, 18)
    q = {"id": "x", "question": "doanh thu ca sáng tháng 3/2026", "as_of_date": "2026-03-18"}
    assert _attempt(ctx, {"khong_co": "shop không ghi ca"}, q, today)[0] == "thieu_nguon"
    assert _attempt(ctx, {"khong_co": "không có thông tin thái độ"}, q, today)[0] == "llm_khong_co"
    sql = "SELECT SUM(tien) FROM v_dong_ban WHERE hop_le AND ca = 'sang' AND thang = '2026-03'"
    assert _attempt(ctx, {"sql": sql, "ra": "tien"}, q, today)[0] == "thieu_nguon"
    q = {"id": "y", "question": "khách chi nhiều nhất tháng 3/2026 là ai", "as_of_date": "2026-03-18"}
    sql = "SELECT khach FROM v_dong_ban WHERE hop_le AND thang = '2026-03' GROUP BY khach ORDER BY SUM(tien) DESC LIMIT 1"
    kind, _, _, v, _ = _attempt(ctx, {"sql": sql, "ra": "string"}, q, today)
    assert kind == "tra_loi" and v["names"][0] == "An" and v["id"] == "K1"


def test_period_miss_ky_tuong_doi_va_moc_ghi_ro():
    T = dt.date(2026, 5, 20)
    five = "SELECT SUM(tien) FROM v_dong_ban WHERE hop_le AND ngay BETWEEN DATE '2026-05-11' AND DATE '2026-05-15'"
    assert "2026-05-17" in _period_miss(five, "doanh thu tuần trước", T)
    week = "SELECT SUM(tien) FROM v_dong_ban WHERE hop_le AND ngay BETWEEN DATE '2026-05-11' AND DATE '2026-05-17'"
    assert _period_miss(week, "doanh thu tuần rồi", T) is None
    # "tháng trước" tính theo tháng ghi trong câu: chỉ xét tháng ghi rõ
    rel = ("SELECT 100.0 * ((SELECT SUM(tien) FROM v_dong_ban WHERE hop_le AND thang = '2025-06') - (SELECT SUM(tien) FROM v_dong_ban "
           "WHERE hop_le AND thang = '2025-05')) / (SELECT SUM(tien) FROM v_dong_ban WHERE hop_le AND thang = '2025-05')")
    assert _period_miss(rel, "Doanh thu tháng 6/2025 hơn hay kém tháng trước bao nhiêu %?", T) is None
    span = "SELECT thang FROM v_dong_ban WHERE hop_le AND ngay BETWEEN DATE '2026-01-01' AND DATE '2026-03-31' GROUP BY thang"
    assert _period_miss(span, "Xét 3 tháng 1/2026, 2/2026 và 3/2026, doanh thu tháng nào lớn nhất?", T) is None
    one = "SELECT SUM(tien) FROM v_dong_ban WHERE hop_le AND thang = '2025-07'"
    assert "2025-09-30" in _period_miss(one, "trong quy 3 nam 2025 dthu bnhiu", T)
    assert _period_miss("SELECT SUM(ton) FROM v_ton", "tồn cuối hôm qua", T) is None       # bảng tình trạng: không xét kỳ


def test_so_chu_doi_sang_khop():
    assert _soft_eq("SELECT 1 FROM v_dong_ban d WHERE d.hoat_chat = 'Vitamin C' AND nhom_hang = 'Dị ứng'") ==         "SELECT 1 FROM v_dong_ban d WHERE khop(d.hoat_chat, 'Vitamin C') AND khop(nhom_hang, 'Dị ứng')"
    assert _soft_eq("SELECT 1 FROM v_don WHERE kenh = 'zalo'") == "SELECT 1 FROM v_don WHERE kenh = 'zalo'"


def test_ma_trong_cau_phai_co_trong_sql_va_nguong_don():
    con = _db()
    ctx = types.SimpleNamespace(con=con, facts=Facts(con))
    assert "K1" in _missing_code(ctx, "SELECT SUM(tien) FROM v_dong_ban WHERE hop_le", "khách K1 mua bao nhiêu")
    assert _missing_code(ctx, "SELECT SUM(tien) FROM v_dong_ban WHERE khach = 'K1'", "khách K1 mua bao nhiêu") is None
    assert _missing_code(ctx, "SELECT SUM(tien) FROM v_dong_ban", "mã XX99 bán bao nhiêu") is None      # không phải mã có thật
    line = "SELECT COUNT(DISTINCT don) FROM v_dong_ban WHERE hop_le AND thang = '2026-02' AND tien >= 56000"
    assert "HAVING" in _sql_mismatch(line, 858, "đếm số đơn hàng tháng 2/2026 có tiền hàng từ 56.000 đồng trở lên")


def test_minus_doi_thanh_except_ngoai_chuoi():
    from datamate.query.sql_tier import _dialect
    assert _dialect("SELECT a FROM t MINUS SELECT a FROM u WHERE x = 'minus'") == "SELECT a FROM t EXCEPT SELECT a FROM u WHERE x = 'minus'"


def test_dem_dong_khi_cau_do_tren_dong():
    sql = "SELECT SUM(tien) / COUNT(*) FROM v_dong_ban WHERE hop_le AND thang = '2025-11' AND la_mat_hang"
    rules = "| Giá trị dòng bình quân | **Giá trị dòng bình quân** là doanh thu của các dòng mặt hàng chia cho số dòng đó |"
    assert _sql_mismatch(sql, 65446, "Giá trị dòng bình quân tháng 11/2025 là bao nhiêu?") is None
    assert _sql_mismatch(sql, 65446, "gia tri dong binh quan thang 11/2025 bn", rules=rules) is None
    assert "COUNT(DISTINCT don)" in _sql_mismatch(sql, 65446, "gia tri dong binh quan thang 11/2025 bn")
    assert "COUNT(DISTINCT don)" in _sql_mismatch(sql, 65446, "Trung bình mỗi đơn tháng 11/2025 bao nhiêu đồng?")


def test_count_trong_khoi_nhom_theo_don_la_so_dong_moi_don():
    sql = ("SELECT COUNT(*) FROM (SELECT don FROM v_dong_ban WHERE hop_le AND thang = '2025-03' AND la_mat_hang "
           "GROUP BY don HAVING COUNT(*) = 1)")
    assert _sql_mismatch(sql, 889, "số đơn gọn của tháng 3 năm 2025 là mấy") is None
    assert _sql_mismatch("SELECT COUNT(*) FROM v_dong_ban WHERE hop_le GROUP BY ngay ORDER BY 1 DESC LIMIT 1", 9,
                         "ngày nào nhiều đơn nhất") is not None


def test_hoi_ngay_nao_ma_ra_so_hoi_bao_nhieu_ma_ra_ten():
    assert "ngày" in _sql_mismatch("SELECT COUNT(DISTINCT don) FROM v_dong_ban", 103, "ngay vang thang 12/2025 la ngay nao")
    assert "con số" in _sql_mismatch("SELECT ANY_VALUE(ten_hang) FROM v_dong_ban", "Ngói Đồng Nai",
                                     "gia tran Dây điện Cadivi thang 2/2025 bn")
    assert _sql_mismatch("SELECT MAX(don_gia) FROM v_dong_ban", 2760000, "gia tran Dây điện Cadivi thang 2/2025 bn") is None
    assert _sql_mismatch("SELECT ANY_VALUE(ten_hang) FROM v_dong_ban", "Cà phê", "mặt hàng nào bán được nhiều nhất") is None


def test_ten_dat_tam_khong_phai_cot_shop_khong_ghi():
    from datamate.query.sql_tier import _uses_unrecorded
    ctx = types.SimpleNamespace(_cat={("khong_ghi", dt.date(2025, 5, 1)): {"dong_ban": ["sl"]}})
    sql = "SELECT COUNT(*) FROM (SELECT don, SUM(sl_co_ban) AS sl FROM v_dong_ban GROUP BY don HAVING SUM(sl_co_ban) >= 20)"
    assert _uses_unrecorded(ctx, sql, dt.date(2025, 5, 1)) is None
    assert _uses_unrecorded(ctx, "SELECT SUM(sl) FROM v_dong_ban", dt.date(2025, 5, 1)) == "sl"


def test_ky_ghi_san_thang_lien_truoc():
    p = periods(dt.date(2026, 9, 20), "Tháng 7/2026 có bao nhiêu khách rời?")
    assert "tháng 7/2026: 2026-07-01 đến 2026-07-31" in p
    assert "tháng liền trước của tháng 7/2026: 2026-06-01 đến 2026-06-30" in p
    assert "tháng liền trước của tháng 1/2026: 2025-12-01 đến 2025-12-31" in periods(dt.date(2026, 3, 1), "khach roi thang 1/2026")


def test_khoang_con_cua_thang_khi_cau_noi_dau_thang():
    today = dt.date(2026, 4, 2)
    sql = "SELECT SUM(tien) FROM v_dong_ban WHERE hop_le AND ngay BETWEEN DATE '2026-03-01' AND DATE '2026-03-10'"
    assert _period_miss(sql, "tháng 3 năm 2026 doanh thu đầu tháng được nhiêu tiền", today) is None
    assert _period_miss(sql, "tháng 3 năm 2026 doanh thu được nhiêu tiền", today) is not None
    sql2 = "SELECT SUM(tien) FROM v_dong_ban WHERE hop_le AND ngay BETWEEN DATE '2026-02-01' AND DATE '2026-02-10'"
    assert _period_miss(sql2, "tháng 3 năm 2026 doanh thu đầu tháng được nhiêu tiền", today) is not None
