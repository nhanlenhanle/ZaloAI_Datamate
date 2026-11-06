import duckdb

from datamate.query.compose import ShopContext, holiday_block


def _db(tmp_path) -> str:
    p = str(tmp_path / "s.duckdb")
    con = duckdb.connect(p)
    con.execute("CREATE TABLE _meta_shop AS SELECT 'tap_hoa' industry")
    con.execute("CREATE TABLE _rulebook (seq INT, level INT, heading VARCHAR, text VARCHAR)")
    con.execute("CREATE TABLE _calendar (date VARCHAR, holiday VARCHAR)")
    con.executemany("INSERT INTO _calendar VALUES (?, ?)", [
        ("2025-09-06", "Vu Lan"), ("2026-08-27", "Vu Lan"), ("2025-10-20", "Phụ nữ Việt Nam"), ("2025-03-08", "Quốc tế Phụ nữ"),
        ("2026-02-17", "Tết"), ("2026-02-18", "Tết"), ("2025-09-07", None), ("2025-09-08", "")])
    con.close()
    return p


def test_le_trong_cau_tra_theo_lich(tmp_path):
    ctx = ShopContext(_db(tmp_path))
    assert ctx.holiday_lines("doanh thu dip vu lan 2025 bao nhieu") == ["- Vu Lan: 2025-09-06, 2026-08-27"]
    # tên dài khớp trước, không bắt nhầm "Quốc tế Phụ nữ"
    assert ctx.holiday_lines("Ngày Phụ nữ Việt Nam bán được bao nhiêu?") == ["- Phụ nữ Việt Nam: 2025-10-20"]
    assert ctx.holiday_lines("Tết 2026 bán được bao nhiêu") == []          # Tết có kỳ riêng trong ngôn ngữ kế hoạch
    assert ctx.holiday_lines("tháng 9/2025 doanh thu") == []
    assert holiday_block(ctx, "vu lan").startswith("NGÀY LỄ")
    assert holiday_block(object(), "vu lan") == ""


def test_khong_co_lich(tmp_path):
    p = str(tmp_path / "k.duckdb")
    con = duckdb.connect(p)
    con.execute("CREATE TABLE _meta_shop AS SELECT 'tap_hoa' industry")
    con.execute("CREATE TABLE _rulebook (seq INT, level INT, heading VARCHAR, text VARCHAR)")
    con.close()
    assert ShopContext(p).holiday_lines("vu lan") == []
