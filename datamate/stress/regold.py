"""Tính lại đáp án các dòng luật đã sửa hàm đáp án, giữ nguyên câu hỏi; câu thành đồng hạng thì bỏ khỏi bộ. Chấm lại các file kết quả đã chạy
theo đáp án mới (không gọi LLM).

    python -m datamate.stress.regold <thư mục bộ câu> <DB> --bo 1 --dong tai_xe xe --ket-qua a.jsonl b.jsonl
"""
from __future__ import annotations

import argparse
import json
import os
import re

from datamate.query.regress import check
from datamate.stress.new_rows import ROWS, ROWS2, ROWS3, Ctx, Missing, Skip


def _load(path):
    return [json.loads(line) for line in open(path, encoding="utf-8")]


def _save(path, rows):
    with open(path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")


def _ok(sub: dict, g: dict) -> bool:
    """Dòng nộp (định dạng §9) có đúng đáp án không."""
    if g["type"] == "unanswerable":
        return sub.get("type") == "unanswerable"
    a = sub.get("answer")
    if sub.get("type") == "string":
        a = {"names": [a], "id": a}
    try:
        return check(a, g)
    except Exception:
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("split")
    ap.add_argument("db_root")
    ap.add_argument("--bo", type=int, required=True, choices=[1, 2, 3])
    ap.add_argument("--dong", nargs="+", required=True)
    ap.add_argument("--ket-qua", nargs="*", default=[])
    a = ap.parse_args()
    rows = {r.key: r for r in {1: ROWS, 2: ROWS2, 3: ROWS3}[a.bo]}
    qs, ans, meta = (_load(os.path.join(a.split, f"{n}.jsonl")) for n in ("questions", "answers", "meta"))
    dong = {m["id"]: m["dong"] for m in meta}
    gold = {g["id"]: g for g in ans}
    ctxs: dict = {}
    drop, changed = set(), 0
    for q in qs:
        key = dong[q["id"]]
        if key not in a.dong:
            continue
        s = q["business_id"]
        c = ctxs.setdefault(s, Ctx(os.path.join(a.db_root, s, f"{s}.duckdb")))
        mm = re.match(r"r_\w+_biz_\d+_(\d+)_(\d+)$", q["id"])
        try:
            g = {"id": q["id"], "type": rows[key].kind, "answer": rows[key].gold(c, int(mm[1]), int(mm[2]), None)}
        except Skip:
            drop.add(q["id"])
            continue
        except Missing:
            g = {"id": q["id"], "type": "unanswerable", "answer": None}
        changed += g != gold[q["id"]]
        gold[q["id"]] = g
    _save(os.path.join(a.split, "questions.jsonl"), [q for q in qs if q["id"] not in drop])
    _save(os.path.join(a.split, "answers.jsonl"), [gold[g["id"]] for g in ans if g["id"] not in drop])
    _save(os.path.join(a.split, "meta.jsonl"), [m for m in meta if m["id"] not in drop])
    print(f"đổi đáp án {changed} câu, bỏ {len(drop)} câu đồng hạng")
    for path in a.ket_qua:
        res = [r for r in _load(path) if r["id"] not in drop]
        for r in res:
            if dong[r["id"]] in a.dong and r["ket_qua"] != "trong":
                g = gold[r["id"]]
                r["gold_type"], r["gold"] = g["type"], g.get("answer")
                r["ket_qua"] = "dung" if _ok(r.get("tra_loi") or {}, g) else "sai"
        _save(path, res)
        print(os.path.basename(path), "chấm lại xong")


if __name__ == "__main__":
    main()
