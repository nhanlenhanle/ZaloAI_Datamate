"""Bảng so các lần build trên bộ shop lạ giả lập, chấm lại bằng SQL mẫu hiện tại (không build lại).

    python -m datamate.stress.report "../solve data/stress" rules_v2 llm_v2 [--holdout biz_107 biz_111 ...]
Mỗi ô: đúng / sai / trống. Điểm = đúng - sai (cách chấm có trừ điểm câu sai). --holdout: in thêm bảng chỉ các shop
đó (họ shop không góp vào dữ liệu fine-tune).
"""
import argparse
import os
from collections import Counter

from datamate.stress.mutate import MUTATIONS
from datamate.stress.score import score_split


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("tags", nargs="+")
    ap.add_argument("--holdout", nargs="*", default=[])
    a = ap.parse_args()
    res = {}
    for mut in MUTATIONS:
        for tag in a.tags:
            out = os.path.join(a.root, mut, f"out_{tag}", mut)
            if os.path.isdir(out):
                res[(mut, tag)] = score_split(os.path.join(a.root, mut), out)
    for title, keep in (("tất cả shop", None), ("shop giữ riêng", set(a.holdout) or None)):
        if title == "shop giữ riêng" and not keep:
            continue
        print(f"\n== {title}")
        print(f"{'phép':<22}" + "".join(f"{t:>26}" for t in a.tags))
        tot = {t: Counter() for t in a.tags}
        for mut in MUTATIONS:
            cells = []
            for t in a.tags:
                r = res.get((mut, t))
                if r is None:
                    cells.append(f"{'-':>26}")
                    continue
                c = sum((v for s, v in r.items() if keep is None or s in keep), Counter())
                tot[t] += c
                cells.append(f"{c['dung']:>6}/{c['sai']:>4}/{c['trong']:>4}  ({c['dung'] - c['sai']:>5})")
            print(f"{mut:<22}" + "".join(cells))
        print(f"{'TỔNG':<22}" + "".join(f"{tot[t]['dung']:>6}/{tot[t]['sai']:>4}/{tot[t]['trong']:>4}  "
                                       f"({tot[t]['dung'] - tot[t]['sai']:>5})" for t in a.tags))


if __name__ == "__main__":
    main()
