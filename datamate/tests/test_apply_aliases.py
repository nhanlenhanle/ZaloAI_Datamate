import pandas as pd

from datamate.loader.build import Built, apply_aliases, collect_aliases


def _shop():
    cat = pd.DataFrame({"product_name": ["Hoa hồng đỏ Đà Lạt", "Cẩm chướng", "Hồng"],
                        "Tên gọi khác": ["Hồng đỏ, hong do DL", "CC", None]})
    cat_cols = [{"column": "product_name", "canonical": "product_name", "kind": "text"},
                {"column": "Tên gọi khác", "original": "Tên gọi khác", "canonical": None, "kind": "text"}]
    sales = pd.DataFrame({"product_name": ["Hồng đỏ", "hoa hồng đỏ đà lạt", "CC", "Hồng", "Lạ"]})
    sales["product_key"] = ["hong do", "hoa hong do da lat", "cc", "hong", "la"]
    sales["line_type"] = "hang"
    return [Built("danhmuc", "DanhMuc", "products", cat, cat_cols, ["DanhMuc"]),
            Built("sobanhang", "SoBanHang", "sales_lines", sales, [], ["SoBanHang"])]


def test_ten_goi_khac_quy_ve_ten_day_du():
    built = _shop()
    stats = apply_aliases(built, collect_aliases(built, None))
    df = built[1].df
    assert list(df["product_key"]) == ["hoa hong do da lat", "hoa hong do da lat", "cam chuong", "hong", "la"]
    assert df["product_full"].iloc[0] == "Hoa hồng đỏ Đà Lạt"
    assert stats == {"sobanhang": {"alias_hit": 2, "rows": 5}}


def test_khong_co_ten_goi_khac_thi_khong_doi():
    built = _shop()
    assert apply_aliases(built, collect_aliases(built[1:], None)) == {}
    assert "product_full" not in built[1].df.columns
