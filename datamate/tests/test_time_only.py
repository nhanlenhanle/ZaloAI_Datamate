import pandas as pd

from datamate.loader.build import join_time_only
from datamate.loader.mapping import _kind_ok, desc_to_canonical, time_only


def test_cot_chi_ghi_gio():
    assert time_only(["18:51", "7:05", "9h30", None, "21:00", "08:15:00"])
    assert not time_only(["18:51", "sáng", "chiều", "tối", "trưa"])
    assert _kind_ok("order_time", "text", ["18:51", "7:05", "9h30", "21:00", "08:15"])
    assert not _kind_ok("order_time", "text", ["a", "b", "c", "d", "e"])
    assert desc_to_canonical("giờ tạo đơn") == (True, "order_time")


def test_ghep_ngay_va_gio():
    df = pd.DataFrame({"order_date": pd.to_datetime(["2025-01-01", "2025-01-02", "2025-01-03"]),
                       "order_time": ["07:05", None, "18h51"]})
    cols = [{"column": "order_time", "kind": "text"}]
    assert join_time_only(df, cols) == 2
    assert df["order_time"].iloc[0] == pd.Timestamp("2025-01-01 07:05")
    assert pd.isna(df["order_time"].iloc[1]) and df["order_time"].iloc[2] == pd.Timestamp("2025-01-03 18:51")
    assert cols[0]["kind"] == "datetime"
    assert join_time_only(df, cols) == 0      # đã là ngày giờ thì thôi
