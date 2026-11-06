"""Thông tin dùng chung của split (lịch, rulebook) và ngành của shop, ghi vào mỗi DuckDB.

- _calendar      : calendar.csv của split (ngày dương, thứ, ngày/tháng/năm âm, nhuận, ngày lễ)
- _tet_periods   : dịp Tết theo rulebook §2: 23 tháng Chạp (năm âm Y-1) -> hết mùng 10 tháng Giêng (năm âm Y)
- _rulebook      : rulebook.md của split cắt theo mục, để phía query lấy đúng mục (vd §6 của ngành shop)
- industry       : suy từ README, cột, tên hàng; kèm bằng chứng, và tên mục §6 tương ứng nếu rulebook có
Đọc từ thư mục của split (không chép cứng): rulebook train và public khác nhau, private có thể khác nữa.
"""
from __future__ import annotations

import os
import re
from collections import Counter

import pandas as pd

from .parsers import fold


def split_root(split_dir: str) -> str:
    """'.../train/train/data' -> '.../train/train' (nơi có calendar.csv, rulebook.md)."""
    d = os.path.abspath(split_dir)
    for cand in (d, os.path.dirname(d)):
        if os.path.exists(os.path.join(cand, "calendar.csv")) or os.path.exists(os.path.join(cand, "rulebook.md")):
            return cand
    return os.path.dirname(d)


def load_calendar(root: str) -> pd.DataFrame | None:
    p = os.path.join(root, "calendar.csv")
    if not os.path.exists(p):
        return None
    # lịch lạ (tên cột khác, không đọc được) không được làm chết cả bộ: thiếu lịch thì chỉ mất phần dùng lịch
    try:
        c = pd.read_csv(p)
    except (ValueError, OSError, UnicodeDecodeError):
        return None
    if "date" not in c.columns:
        # cột ngày đặt tên khác ("ngay"...): cột đầu tiên mà gần hết ô đọc được là ngày
        dates = [col for col in c.columns
                 if c[col].astype(str).str.fullmatch(r"\s*\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}\s*").mean() >= 0.95]
        if not dates:
            return None
        c = c.rename(columns={dates[0]: "date"})
    c["date"] = pd.to_datetime(c["date"].astype(str), errors="coerce", format="mixed")
    c = c[c["date"].notna()]
    if "lunar_leap" in c.columns:
        c["lunar_leap"] = c["lunar_leap"].astype(str).str.lower().isin(["true", "1"])
    return c


def tet_periods(cal: pd.DataFrame | None) -> pd.DataFrame:
    """Mỗi năm âm Y: từ ngày dương của 23/12 âm (năm âm Y-1, tháng không nhuận) đến hết ngày dương của 10/1 âm (năm Y)."""
    cols = ["tet_year", "start_date", "end_date", "days"]
    if cal is None or not {"lunar_day", "lunar_month", "lunar_year"} <= set(cal.columns):
        return pd.DataFrame(columns=cols)
    c = cal[~cal.get("lunar_leap", False)] if "lunar_leap" in cal.columns else cal
    start = c[(c.lunar_month == 12) & (c.lunar_day == 23)].set_index("lunar_year")["date"]
    end = c[(c.lunar_month == 1) & (c.lunar_day == 10)].set_index("lunar_year")["date"]
    rows = [(y, start[y - 1], end[y], (end[y] - start[y - 1]).days + 1) for y in end.index if y - 1 in start.index]
    return pd.DataFrame(rows, columns=cols)


def parse_rulebook(root: str) -> pd.DataFrame:
    """Cắt rulebook theo tiêu đề: (thứ tự, cấp, tiêu đề, đường dẫn tiêu đề, nội dung)."""
    p = os.path.join(root, "rulebook.md")
    cols = ["seq", "level", "heading", "path", "text"]
    if not os.path.exists(p):
        return pd.DataFrame(columns=cols)
    rows, stack, cur, buf = [], [], None, []

    def flush():
        if cur is not None:
            rows.append((len(rows), cur[0], cur[1], " > ".join(h for _, h in stack), "\n".join(buf).strip()))
    with open(p, encoding="utf-8-sig") as f:
        for line in f:
            m = re.match(r"^(#{1,6})\s+(.*)", line.rstrip("\n"))
            if m:
                flush()
                level, head = len(m[1]), m[2].strip()
                stack = [(lv, h) for lv, h in stack if lv < level] + [(level, head)]
                cur, buf = (level, head), []
            else:
                buf.append(line.rstrip("\n"))
    flush()
    return pd.DataFrame(rows, columns=cols)


# ---------------------------------------------------------------- ngành

# (ngành, từ khoá trong README, từ khoá trong tên hàng). Tên ngành trùng cách rulebook §6 đặt tên mục.
INDUSTRIES = [
    ("Cà phê", r"ca phe|cafe|coffee|tra sua|quan nuoc", r"ca phe|tra sua|bac xiu|tra dao|matcha|\((m|l)\)$"),
    ("Nhà thuốc", r"nha thuoc|hieu thuoc|quay thuoc|duoc pham", r"\bvien\b|\bvi\b|siro|\bmg\b|thuoc|khau trang y te"),
    ("Vật liệu xây dựng", r"vat lieu xay dung|\bvlxd\b|xi mang|sat thep", r"xi mang|thep|gach|\bton\b|da 1x2|cat (xay|vang)"),
    ("Mẹ và bé", r"me va be|me & be|\bme be\b", r"\bsua\b.*\b(so|g)\b|\bbim\b|\bta (dan|quan)\b|binh sua|khan uot"),
    ("Sửa xe", r"sua xe|tiem xe|garage|gara", r"thay nhot|bugi|vo xe|ruot xe|ma phanh"),
    ("Cửa hàng điện thoại", r"dien thoai|di dong|smartphone", r"iphone|samsung|\bgb\b|op lung|cuong luc|sac nhanh"),
    ("Nhà hàng", r"nha hang|quan an|quan nhau|quan lau", r"\blau\b|\bcom\b|\bxao\b|nuong|chien|goi\b"),
    ("Tạp hoá", r"tap hoa|bach hoa|sieu thi mini|minimart", r"\bmi\b|nuoc mam|dau an|bot giat|snack|gao\b"),
]
# cột đặc trưng (tên chuẩn) -> ngành
COLUMN_SIGNALS = {"active_ingredient": "Nhà thuốc", "is_prescription": "Nhà thuốc", "batch_id": "Nhà thuốc",
                  "delivery_round": "Vật liệu xây dựng", "driver": "Vật liệu xây dựng",
                  "imei": "Cửa hàng điện thoại", "table_no": "Nhà hàng", "guests": "Nhà hàng"}


def infer_industry(readme, built, rulebook: pd.DataFrame) -> dict:
    """Điểm mỗi ngành = README (3) + cột đặc trưng (2 mỗi cột) + tỉ lệ dòng bán có từ khoá ngành (tối đa 3).
    Trả {industry, industry_score, industry_evidence, rulebook_section}."""
    score, why = Counter(), {}
    text = fold(" ".join([readme.intro if readme else ""] + [b.label for b in built]))
    for name, kw, _ in INDUSTRIES:
        if re.search(kw, text):
            score[name] += 3
            why.setdefault(name, []).append("README")
    cols = {c for b in built for c in b.df.columns}
    for col, name in COLUMN_SIGNALS.items():
        if col in cols:
            score[name] += 2
            why.setdefault(name, []).append(f"cột {col}")
    # tên hàng ở dòng bán; dòng bán chỉ ghi mã hàng thì lấy ở danh mục
    names = []
    for roles in (("sales_lines",), ("products", "stock", "purchase_lines", "price_history")):
        names = [n for b in built if b.role in roles and "product_name" in b.df.columns
                 for n in b.df["product_name"].dropna().astype(str).unique()]
        if names:
            break
    names = pd.Series(names)
    if len(names):
        f = names.map(fold)
        for name, _, kw in INDUSTRIES:
            rx = re.compile(kw)
            share = f.map(lambda s: bool(rx.search(s))).mean()
            if share >= 0.05:
                score[name] += round(3 * min(share / 0.4, 1), 2)
                why.setdefault(name, []).append(f"{share:.0%} tên hàng")
    if not score:
        return {"industry": None, "industry_score": 0, "industry_evidence": None, "rulebook_section": None}
    best, s = score.most_common(1)[0]
    section = None
    if rulebook is not None and len(rulebook):
        heads = rulebook[rulebook.path.str.contains("Theo ngành", na=False) & (rulebook.level >= 3)]
        hit = heads[heads.heading.map(fold) == fold(best)]
        section = hit.heading.iloc[0] if len(hit) else None
    ev = "; ".join(f"{k}: {', '.join(v)} ({score[k]:g})" for k, v in sorted(why.items(), key=lambda x: -score[x[0]]))
    return {"industry": best, "industry_score": float(s), "industry_evidence": ev, "rulebook_section": section}
