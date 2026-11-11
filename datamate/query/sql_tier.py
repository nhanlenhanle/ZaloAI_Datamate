"""LLM viết SQL trên các bảng chuẩn (query/facts.py), thay vì lập kế hoạch JSON.

Bảng chuẩn đã mang sẵn luật dữ liệu (trạng thái, quy đổi, loại dòng); code tính sẵn các kỳ theo §2 và khớp tên hàng trong
câu, rồi chạy SQL và định dạng theo §9. Linh hoạt hơn kế hoạch JSON ở câu ngoài ngôn ngữ kế hoạch; đổi lại LLM phải tự
nhớ lọc đơn hợp lệ, nên SQL là một ý kiến độc lập để đối chiếu và là đường lui, không tự động đáng tin hơn.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import re
import threading
import unicodedata
from collections import Counter

import duckdb

from datamate.loader import llm
from datamate.query import alias
from datamate.query.compose import (ASKS_DAY, _ASKS_COUNT, _ASKS_DATE, _ASKS_NAMES, _ASKS_RX, _IS_DATE, _MONTH_YEAR, ExampleBank,
                                    RuleBank, ShopContext, _is_zero, _plan_names, asks_yes_no, column_meaning, holiday_block,
                                    mask, near_rules, period_text, readme_block, rule_rows, value_key)
from datamate.query.evaluate import HOLDOUT
from datamate.query.facts import AT_DATE, BY_RANGE, FIELDS, NoSource
from datamate.loader.parsers import fold
from datamate.query.plan import PlanError, _product_index, _q, resolve_period, to_record
from datamate.tests.verify_answers import _month_end, flow_sql, names_by_id, text_key

SQL_TIMEOUT = 30        # giây: SQL ghép chéo vô hạn không được làm treo cả lượt chạy

SPEC_SQL = """Bạn viết MỘT câu SQL (DuckDB) trả lời câu hỏi về sổ bán hàng của một cửa hàng nhỏ ở Việt Nam. Câu hỏi có thể viết tắt,
không dấu, sai chính tả, teencode. Chỉ trả về đúng một JSON, không giải thích, không markdown:
{"cach_tinh": "<một câu ngắn: tính gì, trên đối tượng nào, điều kiện gì, kỳ nào>", "sql": "SELECT ...", "ra": "tien|number|percent|date|string|list|table|boolean"}
Câu dùng một thuật ngữ có định nghĩa trong RULEBOOK thì "cach_tinh" và SQL làm đúng theo định nghĩa đó, kể cả khi nó khác nghĩa thường ngày.
Nếu dữ liệu không có loại thông tin câu hỏi cần (vd thái độ nhân viên, giới tính, lý do huỷ, hay cột ghi "shop KHÔNG ghi"):
{"khong_co": "<thiếu gì; thiếu cột shop không ghi thì ghi đúng tên cột>"}.

Kết quả SQL theo "ra":
- tien / number / percent / date / string / boolean: 1 dòng 1 cột. percent là số phần trăm (12.5 nghĩa là 12,5%). Tháng trả 'YYYY-MM'.
- list: nhiều dòng 1 cột đúng thứ tự, hoặc 1 dòng nhiều cột khi hỏi nhiều số theo thứ tự. table: mỗi dòng [tên đối tượng, giá trị].
- Câu hỏi có / không (... không?, có phải ... không, đúng không): "ra": "boolean", SQL trả TRUE / FALSE.
- Hỏi lớn nhất / nhiều nhất / cao nhất: ORDER BY ... DESC; nhỏ nhất / ít nhất / thấp nhất: ORDER BY ... ASC.

Luật bắt buộc khi dùng bảng v_*:
- Doanh thu, số đơn, bán chạy, khách mua nhiều, trung bình mỗi đơn: chỉ đơn hợp lệ, WHERE hop_le. Hỏi riêng đơn huỷ / trả, hoặc tỉ lệ huỷ: không lọc hop_le, mẫu số là mọi đơn.
- Doanh thu = SUM(tien) trên v_dong_ban. Một đơn có nhiều dòng: đếm đơn là COUNT(DISTINCT don); luật nói số dòng thì mới đếm dòng. Bán chạy / xếp hạng hàng thêm la_mat_hang và theo sl_co_ban.
- Khách và nhân viên là cột mã: nhóm theo mã, cột ra là ANY_VALUE(ten_khach). Khách lẻ có khach NULL, không tính khi đếm và xếp hạng khách.
- Lọc mặt hàng theo mục "TÊN TRONG CÂU" nếu có: hang = '<mã>'. Lọc tên khác: khop(ten_khach, 'tên trong câu'), khop(nhom_hang, 'tên').
- Kỳ: hôm nay, hôm qua, tuần, N ngày, từ đầu năm... dùng ngay BETWEEN với đúng các ngày ở mục "KỲ", không dùng thang. Chỉ tháng M năm Y mới dùng thang = 'YYYY-MM'. Kỳ so sánh phải cùng độ dài như rulebook.
- Ngày tính từ một mốc mà mục "KỲ" không ghi sẵn (N ngày cuối tháng, N ngày trước một ngày...): để SQL tính, vd last_day(DATE '2025-12-01') - INTERVAL 6 DAY; không tự nhẩm ngày.
- Nợ thêm, khách trả nợ trong một kỳ: bảng hàm FROM v_dong_tien_no(DATE 'A', DATE 'B') với A, B là kỳ đó. Còn nợ tại một ngày: v_cong_no.
- Ngưỡng tiền của một đơn, một ngày, một khách là ngưỡng trên TỔNG của đối tượng đó: GROUP BY rồi HAVING SUM(tien) >= X, không lọc tien >= X trên từng dòng.
- Chỉ thêm điều kiện câu hỏi nêu: không tự thêm ke_don, trang_thai, nhóm. So tên nhóm, hoạt chất, khách dùng khop(cột, 'tên').
- Không có dòng nào trong kỳ mà hỏi tổng / trung bình thì để SQL trả NULL, không dùng COALESCE về 0.

Ví dụ:
Doanh thu tháng 8/2025 -> {"sql": "SELECT SUM(tien) FROM v_dong_ban WHERE hop_le AND thang = '2025-08'", "ra": "tien"}
Tháng 3/2026 bị huỷ mấy đơn -> {"sql": "SELECT COUNT(DISTINCT don) FROM v_don WHERE trang_thai = 'huy' AND thang = '2026-03'", "ra": "number"}
Tỉ lệ huỷ tháng 3/2026 -> {"sql": "SELECT 100.0 * COUNT(DISTINCT don) FILTER (WHERE trang_thai = 'huy') / COUNT(DISTINCT don) FROM v_don WHERE thang = '2026-03'", "ra": "percent"}
Trung bình mỗi đơn tuần trước -> {"sql": "SELECT SUM(tien) / COUNT(DISTINCT don) FROM v_dong_ban WHERE hop_le AND ngay BETWEEN DATE 'A' AND DATE 'B'", "ra": "tien"}
Top 3 hàng bán chạy tháng 5/2026 -> {"sql": "SELECT ANY_VALUE(ten_hang) FROM v_dong_ban WHERE hop_le AND la_mat_hang AND thang = '2026-05' GROUP BY hang ORDER BY SUM(sl_co_ban) DESC LIMIT 3", "ra": "list"}
Khách chi nhiều nhất tháng 5/2026 -> {"sql": "SELECT ANY_VALUE(ten_khach) FROM v_dong_ban WHERE hop_le AND khach IS NOT NULL AND thang = '2026-05' GROUP BY khach ORDER BY SUM(tien) DESC LIMIT 1", "ra": "string"}
Ngày doanh thu cao nhất tháng 5/2026 -> {"sql": "SELECT ngay FROM v_dong_ban WHERE hop_le AND thang = '2026-05' GROUP BY ngay ORDER BY SUM(tien) DESC LIMIT 1", "ra": "date"}
Doanh thu tháng 2/2026 so với tháng trước tăng bao nhiêu % -> {"sql": "SELECT 100.0 * (SUM(tien) FILTER (WHERE thang = '2026-02') - SUM(tien) FILTER (WHERE thang = '2026-01')) / SUM(tien) FILTER (WHERE thang = '2026-01') FROM v_dong_ban WHERE hop_le", "ra": "percent"}
Có bao nhiêu mặt hàng có từ 5 đơn trong tháng 5/2026 -> {"sql": "SELECT COUNT(*) FROM (SELECT hang FROM v_dong_ban WHERE hop_le AND la_mat_hang AND thang = '2026-05' GROUP BY hang HAVING COUNT(DISTINCT don) >= 5)", "ra": "number"}
Luật tính lấy theo RULEBOOK bên dưới."""

_EXTRA_COLS = {"dong_ban": "hop_le: TRUE nếu đơn hợp lệ; ten_khach: tên khách", "don": "hop_le: TRUE nếu đơn hợp lệ"}
_DATE_IN_Q = re.compile(r"(?<!\d)(\d{1,2})[/-](\d{1,2})[/-](20\d\d)(?!\d)")

# cụm kỳ trong câu (đã bỏ dấu) -> kỳ §2; "cùng kỳ tháng trước" đứng trước "tháng trước" để không bị bắt lại
_PERIOD_PHRASES = (
    (r"\bcung ky (?:thang|th) (?:truoc|roi|qua)\b", "cùng kỳ tháng trước", {"loai": "ky_truoc", "cua": {"loai": "thang_nay"}}),
    (r"\btuan (?:truoc|roi|qua|vua roi|vua qua)\b", "tuần trước", {"loai": "tuan_truoc"}),
    (r"\btuan nay\b", "tuần này", {"loai": "tuan_nay"}),
    (r"\b(?:hom qua|hqua|bua qua)\b", "hôm qua", {"loai": "hom_qua"}),
    (r"\b(?:thang|th|thg) (?:nay|ni)\b", "tháng này", {"loai": "thang_nay"}),
    (r"\b(?:thang truoc|thang roi|thang qua)\b", "tháng trước", {"loai": "thang_truoc"}),
    (r"\btu dau nam\b", "từ đầu năm", {"loai": "tu_dau_nam"}),
)
_N_DAYS = re.compile(r"\b(\d{1,3}) ngay (?:gan nhat|gan day|qua|vua qua|vua roi|cuoi|truoc)\b")
_QUARTER = re.compile(r"\b(?:quy|q)\s*([1-4])\s*(?:/|-|nam)?\s*(20\d\d)\b")
_NOT_WHOLE_MONTH = re.compile(r"\b(?:tu|den|toi|het|cuoi|dau|sau|truoc)\s+(?:thang\s+)?$")


def _asked_periods(question: str, today: dt.date, whole: bool = True) -> list[tuple[str, dt.date, dt.date, list[str], bool]]:
    """Kỳ câu hỏi nêu, code tính theo §2: (tên, ngày đầu, ngày cuối, các tháng 'YYYY-MM' viết thay được khi kỳ là trọn tháng,
    kỳ ghi rõ tháng / quý hay không). whole=False: lấy cả tháng nêu làm mốc ("đến hết tháng 2/2026"), để ghi sẵn ngày."""
    f = period_text(question)
    out = []
    for pat, label, k in _PERIOD_PHRASES:
        if re.search(pat, f):
            f = re.sub(pat, " ", f)
            a, b = resolve_period(k, today)
            full = a.day == 1 and b == _month_end(a.year, a.month)
            out.append((label, a, b, [f"{a:%Y-%m}"] if full else [], False))
    for n in dict.fromkeys(_N_DAYS.findall(f)):
        a, b = resolve_period({"loai": "n_ngay", "n": int(n)}, today)
        out.append((f"{n} ngày gần nhất", a, b, [], False))
    for q, y in dict.fromkeys(_QUARTER.findall(f)):
        months = [dt.date(int(y), 3 * int(q) - 2 + i, 1) for i in range(3)]
        out.append((f"quý {q}/{y}", months[0], _month_end(int(y), 3 * int(q)), [f"{m:%Y-%m}" for m in months], True))
    for m in _MONTH_YEAR.finditer(f):
        mo, y = int(m[1] or m[3]), int(m[2] or m[4])
        # "quý 3/2025", "Q3/2025", "14/06/2025" không phải tháng; "từ tháng 2 tới tháng 4", "cuối tháng 6" không phải kỳ trọn tháng
        before = f[:m.start()]
        if 1 <= mo <= 12 and not re.search(r"(?:\b(?:quy|q)\s*|\d\s*[/-]\s*)$", before) and not (whole and _NOT_WHOLE_MONTH.search(before)):
            a = dt.date(y, mo, 1)
            out.append((f"tháng {mo}/{y}", a, _month_end(y, mo), [f"{a:%Y-%m}"], True))
    return list({p[0]: p for p in out}.values())


def periods(today: dt.date, question: str = "") -> str:
    """Các kỳ theo §2, code tính sẵn: LLM hay sai ngày đầu tuần, số ngày của tháng trước, ngày cuối tháng 2.
    Kỳ nêu trong câu (tháng M/Y, quý, N ngày) cũng ghi sẵn ngày đầu, ngày cuối."""
    def fmt(k):
        a, b = resolve_period(k, today)
        return f"{a} đến {b}"
    named = (("hôm nay", {"loai": "hom_nay"}), ("hôm qua", {"loai": "hom_qua"}), ("tuần này", {"loai": "tuan_nay"}),
             ("tuần trước", {"loai": "tuan_truoc"}), ("tháng này", {"loai": "thang_nay"}),
             ("cùng kỳ tháng trước của tháng này", {"loai": "ky_truoc", "cua": {"loai": "thang_nay"}}),
             ("tháng trước", {"loai": "thang_truoc"}), ("từ đầu năm", {"loai": "tu_dau_nam"}),
             ("7 ngày gần nhất", {"loai": "n_ngay", "n": 7}), ("30 ngày gần nhất", {"loai": "n_ngay", "n": 30}))
    lines = [f"- {name}: {fmt(k)}" for name, k in named]
    known = {name for name, _ in named} | {"cùng kỳ tháng trước"}
    for label, a, b, months, fixed in _asked_periods(question, today, whole=False):
        if label in known:
            continue
        lines.append(f"- {label}: {a} đến {b}")
        if fixed and len(months) == 1:      # nhiều định nghĩa so với tháng liền trước (khách quay lại, tăng so tháng trước...)
            p = a - dt.timedelta(days=1)
            lines.append(f"- tháng liền trước của {label}: {p.replace(day=1)} đến {p}")
    return "\n".join(lines)


def _period_miss(sql: str, question: str, today: dt.date) -> str | None:
    """SQL trên bảng theo kỳ không dùng đúng ngày của kỳ câu hỏi nêu: LLM hay tự tính lại kỳ và sai
    (tuần trước thành 5 ngày, 30 ngày thành 7, "từ đầu tháng đến nay" thành cả tháng).
    Câu có mốc ghi rõ (ngày, tháng, quý) thì "tháng trước", "N ngày trước đó" tính theo mốc đó: không xét kỳ tương đối.
    Câu nêu nhiều tháng thì một khoảng phủ từ đầu tháng sớm nhất đến cuối tháng muộn nhất cũng nhận."""
    if not re.search(r"\bv_(?:dong_ban|don|phieu_nhap|dong_nhap|dot_giao|khoan_chi|dong_tien_no)\b", sql):
        return None
    asked = _asked_periods(question, today)
    fixed = [p for p in asked if p[4]]
    anchored = bool(fixed) or bool(_DATE_IN_Q.search(question))

    def has(a, b, months):
        return (f"'{a}'" in sql and f"'{b}'" in sql) or (months and all(f"'{m}'" in sql for m in months))
    # "đầu tháng", "tuần chót"...: luật có thể định nghĩa một khoảng con của tháng nêu -> nhận ngày nằm trong tháng đó
    sub = bool(_SUB_PERIOD.search(fold(question)))

    def inside(a, b):
        for d in re.findall(r"'(\d{4}-\d{2}-\d{2})'", sql) if sub else []:
            try:
                if a <= dt.date.fromisoformat(d) <= b:
                    return True
            except ValueError:
                continue
        return False
    if len(fixed) > 1 and has(min(p[1] for p in fixed), max(p[2] for p in fixed), None):
        fixed = []
    for label, a, b, months, _ in fixed + ([] if anchored else asked):
        if not has(a, b, months) and not inside(a, b):
            return f"kỳ '{label}' là {a} đến {b} (mục KỲ): lọc ngay BETWEEN DATE '{a}' AND DATE '{b}'"
    return None


_SUB_PERIOD = re.compile(r"\b(?:dau|cuoi|giua) (?:thang|ky|nam)\b|\btuan (?:dau|cuoi|chot)\b|\b\d{1,2} ngay (?:dau|cuoi)\b")


_MONTH_END_IN_Q = re.compile(r"\b(?:het|cuoi) thang (\d{1,2})\s*(?:/|nam)\s*(20\d\d)\b")


def _at_date(question: str, today: dt.date) -> dt.date:
    """Ngày tính của bảng tình trạng (nợ, tồn, lô): ngày ghi trong câu; "đến hết / cuối tháng M/Y" là ngày cuối tháng đó (§2);
    không có thì hôm nay."""
    for d, m, y in _DATE_IN_Q.findall(question):
        try:
            return dt.date(int(y), int(m), int(d))
        except ValueError:
            continue
    for m, y in _MONTH_END_IN_Q.findall(fold(question)):
        if 1 <= int(m) <= 12:
            return min(_month_end(int(y), int(m)), today)
    return today


_GRAIN = {"dong_ban": "mỗi dòng là một dòng hàng của một đơn", "don": "mỗi dòng một đơn", "phieu_nhap": "mỗi dòng một phiếu nhập",
          "dong_nhap": "mỗi dòng một dòng hàng nhập", "dot_giao": "mỗi dòng một đợt giao của một đơn",
          "khoan_chi": "mỗi dòng một khoản chi", "cong_no": "mỗi dòng một đơn còn nợ", "lo_hang": "mỗi dòng một lô hàng",
          "ton": "mỗi dòng một mặt hàng"}
_NAME_COLS = {"ten_khach", "ten_hang"}      # cột hiển thị: thiếu tên thì trả mã, không phải thiếu dữ liệu


def _unrecorded(ctx: ShopContext, today: dt.date) -> dict[str, list[str]]:
    """Bảng chuẩn -> các cột shop không ghi (cả bảng không có giá trị nào)."""
    cache = ctx.__dict__.setdefault("_cat", {})
    if ("khong_ghi", today) not in cache:       # theo ngày như ShopContext.catalog: bảng tính tại ngày đổi theo ngày
        out = {}
        for fact, cols in FIELDS.items():
            if fact in BY_RANGE:
                continue
            try:
                table = ctx.facts.table(fact, at=today if fact in AT_DATE else None)
                have = {r[0] for r in ctx.con.execute(f'DESCRIBE "{table}"').fetchall()}
                if not ctx.con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]:
                    out[fact] = []          # bảng trống tại ngày tính (vd hết nợ): không kết luận được cột nào không ghi
                    continue
                out[fact] = [c for c in cols if c not in have
                             or not ctx.con.execute(f'SELECT COUNT("{c}") FROM "{table}"').fetchone()[0]]
            except (NoSource, duckdb.Error):
                continue
        cache[("khong_ghi", today)] = out
    return cache[("khong_ghi", today)]


def _catalog(ctx: ShopContext, today: dt.date) -> str:
    out = []
    missing = _unrecorded(ctx, today)
    for line in ctx.catalog(today).split("\n"):
        fact, _, rest = line[2:].partition(":")
        if fact in BY_RANGE:        # bảng hàm nhận khoảng ngày làm tham số
            if "KHÔNG có dữ liệu" not in rest:
                out.append(f"- v_{fact}(tu, den) (bảng hàm: FROM v_{fact}(DATE 'A', DATE 'B'); mỗi dòng một đơn):{rest}")
            else:
                out.append(f"- v_{fact}:{rest}")
            continue
        extra = f"; {_EXTRA_COLS[fact]}" if fact in _EXTRA_COLS else ""
        if missing.get(fact):
            extra += f"; shop KHÔNG ghi: {', '.join(missing[fact])}"
        grain = f" ({_GRAIN[fact]})" if fact in _GRAIN and fact in missing else ""
        out.append(f"- v_{fact}{grain}:{rest}{extra}")
    return "\n".join(out)


def _raw_tables(ctx: ShopContext) -> str:
    """Bảng gốc của shop: cho câu về thông tin ngoài bảng chuẩn (bàn, khu vực, IMEI...)."""
    lines = []
    for t, role in ctx.con.execute("SELECT table_name, role FROM _meta_tables").fetchall():
        cols = [(c, column_meaning(o if o and fold(str(o)) != fold(c) else None, d, n))
                for c, o, d, n in ctx.con.execute("SELECT column_name, original_name, description, note FROM _meta_columns "
                                                  "WHERE table_name = ?", [t]).fetchall() if not c.endswith("__raw")]
        lines.append(f'- "{t}" ({role}): ' + ", ".join(f'"{c}"{m}' for c, m in cols[:30]))
    return "\n".join(lines)


def _names_in(ctx: ShopContext, question: str) -> str:
    """Điều kiện lọc của mặt hàng nêu trong câu: dòng bán có thể chỉ ghi tên, không ghi mã."""
    idx = _product_index(ctx.con)
    lines = []
    for k in ctx.names_in(question):
        pid, key, name = idx[k]
        cond = f"khoa_hang = {_q(key)}" if pid is None else f"(ma_hang = {_q(pid)} OR khoa_hang = {_q(key)})"
        lines.append(f"- '{name}': {cond}")
    return "\n".join(lines + _values_in(ctx, question)) or "(không có)"


_ENTITY_COLS = (("dong_ban", "hoat_chat"), ("dong_ban", "ten_khach"), ("phieu_nhap", "nha_cung_cap"), ("dot_giao", "tai_xe"),
                ("khoan_chi", "khoan_muc"))


def _values_in(ctx: ShopContext, question: str) -> list[str]:
    """Hoạt chất, tên khách, nhà cung cấp, tài xế, khoản mục ghi trong dữ liệu mà câu nêu nguyên cụm: ghi sẵn đúng cách viết
    (LLM hay tách hoạt chất phối hợp thành từng chất, hay viết lệch tên). Cụm quá ngắn dễ trùng chữ thường thì bỏ."""
    cache = ctx.__dict__.setdefault("_cat", {})
    if "gia_tri" not in cache:
        vals = []
        for fact, col in _ENTITY_COLS:
            try:
                t = ctx.facts.table(fact)
                vals += [(col, v, text_key(v)) for v, in ctx.con.execute(
                    f'SELECT DISTINCT "{col}" FROM "{t}" WHERE "{col}" IS NOT NULL LIMIT 5000').fetchall() if isinstance(v, str)]
            except (NoSource, duckdb.Error):
                continue
        cache["gia_tri"] = [(c, v, k) for c, v, k in vals if len(k) >= 6 and (" " in k or c == "hoat_chat")]
    q = f" {text_key(question)} "
    hits = [(c, v, k) for c, v, k in cache["gia_tri"] if f" {k} " in q]
    # hoạt chất phối hợp chứa từng hoạt chất: giữ cụm dài
    hits = [h for h in hits if not any(h[2] != o[2] and f" {h[2]} " in f" {o[2]} " for o in hits)]
    return [f"- {c} '{v}': khop({c}, {_q(v)})" for c, v, _ in hits[:6]]


def _prepare(ctx: ShopContext) -> None:
    if getattr(ctx, "sql_ready", False):
        return
    for name, expr in (("_khoa", "strip_accents(replace(lower(trim(CAST(x AS VARCHAR))), 'đ', 'd'))"),):
        ctx.con.execute(f"CREATE OR REPLACE TEMP MACRO {name}(x) AS {expr}")
    ctx.con.execute("CREATE OR REPLACE TEMP MACRO khop(a, b) AS _khoa(a) = _khoa(b)")
    ctx.sql_ready = True


def _views(ctx: ShopContext, sql: str, at: dt.date) -> None:
    """Dựng các bảng chuẩn SQL dùng tới. Thiếu nguồn: NoSource."""
    for fact in ("dong_ban", "don", "phieu_nhap", "dong_nhap", "dot_giao", "khoan_chi", "cong_no", "lo_hang", "ton"):
        if f"v_{fact}" in sql:
            table = ctx.facts.table(fact, at=at if fact in AT_DATE else None)
            cols = {r[0] for r in ctx.con.execute(f'DESCRIBE "{table}"').fetchall()}
            month = ", strftime(ngay, '%Y-%m') thang" if "ngay" in cols and "thang" not in cols else ""
            ctx.con.execute(f'CREATE OR REPLACE TEMP VIEW v_{fact} AS SELECT *{month} FROM "{table}"')
    if "v_dong_tien_no" in sql:
        # nợ thêm / trả nợ trong kỳ (§4) nhận kỳ làm tham số: bảng hàm, cùng SQL đã kiểm như Facts.dong_tien_no
        s = flow_sql(ctx.con)
        if s is None:
            raise NoSource("không có sổ thu / bảng đơn để tính nợ")
        for v in ("_tu", "_den", "_tu", "_den"):
            s = s.replace("?", v, 1)
        ctx.con.execute(f"CREATE OR REPLACE TEMP MACRO v_dong_tien_no(_tu, _den) AS TABLE SELECT CASE WHEN walk THEN NULL "
                        f"ELSE cid END khach, cname ten_khach, add no_them, paid_later tra_no FROM ({s})")


_TEXT_EQ = re.compile(r"\b((?:\w+\.)?(?:nhom_hang|nhom_khach|hoat_chat|ten_khach|ten_hang|khoan_muc|nha_cung_cap|tai_xe|bien_so"
                      r"|don_vi_co_ban))\s*=\s*('(?:[^']|'')*')", re.I)


def _soft_eq(sql: str) -> str:
    """So bằng trên cột chữ -> khop (bỏ dấu, hoa thường), như kế hoạch so tên nhóm, hoạt chất, khách (§3)."""
    return _TEXT_EQ.sub(lambda m: f"khop({m[1]}, {m[2]})", sql)


_CODE = re.compile(r"(?<![\w])([A-Za-z]{1,4}[-_]?\d{1,6})(?![\w])")


def _missing_code(ctx: ShopContext, sql: str, question: str) -> str | None:
    """Mã khách / nhân viên / hàng / đơn nêu trong câu mà SQL không có: thường là LLM bỏ mất điều kiện."""
    low = sql.lower()
    for code in dict.fromkeys(_CODE.findall(question)):
        if code.lower() in low:
            continue
        try:
            t = ctx.facts.table("dong_ban")
            hit = ctx.con.execute(f'SELECT 1 FROM "{t}" WHERE upper(khach) = ? OR upper(nhan_vien) = ? OR upper(hang) = ? '
                                  f'OR upper(don) = ? LIMIT 1', [code.upper()] * 4).fetchone()
        except (NoSource, duckdb.Error):
            return None
        if hit:
            return f"câu nêu mã {code}: lọc đúng theo mã đó"
    return None


def _execute(con, sql: str) -> list[tuple]:
    timer = threading.Timer(SQL_TIMEOUT, con.interrupt)
    timer.start()
    try:
        return con.execute(sql).fetchall()
    finally:
        timer.cancel()


def _execute_alias(con, sql: str) -> tuple[list[tuple], str]:
    """Chạy SQL; lỗi 'không có cột X' mà X là tên cột gốc (README) của đúng một cột -> đổi sang tên trong DB, chạy lại."""
    for _ in range(4):
        try:
            return _execute(con, sql), sql
        except duckdb.BinderException as e:
            new = alias.fix_sql(con, sql, str(e))
            if not new:
                raise
            sql = new
    return _execute(con, sql), sql


def _cell(v):
    if isinstance(v, (dt.datetime, dt.date)):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, float) and v.is_integer():
        return int(v)
    if isinstance(v, float):
        return round(v, 2)
    return v


def to_value(rows: list[tuple], ra: str):
    """Kết quả SQL -> giá trị cùng dạng với bộ chạy kế hoạch. Không hợp dạng: ValueError."""
    if not rows or rows[0] is None:
        raise ValueError("SQL không trả dòng nào")
    first = rows[0][0]
    if ra in ("tien", "number", "percent", "date", "string", "boolean"):
        if len(rows) != 1 or len(rows[0]) != 1:
            raise ValueError(f'"ra": "{ra}" cần 1 dòng 1 cột, SQL trả {len(rows)} dòng {len(rows[0])} cột')
        if first is None:
            raise ValueError("không có dữ liệu trong kỳ")
    if ra == "tien":
        return int(math.floor(float(first) + 0.5))
    if ra == "percent":
        return round(float(first), 2)
    if ra == "number":
        return _cell(float(first) if not isinstance(first, int) else first)
    if ra == "boolean":
        if not isinstance(first, (bool, int)):
            raise ValueError("boolean cần đúng / sai")
        return bool(first)
    if ra == "date":
        s = _cell(first)
        if not re.fullmatch(r"\d{4}-\d{2}(-\d{2})?", str(s)):
            raise ValueError(f"date lạ {s}")
        return str(s)
    if ra == "string":
        return {"names": [str(first)], "id": str(first)}
    if ra == "list":
        cells = list(rows[0]) if len(rows) == 1 and len(rows[0]) > 1 else [r[0] for r in rows]
        if any(c is None for c in cells):
            raise ValueError("danh sách có ô trống")
        return [{"names": [c], "id": c} if isinstance(c, str) and not re.fullmatch(r"\d{4}-\d{2}(-\d{2})?", c)
                else _cell(c) for c in cells]
    if ra == "table":
        if len(rows[0]) != 2:
            raise ValueError("table cần 2 cột: tên, giá trị")
        return {"bang": [[{"names": [str(a)], "id": str(a)}, _cell(b)] for a, b in rows]}
    raise ValueError(f"ra lạ {ra}")


def _named(ctx: ShopContext, s: str) -> dict:
    """Ô SQL là mã khách / hàng / nhân viên: thêm tên đứng trước mã (§9 nộp tên như file ghi)."""
    names = []
    try:
        t = ctx.facts.table("dong_ban")
        for idc, nc in (("khach", "ten_khach"), ("hang", "ten_hang")):
            names += [n for n, in ctx.con.execute(f'SELECT DISTINCT {nc} FROM "{t}" WHERE {idc} = ? AND {nc} IS NOT NULL '
                                                  f'LIMIT 3', [s]).fetchall()]
    except (NoSource, duckdb.Error):
        pass
    for role, idc, nc in (("customers", "customer_id", "customer_name"), ("products", "product_id", "product_name"),
                          ("staff", "staff_id", "staff_name")):
        try:
            names += names_by_id(ctx.con, role, idc, nc, s)
        except duckdb.Error:
            pass
    return {"names": [n for n in dict.fromkeys(names) if n and n != s] + [s], "id": s}


def _code_label(ctx: ShopContext, v: str) -> str | None:
    """Mã chuẩn kênh / thanh toán SQL trả ra ('tai_quay') -> nhãn trong sổ ('Tại cửa hàng'); không phải mã thì None."""
    try:
        return ctx.facts.code_labels().get(v)
    except (NoSource, duckdb.Error):
        return None


def _with_names(ctx: ShopContext, v):
    if isinstance(v, dict) and "names" in v:
        return _named(ctx, v["id"])
    if isinstance(v, str) and (lab := _code_label(ctx, v)):
        return {"names": [lab, v], "id": v}
    if isinstance(v, dict) and "bang" in v:
        return {"bang": [[_with_names(ctx, r[0]), *r[1:]] for r in v["bang"]]}
    if isinstance(v, list):
        return [_with_names(ctx, x) for x in v]
    return v


def _strip_strings(sql: str) -> str:
    return re.sub(r"'(?:[^']|'')*'", "''", sql)


_DATE_CMP = re.compile(r"""(?<![\w."])((?:"[^"]+"|[A-Za-z_]\w*)(?:\.(?:"[^"]+"|[A-Za-z_]\w*))?)\s*(<=|=|(?i:between))"""
                       r"""(\s*(?i:date)\s*'\d{4}-\d{2}-\d{2}')""")
_SQL_WORDS = {"and", "or", "not", "where", "when", "then", "else", "on", "select", "date", "case", "is", "in"}


def _dialect(sql: str) -> str:
    """Cú pháp SQL nơi khác mà DuckDB không nhận: MINUS (Oracle) -> EXCEPT. Không đụng chữ trong chuỗi.
    Cột so với một NGÀY bằng <= / BETWEEN: cột có giờ (2025-09-30 18:00) rơi khỏi ngày cuối kỳ -> so theo ngày."""
    parts = re.split(r"('(?:[^']|'')*')", sql)
    sql = "".join(p if k % 2 else re.sub(r"(?i)\bminus\b", "EXCEPT", p) for k, p in enumerate(parts))
    return _DATE_CMP.sub(lambda m: m.group(0) if m.group(1).lower() in _SQL_WORDS
                         else f"TRY_CAST({m.group(1)} AS DATE) {m.group(2)}{m.group(3)}", sql)


def _block_text(sql: str, p: int) -> str:
    """Chữ của khối SELECT chứa vị trí p, bỏ phần trong ngoặc con (truy vấn con, đối số hàm)."""
    depth, start = 0, 0
    for i in range(p - 1, -1, -1):
        if sql[i] == ")":
            depth += 1
        elif sql[i] == "(":
            if depth == 0:
                start = i + 1
                break
            depth -= 1
    out, depth = [], 0
    for ch in sql[start:]:
        if ch == "(":
            depth += 1
        elif ch == ")":
            if depth == 0:
                break
            depth -= 1
        elif depth == 0:
            out.append(ch)
    return "".join(out)


_GROUP_BY = re.compile(r"(?is)\bgroup\s+by\b(.*?)(?:\bhaving\b|\border\s+by\b|\blimit\b|\bqualify\b|$)")
_LINE_WORD = re.compile(r"(?i)(?<!\w)dòng(?!\w)")


def _per_order(block: str) -> bool:
    """Khối nhóm theo đơn: COUNT(*) trong đó là số dòng của từng đơn, không phải đếm đơn."""
    m = _GROUP_BY.search(block)
    return bool(m and re.search(r"(?<![\w.])(?:\w+\.)?don\b", m[1]))


def _asks_lines(question: str, rules: str) -> bool:
    """Câu đo trên từng dòng hàng ("giá trị dòng bình quân", "tỉ lệ dòng có giảm"): đếm dòng của v_dong_ban là đúng.
    Câu gõ không dấu ("dong" lẫn với "đồng") thì xét tên luật nêu trong câu (ô đầu dòng bảng rulebook) có chữ "dòng" không."""
    if _LINE_WORD.search(unicodedata.normalize("NFC", question)):
        return True
    f = fold(question)
    if not re.search(r"\bdong\b", f):
        return False
    for row in rule_rows(rules):
        term = unicodedata.normalize("NFC", row.strip().strip("|").split("|")[0].strip())
        if _LINE_WORD.search(term) and fold(term) in f:
            return True
    return False


def _block_from(sql: str, p: int) -> str | None:
    """Bảng sau FROM của khối SELECT chứa vị trí p (không tính truy vấn con)."""
    depth, start = 0, 0
    for i in range(p - 1, -1, -1):
        if sql[i] == ")":
            depth += 1
        elif sql[i] == "(":
            if depth == 0:
                start = i + 1
                break
            depth -= 1
    depth = 0
    for i in range(start, len(sql)):
        ch = sql[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            if depth == 0:
                return None
            depth -= 1
        elif depth == 0 and ch in "fF" and (i == 0 or not (sql[i - 1].isalnum() or sql[i - 1] == "_")):
            m = re.match(r"from\s+(\(|\"?\w+\"?)", sql[i:], re.I)
            if m:
                return m.group(1).strip('"').lower()
    return None


def _order_clauses(sql: str) -> list[str]:
    """Phần sau mỗi ORDER BY, đến LIMIT hoặc hết khối (ngoặc trong hàm như SUM(tien) không cắt)."""
    out = []
    for m in re.finditer(r"(?i)\border\s+by\b", sql):
        depth, i = 0, m.end()
        while i < len(sql):
            ch = sql[i]
            if ch == "(":
                depth += 1
            elif ch == ")":
                if depth == 0:
                    break
                depth -= 1
            elif depth == 0 and ch in "lL" and not (sql[i - 1].isalnum() or sql[i - 1] == "_") \
                    and re.match(r"(?i)limit\b", sql[i:]):
                break
            i += 1
        out.append(sql[m.end():i])
    return out


_MAX_Q = re.compile(r"\b(nhieu nhat|cao nhat|lon nhat|dat nhat|chay nhat|top|manh nhat|dong nhat)\b")
# không có "cham nhat": bỏ dấu thì "chăm nhất" (nhiều nhất) và "chậm nhất" trùng nhau
_MIN_Q = re.compile(r"\b(it nhat(?!\s+\d)|thap nhat|nho nhat|re nhat|e nhat|kem nhat)\b")


_ASKS_DAY = ASKS_DAY
_ASKS_HOW_MUCH = re.compile(r"\b(?:bao nhieu|bao nhiu|bnhiu|bn|may)\b")
_ASKS_WHO = re.compile(r"\b(?:ai|nao|gi|ten|nhung|liet ke|top|danh sach|cac)\b")


def _is_name(v) -> bool:
    return (isinstance(v, dict) and "names" in v) or (isinstance(v, str) and not _IS_DATE.fullmatch(v))


def _sql_mismatch(sql: str, v, question: str, today: dt.date | None = None, rules: str = "") -> str | None:
    """Kết quả hay SQL không khớp điều câu hỏi: lỗi để LLM viết lại. Bỏ phiếu không bắt được lỗi này khi các lần sai giống nhau."""
    f = fold(question)
    if asks_yes_no(question) and not isinstance(v, bool):
        return 'câu hỏi có / không: "ra": "boolean", SQL trả TRUE / FALSE'
    if today and (why := _period_miss(sql, question, today)):
        return why
    if isinstance(v, str) and _IS_DATE.fullmatch(v) and not (_ASKS_DATE.search(f) or ASKS_DAY.search(f)):
        return "câu không hỏi ngày nào: trả thẳng con số câu hỏi cần"
    if _ASKS_DAY.search(f) and isinstance(v, (int, float)) and not isinstance(v, bool):
        return "câu hỏi ngày nào: trả về ngày (cột ngay), không phải con số"
    if _ASKS_HOW_MUCH.search(f) and not _ASKS_WHO.search(f) and _is_name(v):
        return "câu hỏi bao nhiêu: trả về con số, không phải tên"
    if isinstance(v, list) and v and isinstance(v[0], dict) and _ASKS_COUNT.search(f) and not _ASKS_NAMES.search(f):
        return "câu hỏi số lượng, không hỏi danh sách tên: trả một con số"
    bare = _strip_strings(sql)
    if re.search(r"(?i)\bke_don\b", bare) and not _ASKS_RX.search(f):
        return "câu không hỏi thuốc kê đơn: bỏ điều kiện ke_don"
    # đếm dòng v_dong_ban để ra số đơn là lỗi hay gặp; trừ khi câu đo trên dòng, hay khối nhóm theo đơn (số dòng mỗi đơn)
    if not _asks_lines(question, rules):
        for m in re.finditer(r"(?i)\bcount\s*\(\s*(\*|don\s*\))", bare):
            if _block_from(bare, m.start()) == "v_dong_ban" and not _per_order(_block_text(bare, m.start())):
                return "v_dong_ban mỗi dòng là một dòng hàng: đếm đơn dùng COUNT(DISTINCT don)"
    if re.search(r"\bdon\b", f):
        for m in re.finditer(r"(?i)(?<![\w.])(?:\w+\.)?tien\s*(?:>=|>|<=|<)\s*\d", bare):
            if _block_from(bare, m.start()) == "v_dong_ban":
                return "ngưỡng tiền của đơn so trên tổng tiền đơn: GROUP BY don HAVING SUM(tien) >= X, hoặc doanh_thu của v_don"
    mx, mn = bool(_MAX_Q.search(f)), bool(_MIN_Q.search(f))
    orders = _order_clauses(bare)
    if mx != mn and len(orders) == 1 and re.search(r"(?i)\blimit\b", bare):
        desc = bool(re.search(r"(?i)\bdesc\b", orders[0]))
        if mx and not desc:
            return "câu hỏi lớn nhất / nhiều nhất / cao nhất: ORDER BY ... DESC"
        if mn and desc:
            return "câu hỏi nhỏ nhất / ít nhất / thấp nhất: ORDER BY ... ASC"
    # §7: không có dữ liệu không phải 0; số 0 đúng thật rất hiếm, thường là lọc sai cột, sai tên, sai kỳ
    if _is_zero(v):
        return "kết quả bằng 0: xem lại cột lọc, tên, kỳ và đối tượng đếm"
    return None


def _uses_unrecorded(ctx: ShopContext, sql: str, today: dt.date) -> str | None:
    """Cột SQL dùng mà shop không ghi: không tính được (§7), không để ra 0 hay lặng lẽ bỏ điều kiện."""
    bare = _strip_strings(sql).lower()
    # tên đặt tạm (SUM(sl_co_ban) AS sl) không phải cột của bảng
    words = set(re.findall(r"[a-z_][a-z0-9_]*", bare)) - set(re.findall(r"\bas\s+([a-z_][a-z0-9_]*)", bare))
    missing = _unrecorded(ctx, today)
    used = [f for f in missing if f"v_{f}" in words]
    for c in sorted(({c for f in used for c in missing[f]} & words) - _NAME_COLS):
        if all(c in missing[f] or c not in FIELDS[f] for f in used):
            return c
    return None


class SqlBank:
    """Kho câu -> SQL đã kiểm với đáp án train (query/plan_sql.py), chọn theo khung câu như kho kế hoạch."""

    def __init__(self, path: str):
        self.bank = ExampleBank.__new__(ExampleBank)
        self.bank.items = []
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                e = json.loads(line)
                if e["shop"] not in HOLDOUT:
                    e["sig"] = mask(e["question"], _plan_names(e["plan"]))
                    self.bank.items.append(e)

    def pick(self, *args, **kw) -> list[dict]:
        return self.bank.pick(*args, **kw)


def _ask(ctx: ShopContext, q: dict, today: dt.date, temperature: float, fix=None, examples: list[dict] | None = None,
         rule_examples: list[dict] | None = None) -> dict:
    system = f"{SPEC_SQL}\n\nRULEBOOK:\n{ctx.rules}"
    at = _at_date(q["question"], today)
    prices = ctx.price_lines(q["question"])
    extra = "LỊCH SỬ GIÁ:\n" + "\n".join(prices) + "\n\n" if prices else ""
    extra += holiday_block(ctx, q["question"])
    ex = ""
    if examples:
        ex = "VÍ DỤ (của shop khác):\n" + "\n".join(f'Câu: {e["question"]}\nHôm nay: {e["as_of_date"]}\n'
                                                    + json.dumps({"sql": e["sql"], "ra": e["ra"]}, ensure_ascii=False) for e in examples) + "\n\n"
    rx = [e for e in rule_examples or [] if e.get("sql")]
    if rx:
        ex += "VÍ DỤ ĐỌC ĐỊNH NGHĨA (luật của shop khác):\n" + "\n".join(
            f'Luật: {e["rule"]}\nCâu: {e["question"]}\nHôm nay: {e["as_of_date"]}\n'
            + json.dumps({"cach_tinh": e["cach_tinh"], "sql": e["sql"], "ra": e["ra_sql"]}, ensure_ascii=False) for e in rx) + "\n\n"
    near = near_rules(ctx.rules, q["question"])
    focus = "DÒNG LUẬT GẦN VỚI CÂU (đối chiếu trước khi tính):\n" + "\n".join(near) + "\n\n" if near else ""
    user = (f"{readme_block(ctx.con)}BẢNG CHUẨN (ưu tiên dùng):\n{_catalog(ctx, today)}\n\n"
            f"BẢNG GỐC (chỉ khi bảng chuẩn không có thông tin):\n{_raw_tables(ctx)}\n\n"
            f"TÊN TRONG CÂU:\n{_names_in(ctx, q['question'])}\n\n{extra}"
            f"KỲ (hôm nay {today}; v_cong_no, v_lo_hang, v_ton tính đến hết {at}):\n{periods(today, q['question'])}\n\n{ex}{focus}"
            f"Câu: {q['question']}\nHôm nay: {today}\nTrả về JSON:")
    if fix:
        user += f"\n{json.dumps({'sql': fix[0]}, ensure_ascii=False)}\n\nCâu SQL trên chưa dùng được: {fix[1]}.\nViết lại, trả về JSON:"
    text = llm.chat(system, user, max_tokens=800, timeout=300, temperature=temperature)
    start = text.find("{")
    if start < 0:
        return {}
    try:
        out, _ = json.JSONDecoder().raw_decode(text, start)
    except json.JSONDecodeError:
        return {}
    return out if isinstance(out, dict) else {}


def _attempt(ctx: ShopContext, out: dict, q: dict, today: dt.date) -> tuple:
    if "khong_co" in out and "sql" not in out:
        why = str(out["khong_co"])
        # LLM chỉ đúng tên cột mà code xác nhận shop không ghi: kết luận không trả lời được (§7) như khi SQL dùng cột đó
        cols = {c for cs in _unrecorded(ctx, today).values() for c in cs} - _NAME_COLS
        hit = sorted(c for c in cols if re.search(rf"(?<!\w){re.escape(c)}(?!\w)", why))
        if hit:
            return "thieu_nguon", f"shop không ghi {hit[0]}", None, None, None
        return "llm_khong_co", why[:150], None, None, None
    sql, ra = _dialect(_soft_eq(str(out.get("sql") or "").strip().rstrip(";"))), out.get("ra")
    if not sql:
        return "loi", "không có sql", sql, None, ra
    if ";" in sql or not re.match(r"(?is)\s*(select|with)\b", sql):
        return "loi", "chỉ được một câu SELECT", sql, None, ra
    try:
        _prepare(ctx)
        _views(ctx, sql, _at_date(q["question"], today))
        if col := _uses_unrecorded(ctx, sql, today):
            raise NoSource(f"shop không ghi {col}")
        rows, sql = _execute_alias(ctx.con, sql)
        v = _with_names(ctx, to_value(rows, ra))
        if why := _missing_code(ctx, sql, q["question"]) or _sql_mismatch(sql, v, q["question"], today, getattr(ctx, "rules", "")):
            return "loi", why, sql, None, ra
        to_record("", v, "percent" if ra == "percent" else None)      # giá trị nộp được (có tên, là số): lỗi thì cho sửa
        return "tra_loi", value_key(v), sql, v, ra
    except NoSource as e:
        return "thieu_nguon", str(e)[:150], sql, None, ra
    except PlanError as e:
        return "loi", str(e)[:220], sql, None, ra
    except (ValueError, TypeError, duckdb.Error) as e:
        return "loi", f"{type(e).__name__}: {e}"[:220], sql, None, ra


def solve_sql(ctx: ShopContext, q: dict, temps=(0, 0.5, 0.9), bank: SqlBank | None = None, skip_shop=None, skip_kinds=None,
              skip_shops=None, rule_bank: RuleBank | None = None, skip_dong=None) -> dict:
    """Cùng cách bỏ phiếu với kế hoạch JSON: 2 lần ra cùng kết quả chạy mới nhận."""
    today = dt.date.fromisoformat(q["as_of_date"])
    ex = bank.pick(q["question"], ctx.names_in(q["question"]), skip_shop=skip_shop, skip_kinds=skip_kinds, skip_id=q["id"],
                   skip_shops=skip_shops) if bank else None
    rx = rule_bank.pick(q["question"], near_rules(ctx.rules, q["question"]), skip_shop=skip_shop, skip_dong=skip_dong,
                        need="sql") if rule_bank else None
    tally: Counter = Counter()
    keep: dict = {}
    notes = []
    for t in temps:
        out = _ask(ctx, q, today, t, examples=ex, rule_examples=rx)
        kind, detail, sql, v, ra = _attempt(ctx, out, q, today)
        if kind == "loi":
            notes.append(("sua", detail))
            out = _ask(ctx, q, today, t, fix=(sql, detail), examples=ex, rule_examples=rx)
            kind, detail, sql, v, ra = _attempt(ctx, out, q, today)
        if kind == "tra_loi":
            keep[detail] = {"value": v, "want": "percent" if ra == "percent" else None, "plan": sql}
        notes.append((kind, detail))
        key = (kind, detail) if kind == "tra_loi" else (kind, "")
        tally[key] += 1
        (top, n), = tally.most_common(1)
        if n >= 2:
            if top[0] == "tra_loi":
                return {"loai": "tra_loi", **keep[top[1]], "notes": notes}
            return {"loai": top[0], "notes": notes, "plan": sql}
    return {"loai": "khong_dong_thuan", "notes": notes}
