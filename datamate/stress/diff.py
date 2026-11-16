"""So từng câu giữa hai lần build cùng một split (vd chỉ luật / có LLM): in các câu đổi kết quả.

    python -m datamate.stress.diff "../solve data/stress/goc" <out_a>/goc <out_b>/goc
"""
import argparse
import datetime as dt
import json
import os

import duckdb

from datamate.tests.verify_answers import answer, out_of_sales_range, parse_question, same


def results(split_root: str, split_out: str) -> dict[str, tuple]:
    """id câu -> (shop, loại câu, câu hỏi, đáp án, giá trị DB ra, đúng/sai/trống)."""
    qs = [json.loads(l) for l in open(os.path.join(split_root, "questions.jsonl"), encoding="utf-8")]
    gold = {r["id"]: r for r in map(json.loads, open(os.path.join(split_root, "answers.jsonl"), encoding="utf-8"))}
    cons, out = {}, {}
    for q in qs:
        p = parse_question(q["question"], dt.date.fromisoformat(q["as_of_date"]))
        if not p:
            continue
        kind, (lo, hi) = p
        shop, g = q["business_id"], gold[q["id"]]
        if shop not in cons:
            db = os.path.join(split_out, shop, f"{shop}.duckdb")
            cons[shop] = duckdb.connect(db, read_only=True) if os.path.exists(db) else None
        got = None
        if cons[shop] is not None:
            try:
                if isinstance(lo, tuple) and lo[0] == "tet":
                    r = cons[shop].execute("SELECT CAST(start_date AS DATE), CAST(end_date AS DATE) FROM "
                                           "_tet_periods WHERE tet_year = ?", [lo[1]]).fetchone()
                    lo, hi = (r[0], min(r[1], hi)) if r else (None, None)
                got = answer(cons[shop], kind, lo, hi)[0] if lo else None
                if got is not None and out_of_sales_range(cons[shop], kind, lo, hi):
                    got = None
            except Exception:
                got = None
        if g["type"] == "unanswerable":
            res = "dung" if got is None else "sai"
        else:
            res = "trong" if got is None else ("dung" if same(got, g["answer"]) else "sai")
        out[q["id"]] = (shop, kind, q["question"], g.get("answer", g["type"]), got, res)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("split_root")
    ap.add_argument("out_a")
    ap.add_argument("out_b")
    a = ap.parse_args()
    ra, rb = results(a.split_root, a.out_a), results(a.split_root, a.out_b)
    for qid in ra:
        x, y = ra[qid], rb.get(qid)
        if y and x[5] != y[5]:
            print(f"{x[0]} {x[1]:<14} {x[5]:>5} -> {y[5]:<5} | {x[2][:60]} | đáp án {str(x[3])[:30]} "
                  f"| A {str(x[4])[:30]} | B {str(y[4])[:30]}")


if __name__ == "__main__":
    main()
