"""Chạy bộ shop lạ giả lập: mỗi phép -> tạo split -> run_all -> chấm, in bảng so với bản gốc.

    python -m datamate.stress.run ../train/train "../solve data/stress" --shops biz_101 biz_120 [--llm] [--tag rules]
Bản gốc ('goc') chạy cùng cách (cùng tập shop, cùng từ điển tên cột) để so công bằng.
"""
import argparse
import glob
import json
import os
import subprocess
import sys
import time
from collections import Counter

import pandas as pd

from datamate.loader import llm
from datamate.stress.mutate import MUTATIONS, make_split
from datamate.stress.score import score_split


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("train_root")
    ap.add_argument("out_root")
    ap.add_argument("--train-out", default="../solve data/train")
    ap.add_argument("--shops", nargs="+", required=True)
    ap.add_argument("--muts", nargs="*", default=list(MUTATIONS))
    ap.add_argument("--tag", default="rules", help="tên lần chạy (thư mục out_<tag>)")
    ap.add_argument("--llm", action="store_true")
    ap.add_argument("--reuse", action="store_true", help="dùng lại split đã tạo")
    a = ap.parse_args()
    rows = []
    for mut in a.muts:
        t0 = time.time()
        dst = os.path.join(a.out_root, mut)
        # mutation.json ghi sau cùng: có nó mới chắc split đã tạo xong
        if not (a.reuse and os.path.exists(os.path.join(dst, "mutation.json"))):
            make_split(a.train_root, a.train_out, a.out_root, mut, a.shops)
        out = os.path.join(dst, f"out_{a.tag}")
        if a.llm:          # LLM chết giữa chừng thì pipeline âm thầm chạy như chỉ có luật: dừng, không ghi số giả
            llm._post("/v1/models", None, 30)
        cmd = [sys.executable, "-m", "datamate.run_all", os.path.join(dst, "data"), "--out", out, "--skip-tables"]
        if a.llm:
            cmd.append("--llm")
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode:
            print(f"{mut}: run_all lỗi\n{r.stderr[-1500:]}", flush=True)
            continue
        if a.llm:
            n_err = sum(str(x).startswith("LLM lỗi") for f in glob.glob(os.path.join(out, mut, "*", "_mapping.csv"))
                        for x in pd.read_csv(f)["note"].dropna())
            if n_err:
                sys.exit(f"{mut}: {n_err} lời gọi LLM lỗi, kết quả không hợp lệ -> dừng")
        res = score_split(dst, os.path.join(out, mut))
        tot = sum(res.values(), Counter())
        rows.append({"mut": mut, **{k: tot[k] for k in ("dung", "sai", "trong")},
                     "per_shop": {s: dict(c) for s, c in res.items()}})
        print(f"{mut:<22} đúng {tot['dung']:>5}  sai {tot['sai']:>4}  trống {tot['trong']:>4}  "
              f"({time.time() - t0:.0f}s)", flush=True)
    with open(os.path.join(a.out_root, f"result_{a.tag}.json"), "w", encoding="utf-8") as fh:
        json.dump(rows, fh, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
