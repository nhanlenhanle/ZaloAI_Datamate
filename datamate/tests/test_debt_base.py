import duckdb
from datamate.tests.verify_answers import debt_sql, _debt_base


def _create_mock_db(with_rulebook_ghi_no=False, with_order_total_date=False):
    con = duckdb.connect()
    # payments
    con.execute("CREATE TABLE payments (order_id VARCHAR, payment_date DATE, payment_amount DOUBLE)")
    con.execute("INSERT INTO payments VALUES ('O1', '2025-01-05', 50.0), ('O2', '2025-01-06', 30.0)")

    if with_order_total_date:
        con.execute("CREATE TABLE orders (order_id VARCHAR, order_date DATE, order_total DOUBLE, status_norm VARCHAR)")
        con.execute("INSERT INTO orders VALUES ('O1', '2025-01-01', 200.0, 'hoan_thanh')")
    else:
        con.execute("""CREATE TABLE orders (
            order_id VARCHAR, order_time TIMESTAMP, status_norm VARCHAR,
            payment_norm VARCHAR, order_discount DOUBLE, shipping_fee DOUBLE
        )""")
        # O1: 100 - 10 + 5 = 95
        # O2: 50 - 0 + 0 = 50 (payment_norm = 'tien_mat')
        con.execute("""INSERT INTO orders VALUES
            ('O1', '2025-01-01 08:30:00', 'hoan_thanh', 'ghi_no', 10.0, 5.0),
            ('O2', '2025-01-02 09:00:00', 'hoan_thanh', 'tien_mat', 0.0, 0.0)
        """)
        con.execute("""CREATE TABLE sales_lines (
            order_id VARCHAR, line_amount DOUBLE, line_type VARCHAR
        )""")
        con.execute("""INSERT INTO sales_lines VALUES
            ('O1', 80.0, 'hang'), ('O1', 20.0, 'hang'), ('O1', 5.0, 'phi_giao'),
            ('O2', 50.0, 'hang')
        """)

    con.execute("CREATE TABLE _meta_tables (table_name VARCHAR, role VARCHAR, n_rows BIGINT)")
    con.execute("INSERT INTO _meta_tables VALUES ('payments', 'payments', 2), ('orders', 'orders', 2)")
    if not with_order_total_date:
        con.execute("INSERT INTO _meta_tables VALUES ('sales_lines', 'sales_lines', 4)")

    con.execute("CREATE TABLE _rulebook (seq INT, level INT, heading VARCHAR, path VARCHAR, text VARCHAR)")
    if with_rulebook_ghi_no:
        con.execute("INSERT INTO _rulebook VALUES (1, 1, 'Cong no', '4', 'Đơn tính vào nợ | đơn ghi nợ')")
    else:
        con.execute("INSERT INTO _rulebook VALUES (1, 1, 'Cong no', '4', 'Đơn tính vào nợ thông thường')")

    return con


def test_debt_base_calc_total(monkeypatch):
    monkeypatch.setenv("DATAMATE_NV2", "1")   # NV2 tắt mặc định
    # tổng = dòng - giảm + phí
    con = _create_mock_db(with_rulebook_ghi_no=False, with_order_total_date=False)
    sql = debt_sql(con)
    assert sql is not None
    # X = '2025-01-10'
    res = con.execute(sql, ['2025-01-10', '2025-01-10']).fetchall()
    # O1: tot = 80+20-10+5 = 95. pay = 50 -> owe = 45
    # O2: tot = 50 - 0 + 0 = 50. pay = 30 -> owe = 20
    rows = {r[0]: r[2] for r in res}
    assert rows['O1'] == 45.0
    assert rows['O2'] == 20.0
    con.close()


def test_debt_base_rulebook_ghi_no(monkeypatch):
    monkeypatch.setenv("DATAMATE_NV2", "1")   # NV2 tắt mặc định
    # có rulebook "ghi nợ" -> đơn tien_mat không vào nợ
    con = _create_mock_db(with_rulebook_ghi_no=True, with_order_total_date=False)
    sql = debt_sql(con)
    res = con.execute(sql, ['2025-01-10', '2025-01-10']).fetchall()
    order_ids = [r[0] for r in res]
    assert 'O1' in order_ids
    assert 'O2' not in order_ids
    con.close()


def test_debt_base_no_rulebook_ghi_no(monkeypatch):
    monkeypatch.setenv("DATAMATE_NV2", "1")   # NV2 tắt mặc định
    # không có rulebook đó -> đơn tien_mat vào nợ
    con = _create_mock_db(with_rulebook_ghi_no=False, with_order_total_date=False)
    sql = debt_sql(con)
    res = con.execute(sql, ['2025-01-10', '2025-01-10']).fetchall()
    order_ids = [r[0] for r in res]
    assert 'O1' in order_ids
    assert 'O2' in order_ids
    con.close()


def test_debt_base_legacy_orders(monkeypatch):
    monkeypatch.setenv("DATAMATE_NV2", "1")   # NV2 tắt mặc định
    # bảng đơn có order_total + order_date -> kết quả như code cũ
    con = _create_mock_db(with_rulebook_ghi_no=False, with_order_total_date=True)
    sql = debt_sql(con)
    res = con.execute(sql, ['2025-01-10', '2025-01-10']).fetchall()
    assert len(res) == 1
    assert res[0][0] == 'O1'
    # 200 - 50 = 150
    assert res[0][2] == 150.0
    con.close()

