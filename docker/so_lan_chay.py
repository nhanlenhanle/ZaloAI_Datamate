"""So các lần chạy image trên cùng bộ đề (thể lệ: điểm hai lần chạy lệch tối đa 0.03).

    python3 docker/so_lan_chay.py lan_1/submission.jsonl lan_2/submission.jsonl [...]
Không cần đáp án: đếm câu đổi kết quả so với lần đầu và chặn trên độ lệch điểm (đổi đáp án tính 2, thêm / bớt bỏ trống tính 1).
"""
import json
import sys


def norm(v):
    if isinstance(v, float):
        return round(v, 4)
    if isinstance(v, list):
        return [norm(x) for x in v]
    if isinstance(v, dict):
        return {k: norm(x) for k, x in sorted(v.items())}
    return v


def load(path):
    out = {}
    for line in open(path, encoding="utf-8"):
        if line.strip():
            r = json.loads(line)
            out[r["id"]] = (r.get("type"), json.dumps(norm(r.get("answer")), ensure_ascii=False, sort_keys=True))
    return out


def main(paths):
    base = load(paths[0])
    n = len(base)
    answered = sum(t != "abstain" for t, _ in base.values())
    print(f"{paths[0]}: {n} câu, trả lời {answered}")
    for p in paths[1:]:
        other = load(p)
        changed = to_blank = from_blank = 0
        for i, (t, a) in base.items():
            t2, a2 = other.get(i, ("abstain", "null"))
            if (t, a) == (t2, a2):
                continue
            if t2 == "abstain":
                to_blank += 1
            elif t == "abstain":
                from_blank += 1
            else:
                changed += 1
        bound = (2 * changed + to_blank + from_blank) / max(n, 1)
        print(f"{p}: đổi đáp án {changed}, thành bỏ trống {to_blank}, thôi bỏ trống {from_blank}, "
              f"lệch điểm tối đa {bound:.3f}")


if __name__ == "__main__":
    main(sys.argv[1:])
