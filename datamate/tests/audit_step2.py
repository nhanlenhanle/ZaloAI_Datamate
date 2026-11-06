"""Soát kết quả bước 2 từ các file _columns.csv và tables/*.csv đã ghi.

    python -m datamate.tests.audit_step2 "../solve data/train"
"""
import glob
import os
import re
import sys

import pandas as pd

from datamate.loader.parsers import fold, norm_status

STATUS_COL = re.compile(r"trang thai|status|xu ly|ket qua|tinh trang|tien do|ghi chu tt|tt don")
NOT_ORDER = re.compile(r"hddt|khach|phieu|giao$|thiet bi")  # trạng thái hoá đơn điện tử, khách, phiếu nhập...


def main(split_out: str):
    pd.set_option("display.width", 250)
    pd.set_option("display.max_colwidth", 60)
    cols = pd.concat([pd.read_csv(f).assign(shop=os.path.basename(os.path.dirname(f)))
                      for f in sorted(glob.glob(os.path.join(split_out, "*", "_columns.csv")))])
    print("== kiểu cột:", cols.kind.value_counts().to_dict())

    print("\n== cột có ô không parse được")
    bad = cols[cols.n_fail > 0]
    print(bad[["shop", "table", "column", "kind", "n", "n_fail", "fail_examples"]].to_string(index=False) if len(bad) else "  (không có)")

    print("\n== cột số có chữ đơn vị đi kèm (phải là số lượng)")
    u = cols[cols.units.notna()]
    print(u[["shop", "table", "column", "units"]].to_string(index=False) if len(u) else "  (không có)")

    print("\n== cột tên gợi ý ngày nhưng KHÔNG thành ngày")
    hint = cols[cols.column.map(lambda c: bool(re.search(r"ngay|thoi gian|date|\bhan\b|hsd|sinh nhat|ngay sinh", fold(c))))
                & (cols.kind != "datetime") & (cols.kind != "empty")]
    print(hint[["shop", "table", "column", "kind", "samples"]].to_string(index=False) if len(hint) else "  (không có)")

    print("\n== cột ngày ghi tháng trước (mm/dd)")
    mf = cols[cols.month_first.fillna(False).astype(bool)]
    print(mf[["shop", "table", "column", "samples"]].to_string(index=False) if len(mf) else "  (không có)")

    print("\n== chuẩn hoá trạng thái đơn: giá trị không nhận ra")
    unknown = {}
    for _, r in cols[cols.kind == "text"].iterrows():
        f = fold(r.column)
        if not STATUS_COL.search(f) or NOT_ORDER.search(f):
            continue
        path = os.path.join(split_out, r.shop, "tables", re.sub(r'[\\/:*?"<>|]+', "_", r.table) + ".csv")
        vals = pd.read_csv(path, usecols=[r.column], dtype=str)[r.column].dropna().value_counts()
        for v, n in vals.items():
            if norm_status(v) is None:
                unknown.setdefault((r.shop, r.table, r.column), []).append(f"{v}({n})")
    for k, v in unknown.items():
        print(" ", k, v[:8])
    if not unknown:
        print("  (không có)")


if __name__ == "__main__":
    main(sys.argv[1])
