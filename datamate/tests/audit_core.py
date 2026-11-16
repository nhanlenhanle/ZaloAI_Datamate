"""Mỗi shop: các cột lõi cho câu hỏi bán hàng đã có tên chuẩn ở ít nhất một bảng chưa?

    python -m datamate.tests.audit_core "../solve data/train"
"""
import glob
import os
import sys

import pandas as pd

CORE = ["order_id", "order_date", "status", "product_name", "product_id", "qty", "qty_base",
        "unit_price", "line_amount", "customer_name", "customer_id"]


def main(split_out: str):
    rows = []
    for p in sorted(glob.glob(os.path.join(split_out, "*", "_mapping.csv"))):
        m = pd.read_csv(p)
        have = set(m.canonical.dropna())
        row = {"shop": os.path.basename(os.path.dirname(p))}
        row.update({c: ("x" if c in have else "") for c in CORE})
        rows.append(row)
    df = pd.DataFrame(rows)
    pd.set_option("display.width", 220)
    print(df.to_string(index=False))
    print("\nThiếu:", {c: list(df.shop[df[c] == ""]) for c in CORE if (df[c] == "").any()})


if __name__ == "__main__":
    main(sys.argv[1])
