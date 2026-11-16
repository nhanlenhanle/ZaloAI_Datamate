"""Kiểm tra bước 1 (read_files + header) trên mọi shop của một split.

    python -m datamate.tests.inspect_step1 <thư mục data của split>
"""
import os
import sys
import time
from collections import Counter

from datamate.loader.header import load_tables
from datamate.loader.read_files import read_shop


def main(split_dir: str):
    t0 = time.time()
    for shop in sorted(os.listdir(split_dir)):
        d = os.path.join(split_dir, shop)
        if not os.path.isdir(d):
            continue
        t = time.time()
        tables, warns = load_tables(read_shop(d))
        print(f"\n### {shop}  ({time.time() - t:.1f}s)")
        for w in warns:
            print("  WARN", w)
        for tb in tables:
            reasons = Counter(r[2] for r in tb.dropped)
            extra = []
            if len(tb.sheets) > 1:
                extra.append(f"{len(tb.sheets)} sheets")
            if reasons:
                extra.append("bỏ " + ", ".join(f"{k}={v}" for k, v in reasons.items()))
            if tb.footnotes:
                extra.append(f"ghi chú={len(tb.footnotes)}")
            if tb.groups:
                extra.append("nhóm=" + "/".join(dict.fromkeys(tb.groups.values())))
            if tb.preamble:
                extra.append("preamble=" + repr(tb.preamble[:2]))
            unnamed = [c for c in tb.columns if c.startswith("col_")]
            if unnamed:
                extra.append(f"CỘT KHÔNG TÊN={unnamed}")
            print(f"  {tb.name:<40} {len(tb.rows):>7} dòng x {len(tb.columns):>2} cột  {'; '.join(extra)}")
    print(f"\nTổng thời gian: {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main(sys.argv[1])
