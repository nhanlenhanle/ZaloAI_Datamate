"""Đọc file của một shop (csv / xlsx / sqlite) thành lưới ô thô.

Không parse giá trị ở bước này: tiền, ngày... giữ nguyên như trong file.
Ô rỗng ('' hoặc chỉ có khoảng trắng) được đổi thành None cho thống nhất.
"""
from __future__ import annotations

import csv
import io
import os
import datetime as dt
import re
import shutil
import sqlite3
import sys
import tempfile
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


_UNIX_COL = re.compile(r"(^|_)(at|time|timestamp|ts|date|ngay|gio|thoi_gian)$|_at_|created|updated|paid", re.I)
_CODE_COL = re.compile(r"^(sku|code|ma|so)$|_(code|no|number)$", re.I)


def _singular(t: str) -> str:
    t = t.lower()
    return t[:-3] + "y" if t.endswith("ies") else t[:-2] if t.endswith(("ses", "xes")) else t[:-1] if t.endswith("s") and not t.endswith(("us", "ss")) else t


def _find_ref(base: str, tables: dict, self_name: str):
    """Bảng mà cột <base>_id trỏ tới: <base>, <base>s, <base>es, ..._<base> (order_status cho status_id)."""
    b = base.lower()
    cands = [t for t in tables if t != self_name and "id" in tables[t][0]
             and (t.lower() in (b, b + "s", b + "es", b[:-1] + "ies" if b.endswith("y") else b)
                  or t.lower().endswith("_" + b) or t.lower().endswith("_" + b + "s"))]
    return cands[0] if len(cands) == 1 else None


def _unix_to_local(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v:
        return v
    x = v / 1000 if v > 1e11 else v
    return (dt.datetime(1970, 1, 1) + dt.timedelta(seconds=float(x) + 7 * 3600)).strftime("%Y-%m-%d %H:%M:%S")


def _is_unix(vals: list) -> bool:
    nums = [v for v in vals if v is not None]
    if len(nums) < 3 or not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in nums):
        return False
    return all(9.46e8 <= v <= 2.21e9 for v in nums) or all(9.46e11 <= v <= 2.21e12 for v in nums)


def _flatten_pos(tables: dict) -> dict:
    """tables: tên -> (header, rows). Phần mềm POS lưu khoá id số và bảng tra; sổ của shop thì ghi thẳng mã, tên.
    Đưa về dạng sổ: id -> mã / tên, giờ Unix -> giờ Việt Nam. Không có cột *_id trỏ tới bảng nào thì không đổi khoá."""
    out = {t: (list(h), [list(r) for r in rows]) for t, (h, rows) in tables.items()}
    referenced = {}        # bảng thực thể có mã riêng -> base (tên thực thể)
    for t, (h, rows) in tables.items():
        for j, c in enumerate(h):
            if not isinstance(c, str) or not c.lower().endswith("_id") or c.lower() == "id":
                continue
            base = c[:-3]
            r = _find_ref(base, tables, t)
            if r is None:
                continue
            rh, rrows = tables[r]
            ki = rh.index("id")
            ni = rh.index("name") if "name" in rh else None
            code = next((i for i, x in enumerate(rh) if isinstance(x, str) and _CODE_COL.search(x) and i != ki
                         and len({rw[i] for rw in rrows if rw[i] is not None}) == sum(rw[i] is not None for rw in rrows)), None)
            th, trows = out[t]
            jj = th.index(c)
            if code is None and ni is not None and len(rh) <= 3:          # bảng tra: id -> tên
                m = {rw[ki]: rw[ni] for rw in rrows}
                for rw in trows:
                    rw[jj] = m.get(rw[jj], rw[jj])
                if base not in th:
                    th[jj] = base
                continue
            if code is None:
                continue
            m = {rw[ki]: rw[code] for rw in rrows}
            extra = [(f"{base}_name", ni)] if ni is not None else []
            extra += [(f"{base}_group", i) for i, x in enumerate(rh) if isinstance(x, str) and "group" in x.lower()]
            extra = [(n, i) for n, i in extra if n not in th]
            by_id = {x[ki]: x for x in rrows}
            for rw in trows:
                row_ref = by_id.get(rw[jj]) if extra else None
                rw.extend(row_ref[i] if row_ref else None for _, i in extra)
                rw[jj] = m.get(rw[jj], rw[jj])
            th.extend(n for n, _ in extra)
            referenced[r] = (base, code, ni)
    for r, (base, code, ni) in referenced.items():
        rh, rrows = out[r]
        ki = rh.index("id")
        rh[code] = f"{base}_id"
        if ni is not None and f"{base}_name" not in rh:
            rh[ni] = f"{base}_name"
        keep = [i for i in range(len(rh)) if i != ki]
        out[r] = ([rh[i] for i in keep], [[rw[i] for i in keep] for rw in rrows])
    if referenced:
        for t, (h, rows) in out.items():
            if t not in referenced and "id" in h and (n := f"{_singular(t)}_id") not in h:
                h[h.index("id")] = n
    for t, (h, rows) in out.items():
        for j, c in enumerate(h):
            if isinstance(c, str) and _UNIX_COL.search(c) and _is_unix([rw[j] for rw in rows]):
                for rw in rows:
                    rw[j] = _unix_to_local(rw[j])
    return out


def read_sqlite(path: str) -> list[RawSheet]:
    # Chép sang /tmp (kèm -wal/-shm nếu có) để đọc an toàn kể cả khi /data mount :ro hoặc path có ký tự đặc biệt (?, #).
    with tempfile.TemporaryDirectory(prefix="dm_sqlite_") as tmpdir:
        tmp_db = os.path.join(tmpdir, "db.sqlite")
        shutil.copy2(path, tmp_db)
        for suffix in ("-wal", "-shm"):
            side = path + suffix
            if os.path.exists(side):
                shutil.copy2(side, tmp_db + suffix)
        con = sqlite3.connect(tmp_db)
        try:
            names = [r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
            tables = {}
            for name in names:
                cur = con.execute(f'SELECT * FROM "{name}"')
                tables[name] = ([d[0] for d in cur.description], [list(r) for r in cur.fetchall()])
            if os.environ.get("DATAMATE_POS_PHANG", "1") == "1":
                tables = _flatten_pos(tables)
            sheets = []
            for name in names:
                header, data = tables[name]
                sheets.append(RawSheet(fix_filename(os.path.basename(path)), name, "sqlite",
                                       _clean_rows([header] + data), header_known=True))
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


def _fold(v) -> str:
    t = unicodedata.normalize("NFD", str(v)).replace("\u0111", "d").replace("\u0110", "d")
    t = "".join(ch for ch in t if unicodedata.category(ch) != "Mn").lower()
    return re.sub(r"\s+", " ", t).strip()


_DAY_ROW = re.compile(r"^ngay\s+(\d{1,2})\s*[/.-]\s*(\d{1,2})(?:\s*[/.-]\s*(\d{2,4}))?$")
_SEQ_NAMES = {"don", "don so", "so don", "stt don", "so thu tu don", "don thu", "so tt don"}
_ID_NAMES = {"ma don", "so hd", "ma hd", "ma hoa don", "so hoa don", "ma phieu", "so phieu", "ma don hang"}
_DM_SEQ = re.compile(r"^(\d{1,2})/(\d{1,2})-(\d{1,4})$")


def _small_ints(vals) -> bool:
    v = [x for x in vals if x is not None]
    ok = [x for x in v if (isinstance(x, (int, float)) and not isinstance(x, bool) and x == int(x) and 0 < x < 1000)
          or (isinstance(x, str) and x.isdigit() and 0 < int(x) < 1000)]
    return len(v) >= 5 and len(ok) >= 0.95 * len(v)


def _dmy(v):
    """ngày trong ô -> (d, m, y) hoặc None."""
    if isinstance(v, (dt.datetime, dt.date)):
        return v.day, v.month, v.year
    if isinstance(v, str) and (m := re.match(r"^(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})", v.strip())):
        y = int(m[3])
        return int(m[1]), int(m[2]), y + 2000 if y < 100 else y
    return None


def _key(d, m, y, n) -> str:
    return f"{d:02d}/{m:02d}/{y}-{int(n)}" if y else f"{d:02d}/{m:02d}-{int(n)}"


def _day_sections(rows: list[list], name: str) -> list[list] | None:
    def one_cell(r):
        cells = [c for c in r if c is not None]
        return _DAY_ROW.match(_fold(cells[0])) if len(cells) == 1 and isinstance(cells[0], str) else None
    idx = {i: m for i, r in enumerate(rows) if (m := one_cell(r))}
    if len(idx) < 3:
        return None
    first = min(idx)
    h = max((i for i in range(first) if sum(c is not None for c in rows[i]) >= 2), default=None)
    if h is None:
        return None
    ym = re.search(r"(20\d\d)", name or "") or re.search(r"(20\d\d)", " ".join(str(c) for r in rows[:h] for c in r if c))
    year = int(ym[1]) if ym else None
    head = list(rows[h])
    seq = next((j for j, c in enumerate(head) if c is not None and _fold(c) in _SEQ_NAMES
                and not any(_fold(x) in _ID_NAMES for x in head if x is not None)
                and _small_ints([r[j] if j < len(r) else None for k, r in enumerate(rows) if k > h and k not in idx])), None)
    out = [[None] + list(r) for r in rows[:h]]
    out.append(["Ngày"] + [("Mã đơn" if j == seq else c) for j, c in enumerate(head)])
    cur = None
    for i in range(h + 1, len(rows)):
        if i in idx:
            m = idx[i]
            y = int(m[3]) if m[3] else year
            y = y + 2000 if y and y < 100 else y
            cur = (int(m[1]), int(m[2]), y)
            continue
        r = list(rows[i])
        if seq is not None and seq < len(r) and r[seq] is not None and cur is not None:
            try:
                r[seq] = _key(*cur, int(float(r[seq])))
            except (TypeError, ValueError):
                pass
        day = None if cur is None else (f"{cur[0]:02d}/{cur[1]:02d}/{cur[2]}" if cur[2] else f"{cur[0]:02d}/{cur[1]:02d}")
        out.append([day] + r)
    return out


def _side_book_keys(rows: list[list]) -> list[list] | None:
    """Sổ phụ ghi đơn theo ngày + số đơn trong ngày (hoặc 'dd/mm-n'): thêm 'Mã đơn' dd/mm/yyyy-n."""
    h = next((i for i, r in enumerate(rows[:10]) if sum(isinstance(c, str) for c in r) >= 3), None)
    if h is None:
        return None
    head = [_fold(c) if c is not None else "" for c in rows[h]]
    if any(c in _ID_NAMES for c in head):
        return None
    dcols = [j for j, c in enumerate(head) if c in ("ngay don", "ngay ban", "ngay mua", "ngay")]
    if not dcols:
        return None
    dj = dcols[0]
    body = rows[h + 1:]
    col = lambda j: [r[j] if j < len(r) else None for r in body]   # noqa: E731
    seq = next((j for j, c in enumerate(head) if c in _SEQ_NAMES and _small_ints(col(j))), None)
    dm = next((j for j, c in enumerate(head) if c in _SEQ_NAMES and len(v := [x for x in col(j) if x is not None]) >= 5
               and sum(isinstance(x, str) and bool(_DM_SEQ.match(x.strip())) for x in v) >= 0.95 * len(v)), None)
    if seq is not None:
        # số đơn TRONG NGÀY: ngày ghi đủ năm, số lặp lại giữa các ngày, mỗi dòng một đơn (cặp ngày + số không trùng).
        # Sổ bán đánh số đơn liên tục ("00001", "00002") thì không phải -> không đổi
        pairs = [(d, r[seq]) for r in body if seq < len(r) and r[seq] is not None and (d := _dmy(r[dj] if dj < len(r) else None))]
        n_seq = sum(1 for r in body if seq < len(r) and r[seq] is not None)
        if not (pairs and len(pairs) >= 0.9 * n_seq and len({n for _, n in pairs}) <= 0.5 * len(pairs)
                and len(set(pairs)) >= 0.95 * len(pairs)):
            seq = None
    if seq is None and dm is None:
        return None
    out = [list(r) for r in rows]
    if seq is not None:
        out[h] = out[h] + ["Mã đơn"]
        for i in range(h + 1, len(out)):
            r = out[i]
            d = _dmy(r[dj]) if dj < len(r) else None
            n = r[seq] if seq < len(r) else None
            r.extend([None] * (len(out[h]) - 1 - len(r)))
            try:        # ô số đơn ghi lệch ("3b", "12*"): dòng đó để trống mã đơn, không làm hỏng cả shop
                r.append(_key(*d, int(float(n))) if d and n is not None else None)
            except (TypeError, ValueError):
                r.append(None)
        return out
    out[h][dm] = "Mã đơn"
    for i in range(h + 1, len(out)):
        r = out[i]
        d = _dmy(r[dj]) if dj < len(r) else None
        if dm < len(r) and isinstance(r[dm], str) and (m := _DM_SEQ.match(r[dm].strip())):
            y = d[2] if d and d[1] == int(m[2]) else (d[2] if d else None)
            r[dm] = _key(int(m[1]), int(m[2]), y, int(m[3]))
    return out


def _so_ngay(sheets: list[RawSheet]) -> list[RawSheet]:
    if os.environ.get("DATAMATE_SO_NGAY", "1") != "1":
        return sheets
    for sh in sheets:
        if sh.kind == "sqlite":
            continue
        new = _day_sections(sh.rows, sh.sheet or sh.file)
        if new is None:
            new = _side_book_keys(sh.rows)
        if new is not None:
            sh.rows = new
    return sheets


def read_file(path: str) -> list[RawSheet]:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".csv":
        return _so_ngay(read_csv(path))
    if ext in (".sqlite", ".db", ".sqlite3"):
        return read_sqlite(path)
    return _so_ngay(read_xlsx(path))


def read_shop(shop_dir: str) -> list[RawSheet]:
    sheets = []
    for path in list_data_files(shop_dir):
        try:
            sheets.extend(read_file(path))
        except Exception as exc:
            print(f"[WARN] Bỏ qua file lỗi {path}: {exc}", file=sys.stderr)
    return sheets
