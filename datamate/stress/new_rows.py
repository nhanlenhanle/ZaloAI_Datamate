"""Bộ câu mô phỏng dòng rulebook chưa từng thấy: luật mới tự đặt, câu hỏi mới, đáp án tính bằng SQL viết tay trên DB train.

Câu hỏi đi theo từng dòng rulebook, nên bộ khác có thể có dòng luật mới. Giấu ví dụ trên train chưa mô phỏng được việc đó:
các dạng đó vẫn nằm trong SPEC, bảng chuẩn và ngôn ngữ kế hoạch. Ở đây LLM chỉ biết luật mới qua đoạn rulebook thêm vào.
Một số dòng cần cột ngoài bảng chuẩn (tài xế, khu vực, sinh nhật...), mô phỏng bảng của ngành lạ.
Shop thiếu dữ liệu của dòng thì đáp án là unanswerable (§7).

    python -m datamate.stress.new_rows ../train/train "../solve data/ban_nop/data_llm_v2/train" "../solve data/query/t9/r"
-> <out>/: questions.jsonl, answers.jsonl, meta.jsonl (dòng luật của từng câu), luat.md (đoạn rulebook thêm).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import random
from collections import Counter
from dataclasses import dataclass
from typing import Callable

import duckdb

from datamate.query.evaluate import HOLDOUT
from datamate.query.facts import Facts, NoSource
from datamate.tests.verify_answers import _cols, _month_end, _tables


class Missing(Exception):
    """Shop không ghi loại thông tin dòng luật cần: đáp án là unanswerable."""


class Skip(Exception):
    """Câu không dùng được (không có dòng nào, đáp án bằng 0, đồng hạng): bỏ, không phải unanswerable."""


@dataclass
class Row:
    key: str
    rule: str
    asks: list[str]             # {m} {y} tháng, {name} tên, {w}: cách nói theo độ khó
    kind: str                   # number | percent | string | boolean
    gold: Callable
    pick: Callable | None = None    # chọn tên đưa vào câu: (ctx, m, y) -> tên


class Ctx:
    def __init__(self, db: str):
        self.con = duckdb.connect(db, read_only=True)
        self.f = Facts(self.con)

    @property
    def D(self) -> str:
        try:
            return self.f.table("dong_ban")
        except NoSource as e:
            raise Missing(str(e)) from e

    @property
    def O(self) -> str:
        try:
            return self.f.table("don")
        except NoSource as e:
            raise Missing(str(e)) from e

    def need(self, table: str, col: str) -> None:
        if not self.con.execute(f'SELECT COUNT("{col}") FROM "{table}"').fetchone()[0]:
            raise Missing(f"shop không ghi {col}")

    def one(self, sql: str):
        return self.con.execute(sql).fetchone()[0]

    def raw(self, role: str, *cols: str) -> str:
        for t in _tables(self.con, role):
            if set(cols) <= _cols(self.con, t):
                for c in cols:
                    if self.one(f'SELECT COUNT("{c}") FROM "{t}"'):
                        continue
                    break
                else:
                    return t
        raise Missing(f"không có {cols} ở bảng {role}")


def _money(v):
    if v is None:
        raise Skip
    return int(math.floor(float(v) + 0.5))


def _pct(v):
    if v is None:
        raise Skip
    return round(float(v), 2)


def _month(m, y) -> str:
    return f"{y}-{m:02d}"


def _top1(ctx: Ctx, sql: str, name_sql: str | None = None):
    """sql trả (khoá, số đo): đứng đầu, đồng hạng thì bỏ câu để không phụ thuộc cách xếp."""
    rows = ctx.con.execute(f"SELECT * FROM ({sql}) ORDER BY 2 DESC, 1 LIMIT 2").fetchall()
    if not rows or rows[0][1] in (None, 0) or (len(rows) > 1 and rows[0][1] == rows[1][1]):
        raise Skip
    return rows[0][0]


def _named(ctx: Ctx, D: str, col: str, key_col: str, key) -> str:
    v = ctx.one(f'''SELECT ANY_VALUE("{col}") FROM "{D}" WHERE "{key_col}" = '{str(key).replace("'", "''")}' AND "{col}" IS NOT NULL''')
    if v is None:
        raise Skip
    return v


# ---------------------------------------------------------------- các dòng chỉ cần bảng chuẩn

def g_don_lon(c, m, y, _):
    return c.one(f"SELECT COUNT(*) FROM (SELECT don FROM \"{c.D}\" WHERE hop_le AND thang = '{_month(m, y)}' GROUP BY don HAVING SUM(tien) >= 300000)")


def g_don_lon_tt(c, m, y, _):
    return _pct(c.one(f"""SELECT 100.0 * SUM(s) FILTER (WHERE s >= 300000) / SUM(s) FROM
        (SELECT SUM(tien) s FROM "{c.D}" WHERE hop_le AND thang = '{_month(m, y)}' GROUP BY don)"""))


def g_dt_ngay(c, m, y, _):
    return _money(c.one(f"SELECT SUM(tien) / COUNT(DISTINCT ngay) FROM \"{c.D}\" WHERE hop_le AND thang = '{_month(m, y)}'"))


def g_gio(c, m, y, _):
    c.need(c.D, "gio")
    return _top1(c, f"SELECT gio, COUNT(DISTINCT don) FROM \"{c.D}\" WHERE hop_le AND thang = '{_month(m, y)}' AND gio IS NOT NULL GROUP BY 1")


def g_thu(c, m, y, _):
    return _top1(c, f"SELECT thu, COUNT(DISTINCT don) FROM \"{c.D}\" WHERE hop_le AND thang = '{_month(m, y)}' GROUP BY 1")


def g_cuoi_tuan(c, m, y, _):
    return _money(c.one(f"SELECT SUM(tien) FROM \"{c.D}\" WHERE hop_le AND thang = '{_month(m, y)}' AND thu IN (6, 7)"))


def g_cuoi_tuan_tt(c, m, y, _):
    return _pct(c.one(f"SELECT 100.0 * SUM(tien) FILTER (WHERE thu IN (6, 7)) / SUM(tien) FROM \"{c.D}\" WHERE hop_le AND thang = '{_month(m, y)}'"))


def p_hang(c, m, y):
    rows = c.con.execute(f"""SELECT ANY_VALUE(ten_hang) FROM "{c.D}" WHERE hop_le AND la_mat_hang AND thang = '{_month(m, y)}' AND ten_hang IS NOT NULL
        GROUP BY hang HAVING SUM(sl_co_ban) > 0 ORDER BY SUM(tien) DESC, 1 LIMIT 10""").fetchall()
    if not rows:
        raise Skip
    return rows[(m * y) % len(rows)][0]


def g_gia_tb(c, m, y, name):
    return _money(c.one(f"""SELECT SUM(tien) / SUM(sl_co_ban) FROM "{c.D}" WHERE hop_le AND thang = '{_month(m, y)}'
        AND hang IN (SELECT hang FROM "{c.D}" WHERE ten_hang = '{name.replace("'", "''")}')"""))


def g_khach_moi(c, m, y, _):
    c.need(c.D, "khach")
    a, b = dt.date(y, m, 1), _month_end(y, m)
    return c.one(f"""SELECT COUNT(*) FROM (SELECT khach FROM "{c.D}" WHERE hop_le AND khach IS NOT NULL GROUP BY khach
        HAVING MIN(ngay) BETWEEN DATE '{a}' AND DATE '{b}')""")


def g_quay_lai(c, m, y, _):
    c.need(c.D, "khach")
    py, pm = (y - 1, 12) if m == 1 else (y, m - 1)
    return c.one(f"""SELECT COUNT(*) FROM (SELECT DISTINCT khach FROM "{c.D}" WHERE hop_le AND khach IS NOT NULL AND thang = '{_month(m, y)}'
        INTERSECT SELECT DISTINCT khach FROM "{c.D}" WHERE hop_le AND khach IS NOT NULL AND thang = '{_month(pm, py)}')""")


def g_chu_luc(c, m, y, _):
    return c.one(f"""WITH s AS (SELECT hang, la_mat_hang, SUM(tien) v FROM "{c.D}" WHERE hop_le AND thang = '{_month(m, y)}' GROUP BY 1, 2)
        SELECT COUNT(*) FROM s WHERE la_mat_hang AND hang IS NOT NULL AND v >= 0.05 * (SELECT SUM(v) FROM s)""")


def g_don_max(c, m, y, _):
    return _money(c.one(f"SELECT MAX(s) FROM (SELECT SUM(tien) s FROM \"{c.D}\" WHERE hop_le AND thang = '{_month(m, y)}' GROUP BY don)"))


def g_ban_it(c, m, y, _):
    rows = c.con.execute(f"""SELECT hang, SUM(sl_co_ban) v FROM "{c.D}" WHERE hop_le AND la_mat_hang AND hang IS NOT NULL AND thang = '{_month(m, y)}'
        GROUP BY 1 ORDER BY v, 1 LIMIT 2""").fetchall()
    if len(rows) < 2 or rows[0][1] == rows[1][1] or rows[0][1] is None:
        raise Skip
    return _named(c, c.D, "ten_hang", "hang", rows[0][0])


def g_nv(c, m, y, _):
    c.need(c.D, "nhan_vien")
    return _top1(c, f"SELECT nhan_vien, COUNT(DISTINCT don) FROM \"{c.D}\" WHERE hop_le AND nhan_vien IS NOT NULL AND thang = '{_month(m, y)}' GROUP BY 1")


def g_ghi_no(c, m, y, _):
    c.need(c.D, "thanh_toan")
    return _pct(c.one(f"""SELECT 100.0 * COUNT(DISTINCT don) FILTER (WHERE thanh_toan = 'ghi_no') / COUNT(DISTINCT don) FROM "{c.D}"
        WHERE hop_le AND thang = '{_month(m, y)}'"""))


def g_ti_le_tra(c, m, y, _):
    return _pct(c.one(f"SELECT 100.0 * COUNT(*) FILTER (WHERE trang_thai = 'tra_hang') / COUNT(*) FROM \"{c.O}\" WHERE thang = '{_month(m, y)}'"))


def g_mat_huy(c, m, y, _):
    return _money(c.one(f"SELECT SUM(tien) FROM \"{c.D}\" WHERE trang_thai = 'huy' AND thang = '{_month(m, y)}'"))


def g_so_mon(c, m, y, _):
    return _pct(c.one(f"SELECT SUM(sl_co_ban) / COUNT(DISTINCT don) FROM \"{c.D}\" WHERE hop_le AND la_mat_hang AND thang = '{_month(m, y)}'"))


def g_ngay_trong(c, m, y, _):
    days = _month_end(y, m).day
    have = c.one(f"SELECT COUNT(DISTINCT ngay) FROM \"{c.D}\" WHERE hop_le AND thang = '{_month(m, y)}'")
    return days - have if have else None


def g_hang_moi(c, m, y, _):
    a, b = dt.date(y, m, 1), _month_end(y, m)
    return c.one(f"""SELECT COUNT(*) FROM (SELECT hang FROM "{c.D}" WHERE hop_le AND la_mat_hang AND hang IS NOT NULL GROUP BY hang
        HAVING MIN(ngay) BETWEEN DATE '{a}' AND DATE '{b}')""")


def g_nhieu_mon(c, m, y, _):
    return c.one(f"""SELECT COUNT(*) FROM (SELECT don FROM "{c.D}" WHERE hop_le AND la_mat_hang AND thang = '{_month(m, y)}' GROUP BY don
        HAVING COUNT(DISTINCT hang) >= 3)""")


def g_khach_le(c, m, y, _):
    return _pct(c.one(f"SELECT 100.0 * COUNT(DISTINCT don) FILTER (WHERE khach_le) / COUNT(DISTINCT don) FROM \"{c.D}\" WHERE hop_le AND thang = '{_month(m, y)}'"))


# ---------------------------------------------------------------- các dòng cần cột ngoài bảng chuẩn

def _rounds(c, t: str) -> str:
    """Số đợt: mỗi đợt của mỗi đơn một đợt (§6); sổ giao ghi mỗi mặt hàng một dòng nên không đếm dòng."""
    return "COUNT(DISTINCT (order_id, delivery_round))" if {"order_id", "delivery_round"} <= _cols(c.con, t) else "COUNT(*)"


def g_tai_xe(c, m, y, _):
    t = c.raw("deliveries", "driver", "delivery_date")
    return _top1(c, f"SELECT driver, {_rounds(c, t)} FROM \"{t}\" WHERE strftime(CAST(delivery_date AS DATE), '%Y-%m') = '{_month(m, y)}' AND driver IS NOT NULL GROUP BY 1")


def g_xe(c, m, y, _):
    t = c.raw("deliveries", "plate", "delivery_date")
    return _top1(c, f"SELECT plate, {_rounds(c, t)} FROM \"{t}\" WHERE strftime(CAST(delivery_date AS DATE), '%Y-%m') = '{_month(m, y)}' AND plate IS NOT NULL GROUP BY 1")


def g_khu_vuc(c, m, y, _):
    t = c.raw("order_info", "area", "order_id")
    return _top1(c, f"""SELECT i.area, SUM(o.doanh_thu) FROM "{c.O}" o JOIN "{t}" i ON o.don = CAST(i.order_id AS VARCHAR)
        WHERE o.hop_le AND o.thang = '{_month(m, y)}' AND i.area IS NOT NULL GROUP BY 1""")


def g_khach_ban(c, m, y, _):
    t = c.raw("order_info", "guests", "order_id")
    return _pct(c.one(f"""SELECT AVG(CAST(i.guests AS DOUBLE)) FROM "{c.O}" o JOIN "{t}" i ON o.don = CAST(i.order_id AS VARCHAR)
        WHERE o.hop_le AND o.thang = '{_month(m, y)}'"""))


def g_phi_giao(c, m, y, _):
    t = c.raw("orders", "shipping_fee", "order_id")
    return _money(c.one(f"""SELECT SUM(i.shipping_fee) FROM "{c.O}" o JOIN "{t}" i ON o.don = CAST(i.order_id AS VARCHAR)
        WHERE o.hop_le AND o.thang = '{_month(m, y)}'"""))


def g_tien_thu(c, m, y, _):
    t = c.raw("payments", "payment_amount", "payment_date")
    return _money(c.one(f"SELECT SUM(payment_amount) FROM \"{t}\" WHERE strftime(CAST(payment_date AS DATE), '%Y-%m') = '{_month(m, y)}'"))


def g_khoan_chi(c, m, y, _):
    t = c.raw("expenses", "expense_item", "expense_date", "expense_amount")
    return _top1(c, f"SELECT expense_item, SUM(expense_amount) FROM \"{t}\" WHERE strftime(CAST(expense_date AS DATE), '%Y-%m') = '{_month(m, y)}' GROUP BY 1")


def _birthday(c) -> tuple[str, str]:
    for t in _tables(c.con, "customers"):
        for col in _cols(c.con, t):
            if col in ("Ngày sinh", "Sinh nhật", "ngay_sinh"):
                if c.one(f'SELECT COUNT(TRY_CAST("{col}" AS DATE)) FROM "{t}"'):
                    return t, col
    raise Missing("không có ngày sinh")


def g_sinh_nhat(c, m, y, _):
    t, col = _birthday(c)
    return c.one(f'SELECT COUNT(*) FROM "{t}" WHERE month(TRY_CAST("{col}" AS DATE)) = {m}')


def g_den_han(c, m, y, _):
    t = c.raw("debt_terms", "due_date", "order_id")
    return c.one(f"SELECT COUNT(DISTINCT order_id) FROM \"{t}\" WHERE strftime(CAST(due_date AS DATE), '%Y-%m') = '{_month(m, y)}'")


def p_brand(c, m, y):
    for t in _tables(c.con, "products"):
        for col in _cols(c.con, t):
            if col in ("Thương hiệu", "thuong_hieu"):
                rows = c.con.execute(f'''SELECT "{col}" FROM "{t}" WHERE "{col}" IS NOT NULL GROUP BY 1 HAVING COUNT(*) >= 2 ORDER BY COUNT(*) DESC, 1 LIMIT 5''').fetchall()
                if rows:
                    return rows[m % len(rows)][0]
    raise Missing("không có thương hiệu")


def g_brand(c, m, y, name):
    for t in _tables(c.con, "products"):
        for col in _cols(c.con, t):
            if col in ("Thương hiệu", "thuong_hieu"):
                return c.one(f'''SELECT COUNT(*) FROM "{t}" WHERE "{col}" = '{name.replace("'", "''")}' ''')
    raise Missing("không có thương hiệu")


ROWS = [
    Row("don_lon", "**Đơn lớn** là đơn có doanh thu (§1) từ 300.000 đồng trở lên",
        ["Tháng {m}/{y} có bao nhiêu đơn lớn?", "thang {m}/{y} co may don lon", "đếm giúp số đơn lớn trong tháng {m} năm {y}"], "number", g_don_lon),
    Row("don_lon_tt", "**Tỉ trọng đơn lớn** là phần trăm doanh thu của các đơn lớn trong doanh thu cả shop cùng kỳ",
        ["Tỉ trọng đơn lớn tháng {m}/{y} là bao nhiêu %?", "thang {m}/{y} don lon chiem bn % dthu", "cho hỏi tỉ trọng đơn lớn của tháng {m} năm {y}"], "percent", g_don_lon_tt),
    Row("dt_ngay", "**Doanh thu bình quân ngày bán** là doanh thu của kỳ chia cho số ngày có ít nhất một đơn §1 trong kỳ; làm tròn về đồng",
        ["Doanh thu bình quân ngày bán tháng {m}/{y} là bao nhiêu?", "dthu binh quan ngay ban thang {m}/{y} la bn", "tháng {m} năm {y} bình quân mỗi ngày bán thu được nhiêu tiền"], "number", g_dt_ngay),
    Row("gio", "**Giờ cao điểm** là giờ (0–23, theo giờ tạo đơn) có nhiều đơn §1 nhất trong kỳ; trả về số giờ",
        ["Giờ cao điểm của tháng {m}/{y} là mấy giờ?", "gio cao diem thang {m}/{y} la may gio", "tháng {m} năm {y} mấy giờ là đông đơn nhất vậy"], "number", g_gio),
    Row("thu", "**Thứ đông khách** là thứ trong tuần có nhiều đơn §1 nhất trong kỳ; ghi bằng số, 1 là thứ Hai, 7 là Chủ nhật",
        ["Tháng {m}/{y} thứ đông khách là thứ mấy, ghi bằng số?", "thu dong khach thang {m}/{y} la so may", "cho hỏi tháng {m} năm {y} thứ đông khách là số mấy"], "number", g_thu),
    Row("cuoi_tuan", "**Doanh thu cuối tuần** là doanh thu của các đơn đặt vào thứ Bảy và Chủ nhật trong kỳ",
        ["Doanh thu cuối tuần tháng {m}/{y} là bao nhiêu?", "dthu cuoi tuan thang {m}/{y} bn", "tháng {m} năm {y} mấy ngày cuối tuần bán đc tổng bao nhiêu tiền"], "number", g_cuoi_tuan),
    Row("cuoi_tuan_tt", "**Tỉ trọng cuối tuần** là phần trăm doanh thu cuối tuần trong doanh thu cả kỳ",
        ["Tỉ trọng cuối tuần tháng {m}/{y} là bao nhiêu %?", "thang {m}/{y} cuoi tuan chiem bao nhieu phan tram dthu", "tỉ trọng cuối tuần của tháng {m} năm {y} bn %"], "percent", g_cuoi_tuan_tt),
    Row("gia_tb", "**Giá bán thực** của một mặt hàng là doanh thu của mặt hàng đó chia cho số lượng quy về đơn vị cơ bản trong kỳ; làm tròn về đồng",
        ["Giá bán thực của {name} tháng {m}/{y} là bao nhiêu?", "gia ban thuc cua {name} thang {m}/{y} la bn", "tháng {m} năm {y} {name} có giá bán thực bao nhiêu vậy"], "number", g_gia_tb, p_hang),
    Row("khach_moi", "**Khách mới** của kỳ là khách có đơn §1 đầu tiên trong dữ liệu rơi vào kỳ đó",
        ["Tháng {m}/{y} có bao nhiêu khách mới?", "thang {m}/{y} co bn khach moi", "đếm giùm số khách mới trong tháng {m} năm {y}"], "number", g_khach_moi),
    Row("quay_lai", "**Khách quay lại** của tháng là khách có đơn §1 trong tháng đó và cũng có đơn §1 trong tháng liền trước",
        ["Tháng {m}/{y} có bao nhiêu khách quay lại?", "thang {m}/{y} co may khach quay lai", "số khách quay lại của tháng {m} năm {y} là bn"], "number", g_quay_lai),
    Row("chu_luc", "**Mặt hàng chủ lực** của kỳ là mặt hàng có doanh thu từ 5% doanh thu cả shop cùng kỳ trở lên",
        ["Tháng {m}/{y} có mấy mặt hàng chủ lực?", "thang {m}/{y} co bn mat hang chu luc", "đếm số mặt hàng chủ lực của tháng {m} năm {y}"], "number", g_chu_luc),
    Row("don_max", "**Đơn kỷ lục** của kỳ là đơn §1 có doanh thu cao nhất trong kỳ; giá trị là doanh thu của đơn đó",
        ["Đơn kỷ lục tháng {m}/{y} trị giá bao nhiêu?", "don ky luc thang {m}/{y} bao nhieu tien", "tháng {m} năm {y} đơn kỷ lục được bn tiền"], "number", g_don_max),
    Row("ban_it", "**Hàng ế nhất** của kỳ là mặt hàng có số lượng quy về đơn vị cơ bản thấp nhất trong các mặt hàng có bán trong kỳ",
        ["Tháng {m}/{y} hàng ế nhất là gì?", "hang e nhat thang {m}/{y} la gi", "cho hỏi mặt hàng ế nhất tháng {m} năm {y}"], "string", g_ban_it),
    Row("nv", "**Nhân viên nhiều đơn** của kỳ là nhân viên có nhiều đơn §1 nhất trong kỳ, không xét doanh thu",
        ["Tháng {m}/{y} nhân viên nhiều đơn là ai?", "nhan vien nhieu don thang {m}/{y} la ai", "ai là nhân viên nhiều đơn của tháng {m} năm {y}"], "string", g_nv),
    Row("ghi_no", "**Tỉ lệ ghi nợ** là phần trăm số đơn §1 có hình thức ghi nợ trong mọi đơn §1 của kỳ",
        ["Tỉ lệ ghi nợ tháng {m}/{y} là bao nhiêu %?", "ti le ghi no thang {m}/{y} bn %", "tháng {m} năm {y} tỉ lệ ghi nợ bao nhiêu phần trăm"], "percent", g_ghi_no),
    Row("ti_le_tra", "**Tỉ lệ trả hàng** là phần trăm đơn trả hàng trong mọi đơn đặt trong kỳ, mọi trạng thái",
        ["Tỉ lệ trả hàng tháng {m}/{y} là bao nhiêu %?", "ti le tra hang thang {m}/{y} la bn phan tram", "tháng {m} năm {y} tỉ lệ trả hàng là mấy %"], "percent", g_ti_le_tra),
    Row("mat_huy", "**Doanh thu mất do huỷ** là tổng thành tiền các dòng hàng của đơn huỷ đặt trong kỳ",
        ["Doanh thu mất do huỷ tháng {m}/{y} là bao nhiêu?", "dthu mat do huy thang {m}/{y} bn", "tháng {m} năm {y} mất bao nhiêu doanh thu do huỷ đơn"], "number", g_mat_huy),
    Row("so_mon", "**Số món mỗi đơn** là tổng số lượng quy về đơn vị cơ bản của các dòng là mặt hàng chia cho số đơn §1 trong kỳ; làm tròn 2 chữ số",
        ["Số món mỗi đơn tháng {m}/{y} là bao nhiêu?", "so mon moi don thang {m}/{y} la bn", "bình quân tháng {m} năm {y} số món mỗi đơn là mấy"], "number", g_so_mon),
    Row("ngay_trong", "**Ngày trắng** của tháng là ngày dương lịch trong tháng không có đơn §1 nào",
        ["Tháng {m}/{y} có mấy ngày trắng?", "thang {m}/{y} co bn ngay trang", "đếm số ngày trắng của tháng {m} năm {y}"], "number", g_ngay_trong),
    Row("hang_moi", "**Hàng mới** của kỳ là mặt hàng có đơn §1 đầu tiên trong dữ liệu rơi vào kỳ đó",
        ["Tháng {m}/{y} có bao nhiêu hàng mới?", "thang {m}/{y} co may hang moi", "số hàng mới của tháng {m} năm {y} là bn"], "number", g_hang_moi),
    Row("nhieu_mon", "**Đơn đa dạng** là đơn §1 có từ 3 mặt hàng khác nhau trở lên",
        ["Tháng {m}/{y} có bao nhiêu đơn đa dạng?", "thang {m}/{y} co bn don da dang", "đếm giúp số đơn đa dạng tháng {m} năm {y}"], "number", g_nhieu_mon),
    Row("khach_le", "**Tỉ lệ khách vãng lai** là phần trăm số đơn §1 của khách lẻ trong mọi đơn §1 của kỳ",
        ["Tỉ lệ khách vãng lai tháng {m}/{y} là bao nhiêu %?", "ti le khach vang lai thang {m}/{y} bn %", "tháng {m} năm {y} khách vãng lai chiếm mấy % số đơn"], "percent", g_khach_le),
    Row("tai_xe", "**Tài xế chăm nhất** của tháng là tài xế có nhiều đợt giao nhất có ngày giao trong tháng",
        ["Tháng {m}/{y} tài xế chăm nhất là ai?", "tai xe cham nhat thang {m}/{y} la ai", "ai là tài xế chạy nhiều đợt nhất tháng {m} năm {y}"], "string", g_tai_xe),
    Row("xe", "**Xe chạy nhiều nhất** của tháng là biển số có nhiều đợt giao nhất có ngày giao trong tháng",
        ["Tháng {m}/{y} xe chạy nhiều nhất là biển số nào?", "xe chay nhieu nhat thang {m}/{y} bien so gi", "biển số nào chạy nhiều đợt nhất tháng {m} năm {y}"], "string", g_xe),
    Row("khu_vuc", "**Khu vực đắt khách** của kỳ là khu vực có doanh thu (§1) cao nhất, theo khu vực ghi cho từng đơn",
        ["Tháng {m}/{y} khu vực đắt khách là khu nào?", "khu vuc dat khach thang {m}/{y} la khu nao", "cho hỏi khu vực bán được nhiều tiền nhất tháng {m} năm {y}"], "string", g_khu_vuc),
    Row("khach_ban", "**Số khách mỗi bàn** là số khách ghi cho từng đơn §1, tính trung bình các đơn trong kỳ; làm tròn 2 chữ số",
        ["Số khách mỗi bàn tháng {m}/{y} là bao nhiêu?", "so khach moi ban thang {m}/{y} bn", "bình quân mỗi bàn có mấy khách trong tháng {m} năm {y}"], "number", g_khach_ban),
    Row("phi_giao", "**Tổng phí giao** là tổng phí giao hàng ghi trên các đơn §1 đặt trong kỳ",
        ["Tổng phí giao tháng {m}/{y} là bao nhiêu?", "tong phi giao thang {m}/{y} la bn", "tháng {m} năm {y} phí giao cộng lại hết nhiêu tiền"], "number", g_phi_giao),
    Row("tien_thu", "**Tiền thu trong kỳ** là tổng các khoản ghi ở sổ thu tiền có ngày thu trong kỳ, không phân biệt đơn nào",
        ["Tiền thu trong tháng {m}/{y} là bao nhiêu?", "tien thu thang {m}/{y} la bn", "theo sổ thu, tháng {m} năm {y} thu được tổng bao nhiêu tiền"], "number", g_tien_thu),
    Row("khoan_chi", "**Khoản chi lớn nhất** của tháng là khoản mục có tổng tiền chi cao nhất trong sổ chi phí của tháng đó",
        ["Khoản chi lớn nhất tháng {m}/{y} là khoản nào?", "khoan chi lon nhat thang {m}/{y} la gi", "tháng {m} năm {y} chi nhiều nhất cho khoản gì"], "string", g_khoan_chi),
    Row("sinh_nhat", "**Khách sinh nhật tháng M** là khách trong danh sách khách có ngày sinh rơi vào tháng M, năm nào cũng được",
        ["Có bao nhiêu khách sinh nhật tháng {m}?", "co bn khach sinh nhat thang {m}", "đếm số khách có sinh nhật trong tháng {m}"], "number", g_sinh_nhat),
    Row("den_han", "**Đơn đến hạn** của tháng là đơn có hạn thanh toán rơi vào tháng đó, theo hạn ghi ở sổ công nợ",
        ["Tháng {m}/{y} có bao nhiêu đơn đến hạn?", "thang {m}/{y} co may don den han", "số đơn đến hạn thanh toán của tháng {m} năm {y} là bn"], "number", g_den_han),
    Row("brand", "**Hàng theo thương hiệu** là số mặt hàng trong danh mục ghi đúng thương hiệu đó",
        ["Có bao nhiêu mặt hàng thương hiệu {name}?", "co bn mat hang thuong hieu {name}", "danh mục có mấy mặt hàng của thương hiệu {name}"], "number", g_brand, p_brand),
]


# ---------------------------------------------------------------- bộ thứ hai: viết sau khi đã mở rộng ngôn ngữ kế hoạch theo bộ trên,
# dùng để đo, không dùng để thiết kế: xem lỗi trên bộ này rồi sửa thì phải viết bộ mới

def g2_dinh_day(c, m, y, _):
    r = c.con.execute(f"""SELECT MAX(s), MIN(s) FROM (SELECT SUM(tien) s FROM "{c.D}" WHERE hop_le AND thang = '{_month(m, y)}' GROUP BY ngay)""").fetchone()
    return None if r[0] is None else _money(r[0] - r[1])


def g2_don_nho(c, m, y, _):
    return c.one(f"SELECT COUNT(*) FROM (SELECT don FROM \"{c.D}\" WHERE hop_le AND thang = '{_month(m, y)}' GROUP BY don HAVING SUM(tien) < 100000)")


def g2_don_sang(c, m, y, _):
    c.need(c.D, "ca")
    return _pct(c.one(f"SELECT 100.0 * COUNT(DISTINCT don) FILTER (WHERE ca = 'sang') / COUNT(DISTINCT don) FROM \"{c.D}\" WHERE hop_le AND thang = '{_month(m, y)}'"))


def g2_mon_ruot(c, m, y, _):
    k = _top1(c, f"SELECT hang, COUNT(DISTINCT don) FROM \"{c.D}\" WHERE hop_le AND la_mat_hang AND hang IS NOT NULL AND thang = '{_month(m, y)}' GROUP BY 1")
    return _named(c, c.D, "ten_hang", "hang", k)


def g2_trung_thanh(c, m, y, _):
    c.need(c.D, "khach")
    return c.one(f"""SELECT COUNT(*) FROM (SELECT khach FROM "{c.D}" WHERE hop_le AND khach IS NOT NULL AND ngay BETWEEN DATE '{y}-01-01' AND DATE '{y}-12-31'
        GROUP BY khach HAVING COUNT(DISTINCT thang) >= 3)""")


def g2_mot_lan(c, m, y, _):
    c.need(c.D, "khach")
    return c.one(f"""SELECT COUNT(*) FROM (SELECT khach FROM "{c.D}" WHERE hop_le AND khach IS NOT NULL AND thang = '{_month(m, y)}' GROUP BY khach
        HAVING COUNT(DISTINCT don) = 1)""")


def g2_dau_thang(c, m, y, _):
    return _money(c.one(f"SELECT SUM(tien) FROM \"{c.D}\" WHERE hop_le AND ngay BETWEEN DATE '{y}-{m:02d}-01' AND DATE '{y}-{m:02d}-10'"))


def g2_gio_trua(c, m, y, _):
    c.need(c.D, "gio")
    return _money(c.one(f"SELECT SUM(tien) FROM \"{c.D}\" WHERE hop_le AND thang = '{_month(m, y)}' AND gio BETWEEN 11 AND 13"))


def g2_tang_thang(c, m, y, _):
    py, pm = (y - 1, 12) if m == 1 else (y, m - 1)
    a = c.one(f"SELECT SUM(tien) FROM \"{c.D}\" WHERE hop_le AND thang = '{_month(m, y)}'")
    b = c.one(f"SELECT SUM(tien) FROM \"{c.D}\" WHERE hop_le AND thang = '{_month(pm, py)}'")
    if a is None or b is None:
        raise Skip
    return bool(a > b)


def g2_hang_dat(c, m, y, _):
    k = _top1(c, f"SELECT hang, MAX(don_gia) FROM \"{c.D}\" WHERE hop_le AND la_mat_hang AND hang IS NOT NULL AND don_gia IS NOT NULL AND thang = '{_month(m, y)}' GROUP BY 1")
    return _named(c, c.D, "ten_hang", "hang", k)


def _end_of(m, y):
    return _month_end(y, m)


def g2_no_lau(c, m, y, _):
    try:
        t = c.f.table("cong_no", at=_end_of(m, y))
    except NoSource as e:
        raise Missing(str(e)) from e
    return c.one(f'SELECT COUNT(*) FROM "{t}" WHERE tuoi_no > 30')


def g2_khach_no(c, m, y, _):
    try:
        t = c.f.table("cong_no", at=_end_of(m, y))
    except NoSource as e:
        raise Missing(str(e)) from e
    c.need(t, "khach")
    k = _top1(c, f'SELECT khach, SUM(con_no) FROM "{t}" WHERE khach IS NOT NULL GROUP BY 1')
    return _named(c, t, "ten_khach", "khach", k)


def g2_phieu_max(c, m, y, _):
    try:
        t = c.f.table("phieu_nhap")
    except NoSource as e:
        raise Missing(str(e)) from e
    return _money(c.one(f"SELECT MAX(tong_tien) FROM \"{t}\" WHERE strftime(ngay, '%Y-%m') = '{_month(m, y)}'"))


def g2_ncc_so(c, m, y, _):
    try:
        t = c.f.table("phieu_nhap")
    except NoSource as e:
        raise Missing(str(e)) from e
    c.need(t, "nha_cung_cap")
    return c.one(f"SELECT COUNT(DISTINCT nha_cung_cap) FROM \"{t}\" WHERE strftime(ngay, '%Y-%m') = '{_month(m, y)}'")


def g2_khach_phone(c, m, y, _):
    t = c.raw("customers", "phone")
    return c.one(f'SELECT COUNT(*) FROM "{t}" WHERE phone IS NOT NULL')


def g2_dot2(c, m, y, _):
    t = c.raw("deliveries", "delivery_round", "delivery_date")
    return c.one(f"""SELECT {_rounds(c, t)} FROM "{t}" WHERE strftime(CAST(delivery_date AS DATE), '%Y-%m') = '{_month(m, y)}' AND TRY_CAST(delivery_round AS DOUBLE) >= 2""")


def g2_nhom_khach(c, m, y, _):
    t = c.raw("customers", "customer_group")
    rows = c.con.execute(f'SELECT customer_group, COUNT(*) v FROM "{t}" WHERE customer_group IS NOT NULL GROUP BY 1 ORDER BY v DESC, 1 LIMIT 2').fetchall()
    if len(rows) < 2 or rows[0][1] == rows[1][1]:
        raise Skip
    return rows[0][0]


def g2_giam_dong(c, m, y, _):
    for t in _tables(c.con, "sales_lines"):
        if "line_discount" in _cols(c.con, t) and "order_id" in _cols(c.con, t):
            v = c.one(f"""SELECT SUM(l.line_discount) FROM "{t}" l JOIN "{c.O}" o ON CAST(l.order_id AS VARCHAR) = o.don
                WHERE o.hop_le AND o.thang = '{_month(m, y)}'""")
            return _money(v)
    raise Missing("không có giảm giá dòng")


ROWS2 = [
    Row("dinh_day", "**Biên độ ngày** của tháng là doanh thu của ngày cao nhất trừ doanh thu của ngày thấp nhất, chỉ xét các ngày có đơn §1",
        ["Biên độ ngày tháng {m}/{y} là bao nhiêu?", "bien do ngay thang {m}/{y} bn", "tháng {m} năm {y} ngày cao nhất hơn ngày thấp nhất bao nhiêu, tức biên độ ngày"], "number", g2_dinh_day),
    Row("don_nho", "**Đơn nhỏ** là đơn có doanh thu (§1) dưới 100.000 đồng",
        ["Tháng {m}/{y} có bao nhiêu đơn nhỏ?", "thang {m}/{y} co may don nho", "đếm số đơn nhỏ của tháng {m} năm {y}"], "number", g2_don_nho),
    Row("don_sang", "**Tỉ lệ đơn sáng** là phần trăm số đơn §1 thuộc ca sáng trong mọi đơn §1 của kỳ",
        ["Tỉ lệ đơn sáng tháng {m}/{y} là bao nhiêu %?", "ti le don sang thang {m}/{y} la bn phan tram", "tháng {m} năm {y} đơn sáng chiếm mấy %"], "percent", g2_don_sang),
    Row("mon_ruot", "**Món ruột** của kỳ là mặt hàng xuất hiện trong nhiều đơn §1 khác nhau nhất, không xét số lượng",
        ["Tháng {m}/{y} món ruột là món nào?", "mon ruot thang {m}/{y} la gi", "cho hỏi món ruột của tháng {m} năm {y}"], "string", g2_mon_ruot),
    Row("trung_thanh", "**Khách trung thành** của năm là khách có đơn §1 trong ít nhất 3 tháng khác nhau của năm đó",
        ["Năm {y} có bao nhiêu khách trung thành?", "nam {y} co bn khach trung thanh", "đếm khách trung thành của năm {y}"], "number", g2_trung_thanh),
    Row("mot_lan", "**Khách một lần** của tháng là khách có đúng một đơn §1 trong tháng đó",
        ["Tháng {m}/{y} có bao nhiêu khách một lần?", "thang {m}/{y} co may khach mot lan", "số khách một lần của tháng {m} năm {y} là bn"], "number", g2_mot_lan),
    Row("dau_thang", "**Doanh thu đầu tháng** là doanh thu của 10 ngày đầu tháng, từ ngày 1 đến hết ngày 10",
        ["Doanh thu đầu tháng {m}/{y} là bao nhiêu?", "dthu dau thang {m}/{y} bn", "tháng {m} năm {y} doanh thu đầu tháng được nhiêu tiền"], "number", g2_dau_thang),
    Row("gio_trua", "**Doanh thu giờ trưa** là doanh thu của các đơn có giờ tạo đơn từ 11:00 đến hết 13:59",
        ["Doanh thu giờ trưa tháng {m}/{y} là bao nhiêu?", "dthu gio trua thang {m}/{y} la bn", "tháng {m} năm {y} giờ trưa bán được bao nhiêu tiền"], "number", g2_gio_trua),
    Row("tang_thang", "**Tháng tăng** là tháng có doanh thu cao hơn tháng liền trước",
        ["Tháng {m}/{y} có phải là tháng tăng không?", "thang {m}/{y} co phai thang tang ko", "tháng {m} năm {y} là tháng tăng đúng không"], "boolean", g2_tang_thang),
    Row("hang_dat", "**Hàng đắt nhất** của kỳ là mặt hàng có đơn giá ghi trên dòng bán cao nhất trong các đơn §1 của kỳ",
        ["Tháng {m}/{y} hàng đắt nhất là gì?", "hang dat nhat thang {m}/{y} la gi", "mặt hàng đắt nhất tháng {m} năm {y} là món nào"], "string", g2_hang_dat),
    Row("no_lau", "**Đơn nợ lâu** tại một ngày là đơn còn nợ có tuổi nợ trên 30 ngày tại ngày đó (§4)",
        ["Đến hết tháng {m}/{y} có bao nhiêu đơn nợ lâu?", "den het thang {m}/{y} co may don no lau", "tính đến cuối tháng {m} năm {y} số đơn nợ lâu là bn"], "number", g2_no_lau),
    Row("khach_no", "**Con nợ lớn nhất** tại một ngày là khách có tổng còn nợ cao nhất tại ngày đó (§4)",
        ["Đến hết tháng {m}/{y} con nợ lớn nhất là ai?", "den het thang {m}/{y} con no lon nhat la ai", "tính đến cuối tháng {m} năm {y} ai là con nợ lớn nhất"], "string", g2_khach_no),
    Row("phieu_max", "**Phiếu nhập lớn nhất** của tháng là phiếu nhập không huỷ có tổng tiền cao nhất trong tháng; giá trị là tổng tiền phiếu đó",
        ["Phiếu nhập lớn nhất tháng {m}/{y} là bao nhiêu tiền?", "phieu nhap lon nhat thang {m}/{y} bn tien", "tháng {m} năm {y} phiếu nhập lớn nhất trị giá bao nhiêu"], "number", g2_phieu_max),
    Row("ncc_so", "**Số nhà cung cấp hoạt động** của tháng là số nhà cung cấp có ít nhất một phiếu nhập không huỷ trong tháng",
        ["Tháng {m}/{y} có bao nhiêu nhà cung cấp hoạt động?", "thang {m}/{y} co may ncc hoat dong", "số nhà cung cấp hoạt động của tháng {m} năm {y} là bn"], "number", g2_ncc_so),
    Row("khach_phone", "**Khách có số điện thoại** là khách trong danh sách khách có ghi số điện thoại",
        ["Có bao nhiêu khách có số điện thoại?", "co bn khach co sdt", "danh sách có mấy khách ghi số điện thoại"], "number", g2_khach_phone),
    Row("dot2", "**Đợt giao bổ sung** của tháng là các đợt giao từ đợt thứ 2 trở đi của một đơn, có ngày giao trong tháng",
        ["Tháng {m}/{y} có bao nhiêu đợt giao bổ sung?", "thang {m}/{y} co may dot giao bo sung", "số đợt giao bổ sung của tháng {m} năm {y}"], "number", g2_dot2),
    Row("nhom_khach", "**Nhóm khách đông nhất** là nhóm khách có nhiều khách nhất trong danh sách khách",
        ["Nhóm khách đông nhất là nhóm nào?", "nhom khach dong nhat la nhom gi", "nhóm nào có nhiều khách nhất trong danh sách"], "string", g2_nhom_khach),
    Row("giam_dong", "**Tiền giảm trên dòng** của kỳ là tổng giảm giá ghi trên từng dòng hàng của các đơn §1 trong kỳ",
        ["Tiền giảm trên dòng tháng {m}/{y} là bao nhiêu?", "tien giam tren dong thang {m}/{y} bn", "tháng {m} năm {y} giảm giá trên dòng hết bao nhiêu tiền"], "number", g2_giam_dong),
]


# ---------------------------------------------------------------- bộ thứ ba: đủ các dạng đáp án (danh sách, ngày, bảng, đúng / sai),
# viết trước khi xem bất kỳ lỗi nào của nó, cho phép đo cuối

def _top_k(ctx: Ctx, sql: str, k: int) -> list:
    """sql trả (khoá, số đo): k đối tượng đầu, từ cao xuống thấp. Thiếu đối tượng hoặc đồng hạng thì bỏ câu."""
    rows = ctx.con.execute(f"SELECT * FROM ({sql}) ORDER BY 2 DESC, 1 LIMIT {k + 1}").fetchall()
    vals = [r[1] for r in rows]
    if len(rows) < k or None in vals or 0 in vals[:k] or len(set(vals)) < len(vals):
        raise Skip
    return [r[0] for r in rows[:k]]


def _day(v) -> str:
    if v is None:
        raise Skip
    return v.strftime("%Y-%m-%d")


def _fact(c: Ctx, name: str, at=None) -> str:
    try:
        return c.f.table(name, at=at) if at else c.f.table(name)
    except NoSource as e:
        raise Missing(str(e)) from e


def g3_ba_ngay(c, m, y, _):
    return [_day(d) for d in _top_k(c, f"SELECT ngay, SUM(tien) FROM \"{c.D}\" WHERE hop_le AND thang = '{_month(m, y)}' GROUP BY 1", 3)]


def g3_mo_hang(c, m, y, _):
    return _day(c.one(f"SELECT MIN(ngay) FROM \"{c.D}\" WHERE hop_le AND thang = '{_month(m, y)}'"))


def g3_chot(c, m, y, _):
    return _day(c.one(f"SELECT MAX(ngay) FROM \"{c.D}\" WHERE hop_le AND thang = '{_month(m, y)}'"))


def g3_hai_nhom(c, m, y, _):
    c.need(c.D, "nhom_hang")
    return _top_k(c, f"SELECT nhom_hang, SUM(tien) FROM \"{c.D}\" WHERE hop_le AND nhom_hang IS NOT NULL AND thang = '{_month(m, y)}' GROUP BY 1", 2)


def g3_bang_kenh(c, m, y, _):
    c.need(c.D, "kenh")
    rows = c.con.execute(f"SELECT kenh, SUM(tien) FROM \"{c.D}\" WHERE hop_le AND kenh IS NOT NULL AND thang = '{_month(m, y)}' GROUP BY 1 ORDER BY 2 DESC, 1").fetchall()
    if len(rows) < 2:
        raise Skip
    return {"columns": ["kenh", "doanh_thu"], "rows": [[k, _money(v)] for k, v in rows]}


def g3_don_toi(c, m, y, _):
    c.need(c.D, "gio")
    return c.one(f"SELECT COUNT(*) FROM (SELECT don FROM \"{c.D}\" WHERE hop_le AND gio >= 20 AND thang = '{_month(m, y)}' GROUP BY don)")


def g3_tt_ck(c, m, y, _):
    c.need(c.D, "thanh_toan")
    return _pct(c.one(f"SELECT 100.0 * SUM(tien) FILTER (WHERE thanh_toan = 'chuyen_khoan') / SUM(tien) FROM \"{c.D}\" WHERE hop_le AND thang = '{_month(m, y)}'"))


def g3_khach_thu(c, m, y, _):
    c.need(c.D, "khach")
    return c.one(f"""SELECT COUNT(*) FROM (SELECT khach FROM "{c.D}" WHERE hop_le AND la_mat_hang AND khach IS NOT NULL AND thang = '{_month(m, y)}'
        GROUP BY khach HAVING COUNT(DISTINCT hang) >= 3)""")


def g3_hang_mot_don(c, m, y, _):
    return c.one(f"""SELECT COUNT(*) FROM (SELECT hang FROM "{c.D}" WHERE hop_le AND la_mat_hang AND hang IS NOT NULL AND thang = '{_month(m, y)}'
        GROUP BY hang HAVING COUNT(DISTINCT don) = 1)""")


def g3_so_dong(c, m, y, _):
    return _pct(c.one(f"SELECT 1.0 * COUNT(*) FILTER (WHERE la_mat_hang) / COUNT(DISTINCT don) FROM \"{c.D}\" WHERE hop_le AND thang = '{_month(m, y)}'"))


def g3_chenh_ca(c, m, y, _):
    c.need(c.D, "ca")
    a, b = c.con.execute(f"""SELECT SUM(tien) FILTER (WHERE ca = 'sang'), SUM(tien) FILTER (WHERE ca = 'chieu') FROM "{c.D}"
        WHERE hop_le AND thang = '{_month(m, y)}'""").fetchone()
    if a is None or b is None:
        raise Skip
    return _money(a - b)


def g3_thang_dinh(c, m, y, _):
    return _top1(c, f"SELECT thang, SUM(tien) FROM \"{c.D}\" WHERE hop_le AND ngay BETWEEN DATE '{y}-01-01' AND DATE '{y}-12-31' GROUP BY 1")


def g3_xuong_doc(c, m, y, _):
    vals = []
    for back in range(3):
        idx = y * 12 + m - 1 - back
        vals.append(c.one(f"SELECT SUM(tien) FROM \"{c.D}\" WHERE hop_le AND thang = '{_month(idx % 12 + 1, idx // 12)}'"))
    if None in vals:
        raise Skip
    return bool(vals[0] < vals[1] < vals[2])


def g3_tien_tra(c, m, y, _):
    return _money(c.one(f"SELECT SUM(tien) FROM \"{c.D}\" WHERE trang_thai = 'tra_hang' AND thang = '{_month(m, y)}'"))


def g3_chi_khach(c, m, y, _):
    c.need(c.D, "khach")
    return _money(c.one(f"SELECT SUM(tien) / COUNT(DISTINCT khach) FROM \"{c.D}\" WHERE hop_le AND khach IS NOT NULL AND thang = '{_month(m, y)}'"))


def g3_ncc_phieu(c, m, y, _):
    t = _fact(c, "phieu_nhap")
    c.need(t, "nha_cung_cap")
    return _top1(c, f"SELECT nha_cung_cap, COUNT(DISTINCT phieu) FROM \"{t}\" WHERE nha_cung_cap IS NOT NULL AND strftime(ngay, '%Y-%m') = '{_month(m, y)}' GROUP BY 1")


def g3_tong_chi(c, m, y, _):
    t = _fact(c, "khoan_chi")
    return _money(c.one(f"SELECT SUM(tien) FROM \"{t}\" WHERE strftime(ngay, '%Y-%m') = '{_month(m, y)}'"))


def g3_ti_le_chi(c, m, y, _):
    t = _fact(c, "khoan_chi")
    a = c.one(f"SELECT SUM(tien) FROM \"{t}\" WHERE strftime(ngay, '%Y-%m') = '{_month(m, y)}'")
    b = c.one(f"SELECT SUM(tien) FROM \"{c.D}\" WHERE hop_le AND thang = '{_month(m, y)}'")
    if not a or not b:
        raise Skip
    return _pct(100.0 * a / b)


def g3_sap_het(c, m, y, _):
    t = _fact(c, "ton", at=_month_end(y, m))
    return c.one(f'SELECT COUNT(*) FROM "{t}" WHERE ton > 0 AND ton < 5')


def g3_no_tb(c, m, y, _):
    t = _fact(c, "cong_no", at=_month_end(y, m))
    return _money(c.one(f'SELECT SUM(con_no) / COUNT(*) FROM "{t}"'))


def g3_nang_suat(c, m, y, _):
    c.need(c.D, "nhan_vien")
    return _pct(c.one(f"SELECT 1.0 * COUNT(DISTINCT don) / COUNT(DISTINCT nhan_vien) FROM \"{c.D}\" WHERE hop_le AND thang = '{_month(m, y)}'"))


def g3_ba_khach(c, m, y, _):
    c.need(c.D, "khach")
    keys = _top_k(c, f"SELECT khach, COUNT(DISTINCT don) FROM \"{c.D}\" WHERE hop_le AND khach IS NOT NULL AND thang = '{_month(m, y)}' GROUP BY 1", 3)
    return [_named(c, c.D, "ten_khach", "khach", k) for k in keys]


def g3_ban(c, m, y, _):
    t = c.raw("order_info", "table_no", "order_id")
    return _top1(c, f"""SELECT i.table_no, COUNT(DISTINCT o.don) FROM "{c.O}" o JOIN "{t}" i ON o.don = CAST(i.order_id AS VARCHAR)
        WHERE o.hop_le AND o.thang = '{_month(m, y)}' AND i.table_no IS NOT NULL GROUP BY 1""")


def g3_han_no(c, m, y, _):
    t = c.raw("debt_terms", "credit_days", "order_id")
    return _pct(c.one(f"""SELECT AVG(CAST(i.credit_days AS DOUBLE)) FROM "{c.O}" o JOIN "{t}" i ON o.don = CAST(i.order_id AS VARCHAR)
        WHERE o.hop_le AND o.thang = '{_month(m, y)}'"""))


def g3_danh_muc(c, m, y, _):
    t = c.raw("products", "category")
    return c.one(f'SELECT COUNT(DISTINCT category) FROM "{t}"')


def g3_khach_dk(c, m, y, _):
    t = c.raw("customers", "created_date")
    return c.one(f"SELECT COUNT(*) FROM \"{t}\" WHERE strftime(CAST(created_date AS DATE), '%Y-%m') = '{_month(m, y)}'")


def g3_giam_don(c, m, y, _):
    t = c.raw("orders", "order_discount", "order_id")
    return _money(c.one(f"""SELECT SUM(CAST(i.order_discount AS DOUBLE)) FROM "{c.O}" o JOIN "{t}" i ON o.don = CAST(i.order_id AS VARCHAR)
        WHERE o.hop_le AND o.thang = '{_month(m, y)}'"""))


def g3_ht_thu(c, m, y, _):
    t = c.raw("payments", "payment_method", "payment_amount", "payment_date")
    return _top1(c, f"""SELECT payment_method, SUM(payment_amount) FROM "{t}" WHERE payment_method IS NOT NULL
        AND strftime(CAST(payment_date AS DATE), '%Y-%m') = '{_month(m, y)}' GROUP BY 1""")


def g3_doi_gia(c, m, y, _):
    t = c.raw("price_history", "price_from")
    return c.one(f"SELECT COUNT(*) FROM \"{t}\" WHERE strftime(CAST(price_from AS DATE), '%Y-%m') = '{_month(m, y)}'")


ROWS3 = [
    Row("ba_ngay", "**Ba ngày đỉnh** của tháng là 3 ngày có doanh thu (§1) cao nhất tháng, xếp từ cao xuống thấp",
        ["Ba ngày đỉnh của tháng {m}/{y} là những ngày nào?", "ba ngay dinh thang {m}/{y} la ngay nao", "liệt kê ba ngày đỉnh tháng {m} năm {y}"], "list", g3_ba_ngay),
    Row("mo_hang", "**Ngày mở hàng** của tháng là ngày sớm nhất trong tháng có đơn §1",
        ["Ngày mở hàng của tháng {m}/{y} là ngày nào?", "ngay mo hang thang {m}/{y} la ngay may", "tháng {m} năm {y} ngày mở hàng là hôm nào"], "date", g3_mo_hang),
    Row("chot", "**Ngày chốt sổ** của tháng là ngày muộn nhất trong tháng có đơn §1",
        ["Ngày chốt sổ của tháng {m}/{y} là ngày nào?", "ngay chot so thang {m}/{y} la ngay may", "tháng {m} năm {y} ngày chốt sổ là hôm nào"], "date", g3_chot),
    Row("hai_nhom", "**Hai nhóm trụ cột** của tháng là 2 nhóm hàng có doanh thu (§1) cao nhất, xếp từ cao xuống thấp",
        ["Hai nhóm trụ cột của tháng {m}/{y} là gì?", "hai nhom tru cot thang {m}/{y} la nhom nao", "tháng {m} năm {y} hai nhóm trụ cột là những nhóm nào"], "list", g3_hai_nhom),
    Row("bang_kenh", "**Bảng kênh** của tháng là bảng doanh thu (§1) theo từng kênh bán, mỗi dòng một kênh",
        ["Cho xem bảng kênh tháng {m}/{y}", "bang kenh thang {m}/{y}", "lập bảng kênh của tháng {m} năm {y}"], "table", g3_bang_kenh),
    Row("don_toi", "**Đơn tối muộn** là đơn §1 có giờ tạo đơn từ 20 giờ trở đi",
        ["Tháng {m}/{y} có bao nhiêu đơn tối muộn?", "thang {m}/{y} co may don toi muon", "đếm số đơn tối muộn của tháng {m} năm {y}"], "number", g3_don_toi),
    Row("tt_ck", "**Tỉ trọng chuyển khoản** là phần trăm doanh thu (§1) của các đơn thanh toán chuyển khoản trong doanh thu cả kỳ",
        ["Tỉ trọng chuyển khoản tháng {m}/{y} là bao nhiêu %?", "ti trong chuyen khoan thang {m}/{y} bn %", "tháng {m} năm {y} tỉ trọng chuyển khoản mấy phần trăm"], "percent", g3_tt_ck),
    Row("khach_thu", "**Khách thử nhiều** của tháng là khách đã mua từ 3 mặt hàng khác nhau trở lên trong tháng, trên các đơn §1",
        ["Tháng {m}/{y} có bao nhiêu khách thử nhiều?", "thang {m}/{y} co may khach thu nhieu", "đếm số khách thử nhiều của tháng {m} năm {y}"], "number", g3_khach_thu),
    Row("hang_mot_don", "**Hàng một đơn** của tháng là mặt hàng chỉ có mặt trong đúng một đơn §1 của tháng",
        ["Tháng {m}/{y} có bao nhiêu hàng một đơn?", "thang {m}/{y} co may hang mot don", "số hàng một đơn của tháng {m} năm {y} là bn"], "number", g3_hang_mot_don),
    Row("so_dong", "**Số dòng mỗi đơn** là số dòng hàng (chỉ dòng là mặt hàng) chia cho số đơn §1 trong kỳ; làm tròn 2 chữ số",
        ["Số dòng mỗi đơn tháng {m}/{y} là bao nhiêu?", "so dong moi don thang {m}/{y} bn", "tháng {m} năm {y} số dòng mỗi đơn được mấy"], "number", g3_so_dong),
    Row("chenh_ca", "**Chênh ca** của tháng là doanh thu ca sáng trừ doanh thu ca chiều; ca sáng thấp hơn thì ra số âm",
        ["Chênh ca tháng {m}/{y} là bao nhiêu?", "chenh ca thang {m}/{y} la bn", "tháng {m} năm {y} chênh ca được bao nhiêu tiền"], "number", g3_chenh_ca),
    Row("thang_dinh", "**Tháng đỉnh** của năm là tháng có doanh thu (§1) cao nhất năm đó",
        ["Tháng đỉnh của năm {y} là tháng nào?", "thang dinh nam {y} la thang may", "năm {y} tháng đỉnh rơi vào tháng nào"], "date", g3_thang_dinh),
    Row("xuong_doc", "**Ba tháng xuống dốc**: doanh thu tháng hỏi thấp hơn tháng liền trước, và tháng liền trước thấp hơn tháng trước nữa",
        ["Tháng {m}/{y} có phải ba tháng xuống dốc không?", "thang {m}/{y} co phai ba thang xuong doc ko", "tính đến tháng {m} năm {y} có đang ba tháng xuống dốc không"], "boolean", g3_xuong_doc),
    Row("tien_tra", "**Tiền hàng bị trả** là tổng thành tiền các dòng hàng của các đơn trả hàng đặt trong kỳ",
        ["Tiền hàng bị trả tháng {m}/{y} là bao nhiêu?", "tien hang bi tra thang {m}/{y} bn", "tháng {m} năm {y} tiền hàng bị trả hết nhiêu"], "number", g3_tien_tra),
    Row("chi_khach", "**Chi tiêu bình quân khách** là doanh thu (§1) của các đơn có khách chia cho số khách có đơn trong kỳ, không tính khách lẻ; làm tròn về đồng",
        ["Chi tiêu bình quân khách tháng {m}/{y} là bao nhiêu?", "chi tieu binh quan khach thang {m}/{y} bn", "tháng {m} năm {y} chi tiêu bình quân khách được bao nhiêu"], "number", g3_chi_khach),
    Row("ncc_phieu", "**Nhà cung cấp năng nổ** của tháng là nhà cung cấp có nhiều phiếu nhập không huỷ nhất trong tháng, không xét số tiền",
        ["Nhà cung cấp năng nổ của tháng {m}/{y} là ai?", "ncc nang no thang {m}/{y} la ai", "tháng {m} năm {y} nhà cung cấp năng nổ là bên nào"], "string", g3_ncc_phieu),
    Row("tong_chi", "**Tổng chi** của tháng là tổng mọi khoản ghi trong sổ chi phí có ngày chi trong tháng",
        ["Tổng chi tháng {m}/{y} là bao nhiêu?", "tong chi thang {m}/{y} bn", "tháng {m} năm {y} tổng chi hết bao nhiêu tiền"], "number", g3_tong_chi),
    Row("ti_le_chi", "**Tỉ lệ chi** của tháng là phần trăm tổng chi trên doanh thu (§1) của cùng tháng",
        ["Tỉ lệ chi tháng {m}/{y} là bao nhiêu %?", "ti le chi thang {m}/{y} bn %", "tháng {m} năm {y} tỉ lệ chi là mấy phần trăm"], "percent", g3_ti_le_chi),
    Row("sap_het", "**Hàng sắp hết** tại một ngày là mặt hàng còn tồn lớn hơn 0 và dưới 5 đơn vị cơ bản lúc hết ngày đó",
        ["Đến hết tháng {m}/{y} có bao nhiêu hàng sắp hết?", "den het thang {m}/{y} co may hang sap het", "tính đến cuối tháng {m} năm {y} số hàng sắp hết là bn"], "number", g3_sap_het),
    Row("no_tb", "**Nợ bình quân đơn** tại một ngày là tổng còn nợ (§4) chia cho số đơn còn nợ tại ngày đó; làm tròn về đồng",
        ["Đến hết tháng {m}/{y} nợ bình quân đơn là bao nhiêu?", "den het thang {m}/{y} no binh quan don bn", "tính đến cuối tháng {m} năm {y} nợ bình quân đơn được bao nhiêu"], "number", g3_no_tb),
    Row("nang_suat", "**Năng suất bán** là số đơn §1 của kỳ chia cho số nhân viên có đơn trong kỳ; làm tròn 2 chữ số",
        ["Năng suất bán tháng {m}/{y} là bao nhiêu?", "nang suat ban thang {m}/{y} bn", "tháng {m} năm {y} năng suất bán được mấy"], "number", g3_nang_suat),
    Row("ba_khach", "**Ba khách ruột** của tháng là 3 khách có nhiều đơn §1 nhất tháng, xếp từ nhiều xuống ít",
        ["Ba khách ruột của tháng {m}/{y} là ai?", "ba khach ruot thang {m}/{y} la ai", "liệt kê ba khách ruột tháng {m} năm {y}"], "list", g3_ba_khach),
    Row("ban", "**Bàn đắt khách** của tháng là số bàn có nhiều đơn §1 nhất, theo số bàn ghi cho từng đơn",
        ["Bàn đắt khách của tháng {m}/{y} là bàn nào?", "ban dat khach thang {m}/{y} la ban nao", "tháng {m} năm {y} bàn đắt khách là bàn số mấy"], "string", g3_ban),
    Row("han_no", "**Hạn nợ bình quân** là trung bình số ngày cho nợ ghi ở sổ công nợ, của các đơn §1 đặt trong kỳ; làm tròn 2 chữ số",
        ["Hạn nợ bình quân tháng {m}/{y} là bao nhiêu ngày?", "han no binh quan thang {m}/{y} bn ngay", "tháng {m} năm {y} hạn nợ bình quân mấy ngày"], "number", g3_han_no),
    Row("danh_muc", "**Độ rộng danh mục** là số nhóm hàng khác nhau trong danh mục hàng",
        ["Độ rộng danh mục là bao nhiêu?", "do rong danh muc bn", "danh mục của shop có độ rộng danh mục bao nhiêu"], "number", g3_danh_muc),
    Row("khach_dk", "**Khách mới đăng ký** của tháng là khách trong danh sách khách có ngày tạo rơi vào tháng đó",
        ["Tháng {m}/{y} có bao nhiêu khách mới đăng ký?", "thang {m}/{y} co may khach moi dang ky", "số khách mới đăng ký tháng {m} năm {y}"], "number", g3_khach_dk),
    Row("giam_don", "**Tiền giảm cả đơn** của tháng là tổng giảm giá trên cả đơn của các đơn §1 đặt trong tháng",
        ["Tiền giảm cả đơn tháng {m}/{y} là bao nhiêu?", "tien giam ca don thang {m}/{y} bn", "tháng {m} năm {y} tiền giảm cả đơn hết bao nhiêu"], "number", g3_giam_don),
    Row("ht_thu", "**Hình thức thu chính** của tháng là hình thức có tổng tiền thu cao nhất trong sổ thu, theo ngày thu",
        ["Hình thức thu chính của tháng {m}/{y} là gì?", "hinh thuc thu chinh thang {m}/{y} la gi", "tháng {m} năm {y} hình thức thu chính là hình thức nào"], "string", g3_ht_thu),
    Row("doi_gia", "**Số lần đổi giá** của tháng là số dòng trong lịch sử giá có ngày hiệu lực trong tháng",
        ["Số lần đổi giá tháng {m}/{y} là bao nhiêu?", "so lan doi gia thang {m}/{y} bn", "tháng {m} năm {y} đổi giá mấy lần"], "number", g3_doi_gia),
]


# ---------------------------------------------------------------- bộ 4 (R4): viết 2026-11-02 sau khi đã chốt cách làm, để đo lần cuối

def _prev(m, y):
    idx = y * 12 + m - 2
    return idx % 12 + 1, idx // 12


def _of(c, name) -> str:
    return f"""hang IN (SELECT hang FROM "{c.D}" WHERE ten_hang = '{name.replace("'", "''")}')"""


def g4_don_si(c, m, y, _):
    c.need(c.D, "sl_co_ban")
    return c.one(f"""SELECT COUNT(*) FROM (SELECT don FROM "{c.D}" WHERE hop_le AND la_mat_hang AND thang = '{_month(m, y)}'
        GROUP BY don HAVING SUM(sl_co_ban) >= 20)""")


def g4_trung_vi(c, m, y, _):
    return _money(c.one(f"""SELECT MEDIAN(dt) FROM (SELECT SUM(tien) dt FROM "{c.D}" WHERE hop_le AND thang = '{_month(m, y)}' GROUP BY don)"""))


def g4_don_gian(c, m, y, _):
    return c.one(f"""SELECT COUNT(*) FROM (SELECT don FROM "{c.D}" WHERE hop_le AND la_mat_hang AND thang = '{_month(m, y)}'
        GROUP BY don HAVING COUNT(DISTINCT hang) = 1)""")


def g4_tuan_chot(c, m, y, _):
    end = _month_end(y, m)
    return _money(c.one(f"SELECT SUM(tien) FROM \"{c.D}\" WHERE hop_le AND ngay BETWEEN DATE '{end - dt.timedelta(days=6)}' AND DATE '{end}'"))


def g4_khach_roi(c, m, y, _):
    c.need(c.D, "khach")
    pm, py = _prev(m, y)
    return c.one(f"""SELECT COUNT(*) FROM (SELECT DISTINCT khach FROM "{c.D}" WHERE hop_le AND khach IS NOT NULL AND thang = '{_month(pm, py)}'
        EXCEPT SELECT DISTINCT khach FROM "{c.D}" WHERE hop_le AND khach IS NOT NULL AND thang = '{_month(m, y)}')""")


def g4_hang_ngung(c, m, y, _):
    pm, py = _prev(m, y)
    return c.one(f"""SELECT COUNT(*) FROM (SELECT DISTINCT hang FROM "{c.D}" WHERE hop_le AND la_mat_hang AND hang IS NOT NULL
        AND thang = '{_month(pm, py)}' EXCEPT SELECT DISTINCT hang FROM "{c.D}" WHERE hop_le AND la_mat_hang AND hang IS NOT NULL
        AND thang = '{_month(m, y)}')""")


def g4_ngay_co_hang(c, m, y, name):
    return c.one(f"SELECT COUNT(DISTINCT ngay) FROM \"{c.D}\" WHERE hop_le AND thang = '{_month(m, y)}' AND {_of(c, name)}")


def g4_gia_tran(c, m, y, name):
    c.need(c.D, "don_gia")
    return _money(c.one(f"SELECT MAX(don_gia) FROM \"{c.D}\" WHERE hop_le AND thang = '{_month(m, y)}' AND {_of(c, name)}"))


def g4_nv_don_to(c, m, y, _):
    c.need(c.D, "nhan_vien")
    return _top1(c, f"""SELECT nhan_vien, SUM(tien) / COUNT(DISTINCT don) FROM "{c.D}" WHERE hop_le AND nhan_vien IS NOT NULL
        AND thang = '{_month(m, y)}' GROUP BY 1 HAVING COUNT(DISTINCT don) >= 10""")


def g4_khach_sieng(c, m, y, _):
    c.need(c.D, "khach")
    k = _top1(c, f"SELECT khach, COUNT(DISTINCT ngay) FROM \"{c.D}\" WHERE hop_le AND khach IS NOT NULL AND thang = '{_month(m, y)}' GROUP BY 1")
    return _named(c, c.D, "ten_khach", "khach", k)


def g4_mon_loi(c, m, y, _):
    c.need(c.D, "gia_von")
    k = _top1(c, f"""SELECT hang, SUM(lai) FROM "{c.D}" WHERE hop_le AND la_mat_hang AND hang IS NOT NULL AND lai IS NOT NULL
        AND thang = '{_month(m, y)}' GROUP BY 1""")
    return _named(c, c.D, "ten_hang", "hang", k)


def g4_ngay_vang(c, m, y, _):
    return _day(_top1(c, f"SELECT ngay, COUNT(DISTINCT don) FROM \"{c.D}\" WHERE hop_le AND thang = '{_month(m, y)}' GROUP BY 1"))


def g4_hai_mon(c, m, y, _):
    keys = _top_k(c, f"""SELECT hang, SUM(tien) FROM "{c.D}" WHERE hop_le AND la_mat_hang AND hang IS NOT NULL AND thang = '{_month(m, y)}'
        GROUP BY 1""", 2)
    return [_named(c, c.D, "ten_hang", "hang", k) for k in keys]


def g4_vuot_nam(c, m, y, _):
    a = c.one(f"SELECT SUM(tien) FROM \"{c.D}\" WHERE hop_le AND thang = '{_month(m, y)}'")
    b = c.one(f"SELECT SUM(tien) FROM \"{c.D}\" WHERE hop_le AND thang = '{_month(m, y - 1)}'")
    if a is None or b is None:
        raise Skip
    return bool(a > b)


def g4_don_khung(c, m, y, _):
    v = c.one(f"SELECT MAX(dt) FROM (SELECT SUM(tien) dt FROM \"{c.D}\" WHERE hop_le AND thang = '{_month(m, y)}' GROUP BY don)")
    if v is None:
        raise Skip
    return bool(v >= 5000000)


def g4_nhap_tb(c, m, y, _):
    t = _fact(c, "phieu_nhap")
    return _money(c.one(f"SELECT SUM(tong_tien) / COUNT(*) FROM \"{t}\" WHERE strftime(ngay, '%Y-%m') = '{_month(m, y)}'"))


def g4_nhap_ban(c, m, y, _):
    t = _fact(c, "phieu_nhap")
    a = c.one(f"SELECT SUM(tong_tien) FROM \"{t}\" WHERE strftime(ngay, '%Y-%m') = '{_month(m, y)}'")
    b = c.one(f"SELECT SUM(tien) FROM \"{c.D}\" WHERE hop_le AND thang = '{_month(m, y)}'")
    if not a or not b:
        raise Skip
    return _pct(100.0 * a / b)


def g4_chi_ngay(c, m, y, _):
    t = _fact(c, "khoan_chi")
    v = c.one(f"SELECT SUM(tien) FROM \"{t}\" WHERE strftime(ngay, '%Y-%m') = '{_month(m, y)}'")
    if v is None:
        raise Skip
    return _money(v / _month_end(y, m).day)


def g4_online(c, m, y, _):
    c.need(c.D, "kenh")
    return _money(c.one(f"""SELECT SUM(tien) FROM "{c.D}" WHERE hop_le AND kenh IS NOT NULL AND kenh <> 'tai_quay'
        AND thang = '{_month(m, y)}'"""))


def g4_kenh_manh(c, m, y, _):
    c.need(c.D, "kenh")
    return _top1(c, f"SELECT kenh, COUNT(DISTINCT don) FROM \"{c.D}\" WHERE hop_le AND kenh IS NOT NULL AND thang = '{_month(m, y)}' GROUP BY 1")


def g4_dong_tb(c, m, y, _):
    return _money(c.one(f"SELECT SUM(tien) / COUNT(*) FROM \"{c.D}\" WHERE hop_le AND la_mat_hang AND thang = '{_month(m, y)}'"))


def g4_len_ke(c, m, y, name):
    return _day(c.one(f"SELECT MIN(ngay) FROM \"{c.D}\" WHERE hop_le AND {_of(c, name)}"))


def g4_tt_dau(c, m, y, _):
    rows = c.con.execute(f"""SELECT SUM(tien) s FROM "{c.D}" WHERE hop_le AND la_mat_hang AND hang IS NOT NULL AND thang = '{_month(m, y)}'
        GROUP BY hang ORDER BY s DESC LIMIT 2""").fetchall()
    total = c.one(f"SELECT SUM(tien) FROM \"{c.D}\" WHERE hop_le AND thang = '{_month(m, y)}'")
    if len(rows) < 2 or rows[0][0] == rows[1][0] or not total:
        raise Skip
    return _pct(100.0 * rows[0][0] / total)


def g4_dong_giam(c, m, y, _):
    c.need(c.D, "giam_dong")
    return _pct(c.one(f"""SELECT 100.0 * COUNT(*) FILTER (WHERE giam_dong > 0) / COUNT(*) FROM "{c.D}" WHERE hop_le AND la_mat_hang
        AND thang = '{_month(m, y)}'"""))


ROWS4 = [
    Row("don_si", "**Đơn sỉ** là đơn §1 có tổng số lượng quy về đơn vị cơ bản của các dòng mặt hàng từ 20 trở lên",
        ["Tháng {m}/{y} có bao nhiêu đơn sỉ?", "thang {m}/{y} co may don si", "đếm giúp số đơn sỉ trong tháng {m} năm {y}"], "number", g4_don_si),
    Row("trung_vi", "**Đơn trung vị** của kỳ là doanh thu đơn đứng giữa khi xếp các đơn §1 theo doanh thu; số đơn chẵn thì lấy trung bình hai đơn giữa, làm tròn về đồng",
        ["Đơn trung vị của tháng {m}/{y} là bao nhiêu tiền?", "don trung vi thang {m}/{y} bn", "tháng {m} năm {y} đơn trung vị được bao nhiêu"], "number", g4_trung_vi),
    Row("don_gian", "**Đơn gọn** là đơn §1 chỉ gồm đúng một mặt hàng (không tính dòng phí)",
        ["Tháng {m}/{y} có bao nhiêu đơn gọn?", "thang {m}/{y} co bn don gon", "số đơn gọn của tháng {m} năm {y} là mấy"], "number", g4_don_gian),
    Row("tuan_chot", "**Doanh thu tuần chót** của tháng là doanh thu (§1) của 7 ngày cuối tháng, tính lùi từ ngày cuối tháng",
        ["Doanh thu tuần chót của tháng {m}/{y} là bao nhiêu?", "dthu tuan chot thang {m}/{y} bn", "tháng {m} năm {y} tuần chót bán được bao nhiêu tiền"], "number", g4_tuan_chot),
    Row("khach_roi", "**Khách rời** của tháng là khách có đơn §1 trong tháng liền trước nhưng không có đơn §1 nào trong tháng đó",
        ["Tháng {m}/{y} có bao nhiêu khách rời?", "thang {m}/{y} co may khach roi", "đếm số khách rời của tháng {m} năm {y}"], "number", g4_khach_roi),
    Row("hang_ngung", "**Hàng ngưng** của tháng là mặt hàng có trong đơn §1 của tháng liền trước nhưng không có trong đơn §1 nào của tháng đó",
        ["Tháng {m}/{y} có mấy hàng ngưng?", "thang {m}/{y} co bao nhieu hang ngung", "số hàng ngưng của tháng {m} năm {y} là bn"], "number", g4_hang_ngung),
    Row("ngay_co_hang", "**Số ngày có hàng** của một mặt hàng trong tháng là số ngày có ít nhất một đơn §1 chứa mặt hàng đó",
        ["Tháng {m}/{y} {name} có bao nhiêu ngày có hàng?", "so ngay co hang cua {name} thang {m}/{y}", "{name} tháng {m} năm {y} được mấy ngày có hàng"], "number", g4_ngay_co_hang, p_hang),
    Row("gia_tran", "**Giá trần** của một mặt hàng trong tháng là đơn giá cao nhất ghi trên dòng bán của mặt hàng đó, trong các đơn §1 của tháng",
        ["Giá trần của {name} tháng {m}/{y} là bao nhiêu?", "gia tran {name} thang {m}/{y} bn", "tháng {m} năm {y} giá trần của {name} là mấy"], "number", g4_gia_tran, p_hang),
    Row("nv_don_to", "**Nhân viên đơn to** của tháng là nhân viên có doanh thu bình quân mỗi đơn §1 cao nhất, chỉ xét nhân viên có từ 10 đơn trong tháng",
        ["Nhân viên đơn to của tháng {m}/{y} là ai?", "nv don to thang {m}/{y} la ai", "tháng {m} năm {y} ai là nhân viên đơn to"], "string", g4_nv_don_to),
    Row("khach_sieng", "**Khách siêng ghé** của tháng là khách có nhiều ngày mua khác nhau nhất trong tháng (đơn §1), không tính khách lẻ",
        ["Khách siêng ghé tháng {m}/{y} là ai?", "khach sieng ghe thang {m}/{y} la ai", "tháng {m} năm {y} khách siêng ghé là người nào"], "string", g4_khach_sieng),
    Row("mon_loi", "**Món sinh lời** của tháng là mặt hàng có tổng lãi gộp (§5) cao nhất trong các đơn §1 của tháng",
        ["Món sinh lời của tháng {m}/{y} là gì?", "mon sinh loi thang {m}/{y} la mon nao", "tháng {m} năm {y} món sinh lời là món gì"], "string", g4_mon_loi),
    Row("ngay_vang", "**Ngày vàng** của tháng là ngày có nhiều đơn §1 nhất tháng",
        ["Ngày vàng của tháng {m}/{y} là ngày nào?", "ngay vang thang {m}/{y} la ngay may", "tháng {m} năm {y} ngày vàng là hôm nào"], "date", g4_ngay_vang),
    Row("hai_mon", "**Hai món đầu bảng** của tháng là 2 mặt hàng có doanh thu (§1) cao nhất tháng, xếp từ cao xuống thấp",
        ["Hai món đầu bảng tháng {m}/{y} là gì?", "hai mon dau bang thang {m}/{y} la mon nao", "liệt kê hai món đầu bảng của tháng {m} năm {y}"], "list", g4_hai_mon),
    Row("vuot_nam", "**Tháng vượt năm** là tháng có doanh thu (§1) cao hơn doanh thu cùng tháng của năm trước",
        ["Tháng {m}/{y} có phải tháng vượt năm không?", "thang {m}/{y} co phai thang vuot nam ko", "tháng {m} năm {y} có vượt năm không"], "boolean", g4_vuot_nam),
    Row("don_khung", "**Tháng có đơn khủng** là tháng có ít nhất một đơn §1 với doanh thu từ 5.000.000 đồng trở lên",
        ["Tháng {m}/{y} có đơn khủng không?", "thang {m}/{y} co don khung k", "tháng {m} năm {y} có phải tháng có đơn khủng không"], "boolean", g4_don_khung),
    Row("nhap_tb", "**Phiếu nhập bình quân** của tháng là tổng tiền các phiếu nhập không huỷ trong tháng chia cho số phiếu đó; làm tròn về đồng",
        ["Phiếu nhập bình quân tháng {m}/{y} là bao nhiêu?", "phieu nhap binh quan thang {m}/{y} bn", "tháng {m} năm {y} phiếu nhập bình quân được bao nhiêu tiền"], "number", g4_nhap_tb),
    Row("nhap_ban", "**Tỉ lệ nhập bán** của tháng là phần trăm tổng tiền phiếu nhập không huỷ của tháng trên doanh thu (§1) cùng tháng",
        ["Tỉ lệ nhập bán tháng {m}/{y} là bao nhiêu %?", "ti le nhap ban thang {m}/{y} bn %", "tháng {m} năm {y} tỉ lệ nhập bán mấy phần trăm"], "percent", g4_nhap_ban),
    Row("chi_ngay", "**Chi bình quân ngày** của tháng là tổng chi trong sổ chi phí của tháng chia cho số ngày dương lịch của tháng; làm tròn về đồng",
        ["Chi bình quân ngày tháng {m}/{y} là bao nhiêu?", "chi binh quan ngay thang {m}/{y} bn", "tháng {m} năm {y} chi bình quân ngày hết bao nhiêu"], "number", g4_chi_ngay),
    Row("online", "**Doanh thu online** là doanh thu (§1) của các đơn bán qua kênh khác bán tại quầy",
        ["Doanh thu online tháng {m}/{y} là bao nhiêu?", "dthu online thang {m}/{y} bn", "tháng {m} năm {y} bán online được bao nhiêu tiền"], "number", g4_online),
    Row("kenh_manh", "**Kênh mạnh** của tháng là kênh bán có nhiều đơn §1 nhất trong tháng",
        ["Kênh mạnh của tháng {m}/{y} là kênh nào?", "kenh manh thang {m}/{y} la kenh nao", "tháng {m} năm {y} kênh mạnh là kênh gì"], "string", g4_kenh_manh),
    Row("dong_tb", "**Giá trị dòng bình quân** là doanh thu (§1) của các dòng mặt hàng chia cho số dòng đó trong kỳ; làm tròn về đồng",
        ["Giá trị dòng bình quân tháng {m}/{y} là bao nhiêu?", "gia tri dong binh quan thang {m}/{y} bn", "tháng {m} năm {y} giá trị dòng bình quân được mấy"], "number", g4_dong_tb),
    Row("len_ke", "**Ngày lên kệ** của một mặt hàng là ngày đầu tiên trong dữ liệu có đơn §1 chứa mặt hàng đó",
        ["Ngày lên kệ của {name} là ngày nào?", "ngay len ke cua {name} la ngay may", "{name} lên kệ từ ngày nào"], "date", g4_len_ke, p_hang),
    Row("tt_dau", "**Tỉ trọng món đầu** của tháng là phần trăm doanh thu của mặt hàng có doanh thu (§1) cao nhất tháng trong doanh thu cả tháng",
        ["Tỉ trọng món đầu tháng {m}/{y} là bao nhiêu %?", "ti trong mon dau thang {m}/{y} bn %", "tháng {m} năm {y} tỉ trọng món đầu mấy phần trăm"], "percent", g4_tt_dau),
    Row("dong_giam", "**Tỉ lệ dòng có giảm** là phần trăm số dòng mặt hàng có giảm giá trên dòng lớn hơn 0, trong mọi dòng mặt hàng của các đơn §1 trong kỳ",
        ["Tỉ lệ dòng có giảm tháng {m}/{y} là bao nhiêu %?", "ti le dong co giam thang {m}/{y} bn %", "tháng {m} năm {y} tỉ lệ dòng có giảm mấy phần trăm"], "percent", g4_dong_giam),
]


# ---------------------------------------------------------------- bộ R5 (viết 2026-11-03, sau khi R4 thành bộ thiết kế: bộ đo mới)

def _end(m, y) -> dt.date:
    return _month_end(y, m)


def p_nhom(c, m, y):
    c.need(c.D, "nhom_hang")
    rows = c.con.execute(f"""SELECT nhom_hang FROM "{c.D}" WHERE hop_le AND nhom_hang IS NOT NULL AND thang = '{_month(m, y)}'
        GROUP BY 1 ORDER BY SUM(tien) DESC, 1 LIMIT 6""").fetchall()
    if len(rows) < 2:
        raise Skip
    return rows[(m + y) % len(rows)][0]


def g5_don_a_quan(c, m, y, _):
    rows = c.con.execute(f"""SELECT SUM(tien) s FROM "{c.D}" WHERE hop_le AND thang = '{_month(m, y)}' GROUP BY don
        ORDER BY s DESC LIMIT 2""").fetchall()
    if len(rows) < 2 or rows[0][0] == rows[1][0]:
        raise Skip
    return _money(rows[1][0])


def g5_khach_quen(c, m, y, _):
    c.need(c.D, "khach")
    return c.one(f"""SELECT COUNT(*) FROM (SELECT khach FROM "{c.D}" WHERE hop_le AND khach IS NOT NULL AND thang = '{_month(m, y)}'
        GROUP BY khach HAVING COUNT(DISTINCT don) >= 2)""")


def g5_mon_ben(c, m, y, _):
    k = _top1(c, f"""SELECT hang, COUNT(DISTINCT ngay) FROM "{c.D}" WHERE hop_le AND la_mat_hang AND hang IS NOT NULL
        AND thang = '{_month(m, y)}' GROUP BY 1""")
    return _named(c, c.D, "ten_hang", "hang", k)


def g5_khung_gio(c, m, y, _):
    c.need(c.D, "gio")
    return c.one(f"SELECT COUNT(DISTINCT gio) FROM \"{c.D}\" WHERE hop_le AND gio IS NOT NULL AND thang = '{_month(m, y)}'")


def g5_bien_gia(c, m, y, name):
    c.need(c.D, "don_gia")
    v = c.one(f"SELECT MAX(don_gia) - MIN(don_gia) FROM \"{c.D}\" WHERE hop_le AND thang = '{_month(m, y)}' AND {_of(c, name)}")
    if not v:
        raise Skip
    return _money(v)


def g5_suc_ban(c, m, y, name):
    v = c.one(f"SELECT SUM(sl_co_ban) FROM \"{c.D}\" WHERE hop_le AND thang = '{_month(m, y)}' AND {_of(c, name)}")
    if not v:
        raise Skip
    return round(float(v) / _end(m, y).day, 2)


def g5_tt_nhom(c, m, y, name):
    a = c.one(f"""SELECT SUM(tien) FROM "{c.D}" WHERE hop_le AND thang = '{_month(m, y)}' AND nhom_hang = '{name.replace("'", "''")}'""")
    b = c.one(f"SELECT SUM(tien) FROM \"{c.D}\" WHERE hop_le AND thang = '{_month(m, y)}'")
    if not a or not b:
        raise Skip
    return _pct(100.0 * a / b)


def g5_tang_cung_ky(c, m, y, _):
    a = c.one(f"SELECT COUNT(DISTINCT don) FROM \"{c.D}\" WHERE hop_le AND thang = '{_month(m, y)}'")
    b = c.one(f"SELECT COUNT(DISTINCT don) FROM \"{c.D}\" WHERE hop_le AND thang = '{_month(m, y - 1)}'")
    if not a or not b:
        raise Skip
    return _pct(100.0 * (a - b) / b)


def g5_huy_troi(c, m, y, _):
    huy = c.one(f"SELECT COUNT(DISTINCT don) FROM \"{c.O}\" WHERE trang_thai = 'huy' AND thang = '{_month(m, y)}'")
    tra = c.one(f"SELECT COUNT(DISTINCT don) FROM \"{c.O}\" WHERE trang_thai = 'tra_hang' AND thang = '{_month(m, y)}'")
    if not huy and not tra:
        raise Skip
    return bool(huy > tra)


def g5_ngay_vang_ve(c, m, y, _):
    rows = c.con.execute(f"""SELECT ngay, COUNT(DISTINCT don) n FROM "{c.D}" WHERE hop_le AND thang = '{_month(m, y)}' GROUP BY 1
        ORDER BY n, 1 LIMIT 2""").fetchall()
    if len(rows) < 2 or rows[0][1] == rows[1][1]:
        raise Skip
    return _day(rows[0][0])


def g5_bo_ba_nv(c, m, y, _):
    c.need(c.D, "nhan_vien")
    keys = _top_k(c, f"""SELECT nhan_vien, COUNT(DISTINCT don) FROM "{c.D}" WHERE hop_le AND nhan_vien IS NOT NULL
        AND thang = '{_month(m, y)}' GROUP BY 1""", 3)
    return [_named(c, c.D, "nhan_vien", "nhan_vien", k) for k in keys]


def g5_ngay_nhap_don(c, m, y, _):
    t = _fact(c, "phieu_nhap")
    return _day(_top1(c, f"SELECT ngay, SUM(tong_tien) FROM \"{t}\" WHERE strftime(ngay, '%Y-%m') = '{_month(m, y)}' GROUP BY 1"))


def g5_chi_lon(c, m, y, _):
    t = _fact(c, "khoan_chi")
    return _money(c.one(f"SELECT MAX(tien) FROM \"{t}\" WHERE strftime(ngay, '%Y-%m') = '{_month(m, y)}'"))


def g5_dot_tb(c, m, y, _):
    t = _fact(c, "dot_giao")
    v = c.con.execute(f"""SELECT COUNT(*), COUNT(DISTINCT don) FROM "{t}" WHERE strftime(ngay, '%Y-%m') = '{_month(m, y)}'""").fetchone()
    if not v[1]:
        raise Skip
    return round(v[0] / v[1], 2)


def g5_no_dai(c, m, y, _):
    t = _fact(c, "cong_no", at=_end(m, y))
    c.need(t, "khach")
    k = _top1(c, f'SELECT khach, MAX(tuoi_no) FROM "{t}" WHERE khach IS NOT NULL GROUP BY 1')
    return _named(c, t, "ten_khach", "khach", k)


def g5_bien_lai(c, m, y, _):
    c.need(c.D, "gia_von")
    a, b, thieu = c.con.execute(f"""SELECT SUM(lai), SUM(tien), COUNT(*) FILTER (WHERE lai IS NULL) FROM "{c.D}"
        WHERE hop_le AND la_mat_hang AND thang = '{_month(m, y)}'""").fetchone()
    if a is None or not b or thieu:       # dòng hàng không có giá vốn: đáp án không rõ, bỏ câu
        raise Skip
    return _pct(100.0 * a / b)


def g5_chuoi_ngay(c, m, y, _):
    days = sorted(d for d, in c.con.execute(f"SELECT DISTINCT ngay FROM \"{c.D}\" WHERE hop_le AND thang = '{_month(m, y)}'").fetchall())
    if not days:
        raise Skip
    best = run = 1
    for a, b in zip(days, days[1:]):
        run = run + 1 if (b - a).days == 1 else 1
        best = max(best, run)
    return best


def g5_qua_nua(c, m, y, _):
    rows = c.con.execute(f"SELECT ngay, SUM(tien) FROM \"{c.D}\" WHERE hop_le AND thang = '{_month(m, y)}' GROUP BY 1 ORDER BY 1").fetchall()
    total = sum(float(v) for _, v in rows)
    if not total:
        raise Skip
    acc = 0.0
    for d, v in rows:
        acc += float(v)
        if acc >= total / 2:
            return _day(d)
    raise Skip


def g5_bung_no(c, m, y, _):
    v = c.one(f"""SELECT MAX(s) FROM (SELECT SUM(sl_co_ban) s FROM "{c.D}" WHERE hop_le AND la_mat_hang AND hang IS NOT NULL
        AND thang = '{_month(m, y)}' GROUP BY hang)""")
    if v is None:
        raise Skip
    return bool(v >= 100)


def g5_ba_ngay_tram(c, m, y, _):
    rows = c.con.execute(f"""SELECT ngay, SUM(tien) s FROM "{c.D}" WHERE hop_le AND thang = '{_month(m, y)}' GROUP BY 1
        ORDER BY s, 1 LIMIT 4""").fetchall()
    vals = [r[1] for r in rows]
    if len(rows) < 4 or len(set(vals)) < 4:
        raise Skip
    return [_day(r[0]) for r in rows[:3]]


def g5_khach_lon(c, m, y, _):
    c.need(c.D, "khach")
    rows = c.con.execute(f"""SELECT khach, SUM(tien) s FROM "{c.D}" WHERE hop_le AND thang = '{_month(m, y)}' GROUP BY don, khach
        ORDER BY s DESC LIMIT 2""").fetchall()
    if len(rows) < 2 or rows[0][1] == rows[1][1] or rows[0][0] is None:
        raise Skip
    return _named(c, c.D, "ten_khach", "khach", rows[0][0])


def g5_bang_nv(c, m, y, _):
    c.need(c.D, "nhan_vien")
    rows = c.con.execute(f"""SELECT nhan_vien, COUNT(DISTINCT don) FROM "{c.D}" WHERE hop_le AND nhan_vien IS NOT NULL
        AND thang = '{_month(m, y)}' GROUP BY 1 ORDER BY 2 DESC, 1""").fetchall()
    if len(rows) < 2:
        raise Skip
    return {"columns": ["nhan_vien", "so_don"], "rows": [[_named(c, c.D, "nhan_vien", "nhan_vien", k), v] for k, v in rows]}


def g5_don_dau_tuan(c, m, y, _):
    return c.one(f"SELECT COUNT(DISTINCT don) FROM \"{c.D}\" WHERE hop_le AND thang = '{_month(m, y)}' AND dayofweek(ngay) = 1")


def g5_ngay_tren_tb(c, m, y, _):
    return c.one(f"""SELECT COUNT(*) FROM (SELECT ngay, SUM(tien) s FROM "{c.D}" WHERE hop_le AND thang = '{_month(m, y)}' GROUP BY 1)
        WHERE s > (SELECT AVG(s) FROM (SELECT SUM(tien) s FROM "{c.D}" WHERE hop_le AND thang = '{_month(m, y)}' GROUP BY ngay))""")


ROWS5 = [
    Row("don_a_quan", "**Đơn á quân** của tháng là doanh thu của đơn §1 lớn thứ hai trong tháng (xếp theo doanh thu đơn)",
        ["Đơn á quân của tháng {m}/{y} là bao nhiêu tiền?", "don a quan thang {m}/{y} bn", "tháng {m} năm {y} đơn á quân được bao nhiêu"], "number", g5_don_a_quan),
    Row("khach_quen", "**Khách quen tháng** là khách có từ 2 đơn §1 trở lên trong tháng, không tính khách lẻ",
        ["Tháng {m}/{y} có bao nhiêu khách quen tháng?", "thang {m}/{y} co may khach quen thang", "đếm khách quen tháng của tháng {m} năm {y}"], "number", g5_khach_quen),
    Row("mon_ben", "**Món bền bỉ** của tháng là mặt hàng có mặt trong nhiều ngày bán nhất tháng (đếm số ngày có đơn §1 chứa mặt hàng)",
        ["Món bền bỉ của tháng {m}/{y} là gì?", "mon ben bi thang {m}/{y} la mon nao", "tháng {m} năm {y} món nào là món bền bỉ"], "string", g5_mon_ben),
    Row("khung_gio", "**Số khung giờ hoạt động** của tháng là số giờ khác nhau (theo giờ tạo đơn) có ít nhất một đơn §1 trong tháng",
        ["Tháng {m}/{y} có bao nhiêu khung giờ hoạt động?", "so khung gio hoat dong thang {m}/{y}", "tháng {m} năm {y} số khung giờ hoạt động là mấy"], "number", g5_khung_gio),
    Row("bien_gia", "**Biên giá** của một mặt hàng trong tháng là đơn giá cao nhất trừ đơn giá thấp nhất ghi trên dòng bán của mặt hàng đó, trong các đơn §1 của tháng",
        ["Biên giá của {name} tháng {m}/{y} là bao nhiêu?", "bien gia {name} thang {m}/{y} bn", "tháng {m} năm {y} {name} có biên giá bao nhiêu"], "number", g5_bien_gia, p_hang),
    Row("suc_ban", "**Sức bán ngày** của một mặt hàng trong tháng là tổng số lượng quy về đơn vị cơ bản của mặt hàng đó trong các đơn §1 của tháng chia cho số ngày dương lịch của tháng; làm tròn 2 chữ số",
        ["Sức bán ngày của {name} tháng {m}/{y} là bao nhiêu?", "suc ban ngay cua {name} thang {m}/{y}", "{name} tháng {m} năm {y} sức bán ngày được mấy"], "number", g5_suc_ban, p_hang),
    Row("tt_nhom", "**Tỉ trọng nhóm** của một nhóm hàng trong tháng là phần trăm doanh thu (§1) của nhóm đó trong doanh thu cả tháng",
        ["Tỉ trọng nhóm {name} tháng {m}/{y} là bao nhiêu %?", "ti trong nhom {name} thang {m}/{y} bn %", "tháng {m} năm {y} nhóm {name} chiếm tỉ trọng nhóm mấy phần trăm"], "percent", g5_tt_nhom, p_nhom),
    Row("tang_cung_ky", "**Tăng trưởng đơn cùng kỳ** của tháng là phần trăm thay đổi số đơn §1 của tháng so với cùng tháng năm trước; giảm thì ra số âm",
        ["Tăng trưởng đơn cùng kỳ của tháng {m}/{y} là bao nhiêu %?", "tang truong don cung ky thang {m}/{y} bn %", "tháng {m} năm {y} tăng trưởng đơn cùng kỳ mấy phần trăm"], "percent", g5_tang_cung_ky),
    Row("huy_troi", "**Tháng huỷ trội** là tháng có số đơn huỷ nhiều hơn số đơn trả hàng (đếm theo ngày đặt)",
        ["Tháng {m}/{y} có phải tháng huỷ trội không?", "thang {m}/{y} co phai thang huy troi ko", "tháng {m} năm {y} có huỷ trội không"], "boolean", g5_huy_troi),
    Row("ngay_vang_ve", "**Ngày vắng nhất** của tháng là ngày có ít đơn §1 nhất trong các ngày có đơn của tháng",
        ["Ngày vắng nhất của tháng {m}/{y} là ngày nào?", "ngay vang nhat thang {m}/{y} la ngay may", "tháng {m} năm {y} ngày vắng nhất là hôm nào"], "date", g5_ngay_vang_ve),
    Row("bo_ba_nv", "**Bộ ba bán hàng** của tháng là 3 nhân viên có nhiều đơn §1 nhất tháng, xếp từ nhiều xuống ít",
        ["Bộ ba bán hàng của tháng {m}/{y} là những ai?", "bo ba ban hang thang {m}/{y} la ai", "liệt kê bộ ba bán hàng tháng {m} năm {y}"], "list", g5_bo_ba_nv),
    Row("ngay_nhap_don", "**Ngày nhập dồn** của tháng là ngày có tổng tiền phiếu nhập không huỷ cao nhất trong tháng",
        ["Ngày nhập dồn của tháng {m}/{y} là ngày nào?", "ngay nhap don thang {m}/{y} la ngay may", "tháng {m} năm {y} ngày nhập dồn là hôm nào"], "date", g5_ngay_nhap_don),
    Row("chi_lon", "**Khoản chi lớn nhất** của tháng là số tiền của một dòng chi lớn nhất trong sổ chi phí, theo ngày chi trong tháng",
        ["Khoản chi lớn nhất tháng {m}/{y} là bao nhiêu?", "khoan chi lon nhat thang {m}/{y} bn", "tháng {m} năm {y} khoản chi lớn nhất hết bao nhiêu tiền"], "number", g5_chi_lon),
    Row("dot_tb", "**Số đợt bình quân** của tháng là số đợt giao có ngày giao trong tháng chia cho số đơn khác nhau có đợt giao trong tháng; làm tròn 2 chữ số",
        ["Số đợt bình quân của tháng {m}/{y} là bao nhiêu?", "so dot binh quan thang {m}/{y} bn", "tháng {m} năm {y} số đợt bình quân được mấy"], "number", g5_dot_tb),
    Row("no_dai", "**Khách nợ dai** tại cuối tháng là khách có đơn còn nợ với tuổi nợ (§4) lớn nhất lúc hết ngày cuối tháng",
        ["Khách nợ dai cuối tháng {m}/{y} là ai?", "khach no dai cuoi thang {m}/{y} la ai", "cuối tháng {m} năm {y} ai là khách nợ dai"], "string", g5_no_dai),
    Row("bien_lai", "**Biên lãi hàng** của tháng là phần trăm tổng lãi gộp (§5) của các dòng mặt hàng trên doanh thu của chính các dòng mặt hàng đó, trong các đơn §1 của tháng",
        ["Biên lãi hàng tháng {m}/{y} là bao nhiêu %?", "bien lai hang thang {m}/{y} bn %", "tháng {m} năm {y} biên lãi hàng mấy phần trăm"], "percent", g5_bien_lai),
    Row("chuoi_ngay", "**Chuỗi ngày bán** của tháng là số ngày liên tiếp dài nhất trong tháng mà ngày nào cũng có đơn §1",
        ["Chuỗi ngày bán của tháng {m}/{y} dài bao nhiêu ngày?", "chuoi ngay ban thang {m}/{y} bn ngay", "tháng {m} năm {y} chuỗi ngày bán được mấy ngày"], "number", g5_chuoi_ngay),
    Row("qua_nua", "**Ngày qua nửa** của tháng là ngày sớm nhất trong tháng mà doanh thu (§1) cộng dồn từ ngày 1 đạt từ một nửa doanh thu cả tháng trở lên",
        ["Ngày qua nửa của tháng {m}/{y} là ngày nào?", "ngay qua nua thang {m}/{y} la ngay may", "tháng {m} năm {y} ngày qua nửa là hôm nào"], "date", g5_qua_nua),
    Row("bung_no", "**Tháng có món bùng nổ** là tháng có ít nhất một mặt hàng bán được từ 100 đơn vị cơ bản trở lên (đơn §1)",
        ["Tháng {m}/{y} có món bùng nổ không?", "thang {m}/{y} co mon bung no k", "tháng {m} năm {y} có phải tháng có món bùng nổ không"], "boolean", g5_bung_no),
    Row("ba_ngay_tram", "**Ba ngày trầm** của tháng là 3 ngày có doanh thu (§1) thấp nhất trong các ngày có đơn, xếp từ thấp lên cao",
        ["Ba ngày trầm của tháng {m}/{y} là những ngày nào?", "ba ngay tram thang {m}/{y} la ngay nao", "liệt kê ba ngày trầm tháng {m} năm {y}"], "list", g5_ba_ngay_tram),
    Row("khach_lon", "**Khách chơi lớn** của tháng là khách của đơn §1 có doanh thu cao nhất tháng; đơn đó của khách lẻ thì không có khách chơi lớn",
        ["Khách chơi lớn của tháng {m}/{y} là ai?", "khach choi lon thang {m}/{y} la ai", "tháng {m} năm {y} ai là khách chơi lớn"], "string", g5_khach_lon),
    Row("bang_nv", "**Bảng đơn nhân viên** của tháng là bảng số đơn §1 theo từng nhân viên, mỗi dòng một nhân viên",
        ["Cho xem bảng đơn nhân viên tháng {m}/{y}", "bang don nhan vien thang {m}/{y}", "lập bảng đơn nhân viên của tháng {m} năm {y}"], "table", g5_bang_nv),
    Row("don_dau_tuan", "**Đơn đầu tuần** là đơn §1 đặt vào thứ Hai",
        ["Tháng {m}/{y} có bao nhiêu đơn đầu tuần?", "thang {m}/{y} co may don dau tuan", "đếm đơn đầu tuần của tháng {m} năm {y}"], "number", g5_don_dau_tuan),
    Row("ngay_tren_tb", "**Ngày trên trung bình** của tháng là ngày có doanh thu (§1) cao hơn doanh thu bình quân mỗi ngày có đơn của tháng",
        ["Tháng {m}/{y} có bao nhiêu ngày trên trung bình?", "thang {m}/{y} co may ngay tren trung binh", "số ngày trên trung bình của tháng {m} năm {y} là bn"], "number", g5_ngay_tren_tb),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("train_root")
    ap.add_argument("db_root")
    ap.add_argument("out")
    ap.add_argument("--per-row", type=int, default=6)
    ap.add_argument("--seed", type=int, default=9)
    ap.add_argument("--bo", type=int, default=1, choices=[1, 2, 3, 4, 5], help="bộ dòng luật")
    a = ap.parse_args()
    rows = {1: ROWS, 2: ROWS2, 3: ROWS3, 4: ROWS4, 5: ROWS5}[a.bo]
    rng = random.Random(a.seed)
    qs = [json.loads(l) for l in open(os.path.join(a.train_root, "questions.jsonl"), encoding="utf-8")]
    dates: dict[str, list[str]] = {}
    for q in qs:
        if q["business_id"] not in HOLDOUT:
            dates.setdefault(q["business_id"], []).append(q["as_of_date"])
    shops = sorted(dates)
    ctxs: dict[str, Ctx] = {}

    def ctx(s):
        return ctxs.setdefault(s, Ctx(os.path.join(a.db_root, s, f"{s}.duckdb")))
    os.makedirs(a.out, exist_ok=True)
    out_q, out_a, meta = [], [], []
    with open(os.path.join(a.out, "luat.md"), "w", encoding="utf-8") as fh:
        fh.write("## 11. Luật bổ sung\n| Luật | Mặc định |\n|---|---|\n")
        for r in rows:
            name, _, rest = r.rule.partition("** ")
            fh.write(f"| {name.strip('*')} | {r.rule} |\n")
    for r in rows:
        order = shops[:]
        rng.shuffle(order)
        done, missing = 0, 0
        for s in order:
            if done >= a.per_row:
                break
            c = ctx(s)
            today = dt.date.fromisoformat(rng.choice(dates[s]))
            se = c.con.execute("SELECT CAST(sales_start AS DATE), CAST(sales_end AS DATE) FROM _meta_shop").fetchone()
            if not se[0] or not se[1]:
                continue
            months = [(d.month, d.year) for d in (dt.date(y, mm, 1) for y in range(se[0].year, se[1].year + 1) for mm in range(1, 13))
                      if d >= se[0].replace(day=1) and _month_end(d.year, d.month) < min(today, se[1])]
            if not months:
                continue
            m, y = rng.choice(months)
            try:
                name = r.pick(c, m, y) if r.pick else None
                v = r.gold(c, m, y, name)
                if v is None or (v == 0 and not isinstance(v, bool)):
                    continue
                g = {"type": r.kind, "answer": v}
            except Skip:
                continue
            except Missing as e:
                if missing >= 1:      # §7: giữ ít câu unanswerable, phần lớn câu phải trả lời được
                    continue
                missing += 1
                # đổi tên không có nghĩa khi thiếu dữ liệu: dòng có tên riêng thì bỏ qua
                if r.pick:
                    continue
                g = {"type": "unanswerable", "answer": None}
                name = None
            except duckdb.Error as e:
                print("gold lỗi", r.key, s, str(e)[:150])
                continue
            qid = f"r_{r.key}_{s}_{m}_{y}"
            ask = r.asks[done % len(r.asks)].format(m=m, y=y, name=name)
            out_q.append({"id": qid, "business_id": s, "question": ask, "as_of_date": today.isoformat()})
            out_a.append({"id": qid, **g})
            meta.append({"id": qid, "dong": r.key, "shop": s})
            done += 1
    for name, rows in (("questions", out_q), ("answers", out_a), ("meta", meta)):
        with open(os.path.join(a.out, f"{name}.jsonl"), "w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    print(len(out_q), "câu", dict(Counter(g["type"] for g in out_a).most_common()))


if __name__ == "__main__":
    main()
