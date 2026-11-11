"""Tên cột gốc (như README / sổ ghi) -> tên cột trong DB.

Lớp dữ liệu đổi cột gốc sang tên chuẩn (bat_dau -> order_time) và ghi lại ở _meta_columns.original_name. Prompt có cả
README nên LLM hay viết tên gốc; DB báo "không có cột". Đổi lại bằng bảng ánh xạ đó (không gọi LLM, không đoán): chỉ đổi
khi tên gốc trỏ tới đúng một cột (trong bảng đang dùng, hoặc cả shop chỉ có một cách hiểu).
"""
from __future__ import annotations

import re

import duckdb

from ..loader.parsers import fold

_NOT_FOUND = re.compile(r'Referenced column "([^"]+)" not found')


def _key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", fold(str(name))).strip("_")


def alias_map(con) -> dict[str, dict[str, str]]:
    """{bảng: {khoá tên gốc: cột DB}} (khoá = tên gốc viết thường bỏ dấu, nối bằng _)."""
    out: dict[str, dict[str, str]] = {}
    try:
        rows = con.execute("SELECT table_name, column_name, original_name FROM _meta_columns "
                           "WHERE original_name IS NOT NULL").fetchall()
    except duckdb.Error:
        return out
    for t, c, o in rows:
        if not c or c.endswith("__raw") or _key(o) == _key(c):
            continue
        out.setdefault(t, {})[_key(o)] = c
    return out


def resolve(con, table: str, col, cols) -> str | None:
    """Cột `col` không có trong `cols` của `table`: tên gốc của cột nào thì trả cột đó, không thì None."""
    if not isinstance(col, str) or col in cols:
        return None
    hit = alias_map(con).get(table, {}).get(_key(col))
    return hit if hit in cols else None


def fix_sql(con, sql: str, err: str) -> str | None:
    """SQL lỗi 'Referenced column "X" not found' mà X là tên gốc của đúng một cột trong các bảng SQL nhắc tới -> SQL đã đổi."""
    m = _NOT_FOUND.search(err)
    if not m:
        return None
    bad = m.group(1)
    amap = alias_map(con)
    low = sql.lower()
    used = [t for t in amap if re.search(rf'(?<![\w"]){re.escape(t.lower())}(?![\w"])|"{re.escape(t.lower())}"', low)]
    cands = {amap[t][_key(bad)] for t in used if _key(bad) in amap[t]}
    if len(cands) != 1:
        cands = {v[_key(bad)] for v in amap.values() if _key(bad) in v}
    if len(cands) != 1:
        return None
    new = cands.pop()
    out = re.sub(rf'"{re.escape(bad)}"', f'"{new}"', sql)
    out = re.sub(rf'(?<![\w."]){re.escape(bad)}(?![\w"])', f'"{new}"', out)
    return out if out != sql else None
