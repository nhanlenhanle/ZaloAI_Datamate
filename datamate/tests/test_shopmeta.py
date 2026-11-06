"""Test lịch, dịp Tết, rulebook, ngành."""
import pandas as pd

from datamate.loader.build import Built
from datamate.loader.readme import ReadmeInfo
from datamate.loader.shopmeta import infer_industry, parse_rulebook, tet_periods


def test_dip_tet_theo_rulebook():
    # Tết 2026: 23 tháng Chạp năm âm 2025 (10/02/2026) -> hết mùng 10 tháng Giêng năm âm 2026 (26/02/2026)
    cal = pd.DataFrame({"date": pd.to_datetime(["2026-02-10", "2026-02-17", "2026-02-26", "2025-01-22", "2025-02-07"]),
                        "lunar_day": [23, 1, 10, 23, 10], "lunar_month": [12, 1, 1, 12, 1],
                        "lunar_year": [2025, 2026, 2026, 2024, 2025], "lunar_leap": [False] * 5})
    t = tet_periods(cal).set_index("tet_year")
    assert str(t.loc[2026, "start_date"].date()) == "2026-02-10" and str(t.loc[2026, "end_date"].date()) == "2026-02-26"
    assert t.loc[2026, "days"] == 17 and 2025 in t.index


def test_cat_rulebook_theo_muc(tmp_path):
    (tmp_path / "rulebook.md").write_text("# Rulebook\n## 6. Theo ngành\n### Cà phê\n| a | b |\n### Sửa xe\nluật\n",
                                          encoding="utf-8")
    rb = parse_rulebook(str(tmp_path))
    assert rb.heading.tolist() == ["Rulebook", "6. Theo ngành", "Cà phê", "Sửa xe"]
    assert rb.path.iloc[2] == "Rulebook > 6. Theo ngành > Cà phê" and rb.text.iloc[3] == "luật"


def test_nganh_va_muc_rulebook(tmp_path):
    (tmp_path / "rulebook.md").write_text("# R\n## 6. Theo ngành\n### Cà phê\nx\n### Nhà thuốc\ny\n", encoding="utf-8")
    rb = parse_rulebook(str(tmp_path))
    sales = Built("s", "s", "sales_lines", pd.DataFrame({"product_name": ["Cà phê sữa (M)", "Bạc xỉu (L)", "Trà đào (M)"]}),
                  [], [])
    ind = infer_industry(ReadmeInfo("x"), [sales], rb)
    assert ind["industry"] == "Cà phê" and ind["rulebook_section"] == "Cà phê"
    drug = Built("t", "t", "drug_info", pd.DataFrame({"active_ingredient": ["Paracetamol"]}), [], [])
    assert infer_industry(ReadmeInfo("y"), [drug], rb)["industry"] == "Nhà thuốc"
    assert infer_industry(ReadmeInfo("z"), [], rb)["industry"] is None
