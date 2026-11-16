"""Chấm câu trả lời của model gốc / model fine-tune (kiem_ra.jsonl) bằng đúng đường pipeline: tách JSON (_unwrap), chạy kế
hoạch trên DB (_attempt), dòng nộp, so đáp án. In kiểu lỗi và vài câu trả lời của model gốc.
python cham_kiem_ft.py <kiem_ra.jsonl> <DB gen_train>"""
import collections
import datetime as dt
import json
import sys

import os
sys.path.insert(0, os.environ.get("DATAMATE_ROOT", "/app"))
sys.stdout.reconfigure(encoding="utf-8")
from datamate.query.compose import ShopContext, _attempt, _unwrap, _want, final_record, shape  # noqa: E402
from datamate.submit import score  # noqa: E402

ra, db = sys.argv[1], sys.argv[2]
B = sys.argv[3] if len(sys.argv) > 3 else os.environ.get("GEN_DIR", "/tmp/gen_train")
Q = {json.loads(l)["id"]: json.loads(l) for l in open(f"{B}/questions.jsonl", encoding="utf-8")}
G = {json.loads(l)["id"]: json.loads(l) for l in open(f"{B}/answers.jsonl", encoding="utf-8")}


def doc_json(text):
    s = text.find("{")
    if s < 0:
        return None, "không có JSON"
    try:
        out, _ = json.JSONDecoder().raw_decode(text, s)
    except json.JSONDecodeError:
        return None, "JSON hỏng"
    return (_unwrap(out) if isinstance(out, dict) else None), None


kq = {m: collections.Counter() for m in ("lora", "goc")}
loai = {m: collections.Counter() for m in ("lora", "goc")}
mau = []
ctxs = {}
for l in open(ra, encoding="utf-8"):
    r = json.loads(l)
    q = Q[r["id"]]
    ctx = ctxs.setdefault(r["shop"], ShopContext(f"{db}/{r['shop']}/{r['shop']}.duckdb"))
    today = dt.date.fromisoformat(q["as_of_date"])
    for m in ("lora", "goc"):
        out, err = doc_json(r[m])
        if out is None:
            loai[m][err] += 1
            kq[m][0] += 1
            continue
        k, detail, plan, v = _attempt(ctx, out, today, q["question"])
        rec = shape(q, final_record(r["id"], {"loai": k, "value": v, "want": _want(plan, out.get("ra"))}))
        sc = score(rec, G[r["id"]])
        kq[m][sc] += 1
        loai[m][k if k != "tra_loi" else ("đúng" if sc == 1 else "chạy được nhưng sai số")] += 1
        if m == "goc" and sc != 1 and len(mau) < 6:
            mau.append((q["question"][:70], r[m][:260].replace("\n", " "), detail[:90], str(G[r["id"]]["answer"])[:40]))
for m in ("goc", "lora"):
    c = kq[m]
    print(f"{m:5s}: đúng {c[1]} sai {c[-1]} trống {c[0]} | {dict(loai[m])}")
print("\nVài câu model gốc sai:")
for x in mau:
    print(" - câu:", x[0], "\n   ra:", x[1], "\n   chạy:", x[2], "| đáp án:", x[3])
