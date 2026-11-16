"""Kiểm bộ chạy kế hoạch bằng đáp án train: mỗi câu bộ mẫu hiểu -> dịch sang kế hoạch -> chạy -> so đáp án.

    python -m datamate.query.regress ../train/train <thư mục DB> [--out examples.jsonl] [--shops ...]
--out: lưu các cặp (câu hỏi, kế hoạch, type) đã ra đúng đáp án: kho ví dụ cho LLM.
"""
import argparse
import datetime as dt
import json
import os
from collections import Counter, defaultdict

import duckdb

from datamate.query.facts import Facts
from datamate.query.from_kind import to_plan
from datamate.query.plan import PlanError, Runner
from datamate.tests.verify_answers import answer, parse_question, same


def check(value, gold) -> bool:
    """Đúng theo §9, tên nhận mọi cách viết (dict names) như bộ chấm."""
    if isinstance(value, dict) and "bang" in value:
        got = [{"names": a["names"], "id": a["id"], "a": b} for a, b in value["bang"]]
        return same(got, gold["answer"])
    if isinstance(value, list) and value and isinstance(value[0], dict):
        exp = gold["answer"]
        return isinstance(exp, list) and len(exp) == len(value) and all(same(v, e) for v, e in zip(value, exp))
    return same(value, gold["answer"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("split_root")
    ap.add_argument("split_out")
    ap.add_argument("--out")
    ap.add_argument("--shops", nargs="*")
    a = ap.parse_args()
    qs = [json.loads(l) for l in open(os.path.join(a.split_root, "questions.jsonl"), encoding="utf-8")]
    gold = {r["id"]: r for r in map(json.loads, open(os.path.join(a.split_root, "answers.jsonl"), encoding="utf-8"))}
    cons, facts, st, bad, good = {}, {}, defaultdict(Counter), [], []
    for q in qs:
        shop = q["business_id"]
        if a.shops and shop not in a.shops:
            continue
        today = dt.date.fromisoformat(q["as_of_date"])
        p = parse_question(q["question"], today)
        g = gold[q["id"]]
        if not p or g["type"] == "unanswerable":
            continue
        if shop not in cons:
            cons[shop] = duckdb.connect(os.path.join(a.split_out, shop, f"{shop}.duckdb"), read_only=True)
            facts[shop] = Facts(cons[shop])
        con = cons[shop]
        kind, (lo, hi) = p
        if isinstance(lo, tuple) and lo and lo[0] == "tet":
            r = con.execute("SELECT CAST(start_date AS DATE), CAST(end_date AS DATE) FROM _tet_periods "
                            "WHERE tet_year = ?", [lo[1]]).fetchone()
            if not r:
                continue
            lo, hi = r[0], min(r[1], hi)
        try:
            old = answer(con, kind, lo, hi)[0]
        except Exception:
            old = None
        old_ok = old is not None and same(old, g["answer"])
        st[kind]["cu_dung"] += old_ok
        try:
            tr = to_plan(con, kind, lo, hi)
        except Exception as e:
            print("LOI DICH", kind, type(e).__name__, str(e)[:120])
            tr = None
        if tr is None:
            st[kind]["chua_dich"] += 1
            continue
        plan, want = tr
        try:
            v = Runner(con, today, facts[shop]).run(plan)
            ok = check(v, g)
        except PlanError as e:
            v, ok = None, False
            why = str(e)
        except Exception as e:
            v, ok, why = f"LOI {type(e).__name__}: {str(e)[:150]}", False, ""
        st[kind]["dung" if ok else ("hoi_quy" if old_ok else ("trong" if v is None else "sai"))] += 1
        if ok:
            good.append({"id": q["id"], "shop": shop, "as_of_date": q["as_of_date"], "question": q["question"],
                         "kind": kind, "plan": plan, "want": want, "type": g["type"]})
        elif old_ok:
            bad.append(f"{shop} {kind} | {q['question'][:55]} | đáp án {str(g['answer'])[:28]} | mới {str(v)[:110]} "
                       f"{why if v is None else ''}")
    tot = Counter()
    for k, c in sorted(st.items()):
        tot.update(c)
        print(f"{k:<20} đúng {c['dung']:>4}  (cũ đúng {c['cu_dung']:>4})  hồi quy {c['hoi_quy']:>3}  sai {c['sai']:>3}  "
              f"trống {c['trong']:>3}  chưa dịch {c['chua_dich']:>3}")
    print("TỔNG", dict(tot))
    for b in bad[:40]:
        print("  ", b)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as fh:
            for e in good:
                fh.write(json.dumps(e, ensure_ascii=False, default=str) + "\n")


if __name__ == "__main__":
    main()
