"""Nhân viên chỉ ghi tên, mỗi lần viết một kiểu ("Lan", "LAN", "lan "): phía truy vấn phải gom thành một người như lớp
dữ liệu gom tên khách / tên hàng, và vẫn in tên đúng dấu."""
import datetime as dt

import duckdb

from datamate.query.facts import Facts
from datamate.query.plan import Runner, to_record

T = dt.date(2026, 3, 31)


def _run():
    con = duckdb.connect()
    con.execute("""CREATE TABLE lines AS SELECT * FROM (VALUES
        ('D1', DATE '2026-03-01', 'hoan_thanh', 100, 'hang', 'SP1', 'sp a', 'SP A', 1.0, 'Lan'),
        ('D2', DATE '2026-03-02', 'hoan_thanh', 100, 'hang', 'SP1', 'sp a', 'SP A', 1.0, 'LAN'),
        ('D3', DATE '2026-03-03', 'hoan_thanh', 100, 'hang', 'SP1', 'sp a', 'SP A', 1.0, 'lan '),
        ('D4', DATE '2026-03-04', 'hoan_thanh', 250, 'hang', 'SP1', 'sp a', 'SP A', 1.0, 'Minh'),
        ('D5', DATE '2026-03-05', 'hoan_thanh', 50, 'hang', 'SP1', 'sp a', 'SP A', 1.0, 'Lan')
        ) t(order_id, order_date, status_norm, line_amount, line_type, product_id, product_key, product_name, qty_base,
            staff_name)""")
    con.execute("""CREATE TABLE _meta_tables AS SELECT 'lines' AS table_name, 'sales_lines' AS "role", 5 AS n_rows""")
    con.execute("CREATE TABLE _product_aliases (alias VARCHAR, product_name VARCHAR)")
    con.execute("CREATE TABLE _tet_periods (tet_year INT, start_date DATE, end_date DATE)")
    return con, Runner(con, T, Facts(con)).run


K = {"loai": "thang", "thang": 3, "nam": 2026}


def test_ba_cach_viet_la_mot_nhan_vien():
    con, run = _run()
    top = run({"nguon": "dong_ban", "phep": "tong", "cot": "tien", "ky": K, "nhom": "nhan_vien",
               "xep": {"chieu": "giam", "lay": 1}})
    assert to_record("q", top)["answer"] == "Lan"          # 350 (gom) > 250; tên đại diện = cách viết gặp nhiều nhất
    n = run({"nguon": "dong_ban", "phep": "dem_khac", "cot": "nhan_vien", "ky": K})
    assert n == 2
    t = Facts(con).table("dong_ban")
    assert con.execute(f'SELECT SUM(tien) FROM "{t}" WHERE nhan_vien = \'Lan\'').fetchone()[0] == 350


def test_nhom_theo_kenh_in_nhan_trong_so():
    con = duckdb.connect()
    con.execute("""CREATE TABLE lines AS SELECT * FROM (VALUES
        ('D1', DATE '2026-03-01', 'hoan_thanh', 100, 'hang', 'SP1', 'sp a', 'SP A', 1.0, 'Tại cửa hàng', 'tai_quay'),
        ('D2', DATE '2026-03-02', 'hoan_thanh', 100, 'hang', 'SP1', 'sp a', 'SP A', 1.0, 'tại cửa hàng', 'tai_quay'),
        ('D3', DATE '2026-03-03', 'hoan_thanh', 100, 'hang', 'SP1', 'sp a', 'SP A', 1.0, 'Tại cửa hàng', 'tai_quay'),
        ('D4', DATE '2026-03-04', 'hoan_thanh', 50, 'hang', 'SP1', 'sp a', 'SP A', 1.0, 'Zalo', 'zalo')
        ) t(order_id, order_date, status_norm, line_amount, line_type, product_id, product_key, product_name, qty_base,
            channel, channel_norm)""")
    con.execute("""CREATE TABLE _meta_tables AS SELECT 'lines' AS table_name, 'sales_lines' AS "role", 4 AS n_rows""")
    con.execute("CREATE TABLE _product_aliases (alias VARCHAR, product_name VARCHAR)")
    con.execute("CREATE TABLE _tet_periods (tet_year INT, start_date DATE, end_date DATE)")
    run = Runner(con, T, Facts(con)).run
    bang = run({"nguon": "dong_ban", "phep": "tong", "cot": "tien", "ky": K, "nhom": "kenh", "cot_ra": "ca_hai"})
    rows = to_record("q", bang)["answer"]["rows"]
    assert rows == [["Tại cửa hàng", 300], ["Zalo", 50]]
    top = run({"nguon": "dong_ban", "phep": "tong", "cot": "tien", "ky": K, "nhom": "kenh", "xep": {"chieu": "giam", "lay": 2}})
    assert to_record("q", top)["answer"] == ["Tại cửa hàng", "Zalo"]
