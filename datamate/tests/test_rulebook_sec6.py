import duckdb

from datamate.llm_query import _sec6_pick, rulebook_text

HEADS_MOI = ["Tiệm hoa (biz_201)", "Phòng máy (biz_203)", "Giặt sấy (biz_204)"]
HEADS_TRAIN = ["Cà phê", "Nhà thuốc", "Vật liệu xây dựng"]


def test_tieu_de_ghi_ma_shop():
    assert _sec6_pick(HEADS_MOI, None, "biz_203", None) == {"Phòng máy (biz_203)"}
    assert _sec6_pick(HEADS_MOI, "Cà phê", "biz_201", "") == {"Tiệm hoa (biz_201)"}      # ngành nhận nhầm không quan trọng
    assert _sec6_pick(["Tiệm hoa (biz_2010)", "Giặt sấy"], None, "biz_201", None) == {"Tiệm hoa (biz_2010)", "Giặt sấy"}


def test_hoa_don_khong_phai_tiem_hoa():
    assert _sec6_pick(["Tiệm hoa", "Giặt sấy"], None, "biz_9", "Danh sách hoá đơn") == {"Tiệm hoa", "Giặt sấy"}


def test_dung_ten_nganh_nhu_cu():
    assert _sec6_pick(HEADS_TRAIN, "Nhà thuốc", "biz_119", "Danh sách hoá đơn") == {"Nhà thuốc"}


def test_chu_trong_gioi_thieu_readme():
    assert _sec6_pick(["Tiệm hoa", "Giặt sấy"], None, "biz_9", "Tiệm hoa ghi sổ bán hàng tay trên Excel") == {"Tiệm hoa"}


def test_nganh_moi_khong_nhan_ra_thi_lay_cac_muc_nganh_la():
    got = _sec6_pick(["Cà phê", "Tiệm hoa", "Giặt sấy"], None, "biz_9", "Danh sách hoá đơn, một file CSV")
    assert got == {"Tiệm hoa", "Giặt sấy"}


def test_rulebook_train_khong_doi():
    # ngành không nhận ra, rulebook chỉ có ngành quen: như cũ, không lấy mục nào
    assert _sec6_pick(HEADS_TRAIN, None, "biz_110", "Danh sách hoá đơn") == set()
    # nhận ra ngành nhưng rulebook không có mục của ngành đó: như cũ
    assert _sec6_pick(HEADS_TRAIN, "Tạp hoá", "biz_101", "Sổ bán hàng") == set()


def _db(tmp_path, shop, intro, heads):
    con = duckdb.connect(str(tmp_path / "s.duckdb"))
    rows = [(1, 1, "Rulebook", ""), (2, 2, "1. Đơn hàng", "luật chung"), (3, 2, "6. Theo ngành", "")]
    rows += [(4 + i, 3, h, f"luật của {h}") for i, h in enumerate(heads)]
    rows += [(20, 2, "9. Đáp án và chấm điểm", "không đưa vào prompt")]
    con.execute("CREATE TABLE _rulebook (seq INT, level INT, heading VARCHAR, text VARCHAR)")
    con.executemany("INSERT INTO _rulebook VALUES (?, ?, ?, ?)", rows)
    con.execute("CREATE TABLE _meta_shop AS SELECT ? AS shop, ? AS intro, NULL::VARCHAR AS industry", [shop, intro])
    return con


def test_rulebook_text_giu_muc_cua_shop(tmp_path):
    con = _db(tmp_path, "biz_204", "Tiệm giặt", HEADS_MOI)
    text = rulebook_text(con, None)
    assert "luật của Giặt sấy (biz_204)" in text and "luật chung" in text
    assert "Tiệm hoa" not in text and "không đưa vào prompt" not in text
