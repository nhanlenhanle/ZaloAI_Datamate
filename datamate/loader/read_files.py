"""Đọc file của một shop (csv / xlsx / sqlite) thành lưới ô thô.

Không parse giá trị ở bước này: tiền, ngày... giữ nguyên như trong file.
Ô rỗng ('' hoặc chỉ có khoảng trắng) được đổi thành None cho thống nhất.
"""
from __future__ import annotations

import csv
import io
import os
import sqlite3
import unicodedata
from dataclasses import dataclass, field

from python_calamine import CalamineWorkbook

DATA_EXTS = {".csv", ".xlsx", ".xls", ".xlsm", ".sqlite", ".db", ".sqlite3"}


@dataclass
class RawSheet:
    """Một lưới ô thô: một sheet Excel, một file CSV hoặc một bảng SQLite."""
    file: str                 # tên file, vd "DanhSachHoaDon.xlsx"
    sheet: str | None         # tên sheet / tên bảng sqlite; None với csv
    kind: str                 # "xlsx" | "csv" | "sqlite"
    rows: list[list] = field(default_factory=list)
    header_known: bool = False  # sqlite: dòng 0 chắc chắn là header


def _clean_cell(v):
    if v is None:
        return None
    if isinstance(v, str):
        # NFC: tiếng Việt dạng tổ hợp (NFD) nhìn giống nhưng so chuỗi sẽ khác
        v = unicodedata.normalize("NFC", v).strip()
        return v or None
    return v


def _clean_rows(rows) -> list[list]:
    out = [[_clean_cell(c) for c in r] for r in rows]
    # bỏ các dòng rỗng ở cuối
    while out and all(c is None for c in out[-1]):
        out.pop()
    return out


def read_xlsx(path: str) -> list[RawSheet]:
    wb = CalamineWorkbook.from_path(path)
    sheets = []
    for name in wb.sheet_names:
        rows = wb.get_sheet_by_name(name).to_python(skip_empty_area=False)
        sheets.append(RawSheet(fix_filename(os.path.basename(path)), name, "xlsx", _clean_rows(rows)))
    return sheets


def read_csv(path: str) -> list[RawSheet]:
    for enc in ("utf-8-sig", "utf-16", "cp1258"):
        try:
            with open(path, encoding=enc, newline="") as f:
                text = f.read()
            break
        except (UnicodeDecodeError, UnicodeError):
            continue
    else:
        raise ValueError(f"không đọc được encoding của {path}")
    rows = list(csv.reader(io.StringIO(text), delimiter=csv_delimiter(text)))
    return [RawSheet(fix_filename(os.path.basename(path)), None, "csv", _clean_rows(rows))]


def csv_delimiter(text: str, sample_rows: int = 50) -> str:
    """Dấu phân cách cho số cột đều nhau nhất ở các dòng đầu (Excel máy tiếng Việt hay xuất ';').
    Hoà thì ưu tiên dấu phẩy."""
    best, best_score = ",", -1.0
    head = text.splitlines()[:sample_rows]
    for d in (",", ";", "\t", "|"):
        counts = [len(r) for r in csv.reader(head, delimiter=d) if r]
        if not counts:
            continue
        mode = max(set(counts), key=counts.count)
        if mode < 2:
            continue
        score = counts.count(mode) / len(counts) + 0.001 * mode
        if score > best_score + 1e-9:
            best, best_score = d, score
    return best


def read_sqlite(path: str) -> list[RawSheet]:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        names = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        sheets = []
        for name in names:
            cur = con.execute(f'SELECT * FROM "{name}"')
            header = [d[0] for d in cur.description]
            rows = [header] + [list(r) for r in cur.fetchall()]
            sheets.append(RawSheet(fix_filename(os.path.basename(path)), name, "sqlite",
                                   _clean_rows(rows), header_known=True))
        return sheets
    finally:
        con.close()


def fix_filename(name: str) -> str:
    """Sửa tên file bị giải nén zip sai bảng mã.

    Vd trên đĩa là 'Danh s├ích h├áng h├│a.xlsx' (byte UTF-8 bị đọc theo CP437),
    README lại ghi 'Danh sách hàng hóa.xlsx'. Tên đúng sẵn thì giữ nguyên.
    """
    try:
        fixed = name.encode("cp437").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return name
    return unicodedata.normalize("NFC", fixed)


def list_data_files(shop_dir: str) -> list[str]:
    """Mọi file dữ liệu trong thư mục shop (bỏ README, file ẩn, file tạm ~$)."""
    out = []
    for name in sorted(os.listdir(shop_dir)):
        if name.startswith((".", "~$")):
            continue
        if os.path.splitext(name)[1].lower() in DATA_EXTS:
            out.append(os.path.join(shop_dir, name))
    return out


def read_file(path: str) -> list[RawSheet]:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".csv":
        return read_csv(path)
    if ext in (".sqlite", ".db", ".sqlite3"):
        return read_sqlite(path)
    return read_xlsx(path)


def read_shop(shop_dir: str) -> list[RawSheet]:
    sheets = []
    for path in list_data_files(shop_dir):
        sheets.extend(read_file(path))
    return sheets
