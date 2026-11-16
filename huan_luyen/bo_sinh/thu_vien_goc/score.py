"""Chấm submission theo rulebook §9: đúng +1, sai -1, bỏ trống 0.
Dùng: python score.py <submission.jsonl> [answers.jsonl]"""
import sys, json, re, os, unicodedata, collections

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(os.path.dirname(HERE), 'private_zalo_ai_hard')

def norm_s(s):
    s = unicodedata.normalize('NFC', str(s)).casefold()
    return re.sub(r'[\s\W_]+', '', s)

def eq_num(a, b):
    return isinstance(a, (int, float)) and not isinstance(a, bool) and abs(float(a) - float(b)) < 1e-6

def eq_atom(g, v, alias=()):
    if isinstance(v, bool): return g is v
    if isinstance(v, (int, float)): return eq_num(g, v)
    if not isinstance(g, str): return False
    return norm_s(g) in {norm_s(v)} | {norm_s(a) for a in alias}

def correct(sub, ans):
    t = ans['type']
    if sub.get('type') != t: return False
    if t == 'unanswerable': return True
    g, v, al = sub.get('answer'), ans['answer'], ans.get('alias') or []
    if t in ('number', 'percent'): return eq_num(g, v)
    if t in ('date', 'boolean'): return g == v
    if t == 'string': return eq_atom(g, v, al)
    if t == 'list':
        if not isinstance(g, list) or len(g) != len(v): return False
        return all(eq_atom(a, b, al[i] if i < len(al) else ()) for i, (a, b) in enumerate(zip(g, v)))
    if t == 'table':
        if not isinstance(g, dict) or not isinstance(g.get('rows'), list): return False
        want = {norm_s(r[0]): r[1:] for r in v['rows']}
        got = {}
        for r in g['rows']:
            if not isinstance(r, list) or not r: return False
            got[norm_s(r[0])] = r[1:]
        if set(got) != set(want): return False
        return all(len(got[k]) == len(want[k]) and all(eq_atom(a, b) for a, b in zip(got[k], want[k])) for k in want)
    return False

def main():
    sp = sys.argv[1]; ap = sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, 'answers.jsonl')
    A = {json.loads(l)['id']: json.loads(l) for l in open(ap, encoding='utf8')}
    Q = {json.loads(l)['id']: json.loads(l) for l in open(os.path.join(ROOT, 'questions.jsonl'), encoding='utf8')}
    dbg = {}
    p = os.path.join(HERE, 'answers_debug.jsonl')
    if os.path.exists(p): dbg = {json.loads(l)['id']: json.loads(l) for l in open(p, encoding='utf8')}
    S = {}
    for l in open(sp, encoding='utf8'):
        l = l.strip()
        if not l: continue
        try: r = json.loads(l)
        except Exception: continue
        if r.get('id') in A: S[r['id']] = r
    c = w = ab = 0
    by_b = collections.defaultdict(lambda: [0, 0, 0]); by_t = collections.defaultdict(lambda: [0, 0, 0]); wrong = []
    for k, a in A.items():
        s = S.get(k); b = Q[k]['business_id']
        if s is None or s.get('type') == 'abstain': ab += 1; i = 2
        elif correct(s, a): c += 1; i = 0
        else: w += 1; i = 1; wrong.append((k, b, s, a))
        by_b[b][i] += 1; by_t[a['type']][i] += 1
    n = len(A)
    print('Điểm: %.4f   (đúng %d, sai %d, bỏ trống %d / %d câu)' % ((c - w) / n, c, w, ab, n))
    print('\nTheo shop (đúng/sai/bỏ):')
    for b in sorted(by_b): print('  %s %-30s %s' % (b, dbg.get(next(k for k in A if Q[k]['business_id'] == b), {}).get('business_id', ''), by_b[b]))
    print('\nTheo kiểu đáp án (đúng/sai/bỏ):')
    for t in sorted(by_t): print('  %-13s %s' % (t, by_t[t]))
    out = os.path.splitext(sp)[0] + '_wrong.jsonl'
    with open(out, 'w', encoding='utf8') as f:
        for k, b, s, a in wrong:
            f.write(json.dumps(dict(id=k, business_id=b, question=Q[k]['question'], as_of=Q[k]['as_of_date'], raw=dbg.get(k, {}).get('_raw'),
                                    submitted=s, expected={'type': a['type'], 'answer': a['answer']}), ensure_ascii=False) + '\n')
    print('\nChi tiết câu sai:', out)

if __name__ == '__main__':
    main()
