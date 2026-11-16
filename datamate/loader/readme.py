"""Parse README.md của một shop.

Khuôn README (giống nhau ở các shop train):
    # Dữ liệu <id>
    <đoạn mô tả shop / cách xuất file>
    ## File                       - `Ten.xlsx` (xlsx); có thể là mẫu `BanHang_T<tháng>_<năm>.xlsx`
    ## Cột trong `file`[, sheet `S`]   - **Tên cột**: mô tả   (từ vựng mô tả cố định: "mã đơn", "tên hàng"...)
    ## Bảng                       (sqlite) danh sách bảng
    ## Quy ước                    - Dữ liệu có đến hết dd/mm/yyyy.
                                  - **Chủ đề**: câu có dạng **Cột** là <ý nghĩa> / `bang.cot` là <ý nghĩa>
                                  - **Quy đổi đơn vị**: ... rồi các dòng "  - Tên hàng: 1 lốc = 6 lon"
                                    hoặc "hệ số quy đổi ở `File.xlsx`"
Có shop không có mục "Cột trong"; khi đó chỉ còn Quy ước + tên cột.
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
# "Dữ liệu có đến hết 31/03/2025", "Dữ liệu từ 01/02/2025 đến hết 12/09/2026", "Số liệu cập nhật tới 31/03/2025",
# "Sổ ghi đến ngày 30-06-2026", "tính đến 30.06.2026": lấy ngày đứng sau đến / tới / hết
_DATA_END = re.compile(r"(?:dữ liệu|số liệu|sổ|ghi nhận|cập nhật)[^.\n]{0,40}?(?:đến|tới|hết)\s*(?:hết\s*)?(?:ngày\s*)?"
                       r"(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})", re.I)
_CONV_LINE = re.compile(r"^\s+-\s+(.+):\s*1\s+(.+?)\s*=\s*([\d.,]+)\s+(.+?)\s*$")
# quy ước dạng câu: "Ống PVC D32, Ống PVC D50 bán theo bó, 1 bó = 10 cây" -> mỗi tên hàng một dòng quy đổi
_CONV_SENT = re.compile(r"(?<![\w.])1\s+([^\W\d_][\w ]{0,15}?)\s*=\s*(\d+(?:[.,]\d+)?)\s+([^\W\d_][\w ]{0,15}?)(?=\s*[;,.)]|\s*$)")
_CONV_LIST_END = re.compile(r"\s+(?:bán|tính|ghi|nhập|đóng)\s+theo\b", re.I)
_TEN_CHUNG = re.compile(r"^(mặt hàng|hàng|sản phẩm|đơn vị|đv|các|mọi|mỗi|hàng hoá|hàng hóa)\b", re.I)


def _conv_in_sentence(body: str) -> list:
    """Câu quy ước nêu tên từng mặt hàng rồi '1 <đơn vị lớn> = <n> <đơn vị cơ bản>'. Bỏ câu ví dụ ("vd", "ví dụ")."""
    out = []
    for m in _CONV_SENT.finditer(body):
        truoc = body[:m.start()]
        if re.search(r"\b(vd|ví dụ|chẳng hạn)\b", truoc[-40:], re.I):
            continue
        e = _CONV_LIST_END.search(truoc)
        if not e:
            continue
        danh_sach = re.sub(r"\*\*|`", "", truoc[:e.start()]).strip(" :;-")
        ten = [t.strip(" .") for t in re.split(r",\s*|\s+và\s+", danh_sach) if t.strip(" .")]
        ten = [t for t in ten if len(t.split()) >= 2 and not _TEN_CHUNG.match(t)]
        try:
            hs = float(m[2].replace(",", "."))
        except ValueError:
            continue
        if hs <= 1:
            continue
        out += [UnitConversion(t, m[1].strip(), hs, m[3].strip()) for t in ten]
    return out
_CONV_FILE = re.compile(r"hệ số quy đổi ở\s+((?:`[^`]+`(?:\s*(?:,|và)\s*)?)+)", re.I)
# "**A** là ...", "**A**, **B** là ...", "`t.c` là ..."; ý nghĩa kéo tới dấu ; hoặc hết câu
_REF = r"(?:\*\*[^*]+\*\*|`[^`]+`)"
_HINT = re.compile(rf"({_REF}(?:\s*,\s*{_REF})*)\s+(?:\([^)]*\)\s+)?là\s+(.+?)(?=;|\.\s|\.$|$)")


def _strip_ref(r: str) -> str:
    return r.strip("*`").strip()


_FILE_EXTS = {".csv", ".xlsx", ".xls", ".sqlite", ".db", ".json", ".txt"}
_FMT_WORDS = {"csv", "xlsx", "xls", "sqlite"}
_INLINE_PAT = re.compile(r"(\*\*([^*]+)\*\*|`([^`]+)`)\s*\(")


def _extract_inline_columns(line: str) -> list[tuple[str | None, str | None, str, str]]:
    """Rút mô tả cột inline dạng **Tên** (...) hoặc `tên` (...) trong dòng mô tả file/bảng."""
    s = line.strip()
    if not s.startswith("- "):
        return []
    m_owner = re.search(r"`([^`]+)`", s)
    if not m_owner:
        return []
    owner_raw = m_owner.group(1).strip()
    _, ext = os.path.splitext(owner_raw.lower())
    if ext in _FILE_EXTS:
        file_name, table_name = owner_raw, None
    else:
        file_name, table_name = None, owner_raw

    colon_idx = s.find(":", m_owner.end())
    if colon_idx == -1:
        return []
    rest = s[colon_idx + 1:]

    res = []
    pos = 0
    while pos < len(rest):
        m = _INLINE_PAT.search(rest, pos)
        if not m:
            break
        name = (m.group(2) if m.group(2) is not None else m.group(3)).strip()
        open_idx = m.end() - 1
        count = 0
        close_idx = -1
        for i in range(open_idx, len(rest)):
            if rest[i] == "(":
                count += 1
            elif rest[i] == ")":
                count -= 1
                if count == 0:
                    close_idx = i
                    break
        if close_idx == -1:
            pos = m.end()
            continue
        desc = rest[open_idx + 1:close_idx].strip()
        pos = close_idx + 1

        _, name_ext = os.path.splitext(name.lower())
        if name_ext in _FILE_EXTS:
            continue
        if name.lower() == owner_raw.lower():
            continue
        if desc.lower() in _FMT_WORDS:
            continue
        res.append((file_name, table_name, name, desc))
    return res


def parse_readme(path: str) -> ReadmeInfo:
    shop = os.path.basename(os.path.dirname(path))
    info = ReadmeInfo(shop=shop)
    if not os.path.exists(path):
        return info
    with open(path, encoding="utf-8-sig") as f:
        lines = [l.rstrip("\n") for l in f]

    def add_inline(line_str: str):
        if not os.environ.get("DATAMATE_INLINE"):   # tắt mặc định
            return
        existing = {(d.file, d.table, d.column) for d in info.columns}
        for f_name, t_name, c_name, c_desc in _extract_inline_columns(line_str):
            key = (f_name, t_name, c_name)
            if key not in existing:
                info.columns.append(ColumnDoc(f_name, None, c_name, c_desc, "inline", t_name))
                existing.add(key)

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
                # README viết tay đặt tên mục tuỳ ý ("Các file", "Ghi chú", "Lưu ý khi đọc số liệu"...): mục nào không phải
                # danh sách file / bảng / cột thì là quy ước (trước đây chỉ nhận "Quy ước" -> mất hết quy ước)
                section = ("files" if re.search(r"\bfile\b", head) else "tables" if head.startswith("bang")
                           else "conv")
            continue
        if section == "intro":
            if s:
                intro.append(s)
        elif section == "files":
            if m := _FILE_ITEM.match(s):
                info.files.append(m[1])
            if s.startswith("- "):
                add_inline(s)
        elif section == "tables":
            names = re.findall(r"`([^`]+)`", s)
            if names and not info.sqlite_tables:
                info.sqlite_tables = names        # dòng đầu: danh sách bảng
            elif s:
                intro.append(s)                   # câu mô tả quan hệ bảng
            if s.startswith("- "):
                add_inline(s)
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
                info.unit_conversions.extend(_conv_in_sentence(body))
                for cm in _CONV_FILE.finditer(body):
                    info.conversion_files.extend(re.findall(r"`([^`]+)`", cm[1]))
                for hm in _HINT.finditer(body):
                    desc = hm[2].strip()
                    # "các dòng cùng **STT** là một đơn": cột đó là mã đơn (sổ ghi tay đánh số thứ tự đơn)
                    if re.search(r"cùng\s*$", body[:hm.start(1)], re.I) and re.match(
                            r"(một|1)\s+(đơn|hoá đơn|hóa đơn|bill|phiếu bán)", desc, re.I):
                        desc = "mã đơn (các dòng cùng giá trị là một đơn)"
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
