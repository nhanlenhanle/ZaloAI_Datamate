"""Bộ "rulebook đổi luật" (sinh.py --luat-doi A|B|C|D): đổi một nhóm luật của rulebook, tính đáp án và lời giải theo luật mới.

A  doanh thu một đơn trừ giảm giá trên cả đơn (voucher, khuyến mãi tổng đơn); doanh thu theo mặt hàng / nhóm hàng giữ nguyên.
B  đơn trả một phần không bỏ cả đơn: chỉ trừ tiền phần hàng bị trả; đơn bị trả hết mọi mặt hàng mới bỏ.
C  tỉ lệ huỷ = số đơn huỷ / số đơn hoàn thành × 100 (không chia cho mọi đơn).
D  đơn COD tính vào tiền mặt; khách vãng lai (không mã khách) xếp vào nhóm khách "lẻ".

Cách làm: bọc các hàm tính của engine (A, C, D) hoặc thay danh sách đơn mà engine nhìn thấy (B), có công tắc `bat` để tính
lại cùng câu hỏi theo luật gốc (so đáp án hai luật). Không sửa thư viện gốc; không bật cờ thì sinh.py chạy y như cũ.
"""
import collections
import copy
import datetime as D
import random
import re

NHOM = ('A', 'B', 'C', 'D', 'E', 'F', 'G')
LINE_F = ('item', 'group', 'owner', 'rx', 'ing')

# ------------------------------------------------------------------ câu chữ luật (mục 1 của rulebook + từng shop ở mục 6)
DONG_CU = {
    'A': '| Doanh thu một đơn |',
    'B': '| Đơn tính doanh thu |',
    'C': '| Tỉ lệ đơn huỷ |',
    'D': '| Doanh thu theo kênh, hình thức thanh toán, nhóm khách |',
    'E': '| Nợ một đơn tại ngày X |',
    'F': '| Tuổi nợ |',
    'G': '| Bán chạy, bán nhiều nhất, hot nhất |',
}
DONG_MOI = {
    'A': '| Doanh thu một đơn | tổng **thành tiền các dòng hàng** (đã trừ giảm giá dòng) **rồi trừ tiếp giảm giá trên cả đơn** '
         '(voucher, khuyến mãi tổng đơn, chiết khấu đơn); không gồm phí giao. Doanh thu theo mặt hàng, nhóm hàng vẫn lấy thành tiền '
         'dòng (giảm giá đơn không chia xuống từng dòng). "Bán được bao nhiêu tiền", "tiền hàng", "tiền bán" cùng nghĩa doanh thu |',
    'B': '| Đơn tính doanh thu | đơn **không huỷ**. Đơn có trả hàng **vẫn tính**: chỉ trừ phần hàng bị trả, mỗi dòng trừ '
         '`thành tiền dòng × SL trả / SL dòng` (quy về đơn vị cơ bản, làm tròn đồng), số lượng bán cũng trừ phần trả; đơn bị trả '
         '**hết** mọi mặt hàng thì bỏ. Hàng trả ghi ở `TraHang.xlsx`. Đơn đang giao vẫn tính |',
    'C': '| Tỉ lệ đơn huỷ | số đơn huỷ chia cho số đơn **hoàn thành** đặt trong kỳ, nhân 100; đơn đang giao, đơn trả hàng '
         'không vào mẫu số |',
    'D': '| Doanh thu theo kênh, hình thức thanh toán, nhóm khách | theo giá trị **ghi trên đơn**, với hai điều chỉnh: đơn '
         '**COD gộp vào tiền mặt** (doanh thu tiền mặt gồm cả COD), và đơn **khách vãng lai** (không mã khách) **thuộc nhóm '
         'khách `lẻ`**. Tỉ trọng chia cho doanh thu **cả cửa hàng** cùng kỳ |',
    'E': '| Nợ một đơn tại ngày X | **tổng tiền hàng của đơn sau giảm giá đơn, KHÔNG gồm phí giao** (phí giao khách trả riêng, không tính '
         'vào nợ) trừ các khoản đã trả đến hết ngày X; cộng các đơn còn nợ > 0 |',
    'F': '| Tuổi nợ | số ngày tính từ **hạn thanh toán** của đơn (cột hạn thanh toán ghi trên đơn) tới ngày X, **không** tính từ ngày '
         'đặt; đơn chưa tới hạn có tuổi nợ **0** ngày |',
    'G': '| Bán chạy, bán nhiều nhất, hot nhất | theo **doanh thu** (tổng thành tiền dòng) của mặt hàng, **không** theo số lượng; bỏ đơn '
         'huỷ, trả. Số lượng chỉ dùng khi câu hỏi hỏi số lượng bán |',
}
# luật đi kèm phải sửa theo cho khỏi mâu thuẫn
DONG_KEM = {
    'E': [('| Nợ thêm / trả nợ trong kỳ |', '| Nợ thêm / trả nợ trong kỳ | **Nợ thêm**: phần tổng phải trả (**không gồm phí giao**) chưa trả '
                                        'ngay trong ngày mua của đơn ghi nợ đặt trong kỳ, âm thì tính 0. **Trả nợ**: các khoản trả có ngày '
                                        'trong kỳ và **sau ngày mua**, của mọi đơn ghi nợ không huỷ |')],
    'B': [('| Số đơn |', '| Số đơn | chỉ đơn không huỷ và **không bị trả hết**; cả khi đếm đơn có một nhóm hàng, đơn của một khách. '
                         '**Khách đã mua** trong kỳ là khách có ít nhất một đơn như vậy |'),
          ('| Bán chạy, bán nhiều nhất, hot nhất |', '| Bán chạy, bán nhiều nhất, hot nhất | theo **số lượng quy về đơn vị cơ bản**; '
                                                     'bỏ đơn huỷ, bỏ phần hàng bị trả |')],
}
CAU_SHOP = {
    'E': ['Phí giao hàng khách trả riêng cho người giao nên không tính vào nợ của đơn.',
          'Nợ của một đơn chỉ tính trên tiền hàng sau giảm giá đơn, bỏ phần phí ship.',
          'Tiền ship không bao giờ nằm trong số khách còn nợ.',
          'Khi tính khách còn nợ bao nhiêu, lấy tổng đơn trừ phí giao rồi mới trừ tiền khách đã trả.',
          'Công nợ không gồm phí vận chuyển; phần đã trả vượt tiền hàng coi như hết nợ.',
          'Số nợ = tiền hàng phải trả (không có phí giao) − tiền đã trả.'],
    'F': ['Tuổi nợ đếm từ ngày đến hạn thanh toán, không đếm từ ngày mua.',
          'Đơn chưa tới hạn trả thì tuổi nợ là 0; quá hạn bao nhiêu ngày thì tuổi nợ bấy nhiêu ngày.',
          'Tuổi của khoản nợ tính theo số ngày quá hạn thanh toán ghi trên đơn.',
          'Shop chỉ tính nợ "già" khi đã qua hạn trả: tuổi nợ = ngày X trừ hạn thanh toán, tối thiểu 0.',
          'Mốc tính tuổi nợ là hạn thanh toán của từng đơn.',
          'Nợ trong hạn có tuổi 0 ngày; đã quá hạn thì tính từ ngày hạn.'],
    'G': ['Hàng bán chạy là hàng mang về nhiều tiền nhất, không phải hàng bán nhiều cái nhất.',
          'Xếp hạng bán chạy theo doanh thu của từng mặt hàng.',
          'Món "hot nhất" là món có tổng thành tiền cao nhất trong kỳ.',
          'Bán nhiều nhất hiểu là bán được nhiều tiền nhất.',
          'Shop đo độ bán chạy bằng tiền bán ra, số lượng chỉ để tham khảo.',
          'Top bán chạy sắp theo doanh thu giảm dần.'],
    'A': ['Voucher và chiết khấu tổng đơn được khấu trừ vào doanh thu của đơn.',
          'Tiền khuyến mãi trên cả đơn trừ thẳng vào doanh thu; doanh thu một đơn là tiền hàng sau khi đã bớt khoản đó.',
          'Doanh thu đơn tính theo số tiền hàng khách thực trả sau giảm giá đơn, chưa cộng phí giao.',
          'Khoản giảm giá đơn (CK đơn, bớt đơn) làm doanh thu giảm đúng bấy nhiêu.',
          'Mọi khoản bớt cho cả đơn đều được trừ ra khỏi doanh thu của đơn đó.',
          'Doanh thu ghi nhận là tiền hàng sau voucher; voucher không phải chi phí riêng.'],
    'B': ['Khách trả lại một phần thì đơn vẫn giữ, chỉ bớt tiền những món bị trả.',
          'Hàng trả lại được trừ khỏi doanh thu theo đúng số lượng trả; phần còn lại của đơn vẫn là doanh thu.',
          'Đơn có hàng hoàn chỉ loại phần hàng hoàn; chỉ đơn hoàn toàn bộ mới không tính.',
          'Trả hàng không làm mất cả đơn: doanh thu đơn là tiền hàng trừ tiền các dòng khách mang trả.',
          'Phần hàng khách trả bị trừ ra theo tỉ lệ số lượng trả của dòng; đơn còn hàng vẫn đếm là một đơn.',
          'Đơn bị trả bớt vẫn là đơn bán, chỉ có tiền và số lượng giảm theo phần trả.'],
    'C': ['Tỉ lệ huỷ lấy mẫu số là các đơn đã hoàn thành.',
          'Cách tính tỉ lệ huỷ: số đơn huỷ chia số đơn giao thành công, nhân 100.',
          'Muốn biết huỷ bao nhiêu phần trăm thì đem số đơn huỷ so với số đơn hoàn tất cùng kỳ.',
          'Phần trăm huỷ đơn tính trên nền đơn đã hoàn thành chứ không trên tổng đơn đặt.',
          'Tỉ lệ huỷ = đơn huỷ / đơn hoàn thành; đơn đang giao và đơn trả không nằm ở mẫu.',
          'Shop đo tỉ lệ huỷ bằng cách chia số đơn huỷ cho số đơn chốt xong.'],
    'D': ['Thu hộ COD xem như khách trả tiền mặt; khách vãng lai không có mã được gộp vào nhóm khách lẻ.',
          'Doanh thu tiền mặt gồm cả các đơn giao COD. Đơn không mã khách tính cho nhóm "lẻ".',
          'COD là tiền mặt do shipper thu nên cộng chung vào tiền mặt; người mua vãng lai thuộc nhóm lẻ.',
          'Khi chia doanh thu theo cách trả tiền, COD nằm trong tiền mặt; khi chia theo nhóm khách, khách vãng lai nằm trong nhóm lẻ.',
          'Đơn thanh toán khi nhận hàng được ghi nhận như tiền mặt, và khách mua không đăng ký được xếp vào nhóm lẻ.',
          'Tiền mặt ở đây hiểu là cả tiền khách đưa tại quầy lẫn tiền COD; nhóm lẻ gồm cả khách vãng lai.'],
}


def cau_cho_shop(luat, sids, seed):
    """Mỗi shop một câu khác nhau (trộn theo seed)."""
    pool = CAU_SHOP[luat][:]
    random.Random('%s-cau-%s' % (seed, luat)).shuffle(pool)
    return {sid: pool[i % len(pool)] for i, sid in enumerate(sids)}


def viet_rulebook(src, dst, luat, shops, cau):
    """shops: [(sid, tên)]; cau: {sid: câu}. Sửa dòng luật ở mục 1, thêm luật riêng từng shop ở mục 6."""
    txt = open(src, encoding='utf-8').read()
    lines = txt.split('\n')
    def thay(dau, moi):
        idx = [i for i, l in enumerate(lines) if l.startswith(dau)]
        assert len(idx) == 1, (dau, idx)
        cu = lines[idx[0]]
        lines[idx[0]] = moi
        return cu
    cu = {'chinh': thay(DONG_CU[luat], DONG_MOI[luat])}
    for dau, moi in DONG_KEM.get(luat, []):
        cu[dau] = thay(dau, moi)
    out = '\n'.join(lines)
    them = ''.join('### %s (%s)\n- %s\n\n' % (ten, sid, cau[sid]) for sid, ten in shops)
    mark = '## 7. Không trả lời được'
    assert mark in out
    out = out.replace(mark, them + mark)
    open(dst, 'w', encoding='utf-8', newline='\n').write(out)
    return cu


# ------------------------------------------------------------------ cấu hình shop theo nhóm
def chinh_shop(luat, S, seed, sid):
    r = random.Random('%s-ld-%s' % (seed, sid))
    if luat == 'A':      # đủ đơn có giảm giá đơn để luật có tác dụng
        S['odisc'] = (r.choice([100000, 150000, 200000]), r.choice([5000, 10000, 15000, 20000]))
    if luat == 'B':      # nhiều đơn trả hơn mặc định (0,5–2 %)
        S['p_return'] = round(r.uniform(0.04, 0.07), 3)
    if luat == 'D':      # nhóm khách chỉ có ở shop có mã khách
        S['cust_code'] = True
    if luat == 'F':      # hạn thanh toán của đơn ghi nợ (cột thêm của sổ, mo_rong_1311.POOL['han'])
        S['han_tt'] = True


def don_B(S):
    """Danh sách đơn engine nhìn thấy theo luật B: đơn trả một phần thành đơn thường với các dòng đã trừ phần trả."""
    from core import money
    out = []
    for o in S['orders']:
        if o['status'] != 'return':
            out.append(o)
            continue
        tra = collections.defaultdict(float)
        for i, q in o['ret_lines']:
            tra[i] += q
        lines = []
        for i, l in enumerate(o['lines']):
            q = tra.get(i, 0)
            if q:
                con = l['qb'] - q
                if con <= 1e-9:
                    continue
                l = dict(l, qb=con, qty=con / l['f'], amt=l['amt'] - money(l['amt'] * q / l['qb']))
            lines.append(l)
        if not any(l['kind'] == 'sale' for l in lines):
            out.append(o)                       # trả hết: giữ trạng thái trả, engine bỏ cả đơn
            continue
        out.append(dict(o, lines=lines, status='done', _tra_mot_phan=True))
    return out


# ------------------------------------------------------------------ bọc engine
class Luat:
    def __init__(self, qgen, luat):
        self.luat, self.qgen, self.E = luat, qgen, qgen.E
        self.bat = True
        E = self.E
        from core import money, r2
        self.money, self.r2 = money, r2
        self.goc = {n: getattr(E, n) for n in ('orders_in', 'rev', 'aov', 'daily', 'ord_ge', 'top_cust', 'crate', 'debt_orders',
                                                'new_debt', 'aged', 'aged_over', 'top_items')}
        g = self.goc
        me = self

        if luat == 'A':
            def gia_tri(o):
                return sum(l['amt'] for l in o['lines']) - (o['odisc'] if me.bat else 0)

            def of(f):
                return {k: v for k, v in f.items() if k not in LINE_F + ('sales_only',)}

            def rev(S, t, p, **f):
                v = g['rev'](S, t, p, **f)
                if not me.bat or any(f.get(k) is not None for k in LINE_F):
                    return v
                return money(v - sum(o['odisc'] for o in E.orders_in(S, t, p, **of(f))))

            def aov(S, t, p, **f):
                os_ = E.orders_in(S, t, p, **f)
                if not os_:
                    raise E.Unans()
                return money(sum(gia_tri(o) for o in os_) / len(os_))

            def daily(S, t, p, **f):
                v = g['daily'](S, t, p, **f)
                if me.bat and not any(f.get(k) is not None for k in LINE_F):
                    for o in E.orders_in(S, t, p, **of(f)):
                        if o['date'] in v:
                            v[o['date']] -= o['odisc']
                return v

            def ord_ge(S, t, p, x):
                return sum(1 for o in E.orders_in(S, t, p) if gia_tri(o) >= x)

            def top_cust(S, t, p, by='ord', k=None):
                if by not in ('rev', 'sop') or not me.bat:
                    return g['top_cust'](S, t, p, by, k)
                os_ = [o for o in E.orders_in(S, t, p) if o['cust']]
                v = collections.defaultdict(float)
                if by == 'rev':
                    for o in os_:
                        v[o['cust']] += gia_tri(o)
                else:
                    n = collections.Counter(o['cust'] for o in os_)
                    tot = collections.defaultdict(float)
                    for o in os_:
                        tot[o['cust']] += gia_tri(o)
                    v = {c: money(tot[c] / n[c]) for c in n if n[c] >= 3}
                if not v:
                    raise E.Unans()
                from core import name_key
                key = (lambda c: (-v[c], c)) if S['cust_code'] else (lambda c: (-v[c], name_key(S['cmap'][c]['name'])))
                r = sorted(v, key=key)
                kk = k or 1
                tie = len(r) > kk and v[r[kk - 1]] == v[r[kk]]
                return (r[0] if k is None else r[:k]), tie

            for n, fn in (('rev', rev), ('aov', aov), ('daily', daily), ('ord_ge', ord_ge), ('top_cust', top_cust)):
                setattr(E, n, fn)

        if luat == 'C':
            def crate(S, t, p):
                if not me.bat:
                    return g['crate'](S, t, p)
                allo = E.orders_in(S, t, p, statuses=('done', 'ship', 'cancel', 'return'))
                xong = sum(o['status'] == 'done' for o in allo)
                if not xong:
                    raise E.Unans()
                return r2(sum(o['status'] == 'cancel' for o in allo) / xong * 100)
            E.crate = crate

        if luat == 'E':
            def debt_orders(S, X):
                if not me.bat:
                    return g['debt_orders'](S, X)
                out = []
                for o in S['orders']:
                    if o['date'] > X or o['status'] == 'cancel':
                        continue
                    if not S.get('deposit') and o['pay'] != 'debt':
                        continue
                    rem = (o['due'] - o['ship']) - sum(a for d_, a, k in o['payments'] if d_ <= X)
                    if rem > 0.5:
                        out.append((o, rem))
                return out

            def new_debt(S, t, p, cust=None):
                if not me.bat:
                    return g['new_debt'](S, t, p, cust)
                a, b = E.clamp(S, t, p)
                s_ = 0
                for o in S['orders']:
                    if o['status'] == 'cancel' or o['pay'] != 'debt' or not (a <= o['date'] <= b):
                        continue
                    if cust and o['cust'] != cust:
                        continue
                    s_ += max(0, o['due'] - o['ship'] - sum(x for d_, x, k in o['payments'] if d_ == o['date']))
                return money(s_)
            E.debt_orders, E.new_debt = debt_orders, new_debt

        if luat == 'F':
            def tuoi(o, X):
                return max(0, (X - o['han']).days) if o.get('han') else (X - o['date']).days

            def aged(S, X):
                if not me.bat:
                    return g['aged'](S, X)
                b = [0, 0, 0]
                for o, r in E.debt_orders(S, X):
                    a = tuoi(o, X)
                    b[0 if a <= 7 else (1 if a <= 15 else 2)] += r
                return [money(x) for x in b]

            def aged_over(S, X, n):
                if not me.bat:
                    return g['aged_over'](S, X, n)
                return money(sum(r for o, r in E.debt_orders(S, X) if tuoi(o, X) > n))
            E.aged, E.aged_over = aged, aged_over

        if luat == 'G':
            def top_items(S, t, p, k=None, by='qty', **f):
                return g['top_items'](S, t, p, k, 'rev' if (me.bat and by == 'qty') else by, **f)
            E.top_items = top_items

        if luat == 'D':
            def orders_in(S, t, p, statuses=E.VALID, **f):
                if not me.bat:
                    return g['orders_in'](S, t, p, statuses=statuses, **f)
                tien_mat = f.get('pay') == 'cash'
                le = f.get('cgroup') == 'lẻ'
                if tien_mat:
                    f = {k: v for k, v in f.items() if k != 'pay'}
                if le:
                    f = {k: v for k, v in f.items() if k != 'cgroup'}
                out = g['orders_in'](S, t, p, statuses=statuses, **f)
                if tien_mat:
                    out = [o for o in out if o['pay'] in ('cash', 'cod')]
                if le:
                    out = [o for o in out if not o['cust'] or S['cmap'][o['cust']]['group'] == 'lẻ']
                return out
            E.orders_in = orders_in

    def sau_sim(self, S, seed, sid):
        """F: hạn thanh toán của đơn ghi nợ theo nhóm khách (sỉ 30, thân thiết 15, lẻ 7 ngày)."""
        if self.luat == 'F':
            han = {'sỉ': 30, 'thân thiết': 15, 'lẻ': 7}
            for o in S['orders']:
                if o['pay'] == 'debt' and o['cust']:
                    o['han'] = o['date'] + D.timedelta(days=han[S['cmap'][o['cust']]['group']])

    def chuan_bi(self, S):
        """Sau khi đã ghi file: B cần danh sách đơn theo luật mới (file vẫn ghi đơn trả như cũ)."""
        if self.luat == 'B':
            S['_don_goc'] = S['orders']
            S['_don_moi'] = don_B(S)
            S['orders'] = S['_don_moi']

    def dat(self, S, bat):
        self.bat = bat
        if self.luat == 'B':
            S['orders'] = S['_don_moi'] if bat else S['_don_goc']

    # -------------------------------------------------------------- họ câu: dồn vào các họ chịu luật đổi
    def ho_cau(self, fams):
        qgen, E = self.qgen, self.E
        from core import month

        def F_cancel(R, S, t):
            x = qgen.pick_month(R, S, t)
            w = qgen.mphrase(R, *x, t)
            if R.random() < (0.15 if self.luat == 'C' else 0.25):
                return R.choice(['%s có mấy đơn bị huỷ?', 'Số đơn huỷ %s?']) % w, 'number', E.cancels(S, t, month(*x)), []
            return R.choice(['Tỉ lệ huỷ đơn %s là bao nhiêu %%?', '%s đơn huỷ chiếm mấy phần trăm?',
                             'Tỉ lệ đơn bị huỷ %s là bao nhiêu %%?']) % w, 'percent', E.crate(S, t, month(*x)), []

        def F_pay(R, S, t):
            if not S.get('pays'):
                return None
            x = qgen.pick_month(R, S, t); p = month(*x); w = qgen.mphrase(R, *x, t)
            ps = [c for c, _ in S['pays']]
            a = 'cash' if 'cash' in ps and R.random() < (0.65 if self.luat == 'D' else 0.5) else R.choice(ps)
            return R.choice(['Doanh thu các đơn %s %s là bao nhiêu?' % (qgen.PAY_TXT[a], w),
                             '%s đơn %s mang về bao nhiêu tiền?' % (w, qgen.PAY_TXT[a])]), 'number', E.rev(S, t, p, pay=a), []

        def F_cgroup(R, S, t):
            if not S['cust_code']:
                return None
            g = 'lẻ' if R.random() < (0.65 if self.luat == 'D' else 0.5) else R.choice(['thân thiết', 'sỉ'])
            x = qgen.pick_month(R, S, t); p = month(*x); w = qgen.mphrase(R, *x, t)
            if R.random() < 0.5:
                return 'Khách nhóm %s %s mua tổng cộng bao nhiêu tiền?' % (g, w), 'number', E.rev(S, t, p, cgroup=g), []
            return 'Khách nhóm %s đóng góp bao nhiêu %% doanh thu %s?' % (g, w), 'percent', \
                self.r2(E.rev(S, t, p, cgroup=g) / E.rev(S, t, p) * 100), []

        thay = {'cancel': F_cancel, 'pay': F_pay, 'cgroup': F_cgroup}
        # trọng số theo nhóm: dồn vào họ câu chịu luật đổi của nhóm, giữ vài họ không đổi làm câu đối chứng
        ts = {'A': {'rev_month': 6, 'rev_rel': 5, 'aov': 3, 'pay': 4, 'cgroup': 3, 'chan': 2, 'mom': 2, 'three': 1.5, 'nord': 3,
                    'cancel': 2, 'days': 1},
              'B': {'rev_month': 6, 'rev_rel': 5, 'nord': 5, 'aov': 2, 'pay': 3, 'cgroup': 3, 'chan': 1.5, 'mom': 2, 'three': 1.5,
                    'cancel': 2, 'days': 1},
              'C': {'cancel': 12, 'rev_month': 3, 'nord': 3, 'rev_rel': 2, 'pay': 2, 'cgroup': 2},
              'D': {'pay': 10, 'cgroup': 10, 'rev_month': 3, 'rev_rel': 2, 'nord': 2, 'cancel': 2},
              'E': {'debt': 14, 'rev_month': 2, 'nord': 2, 'pay': 2, 'aov': 1},
              'F': {'debt': 14, 'rev_month': 2, 'nord': 2, 'pay': 2, 'aov': 1},
              'G': {'top_item': 10, 'top_rev_group': 5, 'tet': 2, 'qty_item': 3, 'rev_item': 2, 'rev_month': 2, 'nord': 1}}[self.luat]
        bo = {'stock'} if self.luat == 'B' else set()     # tồn kho theo ngày trả: luật B không đổi, để khỏi lẫn
        out = []
        for f, _ in fams:
            ho = f.__name__[2:]
            if ho in bo:
                continue
            out.append((thay.get(ho, f), ts.get(ho, 0.3)))
        return out


# ------------------------------------------------------------------ kế hoạch theo luật mới
DON_LOC = {'kenh', 'thanh_toan', 'nhan_vien', 'khach'}      # cột lọc bảng `don` có
HANG_LOC = {'hang', 'nhom_hang', 'hoat_chat', 'don_vi_co_ban', 'ten_hang', 'la_mat_hang'}


class KhongViet(Exception):
    pass


def _A(p):
    if not isinstance(p, dict):
        return p
    if 'ghep' in p:
        return {**p, 'cac': [_A(x) for x in p['cac']]}
    loc = p.get('loc') or []
    cots = {f.get('cot') for f in loc}
    if p.get('nguon') == 'dong_ban' and p.get('cot') == 'tien':
        if cots & HANG_LOC or p.get('nhom') in ('hang', 'nhom_hang', 'ten_hang'):
            return p                               # doanh thu theo mặt hàng, nhóm hàng: luật A không đổi
        if p.get('nhom') or p.get('phep') != 'tong':
            raise KhongViet('doanh thu theo ngày / theo khách sau giảm giá đơn')
        if cots - DON_LOC:
            raise KhongViet('bảng đơn không có cột lọc ' + ', '.join(sorted(cots - DON_LOC)))
        tru = {'nguon': 'don', 'phep': 'tong', 'cot': 'giam_don', 'ky': p['ky']}
        if loc:
            tru['loc'] = loc
        return {'ghep': 'hieu', 'cac': [p, tru]}
    if p.get('nguon') == 'don' and (p.get('cot') == 'doanh_thu' or 'doanh_thu' in cots):
        raise KhongViet('doanh thu đơn sau giảm giá đơn')
    return p


def _B(p):
    if not isinstance(p, dict):
        return p
    if 'ghep' in p:
        return {**p, 'cac': [_B(x) for x in p['cac']]}
    if p.get('nguon') in ('dong_ban', 'don') and not p.get('moi_trang_thai'):
        raise KhongViet('trả một phần: bảng chuẩn bỏ cả đơn trả, chưa có cách trừ riêng dòng trả')
    return p


def _C(p):
    if not isinstance(p, dict):
        return p
    if 'ghep' in p:
        cac = [_C(x) for x in p['cac']]
        if p['ghep'] == 'ti_le' and len(cac) == 2:
            m = cac[1]
            if isinstance(m, dict) and m.get('nguon') == 'don' and m.get('phep') == 'dem' and m.get('moi_trang_thai') \
                    and not m.get('loc'):
                cac[1] = {**m, 'loc': [{'cot': 'trang_thai', 'gt': 'hoan_thanh'}]}
        return {**p, 'cac': cac}
    return p


def _D(p):
    if not isinstance(p, dict):
        return p
    if 'ghep' in p:
        return {**p, 'cac': [_D(x) for x in p['cac']]}
    loc = p.get('loc') or []
    moi = []
    le = False
    for f in loc:
        if f.get('cot') == 'thanh_toan' and f.get('gt') == 'tien_mat':
            moi.append({'cot': 'thanh_toan', 'op': 'in', 'gt': ['tien_mat', 'cod']})
        elif f.get('cot') == 'nhom_khach' and f.get('gt') == 'lẻ':
            le = True
        else:
            moi.append(f)
    if not le:
        return {**p, 'loc': moi} if loc else p
    if p.get('nhom'):
        raise KhongViet('nhóm lẻ kèm nhóm theo cột khác')
    goc = {**p, 'loc': moi} if moi else {k: v for k, v in p.items() if k != 'loc'}
    def voi(g):
        return {**p, 'loc': moi + [{'cot': 'nhom_khach', 'op': '=', 'gt': g}]}
    # nhóm lẻ + khách vãng lai = tất cả − thân thiết − sỉ (khách vãng lai có nhom_khach rỗng)
    return {'ghep': 'hieu', 'cac': [{'ghep': 'hieu', 'cac': [goc, voi('thân thiết')]}, voi('sỉ')]}


def _E(p):
    if not isinstance(p, dict):
        return p
    if 'ghep' in p:
        return {**p, 'cac': [_E(x) for x in p['cac']]}
    if p.get('nguon') == 'cong_no' or (p.get('nguon') == 'dong_tien_no' and p.get('cot') == 'no_them'):
        raise KhongViet('nợ không gồm phí giao: bảng công nợ chưa tách phí giao')
    return p


def _F(p):
    if not isinstance(p, dict):
        return p
    if 'ghep' in p:
        return {**p, 'cac': [_F(x) for x in p['cac']]}
    if p.get('nguon') == 'cong_no' and any(f.get('cot') == 'tuoi_no' for f in p.get('loc') or []):
        raise KhongViet('tuổi nợ tính từ hạn thanh toán: bảng công nợ chưa có hạn')
    return p


def _G(p):
    if not isinstance(p, dict):
        return p
    if 'ghep' in p:
        return {**p, 'cac': [_G(x) for x in p['cac']]}
    if p.get('nguon') == 'dong_ban' and p.get('nhom') == 'hang' and p.get('cot') == 'sl_co_ban' and p.get('phep') == 'tong' and p.get('xep'):
        return {**p, 'cot': 'tien'}
    return p


def doi_ke_hoach(luat, plan):
    """-> (kế hoạch theo luật mới hoặc None, ghi chú)."""
    if plan is None:
        return None, None
    try:
        return {'A': _A, 'B': _B, 'C': _C, 'D': _D, 'E': _E, 'F': _F, 'G': _G}[luat](copy.deepcopy(plan)), None
    except KhongViet as e:
        return None, 'luật %s: ngôn ngữ kế hoạch chưa viết được (%s)' % (luat, e)
