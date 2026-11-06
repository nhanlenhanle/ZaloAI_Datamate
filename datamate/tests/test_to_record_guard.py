import pytest

from datamate.query.compose import final_record
from datamate.query.plan import PlanError, to_record


@pytest.mark.parametrize("v", [{"names": [None], "id": None}, {"names": ["nan"], "id": None}, {"names": [""], "id": "None"},
                               float("nan"), [1.0, float("inf")]])
def test_khong_nop_gia_tri_hong(v):
    with pytest.raises(PlanError):
        to_record("q", v)


def test_gia_tri_binh_thuong():
    assert to_record("q", {"names": [], "id": "SP9"})["answer"] == "SP9"
    assert to_record("q", [1, 2])["answer"] == [1, 2]


def test_ban_cuoi_bo_trong_thay_vi_nop_none():
    assert final_record("q", {"loai": "tra_loi", "value": {"names": [None], "id": None}, "want": None}) == {"id": "q", "type": "abstain"}
