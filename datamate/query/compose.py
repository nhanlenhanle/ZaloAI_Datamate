"""LLM ghép kế hoạch: câu hỏi + rulebook của shop + danh mục bảng chuẩn + ví dụ tương tự -> kế hoạch JSON.

LLM chỉ hiểu câu và chọn phép; luật chung, tính kỳ, khớp tên, số liệu do code (query/plan.py) làm.
Rulebook đọc từ DB của chính shop, nên dòng luật mới của bộ khác vẫn tới được LLM.
Ví dụ lấy từ kho đã kiểm với đáp án (query/regress.py), chọn theo khung câu: che số, ngày, tên hàng.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from collections import Counter

import duckdb

from datamate.llm_query import rulebook_text
from datamate.loader import llm
from datamate.loader.parsers import fold
from datamate.query.evaluate import HOLDOUT
from datamate.query.facts import AT_DATE, BY_RANGE, FIELDS, MONEY, Facts, NoSource
from datamate.query.plan import MissingData, PlanError, Runner, _is_part, _product_index, _q, resolve_period, to_record
from datamate.tests.verify_answers import _cols, _month_end, _tables, text_key

SPEC = """Bạn lập KẾ HOẠCH tính số liệu cho câu hỏi về sổ bán hàng của một cửa hàng nhỏ ở Việt Nam. Câu hỏi có thể viết tắt,
không dấu, sai chính tả, teencode. Bạn KHÔNG tính toán, KHÔNG viết SQL: chỉ trả về một JSON theo ngôn ngữ dưới đây.

Kế hoạch lá:
{"nguon": <bảng>, "phep": "tong|dem|dem_khac|tb|min|max|dem_nhom|gia_duy_nhat|chan_le|hang_e|dem_e|so_ngay", "cot": <cột>,
 "loc": [{"cot": <cột>, "op": "=|!=|>|>=|<|<=|in|ket_thuc|rong|khong_rong", "gt": <giá trị>}],
 "ky": <kỳ>, "den_het": <kỳ>, "moi_trang_thai": true, "nhom": <cột>, "co_dieu_kien": {"op": ">=", "gt": 3},
 "xep": {"chieu": "giam|tang", "lay": <số>}, "cot_ra": "ten|gia_tri|ca_hai"}
- Doanh thu tính trên dong_ban là "phep": "tong", "cot": "tien"; lãi gộp là "cot": "lai". Đếm số đơn: "nguon": "don", "phep": "dem".
- "phep" chỉ nhận các giá trị trên; tỉ lệ, tăng trưởng, thương là kế hoạch ghép, không phải "phep". Tên cột lấy đúng từ danh mục.
- Không tự thêm lọc "trang_thai" hay "la_mat_hang" khi câu không hỏi; code đã áp luật. Thuốc theo hoạt chất: lọc "hoat_chat", không phải "ke_don".
- Giá bán một đơn vị ngày D: {"nguon": "dong_ban", "phep": "gia_duy_nhat", "cot": "gia_1_dv", "moi_trang_thai": true, "ky": <ngày D>, "loc": [hàng]}.
- Ngày / tháng nào cao nhất: "phep": "tong" với "nhom": "ngay" hoặc "thang", "xep": {"chieu": "giam", "lay": 1}.
- Bảng dong_ban và don mặc định chỉ tính đơn hợp lệ theo rulebook (không huỷ, không trả). Chỉ khi cần cả đơn huỷ / trả mới ghi
  "moi_trang_thai": true (vd tỉ lệ huỷ, đếm đơn huỷ, giá bán ngày D).
- Hỏi số còn lại (còn nợ, còn tồn) dùng "den_het"; bỏ "den_het" là tính đến hôm nay. Hỏi số phát sinh dùng "ky".
- Có "nhom" và "xep": xếp hạng. "lay": 1 trả một đối tượng. "cot_ra": "ten" trả tên, "gia_tri" trả số, "ca_hai" trả bảng tên + số.
  Không có "xep" thì liệt kê theo số đo giảm dần. "dem_nhom": đếm số đối tượng (cùng "nhom", có thể kèm "co_dieu_kien", "cot").
  Câu chỉ hỏi tên thì không dùng "ca_hai". Nhiều nhất, cao nhất, chạy nhất là "chieu": "giam".
- Đếm đối tượng đạt ngưỡng: {"phep": "dem_nhom", "nhom": "hang", "cot": "don", "co_dieu_kien": {"op": ">=", "gt": 5}} là số mặt hàng có từ 5 đơn;
  thêm "do": "tong" để so với TỔNG của cột: {"phep": "dem_nhom", "nhom": "don" hoặc "ngay", "cot": "tien", "do": "tong", "co_dieu_kien": {"op": ">=", "gt": 100000}}
  là số đơn hoặc số ngày có tiền từ 100000.
- Mặt hàng ế, không bán được trong kỳ: {"nguon": "dong_ban", "phep": "hang_e", "ky": <kỳ>} trả danh sách; "dem_e" trả số lượng.
- Tỉ lệ đơn huỷ: {"ghep": "ti_le", "cac": [{"nguon": "don", "phep": "dem", "ky": K, "moi_trang_thai": true, "loc": [{"cot": "trang_thai", "op": "=", "gt": "huy"}]},
  {"nguon": "don", "phep": "dem", "ky": K, "moi_trang_thai": true}]}.
- Trung bình mỗi đơn: {"ghep": "thuong", "tien": true, "cac": [{"nguon": "dong_ban", "phep": "tong", "cot": "tien", "ky": K}, {"nguon": "dong_ban", "phep": "dem_khac", "cot": "don", "ky": K}]}.
- Tháng M so với tháng liền trước: kỳ so là {"loai": "ky_truoc", "cua": {"loai": "thang", "thang": M, "nam": Y}}; so với cùng tháng năm trước: {"loai": "cung_ky_nam_truoc", "cua": ...}.
- So với cùng kỳ tháng trước, đầu tháng tới nay: {"ghep": "tang_truong", "cac": [{..., "ky": {"loai": "thang_nay"}}, {..., "ky": {"loai": "ky_truoc", "cua": {"loai": "thang_nay"}}}]}.
- N ngày kể từ ngày D so với N ngày ngay trước (vd hiệu ứng tăng giá): {"ghep": "tang_truong", "cac": [{..., "ky": {"loai": "tu_ngay", "tu": D, "n": N}}, {..., "ky": {"loai": "ky_truoc", "cua": {"loai": "tu_ngay", "tu": D, "n": N}}}]}. Câu không ghi ngày thì tra D ở mục LỊCH SỬ GIÁ.
- Nhà cung cấp nào nhập nhiều tiền nhất: {"nguon": "phieu_nhap", "phep": "tong", "cot": "tong_tien", "nhom": "nha_cung_cap", "xep": {"chieu": "giam", "lay": 1}, "ky": K}.
- Hỏi một con số thì không dùng "nhom" kèm "xep"; chỉ dùng khi câu hỏi tên, ngày, tháng nào. "ke_hoach" luôn là một object, nhiều vế thì dùng "ghep".
- Danh mục ghi bảng nào shop KHÔNG có mà câu cần đúng bảng đó: vẫn lập kế hoạch trên bảng đó, code sẽ báo thiếu dữ liệu.
- Thông tin không có trong bảng chuẩn thì dùng BẢNG GỐC: {"nguon": "<tên bảng gốc>", "phep": ..., "cot": <cột>, "nhom": <cột>, "cot_ngay": <cột ngày để lọc "ky">, "loc": [...]}. Op thêm: "thang_la" (tháng của cột ngày, "gt": số tháng). Bảng gốc có mã đơn thì có thêm cột hop_le, ngay_don, doanh_thu_don; tính doanh thu, số đơn thì lọc {"cot": "hop_le", "op": "=", "gt": true} và dùng "cot_ngay": "ngay_don".
- Điều kiện hai tầng: "co_dieu_kien" có thể là danh sách; {"do": "min", "cot": "ngay", "op": "trong_ky", "ky": K} là lần đầu rơi vào kỳ K (đối tượng mới, không ghi "ky" ở ngoài); {"do": "dem_khac", "cot": "hang", "op": ">=", "gt": 3} so số đo khác của nhóm; {"op": ">=", "phan_tram_tong": 5} so với 5% tổng cả bảng cùng kỳ.
- Tổng theo từng đối tượng rồi gộp tiếp: "nhom" kèm "ngoai": "max|min|tong|tb" (vd đơn lớn nhất: "phep": "tong", "cot": "tien", "nhom": "don", "ngoai": "max"; doanh thu của các đơn đạt ngưỡng: thêm "co_dieu_kien", "ngoai": "tong").
- So hai tập đối tượng: {"ghep": "dem_giao|dem_hieu", "cac": [A, B]}, mỗi vế có "nhom": dem_giao đếm đối tượng có ở cả hai, dem_hieu đếm đối tượng có ở A mà không có ở B.
- Số ngày dương lịch của một kỳ: {"phep": "so_ngay", "ky": K}.
- Lọc mặt hàng, khách, nhân viên: {"cot": "hang|khach|nhan_vien", "op": "=", "gt": <tên như trong câu>}; code tự khớp với dữ liệu.
- Kênh, hình thức thanh toán, trạng thái dùng đúng các mã trong danh mục.

Kế hoạch ghép (kết hợp các kế hoạch khác):
{"ghep": "ti_le", "cac": [A, B]}: 100 x A / B (A là phần, B là tổng) | "tang_truong": 100 x (A - B) / B (B là kỳ so) | "hieu": A - B
| "thuong": A / B (thêm "tien": true nếu là tiền) | "danh_sach": nhiều số theo đúng thứ tự câu hỏi
| "lon_hon": A > B (đúng / sai) | "tang_lien_tuc" / "giam_lien_tuc": các số trong "cac" tăng / giảm liên tục theo thứ tự thời gian (đúng / sai).

Kỳ: {"loai": "ngay", "ngay": "YYYY-MM-DD"} | {"loai": "hom_nay"} | {"loai": "hom_qua"} | {"loai": "tuan_nay"} | {"loai": "tuan_truoc"}
| {"loai": "thang", "thang": 8, "nam": 2025} (không ghi năm thì bỏ "nam") | {"loai": "thang_nay"} | {"loai": "thang_truoc"}
| {"loai": "quy", "quy": 2, "nam": 2026} | {"loai": "nam", "nam": 2025} | {"loai": "tu_dau_nam"} | {"loai": "n_ngay", "n": 7}
| {"loai": "khoang", "tu": "YYYY-MM-DD", "den": "YYYY-MM-DD"} | {"loai": "tu_ngay", "tu": "YYYY-MM-DD", "n": 7} | {"loai": "tet", "nam": 2026} | {"loai": "truoc_tet", "nam": 2026}
| {"loai": "ky_truoc", "cua": <kỳ>} | {"loai": "cung_ky_nam_truoc", "cua": <kỳ>}.

Trả về đúng một JSON, không giải thích, không markdown:
{"cach_tinh": "<một câu ngắn: tính gì, trên đối tượng nào, điều kiện gì, kỳ nào>", "ke_hoach": <kế hoạch>, "ra": "number|percent|date|string|list|table|boolean"}
Câu dùng một thuật ngữ có định nghĩa trong RULEBOOK thì "cach_tinh" và kế hoạch làm đúng theo định nghĩa đó, kể cả khi nó khác nghĩa thường ngày.
Nếu danh mục KHÔNG có loại thông tin câu hỏi cần (vd thái độ nhân viên, giới tính, địa chỉ khách, lý do huỷ):
{"khong_co": "<thiếu thông tin gì>"}. Luật tính lấy theo RULEBOOK bên dưới."""


# ---------------------------------------------------------------- danh mục bảng của shop

_LIST_VALUES = ("kenh", "thanh_toan", "nhom_hang", "nhom_khach", "trang_thai", "don_vi_co_ban")


def catalog(con, facts: Facts, today: dt.date) -> str:
    """Bảng chuẩn shop này có, mỗi bảng chỉ các cột có dữ liệu, kèm giá trị của cột phân loại."""
    lines = []
    for fact, cols in FIELDS.items():
        try:
            table = facts.table(fact, at=today if fact in AT_DATE else None,
                                rng=(today, today) if fact in BY_RANGE else None)
        except NoSource:
            lines.append(f"- {fact}: shop này KHÔNG có dữ liệu bảng này ({', '.join(cols)})")
            continue
        except duckdb.Error:
            continue
        parts = []
        for c, desc in cols.items():
            try:
                if not con.execute(f'SELECT COUNT("{c}") FROM "{table}"').fetchone()[0]:
                    continue
            except duckdb.Error:
                continue
            extra = ""
            if c in _LIST_VALUES:
                vals = [str(v) for v, in con.execute(f'SELECT DISTINCT "{c}" FROM "{table}" WHERE "{c}" IS NOT NULL '
                                                     f'LIMIT 25').fetchall()]
                extra = " {" + ", ".join(vals) + "}"
            parts.append(f"{c}: {desc}{extra}")
        lines.append(f"- {fact}: " + "; ".join(parts))
    return "\n".join(lines) or "(không có)"


# ---------------------------------------------------------------- ví dụ

def naturalize(plan, question: str, today: dt.date):
    """Kỳ dạng khoảng ngày trong kho ví dụ -> cách nói tự nhiên theo câu hỏi (để LLM học đúng: tính kỳ là việc của code)."""
    f = fold(question)

    def nat(k):
        a, b = dt.date.fromisoformat(k["tu"]), dt.date.fromisoformat(k["den"])
        if a == b:
            if a == today and re.search(r"hom nay|bua nay|cuoi ngay", f):
                return {"loai": "hom_nay"}
            if a == today - dt.timedelta(days=1) and re.search(r"hom qua|bua qua|hqua", f):
                return {"loai": "hom_qua"}
            return {"loai": "ngay", "ngay": k["tu"]}
        mon = today - dt.timedelta(days=today.weekday())
        if a == mon and b == today and re.search(r"tuan nay", f):
            return {"loai": "tuan_nay"}
        if a == mon - dt.timedelta(days=7) and b == mon - dt.timedelta(days=1) and re.search(r"tuan (truoc|roi|qua)", f):
            return {"loai": "tuan_truoc"}
        if a == today.replace(day=1) and b == today and re.search(r"thang nay|thang ni|mung 1|dau thang", f):
            return {"loai": "thang_nay"}
        if a == dt.date(today.year, 1, 1) and b == today and "dau nam" in f:
            return {"loai": "tu_dau_nam"}
        if b == today and re.search(rf"\b{(b - a).days + 1} ngay", f):
            return {"loai": "n_ngay", "n": (b - a).days + 1}
        if a.day == 1 and b == _month_end(a.year, a.month):
            return {"loai": "thang", "thang": a.month, "nam": a.year}
        if a.day == 1 and a.month % 3 == 1 and b == _month_end(a.year, a.month + 2) and re.search(r"\bquy\b", f):
            return {"loai": "quy", "quy": (a.month - 1) // 3 + 1, "nam": a.year}
        return k

    def windows(p):
        """Hai khoảng N ngày liền nhau trong câu nêu 'N ngày' -> tu_ngay và ky_truoc: LLM không phải tự tính ngày cuối."""
        c = p.get("cac") or []
        if p.get("ghep") != "tang_truong" or len(c) != 2 or any((x.get("ky") or {}).get("loai") != "khoang" for x in c):
            return None
        a1, b1 = dt.date.fromisoformat(c[0]["ky"]["tu"]), dt.date.fromisoformat(c[0]["ky"]["den"])
        a2, b2 = dt.date.fromisoformat(c[1]["ky"]["tu"]), dt.date.fromisoformat(c[1]["ky"]["den"])
        n = (b1 - a1).days + 1
        if (b2 - a2).days + 1 != n or b2 + dt.timedelta(days=1) != a1 or not re.search(rf"\b{n} ngay", f):
            return None
        base = {"loai": "tu_ngay", "tu": c[0]["ky"]["tu"], "n": n}
        return {**p, "cac": [{**c[0], "ky": base}, {**c[1], "ky": {"loai": "ky_truoc", "cua": base}}]}

    def walk(p):
        if isinstance(p, dict):
            if (w := windows(p)) is not None:
                return w
            out = {}
            for key, v in p.items():
                if key in ("ky", "den_het") and isinstance(v, dict) and v.get("loai") == "khoang":
                    out[key] = nat(v)
                else:
                    out[key] = walk(v)
            if out.get("den_het") == {"loai": "hom_nay"}:
                out.pop("den_het")
            return out
        if isinstance(p, list):
            return [walk(x) for x in p]
        return p
    return walk(plan)


_NUM = re.compile(r"\d[\d.,/:-]*")


def mask(question: str, names: list[str] | None = None) -> set[str]:
    """Khung câu: bỏ dấu, che tên trong kế hoạch, che số; trả tập từ và cặp từ."""
    q = f" {text_key(question)} "
    for n in sorted(names or [], key=len, reverse=True):
        k = text_key(n)
        if k:
            q = q.replace(f" {k} ", " <ten> ")
    q = _NUM.sub(" <so> ", q)
    w = q.split()
    return set(w) | {f"{x}_{y}" for x, y in zip(w, w[1:])}


def _plan_names(plan) -> list[str]:
    out = []
    if isinstance(plan, dict):
        for f in plan.get("loc") or []:
            if f.get("cot") in ("hang", "khach", "nhan_vien", "nhom_hang", "nhom_khach", "hoat_chat"):
                out.append(str(f.get("gt")))
        for p in plan.get("cac") or []:
            out += _plan_names(p)
    return out


class ExampleBank:
    """Kho câu -> kế hoạch đã kiểm với đáp án train. HOLDOUT không có mặt trong kho."""

    def __init__(self, path: str):
        self.items = []
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                e = json.loads(line)
                if e["shop"] in HOLDOUT:
                    continue
                today = dt.date.fromisoformat(e["as_of_date"])
                e["nplan"] = naturalize(e["plan"], e["question"], today)
                e["sig"] = mask(e["question"], _plan_names(e["plan"]))
                self.items.append(e)

    def pick(self, question: str, names: list[str], k: int = 6, skip_shop: str | None = None,
             skip_kinds: set | None = None, skip_id: str | None = None, skip_shops: set | None = None) -> list[dict]:
        sig = mask(question, names)
        scored = []
        for e in self.items:
            if e["shop"] == skip_shop or e["id"] == skip_id or (skip_kinds and e["kind"] in skip_kinds):
                continue
            if skip_shops and e["shop"] in skip_shops:
                continue
            scored.append((len(sig & e["sig"]) / (len(sig | e["sig"]) or 1), e["id"], e))
        scored.sort(key=lambda x: (-x[0], x[1]))
        out, per = [], Counter()
        for _, _, e in scored:
            if per[e["kind"]] < 2:
                out.append(e)
                per[e["kind"]] += 1
                if len(out) == k:
                    break
        return out

    def familiarity(self, question: str, names: list[str], skip_shop: str | None = None) -> float:
        """Độ giống (Jaccard khung câu) với câu gần nhất trong kho: cao là dạng câu quen, kế hoạch JSON đã có mẫu."""
        sig = mask(question, names)
        return max((len(sig & e["sig"]) / (len(sig | e["sig"]) or 1) for e in self.items if e["shop"] != skip_shop), default=0.0)


class RuleBank:
    """Kho "dòng luật -> kế hoạch" (stress/rule_bank.py): luật tự đặt, kế hoạch đã kiểm. Chỉ cách đọc một định nghĩa lạ."""

    def __init__(self, path: str):
        self.items = []
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                e = json.loads(line)
                e["sig"] = mask(f'{e["rule"]} {e["question"]}', _plan_names(e["plan"]))
                self.items.append(e)

    def pick(self, question: str, near: list[str], k: int = 3, skip_shop: str | None = None, skip_dong: str | None = None,
             need: str | None = None) -> list[dict]:
        """need: "plan" | "sql" — chỉ lấy ví dụ có phần tầng đó dùng (dòng R3, R4 chỉ có SQL)."""
        sig = mask(" ".join([*near[:2], question]))
        scored = sorted(((len(sig & e["sig"]) / (len(sig | e["sig"]) or 1), e["id"], e) for e in self.items
                         if e["shop"] != skip_shop and e["dong"] != skip_dong and (need is None or e.get(need))),
                        key=lambda x: (-x[0], x[1]))
        out, seen = [], set()
        for _, _, e in scored:
            if e["dong"] not in seen:
                out.append(e)
                seen.add(e["dong"])
                if len(out) == k:
                    break
        return out


# ---------------------------------------------------------------- dòng luật gần câu hỏi

_ABBR = [(r"\bdthu\b", "doanh thu"), (r"\bkh\b", "khach"), (r"\bsp\b", "san pham"), (r"\bncc\b", "nha cung cap"), (r"\bnv\b", "nhan vien"),
         (r"\bsdt\b", "so dien thoai"), (r"\btb\b", "trung binh"), (r"\bsl\b", "so luong"), (r"\bdc\b", "duoc")]
_RULE_STOP = {"la", "co", "cua", "bao", "nhieu", "cho", "hoi", "va", "trong", "thi", "khi", "mot", "cac", "nao", "gi", "may", "bn", "den", "tu", "ngay", "thang", "nam",
              "don", "tinh", "theo", "khong", "cung", "nay", "do", "ky", "so", "cai", "cau", "giup", "gium", "voi", "duoc", "hay", "vay", "a", "nhi", "ko", "ai"}
_RULE_HEAD = re.compile(r"\|\s*(luat|cach noi|cach ghi|tu|type)\s*\|")


def _rule_words(text: str) -> set[str]:
    f = fold(text)
    for p, r in _ABBR:
        f = re.sub(p, r, f)
    w = re.findall(r"[a-z0-9]+", f)
    return {x for x in w if x not in _RULE_STOP and not x.isdigit()} | {f"{a}_{b}" for a, b in zip(w, w[1:]) if not (a.isdigit() or b.isdigit())}


def rule_rows(rules: str) -> list[str]:
    """Các dòng bảng của rulebook, kể cả dòng thêm ở bộ khác: câu hỏi đi theo từng dòng."""
    return [line for line in rules.split("\n") if line.startswith("|") and not line.startswith("|-") and not _RULE_HEAD.match(fold(line))]


def near_rules(rules: str, question: str, k: int = 3) -> list[str]:
    """Các dòng luật có từ, cụm từ hiếm trùng với câu hỏi. Không có dòng nào đủ gần thì trả rỗng, không ép."""
    rows = rule_rows(rules)
    words = [_rule_words(r) for r in rows]
    df = Counter(w for ws in words for w in ws)
    q = _rule_words(question)
    scored = []
    for i, ws in enumerate(words):
        s = sum((2 if "_" in w else 1) / df[w] for w in q & ws)
        if any("_" in w for w in q & ws) or s >= 1:
            scored.append((s, -i))
    scored.sort(reverse=True)
    return [rows[-i] for _, i in scored[:k]]


# ---------------------------------------------------------------- hỏi LLM

class ShopContext:
    """Ngữ cảnh một shop trên một kết nối (mỗi luồng một bộ: bảng tạm gắn với kết nối)."""

    def __init__(self, db_path: str):
        self.con = duckdb.connect(db_path, read_only=True)
        # một luồng DuckDB: gộp nhóm song song trả các dòng hoà theo thứ tự khác nhau mỗi lần chạy -> "ORDER BY ... LIMIT 1"
        # của SQL do LLM viết và giá trị mẫu trong prompt ("SELECT DISTINCT ... LIMIT") đổi giữa các lần chạy (thể lệ: chạy
        # lại lệch tối đa 0.03); bảng mỗi shop nhỏ, chậm không đáng kể
        self.con.execute("SET threads = 1")
        self.facts = Facts(self.con)
        ind = self.con.execute("SELECT industry FROM _meta_shop").fetchone()[0]
        self.rules = rulebook_text(self.con, ind)
        self.names = None
        self._cat: dict = {}
        self._holidays: dict | None = None
        self._sales: bool | None = None
        self._described: bool | None = None

    def sales_known(self) -> bool:
        """Lớp dữ liệu có nhận ra sổ bán có ngày không (_meta_shop.sales_start / sales_end; cả 30 shop train đều có)."""
        if self._sales is None:
            try:
                s, e = self.con.execute("SELECT sales_start, sales_end FROM _meta_shop").fetchone()
                self._sales = s is not None and e is not None
            except (duckdb.Error, TypeError):
                self._sales = False
        return self._sales

    def columns_described(self) -> bool:
        """README có mô tả ít nhất một cột gốc không (_meta_columns.description; mọi shop train có ít nhất 8 cột mô tả)."""
        if self._described is None:
            try:
                n = self.con.execute("SELECT count(description) FROM _meta_columns WHERE original_name IS NOT NULL").fetchone()[0]
                self._described = n > 0
            except (duckdb.Error, TypeError):
                self._described = False
        return self._described

    def catalog(self, today: dt.date) -> str:
        # theo từng ngày: bảng tính tại ngày (tồn, công nợ, lô) có thể chỉ có từ một ngày nào đó; giữ một bản cho cả shop thì
        # danh mục của một câu tuỳ câu nào của shop được làm trước (đổi giữa các lần chạy song song)
        if ("c", today) not in self._cat:
            self._cat[("c", today)] = catalog(self.con, self.facts, today)
        return self._cat[("c", today)]

    def names_in(self, question: str) -> list[str]:
        if self.names is None:
            self.names = list(_product_index(self.con))
        q = f" {text_key(question)} "
        return [k for k in self.names if f" {k} " in q]

    def holiday_lines(self, question: str) -> list[str]:
        """Ngày lễ nêu trong câu, tra ở lịch của bộ đề (_calendar): lễ âm lịch (Vu Lan, Rằm tháng Giêng...) LLM hay tính
        sai ngày. Tết đã có kỳ riêng trong ngôn ngữ kế hoạch ("tet", "truoc_tet") nên không ghi ở đây."""
        if self._holidays is None:
            try:
                rows = self.con.execute("SELECT holiday, CAST(date AS DATE) FROM _calendar WHERE COALESCE(holiday, '') <> '' "
                                        "ORDER BY date").fetchall()
            except duckdb.Error:
                rows = []
            self._holidays = {}
            for name, d in rows:
                self._holidays.setdefault(str(name), []).append(d)
        q = f" {fold(question)} "
        out = []
        for name in sorted(self._holidays, key=len, reverse=True):      # tên dài trước: "Phụ nữ Việt Nam" không bị bắt sót
            f = fold(name)
            if f == "tet" or not re.search(rf"(?<![a-z0-9]){re.escape(f)}(?![a-z0-9])", q):
                continue
            out.append(f"- {name}: " + ", ".join(str(d) for d in self._holidays[name]))
            q = q.replace(f, " ")
        return out

    def price_lines(self, question: str) -> list[str]:
        """Lịch sử giá của mặt hàng nêu trong câu: câu về hiệu ứng tăng giá có thể không ghi ngày."""
        keys = self.names_in(question)[:3]
        if not keys or not re.search(r"gia", fold(question)):
            return []
        idx = _product_index(self.con)
        out = []
        for t in _tables(self.con, "price_history"):
            c = _cols(self.con, t)
            if not {"price_from", "new_price"} <= c:
                continue
            old = "old_price" if "old_price" in c else "NULL"
            for k in keys:
                pid, key, name = idx[k]
                conds = ([f"product_key = {_q(key)}"] if "product_key" in c else []) + \
                    ([f"CAST(product_id AS VARCHAR) = {_q(pid)}"] if pid and "product_id" in c else [])
                if conds:
                    out += [f"- {name}: từ {str(d)[:10]}, giá {o} -> {n}" for d, o, n in self.con.execute(
                        f'SELECT price_from, {old}, new_price FROM "{t}" WHERE {" OR ".join(conds)} '
                        f'ORDER BY price_from LIMIT 8').fetchall()]
        return out


_STOP = {"la", "co", "cua", "bao", "nhieu", "cho", "hoi", "thang", "nam", "ngay", "trong", "tong", "so", "may", "gi", "nao", "va", "hang", "don",
         "ai", "bn", "tien", "ky", "theo", "tinh", "khong", "cac", "mot", "moi", "tu", "den", "het"}


def raw_catalog(con, question: str, rules: str = "", top: int = 4, per_table: int = 14) -> str:
    """Bảng gốc của shop, ưu tiên bảng và cột có từ gần với câu hỏi và dòng luật nhắc tới nó; tên cột, nghĩa theo README, vài giá trị."""
    words = set(re.findall(r"[a-z0-9]+", fold(question))) - _STOP
    # dòng rulebook có từ trong câu cho biết câu đang nói về thứ gì (tài xế chăm nhất -> đợt giao)
    for line in rules.split("\n"):
        if line.startswith("|"):
            have = set(re.findall(r"[a-z0-9]+", fold(line)))
            if len(words & have) >= 2:
                words |= have - _STOP
    scored = []
    for t, role in con.execute("SELECT table_name, role FROM _meta_tables").fetchall():
        cols = []
        for c, d, kind, orig, note in con.execute("SELECT column_name, description, kind, original_name, note FROM _meta_columns "
                                                  "WHERE table_name = ?", [t]).fetchall():
            if c.endswith("__raw") or c.startswith("_") or c.endswith("_key") or c.endswith("_norm") or c == "qty_base_src":
                continue
            d = column_meaning(orig if orig and fold(str(orig)) != fold(c) else None, d, note)
            cols.append((len(set(re.findall(r"[a-z0-9]+", fold(f"{c} {d}"))) & words), c, d, kind))
        hit = sum(x[0] for x in cols) + len(set(re.findall(r"[a-z0-9]+", fold(t))) & words)
        scored.append((hit, t, role, cols))
    scored.sort(key=lambda x: (-x[0], x[1]))
    lines = []
    for hit, t, role, cols in scored[:top]:
        cols.sort(key=lambda x: -x[0])
        parts = []
        for _, c, d, kind in cols[:per_table]:
            extra = d
            if kind == "text":
                try:
                    vals = [v for v, in con.execute(f'SELECT DISTINCT "{c}" FROM "{t}" WHERE "{c}" IS NOT NULL LIMIT 5').fetchall()]
                    if vals and all(len(str(v)) <= 20 for v in vals):
                        extra += " {" + ", ".join(str(v) for v in vals[:4]) + "}"
                except duckdb.Error:
                    pass
            parts.append(f"{c}{extra}")
        lines.append(f"- {t} ({role}): " + "; ".join(parts))
    rest = [x[1] for x in scored[top:]]
    if rest:
        lines.append("Bảng khác: " + ", ".join(rest))
    return "\n".join(lines)


def readme_block(con, limit: int = 1800) -> str:
    """Mục MÔ TẢ CỦA SHOP (cả hai đường): phần mô tả và quy ước README của chính shop. Sổ lạ (phiên chơi, phiếu giặt...)
    chỉ được giải nghĩa ở đây; README gọi cột theo tên gốc, danh mục bảng gốc ghi kèm tên gốc để đối chiếu."""
    try:
        intro = con.execute("SELECT intro FROM _meta_shop").fetchone()[0] or ""
        conv = [b for b, in con.execute("SELECT body FROM _meta_conventions").fetchall() if b]
    except duckdb.Error:
        return ""
    text = "\n".join([intro.strip()] + [f"- {b.strip()}" for b in conv]).strip()
    if not text:
        return ""
    return "MÔ TẢ CỦA SHOP (README, tên cột theo tên gốc):\n" + (text[:limit] + " ..." if len(text) > limit else text) + "\n\n"


def column_meaning(orig, desc, note) -> str:
    """'(gốc X): nghĩa' của một cột bảng gốc: mô tả README, không có thì nghĩa LLM đọc lúc map cột."""
    out = f" (gốc '{orig}')" if orig else ""
    mean = desc or (note[5:] if isinstance(note, str) and note.startswith("LLM: ") else "")
    return out + (f": {str(mean)[:50]}" if mean else "")


def holiday_block(ctx, question: str) -> str:
    """Mục NGÀY LỄ của prompt (cả hai đường); ngữ cảnh không có lịch thì rỗng."""
    lines = ctx.holiday_lines(question) if hasattr(ctx, "holiday_lines") else []
    return "NGÀY LỄ (theo lịch của bộ đề):\n" + "\n".join(lines) + "\n\n" if lines else ""


def prompt(ctx: ShopContext, q: dict, examples: list[dict], today: dt.date, rule_examples: list[dict] | None = None) -> tuple[str, str]:
    system = f"{SPEC}\n\nRULEBOOK:\n{ctx.rules}"
    ex = "\n".join(f'Câu: {e["question"]}\nHôm nay: {e["as_of_date"]}\n'
                   + json.dumps({"ke_hoach": e["nplan"], "ra": e["type"]}, ensure_ascii=False) for e in examples)
    rx = ""
    if rule_examples:
        rx = "VÍ DỤ ĐỌC ĐỊNH NGHĨA (luật của shop khác):\n" + "\n".join(
            f'Luật: {e["rule"]}\nCâu: {e["question"]}\nHôm nay: {e["as_of_date"]}\n'
            + json.dumps({"cach_tinh": e["cach_tinh"], "ke_hoach": e["plan"], "ra": e["type"]}, ensure_ascii=False) for e in rule_examples) + "\n\n"
    prices = ctx.price_lines(q["question"])
    extra = "LỊCH SỬ GIÁ:\n" + "\n".join(prices) + "\n\n" if prices else ""
    extra += holiday_block(ctx, q["question"])
    near = near_rules(ctx.rules, q["question"])
    focus = "DÒNG LUẬT GẦN VỚI CÂU (đối chiếu trước khi tính):\n" + "\n".join(near) + "\n\n" if near else ""
    user = (f"{readme_block(ctx.con)}DANH MỤC BẢNG CỦA SHOP:\n{ctx.catalog(today)}\n\nBẢNG GỐC (chỉ dùng khi bảng trên không có thông tin):\n"
            f"{raw_catalog(ctx.con, q['question'], ctx.rules)}\n\nVÍ DỤ (của shop khác):\n{ex}\n\n{rx}{extra}{focus}"
            f"Câu: {q['question']}\nHôm nay: {q['as_of_date']}\nTrả về JSON:")
    return system, user


def ask(ctx: ShopContext, q: dict, examples: list[dict], today: dt.date, temperature: float = 0, fix=None, rule_examples: list[dict] | None = None) -> dict:
    """fix = (kế hoạch trước, lỗi): cho LLM xem lỗi để viết lại."""
    system, user = prompt(ctx, q, examples, today, rule_examples)
    if fix:
        user += (f"\n{json.dumps(fix[0], ensure_ascii=False)}\n\nKế hoạch trên không chạy được: {fix[1]}.\n"
                 f"Viết lại toàn bộ, chỉ dùng đúng cú pháp và tên cột trong danh mục. Trả về JSON:")
    text = llm.chat(system, user, max_tokens=900, timeout=300, temperature=temperature)
    start = text.find("{")
    if start < 0:
        return {}
    try:                # chỉ đọc object đầu tiên: LLM có thể viết thêm chữ hoặc JSON khác phía sau
        out, _ = json.JSONDecoder().raw_decode(text, start)
    except json.JSONDecodeError:
        return {}
    return _unwrap(out) if isinstance(out, dict) else {}


def _unwrap(out: dict) -> dict:
    """Kế hoạch viết thiếu lớp bọc "ke_hoach", thành chuỗi JSON hay thành mảng: nghĩa đã rõ, không tốn một lần hỏi lại."""
    if isinstance(out.get("ke_hoach"), str):
        try:
            out = {**out, "ke_hoach": json.loads(out["ke_hoach"])}
        except json.JSONDecodeError:
            pass
    if isinstance(out.get("ke_hoach"), list) and out["ke_hoach"]:
        parts = out["ke_hoach"]
        out = {**out, "ke_hoach": parts[0] if len(parts) == 1 else {"ghep": "danh_sach", "cac": parts}}
    if "ke_hoach" not in out and "khong_co" not in out and ("nguon" in out or "ghep" in out):
        ra = out.get("ra")
        out = {"ke_hoach": {k: v for k, v in out.items() if k not in ("ra", "cach_tinh")}, "ra": ra}
    return out


_MONTH_YEAR = re.compile(r"(?<!\d)(\d{1,2})\s*[/-]\s*(20\d\d)(?!\d)|\bthang\s+(\d{1,2})\s+(?:nam\s+)?(20\d\d)\b")
# tháng với năm 2 chữ số ("th11/25", "1/26", "7-25"): năm 20YY. Không bắt ngày đủ ("5/3/25") hay năm 4 chữ số ("12/2025")
_YY = re.compile(r"(?<![\d/.-])(1[0-2]|0?[1-9])\s*([/-])\s*([23]\d)(?![\d/.-])")


def period_text(question: str) -> str:
    """Câu đã bỏ dấu, năm 2 chữ số của tháng viết thành 4 chữ số: các bộ đọc kỳ chỉ cần biết dạng M/YYYY (§2)."""
    return _YY.sub(lambda m: f"{m[1]}{m[2]}20{m[3]}", fold(question))


def fix_years(plan, question: str):
    """Câu ghi rõ tháng M/Y mà kế hoạch không có kỳ nào đúng M/Y: sửa năm theo câu. Câu nêu M với hai năm thì không đoán."""
    said: dict = {}
    for a, b, c, d in _MONTH_YEAR.findall(period_text(question)):
        said.setdefault(int(a or c), set()).add(int(b or d))

    def months(p):
        if isinstance(p, dict):
            if p.get("loai") == "thang":
                yield p
            for v in p.values():
                yield from months(v)
        elif isinstance(p, list):
            for v in p:
                yield from months(v)
    found = list(months(plan))
    for m, years in said.items():
        same = [k for k in found if k.get("thang") == m]
        if len(years) == 1 and same and not any(k.get("nam") in years for k in same):
            for k in same:
                k["nam"] = next(iter(years))
    return plan


def value_key(v) -> str:
    """Khoá so hai đáp án: theo kết quả chạy, không theo chữ của kế hoạch."""
    def norm(x):
        if isinstance(x, dict) and "names" in x:
            return x["id"]
        if isinstance(x, dict) and "bang" in x:
            return [norm(r) for r in x["bang"]]
        if isinstance(x, list):
            return [norm(i) for i in x]
        return x
    return json.dumps(norm(v), ensure_ascii=False, sort_keys=True, default=str)


def outside_data(ctx: ShopContext, plan, today: dt.date) -> bool:
    """§7: có kỳ của bảng bán nằm HOÀN TOÀN ngoài khoảng ngày có đơn."""
    try:
        s, e = ctx.con.execute("SELECT CAST(sales_start AS DATE), CAST(sales_end AS DATE) FROM _meta_shop").fetchone()
    except duckdb.Error:
        return False
    if s is None or e is None:
        return False

    def walk(p):
        if not isinstance(p, dict):
            return False
        if any(walk(x) for x in p.get("cac") or []):
            return True
        if p.get("ky") and p.get("nguon") in ("dong_ban", "don"):
            try:
                a, b = resolve_period(p["ky"], today, ctx.con)
            except (PlanError, KeyError, TypeError, ValueError):
                return False
            return b < s or a > e
        return False
    return walk(plan)


def _shape_ok(v, ra) -> bool:
    """Kết quả chạy có đúng kiểu đáp án LLM đã khai không (lệch nghĩa là kế hoạch không làm đúng điều câu hỏi cần)."""
    is_num = isinstance(v, (int, float)) and not isinstance(v, bool)
    return {"number": is_num, "percent": is_num, "boolean": isinstance(v, bool), "list": isinstance(v, list) or (isinstance(v, dict) and "bang" in v),
            "table": isinstance(v, list) or (isinstance(v, dict) and "bang" in v), "date": isinstance(v, str),
            "string": isinstance(v, str) or (isinstance(v, dict) and "names" in v)}.get(ra, True)


_NO_RETRY = re.compile(r"không thấy|mẫu số bằng 0|không có dữ liệu|không có dòng|giá vốn|khớp \d+ mã|đúng một")


_ASKS_RATIO = re.compile(r"%|phan tram|\b(ti|ty)\b|\bchiem\b|\bphan\b|tang|giam|thay doi|chenh|\bhon\b|\bkem\b|so (voi|vs|vơi)")
_ASKS_AVG = re.compile(r"trung binh|binh quan|\btb\b|\bmoi\b|\bmot\b|\b1\b|\bgia\b")


def _ratio_unasked(plan, question: str) -> str | None:
    """Kế hoạch tính tỉ lệ / trung bình mà câu không hề hỏi (ví dụ gần giống hay kéo LLM về đó) -> lỗi để viết lại."""
    if not isinstance(plan, dict):
        return None
    f = fold(question)
    if plan.get("ghep") in ("ti_le", "tang_truong") and not _ASKS_RATIO.search(f):
        return "câu không hỏi phần trăm: trả thẳng giá trị câu hỏi, không dùng ti_le / tang_truong"
    if plan.get("ghep") == "thuong" and not _ASKS_AVG.search(f):
        return "câu không hỏi trung bình: trả thẳng giá trị câu hỏi, không dùng thuong"
    return None


_ASKS_STATUS = re.compile(r"huy|\bbom\b|tra hang|tra lai|hoan tra|hoan hang|khong lay|dang giao|dang ship|van chuyen"
                          r"|trang thai|ke ca|moi don|tat ca don|hoan thanh|da giao|thanh cong")
_ASKS_RX = re.compile(r"ke don|theo don|khong can don")
_ASKS_DATE = re.compile(r"\b(ngayf?|hom|tuan|thangs?|quy|nam) naof?\b|\bkhi nao\b|\bbao gio\b|\bhan dung\b|\bhet han\b|\b(ngay|thang) may\b"
                        r"|\blan (cuoi|dau|gan)\b|\bngay (ban|mua|nhap|gan)")
# câu hỏi một ngày ("ngày nào", "ngày naoo / mô", "ngày đông khách nhất"): đáp án là ngày. Trên đáp án thật mẫu này chỉ bắt
# câu có đáp án là ngày (train, gen_hl, hard thiết kế)
ASKS_DAY = re.compile(r"\b(?:ngay|hom)\s+(?:nao+|mo|may)\b|\bkhi nao\b|\bbao gio\b|^\s*ngay\s+(?:dong|dat|vang|nhieu|it|ban)\b[^?]*\bnhat\b"
                      r"|\bngay\s+(?:dong|dat|vang)\s+khach\s+nhat\b")
_ASKS_COUNT = re.compile(r"\b(bao nhieu|bao nhiu|bnhiu|bn|may|so)\b")
_ASKS_NAMES = re.compile(r"\b(nhung|liet ke|la gi|nao|top|danh sach|cac|ke ten)\b")
_IS_DATE = re.compile(r"\d{4}-\d{2}(-\d{2})?")


def _leaves(plan):
    if isinstance(plan, dict):
        if "ghep" in plan:
            for p in plan.get("cac") or []:
                yield from _leaves(p)
        else:
            yield plan


_VALID = {"hoan_thanh", "dang_giao"}
_INVALID = {"huy", "tra_hang"}


def _valid_like(c: dict) -> bool:
    """Lọc trạng thái chỉ để lấy đơn hợp lệ (§1), việc code đã làm: = hoàn thành, != huỷ / trả, trong {hoàn thành, đang giao}."""
    op, gt = c.get("op", "="), c.get("gt")
    if op == "=":
        return gt == "hoan_thanh"
    if op == "!=":
        return gt in _INVALID
    if op == "in" and isinstance(gt, list):
        return "hoan_thanh" in gt and set(gt) <= _VALID
    return False


_ASKS_CHANGE_PCT = re.compile(r"(chenh|tang|giam|hon|kem|thay doi)[^?]{0,25}(%|phan tram)|(%|phan tram)[^?]{0,15}(chenh|tang|giam|hon|kem)")


def clean_plan(plan, question: str):
    """Bỏ phần LLM tự thêm mà code đã áp hoặc câu không hỏi: dòng là mặt hàng khi cộng tiền, lọc lấy đơn hợp lệ,
    thuốc kê đơn, mọi trạng thái khi đếm đơn. Đổi nghĩa thì câu phải nói ra, nên chỉ bỏ khi câu không nhắc tới."""
    f = fold(question)
    asks_status = bool(_ASKS_STATUS.search(f))
    # không vế nào lọc trạng thái và câu không hỏi trạng thái: "mọi trạng thái" là LLM tự thêm, kể cả trong tỉ lệ, thương
    any_status = any(isinstance(c, dict) and c.get("cot") == "trang_thai" and not _valid_like(c)
                     for p in _leaves(plan) for c in p.get("loc") or [])

    def walk(p, alone):
        if not isinstance(p, dict):
            return p
        if "ghep" in p:
            p = {**p, "cac": [walk(x, alone and p["ghep"] == "danh_sach") for x in p.get("cac") or []]}
            # "chênh / tăng / giảm bao nhiêu %" giữa hai vế ngang hàng (ca chiều với ca sáng): phần trăm thay đổi, không
            # phải tỉ số (rulebook: (kỳ hỏi − kỳ so) / kỳ so × 100). Tỉ lệ phần / tổng giữ nguyên
            parts = p["cac"]
            if p["ghep"] == "ti_le" and len(parts) == 2 and all(isinstance(x, dict) for x in parts)                     and _ASKS_CHANGE_PCT.search(f) and not _is_part(parts[0], parts[1]) and not _is_part(parts[1], parts[0]):
                p["ghep"] = "tang_truong"
            return p
        p = dict(p)
        if isinstance(p.get("loc"), list):
            keep = []
            for c in p["loc"]:
                col = c.get("cot") if isinstance(c, dict) else None
                if (col == "la_mat_hang" and p.get("cot") in MONEY) or (col == "ke_don" and not _ASKS_RX.search(f)) \
                        or (col == "trang_thai" and _valid_like(c) and not asks_status):
                    continue
                keep.append(c)
            p["loc"] = keep
        status = any(isinstance(c, dict) and c.get("cot") == "trang_thai" for c in p.get("loc") or [])
        if p.get("moi_trang_thai") and not status and not asks_status and p.get("phep") != "gia_duy_nhat" \
                and (alone and p.get("phep") in ("dem", "dem_khac") or not alone and not any_status):
            p.pop("moi_trang_thai")
        if p.get("phep") == "hang_e" and _ASKS_COUNT.search(f) and not _ASKS_NAMES.search(f):
            p["phep"] = "dem_e"
        return p
    return walk(plan, True)


def _is_zero(v) -> bool:
    if isinstance(v, bool):
        return False
    if isinstance(v, list):
        return bool(v) and all(_is_zero(x) for x in v)
    return isinstance(v, (int, float)) and v == 0


_YES_NO = re.compile(r"\b(co phai|phai khong|phai ko|dung khong|dung ko|hay khong|duoc khong)\b"
                     r"|\b(khong|khoong|ko|k|kh|hok|hong|hem|khum|hk)"
                     r"(\s+(ha|hay|vay|vaay|vaayj|nhi|nha|nhe|a|ah|ak|z|ta|the|v|shop|ban|ad|dzay|day))*\s*[?.!]*\s*$"
                     r"|\bchua\s*[?.!]*\s*$")


def asks_yes_no(question: str) -> bool:
    """Câu hỏi có / không, đáp án đúng / sai: "... không?", "có phải ... không", "đúng không" (kể cả viết tắt cuối câu)."""
    return bool(_YES_NO.search(fold(question).strip().lower()))


_STAFF = re.compile(r"\bnhan vien\b|\bnv\b|\bthu ngan\b|\bnguoi ban\b|\btho\b")
_CUSTOMER = re.compile(r"\bkhach\b")
_ONE_MONTH = re.compile(r"\bthang\s+(\d{1,2})\s*(?:/|nam)\s*(20\d\d)\b")


def _periods(p):
    if isinstance(p, dict):
        for k, v in p.items():
            if k in ("ky", "den_het") and isinstance(v, dict):
                yield v
            yield from _periods(v)
    elif isinstance(p, list):
        for x in p:
            yield from _periods(x)


def _mismatch(plan, v, question: str) -> str | None:
    """Kết quả không khớp điều câu hỏi: lỗi để LLM viết lại. Bỏ phiếu không bắt được lỗi này khi các lần sai giống nhau."""
    f = fold(question)
    leaves = list(_leaves(plan))
    if isinstance(plan, dict) and plan.get("ghep") in ("ti_le", "tang_truong", "thuong", "hieu", "lon_hon"):
        parts = [json.dumps(x, sort_keys=True, ensure_ascii=False) for x in plan.get("cac") or []]
        if len(parts) == 2 and parts[0] == parts[1]:
            return "hai vế của phép ghép giống hệt nhau: vế đầu phải có điều kiện câu hỏi nêu"
    if asks_yes_no(question) and not isinstance(v, bool):
        return "câu hỏi có / không: kết quả phải là đúng / sai (so sánh bằng lon_hon, tang_lien_tuc...), không phải giá trị"
    if ASKS_DAY.search(f) and isinstance(v, (int, float)) and not isinstance(v, bool):
        return 'câu hỏi ngày nào: kết quả là ngày ("nhom": "ngay", xếp rồi lấy tên), không phải con số'
    # câu hỏi đúng một tháng M/Y mà kế hoạch tính cả năm: kỳ phải là tháng đó
    months = set(_ONE_MONTH.findall(f))
    kinds = {k.get("loai") for k in _periods(plan)}
    if len(months) == 1 and "nam" in kinds and not kinds & {"thang", "khoang", "quy", "tu_ngay", "ky_truoc", "cung_ky_nam_truoc"}:
        m, y = next(iter(months))
        return f'câu hỏi tháng {m}/{y}: kỳ là {{"loai": "thang", "thang": {int(m)}, "nam": {y}}}, không phải cả năm'
    # câu hỏi nhân viên mà kế hoạch xếp khách, hay ngược lại
    groups = {p.get("nhom") for p in leaves}
    if "khach" in groups and _STAFF.search(f) and not _CUSTOMER.search(f):
        return "câu hỏi về nhân viên: nhóm theo nhan_vien, không theo khach"
    if "nhan_vien" in groups and _CUSTOMER.search(f) and not _STAFF.search(f):
        return "câu hỏi về khách: nhóm theo khach, không theo nhan_vien"
    for p in leaves:
        for c in p.get("loc") or []:
            if isinstance(c, dict) and c.get("cot") == "trang_thai" and not _ASKS_STATUS.search(f):
                return "câu không hỏi theo trạng thái đơn: bỏ lọc trang_thai"
    if "hoat chat" in f and not any(isinstance(c, dict) and c.get("cot") == "hoat_chat" for p in leaves for c in p.get("loc") or []):
        return "câu hỏi theo hoạt chất: phải lọc cột hoat_chat"
    if isinstance(v, str) and _IS_DATE.fullmatch(v) and not (_ASKS_DATE.search(f) or ASKS_DAY.search(f)):
        return "câu không hỏi ngày nào: trả thẳng con số câu hỏi cần, không dùng nhom và xep"
    if isinstance(v, list) and v and isinstance(v[0], dict) and _ASKS_COUNT.search(f) and not _ASKS_NAMES.search(f):
        return "câu hỏi số lượng, không hỏi danh sách tên"
    # §7: không có dữ liệu không phải 0; số 0 đúng thật rất hiếm, thường là lọc sai cột, sai tên hoặc đếm sai đối tượng
    if _is_zero(v) and not any(p.get("phep") == "dem_e" for p in leaves):
        return "kết quả bằng 0: xem lại cột lọc, tên và đối tượng đếm"
    return None


def _attempt(ctx: ShopContext, out: dict, today: dt.date, question: str = "") -> tuple:
    """Chạy một câu trả lời của LLM -> (loại, chi tiết, kế hoạch, giá trị)."""
    if "khong_co" in out and "ke_hoach" not in out:
        return "llm_khong_co", str(out["khong_co"])[:150], None, None
    if "ke_hoach" not in out:
        return "loi", "không có kế hoạch", None, None
    plan = clean_plan(fix_years(out["ke_hoach"], question), question)
    if question and (why := _ratio_unasked(plan, question)):
        return "loi", why, plan, None
    try:
        if outside_data(ctx, plan, today):
            return "ngoai_ky", "kỳ ngoài khoảng dữ liệu", plan, None
        v = Runner(ctx.con, today, ctx.facts).run(plan)
        ra = out.get("ra")
        if isinstance(v, list) and len(v) == 1 and ra not in ("list", "table"):
            v = v[0]
        if ra == "list" and isinstance(v, dict) and "bang" in v:                # câu chỉ hỏi danh sách: bỏ cột số
            v = [row[0] for row in v["bang"]]
        if ra == "list" and isinstance(plan, dict) and plan.get("ghep") == "danh_sach" and not isinstance(v, list):
            ra = None                                                           # danh sách một vế là một giá trị
        if ra in ("number", "percent") and isinstance(v, dict) and "names" in v and isinstance(plan, dict) and plan.get("nhom") \
                and (plan.get("xep") or {}).get("lay") == 1:
            # hỏi một con số mà kế hoạch trả đối tượng đứng đầu (vd đơn lớn nhất trị giá bao nhiêu): lấy số đo của nó
            plan = {**plan, "cot_ra": "gia_tri"}
            v = Runner(ctx.con, today, ctx.facts).run(plan)
        if not _shape_ok(v, ra):
            raise PlanError(f"khai \"ra\": \"{ra}\" nhưng kế hoạch trả về {str(v)[:60]}")
        if question and (why := _mismatch(plan, v, question)):
            return "loi", why, plan, None
        to_record("", v, _want(plan, out.get("ra")))
        return "tra_loi", value_key(v), plan, v
    except MissingData as e:
        return "thieu_nguon", str(e)[:150], plan, None
    except PlanError as e:
        msg = str(e)
        # cột viết sai là lỗi kế hoạch; "shop không ghi", "không có nguồn" mới là thiếu dữ liệu thật
        missing = "không có cột" not in msg and re.search(r"không có |shop không ghi|không ghi", msg)
        return ("thieu_nguon" if missing and not _NO_RETRY.search(msg) else "loi"), msg[:150], plan, None
    except (AttributeError, KeyError, TypeError, ValueError, duckdb.Error) as e:
        return "loi", f"{type(e).__name__}: {e}"[:150], plan, None


def solve(ctx: ShopContext, q: dict, bank: ExampleBank, skip_shop=None, skip_kinds=None, temps=(0, 0.5, 0.9),
          skip_shops=None, rule_bank: RuleBank | None = None, skip_dong=None) -> dict:
    """Một câu -> {'value', 'want', 'loai': tra_loi|ngoai_ky|thieu_nguon|llm_khong_co|khong_dong_thuan|loi, 'plans', ...}.
    Hỏi tối đa 3 lần, mỗi lần sai cú pháp được cho xem lỗi để viết lại một lần; chỉ nhận khi 2 lần ra CÙNG kết quả chạy.
    Quyết định nộp hay bỏ trống do bước sau."""
    today = dt.date.fromisoformat(q["as_of_date"])
    ex = bank.pick(q["question"], ctx.names_in(q["question"]), skip_shop=skip_shop, skip_kinds=skip_kinds, skip_id=q["id"],
                   skip_shops=skip_shops)
    rx = rule_bank.pick(q["question"], near_rules(ctx.rules, q["question"]), skip_shop=skip_shop, skip_dong=skip_dong,
                        need="plan") if rule_bank else None
    tally: Counter = Counter()
    keep: dict = {}
    notes = []
    for t in temps:
        out = ask(ctx, q, ex, today, temperature=t, rule_examples=rx)
        kind, detail, plan, v = _attempt(ctx, out, today, q["question"])
        if kind == "loi" and not _NO_RETRY.search(detail):
            notes.append(("sua", detail))
            out = ask(ctx, q, ex, today, temperature=t, fix=(out.get("ke_hoach", out), detail), rule_examples=rx)
            kind, detail, plan, v = _attempt(ctx, out, today, q["question"])
        if kind == "tra_loi":
            keep[detail] = {"value": v, "want": _want(plan, out.get("ra")), "plan": plan}
        notes.append((kind, detail))
        key = (kind, detail) if kind == "tra_loi" else (kind, "")
        tally[key] += 1
        (top, n), = tally.most_common(1)
        if n >= 2:
            if top[0] == "tra_loi":
                return {"loai": "tra_loi", **keep[top[1]], "notes": notes, "n_examples": len(ex)}
            return {"loai": top[0], "notes": notes, "plan": plan}
    return {"loai": "khong_dong_thuan", "notes": notes}


# Kết thúc được nộp là "không trả lời được" (§7). Các loại khác không đủ chắc: bỏ trống.
UNANSWERABLE = {"thieu_nguon", "ngoai_ky"}


def final_record(qid: str, r: dict) -> dict:
    """Kết quả solve -> dòng nộp."""
    if r["loai"] == "tra_loi":
        try:
            return to_record(qid, r["value"], r["want"])
        except PlanError:       # giá trị không nộp được (đối tượng không tên, NaN): bỏ trống, không nộp bậy
            return {"id": qid, "type": "abstain"}
    # khong_ghi (hybrid.both): hai đường cùng kết luận shop không ghi thông tin đó; không qua guard_unanswerable
    return {"id": qid, "type": "unanswerable" if r["loai"] in UNANSWERABLE or r["loai"] == "khong_ghi" else "abstain"}


# Dạng đáp án theo câu hỏi (§9: bảng chỉ khi câu bảo lập bảng / hỏi nhiều đối tượng kèm số đo). Trên đáp án thật: câu
# "lần lượt / theo thứ tự" (không "bảng", "lập") là list ở 26/26 câu train, 35/35 gen_hl; câu "top k / những ... nào" không
# đòi kèm số đo là list / string ở 121/121 train, 96/96 gen_hl, không câu nào là bảng.
_ASKS_IN_ORDER = re.compile(r"\blan luot\b|theo (dung )?thu tu")
_ASKS_RANKED = re.compile(r"\btop \d+\b|\b\d+ (mon|mat hang|khach|san pham|hang|dong|loai)\b.*\b(nao|nhat)\b"
                          r"|\bnhung (mon|mat hang|khach|san pham|hang|loai)\b.*\bnao\b")
_ASKS_TABLE = re.compile(r"\bbang\b|\blap\b")
_ASKS_MEASURE = re.compile(r"\bkem\b|\btung\b|\bmoi\b|\bcung so\b|\bva so\b|\bbao nhieu\b|\bbn\b|\bgom\b")


def shape(q: dict, rec: dict) -> dict:
    """Bảng nộp cho câu hỏi một dãy: "lần lượt" các tháng -> list giá trị theo thứ tự câu nêu; "top k ..." -> list tên
    theo thứ tự xếp (một dòng -> string). Không đổi gì khi không chắc."""
    if rec.get("type") != "table":
        return rec
    f = fold(q["question"])
    rows = rec["answer"]["rows"]
    if _ASKS_TABLE.search(f) or not rows:
        return rec
    if _ASKS_IN_ORDER.search(f) and all(len(r) == 2 for r in rows):
        from datamate.query.sql_tier import _asked_periods
        months = [m[0] for p in _asked_periods(q["question"], dt.date.fromisoformat(q["as_of_date"])) for m in [p[3]] if len(m) == 1]
        by = {str(r[0])[:7]: r[1] for r in rows}
        if len(months) >= 2 and len(months) == len(rows) and all(m in by for m in months):
            return {"id": rec["id"], "type": "list", "answer": [by[m] for m in months]}
    if _ASKS_RANKED.search(f) and not _ASKS_MEASURE.search(f):
        names = [r[0] for r in rows]
        return {"id": rec["id"], "type": "string", "answer": names[0]} if len(names) == 1 else \
            {"id": rec["id"], "type": "list", "answer": names}
    return rec


def _want(plan, ra) -> str | None:
    if isinstance(plan, dict) and plan.get("ghep") in ("ti_le", "tang_truong"):
        return "percent"
    return ra if ra == "percent" else None
