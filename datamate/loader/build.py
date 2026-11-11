"""Bước 4: bảng đã parse + mapping -> một file DuckDB mỗi shop, kèm bảng meta.

Làm sạch theo rulebook §8 (cách ghi trong file), không lọc nghiệp vụ:
  - bảng chia nhiều file (theo tháng / năm / phần) cùng bộ cột   -> gộp một bảng      merge_split
  - ô trống ở các dòng sau của cùng một đơn = giống dòng đầu     -> fill_order_groups
  - hai dòng của CÙNG MỘT ĐƠN giống nhau mọi ô = lỗi xuất file   -> drop_dup_lines (chỉ bảng có mã đơn)
  - mỗi đơn đúng một trạng thái                                  -> status_norm theo đơn
và §10: đơn vị không có dòng quy đổi là đơn vị cơ bản, hệ số 1   -> qty_base khi file không có.
Đơn huỷ / trả, kỳ thời gian, phí phục vụ... vẫn nằm nguyên; chỉ thêm cột để phía query lọc.
"""
from __future__ import annotations

import json
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

import duckdb
import pandas as pd

from . import labels
from .conventions import drop_contradicted
from .mapping import TIME_ONLY
from .shopmeta import infer_industry, tet_periods
from .parsers import (STATUS_CANCEL, STATUS_DONE, STATUS_RETURN, STATUS_SHIPPING, fold, is_walk_in,
                      norm_status, parse_number)


@dataclass
class Built:
    name: str                  # tên bảng trong DuckDB (ASCII)
    label: str                 # tên gốc (sau khi gộp)
    role: str
    df: pd.DataFrame
    columns: list[dict]        # meta từng cột: column, original, canonical, map_source, kind, description, note
    sources: list[str]         # các bảng gốc đã gộp vào
    stats: dict = field(default_factory=dict)


# ---------------------------------------------------------------- đổi tên, gộp

NEAR_COLUMNS = 0.7          # tỉ lệ cột chung để coi hai bảng cùng họ là các phần của một sổ

def rename_columns(df: pd.DataFrame, maps, kinds: dict[str, str]) -> tuple[pd.DataFrame, list[dict]]:
    """Cột đã map -> tên chuẩn, cột chưa map giữ tên gốc; '<cột>__raw' đổi theo."""
    canon = {m.canonical for m in maps if m.canonical}
    ren, meta = {}, []
    for m in maps:
        new = m.canonical or m.column
        if not m.canonical and m.column in canon:
            new = f"{m.column}__goc"        # tên gốc trùng tên chuẩn của cột khác (hiếm)
        ren[m.column] = new
        if f"{m.column}__raw" in df.columns:
            ren[f"{m.column}__raw"] = f"{new}__raw"
        meta.append({"column": new, "original": m.column, "canonical": m.canonical, "map_source": m.source,
                     "kind": kinds.get(m.column), "description": m.description, "note": m.note or None})
    return df.rename(columns=ren), meta


def _data_cols(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if not c.startswith("_src") and not c.endswith("__raw")]


def _merged_label(names: list[str]) -> str:
    """'BanHang_T1_2025', 'BanHang_T12_2025'... -> 'BanHang'; 'SoBanHang_1', 'SoBanHang_2026' -> 'SoBanHang'."""
    if len(names) == 1:
        return names[0]
    prefix = os.path.commonprefix(names)
    label = re.sub(r"([_\s-]+(T|Thang|thang)?\d*)+$", "", prefix)
    return label or names[0]


def _merge_kind(a: str | None, b: str | None) -> str | None:
    if a == b or b in (None, "empty"):
        return a
    if a in (None, "empty"):
        return b
    return "text"


def _family(label: str) -> str:
    """'SoBan_1', 'SoBan_2026', 'SoBan__T07-2025' -> 'soban': cùng họ là các phần của một sổ."""
    s = fold(label).split("__")[0]
    return re.sub(r"([_\s.-]+(t|thang)?\d+)+$", "", s)


def _near_set(a: frozenset, b: frozenset) -> bool:
    """Hai phần của một sổ có thể lệch vài cột phụ (cột thêm giữa chừng, LLM nhận cột phụ ở một phần)."""
    return len(a & b) >= 3 and len(a & b) / len(a | b) >= NEAR_COLUMNS


def _line_discount_data(dfs: list[pd.DataFrame]) -> bool:
    """Giảm theo dòng: >= 20 dòng có giảm, tỉ lệ giảm / (qty x unit_price) gom vào <= 3 mức chiếm >= 80%."""
    parts = [df[["line_discount", "qty", "unit_price"]] for df in dfs
             if {"line_discount", "qty", "unit_price"} <= set(df.columns)]
    if not parts:
        return False
    x = pd.concat(parts).apply(pd.to_numeric, errors="coerce")
    x = x[(x["line_discount"] > 0) & (x["qty"] * x["unit_price"] > 0)]
    if len(x) < 20:
        return False
    r = (x["line_discount"] / (x["qty"] * x["unit_price"])).round(3)
    return r.value_counts().head(3).sum() >= 0.8 * len(x)


def _align_parts(g: list[Built]) -> None:
    """Cột chuẩn chỉ một số phần có và chỉ do LLM đoán: không đủ chắc để gọi là cột chuẩn của cả sổ, trả về tên gốc.
    Trước đó: phần khác có cùng tên cột gốc mà chưa map (và chưa có cột chuẩn đó) thì nhận cùng tên chuẩn: cùng một sổ,
    cùng tên cột là cùng nghĩa (LLM có thể đoán khác nhau giữa các phần, vd GiamThe dòng / đơn ở hai file năm).
    Nhãn LLM sai được cả hai chiều (biz_605 "Bớt" cả bill bị gán giảm dòng) -> chỉ lan khi dữ liệu xác nhận:
    hiện chỉ line_discount, khi tỉ lệ giảm / (SL x giá) trên mọi phần gom vào <= 3 mức (giảm theo dòng, vd thẻ 3% / 5%)."""
    for b in g:
        for c in b.columns:
            col, orig = c["column"], c.get("original")
            if c.get("map_source") != "llm" or not c.get("canonical") or not orig or col not in b.df:
                continue
            if c["canonical"] != "line_discount" or not _line_discount_data(
                    [x.df.rename(columns={orig: col}) for x in g]):
                continue
            for x in g:
                if x is b or col in x.df or orig not in x.df:
                    continue
                xc = next((y for y in x.columns if y["column"] == orig), None)
                if xc is None or xc.get("canonical"):
                    continue
                ren = {orig: col}
                if f"{orig}__raw" in x.df:
                    ren[f"{orig}__raw"] = f"{col}__raw"
                x.df = x.df.rename(columns=ren)
                xc.update(column=col, canonical=c["canonical"], map_source="llm",
                          note=((xc.get("note") or "") + " | theo phần khác của sổ").strip(" |"))
    for b in g:
        for c in b.columns:
            col, orig = c["column"], c.get("original")
            if c.get("map_source") == "llm" and c.get("canonical") and orig and col in b.df \
                    and orig not in b.df and not all(col in x.df for x in g):
                ren = {col: orig}
                if f"{col}__raw" in b.df:
                    ren[f"{col}__raw"] = f"{orig}__raw"
                b.df = b.df.rename(columns=ren)
                c.update(column=orig, canonical=None, map_source=None)


def merge_split(items: list[Built]) -> tuple[list[Built], list[str]]:
    """Gộp các bảng có cùng bộ cột (sau đổi tên), vd sổ bán chia theo tháng / năm / phần.
    Cùng họ tên mà bộ cột gần giống cũng là một sổ: tách ra thì mọi số tính trên sổ chỉ còn một phần, sai âm thầm."""
    groups: dict[frozenset, list[Built]] = defaultdict(list)
    order = []
    for b in items:
        key = frozenset(_data_cols(b.df))
        if len(key) < 3:
            key = frozenset([f"__single__{b.label}"])
        if key not in groups:
            home = next((k for k in order if _near_set(k, key)
                         and _family(groups[k][0].label) == _family(b.label)), None)
            if home is not None:
                groups[home].append(b)
                continue
            order.append(key)
        groups[key].append(b)
    out, warnings = [], []
    for key in order:
        g = groups[key]
        if len(g) == 1:
            out.append(g[0])
            continue
        _align_parts(g)
        first = g[0]
        kinds = {c["column"]: c["kind"] for c in first.columns}
        for b in g[1:]:
            for c in b.columns:
                k = _merge_kind(kinds.get(c["column"]), c["kind"])
                if k != kinds.get(c["column"]) and kinds.get(c["column"]) not in (None, "empty"):
                    warnings.append(f"gộp {first.label}: cột {c['column']} {kinds[c['column']]}/{c['kind']} -> {k}")
                kinds[c["column"]] = k
        df = pd.concat([b.df for b in g], ignore_index=True)
        cols, seen = [], set()
        for b in g:                 # các phần có thể lệch cột: meta gồm mọi cột, phần không có cột đó để trống
            for c in b.columns:
                if c["column"] not in seen:
                    seen.add(c["column"])
                    cols.append(dict(c, kind=kinds[c["column"]]))
        label = _merged_label([b.label for b in g])
        out.append(Built("", label, "", df, cols, [s for b in g for s in b.sources]))
    return out, warnings


def sql_name(label: str, used: set[str]) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", fold(label)).strip("_") or "bang"
    if s[0].isdigit():
        s = "t_" + s
    name, i = s, 2
    while name in used:
        name, i = f"{s}_{i}", i + 1
    used.add(name)
    return name


# ---------------------------------------------------------------- vai trò bảng

ROLE_DESC = {
    "sales_lines": "dòng hàng bán (mỗi dòng một mặt hàng của một đơn; có thể kèm thông tin đơn lặp ở mọi dòng)",
    "orders": "đơn bán, mỗi dòng một đơn",
    "order_info": "thông tin thêm của đơn (bàn, khu vực...)",
    "sales_batches": "dòng bán theo lô (đơn - lô - số lượng đơn vị cơ bản)",
    "payments": "các lần thu tiền",
    "purchases": "phiếu nhập, mỗi dòng một phiếu",
    "purchase_lines": "dòng hàng nhập",
    "batches": "lô hàng nhập (số lô, hạn dùng)",
    "products": "danh mục hàng",
    "drug_info": "thông tin thuốc (hoạt chất, kê đơn)",
    "customers": "danh sách khách",
    "suppliers": "nhà cung cấp",
    "staff": "nhân viên",
    "expenses": "sổ chi phí (các khoản chi vận hành; lãi ròng = lãi gộp - chi phí, rulebook §5)",
    "stock": "tồn kho",
    "stock_moves": "thẻ kho (tồn sau mỗi phát sinh)",
    "unit_conversions": "đơn vị quy đổi",
    "price_history": "lịch sử / bảng giá",
    "deliveries": "giao hàng theo đợt",
    "debt_terms": "hạn nợ của đơn",
    "debts": "sổ nợ",
    "returns": "phiếu khách trả hàng (mã đơn, mặt hàng, số lượng trả, ngày trả)",
    "other": "bảng khác (giữ nguyên)",
}

_QTY = {"qty", "qty_base", "line_amount", "unit_price"}


def table_role(cols: set[str]) -> str:
    item = bool(cols & {"product_name", "product_id"})
    if "expense_amount" in cols and not item:
        return "expenses"
    if "conv_factor" in cols:
        return "unit_conversions"
    if cols & {"new_price", "old_price"} or ("price_from" in cols and not cols & {"order_id", "purchase_id"}):
        return "price_history"
    if "stock_after" in cols:
        return "stock_moves"
    if cols & {"delivery_round", "driver", "plate"}:
        return "deliveries"
    # phiếu khách trả: số lượng trả / ngày trả theo đơn hoặc mặt hàng, không có giá bán / thành tiền của dòng bán
    if cols & {"qty_returned", "qty_returned_base", "return_date"} and cols & {"order_id", "product_id", "product_name"}             and not cols & {"qty", "qty_base", "unit_price", "line_amount", "order_total", "purchase_id", "batch_id"}:
        return "returns"
    if "credit_days" in cols and not item:
        return "debt_terms"
    # mã thanh toán ghi trên sổ đơn (có mã + ngày đơn, không có tiền thanh toán) thì vẫn là sổ đơn
    order_book = {"order_id", "order_date"} <= cols and "payment_amount" not in cols
    if "payment_id" in cols and not order_book or ({"payment_amount", "order_id"} <= cols and not item):
        return "payments"
    # bảng nhập: có mã / ngày phiếu nhập, hoặc tên NCC đi cùng mặt hàng. Chỉ có mã + tên NCC là danh sách NCC
    if (cols & {"purchase_id", "purchase_date"} or "supplier_name" in cols and item) and "order_id" not in cols:
        if "batch_id" in cols and "expiry_date" in cols and not {"qty", "unit_price"} <= cols:
            return "batches"
        return "purchase_lines" if item and cols & _QTY else "purchases"
    if "order_id" in cols and "batch_id" in cols and "product_name" not in cols:
        return "sales_batches"
    # sổ dịch vụ không có tên hàng: dòng có tiền theo dòng (thành tiền, hoặc số lượng + đơn giá) cũng là dòng bán
    priced = "line_amount" in cols or {"qty", "unit_price"} <= cols or {"qty_base", "unit_price"} <= cols
    if (item or priced) and cols & _QTY and cols & {"order_id", "order_date", "order_time", "status", "customer_name"}:
        return "sales_lines"
    if "order_id" in cols and cols & {"order_total", "order_subtotal", "paid", "order_date", "status"}:
        return "orders"
    if "order_id" in cols and cols & {"table_no", "area", "guests"}:
        return "order_info"
    if "order_date" in cols and cols & {"order_total", "paid"} and not item and "debt" not in cols:
        return "orders"          # sổ phiếu dịch vụ / sổ đơn không ghi mã: mỗi dòng một phiếu
    if "staff_name" in cols and not item and cols & {"commission_pct", "start_date", "staff_id", "phone"}:
        return "staff"
    if "stock_qty" in cols:
        return "stock"
    if cols & {"active_ingredient", "is_prescription"}:
        return "drug_info"
    if "debt" in cols and not item:
        return "debts"
    if item:
        return "products"
    if cols & {"customer_id", "customer_name"}:
        return "customers"
    if cols & {"supplier_id", "supplier_name"}:
        return "suppliers"
    if "staff_id" in cols and not cols & {"order_date", "order_time"}:
        return "staff"
    return "other"


# ---------------------------------------------------------------- §8: ô trống trong nhóm dòng, dòng trùng

ORDER_LEVEL = ["order_id", "order_date", "order_time", "customer_id", "customer_name", "customer_group", "phone",
               "address", "status", "order_note", "channel", "payment_method", "staff_id", "shift_id", "promo_id",
               "table_no", "area", "guests", "order_subtotal", "order_discount", "order_total", "shipping_fee",
               "paid", "debt"]
PURCHASE_LEVEL = ["purchase_id", "purchase_date", "supplier_id", "supplier_name", "purchase_status", "purchase_total"]


def _group_ids(df: pd.DataFrame, key: str) -> pd.Series:
    """Nhóm dòng liền nhau của cùng một đơn. Dòng trống mã thuộc nhóm ngay trên nó,
    trừ khi dòng đó ghi ngày khác ngày của nhóm (sổ tay: đơn mới không ghi số)."""
    k = df[key]
    start = k.notna() & (k.ffill().shift() != k)
    # không điền tràn qua ranh giới file / sheet (sau khi gộp các file tháng thành một bảng)
    parts = [df[c].astype(str) for c in ("_src_file", "_src_sheet") if c in df.columns]
    if parts:
        part = parts[0] if len(parts) == 1 else parts[0] + "|" + parts[1]
        start |= part != part.shift()
    for dcol in ("order_date", "purchase_date"):
        if dcol in df.columns and dcol != key:
            d = df[dcol]
            start |= k.isna() & d.notna() & (d.ffill().shift() != d)
            break
    return start.cumsum()


def fill_order_groups(df: pd.DataFrame, key: str, cols: list[str]) -> dict[str, int]:
    """Điền ô trống của cột cấp đơn từ dòng trên trong cùng nhóm dòng. Trả số ô đã điền theo cột."""
    grp = _group_ids(df, key)
    filled = {}
    for c in [key] + [c for c in cols if c != key]:
        for col in (c, f"{c}__raw"):
            if col not in df.columns or not df[col].isna().any():
                continue
            new = df[col].groupby(grp).ffill()
            n = int((df[col].isna() & new.notna()).sum())
            if n:
                df[col] = new
                filled[col] = n
    return filled


DAY_FILL = os.environ.get("DATAMATE_DAY_FILL", "1") != "0"


def fill_day_dates(df: pd.DataFrame, dcol: str) -> int:
    """Sổ tay ghi ngày một lần cho cả ngày, các đơn sau cùng ngày để trống ngày (§8 điền xuống).
    Sau khi đã điền trong đơn, nếu vẫn còn nhiều dòng trống ngày và các ngày đã ghi đi lên theo thứ tự dòng
    trong từng file / sheet, thì dòng trống ngày lấy ngày của dòng có ngày gần nhất phía trên (cùng file / sheet)."""
    if not DAY_FILL or dcol not in df.columns:
        return 0
    d = df[dcol]
    if d.isna().mean() < 0.2 or d.notna().sum() < 10:
        return 0
    parts = [df[c].astype(str) for c in ("_src_file", "_src_sheet") if c in df.columns]
    part = (parts[0] + "|" + parts[1]) if len(parts) == 2 else parts[0] if parts else pd.Series("", index=df.index)
    nn = d.notna()
    prev = d[nn].groupby(part[nn]).shift()
    step = prev.notna()
    if step.sum() < 5 or (d[nn][step] < prev[step]).mean() > 0.02:
        return 0
    n = 0
    for col in (dcol, f"{dcol}__raw"):
        if col in df.columns:
            new = df[col].groupby(part).ffill()
            if col == dcol:
                n = int((df[col].isna() & new.notna()).sum())
            df[col] = new
    return n


# cột cấp dòng: ô trống là trống thật, không lấy theo dòng đầu đơn
_LINE_COLS = {"product_name", "product_id", "qty", "qty_base", "unit", "unit_price", "line_amount", "line_discount",
              "line_no", "batch_id", "expiry_date", "unit_cost", "conv_factor", "qty_returned", "qty_returned_base",
              "imei", "base_unit", "is_prescription", "active_ingredient", "category"}


def drop_dup_lines(df: pd.DataFrame, key: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Bỏ dòng giống hệt một dòng trước đó của cùng đơn (so mọi ô dữ liệu, kể cả giá trị gốc).
    Khi so, ô trống ở dòng sau của đơn coi như giống dòng trên (§8: kể cả cột luật chưa biết tên chuẩn, vd mã
    cửa hàng chỉ ghi dòng đầu) — chỉ để so, không ghi đè; cột cấp dòng không điền."""
    cols = [c for c in df.columns if not c.startswith("_src")]
    cmp = df[cols]
    fill = [c for c in cols if c != key and c.removesuffix("__raw") not in _LINE_COLS and cmp[c].isna().any()]
    if fill and df[key].notna().any():
        cmp = cmp.copy()
        cmp[fill] = cmp[fill].groupby(df[key]).ffill()
    dup = df[key].notna() & cmp.duplicated(subset=cols, keep="first")
    return df[~dup].reset_index(drop=True), df[dup]


# ---------------------------------------------------------------- cột suy ra

_STATUS_RANK = {STATUS_CANCEL: 0, STATUS_RETURN: 1, STATUS_SHIPPING: 2, STATUS_DONE: 3}
_RANK_STATUS = {v: k for k, v in _STATUS_RANK.items()}


# cột ngày không phải lúc trạng thái đổi
_NOT_EVENT_TIME = {"expiry_date", "due_date", "start_date", "price_from", "created_date"}


def _item_status_rank(df: pd.DataFrame, rank: pd.Series) -> tuple[pd.Series, int, pd.Series | None]:
    """Hạng trạng thái của từng mặt hàng trong đơn (xem add_status_norm). Trả (hạng theo dòng,
    số đơn mà lấy-lần-muộn-nhất cho kết quả khác thứ tự ưu tiên, cờ dòng muộn nhất hoặc None).

    Cờ: nhóm (đơn, mặt hàng) ghi KHÁC trạng thái ở KHÁC thời điểm là lịch sử của một dòng hàng -> chỉ dòng
    muộn nhất là dòng thật (không thì cộng tiền / số lượng hai lần). Cùng trạng thái mà nhiều dòng (gọi thêm
    cùng món) là các lần bán thật: giữ cả."""
    item = next((c for c in ("product_id", "product_name") if c in df.columns), None)
    keys = [df["order_id"]] + ([df[item].astype(str)] if item else [])
    prio = rank.groupby(keys, dropna=False).transform("min")
    mixed = rank.groupby(keys, dropna=False).transform("nunique") > 1
    if not mixed.any():
        return prio, 0, None
    # cột thời điểm: cột ngày giờ thay đổi giữa các dòng của cùng mặt hàng (ngày đặt điền cho cả đơn thì không)
    best, best_n = None, 0
    for c in df.columns:
        if c in _NOT_EVENT_TIME or c.endswith("__raw") or not pd.api.types.is_datetime64_any_dtype(df[c]):
            continue
        n = int((df[c][mixed].groupby([k[mixed] for k in keys], dropna=False).nunique() > 1).sum())
        if n > best_n:
            best, best_n = c, n
    if best is None:
        return prio, 0, None
    t = df[best]
    latest = rank.where(t.eq(t.groupby(keys, dropna=False).transform("max"))).groupby(
        keys, dropna=False).transform("min")
    out = prio.where((prio <= _STATUS_RANK[STATUS_RETURN]) | latest.isna(), latest)
    changed = (out.groupby(df["order_id"]).min() != prio.groupby(df["order_id"]).min())
    history = mixed & (t.groupby(keys, dropna=False).transform("nunique") > 1)
    # dòng muộn nhất của nhóm lịch sử; nhiều dòng cùng giờ muộn nhất thì lấy dòng ghi sau cùng
    pos = pd.Series(range(len(df)), index=df.index)
    last = pos.where(t.eq(t.groupby(keys, dropna=False).transform("max"))).groupby(
        keys, dropna=False).transform("max")
    flag = (~history) | pos.eq(last)
    return out, int(changed.sum()), flag


def llm_codes(values: pd.Series, codes: pd.Series, kind: str) -> pd.Series:
    """Dòng luật chưa ra mã (codes trống) -> mã LLM xếp theo nhãn khác nhau (loader/labels.py); không chắc thì trống.
    note_status: 'khong_nhac' (ghi chú không nói trạng thái) cũng để trống."""
    todo = codes.isna() & values.notna()
    if not todo.any():
        return pd.Series(None, index=values.index, dtype=object)
    counts = values[todo].astype(str).value_counts().to_dict()
    got = labels.classify(kind, counts, column=str(values.name), total=int(values.notna().sum()))
    got = {k: v for k, v in got.items() if v != "khong_nhac"}
    return values.map(lambda v: got.get(str(v)) if v is not None else None).where(todo)


def add_status_norm(df: pd.DataFrame) -> dict:
    """status_norm ∈ {hoan_thanh, huy, tra_hang, dang_giao}, một giá trị cho cả đơn.

    Nguồn: cột trạng thái; không có thì ghi chú của đơn (sổ ghi huỷ / trả ở ghi chú; trống = hoàn thành).
    Các dòng của một đơn ghi khác nhau:
      - cùng một mặt hàng ghi nhiều lần (lịch sử: đang giao rồi hoàn thành) -> trạng thái của lần muộn nhất
        theo cột thời điểm thay đổi trong nhóm; huỷ / trả là trạng thái kết thúc nên luôn thắng
      - các mặt hàng khác nhau -> huỷ > trả > đang giao > hoàn thành (trả một phần là đơn trả hàng,
        rulebook §1; còn mặt hàng chưa giao thì đơn còn đang giao)
    Rulebook: trạng thái huỷ / trả lấy theo đơn, không theo ngày hỏi, nên chỉ cần trạng thái cuối.
    Trạng thái gốc vẫn giữ nguyên ở cột status / order_note.
    """
    if "status" in df.columns:
        src, s = "status", df["status"].map(norm_status)
    elif "order_note" in df.columns:
        src, s = "order_note", df["order_note"].map(norm_status)
    else:
        return {}
    s = s.fillna(llm_codes(df[src], s, "status" if src == "status" else "note_status"))
    info = {"status_source": src,
            "status_unknown": int((s.isna() & df[src].notna()).sum()),
            "status_unknown_values": " | ".join(map(str, df.loc[s.isna() & df[src].notna(), src].unique()[:5]))}
    if "order_id" in df.columns:
        rank = s.map(_STATUS_RANK)
        n_mixed = rank.groupby(df["order_id"]).nunique()
        info["orders_mixed_status"] = int((n_mixed > 1).sum())
        item_rank, n_time, latest = _item_status_rank(df, rank)
        per_order = item_rank.groupby(df["order_id"]).transform("min")
        info["orders_status_by_time"] = n_time
        if latest is not None and not latest.all():
            df["is_latest_row"] = latest.astype("boolean")
            info["history_rows"] = int((~latest).sum())
        s = per_order.map(_RANK_STATUS).where(df["order_id"].notna(), s)
    if src == "order_note":
        s = s.fillna(STATUS_DONE)
    df["status_norm"] = s
    return info


def reconcile_status(built: list["Built"]) -> dict:
    """Trạng thái cuối của đơn trên cả shop (rulebook §8: mỗi đơn đúng một trạng thái).

    - Bảng đơn và bảng dòng cùng có status_norm mà ghi khác nhau -> huỷ > trả > đang giao > hoàn thành.
    - Trả hàng ghi ở chỗ khác (bảng lô / dòng có số lượng trả > 0, phiếu trả có mã đơn) mà đơn chưa
      ghi trả -> đơn trả hàng (§1: trả một phần cũng là đơn trả), trừ đơn đã huỷ.
    Chỉ xét bảng bán (không xét bảng nhập: trả hàng cho nhà cung cấp là chuyện khác).
    """
    sales = [b for b in built if b.role in ("sales_lines", "orders", "order_info", "sales_batches", "returns", "other")
             and "order_id" in b.df.columns]
    # đơn đã có cột trạng thái thật (rulebook: chỉ sổ KHÔNG có cột trạng thái mới đọc trạng thái ở ghi chú):
    # trạng thái đọc từ ghi chú của bảng khác không được đè lên
    by_col = set()
    for b in sales:
        if b.stats.get("status_source") == "status" and "status_norm" in b.df.columns:
            by_col |= set(b.df.loc[b.df["status_norm"].notna(), "order_id"].astype(str))
    rank = {}
    for b in sales:
        if "status_norm" in b.df.columns:
            r = b.df["status_norm"].map(_STATUS_RANK).groupby(b.df["order_id"].astype(str)).min().dropna()
            note = b.stats.get("status_source") == "order_note"
            for k, v in r.items():
                if note and k in by_col:
                    continue
                rank[k] = min(rank.get(k, 9), v)
    returned: dict[str, str] = {}
    for b in sales:
        df, hit = b.df, None
        for c in ("qty_returned", "qty_returned_base"):
            if c in df.columns:
                q = pd.to_numeric(df[c], errors="coerce").fillna(0) > 0
                hit = q if hit is None else hit | q
        if "return_id" in df.columns:
            hit = df["return_id"].notna() if hit is None else hit | df["return_id"].notna()
        if hit is not None:
            for k in df.loc[hit & df["order_id"].notna(), "order_id"].astype(str).unique():
                returned.setdefault(k, b.name)
    final = dict(rank)
    by_return = 0
    for k in returned:
        if k in final and final[k] > _STATUS_RANK[STATUS_RETURN]:
            final[k] = _STATUS_RANK[STATUS_RETURN]
            by_return += 1
    changed = 0
    for b in sales:
        if "status_norm" not in b.df.columns:
            continue
        key = b.df["order_id"].astype(str).where(b.df["order_id"].notna())
        new = key.map(final).map(_RANK_STATUS)
        new = new.where(new.notna(), b.df["status_norm"])
        diff = new.ne(b.df["status_norm"]) & new.notna()
        changed += int(b.df.loc[diff, "order_id"].nunique())
        b.df["status_norm"] = new
    return {"orders_returned_elsewhere": by_return, "orders_status_reconciled": changed,
            "return_sources": sorted(set(returned.values()))}


def text_key(v) -> str | None:
    """Khoá so tên 'chỉ khác cách viết' (hoa thường, dấu, khoảng trắng, dấu câu)."""
    if v is None or (isinstance(v, float) and v != v):
        return None
    k = re.sub(r"[^\w]+", " ", fold(v)).strip()
    return k or None


def phone_same_customer(rulebook) -> bool:
    """Rulebook nói tên có / không kèm số điện thoại là cùng một khách (bộ đề tự sinh). Rulebook train chỉ nói "khác số là
    hai khách" nên giữ khoá trên tên đầy đủ."""
    if rulebook is None or not len(rulebook):
        return False
    text = fold(" ".join(str(t) for t in rulebook["text"]))
    return bool(re.search(r"co\s*(/|hoac)\s*khong kem so dien thoai[^|]*cung mot khach", text))


def add_customer_cols(df: pd.DataFrame, walk_labels: list[str] | None = None, phone_same: bool = False):
    """is_walk_in: đơn khách lẻ / vãng lai. Có cột mã khách: không ghi mã = khách lẻ (rulebook §3).
    Không có mã: tên trống hoặc ghi 'khách lẻ' (hay nhãn README nêu: walk_labels). customer_key: khoá tên khách,
    trống với khách lẻ; phone_same (phone_same_customer): khoá trên tên đã bỏ số điện thoại ghi kèm."""
    if "customer_id" in df.columns:
        walk = df["customer_id"].isna()
    elif "customer_name" in df.columns:
        names = df["customer_name"]
        own = {fold(x) for x in walk_labels or []}
        walk = names.isna() | names.map(lambda v: is_walk_in(v) or (v is not None and fold(str(v)) in own))
        # nhãn khách lẻ riêng của shop ("Khách qua đường"...): LLM xét các tên xuất hiện nhiều nhất
        extra = labels.walk_in_markers(names[~walk].astype(str).value_counts().to_dict(), total=len(df))
        if extra:
            walk = walk | names.astype(str).isin(extra)
    else:
        return
    df["is_walk_in"] = walk.astype("boolean")
    if "customer_name" in df.columns:
        names = df["customer_name"].map(lambda v: split_phone(v)[0]) if phone_same else df["customer_name"]
        df["customer_key"] = names.map(text_key).where(~walk)


# số điện thoại Việt Nam ghi kèm tên khách: 0xxxxxxxxx / +84xxxxxxxxx, có thể cách bằng khoảng trắng, chấm, gạch
_PHONE = re.compile(r"\(?\s*((?:\+84|84|0)(?:[\s.\-]?\d){9})\s*\)?")


def split_phone(name) -> tuple:
    """'Lê Hải Hà - 0327 210 166' -> ('Lê Hải Hà', '0327210166'). Không có số: (tên, None)."""
    if not isinstance(name, str):
        return name, None
    m = _PHONE.search(name)
    if not m:
        return name, None
    phone = re.sub(r"\D", "", m[1])
    phone = "0" + phone[2:] if phone.startswith("84") else phone
    clean = re.sub(r"\s*[-–,/|:]\s*$|^\s*[-–,/|:]\s*", "", (name[:m.start()] + " " + name[m.end():]).strip())
    clean = re.sub(r"\(\s*\)", "", re.sub(r"\s+", " ", clean)).strip()
    return (clean or name), phone


# Hình thức thanh toán / kênh bán ghi bằng chữ Việt, viết tắt hay mã phần mềm (cash, zalo_oa...) -> một mã chung.
# Rulebook §1: COD là hình thức riêng (không phải tiền mặt); ghi nợ không tính vào tiền mặt hay chuyển khoản.
_PAYMENT_NORM = [
    (r"\bcod\b|\bthu ho\b|ship cod", "cod"),
    (r"\bghi no\b|\bcong no\b|\bno\b|\bdebt\b|\btra sau\b|\bcredit\b", "ghi_no"),
    (r"\bvi\b|vi dien tu|e-?wallet|momo|zalo ?pay|vnpay|shopee ?pay|viettel ?money", "vi"),
    (r"chuyen khoan|\bck\b|transfer|\bbank|ngan hang|\bqr\b", "chuyen_khoan"),
    (r"\bthe\b|quet the|\bcard\b|\bpos\b|visa|master", "the"),
    (r"tien mat|\btm\b|\bcash\b", "tien_mat"),
]
_CHANNEL_NORM = [
    (r"zalo", "zalo"), (r"facebook|\bfb\b|messenger", "facebook"), (r"shopee", "shopee"), (r"lazada", "lazada"),
    (r"tiktok", "tiktok"), (r"\bgrab|shopeefood|baemin|gojek|be food", "grab"),
    (r"dien thoai|\bphone\b|hotline|goi dien", "dien_thoai"),
    (r"website|\bweb\b|online", "website"),
    (r"tai quay|tai cua hang|\bstore\b|cua hang|truc tiep|offline|tai quan|\bpos\b", "tai_quay"),
]
_PAYMENT_NORM = [(re.compile(p), c) for p, c in _PAYMENT_NORM]
_CHANNEL_NORM = [(re.compile(p), c) for p, c in _CHANNEL_NORM]


def _code_norm(v, rules) -> str | None:
    if v is None or (isinstance(v, float) and v != v):
        return None
    f = fold(str(v)).replace("_", " ")
    return next((c for rx, c in rules if rx.search(f)), "khac")


def add_code_norms(df: pd.DataFrame) -> None:
    """payment_norm, channel_norm: mã chung của hình thức thanh toán / kênh bán, để khớp chữ trong câu hỏi."""
    for col, out, kind, rules in (("payment_method", "payment_norm", "payment", _PAYMENT_NORM),
                                  ("channel", "channel_norm", "channel", _CHANNEL_NORM)):
        if col in df.columns:
            norm = df[col].map(lambda v: _code_norm(v, rules))
            # 'khac' = luật không nhận ra: LLM xếp theo nhãn; không chắc thì vẫn 'khac'
            got = llm_codes(df[col], norm.where(norm != "khac"), kind)
            df[out] = norm.where(got.isna(), got)


def add_phone_cols(df: pd.DataFrame) -> int:
    """Tên khách ghi kèm SĐT: customer_name_clean (bỏ số, để khớp tên trong câu hỏi), phone_in_name.
    customer_key vẫn tính trên tên đầy đủ: tên khác số là hai khách (rulebook §3)."""
    if "customer_name" not in df.columns:
        return 0
    parts = df["customer_name"].map(split_phone)
    phone = parts.map(lambda x: x[1])
    if not phone.notna().any():
        return 0
    df["customer_name_clean"] = parts.map(lambda x: x[0])
    df["phone_in_name"] = phone
    return int(phone.notna().sum())


# Neo ở đầu tên để không bắt nhầm tên hàng ("Thép cuộn phi 6", "Phi lê cá"). Các loại theo rulebook:
# phí phục vụ (tính doanh thu, không phải mặt hàng) | giảm giá đơn (không trừ vào doanh thu)
# | phí giao, thuế (không tính vào doanh thu) | phụ thu / phí khác (để phía query quyết)
_NON_ITEM = [(re.compile(p), t) for p, t in [
    (r"^(phi phuc vu|service charge)\b", "phi_phuc_vu"),
    (r"^(voucher|coupon|ma giam gia)\b", "voucher"),
    (r"^(giam gia|chiet khau|khuyen mai|discount)\b", "giam_gia"),
    (r"^dung \d+ diem\b", "dung_diem"),
    (r"^((phi|tien|cuoc) )?(ship|shipping|giao hang|van chuyen)\b|^phi giao\b", "phi_giao"),
    # bỏ dấu thì "Vật tư" = "vat tu", "Thuê xe" = "thue xe": thuế phải đứng riêng hoặc kèm VAT/GTGT/con số
    (r"^thue\s*(vat|gtgt|\d|%|$)|^vat\s*(\d|%|$)", "thue"),
    (r"^phu thu\b|^phi (dong goi|bao bi|tui|hop|dich vu|lap dat|cong)\b", "phi_khac"),
]]


def line_type(name) -> str:
    """'hang' hoặc loại dòng không phải hàng (rulebook §3: phí phục vụ không phải mặt hàng)."""
    if name is None or (isinstance(name, float) and name != name):
        return "hang"
    f = fold(name)
    for rx, t in _NON_ITEM:
        if rx.search(f):
            return t
    return "hang"


# ---------------------------------------------------------------- tên ghi tắt, tên gọi khác

_ALIAS_COL = re.compile(r"ten (goi )?khac|ten tat|viet tat|ghi tat|biet danh|alias|nickname")


def _weights(built: list[Built]) -> Counter:
    """Khoá tên hàng trong dòng bán (chỉ dòng hàng), đếm theo số dòng."""
    w = Counter()
    for b in built:
        if b.role == "sales_lines" and "product_name" in b.df.columns:
            names = b.df["product_name"]
            if "line_type" in b.df.columns:
                names = names[b.df["line_type"] == "hang"]
            w.update(k for k in names.map(text_key) if k)
    return w


def find_abbreviations(built: list[Built], min_cover: float = 0.5) -> dict | None:
    """Tìm bảng tra tên ghi tắt: một cột chữ phủ phần lớn tên hàng ghi trong sổ bán, cột chữ khác
    (dài hơn) là tên đầy đủ. Chỉ khi danh mục KHÔNG phủ được tên trong sổ bán (sổ ghi tắt thật).
    Trả {"table", "alias_col", "full_col", "group_col", "map": {khoá ghi tắt: tên đầy đủ}, "cover"}."""
    w = _weights(built)
    total = sum(w.values())
    if not total:
        return None
    catalog = set()
    for b in built:
        if b.role != "sales_lines" and "product_name" in b.df.columns:
            catalog.update(k for k in b.df["product_name"].map(text_key) if k)
    direct = sum(n for k, n in w.items() if k in catalog) / total
    if direct >= 0.9:
        return None
    best = None
    for b in built:
        if b.role == "sales_lines":
            continue
        text_cols = [c["column"] for c in b.columns if c.get("kind") == "text" and c["column"] in b.df.columns]
        for a in text_cols:
            keys = b.df[a].map(text_key)
            cover = sum(n for k, n in w.items() if k in set(keys.dropna())) / total
            if cover < min_cover or cover < direct + 0.2:
                continue
            for f in text_cols:
                if f == a:
                    continue
                pairs = b.df[[a, f]].dropna()
                if pairs.empty or pairs[f].str.len().mean() <= pairs[a].str.len().mean():
                    continue
                if best is None or cover > best["cover"]:
                    best = {"table": b.name, "alias_col": a, "full_col": f, "cover": cover, "direct": direct,
                            "map": {text_key(x): y for x, y in zip(pairs[a], pairs[f]) if text_key(x)}}
    if best is None:
        return None
    t = next(b for b in built if b.name == best["table"])
    # cột nhóm của bảng tra (vd "Loại": máy mới / máy cũ / phụ kiện): cột chữ ít giá trị
    groups = [c["column"] for c in t.columns if c.get("kind") == "text" and c["column"] in t.df.columns
              and c["column"] not in (best["alias_col"], best["full_col"]) and 2 <= t.df[c["column"]].nunique() <= 30]
    best["group_col"] = "category" if "category" in groups else (groups[0] if groups else None)
    if best["group_col"]:
        best["group_map"] = {text_key(x): g for x, g in zip(t.df[best["alias_col"]], t.df[best["group_col"]])
                             if text_key(x) and isinstance(g, str)}
    return best


def apply_abbreviations(built: list[Built], ab: dict) -> dict:
    """Dòng bán / nhập ghi tắt: thêm product_full (tên đầy đủ; không tra được thì giữ tên đã ghi),
    tính lại product_key, line_type theo tên đầy đủ; thêm category từ cột nhóm của bảng tra nếu chưa có."""
    stats = {}
    for b in built:
        df = b.df
        if b.role not in ("sales_lines", "purchase_lines", "deliveries") or "product_name" not in df.columns:
            continue
        keys = df["product_name"].map(text_key)
        hit = keys.map(lambda k: ab["map"].get(k) if k else None)
        df["product_full"] = hit.where(hit.notna(), df["product_name"])
        df["product_key"] = df["product_full"].map(text_key)
        if "line_type" in df.columns:
            df["line_type"] = df["product_full"].map(line_type)
        if ab.get("group_map") and "category" not in df.columns:
            df["category"] = keys.map(lambda k: ab["group_map"].get(k) if k else None)
            b.columns.append({"column": "category", "original": None, "canonical": "category",
                              "map_source": "derived", "kind": "text", "note": None,
                              "description": f"nhóm hàng tra từ bảng ghi tắt {ab['table']}.{ab['group_col']}"})
        stats[b.name] = {"abbrev_hit": int(hit.notna().sum()), "rows": len(df)}
    return stats


def collect_aliases(built: list[Built], ab: dict | None) -> pd.DataFrame:
    """_product_aliases: cách gọi khác của một mặt hàng (ghi tắt trong sổ, cột 'Tên gọi khác' của danh mục),
    để phía query khớp tên trong câu hỏi ("similac 1") với tên trong data."""
    rows = []
    if ab:
        rows += [(alias, full, f"{ab['table']}.{ab['alias_col']}") for alias, full in
                 next(b for b in built if b.name == ab["table"]).df[[ab["alias_col"], ab["full_col"]]]
                 .dropna().itertuples(index=False, name=None)]
    for b in built:
        if "product_name" not in b.df.columns:
            continue
        for c in b.columns:
            col = c["column"]
            # chỉ cột gốc chưa có tên chuẩn (cột build tự thêm có mô tả chứa "ghi tắt" nhưng không phải tên gọi)
            # "name" (tên chung chưa xếp) cạnh product_name mà tên gốc là "tên gọi khác" vẫn là cột tên gọi khác
            if c.get("map_source") == "derived" or (c.get("canonical") and c.get("canonical") != "name"):
                continue
            if col in b.df.columns and c.get("kind") == "text" and col != "product_name" and (
                    _ALIAS_COL.search(fold(c.get("original") or col)) or
                    _ALIAS_COL.search(fold(c.get("description") or ""))):
                for full, v in b.df[["product_name", col]].dropna().itertuples(index=False, name=None):
                    rows += [(a.strip(), full, f"{b.name}.{col}") for a in re.split(r"[,;/]", str(v)) if a.strip()]
    out = pd.DataFrame(rows, columns=["alias", "product_name", "source"]).drop_duplicates(["alias", "product_name"])
    out["alias_key"] = out["alias"].map(text_key)
    out["product_key"] = out["product_name"].map(text_key)
    return out


def apply_aliases(built: list[Built], aliases: pd.DataFrame) -> dict:
    """Dòng bán / nhập / giao ghi theo tên gọi khác của danh mục ("Hồng đỏ" = "Hoa hồng đỏ Đà Lạt", rulebook: các tên
    cùng chỉ một thứ là cùng một thứ): quy về tên đầy đủ như apply_abbreviations. Chỉ tên không phải tên trong danh mục
    và chỉ cách gọi trỏ về đúng một mặt hàng."""
    if aliases.empty:
        return {}
    catalog = set()
    for b in built:
        if b.role not in ("sales_lines", "purchase_lines", "deliveries") and "product_name" in b.df.columns:
            catalog.update(k for k in b.df["product_name"].map(text_key) if k)
    al = aliases.dropna(subset=["alias_key", "product_key"])
    al = al[~al["alias_key"].isin(catalog) & (al["alias_key"] != al["product_key"])]
    uniq = al.groupby("alias_key")["product_key"].nunique()
    full = dict(al[al["alias_key"].isin(uniq[uniq == 1].index)].drop_duplicates("alias_key")
                [["alias_key", "product_name"]].itertuples(index=False, name=None))
    stats = {}
    for b in built:
        df = b.df
        if not full or b.role not in ("sales_lines", "purchase_lines", "deliveries") or "product_name" not in df.columns:
            continue
        cur = df["product_full"] if "product_full" in df.columns else df["product_name"]
        hit = cur.map(text_key).map(lambda k: full.get(k) if k else None)
        if not hit.notna().any():
            continue
        df["product_full"] = hit.where(hit.notna(), cur)
        df["product_key"] = df["product_full"].map(text_key)
        if "line_type" in df.columns:
            df["line_type"] = df["product_full"].map(line_type)
        stats[b.name] = {"alias_hit": int(hit.notna().sum()), "rows": len(df)}
    return stats


# ---------------------------------------------------------------- dịch vụ: biển số, người làm, bảo hành

_PLATE = re.compile(r"\b(\d{2}[A-Z]{1,2}\d?)[\s-]*(\d{3}\.?\d{2}|\d{4,5})\b")
_HONORIFIC = re.compile(r"^(a|anh|c|chi|chu|co|em|e|ong|ba|bac|thay|mr|ms)\.?\s+|^(a|c|e)\.(?=\w)")


def plate_of(v) -> str | None:
    """'wave alpha 50K2-994.07' -> '50K2-99407' (bỏ dấu chấm, giữ gạch: một xe ghi '994.07' hay '99407' là một)."""
    if not isinstance(v, str):
        return None
    m = _PLATE.search(v.upper())
    return f"{m[1]}-{m[2].replace('.', '')}" if m else None


def person_key(v) -> str | None:
    """Tên gọi người làm: bỏ cách gọi đứng trước ('A.Đức', 'a Đức', 'anh Đức') rồi lấy tên (chữ cuối)."""
    k = text_key(v)
    if not k:
        return None
    k = _HONORIFIC.sub("", k).strip()
    return k.split()[-1] if k else None


def add_service_cols(df: pd.DataFrame) -> dict:
    out = {}
    if "vehicle" in df.columns and "plate" not in df.columns:
        df["plate"] = df["vehicle"].map(plate_of)
        out["plate_found"] = int(df["plate"].notna().sum())
    if "staff_name" in df.columns:
        df["staff_key"] = df["staff_name"].map(person_key)
    notes = [c for c in ("note", "order_note", "service_desc") if c in df.columns]
    if notes and not {"product_name", "product_id"} & set(df.columns):
        w = pd.Series(False, index=df.index)
        for c in notes:
            w |= df[c].map(lambda v: isinstance(v, str) and "bao hanh" in fold(v))
        df["is_warranty"] = w.astype("boolean")
        out["warranty_rows"] = int(w.sum())
    return out


def add_pct_flags(df: pd.DataFrame, columns: list[dict]):
    """Cột số có ô ghi '10%': thêm '<cột>_is_pct' để không hiểu nhầm 10% là 10 đồng."""
    for c in list(columns):
        col, raw = c["column"], f"{c['column']}__raw"
        if c.get("kind") != "number" or raw not in df.columns:
            continue
        mask = df[raw].map(lambda v: isinstance(v, str) and v.strip().endswith("%"))
        if mask.any():
            df[f"{col}_is_pct"] = mask.astype("boolean")
            columns.append({"column": f"{col}_is_pct", "original": None, "canonical": None, "map_source": "derived",
                            "kind": "bool", "note": None,
                            "description": f"ô {col} ghi phần trăm (giá trị là số %, không phải tiền)"})


# ---------------------------------------------------------------- quy đổi đơn vị

_CONV_TXT = re.compile(r"1\s+([^\d=;,]+?)\s*=\s*([\d.,]+)\s*([^\d=;,]+?)\s*(?=[;,]|$)")


# dạng gọn "bao=25", "cặp=2;đàn=10": vế phải không ghi đơn vị thì là đơn vị cơ bản của hàng (cột base_unit cùng dòng)
_CONV_SHORT = re.compile(r"(?:^|(?<=[;,]))\s*(?:1\s+)?([^\d=;,]+?)\s*=\s*([\d.,]+)\s*([^\d=;,]*?)\s*(?=[;,]|$)")


def _conv_rows_from_text(v, base=None) -> list[tuple[str, float, str]]:
    if not isinstance(v, str):
        return []
    out = []
    for m in _CONV_TXT.finditer(v):
        f = parse_number(m[2])
        if f:
            out.append((m[1].strip(), float(f), m[3].strip()))
    if out:
        return out
    for m in _CONV_SHORT.finditer(v):
        f, bu = parse_number(m[2]), m[3].strip() or (base if isinstance(base, str) and base.strip() else None)
        if f and bu:
            out.append((m[1].strip(), float(f), bu))
    return out


def _unit_like_col(b: "Built", skip: str, seen_units: set) -> pd.Series:
    """Bảng chưa có cột base_unit: cột chữ khác mà >= 80% giá trị là đơn vị đã thấy ở sổ (vd "ĐV cơ bản" chưa ánh xạ)."""
    df = b.df
    empty = pd.Series([None] * len(df), index=df.index)
    if not seen_units:
        return empty
    best, best_r = None, 0.0
    for c in df.columns:
        if c == skip or c.startswith("_") or c.endswith("__raw") or df[c].dtype != object:
            continue
        v = df[c].dropna()
        if len(v) < 3:
            continue
        r = v.map(text_key).isin(seen_units).mean()
        if r >= 0.8 and r > best_r:
            best, best_r = c, r
    return df[best] if best is not None else empty


def collect_conversions(built: list[Built], readme) -> pd.DataFrame:
    """Mọi dòng quy đổi của shop: bảng quy đổi, cột chữ '1 thùng = 4 bịch' trong danh mục, README.
    Kết quả mỗi dòng: (product_id, product_name, product_key, unit, factor, base_unit, source)."""
    rows = []
    # đơn vị đã thấy ở các cột đơn vị (để nhận cột "đơn vị cơ bản" chưa ánh xạ theo giá trị)
    seen_units = set()
    for b in built:
        for uc in ("unit", "base_unit", "big_unit"):
            if uc in b.df.columns:
                seen_units |= {text_key(v) for v in b.df[uc].dropna().unique()} - {None}
    for b in built:
        df, cols = b.df, set(b.df.columns)
        pid = df["product_id"] if "product_id" in cols else pd.Series([None] * len(df))
        pname = df["product_name"] if "product_name" in cols else pd.Series([None] * len(df))
        if b.role == "unit_conversions" and "big_unit" in cols:
            base = df["base_unit"] if "base_unit" in cols else pd.Series([None] * len(df))
            for i, u, f, bu in zip(range(len(df)), df["big_unit"], df["conv_factor"], base):
                if isinstance(u, str) and isinstance(f, (int, float)) and f == f and f > 0:
                    rows.append((pid.iloc[i], pname.iloc[i], u, float(f), bu, b.name))
        if "product_name" not in cols and "product_id" not in cols:
            continue
        for c in b.columns:     # cột chữ dạng "1 thùng = 4 bịch" (vd dev_013 DanhMuc.Quy đổi)
            col = c["column"]
            if c["kind"] != "text" or col not in cols:
                continue
            base = df["base_unit"] if "base_unit" in cols else _unit_like_col(b, col, seen_units)
            vals = df[col].dropna()
            if len(vals) < 3 or sum(bool(_conv_rows_from_text(v, base[i])) for i, v in vals.items()) < 0.9 * len(vals):
                continue
            for i, v in df[col].items():
                for u, f, bu in _conv_rows_from_text(v, base[i]):
                    rows.append((pid.iloc[i], pname.iloc[i], u, f, bu, f"{b.name}.{col}"))
    if readme is not None:
        for c in readme.unit_conversions:
            rows.append((None, c.product, c.big_unit, c.factor, c.base_unit, "README"))
    conv = pd.DataFrame(rows, columns=["product_id", "product_name", "unit", "factor", "base_unit", "source"])
    conv["product_key"] = conv["product_name"].map(text_key)
    conv["unit_key"] = conv["unit"].map(text_key)
    return _resolve_chains(conv.drop_duplicates(["product_id", "product_key", "unit_key", "factor"]))


def _resolve_chains(conv: pd.DataFrame) -> pd.DataFrame:
    """1 thùng = 4 lốc, 1 lốc = 6 lon -> thùng = 24 lon (đơn vị vế phải lại là đơn vị lớn của cùng hàng)."""
    if conv.empty:
        return conv
    conv = conv.copy()
    for _ in range(3):
        idx = {(r.product_id, r.product_key, r.unit_key): (r.factor, r.base_unit) for r in conv.itertuples()}
        changed = False
        for i, r in conv.iterrows():
            nxt = idx.get((r.product_id, r.product_key, text_key(r.base_unit)))
            if nxt and text_key(nxt[1]) != text_key(r.base_unit):
                conv.at[i, "factor"], conv.at[i, "base_unit"] = r.factor * nxt[0], nxt[1]
                changed = True
        if not changed:
            break
    return conv


# cột ngày chính của bảng, theo thứ tự ưu tiên (ngày phát sinh nghiệp vụ, không phải hạn dùng / ngày sinh)
_MAIN_DATE = ("order_date", "order_time", "purchase_date", "payment_date", "delivery_date", "expense_date",
              "return_date", "price_from")


def _date_range(df: pd.DataFrame) -> tuple:
    """(ngày nhỏ nhất, lớn nhất, tên cột) theo cột ngày chính của bảng; bảng không có ngày -> (NaT, NaT, None)."""
    for c in _MAIN_DATE:
        if c in df.columns:
            d = pd.to_datetime(df[c], errors="coerce").dropna()
            if len(d):
                return d.min().normalize(), d.max().normalize(), c
    return pd.NaT, pd.NaT, None


def fill_conv_ids(conv: pd.DataFrame, built: list[Built]) -> int:
    """Dòng quy đổi chỉ có tên (README, bảng quy đổi không ghi mã) -> điền mã hàng từ bảng có cả mã và tên,
    và ngược lại; chỉ khi khoá tên ứng với đúng một mã. Để phía query tra quy đổi theo mã (§8: có mã thì theo mã)."""
    if conv.empty:
        return 0
    pairs: dict[str, set] = defaultdict(set)
    names: dict[str, str] = {}
    for b in built:
        if {"product_id", "product_name"} <= set(b.df.columns):
            sub = b.df[["product_id", "product_name"]].dropna().drop_duplicates()
            for pid, nm in zip(sub["product_id"].astype(str), sub["product_name"]):
                if (k := text_key(nm)):
                    pairs[k].add(pid)
                    names.setdefault(pid, nm)
    by_key = {k: next(iter(v)) for k, v in pairs.items() if len(v) == 1}
    need_id = conv["product_id"].isna() & conv["product_key"].isin(by_key)
    conv.loc[need_id, "product_id"] = conv.loc[need_id, "product_key"].map(by_key)
    need_name = conv["product_name"].isna() & conv["product_id"].notna()
    conv.loc[need_name, "product_name"] = conv.loc[need_name, "product_id"].astype(str).map(names)
    conv.loc[need_name, "product_key"] = conv.loc[need_name, "product_name"].map(text_key)
    return int(need_id.sum() + conv.loc[need_name, "product_name"].notna().sum())


def _base_units(built: list[Built]) -> tuple[dict, dict]:
    """Đơn vị cơ bản theo mã hàng / theo khoá tên, lấy từ danh mục, tồn kho, bảng quy đổi."""
    by_id, by_name = {}, {}
    for b in built:
        if "base_unit" not in b.df.columns or b.role in ("sales_lines", "purchase_lines", "deliveries"):
            continue
        df = b.df
        if "product_id" in df.columns:
            for k, u in zip(df["product_id"], df["base_unit"]):
                if isinstance(u, str) and k is not None:
                    by_id.setdefault(str(k), u)
        if "product_name" in df.columns:
            for k, u in zip(df["product_name"].map(text_key), df["base_unit"]):
                if isinstance(u, str) and k:
                    by_name.setdefault(k, u)
    return by_id, by_name


def add_qty_base(df: pd.DataFrame, conv: pd.DataFrame, base_id: dict, base_name: dict) -> dict:
    """Thêm qty_base (và base_unit nếu thiếu) cho bảng dòng hàng có qty nhưng không có qty_base.

    qty_base_src: quy_doi (đơn vị có dòng quy đổi) | co_ban (đơn vị = đơn vị cơ bản của hàng)
                  | mac_dinh (hàng / đơn vị không có dòng quy đổi nào: hệ số 1, rulebook §10)
                  | khong_ro (thiếu số lượng).
    """
    if "qty" not in df.columns or "qty_base" in df.columns:
        return {}
    by_id = {(str(r.product_id), r.unit_key): (r.factor, r.base_unit) for r in conv.itertuples()
             if r.product_id is not None and r.product_id == r.product_id}
    by_name = {(r.product_key, r.unit_key): (r.factor, r.base_unit) for r in conv.itertuples() if r.product_key}
    has_conv_id = {k[0] for k in by_id}
    has_conv_name = {k[0] for k in by_name}
    # đơn vị cơ bản ghi ở vế phải bảng quy đổi ("1 thùng = 24 lon"): dùng khi danh mục không ghi
    conv_base_id = {str(r.product_id): r.base_unit for r in conv.itertuples()
                    if r.product_id is not None and r.product_id == r.product_id and isinstance(r.base_unit, str)}
    conv_base_name = {r.product_key: r.base_unit for r in conv.itertuples()
                      if r.product_key and isinstance(r.base_unit, str)}
    pid = df["product_id"].astype("object") if "product_id" in df.columns else pd.Series([None] * len(df))
    pkey = (df["product_key"] if "product_key" in df.columns else
            df["product_name"].map(text_key) if "product_name" in df.columns else pd.Series([None] * len(df)))
    unit = df["unit"].map(text_key) if "unit" in df.columns else pd.Series([None] * len(df))
    qb, bu, src = [], [], []
    for q, i, k, u, u_raw in zip(df["qty"], pid, pkey, unit,
                                 df["unit"] if "unit" in df.columns else [None] * len(df)):
        i = None if i is None or (isinstance(i, float) and i != i) else str(i)
        hit = by_id.get((i, u)) if i else None
        hit = hit or by_name.get((k, u))
        base = ((base_id.get(i) if i else None) or base_name.get(k)
                or (conv_base_id.get(i) if i else None) or conv_base_name.get(k))
        if not isinstance(q, (int, float)) or q != q:
            qb.append(None), bu.append(base), src.append("khong_ro")
        elif hit:
            qb.append(q * hit[0]), bu.append(hit[1] or base), src.append("quy_doi")
        elif u and (i in has_conv_id or k in has_conv_name) and not (base and text_key(base) == u):
            # hàng CÓ dòng quy đổi nhưng đơn vị của dòng không khớp đơn vị lớn nào, cũng không phải đơn vị
            # cơ bản ("th", "két"): không lặng lẽ coi hệ số 1
            qb.append(None), bu.append(base), src.append("khong_khop")
        else:
            qb.append(q), bu.append(base or (u_raw if isinstance(u_raw, str) else None))
            src.append("co_ban" if base and text_key(base) == u else "mac_dinh")
    df["qty_base"] = qb
    df["qty_base_src"] = src
    if "base_unit" not in df.columns:
        df["base_unit"] = bu
    return {k: int(v) for k, v in pd.Series(src).value_counts().items()}


# ---------------------------------------------------------------- kiểu dữ liệu, ghi DuckDB

def _is_null(v) -> bool:
    return v is None or (isinstance(v, float) and v != v) or v is pd.NaT or v is pd.NA


def cast_columns(df: pd.DataFrame, kinds: dict[str, str]) -> pd.DataFrame:
    out = {}
    for c in df.columns:
        k = kinds.get(c)
        s = df[c]
        if c.endswith("__raw") or c.startswith("_src_file") or c.startswith("_src_sheet"):
            out[c] = s.map(lambda v: None if _is_null(v) else str(v)).astype("object")
        elif c == "_src_row":
            out[c] = pd.to_numeric(s, errors="coerce").astype("Int64")
        elif k == "number":
            n = pd.to_numeric(s, errors="coerce")
            nn = n.dropna()
            out[c] = n.round().astype("Int64") if len(nn) and ((nn % 1).abs() < 1e-9).all() else n
        elif k == "datetime":
            out[c] = pd.to_datetime(s, errors="coerce")
        elif k == "bool":
            out[c] = s.map(lambda v: None if _is_null(v) else bool(v)).astype("boolean")
        elif k == "empty":
            out[c] = pd.Series([None] * len(s), dtype="object")
        else:
            out[c] = s.map(lambda v: None if _is_null(v) else str(v)).astype("object")
    return pd.DataFrame(out)


# cột build thêm: (tên, kiểu, mô tả)
DERIVED = {
    "status_norm": ("text", "trạng thái đơn chuẩn: hoan_thanh | huy | tra_hang | dang_giao (một giá trị cho cả đơn)"),
    "is_walk_in": ("bool", "đơn khách lẻ / vãng lai (có mã khách: không ghi mã; không có mã: tên trống hoặc 'khách lẻ')"),
    "customer_key": ("text", "khoá tên khách: bỏ dấu, hoa thường, khoảng trắng, dấu câu; trống với khách lẻ"),
    "is_latest_row": ("bool", "bảng ghi lịch sử trạng thái của dòng hàng: TRUE ở dòng muộn nhất của mỗi (đơn, "
                              "mặt hàng); cộng tiền / số lượng thì lọc TRUE để không tính lặp"),
    "customer_name_clean": ("text", "tên khách đã bỏ số điện thoại ghi kèm (để khớp tên trong câu hỏi)"),
    "phone_in_name": ("text", "số điện thoại tách từ tên khách"),
    "payment_norm": ("text", "hình thức thanh toán chuẩn: tien_mat / chuyen_khoan / the / vi / cod / ghi_no / khac"),
    "channel_norm": ("text", "kênh bán chuẩn: tai_quay / dien_thoai / zalo / facebook / shopee / lazada / tiktok / "
                             "grab / website / khac"),
    "product_key": ("text", "khoá tên hàng: bỏ dấu, hoa thường, khoảng trắng, dấu câu (theo product_full nếu có)"),
    "product_full": ("text", "tên hàng đầy đủ tra từ bảng ghi tắt (sổ ghi tắt); không tra được thì là tên đã ghi"),
    "line_type": ("text", "hang | phi_phuc_vu | voucher | giam_gia | dung_diem | phi_giao | thue | phi_khac "
                          "(khác 'hang' = dòng không phải mặt hàng)"),
    "qty_base": ("number", "số lượng quy về đơn vị cơ bản = qty x hệ số quy đổi (file không có cột này)"),
    "qty_base_src": ("text", "cách tính qty_base: quy_doi | co_ban | mac_dinh (hệ số 1) | khong_ro (thiếu SL) "
                             "| khong_khop (hàng có quy đổi nhưng đơn vị dòng không khớp: qty_base để trống)"),
    "base_unit": ("text", "đơn vị cơ bản của mặt hàng (lấy từ danh mục / quy đổi; không có thì đơn vị của dòng)"),
    "purchase_cancelled": ("bool", "phiếu nhập bị huỷ (theo trạng thái phiếu)"),
    "plate": ("text", "biển số tách từ ô xe (bỏ dấu chấm), xác định xe theo biển số"),
    "staff_key": ("text", "tên gọi người làm / bán: bỏ cách gọi đứng trước (A., anh, chị...), lấy tên"),
    "is_warranty": ("bool", "phiếu bảo hành (ghi chú / nội dung có 'bảo hành')"),
}


MONEY_COLS = {"unit_price", "line_amount", "line_discount", "unit_cost", "price", "new_price", "old_price",
              "order_subtotal", "order_discount", "discount", "purchase_total", "order_total", "shipping_fee", "paid",
              "debt", "payment_amount", "money", "expense_amount"}


def apply_money_scale(built: list[Built], scale: int | None) -> dict:
    """README nói tiền ghi theo nghìn / triệu đồng -> nhân mọi cột tiền về đồng. Kiểm bằng dữ liệu trước:
    giá trị tiền dòng bán (trung vị) đã từ 1.000 trở lên thì README và dữ liệu vênh nhau -> không nhân, cảnh báo."""
    if not scale or scale == 1:
        return {}
    probe = [b.df[c] for b in built if b.role in ("sales_lines", "orders")
             for c in ("unit_price", "line_amount", "order_total", "money") if c in b.df.columns]
    vals = pd.concat(probe) if probe else pd.Series(dtype=float)
    vals = pd.to_numeric(vals, errors="coerce")
    vals = vals[vals > 0]
    if vals.empty or vals.median() >= 1000:
        return {"money_scale_warning": f"README nói tiền x{scale} nhưng trung vị tiền bán = "
                                       f"{None if vals.empty else round(float(vals.median()), 2)}: không nhân"}
    for b in built:
        for c in MONEY_COLS & set(b.df.columns):
            b.df[c] = pd.to_numeric(b.df[c], errors="coerce") * scale
    return {"money_scale": scale}


def _original_column(b: Built, original: str) -> str | None:
    """Tên cột hiện tại (đã đổi tên chuẩn) của cột gốc `original` trong bảng."""
    for c in b.columns:
        if c.get("original") is not None and fold(str(c["original"])) == fold(original) and c["column"] in b.df:
            return c["column"]
    return None


def join_time_only(df: pd.DataFrame, columns: list[dict]) -> int:
    """order_time chỉ ghi giờ ("18:51", mapping.time_only) -> ngày đơn + giờ (ca sáng / chiều theo giờ tạo đơn, §2).
    Ô giờ trống giữ trống (điền theo đơn sau đó). Trả số ô đã ghép."""
    if "order_time" not in df.columns or "order_date" not in df.columns \
            or pd.api.types.is_datetime64_any_dtype(df["order_time"]):
        return 0
    hm = df["order_time"].astype("string").str.extract(TIME_ONLY.pattern, flags=re.I)
    d = pd.to_datetime(df["order_date"], errors="coerce").dt.normalize()
    t = d + pd.to_timedelta(pd.to_numeric(hm[0]), unit="h") + pd.to_timedelta(pd.to_numeric(hm[1]), unit="m")
    df["order_time"] = t
    for c in columns:
        if c["column"] == "order_time":
            c["kind"] = "datetime"
    return int(t.notna().sum())


def build_shop(shop: str, items: list[Built], readme, dropped_step1: list[dict], db_path: str,
               shared: dict | None = None, conventions: dict | None = None) -> dict:
    """items: mỗi bảng gốc đã đổi tên (name/role trống). shared: {"calendar", "rulebook"} của split.
    conventions: quy ước README đã đọc (loader/conventions.py). Ghi db_path, trả thống kê."""
    shared = shared or {}
    conventions = conventions or {}
    rb = shared.get("rulebook")
    labels.set_rules(list(rb["text"]) if rb is not None and len(rb) else [])
    built, warnings = merge_split(items)
    used: set[str] = set()
    for b in built:
        b.role = table_role(set(b.df.columns))
        if b.role == "customers" and os.environ.get("DATAMATE_KHACH_KHONG_LAP"):   # tắt mặc định (FX3f)
            # danh sách khách: mỗi khách một dòng. Mã / tên khách lặp nhiều (sổ phiên, sổ nạp tiền...) là sổ sự việc
            key = next((c for c in ("customer_id", "customer_name") if c in b.df.columns), None)
            v = b.df[key].dropna() if key else None
            if v is not None and len(v) >= 20 and v.nunique() < 0.8 * len(v):
                b.role = "other"
        b.name = sql_name(b.label, used)
    conventions = drop_contradicted(conventions, {c for b in built for c in b.df.columns})
    conv_stats = apply_money_scale(built, conventions.get("money_scale"))

    dropped = list(dropped_step1)
    for b in built:
        df, st = b.df, b.stats
        # README: trạng thái đơn ghi ở một cột khác (ghi chú...) -> nguồn trạng thái của bảng bán
        if (b.role in ("sales_lines", "orders") and "status" not in df.columns and "order_note" not in df.columns
                and conventions.get("status_column")):
            col = _original_column(b, conventions["status_column"])
            if col:
                df["order_note"] = df[col]
                st["status_from_readme"] = col
        st["rows_in"] = len(df)
        if n_time := join_time_only(df, b.columns):
            st["order_time_joined"] = n_time
        key = "order_id" if "order_id" in df.columns else "purchase_id" if "purchase_id" in df.columns else None
        if key and b.role not in ("products", "customers", "price_history", "stock", "unit_conversions"):
            st["filled"] = fill_order_groups(df, key, ORDER_LEVEL if key == "order_id" else PURCHASE_LEVEL)
            if n_day := fill_day_dates(df, "order_date" if key == "order_id" else "purchase_date"):
                st["day_filled"] = n_day
        if key == "order_id" and b.role in ("sales_lines", "orders", "sales_batches", "order_info"):
            df, dups = drop_dup_lines(df, key)
            st["dup_dropped"] = len(dups)
            dropped += [{"table": b.name, "file": f, "sheet": s, "row": r,
                         "reason": "dòng trùng cùng đơn (rulebook §8)", "text": str(k)}
                        for f, s, r, k in dups[["_src_file", "_src_sheet", "_src_row", key]].itertuples(
                            index=False, name=None)]
        if b.role in ("sales_lines", "orders"):
            st.update(add_status_norm(df))
            add_customer_cols(df, conventions.get("walk_in_labels"), phone_same_customer(shared.get("rulebook")))
        if b.role == "sales_lines" and "product_name" in df.columns:
            df["line_type"] = df["product_name"].map(line_type)
            st["non_item_lines"] = int((df["line_type"] != "hang").sum())
        if "product_name" in df.columns:
            df["product_key"] = df["product_name"].map(text_key)
        if "purchase_status" in df.columns:
            ps = df["purchase_status"].map(norm_status)
            ps = ps.fillna(llm_codes(df["purchase_status"], ps, "status"))
            df["purchase_cancelled"] = (ps == STATUS_CANCEL).astype("boolean")
        add_pct_flags(df, b.columns)
        st.update(add_service_cols(df))
        add_code_norms(df)
        if n_phone := add_phone_cols(df):
            st["names_with_phone"] = n_phone
        b.df = df

    status_stats = reconcile_status(built)

    ab = find_abbreviations(built)
    ab_stats = apply_abbreviations(built, ab) if ab else {}
    aliases = collect_aliases(built, ab)
    alias_stats = apply_aliases(built, aliases)

    conv = collect_conversions(built, readme)
    base_id, base_name = _base_units(built)
    for b in built:
        if b.role in ("sales_lines", "purchase_lines"):
            r = add_qty_base(b.df, conv, base_id, base_name)
            if r:
                b.stats["qty_base_src"] = r

    for b in built:
        known = {c["column"] for c in b.columns}
        for col, (kind, desc) in DERIVED.items():
            if col in b.df.columns and col not in known:
                b.columns.append({"column": col, "original": None, "canonical": col, "map_source": "derived",
                                  "kind": kind, "description": desc, "note": None})
        kinds = {c["column"]: c["kind"] for c in b.columns}
        b.df = cast_columns(b.df, kinds)
        b.stats["rows_out"] = len(b.df)

    conv_filled = fill_conv_ids(conv, built)      # sau qty_base: chỉ làm bảng quy đổi tra được theo mã
    ind = infer_industry(readme, built, shared.get("rulebook"))
    _write_db(db_path, shop, built, conv, readme, dropped, aliases, shared, ind,
              {**conventions, **conv_stats} if conventions else None)
    return {"tables_out": len(built), "merge_warnings": warnings, "conversions": len(conv), **conv_stats,
            "conversions_id_filled": conv_filled, **ind,
            "abbreviations": (f"{ab['table']}.{ab['alias_col']} -> {ab['full_col']} "
                              f"(phủ {ab['cover']:.0%}, danh mục phủ {ab['direct']:.0%}) {ab_stats}") if ab else None,
            "aliases": len(aliases), "alias_hits": alias_stats or None, **status_stats,
            "tables": {b.name: {"role": b.role, "label": b.label, "sources": b.sources, **b.stats} for b in built}}


def _write_db(path: str, shop: str, built: list[Built], conv: pd.DataFrame, readme, dropped: list[dict],
              aliases: pd.DataFrame | None = None, shared: dict | None = None, ind: dict | None = None,
              conventions: dict | None = None):
    shared, ind = shared or {}, ind or {}
    if os.path.exists(path):
        os.remove(path)
    con = duckdb.connect(path)
    try:
        def put(name: str, df: pd.DataFrame):
            con.register("_tmp", df)
            con.execute(f'CREATE TABLE "{name}" AS SELECT * FROM _tmp')
            con.unregister("_tmp")

        for b in built:
            put(b.name, b.df)
        has_cid = any("customer_id" in b.df.columns and b.df["customer_id"].notna().any()
                      for b in built if b.role in ("sales_lines", "orders"))
        ranges = {b.name: _date_range(b.df) for b in built}
        sales = [ranges[b.name] for b in built if b.role in ("sales_lines", "orders") and pd.notna(ranges[b.name][0])]
        put("_meta_shop", pd.DataFrame([{
            "shop": shop,
            "data_end": pd.Timestamp(readme.data_end) if readme and readme.data_end else pd.NaT,
            # khoảng ngày có đơn bán: kỳ nằm HOÀN TOÀN ngoài khoảng này thì không trả lời được (rulebook §7)
            "sales_start": min((r[0] for r in sales), default=pd.NaT),
            "sales_end": max((r[1] for r in sales), default=pd.NaT),
            "has_customer_id": has_cid,
            "intro": readme.intro if readme else None,
            "files": " | ".join(readme.files) if readme else None,
            "industry": ind.get("industry"), "industry_evidence": ind.get("industry_evidence"),
            "rulebook_section": ind.get("rulebook_section"),
            # quy ước README do LLM đọc (đơn vị tiền đã áp, cột trạng thái, thông tin sổ không ghi, quy ước khác)
            "conventions": json.dumps(conventions, ensure_ascii=False) if conventions else None,
        }]))
        if shared.get("calendar") is not None:
            put("_calendar", shared["calendar"])
            put("_tet_periods", tet_periods(shared["calendar"]))
        if shared.get("rulebook") is not None:
            put("_rulebook", shared["rulebook"])
        put("_meta_tables", pd.DataFrame([{
            "table_name": b.name, "role": b.role, "role_desc": ROLE_DESC.get(b.role), "label": b.label,
            "source_tables": " | ".join(b.sources),
            "source_files": " | ".join(sorted(b.df["_src_file"].dropna().unique())) if "_src_file" in b.df else None,
            "n_rows": len(b.df), "n_dup_dropped": b.stats.get("dup_dropped", 0),
            "n_filled_cells": sum(b.stats.get("filled", {}).values()),
            "date_column": ranges[b.name][2], "date_min": ranges[b.name][0], "date_max": ranges[b.name][1],
        } for b in built]))
        put("_meta_columns", pd.DataFrame([{"table_name": b.name, **{k: c.get(k) for k in (
            "column", "original", "canonical", "map_source", "kind", "description", "note")}}
            for b in built for c in b.columns if c["column"] in b.df.columns],
        ).rename(columns={"column": "column_name", "original": "original_name"}))
        put("_meta_conventions", pd.DataFrame(readme.conventions if readme else [], columns=["topic", "body"]))
        put("_unit_conversions", conv[["product_id", "product_name", "product_key", "unit", "factor", "base_unit",
                                       "source"]].astype({"product_id": "object", "product_name": "object"}))
        al = aliases if aliases is not None else pd.DataFrame(
            columns=["alias", "product_name", "source", "alias_key", "product_key"])
        put("_product_aliases", al.astype(object))
        md = pd.DataFrame(dropped, columns=["table", "file", "sheet", "row", "reason", "text"])
        put("_meta_dropped", md.apply(lambda s: s.map(lambda v: None if _is_null(v) else str(v)))
            .rename(columns={"table": "table_name"}))
    finally:
        con.close()
