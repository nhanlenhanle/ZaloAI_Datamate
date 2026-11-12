"""Vòng tự sửa lớp dữ liệu: khám DB vừa dựng -> LLM đề xuất cách đọc lại sổ -> dựng lại -> khám lại.

Chỉ nhận đề xuất khi điểm cờ giảm và không sinh loại cờ mới (LLM đoán sai thì bị loại, không làm hỏng DB).
Bật bằng DATAMATE_TU_SUA=1 cùng --llm. Ghi <shop>/_tu_sua.json (cách sửa đã nhận) và _tu_sua.txt (nhật ký).

Phép khám (dữ liệu tự đối chiếu, không cần đáp án):
  K1 không nhận ra sổ bán                       K2 một dòng chiếm >= 30% tiền cả sheet (dòng tổng lọt?)
  K3 tổng tiền dòng / tổng đơn lệch > 25%        K4 cột gán số thứ tự dòng lặp nhiều, bảng không có mã đơn
  K5 SL x giá khớp thành tiền < 50% dòng         K6 README nói huỷ / trả mà bảng bán không có trạng thái
  K7 có sổ thu / sổ nợ mà không tính được nợ     K8 bảng lớn có ngày + tiền mà vai trò danh sách
  K10 trạng thái đơn: >= 5% dòng có chữ trạng thái không nhận ra
"""
from __future__ import annotations

import csv
import glob
import json
import os
import re
import shutil

import duckdb

from .parsers import fold

TRONG_SO = {"K1": 3, "K2": 1, "K3": 2, "K4": 2, "K5": 1, "K6": 2, "K7": 2, "K8": 1, "K10": 1, "K11": 3, "K12": 2, "K13": 2, "K14": 1, "K15": 2, "K16": 1}
TEN_CHUAN = {
    "order_id": "mã đơn / hoá đơn / bill / phiếu bán (các dòng cùng mã là một đơn)",
    "order_date": "ngày bán", "order_time": "giờ / thời điểm bán",
    "line_amount": "thành tiền của dòng hàng", "order_total": "tổng tiền khách phải trả cả đơn",
    "line_discount": "giảm giá của dòng", "order_discount": "giảm giá / voucher của cả đơn",
    "qty": "số lượng", "unit_price": "đơn giá", "product_name": "tên hàng", "product_id": "mã hàng",
    "customer_name": "tên khách", "customer_id": "mã khách", "status": "trạng thái đơn (xong / huỷ / trả...)",
    "order_note": "ghi chú của đơn (có thể ghi huỷ / trả)", "payment_method": "hình thức thanh toán (TM, CK, nợ...)",
    "paid": "tiền khách đã trả / đưa trước lúc mua", "shipping_fee": "phí giao",
    "payment_id": "mã phiếu thu", "payment_date": "ngày khách trả tiền / ngày thu nợ",
    "payment_amount": "số tiền khách trả lần đó", "debt": "số tiền còn nợ",
    "line_no": "số thứ tự dòng trong một đơn", "purchase_id": "mã phiếu NHẬP hàng từ nhà cung cấp",
    "supplier_name": "nhà cung cấp", "staff_name": "nhân viên", "note": "ghi chú chung",
}
VAI_TRO = ["sales_lines", "orders", "payments", "debts", "customers", "products", "purchase_lines", "purchases",
           "expenses", "stock", "other"]


def _cols(c, t):
    return {r[0] for r in c.execute(f'DESCRIBE "{t}"').fetchall()}


def kham(db: str, shop_dir: str) -> list[tuple[str, str, str]]:
    """[(mã cờ, bảng, mô tả)]."""
    import datamate.tests.verify_answers as v
    from datamate.query.facts import sales_sql
    d = os.path.dirname(db)
    roles = {r["table_name"]: r for r in csv.DictReader(open(os.path.join(d, "_build.csv"), encoding="utf-8-sig"))}
    p = os.path.join(shop_dir, "README.md")
    readme = fold(open(p, encoding="utf-8-sig").read()) if os.path.exists(p) else ""
    c = duckdb.connect(db, read_only=True)
    co = []
    try:
        sales = [t for t, r in roles.items() if r["role"] in ("sales_lines", "orders")]
        if not sales_sql(c):
            co.append(("K1", "", "không nhận ra sổ bán nào (không tính được doanh thu)"))
        for t in sales:
            cs = _cols(c, t)
            n = c.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
            if n < 20:
                continue
            if "line_amount" in cs and "_src_sheet" in cs:
                r = c.execute(f'''SELECT _src_sheet, m, s FROM (SELECT _src_sheet, MAX(TRY_CAST(line_amount AS DOUBLE)) m,
                    SUM(TRY_CAST(line_amount AS DOUBLE)) s, COUNT(*) k FROM "{t}" GROUP BY 1)
                    WHERE k >= 20 AND s > 0 AND m >= 0.3 * s''').fetchall()
                if r:
                    co.append(("K2", t, f"{len(r)} sheet có một dòng chiếm >= 30% tiền cả sheet (dòng tổng / cộng lọt vào?)"))
            if {"order_id", "line_amount", "order_total"} <= cs:
                a, b = c.execute(f'''SELECT SUM(s), SUM(t) FROM (SELECT order_id, SUM(TRY_CAST(line_amount AS DOUBLE)) s,
                    ANY_VALUE(TRY_CAST(order_total AS DOUBLE)) t FROM "{t}" WHERE order_id IS NOT NULL GROUP BY 1)''').fetchone()
                if a and b and not 0.8 <= a / b <= 1.25:
                    co.append(("K3", t, f"tổng tiền các dòng / tổng tiền đơn = {a / b:.2f} (phải gần 1)"))
            if "line_no" in cs and "order_id" not in cs:
                lap = c.execute(f'SELECT COUNT(*) - COUNT(DISTINCT CAST(line_no AS VARCHAR) || COALESCE(CAST(_src_sheet AS VARCHAR), \'\')) '
                                f'FROM "{t}" WHERE line_no IS NOT NULL').fetchone()[0]
                if lap > 0.1 * n:
                    co.append(("K4", t, f"cột gán số thứ tự dòng (line_no) lặp {lap}/{n} dòng, bảng không có mã đơn: có thể nó là mã đơn"))
            if {"qty", "unit_price", "line_amount"} <= cs:
                r = c.execute(f'''SELECT AVG(CASE WHEN ABS(TRY_CAST(qty AS DOUBLE) * TRY_CAST(unit_price AS DOUBLE)
                    - TRY_CAST(line_amount AS DOUBLE)) <= GREATEST(1, 0.02 * ABS(TRY_CAST(line_amount AS DOUBLE))) THEN 1.0 ELSE 0.0 END)
                    FROM "{t}" WHERE line_amount IS NOT NULL AND qty IS NOT NULL AND unit_price IS NOT NULL''').fetchone()[0]
                if r is not None and r < 0.5:
                    co.append(("K5", t, f"số lượng x đơn giá khớp thành tiền chỉ {r:.0%} dòng"))
            src = next((x for x in ("status", "order_note") if x in cs), None)
            if src and "status_norm" in cs:
                r = c.execute(f'''SELECT COUNT(*) FILTER (WHERE status_norm IS NULL AND "{src}" IS NOT NULL), COUNT(*) FROM "{t}"''').fetchone()
                if r[1] and r[0] >= 0.05 * r[1] and src == "status":
                    co.append(("K10", t, f"{r[0]}/{r[1]} dòng có trạng thái không nhận ra"))
        lines = [t for t, r in roles.items() if r["role"] == "sales_lines"]
        if len(lines) > 1:
            co.append(("K11", lines[1], f"sổ bán bị tách {len(lines)} bảng ({', '.join(lines)}), chỉ bảng đầu được dùng: "
                                        "nếu là các phần (năm / quý / tháng) của một sổ thì cột phải map giống nhau để gộp"))
        if re.search(r"\bhuy\b|tra lai|tra hang|khach bom", readme) and sales and \
                not any("status_norm" in _cols(c, u) for u in sales):
            co.append(("K6", sales[0], "README nói có đơn huỷ / trả nhưng bảng bán không có cột trạng thái"))
        if any(r["role"] in ("payments", "debts") for r in roles.values()) and v._debt_base(c) is None:
            co.append(("K7", "", "có sổ thu tiền / sổ nợ nhưng không tính được nợ (sổ thu cần mã đơn + ngày trả + số tiền trả)"))
        for t, r in roles.items():
            if r["role"] in ("customers", "other", "products"):
                cs = _cols(c, t)
                n = c.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
                if n >= 100 and cs & {"order_date", "payment_date", "purchase_date"} and \
                        cs & {"order_total", "line_amount", "payment_amount", "unit_price", "debt", "paid"}:
                    co.append(("K8", t, f"{n} dòng có ngày + tiền nhưng bị coi là danh sách ('{r['role']}')"))
        co += _kham_bat_bien(c, roles, sales)
    finally:
        c.close()
    return co


def _kham_bat_bien(c, roles, sales) -> list[tuple[str, str, str]]:
    """Tính chất chung của sổ bán (không theo chữ cụ thể của shop nào):
    K12 các dòng cùng mã đơn phải cùng ngày bán (bỏ dòng âm: dòng trả hàng ghi ngày trả)
    K13 sổ bán không được trống cả tháng giữa tháng đầu và tháng cuối (dấu hiệu sổ bị tách / đọc sai ngày)
    K14 ngày khách trả tiền không trước ngày mua
    K15 trạng thái đơn: đơn xong phải là phần lớn
    K16 dòng bán có ngày sau ngày cuối dữ liệu README"""
    co = []
    data_end = None
    try:
        data_end = c.execute("SELECT CAST(data_end AS DATE) FROM _meta_shop").fetchone()[0]
    except Exception:
        pass
    for t in sales:
        cs = _cols(c, t)
        n = c.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
        if n < 50 or "order_date" not in cs:
            continue
        pos = "AND TRY_CAST(line_amount AS DOUBLE) >= 0" if "line_amount" in cs else ""
        if "order_id" in cs:
            r = c.execute(f'''SELECT COUNT(*) FILTER (WHERE k > 1), COUNT(*) FROM (SELECT order_id, COUNT(DISTINCT
                CAST(order_date AS DATE)) k FROM "{t}" WHERE order_id IS NOT NULL AND order_date IS NOT NULL {pos} GROUP BY 1)''').fetchone()
            if r[1] >= 50 and r[0] > 0.1 * r[1]:
                co.append(("K12", t, f"{r[0]}/{r[1]} mã đơn có dòng thuộc nhiều ngày khác nhau (mã đơn có thể sai cột, "
                                     "hoặc mã lặp lại theo ngày / theo sheet)"))
        m = c.execute(f'''SELECT MIN(d), MAX(d), COUNT(DISTINCT strftime(d, '%Y-%m')) FROM
            (SELECT CAST(order_date AS DATE) d FROM "{t}" WHERE order_date IS NOT NULL)''').fetchone()
        if m[0] and m[1]:
            span = (m[1].year - m[0].year) * 12 + m[1].month - m[0].month + 1
            if span >= 6 and m[2] < span:
                co.append(("K13", t, f"sổ bán có {m[2]}/{span} tháng có dòng, trống {span - m[2]} tháng ở giữa "
                                     f"({m[0]} -> {m[1]}): phần sổ bị bỏ / ngày đọc sai?"))
            if data_end:
                x = c.execute(f'SELECT COUNT(*) FROM "{t}" WHERE CAST(order_date AS DATE) > ?', [data_end]).fetchone()[0]
                if x > 0.01 * n:
                    co.append(("K16", t, f"{x}/{n} dòng có ngày sau ngày cuối dữ liệu {data_end} (ngày / tháng đọc nhầm?)"))
        if "status_norm" in cs:
            r = c.execute(f'''SELECT COUNT(*) FILTER (WHERE status_norm = 'hoan_thanh'), COUNT(*) FILTER (WHERE status_norm IS NOT NULL)
                FROM "{t}"''').fetchone()
            if r[1] >= 50 and r[0] < 0.5 * r[1]:
                co.append(("K15", t, f"chỉ {r[0]}/{r[1]} dòng có trạng thái 'xong': trạng thái có thể bị hiểu sai"))
    for p, r in roles.items():
        if r["role"] != "payments":
            continue
        pc = _cols(c, p)
        if not {"order_id", "payment_date"} <= pc:
            continue
        for t in sales:
            if not {"order_id", "order_date"} <= _cols(c, t):
                continue
            x = c.execute(f'''SELECT COUNT(*) FILTER (WHERE CAST(p.payment_date AS DATE) < o.d), COUNT(*) FROM "{p}" p JOIN
                (SELECT CAST(order_id AS VARCHAR) k, MIN(CAST(order_date AS DATE)) d FROM "{t}" GROUP BY 1) o
                ON o.k = CAST(p.order_id AS VARCHAR)''').fetchone()
            if x[1] >= 30 and x[0] > 0.1 * x[1]:
                co.append(("K14", p, f"{x[0]}/{x[1]} lần trả tiền có ngày TRƯỚC ngày mua (ngày trả / mã đơn đọc sai?)"))
            break
    return co


def diem(co) -> float:
    return sum(TRONG_SO.get(x[0], 1) for x in co)


def _mo_ta(out_dir: str, shop_dir: str, co) -> str:
    """Prompt: README, các bảng (cột gốc -> tên chuẩn, giá trị mẫu), cờ, chi tiết cho từng loại cờ."""
    db = glob.glob(os.path.join(out_dir, "*.duckdb"))[0]
    maps = list(csv.DictReader(open(os.path.join(out_dir, "_mapping.csv"), encoding="utf-8-sig")))
    build = list(csv.DictReader(open(os.path.join(out_dir, "_build.csv"), encoding="utf-8-sig")))
    p = os.path.join(shop_dir, "README.md")
    readme = open(p, encoding="utf-8-sig").read()[:3500] if os.path.exists(p) else "(không có README)"
    mau = {}
    for f in glob.glob(os.path.join(out_dir, "samples", "*.csv")):
        try:
            with open(f, encoding="utf-8-sig") as fh:
                rows = list(csv.reader(fh))
            mau[os.path.basename(f)[:-4]] = rows
        except Exception:
            pass
    out = ["README:", readme, "", "CÁC BẢNG (tên bảng gốc | cột gốc -> tên chuẩn hiện tại | 3 giá trị mẫu):"]
    by_t = {}
    for m in maps:
        by_t.setdefault(m["table"], []).append(m)
    for t, ms in by_t.items():
        rows = next((r for k, r in mau.items() if fold(k).replace(" ", "_") == fold(t).replace(" ", "_")
                     or fold(k) == fold(t)), None)
        hdr = rows[0] if rows else []
        out.append(f"- bảng `{t}`:")
        for m in ms:
            vs = []
            if rows and m["column"] in hdr:
                j = hdr.index(m["column"])
                vs = [r[j] for r in rows[1:6] if j < len(r) and r[j]][:3]
            out.append(f"    `{m['column']}` -> {m['canonical'] or '(không map)'} | {vs}")
    out.append("")
    out.append("VAI TRÒ HIỆN TẠI (nhãn bảng: vai trò, số dòng): " +
               "; ".join(f"`{b['label']}`: {b['role']}, {b.get('rows_in')}" for b in build))
    out.append("")
    out.append("LỖI PHÁT HIỆN KHI TỰ KIỂM:")
    out += [f"- {x[0]} {x[1]}: {x[2]}" for x in co]
    c = duckdb.connect(db, read_only=True)
    try:
        for code, t, _ in co:
            if code == "K2" and t:
                r = c.execute(f'SELECT * FROM "{t}" ORDER BY TRY_CAST(line_amount AS DOUBLE) DESC NULLS LAST LIMIT 2').df()
                out.append(f"  dòng tiền lớn nhất của `{t}`: " + r.astype(str).to_dict("records").__repr__()[:900])
            if code in ("K6", "K10") and t:
                cs = _cols(c, t)
                for col in [x for x in ("status", "order_note", "note") if x in cs] + \
                           [x for x in cs if fold(x).startswith(("ghi chu", "trang thai", "tinh trang"))]:
                    r = c.execute(f'SELECT "{col}", COUNT(*) FROM "{t}" GROUP BY 1 ORDER BY 2 DESC LIMIT 15').fetchall()
                    out.append(f"  giá trị cột `{col}` của `{t}`: {r}")
    finally:
        c.close()
    return "\n".join(out)


HE_THONG = """Bạn kiểm tra cách một chương trình đọc sổ sách Excel của cửa hàng nhỏ. Chương trình đã đọc sổ và tự kiểm thấy lỗi.
Dựa vào README và giá trị mẫu, đề xuất cách đọc lại để hết lỗi. Chỉ dùng tên bảng, tên cột, giá trị có trong mô tả.
Tên chuẩn được dùng:
""" + "\n".join(f"- {k}: {v}" for k, v in TEN_CHUAN.items()) + """
Vai trò bảng được dùng: """ + ", ".join(VAI_TRO) + """
Gợi ý: sổ thu nợ cần order_id (mã đơn được trả), payment_date, payment_amount; dòng tổng / cộng cuối sheet thì bỏ theo nhãn ở ô chữ;
cột ghi "huỷ / bom / khách trả" là trạng thái (status hoặc order_note); các dòng cùng một số thứ tự đơn là order_id.
Chỉ trả về một JSON:
{"cot": {"<bảng gốc>": {"<cột gốc>": "<tên chuẩn hoặc null>"}}, "vai_tro": {"<nhãn bảng>": "<vai trò>"},
 "bo_dong": ["<nhãn ô chữ của dòng cần bỏ>"], "trang_thai": {"<giá trị trạng thái>": "hoan_thanh|huy|tra_hang|dang_giao"},
 "ly_do": "<một câu>"}
Không có gì cần sửa ở mục nào thì để trống mục đó. Không giải thích ngoài JSON."""


def _json(text: str) -> dict:
    i = text.find("{")
    while i >= 0:
        try:
            out, _ = json.JSONDecoder().raw_decode(text, i)
            if isinstance(out, dict):
                return out
        except ValueError:
            pass
        i = text.find("{", i + 1)
    return {}


def _hop(a: dict, b: dict) -> dict:
    out = json.loads(json.dumps(a))
    for k in ("cot",):
        for t, d in (b.get(k) or {}).items():
            out.setdefault(k, {}).setdefault(t, {}).update(d or {})
    for k in ("vai_tro", "trang_thai"):
        out.setdefault(k, {}).update(b.get(k) or {})
    out["bo_dong"] = sorted(set(out.get("bo_dong") or []) | set(b.get("bo_dong") or []))
    return out


def _sach(de: dict) -> dict:
    """Bỏ phần đề xuất không hợp lệ (tên chuẩn / vai trò / mã trạng thái lạ)."""
    ok = {"cot": {}, "vai_tro": {}, "bo_dong": [], "trang_thai": {}}
    for t, d in (de.get("cot") or {}).items():
        if isinstance(d, dict):
            dd = {str(c): v for c, v in d.items() if v is None or v in TEN_CHUAN}
            if dd:
                ok["cot"][str(t)] = dd
    ok["vai_tro"] = {str(t): v for t, v in (de.get("vai_tro") or {}).items() if v in VAI_TRO}
    ok["bo_dong"] = [str(x)[:60] for x in (de.get("bo_dong") or []) if isinstance(x, str) and 1 <= len(x.strip()) <= 60]
    ok["trang_thai"] = {str(k)[:60]: v for k, v in (de.get("trang_thai") or {}).items()
                        if v in ("hoan_thanh", "huy", "tra_hang", "dang_giao")}
    return ok


def _nguon(out_dir: str) -> dict[str, list[str]]:
    """bảng trong DB -> tên bảng gốc (các phần đã gộp), theo _build.csv."""
    out = {}
    for r in csv.DictReader(open(os.path.join(out_dir, "_build.csv"), encoding="utf-8-sig")):
        try:
            out[r["table_name"]] = list(json.loads(r["sources"].replace("'", '"')))
        except Exception:
            out[r["table_name"]] = [r.get("label") or r["table_name"]]
    return out


def _sales_first(out_dir: str) -> str | None:
    for r in csv.DictReader(open(os.path.join(out_dir, "_build.csv"), encoding="utf-8-sig")):
        if r["role"] == "sales_lines":
            return r["table_name"]
    return None


def tat_dinh(out_dir: str, co) -> dict:
    """Sửa không cần LLM cho dấu hiệu rõ:
    K11 các phần của sổ bán map lệch -> cột gốc cùng tên nhận cùng tên chuẩn (lấy tên chuẩn có ở phần khác);
    K4  cột gán line_no lặp, không có mã đơn -> cột đó là order_id;
    K2  dòng tiền >= 30% cả sheet -> bỏ dòng có cùng ô chữ (nhãn dòng tổng) nếu ô chữ đó chỉ có ở các dòng như vậy."""
    maps = list(csv.DictReader(open(os.path.join(out_dir, "_mapping.csv"), encoding="utf-8-sig")))
    nguon = _nguon(out_dir)
    sua = {"cot": {}, "bo_dong": []}
    k11 = [x[1] for x in co if x[0] == "K11"]
    if k11:
        parts = [n for tb in [_sales_first(out_dir)] + k11 for n in nguon.get(tb, [])]
        by_col = {}
        for m in maps:
            if m["table"] in parts:
                by_col.setdefault(m["column"], {})[m["table"]] = m["canonical"] or None
        for col, d in by_col.items():
            names = {v for v in d.values() if v}
            if len(names) == 1 and None in d.values():
                v = names.pop()
                for tb, cur in d.items():
                    if cur is None:
                        sua["cot"].setdefault(tb, {})[col] = v
    for code, t, _ in co:
        if code == "K4" and t:
            for tb in nguon.get(t, []):
                for m in maps:
                    if m["table"] == tb and m["canonical"] == "line_no":
                        sua["cot"].setdefault(tb, {})[m["column"]] = "order_id"
        if code == "K2" and t:
            db = glob.glob(os.path.join(out_dir, "*.duckdb"))[0]
            c = duckdb.connect(db, read_only=True)
            try:
                cs = [r[0] for r in c.execute(f'DESCRIBE "{t}"').fetchall()]
                big = c.execute(f'SELECT t.* FROM "{t}" t JOIN (SELECT _src_sheet s, SUM(TRY_CAST(line_amount AS DOUBLE)) tot '
                                f'FROM "{t}" GROUP BY 1) g ON g.s = t._src_sheet '
                                f'WHERE TRY_CAST(t.line_amount AS DOUBLE) >= 0.3 * g.tot').df()
                for col in cs:
                    if col.startswith(("_", "is_")) or col.endswith(("__raw", "_norm", "_key")) or col in (
                            "line_type", "qty_base_src") or col not in big or big[col].dtype != object:
                        continue
                    for val in {str(x) for x in big[col].dropna()}:
                        # nhãn chỉ có ở dòng tổng: mọi dòng mang giá trị này đều là dòng tiền lớn bất thường
                        n = c.execute(f'SELECT COUNT(*) FROM "{t}" WHERE CAST("{col}" AS VARCHAR) = ?', [val]).fetchone()[0]
                        n_big = int((big[col].astype(str) == val).sum())
                        if n == n_big and 1 <= len(val.strip()) <= 40:
                            sua["bo_dong"].append(val)
            finally:
                c.close()
    sua["bo_dong"] = sorted(set(sua["bo_dong"]))
    return {k: v for k, v in sua.items() if v}


def bang_chung(out_dir: str) -> list[str]:
    """Bằng chứng giá trị cho LLM: cột chữ có giá trị trùng mã đơn của bảng khác; bảng gán mã phiếu nhập mà không có
    nhà cung cấp."""
    db = glob.glob(os.path.join(out_dir, "*.duckdb"))[0]
    nguon = _nguon(out_dir)
    out = []
    c = duckdb.connect(db, read_only=True)
    try:
        tabs = [r[0] for r in c.execute("SELECT table_name FROM information_schema.tables").fetchall()
                if not r[0].startswith("_")]
        ids = {}
        for t in tabs:
            if "order_id" in _cols(c, t):
                ids[t] = {r[0] for r in c.execute(f'SELECT DISTINCT CAST(order_id AS VARCHAR) FROM "{t}" '
                                                  f'WHERE order_id IS NOT NULL').fetchall()}
        for t in tabs:
            cs = _cols(c, t)
            typ = dict(c.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_name = ?",
                                 [t]).fetchall())
            for col in cs:
                if col.startswith("_") or col.endswith("__raw") or col == "order_id" or typ.get(col) != "VARCHAR":
                    continue
                vs = [r[0] for r in c.execute(f'SELECT DISTINCT CAST("{col}" AS VARCHAR) FROM "{t}" '
                                              f'WHERE "{col}" IS NOT NULL LIMIT 400').fetchall()]
                if len(vs) < 10:
                    continue
                for t2, s2 in ids.items():
                    if t2 == t or not s2:
                        continue
                    hit = sum(v.strip() in s2 for v in vs) / len(vs)
                    if hit >= 0.5:
                        out.append(f"- giá trị cột `{col}` (bảng gốc {nguon.get(t, [t])}) trùng {hit:.0%} mã đơn của bảng "
                                   f"{nguon.get(t2, [t2])}: cột này là mã đơn được tham chiếu -> order_id")
            if "purchase_id" in cs and not cs & {"supplier_name", "supplier_id", "purchase_date"}:
                out.append(f"- bảng gốc {nguon.get(t, [t])} có cột gán purchase_id (mã phiếu NHẬP) nhưng không có nhà cung cấp"
                           " / ngày nhập" + (", lại có hình thức thanh toán của khách: đây là giao dịch BÁN, mã đó là order_id"
                                             if "payment_method" in cs else ""))
    finally:
        c.close()
    return out


def vong(run, out_dir: str, shop_dir: str, so_vong: int = 2) -> dict:
    """run(sua, out) dựng shop vào thư mục out với cách sửa `sua`. Trả cách sửa đã nhận ({} nếu không).
    Bước 0: sửa tất định (không LLM); rồi tối đa so_vong lượt LLM. Nhận khi điểm cờ giảm và (không cờ mới, hoặc điểm
    giảm >= 2)."""
    from .llm import chat
    db = glob.glob(os.path.join(out_dir, "*.duckdb"))
    if not db:
        return {}
    co = kham(db[0], shop_dir)
    log = [f"khám lần đầu: điểm {diem(co)} {[x[0] for x in co]}"]
    nhan: dict = {}

    def thu_sua(thu, ten):
        nonlocal nhan, co
        tmp = out_dir.rstrip("/\\") + "__thu"
        shutil.rmtree(tmp, ignore_errors=True)
        try:
            run(thu, tmp)
            co2 = kham(glob.glob(os.path.join(tmp, "*.duckdb"))[0], shop_dir)
        except Exception as e:
            log.append(f"   {ten}: dựng lại lỗi {type(e).__name__}: {str(e)[:150]}")
            shutil.rmtree(tmp, ignore_errors=True)
            return
        moi = {x[0] for x in co2} - {x[0] for x in co}
        giam = diem(co) - diem(co2)
        log.append(f"   {ten}: khám lại điểm {diem(co)} -> {diem(co2)} {[x[0] for x in co2]}, cờ mới {sorted(moi)}")
        if giam > 0 and (not moi or giam >= 2):
            shutil.rmtree(out_dir, ignore_errors=True)
            shutil.move(tmp, out_dir)
            nhan, co = thu, co2
            log.append("   NHẬN")
        else:
            shutil.rmtree(tmp, ignore_errors=True)
            log.append("   bỏ")

    if co:
        try:
            td = tat_dinh(out_dir, co)
        except Exception as e:
            td = {}
            log.append(f"tất định lỗi {type(e).__name__}: {str(e)[:150]}")
        log.append(f"tất định: {json.dumps(td, ensure_ascii=False)[:500]}")
        if td:
            thu_sua(_hop(nhan, td), "tất định")
    for k in range(so_vong):
        if not co:
            break
        prompt = _mo_ta(out_dir, shop_dir, co)
        try:
            bc = bang_chung(out_dir)
        except Exception:
            bc = []
        if bc:
            prompt += "\n\nBẰNG CHỨNG TỪ GIÁ TRỊ (đã kiểm trên dữ liệu):\n" + "\n".join(bc)
        try:
            de = _sach(_json(chat(HE_THONG, prompt, max_tokens=900, timeout=600)))
        except Exception as e:        # LLM lỗi: giữ DB như cũ
            log.append(f"vòng {k + 1}: LLM lỗi {type(e).__name__}")
            break
        thu = _hop(nhan, de)
        log.append(f"vòng {k + 1}: bằng chứng {len(bc)} dòng; đề xuất {json.dumps(de, ensure_ascii=False)[:600]}")
        if thu == nhan or not any(thu.get(x) for x in ("cot", "vai_tro", "bo_dong", "trang_thai")):
            log.append("   không có gì mới")
            break
        thu_sua(thu, f"vòng {k + 1}")
    with open(os.path.join(out_dir, "_tu_sua.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(log))
    with open(os.path.join(out_dir, "_tu_sua.json"), "w", encoding="utf-8") as f:
        json.dump(nhan, f, ensure_ascii=False, indent=1)
    return nhan
