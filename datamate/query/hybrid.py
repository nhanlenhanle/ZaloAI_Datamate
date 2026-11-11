"""Ghép hai đường giải một câu: LLM lập kế hoạch JSON (query/compose.py) và LLM viết SQL (query/sql_tier.py).

Hai đường hỏi độc lập nên sai ít trùng nhau: cùng ra một kết quả thì đáng tin hơn hẳn từng đường; khác nhau thì tin đường
mạnh hơn với loại câu đó (câu quen: JSON, câu lạ / dòng luật mới: SQL).
"""
from __future__ import annotations

import re

from datamate.loader.parsers import fold
from datamate.query.compose import UNANSWERABLE, ExampleBank, RuleBank, ShopContext, solve
from datamate.query.sql_tier import SqlBank, solve_sql

_NUM_TOL = 0.006


def _name_keys(x: dict) -> set[str]:
    keys = {re.sub(r"[^\w]+", "", fold(str(n))) for n in x.get("names") or [] if n}
    if x.get("id") is not None:
        keys.add(re.sub(r"[^\w]+", "", fold(str(x["id"]))))
    return keys


def same_value(a, b) -> bool:
    """Hai kết quả chạy có cùng là một đáp án không. Danh sách một phần tử coi như chính phần tử đó; bảng so không theo thứ tự dòng."""
    if isinstance(a, list) and len(a) == 1 and not isinstance(b, list):
        a = a[0]
    if isinstance(b, list) and len(b) == 1 and not isinstance(a, list):
        b = b[0]
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) < _NUM_TOL
    if isinstance(a, dict) and isinstance(b, dict) and "bang" in a and "bang" in b:
        ra, rb = a["bang"], b["bang"]
        return len(ra) == len(rb) and all(any(same_value(x, y) for y in rb) for x in ra)
    if isinstance(a, dict) and isinstance(b, dict) and "names" in a and "names" in b:
        return bool(_name_keys(a) & _name_keys(b))
    if isinstance(a, dict) and "names" in a and isinstance(b, str):
        return re.sub(r"[^\w]+", "", fold(b)) in _name_keys(a)
    if isinstance(b, dict) and "names" in b and isinstance(a, str):
        return same_value(b, a)
    if isinstance(a, str) and isinstance(b, str):
        return re.sub(r"[^\w]+", "", fold(a)) == re.sub(r"[^\w]+", "", fold(b))
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(same_value(x, y) for x, y in zip(a, b))
    return False


POLICIES = ("ca_hai", "dinh_tuyen", "json", "sql", "bi_thi_sql", "bi_thi_json", "doi_chieu")
# Câu giống kho ví dụ từ mức này trở lên là dạng quen (kế hoạch JSON có mẫu), dưới là câu lạ (thường là dòng luật mới, SQL
# đọc luật tốt hơn hẳn). ca_hai: hai đường khác nhau thì câu quen tin JSON, câu lạ tin SQL; dinh_tuyen: câu quen hỏi JSON
# trước. Chọn 2026-11-02 trên Qwen3.5-9B Q8 bằng luật đặt trước khi xem số: trung bình (nhóm câu quen: holdout s31, F;
# nhóm luật mới: R2, R). ca_hai +0.837 (quen +0.932, mới +0.742), dinh_tuyen 0.6 +0.830, dinh_tuyen 0.4 +0.798,
# chỉ SQL +0.791, chỉ JSON +0.693. Ngưỡng 0.5 và 0.6 hoà trên cả bốn bộ -> lấy 0.6 (nghiêng về SQL: đề thật nhiều câu lạ).
FAMILIAR = 0.6
_NO_DATA = UNANSWERABLE | {"llm_khong_co"}


def _settled(r: dict) -> bool:
    return r["loai"] == "tra_loi" or r["loai"] in UNANSWERABLE


def guard_unanswerable(ctx, r: dict) -> dict:
    """§7 cần bằng chứng shop không ghi. Shop mà lớp dữ liệu không nhận ra sổ bán có ngày (README không mô tả cột, sổ lạ)
    thì "thiếu nguồn" thường là sổ chưa đọc được: bỏ trống thay vì nộp không trả lời được. Bộ hard tự sinh (shop thiết kế,
    2026-11-03): 69 / 70 câu nộp không trả lời được là sai, phần lớn ở shop như vậy. Shop có README không mô tả cột nào
    cũng vậy (cột do từ điển tên / LLM đoán): hard thiết kế 2 / 15 câu đúng (xem nhat_ky_thu_nghiem.md, PP3b)."""
    if r["loai"] in UNANSWERABLE and not (ctx.sales_known() and ctx.columns_described()):
        return {**r, "loai": "khong_chac"}
    return r


def solve_both(ctx: ShopContext, q: dict, bank: ExampleBank, sql_bank: SqlBank | None = None, rule_bank: RuleBank | None = None,
               policy: str = "ca_hai", temps=(0, 0.5, 0.9), skip_shop=None, skip_dong=None) -> dict:
    """policy: ca_hai (luôn hỏi cả hai, xem both) | dinh_tuyen (câu quen: kế hoạch trước, câu lạ: SQL trước; bên trước bí thì
    hỏi bên kia) | json / sql (một đường) | bi_thi_sql (kế hoạch trước) | bi_thi_json (SQL trước)
    | doi_chieu (luôn hỏi cả hai; khác nhau thì trống). Kết luận không trả lời được qua guard_unanswerable."""
    return guard_unanswerable(ctx, _solve_both(ctx, q, bank, sql_bank, rule_bank, policy, temps, skip_shop, skip_dong))


def _solve_both(ctx, q, bank, sql_bank, rule_bank, policy, temps, skip_shop, skip_dong) -> dict:
    def j():
        return solve(ctx, q, bank, skip_shop=skip_shop, temps=temps, rule_bank=rule_bank, skip_dong=skip_dong)

    def s():
        return solve_sql(ctx, q, temps=temps, bank=sql_bank, skip_shop=skip_shop, rule_bank=rule_bank, skip_dong=skip_dong)
    if policy in ("ca_hai", "dinh_tuyen"):
        familiar = bank.familiarity(q["question"], ctx.names_in(q["question"]), skip_shop=skip_shop) >= FAMILIAR
        if policy == "ca_hai":
            return both(j(), s(), familiar, cautious=not ctx.columns_described())
        policy = "bi_thi_sql" if familiar else "bi_thi_json"
    if policy == "sql":
        return {**s(), "tang": "sql"}
    if policy == "bi_thi_json":
        first = s()
        return {**first, "tang": "sql"} if _settled(first) else combine(j(), first)
    first = j()
    if policy == "json" or (policy == "bi_thi_sql" and _settled(first)):
        return first
    return combine(first, s(), cross_check=policy == "doi_chieu")


def both(j: dict, s: dict, familiar: bool, cautious: bool = False) -> dict:
    """Kết quả của hai đường cho cùng một câu. Cùng trả lời: trùng thì nộp, khác thì câu quen lấy JSON, câu lạ lấy SQL
    (cautious: bỏ trống). Chỉ một đường trả lời thì lấy đường đó (kể cả khi đường kia kết luận không trả lời được). Không
    đường nào trả lời: giữ kết luận không trả lời được (§7) của JSON, rồi của SQL; không có thì bỏ trống.
    cautious = shop có README không mô tả cột nào: hai đường lệch ở đó phần lớn là cả hai đoán sai cột (hard thiết kế: lấy
    SQL 4 đúng / 19 sai), còn ở shop train lấy SQL lợi hơn (R2-R5: 53 / 30). PP3b trong nhat_ky_thu_nghiem.md."""
    sql = {**s, "tang": "sql"}
    if j["loai"] == s["loai"] == "llm_khong_co":
        # hai đường cùng nói shop không ghi loại thông tin câu hỏi cần (giới tính, lý do huỷ, mức hài lòng...): §7 không trả
        # lời được. Thiết kế: hard 5 / 6, gen_hl 16 / 20, train 1 / 1 câu như vậy có đáp án "không trả lời được"
        return {"loai": "khong_ghi", "notes": (j.get("notes") or []) + (s.get("notes") or [])}
    if j["loai"] == "tra_loi" and s["loai"] == "tra_loi":
        if same_value(j["value"], s["value"]):
            return j
        if cautious:
            return {"loai": "khong_chac", "notes": (j.get("notes") or []) + (s.get("notes") or [])}
        return j if familiar else sql
    # một đường trả lời, đường kia nói shop không có dữ liệu đó: hai đường hiểu câu khác nhau, bỏ trống. Thiết kế (hard 201-205,
    # gen_hl, train) chọn phương án này trên các phương án đặt trước; R2-R5 + F: câu như vậy đúng 8 / sai 8 (T2, nhat_ky)
    if j["loai"] == "tra_loi" and s["loai"] in _NO_DATA or s["loai"] == "tra_loi" and j["loai"] in _NO_DATA:
        return {"loai": "khong_chac", "notes": (j.get("notes") or []) + (s.get("notes") or [])}
    if j["loai"] == "tra_loi":
        return j
    if s["loai"] == "tra_loi":
        return sql
    if j["loai"] in UNANSWERABLE:
        return j
    return sql if s["loai"] in UNANSWERABLE else j


def combine(j: dict, s: dict, cross_check: bool = False) -> dict:
    """Kế hoạch trả lời được thì lấy kế hoạch (đối chiếu: SQL ra khác thì trống). Kế hoạch kết luận không trả lời được (§7)
    thì giữ kết luận đó. Kế hoạch bí (lỗi, không đồng thuận) mới lấy SQL."""
    if j["loai"] == "tra_loi":
        if cross_check and s["loai"] == "tra_loi" and not same_value(j["value"], s["value"]):
            return {"loai": "khac_nhau", "notes": (j.get("notes") or []) + (s.get("notes") or [])}
        return j
    if j["loai"] in UNANSWERABLE:
        return j
    if s["loai"] == "tra_loi":
        return {**s, "tang": "sql"}
    return j
