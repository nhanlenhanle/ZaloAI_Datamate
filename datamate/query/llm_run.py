"""Đo LLM ghép kế hoạch trên train (có đáp án). Mỗi câu ghi đủ: kết quả, cách quyết, loại kết thúc.

    python -m datamate.query.llm_run ../train/train <DB> --out r.jsonl --sample 300 [--mode thuong|giau_loai] [--shops ...]
giau_loai: không cho LLM ví dụ nào cùng dạng câu với câu đang hỏi (mô phỏng dòng rulebook mới của bộ khác).
Mọi chế độ đều không dùng ví dụ của chính shop đang hỏi và của các shop giữ riêng. Chạy dở thì chạy lại: bỏ qua câu đã có.
"""
import argparse
import datetime as dt
import json
import os
import random
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import duckdb

from datamate.query.compose import UNANSWERABLE, ExampleBank, RuleBank, ShopContext, solve
from datamate.query.evaluate import HOLDOUT
from datamate.query.plan import to_record
from datamate.query.regress import check
from datamate.query.sql_tier import SqlBank, solve_sql
from datamate.tests.verify_answers import parse_question

_local = threading.local()
_io = threading.Lock()


def _ctx(db_root: str, shop: str, extra_rules: str = "") -> ShopContext:
    cache = getattr(_local, "ctx", None)
    if cache is None:
        cache = _local.ctx = {}
    if shop not in cache:
        cache[shop] = ShopContext(os.path.join(db_root, shop, f"{shop}.duckdb"))
        if extra_rules:
            cache[shop].rules += "\n" + extra_rules
    return cache[shop]


def _industries(db_root: str) -> dict[str, str | None]:
    out = {}
    for shop in os.listdir(db_root):
        db = os.path.join(db_root, shop, f"{shop}.duckdb")
        if os.path.exists(db):
            con = duckdb.connect(db, read_only=True)
            out[shop] = con.execute("SELECT industry FROM _meta_shop").fetchone()[0]
            con.close()
    return out


def summarize(path: str) -> None:
    rows = [json.loads(l) for l in open(path, encoding="utf-8")]
    def line(name, rs):
        c = Counter(r["ket_qua"] for r in rs)
        n = len(rs)
        if n:
            print(f"{name:<24} đúng {c['dung']:>4}  sai {c['sai']:>4}  trống {c['trong']:>4}  "
                  f"điểm {(c['dung'] - c['sai']) / n:+.3f}  (n={n})")
    line("tất cả (chỉ nộp tra_loi)", rows)
    line("dev", [r for r in rows if r["shop"] not in HOLDOUT])
    line("shop giữ riêng", [r for r in rows if r["shop"] in HOLDOUT])
    line("mẫu regex hiểu", [r for r in rows if r["regex_hieu"]])
    line("mẫu regex KHÔNG hiểu", [r for r in rows if not r["regex_hieu"]])
    for t in sorted({r["gold_type"] for r in rows}):
        line(f"đáp án {t}", [r for r in rows if r["gold_type"] == t])
    print("kết thúc:", Counter(r["loai"] for r in rows).most_common())
    print("loại kết thúc x đáp án unanswerable:", Counter((r["loai"], r["gold_type"] == "unanswerable") for r in rows
                                                          if r["loai"] != "tra_loi").most_common())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("split_root")
    ap.add_argument("split_out")
    ap.add_argument("--out", required=True)
    ap.add_argument("--examples", default="../solve data/query/examples_train.jsonl")
    ap.add_argument("--sample", type=int, default=0)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--mode", default="thuong", choices=["thuong", "giau_loai"])
    ap.add_argument("--shops", nargs="*")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--temps", default="0,0.5,0.9", help="nhiệt độ các lần bỏ phiếu")
    ap.add_argument("--nganh-db", help="thư mục DB train đủ shop: không cho ví dụ từ shop cùng ngành với câu đang hỏi")
    ap.add_argument("--tang", default="json", choices=["json", "sql"], help="LLM lập kế hoạch JSON hay viết SQL")
    ap.add_argument("--luat", help="file đoạn rulebook thêm vào (bộ câu mô phỏng dòng luật mới, stress/new_rows.py)")
    ap.add_argument("--sql-examples", help="kho ví dụ SQL đã kiểm cho tầng SQL (query/plan_sql.py)")
    ap.add_argument("--luat-examples", help="kho ví dụ dòng luật -> kế hoạch (stress/rule_bank.py)")
    a = ap.parse_args()
    extra_rules = open(a.luat, encoding="utf-8").read() if a.luat else ""
    sql_bank = SqlBank(a.sql_examples) if a.sql_examples else None
    rule_bank = RuleBank(a.luat_examples) if a.luat_examples else None
    # bộ dòng luật mới: ví dụ không được là chính dòng đang hỏi
    meta_path = os.path.join(a.split_root, "meta.jsonl")
    dong = {r["id"]: r["dong"] for r in map(json.loads, open(meta_path, encoding="utf-8"))} if os.path.exists(meta_path) else {}
    qs = [json.loads(l) for l in open(os.path.join(a.split_root, "questions.jsonl"), encoding="utf-8")]
    gold = {r["id"]: r for r in map(json.loads, open(os.path.join(a.split_root, "answers.jsonl"), encoding="utf-8"))}
    if a.shops:
        qs = [q for q in qs if q["business_id"] in a.shops]
    random.Random(a.seed).shuffle(qs)
    if a.sample:
        qs = qs[:a.sample]
    done = set()
    if os.path.exists(a.out):
        done = {json.loads(l)["id"] for l in open(a.out, encoding="utf-8")}
    todo = [q for q in qs if q["id"] not in done]
    bank = ExampleBank(a.examples)
    temps = tuple(float(t) for t in a.temps.split(","))
    nganh = _industries(a.nganh_db) if a.nganh_db else {}
    print(f"{len(todo)} câu (đã có {len(done)}), {len(bank.items)} ví dụ", flush=True)

    def work(q):
        shop = q["business_id"]
        today = dt.date.fromisoformat(q["as_of_date"])
        # câu diễn đạt lại giữ câu gốc ở 'goc': dạng câu lấy từ câu gốc
        p = parse_question(q.get("goc", q["question"]), today)
        kinds = {p[0]} if (p and a.mode == "giau_loai") else None
        same = {s for s, i in nganh.items() if i == nganh.get(shop)} if nganh.get(shop) else None
        g = gold[q["id"]]
        try:
            ctx = _ctx(a.split_out, shop, extra_rules)
            if a.tang == "sql":
                r = solve_sql(ctx, q, temps=temps, bank=sql_bank, skip_shop=shop, skip_kinds=kinds, skip_shops=same, rule_bank=rule_bank,
                              skip_dong=dong.get(q["id"]))
            else:
                r = solve(ctx, q, bank, skip_shop=shop, skip_kinds=kinds, temps=temps, skip_shops=same, rule_bank=rule_bank,
                          skip_dong=dong.get(q["id"]))
        except Exception as e:      # mạng / server lỗi: ghi lại để chạy lại, không tính là bỏ trống
            return None, f"{type(e).__name__}: {str(e)[:120]}"
        rec = {"id": q["id"], "shop": shop, "question": q["question"], "gold_type": g["type"], "gold": g.get("answer"),
               "regex_hieu": bool(p), "kind": p[0] if p else None, "loai": r["loai"], "notes": r.get("notes"),
               "plan": r.get("plan")}
        if r["loai"] == "tra_loi":
            try:
                ok = g["type"] != "unanswerable" and check(r["value"], g)
            except Exception:
                ok = False
            rec.update(ket_qua="dung" if ok else "sai", tra_loi=to_record(q["id"], r["value"], r["want"]))
        elif r["loai"] in UNANSWERABLE:
            rec.update(ket_qua="dung" if g["type"] == "unanswerable" else "sai", tra_loi={"id": q["id"], "type": "unanswerable"})
        else:
            rec["ket_qua"] = "trong"
        return rec, None
    errs = Counter()
    with ThreadPoolExecutor(a.workers) as ex, open(a.out, "a", encoding="utf-8") as fh:
        for i, (rec, err) in enumerate(ex.map(work, todo), 1):
            if rec is None:
                errs[err[:60]] += 1
                if sum(errs.values()) >= 20:
                    print("Lỗi gọi LLM liên tục, dừng:", errs.most_common(3), flush=True)
                    break
                continue
            with _io:
                fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
                fh.flush()
            if i % 25 == 0:
                print(f"  {i}/{len(todo)}", flush=True)
    if errs:
        print("lỗi:", errs.most_common(5))
    summarize(a.out)


if __name__ == "__main__":
    main()
