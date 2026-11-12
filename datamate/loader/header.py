"""Cắt một lưới ô thô thành bảng: tìm header, bỏ dòng tổng / ghi chú, gộp sheet.

Các pattern gặp trong data thật (train + public):
- Header ở dòng 0..3, phía trên là tiêu đề ("SỔ CHI TIẾT BÁN HÀNG"), dòng lọc
  ("Kỳ báo cáo: toàn bộ", "Trạng thái đơn hàng | Đặt hàng (Đã duyệt)") hoặc dòng trống.
- Header 2 tầng: dòng nhóm thưa ("Hàng", _, _, "Tiền", ...) ngay trên header thật.
- Dòng tổng xen giữa data, nhãn nằm ở cột bất kỳ: "Tổng ngày 02/06",
  "Cộng tháng 09/2026", "tổng 06/09", "TỔNG THÁNG", "Tổng cộng".
- Dòng ghi chú cuối sheet: "Ghi chú: số liệu ghi tay".
- Một file nhiều sheet: cùng header (chia theo tháng) -> gộp; khác header -> bảng riêng.

Giá trị ô KHÔNG bị sửa ở đây; mọi dòng bị bỏ đều được ghi lại trong `dropped`.
"""
from __future__ import annotations

import datetime as dt
import math
import os
import re
from dataclasses import dataclass, field

from .read_files import RawSheet

SCAN_ROWS = 30
# Sổ gõ không dấu ("Tong cong", "Cong thang 9"): chữ không dấu đứng một mình ("Tong", "Cong") có thể là tên người, nên
# dạng không dấu phải có từ thứ hai hoặc có số / ngày đi kèm.
SUMMARY_RE = re.compile(
    r"^(?:(tổng|cộng|total|subtotal)"
    r"(\s+(cộng|ngày|tháng|năm|quý|tuần|kỳ|ca))?"
    r"[\s:]*[\d/.\-\s]*"
    r"|(tong|cong)\s+(cong|ngay|thang|nam|quy|tuan|ky|ca)[\s:]*[\d/.\-\s]*"
    r"|(tong|cong)[\s:]*\d[\d/.\-\s]*)$",
    re.IGNORECASE,
)
NOTE_RE = re.compile(r"^(ghi chú|lưu ý|chú thích|note)\s*:", re.IGNORECASE)
# nhãn dòng tổng có số ("Tổng tiền tháng 3", "TC 03/2025"): chỉ nhận khi mở đầu bằng chữ kiểu tổng (lớp số vẫn phải khớp)
_TOTAL_WORD = re.compile(r"^(tổng|tong|tông|cộng|cong|t\.?\s?c\.?\b|tc\b|sum|total|subtotal|∑)")


@dataclass
class Table:
    name: str
    file: str
    sheets: list[str | None]
    columns: list[str]
    rows: list[list]
    src: list[tuple]                 # (sheet, số dòng trong sheet, đếm từ 1) cho từng dòng
    groups: dict[str, str] = field(default_factory=dict)   # cột -> nhóm header tầng trên
    preamble: list[str] = field(default_factory=list)      # dòng tiêu đề / bộ lọc trên header
    footnotes: list[str] = field(default_factory=list)     # dòng "Ghi chú: ..."
    dropped: list[tuple] = field(default_factory=list)     # (sheet, dòng, lý do, nội dung)


def _nonempty(row) -> list:
    return [c for c in row if c is not None]


def _header_cell(c) -> bool:
    """Ô header: chữ; hoặc năm / ngày làm tên cột (bảng theo năm, theo tháng: 'Hàng | 2024 | 2025')."""
    if isinstance(c, str):
        return True
    if isinstance(c, (int, float)) and not isinstance(c, bool):
        return float(c).is_integer() and 1900 <= c <= 2100
    return isinstance(c, (dt.date, dt.datetime))


def _is_header_like(row, min_cells: int) -> bool:
    cells = _nonempty(row)
    n_str = sum(isinstance(c, str) for c in cells)
    return len(cells) >= min_cells and all(_header_cell(c) for c in cells) and n_str >= 0.5 * len(cells)


def detect_header(rows: list[list]) -> tuple[int | None, int | None]:
    """Trả (dòng header, dòng nhóm phía trên hoặc None)."""
    scan = rows[:SCAN_ROWS]
    width = max((len(_nonempty(r)) for r in scan), default=0)
    if width == 0:
        return None, None
    min_cells = max(1, math.ceil(0.6 * width)) if width > 1 else 1
    for i, row in enumerate(scan):
        if not _is_header_like(row, min_cells):
            continue
        # dòng nhóm bị nhận nhầm: dòng ngay dưới cũng toàn chữ và dày hơn
        if i + 1 < len(rows):
            nxt = rows[i + 1]
            if _is_header_like(nxt, min_cells) and len(_nonempty(nxt)) > len(_nonempty(row)):
                return i + 1, i
        group = None
        if i > 0 and _nonempty(rows[i - 1]) and all(isinstance(c, str) for c in _nonempty(rows[i - 1])):
            prev = rows[i - 1]
            # dòng nhóm: thưa, các nhãn nằm trên vị trí có cột của header
            if 1 < len(_nonempty(prev)) < len(_nonempty(row)) and len(prev) > 2:
                group = i - 1
        return i, group
    return None, None


def _row_text(row) -> str:
    return " | ".join(str(c) for c in row if c is not None)


def classify_row(row, header: list) -> str | None:
    """Lý do bỏ dòng, hoặc None nếu là dòng data."""
    cells = _nonempty(row)
    if not cells:
        return "empty"
    # kiểm tra trước "summary": header có thể có cột tên "Cộng" (dev_010)
    if [c for c in row[:len(header)]] == header:
        return "repeat_header"
    if any(isinstance(c, str) and SUMMARY_RE.match(c) for c in cells):
        return "summary"
    if len(cells) <= 2 and isinstance(cells[0], str) and NOTE_RE.match(cells[0]):
        return "note"
    return None


def _make_columns(header_row: list, width: int) -> list[str]:
    cols, seen = [], {}
    for j in range(width):
        name = header_row[j] if j < len(header_row) else None
        if isinstance(name, float) and name.is_integer():
            name = int(name)                        # năm làm tên cột: "2024", không phải "2024.0"
        elif isinstance(name, dt.datetime):
            name = name.strftime("%Y-%m-%d")
        name = re.sub(r"\s+", " ", str(name)).strip() if name is not None else f"col_{j + 1}"
        if name in seen:
            seen[name] += 1
            name = f"{name} ({seen[name]})"
        else:
            seen[name] = 1
        cols.append(name)
    return cols


def _drop_unlabeled_totals(data: list, src: list, dropped: list, max_tail: int = 3):
    """Dòng tổng KHÔNG có chữ "Tổng/Cộng" ở cuối sheet: thưa ô, mọi ô số = tổng cột đó ở các dòng trên.
    Giữ lại thì doanh thu bị cộng gấp đôi."""
    from .parsers import parse_number
    if len(data) < 3:
        return
    filled = sorted(len(_nonempty(r)) for r in data)
    median = filled[len(filled) // 2]
    for _ in range(max_tail):
        row, body = data[-1], data[:-1]
        filled_cells = [(j, c) for j, c in enumerate(row) if c is not None and str(c).strip() != ""]
        cells = [(j, parse_number(c)) for j, c in filled_cells]
        # ô chữ (nhãn "Tong cong", "Sum", "Cộng tiền"... ghi kiểu gì cũng được) không làm hỏng phép kiểm: bằng chứng là
        # các ô SỐ đều bằng tổng cột phía trên. Nhãn chỉ được là chữ ngắn, không phải số / ngày.
        labels = [c for (j, c), (_, v) in zip(filled_cells, cells) if v is None]
        cells = [(j, v) for j, v in cells if v is not None]
        if not cells or len(filled_cells) > max(1, median // 2) or len(labels) > 1                 or any(not isinstance(c, str) or len(c) > 40 or re.search(r"\d", c) and not _TOTAL_WORD.match(c.strip().lower())
                       for c in labels):
            return
        ok = 0
        for j, v in cells:
            col = [parse_number(r[j]) for r in body if j < len(r) and r[j] is not None]
            col = [x for x in col if x is not None]
            if len(col) < 2 or abs(sum(col) - v) > max(1.0, 0.005 * abs(v)):
                return
            ok += 1
        if not ok:
            return
        sheet, k = src[-1]
        dropped.append((sheet, k, "summary_no_label", _row_text(row)))
        del data[-1], src[-1]


def extract_table(raw: RawSheet) -> Table | None:
    rows = raw.rows
    if not rows:
        return None
    if raw.header_known:
        h, g = 0, None
    else:
        h, g = detect_header(rows)
        if h is None:
            return None

    header_row = rows[h]
    body_start = h + 1
    data, src, dropped, footnotes = [], [], [], []
    for k in range(body_start, len(rows)):
        row = rows[k]
        reason = None if raw.header_known else classify_row(row, header_row)
        if reason is None:
            data.append(row)
            src.append((raw.sheet, k + 1))
        elif reason == "note":
            footnotes.append(_row_text(row))
        elif reason != "empty":
            dropped.append((raw.sheet, k + 1, reason, _row_text(row)))

    if not raw.header_known:
        _drop_unlabeled_totals(data, src, dropped)

    # độ rộng = vị trí cuối cùng có header hoặc có data
    last_hdr = max((j for j, c in enumerate(header_row) if c is not None), default=-1)
    last_data = max((max((j for j, c in enumerate(r) if c is not None), default=-1) for r in data), default=-1)
    width = max(last_hdr, last_data) + 1
    columns = _make_columns(header_row, width)
    data = [(r + [None] * width)[:width] for r in data]

    groups = {}
    if g is not None:
        cur = None
        for j, c in enumerate((rows[g] + [None] * width)[:width]):
            cur = c if c is not None else cur
            if cur is not None:
                groups[columns[j]] = cur
    preamble = [_row_text(r) for r in rows[:g if g is not None else h] if _nonempty(r)]

    stem = os.path.splitext(raw.file)[0]
    return Table(name=stem if raw.kind != "sqlite" else raw.sheet, file=raw.file,
                 sheets=[raw.sheet], columns=columns, rows=data, src=src, groups=groups,
                 preamble=preamble, footnotes=footnotes, dropped=dropped)


def _same_ledger(a: set, b: set) -> bool:
    """Sheet cùng file: cùng tập cột, hoặc gần cùng (sheet tháng sau thêm vài cột phụ)."""
    return a == b or (len(a & b) >= 3 and len(a & b) / len(a | b) >= 0.7)


def merge_sheets(tables: list[Table]) -> list[Table]:
    """Gộp các sheet cùng file có cùng tập cột (vd mỗi tháng một sheet); sheet thiếu cột thì để trống ô đó."""
    out: list[Table] = []
    by_file: dict[str, list[Table]] = {}
    for t in tables:
        by_file.setdefault(t.file, []).append(t)
    for file, ts in by_file.items():
        if ts[0].sheets == [None] or len(ts) == 1 or file.lower().endswith((".sqlite", ".db", ".sqlite3")):
            out.extend(ts)
            continue
        groups: list[list[Table]] = []
        for t in ts:
            for grp in groups:
                if _same_ledger(set(grp[0].columns), set(t.columns)):
                    grp.append(t)
                    break
            else:
                groups.append([t])
        for grp in groups:
            base = grp[0]
            if len(groups) > 1:
                base.name = f"{base.name}__{base.sheets[0]}" if len(grp) == 1 else base.name
            for t in grp[1:]:
                new = [c for c in t.columns if c not in base.columns]
                if new:
                    base.columns.extend(new)
                    for r in base.rows:
                        r.extend([None] * len(new))
                pos = {c: i for i, c in enumerate(t.columns)}     # sắp lại theo thứ tự cột của sheet đầu
                base.rows.extend([r[pos[c]] if c in pos else None for c in base.columns] for r in t.rows)
                base.src.extend(t.src)
                base.sheets.extend(t.sheets)
                base.dropped.extend(t.dropped)
                base.footnotes.extend(t.footnotes)
                base.preamble.extend(p for p in t.preamble if p not in base.preamble)
            out.append(base)
    # tên trùng (vd 2 nhóm sheet cùng tên file) -> thêm hậu tố
    seen: dict[str, int] = {}
    for t in out:
        if t.name in seen:
            seen[t.name] += 1
            t.name = f"{t.name}_{seen[t.name]}"
        else:
            seen[t.name] = 1
    return out


def load_tables(raw_sheets: list[RawSheet]) -> tuple[list[Table], list[str]]:
    """Trả (các bảng, cảnh báo cho sheet không tìm được header)."""
    tables, warnings = [], []
    for raw in raw_sheets:
        t = extract_table(raw)
        if t is None:
            if raw.rows:
                warnings.append(f"{raw.file}[{raw.sheet}]: không tìm được header")
            continue
        tables.append(t)
    return merge_sheets(tables), warnings
