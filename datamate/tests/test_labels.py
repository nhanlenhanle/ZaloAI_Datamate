"""Test LLM xếp nhãn lạ (loader/labels.py) với LLM giả: chỉ nhận mã hợp lệ, không chắc thì để trống."""
import json

import pandas as pd
import pytest

from datamate.loader import labels
from datamate.loader.build import add_code_norms, add_customer_cols, add_status_norm


@pytest.fixture
def fake_llm(monkeypatch):
    """LLM giả trả lời theo bảng `answers`; ghi lại các prompt nhận được."""
    answers, prompts = {}, []

    def chat(system, user, **kw):
        prompts.append(user)
        return json.dumps({k: v for k, v in answers.items() if f'"{k}"' in user}, ensure_ascii=False)
    monkeypatch.setattr(labels, "ENABLED", True)
    monkeypatch.setattr(labels.llm, "available", lambda: True)
    monkeypatch.setattr(labels.llm, "chat", chat)
    return answers, prompts


def test_trang_thai_la_hoi_llm_theo_nhan(fake_llm):
    answers, prompts = fake_llm
    answers.update({"Đã chốt": "hoan_thanh", "Bỏ đơn": "huy", "Đã gửi bưu điện": "dang_giao"})
    df = pd.DataFrame({"order_id": ["1", "2", "3", "4", "5"],
                       "status": ["Đã chốt", "Đã chốt", "Bỏ đơn", "Đã gửi bưu điện", "Thành công"]})
    add_status_norm(df)
    assert df.status_norm.tolist() == ["hoan_thanh", "hoan_thanh", "huy", "dang_giao", "hoan_thanh"]
    # chỉ gửi nhãn luật không nhận ra, mỗi nhãn một lần kèm số dòng
    assert len(prompts) == 1 and '"Thành công"' not in prompts[0] and '"Đã chốt" (2)' in prompts[0]


def test_nhan_chiem_da_so_khong_tin_la_huy(fake_llm):
    answers, _ = fake_llm
    answers.update({"Đã chốt": "huy"})          # LLM sai: nhãn của 3/4 số đơn mà là huỷ
    df = pd.DataFrame({"order_id": ["1", "2", "3", "4"], "status": ["Đã chốt", "Đã chốt", "Đã chốt", "Huỷ"]})
    add_status_norm(df)
    assert df.status_norm[:3].isna().all() and df.status_norm[3] == "huy"


def test_ma_khong_hop_le_bi_bo(fake_llm):
    answers, _ = fake_llm
    answers.update({"Tiền tươi": "tien_mat", "Ký sổ": "no_nan"})      # 'no_nan' không phải mã
    df = pd.DataFrame({"payment_method": ["Tiền tươi", "Ký sổ", "CK", None]})
    add_code_norms(df)
    assert df.payment_norm.tolist() == ["tien_mat", "khac", "chuyen_khoan", None]


def test_khong_bat_llm_thi_nhu_chi_co_luat(monkeypatch):
    monkeypatch.setattr(labels, "ENABLED", False)
    df = pd.DataFrame({"order_id": ["1"], "status": ["Đã chốt"]})
    add_status_norm(df)
    assert df.status_norm.isna().all()


def test_nhan_khach_le_rieng_cua_shop(fake_llm):
    answers, _ = fake_llm
    answers.update({"Khách qua đường": True, "Nguyễn Văn An": False})
    df = pd.DataFrame({"customer_name": ["Khách qua đường"] * 3 + ["Nguyễn Văn An"] * 2 + ["Khách lẻ"]})
    add_customer_cols(df)
    assert df.is_walk_in.tolist() == [True, True, True, False, False, True]
    assert df.customer_key.isna().tolist() == [True, True, True, False, False, True]


def test_ghi_chu_chi_nhan_khi_noi_ro_trang_thai(fake_llm):
    answers, _ = fake_llm
    answers.update({"Khách bom": "huy", "Giao trước 5h": "khong_nhac"})
    df = pd.DataFrame({"order_id": ["1", "2", "3"], "order_note": ["Khách bom", "Giao trước 5h", None]})
    add_status_norm(df)
    assert df.status_norm.tolist() == ["huy", "hoan_thanh", "hoan_thanh"]


# ---------------------------------------------------------------- quy ước README (loader/conventions.py)

from datamate.loader.build import Built, apply_money_scale, build_shop          # noqa: E402
from datamate.loader.conventions import _validate                              # noqa: E402
from datamate.loader.readme import ReadmeInfo                                   # noqa: E402


def test_quy_uoc_chi_nhan_gia_tri_hop_le():
    cols = {"ban_hang": ["Ngày", "Mặt hàng", "Ghi chú"]}
    out = _validate({"don_vi_tien": 7, "cot_trang_thai": "Ghi chú", "khong_ghi": ["ma_don", "mau_sac"],
                     "nhan_khach_le": ["Khách qua đường"], "khac": []}, cols)
    assert out == {"status_column": "Ghi chú", "not_recorded": ["ma_don"], "walk_in_labels": ["Khách qua đường"]}
    assert _validate({"don_vi_tien": 1000, "cot_trang_thai": "Cột không có"}, cols) == {"money_scale": 1000}


def _sales(**cols) -> Built:
    df = pd.DataFrame(cols)
    meta = [{"column": c, "original": c, "canonical": c, "map_source": "readme_col", "kind": "number",
             "description": None, "note": None} for c in df.columns]
    return Built("ban_hang", "ban_hang", "sales_lines", df, meta, ["ban_hang"])


def test_tien_nghin_kiem_bang_du_lieu():
    b = _sales(unit_price=[12.5, 30.0], line_amount=[25.0, 30.0], qty=[2, 1])
    assert apply_money_scale([b], 1000) == {"money_scale": 1000}
    assert b.df.unit_price.tolist() == [12500, 30000] and b.df.qty.tolist() == [2, 1]
    # README nói nghìn mà dữ liệu đã là đồng: không nhân
    b = _sales(unit_price=[12500.0, 30000.0], line_amount=[25000.0, 30000.0])
    assert "money_scale_warning" in apply_money_scale([b], 1000) and b.df.unit_price.tolist() == [12500, 30000]


def test_trang_thai_o_cot_readme_chi_ra(tmp_path):
    df = pd.DataFrame({"order_id": ["1", "2", "3"], "order_date": pd.to_datetime(["2025-01-01"] * 3),
                       "product_name": ["A", "B", "C"], "line_amount": [10, 20, 30],
                       "note": ["giao sớm", "Khách hủy đơn", None],
                       "_src_file": ["so.xlsx"] * 3, "_src_sheet": ["T1"] * 3, "_src_row": [2, 3, 4]})
    meta = [{"column": c, "original": "Ghi chú" if c == "note" else c, "canonical": c, "map_source": "readme_col",
             "kind": "text", "description": None, "note": None} for c in df.columns if not c.startswith("_src")]
    items = [Built("", "ban_hang", "", df, meta, ["ban_hang"])]
    db = str(tmp_path / "x.duckdb")
    build_shop("x", items, ReadmeInfo(shop="x"), [], db, conventions={"status_column": "Ghi chú"})
    import duckdb
    got = duckdb.connect(db).execute("SELECT order_id, status_norm FROM ban_hang ORDER BY 1").fetchall()
    assert got == [("1", "hoan_thanh"), ("2", "huy"), ("3", "hoan_thanh")]


def test_khong_ghi_mau_thuan_du_lieu_thi_bo():
    from datamate.loader.conventions import drop_contradicted
    conv = {"not_recorded": ["ma_don", "ten_khach", "gio_ban"], "money_scale": 1000}
    out = drop_contradicted(conv, {"order_id", "customer_name", "line_amount"})
    assert out["not_recorded"] == ["gio_ban"] and out["not_recorded_dropped"] == ["ma_don", "ten_khach"]
    assert out["money_scale"] == 1000


# ---------------------------------------------------------------- sửa ô không đọc được (loader/repair.py)

from datamate.loader import repair                                              # noqa: E402
from datamate.loader.parsers import parse_column                                # noqa: E402


@pytest.fixture
def fake_repair(monkeypatch):
    answers = {}

    def chat(system, user, **kw):
        return json.dumps({k: v for k, v in answers.items() if f'"{k}"' in user}, ensure_ascii=False)
    monkeypatch.setattr(repair, "ENABLED", True)
    monkeypatch.setattr(repair.llm, "available", lambda: True)
    monkeypatch.setattr(repair.llm, "chat", chat)
    return answers


def test_sua_o_so_viet_bang_chu(fake_repair):
    fake_repair.update({"hai trăm nghìn": "200000", "khoảng 50k": "50000", "???": None,
                        "x9": "900000000000"})                  # lệch cỡ: không nhận
    raw = ["120.000", "45.000", "300.000", "hai trăm nghìn", "khoảng 50k", "???", "x9"] + ["10.000"] * 50
    res = repair.repair_column("Thành tiền", raw, [None] * len(raw), parse_column("Thành tiền", raw))
    assert res["kind"] == "number" and res["values"][3:7] == [200000, 50000, None, None]
    assert res["repaired"] == 2 and res["n_fail"] == 2


def test_cot_roi_ve_chu_duoc_cuu_thanh_so(fake_repair):
    raw = ["2", "3", "x2", "x5", "1", "4", "x3", "2", "5", "1"]       # 30% ô "x2": cả cột rơi về chữ
    fake_repair.update({"x2": "2", "x5": "5", "x3": "3"})
    res0 = parse_column("SL", raw)
    assert res0["kind"] == "text"
    res = repair.repair_column("SL", raw, [None] * len(raw), res0)
    assert res["kind"] == "number" and res["values"] == [2, 3, 2, 5, 1, 4, 3, 2, 5, 1]


def test_tat_thi_khong_sua(monkeypatch):
    monkeypatch.setattr(repair, "ENABLED", False)
    raw = ["120.000", "hai trăm nghìn"] + ["10.000"] * 30
    res0 = parse_column("Tiền", raw)
    assert repair.repair_column("Tiền", raw, [None] * len(raw), res0) is res0


def test_luat_mo_rong_doc_so_chu_va_o_kem_chu():
    from datamate.loader.repair import loose_date, loose_number, parse_vn_words
    assert parse_vn_words("hai trăm bốn mươi lăm nghìn") == 245000
    assert parse_vn_words("mot trieu khong tram le nam nghin") == 1005000      # không dấu
    assert parse_vn_words("hai mươi mốt ngàn") == 21000
    assert parse_vn_words("Nguyễn Văn An") is None and parse_vn_words("hai ba") is None
    assert loose_number("x2") == 2 and loose_number("245.000đ (đã CK)") == 245000
    assert loose_number("30.000-") is None and loose_number("2 hộp 30 viên") is None    # không đoán
    assert loose_date("Mar 05, 2025").day == 5 and loose_date("Thứ 4, 05/03/2025").month == 3
    assert loose_date("Foo 5, 2025") is None


def test_cot_sdt_khong_bi_doi_thanh_so(fake_repair):
    raw = ["0912345678", "0987654321", "chưa có"] + ["0901234567"] * 20
    res0 = parse_column("SĐT", raw)
    assert repair.repair_column("SĐT", raw, [None] * len(raw), res0) is res0


def test_quy_uoc_json_bi_cat_van_nhat_duoc_o_co_dinh():
    from datamate.loader.conventions import _salvage
    text = ('{\n  "don_vi_tien": 1000,\n  "cot_trang_thai": null,\n  "trong_la_hoan_thanh": null,\n'
            '  "nhan_khach_le": [],\n  "khong_ghi": ["gio_ban"],\n  "khac": [\n    "Mã đơn được tạo bằng cách nối tr')
    assert _salvage(text) == {"don_vi_tien": 1000.0, "cot_trang_thai": None, "trong_la_hoan_thanh": None,
                              "nhan_khach_le": [], "khong_ghi": ["gio_ban"]}
    assert _validate(_salvage(text), {"t": ["a"]}) == {"money_scale": 1000, "not_recorded": ["gio_ban"]}
