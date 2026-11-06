"""Tìm dòng luật gần câu hỏi và kho ví dụ đọc định nghĩa."""
import json

from datamate.query.compose import RuleBank, _unwrap, near_rules, rule_rows

RULES = """## 1. Đơn hàng
| Luật | Mặc định |
|---|---|
| Đơn bị huỷ | đơn có trạng thái huỷ |
| Khách sỉ lẻ | **Khách quen** là khách có từ 5 đơn trong kỳ |
| Tỉ lệ đơn huỷ trong kỳ | phần trăm đơn huỷ trong mọi đơn đặt trong kỳ |
## 2. Từ ngữ
| Từ | Nghĩa |
|---|---|
| Bình quân ngày bán | doanh thu chia cho số ngày có đơn |"""


def test_rows_skip_table_headers():
    rows = rule_rows(RULES)
    assert len(rows) == 4
    assert not any(r.startswith("|---") or r.startswith("| Luật") or r.startswith("| Từ") for r in rows)


def test_near_rules_finds_term_without_accents():
    assert "Khách quen" in near_rules(RULES, "thang 3/2026 co may khach quen")[0]
    assert "Bình quân" in near_rules(RULES, "binh quan ngay ban thang 3 bn")[0]


def test_near_rules_empty_when_nothing_close():
    assert near_rules(RULES, "thời tiết hôm nay") == []


def test_near_rules_reads_abbreviations():
    assert near_rules("| Doanh thu ròng | doanh thu trừ chiết khấu |", "dthu rong thang 3") != []


def test_unwrap_drops_explanation_from_bare_plan():
    out = _unwrap({"cach_tinh": "cộng tiền", "nguon": "dong_ban", "phep": "tong", "cot": "tien", "ra": "number"})
    assert "cach_tinh" not in out["ke_hoach"]
    assert out["ra"] == "number"


def test_rule_bank_one_example_per_rule_and_skips(tmp_path):
    rows = [{"id": f"r{i}", "shop": s, "as_of_date": "2026-01-01", "question": q, "dong": d, "rule": r, "cach_tinh": "x", "plan": {"nguon": "dong_ban"}, "type": "number"}
            for i, (s, q, d, r) in enumerate([
                ("a", "Tháng 3 có bao nhiêu đơn lớn", "don_lon", "**Đơn lớn** là đơn từ 300.000"),
                ("b", "thang 4 co may don lon", "don_lon", "**Đơn lớn** là đơn từ 300.000"),
                ("c", "Tháng 3 có bao nhiêu khách mới", "khach_moi", "**Khách mới** là khách có đơn đầu tiên trong kỳ")])]
    p = tmp_path / "b.jsonl"
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    bank = RuleBank(str(p))
    got = bank.pick("tháng 5 có bao nhiêu đơn nhỏ", ["**Đơn nhỏ** là đơn dưới 100.000"], k=3)
    assert [e["dong"] for e in got] == ["don_lon", "khach_moi"]
    assert all(e["dong"] != "don_lon" for e in bank.pick("đơn lớn", [], skip_dong="don_lon"))
    assert all(e["shop"] != "a" for e in bank.pick("đơn lớn", [], skip_shop="a"))
