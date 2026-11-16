"""Mô phỏng dữ liệu SẠCH (sự thật gốc). Đáp án chỉ tính từ đây, không đọc lại file bẩn."""
import random, datetime as D, math, collections
from core import *

def poisson(R, lam):
    if lam <= 0: return 0
    L = math.exp(-min(lam, 600)); k = 0; p = 1.0
    if lam > 60:
        return max(0, int(round(R.gauss(lam, math.sqrt(lam)))))
    while True:
        p *= R.random()
        if p < L: return k
        k += 1

def r100(x): return int(round(x / 100.0)) * 100

def wchoice(R, items, weights):
    return R.choices(items, weights=weights, k=1)[0]

# ============================================================ cửa hàng bán lẻ chung
def mk_items(spec, prefix):
    """spec: list of (name, group, base, {unit:factor}, price_base, extra dict)"""
    out = []
    for i, s in enumerate(spec, 1):
        name, group, base, units, price = s[:5]
        ex = s[5] if len(s) > 5 else {}
        it = dict(code='%s%03d' % (prefix, i), name=name, group=group, base=base, units=dict(units), price=price,
                  cost=ex.get('cost', round(price * ex.get('cr', 0.62))), **{k: v for k, v in ex.items() if k not in ('cost', 'cr')})
        it['units'].setdefault(base, 1)
        out.append(it)
    return out

def add_price_history(R, S):
    """mỗi mặt hàng 0-2 lần tăng giá; giá theo đơn vị cơ bản"""
    S['ph'] = {}
    span = (S['end'] - S['start']).days
    for it in S['items']:
        h = [(S['start'], it['price'])]
        p = it['price']
        for _ in range(R.choice([0, 1, 1, 2])):
            d = S['start'] + D.timedelta(days=R.randint(40, span - 40))
            if any(abs((d - x[0]).days) < 45 for x in h): continue
            p = r100(p * R.uniform(1.04, 1.15)) if p >= 2000 else p + R.choice([100, 200, 500])
            h.append((d, p))
        h.sort()
        # đảm bảo giá tăng dần theo thời gian
        fixed = [h[0]]
        for d, v in h[1:]:
            if v > fixed[-1][1]: fixed.append((d, v))
        S['ph'][it['code']] = fixed

def price_at(S, code, d):
    p = None
    for x, v in S['ph'][code]:
        if x <= d: p = v
    return p

def unit_price(S, it, unit, d):
    f = it['units'][unit]
    p = price_at(S, it['code'], d) * f
    if f > 1: p = r100(p * 0.96)
    return p

def gen_customers(R, S, n, used):
    names = make_names(R, n, used)
    cs = []
    for i, nm in enumerate(names, 1):
        cs.append(dict(id='KH%04d' % i, name=nm, phone=phone(R), group=R.choices(['lẻ', 'thân thiết', 'sỉ'], [5, 3, 1])[0],
                       w=R.paretovariate(1.3), reg=S['start'] + D.timedelta(days=R.randint(-200, (S['end'] - S['start']).days - 10))))
    if S.get('accent_trap') and len(cs) > 4:
        # bẫy: hai khách chỉ khác dấu (khác chữ) là hai người khác nhau
        base = cs[1]['name']; parts = base.split(' ')
        alt = {'Hà': 'Hạ', 'Thu': 'Thư', 'Lan': 'Lân', 'Mai': 'Mại', 'Linh': 'Lình', 'Nam': 'Nâm'}
        parts[-1] = alt.get(parts[-1], parts[-1] + 'h')
        cs[3]['name'] = ' '.join(parts)
        if S.get('digit_trap'): cs[5]['name'] = cs[2]['name'] + ' 2'
    return cs

def sim_retail(R, S):
    items = S['items']; byc = {it['code']: it for it in items}
    add_price_history(R, S)
    used = set(); S['custs'] = gen_customers(R, S, S['ncust'], used)
    cw = [c['w'] for c in S['custs']]
    pop = [it.get('pop', 1.0) * R.uniform(0.4, 2.5) for it in items]
    sale_items = [it for it in items if not it.get('topping')]
    sale_pop = [p for it, p in zip(items, pop) if not it.get('topping')]
    tops = [it for it in items if it.get('topping')]
    orders = []
    oid = 0
    days = list(daterange(S['start'], S['end']))
    tet26, tet25 = tet(2026), tet(2025)
    for d in days:
        lam = S['lam'] * S.get('wk', [1, 1, 1, 1, 1.1, 1.3, 1.3])[d.weekday()]
        lam *= 1 + 0.25 * math.sin((d.timetuple().tm_yday / 365.0) * 2 * math.pi + S.get('phase', 0))
        lam *= 1 + S.get('growth', 0.1) * (d - S['start']).days / 365.0
        for a, b in (tet25, tet26):
            if a <= d <= b: lam *= S.get('tet_mult', 1.4)
        if S.get('holiday_boost'):
            for nm, mult in S['holiday_boost']:
                for hd in holiday_dates(nm):
                    if 0 <= (hd - d).days <= 2: lam *= mult
            ld = int(CAL[d]['lunar_day'])
            if ld in (1, 15): lam *= S.get('lunar_mult', 2.0)
        n = poisson(R, lam)
        times = sorted((wchoice(R, [h for h, _ in S['hours']], [w for _, w in S['hours']]), R.randint(0, 59), R.randint(0, 59)) for _ in range(n))
        for (h, mi, se) in times:
            oid += 1
            c = None if R.random() < S['p_walkin'] else wchoice(R, S['custs'], cw)
            o = dict(id=S['oid_fmt'] % oid, date=d, t=(h, mi, se), cust=c['id'] if c else None, lines=[], odisc=0, ship=0,
                     chan=None, pay=None, staff=None, status='done', ret_date=None, payments=[], deposit=0, note=None)
            if S.get('chans'):
                o['chan'] = wchoice(R, [x for x, _ in S['chans']], [w for _, w in S['chans']])
            if S.get('staff'): o['staff'] = R.choice(S['staff'])
            k = wchoice(R, [1, 2, 3, 4, 5], S.get('kdist', [40, 30, 15, 10, 5]))
            chosen = R.choices(sale_items, weights=sale_pop, k=k)
            seen = set()
            for it in chosen:
                if it['code'] in seen: continue
                seen.add(it['code'])
                units = list(it['units'])
                if len(units) > 1 and (R.random() < S.get('p_big', 0.15) or (c and c['group'] == 'sỉ' and R.random() < 0.6)):
                    u = R.choice([x for x in units if it['units'][x] > 1])
                else: u = it['base']
                q = R.choice(S.get('qdist', [1, 1, 1, 2, 2, 3])) if it['units'][u] == 1 else R.choice([1, 1, 2])
                if it.get('qrange') and u == it['base']: q = R.randint(*it['qrange'])
                pr = unit_price(S, it, u, d)
                disc = r100(pr * q * 0.05) if R.random() < S.get('p_ldisc', 0.06) else 0
                ln = dict(code=it['code'], unit=u, f=it['units'][u], qty=q, qb=q * it['units'][u], price=pr, disc=disc,
                          amt=money(pr * q - disc), kind='sale', cost=round(it['cost'] * it['units'][u] * R.uniform(0.97, 1.03)), parent=None)
                o['lines'].append(ln)
                if tops and it.get('drink') and R.random() < 0.45:
                    for t_ in R.sample(tops, R.choice([1, 1, 2])):
                        if t_['code'] in seen: continue   # một topping chỉ một lần mỗi đơn: tránh hai dòng giống hệt nhau
                        seen.add(t_['code'])
                        tq = R.choice([1, 1, 2]); tp = price_at(S, t_['code'], d)
                        o['lines'].append(dict(code=t_['code'], unit=t_['base'], f=1, qty=tq, qb=tq, price=tp, disc=0, amt=tp * tq,
                                               kind='topping', cost=t_['cost'], parent=len(o['lines']) - 1))
            if S.get('exchange') and c and R.random() < S['exchange']:
                it = R.choice([x for x in sale_items if x.get('live')])
                o['lines'].append(dict(code=it['code'], unit=it['base'], f=1, qty=1, qb=1, price=0, disc=0, amt=0, kind='exchange',
                                       cost=it['cost'], parent=None))
            sub = sum(l['amt'] for l in o['lines'])
            if sub == 0:
                o['lines'] = [l for l in o['lines'] if l['kind'] != 'exchange']
                oid -= 1; continue
            if S.get('odisc') and sub >= S['odisc'][0] and R.random() < 0.5: o['odisc'] = S['odisc'][1]
            if o['chan'] in S.get('delivery', ()): o['ship'] = R.choice([15000, 20000, 25000, 30000])
            # thanh toán
            if S.get('pays'):
                ps = [(p, w) for p, w in S['pays'] if not (p == 'debt' and c is None) and not (p == 'cod' and o['chan'] not in S.get('delivery', ()))]
                o['pay'] = wchoice(R, [p for p, _ in ps], [w for _, w in ps])
            # trạng thái
            x = R.random()
            if (S['end'] - d).days <= 3 and o['chan'] in S.get('delivery', ()) and R.random() < 0.5: o['status'] = 'ship'
            elif x < S.get('p_cancel', 0.02): o['status'] = 'cancel'
            elif x < S.get('p_cancel', 0.02) + S.get('p_return', 0.012): o['status'] = 'return'
            elif x < S.get('p_cancel', 0.02) + S.get('p_return', 0.012) + 0.003: o['status'] = 'ship'
            if o['status'] == 'return':
                o['ret_date'] = d + D.timedelta(days=R.randint(0, 9))
                sl = [l for l in o['lines'] if l['kind'] == 'sale']
                o['ret_lines'] = []
                for l in sl if R.random() < 0.5 else [R.choice(sl)]:
                    o['ret_lines'].append((o['lines'].index(l), l['qb'] if R.random() < 0.6 or l['qb'] < 2 else int(l['qb'] // 2)))
            due = sub - o['odisc'] + o['ship']
            o['due'] = due
            mk_payments(R, S, o)
            orders.append(o)
    S['orders'] = orders
    if S.get('stock'): sim_stock(R, S)
    return S

def mk_payments(R, S, o):
    d = o['date']; due = o['due']
    if o['status'] == 'cancel':
        if S.get('deposit'):
            o['deposit'] = r100(due * R.choice([0.3, 0.4, 0.5]))
            o['payments'] = [(d, o['deposit'], 'cọc')]
        return
    if S.get('deposit'):
        o['deposit'] = r100(due * R.choice([0.3, 0.4, 0.5])); o['payments'] = [(d, o['deposit'], 'cọc')]
        rest = due - o['deposit']
        pick = d + D.timedelta(days=R.randint(2, 12))
        if R.random() < 0.08: return
        if R.random() < 0.15:
            a = r100(rest * 0.5); o['payments'] += [(pick, a, 'trả'), (pick + D.timedelta(days=R.randint(3, 30)), rest - a, 'trả')]
        else: o['payments'].append((pick, rest, 'trả'))
        return
    if o['pay'] == 'debt':
        now = R.choice([0, 0, r100(due * 0.3), r100(due * 0.5)])
        if now: o['payments'].append((d, now, 'trả'))
        rest = due - now; t = d
        for i in range(R.choice([1, 1, 2, 3])):
            if rest <= 0 or R.random() < 0.12: break
            t = t + D.timedelta(days=R.randint(2, 25))
            a = rest if i == 2 or R.random() < 0.5 else r100(rest * R.uniform(0.3, 0.7))
            o['payments'].append((t, a, 'trả')); rest -= a
    elif o['pay'] == 'cod':
        o['payments'].append((d + D.timedelta(days=R.randint(1, 3)), due, 'cod'))
    else:
        o['payments'].append((d, due, o['pay'] or 'cash'))

def sim_stock(R, S):
    """phiếu nhập để tồn không âm cuối ngày; tuỳ chọn lô + hạn dùng (FEFO)"""
    items = [it for it in S['items'] if not it.get('made')]
    byc = {it['code']: it for it in items}
    out_by_day = collections.defaultdict(lambda: collections.defaultdict(float))
    ret_by_day = collections.defaultdict(lambda: collections.defaultdict(float))
    for o in S['orders']:
        if o['status'] == 'cancel': continue
        for l in o['lines']:
            if l['code'] in byc: out_by_day[o['date']][l['code']] += l['qb']
        if o['status'] == 'return':
            for i, q in o['ret_lines']:
                if o['lines'][i]['code'] in byc: ret_by_day[o['ret_date']][o['lines'][i]['code']] += q
    avg = collections.defaultdict(float)
    ndays = (S['end'] - S['start']).days + 1
    for d in out_by_day:
        for c, q in out_by_day[d].items(): avg[c] += q / ndays
    stock = collections.defaultdict(float)
    purchases = []; pid = 0
    sups = S['suppliers']
    def buy(d, need, first=False):
        nonlocal pid
        pid += 1
        lines = []
        for c, q in need.items():
            it = byc[c]
            big = [u for u, f in it['units'].items() if f > 1]
            u = R.choice(big) if big and R.random() < 0.7 else it['base']
            f = it['units'][u]; nq = max(1, math.ceil(q / f))
            if it['cost'] == 0: pr = 0
            else: pr = r100(it['cost'] * f * R.uniform(0.95, 1.05)) if it['cost'] * f >= 1000 else max(100, round(it['cost'] * f))
            ln = dict(code=c, unit=u, f=f, qty=nq, qb=nq * f, price=pr, amt=nq * pr)
            if S.get('lots'):
                ln['lot'] = 'LO%04d-%02d' % (pid, len(lines) + 1)
                ln['exp'] = d + D.timedelta(days=R.choice([60, 90, 150, 240, 365, 540, 730]) + R.randint(0, 40))
            lines.append(ln); stock[c] += nq * f
        purchases.append(dict(id='PN%05d' % pid, date=d, sup=R.choice(sups), lines=lines, cancel=False, first=first))
        return purchases[-1]
    lots = []  # dict(lot, code, exp, rem, cost_base, date)
    def add_lots(p):
        for ln in p['lines']:
            if 'lot' in ln:
                lots.append(dict(lot=ln['lot'], code=ln['code'], exp=ln['exp'], rem=ln['qb'], cost=ln['price'] / ln['f'], date=p['date'], qin=ln['qb']))
    p0 = buy(S['start'], {c: max(5, avg[c] * 20) for c in byc}, first=True); add_lots(p0)
    # theo dõi đơn theo ngày cho FEFO
    by_day_orders = collections.defaultdict(list)
    for o in S['orders']: by_day_orders[o['date']].append(o)
    by_day_ret = collections.defaultdict(list)
    for o in S['orders']:
        if o['status'] == 'return': by_day_ret[o['ret_date']].append(o)
    for d in daterange(S['start'], S['end'] + D.timedelta(days=12)):
        need = {}
        for c in byc:
            if d.weekday() == 0 and stock[c] < avg[c] * 9:
                need[c] = avg[c] * 14 - stock[c]
            if stock[c] - out_by_day[d][c] < 0:
                need[c] = max(need.get(c, 0), out_by_day[d][c] - stock[c] + avg[c] * 5)
        if need and d <= S['end']:
            add_lots(buy(d, need))
        for o in by_day_orders.get(d, []):
            if o['status'] == 'cancel': continue
            for l in o['lines']:
                if l['code'] not in byc: continue
                stock[l['code']] -= l['qb']
                if S.get('lots'):
                    q = l['qb']; l['alloc'] = []
                    for lt in sorted([x for x in lots if x['code'] == l['code'] and x['rem'] > 1e-9], key=lambda x: (x['exp'], x['lot'])):
                        a = min(q, lt['rem']); lt['rem'] -= a; l['alloc'].append([lt['lot'], a]); q -= a
                        if q <= 1e-9: break
                    assert q <= 1e-9, 'thiếu lô'
        for o in by_day_ret.get(d, []):
            for i, q in o['ret_lines']:
                l = o['lines'][i]
                if l['code'] not in byc: continue
                stock[l['code']] += q
                if S.get('lots'):
                    rem = q
                    for a in l['alloc']:
                        b = min(rem, a[1] - a[2] if len(a) > 2 else a[1])
                        if len(a) == 2: a.append(0)
                        a[2] += b; rem -= b
                        for lt in lots:
                            if lt['lot'] == a[0]: lt['rem'] += b
                        if rem <= 1e-9: break
        for c in byc: assert stock[c] >= -1e-9, ('tồn âm', S['id'], c, d)
    # vài phiếu nhập huỷ (không vào kho)
    for _ in range(R.randint(2, 5)):
        p = R.choice(purchases[1:])
        pid += 1
        purchases.append(dict(id='PN%05d' % pid, date=p['date'], sup=R.choice(sups),
                              lines=[dict(x, qty=x['qty'], amt=x['amt']) for x in p['lines'][:2]], cancel=True, first=False))
    for p in purchases:
        for ln in p['lines']:
            if p['cancel'] and 'lot' in ln: ln['lot'] = ln['lot'] + 'X'
    S['purchases'] = sorted(purchases, key=lambda p: (p['date'], p['id']))
    S['lots'] = lots

# ============================================================ quán net
def sim_net(R, S):
    S['machines'] = []
    for i in range(1, 31):
        z = 'thường' if i <= 18 else ('VIP' if i <= 26 else 'thi đấu')
        S['machines'].append(dict(id='M%02d' % i, zone=z, rate={'thường': 8000, 'VIP': 12000, 'thi đấu': 18000}[z]))
    S['rate_change'] = (D.date(2026, 3, 1), {'thường': 9000, 'VIP': 13000, 'thi đấu': 20000})
    used = set(); names = make_names(R, 140, used)
    S['members'] = [dict(id='HV%03d' % i, name=n, w=R.paretovariate(1.2), bal=0.0) for i, n in enumerate(names, 1)]
    S['menu'] = mk_items([('Mì ly trứng', 'đồ ăn', 'ly', {}, 25000), ('Cơm chiên dương châu', 'đồ ăn', 'đĩa', {}, 35000),
                          ('Xúc xích nướng', 'đồ ăn', 'cây', {}, 15000), ('Sting dâu', 'nước', 'chai', {}, 15000),
                          ('Redbull', 'nước', 'lon', {}, 20000), ('Trà đá', 'nước', 'ly', {}, 5000), ('Cà phê sữa đá', 'nước', 'ly', {}, 20000),
                          ('Bánh mì ốp la', 'đồ ăn', 'ổ', {}, 25000)], 'FD')
    sess, tops, food = [], [], []
    sid = tid = fid = 0
    mw = [m['w'] for m in S['members']]
    hours = [(h, w) for h, w in zip(range(24), [6, 4, 3, 2, 1, 1, 1, 1, 2, 3, 4, 5, 6, 6, 6, 7, 8, 9, 10, 12, 13, 13, 12, 9])]
    busy_until = {m['id']: D.datetime(2000, 1, 1) for m in S['machines']}
    for d in daterange(S['start'], S['end']):
        n = poisson(R, S['lam'] * (1.35 if d.weekday() >= 5 else 1))
        starts = sorted(D.datetime(d.year, d.month, d.day, wchoice(R, [h for h, _ in hours], [w for _, w in hours]), R.randint(0, 59)) for _ in range(n))
        for st in starts:
            free = [m for m in S['machines'] if busy_until[m['id']] <= st]
            if not free: continue
            zw = {'thường': 6, 'VIP': 3, 'thi đấu': 1.2}
            m = wchoice(R, free, [zw[x['zone']] for x in free])
            mins = R.choice([30, 45, 60, 60, 90, 120, 120, 150, 180, 240, 300, 360, 480]) + R.randint(-5, 25)
            en = st + D.timedelta(minutes=mins)
            busy_until[m['id']] = en
            rate = (S['rate_change'][1] if d >= S['rate_change'][0] else {'thường': 8000, 'VIP': 12000, 'thi đấu': 18000})[m['zone']]
            mem = wchoice(R, S['members'], mw) if R.random() < 0.65 else None
            amt = r100(mins * rate / 60.0)
            status = 'hoàn tiền' if R.random() < 0.02 else 'xong'
            pay = 'tài khoản' if mem else R.choice(['tiền mặt', 'chuyển khoản'])
            sid += 1
            if mem and status == 'xong':
                while mem['bal'] < amt:
                    a = R.choice([50000, 100000, 100000, 200000, 300000, 500000]); bonus = int(a * 0.1) if a >= 200000 else 0
                    tid += 1; t0 = st - D.timedelta(minutes=R.randint(1, 20))
                    tops.append(dict(id='NT%06d' % tid, mem=mem['id'], ts=t0, amt=a, bonus=bonus, method=R.choice(['tiền mặt', 'chuyển khoản', 'ví điện tử'])))
                    mem['bal'] += a + bonus
                mem['bal'] -= amt
            sess.append(dict(id='PH%06d' % sid, machine=m['id'], zone=m['zone'], mem=mem['id'] if mem else None, st=st, en=en, mins=mins,
                             rate=rate, amt=amt if status == 'xong' else 0, gross=amt, status=status, pay=pay))
            if R.random() < 0.35:
                fid += 1
                ft = st + D.timedelta(minutes=R.randint(5, max(6, mins - 5)))
                ls = []
                for it in R.sample(S['menu'], R.choice([1, 1, 2, 3])):
                    q = R.choice([1, 1, 2]); ls.append(dict(code=it['code'], qty=q, price=it['price'], amt=q * it['price']))
                food.append(dict(id='DA%06d' % fid, sess=sess[-1]['id'], machine=m['id'], ts=ft, lines=ls,
                                 status='huỷ' if R.random() < 0.03 else 'xong'))
        # nạp thêm ngẫu nhiên
        for _ in range(poisson(R, 4)):
            mem = wchoice(R, S['members'], mw); a = R.choice([50000, 100000, 200000, 500000]); bonus = int(a * 0.1) if a >= 200000 else 0
            tid += 1; tops.append(dict(id='NT%06d' % tid, mem=mem['id'], ts=D.datetime(d.year, d.month, d.day, R.randint(8, 23), R.randint(0, 59)),
                                       amt=a, bonus=bonus, method=R.choice(['tiền mặt', 'chuyển khoản', 'ví điện tử'])))
            mem['bal'] += a + bonus
    S['sessions'], S['topups'], S['food'] = sess, sorted(tops, key=lambda x: x['ts']), food
    return S

# ============================================================ giặt sấy
def sim_laundry(R, S):
    used = set(); names = make_names(R, 160, used)
    S['custs'] = [dict(name=n, phone=phone(R), w=R.paretovariate(1.25)) for n in names]
    cw = [c['w'] for c in S['custs']]
    svc = [('giặt sấy', 'kg', 16000, 50), ('giặt hấp', 'món', 35000, 15), ('chăn mền', 'cái', 60000, 10), ('ủi', 'món', 8000, 12),
           ('giày', 'đôi', 50000, 6)]
    S['services'] = svc
    tk = []; n_ = 0
    for d in daterange(S['start'], S['end']):
        if d.weekday() == 6 and R.random() < 0.5: continue
        for _ in range(poisson(R, S['lam'] * (1.4 if d.weekday() in (5, 6) else 1))):
            n_ += 1
            s = wchoice(R, svc, [x[3] for x in svc])
            c = wchoice(R, S['custs'], cw)
            if s[1] == 'kg': q = round(R.uniform(1.2, 9.5), 1)
            else: q = R.choice([1, 1, 2, 3, 4, 5])
            price = s[2] if d < D.date(2026, 1, 1) else (s[2] + 1000 if s[1] == 'kg' else s[2])
            amt = money(max(q, 3) * price) if s[1] == 'kg' else money(q * price)
            disc = r100(amt * 0.1) if R.random() < 0.07 else 0
            ship = R.choice([15000, 20000]) if R.random() < 0.15 else 0
            due = d + D.timedelta(days=R.choice([1, 1, 2, 2, 3]))
            st = 'huỷ' if R.random() < 0.025 else 'ok'
            ret = None
            if st == 'ok':
                if R.random() < 0.97:
                    ret = due + D.timedelta(days=R.choice([0, 0, 0, 0, 1, 2, -1, 5, 9]))
                    if ret < d: ret = d
            h = (R.randint(7, 20), R.randint(0, 59))
            tk.append(dict(id='%05d' % n_, date=d, t=h, cust=c, svc=s[0], unit=s[1], q=q, price=price, amt=amt - disc, disc=disc,
                           ship=ship, due=due, ret=ret, status=st))
    S['tickets'] = tk
    return S

# ============================================================ trạm sạc
def sim_charge(R, S):
    S['posts'] = [dict(id='T%02d' % i, kind='AC' if i <= 5 else 'DC', kw=7.4 if i <= 5 else 60) for i in range(1, 9)]
    S['prices'] = {'AC': {'thấp điểm': 3200, 'cao điểm': 3900}, 'DC': {'thấp điểm': 4300, 'cao điểm': 5200}}
    S['price_change'] = (D.date(2026, 4, 1), {'AC': {'thấp điểm': 3400, 'cao điểm': 4100}, 'DC': {'thấp điểm': 4500, 'cao điểm': 5500}})
    prov = ['51H', '51K', '59A', '30G', '29E', '60C', '43A', '65B', '51L', '50H']
    S['cars'] = [dict(plate='%s-%03d.%02d' % (R.choice(prov), R.randint(100, 999), R.randint(10, 99)), w=R.uniform(0.3, 3.0)) for _ in range(260)]
    S['cars'] = list({c['plate']: c for c in S['cars']}.values())
    ww = [c['w'] for c in S['cars']]
    hours = list(zip(range(24), [2, 1, 1, 1, 1, 2, 4, 6, 7, 6, 5, 6, 7, 6, 5, 5, 6, 9, 10, 10, 8, 6, 4, 3]))
    ss = []; n_ = 0
    busy = {p['id']: D.datetime(2000, 1, 1) for p in S['posts']}
    for d in daterange(S['start'], S['end']):
        lam = S['lam'] * (1 + 0.6 * (d - S['start']).days / 365.0)
        for _ in range(poisson(R, lam)):
            st = D.datetime(d.year, d.month, d.day, wchoice(R, [h for h, _ in hours], [w for _, w in hours]), R.randint(0, 59), R.randint(0, 59))
            free = [p for p in S['posts'] if busy[p['id']] <= st]
            if not free: continue
            p = R.choice(free); car = wchoice(R, S['cars'], ww)
            mins = R.randint(25, 70) if p['kind'] == 'DC' else R.randint(60, 420)
            kwh = round(min(p['kw'] * mins / 60.0 * R.uniform(0.55, 0.95), 75), 3)
            en = st + D.timedelta(minutes=mins); busy[p['id']] = en
            tier = 'cao điểm' if 17 <= st.hour <= 21 else 'thấp điểm'
            pr = (S['price_change'][1] if d >= S['price_change'][0] else S['prices'])[p['kind']][tier]
            status = 'lỗi' if R.random() < 0.025 else 'hoàn tất'
            n_ += 1
            ss.append(dict(id='S%06d' % n_, post=p['id'], kind=p['kind'], plate=car['plate'], st=st, en=en, kwh=kwh, tier=tier, price=pr,
                           amt=money(kwh * pr) if status == 'hoàn tất' else 0, status=status,
                           pay=R.choice(['ví điện tử', 'thẻ', 'chuyển khoản', 'ví điện tử'])))
    S['sessions'] = ss
    return S
