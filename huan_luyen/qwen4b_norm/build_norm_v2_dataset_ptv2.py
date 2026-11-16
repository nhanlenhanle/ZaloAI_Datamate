"""Build clean, rule-aware, hard-balanced ChatML dataset for Qwen3.5-4B Normalizer (v2).

Nguồn dữ liệu:
  - Tập train của BTC (biz_101..biz_130).
  - Bộ tự sinh bo_tu_sinh_v2 (biz_501..biz_536, 2.473 câu):
      đầu vào = questions.jsonl["question"] (câu nhiễu), đích = answers.jsonl["raw"] (câu sạch),
      che thực thể bằng đúng hàm runtime extract_and_mask, luật lấy từ bo_tu_sinh_v2/rulebook.md.

Hai chế độ:
  python build_norm_v2_dataset_ptv2.py            -> dựng từ đầu  -> OUT_DIR/full_gold_norm_v2_chatml.jsonl
  python build_norm_v2_dataset_ptv2.py --cleaned  -> gộp thêm dòng bo_tu_sinh_v2 và chuẩn hóa
        -> OUT_DIR/full_gold_norm_v2_chatml_cleaned.jsonl
"""
from __future__ import annotations

import json
import os
import random
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

import duckdb

ROOT = Path(os.environ.get("DATAMATE_ROOT", "/app"))
sys.path.insert(0, str(ROOT))

PTV2_DIR = Path(os.environ.get("SYNTH_V2_DIR", "data/bo_tu_sinh_v2"))
OUT_DIR = Path(os.environ.get("NORM_OUT_DIR", "."))

from datamate.loader.parsers import fold
from datamate.query.compose import near_rules
from datamate.query.normalize_all import extract_and_mask

NORM_SYSTEM_PROMPT_V2 = (
    "Bạn là chuyên gia chuẩn hóa câu hỏi tiếng Việt cho bài toán Text-to-SQL quản lý bán hàng.\n"
    "Nhiệm vụ: Sửa lỗi chính tả, teencode, viết tắt, thêm dấu và chuẩn hóa câu hỏi rõ ràng về hình thức và kiểu trả về (bảng, danh sách, %).\n"
    "Nếu có mục \"Luật liên quan:\", PHẢI giữ nguyên đúng tên thuật ngữ trong luật, không tự ý đổi sang chỉ số khác và không tự chèn giải thích dài trong ngoặc.\n"
    "TUYỆT ĐỐI GIỮ NGUYÊN các thẻ placeholder <ENT_X>. Chỉ trả về đúng 1 câu chuẩn hóa."
)

FOREIGN_RE = re.compile(r"[\u0400-\u04FF\u4E00-\u9FFF\u3040-\u30FF\uAC00-\uD7AF\u0E00-\u0E7F]")
ENT_TAG_RE = re.compile(r"<ENT_\d+>")
PAREN_BOILER_RE = re.compile(r"\s*\(tổng số lượng quy đổi cao nhất\)", re.I)

_SHOP_RULES_CACHE: dict[str, str] = {}


def load_shop_rules(shop: str) -> str:
    if not shop:
        return ""
    if shop in _SHOP_RULES_CACHE:
        return _SHOP_RULES_CACHE[shop]
    if (PTV2_DIR / "data" / shop).is_dir():
        # bo_tu_sinh_v2: một rulebook chung cho cả 36 shop
        txt = (PTV2_DIR / "rulebook.md").read_text(encoding="utf-8")
        _SHOP_RULES_CACHE[shop] = txt
        return txt
    for sub in ("train",):
        db_p = ROOT / "data" / "solve_data" / sub / shop / f"{shop}.duckdb"
        if db_p.exists():
            try:
                con = duckdb.connect(str(db_p), read_only=True)
                rows = con.execute("SELECT text FROM _rulebook ORDER BY seq").fetchall()
                con.close()
                txt = "\n".join(r[0] or "" for r in rows)
                _SHOP_RULES_CACHE[shop] = txt
                return txt
            except Exception:
                pass
    _SHOP_RULES_CACHE[shop] = ""
    return ""


def format_user(masked_q: str, rule_lines: list[str] | None = None) -> str:
    if rule_lines:
        rules_block = "\n".join(line.strip() for line in rule_lines[:3] if line.strip())
        return f"Luật liên quan:\n{rules_block}\n\nCâu hỏi: {masked_q}"
    return f"Câu hỏi: {masked_q}"


def make_msg(user_text: str, assistant_text: str, meta: dict | None = None) -> dict:
    row = {
        "messages": [
            {"role": "system", "content": NORM_SYSTEM_PROMPT_V2},
            {"role": "user", "content": user_text},
            {"role": "assistant", "content": assistant_text},
        ]
    }
    if meta:
        row.update(meta)
    return row


def skel(s: str) -> str:
    s = ENT_TAG_RE.sub("<ENT>", s)
    s = re.sub(r"\b\d+\b", "<N>", s)
    return re.sub(r"\s+", " ", s.lower()).strip()


def difficulty_score(user_q: str) -> tuple[int, int, int]:
    """Higher score = harder input (no accents, abbreviations, longer/multi-clause)."""
    has_accents = 1 if fold(user_q) != user_q.lower() else 0
    abbr_hits = len(re.findall(r"\b(dthu|bnhiu|bn|ko|k|dc|đc|th\d+|t\d+|hqua|hnay|sp|kh|nv|ncc|sl|tb)\b", user_q.lower()))
    return (1 - has_accents, abbr_hits, len(user_q))


def noisify_vietnamese(text: str, rng: random.Random, strip_accents_prob: float = 0.45) -> str:
    """Create realistic noisy Vietnamese variations while preserving <ENT_X> and numbers."""
    parts = re.split(r"(<ENT_\d+>)", text)
    repls = [
        (r"\bdoanh thu\b", ["dthu", "dt", "tiền bán"]),
        (r"\bbao nhiêu\b", ["bnhiu", "bn", "nhiêu"]),
        (r"\bkhông\b", ["ko", "k", "hong"]),
        (r"\bđược\b", ["đc", "dc"]),
        (r"\bhôm nay\b", ["hnay", "hôm nay"]),
        (r"\bhôm qua\b", ["hqua", "hôm qua"]),
        (r"\bkhách hàng\b", ["khách", "kh"]),
        (r"\bnhân viên\b", ["nv", "nhân viên"]),
        (r"\bnhà cung cấp\b", ["ncc", "nhà cung cấp"]),
        (r"\bsản phẩm\b", ["sp", "món"]),
        (r"\bphần trăm\s*\(%\)", ["%", "phan tram", "mấy %"]),
        (r"\bphần trăm\b", ["%", "phan tram"]),
        (r"\bTháng\s+(\d{1,2})/(\d{2,4})\b", [r"T\1/\2", r"th\1/\2", r"\1-\2"]),
        (r"\btháng\s+(\d{1,2})/(\d{2,4})\b", [r"t\1/\2", r"th\1/\2", r"\1/\2"]),
        (r"\btháng\s+(\d{1,2})\s+năm\s+(\d{4})\b", [r"T\1/\2", r"th\1/\2"]),
    ]
    do_strip = rng.random() < strip_accents_prob
    out_parts = []
    for p in parts:
        if ENT_TAG_RE.fullmatch(p):
            out_parts.append(p)
            continue
        cur = p
        for pat, cands in repls:
            if re.search(pat, cur, flags=re.I) and rng.random() < 0.55:
                cur = re.sub(pat, rng.choice(cands), cur, count=1, flags=re.I)
        if do_strip:
            cur = fold(cur)
        elif rng.random() < 0.3:
            cur = cur[0].lower() + cur[1:] if cur else cur
        out_parts.append(cur)
    res = re.sub(r"\s+", " ", "".join(out_parts)).strip()
    if rng.random() < 0.25 and res.endswith("?"):
        res = res[:-1] + rng.choice([" z?", " nhỉ?", " vậy?", " ạ?", ""])
    return res


def clean_assistant_text(a: str) -> str:
    a = PAREN_BOILER_RE.sub("", a)
    a = a.replace("утра", "trưa")
    a = re.sub(r"\bsố cùng kỳ\b", "so với cùng kỳ", a)
    return re.sub(r"\s+", " ", a).strip()


def load_blind_test_texts() -> set[str]:
    blind = set()
    for p in [
        Path("data/gen_do/questions.jsonl"),
    ]:
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    blind.add(json.loads(line)["question"].strip().lower())
    return blind


PTV2_ENT_COLS = {"hang", "nhom_hang", "nhom_khach", "khach", "nhan_vien", "ncc", "nha_cung_cap"}


def _ascii_low(s: str) -> str:
    """Bỏ dấu + chữ thường, giữ nguyên độ dài (từng ký tự NFC -> 1 ký tự)."""
    out = []
    for ch in s:
        d = unicodedata.normalize("NFD", ch)
        base = "".join(c for c in d if unicodedata.category(c) != "Mn") or ch
        out.append(base[0].replace("đ", "d").replace("Đ", "D").lower())
    return "".join(out)


def _ptv2_shop_entities() -> dict[str, list[str]]:
    """Danh mục thực thể mỗi shop, giống vai trò catalog DuckDB ở runtime:
    giá trị lọc (hàng, nhóm hàng, khách, nhóm khách, NV, NCC) trong lời giải + đáp án dạng tên/danh sách."""
    ents: dict[str, set[str]] = defaultdict(set)
    shop_of: dict[str, str] = {}

    def walk(k, shop):
        if isinstance(k, dict):
            for f in k.get("loc", []) or []:
                if f.get("cot") in PTV2_ENT_COLS:
                    vals = f.get("gt") if isinstance(f.get("gt"), list) else [f.get("gt")]
                    for v in vals:
                        if isinstance(v, str) and len(v.strip()) >= 4:
                            ents[shop].add(v.strip())
            for v in k.values():
                walk(v, shop)
        elif isinstance(k, list):
            for v in k:
                walk(v, shop)

    for l in (PTV2_DIR / "loi_giai.jsonl").read_text(encoding="utf-8").splitlines():
        if l.strip():
            r = json.loads(l)
            shop_of[r["id"]] = r["business_id"]
            walk(r.get("ke_hoach"), r["business_id"])
    for l in (PTV2_DIR / "answers.jsonl").read_text(encoding="utf-8").splitlines():
        if not l.strip():
            continue
        a = json.loads(l)
        shop = shop_of.get(a["id"])
        if not shop:
            continue
        if a.get("type") == "string" and isinstance(a.get("answer"), str):
            vals = [a["answer"]]
        elif a.get("type") == "list" and isinstance(a.get("answer"), list):
            vals = [v for v in a["answer"] if isinstance(v, str)]
        else:
            vals = []
        for v in vals:
            if len(v.strip()) >= 4 and not v.strip().isdigit():
                ents[shop].add(v.strip())
    return {s: sorted(v, key=len, reverse=True) for s, v in ents.items()}


def load_ptv2_items(stats: Counter) -> list[dict]:
    """bo_tu_sinh_v2 -> các mục {u_q, a_q, near, meta} giống mục BTC.
    u_q = câu nhiễu đã che <ENT_k> bằng extract_and_mask (như runtime); a_q = câu sạch `raw`, che cùng thẻ."""
    shop_ents = _ptv2_shop_entities()
    answers = {}
    for l in (PTV2_DIR / "answers.jsonl").read_text(encoding="utf-8").splitlines():
        if l.strip():
            a = json.loads(l)
            answers[a["id"]] = a
    items = []
    for l in (PTV2_DIR / "questions.jsonl").read_text(encoding="utf-8").splitlines():
        if not l.strip():
            continue
        q = json.loads(l)
        a = answers.get(q["id"])
        if not a or not str(a.get("raw") or "").strip():
            stats["ptv2_no_raw"] += 1
            continue
        shop = q["business_id"]
        noisy = unicodedata.normalize("NFC", q["question"].strip())
        clean = unicodedata.normalize("NFC", clean_assistant_text(str(a["raw"])))
        clean = clean[0].upper() + clean[1:]
        u_q, ent_map = extract_and_mask(noisy, shop_ents.get(shop, []))
        # che câu đích bằng cùng thẻ: khớp nguyên văn, không thì khớp bỏ dấu/chữ thường cùng độ dài
        a_q = clean
        ok = True
        for tag, val in sorted(ent_map.items(), key=lambda kv: len(kv[1]), reverse=True):
            if val in a_q:
                a_q = a_q.replace(val, tag)
                continue
            idx = _ascii_low(a_q).find(_ascii_low(val))
            if idx == -1:
                ok = False
                break
            a_q = a_q[:idx] + tag + a_q[idx + len(val):]
        if not ok:
            stats["ptv2_tag_not_in_target"] += 1
            continue
        rules = load_shop_rules(shop)
        near = near_rules(rules, a_q, k=2) if rules else []
        items.append({
            "u_q": u_q,
            "a_q": a_q,
            "near": near,
            "meta": {"id": q["id"], "business_id": shop, "source": "ptv2_clean"},
        })
    stats["ptv2_items"] = len(items)
    stats["ptv2_masked"] = sum(1 for it in items if ENT_TAG_RE.search(it["u_q"]))
    return items


def select_capped(items: list[dict], cap: int = 8) -> list[dict]:
    """Giữ tối đa `cap` câu mỗi khung câu, ưu tiên đầu vào khó (như bước 1 bản gốc)."""
    by_skel: dict[str, list[dict]] = defaultdict(list)
    for it in items:
        by_skel[skel(it["a_q"])].append(it)
    out = []
    for _, its in by_skel.items():
        its.sort(key=lambda x: difficulty_score(x["u_q"]), reverse=True)
        for it in its[:cap]:
            out.append(make_msg(format_user(it["u_q"], it["near"]), it["a_q"], it["meta"]))
    return out


def audit(all_rows: list[dict], blind_texts: set[str]) -> tuple[list[dict], Counter]:
    clean_rows = []
    seen_pairs = set()
    skipped = Counter()
    for r in all_rows:
        u = r["messages"][1]["content"]
        a = r["messages"][2]["content"]
        u_q = u.split("Câu hỏi:")[-1].strip()
        if set(ENT_TAG_RE.findall(u_q)) != set(ENT_TAG_RE.findall(a)):
            skipped["tag_mismatch"] += 1
            continue
        if FOREIGN_RE.search(a):
            skipped["foreign_script"] += 1
            continue
        if not a.strip():
            skipped["empty"] += 1
            continue
        if a.lower() in blind_texts or u_q.lower() in blind_texts:
            skipped["heldout_overlap"] += 1
            continue
        pair = (u, a)
        if pair in seen_pairs:
            skipped["exact_dup"] += 1
            continue
        seen_pairs.add(pair)
        clean_rows.append(r)
    return clean_rows, skipped


def write_rows(rows: list[dict], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    cnt = Counter((r.get("source", "unknown"), (r.get("business_id") or "")[:5]) for r in rows)
    print(f"Wrote {len(rows)} rows to {out_path}")
    print("Distribution (source, shop prefix):", dict(sorted(cnt.items(), key=str)))


def main_cleaned():
    """Gộp tập train chuẩn hóa và bộ tự sinh bo_tu_sinh_v2."""
    rng = random.Random(2026)
    blind_texts = load_blind_test_texts()
    src = Path(__file__).resolve().parent / "full_gold_norm_v2_chatml_cleaned.jsonl"
    if not src.exists():
        src = ROOT / "full_gold_norm_v2_chatml_cleaned.jsonl"
    rows = [json.loads(l) for l in src.read_text(encoding="utf-8").splitlines() if l.strip()]
    train_targets = {r["messages"][2]["content"] for r in rows if r.get("source") == "btc_clean"}
    kept, dropped = [], Counter()
    for r in rows:
        if r.get("source") == "identity" and r["messages"][2]["content"] not in train_targets:
            dropped["identity_filtered"] += 1
            continue
        kept.append(r)
    stats = Counter()
    ptv2_rows = select_capped(load_ptv2_items(stats))
    # identity bổ sung từ câu bo_tu_sinh_v2
    pool = [r for r in ptv2_rows if "?" in r["messages"][2]["content"]]
    rng.shuffle(pool)
    ident = []
    for r in pool[:dropped["identity_filtered"]]:
        a_txt, u_txt = r["messages"][2]["content"], r["messages"][1]["content"]
        prefix = u_txt.split("\n\nCâu hỏi:")[0] if u_txt.startswith("Luật liên quan:") else ""
        new_u = f"{prefix}\n\nCâu hỏi: {a_txt}" if prefix else f"Câu hỏi: {a_txt}"
        ident.append(make_msg(new_u, a_txt, {"source": "identity"}))
    print("Filtered:", dict(dropped), "| PTV2:", dict(stats), "| ptv2 rows after cap:", len(ptv2_rows))
    all_rows = kept + ptv2_rows + ident
    rng.shuffle(all_rows)
    all_rows, skipped = audit(all_rows, blind_texts)
    print("Audit filtered:", dict(skipped))
    write_rows(all_rows, OUT_DIR / "full_gold_norm_v2_chatml_cleaned.jsonl")


def main():
    rng = random.Random(2026)
    blind_texts = load_blind_test_texts()

    # 1. BTC train rows: clean, attach near_rules, and cap top repeated skeletons at max 8
    btc_raw = [json.loads(l) for l in (ROOT / "full_gold_norm_chatml.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    by_skel: dict[str, list[dict]] = defaultdict(list)
    stats = Counter()
    for r in btc_raw:
        if not str(r.get("business_id", "")).startswith("biz_"):
            continue
        u_q = r["messages"][1]["content"].strip()
        a_q = clean_assistant_text(r["messages"][2]["content"])
        if not u_q or not a_q:
            continue
        if ENT_TAG_RE.findall(u_q) and set(ENT_TAG_RE.findall(u_q)) != set(ENT_TAG_RE.findall(a_q)):
            continue
        shop = r.get("business_id", "")
        rules = load_shop_rules(shop)
        near = near_rules(rules, a_q, k=2) if rules else []
        by_skel[skel(a_q)].append({
            "u_q": u_q,
            "a_q": a_q,
            "near": near,
            "meta": {"id": r.get("id", ""), "business_id": shop, "source": "btc_clean"},
        })
    # 1b. bo_tu_sinh_v2 (tự sinh): chung bộ giới hạn 8 câu / khung câu
    for it in load_ptv2_items(stats):
        by_skel[skel(it["a_q"])].append(it)
    print("Step 1 stats:", dict(stats))

    btc_selected: list[dict] = []
    for k_skel, items in by_skel.items():
        items.sort(key=lambda x: difficulty_score(x["u_q"]), reverse=True)
        chosen = items[:8]
        for it in chosen:
            btc_selected.append(make_msg(format_user(it["u_q"], it["near"]), it["a_q"], it["meta"]))

    # 2. Rulebook gold (examples_luat + examples_luat_norm) fixed + noisy variants
    assets_dir = ROOT / "docker/assets" if (ROOT / "docker/assets").is_dir() else ROOT / "assets"
    luat_raw = [json.loads(l) for l in (assets_dir / "examples_luat.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    luat_norm = [json.loads(l) for l in (assets_dir / "examples_luat_norm.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]

    DONG_TERM_FIX = {
        "tien_thu": (r"\bdoanh thu\b", "Tiền thu"),
        "hang_dat": (r"\b(hàng|mặt hàng)\s+bán chạy nhất\b", r"\1 đắt nhất"),
        "chu_luc": (r"mặt hàng đã từng bán trước đó nhưng không bán được", "mặt hàng chủ lực"),
        "don_sang": (r"\bđơn hàng\b", "đơn sáng"),
        "mon_ruot": (r"\bMón có lượt bán cao nhất\b", "Món ruột"),
        "mat_huy": (r"\bmặt hàng hủy\b", "mất do huỷ"),
        "thu": (r"\bSố khách mới\b", "Thứ đông khách"),
        "gio_trua": (r"\bgiờ утра\b", "giờ trưa"),
        "no_lau": (r"có tiền còn nợ", "nợ lâu"),
        "ncc_so": (r"nhà cung cấp", "nhà cung cấp"),
        "giam_dong": (r"trên đơn", "trên dòng"),
        "so_mon": (r"\bmới đơn\b", "mỗi đơn"),
        "khach_le": (r"\bkhách vắng mặt\b", "khách vãng lai"),
        "ban_it": (r"\bbán chạy nhất\b", "ế nhất"),
    }

    rule_rows_out: list[dict] = []
    for a_rec, n_rec in zip(luat_raw, luat_norm):
        raw_q = a_rec["question"].strip()
        norm_q = clean_assistant_text(n_rec["question"])
        dong = a_rec.get("dong", "")
        if dong in DONG_TERM_FIX:
            pat, rep = DONG_TERM_FIX[dong]
            norm_q = re.sub(pat, rep, norm_q, flags=re.I)
            if norm_q:
                norm_q = norm_q[0].upper() + norm_q[1:]
        rule_line = str(a_rec.get("rule", "")).strip()
        rule_rows_out.append(make_msg(
            format_user(raw_q, [rule_line] if rule_line else None),
            norm_q,
            {"id": a_rec.get("id", ""), "business_id": a_rec.get("shop", ""), "source": "rulebook_gold"},
        ))
        # Add 1-2 noisy/teencode variants per rule row
        for v_idx in range(2):
            noisy = noisify_vietnamese(raw_q, rng, strip_accents_prob=0.6 if v_idx == 1 else 0.25)
            if noisy != raw_q and noisy.lower() not in blind_texts:
                rule_rows_out.append(make_msg(
                    format_user(noisy, [rule_line] if rule_line else None),
                    norm_q,
                    {"id": f"{a_rec.get('id','')}_v{v_idx}", "business_id": a_rec.get("shop", ""), "source": "rulebook_aug"},
                ))

    # 3. Synthetic rule-swap pairs (teach 4B to follow unseen rules in "Luật liên quan:")
    synthetic_rules = [
        ("Khách VIP", "là khách có tổng doanh thu tích lũy trong kỳ từ 5.000.000 đồng trở lên", [
            ("Tháng <ENT_0> có bao nhiêu khách VIP?", "Tháng <ENT_0> có bao nhiêu khách VIP?"),
            ("thang <ENT_0> co bnhiu khach vip?", "Tháng <ENT_0> có bao nhiêu khách VIP?"),
            ("danh sach khach vip <ENT_0>", "Danh sách khách VIP <ENT_0> dưới dạng danh sách?"),
        ]),
        ("Đơn ship xa", "là đơn giao hàng có phí vận chuyển từ 50.000 đồng trở lên", [
            ("<ENT_0> có mấy đơn ship xa?", "<ENT_0> có mấy đơn ship xa?"),
            ("ti le don ship xa <ENT_0> bn %?", "Tỉ lệ đơn ship xa <ENT_0> là bao nhiêu phần trăm (%)?"),
        ]),
        ("Giờ vàng", "là khung giờ từ 17:00 đến 19:59 hằng ngày", [
            ("dthu gio vang <ENT_0> la bn?", "Doanh thu giờ vàng <ENT_0> là bao nhiêu?"),
            ("<ENT_0> gio vang duoc may don?", "<ENT_0> giờ vàng được mấy đơn?"),
        ]),
        ("Hàng tồn lâu", "là mặt hàng có số ngày tồn kho trên 60 ngày", [
            ("hien co bn mat hang ton lau?", "Hiện có bao nhiêu mặt hàng tồn lâu?"),
            ("bang cac mat hang ton lau <ENT_0>", "Bảng các mặt hàng tồn lâu <ENT_0> dưới dạng bảng?"),
        ]),
        ("Tiền thu thực", "là tổng tiền đã thực nhận trên sổ quỹ, không tính công nợ", [
            ("tien thu thuc <ENT_0> la bnhiu?", "Tiền thu thực <ENT_0> là bao nhiêu?"),
            ("so sanh tien thu thuc <ENT_0> voi thang truoc tang hay giam bn %?", "So sánh tiền thu thực <ENT_0> với tháng trước tăng hay giảm bao nhiêu phần trăm (%)?"),
        ]),
        ("Đơn gấp", "là đơn cần giao trong vòng 2 giờ kể từ lúc đặt", [
            ("th6/2025 co may don gap?", "Tháng 6/2025 có mấy đơn gấp?"),
            ("ti le don gap <ENT_0> bnhiu %?", "Tỉ lệ đơn gấp <ENT_0> là bao nhiêu phần trăm (%)?"),
        ]),
    ]
    for term, defn, pairs in synthetic_rules:
        rline = f"| {term} | {defn} |"
        for raw_q, gold_q in pairs:
            for k_dup in range(15):
                q_in = raw_q if k_dup == 0 else noisify_vietnamese(raw_q, rng, strip_accents_prob=0.5)
                if ENT_TAG_RE.findall(raw_q) and set(ENT_TAG_RE.findall(raw_q)) != set(ENT_TAG_RE.findall(q_in)):
                    continue
                rule_rows_out.append(make_msg(
                    format_user(q_in, [rline]),
                    gold_q,
                    {"source": "rulebook_swap"},
                ))

    # 4. Hard & New-industry noisy variants (clean, zero-hallucination pairs inspired by Nhan_Gen/hard styles)
    hard_templates = [
        ("Từ đầu tuần tới giờ, doanh thu của tiệm tăng hay giảm bao nhiêu phần trăm (%) so với cùng kỳ tuần trước?", None),
        ("Doanh thu 7 ngày qua tính cả hôm nay là bao nhiêu?", None),
        ("Giữa <ENT_0>, <ENT_1> và <ENT_2> thì tháng nào có doanh thu cao nhất?", None),
        ("<ENT_0> trụ nào sạc ra nhiều kWh nhất?", "| Trụ sạc nhiều nhất | tính theo tổng sản lượng điện (kWh) đã sạc trong kỳ |"),
        ("<ENT_0> tổng sản lượng điện sạc của <ENT_1> là bao nhiêu kWh?", None),
        ("<ENT_0> máy in 3D nào hoàn thành nhiều đơn nhất?", None),
        ("<ENT_0> dịch vụ thú y nào mang lại doanh thu cao nhất?", None),
        ("<ENT_0> sách ký gửi nào bán được nhiều cuốn nhất?", None),
        ("<ENT_0> tổng khối lượng đồ giặt sấy nhận trong kỳ là bao nhiêu kg?", None),
        ("<ENT_0> <ENT_1> có số tiền nợ thêm là bao nhiêu và số tiền thu nợ là bao nhiêu?", None),
        ("<ENT_0> top 5 mặt hàng có doanh thu cao nhất dưới dạng bảng?", None),
        ("<ENT_0> danh sách các khách hàng mua từ 3 đơn trở lên dưới dạng danh sách?", None),
        ("So với cùng kỳ tháng trước, số đơn hàng từ đầu tháng đến hôm nay tăng hay giảm bao nhiêu phần trăm (%)?", None),
        ("<ENT_0> trung bình mỗi đơn hàng có giá trị là bao nhiêu?", None),
        ("Có phải <ENT_0> có doanh thu cao hơn tháng trước hay không?", None),
    ]
    hard_rows_out: list[dict] = []
    for clean_q, rline in hard_templates:
        for idx in range(40):
            noisy_q = noisify_vietnamese(clean_q, rng, strip_accents_prob=0.55)
            if noisy_q.lower() in blind_texts:
                continue
            if set(ENT_TAG_RE.findall(noisy_q)) != set(ENT_TAG_RE.findall(clean_q)):
                continue
            hard_rows_out.append(make_msg(
                format_user(noisy_q, [rline] if rline else None),
                clean_q,
                {"source": "hard_new_domain"},
            ))

    # 5. Identity rows (teach 4B not to over-edit already clean questions)
    identity_rows: list[dict] = []
    clean_pool = [r for r in btc_selected if "?" in r["messages"][2]["content"]]
    rng.shuffle(clean_pool)
    for r in clean_pool[:200]:
        a_txt = r["messages"][2]["content"]
        u_txt = r["messages"][1]["content"]
        # preserve rule block if present
        if u_txt.startswith("Luật liên quan:"):
            prefix = u_txt.split("\n\nCâu hỏi:")[0]
            new_u = f"{prefix}\n\nCâu hỏi: {a_txt}"
        else:
            new_u = f"Câu hỏi: {a_txt}"
        identity_rows.append(make_msg(new_u, a_txt, {"source": "identity"}))

    all_rows = btc_selected + rule_rows_out + hard_rows_out + identity_rows
    rng.shuffle(all_rows)

    # Strict Automated Audit + Exact Pair Deduplication
    all_rows, skipped = audit(all_rows, blind_texts)
    print("Audit filtered:", dict(skipped))
    write_rows(all_rows, OUT_DIR / "full_gold_norm_v2_chatml.jsonl")


if __name__ == "__main__":
    if "--cleaned" in sys.argv[1:]:
        main_cleaned()
    else:
        main()
