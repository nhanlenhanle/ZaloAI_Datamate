"""Parse README.md của một shop.

Khuôn README (giống nhau ở cả 44 shop train + public):
    # Dữ liệu <id>
    <đoạn mô tả shop / cách xuất file>
    ## File                       - `Ten.xlsx` (xlsx); có thể là mẫu `BanHang_T<tháng>_<năm>.xlsx`
    ## Cột trong `file`[, sheet `S`]   - **Tên cột**: mô tả   (từ vựng mô tả cố định: "mã đơn", "tên hàng"...)
    ## Bảng                       (sqlite) danh sách bảng
    ## Quy ước                    - Dữ liệu có đến hết dd/mm/yyyy.
                                  - **Chủ đề**: câu có dạng **Cột** là <ý nghĩa> / `bang.cot` là <ý nghĩa>
                                  - **Quy đổi đơn vị**: ... rồi các dòng "  - Tên hàng: 1 lốc = 6 lon"
                                    hoặc "hệ số quy đổi ở `File.xlsx`"
Có 7/44 shop không có mục "Cột trong"; khi đó chỉ còn Quy ước + tên cột.
"""
from __future__ import annotations

import datetime as dt
import fnmatch
import os
import re
from dataclasses import dataclass, field

from .parsers import fold


@dataclass
class ColumnDoc:
    file: str | None        # tên file / mẫu tên file; None nếu không rõ file
    sheet: str | None
    column: str             # tên cột như ghi trong README (sqlite: chỉ tên cột, không kèm bảng)
    description: str
    source: str             # "columns" (mục Cột trong) | "convention" (mục Quy ước)
    table: str | None = None  # sqlite: tên bảng trong `bang.cot`


@dataclass
class UnitConversion:
    product: str
    big_unit: str
    factor: float
    base_unit: str


@dataclass
class ReadmeInfo:
    shop: str
    intro: str = ""
    files: list[str] = field(default_factory=list)
    sqlite_tables: list[str] = field(default_factory=list)
    columns: list[ColumnDoc] = field(default_factory=list)
    conventions: list[tuple[str, str]] = field(default_factory=list)   # (chủ đề, nội dung)
    data_end: dt.date | None = None
    unit_conversions: list[UnitConversion] = field(default_factory=list)
    conversion_files: list[str] = field(default_factory=list)          # "hệ số quy đổi ở `X`"

    def docs_for(self, file: str, sheets: list, table: str | None = None) -> list[ColumnDoc]:
        """Mô tả cột áp cho một bảng (khớp file, sheet; sqlite khớp tên bảng)."""
        out = []
        for d in self.columns:
            if d.table is not None:
                if table is not None and d.table == table:
                    out.append(d)
                continue
            # gợi ý ở Quy ước không gắn file: áp cho mọi bảng có cột cùng tên
            if d.file is not None and not file_matches(d.file, file):
                continue
            if d.sheet is not None and d.sheet not in sheets:
                continue
            out.append(d)
        return out


def file_matches(pattern: str, filename: str) -> bool:
    """'BanHang_T<tháng>_<năm>.xlsx' khớp 'BanHang_T1_2025.xlsx'; so không phân biệt hoa thường."""
    glob = re.sub(r"<[^>]*>", "*", pattern)
    return fnmatch.fnmatch(fold(filename), fold(glob))


_H_COLS = re.compile(r"^##\s*Cột trong\s+`([^`]+)`(?:\s*,\s*sheet\s+`([^`]+)`)?", re.I)
_BULLET = re.compile(r"^-\s+\*\*(.+?)\*\*\s*:\s*(.*)$")
_FILE_ITEM = re.compile(r"^-\s+`([^`]+)`")
_DATA_END = re.compile(r"dữ liệu có đến hết\s+(\d{1,2})/(\d{1,2})/(\d{4})", re.I)
_CONV_LINE = re.compile(r"^\s+-\s+(.+):\s*1\s+(.+?)\s*=\s*([\d.,]+)\s+(.+?)\s*$")
_CONV_FILE = re.compile(r"hệ số quy đổi ở\s+((?:`[^`]+`(?:\s*(?:,|và)\s*)?)+)", re.I)
# "**A** là ...", "**A**, **B** là ...", "`t.c` là ..."; ý nghĩa kéo tới dấu ; hoặc hết câu
_REF = r"(?:\*\*[^*]+\*\*|`[^`]+`)"
_HINT = re.compile(rf"({_REF}(?:\s*,\s*{_REF})*)\s+(?:\([^)]*\)\s+)?là\s+(.+?)(?=;|\.\s|\.$|$)")


def _strip_ref(r: str) -> str:
    return r.strip("*`").strip()


def parse_readme(path: str) -> ReadmeInfo:
    shop = os.path.basename(os.path.dirname(path))
    info = ReadmeInfo(shop=shop)
    if not os.path.exists(path):
        return info
    with open(path, encoding="utf-8-sig") as f:
        lines = [l.rstrip("\n") for l in f]

    section, cur_file, cur_sheet, intro = None, None, None, []
    last_topic = None
    for line in lines:
        s = line.strip()
        if s.startswith("# "):
            section = "intro"
            continue
        if s.startswith("## "):
            m = _H_COLS.match(s)
            if m:
                section, cur_file, cur_sheet = "cols", m[1], m[2]
            else:
                head = fold(s[3:])
                section = ("files" if head.startswith("file") else "tables" if head.startswith("bang")
                           else "conv" if head.startswith("quy uoc") else "other")
            continue
        if section == "intro":
            if s:
                intro.append(s)
        elif section == "files":
            if m := _FILE_ITEM.match(s):
                info.files.append(m[1])
        elif section == "tables":
            names = re.findall(r"`([^`]+)`", s)
            if names and not info.sqlite_tables:
                info.sqlite_tables = names        # dòng đầu: danh sách bảng
            elif s:
                intro.append(s)                   # câu mô tả quan hệ bảng
        elif section == "cols":
            if m := _BULLET.match(s):
                info.columns.append(ColumnDoc(cur_file, cur_sheet, m[1].strip(), m[2].strip(), "columns"))
        elif section == "conv":
            if m := _DATA_END.search(s):
                info.data_end = dt.date(int(m[3]), int(m[2]), int(m[1]))
            if (m := _CONV_LINE.match(line)) and last_topic and fold(last_topic).startswith("quy doi"):
                factor = float(m[3].replace(",", "."))
                info.unit_conversions.append(UnitConversion(m[1].strip(), m[2].strip(), factor, m[4].strip()))
                continue
            if m := _BULLET.match(s):
                last_topic, body = m[1].strip(), m[2].strip()
                info.conventions.append((last_topic, body))
                for cm in _CONV_FILE.finditer(body):
                    info.conversion_files.extend(re.findall(r"`([^`]+)`", cm[1]))
                for hm in _HINT.finditer(body):
                    desc = hm[2].strip()
                    for ref in re.findall(_REF, hm[1]):
                        name = _strip_ref(ref)
                        table = None
                        if ref.startswith("`") and "." in name and info.sqlite_tables:
                            table, name = name.split(".", 1)
                        elif ref.startswith("`"):
                            continue   # `File.xlsx` là tên file, không phải cột
                        info.columns.append(ColumnDoc(None, None, name, desc, "convention", table))
            elif s.startswith("-"):
                info.conventions.append(("", s.lstrip("- ").strip()))
    info.intro = "\n".join(intro)
    return info
