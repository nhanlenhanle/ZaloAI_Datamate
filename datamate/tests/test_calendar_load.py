from datamate.loader.shopmeta import load_calendar


def test_lich_chuan(tmp_path):
    (tmp_path / "calendar.csv").write_text("date,holiday\n2025-01-01,Tết Dương lịch\n2025-01-02,\n", encoding="utf-8")
    c = load_calendar(str(tmp_path))
    assert list(c["date"].dt.day) == [1, 2] and c["holiday"].iloc[0] == "Tết Dương lịch"


def test_lich_ten_cot_khac(tmp_path):
    (tmp_path / "calendar.csv").write_text("ngay,ngay_chu_ky,ghi_chu\n2025-01-01,1,a\n2025-01-02,2,b\n", encoding="utf-8")
    c = load_calendar(str(tmp_path))
    assert "date" in c.columns and len(c) == 2 and c["ngay_chu_ky"].tolist() == [1, 2]


def test_lich_khong_co_cot_ngay(tmp_path):
    (tmp_path / "calendar.csv").write_text("a,b\nx,1\ny,2\n", encoding="utf-8")
    assert load_calendar(str(tmp_path)) is None
