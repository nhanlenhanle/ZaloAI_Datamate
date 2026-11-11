"""So hai kết quả chạy và ghép hai đường giải."""
from datamate.query import hybrid
from datamate.query.hybrid import both, combine, same_value, solve_both


def name(*names, id=None):
    return {"names": list(names), "id": id or names[0]}


def test_numbers_within_tolerance():
    assert same_value(100, 100.0)
    assert same_value(12.345, 12.35)
    assert not same_value(100, 101)


def test_bool_is_not_number():
    assert same_value(True, True)
    assert not same_value(True, 1)
    assert not same_value(False, 0)


def test_names_match_any_spelling_or_id():
    assert same_value(name("Cà phê sữa", id="SP01"), name("ca phe sua"))
    assert same_value(name("Cà phê", id="SP01"), name("SP01"))
    assert not same_value(name("Cà phê đen"), name("Cà phê sữa"))
    assert same_value(name("Cà phê"), "ca phe")


def test_single_item_list_equals_item():
    assert same_value([5], 5)
    assert same_value(name("A"), [name("A")])


def test_list_keeps_order():
    assert same_value([1, 2], [1, 2])
    assert not same_value([1, 2], [2, 1])
    assert same_value([name("A"), name("B")], [name("a"), name("b")])


def test_dates():
    assert same_value("2026-05-01", "2026-05-01")
    assert not same_value("2026-05-01", "2026-05-02")


def test_table_ignores_row_order():
    t1 = {"bang": [[name("A"), 1], [name("B"), 2]]}
    t2 = {"bang": [[name("b"), 2], [name("a"), 1]]}
    assert same_value(t1, t2)
    assert not same_value(t1, {"bang": [[name("A"), 1], [name("B"), 3]]})


def test_combine_disagreement_blanks_only_when_cross_checking():
    j = {"loai": "tra_loi", "value": 5, "want": None, "notes": []}
    s = {"loai": "tra_loi", "value": 6, "want": None, "notes": []}
    assert combine(j, s, cross_check=True)["loai"] == "khac_nhau"
    assert combine(j, s) is j


def test_combine_agreement_keeps_json_value():
    j = {"loai": "tra_loi", "value": 5, "want": "percent"}
    assert combine(j, {"loai": "tra_loi", "value": 5.0, "want": None}, cross_check=True) is j


def test_combine_sql_only_when_json_stuck():
    s = {"loai": "tra_loi", "value": 6, "want": None}
    assert combine({"loai": "loi"}, s)["value"] == 6
    assert combine({"loai": "khong_dong_thuan"}, s)["tang"] == "sql"


def test_combine_keeps_json_unanswerable():
    s = {"loai": "tra_loi", "value": 6, "want": None}
    assert combine({"loai": "thieu_nguon"}, s)["loai"] == "thieu_nguon"
    assert combine({"loai": "ngoai_ky"}, s)["loai"] == "ngoai_ky"


def test_combine_both_stuck_keeps_json_outcome():
    j = {"loai": "loi"}
    assert combine(j, {"loai": "khong_dong_thuan"}) is j


def test_solve_both_hoi_dung_duong_can_hoi(monkeypatch):
    calls = []

    def fake(tier, out):
        def f(*a, **k):
            calls.append(tier)
            return dict(out)
        return f
    monkeypatch.setattr(hybrid, "solve", fake("j", {"loai": "khong_dong_thuan"}))
    monkeypatch.setattr(hybrid, "solve_sql", fake("s", {"loai": "tra_loi", "value": 5}))
    assert solve_both(None, {}, None, policy="sql")["tang"] == "sql" and calls == ["s"]
    calls.clear()
    assert solve_both(None, {}, None, policy="bi_thi_json")["value"] == 5 and calls == ["s"]
    calls.clear()
    assert solve_both(None, {}, None, policy="bi_thi_sql")["value"] == 5 and calls == ["j", "s"]
    monkeypatch.setattr(hybrid, "solve_sql", fake("s", {"loai": "loi"}))
    monkeypatch.setattr(hybrid, "solve", fake("j", {"loai": "tra_loi", "value": 7}))
    calls.clear()
    assert solve_both(None, {}, None, policy="bi_thi_json")["value"] == 7 and calls == ["s", "j"]


def test_both_trung_thi_nop_khac_thi_theo_do_quen():
    j = {"loai": "tra_loi", "value": 5, "want": "percent"}
    s = {"loai": "tra_loi", "value": 6, "want": None}
    assert both(j, {**s, "value": 5.0}, familiar=False) is j
    assert both(j, s, familiar=True) is j
    r = both(j, s, familiar=False)
    assert r["value"] == 6 and r["tang"] == "sql"


def test_both_mot_duong_tra_loi_thi_lay_duong_do():
    j = {"loai": "tra_loi", "value": 5}
    s = {"loai": "tra_loi", "value": 6}
    assert both(j, {"loai": "loi"}, familiar=False) is j
    assert both({"loai": "khong_dong_thuan"}, s, familiar=True)["value"] == 6
    assert both({"loai": "loi"}, s, familiar=True)["tang"] == "sql"
    # đường kia nói shop không có dữ liệu: hai đường hiểu câu khác nhau -> bỏ trống (T2)
    for miss in ("thieu_nguon", "ngoai_ky", "llm_khong_co"):
        assert both(j, {"loai": miss}, familiar=False)["loai"] == "khong_chac"
        assert both({"loai": miss}, s, familiar=True)["loai"] == "khong_chac"


def test_both_khong_duong_nao_tra_loi():
    assert both({"loai": "thieu_nguon"}, {"loai": "ngoai_ky"}, familiar=False)["loai"] == "thieu_nguon"
    r = both({"loai": "loi"}, {"loai": "thieu_nguon"}, familiar=True)
    assert r["loai"] == "thieu_nguon" and r["tang"] == "sql"
    assert both({"loai": "loi"}, {"loai": "khong_dong_thuan"}, familiar=True)["loai"] == "loi"


def test_ca_hai_luon_hoi_hai_duong(monkeypatch):
    import types
    calls = []

    def fake(tier, out):
        def f(*a, **k):
            calls.append(tier)
            return dict(out)
        return f
    monkeypatch.setattr(hybrid, "solve", fake("j", {"loai": "tra_loi", "value": 1}))
    monkeypatch.setattr(hybrid, "solve_sql", fake("s", {"loai": "tra_loi", "value": 2}))
    ctx = types.SimpleNamespace(names_in=lambda q: [], columns_described=lambda: True)
    for fam, value in ((0.9, 1), (0.1, 2)):
        bank = types.SimpleNamespace(familiarity=lambda q, names, skip_shop=None, fam=fam: fam)
        calls.clear()
        assert solve_both(ctx, {"question": "x"}, bank)["value"] == value
        assert calls == ["j", "s"]


def test_dinh_tuyen_cau_quen_hoi_ke_hoach_truoc_cau_la_hoi_sql_truoc(monkeypatch):
    import types
    calls = []

    def fake(tier, out):
        def f(*a, **k):
            calls.append(tier)
            return dict(out)
        return f
    monkeypatch.setattr(hybrid, "solve", fake("j", {"loai": "tra_loi", "value": 1}))
    monkeypatch.setattr(hybrid, "solve_sql", fake("s", {"loai": "tra_loi", "value": 2}))
    ctx = types.SimpleNamespace(names_in=lambda q: [], columns_described=lambda: True)
    for fam, first in ((0.9, "j"), (0.1, "s")):
        bank = types.SimpleNamespace(familiarity=lambda q, names, skip_shop=None, fam=fam: fam)
        calls.clear()
        solve_both(ctx, {"question": "x"}, bank, policy="dinh_tuyen")
        assert calls == [first]


def test_kho_luat_chi_lay_vi_du_tang_dung_duoc(tmp_path):
    import json
    from datamate.query.compose import RuleBank
    p = tmp_path / "luat.jsonl"
    rows = [{"id": "a", "shop": "s1", "dong": "x", "rule": "Đơn sỉ là đơn lớn", "question": "đơn sỉ tháng 5", "plan": None, "sql": "SELECT 1"},
            {"id": "b", "shop": "s1", "dong": "y", "rule": "Đơn sỉ là đơn lớn", "question": "đơn sỉ tháng 6", "plan": {"nguon": "don"}, "sql": None}]
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    bank = RuleBank(str(p))
    assert [e["id"] for e in bank.pick("đơn sỉ tháng 7", [], need="sql")] == ["a"]
    assert [e["id"] for e in bank.pick("đơn sỉ tháng 7", [], need="plan")] == ["b"]
    assert len(bank.pick("đơn sỉ tháng 7", [])) == 2
