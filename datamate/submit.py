"""Tạo submission.jsonl từ DB sạch (bản nền: chỉ mẫu SQL đã kiểm trên train, tuỳ chọn thêm LLM viết SQL).

Mỗi câu: hiểu được dạng câu -> chạy SQL mẫu (tests/verify_answers.py) -> ghi đáp án đúng format §9.
DB thiếu hẳn nguồn (shop không ghi loại thông tin, kỳ nằm ngoài khoảng dữ liệu) -> "unanswerable" (§7).
Không hiểu câu -> "abstain" (0 điểm; trả lời sai bị -1). --llm: câu không hiểu thì hỏi LLM viết SQL.

    python -m datamate.submit ../train/train "../solve data/train" --out sub_train.jsonl --eval
    python -m datamate.submit ../public_test/public_test "../solve data/ban_nop/public_test_khong_llm" --out sub.jsonl
"""
import argparse
import datetime as dt
import json
import os
import re
import unicodedata
from collections import Counter

import duckdb

from datamate.loader.build import split_phone
from datamate.loader.parsers import fold
from datamate.tests.verify_answers import answer, out_of_sales_range, parse_question

PERCENT_KINDS = {"cancel_rate", "rx_rate", "group_share", "growth", "price_effect", "cust_min_orders"}
# Chỉ ghi unanswerable khi chắc theo DỮ LIỆU: kỳ hỏi nằm hoàn toàn ngoài khoảng ngày có đơn bán (§7).
# "SQL mẫu không dựng được" chỉ nghĩa là shop có cấu trúc mẫu chưa biết (sổ nợ riêng, sổ phiếu sửa xe...),
# không phải data thiếu -> bỏ trống (nộp thử public: 28/30 câu unanswerable kiểu này bị chấm sai, -1 mỗi câu)
_NO_SOURCE = re.compile(r"§7", re.I)


def _num(v):
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


def to_record(qid: str, kind: str, got, note: str, question: str) -> dict:
    """Giá trị từ SQL mẫu -> dòng nộp đúng format §9."""
    if got is None:
        if _NO_SOURCE.search(note or ""):
            return {"id": qid, "type": "unanswerable", "reason": note}
        return {"id": qid, "type": "abstain"}
    f = fold(question)
    if isinstance(got, dict):                               # tên: lấy cách viết trong file, không có thì mã
        names = [n for n in got.get("names", []) if n]
        return {"id": qid, "type": "string", "answer": str(names[0] if names else got.get("id"))}
    if isinstance(got, list) and got and isinstance(got[0], dict):     # bảng [tên, số]
        rows = [[str(([n for n in g["names"] if n] or [g["id"]])[0]), _num(round(g["a"]))] for g in got]
        return {"id": qid, "type": "table", "answer": {"columns": ["khach_hang", "so_tien_no"], "rows": rows}}
    if isinstance(got, list):
        return {"id": qid, "type": "list", "answer": [_num(v) for v in got]}
    if isinstance(got, str):
        if re.fullmatch(r"\d{4}-\d{2}(-\d{2})?", got):
            return {"id": qid, "type": "date", "answer": got}
        return {"id": qid, "type": "string", "answer": got}
    if isinstance(got, bool):
        return {"id": qid, "type": "boolean", "answer": got}
    pct = kind in PERCENT_KINDS or (kind == "rev_filter" and re.search(r"phan tram|%|\bchiem\b|\b(ti|ty) (le|trong)\b", f))
    if pct:
        return {"id": qid, "type": "percent", "answer": round(float(got), 2)}
    return {"id": qid, "type": "number", "answer": _num(got)}


# ---------------------------------------------------------------- tự chấm theo §9 (chỉ dùng trên train)

def _norm_name(s) -> str:
    # §9: không phân biệt hoa thường, khoảng trắng, dấu câu; dấu tiếng Việt phải đúng (cách viết khác nằm trong alias)
    return re.sub(r"[^\w]+", "", unicodedata.normalize("NFC", split_phone(str(s))[0]).lower())


def _val_eq(a, b) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        return abs(a - b) < 0.006
    if isinstance(a, str) and isinstance(b, str):
        return _norm_name(a) == _norm_name(b)
    return a == b


def _any_eq(a, g, alias) -> bool:
    # alias: các cách ghi khác được nhận (mã, cách viết khác trong file của shop), §9 "nhận mọi cách viết ... hoặc mã"
    return _val_eq(a, g) or any(_val_eq(a, x) for x in alias or [])


def score(rec: dict, gold: dict) -> int:
    """+1 đúng, -1 sai, 0 bỏ trống (§9). Đúng type rồi mới so giá trị."""
    t = rec["type"]
    if t == "abstain":
        return 0
    if t != gold["type"]:
        return -1
    if t == "unanswerable":
        return 1
    a, g = rec["answer"], gold["answer"]
    alias = gold.get("alias") or []
    if t == "list":
        if not (isinstance(g, list) and isinstance(a, list) and len(a) == len(g)):
            return -1
        alts = alias if len(alias) == len(g) else [[]] * len(g)     # alias[i]: cách ghi khác của phần tử i
        return 1 if all(_any_eq(x, y, al) for x, y, al in zip(a, g, alts)) else -1
    if t == "table":
        rows = g.get("rows", []) if isinstance(g, dict) else []
        alts = alias if len(alias) == len(rows) else [[]] * len(rows)  # alias[i]: cách ghi khác của tên dòng i
        ok = len(rows) == len(a["rows"]) and all(
            any(_any_eq(x[0], r[0], al) and all(_val_eq(u, v) for u, v in zip(r[1:], x[1:])) for x in a["rows"])
            for r, al in zip(rows, alts))
        return 1 if ok else -1
    if t == "string":
        return 1 if _any_eq(a, g, alias) else -1
    return 1 if _val_eq(a, g) else -1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("split_root", help="thư mục có questions.jsonl (và answers.jsonl nếu --eval)")
    ap.add_argument("split_out", help="thư mục chứa <shop>/<shop>.duckdb")
    ap.add_argument("--out", required=True, help="file submission.jsonl")
    ap.add_argument("--eval", action="store_true", help="tự chấm theo answers.jsonl (train)")
    ap.add_argument("--llm", action="store_true", help="tầng 2: câu bỏ trống hỏi LLM viết SQL (cần DATAMATE_LLM_URL)")
    ap.add_argument("--llm-sample", type=int, default=0, help="chỉ hỏi LLM N câu bỏ trống ngẫu nhiên (để đo)")
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args()
    qs = [json.loads(l) for l in open(os.path.join(a.split_root, "questions.jsonl"), encoding="utf-8")]
    cons, recs, kinds = {}, [], {}
    for q in qs:
        shop, today = q["business_id"], dt.date.fromisoformat(q["as_of_date"])
        p = parse_question(q["question"], today)
        if shop not in cons:
            db = os.path.join(a.split_out, shop, f"{shop}.duckdb")
            cons[shop] = duckdb.connect(db, read_only=True) if os.path.exists(db) else None
        con = cons[shop]
        if not p or con is None:
            recs.append({"id": q["id"], "type": "abstain"})
            kinds[q["id"]] = None
            continue
        kind, (lo, hi) = p
        try:
            if isinstance(lo, tuple) and lo[0] == "tet":
                r = con.execute("SELECT CAST(start_date AS DATE), CAST(end_date AS DATE) FROM _tet_periods "
                                "WHERE tet_year = ?", [lo[1]]).fetchone()
                lo, hi = (r[0], min(r[1], hi)) if r else (None, None)
            got, note = answer(con, kind, lo, hi) if lo else (None, "không có kỳ Tết")
            if got is not None and out_of_sales_range(con, kind, lo, hi):
                got, note = None, "kỳ nằm hoàn toàn ngoài khoảng ngày có đơn bán (§7)"
        except Exception as e:                       # SQL lỗi: không đoán
            got, note = None, f"lỗi {type(e).__name__}"
        recs.append(to_record(q["id"], kind, got, note, q["question"]))
        kinds[q["id"]] = kind
    via_llm = set()
    if a.llm:
        via_llm = run_llm(a, qs, recs)
    with open(a.out, "w", encoding="utf-8") as fh:
        for r in recs:
            r = {k: v for k, v in r.items() if k != "reason" or isinstance(v, str)}
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    types = Counter(r["type"] for r in recs)
    print(f"{len(recs)} câu -> {a.out}: {dict(types)}")
    if a.eval:
        gold = {r["id"]: r for r in map(json.loads, open(os.path.join(a.split_root, "answers.jsonl"), encoding="utf-8"))}
        sc = Counter()
        for r in recs:
            s = score(r, gold[r["id"]])
            sc[s] += 1
            if s < 0:
                sc[("sai", kinds[r["id"]], r["type"], gold[r["id"]]["type"])] += 1
        tot = sc[1] - sc[-1]
        print(f"điểm {tot} / {len(recs)}  (đúng {sc[1]}, sai {sc[-1]}, bỏ trống {sc[0]})")
        for k, v in sorted(((k, v) for k, v in sc.items() if isinstance(k, tuple)), key=lambda x: -x[1])[:15]:
            print("   sai:", k[1:], v)
        if via_llm:
            ls = Counter()
            for r in recs:
                if r["id"] in via_llm:
                    ls[(r["type"], score(r, gold[r["id"]]))] += 1
            ok, bad = sum(v for (t, s), v in ls.items() if s > 0), sum(v for (t, s), v in ls.items() if s < 0)
            print(f"tầng LLM: hỏi {len(via_llm)} câu -> đúng {ok}, sai {bad}, bỏ trống {len(via_llm) - ok - bad}")
            for t in sorted({t for t, _ in ls}):
                print(f"   {t:<13} đúng {ls[(t, 1)]:>3}  sai {ls[(t, -1)]:>3}")


def run_llm(a, qs, recs) -> set:
    """Tầng 2: các câu đang bỏ trống -> LLM viết SQL (song song, mỗi luồng một kết nối DB chỉ đọc)."""
    import random
    from concurrent.futures import ThreadPoolExecutor
    from datamate.llm_query import llm_answer

    todo = [i for i, r in enumerate(recs) if r["type"] == "abstain"]
    if a.llm_sample:
        random.Random(0).shuffle(todo)
        todo = sorted(todo[:a.llm_sample])

    def work(i):
        q = qs[i]
        db = os.path.join(a.split_out, q["business_id"], f"{q['business_id']}.duckdb")
        if not os.path.exists(db):
            return i, None, "không có db"
        con = duckdb.connect(db, read_only=True)
        try:
            return (i, *llm_answer(con, q["question"], dt.date.fromisoformat(q["as_of_date"]), {}))
        except Exception as e:
            return i, None, f"lỗi {type(e).__name__}"
        finally:
            con.close()
    done = set()
    with ThreadPoolExecutor(a.workers) as ex:
        for n, (i, rec, note) in enumerate(ex.map(work, todo), 1):
            if rec is not None:
                recs[i] = {"id": qs[i]["id"], **rec}
            done.add(qs[i]["id"])
            if n % 25 == 0:
                print(f"  LLM {n}/{len(todo)}", flush=True)
    return done


if __name__ == "__main__":
    main()
