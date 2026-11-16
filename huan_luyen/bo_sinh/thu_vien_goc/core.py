"""Tiện ích chung: lịch, làm tròn, kỳ thời gian, tên người, làm bẩn chữ."""
import random, datetime as D, csv, re, unicodedata, math, os
from decimal import Decimal, ROUND_HALF_UP

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), 'private_zalo_ai_hard')
TRAIN_CAL = os.path.join(os.path.dirname(HERE), 'train', 'train', 'calendar.csv')
SEED = 20261102

def money(x):
    return int(Decimal(repr(round(float(x), 6))).quantize(Decimal(1), ROUND_HALF_UP))

def r2(x):
    return float(Decimal(repr(round(float(x), 8))).quantize(Decimal('0.01'), ROUND_HALF_UP))

def num_out(x):
    """số đếm: int nếu nguyên, ngược lại 2 chữ số thập phân"""
    x = float(x)
    return int(round(x)) if abs(x - round(x)) < 1e-9 else r2(x)

def daterange(a, b):
    d = a
    while d <= b:
        yield d
        d += D.timedelta(days=1)

# ---------------- lịch
EXTRA_HOL = {(2, 14): 'Valentine', (3, 8): 'Quốc tế Phụ nữ', (10, 20): 'Phụ nữ Việt Nam',
             (11, 20): 'Nhà giáo Việt Nam', (12, 24): 'Giáng sinh'}
EXTRA_LUNAR = {(1, 15): 'Rằm tháng Giêng', (7, 15): 'Vu Lan'}

def load_calendar():
    rows = list(csv.DictReader(open(TRAIN_CAL, encoding='utf-8-sig')))
    cal = {}
    for r in rows:
        d = D.date.fromisoformat(r['date'])
        h = [r['holiday']] if r['holiday'] else []
        if (d.month, d.day) in EXTRA_HOL: h.append(EXTRA_HOL[(d.month, d.day)])
        if r['lunar_leap'] == 'false' and (int(r['lunar_month']), int(r['lunar_day'])) in EXTRA_LUNAR:
            h.append(EXTRA_LUNAR[(int(r['lunar_month']), int(r['lunar_day']))])
        r = dict(r); r['holiday'] = '; '.join(h)
        cal[d] = r
    return rows, cal

CAL_ROWS, CAL = load_calendar()

def lunar_to_solar(y, m, d):
    for k, v in CAL.items():
        if v['lunar_leap'] == 'false' and int(v['lunar_year']) == y and int(v['lunar_month']) == m and int(v['lunar_day']) == d:
            return k
    return None

def tet(y):
    return (lunar_to_solar(y - 1, 12, 23), lunar_to_solar(y, 1, 10))

def holiday_dates(name):
    return sorted(d for d, v in CAL.items() if name in v['holiday'].split('; '))

# ---------------- kỳ thời gian: trả (a, b) ngày, gồm 2 đầu
def month(y, m):
    a = D.date(y, m, 1)
    b = (D.date(y + (m == 12), m % 12 + 1, 1) - D.timedelta(days=1))
    return a, b

def quarter(y, q):
    return month(y, 3 * q - 2)[0], month(y, 3 * q)[1]

def this_month(t): return t.replace(day=1), t
def last_week(t):
    a = t - D.timedelta(days=t.weekday() + 7); return a, a + D.timedelta(days=6)
def this_week(t): return t - D.timedelta(days=t.weekday()), t
def last_n(t, n): return t - D.timedelta(days=n - 1), t
def ytd(t): return D.date(t.year, 1, 1), t
def prev_month(y, m): return (y - 1, 12) if m == 1 else (y, m - 1)

def same_days_prev_month(t):
    a = t.replace(day=1)
    pe = a - D.timedelta(days=1)
    return pe.replace(day=1), pe.replace(day=min(t.day, pe.day))

def month_no_year(t, m):
    y = t.year if D.date(t.year, m, 1) <= t else t.year - 1
    return y, m

# ---------------- tên người
HO = ['Nguyễn', 'Trần', 'Lê', 'Phạm', 'Hoàng', 'Huỳnh', 'Phan', 'Vũ', 'Võ', 'Đặng', 'Bùi', 'Đỗ', 'Hồ', 'Ngô', 'Dương', 'Lý',
      'Đinh', 'Trịnh', 'Mai', 'Tô', 'Lương', 'Hà', 'Kiều', 'Thái', 'Quách', 'Doãn', 'La', 'Lục', 'Âu', 'Mạc']
DEM = ['Văn', 'Thị', 'Minh', 'Ngọc', 'Thu', 'Hữu', 'Đức', 'Thanh', 'Bảo', 'Gia', 'Khánh', 'Quốc', 'Kim', 'Xuân', 'Hoài', 'Diệu']
TEN = ['An', 'Bình', 'Châu', 'Dung', 'Giang', 'Hà', 'Hải', 'Hạnh', 'Hiếu', 'Hoa', 'Hùng', 'Huy', 'Khoa', 'Lan', 'Linh', 'Long',
       'Mai', 'Nam', 'Ngân', 'Nhung', 'Phong', 'Phúc', 'Quân', 'Sơn', 'Tâm', 'Thảo', 'Thắng', 'Trang', 'Trung', 'Tú', 'Vy', 'Yến',
       'Lộc', 'Uyên', 'Đào', 'Tín', 'Kha', 'Nghi', 'Thư', 'Thu']

def strip_acc(s):
    s = unicodedata.normalize('NFD', s)
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    return s.replace('đ', 'd').replace('Đ', 'D')

def name_key(s):
    return re.sub(r'\s+', ' ', s.strip().lower())

def make_names(R, n, used=None):
    used = used if used is not None else set()
    out = []
    while len(out) < n:
        s = '%s %s %s' % (R.choice(HO), R.choice(DEM), R.choice(TEN))
        if name_key(s) in used or name_key(strip_acc(s)) in {name_key(strip_acc(u)) for u in out}:
            continue
        used.add(name_key(s)); out.append(s)
    return out

def phone(R):
    return '0' + R.choice(['90', '91', '93', '97', '98', '32', '35', '38', '70', '79', '86']) + ''.join(R.choice('0123456789') for _ in range(7))

# ---------------- định dạng tiền/ngày bẩn (luôn đọc lại được đúng giá trị)
def fmt_money(R, v, styles):
    v = int(v)
    st = R.choice(styles)
    neg = '-' if v < 0 else ''
    a = abs(v)
    if st == 'plain': return v
    if st == 'dot': return neg + '{:,}'.format(a).replace(',', '.')
    if st == 'dotd': return neg + '{:,}'.format(a).replace(',', '.') + 'đ'
    if st == 'comma': return neg + '{:,}'.format(a)
    if st == 'k' and a % 1000 == 0 and a > 0: return neg + '%dk' % (a // 1000)
    if st == 'tr' and a % 10000 == 0 and a >= 1000000:
        t = a / 1e6; s = ('%.2f' % t).rstrip('0').rstrip('.').replace('.', ',')
        return neg + s + 'tr'
    if st == 'space' and a >= 1000: return neg + '{:,}'.format(a).replace(',', ' ')
    return neg + '{:,}'.format(a).replace(',', '.')

def fmt_date(R, d, styles, t=None):
    st = R.choice(styles)
    if st == 'obj':
        return D.datetime(d.year, d.month, d.day, *(t or (0, 0)))
    if st == 'dmy': s = '%02d/%02d/%d' % (d.day, d.month, d.year)
    elif st == 'dmy1': s = '%d/%d/%d' % (d.day, d.month, d.year)
    elif st == 'dmy2': s = '%02d-%02d-%02d' % (d.day, d.month, d.year % 100)
    elif st == 'iso': s = d.isoformat()
    elif st == 'thg': s = '%d thg %d %d' % (d.day, d.month, d.year)
    elif st == 'serial':
        n = (d - D.date(1899, 12, 30)).days
        return n if t is None else round(n + (t[0] * 60 + t[1]) / 1440.0, 6)
    else: raise ValueError(st)
    if t is not None: s += ' %02d:%02d' % t
    return s

# ---------------- câu hỏi văn nói
TEEN = [('bao nhiêu', ['bnhiu', 'bn', 'bao nhiu', 'nhiêu', 'bao nhiêu']), ('doanh thu', ['dthu', 'doanh thu', 'dt']),
        ('được', ['đc', 'dc', 'được']), ('không', ['ko', 'hông', 'k', 'không']), ('tháng', ['th', 'thg', 'tháng']),
        ('vậy', ['z', 'zậy', 'dzậy', 'rứa', 'vậy']), ('nào', ['mô', 'nào', 'nàoo']), ('hôm nay', ['hnay', 'bữa ni', 'hôm nay']),
        ('hôm qua', ['hqua', 'bữa qua', 'hôm qua']), ('khách', ['khach', 'kh', 'khách']), ('mấy', ['mí', 'mấy']),
        ('đơn hàng', ['đh', 'đơn', 'đơn hàng']), ('trước', ['trc', 'trước']), ('nhiều', ['nhìu', 'nhiều']), ('với', ['vs', 'với'])]

def noisy(R, s, level=0.5):
    if R.random() < level:
        for a, bs in TEEN:
            if a in s and R.random() < 0.6:
                s = s.replace(a, R.choice(bs), 1)
    if R.random() < level * 0.35:
        s = strip_acc(s)
    if R.random() < level * 0.4:
        w = s.split(' ')
        i = R.randrange(len(w))
        if len(w[i]) > 3 and w[i].isalpha():
            j = R.randrange(len(w[i]) - 1)
            w[i] = w[i][:j] + w[i][j + 1] + w[i][j] + w[i][j + 2:]
        s = ' '.join(w)
    if R.random() < level * 0.3:
        s = s[0].lower() + s[1:]
    if R.random() < level * 0.2:
        s = R.choice(['alo ', 'e ơi ', 'chị ơi cho hỏi, ', 'ad ơi ', 'nhờ xem giúp: ']) + s
    if R.random() < level * 0.15:
        s = s.rstrip('?') + R.choice([' 🙏', ' nha', ' hen', ' z ta', '??'])
    return s

def say_month(R, y, m, short_ok=True):
    c = ['tháng %d/%d' % (m, y), 'th%d/%d' % (m, y), 'T%d/%d' % (m, y), '%02d/%d' % (m, y), '%d-%d' % (m, y),
         'tháng %d năm %d' % (m, y)]
    if short_ok: c.append('th%d/%02d' % (m, y % 100))
    return R.choice(c)

def say_money(R, v):
    c = ['{:,}'.format(v).replace(',', '.') + ' đồng', '{:,}'.format(v).replace(',', '.') + 'đ']
    if v % 1000000 == 0: c += ['%d triệu' % (v // 10**6), '%d củ' % (v // 10**6)]
    elif v % 100000 == 0 and v > 10**6: c += ['%dtr%d' % (v // 10**6, (v % 10**6) // 100000), ('%.1f triệu' % (v / 1e6)).replace('.', ',')]
    if v % 1000 == 0 and v < 10**6: c.append('%dk' % (v // 1000))
    return R.choice(c)
