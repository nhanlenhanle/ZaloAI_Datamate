"""Đọc ngược file BẨN bằng bộ đọc độc lập, so với dữ liệu sạch gốc.
Mục đích: chứng minh dữ liệu phát hành đủ thông tin và không mơ hồ để tính đúng đáp án."""
import os, sys, re, glob, json, pickle, sqlite3, collections, math, datetime as D, unicodedata
import pandas as pd, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core import OUT, HERE

def isna(v): return v is None or (isinstance(v, float) and math.isnan(v)) or (isinstance(v, str) and v.strip() == '') or v is pd.NaT
def num(v):
    if isna(v): return 0.0
    if isinstance(v, (int, float, np.integer, np.floating)): return float(v)
    s = str(v).strip().lower().replace('đ', '').strip()
    neg = s.startswith('-'); s = s.lstrip('-')
    m = re.fullmatch(r'(\d+(?:,\d+)?)tr', s)
    if m: r = float(m[1].replace(',', '.')) * 1e6
    elif re.fullmatch(r'\d+k', s): r = float(s[:-1]) * 1000
    elif re.fullmatch(r'\d{1,3}([., ]\d{3})+', s): r = float(re.sub(r'[., ]', '', s))
    else: r = float(s.replace(',', '.'))
    return -r if neg else r
EP = D.date(1899, 12, 30)
def dt(v, year=None):
    if isinstance(v, (D.datetime, pd.Timestamp)): return v.date() if hasattr(v, 'date') else v
    if isinstance(v, (int, float, np.integer, np.floating)): return EP + D.timedelta(days=int(v))
    s = str(v).strip()
    m = re.match(r'(\d{4})-(\d\d)-(\d\d)', s)
    if m: return D.date(int(m[1]), int(m[2]), int(m[3]))
    m = re.match(r'(\d{1,2}) thg (\d{1,2}) (\d{4})', s)
    if m: return D.date(int(m[3]), int(m[2]), int(m[1]))
    m = re.match(r'(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})', s)
    if m:
        y = int(m[3]); y += 2000 if y < 100 else 0; return D.date(y, int(m[2]), int(m[1]))
    m = re.match(r'(\d{1,2})/(\d{1,2})$', s)
    if m: return D.date(year, int(m[2]), int(m[1]))
    raise ValueError(s)
def nk(s): return re.sub(r'\s+', ' ', str(s).strip().lower())

ST = [('cancel', r'huỷ|hủy|cancel'), ('return', r'trả|hoàn tiền|return'), ('ship', r'đang giao|đang chở|shipper|đang gửi|chờ giao|đang')]
def st(s):
    if isna(s): return 'done'
    k = str(s).lower()
    for a, p in ST:
        if re.search(p, k): return a
    return 'done'

def truth_orders(S):
    return {o['id']: (o['date'], o['status'], sum(l['amt'] for l in o['lines'])) for o in S['orders']}

def cmp(name, got, S, extra=''):
    tr = truth_orders(S); bad = 0; ex = []
    for k, v in tr.items():
        g = got.get(k)
        if g is None or g[0] != v[0] or g[1] != v[1] or abs(g[2] - v[2]) > 0.5:
            bad += 1
            if len(ex) < 3: ex.append((k, v, g))
    extra_keys = set(got) - set(tr)
    print('%-8s đơn %6d | lệch %d | thừa %d %s %s' % (name, len(tr), bad, len(extra_keys), ex, extra))
    return bad == 0 and not extra_keys

def rd_xl(p, sheet=None, header=0):
    return pd.read_excel(p, sheet_name=sheet, header=header, dtype=object)

def v201(S, d):
    got = {}
    for f in sorted(glob.glob(d + '/SoBanHang_*.xlsx')):
        y = int(re.search(r'(\d{4})', os.path.basename(f))[1])
        for nm, df in rd_xl(f, None, 2).items():
            cur = None
            for r in df.itertuples(index=False):
                if str(r[3]).strip() == 'CỘNG THÁNG': continue
                if not isna(r[2]):
                    cur = str(r[2]).zfill(5) if not isinstance(r[2], str) else r[2]
                    seen = set(); got[cur] = [dt(r[0], y), st(r[9]), 0.0]
                key = tuple(map(str, r[4:9]))
                if key in seen and isna(r[2]): continue
                seen.add(key); got[cur][2] += num(r[8])
    return cmp('201', {k: tuple(v) for k, v in got.items()}, S)

def v202(S, d):
    o = pd.read_csv(d + '/don_hang.csv', dtype=str, keep_default_na=False)
    o = o[o['Mã đơn'].str.match(r'^CA\d+$')]
    det = pd.read_csv(d + '/chi_tiet_don.csv', dtype=str, keep_default_na=False)
    det['Mã đơn'] = det['Mã đơn'].str.strip(); det = det.drop_duplicates()
    det2 = det.copy(); det2['Mã đơn'] = det2['Mã đơn'].str.strip(); det2['Mã SP'] = det2['Mã SP'].str.strip(); det2 = det2.drop_duplicates()
    s = det2.groupby('Mã đơn')['Thành tiền'].apply(lambda x: sum(num(v) for v in x))
    got = {r['Mã đơn']: (dt(r['Thời gian']), st(r['Trạng thái']), s.get(r['Mã đơn'], 0)) for _, r in o.iterrows()}
    ok = cmp('202', got, S)
    # công nợ cuối kỳ từ thanh_toan
    p = pd.read_csv(d + '/thanh_toan.csv', dtype=str, keep_default_na=False); p['Mã đơn'] = p['Mã đơn'].str.strip()
    paid = p.groupby('Mã đơn')['Số tiền'].apply(lambda x: sum(num(v) for v in x))
    calc = sum(max(0, num(r['Tổng phải trả']) - paid.get(r['Mã đơn'], 0)) for _, r in o.iterrows()
               if r['Thanh toán'] in ('Ghi nợ', 'Nợ') and st(r['Trạng thái']) != 'cancel')
    import engine as E
    tru = E.debt_total(S, S['end'] + D.timedelta(days=400))
    print('         nợ (mọi khoản thu) đọc lại %d / gốc %d' % (calc, tru))
    return ok and abs(calc - tru) < 1

def v205(S, d):
    df = rd_xl(d + '/DonHang_ChiTiet.xlsx', 'Data', 3)
    df = df[df['Mã đơn'].astype(str).str.startswith('3D-')].drop_duplicates()
    got = {}
    for k, g in df.groupby('Mã đơn'):
        r = g.iloc[0]; got[k] = (dt(r['Ngày đặt']), st(r['Trạng thái']), sum(num(x) for x in g['Thành tiền']))
    return cmp('205', got, S)

def v206(S, d):
    got = {}
    for f in sorted(glob.glob(d + '/So_ban_hang_*.xlsx')):
        df = rd_xl(f, 'Sheet1'); df = df.drop_duplicates()
        for k, g in df.groupby('Số phiếu'):
            r = g.iloc[0]; got[k] = (dt(r['Ngày']), st(r['Tình trạng']), sum(num(x) for x in g['Thành tiền']))
    ok = cmp('206', got, S)
    # kiểm tra quy đổi theo bậc ra đúng hệ số
    dm = rd_xl(d + '/DanhMuc.xlsx', 'DanhMuc'); bad = 0
    for _, r in dm.iterrows():
        f = {r['ĐV nhỏ nhất']: 1}
        steps = [re.match(r'1 (\S+) = (\d+) (\S+)', x.strip()).groups() for x in str(r['Quy đổi']).split(';') if x.strip() and x != 'nan']
        for big, n, small in reversed(steps): f[big] = int(n) * f[small]
        it = S['imap'][r['Mã hàng']]
        if any(f.get(u) != v for u, v in it['units'].items()): bad += 1
    print('         quy đổi theo bậc lệch %d mặt hàng' % bad)
    return ok and bad == 0

def v207(S, d):
    df = pd.read_csv(d + '/ban_hang.csv', dtype=str, keep_default_na=False).drop_duplicates()
    got = {}
    for k, g in df.groupby('ma_hd'):
        r = g.iloc[0]; got[k] = (dt(r['ngay']), st(r['trang_thai']), sum(num(x) for x in g['thanh_tien']))
    return cmp('207', got, S)

def v208(S, d):
    got = {}
    for f in glob.glob(d + '/BanHang_T*.xlsx'):
        df = rd_xl(f, 'DonHang')
        for k, g in df.groupby('Mã đơn'):
            r = g.iloc[0]; got[k] = (dt(r['Ngày']), st(r['Trạng thái']), sum(num(x) for x in g['Thành tiền']))
    ok = cmp('208', got, S)
    # topping tách được: tổng phần topping
    tp = 0
    for f in glob.glob(d + '/BanHang_T*.xlsx'):
        df = rd_xl(f, 'DonHang')
        for m_, sl in zip(df['Món'].astype(str), df['SL']):
            parts = m_.split(' + ')
            if m_.startswith('Topping'): tp += num(sl)
            for p_ in parts[1:]:
                mm = re.match(r'(?:(\d+) )?(.*) \((.*)\)$', p_); tp += int(mm[1] or 1)
    tru = sum(l['qty'] for o in S['orders'] for l in o['lines'] if l['kind'] == 'topping')
    print('         phần topping đọc lại %d / gốc %d' % (tp, tru))
    return ok and tp == tru

def v209(S, d):
    h = rd_xl(d + '/HoaDon.xlsx', 'HoaDon'); c = rd_xl(d + '/HoaDonChiTiet.xlsx', 'ChiTiet')
    s = c.groupby('Mã HĐ')['Thành tiền'].sum()
    got = {r['Mã HĐ']: (dt(r['Ngày giờ']), st(r['Trạng thái']), s.get(r['Mã HĐ'], 0)) for _, r in h.iterrows()}
    ok = cmp('209', got, S)
    x = rd_xl(d + '/XuatTheoLo.xlsx', 'XuatLo'); n = rd_xl(d + '/NhapHangTheoLo.xlsx', 'NhapLo')
    rem = collections.defaultdict(float)
    for _, r in n.iterrows():
        if r['Trạng thái'] != 'Huỷ': rem[r['Số lô']] += num(r['SL nhập']) * S['imap'][r['Mã SP']]['units'][r['ĐV nhập']]
    stt = {r['Mã HĐ']: st(r['Trạng thái']) for _, r in h.iterrows()}
    for _, r in x.iterrows():
        if stt[r['Mã HĐ']] != 'cancel': rem[r['Số lô']] += -num(r['SL xuất (ĐVCB)']) + num(r['SL trả (ĐVCB)'])
    import engine as E
    tru = E.lot_remaining(S, S['end'] + D.timedelta(days=400))
    bad = sum(1 for k in tru if abs(tru[k] - rem.get(k, 0)) > 1e-6)
    print('         tồn theo lô lệch %d / %d lô' % (bad, len(tru)))
    return ok and bad == 0

def v203(S, d):
    db = sqlite3.connect(d + '/pixel.sqlite')
    ph = pd.read_sql('select * from phien_choi', db)
    a = int(ph[ph.tinh_trang == 'xong'].tien_gio.sum()); b = sum(s['amt'] for s in S['sessions'])
    fd = pd.read_sql("select c.thanh_tien from chi_tiet_do_an c join don_do_an d on c.ma_don=d.ma_don where d.tinh_trang!='huỷ'", db).thanh_tien.sum()
    fb = sum(l['amt'] for f in S['food'] if f['status'] != 'huỷ' for l in f['lines'])
    print('203      tiền giờ %d/%d | đồ ăn %d/%d | phiên %d/%d' % (a, b, fd, fb, len(ph), len(S['sessions'])))
    return a == b and fd == fb and len(ph) == len(S['sessions'])

def v204(S, d):
    tot = 0; kg = 0; n = 0
    for nm, df in rd_xl(d + '/SoGiat.xlsx', None).items():
        for _, r in df.iterrows():
            if 'huỷ' in str(r['Ghi chú']) or 'hủy' in str(r['Ghi chú']): continue
            n += 1; tot += num(r['Thành tiền'])
            if str(r['Dịch vụ']).lower() == 'giặt sấy':
                kg += float(re.sub(r'[^\d,.]', '', str(r['Số lượng'])).replace(',', '.'))
    tk = [t for t in S['tickets'] if t['status'] != 'huỷ']
    tkg = sum(t['q'] for t in tk if t['svc'] == 'giặt sấy')
    print('204      phiếu %d/%d | tiền %d/%d | kg %.1f/%.1f' % (n, len(tk), tot, sum(t['amt'] for t in tk), kg, tkg))
    return n == len(tk) and tot == sum(t['amt'] for t in tk) and abs(kg - tkg) < 1e-6

def v210(S, d):
    df = pd.read_csv(d + '/phien_sac.csv', dtype=str, keep_default_na=False)
    ok_ = df[df.trang_thai == 'hoàn tất']
    kwh = sum(float(x.replace(',', '.')) for x in ok_.kwh); amt = ok_.thanh_tien.astype(int).sum()
    norm = lambda p: re.sub(r'[\s.\-]', '', p).upper()
    nplate = df.bien_so.map(norm).nunique(); tp = len({s['plate'] for s in S['sessions']})
    tk = sum(s['kwh'] for s in S['sessions'] if s['status'] == 'hoàn tất'); ta = sum(s['amt'] for s in S['sessions'])
    print('210      kWh %.3f/%.3f | tiền %d/%d | số xe %d/%d' % (kwh, tk, amt, ta, nplate, tp))
    return abs(kwh - tk) < 1e-6 and amt == ta and nplate == tp

def main():
    shops = pickle.load(open(os.path.join(HERE, '_truth.pkl'), 'rb'))
    allok = True
    for S in shops:
        f = globals().get('v' + S['id'][-3:])
        ok = f(S, os.path.join(OUT, 'data', S['id']))
        allok &= bool(ok)
    # định dạng file đáp án
    Q = [json.loads(l) for l in open(os.path.join(OUT, 'questions.jsonl'), encoding='utf8')]
    A = [json.loads(l) for l in open(os.path.join(OUT, 'answers.jsonl'), encoding='utf8')]
    assert [q['id'] for q in Q] == [a['id'] for a in A] and len({q['id'] for q in Q}) == len(Q)
    for a in A:
        t, v = a['type'], a['answer']
        if t in ('number', 'percent'): assert isinstance(v, (int, float)) and v == v, a
        if t == 'date': assert re.fullmatch(r'\d{4}-\d\d(-\d\d)?', v), a
        if t == 'list': assert isinstance(v, list) and v, a
        if t == 'string': assert isinstance(v, str) and v, a
        if t == 'boolean': assert isinstance(v, bool), a
        if t == 'table': assert v['rows'], a
        if t == 'unanswerable': assert v is None
    print('FORMAT OK', len(A), 'câu'); print('TẤT CẢ KHỚP' if allok else 'CÓ LỆCH')

if __name__ == '__main__':
    main()
