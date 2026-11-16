"""Dữ liệu fine-tune tầng KẾ HOẠCH (câu hỏi -> {"ke_hoach", "ra"}), đúng prompt pipeline gửi (compose.prompt).

Nguồn:
  - bộ sinh có lời giải (questions / answers / loi_giai.jsonl): chỉ lấy câu mà kế hoạch đúng chạy
    trên DB của mình ra ĐÚNG đáp án (file chấm của kg_chay_kh.py, diem = 1), và câu "không trả lời được" (khong_co).
  - kho ví dụ train BTC (docker/assets/examples_train.jsonl) trên DB train: giữ kiểu shop BTC, ví dụ trong prompt bỏ
    chính shop đó (như lúc đo bỏ-một-shop).
Chia theo SHOP: --test-shops (danh sách) không vào tập huấn luyện; ra file test riêng để đo.
Kỳ trong đáp án viết lại theo cách nói của câu (compose.naturalize), như kho ví dụ đưa cho LLM.

    python -m datamate.finetune.make_plan_data --gen <bộ sinh> --gen-db <DB split bộ sinh> --gen-cham <kh.jsonl>
        --train-db <DB split train BTC> --out <thư mục> --test-shops biz_801,... [--max-gen-per-shop 60]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import random
from collections import Counter

from datamate.query.compose import ExampleBank, RuleBank, ShopContext, naturalize, near_rules, prompt
from datamate.query.telex import sua_q

AS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "docker", "assets")


def doc(p):
    return {json.loads(l)["id"]: json.loads(l) for l in open(p, encoding="utf-8") if l.strip()}


def mot(ctx, q, target, bank, rule_bank, skip_shop=None):
    q = sua_q(q)
    today = dt.date.fromisoformat(q["as_of_date"])
    ex = bank.pick(q["question"], ctx.names_in(q["question"]), skip_shop=skip_shop, skip_id=q["id"])
    rx = rule_bank.pick(q["question"], near_rules(ctx.rules, q["question"]), skip_shop=skip_shop, need="plan")
    system, user = prompt(ctx, q, ex, today, rx)
    return {"messages": [{"role": "system", "content": system}, {"role": "user", "content": user},
                         {"role": "assistant", "content": json.dumps(target, ensure_ascii=False)}]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gen", required=True)
    ap.add_argument("--gen-db", required=True)
    ap.add_argument("--gen-cham", required=True)
    ap.add_argument("--train-db")
    ap.add_argument("--out", required=True)
    ap.add_argument("--test-shops", required=True)
    ap.add_argument("--max-gen-per-shop", type=int, default=60)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    rnd = random.Random(a.seed)
    test = set(a.test_shops.split(","))
    bank = ExampleBank(f"{AS}/examples_train.jsonl")
    rule_bank = RuleBank(f"{AS}/examples_luat.jsonl")
    Q, G, L = doc(f"{a.gen}/questions.jsonl"), doc(f"{a.gen}/answers.jsonl"), doc(f"{a.gen}/loi_giai.jsonl")
    dung = {r["id"] for r in map(json.loads, open(a.gen_cham, encoding="utf-8")) if r["diem"] == 1}
    os.makedirs(a.out, exist_ok=True)
    by_shop: dict[str, list] = {}
    for i, lg in L.items():
        g = G[i]
        if lg["ke_hoach"] and i in dung:
            today = dt.date.fromisoformat(Q[i]["as_of_date"])
            tgt = {"ke_hoach": naturalize(lg["ke_hoach"], Q[i]["question"], today), "ra": lg["type"]}
        elif g["type"] == "unanswerable":
            tgt = {"khong_co": "sổ của shop không ghi thông tin câu hỏi cần"}
        else:
            continue
        by_shop.setdefault(lg["business_id"], []).append((i, tgt, lg["ho"]))
    n, ho = Counter(), Counter()
    ctxs = {}
    with open(f"{a.out}/train.jsonl", "w", encoding="utf-8") as tr, open(f"{a.out}/test_ids.txt", "w") as te:
        for s in sorted(by_shop):
            items = by_shop[s]
            if s in test:
                te.writelines(f"{i}\n" for i, _, _ in items)
                continue
            rnd.shuffle(items)
            # đều theo họ câu: mỗi họ tối đa max/31 + 2 câu một shop
            per, keep = Counter(), []
            for it in items:
                if per[it[2]] < max(2, a.max_gen_per_shop // 31 + 1) and len(keep) < a.max_gen_per_shop:
                    keep.append(it)
                    per[it[2]] += 1
            ctx = ctxs.setdefault(s, ShopContext(os.path.join(a.gen_db, s, f"{s}.duckdb")))
            for i, tgt, h in keep:
                tr.write(json.dumps(mot(ctx, Q[i], tgt, bank, rule_bank), ensure_ascii=False) + "\n")
                n["gen"] += 1
                ho[h] += 1
        if a.train_db:
            for e in bank.items:
                s = e["shop"]
                ctx = ctxs.setdefault(s, ShopContext(os.path.join(a.train_db, s, f"{s}.duckdb")))
                q = {"id": e["id"], "business_id": s, "question": e["question"], "as_of_date": e["as_of_date"]}
                tr.write(json.dumps(mot(ctx, q, {"ke_hoach": e["nplan"], "ra": e["type"]}, bank, rule_bank, skip_shop=s),
                                    ensure_ascii=False) + "\n")
                n["train_btc"] += 1
    print(dict(n), "họ:", dict(ho.most_common()))


if __name__ == "__main__":
    main()
