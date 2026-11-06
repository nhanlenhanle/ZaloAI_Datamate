import duckdb

from datamate.query.compose import ShopContext, final_record
from datamate.query.hybrid import both, guard_unanswerable


def _ctx(tmp_path, start, end, described=True) -> ShopContext:
    p = str(tmp_path / "s.duckdb")
    con = duckdb.connect(p)
    con.execute("CREATE TABLE _meta_shop AS SELECT 'tap_hoa' industry, CAST(? AS DATE) sales_start, CAST(? AS DATE) sales_end",
                [start, end])
    con.execute("CREATE TABLE _rulebook (seq INT, level INT, heading VARCHAR, text VARCHAR)")
    con.execute("CREATE TABLE _meta_columns (table_name VARCHAR, column_name VARCHAR, original_name VARCHAR, description VARCHAR)")
    con.execute("INSERT INTO _meta_columns VALUES ('don', 'order_date', 'Ngày', ?), ('don', 'product_key', NULL, 'khoá')",
                ["ngày bán" if described else None])
    con.close()
    return ShopContext(p)


def test_khong_co_so_ban_thi_bo_trong(tmp_path):
    ctx = _ctx(tmp_path, None, None)
    assert not ctx.sales_known()
    for loai in ("thieu_nguon", "ngoai_ky"):
        assert final_record("q", guard_unanswerable(ctx, {"loai": loai})) == {"id": "q", "type": "abstain"}
    r = {"loai": "tra_loi", "value": 5.0, "want": None}
    assert guard_unanswerable(ctx, r) is r                 # câu đã trả lời không đổi


def test_co_so_ban_thi_giu_ket_luan(tmp_path):
    ctx = _ctx(tmp_path, "2025-01-01", "2026-06-30")
    assert ctx.sales_known() and ctx.columns_described()
    assert final_record("q", guard_unanswerable(ctx, {"loai": "thieu_nguon"})) == {"id": "q", "type": "unanswerable"}


def test_readme_khong_mo_ta_cot_thi_bo_trong(tmp_path):
    ctx = _ctx(tmp_path, "2025-01-01", "2026-06-30", described=False)   # mô tả của cột dẫn xuất không tính
    assert ctx.sales_known() and not ctx.columns_described()
    assert final_record("q", guard_unanswerable(ctx, {"loai": "thieu_nguon"})) == {"id": "q", "type": "abstain"}


def test_hai_duong_lech_o_shop_khong_mo_ta():
    j = {"loai": "tra_loi", "value": 5.0}
    s = {"loai": "tra_loi", "value": 7.0}
    assert both(j, s, False)["tang"] == "sql"
    assert both(j, s, True) is j
    assert both(j, s, False, cautious=True)["loai"] == "khong_chac"
    assert both(j, s, True, cautious=True)["loai"] == "khong_chac"
    assert both(j, {**s, "value": 5.0}, False, cautious=True) is j      # trùng thì vẫn nộp
    assert both(j, {"loai": "loi"}, False, cautious=True) is j          # một đường trả lời: không đổi


def test_thieu_bang_meta(tmp_path):
    p = str(tmp_path / "k.duckdb")
    con = duckdb.connect(p)
    con.execute("CREATE TABLE _meta_shop AS SELECT 'tap_hoa' industry")
    con.execute("CREATE TABLE _rulebook (seq INT, level INT, heading VARCHAR, text VARCHAR)")
    con.close()
    assert not ShopContext(p).sales_known()
    assert not ShopContext(p).columns_described()
