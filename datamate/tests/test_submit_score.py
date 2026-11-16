from datamate.submit import score


def test_chuoi_nhan_alias_ma():
    gold = {"type": "string", "answer": "Rau câu dừa", "alias": ["CB015"]}
    assert score({"type": "string", "answer": "CB015"}, gold) == 1
    assert score({"type": "string", "answer": "rau cau dua"}, gold) == -1      # sai dấu, không phải cách viết trong file
    assert score({"type": "string", "answer": "Rau câu dừa"}, gold) == 1


def test_danh_sach_alias_tung_phan_tu():
    gold = {"type": "list", "answer": ["Cà phê sữa (M)", "Cà phê đen (M)"], "alias": [["SP0003"], ["SP0001"]]}
    assert score({"type": "list", "answer": ["SP0003", "Cà phê đen (M)"]}, gold) == 1
    assert score({"type": "list", "answer": ["SP0001", "SP0003"]}, gold) == -1      # sai thứ tự
    assert score({"type": "list", "answer": ["SP0003"]}, gold) == -1


def test_bang_alias_ten_dong():
    gold = {"type": "table", "answer": {"columns": ["khach_hang", "so_tien_no"], "rows": [["Lâm Bảo Ngọc", 632000], ["Nghiêm Duy Linh", 620000]]},
            "alias": [["KH0027"], ["KH0097"]]}
    rec = {"type": "table", "answer": {"columns": ["khach_hang", "so_tien_no"], "rows": [["Nghiêm Duy Linh", 620000], ["KH0027", 632000]]}}
    assert score(rec, gold) == 1
    rec["answer"]["rows"][1][1] = 632001
    assert score(rec, gold) == -1


def test_khong_alias_nhu_cu():
    assert score({"type": "number", "answer": 5}, {"type": "number", "answer": 5}) == 1
    assert score({"type": "list", "answer": [1, 2]}, {"type": "list", "answer": [1, 2], "alias": []}) == 1
    assert score({"type": "abstain"}, {"type": "number", "answer": 5}) == 0
