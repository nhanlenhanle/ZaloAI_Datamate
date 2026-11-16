"""Các lỗi do bản kiểm định S20 tái hiện (B1, B2, B3, B4, B7, B9): khoá lại để không hỏng lại."""
import json
import os
import subprocess
import sys

import pandas as pd

from datamate.loader.build import add_line_amount
from datamate.loader.header import Table, khac_loai, ledger_kind, merge_sheets
from datamate.loader.parsers import is_walk_in, parse_number_unit
from datamate.loader.readme import _DATA_END


def test_b7_don_vi_viet_hoa():
    assert parse_number_unit("2 Bó") == (2, "Bó")
    assert parse_number_unit("3 Chai") == (3, "Chai")
    assert parse_number_unit("2 Lít") == (2, "Lít")
    assert parse_number_unit("452 Tân Kỳ Tân Quý") == (None, None)
    assert parse_number_unit("5 chai") == (5, "chai")


def test_b9_khach_le_khong_nuot_ten_that():
    for v in ["Khách lẻ", "Khách lẻ 1", "Khách lẻ - 0901", "Khách vãng lai (A Tú)", "KL", "guest"]:
        assert is_walk_in(v), v
    for v in ["Khách Lê Văn A", "Guest House Co", "KL Trading"]:
        assert not is_walk_in(v), v


def test_b2_ngay_cuoi_du_lieu_nhieu_cach_viet():
    for t, want in [("Dữ liệu có đến hết 31/03/2025.", ("31", "03", "2025")),
                    ("Dữ liệu từ 01/02/2025 đến hết 12/09/2026.", ("12", "09", "2026")),
                    ("Số liệu cập nhật tới 31/03/2025", ("31", "03", "2025")),
                    ("Sổ ghi đến ngày 30-06-2026", ("30", "06", "2026"))]:
        assert _DATA_END.search(t).groups() == want, t


def test_b1_thanh_tien_tu_sl_x_gia():
    df = pd.DataFrame({"qty": [2, 3], "unit_price": [10000, 5000], "line_discount": [1000, 0]})
    cols = []
    assert add_line_amount(df, cols) == 2
    assert list(df["line_amount"]) == [19000, 15000]
    df2 = pd.DataFrame({"qty": [1], "unit_price": [1], "line_amount": [7]})
    assert add_line_amount(df2, []) == 0 and list(df2["line_amount"]) == [7]


def test_b3_khong_gop_so_khac_loai():
    assert ledger_kind("BanHang") == "ban" and ledger_kind("NhapHang") == "nhap" and ledger_kind("TraHang") == "tra"
    assert khac_loai("BanHang", "TraHang") and khac_loai("SoBan", "SoNhapHang")
    assert not khac_loai("T01", "T02") and not khac_loai("BanHang", "DonHang_Online") and not khac_loai("Sheet1", "SoBan")
    cols = ["Ngày", "Mã phiếu", "Tên hàng", "SL", "Đơn giá", "Thành tiền"]
    a = Table("So", "So.xlsx", ["BanHang"], cols, [["1/1/2025", "P1", "A", 1, 1, 1]], [("BanHang", 2)])
    b = Table("So", "So.xlsx", ["NhapHang"], cols, [["1/1/2025", "N1", "A", 1, 1, 1]], [("NhapHang", 2)])
    assert len(merge_sheets([a, b])) == 2
    c = Table("So", "So.xlsx", ["T01"], cols, [["1/1/2025", "P1", "A", 1, 1, 1]], [("T01", 2)])
    d = Table("So", "So.xlsx", ["T02"], cols, [["1/2/2025", "P2", "A", 1, 1, 1]], [("T02", 2)])
    assert len(merge_sheets([c, d])) == 1


def test_b4_dong_trong_trong_questions(tmp_path):
    split = tmp_path / "split"
    split.mkdir()
    q = {"id": "q1", "business_id": "x", "question": "doanh thu", "as_of_date": "2026-01-01"}
    (split / "questions.jsonl").write_text("﻿" + json.dumps(q) + "\n\n\n", encoding="utf-8")
    out = tmp_path / "a.jsonl"
    out.write_text('{"id": "q0", "type": "abstain"}\n{"id": "q', encoding="utf-8")       # dòng ghi dở
    code = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    env = dict(os.environ, DATAMATE_LLM_URL="", PYTHONPATH=code)
    r = subprocess.run([sys.executable, "-m", "datamate.query.answer", str(split), str(tmp_path / "db"), "--out", str(out)],
                       capture_output=True, text=True, env=env, cwd=code, timeout=120)
    assert "JSONDecodeError" not in r.stderr, r.stderr[-500:]
