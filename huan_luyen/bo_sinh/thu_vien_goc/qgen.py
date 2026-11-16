"""Sinh câu hỏi + đáp án. Mỗi họ câu hỏi trả (câu, type, answer, alias) hoặc None nếu không dùng được."""
import datetime as D, collections, math
from core import *
import engine as E

U = ('unanswerable', None, [])

def months_done(S, t):
    out = []
    y, m = S['start'].year, S['start'].month
    while True:
        a, b = month(y, m)
        if b > min(t, S['end']): break
        out.append((y, m)); y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out

def pick_month(R, S, t, need_prev=False, need_yoy=False):
    ms = months_done(S, t)
    if need_prev: ms = [x for x in ms if month(*prev_month(*x))[0] >= S['start']]
    if need_yoy: ms = [x for x in ms if D.date(x[0] - 1, x[1], 1) >= S['start']]
    return R.choice(ms) if ms else None

def nice(x):
    if x <= 0: return 0
    p = 10 ** max(0, int(math.log10(x)) - 1)
    return int(round(x / p) * p)

def rel_period(R, S, t):
    k = R.choice(['TD', 'YD', 'LW', 'WK', 'LN7', 'LN30', 'YTD', 'TM'])
    if k == 'TD': return (t, t), R.choice(['hôm nay', 'hnay', 'bữa nay', 'riêng hôm nay'])
    if k == 'YD': y = t - D.timedelta(days=1); return (y, y), R.choice(['hôm qua', 'hqua', 'bữa qua'])
    if k == 'LW': return last_week(t), R.choice(['tuần trước', 'tuần rồi', 'tuần trc'])
    if k == 'WK': return this_week(t), R.choice(['tuần này', 'từ đầu tuần tới giờ'])
    if k == 'LN7': return last_n(t, 7), R.choice(['7 ngày gần nhất', '7 ngày qua tính cả hôm nay'])
    if k == 'LN30': return last_n(t, 30), R.choice(['30 ngày gần nhất', '30 ngày qua'])
    if k == 'YTD': return ytd(t), R.choice(['từ đầu năm tới giờ', 'từ đầu năm đến hết hôm nay', 'từ 1/1 tới nay'])
    return this_month(t), R.choice(['tháng này', 'tháng ni', 'th này'])

def mphrase(R, y, m, t):
    if y == t.year and R.random() < 0.15 and D.date(y, m, 1) <= t: return 'tháng %d' % m
    return say_month(R, y, m)

def dphrase(R, d):
    return R.choice(['%02d/%02d/%d' % (d.day, d.month, d.year), '%d/%d/%d' % (d.day, d.month, d.year), 'ngày %d tháng %d năm %d' % (d.day, d.month, d.year)])

# ======================================================================= bán lẻ chung
def F_rev_month(R, S, t):
    x = pick_month(R, S, t)
    if not x: return None
    p = mphrase(R, *x, t)
    q = R.choice(['Doanh thu %s là bao nhiêu?', '%s bán được bao nhiêu tiền?', 'Tổng tiền bán %s được bao nhiêu vậy?', '%s tiệm thu về bao nhiêu doanh thu?']) % p
    return q, 'number', E.rev(S, t, month(*x)), []

def F_rev_rel(R, S, t):
    p, w = rel_period(R, S, t)
    q = R.choice(['Doanh thu %s được bao nhiêu?', '%s bán được bao nhiêu tiền rồi?', 'Tiền bán hàng %s là bao nhiêu?']) % w
    try: return q, 'number', E.rev(S, t, p), []
    except E.Unans: return (q,) + U

def F_nord(R, S, t):
    if R.random() < 0.5:
        x = pick_month(R, S, t); p = month(*x); w = mphrase(R, *x, t)
    else: p, w = rel_period(R, S, t)
    q = R.choice(['%s có bao nhiêu đơn?', 'Số đơn hàng %s là bao nhiêu?', '%s chốt được mấy đơn?']) % w
    try: return q, 'number', E.nord(S, t, p), []
    except E.Unans: return (q,) + U

def F_aov(R, S, t):
    if R.random() < 0.6:
        x = pick_month(R, S, t); p = month(*x); w = mphrase(R, *x, t)
    else: p = last_week(t); w = R.choice(['tuần trước', 'tuần rồi'])
    q = R.choice(['%s trung bình mỗi đơn bao nhiêu tiền?', 'Giá trị trung bình một đơn %s là bao nhiêu?', 'Bình quân 1 đơn %s mang về bao nhiêu doanh thu?']) % w
    try: return q, 'number', E.aov(S, t, p), []
    except E.Unans: return (q,) + U

def F_cancel(R, S, t):
    x = pick_month(R, S, t); w = mphrase(R, *x, t)
    if R.random() < 0.5:
        return R.choice(['%s có mấy đơn bị huỷ?', 'Số đơn huỷ %s?']) % w, 'number', E.cancels(S, t, month(*x)), []
    return R.choice(['Tỉ lệ huỷ đơn %s là bao nhiêu %%?', '%s đơn huỷ chiếm mấy phần trăm?']) % w, 'percent', E.crate(S, t, month(*x)), []

def F_mom(R, S, t):
    x = pick_month(R, S, t, need_prev=True)
    if not x: return None
    w = mphrase(R, *x, t)
    q = R.choice(['Doanh thu %s so với tháng trước tăng hay giảm bao nhiêu %%?', '%s dthu hơn hay kém tháng liền trước mấy %%?']) % w
    return q, 'percent', E.pct(E.rev(S, t, month(*x)), E.rev(S, t, month(*prev_month(*x)))), []

def F_yoy(R, S, t):
    x = pick_month(R, S, t, need_yoy=True)
    if not x: return None
    q = R.choice(['Doanh thu %s so với cùng kỳ năm trước thay đổi bao nhiêu %%?', '%s so với tháng %d/%d doanh thu tăng giảm mấy %%?' % ('%s', x[1], x[0] - 1)]) % say_month(R, *x)
    return q, 'percent', E.pct(E.rev(S, t, month(*x)), E.rev(S, t, month(x[0] - 1, x[1]))), []

def F_mtd(R, S, t):
    if t.day < 3: return None
    q = R.choice(['Doanh thu tháng này tới hôm nay so với cùng kỳ tháng trước hơn hay kém mấy %?', 'Từ đầu tháng đến giờ, doanh thu so cùng số ngày tháng trước tăng hay giảm bao nhiêu %?'])
    return q, 'percent', E.pct(E.rev(S, t, this_month(t)), E.rev(S, t, same_days_prev_month(t))), []

def three(R, S, t):
    ms = months_done(S, t)
    if len(ms) < 3: return None
    i = R.randrange(len(ms) - 2); return ms[i:i + 3]

def F_three(R, S, t):
    ms = three(R, S, t)
    if not ms: return None
    w = ', '.join(say_month(R, *x) for x in ms)
    k = R.random()
    vals = [E.rev(S, t, month(*x)) for x in ms]
    if k < 0.34:
        return R.choice(['Doanh thu %s lần lượt bao nhiêu?', 'Cho xin doanh thu từng tháng %s theo đúng thứ tự.']) % w, 'list', vals, []
    if k < 0.67:
        b = min(range(3), key=lambda i: (-vals[i], ms[i]))
        return R.choice(['Trong %s, tháng nào doanh thu cao nhất?', 'Giữa %s thì tháng nào bán được nhiều tiền nhất?']) % w, 'date', '%d-%02d' % ms[b], []
    return R.choice(['Doanh thu %s có tăng liên tục không?', 'Từ %s, tháng sau luôn cao hơn tháng trước phải không?']) % w, 'boolean', vals[0] < vals[1] < vals[2], []

def F_days(R, S, t):
    x = pick_month(R, S, t); p = month(*x); w = mphrase(R, *x, t); k = R.random()
    if k < 0.3: return R.choice(['%s ngày nào bán được nhiều tiền nhất?', 'Ngày có doanh thu cao nhất %s là ngày nào?']) % w, 'date', E.best_day(S, t, p).isoformat(), []
    if k < 0.5: return R.choice(['%s ngày nào đắt khách nhất?', 'Ngày đông khách nhất %s?']) % w, 'date', E.busy_day(S, t, p).isoformat(), []
    dv = sorted(E.daily(S, t, p).values())
    if not dv: return None
    th = nice(dv[len(dv) // 2] * R.uniform(0.9, 1.15))
    if k < 0.75: return R.choice(['%s có mấy ngày doanh thu từ %s trở lên?', 'Đếm số ngày %s bán được từ %s trở lên.']) % (w, say_money(R, th)), 'number', E.days_ge(S, t, p, th), []
    ov = sorted(sum(l['amt'] for l in o['lines']) for o in E.orders_in(S, t, p))
    th = nice(ov[int(len(ov) * R.uniform(0.6, 0.9))])
    return R.choice(['%s có bao nhiêu đơn tiền hàng từ %s trở lên?', 'Đếm số đơn %s đạt %s trở lên.']) % (w, say_money(R, th)), 'number', E.ord_ge(S, t, p, th), []

def item_name(S, c): return S['imap'][c]['name']

def F_top_item(R, S, t):
    if R.random() < 0.6:
        x = pick_month(R, S, t); p = month(*x); w = mphrase(R, *x, t)
    else: p = last_week(t); w = R.choice(['tuần trước', 'tuần rồi'])
    k = R.choice([None, None, 3, 5])
    try: r, tie = E.top_items(S, t, p, k)
    except E.Unans: return None
    if tie: return None
    if k is None:
        return R.choice(['%s mặt hàng nào bán chạy nhất?', 'Món hot nhất %s là gì?', 'Hàng bán được nhiều nhất %s?']) % w, 'string', item_name(S, r), [r]
    return R.choice(['Top %d mặt hàng bán chạy nhất %s?', '%d món bán nhiều nhất %s là những món nào?']) % (k, w), 'list', [item_name(S, c) for c in r], [[c] for c in r]

def F_top_rev_group(R, S, t):
    groups = sorted({it['group'] for it in S['items']})
    g = R.choice(groups); x = pick_month(R, S, t); w = mphrase(R, *x, t)
    by = R.choice(['rev', 'qty', 'ord'])
    try: r, tie = E.top_items(S, t, month(*x), None, by, group=g)
    except E.Unans: return None
    if tie: return None
    q = {'rev': ['Trong nhóm %s, mặt hàng nào có doanh thu cao nhất %s?', 'Nhóm %s %s hàng nào thu nhiều tiền nhất?'],
         'qty': ['Nhóm %s %s món nào bán chạy nhất?', 'Trong nhóm %s, hàng bán được nhiều nhất %s là gì?'],
         'ord': ['Trong nhóm %s, mặt hàng nào được ưa chuộng nhất %s?', 'Nhóm %s %s món nào có mặt trong nhiều đơn nhất?']}[by]
    return R.choice(q) % (g, w), 'string', item_name(S, r), [r]

def F_qty_item(R, S, t):
    x = pick_month(R, S, t); w = mphrase(R, *x, t)
    it = R.choice([i for i in S['items'] if not i.get('topping')])
    v = E.qty(S, t, month(*x), item=it['code'])
    nm = R.choice([it['name']] + (it.get('alias') or []))
    return R.choice(['%s bán được bao nhiêu %s %s?' % (w, it['base'], nm), '%s %s bán ra mấy %s?' % (nm, w, it['base'])]), 'number', v, []

def F_rev_item(R, S, t):
    x = pick_month(R, S, t); w = mphrase(R, *x, t)
    it = R.choice(S['items']); nm = R.choice([it['name']] + (it.get('alias') or []))
    return R.choice(['Tiền bán %s %s là bao nhiêu?' % (nm, w), '%s mặt hàng %s thu về bao nhiêu tiền?' % (w, nm)]), 'number', E.rev(S, t, month(*x), item=it['code']), []

def F_units(R, S, t):
    bases = collections.Counter(it['base'] for it in S['items'] if not it.get('topping'))
    bs = [b for b, n in bases.items() if n >= 2]
    if not bs: return None
    b = R.choice(bs)
    if R.random() < 0.5:
        x = pick_month(R, S, t); p = month(*x); w = mphrase(R, *x, t)
    else: p, w = rel_period(R, S, t)
    q = R.choice(['%s bán được tổng cộng bao nhiêu %s, tính mọi mặt hàng bán theo %s?' % (w, b, b), 'Tất cả hàng tính theo %s, %s bán ra mấy %s?' % (b, w, b)])
    try: return q, 'number', E.units_of(S, t, p, b), []
    except E.Unans: return (q,) + U

def F_group(R, S, t):
    g = R.choice(sorted({it['group'] for it in S['items']})); x = pick_month(R, S, t); w = mphrase(R, *x, t); k = R.random()
    if k < 0.35:
        return R.choice(['Nhóm %s %s chiếm bao nhiêu %% doanh thu?', 'Tỉ trọng nhóm %s trong doanh thu %s?']) % (g, w), 'percent', \
            r2(E.rev(S, t, month(*x), group=g) / E.rev(S, t, month(*x)) * 100), []
    if k < 0.7: return R.choice(['Nhóm %s %s bán được bao nhiêu tiền?', 'Doanh thu nhóm %s %s?']) % (g, w), 'number', E.rev(S, t, month(*x), group=g), []
    return R.choice(['%s có bao nhiêu đơn mua hàng nhóm %s?' % (w, g), 'Số đơn có ít nhất một món nhóm %s %s?' % (g, w)]), 'number', E.nord_item(S, t, month(*x), group=g), []

def F_itemsin(R, S, t):
    x = pick_month(R, S, t); p = month(*x); w = mphrase(R, *x, t)
    v = sorted(E.item_vals(S, t, p, 'ord').values())
    if len(v) < 4: return None
    n = v[int(len(v) * R.uniform(0.4, 0.8))]
    return R.choice(['%s có mấy mặt hàng có mặt trong ít nhất %d đơn?', '%s bao nhiêu món xuất hiện trong từ %d đơn khác nhau trở lên?']) % (w, n), 'number', E.items_in_n(S, t, p, n), []

def F_cust(R, S, t):
    x = pick_month(R, S, t); p = month(*x); w = mphrase(R, *x, t); k = R.random()
    try: co = E.cust_orders(S, t, p)
    except E.Unans: return None
    vals = sorted(co.values()); n = max(2, vals[int(len(vals) * R.uniform(0.5, 0.85))])
    if k < 0.25:
        q = R.choice(['%s có mấy khách mua từ %d đơn trở lên?' % (w, n), 'Bao nhiêu khách mua ít nhất %d đơn %s?' % (n, w)])
        return q, 'number', E.n_cust_ge(S, t, p, n), []
    if k < 0.45: return 'Trong số khách đã mua %s, mấy %% mua từ %d đơn trở lên?' % (w, n), 'percent', E.pct_cust_ge(S, t, p, n), []
    by = R.choice(['ord', 'rev', 'days', 'sop', 'cancel'])
    if by == 'cancel': p = quarter(x[0], (x[1] - 1) // 3 + 1); w = R.choice(['quý %d/%d', 'Q%d/%d']) % ((x[1] - 1) // 3 + 1, x[0])
    if by == 'cancel' and p[1] > t: return None
    try: r, tie = E.top_cust(S, t, p, by)
    except E.Unans: return None
    if tie: return None
    q = {'ord': '%s khách nào mua nhiều đơn nhất?', 'rev': '%s khách nào chi nhiều tiền nhất?', 'days': '%s ai là khách trung thành nhất?',
         'sop': 'Khách sộp nhất %s là ai?', 'cancel': 'Trong %s, ai là khách hay đổi ý nhất?'}[by] % w
    c = S['cmap'][r]
    return q, 'string', c['name'], ([c['id']] if S['cust_code'] else [])

def F_cust_top_k(R, S, t):
    p = last_week(t) if R.random() < 0.5 else month(*pick_month(R, S, t))
    w = 'tuần trước' if p == last_week(t) else say_month(R, p[0].year, p[0].month)
    k = R.choice([3, 5])
    try: r, tie = E.top_cust(S, t, p, 'rev', k)
    except E.Unans: return None
    if tie or len(r) < k: return None
    return 'Top %d khách chi nhiều tiền nhất %s?' % (k, w), 'list', [S['cmap'][c]['name'] for c in r], ([[c] for c in r] if S['cust_code'] else [])

CH_TXT = {'store': 'bán tại quầy', 'zalo': 'qua Zalo', 'facebook': 'qua Facebook', 'shopee': 'trên Shopee', 'grab': 'qua GrabFood', 'shopeefood': 'qua ShopeeFood'}
PAY_TXT = {'cash': 'trả tiền mặt', 'transfer': 'chuyển khoản', 'ewallet': 'trả bằng ví điện tử', 'cod': 'COD', 'debt': 'ghi nợ'}

def F_chan(R, S, t):
    if not S.get('chans'): return None
    x = pick_month(R, S, t); p = month(*x); w = mphrase(R, *x, t)
    a, b = R.sample([c for c, _ in S['chans']], 2)
    if R.random() < 0.5:
        return 'Doanh thu đơn %s và đơn %s %s lần lượt là bao nhiêu?' % (CH_TXT[a], CH_TXT[b], w), 'list', [E.rev(S, t, p, chan=a), E.rev(S, t, p, chan=b)], []
    return 'Đơn %s chiếm mấy %% doanh thu %s?' % (CH_TXT[a], w), 'percent', r2(E.rev(S, t, p, chan=a) / E.rev(S, t, p) * 100), []

def F_pay(R, S, t):
    if not S.get('pays'): return None
    x = pick_month(R, S, t); p = month(*x); w = mphrase(R, *x, t); a = R.choice([c for c, _ in S['pays']])
    return R.choice(['Doanh thu các đơn %s %s là bao nhiêu?' % (PAY_TXT[a], w), '%s đơn %s mang về bao nhiêu tiền?' % (w, PAY_TXT[a])]), 'number', E.rev(S, t, p, pay=a), []

def F_cgroup(R, S, t):
    if not S['cust_code']: return None
    g = R.choice(['thân thiết', 'sỉ', 'lẻ']); x = pick_month(R, S, t); p = month(*x); w = mphrase(R, *x, t)
    if R.random() < 0.5: return 'Khách nhóm %s %s mua tổng cộng bao nhiêu tiền?' % (g, w), 'number', E.rev(S, t, p, cgroup=g), []
    return 'Khách nhóm %s đóng góp bao nhiêu %% doanh thu %s?' % (g, w), 'percent', r2(E.rev(S, t, p, cgroup=g) / E.rev(S, t, p) * 100), []

def F_shift(R, S, t):
    if not S.get('shift_ok', True): return None
    if R.random() < 0.5:
        x = pick_month(R, S, t); p = month(*x); w = mphrase(R, *x, t)
    else: p = last_week(t); w = 'tuần trước'
    k = R.random()
    if k < 0.35: return '%s doanh thu ca chiều so với ca sáng chênh bao nhiêu %%?' % w, 'percent', E.pct(E.rev(S, t, p, shift='c'), E.rev(S, t, p, shift='s')), []
    if k < 0.65: return 'Số đơn ca chiều %s nhiều hay ít hơn ca sáng mấy %%?' % w, 'percent', E.pct(E.nord(S, t, p, shift='c'), E.nord(S, t, p, shift='s')), []
    if k < 0.85: s = R.choice(['s', 'c']); return 'Riêng ca %s %s bán được bao nhiêu tiền?' % ({'s': 'sáng', 'c': 'chiều'}[s], w), 'number', E.rev(S, t, p, shift=s), []
    return 'Giờ cao điểm %s là mấy giờ?' % w, 'number', E.peak_hour(S, t, p), []

def F_staff(R, S, t):
    if not S.get('staff'): return None
    x = pick_month(R, S, t); p = month(*x); w = mphrase(R, *x, t)
    if R.random() < 0.5:
        s = R.choice(S['staff']); return 'Nhân viên mã %s %s bán được bao nhiêu tiền?' % (s, w), 'number', E.rev(S, t, p, staff=s), []
    v = {s: E.rev(S, t, p, staff=s) for s in S['staff']}; r = sorted(v, key=lambda s: (-v[s], s))
    if v[r[0]] == v[r[1]]: return None
    return '%s nhân viên nào bán giỏi nhất?' % w, 'string', r[0], []

def debt_date(R, S, t):
    if R.random() < 0.5: return t, R.choice(['đến hết hôm nay', 'tính tới hôm nay'])
    return t, 'đến hết ngày ' + dphrase(R, t)

def F_debt(R, S, t):
    if not (S.get('deposit') or any(p == 'debt' for p, _ in S.get('pays') or [])): return None
    X, w = debt_date(R, S, t); k = R.random()
    if k < 0.2: return '%s khách còn nợ tổng cộng bao nhiêu tiền?' % w.capitalize(), 'number', E.debt_total(S, X), []
    if k < 0.35: return '%s còn bao nhiêu khách chưa trả hết nợ?' % w.capitalize(), 'number', E.n_debtors(S, X), []
    if k < 0.5:
        kk = R.choice([3, 5]); rows, tie = E.top_debtors(S, X, kk)
        if tie or len(rows) < kk: return None
        return '%s, %d khách nợ nhiều nhất là ai, mỗi người còn nợ bao nhiêu?' % (w.capitalize(), kk), 'table', {'columns': ['khach_hang', 'so_tien_no'], 'rows': rows}, []
    if k < 0.65: return '%s, nợ còn lại chia theo tuổi nợ 0–7 ngày, 8–15 ngày và trên 15 ngày mỗi nhóm bao nhiêu?' % w.capitalize(), 'list', E.aged(S, X), []
    if k < 0.78:
        n = R.choice([7, 10, 14, 30]); return '%s, các khoản nợ có tuổi quá %d ngày còn bao nhiêu tiền?' % (w.capitalize(), n), 'number', E.aged_over(S, X, n), []
    x = pick_month(R, S, t); w2 = mphrase(R, *x, t)
    if k < 0.9 or S.get('deposit'):
        return R.choice(['%s thu được bao nhiêu tiền khách trả nợ?', '%s khách trả bớt nợ được bao nhiêu?']) % w2, 'number', E.repay(S, t, month(*x)), []
    cs = [o['cust'] for o in E.orders_in(S, t, month(*x)) if o['pay'] == 'debt' and o['cust']]
    if not cs: return None
    c = S['cmap'][R.choice(cs)]
    return 'Khách %s %s nợ thêm bao nhiêu, trả nợ bao nhiêu? Cho số nợ thêm trước.' % (c['name'], w2), 'list', [E.new_debt(S, t, month(*x), c['id']), E.repay(S, t, month(*x), c['id'])], []

def F_purch(R, S, t):
    if not S.get('stock'): return None
    x = pick_month(R, S, t); p = month(*x); w = mphrase(R, *x, t); k = R.random()
    if k < 0.45: return R.choice(['%s nhập hàng tổng cộng bao nhiêu tiền?', 'Tiền nhập hàng %s?']) % w, 'number', E.purch(S, t, p), []
    by = 'amt' if k < 0.75 else 'n'
    try: s, tie = E.top_sup(S, t, p, by)
    except E.Unans: return None
    if tie: return None
    return ('%s nhập của nhà cung cấp nào nhiều tiền nhất?' % w) if by == 'amt' else ('%s nhà cung cấp chính của tiệm là ai?' % w), 'string', s, []

def F_stock(R, S, t):
    if not S.get('stock'): return None
    X = t if R.random() < 0.6 else S['start'] + D.timedelta(days=R.randint(20, (t - S['start']).days))
    if R.random() < 0.6:
        it = R.choice([i for i in S['items'] if not i.get('made')])
        return 'Đến hết ngày %s còn tồn bao nhiêu %s %s?' % (dphrase(R, X), it['base'], it['name']), 'number', num_out(E.stock_at(S, X, it['code'])), []
    return 'Hết ngày %s, hàng tồn kho tính theo giá vốn danh mục là bao nhiêu tiền?' % dphrase(R, X), 'number', E.stock_value(S, X), []

def F_hike(R, S, t):
    cand = []
    for c, h in S['ph'].items():
        for (d0, p0), (d1, p1) in zip(h, h[1:]): cand.append((c, d1, p1, p0))
    R.shuffle(cand)
    for c, d1, p1, p0 in cand:
        n = R.choice([7, 14, 30])
        try: v = E.hike(S, t, c, d1, n)
        except E.Unans: continue
        it = S['imap'][c]
        if R.random() < 0.5:
            q = '%s lên giá %s từ ngày %s; so %d ngày kể từ ngày tăng với %d ngày ngay trước, số %s bán ra tăng hay giảm bao nhiêu %%?' % (
                it['name'], say_money(R, p1), dphrase(R, d1), n, n, it['base'])
        else:
            q = 'Từ khi %s tăng giá lên %s/%s, %d ngày đầu bán nhiều hay ít hơn %d ngày liền trước mấy %%, tính theo %s?' % (it['name'], say_money(R, p1), it['base'], n, n, it['base'])
        return q, 'percent', v, []
    return None

def F_tet(R, S, t):
    a, b = tet(2026)
    if not (S['start'] <= a - D.timedelta(days=(b - a).days + 1) and b <= min(t, S['end'])): return None
    k = R.random()
    if k < 0.35: return 'Dịp Tết 2026 doanh thu được bao nhiêu?', 'number', E.rev(S, t, (a, b)), []
    if k < 0.7:
        n = (b - a).days + 1; pa = (a - D.timedelta(days=n), a - D.timedelta(days=1))
        return 'Doanh thu dịp Tết âm lịch 2026 so với %d ngày ngay trước Tết thay đổi bao nhiêu %%?' % n, 'percent', E.pct(E.rev(S, t, (a, b)), E.rev(S, t, pa)), []
    r, tie = E.top_items(S, t, (a, b))
    if tie: return None
    return 'Dịp Tết Nguyên đán 2026 mặt hàng nào bán chạy nhất?', 'string', item_name(S, r), [r]

def F_unans(R, S, t):
    x = pick_month(R, S, t); w = mphrase(R, *x, t)
    qs = ['%s khách nữ mua tổng cộng bao nhiêu tiền?' % w, '%s món nào ngon nhất?' % w, 'Khách ở đường Trần Hưng Đạo %s mua bao nhiêu tiền?' % w,
          '%s khách huỷ đơn chủ yếu vì lý do gì?' % w, 'Nhân viên nào phục vụ niềm nở nhất %s?' % w, 'Doanh thu tháng 11/2024 là bao nhiêu?',
          'Khách nào hài lòng nhất %s?' % w]
    if not S.get('chans'): qs.append('Doanh thu đơn bán qua Zalo %s là bao nhiêu?' % w)
    if not S.get('staff'): qs.append('%s nhân viên nào bán được nhiều tiền nhất?' % w)
    if not S.get('stock'): qs.append('Đến hết hôm nay còn tồn bao nhiêu hàng?')
    if not (S.get('deposit') or any(p == 'debt' for p, _ in S.get('pays') or [])): qs.append('Đến hết hôm nay khách còn nợ bao nhiêu tiền?')
    if not S.get('shift_ok', True): qs.append('Ca chiều %s bán được bao nhiêu?' % w)
    return (R.choice(qs),) + U

# ----- riêng ngành
def F_flower(R, S, t):
    k = R.random()
    hol = R.choice(['Valentine', 'Quốc tế Phụ nữ', 'Phụ nữ Việt Nam', 'Nhà giáo Việt Nam'])
    ds = [d for d in holiday_dates(hol) if S['start'] <= d - D.timedelta(days=2) and d <= min(t, S['end'])]
    lab = {'Valentine': 'Valentine 14/2', 'Quốc tế Phụ nữ': '8/3', 'Phụ nữ Việt Nam': '20/10', 'Nhà giáo Việt Nam': '20/11'}[hol]
    if k < 0.4 and ds:
        d = R.choice(ds); p = (d - D.timedelta(days=2), d)
        if R.random() < 0.6: return 'Dịp %s năm %d tiệm bán được bao nhiêu tiền?' % (lab, d.year), 'number', E.rev(S, t, p), []
        return 'Dịp %s năm %d bán ra bao nhiêu cành hoa hồng đỏ Đà Lạt?' % (lab, d.year), 'number', E.qty(S, t, p, item='HM001'), []
    if k < 0.55 and len(ds) >= 2:
        d0, d1 = ds[-2], ds[-1]
        return 'Doanh thu dịp %s năm %d so với năm %d tăng hay giảm bao nhiêu %%?' % (lab, d1.year, d0.year), 'percent', \
            E.pct(E.rev(S, t, (d1 - D.timedelta(days=2), d1)), E.rev(S, t, (d0 - D.timedelta(days=2), d0))), []
    if k < 0.85:
        lm = R.choice([1, 7, 8, 10, 12, 3]); ld = R.choice([1, 15])
        cands = [y for y in (2025, 2026) if lunar_to_solar(y, lm, ld) and S['start'] <= lunar_to_solar(y, lm, ld) <= min(t, S['end'])]
        if not cands: return None
        y = R.choice(cands); d = lunar_to_solar(y, lm, ld)
        nm = ('rằm' if ld == 15 else 'mùng 1') + ' tháng %s âm lịch năm %d' % ({1: 'Giêng', 12: 'Chạp'}.get(lm, str(lm)), y)
        if R.random() < 0.5: return 'Ngày %s tiệm bán được bao nhiêu tiền?' % nm, 'number', E.rev(S, t, (d, d)), []
        return 'Ngày %s bán bao nhiêu cành cúc vàng?' % nm, 'number', E.qty(S, t, (d, d), item='HM008'), []
    x = pick_month(R, S, t)
    return '%s bán được bao nhiêu bó hoa hồng đỏ Đà Lạt nguyên bó (tính theo dòng bán theo bó)?' % say_month(R, *x), 'number', \
        num_out(sum(l['qty'] for o, l in E.lines_in(S, t, month(*x), item='HM001') if l['unit'] == 'bó')), []

def F_fish(R, S, t):
    x = pick_month(R, S, t); p = month(*x); w = mphrase(R, *x, t); k = R.random()
    if k < 0.4:
        n = sum(1 for o, l in E.lines_in(S, t, p) if l['kind'] == 'exchange')
        return '%s tiệm đổi bao nhiêu con cá chết cho khách?' % w, 'number', n, []
    if k < 0.7: return '%s bán được bao nhiêu con cá (nhóm cá)?' % w, 'number', E.units_of(S, t, p, 'con', group='cá'), []
    it = R.choice([i for i in S['items'] if i.get('live')])
    return '%s bán ra bao nhiêu con %s?' % (w, it['name']), 'number', E.qty(S, t, p, item=it['code']), []

def F_print(R, S, t):
    x = pick_month(R, S, t); p = month(*x); w = mphrase(R, *x, t); k = R.random()
    if k < 0.25: return '%s xưởng in bao nhiêu gram nhựa PLA cho khách?' % w, 'number', E.qty(S, t, p, item='IN001'), []
    if k < 0.45:
        v = sum(o['deposit'] for o in E.orders_in(S, t, p, statuses=('cancel',)))
        return '%s tiền cọc của các đơn bị huỷ cộng lại bao nhiêu?' % w, 'number', money(v), []
    if k < 0.65:
        v = sum(l['amt'] - l['qty'] * l['cost'] for o, l in E.lines_in(S, t, p)); return 'Lãi gộp %s được bao nhiêu?' % w, 'number', money(v), []
    if k < 0.8:
        r, tie = E.top_items(S, t, p, None, 'margin')
        if tie: return None
        return '%s mặt hàng nào lời nhiều nhất?' % w, 'string', item_name(S, r), [r]
    v = sum(o['deposit'] for o in E.orders_in(S, t, p, statuses=('done', 'ship', 'return', 'cancel')))
    return '%s xưởng thu tiền cọc tổng cộng bao nhiêu?' % w, 'number', money(v), []

def F_books(R, S, t):
    x = pick_month(R, S, t); p = month(*x); w = mphrase(R, *x, t); k = R.random()
    ow = R.choice(list(S['owners']))
    if k < 0.35:
        v = sum(l['amt'] for o, l in E.lines_in(S, t, p, owner=ow)) * (100 - S['owners'][ow]) / 100
        return '%s tiệm phải trả cho chủ ký gửi %s bao nhiêu tiền?' % (w, ow), 'number', money(v), []
    if k < 0.6:
        v = sum(money(sum(l['amt'] for o, l in E.lines_in(S, t, p, owner=o_)) * r_ / 100) for o_, r_ in S['owners'].items())
        return '%s tiền hoa hồng tiệm hưởng từ sách ký gửi (cộng mọi chủ) là bao nhiêu?' % w, 'number', money(v), []
    if k < 0.8:
        a = sum(l['amt'] for o, l in E.lines_in(S, t, p) if S['imap'][l['code']]['owner'] != 'Tiệm')
        return 'Sách ký gửi chiếm bao nhiêu %% doanh thu %s?' % w, 'percent', r2(a / E.rev(S, t, p) * 100), []
    g = R.choice(sorted({it['group'] for it in S['items']}))
    return '%s bán được bao nhiêu cuốn sách thể loại %s?' % (w, g), 'number', E.qty(S, t, p, group=g), []

def F_dessert(R, S, t):
    x = pick_month(R, S, t); p = month(*x); w = mphrase(R, *x, t); k = R.random()
    if k < 0.45:
        s = R.choice(['M', 'L'])
        v = sum(l['qb'] for o, l in E.lines_in(S, t, p) if S['imap'][l['code']]['name'].lower().endswith('(%s)' % s.lower()))
        return '%s quán bán được bao nhiêu ly size %s, cộng mọi món?' % (w, s), 'number', num_out(v), []
    tp = R.choice([i for i in S['items'] if i.get('topping')])
    if k < 0.75: return '%s %s bán được bao nhiêu phần?' % (w, tp['name']), 'number', E.qty(S, t, p, item=tp['code']), []
    return '%s topping bán được bao nhiêu tiền tất cả?' % w, 'number', E.rev(S, t, p, group='topping'), []

def F_vet(R, S, t):
    k = R.random()
    if k < 0.3:
        x = pick_month(R, S, t); p = month(*x); w = mphrase(R, *x, t)
        if R.random() < 0.5: return 'Thuốc kê đơn chiếm bao nhiêu %% doanh thu %s?' % w, 'percent', r2(E.rev(S, t, p, rx=True) / E.rev(S, t, p) * 100), []
        ing = R.choice([i['ing'] for i in S['items'] if i.get('ing')])
        return 'Doanh thu các thuốc có hoạt chất %s %s?' % (ing, w), 'number', E.rev(S, t, p, ing=ing), []
    n = R.choice([30, 60, 90, 120, 180])
    lots, rem = E.expiring(S, t, n)
    if k < 0.5: return 'Hàng còn tồn hết hạn trong %d ngày tới đọng bao nhiêu tiền vốn?' % n, 'number', money(sum(rem[l['lot']] * l['cost'] for l in lots)), []
    if k < 0.65: return 'Hiện còn bao nhiêu lô chưa bán hết có hạn dùng trong %d ngày tới?' % n, 'number', len(lots), []
    if k < 0.85:
        it = R.choice(S['items']); rem = E.lot_remaining(S, t)
        ls = [l for l in S['lots'] if l['code'] == it['code'] and rem[l['lot']] > 1e-9 and l['exp'] >= t]
        if not ls: return None
        return 'Tính tại hôm nay, lô %s gần hết hạn nhất hết hạn ngày nào?' % it['name'], 'date', min(l['exp'] for l in ls).isoformat(), []
    lots, rem = E.expiring(S, t, n)
    m = collections.defaultdict(lambda: D.date(9999, 1, 1))
    for l in lots: m[l['code']] = min(m[l['code']], l['exp'])
    if not m or len(m) > 8: return None
    r = sorted(m, key=lambda c: (m[c], c))
    return 'Liệt kê các sản phẩm còn lô tồn hết hạn trong %d ngày tới, hạn sớm trước.' % n, 'list', [item_name(S, c) for c in r], [[c] for c in r]

def F_table(R, S, t):
    x = pick_month(R, S, t); p = month(*x); w = mphrase(R, *x, t); k = R.random()
    if k < 0.5 or not (S.get('staff') or S.get('chans')):
        gs = sorted({it['group'] for it in S['items']})
        rows = [[g, E.rev(S, t, p, group=g), E.nord_item(S, t, p, group=g)] for g in gs]
        return 'Lập bảng mọi nhóm hàng %s gồm doanh thu và số đơn có mua nhóm đó.' % w, 'table', {'columns': ['nhom_hang', 'doanh_thu', 'so_don'], 'rows': rows}, []
    if S.get('staff') and (k < 0.8 or not S.get('chans')):
        rows = [[s, E.rev(S, t, p, staff=s), E.nord(S, t, p, staff=s)] for s in S['staff']]
        return 'Cho bảng doanh thu và số đơn của từng nhân viên %s.' % w, 'table', {'columns': ['nhan_vien', 'doanh_thu', 'so_don'], 'rows': rows}, []
    rows = [[__import__('writers').CHAN_VN[c][0], E.rev(S, t, p, chan=c)] for c, _ in S['chans']]
    return 'Lập bảng doanh thu %s theo từng kênh bán.' % w, 'table', {'columns': ['kenh', 'doanh_thu'], 'rows': rows}, []

RETAIL = [(F_rev_month, 5), (F_rev_rel, 5), (F_nord, 4), (F_aov, 3), (F_cancel, 3), (F_mom, 3), (F_yoy, 2), (F_mtd, 2), (F_three, 4), (F_days, 4),
          (F_top_item, 4), (F_top_rev_group, 2), (F_qty_item, 3), (F_rev_item, 2), (F_units, 3), (F_group, 3), (F_itemsin, 1.5), (F_cust, 3.5),
          (F_cust_top_k, 1), (F_chan, 2), (F_pay, 1.5), (F_cgroup, 1.5), (F_shift, 2.5), (F_staff, 1.5), (F_debt, 4), (F_purch, 2), (F_stock, 3),
          (F_hike, 2), (F_tet, 1.5), (F_unans, 2.5), (F_table, 1.5)]
SPECIAL = {'biz_201': (F_flower, 9), 'biz_202': (F_fish, 5), 'biz_205': (F_print, 7), 'biz_207': (F_books, 8), 'biz_208': (F_dessert, 6), 'biz_209': (F_vet, 9)}

# ======================================================================= phòng net
def in_p(dt, p): return p[0] <= dt.date() <= p[1]

def net_q(R, S, t):
    def P(x): return E.clamp(S, t, month(*x))
    x = pick_month(R, S, t); p = P(x); w = mphrase(R, *x, t); k = R.randrange(15)
    ss = [s for s in S['sessions'] if in_p(s['st'], p)]
    ok = [s for s in ss if s['status'] == 'xong']
    fd = [f for f in S['food'] if in_p(f['ts'], p) and f['status'] != 'huỷ']
    frev = sum(l['amt'] for f in fd for l in f['lines'])
    if k == 0: return 'Doanh thu %s của quán (tiền giờ và đồ ăn uống) là bao nhiêu?' % w, 'number', money(sum(s['amt'] for s in ok) + frev), []
    if k == 1: return '%s hội viên nạp vào tài khoản bao nhiêu tiền (tiền khách đưa)?' % w, 'number', money(sum(x['amt'] for x in S['topups'] if in_p(x['ts'], p))), []
    if k == 2: return '%s khách chơi tổng cộng bao nhiêu giờ?' % w, 'number', r2(sum(s['mins'] for s in ok) / 60), []
    if k == 3:
        v = sum(s['mins'] for s in ok if s['zone'] == 'VIP') / sum(s['mins'] for s in ok) * 100
        return 'Giờ chơi khu VIP chiếm bao nhiêu %% tổng giờ chơi %s?' % w, 'percent', r2(v), []
    if k == 4:
        c = collections.Counter()
        for s in ok: c[s['machine']] += s['mins']
        r = sorted(c, key=lambda m: (-c[m], m))
        if c[r[0]] == c[r[1]]: return None
        return '%s máy nào được chơi nhiều giờ nhất?' % w, 'string', r[0], []
    if k == 5: return 'Tiền giờ ca đêm %s được bao nhiêu?' % w, 'number', money(sum(s['amt'] for s in ok if s['st'].hour >= 22 or s['st'].hour < 6)), []
    if k == 6: return '%s có bao nhiêu phiên phải hoàn tiền vì lỗi máy?' % w, 'number', sum(1 for s in ss if s['status'] == 'hoàn tiền'), []
    if k == 7: return 'Trung bình mỗi phiên chơi %s kéo dài bao nhiêu phút?' % w, 'number', r2(sum(s['mins'] for s in ok) / len(ok)), []
    if k == 8:
        c = collections.Counter(s['st'].hour for s in ok); return 'Giờ cao điểm %s (khung giờ có nhiều phiên bắt đầu nhất) là mấy giờ?' % w, 'number', min(c, key=lambda h: (-c[h], h)), []
    if k == 9:
        m = R.choice(S['members']); X = t
        bal = sum(x['amt'] + x['bonus'] for x in S['topups'] if x['mem'] == m['id'] and x['ts'].date() <= X) - \
              sum(s['amt'] for s in S['sessions'] if s['mem'] == m['id'] and s['status'] == 'xong' and s['pay'] == 'tài khoản' and s['st'].date() <= X)
        return 'Đến hết ngày %s, tài khoản hội viên %s (%s) còn bao nhiêu tiền?' % (dphrase(R, X), m['name'], m['id']), 'number', money(bal), []
    if k == 10:
        c = collections.Counter()
        for x_ in S['topups']:
            if in_p(x_['ts'], p): c[x_['mem']] += x_['amt']
        r = sorted(c, key=lambda m: (-c[m], m))
        if len(r) < 2 or c[r[0]] == c[r[1]]: return None
        mm = {m['id']: m for m in S['members']}
        return '%s hội viên nào nạp nhiều tiền nhất?' % w, 'string', mm[r[0]]['name'], [r[0]]
    if k == 11:
        c = collections.Counter()
        for f in fd:
            for l in f['lines']: c[l['code']] += l['qty']
        r = sorted(c, key=lambda m: (-c[m], m))
        if c[r[0]] == c[r[1]]: return None
        nm = {it['code']: it['name'] for it in S['menu']}
        return '%s món nào được gọi nhiều nhất (theo số lượng)?' % w, 'string', nm[r[0]], [r[0]]
    if k == 12: return '%s có bao nhiêu phiên chơi kéo dài qua nửa đêm?' % w, 'number', sum(1 for s in ok if s['en'].date() > s['st'].date()), []
    if k == 13: return '%s có bao nhiêu hội viên khác nhau ra chơi?' % w, 'number', len({s['mem'] for s in ok if s['mem']}), []
    return (R.choice(['Khách nữ %s chơi bao nhiêu giờ?' % w, 'Máy nào %s hay bị khách chê lag nhất?' % w, 'Doanh thu tháng 2/2025 bao nhiêu?']),) + U

# ======================================================================= giặt sấy
def norm_phone(s): return re.sub(r'\D', '', s).replace('84', '0', 1) if s.startswith('+') else re.sub(r'\D', '', s)

def laundry_q(R, S, t):
    x = pick_month(R, S, t); p = E.clamp(S, t, month(*x)); w = mphrase(R, *x, t); k = R.randrange(13)
    tk = [z for z in S['tickets'] if p[0] <= z['date'] <= p[1]]
    ok = [z for z in tk if z['status'] != 'huỷ']
    if k == 0: return 'Doanh thu %s của tiệm là bao nhiêu?' % w, 'number', money(sum(z['amt'] for z in ok)), []
    if k == 1: return '%s tiệm giặt sấy bao nhiêu kg đồ?' % w, 'number', r2(sum(z['q'] for z in ok if z['svc'] == 'giặt sấy')), []
    if k == 2: return '%s tiệm nhận bao nhiêu phiếu?' % w, 'number', len(ok), []
    if k == 3:
        X = t if R.random() < 0.5 else S['start'] + D.timedelta(days=R.randint(30, (t - S['start']).days))
        v = sum(1 for z in S['tickets'] if z['status'] != 'huỷ' and z['date'] <= X and (z['ret'] is None or z['ret'] > X))
        return 'Đến hết ngày %s tiệm còn giữ đồ của bao nhiêu phiếu chưa trả khách?' % dphrase(R, X), 'number', v, []
    if k == 4: return 'Trong các phiếu nhận %s, bao nhiêu phiếu trả đồ trễ hẹn?' % w, 'number', sum(1 for z in ok if z['ret'] and z['ret'] > z['due']), []
    if k == 5:
        done = [z for z in ok if z['ret']]
        return 'Các phiếu nhận %s đã trả đồ, mấy %% bị trả trễ hẹn?' % w, 'percent', r2(sum(1 for z in done if z['ret'] > z['due']) / len(done) * 100), []
    if k == 6:
        c = collections.Counter(z['cust']['phone'] for z in ok); r = sorted(c, key=lambda m: (-c[m], m))
        if c[r[0]] == c[r[1]]: return None
        return '%s khách nào gửi đồ nhiều phiếu nhất? Trả lời số điện thoại.' % w, 'string', r[0], []
    if k == 7:
        g = [z['q'] for z in ok if z['svc'] == 'giặt sấy']
        return 'Trung bình mỗi phiếu giặt sấy %s bao nhiêu kg?' % w, 'number', r2(sum(g) / len(g)), []
    if k == 8:
        s = R.choice(['giặt hấp', 'chăn mền', 'ủi', 'giày'])
        return 'Dịch vụ %s %s thu được bao nhiêu tiền?' % (s, w), 'number', money(sum(z['amt'] for z in ok if z['svc'] == s)), []
    if k == 9: return '%s tiệm thu phí giao tận nhà tổng cộng bao nhiêu?' % w, 'number', money(sum(z['ship'] for z in ok)), []
    if k == 10:
        c = collections.Counter(z['date'] for z in ok); return '%s ngày nào nhận nhiều phiếu nhất?' % w, 'date', min(c, key=lambda d: (-c[d], d)).isoformat(), []
    if k == 11: return '%s có bao nhiêu khách khác nhau gửi đồ?' % w, 'number', len({z['cust']['phone'] for z in ok}), []
    return (R.choice(['%s khách nào đánh giá tiệm 5 sao?' % w, 'Máy giặt nào %s chạy nhiều nhất?' % w]),) + U

# ======================================================================= trạm sạc
def charge_q(R, S, t):
    x = pick_month(R, S, t); p = E.clamp(S, t, month(*x)); w = mphrase(R, *x, t); k = R.randrange(13)
    ss = [s for s in S['sessions'] if p[0] <= s['st'].date() <= p[1]]
    ok = [s for s in ss if s['status'] == 'hoàn tất']
    if k == 0: return '%s trạm sạc được bao nhiêu kWh?' % w, 'number', r2(sum(s['kwh'] for s in ok)), []
    if k == 1: return 'Doanh thu %s của trạm là bao nhiêu?' % w, 'number', money(sum(s['amt'] for s in ok)), []
    if k == 2: return 'Điện năng sạc ở trụ DC chiếm bao nhiêu %% tổng kWh %s?' % w, 'percent', r2(sum(s['kwh'] for s in ok if s['kind'] == 'DC') / sum(s['kwh'] for s in ok) * 100), []
    if k == 3:
        c = collections.Counter(s['plate'] for s in ok); r = sorted(c, key=lambda m: (-c[m], m))
        if c[r[0]] == c[r[1]]: return None
        return '%s xe nào sạc nhiều lần nhất? Trả lời biển số.' % w, 'string', r[0], [r[0].replace('-', '').replace('.', '')]
    if k == 4: return '%s có bao nhiêu xe khác nhau tới sạc?' % w, 'number', len({s['plate'] for s in ok}), []
    if k == 5: return 'Trung bình mỗi phiên sạc %s được bao nhiêu kWh?' % w, 'number', r2(sum(s['kwh'] for s in ok) / len(ok)), []
    if k == 6:
        c = collections.Counter(s['st'].hour for s in ok); return 'Giờ cao điểm %s (khung giờ có nhiều phiên bắt đầu nhất) là mấy giờ?' % w, 'number', min(c, key=lambda h: (-c[h], h)), []
    if k == 7:
        a = sum(s['amt'] for s in ok if s['tier'] == 'cao điểm'); b = sum(s['amt'] for s in ok if s['tier'] == 'thấp điểm')
        return 'Doanh thu khung cao điểm %s so với khung thấp điểm chênh bao nhiêu %%?' % w, 'percent', E.pct(a, b), []
    if k == 8:
        c = collections.Counter()
        for s in ok: c[s['post']] += s['kwh']
        r = sorted(c, key=lambda m: (-c[m], m))
        return '%s trụ nào sạc ra nhiều kWh nhất?' % w, 'string', r[0], []
    if k == 9: return '%s có bao nhiêu phiên sạc bị lỗi?' % w, 'number', sum(1 for s in ss if s['status'] == 'lỗi'), []
    if k == 10:
        car = R.choice(ok)['plate']; v = [s for s in ok if s['plate'] == car]
        return '%s xe biển %s sạc tổng cộng bao nhiêu tiền?' % (w, car.replace('.', '').replace('-', ' ')), 'number', money(sum(s['amt'] for s in v)), []
    if k == 11:
        if R.random() < 0.5: return '%s doanh thu các trụ AC là bao nhiêu?' % w, 'number', money(sum(s['amt'] for s in ok if s['kind'] == 'AC')), []
        rows = [[pp['id'], r2(sum(s['kwh'] for s in ok if s['post'] == pp['id'])), money(sum(s['amt'] for s in ok if s['post'] == pp['id']))] for pp in S['posts']]
        return 'Lập bảng từng trụ sạc %s gồm số kWh và doanh thu.' % w, 'table', {'columns': ['tru', 'kwh', 'doanh_thu'], 'rows': rows}, []
    return (R.choice(['%s xe hãng VinFast sạc bao nhiêu kWh?' % w, 'Tài xế nào %s đậu xe lâu nhất sau khi sạc xong?' % w]),) + U

# ======================================================================= chạy
def asof_dates(R, S, n):
    out = []
    span = (S['end'] - S['start']).days
    for _ in range(n):
        if R.random() < 0.5: out.append(S['end'])
        else: out.append(S['start'] + D.timedelta(days=R.randint(int(span * 0.35), span)))
    return out

def gen_questions(R, S, n):
    res = []; seen = set(); tries = 0
    fams = RETAIL + ([SPECIAL[S['id']]] if S['id'] in SPECIAL else [])
    while len(res) < n and tries < n * 40:
        tries += 1
        t = asof_dates(R, S, 1)[0]
        try:
            if S['kind'] == 'retail': f = R.choices([f for f, _ in fams], [w for _, w in fams])[0]; out = f(R, S, t)
            elif S['kind'] == 'net': out = net_q(R, S, t)
            elif S['kind'] == 'laundry': out = laundry_q(R, S, t)
            else: out = charge_q(R, S, t)
        except (E.Unans, ZeroDivisionError, IndexError, ValueError, TypeError):
            continue
        if not out: continue
        q, typ, ans, alias = out
        key = (q, t)
        if key in seen: continue
        seen.add(key)
        res.append(dict(q=noisy(R, q[0].upper() + q[1:], R.uniform(0.15, 0.85)), raw=q, t=t, type=typ, answer=ans, alias=alias))
    return res
