"""Tính đáp án từ dữ liệu sạch, đúng theo rulebook.md."""
import datetime as D, collections
from core import *

class Unans(Exception): pass

VALID = ('done', 'ship')

def clamp(S, t, p):
    a, b = p
    if a > t or b < S['start'] or a > S['end']: raise Unans()
    return a, min(b, t)

def orders_in(S, t, p, statuses=VALID, **f):
    a, b = clamp(S, t, p)
    out = []
    for o in S['orders']:
        if not (a <= o['date'] <= b) or o['status'] not in statuses: continue
        if 'chan' in f and o['chan'] != f['chan']: continue
        if 'pay' in f and o['pay'] != f['pay']: continue
        if 'staff' in f and o['staff'] != f['staff']: continue
        if 'cgroup' in f:
            c = S['cmap'].get(o['cust'])
            if not c or c['group'] != f['cgroup']: continue
        if 'shift' in f:
            h = o['t'][0]
            if f['shift'] == 's' and not (6 <= h <= 13): continue
            if f['shift'] == 'c' and not (14 <= h <= 21): continue
        if 'cust' in f and o['cust'] != f['cust']: continue
        out.append(o)
    return out

def lines_in(S, t, p, item=None, group=None, owner=None, rx=None, ing=None, sales_only=False, **f):
    for o in orders_in(S, t, p, **f):
        for l in o['lines']:
            it = S['imap'][l['code']]
            if item and l['code'] != item: continue
            if group and it['group'] != group: continue
            if owner and it.get('owner') != owner: continue
            if rx is not None and bool(it.get('rx')) != rx: continue
            if ing and it.get('ing') != ing: continue
            if sales_only and l['kind'] == 'exchange': continue
            yield o, l

def rev(S, t, p, **f): return money(sum(l['amt'] for o, l in lines_in(S, t, p, **f)))
def nord(S, t, p, **f): return len(orders_in(S, t, p, **f))
def nord_item(S, t, p, **f): return len({o['id'] for o, l in lines_in(S, t, p, sales_only=True, **f)})
def aov(S, t, p, **f):
    os_ = orders_in(S, t, p, **f)
    if not os_: raise Unans()
    return money(sum(sum(l['amt'] for l in o['lines']) for o in os_) / len(os_))
def cancels(S, t, p): return len(orders_in(S, t, p, statuses=('cancel',)))
def crate(S, t, p):
    allo = orders_in(S, t, p, statuses=('done', 'ship', 'cancel', 'return'))
    if not allo: raise Unans()
    return r2(sum(o['status'] == 'cancel' for o in allo) / len(allo) * 100)
def pct(a, b):
    if b == 0: raise Unans()
    return r2((a - b) / b * 100)
def qty(S, t, p, **f): return num_out(sum(l['qb'] for o, l in lines_in(S, t, p, sales_only=True, **f)))
def units_of(S, t, p, base, **f):
    return num_out(sum(l['qb'] for o, l in lines_in(S, t, p, sales_only=True, **f) if S['imap'][l['code']]['base'] == base))

def rank_items(S, vals):
    return sorted(vals, key=lambda c: (-vals[c], c))

def item_vals(S, t, p, by='qty', **f):
    v = collections.defaultdict(float)
    if by == 'ord':
        seen = collections.defaultdict(set)
        for o, l in lines_in(S, t, p, sales_only=True, **f): seen[l['code']].add(o['id'])
        return {c: len(s) for c, s in seen.items()}
    for o, l in lines_in(S, t, p, sales_only=True, **f):
        if by == 'qty': v[l['code']] += l['qb']
        elif by == 'rev': v[l['code']] += l['amt']
        elif by == 'margin': v[l['code']] += l['amt'] - l['qty'] * l['cost']
    return dict(v)

def top_items(S, t, p, k=None, by='qty', **f):
    v = item_vals(S, t, p, by, **f)
    if not v: raise Unans()
    r = rank_items(S, v)
    tie = (k is None and len(r) > 1 and v[r[0]] == v[r[1]]) or (k and len(r) > k and v[r[k - 1]] == v[r[k]])
    return (r[0] if k is None else r[:k]), tie

def items_in_n(S, t, p, n):
    v = item_vals(S, t, p, 'ord'); return sum(1 for x in v.values() if x >= n)

def cust_orders(S, t, p):
    c = collections.Counter(o['cust'] for o in orders_in(S, t, p) if o['cust'])
    if not c: raise Unans()
    return c
def n_cust_ge(S, t, p, n): return sum(1 for v in cust_orders(S, t, p).values() if v >= n)
def pct_cust_ge(S, t, p, n):
    c = cust_orders(S, t, p); return r2(sum(1 for v in c.values() if v >= n) / len(c) * 100)

def top_cust(S, t, p, by='ord', k=None):
    os_ = [o for o in orders_in(S, t, p) if o['cust']]
    v = collections.defaultdict(float)
    if by == 'ord':
        for o in os_: v[o['cust']] += 1
    elif by == 'rev':
        for o in os_: v[o['cust']] += sum(l['amt'] for l in o['lines'])
    elif by == 'days':
        s = collections.defaultdict(set)
        for o in os_: s[o['cust']].add(o['date'])
        v = {c: len(x) for c, x in s.items()}
    elif by == 'sop':
        n = collections.Counter(o['cust'] for o in os_); tot = collections.defaultdict(float)
        for o in os_: tot[o['cust']] += sum(l['amt'] for l in o['lines'])
        v = {c: money(tot[c] / n[c]) for c in n if n[c] >= 3}
    elif by == 'cancel':
        for o in orders_in(S, t, p, statuses=('cancel',)):
            if o['cust']: v[o['cust']] += 1
    if not v: raise Unans()
    key = (lambda c: (-v[c], c)) if S['cust_code'] else (lambda c: (-v[c], name_key(S['cmap'][c]['name'])))
    r = sorted(v, key=key)
    kk = k or 1
    tie = len(r) > kk and v[r[kk - 1]] == v[r[kk]]
    return (r[0] if k is None else r[:k]), tie

def daily(S, t, p, **f):
    v = collections.defaultdict(float)
    for o, l in lines_in(S, t, p, **f): v[o['date']] += l['amt']
    return v
def best_day(S, t, p):
    v = daily(S, t, p); return min(v, key=lambda d: (-v[d], d))
def busy_day(S, t, p):
    c = collections.Counter(o['date'] for o in orders_in(S, t, p)); return min(c, key=lambda d: (-c[d], d))
def days_ge(S, t, p, x): return sum(1 for v in daily(S, t, p).values() if v >= x)
def ord_ge(S, t, p, x): return sum(1 for o in orders_in(S, t, p) if sum(l['amt'] for l in o['lines']) >= x)

def peak_hour(S, t, p):
    c = collections.Counter(o['t'][0] for o in orders_in(S, t, p)); return min(c, key=lambda h: (-c[h], h))

# ----- công nợ
def debt_orders(S, X):
    out = []
    for o in S['orders']:
        if o['date'] > X or o['status'] == 'cancel': continue
        if not S.get('deposit') and o['pay'] != 'debt': continue
        paid = sum(a for d, a, k in o['payments'] if d <= X)
        rem = o['due'] - paid
        if rem > 0.5: out.append((o, rem))
    return out
def debt_total(S, X): return money(sum(r for o, r in debt_orders(S, X)))
def n_debtors(S, X): return len({o['cust'] for o, r in debt_orders(S, X) if o['cust']})
def top_debtors(S, X, k):
    v = collections.defaultdict(float)
    for o, r in debt_orders(S, X):
        if o['cust']: v[o['cust']] += r
    rr = sorted(v, key=lambda c: (-v[c], c))
    tie = len(rr) > k and v[rr[k - 1]] == v[rr[k]]
    return [[S['cmap'][c]['name'], money(v[c])] for c in rr[:k]], tie
def aged(S, X):
    b = [0, 0, 0]
    for o, r in debt_orders(S, X):
        a = (X - o['date']).days
        b[0 if a <= 7 else (1 if a <= 15 else 2)] += r
    return [money(x) for x in b]
def aged_over(S, X, n): return money(sum(r for o, r in debt_orders(S, X) if (X - o['date']).days > n))
def repay(S, t, p, cust=None):
    a, b = clamp(S, t, p); s = 0
    for o in S['orders']:
        if o['status'] == 'cancel': continue
        if not S.get('deposit') and o['pay'] != 'debt': continue
        if cust and o['cust'] != cust: continue
        for d, x, k in o['payments']:
            if a <= d <= b and d > o['date']: s += x
    return money(s)
def new_debt(S, t, p, cust=None):
    a, b = clamp(S, t, p); s = 0
    for o in S['orders']:
        if o['status'] == 'cancel' or o['pay'] != 'debt' or not (a <= o['date'] <= b): continue
        if cust and o['cust'] != cust: continue
        s += o['due'] - sum(x for d, x, k in o['payments'] if d == o['date'])
    return money(s)

# ----- nhập hàng, kho
def purch(S, t, p):
    a, b = clamp(S, t, p)
    return money(sum(sum(l['amt'] for l in x['lines']) for x in S['purchases'] if not x['cancel'] and a <= x['date'] <= b))
def top_sup(S, t, p, by='amt'):
    a, b = clamp(S, t, p); v = collections.defaultdict(float)
    for x in S['purchases']:
        if x['cancel'] or not (a <= x['date'] <= b): continue
        v[x['sup']] += sum(l['amt'] for l in x['lines']) if by == 'amt' else 1
    if not v: raise Unans()
    r = sorted(v, key=lambda s: (-v[s], s)); return r[0], len(r) > 1 and v[r[0]] == v[r[1]]
def stock_at(S, X, code):
    s = 0.0
    for x in S['purchases']:
        if not x['cancel'] and x['date'] <= X:
            s += sum(l['qb'] for l in x['lines'] if l['code'] == code)
    for o in S['orders']:
        if o['status'] == 'cancel' or o['date'] > X: continue
        s -= sum(l['qb'] for l in o['lines'] if l['code'] == code)
        if o['status'] == 'return' and o['ret_date'] <= X:
            s += sum(q for i, q in o['ret_lines'] if o['lines'][i]['code'] == code)
    return s
def stock_value(S, X):
    v = 0
    for it in S['items']:
        if it.get('made'): continue
        q = stock_at(S, X, it['code'])
        if q > 0: v += q * it['cost']
    return money(v)
def out_of_stock(S, X):
    return sum(1 for it in S['items'] if not it.get('made') and abs(stock_at(S, X, it['code'])) < 1e-9)

def hike(S, t, code, d0, n):
    a1, b1 = d0, d0 + D.timedelta(days=n - 1); a0, b0 = d0 - D.timedelta(days=n), d0 - D.timedelta(days=1)
    if a0 < S['start'] or b1 > min(t, S['end']): raise Unans()
    q1 = sum(l['qb'] for o, l in lines_in(S, t, (a1, b1), item=code, sales_only=True))
    q0 = sum(l['qb'] for o, l in lines_in(S, t, (a0, b0), item=code, sales_only=True))
    return pct(q1, q0)

def lot_remaining(S, X):
    rem = {lt['lot']: (lt['qin'] if lt['date'] <= X else 0.0) for lt in S['lots']}
    for o in S['orders']:
        if o['status'] == 'cancel' or o['date'] > X: continue
        for l in o['lines']:
            for a in l.get('alloc', []):
                rem[a[0]] -= a[1]
                if o['status'] == 'return' and o['ret_date'] <= X and len(a) > 2: rem[a[0]] += a[2]
    return rem
def expiring(S, t, n):
    rem = lot_remaining(S, t); end = t + D.timedelta(days=n)
    return [lt for lt in S['lots'] if rem[lt['lot']] > 1e-9 and t <= lt['exp'] <= end], rem
