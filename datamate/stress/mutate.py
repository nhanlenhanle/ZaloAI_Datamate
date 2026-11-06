"""Shop lạ giả lập từ shop train: đổi CÁCH GHI, giữ NỘI DUNG, nên đáp án train vẫn đúng.

Đo lớp data khi gặp nhãn, tên cột, README, quy ước chưa thấy mà không nhìn public. Mỗi phép lấy mẫu từ
các cách ghi rulebook §8 và README thừa nhận: tên gọi khác của cùng một thứ, ô trống ở các dòng sau của nhóm,
trạng thái ghi ở ghi chú, dòng tiêu đề / dòng tổng của file xuất, quy ước nêu trong README.
Nghĩa cột lấy từ DB train đã build (đã kiểm với đáp án).

    python -m datamate.stress.mutate ../train/train "../solve data/stress" --mut nhan_trang_thai --shops biz_101
-> <out>/<phép>/: data/<shop>/ (file + README), questions/answers của các shop đó, rulebook.md, calendar.csv.
Data gốc chỉ đọc.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import random
import re
import shutil
import sqlite3
import unicodedata
from dataclasses import dataclass

import duckdb
from openpyxl import Workbook

from datamate.loader.build import _CHANNEL_NORM, _PAYMENT_NORM, _code_norm
from datamate.loader.header import _make_columns, detect_header
from datamate.loader.parsers import fold, is_walk_in, norm_status, parse_date, parse_number
from datamate.loader.read_files import list_data_files, read_file

MONEY = {"unit_price", "line_amount", "line_discount", "unit_cost", "price", "new_price", "old_price",
         "order_subtotal", "order_discount", "discount", "purchase_total", "order_total", "shipping_fee", "paid",
         "debt", "payment_amount", "money", "expense_amount"}
QTY = {"qty", "qty_base", "qty_returned", "qty_returned_base"}


@dataclass
class Sheet:
    file: str
    sheet: str | None
    kind: str                   # csv | xlsx | sqlite
    rows: list[list]
    h: int | None               # dòng header
    canon: dict[int, str]       # vị trí cột -> tên chuẩn (theo DB train)

    def cols(self, *names) -> list[int]:
        return [j for j, c in self.canon.items() if c in names]

    def data(self) -> range:
        return range(self.h + 1, len(self.rows)) if self.h is not None else range(0)

    def get(self, i: int, j: int):
        r = self.rows[i]
        return r[j] if j < len(r) else None

    def put(self, i: int, j: int, v):
        r = self.rows[i]
        if j >= len(r):
            r.extend([None] * (j + 1 - len(r)))
        r[j] = v


def _norm_col(s) -> str:
    return re.sub(r"\s+", " ", str(s)).strip()


def column_meanings(db_path: str) -> dict[tuple, dict[str, str]]:
    """(file, sheet) -> {tên cột gốc: tên chuẩn} từ _meta_columns và cột _src_file/_src_sheet của DB."""
    con = duckdb.connect(db_path, read_only=True)
    out: dict[tuple, dict[str, str]] = {}
    try:
        for t, in con.execute("SELECT table_name FROM _meta_tables").fetchall():
            cols = con.execute("SELECT original_name, canonical FROM _meta_columns WHERE table_name = ? "
                               "AND canonical IS NOT NULL AND original_name IS NOT NULL", [t]).fetchall()
            try:
                srcs = con.execute(f'SELECT DISTINCT _src_file, _src_sheet FROM "{t}"').fetchall()
            except duckdb.Error:
                continue
            for f, s in srcs:
                m = {_norm_col(o): c for o, c in cols}
                out.setdefault((f, s), {}).update(m)
                out.setdefault((f, None), {}).update(m)
    finally:
        con.close()
    return out


def load_shop(shop_dir: str, db_path: str) -> list[Sheet]:
    meanings = column_meanings(db_path)
    sheets = []
    for path in list_data_files(shop_dir):
        for raw in read_file(path):
            h = 0 if raw.header_known else detect_header(raw.rows)[0]
            canon = {}
            if h is not None:
                names = _make_columns(raw.rows[h], len(raw.rows[h]))
                m = meanings.get((raw.file, raw.sheet)) or meanings.get((raw.file, None)) or {}
                canon = {j: m[c] for j, c in enumerate(names) if c in m}
            sheets.append(Sheet(raw.file, raw.sheet, raw.kind, [list(r) for r in raw.rows], h, canon))
    return sheets


# ---------------------------------------------------------------- ghi file

def _num_text(x: float) -> str:
    """Số -> chữ không nhập nhằng với dấu nghìn: 12.345 (3 số lẻ) ghi 12.3450."""
    if float(x).is_integer():
        return str(int(x))
    s = f"{x:.4f}".rstrip("0")
    return s + "0" if len(s.split(".")[1]) == 3 else s


def _cell_text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        return _num_text(v)
    if isinstance(v, dt.datetime):
        return v.strftime("%d/%m/%Y %H:%M:%S") if (v.hour or v.minute or v.second) else v.strftime("%d/%m/%Y")
    if isinstance(v, dt.date):
        return v.strftime("%d/%m/%Y")
    return str(v)


def write_shop(sheets: list[Sheet], dst: str) -> None:
    os.makedirs(dst, exist_ok=True)
    files: dict[str, list[Sheet]] = {}
    for s in sheets:
        files.setdefault(s.file, []).append(s)
    for name, ss in files.items():
        path = os.path.join(dst, name)
        kind = ss[0].kind
        if kind == "csv":
            with open(path, "w", encoding="utf-8-sig", newline="") as fh:
                csv.writer(fh).writerows([[_cell_text(v) for v in r] for r in ss[0].rows])
        elif kind == "sqlite":
            con = sqlite3.connect(path)
            for s in ss:
                head = [str(c) for c in s.rows[0]]
                con.execute(f'CREATE TABLE "{s.sheet}" ({", ".join(chr(34) + c + chr(34) for c in head)})')
                body = [[(_cell_text(v) if isinstance(v, (dt.date, dt.datetime)) else v) for v in r]
                        + [None] * (len(head) - len(r)) for r in s.rows[1:]]
                con.executemany(f'INSERT INTO "{s.sheet}" VALUES ({", ".join("?" * len(head))})',
                                [r[:len(head)] for r in body])
            con.commit()
            con.close()
        else:
            wb = Workbook(write_only=True)
            for s in ss:
                ws = wb.create_sheet(title=s.sheet or "Sheet1")
                for r in s.rows:
                    ws.append(r)
            wb.save(path)


# ---------------------------------------------------------------- README

_COLS_H = re.compile(r"^##\s*Cột trong\s+`([^`]+)`")
_DOC = re.compile(r"^- \*\*(.+?)\*\*:")


def readme_lines_for(readme: str, file: str) -> list[int]:
    """Số dòng mô tả cột ('- **Cột**: ...') thuộc các mục 'Cột trong `file`'."""
    out, cur = [], None
    for i, line in enumerate(readme.split("\n")):
        if line.startswith("## "):
            m = _COLS_H.match(line)
            cur = m[1] if m else None
        elif cur is not None and (cur == file or fold(cur) == fold(file)) and _DOC.match(line):
            out.append(i)
    return out


def readme_rename(readme: str, file: str, old: str, new: str) -> str:
    lines = readme.split("\n")
    for i in readme_lines_for(readme, file):
        if _DOC.match(lines[i])[1].strip() == old:
            lines[i] = lines[i].replace(f"**{old}**", f"**{new}**", 1)
    text = "\n".join(lines)
    # câu quy ước nhắc tên cột ("**Còn nợ** là ...")
    return text.replace(f"**{old}** ", f"**{new}** ")


def readme_drop_columns(readme: str) -> str:
    """Bỏ hết các mục 'Cột trong `file`' (README không mô tả cột)."""
    out, skip = [], False
    for line in readme.split("\n"):
        if line.startswith("## "):
            skip = bool(_COLS_H.match(line))
        if not skip:
            out.append(line)
    return "\n".join(out)


def readme_add_intro(readme: str, sentence: str) -> str:
    """Thêm câu vào cuối đoạn mở đầu (trước '## File')."""
    i = readme.find("\n## ")
    return readme[:i].rstrip() + " " + sentence + "\n" + readme[i:] if i >= 0 else readme + "\n" + sentence


def readme_add_rule(readme: str, bullet: str) -> str:
    """Thêm một dòng vào mục Quy ước."""
    m = re.search(r"^## Quy ước\s*$", readme, re.M)
    if not m:
        return readme.rstrip() + "\n\n## Quy ước\n" + bullet + "\n"
    return readme[:m.end()] + "\n" + bullet + readme[m.end():]


def readme_replace_in_docs(readme: str, file: str, header: str, old: str, new: str) -> str:
    lines = readme.split("\n")
    for i in readme_lines_for(readme, file):
        if _DOC.match(lines[i])[1].strip() == header:
            lines[i] = re.sub(rf"(?<![\w]){re.escape(old)}(?![\w])", new, lines[i])
    return "\n".join(lines)


# ---------------------------------------------------------------- các phép

STATUS_LABELS = {
    "hoan_thanh": ["Đã chốt", "Hoàn tất", "Đã nhận hàng", "Thành công", "Xong"],
    "huy": ["Không lấy", "Khách bom", "Hủy đơn", "Đã hủy", "Bỏ đơn"],
    "tra_hang": ["Hàng hoàn", "Khách trả lại", "Đổi trả", "Hoàn trả", "Trả hàng"],
    "dang_giao": ["Đã gửi bưu điện", "Đang ship", "Chờ giao", "Đang vận chuyển", "Đang giao"],
}
PAYMENT_LABELS = {
    "tien_mat": ["Tiền tươi", "TM", "Trả tiền mặt", "Cash", "Tiền mặt"],
    "chuyen_khoan": ["Chuyển tiền", "CK", "Banking", "QR ngân hàng", "Chuyển khoản"],
    "the": ["Quẹt thẻ", "Thẻ ATM", "Visa/Master", "Máy POS"],
    "vi": ["Ví MoMo", "ZaloPay", "Ví điện tử", "VNPay"],
    "cod": ["Ship thu tiền", "COD", "Thu hộ"],
    "ghi_no": ["Ký sổ", "Thiếu", "Ghi nợ", "Trả sau"],
}
CHANNEL_LABELS = {
    "tai_quay": ["Mua trực tiếp", "Khách đến mua", "Tại tiệm", "Tại quầy"],
    "dien_thoai": ["Gọi điện", "Đặt qua ĐT", "Hotline", "Điện thoại"],
    "zalo": ["Nhắn Zalo", "Zalo OA", "Zalo"],
    "facebook": ["Fanpage", "Inbox page", "FB", "Facebook"],
    "shopee": ["Sàn Shopee", "Shopee"],
    "grab": ["GrabFood", "ShopeeFood", "Grab"],
    "website": ["Đặt online", "Website", "Web"],
}
WALK_IN_LABELS = ["Khách qua đường", "Khách mua lẻ", "Khách vãng lai", "KL", "Khách không tên"]
HEADER_SYNONYMS = {
    "order_id": ["Số CT", "Số chứng từ", "Mã HĐ", "Invoice No", "Số phiếu bán"],
    "order_date": ["Ngày CT", "Ngày chứng từ", "Ngày lập", "Date"],
    "order_time": ["Giờ lập", "Thời gian tạo", "Created at"],
    "product_name": ["Mặt hàng", "Hàng hóa", "Tên SP", "Item name"],
    "product_id": ["Mã SP", "SKU", "Mã vạch", "Item code"],
    "qty": ["SL", "Số lg", "Lượng", "Qty"],
    "qty_base": ["SL lẻ", "Số lượng quy đổi", "Qty (base)"],
    "unit": ["ĐVT", "Đơn vị", "Unit"],
    "base_unit": ["ĐV nhỏ nhất", "Đơn vị lẻ", "Base unit"],
    "unit_price": ["Giá", "Giá bán lẻ", "Đơn giá bán", "Price"],
    "line_amount": ["Tiền hàng", "Thành tiền (VNĐ)", "Doanh số dòng", "Amount"],
    "line_discount": ["CK dòng", "Giảm giá SP", "Item discount"],
    "customer_name": ["Người mua", "Tên KH", "Khách", "Customer"],
    "customer_id": ["Mã KH", "ID khách", "Customer ID"],
    "status": ["Tình trạng", "TT đơn", "Status"],
    "payment_method": ["HTTT", "PT thanh toán", "Thanh toán bằng", "Payment"],
    "channel": ["Nguồn đơn", "Kênh", "Bán qua", "Source"],
    "order_total": ["Tổng thanh toán", "Khách cần trả", "Tổng HĐ", "Total"],
    "order_subtotal": ["Tổng tiền hàng", "Tiền hàng trước giảm", "Subtotal"],
    "order_discount": ["Giảm giá HĐ", "CK hóa đơn", "Order discount"],
    "paid": ["Khách đã trả", "Đã thu", "Paid"],
    "debt": ["Còn thiếu", "Nợ lại", "Balance due"],
    "staff_name": ["Người bán", "NV bán", "Thu ngân", "Seller"],
    "category": ["Loại hàng", "Danh mục", "Category"],
    "unit_cost": ["Giá nhập TB", "Giá vốn TB", "Cost"],
    "supplier_name": ["Nhà CC", "Tên NCC", "Supplier"],
    "purchase_id": ["Số phiếu nhập", "Mã PN", "PO No"],
    "purchase_date": ["Ngày PN", "Ngày nhập kho", "Receipt date"],
    "payment_amount": ["Số tiền thu", "Tiền thu", "Amount paid"],
    "payment_date": ["Ngày thu", "Thời điểm thu tiền", "Paid at"],
    "stock_qty": ["Tồn", "SL tồn", "On hand"],
    "expiry_date": ["Hạn SD", "Ngày hết hạn", "Exp date"],
    "batch_id": ["Số lô SX", "Lô SX", "Lot"],
    "note": ["Diễn giải", "Ghi chú thêm", "Note"],
    "order_note": ["Ghi chú HĐ", "Ghi chú đơn hàng", "Order note"],
}


def _relabel(sheets, readme, canon_names, norm, labels, rng, info):
    """Mọi cột có tên chuẩn trong canon_names: nhãn mã X -> một nhãn khác của X (chọn một lần cho shop)."""
    pick = {code: rng.choice(opts) for code, opts in labels.items()}
    for s in sheets:
        for j in s.cols(*canon_names):
            seen = {}
            for i in s.data():
                v = s.get(i, j)
                if v is None or not isinstance(v, str):
                    continue
                code = norm(v)
                if code in pick and v != pick[code]:
                    s.put(i, j, pick[code])
                    seen[v] = pick[code]
            for old, new in seen.items():
                readme = readme_replace_in_docs(readme, s.file, _norm_col(s.rows[s.h][j]), old, new)
            info.setdefault("doi_nhan", {}).update(seen)
    return readme


def m_goc(sheets, readme, rng, info):
    return readme


def m_nhan_trang_thai(sheets, readme, rng, info):
    return _relabel(sheets, readme, ("status", "purchase_status"), norm_status, STATUS_LABELS, rng, info)


def m_nhan_thanh_toan(sheets, readme, rng, info):
    readme = _relabel(sheets, readme, ("payment_method",), lambda v: _code_norm(v, _PAYMENT_NORM),
                      PAYMENT_LABELS, rng, info)
    return _relabel(sheets, readme, ("channel",), lambda v: _code_norm(v, _CHANNEL_NORM), CHANNEL_LABELS, rng, info)


def m_khach_le(sheets, readme, rng, info):
    label = rng.choice(WALK_IN_LABELS)
    n = 0
    for s in sheets:
        for j in s.cols("customer_name", "name"):
            for i in s.data():
                v = s.get(i, j)
                if isinstance(v, str) and is_walk_in(v):
                    s.put(i, j, label)
                    n += 1
    if n:
        readme = re.sub(r"[Kk]hách lẻ", label, readme)
    info.update(nhan=label, so_o=n)
    return readme


def _rename_headers(sheets, readme, rng, info):
    pick = {c: rng.choice(v) for c, v in HEADER_SYNONYMS.items()}
    done = {}
    for s in sheets:
        if s.h is None:
            continue
        used = {_norm_col(c) for c in s.rows[s.h] if c is not None}
        for j, c in s.canon.items():
            new = pick.get(c)
            old = _norm_col(s.get(s.h, j))
            if not new or new in used:
                continue
            s.put(s.h, j, new)
            used.add(new)
            readme = readme_rename(readme, s.file, old, new)
            done[old] = new
    info["doi_ten"] = done
    return readme


def m_ten_cot(sheets, readme, rng, info):
    return _rename_headers(sheets, readme, rng, info)


def m_ten_cot_khong_mo_ta(sheets, readme, rng, info):
    return readme_drop_columns(_rename_headers(sheets, readme, rng, info))


_NOTE_TEXT = {"huy": "Khách hủy đơn", "tra_hang": "Khách trả hàng", "dang_giao": "Đang giao"}
# câu quy ước bộ đo chèn vào README (dữ liệu fine-tune phải tránh đúng các câu này)
GHI_CHU_INTRO = ("Sổ không có cột trạng thái: đơn huỷ, đơn trả hàng, đơn đang giao ghi ở cột Ghi chú; ghi chú không "
                 "nhắc trạng thái là đơn hoàn thành.")
TIEN_NGHIN_RULE = ("- **Đơn vị tiền**: mọi cột tiền ghi theo **nghìn đồng**: 45 là 45.000 đồng, 12,5 là 12.500 đồng.")


def m_trang_thai_ghi_chu(sheets, readme, rng, info):
    n = 0
    for s in sheets:
        st = s.cols("status")
        if not st:
            continue
        j = st[0]
        notes = s.cols("order_note", "note")
        head = _norm_col(s.rows[s.h][j])
        lines = readme.split("\n")
        for k in readme_lines_for(readme, s.file):
            if _DOC.match(lines[k])[1].strip() == head:
                lines[k] = None if notes else f"- **Ghi chú**: ghi chú của đơn"
        readme = "\n".join(x for x in lines if x is not None)
        for i in s.data():
            code = norm_status(s.get(i, j))
            text = _NOTE_TEXT.get(code)
            if notes:
                if text:
                    old = s.get(i, notes[0])
                    s.put(i, notes[0], f"{old}. {text}" if old else text)
                n += bool(text)
            else:
                s.put(i, j, text)
                n += bool(text)
        if notes:                                    # bỏ hẳn cột trạng thái
            for r in s.rows[s.h:]:
                if j < len(r):
                    del r[j]
            s.canon = {(k if k < j else k - 1): c for k, c in s.canon.items() if k != j}
        else:
            s.put(s.h, j, "Ghi chú")
            s.canon[j] = "order_note"
    if n:
        readme = readme_add_intro(readme, GHI_CHU_INTRO)
    info["so_dong_ghi_chu"] = n
    return readme


_LINE_LEVEL = {"product_name", "product_id", "qty", "qty_base", "unit", "unit_price", "line_amount", "line_discount",
               "line_no", "batch_id", "expiry_date", "unit_cost", "category", "base_unit", "conv_factor",
               "qty_returned", "qty_returned_base", "is_prescription", "active_ingredient", "imei"}


def m_o_trong_nhom(sheets, readme, rng, info):
    """Bảng dòng hàng: thông tin của đơn chỉ ghi ở dòng đầu đơn, các dòng sau để trống (§8)."""
    n = 0
    for s in sheets:
        oid = s.cols("order_id")
        if not oid or s.h is None:
            continue
        o = oid[0]
        runs, start = [], None
        rows = list(s.data())
        for k, i in enumerate(rows):
            if start is None or s.get(i, o) != s.get(rows[start], o):
                start = k
                runs.append([i])
            else:
                runs[-1].append(i)
        multi = [r for r in runs if len(r) > 1]
        if len(multi) < 0.1 * len(runs):
            continue
        width = max(len(r) for r in s.rows)
        level = []
        for j in range(width):
            if j == o or s.canon.get(j) in _LINE_LEVEL:
                continue
            same = sum(len({s.get(i, j) for i in r}) == 1 for r in multi)
            if same >= 0.99 * len(multi) and any(s.get(r[0], j) is not None for r in multi[:50]):
                level.append(j)
        for r in multi:
            for i in r[1:]:
                for j in level:
                    if s.get(i, j) is not None:
                        s.put(i, j, None)
                        n += 1
        info.setdefault("cot_de_trong", {})[f"{s.file}/{s.sheet}"] = [_norm_col(s.rows[s.h][j]) for j in level]
    info["so_o"] = n
    return readme


def m_tieu_de_dong_tong(sheets, readme, rng, info):
    """File xuất kèm dòng tiêu đề báo cáo phía trên header và dòng 'Tổng cộng' cuối bảng."""
    n = 0
    for s in sheets:
        if s.kind == "sqlite" or s.h is None:
            continue
        stem = os.path.splitext(s.file)[0].replace("_", " ")
        sums = {}
        for j, c in s.canon.items():
            if c in MONEY | QTY:
                vals = [parse_number(s.get(i, j)) for i in s.data()]
                vals = [v for v in vals if isinstance(v, (int, float))]
                if vals:
                    sums[j] = round(sum(vals), 2)
        width = len(s.rows[s.h])
        foot = [None] * width
        foot[0] = "Tổng cộng"
        for j, v in sums.items():
            if j > 0:
                foot[j] = v
        s.rows[s.h:s.h] = [[f"BÁO CÁO {stem.upper()}"], ["Đơn vị tính: đồng"], []]
        s.h += 3
        s.rows.append(foot)
        n += 1
    info["so_sheet"] = n
    return readme


def m_tien_nghin(sheets, readme, rng, info):
    """Mọi cột tiền ghi theo nghìn đồng; README nói rõ."""
    n = 0
    for s in sheets:
        for j in s.cols(*MONEY):
            for i in s.data():
                v = parse_number(s.get(i, j))
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    s.put(i, j, v / 1000 if s.kind != "csv" else _num_text(v / 1000))
                    n += 1
    readme = readme_add_rule(readme, TIEN_NGHIN_RULE)
    info["so_o"] = n
    return readme


_DIGITS = ["không", "một", "hai", "ba", "bốn", "năm", "sáu", "bảy", "tám", "chín"]


def _read3(n: int, full: bool) -> str:
    """0..999 đọc tiếng Việt; full: nằm sau hàng lớn hơn (đọc cả 'không trăm', 'lẻ')."""
    h, t, u = n // 100, (n // 10) % 10, n % 10
    parts = []
    if h or full:
        parts.append(_DIGITS[h] + " trăm")
    if t == 0:
        if u:
            parts.append(("lẻ " if (h or full) else "") + _DIGITS[u])
    elif t == 1:
        parts.append("mười" + ("" if u == 0 else " " + ("lăm" if u == 5 else _DIGITS[u])))
    else:
        parts.append(_DIGITS[t] + " mươi" + ("" if u == 0 else " " + ("mốt" if u == 1 else "lăm" if u == 5
                                                                        else _DIGITS[u])))
    return " ".join(parts)


def so_thanh_chu(x) -> str | None:
    """245000 -> 'hai trăm bốn mươi lăm nghìn'; chỉ số nguyên dương < 1 tỷ, chia hết cho 1000."""
    if not isinstance(x, (int, float)) or x <= 0 or x >= 1e9 or x % 1000:
        return None
    k = int(x) // 1000
    tr, ng = k // 1000, k % 1000
    out = ([_read3(tr, False) + " triệu"] if tr else []) + ([_read3(ng, bool(tr)) + " nghìn"] if ng else [])
    return " ".join(out)


def _odd(kind: str, v, rng: random.Random):
    """Một ô viết kiểu tay, cùng nội dung (bộ đo; dữ liệu fine-tune dùng kiểu khác)."""
    if kind == "date":
        d = parse_date(v)
        return d.strftime("%b %d, %Y") if d is not None and not (d.hour or d.minute) else None
    x = parse_number(v)
    if not isinstance(x, (int, float)) or isinstance(x, bool) or x <= 0 or not float(x).is_integer():
        return None
    x = int(x)
    if kind == "qty":
        return f"x{x}"
    words = so_thanh_chu(x)
    if words and rng.random() < 0.5:
        return words
    return f"{x:,}đ (đã CK)".replace(",", ".")


def m_o_la(sheets, readme, rng, info):
    """Vài ô số / ngày viết kiểu tay (tiền bằng chữ hay kèm chữ, số lượng 'x2', ngày kiểu tiếng Anh); nội dung giữ."""
    n = 0
    salt = rng.random()
    for s in sheets:
        if s.h is None:
            continue
        cols = []
        for j, c in s.canon.items():
            kind, rate = ("money", 0.03) if c in MONEY else ("qty", 0.08) if c == "qty" else \
                ("date", 0.03) if c == "order_date" else (None, 0)
            if kind:
                cols.append((j, kind, rate))
        for i in s.data():
            # chọn theo nội dung dòng: hai dòng trùng (lỗi xuất file, §8) bị đổi giống nhau, vẫn là dòng trùng
            key = f"{salt}|{s.rows[i]!r}"
            for j, kind, rate in cols:
                r = random.Random(f"{key}|{j}")
                if r.random() < rate and (new := _odd(kind, s.get(i, j), r)):
                    s.put(i, j, new)
                    n += 1
    info["so_o"] = n
    return readme


def m_xao_cot(sheets, readme, rng, info):
    """Đổi thứ tự cột trong từng bảng."""
    for s in sheets:
        if s.h is None:
            continue
        width = max(len(r) for r in s.rows[s.h:])
        order = list(range(width))
        rng.shuffle(order)
        for i in range(s.h, len(s.rows)):
            r = s.rows[i] + [None] * (width - len(s.rows[i]))
            s.rows[i] = [r[j] for j in order]
        s.canon = {order.index(j): c for j, c in s.canon.items()}
    return readme


_EXTRA_COLS = [("Mã chi nhánh", lambda r: "CN01"), ("Điểm tích lũy", lambda r: r.randint(0, 500)),
               ("Người nhập liệu", lambda r: r.choice(["admin", "ketoan"])), ("Số lần in", lambda r: r.randint(0, 3))]


def m_cot_thua(sheets, readme, rng, info):
    """Thêm hai cột không liên quan vào mọi bảng, có số và chữ; README không mô tả."""
    return _add_extra(sheets, readme, rng, info, rng.sample(_EXTRA_COLS, 2))


def m_cot_lech(sheets, readme, rng, info):
    """Như cot_thua nhưng mỗi sheet thêm cột khác nhau: các phần của một sổ không còn cùng bộ cột."""
    return _add_extra(sheets, readme, rng, info, None)


def _add_extra(sheets, readme, rng, info, fixed):
    n = 0
    for s in sheets:
        if s.h is None or not s.canon:
            continue
        width = max(len(r) for r in s.rows[s.h:])
        extra = fixed or rng.sample(_EXTRA_COLS, 2)
        salt = rng.random()
        for i in range(s.h, len(s.rows)):
            s.rows[i] += [None] * (width - len(s.rows[i]))
            # giá trị theo nội dung dòng: hai dòng trùng (lỗi xuất file, §8) vẫn là hai dòng trùng
            r = random.Random(f"{salt}|{s.rows[i]!r}")
            s.rows[i] += [name if i == s.h else make(r) for name, make in extra]
        n += 1
    info["so_bang"] = n
    return readme


def m_ngay_khac(sheets, readme, rng, info):
    """Ngày ghi theo một định dạng khác, thứ tự ngày / tháng vẫn rõ."""
    fmt = rng.choice(["%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y"])
    n = 0
    for s in sheets:
        for j in s.cols("order_date", "purchase_date", "payment_date", "expiry_date"):
            for i in s.data():
                d = parse_date(s.get(i, j))
                if d is not None and not (d.hour or d.minute):
                    s.put(i, j, d.strftime(fmt))
                    n += 1
    info.update(dinh_dang=fmt, so_o=n)
    return readme


def _no_marks(text: str) -> str:
    text = unicodedata.normalize("NFD", text).replace("đ", "d").replace("Đ", "D")
    return "".join(c for c in text if not unicodedata.combining(c))


def m_cot_khong_dau(sheets, readme, rng, info):
    """Tên cột gõ không dấu, README đổi theo."""
    for s in sheets:
        if s.h is None:
            continue
        used = {_norm_col(c) for c in s.rows[s.h] if c is not None}
        for j in range(len(s.rows[s.h])):
            old = s.get(s.h, j)
            if not isinstance(old, str) or (new := _no_marks(old)) == old or new in used:
                continue
            s.put(s.h, j, new)
            used.add(new)
            readme = readme_rename(readme, s.file, _norm_col(old), new)
    return readme


def m_tach_thang(sheets, readme, rng, info):
    """Bảng có ngày bán trong Excel: mỗi tháng một sheet, cùng tên cột."""
    n = 0
    for s in list(sheets):
        cols = s.cols("order_date")
        if s.kind != "xlsx" or s.h is None or not cols:
            continue
        groups: dict[str, list] = {}
        key = None
        for i in s.data():
            d = parse_date(s.get(i, cols[0]))
            key = d.strftime("%Y-%m") if d is not None else key
            groups.setdefault(key or "khac", []).append(s.rows[i])
        if len(groups) < 2:
            continue
        at = sheets.index(s)
        sheets[at:at + 1] = [Sheet(s.file, f"T{k}", s.kind, s.rows[:s.h + 1] + rows, s.h, dict(s.canon))
                             for k, rows in sorted(groups.items())]
        n += 1
    info["so_bang"] = n
    return readme


def m_tong_hop(sheets, readme, rng, info):
    """Nhiều cách ghi lạ cùng lúc trên một shop, như một shop thật khác hẳn train."""
    steps = [m_xao_cot, m_cot_thua, m_ngay_khac, m_nhan_trang_thai, m_nhan_thanh_toan, m_khach_le, m_ten_cot, m_cot_khong_dau]
    if rng.random() < 0.25:
        steps.insert(3, m_trang_thai_ghi_chu)
    if rng.random() < 0.25:
        steps.append(m_tien_nghin)
    steps += [m_o_trong_nhom, m_tach_thang, m_tieu_de_dong_tong]
    info["cac_phep"] = [f.__name__[2:] for f in steps]
    for f in steps:
        readme = f(sheets, readme, rng, info)
    return readme


MUTATIONS = {
    "xao_cot": m_xao_cot,
    "cot_thua": m_cot_thua,
    "cot_lech": m_cot_lech,
    "ngay_khac": m_ngay_khac,
    "cot_khong_dau": m_cot_khong_dau,
    "tach_thang": m_tach_thang,
    "tong_hop": m_tong_hop,
    "goc": m_goc,
    "nhan_trang_thai": m_nhan_trang_thai,
    "nhan_thanh_toan": m_nhan_thanh_toan,
    "khach_le": m_khach_le,
    "ten_cot": m_ten_cot,
    "ten_cot_khong_mo_ta": m_ten_cot_khong_mo_ta,
    "trang_thai_ghi_chu": m_trang_thai_ghi_chu,
    "o_trong_nhom": m_o_trong_nhom,
    "tieu_de_dong_tong": m_tieu_de_dong_tong,
    "tien_nghin": m_tien_nghin,
    "o_la": m_o_la,
}


def make_split(train_root: str, train_out: str, out_root: str, mut: str, shops: list[str], seed: int = 0) -> str:
    """Tạo split giả lập <out_root>/<mut>/ và trả đường dẫn."""
    dst = os.path.join(out_root, mut)
    if os.path.exists(dst):
        shutil.rmtree(dst)
    os.makedirs(os.path.join(dst, "data"))
    for f in ("rulebook.md", "calendar.csv"):
        if os.path.exists(os.path.join(train_root, f)):
            shutil.copy(os.path.join(train_root, f), dst)
    for f in ("questions.jsonl", "answers.jsonl"):
        keep = set()
        with open(os.path.join(train_root, "questions.jsonl"), encoding="utf-8") as fh:
            keep = {q["id"] for q in map(json.loads, fh) if q["business_id"] in shops}
        with open(os.path.join(train_root, f), encoding="utf-8") as fh, \
                open(os.path.join(dst, f), "w", encoding="utf-8") as out:
            out.writelines(line for line in fh if json.loads(line)["id"] in keep)
    report = {}
    for shop in shops:
        rng = random.Random(f"{seed}-{mut}-{shop}")
        src = os.path.join(train_root, "data", shop)
        sheets = load_shop(src, os.path.join(train_out, shop, f"{shop}.duckdb"))
        with open(os.path.join(src, "README.md"), encoding="utf-8") as fh:
            readme = fh.read()
        info = {"cot_co_nghia": sum(len(s.canon) for s in sheets)}
        readme = MUTATIONS[mut](sheets, readme, rng, info)
        write_shop(sheets, os.path.join(dst, "data", shop))
        with open(os.path.join(dst, "data", shop, "README.md"), "w", encoding="utf-8") as fh:
            fh.write(readme)
        report[shop] = info
    with open(os.path.join(dst, "mutation.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1, default=str)
    return dst


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("train_root", help="vd ../train/train (có data/, questions.jsonl, answers.jsonl)")
    ap.add_argument("out_root")
    ap.add_argument("--train-out", default="../solve data/train", help="DB train đã build (nghĩa cột)")
    ap.add_argument("--mut", required=True, choices=list(MUTATIONS))
    ap.add_argument("--shops", nargs="+", required=True)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    print(make_split(a.train_root, a.train_out, a.out_root, a.mut, a.shops, a.seed))


if __name__ == "__main__":
    main()
