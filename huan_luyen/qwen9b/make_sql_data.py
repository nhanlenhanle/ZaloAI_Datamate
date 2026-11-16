"""Dữ liệu fine-tune tầng SQL (câu hỏi -> {"sql", "ra"}), đúng prompt đường SQL gửi (sql_tier._ask).

Lời giải SQL tự sinh: kế hoạch đúng của bộ sinh (loi_giai.jsonl, chỉ câu mà kế hoạch chạy ra đúng đáp án trong file chấm
kg_chay_kh.py) dịch sang một câu SQL trên các view v_* (plan_sql.to_sql), CHẠY LẠI qua đường SQL và so đáp án; chỉ giữ câu
khớp. Prompt lấy bằng cách thay llm.chat bằng hàm ghi lại (system, user) rồi gọi đúng sql_tier._ask với ví dụ chọn như
solve_sql. Chia theo shop như make_plan_data (--test-shops không vào tập huấn luyện).

    python -m datamate.finetune.make_sql_data --gen <bộ sinh> --gen-db <DB split> --gen-cham <kh.jsonl>
        --out <file.jsonl> --test-shops biz_801,... [--max-per-shop 40]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import random
from collections import Counter

import duckdb

from datamate.loader import llm
from datamate.query import sql_tier
from datamate.query.compose import RuleBank, ShopContext, clean_plan, naturalize, near_rules
from datamate.query.plan import PlanError, Runner
from datamate.query.plan_sql import NoSql, to_sql
from datamate.query.regress import check
from datamate.query.sql_tier import SqlBank, _attempt, _prepare
from datamate.query.telex import sua_q

AS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "docker", "assets")
if not os.path.isdir(AS):
    AS = "/app/assets"
_bat = {}


def _ghi(system, user, **kw):
    _bat["p"] = (system, user)
    return "{}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gen", required=True)
    ap.add_argument("--gen-db", required=True)
    ap.add_argument("--gen-cham", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--test-shops", default="")
    ap.add_argument("--max-per-shop", type=int, default=40)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    test = set(filter(None, a.test_shops.split(",")))
    rnd = random.Random(a.seed)
    sql_bank, rule_bank = SqlBank(f"{AS}/examples_sql_train.jsonl"), RuleBank(f"{AS}/examples_luat.jsonl")
    Q = {json.loads(l)["id"]: json.loads(l) for l in open(f"{a.gen}/questions.jsonl", encoding="utf-8") if l.strip()}
    G = {json.loads(l)["id"]: json.loads(l) for l in open(f"{a.gen}/answers.jsonl", encoding="utf-8") if l.strip()}
    L = {json.loads(l)["id"]: json.loads(l) for l in open(f"{a.gen}/loi_giai.jsonl", encoding="utf-8") if l.strip()}
    dung = {r["id"] for r in map(json.loads, open(a.gen_cham, encoding="utf-8")) if r["diem"] == 1}
    by_shop: dict[str, list] = {}
    for i, lg in L.items():
        if lg["ke_hoach"] and i in dung and lg["business_id"] not in test:
            by_shop.setdefault(lg["business_id"], []).append(lg)
    llm.chat = _ghi                      # chỉ lấy prompt, không gọi LLM
    n = Counter()
    with open(a.out, "w", encoding="utf-8") as fh:
        for s in sorted(by_shop):
            items = by_shop[s]
            rnd.shuffle(items)
            ctx = ShopContext(os.path.join(a.gen_db, s, f"{s}.duckdb"))
            _prepare(ctx)
            kept = 0
            for lg in items:
                if kept >= a.max_per_shop:
                    break
                q = sua_q(Q[lg["id"]])
                today = dt.date.fromisoformat(q["as_of_date"])
                plan = clean_plan(naturalize(lg["ke_hoach"], q["question"], today), q["question"])
                try:
                    sql, ra = to_sql(Runner(ctx.con, today, ctx.facts), plan)
                    t = lg.get("type")
                    ra = "percent" if t == "percent" else (t if t in ("list", "table", "date", "string", "boolean") else ra)
                    kind, _, _, v, _ = _attempt(ctx, {"sql": sql, "ra": ra}, q, today)
                except (NoSql, PlanError, KeyError, TypeError, ValueError, AttributeError, duckdb.Error):
                    n["khong_dich"] += 1
                    continue
                if kind != "tra_loi" or not check(v, G[lg["id"]]):
                    n["sai"] += 1
                    continue
                ex = sql_bank.pick(q["question"], ctx.names_in(q["question"]), skip_id=q["id"])
                rx = rule_bank.pick(q["question"], near_rules(ctx.rules, q["question"]), need="sql")
                sql_tier._ask(ctx, q, today, 0, examples=ex, rule_examples=rx)
                system, user = _bat["p"]
                fh.write(json.dumps({"id": lg["id"], "shop": s, "messages": [
                    {"role": "system", "content": system}, {"role": "user", "content": user},
                    {"role": "assistant", "content": json.dumps({"sql": sql, "ra": ra}, ensure_ascii=False)}]},
                    ensure_ascii=False, default=str) + "\n")
                kept += 1
                n["giu"] += 1
    print(dict(n))


if __name__ == "__main__":
    main()
