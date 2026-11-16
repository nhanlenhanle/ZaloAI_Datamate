"""Test mapping: mô tả README (lấy nguyên từ data) -> tên chuẩn, và các luật ngữ cảnh."""
import pytest

from datamate.loader.mapping import desc_to_canonical, map_table
from datamate.loader.readme import ColumnDoc, file_matches


@pytest.mark.parametrize("desc, canon", [
    ("mã đơn", "order_id"),
    ("số hoá đơn, ghi ở mọi dòng của hoá đơn kể cả dòng Voucher / Dùng điểm / Phí ship", "order_id"),
    ("số thứ tự đơn (hoá đơn) trong sổ", "order_id"),
    ("số thứ tự dòng trong đơn", "line_no"),           # từng bị nhầm thành order_id
    ("số thứ tự dòng trong phiếu nhập", "line_no"),
    ("tên hàng", "product_name"),
    ("tên hàng (file chỉ có mặt hàng có đơn vị lớn)", "product_name"),
    ("hàng bán, có thể ghi tắt (tra ở sheet Ghi tắt)", "product_name"),
    ("mã hàng", "product_id"),
    ("đơn vị cơ bản", "base_unit"),
    ("đơn vị tính", "unit"),
    ("đơn vị lớn (thùng, hộp, tấn...)", "big_unit"),
    ("hệ số: số đơn vị cơ bản trong 1 đơn vị lớn", "conv_factor"),
    ("số lượng", "qty"),
    ("số lượng đã đổi ra đơn vị cơ bản", "qty_base"),  # từng bị nhầm thành qty
    ("số lượng nhập (đơn vị cơ bản)", "qty_base"),
    ("số lượng bán lấy từ lô (đơn vị cơ bản)", "qty_base"),
    ("số lượng khách trả lại (đơn vị cơ bản); lớn hơn 0: đơn đó có trả hàng", "qty_returned_base"),
    ("tồn kho (đơn vị cơ bản)", "stock_qty"),
    ("đơn giá", "unit_price"),
    ("giá nhập một đơn vị (theo đơn vị nhập của dòng)", "unit_price"),
    ("thành tiền sau giảm", "line_amount"),
    ("tiền nhập của cả dòng", "line_amount"),
    ("giá vốn một đơn vị bán", "unit_cost"),
    ("ngày bán", "order_date"),
    ("thời điểm đặt đơn (ngày giờ)", "order_time"),
    ("giờ đặt đơn (dòng trả hàng: lúc trả)", "order_time"),
    ("trạng thái đơn", "status"),
    ("tên khách (Khách lẻ nếu không lưu)", "customer_name"),
    ("mã khách (trống nếu khách lẻ)", "customer_id"),
    ("tổng tiền hàng của đơn (cộng thành tiền các dòng), trước giảm giá của đơn", "order_subtotal"),
    ("giảm giá của cả đơn (lặp lại ở mọi dòng của đơn)", "order_discount"),
    ("số khách phải trả cho cả đơn (đã tính giảm giá của đơn và phí giao)", "order_total"),
    ("tổng tiền của cả phiếu nhập", "purchase_total"),
    ("tổng tiền phiếu nhập", "purchase_total"),
    ("tổng tiền cả phiếu", "money"),          # phiếu không rõ loại: ngữ cảnh bảng quyết
    # cụm cụ thể đổi nghĩa chữ chung
    ("mã đơn nhập hàng", "purchase_id"), ("mã đơn trả hàng", "return_id"), ("tổng tiền đơn nhập", "purchase_total"),
    ("trạng thái đơn nhập", "purchase_status"), ("số lượng khách", "guests"), ("số lượng khách mua", "qty"),
    ("số lượng tồn", "stock_qty"), ("số lượng trả lại", "qty_returned"), ("thành tiền của cả đơn", "money"),
    ("ngày nhập dữ liệu vào phần mềm", "created_date"), ("ngày nhập kho", "purchase_date"),
    ("ngày trả hàng", "return_date"),
    ("số tiền trả lần đó", "payment_amount"),
    ("phí giao hàng của cả đơn (lặp lại ở mọi dòng của đơn)", "shipping_fee"),
    ("hình thức thanh toán của đơn: cash tiền mặt, transfer chuyển khoản, ewallet ví điện tử, cod giao hàng thu tiền, debt ghi nợ", "payment_method"),
    ("mã phiếu nhập", "purchase_id"),
    ("ngày nhập", "purchase_date"),
    ("số lô", "batch_id"),
    ("hạn sử dụng", "expiry_date"),
    ("hoạt chất (trống với thực phẩm chức năng, vật tư)", "active_ingredient"),
    ("thuốc kê đơn", "is_prescription"),
    ("đợt giao (1, 2, 3)", "delivery_round"),
    ("số ngày được nợ", "credit_days"),
    ("hạn thanh toán", "due_date"),
    ("ghi chú của đơn; đơn huỷ hoặc đang giao được ghi ở đây, không có cột trạng thái riêng", "order_note"),
    ("tồn sau lần nhập/bán/trả đó, theo đơn vị cơ bản", "stock_after"),
    ("ngày tạo khách trên phần mềm", "created_date"),
])
def test_mo_ta_readme(desc, canon):
    assert desc_to_canonical(desc) == (True, canon)


def test_mo_ta_train_khong_doi_nghia():
    """Mọi mô tả cột trong README train giữ đúng tên chuẩn đã kiểm (tests/desc_baseline_train.json)."""
    import json
    import os
    base = json.load(open(os.path.join(os.path.dirname(__file__), "desc_baseline_train.json"), encoding="utf-8"))
    assert {d: list(desc_to_canonical(d)) for d in base} == base


def test_cot_trong_theo_readme():
    assert desc_to_canonical("cột trống, không có dữ liệu") == (True, None)


def test_mau_ten_file():
    assert file_matches("BanHang_T<tháng>_<năm>.xlsx", "BanHang_T10_2025.xlsx")
    assert file_matches("Danh sách hàng hóa.xlsx", "Danh sách hàng hóa.xlsx")
    assert not file_matches("DonHang_ChiTiet.xlsx", "DonHang_ChiTiet_1.xlsx")


def _map(cols, kinds, samples=None, docs=(), name_dict=None):
    ms = map_table("t", cols, kinds, samples or {}, list(docs), name_dict or {})
    return {m.column: m.canonical for m in ms}


def test_ten_chung_theo_ngu_canh():
    docs = [ColumnDoc("f", None, "Mã", "mã khách", "columns"), ColumnDoc("f", None, "Tên", "tên", "columns")]
    assert _map(["Mã", "Tên"], {"Mã": "text", "Tên": "text"}, docs=docs) == {"Mã": "customer_id", "Tên": "customer_name"}


def test_gia_tri_thang_tu_dien_voi_cot_ma():
    # biz_106 SoQuy: 'Mã phiếu' từ điển nói order_id nhưng giá trị là PAY...
    got = _map(["Mã phiếu"], {"Mã phiếu": "text"}, samples={"Mã phiếu": ["PAY000001", "PAY000002", "PAY000003"]},
               name_dict={"ma phieu": "order_id"})
    assert got == {"Mã phiếu": "payment_id"}


def test_kieu_khong_khop_thi_giu_ten_goc():
    docs = [ColumnDoc("f", None, "Tiền", "thành tiền sau giảm", "columns")]
    assert _map(["Tiền"], {"Tiền": "text"}, docs=docs) == {"Tiền": None}


def test_trung_ten_chuan_giu_cot_bang_chung_manh_hon():
    docs = [ColumnDoc("f", None, "SL", "số lượng", "columns")]
    got = _map(["SL", "Số lượng (2)"], {"SL": "number", "Số lượng (2)": "number"}, docs=docs,
               name_dict={"so luong (2)": "qty"})
    assert got == {"SL": "qty", "Số lượng (2)": None}


def test_thoi_gian_theo_loai_bang():
    nd = {"thoi gian": "order_date", "ma phieu": "payment_id", "ma hoa don": "order_id", "ma nhap hang": "purchase_id"}
    k = {"Thời gian": "datetime", "Mã phiếu": "text", "Mã hóa đơn": "text", "Mã nhập hàng": "text"}
    # biz_106 SoQuy: có mã phiếu thu -> thời điểm thu
    assert _map(["Mã phiếu", "Thời gian", "Mã hóa đơn"], k, name_dict=nd)["Thời gian"] == "payment_date"
    # biz_106 DanhSachNhapHang: phiếu nhập -> ngày nhập
    assert _map(["Mã nhập hàng", "Thời gian"], k, name_dict=nd)["Thời gian"] == "purchase_date"
    assert _map(["Mã hóa đơn", "Thời gian"], k, name_dict=nd)["Thời gian"] == "order_date"


def test_trang_thai_khong_phai_don_ban():
    nd = {"trang thai": "status", "ma khach hang": "customer_id", "ma nhap hang": "purchase_id"}
    k = {"Trạng thái": "text", "Mã khách hàng": "text", "Mã nhập hàng": "text"}
    assert _map(["Mã khách hàng", "Trạng thái"], k, name_dict=nd)["Trạng thái"] is None
    assert _map(["Mã nhập hàng", "Trạng thái"], k, name_dict=nd)["Trạng thái"] == "purchase_status"


def test_so_ban_ghi_tay_khong_ma_don_van_giu_trang_thai():
    # biz_107: sổ bán không có mã đơn nhưng có số lượng, thành tiền
    nd = {"trang thai xu ly": "status", "so luong": "qty", "tong tien": "line_amount"}
    k = {"Trạng thái xử lý": "text", "Số lượng": "number", "Tổng tiền": "number"}
    assert _map(["Trạng thái xử lý", "Số lượng", "Tổng tiền"], k, name_dict=nd)["Trạng thái xử lý"] == "status"


def test_luat_gia_tri():
    n = 30
    raw = {"Kết quả": ["Xong"] * 25 + ["Đã hủy"] * 5,
           "Đối tác": ["Khách lẻ"] * 10 + [f"Khách {i}" for i in range(20)],
           "ĐV": ["chai", "lon", "hộp"] * 10,
           "PTTT": ["Tiền mặt", "Chuyển khoản", "Ghi nợ"] * 10,
           "SL": [2] * n, "Giá": [10000] * n, "Tiền": [20000] * (n - 3) + [18000] * 3}
    kinds = {"Kết quả": "text", "Đối tác": "text", "ĐV": "text", "PTTT": "text",
             "SL": "number", "Giá": "number", "Tiền": "number"}
    nd = {"sl": "qty", "gia": "unit_price"}
    got = {m.column: m.canonical for m in map_table("t", list(raw), kinds, raw, [], nd, raw)}
    assert got == {"Kết quả": "status", "Đối tác": "customer_name", "ĐV": "unit", "PTTT": "payment_method",
                   "SL": "qty", "Giá": "unit_price", "Tiền": "line_amount"}


def test_nhom_khach_khong_phai_ten_khach():
    # biz_129 "Nhóm": "lẻ" trùng cách ghi khách lẻ nhưng cột chỉ có vài giá trị
    raw = {"Nhóm": ["lẻ", "thân thiết", "sỉ"] * 10}
    got = {m.column: m.canonical for m in map_table("t", ["Nhóm"], {"Nhóm": "text"}, raw, [], {}, raw)}
    assert got == {"Nhóm": None}


def test_giam_gia_hoa_don():
    nd = {"giam gia hd": "discount", "ma hang": "product_id"}
    k = {"Giảm giá HĐ": "number", "Mã hàng": "text"}
    assert _map(["Mã hàng", "Giảm giá HĐ"], k, name_dict=nd)["Giảm giá HĐ"] == "order_discount"


def test_khoa_tu_dien():
    from datamate.loader.mapping import name_key
    assert name_key("TenSanPham") == "ten san pham"       # sqlite biz_123
    assert name_key("ten_san_pham") == "ten san pham"
    assert name_key("Tên sản phẩm") == "ten san pham"
    assert name_key("Mã hàng") == "ma hang"               # không tách nhầm chữ thường có dấu
    assert name_key("SLQuyDoi") == "slquy doi"            # chữ hoa liền nhau giữ nguyên


def _ctx(cols, nd, kinds=None):
    k = kinds or {c: "text" for c in cols}
    return _map(cols, k, name_dict=nd)


def test_don_vi_theo_so_luong_cua_bang():
    nd = {"dvt": "unit", "ten hang": "product_name", "so luong": "qty", "sl co ban": "qty_base",
          "ma don": "order_id", "dot giao": "delivery_round"}
    num = {"Số lượng": "number", "SL cơ bản": "number", "Đợt giao": "number"}
    assert _ctx(["Tên hàng", "ĐVT"], nd)["ĐVT"] == "base_unit"                       # danh mục
    assert _ctx(["Mã đơn", "Tên hàng", "Số lượng", "ĐVT"], nd,
                {"Mã đơn": "text", "Tên hàng": "text", "ĐVT": "text", **num})["ĐVT"] == "unit"   # dòng bán
    assert _ctx(["Mã đơn", "Tên hàng", "SL cơ bản", "Đợt giao", "ĐVT"], nd,
                {"Mã đơn": "text", "Tên hàng": "text", "ĐVT": "text", **num})["ĐVT"] == "base_unit"  # phiếu giao
    assert _ctx(["Mã đơn", "Tên hàng", "SL cơ bản", "ĐVT"], nd,
                {"Mã đơn": "text", "Tên hàng": "text", "ĐVT": "text", **num})["ĐVT"] == "unit"   # sổ bán có SL cơ bản


def test_ten_cot_noi_ro_doi_tuong():
    nd = {"ten khach hang": "name", "ten san pham": "name", "khach hang (ten)": "product_name",
          "don vi co ban": "unit", "he so": "conv_factor"}
    got = _ctx(["Tên khách hàng", "Tên sản phẩm"], nd)
    assert got == {"Tên khách hàng": "customer_name", "Tên sản phẩm": "product_name"}
    assert _ctx(["Khách hàng (tên)"], nd)["Khách hàng (tên)"] == "customer_name"
    got = _ctx(["Đơn vị cơ bản", "Hệ số"], nd, {"Đơn vị cơ bản": "text", "Hệ số": "number"})
    assert got["Đơn vị cơ bản"] == "base_unit"


def test_tien_va_gia_theo_ngu_canh():
    nd = {"tong tien": "money", "gia": "unit_price", "ten hang": "product_name", "so luong": "qty",
          "ma don": "order_id", "ma phieu": "payment_id"}
    k = {"Tổng tiền": "number", "Giá": "number", "Số lượng": "number", "Tên hàng": "text", "Mã đơn": "text",
         "Mã phiếu": "text"}
    assert _ctx(["Mã đơn", "Tổng tiền"], nd, k)["Tổng tiền"] == "order_total"
    assert _ctx(["Mã đơn", "Tên hàng", "Số lượng", "Tổng tiền"], nd, k)["Tổng tiền"] == "line_amount"
    assert _ctx(["Mã phiếu", "Mã đơn", "Tổng tiền"], nd, k)["Tổng tiền"] == "payment_amount"
    assert _ctx(["Tên hàng", "Giá"], nd, k)["Giá"] == "price"
    assert _ctx(["Mã đơn", "Tên hàng", "Số lượng", "Giá"], nd, k)["Giá"] == "unit_price"


def test_tien_ca_phieu_theo_ngu_canh():
    k = {"Tiền": "number", "Mã nhập": "text", "Ngày": "datetime"}
    docs = [ColumnDoc("f", None, "Tiền", "tổng tiền cả phiếu", "columns")]
    # sổ phiếu không có mã nhập, không có dòng hàng: tiền cả phiếu (đơn), không phải tiền nhập hàng
    assert _map(["Ngày", "Tiền"], k, docs=docs)["Tiền"] == "order_total"
    docs2 = docs + [ColumnDoc("f", None, "Mã nhập", "mã phiếu nhập", "columns")]
    assert _map(["Mã nhập", "Tiền"], k, docs=docs2)["Tiền"] == "purchase_total"
    # sổ bán có dòng hàng, cột "tổng tiền cả phiếu" lặp ở mọi dòng: tiền cả đơn, không phải thành tiền dòng
    k3 = {"Tổng phiếu": "number", "SL": "number", "Hàng": "text", "Mã": "text"}
    docs3 = [ColumnDoc("f", None, "Tổng phiếu", "tổng tiền cả phiếu", "columns"),
             ColumnDoc("f", None, "SL", "số lượng", "columns"), ColumnDoc("f", None, "Hàng", "tên hàng", "columns"),
             ColumnDoc("f", None, "Mã", "mã đơn", "columns")]
    assert _map(["Mã", "Hàng", "SL", "Tổng phiếu"], k3, docs=docs3)["Tổng phiếu"] == "order_total"


def test_thoi_gian_gop_ho_khi_bo_phieu():
    from datamate.loader.mapping import build_name_dict
    from datamate.loader.readme import ReadmeInfo
    docs = [ColumnDoc("a", None, "Thời gian", "ngày bán", "columns")] * 5 + \
           [ColumnDoc("b", None, "Thời gian", "ngày nhập", "columns")] * 4
    assert build_name_dict([ReadmeInfo("x", columns=docs)])["thoi gian"] == "order_date"


def test_trang_thai_thanh_toan_khong_phai_trang_thai_don():
    nd = {"trang thai thanh toan": "status", "trang thai hddt": "status", "trang thai": "status", "ma don": "order_id"}
    k = {"Mã đơn": "text", "Trạng thái": "text", "Trạng thái thanh toán": "text", "Trạng thái HĐĐT": "text"}
    got = _map(["Mã đơn", "Trạng thái", "Trạng thái thanh toán", "Trạng thái HĐĐT"], k, name_dict=nd)
    assert got["Trạng thái"] == "status" and got["Trạng thái thanh toán"] is None and got["Trạng thái HĐĐT"] is None
    # "TT" mơ hồ (trạng thái / thanh toán / thành tiền): cột "Ghi chú TT" toàn giá trị trạng thái đơn -> status
    raw = {"Ghi chú TT": ["xong"] * 20 + ["Đã hủy"] * 5 + ["trả hàng"] * 5, "SL": [1] * 30, "Hàng": ["A"] * 30}
    kk = {"Ghi chú TT": "text", "SL": "number", "Hàng": "text"}
    got = {m.column: m.canonical for m in map_table("t", list(raw), kk, raw, [], {"sl": "qty", "hang": "product_name"}, raw)}
    assert got["Ghi chú TT"] == "status"


def test_don_vi_quy_doi_theo_ten_cot():
    nd = {"ten san pham": "product_name", "ti le quy doi": "conv_factor"}
    raw = {"Tên sản phẩm": ["Coca"] * 6, "Đơn vị quy đổi": ["thùng", "lốc"] * 3, "Tỉ lệ quy đổi": [24, 6] * 3,
           "Đơn vị cơ bản": ["lon"] * 6}
    kk = {"Tên sản phẩm": "text", "Đơn vị quy đổi": "text", "Tỉ lệ quy đổi": "number", "Đơn vị cơ bản": "text"}
    got = {m.column: m.canonical for m in map_table("t", list(raw), kk, raw, [], nd, raw)}
    assert got["Đơn vị quy đổi"] == "big_unit" and got["Đơn vị cơ bản"] == "base_unit"


def test_ten_goi_chung_theo_ma_cua_bang():
    # POS sqlite: cột "TenGoi" ở bảng hàng / khách / NCC / nhân viên / chi nhánh
    k = {"MaHang": "text", "TenGoi": "text", "MaKH": "text", "MaNCC": "text", "MaNV": "text"}
    nd = {"ma hang": "product_id", "ma kh": "customer_id", "ma ncc": "supplier_id", "ma nv": "staff_id"}
    assert _map(["MaHang", "TenGoi"], k, name_dict=nd)["TenGoi"] == "product_name"
    assert _map(["MaKH", "TenGoi"], k, name_dict=nd)["TenGoi"] == "customer_name"
    assert _map(["MaNCC", "TenGoi"], k, name_dict=nd)["TenGoi"] == "supplier_name"
    assert _map(["MaNV", "TenGoi"], k, name_dict=nd)["TenGoi"] == "staff_name"
    assert _map(["TenGoi"], k, name_dict=nd)["TenGoi"] == "name"


# ---- lượt LLM: kết quả model giả lập, chỉ kiểm phần hậu kiểm (không cần server) ----
from datamate.loader import mapping as _mp
from datamate.loader.mapping import DEFAULT_UNITS, TableInput, canonical_vocab


def _llm_run(monkeypatch, columns, kinds, raw, answers, known=None):
    monkeypatch.setattr(_mp, "llm_map", lambda *a, **k: {c: {"nghia": "x", "ten": t} for c, t in answers.items()})
    t = TableInput("t", "", [], columns, kinds, raw, raw)
    maps = [_mp.ColumnMap("t", c, (known or {}).get(c), "name_dict" if c in (known or {}) else None, None)
            for c in columns]
    _mp._llm_pass([t], {"t": maps}, DEFAULT_UNITS)
    return {m.column: m.canonical for m in maps}


def test_tu_dien_ten_chuan_doc_tu_schema():
    v = canonical_vocab()
    assert {"order_id", "qty_base", "order_total", "is_prescription"} <= set(v) and "money" not in v


def test_llm_so_luong_bang_khong_co_don_vi_la_co_ban(monkeypatch):
    cols = ["Mã đơn", "Hàng", "SL giao"]
    out = _llm_run(monkeypatch, cols, {"Mã đơn": "text", "Hàng": "text", "SL giao": "number"},
                   {c: ["a"] * 5 for c in cols}, {"SL giao": "qty"},
                   known={"Mã đơn": "order_id", "Hàng": "product_name"})
    assert out["SL giao"] == "qty_base"


def test_llm_thoi_diem_dau_la_ngay_dat_o_bang_ban(monkeypatch):
    cols = ["Mã HĐ", "Tổng", "Thời gian", "Thời gian tạo"]
    kinds = {"Mã HĐ": "text", "Tổng": "number", "Thời gian": "datetime", "Thời gian tạo": "datetime"}
    out = _llm_run(monkeypatch, cols, kinds, {c: ["a"] * 5 for c in cols},
                   {"Thời gian": "order_time", "Thời gian tạo": "created_date"},
                   known={"Mã HĐ": "order_id", "Tổng": "order_total"})
    assert out["Thời gian"] == "order_date" and out["Thời gian tạo"] == "order_time"
    # danh mục hàng: "Thời gian tạo" vẫn là ngày tạo
    cols = ["Mã hàng", "Tên", "Thời gian tạo"]
    out = _llm_run(monkeypatch, cols, {"Mã hàng": "text", "Tên": "text", "Thời gian tạo": "datetime"},
                   {c: ["a"] * 5 for c in cols}, {"Thời gian tạo": "created_date"},
                   known={"Mã hàng": "product_id", "Tên": "product_name"})
    assert out["Thời gian tạo"] == "created_date"


def test_llm_bi_chan_khi_sai_gia_tri_hoac_doi_thuc_the(monkeypatch):
    cols = ["Mã KH", "Tên KH", "Bán theo đơn", "Tổng điểm", "Tồn lớn nhất"]
    kinds = {c: "text" for c in cols} | {"Tồn lớn nhất": "number", "Tổng điểm": "number"}
    raw = {c: ["a"] * 5 for c in cols} | {"Bán theo đơn": ["Có", "Không"] * 3}
    out = _llm_run(monkeypatch, cols, kinds, raw,
                   {"Bán theo đơn": "unit", "Tổng điểm": "stock_qty", "Tồn lớn nhất": "ngưỡng_tồn"},
                   known={"Mã KH": "customer_id", "Tên KH": "customer_name"})
    # giá trị không phải đơn vị tính; danh sách khách -> bảng tồn kho; tên ngoài schema
    assert out["Bán theo đơn"] is None and out["Tổng điểm"] is None and out["Tồn lớn nhất"] is None


def test_llm_khong_bien_bang_la_thanh_bang_ban(monkeypatch):
    # sổ chi phí: luật chưa nhận ra -> "Ngày chi" không được thành order_date (bảng sẽ thành bảng đơn)
    cols = ["Ngày chi", "Số tiền", "Nội dung"]
    out = _llm_run(monkeypatch, cols, {"Ngày chi": "datetime", "Số tiền": "number", "Nội dung": "text"},
                   {c: ["a"] * 5 for c in cols}, {"Ngày chi": "order_date", "Số tiền": "order_total", "Nội dung": "note"})
    assert out["Ngày chi"] is None or out["Số tiền"] is None
    assert out["Nội dung"] == "note"


def test_llm_loi_mang_giu_ket_qua_luat(monkeypatch):
    def boom(*a, **k):
        raise TimeoutError
    monkeypatch.setattr(_mp, "llm_map", boom)
    t = TableInput("t", "", [], ["X"], {"X": "text"}, {"X": ["a"]}, {"X": ["a"]})
    maps = [_mp.ColumnMap("t", "X", None, None, None)]
    _mp._llm_pass([t], {"t": maps}, DEFAULT_UNITS)
    assert maps[0].canonical is None and "LLM lỗi" in maps[0].note


def test_trung_chu_khi_bo_dau_khong_dung_tu_dien():
    # "Hạng" (hạng khách) bỏ dấu trùng "Hàng"; "Hoá đơn" / "Hóa đơn" chỉ khác chỗ đặt dấu là cùng chữ
    from datamate.loader.mapping import accent_clash, build_name_dict, name_key
    from datamate.loader.readme import ReadmeInfo
    info = ReadmeInfo("x")
    info.columns = [ColumnDoc("f.xlsx", None, "Hàng", "tên hàng", "columns"),
                    ColumnDoc("f.xlsx", None, "Hoá đơn", "mã đơn", "columns")]
    nd = build_name_dict([info])
    assert nd[name_key("Hàng")] == "product_name"
    assert accent_clash("Hạng", name_key("Hạng"), nd)
    assert not accent_clash("Hàng", name_key("Hàng"), nd) and not accent_clash("HANG", name_key("HANG"), nd)
    assert not accent_clash("Hóa đơn", name_key("Hóa đơn"), nd)
    maps = map_table("kh", ["Mã KH", "Hạng"], {"Mã KH": "text", "Hạng": "text"},
                     {"Mã KH": ["KH1"] * 5, "Hạng": ["sỉ", "lẻ", "thân thiết", "sỉ", "lẻ"]}, [], nd)
    assert next(m for m in maps if m.column == "Hạng").canonical is None


def test_cot_chu_chung_o_dau_phieu_la_ghi_chu():
    nd = {"ma phieu nhap": "purchase_id", "tong gia tri nhap": "money", "dien giai": "product_name"}
    cols = ["MaPhieuNhap", "TongGiaTriNhap", "DienGiai"]
    maps = map_table("phieu_nhap", cols, {"MaPhieuNhap": "text", "TongGiaTriNhap": "number", "DienGiai": "text"},
                     {"MaPhieuNhap": ["PN1"] * 5, "TongGiaTriNhap": [1] * 5, "DienGiai": ["nhập đầu kỳ"] + [None] * 4},
                     [], nd)
    assert {m.column: m.canonical for m in maps}["DienGiai"] == "note"
    # bảng có dòng hàng thì vẫn là tên hàng
    maps = map_table("so_nhap", ["MaPhieuNhap", "DienGiai", "SL"], {"MaPhieuNhap": "text", "DienGiai": "text", "SL": "number"},
                     {"MaPhieuNhap": ["PN1"] * 5, "DienGiai": ["Xi măng"] * 5, "SL": [1] * 5}, [], nd | {"sl": "qty"})
    assert {m.column: m.canonical for m in maps}["DienGiai"] == "product_name"


def test_danh_sach_ncc_khong_phai_bang_nhap():
    from datamate.loader.build import table_role
    assert table_role({"supplier_id", "supplier_name", "phone"}) == "suppliers"
    assert table_role({"supplier_name", "product_name", "qty", "unit_price"}) == "purchase_lines"
    assert table_role({"purchase_id", "supplier_id", "purchase_total"}) == "purchases"


def test_so_chi_phi():
    from datamate.loader.build import table_role
    nd = {"so tien": "money"}
    cols = ["Ngày chi", "Mục", "So tien"]
    kinds = {"Ngày chi": "datetime", "Mục": "text", "So tien": "number"}
    raw = {"Ngày chi": ["01/01/2025"] * 5, "Mục": ["điện"] * 5, "So tien": [100] * 5}
    out = {m.column: m.canonical for m in map_table("SoTay_ChiPhi", cols, kinds, raw, [], nd)}
    assert out["So tien"] == "expense_amount" and out["Ngày chi"] == "expense_date"
    assert table_role({c for c in out.values() if c}) == "expenses"
    # bảng không phải chi phí: tiền chung vẫn là tiền đơn
    out = {m.column: m.canonical for m in map_table("SoThu", ["Mã đơn", "So tien"], {"Mã đơn": "text", "So tien": "number"},
                                                     {"Mã đơn": ["ORD001"] * 5, "So tien": [1] * 5}, [], nd)}
    assert out["So tien"] == "order_total"


def test_tu_vung_nha_thuoc():
    from datamate.loader.build import table_role
    out = {m.column: m.canonical for m in map_table(
        "thong_tin_thuoc", ["MaHangHoa", "ThanhPhanChinh", "BanTheoDon"],
        {"MaHangHoa": "text", "ThanhPhanChinh": "text", "BanTheoDon": "text"},
        {"MaHangHoa": ["SP001"] * 5, "ThanhPhanChinh": ["Paracetamol"] * 5, "BanTheoDon": ["Có"] * 5}, [], {})}
    assert out["ThanhPhanChinh"] == "active_ingredient" and out["BanTheoDon"] == "is_prescription"
    assert table_role({c for c in out.values() if c}) == "drug_info"


def test_cot_hang_khach_theo_gia_tri_la_nhom_khach():
    nd = {"ma kh": "customer_id"}
    cols = ["Mã KH", "Hạng", "Loại hình khách"]
    raw = {"Mã KH": [f"KH{i}" for i in range(6)], "Hạng": ["lẻ", "thân thiết", "sỉ", "lẻ", "lẻ", "sỉ"],
           "Loại hình khách": ["Cá nhân"] * 6}
    out = {m.column: m.canonical for m in map_table("kh", cols, {c: "text" for c in cols}, raw, [], nd)}
    assert out["Hạng"] == "customer_group" and out["Loại hình khách"] is None


def test_cot_ngay_gio_o_bang_don_la_gio_tao_don():
    import datetime as dt
    nd = {"ma hoa don": "order_id", "thoi gian": "order_date", "tong tien": "money"}
    cols = ["Mã hóa đơn", "Thời gian", "Tổng tiền", "Thời gian tạo"]
    days = [dt.datetime(2025, 1, i + 1) for i in range(6)]
    times = [d.replace(hour=8 + i, minute=5) for i, d in enumerate(days)]
    raw = {"Mã hóa đơn": [f"HD{i}" for i in range(6)], "Thời gian": days, "Tổng tiền": [1] * 6, "Thời gian tạo": times}
    kinds = {"Mã hóa đơn": "text", "Thời gian": "datetime", "Tổng tiền": "number", "Thời gian tạo": "datetime"}
    out = {m.column: m.canonical for m in map_table("hd", cols, kinds, raw, [], nd, raw)}
    assert out["Thời gian"] == "order_date" and out["Thời gian tạo"] == "order_time"
    # bảng trả hàng (mã đơn + ngày giờ trả): ngày giờ không phải giờ đặt
    raw2 = {"Mã phiếu trả": [f"PT{i}" for i in range(6)], "Mã hóa đơn": [f"HD{i}" for i in range(6)], "NgayGioTra": times}
    out = {m.column: m.canonical for m in map_table(
        "tra_hang", list(raw2), {"Mã phiếu trả": "text", "Mã hóa đơn": "text", "NgayGioTra": "datetime"}, raw2, [],
        {"ma hoa don": "order_id", "ma phieu tra": "return_id"}, raw2)}
    assert out["NgayGioTra"] is None
    # danh mục hàng: "Thời gian tạo" không phải giờ đặt
    out = {m.column: m.canonical for m in map_table(
        "sp", ["Mã hàng", "Thời gian tạo"], {"Mã hàng": "text", "Thời gian tạo": "datetime"},
        {"Mã hàng": [f"SP{i}" for i in range(6)], "Thời gian tạo": times}, [], {"ma hang": "product_id"},
        {"Mã hàng": [f"SP{i}" for i in range(6)], "Thời gian tạo": times})}
    assert out["Thời gian tạo"] is None


def test_llm_khong_lam_mat_bang_ban(monkeypatch):
    # biz_124: "Slg" -> conv_factor từng biến bảng chi tiết hoá đơn thành bảng quy đổi (mất cả bảng bán)
    cols = ["Mã HĐ", "Tên hàng", "SL", "Đơn giá", "Thành tiền", "Slg"]
    kinds = {"Mã HĐ": "text", "Tên hàng": "text", "SL": "number", "Đơn giá": "number", "Thành tiền": "number",
             "Slg": "number"}
    out = _llm_run(monkeypatch, cols, kinds, {c: ["1"] * 5 for c in cols}, {"Slg": "conv_factor"},
                   known={"Mã HĐ": "order_id", "Tên hàng": "product_name", "SL": "qty_base",
                          "Đơn giá": "unit_price", "Thành tiền": "line_amount"})
    assert out["Slg"] is None and out["Thành tiền"] == "line_amount"


def test_llm_hai_cot_cung_ten_chuan_chon_theo_du_lieu(monkeypatch):
    # biz_111 đổi tên cột: LLM gán product_name cho cả cột nhóm hàng (ít giá trị) lẫn cột tên món (nhiều giá trị)
    cols = ["Loại hàng", "Hàng hóa", "Loại hàng hóa", "Giá"]
    kinds = {"Loại hàng": "text", "Hàng hóa": "text", "Loại hàng hóa": "text", "Giá": "number"}
    samples = {"Loại hàng": ["cà phê", "trà", "cà phê", "sinh tố"] * 5,
               "Hàng hóa": [f"Món {i} (M)" for i in range(20)],
               "Loại hàng hóa": ["Hàng hóa"] * 20, "Giá": ["25000"] * 20}
    out = _llm_run(monkeypatch, cols, kinds, samples,
                   {"Loại hàng": "product_name", "Hàng hóa": "product_name", "Loại hàng hóa": "category",
                    "Giá": "price"})
    assert out["Hàng hóa"] == "product_name" and out["Loại hàng"] is None
    assert out["Loại hàng hóa"] is None          # một giá trị cho mọi dòng: không phải nhóm hàng


def test_llm_hai_cot_so_luong_phan_dinh_theo_du_lieu(monkeypatch):
    # biz_113 đổi tên cột: LLM gán qty cho cả cột ghi trên dòng lẫn cột quy ra đơn vị cơ bản
    cols = ["Mã đơn", "Hàng", "SL", "SL lẻ"]
    raw = {"Mã đơn": ["1"] * 6, "Hàng": ["a"] * 6, "SL": [1, 2, 1, 3, 1, 2], "SL lẻ": [24, 2, 12, 3, 6, 48]}
    out = _llm_run(monkeypatch, cols, {"Mã đơn": "text", "Hàng": "text", "SL": "number", "SL lẻ": "number"}, raw,
                   {"SL": "qty", "SL lẻ": "qty"}, known={"Mã đơn": "order_id", "Hàng": "product_name"})
    assert out["SL"] == "qty" and out["SL lẻ"] == "qty_base"
