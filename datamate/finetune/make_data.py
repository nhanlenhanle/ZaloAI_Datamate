"""Dữ liệu fine-tune LLM lớp data (Qwen3.5-9B, LoRA): đúng các prompt pipeline gửi, đáp án lấy từ train.

Năm việc, cùng định dạng chat (system / user / assistant), prompt dựng bằng chính hàm của pipeline:
  nhan      : xếp nhãn lạ vào mã (labels.label_prompt): nhãn thật của train (mã do luật đã kiểm với đáp án)
              + nhãn từ BỘ TỪ HUẤN LUYỆN dưới đây + nhãn rác ('khong_ro')
  ghi_chu   : ghi chú có nói trạng thái đơn không (labels.label_prompt, note_status)
  khach_le  : nhãn khách lẻ trong các tên hay gặp (labels.walk_in_prompt)
  quy_uoc   : đọc quy ước README (conventions.readme_prompt): README train + câu quy ước chèn từ bộ câu huấn luyện
  map_cot   : tên chuẩn cho cột (mapping.llm_map_prompt): cột train, đáp án = tên chuẩn đã kiểm; tên cột đổi bằng
              bộ tên huấn luyện, có / không có mô tả README, có lúc bỏ tên đúng khỏi danh sách (đáp án null)
  sua_o     : ô số / ngày viết lạ -> chuỗi chuẩn (repair.repair_prompt): ô thật của train viết lại theo kiểu huấn
              luyện ("SL:2", "TT 245.000", số chữ kiểu "ngàn", ngày kèm thứ); bộ đo dùng kiểu khác ("x2", "(đã CK)",
              "nghìn", "Mar 05, 2025")
Chống học vẹt bộ đo (datamate/stress): mọi nhãn, tên cột, câu quy ước bộ đo dùng đều bị loại (kể cả gần giống:
trùng khi bỏ dấu hay chứa nhau). Các shop HOLDOUT (5 họ) không góp gì: đo trên chúng là đo shop lạ thật.

    python -m datamate.finetune.make_data ../train/train "../solve data/train" "../solve data/finetune"
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
from collections import Counter

import duckdb
import pandas as pd

from datamate.loader.build import _CHANNEL_NORM, _PAYMENT_NORM, _code_norm
from datamate.loader.conventions import _SYSTEM as CONV_SYSTEM, NOT_RECORDED, readme_prompt
from datamate.loader.labels import CODESETS, label_prompt, walk_in_prompt
from datamate.loader.mapping import canonical_vocab, llm_map_prompt
from datamate.loader.parsers import fold, is_walk_in, norm_status, parse_date, parse_number
from datamate.loader.readme import parse_readme
from datamate.loader.repair import repair_prompt
from datamate.stress import mutate as bench
from datamate.tests.audit_mapping import load_inputs

# 5 họ shop (mỗi họ một shop) giữ riêng: tạp hoá xlsx, cà phê csv, VLXD, nhà thuốc sqlite, nhà hàng
HOLDOUT = ["biz_107", "biz_111", "biz_113", "biz_123", "biz_126"]

# ---------------------------------------------------------------- bộ từ huấn luyện (khác bộ đo)
TRAIN_LABELS = {
    "status": {
        "hoan_thanh": ["Đã hoàn thành", "Giao thành công", "Khách đã nhận", "Đã giao xong", "Đơn xong", "Completed",
                       "Chốt xong", "Nhận hàng OK", "Hoàn thành ✓", "Đã thanh toán đủ", "Finished", "Ok rồi"],
        "huy": ["Hủy", "Đơn hủy bỏ", "Cancelled", "Hủy - hết hàng", "Không giao được", "Giao thất bại", "Từ chối nhận",
                "Khách không nghe máy", "Hủy bởi shop", "Void", "Khách đổi ý không mua"],
        "tra_hang": ["Trả lại", "Đã trả", "Hoàn hàng về kho", "Returned", "Trả một phần", "Đổi hàng", "Refund",
                     "Hoàn tiền cho khách", "Khách gửi trả", "Return"],
        "dang_giao": ["Đang giao hàng", "Chờ lấy hàng", "Chờ xác nhận", "Đang xử lý", "In transit",
                      "Đã bàn giao vận chuyển", "Shipper đang giao", "Chờ giao lại", "Pending", "Đang trên đường"],
    },
    "payment": {
        "tien_mat": ["Thanh toán tiền mặt", "Cash on hand", "Tiền mặt (TM)", "Nhận tiền mặt", "Đưa tiền mặt"],
        "chuyen_khoan": ["CK Vietcombank", "Bank transfer", "Quét QR", "CK MB", "Chuyển khoản NH", "STK cá nhân"],
        "the": ["Thẻ tín dụng", "Cà thẻ", "Thanh toán thẻ", "Credit card", "Thẻ ghi nợ", "Debit card"],
        "vi": ["Momo", "Shopee Pay", "ViettelPay", "Apple Pay", "Ví Viettel"],
        "cod": ["Giao hàng thu tiền", "Thu tiền khi giao", "COD - GHTK", "Ship COD", "Nhận hàng trả tiền"],
        "ghi_no": ["Nợ", "Mua chịu", "Ghi sổ nợ", "Công nợ", "Nợ lại", "Khách nợ", "Cho nợ", "Gối đầu"],
    },
    "channel": {
        "tai_quay": ["Tại cửa hàng", "Khách tới quán", "Offline", "Bán lẻ tại chỗ", "Walk-in store"],
        "dien_thoai": ["Gọi đặt", "Đặt qua điện thoại", "SĐT", "Phone order"],
        "zalo": ["Zalo cá nhân", "Đặt qua Zalo"],
        "facebook": ["Messenger", "Page FB", "Facebook shop"],
        "shopee": ["Shopee Mall", "Đơn Shopee"],
        "lazada": ["Lazada", "Sàn Lazada"],
        "tiktok": ["TikTok Shop", "Tiktok live"],
        "grab": ["Grab Food", "Baemin", "Be Food", "Gojek"],
        "website": ["Web shop", "Trang web", "Đặt trên website"],
    },
}
JUNK = ["Bàn 5", "Ca sáng", "Mã KM10", "x", "Khác", "Chưa rõ", "Loại 2", "???", "0", "Kho 1", "Ghi chú"]
NOTE_TRAIN = {
    "huy": ["Khách hủy do đổi ý", "Hủy vì hết hàng", "Không liên lạc được, hủy", "Shop hủy đơn"],
    "tra_hang": ["Trả lại 1 hộp", "Khách mang trả vì hư", "Đổi trả size", "Hàng lỗi, khách trả về"],
    "dang_giao": ["Đang ship, khách hẹn chiều", "Chờ giao lại ngày mai", "Đã gửi xe, chưa nhận"],
    "khong_nhac": ["Giao giờ hành chính", "Khách quen", "Gói quà giúp", "Xuất hóa đơn VAT", "Ít đá", "Giao trước 5h",
                   "Gọi trước khi giao", "Thêm đường", "Lấy hóa đơn đỏ", "Khách VIP"],
}
WALK_TRAIN = ["Khách ghé", "Khách đi đường", "N/A", "-", "Anonymous", "Khách tại quầy", "Vô danh", "Khách vô",
              "Khách lạ", "Walk in"]
NAME_NEG = ["Chị Lan", "Anh Tú", "Cô Ba", "Cty TNHH An Phát", "Quán Bà Tư", "Nhà thuốc Minh Châu", "Chú Sáu",
            "Trường MN Hoa Sen", "Đại lý Hùng Cường", "Bác Hai"]
HEADER_TRAIN = {
    "order_id": ["Mã chứng từ", "Số đơn", "Số HĐ bán", "Mã phiếu xuất", "Order ID"],
    "order_date": ["Ngày bán hàng", "Ngày xuất", "Ngày GD", "Order date"],
    "order_time": ["Giờ bán", "Thời điểm bán", "Time"],
    "product_name": ["Tên mặt hàng", "Sản phẩm", "Product"],
    "product_id": ["Mã hàng hóa", "Product code", "Mã SKU"],
    "qty": ["Số lượng bán", "Quantity", "SL xuất"],
    "unit": ["Đơn vị bán", "UoM"],
    "unit_price": ["Giá bán/đv", "Unit price", "Đơn giá xuất"],
    "line_amount": ["Thành tiền dòng", "Line total", "Tiền dòng"],
    "customer_name": ["Tên người mua", "Khách mua", "Buyer"],
    "customer_id": ["Mã người mua", "Mã khách hàng", "Cust ID"],
    "status": ["Trạng thái HĐ", "Order status", "Tình trạng đơn"],
    "payment_method": ["Hình thức TT", "Phương thức trả tiền", "Pay type"],
    "channel": ["Kênh đặt", "Nguồn bán", "Sales channel"],
    "order_total": ["Tổng cần thu", "Grand total", "Phải thu"],
    "paid": ["Tiền khách đưa", "Đã thanh toán", "Amount received"],
    "debt": ["Nợ còn lại", "Outstanding", "Công nợ còn"],
    "staff_name": ["Nhân viên bán", "Thu ngân ca", "Cashier"],
    "category": ["Nhóm sản phẩm", "Ngành hàng", "Product group"],
    "supplier_name": ["Nhà phân phối", "Vendor", "Đơn vị cung cấp"],
    "stock_qty": ["Tồn kho cuối", "Stock", "Còn lại trong kho"],
    "expiry_date": ["HSD", "Expiry", "Hạn dùng đến"],
}
MONEY_PHRASES = [  # (câu, đơn vị); câu bộ đo dùng ở bench.TIEN_NGHIN_RULE
    ("Các cột tiền ghi theo đơn vị nghìn đồng (1 = 1.000đ).", 1000),
    ("Số tiền trong sổ tính bằng ngàn đồng.", 1000),
    ("ĐVT tiền: 1.000 VNĐ.", 1000),
    ("Tiền ghi gọn, bỏ ba số 0 cuối (25 nghĩa là 25.000đ).", 1000),
    ("Đơn vị tiền tệ trong file: triệu đồng.", 1000000),
    ("Tiền ghi theo đồng, đã gồm VAT.", 1),
    ("Giá bán đã gồm thuế.", None),
]
STATUS_COL_PHRASES = [
    "Đơn hủy hay trả hàng được ghi chú ở cột {col}; không ghi gì là đơn đã xong.",
    "Sổ không có cột tình trạng đơn, chủ tiệm ghi 'hủy', 'trả' vào cột {col}.",
    "Trạng thái đơn (hủy / trả / đang giao) nằm trong cột {col}, ô trống nghĩa là đơn hoàn thành.",
]
WALK_PHRASES = ["Khách không để tên ghi là \"{label}\".", "Khách lẻ ghi \"{label}\" ở cột tên khách."]
NOT_REC_PHRASES = {"gio_ban": "Sổ không ghi giờ bán.", "ma_khach": "Không có mã khách hàng.",
                   "nhan_vien": "Sổ không ghi người bán.", "gia_von": "Không ghi giá vốn."}


def _f(s) -> str:
    return re.sub(r"\s+", " ", fold(str(s))).strip()


def _bench_strings() -> set[str]:
    out = set()
    for pool in (bench.STATUS_LABELS, bench.PAYMENT_LABELS, bench.CHANNEL_LABELS, bench.HEADER_SYNONYMS):
        for vals in pool.values():
            out.update(_f(v) for v in vals)
    out.update(_f(v) for v in bench.WALK_IN_LABELS)
    out.update(_f(v) for v in bench._NOTE_TEXT.values())
    return out


BENCH = _bench_strings()


def blocked(s: str) -> bool:
    """Nhãn trùng / chứa / nằm trong một nhãn của bộ đo (so bỏ dấu)."""
    f = _f(s)
    return any(f == b or (len(b) >= 4 and (b in f or (len(f) >= 4 and f in b))) for b in BENCH)


def chat(system: str, user: str, answer) -> dict:
    return {"messages": [{"role": "system", "content": system}, {"role": "user", "content": user},
                         {"role": "assistant", "content": json.dumps(answer, ensure_ascii=False)}]}


# ---------------------------------------------------------------- nguồn train

def real_labels(shops: list[str], train_out: str) -> dict[str, list[dict]]:
    """kind -> [ {nhãn: số dòng} của một cột một shop ], kèm mã luật (đã kiểm với đáp án train)."""
    out = {"status": [], "payment": [], "channel": [], "note": [], "names": []}
    for shop in shops:
        con = duckdb.connect(os.path.join(train_out, shop, f"{shop}.duckdb"), read_only=True)
        for (t,) in con.execute("SELECT table_name FROM _meta_tables").fetchall():
            cols = {r[0] for r in con.execute(f'DESCRIBE "{t}"').fetchall()}
            for col, kind in (("status", "status"), ("purchase_status", "status"), ("payment_method", "payment"),
                              ("channel", "channel"), ("order_note", "note"), ("note", "note"),
                              ("customer_name", "names")):
                if col in cols:
                    rows = con.execute(f'SELECT CAST("{col}" AS VARCHAR), count(*) FROM "{t}" WHERE "{col}" '
                                       f'IS NOT NULL GROUP BY 1 ORDER BY 2 DESC LIMIT 200').fetchall()
                    if rows:
                        out[kind].append(dict(rows))
        con.close()
    return out


def _code(kind: str, v: str) -> str | None:
    if kind == "status":
        return norm_status(v)
    c = _code_norm(v, _PAYMENT_NORM if kind == "payment" else _CHANNEL_NORM)
    return None if c == "khac" else c


# ---------------------------------------------------------------- các việc

def gen_labels(real: dict, rng: random.Random, n: int) -> list[dict]:
    ex = []
    kinds = ["status"] * 5 + ["payment"] * 3 + ["channel"] * 2
    for _ in range(n):
        kind = rng.choice(kinds)
        counts, gold = {}, {}
        # nhãn thật của một cột (đa số) - như khi luật vẫn nhận một phần
        if real[kind] and rng.random() < 0.5:
            col = rng.choice(real[kind])
            for v, c in list(col.items())[:rng.randint(1, 6)]:
                code = _code(kind, v)
                if code and not blocked(v):
                    counts[v], gold[v] = c, code
        # nhãn lạ từ bộ huấn luyện
        pool = TRAIN_LABELS[kind]
        for code in rng.sample(list(pool), k=min(len(pool), rng.randint(1, 4))):
            v = rng.choice(pool[code])
            if blocked(v) or v in counts:
                continue
            counts[v] = int(rng.lognormvariate(4, 1.5)) + 1
            gold[v] = code
        if rng.random() < 0.3:
            v = rng.choice(JUNK)
            if v not in counts:
                counts[v], gold[v] = int(rng.lognormvariate(2, 1)) + 1, "khong_ro"
        if not counts:
            continue
        if kind == "status":           # nhãn nhiều dòng nhất là hoàn thành (như shop thật)
            top = max(counts, key=counts.get)
            if gold[top] != "hoan_thanh":
                done = [v for v in counts if gold[v] == "hoan_thanh"]
                if done:
                    counts[done[0]] = counts[top] * rng.randint(3, 30)
        system, user, top = label_prompt(kind, counts, rng.choice(["Trạng thái", "Tình trạng", "status", ""])
                                         if kind == "status" else "")
        ex.append(chat(system, user, {v: gold[v] for v, _ in top}))
    return ex


def gen_notes(real: dict, rng: random.Random, n: int) -> list[dict]:
    ex = []
    real_notes = [v for col in real["note"] for v in col if norm_status(v) is None and not blocked(v)]
    for _ in range(n):
        counts, gold = {}, {}
        for code, vals in NOTE_TRAIN.items():
            for v in rng.sample(vals, k=rng.randint(0, min(2, len(vals)))):
                counts[v], gold[v] = rng.randint(1, 40), code
        for v in rng.sample(real_notes, k=min(len(real_notes), rng.randint(0, 3))):
            counts[v], gold[v] = rng.randint(1, 40), "khong_nhac"
        if not counts:
            continue
        system, user, top = label_prompt("note_status", counts, "Ghi chú")
        ex.append(chat(system, user, {v: gold[v] for v, _ in top}))
    return ex


def gen_walk_in(real: dict, rng: random.Random, n: int) -> list[dict]:
    ex = []
    for _ in range(n):
        col = rng.choice(real["names"]) if real["names"] else {}
        counts, gold = {}, {}
        for v, c in list(col.items())[:8]:
            if not blocked(v):
                counts[v], gold[v] = c, bool(is_walk_in(v))
        if rng.random() < 0.7:
            v = rng.choice([w for w in WALK_TRAIN if not blocked(w)])
            counts[v], gold[v] = max(list(counts.values()) + [10]) * rng.randint(2, 20), True
        for v in rng.sample(NAME_NEG, k=rng.randint(1, 3)):
            counts.setdefault(v, rng.randint(2, 60))
            gold.setdefault(v, False)
        system, user, top = walk_in_prompt(counts, total=sum(counts.values()) + rng.randint(0, 500))
        if top:
            ex.append(chat(system, user, {v: gold[v] for v, _ in top}))
    return ex


_NOT_REC_RX = {"ma_don": r"khong ghi ma (don|hoa don|phieu)", "ten_khach": r"khong ghi ten khach",
               "ma_khach": r"khong (ghi|co) ma khach", "ma_hang": r"khong (ghi|co) ma hang",
               "gio_ban": r"khong ghi gio", "nhan_vien": r"khong ghi (nguoi ban|nhan vien)"}


def gen_conventions(shops: list[str], data_dir: str, rng: random.Random, per_shop: int) -> list[dict]:
    ex = []
    for shop in shops:
        base = parse_readme(os.path.join(data_dir, shop, "README.md"))
        cols = {}
        for d in base.columns:
            cols.setdefault(d.file or "?", []).append(d.column)
        text_cols = [c for d in base.columns for c in [d.column] if fold(d.description).startswith(("ghi chu", "dien giai"))]
        for k in range(per_shop):
            r = parse_readme(os.path.join(data_dir, shop, "README.md"))
            nr = [x for x, rx in _NOT_REC_RX.items() if re.search(rx, fold(r.intro or ""))]
            gold = {"don_vi_tien": None, "cot_trang_thai": None, "trong_la_hoan_thanh": None, "nhan_khach_le": [],
                    "khong_ghi": nr, "khac": []}
            if k > 0:                                     # bản 0: README nguyên gốc
                if rng.random() < 0.5:
                    s, scale = rng.choice(MONEY_PHRASES)
                    r.conventions.append(("Tiền", s))
                    gold["don_vi_tien"] = scale
                if text_cols and rng.random() < 0.4:
                    col = rng.choice(text_cols)
                    s = rng.choice(STATUS_COL_PHRASES).format(col=col)
                    r.intro = (r.intro or "").rstrip() + " " + s
                    gold["cot_trang_thai"] = col
                    gold["trong_la_hoan_thanh"] = True if ("trống" in s or "không ghi gì" in s) else None
                if rng.random() < 0.3:
                    label = rng.choice([w for w in WALK_TRAIN if not blocked(w)])
                    r.intro = (r.intro or "").rstrip() + " " + rng.choice(WALK_PHRASES).format(label=label)
                    gold["nhan_khach_le"] = [label]
                if rng.random() < 0.3:
                    key = rng.choice(list(NOT_REC_PHRASES))
                    r.intro = (r.intro or "").rstrip() + " " + NOT_REC_PHRASES[key]
                    gold["khong_ghi"] = sorted(set(gold["khong_ghi"]) | {key})
            if any(blocked(x) for x in gold["nhan_khach_le"]):
                continue
            ex.append(chat(CONV_SYSTEM, readme_prompt(r, cols), gold))
    return ex


def _meaning(desc, canon, vocab) -> str:
    text = str(desc) if isinstance(desc, str) and desc.strip() else vocab.get(canon or "", "")
    return " ".join(re.sub(r"[`*]", "", text).split()[:12])


def gen_mapping(shops: list[str], train_out: str, rng: random.Random, per_table: int) -> list[dict]:
    ex = []
    vocab = canonical_vocab()
    for shop in shops:
        out = os.path.join(train_out, shop)
        mp = pd.read_csv(os.path.join(out, "_mapping.csv"))
        inputs = {t.name: t for t in load_inputs(out)}
        for table, g in mp.groupby("table", sort=False):
            tin = inputs.get(table)
            if tin is None:
                continue
            # chỉ cột luật đã map làm đáp án: cột luật để trống lẫn cả cột thật sự không có tên chuẩn ("Thương hiệu")
            # lẫn cột luật bỏ sót ("Slg" là số lượng) -> đáp án null sẽ dạy sai; null học từ ví dụ bỏ tên khỏi danh sách
            rows = [r for r in g.itertuples() if r.kind != "empty" and isinstance(r.canonical, str)]
            for _ in range(per_table):
                if not rows:
                    break
                targets = rng.sample(rows, k=min(len(rows), rng.randint(1, 5)))
                known = [(r.column, r.canonical) for r in rows if r not in targets and isinstance(r.canonical, str)]
                drop = set()
                if rng.random() < 0.15:                   # tên đúng không có trong danh sách -> null
                    drop = {r.canonical for r in targets if isinstance(r.canonical, str)}
                unmapped, gold = [], {}
                for r in targets:
                    name = r.column
                    canon = r.canonical if isinstance(r.canonical, str) else None
                    x = rng.random()
                    if canon in HEADER_TRAIN and x < 0.4:
                        alt = rng.choice(HEADER_TRAIN[canon])
                        name = alt if not blocked(alt) else name
                    elif x < 0.55:
                        name = fold(name)
                    vals = [v for v in dict.fromkeys(tin.raw.get(r.column, [])) if v is not None][:8]
                    desc = r.description if (isinstance(r.description, str) and rng.random() < 0.5) else None
                    unmapped.append({"column": name, "kind": r.kind, "description": desc, "samples": vals})
                    gold[name] = {"nghia": _meaning(r.description, canon, vocab),
                                  "ten": None if (canon in drop or canon not in vocab) else canon}
                v = {k: m for k, m in vocab.items() if k not in drop}
                system, user = llm_map_prompt(table, unmapped, known, v)
                ex.append(chat(system, user, gold))
    return ex


_DIGITS = ["không", "một", "hai", "ba", "bốn", "năm", "sáu", "bảy", "tám", "chín"]


def _ngan(x: int) -> str | None:
    """245000 -> 'hai trăm bốn mươi lăm ngàn' (kiểu 'ngàn'; bộ đo dùng 'nghìn')."""
    words = bench.so_thanh_chu(x)
    return words.replace("nghìn", "ngàn").replace("lẻ", "linh") if words else None


def _odd_train(kind: str, v, rng: random.Random):
    """(ô viết lạ, chuỗi chuẩn) theo kiểu HUẤN LUYỆN (khác bench._odd)."""
    if kind == "date":
        d = parse_date(v)
        if d is None or d.hour or d.minute:
            return None
        wd = ["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "CN"][d.weekday()]
        s = rng.choice([f"{wd}, {d:%d/%m/%Y}", f"{d:%d/%m/%Y} ({wd})", f"{d.day} tháng {d.month}/{d.year}"])
        return s, d.strftime("%Y-%m-%d")
    x = parse_number(v)
    if not isinstance(x, (int, float)) or isinstance(x, bool) or x <= 0 or not float(x).is_integer():
        return None
    x = int(x)
    if kind == "qty":
        return rng.choice([f"SL:{x}", f"{x}sp", f"#{x}"]), str(x)
    words = _ngan(x)
    if words and rng.random() < 0.5:
        return words, str(x)
    return rng.choice([f"TT {x:,}".replace(",", "."), f"{x:,}đ - đã thu".replace(",", "."),
                       f"giá {x:,}".replace(",", ".")]), str(x)


def gen_repair(shops: list[str], train_out: str, rng: random.Random, per_col: int) -> list[dict]:
    """Ô số / ngày viết lạ -> chuỗi chuẩn (repair.repair_prompt); ô mẫu là ô thật của cột train."""
    ex = []
    junk = ["chưa nhập", "?", "xem lại", "ghi sau", "hỏi chị Lan"]
    for shop in shops:
        out = os.path.join(train_out, shop)
        mp = pd.read_csv(os.path.join(out, "_mapping.csv"))
        inputs = {t.name: t for t in load_inputs(out)}
        for r in mp.itertuples():
            canon = r.canonical if isinstance(r.canonical, str) else None
            kind = "money" if canon in bench.MONEY else "qty" if canon == "qty" else \
                "date" if canon in ("order_date", "purchase_date") else None
            tin = inputs.get(r.table)
            if not kind or tin is None:
                continue
            vals = [v for v in dict.fromkeys(tin.raw.get(r.column, [])) if v is not None]
            if len(vals) < 8:
                continue
            for _ in range(per_col):
                good = [str(v) for v in rng.sample(vals, k=min(6, len(vals)))]
                bad, gold = [], {}
                for v in rng.sample(vals, k=min(len(vals), rng.randint(1, 6))):
                    o = _odd_train(kind, v, rng)
                    if o and o[0] not in gold and not blocked(o[0]):
                        bad.append(o[0])
                        gold[o[0]] = o[1]
                if rng.random() < 0.3:
                    j = rng.choice(junk)
                    bad.append(j)
                    gold[j] = None
                if not bad:
                    continue
                system, user = repair_prompt(r.column, "datetime" if kind == "date" else "number", bad, good)
                ex.append(chat(system, user, gold))
    return ex


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("train_root")
    ap.add_argument("train_out")
    ap.add_argument("out_dir")
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    rng = random.Random(a.seed)
    shops = sorted(s for s in os.listdir(os.path.join(a.train_root, "data")) if s.startswith("biz_"))
    train_shops = [s for s in shops if s not in HOLDOUT]
    real = real_labels(train_shops, a.train_out)
    parts = {
        "nhan": gen_labels(real, rng, 1400),
        "ghi_chu": gen_notes(real, rng, 250),
        "khach_le": gen_walk_in(real, rng, 300),
        "quy_uoc": gen_conventions(train_shops, os.path.join(a.train_root, "data"), rng, 14),
        "map_cot": gen_mapping(train_shops, a.train_out, rng, 6),
        "sua_o": gen_repair(train_shops, a.train_out, rng, 2),
    }
    allx = [(k, e) for k, v in parts.items() for e in v]
    rng.shuffle(allx)
    n_val = max(50, len(allx) // 20)
    os.makedirs(a.out_dir, exist_ok=True)
    for name, chunk in (("val", allx[:n_val]), ("train", allx[n_val:])):
        with open(os.path.join(a.out_dir, f"{name}.jsonl"), "w", encoding="utf-8") as fh:
            for _, e in chunk:
                fh.write(json.dumps(e, ensure_ascii=False) + "\n")
    manifest = {"holdout_shops": HOLDOUT, "train_shops": train_shops, "counts": {k: len(v) for k, v in parts.items()},
                "val": n_val, "train": len(allx) - n_val, "bench_strings_blocked": len(BENCH)}
    with open(os.path.join(a.out_dir, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=1)
    print(json.dumps(manifest["counts"], ensure_ascii=False), "val", n_val, "train", len(allx) - n_val)


if __name__ == "__main__":
    main()
