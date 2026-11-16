"""Kho ví dụ "dòng luật -> kế hoạch" từ các dòng luật tự đặt (stress/new_rows.py): LLM thấy cách đọc một định nghĩa lạ.

Luật, câu hỏi đều tự đặt trên dữ liệu train; mỗi kế hoạch được chạy và so với đáp án SQL viết tay rồi mới vào kho.

    python -m datamate.stress.rule_bank ../train/train <DB> "../solve data/query/t9/r" --out "../solve data/query/examples_luat.jsonl"
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
from collections import Counter

from datamate.query.compose import ShopContext
from datamate.query.plan import MissingData, PlanError, Runner, _product_index, _q
from datamate.query.regress import check
from datamate.query.sql_tier import _attempt as sql_attempt, _prepare
from datamate.stress.new_rows import ROWS, ROWS2, ROWS3, ROWS4
from datamate.tests.verify_answers import _cols, _month_end, _tables, text_key

BIG = {"op": ">=", "gt": 300000}


def _raw(con, role, *cols):
    for t in _tables(con, role):
        if set(cols) <= _cols(con, t):
            return t
    raise MissingData("không có bảng")


def _birthday(con):
    for t in _tables(con, "customers"):
        for c in _cols(con, t):
            if c in ("Ngày sinh", "Sinh nhật", "ngay_sinh"):
                return t, c
    raise MissingData("không có ngày sinh")


def plan_of(con, key: str, m: int, y: int, name: str | None) -> dict:
    K = {"loai": "thang", "thang": m, "nam": y}
    D = {"nguon": "dong_ban"}
    prev = {"loai": "ky_truoc", "cua": K}
    REV = {**D, "phep": "tong", "cot": "tien", "ky": K}
    ORD = {**D, "phep": "dem_khac", "cot": "don", "ky": K}
    OK = [{"cot": "hop_le", "op": "=", "gt": True}]
    match key:
        case "don_lon":
            return {**D, "phep": "dem_nhom", "nhom": "don", "cot": "tien", "do": "tong", "ky": K, "co_dieu_kien": BIG}
        case "don_lon_tt":
            return {"ghep": "ti_le", "cac": [{**REV, "nhom": "don", "co_dieu_kien": BIG, "ngoai": "tong"}, REV]}
        case "dt_ngay":
            return {"ghep": "thuong", "tien": True, "cac": [REV, {**D, "phep": "dem_khac", "cot": "ngay", "ky": K}]}
        case "gio":
            return {**ORD, "nhom": "gio", "xep": {"chieu": "giam", "lay": 1}}
        case "thu":
            return {**ORD, "nhom": "thu", "xep": {"chieu": "giam", "lay": 1}}
        case "cuoi_tuan":
            return {**REV, "loc": [{"cot": "thu", "op": "in", "gt": [6, 7]}]}
        case "cuoi_tuan_tt":
            return {"ghep": "ti_le", "cac": [{**REV, "loc": [{"cot": "thu", "op": "in", "gt": [6, 7]}]}, REV]}
        case "gia_tb":
            fl = [{"cot": "hang", "op": "=", "gt": name}]
            return {"ghep": "thuong", "tien": True, "cac": [{**REV, "loc": fl}, {**D, "phep": "tong", "cot": "sl_co_ban", "ky": K, "loc": fl}]}
        case "khach_moi":
            return {**D, "phep": "dem_nhom", "nhom": "khach", "co_dieu_kien": {"do": "min", "cot": "ngay", "op": "trong_ky", "ky": K}}
        case "quay_lai":
            return {"ghep": "dem_giao", "cac": [{**D, "nhom": "khach", "ky": K}, {**D, "nhom": "khach", "ky": prev}]}
        case "chu_luc":
            return {**REV, "phep": "dem_nhom", "nhom": "hang", "do": "tong", "co_dieu_kien": {"op": ">=", "phan_tram_tong": 5}}
        case "don_max":
            return {**REV, "nhom": "don", "ngoai": "max"}
        case "ban_it":
            return {**D, "phep": "tong", "cot": "sl_co_ban", "ky": K, "nhom": "hang", "xep": {"chieu": "tang", "lay": 1}}
        case "nv":
            return {**ORD, "nhom": "nhan_vien", "xep": {"chieu": "giam", "lay": 1}}
        case "ghi_no":
            return {"ghep": "ti_le", "cac": [{**ORD, "loc": [{"cot": "thanh_toan", "op": "=", "gt": "ghi_no"}]}, ORD]}
        case "ti_le_tra":
            h = {"nguon": "don", "phep": "dem", "ky": K, "moi_trang_thai": True}
            return {"ghep": "ti_le", "cac": [{**h, "loc": [{"cot": "trang_thai", "op": "=", "gt": "tra_hang"}]}, h]}
        case "mat_huy":
            return {**REV, "moi_trang_thai": True, "loc": [{"cot": "trang_thai", "op": "=", "gt": "huy"}]}
        case "so_mon":
            hang = [{"cot": "la_mat_hang", "op": "=", "gt": True}]
            return {"ghep": "thuong", "cac": [{**D, "phep": "tong", "cot": "sl_co_ban", "ky": K, "loc": hang}, {**ORD, "loc": hang}]}
        case "ngay_trong":
            return {"ghep": "hieu", "cac": [{"phep": "so_ngay", "ky": K}, {**D, "phep": "dem_khac", "cot": "ngay", "ky": K}]}
        case "hang_moi":
            return {**D, "phep": "dem_nhom", "nhom": "hang", "co_dieu_kien": {"do": "min", "cot": "ngay", "op": "trong_ky", "ky": K}}
        case "nhieu_mon":
            return {**D, "phep": "dem_nhom", "nhom": "don", "cot": "hang", "ky": K, "loc": [{"cot": "la_mat_hang", "op": "=", "gt": True}],
                    "co_dieu_kien": {"op": ">=", "gt": 3}}
        case "khach_le":
            return {"ghep": "ti_le", "cac": [{**ORD, "loc": [{"cot": "khach_le", "op": "=", "gt": True}]}, ORD]}
        case "tai_xe":
            return {"nguon": "dot_giao", "phep": "dem", "ky": K, "nhom": "tai_xe", "xep": {"chieu": "giam", "lay": 1}}
        case "xe":
            return {"nguon": "dot_giao", "phep": "dem", "ky": K, "nhom": "bien_so", "xep": {"chieu": "giam", "lay": 1}}
        case "khu_vuc":
            return {"nguon": _raw(con, "order_info", "area", "order_id"), "phep": "tong", "cot": "doanh_thu_don", "cot_ngay": "ngay_don", "ky": K, "loc": OK,
                    "nhom": "area", "xep": {"chieu": "giam", "lay": 1}}
        case "khach_ban":
            return {"nguon": _raw(con, "order_info", "guests", "order_id"), "phep": "tb", "cot": "guests", "cot_ngay": "ngay_don", "ky": K, "loc": OK}
        case "phi_giao":
            return {"nguon": _raw(con, "orders", "shipping_fee", "order_id"), "phep": "tong", "cot": "shipping_fee", "cot_ngay": "ngay_don", "ky": K, "loc": OK}
        case "tien_thu":
            return {"nguon": _raw(con, "payments", "payment_amount", "payment_date"), "phep": "tong", "cot": "payment_amount", "cot_ngay": "payment_date", "ky": K}
        case "khoan_chi":
            return {"nguon": _raw(con, "expenses", "expense_item", "expense_date"), "phep": "tong", "cot": "expense_amount", "cot_ngay": "expense_date", "ky": K,
                    "nhom": "expense_item", "xep": {"chieu": "giam", "lay": 1}}
        case "sinh_nhat":
            t, c = _birthday(con)
            return {"nguon": t, "phep": "dem", "loc": [{"cot": c, "op": "thang_la", "gt": m}]}
        case "den_han":
            return {"nguon": _raw(con, "debt_terms", "due_date", "order_id"), "phep": "dem_khac", "cot": "order_id", "cot_ngay": "due_date", "ky": K}
    raise KeyError(key)


CACH = {
    "don_lon": "đếm số đơn hợp lệ có tổng tiền từ 300000 trong kỳ; ngưỡng so với tổng của đơn, không so từng dòng",
    "don_lon_tt": "doanh thu của các đơn đạt 300000 chia cho doanh thu cả kỳ",
    "dt_ngay": "doanh thu của kỳ chia cho số ngày có đơn trong kỳ",
    "gio": "giờ có nhiều đơn nhất: nhóm theo giờ, đếm đơn, lấy 1 giờ đứng đầu",
    "thu": "thứ có nhiều đơn nhất: nhóm theo thứ, đếm đơn, lấy 1 thứ đứng đầu",
    "cuoi_tuan": "cộng doanh thu của các dòng có thứ là 6 hoặc 7 trong kỳ",
    "cuoi_tuan_tt": "doanh thu thứ 6, 7 chia cho doanh thu cả kỳ",
    "gia_tb": "doanh thu của mặt hàng chia cho số lượng đơn vị cơ bản của nó trong kỳ",
    "khach_moi": "đếm khách có ngày mua đầu tiên rơi vào kỳ; lấy ngày đầu trên toàn bộ dữ liệu nên không ghi ky ở ngoài",
    "quay_lai": "tập khách mua trong tháng giao với tập khách mua tháng liền trước",
    "chu_luc": "đếm mặt hàng có tổng tiền từ 5% tổng tiền của cả kỳ",
    "don_max": "tổng tiền từng đơn, rồi lấy lớn nhất; trả về số tiền",
    "ban_it": "tổng số lượng đơn vị cơ bản theo mặt hàng, lấy mặt hàng thấp nhất",
    "nv": "đếm đơn theo nhân viên, lấy người đứng đầu",
    "ghi_no": "số đơn hợp lệ ghi nợ chia cho mọi đơn hợp lệ trong kỳ",
    "ti_le_tra": "đơn trả hàng chia cho mọi đơn trong kỳ, mọi trạng thái",
    "mat_huy": "cộng tiền các dòng của đơn huỷ trong kỳ; phải tính cả trạng thái huỷ",
    "so_mon": "số lượng đơn vị cơ bản của dòng mặt hàng chia cho số đơn trong kỳ",
    "ngay_trong": "số ngày dương lịch của kỳ trừ số ngày có đơn",
    "hang_moi": "đếm mặt hàng có ngày bán đầu tiên rơi vào kỳ",
    "nhieu_mon": "đếm đơn có từ 3 mặt hàng khác nhau; chỉ xét dòng là mặt hàng",
    "khach_le": "số đơn hợp lệ của khách lẻ chia cho mọi đơn hợp lệ trong kỳ",
    "tai_xe": "bảng dot_giao mỗi đợt một dòng: đếm đợt theo tài xế, kỳ theo ngày giao, lấy người đứng đầu",
    "xe": "bảng dot_giao mỗi đợt một dòng: đếm đợt theo biển số, kỳ theo ngày giao, lấy biển số đứng đầu",
    "khu_vuc": "bảng chuẩn không có khu vực: bảng gốc thông tin đơn, chỉ đơn hợp lệ, cộng doanh thu đơn theo khu vực",
    "khach_ban": "bảng chuẩn không có số khách: bảng gốc thông tin đơn, chỉ đơn hợp lệ, trung bình số khách",
    "phi_giao": "bảng chuẩn không có phí giao: bảng gốc đơn, chỉ đơn hợp lệ, cộng phí giao theo ngày đặt",
    "tien_thu": "bảng gốc sổ thu, cộng số tiền theo ngày thu; không phải doanh thu",
    "khoan_chi": "bảng gốc sổ chi, cộng tiền theo khoản mục trong kỳ, lấy khoản cao nhất",
    "sinh_nhat": "bảng gốc khách, đếm khách có tháng sinh là M, không xét năm",
    "den_han": "bảng gốc công nợ, đếm đơn khác nhau có hạn thanh toán trong kỳ",
}


def sql_of(con, key: str, m: int, y: int, name: str | None) -> tuple[str, str]:
    """Cùng dòng luật viết bằng SQL trên các bảng v_* của tầng SQL (query/sql_tier.py) -> (sql, ra)."""
    ym = f"{y}-{m:02d}"
    a, b = dt.date(y, m, 1), _month_end(y, m)
    pym = f"{y - 1}-12" if m == 1 else f"{y}-{m - 1:02d}"
    W = f"hop_le AND thang = '{ym}'"
    top = "DESC, {g} LIMIT 1"
    match key:
        case "don_lon":
            return f"SELECT COUNT(*) FROM (SELECT don FROM v_dong_ban WHERE {W} GROUP BY don HAVING SUM(tien) >= 300000)", "number"
        case "don_lon_tt":
            return f"SELECT 100.0 * SUM(s) FILTER (WHERE s >= 300000) / SUM(s) FROM (SELECT SUM(tien) s FROM v_dong_ban WHERE {W} GROUP BY don)", "percent"
        case "dt_ngay":
            return f"SELECT SUM(tien) / COUNT(DISTINCT ngay) FROM v_dong_ban WHERE {W}", "tien"
        case "gio" | "thu":
            return f"SELECT {key} FROM v_dong_ban WHERE {W} AND {key} IS NOT NULL GROUP BY {key} ORDER BY COUNT(DISTINCT don) {top.format(g=key)}", "number"
        case "cuoi_tuan":
            return f"SELECT SUM(tien) FROM v_dong_ban WHERE {W} AND thu IN (6, 7)", "tien"
        case "cuoi_tuan_tt":
            return f"SELECT 100.0 * SUM(tien) FILTER (WHERE thu IN (6, 7)) / SUM(tien) FROM v_dong_ban WHERE {W}", "percent"
        case "gia_tb":
            pid, k, _ = _product_index(con)[text_key(name)]
            cond = f"khoa_hang = {_q(k)}" if pid is None else f"(ma_hang = {_q(pid)} OR khoa_hang = {_q(k)})"
            return f"SELECT SUM(tien) / SUM(sl_co_ban) FROM v_dong_ban WHERE {W} AND {cond}", "tien"
        case "khach_moi" | "hang_moi":
            g, extra = ("khach", "") if key == "khach_moi" else ("hang", " AND la_mat_hang")
            return (f"SELECT COUNT(*) FROM (SELECT {g} FROM v_dong_ban WHERE hop_le{extra} AND {g} IS NOT NULL GROUP BY {g} "
                    f"HAVING MIN(ngay) BETWEEN DATE '{a}' AND DATE '{b}')"), "number"
        case "quay_lai":
            return (f"SELECT COUNT(*) FROM (SELECT DISTINCT khach FROM v_dong_ban WHERE {W} AND khach IS NOT NULL INTERSECT "
                    f"SELECT DISTINCT khach FROM v_dong_ban WHERE hop_le AND thang = '{pym}' AND khach IS NOT NULL)"), "number"
        case "chu_luc":
            return (f"SELECT COUNT(*) FROM (SELECT hang FROM v_dong_ban WHERE {W} AND la_mat_hang AND hang IS NOT NULL GROUP BY hang "
                    f"HAVING SUM(tien) >= 0.05 * (SELECT SUM(tien) FROM v_dong_ban WHERE {W}))"), "number"
        case "don_max":
            return f"SELECT MAX(s) FROM (SELECT SUM(tien) s FROM v_dong_ban WHERE {W} GROUP BY don)", "tien"
        case "ban_it":
            return f"SELECT ANY_VALUE(ten_hang) FROM v_dong_ban WHERE {W} AND la_mat_hang AND hang IS NOT NULL GROUP BY hang ORDER BY SUM(sl_co_ban), hang LIMIT 1", "string"
        case "nv":
            return f"SELECT nhan_vien FROM v_dong_ban WHERE {W} AND nhan_vien IS NOT NULL GROUP BY nhan_vien ORDER BY COUNT(DISTINCT don) {top.format(g='nhan_vien')}", "string"
        case "ghi_no" | "khach_le":
            f = "thanh_toan = 'ghi_no'" if key == "ghi_no" else "khach_le"
            return f"SELECT 100.0 * COUNT(DISTINCT don) FILTER (WHERE {f}) / COUNT(DISTINCT don) FROM v_dong_ban WHERE {W}", "percent"
        case "ti_le_tra":
            return f"SELECT 100.0 * COUNT(DISTINCT don) FILTER (WHERE trang_thai = 'tra_hang') / COUNT(DISTINCT don) FROM v_don WHERE thang = '{ym}'", "percent"
        case "mat_huy":
            return f"SELECT SUM(tien) FROM v_dong_ban WHERE trang_thai = 'huy' AND thang = '{ym}'", "tien"
        case "so_mon":
            return f"SELECT SUM(sl_co_ban) / COUNT(DISTINCT don) FROM v_dong_ban WHERE {W} AND la_mat_hang", "number"
        case "ngay_trong":
            return f"SELECT day(last_day(DATE '{a}')) - COUNT(DISTINCT ngay) FROM v_dong_ban WHERE {W}", "number"
        case "nhieu_mon":
            return f"SELECT COUNT(*) FROM (SELECT don FROM v_dong_ban WHERE {W} AND la_mat_hang GROUP BY don HAVING COUNT(DISTINCT hang) >= 3)", "number"
        case "tai_xe" | "xe":
            g = "tai_xe" if key == "tai_xe" else "bien_so"
            return f"SELECT {g} FROM v_dot_giao WHERE thang = '{ym}' AND {g} IS NOT NULL GROUP BY {g} ORDER BY COUNT(*) {top.format(g=g)}", "string"
        case "khu_vuc":
            t = _raw(con, "order_info", "area", "order_id")
            return (f'SELECT i.area FROM v_don d JOIN "{t}" i ON d.don = CAST(i.order_id AS VARCHAR) WHERE d.hop_le AND d.thang = \'{ym}\' '
                    f"AND i.area IS NOT NULL GROUP BY i.area ORDER BY SUM(d.doanh_thu) DESC, i.area LIMIT 1"), "string"
        case "khach_ban":
            t = _raw(con, "order_info", "guests", "order_id")
            return (f'SELECT AVG(CAST(i.guests AS DOUBLE)) FROM v_don d JOIN "{t}" i ON d.don = CAST(i.order_id AS VARCHAR) '
                    f"WHERE d.hop_le AND d.thang = '{ym}'"), "number"
        case "phi_giao":
            t = _raw(con, "orders", "shipping_fee", "order_id")
            return (f'SELECT SUM(CAST(i.shipping_fee AS DOUBLE)) FROM v_don d JOIN "{t}" i ON d.don = CAST(i.order_id AS VARCHAR) '
                    f"WHERE d.hop_le AND d.thang = '{ym}'"), "tien"
        case "tien_thu":
            t = _raw(con, "payments", "payment_amount", "payment_date")
            return f"SELECT SUM(payment_amount) FROM \"{t}\" WHERE strftime(CAST(payment_date AS DATE), '%Y-%m') = '{ym}'", "tien"
        case "khoan_chi":
            return f"SELECT khoan_muc FROM v_khoan_chi WHERE thang = '{ym}' AND khoan_muc IS NOT NULL GROUP BY khoan_muc ORDER BY SUM(tien) {top.format(g='khoan_muc')}", "string"
        case "sinh_nhat":
            t, c = _birthday(con)
            return f'SELECT COUNT(*) FROM "{t}" WHERE month(TRY_CAST("{c}" AS DATE)) = {m}', "number"
        case "den_han":
            t = _raw(con, "debt_terms", "due_date", "order_id")
            return f"SELECT COUNT(DISTINCT order_id) FROM \"{t}\" WHERE strftime(CAST(due_date AS DATE), '%Y-%m') = '{ym}'", "number"
    raise KeyError(key)


# ---------------------------------------------------------------- bộ R2 (viết sau khi đã đo bộ R2: từ đây R2 không còn là bộ đo)

def plan_of2(con, key: str, m: int, y: int, name: str | None) -> dict:
    K = {"loai": "thang", "thang": m, "nam": y}
    D = {"nguon": "dong_ban"}
    REV = {**D, "phep": "tong", "cot": "tien", "ky": K}
    ORD = {**D, "phep": "dem_khac", "cot": "don", "ky": K}
    end = {"loai": "ngay", "ngay": str(_month_end(y, m))}
    top = {"chieu": "giam", "lay": 1}
    match key:
        case "dinh_day":
            day = {**REV, "nhom": "ngay", "cot_ra": "gia_tri"}
            return {"ghep": "hieu", "cac": [{**day, "xep": top}, {**day, "xep": {"chieu": "tang", "lay": 1}}]}
        case "don_nho":
            return {**D, "phep": "dem_nhom", "nhom": "don", "cot": "tien", "do": "tong", "ky": K, "co_dieu_kien": {"op": "<", "gt": 100000}}
        case "don_sang":
            return {"ghep": "ti_le", "cac": [{**ORD, "loc": [{"cot": "ca", "op": "=", "gt": "sang"}]}, ORD]}
        case "mon_ruot":
            return {**ORD, "nhom": "hang", "xep": top}
        case "trung_thanh":
            return {**D, "phep": "dem_nhom", "nhom": "khach", "ky": {"loai": "nam", "nam": y},
                    "co_dieu_kien": {"do": "dem_khac", "cot": "thang", "op": ">=", "gt": 3}}
        case "mot_lan":
            return {**D, "phep": "dem_nhom", "nhom": "khach", "cot": "don", "ky": K, "co_dieu_kien": {"op": "=", "gt": 1}}
        case "dau_thang":
            return {**REV, "ky": {"loai": "khoang", "tu": f"{y}-{m:02d}-01", "den": f"{y}-{m:02d}-10"}}
        case "gio_trua":
            return {**REV, "loc": [{"cot": "gio", "op": ">=", "gt": 11}, {"cot": "gio", "op": "<=", "gt": 13}]}
        case "tang_thang":
            return {"ghep": "lon_hon", "cac": [REV, {**REV, "ky": {"loai": "ky_truoc", "cua": K}}]}
        case "hang_dat":
            return {**D, "phep": "max", "cot": "don_gia", "ky": K, "nhom": "hang", "xep": top}
        case "no_lau":
            return {"nguon": "cong_no", "phep": "dem", "den_het": end, "loc": [{"cot": "tuoi_no", "op": ">", "gt": 30}]}
        case "khach_no":
            return {"nguon": "cong_no", "phep": "tong", "cot": "con_no", "den_het": end, "nhom": "khach", "xep": top}
        case "phieu_max":
            return {"nguon": "phieu_nhap", "phep": "max", "cot": "tong_tien", "ky": K}
        case "ncc_so":
            return {"nguon": "phieu_nhap", "phep": "dem_khac", "cot": "nha_cung_cap", "ky": K}
        case "khach_phone":
            return {"nguon": _raw(con, "customers", "phone"), "phep": "dem", "loc": [{"cot": "phone", "op": "khong_rong"}]}
        case "dot2":
            return {"nguon": "dot_giao", "phep": "dem", "ky": K, "loc": [{"cot": "dot", "op": ">=", "gt": 2}]}
        case "nhom_khach":
            return {"nguon": _raw(con, "customers", "customer_group"), "phep": "dem", "nhom": "customer_group", "xep": top}
        case "giam_dong":
            return {"nguon": _raw(con, "sales_lines", "line_discount", "order_id"), "phep": "tong", "cot": "line_discount", "cot_ngay": "ngay_don",
                    "ky": K, "loc": [{"cot": "hop_le", "op": "=", "gt": True}]}
    raise KeyError(key)


def sql_of2(con, key: str, m: int, y: int, name: str | None) -> tuple[str, str]:
    ym = f"{y}-{m:02d}"
    pym = f"{y - 1}-12" if m == 1 else f"{y}-{m - 1:02d}"
    W = f"hop_le AND thang = '{ym}'"
    match key:
        case "dinh_day":
            return f"SELECT MAX(s) - MIN(s) FROM (SELECT SUM(tien) s FROM v_dong_ban WHERE {W} GROUP BY ngay)", "tien"
        case "don_nho":
            return f"SELECT COUNT(*) FROM (SELECT don FROM v_dong_ban WHERE {W} GROUP BY don HAVING SUM(tien) < 100000)", "number"
        case "don_sang":
            return f"SELECT 100.0 * COUNT(DISTINCT don) FILTER (WHERE ca = 'sang') / COUNT(DISTINCT don) FROM v_dong_ban WHERE {W}", "percent"
        case "mon_ruot":
            return f"SELECT ANY_VALUE(ten_hang) FROM v_dong_ban WHERE {W} AND la_mat_hang AND hang IS NOT NULL GROUP BY hang ORDER BY COUNT(DISTINCT don) DESC, hang LIMIT 1", "string"
        case "trung_thanh":
            return (f"SELECT COUNT(*) FROM (SELECT khach FROM v_dong_ban WHERE hop_le AND khach IS NOT NULL AND ngay BETWEEN DATE '{y}-01-01' AND DATE '{y}-12-31' "
                    f"GROUP BY khach HAVING COUNT(DISTINCT thang) >= 3)"), "number"
        case "mot_lan":
            return f"SELECT COUNT(*) FROM (SELECT khach FROM v_dong_ban WHERE {W} AND khach IS NOT NULL GROUP BY khach HAVING COUNT(DISTINCT don) = 1)", "number"
        case "dau_thang":
            return f"SELECT SUM(tien) FROM v_dong_ban WHERE hop_le AND ngay BETWEEN DATE '{y}-{m:02d}-01' AND DATE '{y}-{m:02d}-10'", "tien"
        case "gio_trua":
            return f"SELECT SUM(tien) FROM v_dong_ban WHERE {W} AND gio BETWEEN 11 AND 13", "tien"
        case "tang_thang":
            return (f"SELECT (SELECT SUM(tien) FROM v_dong_ban WHERE {W}) > (SELECT SUM(tien) FROM v_dong_ban WHERE hop_le AND thang = '{pym}')"), "boolean"
        case "hang_dat":
            return f"SELECT ANY_VALUE(ten_hang) FROM v_dong_ban WHERE {W} AND la_mat_hang AND hang IS NOT NULL GROUP BY hang ORDER BY MAX(don_gia) DESC, hang LIMIT 1", "string"
        case "no_lau":
            return "SELECT COUNT(*) FROM v_cong_no WHERE tuoi_no > 30", "number"
        case "khach_no":
            return "SELECT ANY_VALUE(ten_khach) FROM v_cong_no WHERE khach IS NOT NULL GROUP BY khach ORDER BY SUM(con_no) DESC, khach LIMIT 1", "string"
        case "phieu_max":
            return f"SELECT MAX(tong_tien) FROM v_phieu_nhap WHERE thang = '{ym}'", "tien"
        case "ncc_so":
            return f"SELECT COUNT(DISTINCT nha_cung_cap) FROM v_phieu_nhap WHERE thang = '{ym}'", "number"
        case "khach_phone":
            return f'SELECT COUNT(*) FROM "{_raw(con, "customers", "phone")}" WHERE phone IS NOT NULL', "number"
        case "dot2":
            return f"SELECT COUNT(*) FROM v_dot_giao WHERE thang = '{ym}' AND dot >= 2", "number"
        case "nhom_khach":
            t = _raw(con, "customers", "customer_group")
            return f'SELECT customer_group FROM "{t}" WHERE customer_group IS NOT NULL GROUP BY 1 ORDER BY COUNT(*) DESC, 1 LIMIT 1', "string"
        case "giam_dong":
            t = _raw(con, "sales_lines", "line_discount", "order_id")
            return (f'SELECT SUM(CAST(l.line_discount AS DOUBLE)) FROM "{t}" l JOIN v_don d ON CAST(l.order_id AS VARCHAR) = d.don '
                    f"WHERE d.hop_le AND d.thang = '{ym}'"), "tien"
    raise KeyError(key)


CACH2 = {
    "dinh_day": "doanh thu từng ngày có đơn, lấy ngày cao nhất trừ ngày thấp nhất",
    "don_nho": "đếm đơn có tổng tiền dưới 100000; ngưỡng so với tổng của đơn",
    "don_sang": "số đơn ca sáng chia cho mọi đơn hợp lệ trong kỳ",
    "mon_ruot": "đếm số đơn khác nhau theo mặt hàng, lấy mặt hàng đứng đầu; không xét số lượng",
    "trung_thanh": "đếm khách có đơn ở từ 3 tháng khác nhau trong năm",
    "mot_lan": "đếm khách có đúng 1 đơn trong tháng",
    "dau_thang": "doanh thu từ ngày 1 đến hết ngày 10 của tháng",
    "gio_trua": "doanh thu các dòng có giờ tạo đơn từ 11 đến 13",
    "tang_thang": "doanh thu tháng hỏi có lớn hơn tháng liền trước không",
    "hang_dat": "đơn giá lớn nhất theo mặt hàng, lấy mặt hàng đứng đầu",
    "no_lau": "bảng công nợ tính đến hết ngày cuối tháng: đếm đơn có tuổi nợ trên 30 ngày",
    "khach_no": "bảng công nợ tính đến hết ngày cuối tháng: cộng còn nợ theo khách, lấy khách đứng đầu",
    "phieu_max": "phiếu nhập có tổng tiền lớn nhất trong tháng; trả về số tiền",
    "ncc_so": "đếm nhà cung cấp khác nhau có phiếu nhập trong tháng",
    "khach_phone": "bảng gốc danh sách khách: đếm khách có ghi số điện thoại",
    "dot2": "bảng dot_giao mỗi đợt một dòng: đếm đợt có số thứ tự từ 2 trở lên, kỳ theo ngày giao",
    "nhom_khach": "bảng gốc danh sách khách: đếm khách theo nhóm, lấy nhóm đông nhất",
    "giam_dong": "bảng gốc dòng bán có giảm giá dòng: cộng giảm giá của các đơn hợp lệ đặt trong tháng",
}


# ---------------------------------------------------------------- bộ R3, R4 (viết 2026-11-03 sau khi đã đo cả hai): chỉ SQL
# Tầng SQL là đường chính cho dòng luật mới; kế hoạch JSON của các dòng này không viết. Ví dụ không có "plan" chỉ vào prompt SQL.

def _cond_hang(con, name: str) -> str:
    pid, k, _ = _product_index(con)[text_key(name)]
    return f"khoa_hang = {_q(k)}" if pid is None else f"(ma_hang = {_q(pid)} OR khoa_hang = {_q(k)})"


def sql_of3(con, key: str, m: int, y: int, name: str | None) -> tuple[str, str]:
    ym = f"{y}-{m:02d}"
    pi = y * 12 + m - 2
    pym = f"{pi // 12}-{pi % 12 + 1:02d}"
    ppym = f"{(pi - 1) // 12}-{(pi - 1) % 12 + 1:02d}"
    W = f"hop_le AND thang = '{ym}'"
    sales = f"(SELECT SUM(tien) FROM v_dong_ban WHERE hop_le AND thang = '{{}}')"
    match key:
        case "ba_ngay":
            return f"SELECT ngay FROM v_dong_ban WHERE {W} GROUP BY ngay ORDER BY SUM(tien) DESC, ngay LIMIT 3", "list"
        case "mo_hang":
            return f"SELECT MIN(ngay) FROM v_dong_ban WHERE {W}", "date"
        case "chot":
            return f"SELECT MAX(ngay) FROM v_dong_ban WHERE {W}", "date"
        case "hai_nhom":
            return f"SELECT nhom_hang FROM v_dong_ban WHERE {W} AND nhom_hang IS NOT NULL GROUP BY nhom_hang ORDER BY SUM(tien) DESC, nhom_hang LIMIT 2", "list"
        case "bang_kenh":
            return f"SELECT kenh, SUM(tien) FROM v_dong_ban WHERE {W} AND kenh IS NOT NULL GROUP BY kenh ORDER BY 2 DESC, 1", "table"
        case "don_toi":
            return f"SELECT COUNT(DISTINCT don) FROM v_dong_ban WHERE {W} AND gio >= 20", "number"
        case "tt_ck":
            return f"SELECT 100.0 * SUM(tien) FILTER (WHERE thanh_toan = 'chuyen_khoan') / SUM(tien) FROM v_dong_ban WHERE {W}", "percent"
        case "khach_thu":
            return (f"SELECT COUNT(*) FROM (SELECT khach FROM v_dong_ban WHERE {W} AND la_mat_hang AND khach IS NOT NULL GROUP BY khach "
                    f"HAVING COUNT(DISTINCT hang) >= 3)"), "number"
        case "hang_mot_don":
            return (f"SELECT COUNT(*) FROM (SELECT hang FROM v_dong_ban WHERE {W} AND la_mat_hang AND hang IS NOT NULL GROUP BY hang "
                    f"HAVING COUNT(DISTINCT don) = 1)"), "number"
        case "so_dong":
            return f"SELECT ROUND(1.0 * COUNT(*) FILTER (WHERE la_mat_hang) / COUNT(DISTINCT don), 2) FROM v_dong_ban WHERE {W}", "number"
        case "chenh_ca":
            return f"SELECT SUM(tien) FILTER (WHERE ca = 'sang') - SUM(tien) FILTER (WHERE ca = 'chieu') FROM v_dong_ban WHERE {W}", "tien"
        case "thang_dinh":
            return (f"SELECT thang FROM v_dong_ban WHERE hop_le AND ngay BETWEEN DATE '{y}-01-01' AND DATE '{y}-12-31' GROUP BY thang "
                    f"ORDER BY SUM(tien) DESC, thang LIMIT 1"), "date"
        case "xuong_doc":
            return f"SELECT {sales.format(ym)} < {sales.format(pym)} AND {sales.format(pym)} < {sales.format(ppym)}", "boolean"
        case "tien_tra":
            return f"SELECT SUM(tien) FROM v_dong_ban WHERE trang_thai = 'tra_hang' AND thang = '{ym}'", "tien"
        case "chi_khach":
            return f"SELECT SUM(tien) / COUNT(DISTINCT khach) FROM v_dong_ban WHERE {W} AND khach IS NOT NULL", "tien"
        case "ncc_phieu":
            return (f"SELECT nha_cung_cap FROM v_phieu_nhap WHERE thang = '{ym}' AND nha_cung_cap IS NOT NULL GROUP BY nha_cung_cap "
                    f"ORDER BY COUNT(DISTINCT phieu) DESC, nha_cung_cap LIMIT 1"), "string"
        case "tong_chi":
            return f"SELECT SUM(tien) FROM v_khoan_chi WHERE thang = '{ym}'", "tien"
        case "ti_le_chi":
            return f"SELECT 100.0 * (SELECT SUM(tien) FROM v_khoan_chi WHERE thang = '{ym}') / {sales.format(ym)}", "percent"
        case "sap_het":
            return "SELECT COUNT(*) FROM v_ton WHERE ton > 0 AND ton < 5", "number"
        case "no_tb":
            return "SELECT SUM(con_no) / COUNT(*) FROM v_cong_no", "tien"
        case "nang_suat":
            return f"SELECT ROUND(1.0 * COUNT(DISTINCT don) / COUNT(DISTINCT nhan_vien), 2) FROM v_dong_ban WHERE {W}", "number"
        case "ba_khach":
            return (f"SELECT ANY_VALUE(ten_khach) FROM v_dong_ban WHERE {W} AND khach IS NOT NULL GROUP BY khach "
                    f"ORDER BY COUNT(DISTINCT don) DESC, khach LIMIT 3"), "list"
        case "ban":
            t = _raw(con, "order_info", "table_no", "order_id")
            return (f'SELECT i.table_no FROM v_don d JOIN "{t}" i ON d.don = CAST(i.order_id AS VARCHAR) WHERE d.hop_le AND d.thang = \'{ym}\' '
                    f"AND i.table_no IS NOT NULL GROUP BY i.table_no ORDER BY COUNT(DISTINCT d.don) DESC, i.table_no LIMIT 1"), "string"
        case "han_no":
            t = _raw(con, "debt_terms", "credit_days", "order_id")
            return (f'SELECT ROUND(AVG(CAST(i.credit_days AS DOUBLE)), 2) FROM v_don d JOIN "{t}" i ON d.don = CAST(i.order_id AS VARCHAR) '
                    f"WHERE d.hop_le AND d.thang = '{ym}'"), "number"
        case "danh_muc":
            return f'SELECT COUNT(DISTINCT category) FROM "{_raw(con, "products", "category")}"', "number"
        case "khach_dk":
            t = _raw(con, "customers", "created_date")
            return f"SELECT COUNT(*) FROM \"{t}\" WHERE strftime(CAST(created_date AS DATE), '%Y-%m') = '{ym}'", "number"
        case "giam_don":
            return f"SELECT SUM(giam_don) FROM v_don WHERE {W}", "tien"
        case "ht_thu":
            t = _raw(con, "payments", "payment_method", "payment_amount", "payment_date")
            return (f"SELECT payment_method FROM \"{t}\" WHERE payment_method IS NOT NULL AND strftime(CAST(payment_date AS DATE), '%Y-%m') = '{ym}' "
                    f"GROUP BY 1 ORDER BY SUM(payment_amount) DESC, 1 LIMIT 1"), "string"
        case "doi_gia":
            t = _raw(con, "price_history", "price_from")
            return f"SELECT COUNT(*) FROM \"{t}\" WHERE strftime(CAST(price_from AS DATE), '%Y-%m') = '{ym}'", "number"
    raise KeyError(key)


CACH3 = {
    "ba_ngay": "doanh thu theo ngày trong tháng, lấy 3 ngày cao nhất, xếp từ cao xuống thấp; trả về các ngày",
    "mo_hang": "ngày nhỏ nhất trong tháng có đơn hợp lệ",
    "chot": "ngày lớn nhất trong tháng có đơn hợp lệ",
    "hai_nhom": "doanh thu theo nhóm hàng, lấy 2 nhóm đứng đầu theo thứ tự",
    "bang_kenh": "bảng doanh thu theo kênh bán: mỗi dòng [kênh, doanh thu]",
    "don_toi": "đếm đơn hợp lệ khác nhau có giờ tạo từ 20 trở đi",
    "tt_ck": "doanh thu của đơn chuyển khoản chia cho doanh thu cả kỳ",
    "khach_thu": "đếm khách có từ 3 mặt hàng khác nhau trong tháng",
    "hang_mot_don": "đếm mặt hàng chỉ nằm trong đúng 1 đơn khác nhau của tháng",
    "so_dong": "số dòng là mặt hàng chia cho số đơn khác nhau; luật nói số dòng nên đếm dòng",
    "chenh_ca": "doanh thu ca sáng trừ doanh thu ca chiều, có thể âm",
    "thang_dinh": "doanh thu theo tháng trong năm hỏi, lấy tháng cao nhất; trả về 'YYYY-MM'",
    "xuong_doc": "so doanh thu ba tháng liền nhau: tháng hỏi < tháng trước < tháng trước nữa",
    "tien_tra": "cộng tiền các dòng của đơn trả hàng đặt trong kỳ; không lọc hop_le",
    "chi_khach": "doanh thu của đơn có khách chia cho số khách khác nhau; bỏ khách lẻ",
    "ncc_phieu": "đếm phiếu nhập theo nhà cung cấp trong tháng, lấy nhà cung cấp đứng đầu; không xét tiền",
    "tong_chi": "cộng sổ chi phí theo ngày chi trong tháng",
    "ti_le_chi": "tổng chi của tháng chia cho doanh thu cùng tháng",
    "sap_het": "bảng tồn lúc hết ngày cuối tháng: đếm mặt hàng có tồn lớn hơn 0 và dưới 5",
    "no_tb": "bảng công nợ lúc hết ngày cuối tháng: tổng còn nợ chia cho số đơn còn nợ",
    "nang_suat": "số đơn khác nhau chia cho số nhân viên khác nhau có đơn trong kỳ",
    "ba_khach": "đếm đơn theo khách, lấy 3 khách đứng đầu theo thứ tự; bỏ khách lẻ",
    "ban": "bảng chuẩn không có số bàn: bảng gốc thông tin đơn, chỉ đơn hợp lệ, đếm đơn theo bàn, lấy bàn đứng đầu",
    "han_no": "bảng gốc điều khoản nợ, trung bình số ngày cho nợ của đơn hợp lệ đặt trong kỳ",
    "danh_muc": "bảng gốc danh mục hàng: đếm nhóm khác nhau, không theo kỳ",
    "khach_dk": "bảng gốc danh sách khách: đếm khách có ngày tạo trong tháng",
    "giam_don": "cộng giảm giá trên cả đơn (giam_don) của đơn hợp lệ trong tháng",
    "ht_thu": "bảng gốc sổ thu: cộng tiền theo hình thức trong tháng thu, lấy hình thức đứng đầu",
    "doi_gia": "bảng gốc lịch sử giá: đếm dòng có ngày hiệu lực trong tháng",
}


def sql_of4(con, key: str, m: int, y: int, name: str | None) -> tuple[str, str]:
    ym = f"{y}-{m:02d}"
    pi = y * 12 + m - 2
    pym = f"{pi // 12}-{pi % 12 + 1:02d}"
    a = dt.date(y, m, 1)
    W = f"hop_le AND thang = '{ym}'"
    sales = "(SELECT SUM(tien) FROM v_dong_ban WHERE hop_le AND thang = '{}')"
    match key:
        case "don_si":
            return (f"SELECT COUNT(*) FROM (SELECT don FROM v_dong_ban WHERE {W} AND la_mat_hang GROUP BY don "
                    f"HAVING SUM(sl_co_ban) >= 20)"), "number"
        case "trung_vi":
            return f"SELECT MEDIAN(s) FROM (SELECT SUM(tien) s FROM v_dong_ban WHERE {W} GROUP BY don)", "tien"
        case "don_gian":
            return (f"SELECT COUNT(*) FROM (SELECT don FROM v_dong_ban WHERE {W} AND la_mat_hang GROUP BY don "
                    f"HAVING COUNT(DISTINCT hang) = 1)"), "number"
        case "tuan_chot":
            return (f"SELECT SUM(tien) FROM v_dong_ban WHERE hop_le AND ngay BETWEEN last_day(DATE '{a}') - INTERVAL 6 DAY "
                    f"AND last_day(DATE '{a}')"), "tien"
        case "khach_roi" | "hang_ngung":
            g, extra = ("khach", "") if key == "khach_roi" else ("hang", " AND la_mat_hang")
            return (f"SELECT COUNT(*) FROM (SELECT DISTINCT {g} FROM v_dong_ban WHERE hop_le{extra} AND {g} IS NOT NULL AND thang = '{pym}' "
                    f"EXCEPT SELECT DISTINCT {g} FROM v_dong_ban WHERE hop_le{extra} AND {g} IS NOT NULL AND thang = '{ym}')"), "number"
        case "ngay_co_hang":
            return f"SELECT COUNT(DISTINCT ngay) FROM v_dong_ban WHERE {W} AND {_cond_hang(con, name)}", "number"
        case "gia_tran":
            return f"SELECT MAX(don_gia) FROM v_dong_ban WHERE {W} AND {_cond_hang(con, name)}", "tien"
        case "nv_don_to":
            return (f"SELECT nhan_vien FROM v_dong_ban WHERE {W} AND nhan_vien IS NOT NULL GROUP BY nhan_vien HAVING COUNT(DISTINCT don) >= 10 "
                    f"ORDER BY SUM(tien) / COUNT(DISTINCT don) DESC, nhan_vien LIMIT 1"), "string"
        case "khach_sieng":
            return (f"SELECT ANY_VALUE(ten_khach) FROM v_dong_ban WHERE {W} AND khach IS NOT NULL GROUP BY khach "
                    f"ORDER BY COUNT(DISTINCT ngay) DESC, khach LIMIT 1"), "string"
        case "mon_loi":
            return (f"SELECT ANY_VALUE(ten_hang) FROM v_dong_ban WHERE {W} AND la_mat_hang AND hang IS NOT NULL AND lai IS NOT NULL "
                    f"GROUP BY hang ORDER BY SUM(lai) DESC, hang LIMIT 1"), "string"
        case "ngay_vang":
            return f"SELECT ngay FROM v_dong_ban WHERE {W} GROUP BY ngay ORDER BY COUNT(DISTINCT don) DESC, ngay LIMIT 1", "date"
        case "hai_mon":
            return (f"SELECT ANY_VALUE(ten_hang) FROM v_dong_ban WHERE {W} AND la_mat_hang AND hang IS NOT NULL GROUP BY hang "
                    f"ORDER BY SUM(tien) DESC, hang LIMIT 2"), "list"
        case "vuot_nam":
            return f"SELECT {sales.format(ym)} > {sales.format(f'{y - 1}-{m:02d}')}", "boolean"
        case "don_khung":
            return f"SELECT MAX(s) >= 5000000 FROM (SELECT SUM(tien) s FROM v_dong_ban WHERE {W} GROUP BY don)", "boolean"
        case "nhap_tb":
            return f"SELECT SUM(tong_tien) / COUNT(*) FROM v_phieu_nhap WHERE thang = '{ym}'", "tien"
        case "nhap_ban":
            return f"SELECT 100.0 * (SELECT SUM(tong_tien) FROM v_phieu_nhap WHERE thang = '{ym}') / {sales.format(ym)}", "percent"
        case "chi_ngay":
            return f"SELECT SUM(tien) / day(last_day(DATE '{a}')) FROM v_khoan_chi WHERE thang = '{ym}'", "tien"
        case "online":
            return f"SELECT SUM(tien) FROM v_dong_ban WHERE {W} AND kenh IS NOT NULL AND kenh <> 'tai_quay'", "tien"
        case "kenh_manh":
            return f"SELECT kenh FROM v_dong_ban WHERE {W} AND kenh IS NOT NULL GROUP BY kenh ORDER BY COUNT(DISTINCT don) DESC, kenh LIMIT 1", "string"
        case "dong_tb":
            return f"SELECT SUM(tien) / COUNT(*) FROM v_dong_ban WHERE {W} AND la_mat_hang", "tien"
        case "len_ke":
            return f"SELECT MIN(ngay) FROM v_dong_ban WHERE hop_le AND {_cond_hang(con, name)}", "date"
        case "tt_dau":
            return (f"SELECT 100.0 * MAX(s) / {sales.format(ym)} FROM (SELECT SUM(tien) s FROM v_dong_ban WHERE {W} AND la_mat_hang "
                    f"AND hang IS NOT NULL GROUP BY hang)"), "percent"
        case "dong_giam":
            return f"SELECT 100.0 * COUNT(*) FILTER (WHERE giam_dong > 0) / COUNT(*) FROM v_dong_ban WHERE {W} AND la_mat_hang", "percent"
    raise KeyError(key)


CACH4 = {
    "don_si": "đếm đơn có tổng số lượng đơn vị cơ bản của dòng mặt hàng từ 20; ngưỡng trên tổng của đơn",
    "trung_vi": "doanh thu từng đơn, lấy trung vị (MEDIAN)",
    "don_gian": "đếm đơn chỉ có đúng 1 mặt hàng khác nhau, chỉ xét dòng là mặt hàng",
    "tuan_chot": "doanh thu 7 ngày cuối tháng: từ ngày cuối tháng lùi 6 ngày; để SQL tính ngày",
    "khach_roi": "tập khách tháng liền trước trừ tập khách tháng hỏi (EXCEPT)",
    "hang_ngung": "tập mặt hàng tháng liền trước trừ tập mặt hàng tháng hỏi (EXCEPT)",
    "ngay_co_hang": "đếm ngày khác nhau có dòng của mặt hàng nêu trong tháng",
    "gia_tran": "đơn giá lớn nhất của mặt hàng nêu trong tháng; trả về số tiền",
    "nv_don_to": "doanh thu chia số đơn theo nhân viên có từ 10 đơn, lấy người cao nhất",
    "khach_sieng": "đếm ngày mua khác nhau theo khách, lấy khách đứng đầu; bỏ khách lẻ",
    "mon_loi": "cộng lãi gộp theo mặt hàng, lấy mặt hàng cao nhất",
    "ngay_vang": "đếm đơn theo ngày, lấy ngày nhiều đơn nhất; trả về ngày, không theo doanh thu",
    "hai_mon": "doanh thu theo mặt hàng, lấy 2 mặt hàng đứng đầu theo thứ tự",
    "vuot_nam": "doanh thu tháng hỏi có lớn hơn cùng tháng năm trước không",
    "don_khung": "có đơn nào tổng tiền từ 5000000 không: MAX tổng đơn >= 5000000",
    "nhap_tb": "tổng tiền phiếu nhập trong tháng chia cho số phiếu",
    "nhap_ban": "tổng tiền phiếu nhập của tháng chia cho doanh thu cùng tháng",
    "chi_ngay": "tổng chi của tháng chia cho số ngày dương lịch của tháng",
    "online": "doanh thu các đơn có kênh khác bán tại quầy",
    "kenh_manh": "đếm đơn theo kênh bán, lấy kênh đứng đầu",
    "dong_tb": "doanh thu dòng mặt hàng chia cho số dòng mặt hàng; luật nói số dòng nên đếm dòng",
    "len_ke": "ngày nhỏ nhất trên toàn bộ dữ liệu có dòng của mặt hàng nêu; không giới hạn kỳ",
    "tt_dau": "doanh thu mặt hàng cao nhất chia cho doanh thu cả tháng",
    "dong_giam": "số dòng mặt hàng có giảm giá dòng lớn hơn 0 chia cho mọi dòng mặt hàng; đếm dòng, không đếm đơn",
}


def _name_in(question: str) -> str:
    return re.search(r"(?:của |cua |\d{4} )(.+?)(?: thang| tháng| có giá|$)", question)[1]


def _name_db(ctx, question: str) -> str:
    """Tên mặt hàng dài nhất có trong câu (câu R4 đặt tên ở nhiều chỗ khác nhau)."""
    t = ctx.facts.table("dong_ban")
    names = [n for n, in ctx.con.execute(f'SELECT DISTINCT ten_hang FROM "{t}" WHERE ten_hang IS NOT NULL').fetchall()]
    hits = [n for n in names if n in question]
    if not hits:
        raise KeyError("không thấy tên hàng trong câu")
    return max(hits, key=len)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("train_root")
    ap.add_argument("db_root")
    ap.add_argument("split")
    ap.add_argument("--out", required=True)
    ap.add_argument("--bo", type=int, default=1, choices=[1, 2, 3, 4])
    a = ap.parse_args()
    rows, plan_fn, sql_fn, cach = {1: (ROWS, plan_of, sql_of, CACH), 2: (ROWS2, plan_of2, sql_of2, CACH2),
                                   3: (ROWS3, None, sql_of3, CACH3), 4: (ROWS4, None, sql_of4, CACH4)}[a.bo]
    rule = {r.key: r.rule for r in rows}
    named = {r.key for r in rows if r.pick}
    # đoạn rulebook thêm của bộ: chốt của tầng SQL đọc cả tên luật (vd câu không dấu về "dòng")
    luat_path = os.path.join(a.split, "luat.md")
    extra = open(luat_path, encoding="utf-8").read() if os.path.exists(luat_path) else ""

    def load(n):
        return [json.loads(line) for line in open(os.path.join(a.split, f"{n}.jsonl"), encoding="utf-8")]
    golds, meta = {x["id"]: x for x in load("answers")}, {x["id"]: x["dong"] for x in load("meta")}
    seen: dict = {}
    res: Counter = Counter()
    with open(a.out, "w", encoding="utf-8") as fh:
        for q in load("questions"):
            g, key, s = golds[q["id"]], meta[q["id"]], q["business_id"]
            if g["type"] == "unanswerable" or key not in cach:
                continue
            if s not in seen:
                seen[s] = ShopContext(os.path.join(a.db_root, s, f"{s}.duckdb"))
                if a.bo >= 3 and extra:
                    seen[s].rules += "\n" + extra
            ctx = seen[s]
            mm = re.match(r"r_\w+_biz_\d+_(\d+)_(\d+)$", q["id"])
            m, y = int(mm[1]), int(mm[2])
            today = dt.date.fromisoformat(q["as_of_date"])
            try:
                name = _name_in(q["question"]) if key == "gia_tb" else _name_db(ctx, q["question"]) if key in named else None
            except KeyError:
                res["khong_ten"] += 1
                continue
            plan, ok = None, False
            if plan_fn:
                try:
                    plan = plan_fn(ctx.con, key, m, y, name)
                    ok = check(Runner(ctx.con, today, ctx.facts).run(plan), g)
                except (PlanError, KeyError):
                    ok = False
            row = {"id": q["id"], "shop": s, "as_of_date": q["as_of_date"], "question": q["question"], "dong": key, "rule": rule[key],
                   "cach_tinh": cach[key], "plan": plan if ok else None, "type": g["type"]}
            why = None
            try:        # cùng dòng luật viết bằng SQL, kiểm như kế hoạch
                sql, ra = sql_fn(ctx.con, key, m, y, name)
                _prepare(ctx)
                kind, why, _, v, _ = sql_attempt(ctx, {"sql": sql, "ra": ra}, q, today)
                if kind == "tra_loi" and check(v, g):
                    row.update(sql=sql, ra_sql=ra)
            except (MissingData, KeyError) as e:
                why = str(e)
            res["giu_ke_hoach" if ok else "bo_ke_hoach"] += 1
            res["co_sql"] += "sql" in row
            if "sql" not in row and not plan_fn:
                print("SQL không qua:", q["id"], str(why)[:200])
            if ok or "sql" in row:
                fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    print(dict(res))


if __name__ == "__main__":
    main()
