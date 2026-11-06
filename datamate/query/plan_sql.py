"""Dịch kế hoạch đã kiểm sang một câu SQL trên các bảng v_*: kho ví dụ cho tầng SQL (query/sql_tier.py).

Mỗi ví dụ được chạy lại và so đáp án train trước khi vào kho. Không dịch được thì bỏ qua, kho chỉ cần đủ dạng.

    python -m datamate.query.plan_sql ../train/train <DB> --examples examples_train.jsonl --out examples_sql_train.jsonl
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re

import duckdb

from datamate.query.compose import ShopContext, clean_plan, naturalize
from datamate.query.plan import PlanError, Runner, normalize
from datamate.query.regress import check
from datamate.query.sql_tier import _attempt, _prepare


class NoSql(Exception):
    """Kế hoạch này không có dạng một câu SQL gọn."""


_NAME = {"hang": "ANY_VALUE(ten_hang)", "khach": "ANY_VALUE(ten_khach)"}


def _table(name: str) -> str:
    m = re.match(r"_f_dong_tien_no_(\d{8})_(\d{8})$", name)
    if m:       # bảng nhận kỳ làm tham số: bảng hàm của tầng SQL
        a, b = (dt.datetime.strptime(x, "%Y%m%d").date() for x in m.groups())
        return f"v_dong_tien_no(DATE '{a}', DATE '{b}')"
    m = re.match(r"_f_([a-z_]+?)(_\d{8})?$", name)
    if not m:
        raise NoSql(name)
    return f"v_{m[1]}"


def _leaf(r: Runner, plan: dict) -> tuple[str, str | None]:
    """-> (SQL, ra)."""
    plan = normalize(plan)
    op = plan.get("phep")
    if op in ("hang_e", "dem_e", "chan_le"):
        raise NoSql(op)
    fact, table, conds = r._source(plan)
    v = _table(table)
    where = " AND ".join(conds) or "TRUE"
    if op == "gia_duy_nhat":
        return f'SELECT DISTINCT ROUND("{plan["cot"]}", 2) FROM {v} WHERE {where}', "number"
    g = plan.get("nhom")
    if not g:
        expr, col = r._measure(plan, fact, table, where)
        return f"SELECT {expr} FROM {v} WHERE {where}", "tien" if col and _is_money(col) else "number"
    if g == "hang" and fact == "dong_ban":
        where += " AND la_mat_hang"
    if op == "dem_nhom":
        if plan.get("do") == "tong":
            expr = f'SUM("{plan["cot"]}")'
        else:
            expr = f'COUNT(DISTINCT "{plan["cot"]}")' if plan.get("cot") else "COUNT(*)"
        hv = plan.get("co_dieu_kien") or {}
        having = f" HAVING {expr} {hv['op']} {float(hv['gt']):g}" if hv else ""
        return f'SELECT COUNT(*) FROM (SELECT "{g}" FROM {v} WHERE {where} AND "{g}" IS NOT NULL GROUP BY "{g}"{having})', "number"
    expr, col = r._measure(plan, fact, table, where)
    xep = plan.get("xep") or {}
    order = "ASC" if xep.get("chieu") == "tang" else "DESC"
    lim = xep.get("lay")
    out = _NAME.get(g, f'"{g}"')
    tail = f'FROM {v} WHERE {where} AND "{g}" IS NOT NULL GROUP BY "{g}" ORDER BY {expr} {order}, "{g}"' + (f" LIMIT {int(lim)}" if lim else "")
    keep = plan.get("cot_ra", "ten")
    if keep == "gia_tri":
        return f"SELECT {expr} {tail}", "tien" if col and _is_money(col) else ("number" if lim == 1 else "list")
    if keep == "ca_hai":
        return f"SELECT {out}, {expr} {tail}", "table"
    if lim != 1:
        return f"SELECT {out} {tail}", "list"
    return f"SELECT {out} {tail}", "date" if g in ("ngay", "thang") else "number" if g in ("gio", "thu") else "string"


def _is_money(col: str) -> bool:
    from datamate.query.facts import MONEY
    return col in MONEY


def to_sql(r: Runner, plan: dict) -> tuple[str, str]:
    if "ghep" not in plan:
        return _leaf(r, plan)
    plan = normalize(plan)
    kind, parts = plan["ghep"], plan.get("cac") or []
    subs = [_leaf(r, p) if "ghep" not in p else to_sql(r, p) for p in parts]
    q = [f"({s})" for s, _ in subs]
    if kind == "danh_sach":
        return "SELECT " + ", ".join(q), "list"
    if kind in ("tang_lien_tuc", "giam_lien_tuc"):
        op = "<" if kind == "tang_lien_tuc" else ">"
        return "SELECT " + " AND ".join(f"{a} {op} {b}" for a, b in zip(q, q[1:])), "boolean"
    a, b = q[0], q[1]
    if kind == "hieu":
        return f"SELECT {a} - {b}", "number"
    if kind == "lon_hon":
        return f"SELECT {a} > {b}", "boolean"
    if kind == "ti_le":
        return f"SELECT 100.0 * {a} / {b}", "percent"
    if kind == "tang_truong":
        return f"SELECT 100.0 * ({a} - {b}) / {b}", "percent"
    if kind == "thuong":
        return f"SELECT 1.0 * {a} / {b}", "tien" if plan.get("tien") else "number"
    raise NoSql(kind)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("split_root")
    ap.add_argument("db_root")
    ap.add_argument("--examples", default="../solve data/query/examples_train.jsonl")
    ap.add_argument("--out", default="../solve data/query/examples_sql_train.jsonl")
    a = ap.parse_args()
    gold = {r["id"]: r for r in map(json.loads, open(os.path.join(a.split_root, "answers.jsonl"), encoding="utf-8"))}
    ctxs: dict = {}
    kept = skipped = wrong = 0
    with open(a.out, "w", encoding="utf-8") as fh:
        for e in map(json.loads, open(a.examples, encoding="utf-8")):
            s = e["shop"]
            ctx = ctxs.setdefault(s, ShopContext(os.path.join(a.db_root, s, f"{s}.duckdb")))
            today = dt.date.fromisoformat(e["as_of_date"])
            q = {"id": e["id"], "question": e["question"], "as_of_date": e["as_of_date"]}
            plan = clean_plan(naturalize(e["plan"], e["question"], today), e["question"])
            try:
                sql, ra = to_sql(Runner(ctx.con, today, ctx.facts), plan)
                if e.get("type") == "percent":
                    ra = "percent"
                elif e.get("type") in ("list", "table", "date", "string", "boolean"):
                    ra = e["type"]
            except (NoSql, PlanError, KeyError, TypeError, ValueError, AttributeError, duckdb.Error):
                skipped += 1
                continue
            _prepare(ctx)
            kind, _, _, v, _ = _attempt(ctx, {"sql": sql, "ra": ra}, q, today)
            if kind != "tra_loi" or not check(v, gold[e["id"]]):
                wrong += 1
                continue
            kept += 1
            fh.write(json.dumps({"id": e["id"], "shop": s, "as_of_date": e["as_of_date"], "question": e["question"], "kind": e["kind"],
                                 "type": e["type"], "plan": e["plan"], "sql": sql, "ra": ra}, ensure_ascii=False, default=str) + "\n")
    print(f"giữ {kept}, không dịch được {skipped}, chạy lại không ra đáp án {wrong}")


if __name__ == "__main__":
    main()
