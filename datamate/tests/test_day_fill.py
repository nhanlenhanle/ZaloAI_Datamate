import pandas as pd

from datamate.loader.build import fill_day_dates


def _df(dates, sheet="T1"):
    return pd.DataFrame({"_src_file": "f", "_src_sheet": sheet, "order_id": [f"HD{i}" for i in range(len(dates))],
                         "order_date": pd.to_datetime(dates)})


def test_ngay_ghi_mot_lan_cho_ca_ngay_duoc_dien_xuong():
    days = []
    for d in range(1, 13):
        days += [f"2026-01-{d:02d}", None, None]
    df = _df(days)
    assert fill_day_dates(df, "order_date") == 24
    assert df["order_date"].isna().sum() == 0
    assert df["order_date"].iloc[2] == pd.Timestamp("2026-01-01")


def test_khong_dien_khi_ngay_khong_di_len():
    days = []
    for d in [5, 1, 9, 2, 8, 3, 7, 4, 6, 10, 12, 11]:
        days += [f"2026-01-{d:02d}", None]
    df = _df(days)
    assert fill_day_dates(df, "order_date") == 0


def test_khong_dien_khi_it_o_trong():
    df = _df([f"2026-01-{d:02d}" for d in range(1, 29)] + [None])
    assert fill_day_dates(df, "order_date") == 0


def test_khong_dien_tran_qua_sheet():
    a = _df([f"2026-01-{d:02d}" if d % 2 else None for d in range(1, 25)], "T1")
    b = _df([None] + [f"2026-02-{d:02d}" for d in range(1, 12)], "T2")
    df = pd.concat([a, b], ignore_index=True)
    fill_day_dates(df, "order_date")
    assert pd.isna(df["order_date"].iloc[24])
