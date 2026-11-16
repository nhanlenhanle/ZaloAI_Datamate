"""Luật mặc định viết cứng trong code (lớp dữ liệu + bộ chạy kế hoạch / view SQL) và dòng rulebook tương ứng.

Code tính theo rulebook BTC (train). Bộ đề mới có rulebook riêng: có thể giữ phần lớn dòng, viết rõ
thêm 3, thêm 24, không dòng lõi nào đổi nghĩa; nhưng nếu một bộ đổi nghĩa dòng lõi (vd doanh thu trừ giảm giá đơn) thì code
vẫn tính theo luật cũ -> sai. Ở đây mỗi luật mặc định có:
  - dòng gốc BTC (nguyên văn): dòng của bộ đề giống hệt (bỏ dấu, hoa thường, dấu **) -> luật giữ, không hỏi gì;
  - BẢNG CÂU HỎI có / không kèm đáp án theo luật BTC: dòng khác chữ -> LLM đọc dòng của bộ đề, trả lời từng câu CHỈ theo
    dòng đó ('co' / 'khong' / 'khong_noi'); câu nào trả lời rõ mà khác đáp án mặc định = luật đổi nghĩa. Đọc theo nghĩa nên
    rulebook viết lại câu chữ (bộ sinh, hard) không bị coi là đổi, câu nói vòng mà đổi nghĩa vẫn bắt được;
  - không có LLM: dò chữ (dấu hiệu nghĩa phải có + cụm cấm) cho các luật lõi.
Luật đổi -> câu nào dùng nguồn / cột chịu luật đó thì bỏ trống (0) thay vì nộp số tính theo luật cũ (-1).
Không có dòng (rulebook không nói): giữ luật mặc định.
Đã có luật đọc rulebook để tính đúng (không cần bỏ trống): đơn ghi nợ (verify_answers._debt_base), đơn bán qua sàn (S23e).
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading

from datamate.loader.parsers import fold

DT, DON, NO = {"dong_ban", "don"}, {"don"}, {"cong_no", "dong_tien_no"}

# ma: mã; ten: regex tên dòng (bỏ dấu); goc: dòng BTC; hoi: [(câu hỏi, đáp án BTC)]; nguon: nguồn chịu luật;
# cot: chỉ khi kế hoạch / SQL nhắc một trong các chữ này (None: mọi câu dùng nguồn); dau / cam: dò chữ khi không có LLM;
# moi: kế hoạch / SQL có chữ này là đã tính theo luật mới (không bỏ trống)
LUAT = [
    dict(ma="doanh_thu_hop_le", ten=r"^don (duoc )?tinh (vao )?doanh thu",
         goc="đơn **không huỷ** và **không trả hàng**. Đơn có trả hàng, **kể cả chỉ trả một phần**, là đơn trả hàng: bỏ **cả đơn**. Đơn đang giao vẫn tính",
         hoi=[("Đơn bị huỷ có được tính vào doanh thu không?", "khong"),
              ("Đơn trả hàng có được tính vào doanh thu không?", "khong"),
              ("Khi khách chỉ trả lại một phần hàng của đơn, tiền các món khách GIỮ LẠI của đơn đó có được tính vào doanh thu không?", "khong"),
              ("Đơn đang giao có được tính vào doanh thu không?", "co")],
         nguon=DT, dau=[r"khong huy", r"khong tra", r"mot phan", r"\bca don\b"],
         cam=[r"khong (bo|loai|tinh bo) (ca|toan bo) don", r"chi tru (phan|tien|cac dong|dong)"]),
    dict(ma="doanh_thu_mot_don", ten=r"^doanh thu (cua )?mot don\b",
         goc="tổng **thành tiền các dòng hàng** (đã trừ giảm giá trên từng dòng). **Không** trừ giảm giá trên cả đơn (khuyến mãi theo tổng tiền đơn, voucher shop), **không** cộng thuế VAT, **không** gồm phí giao hàng. **Tiền hàng**, **tiền bán** của đơn bán cùng nghĩa với doanh thu",
         hoi=[("Doanh thu một đơn có trừ giảm giá trên CẢ ĐƠN (voucher, khuyến mãi theo tổng tiền đơn) không?", "khong"),
              ("Doanh thu một đơn có cộng phí giao hàng không?", "khong"),
              ("Doanh thu một đơn có cộng thuế VAT không?", "khong"),
              ("Doanh thu có lấy theo thành tiền dòng hàng đã trừ giảm giá trên từng dòng không?", "co")],
         nguon=DT, moi=r"giam_don|phi_giao|phi_ship", dau=[r"thanh tien|tien (cac )?dong", r"khong\W*(tru )?giam gia (tren |cua )?(ca )?don",
                         r"khong\W*(gom|cong|tinh)( ca)? phi (giao|ship|van chuyen)"]),
    dict(ma="ky_ngay_dat", ten=r"^don thuoc ky nao",
         goc="theo **ngày đặt**, không theo ngày giao hay ngày thu tiền",
         hoi=[("Đơn được tính vào kỳ theo NGÀY ĐẶT đơn (không theo ngày giao, ngày thu tiền) phải không?", "co")],
         nguon=DT, dau=[r"ngay dat"]),
    dict(ma="so_don", ten=r"^so don$",
         goc="chỉ tính đơn không huỷ, không trả; cả khi đếm số đơn có một mặt hàng, số đơn của một khách. **Khách đã mua** trong kỳ là khách có ít nhất một đơn như vậy trong kỳ",
         hoi=[("Khi đếm số đơn có đếm đơn bị huỷ không?", "khong"), ("Khi đếm số đơn có đếm đơn trả hàng không?", "khong")],
         nguon=DT, cot={"dem", "dem_nhom"}, dau=[r"khong huy", r"khong tra"]),
    dict(ma="ti_le_huy", ten=r"^ti le (don )?huy",
         goc="phần trăm đơn huỷ trong **mọi đơn đặt trong kỳ** (theo ngày đặt, **mọi trạng thái**: cả đơn huỷ, đơn trả, đơn đang giao). Làm tròn 2 chữ số thập phân.",
         hoi=[("Đơn bị huỷ có được đếm trong MẪU SỐ (số đơn đem chia) của tỉ lệ huỷ không?", "co"),
              ("Mẫu số của tỉ lệ huỷ có phải CHỈ gồm các đơn đã hoàn thành không?", "khong")],
         nguon=DON, ti_le=True, moi=r"hoan_thanh", dau=[r"moi (don|trang thai)"]),
    dict(ma="don_bi_huy", ten=r"^don (bi )?huy$",
         goc="đơn có trạng thái huỷ. Đơn trả hàng **không** phải đơn huỷ",
         hoi=[("Đơn trả hàng có được coi là đơn huỷ không?", "khong")], nguon=DT, cot={"huy"}),
    dict(ma="dt_thanh_toan", ten=r"^doanh thu theo\b.*\bthanh toan",
         goc="theo hình thức **ghi trên đơn**, không theo lần trả nợ về sau: đơn ghi nợ không tính vào tiền mặt hay chuyển khoản. Đơn **COD** là hình thức riêng, không tính vào tiền mặt",
         hoi=[("Doanh thu theo hình thức thanh toán có lấy theo hình thức ghi trên đơn (không theo lần trả nợ về sau) không?", "co"),
              ("Đơn COD có được tính vào tiền mặt không?", "khong")], nguon=DT, cot={"thanh_toan"}, moi=r"\bcod\b"),
    dict(ma="dt_nhom_khach", ten=r"^doanh thu theo\b.*\bnhom khach",
         goc="nhóm theo cột nhóm khách. Đơn không ghi khách (khách vãng lai) **không thuộc nhóm nào**, kể cả nhóm `lẻ`. Tỉ trọng của nhóm chia cho doanh thu **cả shop** cùng kỳ, tính cả đơn vãng lai",
         hoi=[("Đơn của khách vãng lai (không ghi khách) có thuộc nhóm khách nào không?", "khong"),
              ("Tỉ trọng của một nhóm khách có chia cho doanh thu cả shop (kể cả đơn vãng lai) không?", "co")],
         nguon=DT, cot={"nhom_khach"}, moi=r"khach_le"),
    dict(ma="ban_chay", ten=r"^ban chay",
         goc="theo **số lượng quy về đơn vị cơ bản**, không theo số dòng hay số tiền; bỏ đơn huỷ, trả. Mặt hàng khác đơn vị cơ bản vẫn xếp chung theo số đó. **Bán nhiều nhất**, **bán được nhiều nhất**, **hot nhất** cùng nghĩa với **bán chạy nhất**",
         hoi=[("Bán chạy có xếp theo số lượng quy về đơn vị cơ bản (không theo số tiền, số dòng) không?", "co")],
         nguon=DT, cot={"sl_co_ban", "so_luong"}),
    dict(ma="nv_gioi", ten=r"^nhan vien ban gioi",
         goc="theo **doanh thu** (§1) của nhân viên trong kỳ, không theo số đơn",
         hoi=[("Nhân viên bán giỏi nhất có xếp theo doanh thu (không theo số đơn) không?", "co")], nguon=DT, cot={"nhan_vien"}),
    dict(ma="no_mot_don", ten=r"^no (cua )?mot don",
         goc="phần chưa trả của **tổng đơn** (số khách phải trả cả đơn: đã trừ giảm giá trên cả đơn, **gồm phí giao**), tính các khoản trả đến hết ngày X. Còn nợ = cộng các đơn **còn nợ > 0**",
         hoi=[("Tổng đơn để tính nợ có trừ giảm giá trên cả đơn không?", "co"), ("Tổng đơn để tính nợ có gồm phí giao không?", "co")],
         nguon=NO, dau=[r"giam gia (tren |cua )?(ca )?don", r"phi (giao|ship)"]),
    dict(ma="no_tra_hang", ten=r"^don (duoc )?tinh vao no",
         goc="đơn không huỷ; **đơn trả hàng vẫn tính** nếu còn nợ",
         hoi=[("Đơn trả hàng còn nợ có được tính vào nợ không?", "co"), ("Đơn huỷ có được tính vào nợ không?", "khong")],
         nguon=NO, dau=[r"khong huy", r"tra hang (van|cung) tinh|van tinh"]),
    dict(ma="tuoi_no", ten=r"^tuoi no",
         goc="số ngày tính từ **ngày đặt**, không từ hạn thanh toán. Đơn đặt hôm nay có tuổi nợ **0** ngày, đơn đặt hôm qua **1** ngày",
         hoi=[("Tuổi nợ có tính từ ngày đặt đơn (không từ hạn thanh toán) không?", "co"),
              ("Đơn đặt hôm nay có tuổi nợ 0 ngày không?", "co")], nguon=NO, cot={"tuoi_no"}),
    dict(ma="no_them_tra_no", ten=r"^no them",
         goc="chỉ đơn **ghi nợ**, không huỷ. **Nợ thêm**: phần tổng đơn chưa trả ngay trong ngày mua, của đơn đặt trong kỳ. **Trả nợ / thu nợ**: các khoản trả **sau ngày mua** có ngày trả trong kỳ, của mọi đơn ghi nợ (kể cả đơn kỳ trước, đơn trả hàng). Tiền trả cùng ngày mua là trả lúc mua. Hoàn tiền trả hàng không trừ",
         hoi=[("Khoản khách trả CÙNG NGÀY mua có được tính là trả nợ / thu nợ không?", "khong")], nguon={"dong_tien_no"}),
    dict(ma="tien_nhap", ten=r"^tien nhap( hang)?( trong ky)?",
         goc="tổng tiền các phiếu nhập có **ngày phiếu** trong kỳ, bỏ phiếu huỷ. Phiếu, dòng ghi **nhập đầu kỳ** là phiếu nhập như mọi phiếu khác: có ngày phiếu trong kỳ thì tính. Nhà cung cấp nhập nhiều nhất = nhà cung cấp có tiền nhập cao nhất",
         hoi=[("Phiếu nhập bị huỷ có được tính vào tiền nhập không?", "khong"),
              ("Phiếu nhập đầu kỳ có ngày trong kỳ có được tính vào tiền nhập không?", "co")],
         nguon={"phieu_nhap", "dong_nhap"}),
]

# từ khoá (bỏ dấu) để chọn gạch đầu dòng README / §6 cần hỏi theo từng luật
TU_KHOA = {
    "doanh_thu_hop_le": r"tra (hang|lai)|mot phan|khach tra",
    "doanh_thu_mot_don": r"giam gia|voucher|khuyen mai|chiet khau|phi (giao|ship)|\bship\b|\bvat\b|\bthue\b",
    "ky_ngay_dat": r"ngay (giao|dat|thu tien)|thuoc ky|tinh theo ngay",
    "so_don": r"so don|dem don",
    "ti_le_huy": r"ti le huy",
    "don_bi_huy": r"don huy|huy don|bi huy",
    "dt_thanh_toan": r"\bcod\b|thu ho|tien mat|thanh toan khi nhan",
    "dt_nhom_khach": r"vang lai|khach le|nhom (khach|le)",
    "ban_chay": r"ban chay|ban nhieu nhat",
    "nv_gioi": r"nhan vien .*(gioi|nhat)",
    "no_mot_don": r"cong no|con no|ghi no|\bno\b",
    "no_tra_hang": r"cong no|ghi no|\bno\b",
    "tuoi_no": r"tuoi no",
    "no_them_tra_no": r"tra no|thu no|no them",
    "tien_nhap": r"phieu nhap|tien nhap|nhap hang",
}

_SYS = ("Bạn đọc MỘT dòng luật trong rulebook của một bộ đề về sổ bán hàng. Trả lời từng câu hỏi CHỈ theo đúng dòng luật đó: "
        "\"co\" (dòng luật nói có / đúng), \"khong\" (dòng luật nói không / sai), \"khong_noi\" (dòng luật không nói tới). "
        "Không suy đoán theo thói quen hay luật ở nơi khác. Trả về JSON {\"1\": ..., \"2\": ...}.")


def _norm(t: str) -> str:
    return re.sub(r"\s+", " ", fold(re.sub(r"[*`]", "", t))).strip(" .")


def _rows(rules: str) -> list[tuple[str, str]]:
    out = []
    for line in rules.split("\n"):
        if line.startswith("|") and not line.startswith("|-"):
            c = [x.strip() for x in line.strip().strip("|").split("|")]
            if len(c) >= 2:
                out.append((_norm(c[0]), " ".join(c[1:])))
    return out


def _hoi_llm(ten: str, text: str, hoi: list) -> dict | None:
    """{số câu: 'co' | 'khong' | 'khong_noi'} hoặc None (không gọi được LLM / trả lời không đọc được)."""
    from datamate.loader import llm
    if not llm.available():
        return None
    user = f"Dòng luật: | {ten} | {text} |\n\nCâu hỏi:\n" + "\n".join(f"{i + 1}. {q}" for i, (q, _) in enumerate(hoi))
    try:
        out = llm.chat(_SYS, user, max_tokens=200, timeout=120)
        s = out.find("{")
        d, _ = json.JSONDecoder().raw_decode(out, s)
        return {str(k): fold(str(v)).replace(" ", "_") for k, v in d.items()}
    except Exception:           # noqa: BLE001 - không đọc được thì coi như không biết (dò chữ)
        return None


def _do_chu(l: dict, hit: list[str]) -> str | None:
    t = [_norm(x) for x in hit]
    thieu = [d for d in l.get("dau", []) if not any(re.search(d, x) for x in t)]
    co = [c for c in l.get("cam", []) if any(re.search(c, x) for x in t)]
    return f"dò chữ: thiếu {thieu}, có {co}" if thieu or co else None


_memo: dict[str, dict] = {}
_lock = threading.Lock()


def luat_doi(rules: str, dung_llm: bool = True) -> dict[str, str]:
    """{mã luật: lý do} của các luật mặc định mà rulebook này đổi nghĩa. Nhớ theo nội dung rulebook (mọi shop một bộ đề)."""
    key = f"{dung_llm}|{rules}"
    with _lock:
        if key in _memo:
            return _memo[key]
    rows = _rows(rules or "")
    out = {}
    for l in LUAT:
        hit = [(n, t) for n, t in rows if re.search(l["ten"], n)]
        if not hit:
            continue
        if all(_norm(t) == _norm(l["goc"]) for _, t in hit):
            continue
        tl = _hoi_llm(hit[0][0], " ".join(t for _, t in hit), l["hoi"]) if dung_llm else None
        if tl is not None:
            lech = [f"{q} -> {tl.get(str(i + 1))} (BTC: {d})" for i, (q, d) in enumerate(l["hoi"])
                    if tl.get(str(i + 1)) in ("co", "khong") and tl.get(str(i + 1)) != d]
            if lech:
                out[l["ma"]] = "LLM: " + "; ".join(lech)
        elif (why := _do_chu(l, [t for _, t in hit])):
            out[l["ma"]] = why
    with _lock:
        _memo[key] = out
    return out


def _gach(text: str) -> list[str]:
    return [l.strip()[2:].strip() for l in (text or "").split("\n") if l.strip().startswith(("- ", "* "))]


def luat_doi_dong(lines: list[str]) -> dict[str, str]:
    """Như luat_doi cho các gạch đầu dòng (§6 riêng của shop, quy ước README): mỗi luật hỏi trên các dòng có từ khoá của nó."""
    key = "dong|" + "\n".join(lines)
    with _lock:
        if key in _memo:
            return _memo[key]
    out = {}
    for l in LUAT:
        kw = TU_KHOA.get(l["ma"])
        hit = [x for x in lines if kw and re.search(kw, fold(x))][:4]
        if not hit:
            continue
        tl = _hoi_llm("quy ước riêng của shop", " ".join(hit), l["hoi"])
        if tl is None:
            continue
        lech = [f"{q} -> {tl.get(str(i + 1))} (BTC: {d})" for i, (q, d) in enumerate(l["hoi"])
                if tl.get(str(i + 1)) in ("co", "khong") and tl.get(str(i + 1)) != d]
        if lech:
            out[l["ma"]] = "LLM (gạch đầu dòng): " + "; ".join(lech)
    with _lock:
        _memo[key] = out
    return out


def _dong_shop(ctx) -> list[str]:
    """Gạch đầu dòng của rulebook (§6 riêng của shop đã lọc trong ctx.rules) + quy ước README của shop."""
    lines = _gach(getattr(ctx, "rules", "") or "")
    con = getattr(ctx, "con", None)
    if con is not None:
        try:
            lines += [b.strip() for b, in con.execute("SELECT body FROM _meta_conventions").fetchall() if b]
        except Exception:       # noqa: BLE001 - DB cũ không có bảng quy ước
            pass
    return lines


def _nguon(plan) -> set:
    src = set()

    def walk(p):
        if isinstance(p, dict):
            if isinstance(p.get("nguon"), str):
                src.add(p["nguon"])
            for v in p.values():
                walk(v)
        elif isinstance(p, list):
            for v in p:
                walk(v)
    walk(plan)
    return src


def cham(ctx, r: dict) -> dict:
    """Kết quả đã trả lời mà dùng nguồn / cột chịu luật bộ đề đã đổi nghĩa -> bỏ trống (loai 'luat_doi')."""
    if r.get("loai") != "tra_loi" or os.environ.get("DATAMATE_LUAT_GOC") == "0":   # công tắc tắt (để đo)
        return r
    doi = getattr(ctx, "_luat_doi", None)
    if doi is None:
        doi = dict(luat_doi(getattr(ctx, "rules", "") or ""))
        # gạch đầu dòng §6 / README: tắt mặc định (báo nhầm nhiều, vd train 10/30 shop: README mô tả cách
        # GHI sổ "đơn trả ghi ở sổ TraHang" bị đọc thành luật tính); bật DATAMATE_LUAT_DONG=1
        if os.environ.get("DATAMATE_LUAT_DONG") == "1":
            for ma, why in luat_doi_dong(_dong_shop(ctx)).items():
                doi.setdefault(ma, why)
        try:
            ctx._luat_doi = doi
        except AttributeError:
            pass
        if doi:
            print(f"luật bộ đề khác luật code đang tính: {doi}", file=sys.stderr)
    if not doi:
        return r
    plan = r.get("plan")
    if isinstance(plan, str):                       # SQL: nguồn là các view v_<nguồn>
        src, text = set(re.findall(r"\bv_([a-z_]+)", plan)), plan
        moi = "hop_le" not in plan and "'huy'" in plan
    else:
        src, text = _nguon(plan), json.dumps(plan, ensure_ascii=False)
        moi = '"moi_trang_thai": true' in text
    for l in LUAT:
        if l["ma"] not in doi or not src & l["nguon"]:
            continue
        if l.get("ti_le") and not moi:
            continue
        if l.get("cot") and not any(re.search(rf"\b{c}\b", text) for c in l["cot"]):
            continue
        if l.get("moi") and re.search(l["moi"], text):      # kế hoạch đã viết theo luật mới (vd tự trừ giảm đơn): giữ
            continue
        return {**r, "loai": "luat_doi", "notes": (r.get("notes") or []) + [("luat_doi", doi[l["ma"]])]}
    return r


_DOMAIN_KW = {
    "dong_ban": r"\b(doanh thu|dthu|tien hang|tien ban|ban duoc|lai|don|khach|san pham|mat hang|hang)\b",
    "don": r"\b(doanh thu|dthu|so don|don|huy|ti le huy)\b",
    "cong_no": r"\b(no|cong no|con no|ghi no|tra no|thu no)\b",
    "dong_tien_no": r"\b(no|cong no|tra no|thu no|no them)\b",
    "phieu_nhap": r"\b(nhap|phieu nhap|tien nhap|nha cung cap)\b",
}


def luat_changed_for_q(ctx, q: dict, near_lines: list[str] | None = None) -> bool:
    """True nếu bộ đề có luật mặc định bị đổi nghĩa và câu hỏi (hoặc dòng luật gần câu) chạm tới luật đó."""
    if os.environ.get("DATAMATE_LUAT_GOC") == "0":
        return False
    doi = getattr(ctx, "_luat_doi", None)
    if doi is None:
        doi = dict(luat_doi(getattr(ctx, "rules", "") or ""))
        try:
            ctx._luat_doi = doi
        except AttributeError:
            pass
    if not doi:
        return False
    qf = fold((q or {}).get("question") or "")
    near_titles = []
    for line in near_lines or []:
        if line.startswith("|"):
            near_titles.append(_norm(line.strip("|").split("|")[0]))
    for l in LUAT:
        ma = l["ma"]
        if ma not in doi:
            continue
        if any(re.search(l["ten"], t) for t in near_titles):
            return True
        kw = TU_KHOA.get(ma)
        if kw and re.search(kw, qf):
            return True
        if l.get("cot"):
            if any(c.replace("_", " ") in qf for c in l["cot"]):
                return True
        elif any(re.search(_DOMAIN_KW[s], qf) for s in l["nguon"] if s in _DOMAIN_KW):
            return True
    return False
