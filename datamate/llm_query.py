"""Tầng LLM cho phía query: câu mẫu SQL không hiểu -> LLM viết SQL trên DB sạch của shop.

Prompt = tóm tắt DB (bảng, vai trò, cột, giá trị mẫu) + rulebook của shop (bảng _rulebook, bỏ §9 chấm điểm,
§6 chỉ giữ ngành của shop) + quy ước của lớp data. LLM trả JSON {type, sql}; code chạy SQL và tự định dạng
theo §9. SQL lỗi: cho LLM sửa một lần; vẫn lỗi -> bỏ trống.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import unicodedata

from datamate.loader import llm
from datamate.loader.parsers import fold
from datamate.loader.shopmeta import INDUSTRIES

_SKIP_META = {"_meta_columns", "_meta_tables", "_meta_shop", "_meta_conventions", "_meta_dropped", "_calendar",
              "_rulebook"}

CONVENTIONS = """Quy ước của DB (đã làm sạch theo rulebook):
- Mỗi shop một DB DuckDB. Tên cột là tên chuẩn; cột tên gốc giữ nguyên tên gốc (xem mô tả).
- status_norm: trạng thái CUỐI của đơn ('hoan_thanh','huy','tra_hang','dang_giao'), giống nhau ở mọi dòng của đơn.
  Doanh thu, số đơn, bán chạy: chỉ đơn status_norm NOT IN ('huy','tra_hang'). Tỉ lệ huỷ: mẫu số là mọi đơn.
- line_type: 'hang' là mặt hàng; doanh thu loại 'voucher','giam_gia','dung_diem','phi_giao','thue' (giữ 'phi_phuc_vu').
- Doanh thu = SUM(line_amount) của dòng bán. Ngày của đơn: order_date (nếu bảng dòng không có thì JOIN bảng đơn qua order_id).
- qty_base: số lượng quy về đơn vị cơ bản (dùng cho bán chạy, số lượng bán). base_unit: đơn vị cơ bản.
- is_walk_in: khách lẻ (không xếp hạng khách). customer_key / product_key: khoá tên đã bỏ dấu (gộp tên chỉ khác cách viết).
- is_latest_row (nếu có): chỉ cộng các dòng TRUE.
- payment_norm: 'tien_mat','chuyen_khoan','the','vi','cod','ghi_no'. channel_norm: 'tai_quay','dien_thoai','zalo',...
- order_time: giờ tạo đơn (ca sáng 6-13h, ca chiều 14-21h).
- Bảng phụ: _unit_conversions(product_id, product_name, product_key, unit, factor, base_unit), _tet_periods(tet_year,
  start_date, end_date), _product_aliases(alias, product_name).
- So sánh tên: dùng strip_accents(lower(...)) hoặc product_key/customer_key, không so nguyên văn."""

SYSTEM = """Bạn là chuyên gia SQL (DuckDB) phân tích dữ liệu bán hàng cửa hàng nhỏ ở Việt Nam.
Viết MỘT câu SQL DuckDB trả lời câu hỏi, theo đúng rulebook và quy ước của DB.
Chỉ trả về một JSON object: {"type": "...", "sql": "..."}.
type là một trong: number, percent, date, string, list, table, boolean, unanswerable.
- number / percent: SQL trả 1 dòng 1 cột. percent là số phần trăm (12.4 nghĩa là 12,4%).
- date: SQL trả 1 ngày (hoặc chuỗi 'YYYY-MM' nếu hỏi tháng nào).
- string: SQL trả 1 dòng, cột đầu là tên (tên như trong dữ liệu).
- list: SQL trả nhiều dòng 1 cột theo đúng thứ tự cần (hoặc 1 dòng nhiều cột khi hỏi nhiều số theo thứ tự).
- table: SQL trả nhiều dòng; cột đầu là tên đối tượng, các cột sau là số đo theo thứ tự câu hỏi.
- unanswerable: dữ liệu không có thông tin câu hỏi cần (khi đó sql để trống).
Không giải thích, không markdown."""


def shop_summary(con, max_cols: int = 40) -> str:
    """Tóm tắt DB cho prompt: thông tin shop, mỗi bảng (vai trò, số dòng, khoảng ngày) và cột."""
    lines = []
    shop = con.execute("SELECT * FROM _meta_shop").fetchdf().iloc[0].to_dict()
    lines.append(f"Shop {shop.get('shop')}: ngành {shop.get('industry')}, có mã khách: {shop.get('has_customer_id')}, "
                 f"có đơn từ {str(shop.get('sales_start'))[:10]} đến {str(shop.get('sales_end'))[:10]}.")
    tables = con.execute("SELECT table_name, role, n_rows, date_column, date_min, date_max FROM _meta_tables").fetchall()
    for t, role, n, dcol, dmin, dmax in tables:
        cols = con.execute("SELECT column_name, canonical, original_name, kind, description FROM _meta_columns "
                           "WHERE table_name = ?", [t]).fetchall()
        parts = []
        for col, canon, orig, kind, desc in cols[:max_cols]:
            if col.endswith("__raw"):
                continue
            extra = []
            if orig and orig != col:
                extra.append(f"gốc '{orig}'")
            if kind == "text" and (canon in ("status_norm", "line_type", "payment_norm", "channel_norm", "category",
                                             "customer_group", "status", "unit", "base_unit", "channel",
                                             "payment_method") or canon is None):
                try:
                    vals = [v for v, in con.execute(f'SELECT DISTINCT "{col}" FROM "{t}" WHERE "{col}" IS NOT NULL '
                                                     f'LIMIT 9').fetchall()]
                    if 0 < len(vals) <= 8:
                        extra.append("giá trị: " + ", ".join(repr(str(v))[:30] for v in vals))
                except Exception:
                    pass
            elif desc and canon is None:
                extra.append(str(desc)[:60])
            parts.append(f"{col} {kind}" + (f" ({'; '.join(extra)})" if extra else ""))
        rng = f", ngày theo {dcol} từ {str(dmin)[:10]} đến {str(dmax)[:10]}" if dcol else ""
        lines.append(f'- "{t}" vai trò {role}, {n} dòng{rng}: ' + ", ".join(parts))
    return "\n".join(lines)


# chữ chung trong tên mục ngành, không cho biết ngành nào
_SEC6_STOP = {"ngành", "cửa", "hàng", "quán", "tiệm", "shop", "cho", "bán", "và"}


def _vi_words(s: str) -> set[str]:
    # giữ dấu: bỏ dấu thì "hoá đơn" thành "hoa don", trùng chữ "hoa" của "Tiệm hoa"
    return set(re.findall(r"\w+", unicodedata.normalize("NFC", s).lower()))


def _sec6_pick(heads: list[str], industry: str | None, shop: str | None, intro: str | None) -> set[str]:
    """Các mục §6 (theo ngành) áp cho shop. Tiêu đề ghi đúng mã shop thì chỉ lấy mục đó; không thì lấy mục trùng tên ngành
    đã nhận ra và mục có mọi chữ của tiêu đề nằm trong phần giới thiệu README. Vẫn không có mục nào thì lấy các mục của ngành
    code không nhận ra được (ngoài INDUSTRIES): shop có thể thuộc một mục như vậy, thiếu luật ngành hại hơn thừa."""
    f = {h: fold(h) for h in heads}
    if shop:
        hit = {h for h in heads if re.search(rf"(?<![a-z0-9]){re.escape(fold(shop))}(?![a-z0-9])", f[h])}
        if hit:
            return hit
    hit = {h for h in heads if industry and f[h] == fold(industry)}
    words = _vi_words(intro or "")
    for h in heads:
        core = _vi_words(re.sub(r"\(.*?\)", " ", h)) - _SEC6_STOP
        if core and core <= words:
            hit.add(h)
    if not hit:
        known = {fold(name) for name, _, _ in INDUSTRIES}
        hit = {h for h in heads if re.sub(r"\s*\(.*?\)", "", f[h]).strip() not in known}
    return hit


def rulebook_text(con, industry: str | None) -> str:
    """Rulebook của shop từ _rulebook: bỏ §9 (chấm điểm, code tự định dạng); §6 chỉ giữ các mục ngành của shop."""
    rows = con.execute("SELECT level, heading, text FROM _rulebook ORDER BY seq").fetchall()
    try:
        shop, intro = con.execute("SELECT shop, intro FROM _meta_shop").fetchone()
    except Exception:       # DB cũ / thiếu cột: chỉ dựa vào tên ngành như trước
        shop = intro = None
    heads, section = [], ""
    for level, heading, _ in rows:
        if level == 2:
            section = fold(heading)
        elif level == 3 and section.startswith("6."):
            heads.append(heading)
    keep = _sec6_pick(heads, industry, shop, intro)
    out, section = [], ""
    for level, heading, text in rows:
        h = fold(heading)
        if level == 1:
            continue
        if level == 2:
            section = h
        if section.startswith("9."):
            continue
        if section.startswith("6.") and level == 3 and heading not in keep:
            continue
        out.append(f"{'#' * level} {heading}\n{text}")
    return "\n".join(out)


def ask_sql(con, question: str, today: dt.date, summary: str, rules: str, error: str | None = None,
            prev_sql: str | None = None, temperature: float = 0) -> dict:
    user = (f"{CONVENTIONS}\n\nRULEBOOK:\n{rules}\n\nDB:\n{summary}\n\n"
            f"Hôm nay (as_of_date): {today.isoformat()}. Bản ghi sau hôm nay coi như chưa xảy ra.\n"
            f"Câu hỏi: {question}")
    if error:
        user += f"\n\nSQL trước bị lỗi:\n{prev_sql}\nLỗi: {error[:300]}\nHãy sửa."
    text = llm.chat(SYSTEM, user, max_tokens=700, timeout=180, temperature=temperature)
    m = re.search(r"\{.*\}", text, re.S)
    try:
        out = json.loads(m.group(0)) if m else {}
    except json.JSONDecodeError:
        return {}
    return out if isinstance(out, dict) else {}


def _num(v):
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        f = float(v)
        return int(round(f)) if abs(f - round(f)) < 1e-6 else round(f, 2)
    try:
        return _num(float(v))
    except (TypeError, ValueError):
        return None


def to_answer(typ: str, rows: list, question: str):
    """Kết quả SQL -> giá trị đáp án theo §9; None nếu không định dạng được."""
    if typ == "unanswerable":
        return True
    if not rows:
        return None
    first = rows[0]
    if typ == "number":
        v = _num(first[0])
        if v is not None and isinstance(v, float) and re.search(r"\b(tien|doanh thu|dthu|gia|von|no)\b", fold(question)):
            v = int(v + 0.5)          # tiền làm tròn về đồng, nửa đồng lên
        return v
    if typ == "percent":
        v = _num(first[0])
        return None if v is None else round(float(v), 2)
    if typ == "date":
        v = first[0]
        if isinstance(v, (dt.date, dt.datetime)):
            return v.strftime("%Y-%m-%d")
        s = str(v)
        return s[:10] if re.match(r"\d{4}-\d{2}-\d{2}", s) else (s[:7] if re.match(r"\d{4}-\d{2}", s) else None)
    if typ == "string":
        return None if first[0] is None else str(first[0])
    if typ == "boolean":
        v = first[0]
        return bool(v) if isinstance(v, (bool, int)) else None
    if typ == "list":
        vals = list(first) if len(rows) == 1 and len(first) > 1 else [r[0] for r in rows]
        return [(_num(v) if isinstance(v, (int, float)) else str(v)) for v in vals]
    if typ == "table":
        return {"columns": [f"c{i}" for i in range(len(first))],
                "rows": [[str(r[0])] + [_num(v) for v in r[1:]] for r in rows]}
    return None


# loại đáp án nhận từ LLM: đo trên train, list / table / string sai nhiều hơn đúng
ACCEPT = ("number", "percent", "date")    # unanswerable do LLM tự kết luận: hoà trên train -> bỏ


def _one(con, question, today, summary, rules, temperature):
    r = ask_sql(con, question, today, summary, rules, temperature=temperature)
    typ, sql = r.get("type"), r.get("sql") or ""
    if typ not in ("number", "percent", "date", "string", "list", "table", "boolean", "unanswerable"):
        return None, f"type lạ {typ}"
    if typ == "unanswerable":
        return {"type": "unanswerable", "reason": "LLM: dữ liệu không có thông tin"}, "unanswerable"
    for attempt in range(2):
        try:
            rows = con.execute(sql).fetchall()
            break
        except Exception as e:
            if attempt:
                return None, f"SQL lỗi: {e}"[:200]
            r = ask_sql(con, question, today, summary, rules, error=str(e), prev_sql=sql, temperature=temperature)
            typ, sql = r.get("type", typ), r.get("sql") or ""
    ans = to_answer(typ, rows, question)
    if ans is None:
        return None, "không định dạng được"
    return {"type": typ, "answer": ans}, sql[:200]


def llm_answer(con, question: str, today: dt.date, cache: dict, votes: int = 2) -> tuple[dict | None, str]:
    """-> (dòng nộp không có id, ghi chú). Chỉ nhận khi `votes` lần hỏi (nhiệt độ 0 rồi 0.7) ra CÙNG đáp án và
    loại đáp án thuộc ACCEPT; không thì None (bỏ trống: 0 điểm, đỡ hơn sai -1)."""
    key = id(con)
    if key not in cache:
        ind = con.execute("SELECT industry FROM _meta_shop").fetchone()[0]
        cache[key] = (shop_summary(con), rulebook_text(con, ind))
    summary, rules = cache[key]
    first, note = _one(con, question, today, summary, rules, 0)
    if first is None or first["type"] not in ACCEPT:
        return None, note if first is None else f"loại {first['type']} không nhận"
    for _ in range(votes - 1):
        other, _n = _one(con, question, today, summary, rules, 0.7)
        if other is None or other.get("type") != first["type"] or other.get("answer") != first.get("answer"):
            return None, "hai lần hỏi không khớp"
    return first, note
