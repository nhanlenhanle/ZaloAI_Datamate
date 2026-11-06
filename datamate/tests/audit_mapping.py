"""Đo mapping dự phòng (khi README không mô tả cột) bằng các shop CÓ mô tả cột.

Đáp án = tên chuẩn suy từ mô tả README (nguồn readme_col). Dự đoán = map lại cùng shop bằng
map_shop(use_readme=False): chỉ còn từ điển tên cột của shop khác + luật theo giá trị.
Đọc samples/*.csv và _columns.csv do run_all ghi.

    python -m datamate.tests.audit_mapping ../train/train/data "../solve data/train" --extra ../public_test/public_test/data
"""
import argparse
import glob
import os
import re
from collections import Counter

import pandas as pd

from datamate.loader.mapping import TableInput, build_name_dict, map_shop
from datamate.loader.parsers import fold
from datamate.loader.readme import parse_readme


def _none(vals):
    return [None if (isinstance(v, float) and v != v) else v for v in vals]


def load_inputs(shop_out: str) -> list[TableInput]:
    cols = pd.read_csv(os.path.join(shop_out, "_columns.csv"))
    out = []
    for table, g in cols.groupby("table", sort=False):
        path = os.path.join(shop_out, "samples", re.sub(r'[\\/:*?"<>|]+', "_", table) + ".csv")
        parsed, raw = pd.read_csv(path), pd.read_csv(path, dtype=str)
        columns = list(g.column)
        rawd = {c: _none(raw[c + "__raw"] if c + "__raw" in raw else raw[c]) for c in columns}
        pard = {c: _none(parsed[c]) for c in columns}
        out.append(TableInput(table, "", [], columns, dict(zip(g.column, g.kind)), rawd, pard))
    return out


def families(split_out: str, shops: list[str], threshold: float = 0.3) -> dict[str, str]:
    """Shop -> họ. Hai shop cùng họ nếu tập tên cột thật giống nhau (Jaccard >= threshold), gộp bắc cầu.
    Tên cột trùng là thứ duy nhất 'rò' qua từ điển tên cột, nên đo rò theo đúng tiêu chí đó."""
    cols = {s: {fold(c) for c in pd.read_csv(os.path.join(split_out, s, "_columns.csv")).column} for s in shops}
    parent = {s: s for s in shops}

    def find(s):
        while parent[s] != s:
            s = parent[s]
        return s
    for i, x in enumerate(shops):
        for y in shops[i + 1:]:
            if len(cols[x] & cols[y]) / max(len(cols[x] | cols[y]), 1) >= threshold:
                parent[find(x)] = find(y)
    return {s: find(s) for s in shops}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("split_dir")
    ap.add_argument("split_out")
    ap.add_argument("--extra", nargs="*", default=[])
    ap.add_argument("--leave", choices=["shop", "family"], default="shop",
                    help="từ điển tên cột bỏ README của chính shop, hay của cả họ shop")
    ap.add_argument("--llm", action="store_true", help="cột luật để trống hỏi LLM (cần DATAMATE_LLM_URL)")
    a = ap.parse_args()
    shops = sorted(s for s in os.listdir(a.split_dir) if os.path.isdir(os.path.join(a.split_dir, s)))
    readmes = {s: parse_readme(os.path.join(a.split_dir, s, "README.md")) for s in shops}
    extra = [parse_readme(p) for d in a.extra for p in glob.glob(os.path.join(d, "*", "README.md"))]
    fam = families(a.split_out, shops) if a.leave == "family" else {s: s for s in shops}
    if a.leave == "family":
        groups = {}
        for s, f in fam.items():
            groups.setdefault(f, []).append(s)
        print("Họ:", sorted(groups.values()))

    stats, wrong, missed, by_source = Counter(), [], Counter(), Counter()
    for shop in shops:
        shop_out = os.path.join(a.split_out, shop)
        gold = pd.read_csv(os.path.join(shop_out, "_mapping.csv"))
        gold = gold[gold.source == "readme_col"]
        if gold.empty:
            continue
        name_dict = build_name_dict([r for s, r in readmes.items() if fam[s] != fam[shop]] + extra)
        pred = map_shop(load_inputs(shop_out), None, name_dict, use_readme=False, use_llm=a.llm)
        for _, row in gold.iterrows():
            m = next(x for x in pred[row.table] if x.column == row.column)
            if m.canonical is None:
                stats["bỏ trống"] += 1
                missed[row.canonical] += 1
            elif m.canonical == row.canonical:
                stats["đúng"] += 1
                by_source[m.source] += 1
            else:
                stats["SAI"] += 1
                by_source["SAI " + str(m.source)] += 1
                wrong.append((shop, row.table, row.column, row.canonical, m.canonical, m.source))
    total = sum(stats.values())
    print(f"Cột có đáp án: {total}")
    for k in ("đúng", "SAI", "bỏ trống"):
        print(f"  {k:<9} {stats[k]:>5}  ({stats[k] / max(total, 1):.1%})")
    print("  đúng theo nguồn:", dict(by_source))
    print("\nMap SAI (shop, bảng, cột, đáp án, dự đoán, nguồn):")
    for w in wrong:
        print("  ", w)
    print("\nBỏ trống theo tên chuẩn:", dict(missed.most_common()))


if __name__ == "__main__":
    main()
