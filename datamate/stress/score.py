"""Chấm DB của một split bằng các SQL mẫu đã kiểm (tests/verify_answers.py), tách 3 loại:
đúng | sai (ra số khác đáp án: lỗi âm thầm, tệ nhất) | trống (DB không dựng được nguồn).
Câu đáp án 'unanswerable': DB không dựng được nguồn là đúng, ra số là sai.
Chỉ chấm câu mẫu SQL hiểu được, nên đo đúng lớp data, không đo phần hiểu câu hỏi.

    python -m datamate.stress.score "../solve data/stress/goc" "../solve data/stress/goc/out"
"""
import argparse
import datetime as dt
import json
import os
from collections import Counter

import duckdb

from datamate.tests.verify_answers import answer, out_of_sales_range, parse_question, same


def score_split(split_root: str, split_out: str) -> dict[str, Counter]:
    """shop -> Counter(dung, sai, trong)."""
    qs = [json.loads(l) for l in open(os.path.join(split_root, "questions.jsonl"), encoding="utf-8")]
    gold = {r["id"]: r for r in map(json.loads, open(os.path.join(split_root, "answers.jsonl"), encoding="utf-8"))}
    cons, out = {}, {}
    for q in qs:
        today = dt.date.fromisoformat(q["as_of_date"])
        p = parse_question(q["question"], today)
        if not p:
            continue
        kind, (lo, hi) = p
        shop, g = q["business_id"], gold[q["id"]]
        if shop not in cons:
            db = os.path.join(split_out, shop, f"{shop}.duckdb")
            cons[shop] = duckdb.connect(db, read_only=True) if os.path.exists(db) else None
        con = cons[shop]
        got = None
        if con is not None:
            try:
                if isinstance(lo, tuple) and lo[0] == "tet":
                    r = con.execute("SELECT CAST(start_date AS DATE), CAST(end_date AS DATE) FROM _tet_periods "
                                    "WHERE tet_year = ?", [lo[1]]).fetchone()
                    lo, hi = (r[0], min(r[1], hi)) if r else (None, None)
                got = answer(con, kind, lo, hi)[0] if lo else None
                if got is not None and out_of_sales_range(con, kind, lo, hi):
                    got = None
            except Exception:
                got = None
        c = out.setdefault(shop, Counter())
        if g["type"] == "unanswerable":
            c["dung" if got is None else "sai"] += 1
        elif got is None:
            c["trong"] += 1
        else:
            c["dung" if same(got, g["answer"]) else "sai"] += 1
    for con in cons.values():
        if con is not None:
            con.close()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("split_root")
    ap.add_argument("split_out")
    a = ap.parse_args()
    res = score_split(a.split_root, a.split_out)
    tot = sum(res.values(), Counter())
    for shop, c in sorted(res.items()):
        print(f"{shop}: đúng {c['dung']:>4}  sai {c['sai']:>3}  trống {c['trong']:>3}")
    print(f"TỔNG: đúng {tot['dung']}  sai {tot['sai']}  trống {tot['trong']}")


if __name__ == "__main__":
    main()
