"""Sinh toàn bộ bộ private_zalo_ai_hard. Chạy: python main.py"""
import os, sys, json, shutil, random, hashlib, pickle, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core import *
import sim, shops, writers, qgen

def build():
    R = random.Random(SEED)
    if os.path.exists(OUT): shutil.rmtree(OUT)
    os.makedirs(os.path.join(OUT, 'data'))
    all_s = []
    for S in shops.shops():
        r = random.Random('%s-%s' % (SEED, S['id']))
        if S['kind'] == 'retail': sim.sim_retail(r, S)
        elif S['kind'] == 'net': sim.sim_net(r, S)
        elif S['kind'] == 'laundry': sim.sim_laundry(r, S)
        else: sim.sim_charge(r, S)
        S['imap'] = {it['code']: it for it in S.get('items', [])}
        S['cmap'] = {c['id']: c for c in S.get('custs', []) if 'id' in c}
        d = os.path.join(OUT, 'data', S['id']); os.makedirs(d)
        writers.WRITERS[S['writer']](random.Random('%s-w-%s' % (SEED, S['id'])), S, d)
        all_s.append(S)
        print(S['id'], S['name'], len(S.get('orders', S.get('sessions', S.get('tickets', [])))))
    qs, ans = [], []
    for S in all_s:
        r = random.Random('%s-q-%s' % (SEED, S['id']))
        n = 52 if S['kind'] == 'retail' else 40
        for x in qgen.gen_questions(r, S, n):
            h = hashlib.md5(('%s|%s|%s' % (S['id'], x['raw'], x['t'])).encode()).hexdigest()[:12]
            qs.append(dict(id='hq_' + h, business_id=S['id'], question=x['q'], as_of_date=x['t'].isoformat()))
            a = dict(id='hq_' + h, type=x['type'], answer=x['answer'], alias=x['alias'], _raw=x['raw'])
            ans.append(a)
    order = list(range(len(qs))); R.shuffle(order)
    qs = [qs[i] for i in order]; ans = [ans[i] for i in order]
    assert len({q['id'] for q in qs}) == len(qs)
    with open(os.path.join(OUT, 'questions.jsonl'), 'w', encoding='utf-8', newline='\n') as f:
        for q in qs: f.write(json.dumps(q, ensure_ascii=False) + '\n')
    with open(os.path.join(OUT, 'answers.jsonl'), 'w', encoding='utf-8', newline='\n') as f:
        for a in ans: f.write(json.dumps({k: v for k, v in a.items() if k != '_raw'}, ensure_ascii=False) + '\n')
    with open(os.path.join(HERE, 'answers_debug.jsonl'), 'w', encoding='utf-8', newline='\n') as f:
        for q, a in zip(qs, ans): f.write(json.dumps(dict(q, **a), ensure_ascii=False, default=str) + '\n')
    shutil.copy(os.path.join(HERE, 'rulebook.md'), os.path.join(OUT, 'rulebook.md'))
    with open(os.path.join(OUT, 'calendar.csv'), 'w', encoding='utf-8', newline='') as f:
        w = csv.writer(f); cols = list(CAL_ROWS[0].keys()); w.writerow(cols)
        for r in CAL_ROWS:
            d = D.date.fromisoformat(r['date']); w.writerow([CAL[d][c] for c in cols])
    tc = collections.Counter(a['type'] for a in ans)
    open(os.path.join(OUT, 'README.md'), 'w', encoding='utf-8').write("""# private_zalo_ai_hard

Bộ test tự sinh để thử mô hình theo kiểu DataMate, cố ý khó và lạ hơn bộ train: 10 cơ sở hư cấu thuộc ngành ít gặp, mỗi cơ sở một kiểu sổ sách (Excel nhiều sheet, CSV tách bảng, SQLite, sổ ghi tay), dữ liệu bẩn (mã dính khoảng trắng, tiền `1,2tr` / `850k`, ngày lẫn kiểu, dòng tổng, dòng trùng, tên viết tắt, trạng thái nằm trong ghi chú) và luật ngành mới (đổi cá bảo hành, tiền cọc, sách ký gửi, nạp tài khoản phòng máy, giặt sấy theo SĐT, trạm sạc theo khung giờ, lễ âm lịch).

- `questions.jsonl`: %d câu (`id`, `business_id`, `question`, `as_of_date`).
- `answers.jsonl`: đáp án (`id`, `type`, `answer`, `alias`). Phân bố: %s.
- `rulebook.md`: luật tính đáp án. `calendar.csv`: lịch dương–âm 2024–2027, cột `holiday` có thêm các ngày lễ dùng trong câu hỏi.
- `data/biz_2xx/`: dữ liệu và README từng cơ sở.

Đáp án được tính từ dữ liệu gốc trước khi làm bẩn, theo đúng rulebook. Mọi dữ liệu là hư cấu.
""" % (len(qs), ', '.join('%s %d' % kv for kv in tc.most_common())))
    pickle.dump(all_s, open(os.path.join(HERE, '_truth.pkl'), 'wb'))
    print(len(qs), tc)

if __name__ == '__main__':
    build()
