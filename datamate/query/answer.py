"""Chạy hệ thống trên một bộ câu hỏi, ra file nộp. Không đọc đáp án.

    python -m datamate.query.answer <thư mục có questions.jsonl> <DB> --out answer.jsonl [--policy ca_hai] [--workers 8]
Ghi từng câu ngay khi xong: dừng giữa chừng thì câu chưa ghi tính là bỏ trống; chạy lại thì bỏ qua câu đã có.
Mỗi luồng một bộ kết nối DB (bảng tạm gắn với kết nối). Kết quả không phụ thuộc thứ tự câu hay số luồng: mỗi lần hỏi LLM
dùng nhiệt độ và seed cố định.
"""
import argparse
import datetime as dt
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from datamate.query.compose import ExampleBank, RuleBank, ShopContext, final_record, shape
from datamate.query.hybrid import POLICIES, solve_both
from datamate.query.sql_tier import SqlBank

_local = threading.local()


def _ctx(db_root: str, shop: str) -> ShopContext:
    cache = getattr(_local, "ctx", None)
    if cache is None:
        cache = _local.ctx = {}
    if shop not in cache:
        cache[shop] = ShopContext(os.path.join(db_root, shop, f"{shop}.duckdb"))
    return cache[shop]


def _bank(path: str | None, kind):
    return kind(path) if path and os.path.exists(path) else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("split_root")
    ap.add_argument("split_out")
    ap.add_argument("--out", required=True)
    ap.add_argument("--examples", default="../solve data/query/examples_train.jsonl")
    ap.add_argument("--luat-examples", default="../solve data/query/examples_luat.jsonl")
    ap.add_argument("--sql-examples", default="../solve data/query/examples_sql_train.jsonl")
    ap.add_argument("--policy", default="ca_hai", choices=POLICIES)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--han-giay", type=float, default=0,
                    help="quá số giây này (tính từ lúc bắt đầu) thì câu chưa bắt đầu ghi bỏ trống, không hỏi LLM (giữ trong giờ thi)")
    a = ap.parse_args()
    qs = [json.loads(l) for l in open(os.path.join(a.split_root, "questions.jsonl"), encoding="utf-8")]
    done = set()
    if os.path.exists(a.out):
        done = {json.loads(l)["id"] for l in open(a.out, encoding="utf-8") if l.strip()}
    todo = [q for q in qs if q["id"] not in done]
    bank = ExampleBank(a.examples)
    rule_bank, sql_bank = _bank(a.luat_examples, RuleBank), _bank(a.sql_examples, SqlBank)
    print(f"{len(todo)} câu (đã có {len(done)}), cách ghép {a.policy}, ví dụ dòng luật {'có' if rule_bank else 'không'}, "
          f"ví dụ SQL {'có' if sql_bank else 'không'}", flush=True)
    lock = threading.Lock()
    t0 = time.time()

    def work(q):
        if a.han_giay and time.time() - t0 > a.han_giay:
            return {"id": q["id"], "type": "abstain"}
        try:
            r = solve_both(_ctx(a.split_out, q["business_id"]), q, bank, sql_bank, rule_bank, policy=a.policy)
            return shape(q, final_record(q["id"], r))
        except OSError as e:        # mạng / server LLM: không ghi -> chạy lại thì làm lại câu này (lúc chấm run.sh ghi bỏ trống)
            print(f"mạng lỗi câu {q['id']}: {type(e).__name__}: {str(e)[:150]}", file=sys.stderr, flush=True)
            return None
        except Exception as e:      # một câu lỗi không được làm mất các câu sau
            print(f"lỗi câu {q['id']}: {type(e).__name__}: {str(e)[:150]}", file=sys.stderr, flush=True)
            return {"id": q["id"], "type": "abstain"}

    with ThreadPoolExecutor(a.workers) as ex, open(a.out, "a", encoding="utf-8") as fh:
        for i, rec in enumerate(ex.map(work, todo), 1):
            if rec is not None:
                with lock:
                    fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
                    fh.flush()
            if i % 25 == 0:
                print(f"  {i}/{len(todo)} {time.time() - t0:.0f}s {dt.datetime.now():%H:%M}", flush=True)
    print("XONG", flush=True)


if __name__ == "__main__":
    main()
