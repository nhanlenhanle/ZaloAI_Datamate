"""NGANH cho sinh.py = 27 ngành của nhanld (nganh_nhanld.py) + 15 ngành mới (nganh_moi.py)."""
from nganh_moi import NGANH_MOI
from nganh_nhanld import NGANH as _NGANH_NHANLD

NGANH = {**_NGANH_NHANLD, **NGANH_MOI}
