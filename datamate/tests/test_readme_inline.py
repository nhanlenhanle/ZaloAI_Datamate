from datamate.loader.readme import parse_readme


def test_readme_inline_examples(tmp_path, monkeypatch):
    monkeypatch.setenv("DATAMATE_INLINE", "1")   # NV1 tắt mặc định
    p = tmp_path / "README.md"
    content = """# Dữ liệu shop test
Mô tả chung
## File
- `don_hang.csv`: **Mã đơn**, **Thời gian** (ngày giờ đặt), **Thanh toán** (hình thức ghi trên đơn).
- `ban_hang.csv` (csv)
- `DonHang_ChiTiet.xlsx`, sheet `Data`: ... **Tổng đơn** (số khách phải trả cả đơn).
- `test_nested.xlsx`: **Mô tả lồng** (tên khách (khách không lưu ghi khách lẻ); có lúc ghi kèm số đ).

## Bảng
- `phien_choi`: mỗi lượt: `so_phut` (số phút chơi), `ket_thuc` (`dd/mm/yyyy hh:mm`).
"""
    p.write_text(content, encoding="utf-8")
    info = parse_readme(str(p))

    cols = {(d.file, d.table, d.column, d.description, d.source) for d in info.columns}

    # don_hang.csv
    assert ("don_hang.csv", None, "Thời gian", "ngày giờ đặt", "inline") in cols
    assert ("don_hang.csv", None, "Thanh toán", "hình thức ghi trên đơn", "inline") in cols
    # Mã đơn không có ngoặc -> không thêm
    assert not any(d.column == "Mã đơn" for d in info.columns)

    # ban_hang.csv (csv) -> 0 mô tả (không có : và (csv) là định dạng)
    assert not any(d.file == "ban_hang.csv" for d in info.columns)

    # phien_choi
    assert (None, "phien_choi", "so_phut", "số phút chơi", "inline") in cols
    assert (None, "phien_choi", "ket_thuc", "`dd/mm/yyyy hh:mm`", "inline") in cols

    # nested parentheses
    assert ("test_nested.xlsx", None, "Mô tả lồng", "tên khách (khách không lưu ghi khách lẻ); có lúc ghi kèm số đ", "inline") in cols

    # DonHang_ChiTiet.xlsx
    assert ("DonHang_ChiTiet.xlsx", None, "Tổng đơn", "số khách phải trả cả đơn", "inline") in cols

