"""Kiểm lại câu chỉ một đường trả lời (đường kia bí): LLM đọc câu hỏi, luật liên quan, cách tính và kết quả rồi nói kết quả
có trả lời đúng câu hỏi không. Ở shop ngành lạ câu một đường chỉ đúng khoảng một nửa (hard thiết kế: chỉ JSON 42%, chỉ SQL
52%; gen_hl 50% / 57%; train 100%), nên câu bị chê thì bỏ trống. Một lần hỏi, nhiệt độ 0: chạy lại ra cùng kết quả.
"""
from __future__ import annotations

import datetime as dt
import json

from datamate.loader import llm
from datamate.query.compose import near_rules, readme_block

SYSTEM = (
    "Bạn kiểm bài cho một trợ lý trả lời câu hỏi kinh doanh trên sổ sách của một shop. Bạn nhận câu hỏi, các luật tính liên "
    "quan, cách tính trợ lý đã dùng (kế hoạch JSON hoặc SQL) và kết quả. Xét xem cách tính có đo ĐÚNG đại lượng câu hỏi hỏi "
    "không: đúng đối tượng (đơn / dòng / khách / mặt hàng / tiền / số lượng), đúng kỳ, đúng bộ lọc, đúng luật, đúng dạng "
    "đáp án (số, phần trăm, tên, ngày, danh sách theo thứ tự hỏi, bảng). Không tính lại con số. Trả về đúng một JSON: "
    '{"ly_do": "<một câu>", "dung": true|false}. Chỉ "dung": false khi thấy rõ một chỗ sai.'
)


def _value_text(rec: dict) -> str:
    return json.dumps({k: rec[k] for k in ("type", "answer") if k in rec}, ensure_ascii=False, default=str)[:600]


def prompt(ctx, q: dict, r: dict, rec: dict) -> str:
    rules = near_rules(ctx.rules, q["question"])
    method = r.get("plan")
    method = method if isinstance(method, str) else json.dumps(method, ensure_ascii=False, default=str)
    from datamate.query.sql_tier import periods
    today = dt.date.fromisoformat(q["as_of_date"])
    return (readme_block(ctx.con, limit=900)
            + (("LUẬT LIÊN QUAN:\n" + "\n".join(f"- {x}" for x in rules) + "\n\n") if rules else "")
            + f"HÔM NAY: {today}\nCÁC KỲ (code tính sẵn):\n{periods(today, q['question'])}\n\n"
            + f"CÂU HỎI: {q['question']}\n\n"
            + f"CÁCH TÍNH ({'SQL' if r.get('tang') == 'sql' else 'kế hoạch JSON'}):\n{str(method)[:2500]}\n\n"
            + f"KẾT QUẢ: {_value_text(rec)}\n\nTrả về JSON:")


def check(ctx, q: dict, r: dict, rec: dict) -> bool | None:
    """True: nhận; False: LLM chỉ ra chỗ sai; None: không đọc được câu trả lời (coi như nhận, không chặn bừa)."""
    text = llm.chat(SYSTEM, prompt(ctx, q, r, rec), max_tokens=200, timeout=180, temperature=0)
    start = text.find("{")
    if start < 0:
        return None
    try:
        out, _ = json.JSONDecoder().raw_decode(text, start)
    except json.JSONDecodeError:
        return None
    v = out.get("dung") if isinstance(out, dict) else None
    return v if isinstance(v, bool) else None
