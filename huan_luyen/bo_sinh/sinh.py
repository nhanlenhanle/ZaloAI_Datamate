"""Sinh thêm shop ngành mới theo đúng khuôn bộ hard của người dùng (bộ sinh private_zalo_ai_hard_generator): dùng lại
core / sim / engine / qgen của bộ sinh đó (mô phỏng dữ liệu sạch, tính đáp án theo rulebook, câu hỏi văn nói), chỉ thêm:
cấu hình ngẫu nhiên cho các ngành trong nganh.py và một bộ ghi file ngẫu nhiên hoá (kiểu sổ, tên cột, kiểu README, làm bẩn).

    python -I sinh.py <thư mục bộ sinh> <thư mục ra> --n 30 --seed 7 [--start 301]
-> <ra>/data/biz_xxx/ (file + README), questions.jsonl, answers.jsonl, rulebook.md, calendar.csv, _shops.json (cấu hình,
cột thật của từng file: dùng làm nhãn cho dữ liệu fine-tune ánh xạ cột). Không đọc / ghi gì trong thư mục bộ sinh."""
import argparse, csv, datetime as D, hashlib, json, math, os, random, re, shutil, sqlite3, sys

ap = argparse.ArgumentParser()
ap.add_argument("gen"); ap.add_argument("out")
ap.add_argument("--n", type=int, default=30); ap.add_argument("--seed", type=int, default=7)
ap.add_argument("--start", type=int, default=301); ap.add_argument("--nganh", nargs="*")
ap.add_argument("--cau", type=int, default=52, help="số câu mỗi shop")
ap.add_argument("--deu", action="store_true", help="chia đều các họ câu (mặc định: trọng số của qgen)")
ap.add_argument("--loi-giai", action="store_true", help="ghi loi_giai.jsonl: kế hoạch JSON cho từng câu")
ap.add_argument("--nganh-test", action="store_true", help="dùng 14 ngành của nganh_test.py (chỉ cho tập kiểm thử nội bộ)")
ap.add_argument("--layout-public", action="store_true",
                help="thêm 3 kiểu sổ mở rộng (mỗi tháng một file, nhiều file xlsx cùng bảng, chỉ hoá đơn)")
ap.add_argument("--van-public", action="store_true", help="làm bẩn câu theo phân bố văn nói: 92%% có dấu hỏi, ít không dấu, nhiều viết tắt")
ap.add_argument("--cau-lech", action="store_true", help="số câu mỗi shop lệch nhau (20-130), tổng ≈ --cau × --n")
ap.add_argument("--giau", type=float, default=0, help="tỉ lệ shop bật đủ tính năng (kênh, ghi nợ, nhân viên, kho...)")
ap.add_argument("--luat-doi", choices=["A", "B", "C", "D", "E", "F", "G"], help="bộ rulebook đổi luật (luat_doi.py): đổi một nhóm luật, đáp án theo luật mới")
ap.add_argument("--b1311", help="file JSON mô tả từng shop (nganh, kieu, layout, giau): bộ Gen_1311 (mo_rong_1311.py)")
args = ap.parse_args()
sys.path.insert(0, args.gen)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core import *            # noqa: E402,F403  (bộ sinh của người dùng)
import sim, qgen, writers as W  # noqa: E402
from shops import H_DAY, H_EVE  # noqa: E402
from nganh import NGANH        # noqa: E402
if args.nganh_test:
    from nganh_test import NGANH_TEST
    NGANH = dict(NGANH_TEST)
import loi_giai                # noqa: E402
MR = None
if args.b1311:
    import mo_rong_1311 as MR   # noqa: E402
    NGANH.update(MR.NGANH_1311)
LD = None
if args.luat_doi:
    import luat_doi             # noqa: E402
    LD = luat_doi.Luat(qgen, args.luat_doi)     # bọc engine trước khi loi_giai.Vet bọc tiếp

# ------------------------------------------------------------------ cấu hình shop
TEN_RIENG = ['Minh Phát', 'Thanh Bình', 'Hồng Phúc', 'An Khang', 'Tân Tiến', 'Gia Hưng', 'Phúc Lộc', 'Kim Ngân', 'Hoà Bình',
             'Đức Thành', 'Bảo Ngọc', 'Hải Đăng', 'Tuấn Kiệt', 'Mai Anh', 'Song Long', 'Ngọc Lan', 'Phú Quý', 'Vạn Xuân']
CHANS = [('store', 70), ('zalo', 12), ('facebook', 10), ('shopee', 8)]


def cau_hinh(R, key, sid):
    title, prefix, spec = NGANH[key]
    start = D.date(2025, R.randint(1, 7), 1)
    end = min(start + D.timedelta(days=R.randint(420, 600)), D.date(2026, 9, 30))
    S = dict(id=sid, nganh=key, name='%s %s' % (title, R.choice(TEN_RIENG)), kind='retail', start=start, end=end,
             lam=round(R.uniform(6, 15), 1), hours=R.choice([H_DAY, H_EVE]), p_walkin=round(R.uniform(0.15, 0.5), 2),
             ncust=R.randint(80, 220), cust_code=R.random() < 0.5, oid_fmt=R.choice(['%05d', 'HD%06d', 'DH-%05d', '%06d']),
             items=sim.mk_items(spec, prefix), p_cancel=round(R.uniform(0.01, 0.05), 3), p_return=round(R.uniform(0.005, 0.02), 3),
             accent_trap=R.random() < 0.3, p_ldisc=R.choice([0, 0.04, 0.08]))
    if R.random() < 0.5:
        S['chans'] = CHANS[:R.randint(2, 4)]
        S['delivery'] = tuple(c for c, _ in S['chans'] if c != 'store')
    if R.random() < 0.2:
        S['deposit'] = True
    elif R.random() < 0.6:
        pays = [('cash', 45), ('transfer', 35), ('ewallet', 10)]
        if S.get('delivery'):
            pays.append(('cod', 10))
        if R.random() < 0.6:
            pays.append(('debt', R.choice([4, 8, 12])))
        S['pays'] = pays
    if R.random() < 0.4:
        S['staff'] = ['NV%02d' % i for i in range(1, R.randint(3, 6))]
    if R.random() < 0.3:
        S['odisc'] = (R.choice([300000, 500000, 1000000]), R.choice([10000, 20000, 50000]))
    if R.random() < 0.35 and sum(1 for it in S['items'] if not it.get('made')) >= 4:
        S['stock'] = True
        S['suppliers'] = ['NCC %s' % R.choice(TEN_RIENG) for _ in range(R.randint(2, 4))]
    return S


# ------------------------------------------------------------------ tên cột, nhãn
POOL = {
    'date': ['Ngày', 'Ngày bán', 'Ngày lập', 'Ngay', 'NgayCT', 'ngay_ban', 'Ngày chứng từ'],
    'datetime': ['Thời gian', 'Ngày giờ', 'Thời điểm', 'ThoiGian', 'thoi_gian', 'Ngày giờ lập'],
    'time': ['Giờ', 'Giờ bán', 'gio', 'Lúc', 'Giờ lập'],
    'oid': ['Số HĐ', 'Mã đơn', 'Số phiếu', 'Mã HĐ', 'ma_don', 'So CT', 'Số đơn'],
    'cust': ['Khách', 'Khách hàng', 'Tên khách', 'Người mua', 'khach', 'Tên KH'],
    'cid': ['Mã KH', 'Mã khách', 'ma_kh', 'IDKhach'],
    'chan': ['Kênh', 'Nguồn đơn', 'Kênh bán', 'kenh', 'Nơi bán'],
    'pay': ['Thanh toán', 'Hình thức TT', 'HTTT', 'thanh_toan', 'Trả bằng'],
    'staff': ['Nhân viên', 'NV bán', 'Người bán', 'ma_nv', 'Thu ngân'],
    'status': ['Trạng thái', 'Tình trạng', 'TT đơn', 'trang_thai', 'Kết quả'],
    'note': ['Ghi chú', 'Note', 'ghi_chu', 'Diễn giải'],
    'total': ['Tổng tiền', 'Thành tiền', 'Tiền hàng', 'Tổng cộng', 'tong_tien'],
    'icode': ['Mã hàng', 'Mã SP', 'ma_hang', 'SKU', 'Mã vật tư'],
    'iname': ['Hàng', 'Tên hàng', 'Mặt hàng', 'Sản phẩm', 'ten_hang', 'Tên SP'],
    'unit': ['ĐVT', 'Đơn vị', 'dvt', 'ĐV tính'],
    'qty': ['SL', 'Số lượng', 'so_luong', 'Slg', 'Số lg'],
    'price': ['Đơn giá', 'Giá', 'don_gia', 'Giá bán'],
    'ldisc': ['Giảm', 'Chiết khấu', 'CK dòng', 'giam_gia'],
    'amt': ['Thành tiền', 'Tiền', 'thanh_tien', 'T.Tiền', 'Thành tiền (đ)'],
    'odisc': ['Giảm giá đơn', 'CK đơn', 'giam_don', 'Bớt đơn'],
    'ship': ['Phí ship', 'Phí giao', 'phi_ship', 'Tiền ship'],
    'due': ['Tổng phải trả', 'Khách phải trả', 'tong_tien', 'Tổng đơn'],
    'stt': ['STT', 'Dòng', 'stt'],
}
DESC = {'date': 'ngày bán', 'time': 'giờ tạo đơn', 'datetime': 'ngày giờ tạo đơn', 'oid': 'số hoá đơn',
        'cust': 'tên khách (khách không lưu ghi khách lẻ); có lúc ghi kèm số điện thoại', 'cid': 'mã khách (trống: khách lẻ)',
        'chan': 'kênh bán', 'pay': 'hình thức thanh toán của đơn', 'staff': 'mã nhân viên bán', 'status': 'trạng thái đơn',
        'note': 'ghi chú của đơn', 'icode': 'mã hàng', 'iname': 'tên hàng (có thể ghi theo tên gọi khác trong danh mục)',
        'unit': 'đơn vị tính của dòng', 'qty': 'số lượng theo đơn vị của dòng', 'price': 'đơn giá theo đơn vị của dòng',
        'ldisc': 'tiền giảm của dòng', 'amt': 'thành tiền dòng (đã trừ giảm giá dòng)', 'odisc': 'giảm giá trên cả đơn',
        'ship': 'phí giao hàng của đơn', 'due': 'tổng khách phải trả cả đơn (= tổng thành tiền dòng − giảm giá đơn + phí ship)',
        'stt': 'số thứ tự dòng trong đơn',
    'total': 'tổng tiền của cả hoá đơn (đã gồm mọi dòng hàng)'}
ST_POOL = {'done': [['Hoàn thành', 'Đã giao', 'hoàn thành'], ['Hoàn tất', 'xong'], ['Đã thanh toán', 'Xong']],
           'cancel': [['Huỷ', 'Đã huỷ', 'khách huỷ'], ['Hủy đơn', 'Bỏ đơn']],
           'return': [['Trả hàng', 'Khách trả'], ['Hoàn hàng', 'Trả lại']],
           'ship': [['Đang giao', 'Chờ giao'], ['Đang ship']]}
NOTE_ST = {'done': [None, None, None, 'khách quen', 'gói quà'], 'cancel': ['khách huỷ', 'hủy đơn', 'Huỷ - hết hàng'],
           'return': ['khách trả lại hàng', 'trả hàng - lỗi'], 'ship': ['đang giao', 'shipper đang chở']}


def ten_cot(R):
    """Mỗi shop một bộ tên cột (không trùng nhau trong bộ)."""
    used, out = set(), {}
    for k, pool in (dict(POOL, **MR.POOL) if MR else POOL).items():
        c = R.choice([p for p in pool if p not in used] or pool)
        used.add(c); out[k] = c
    return out


def tien(R, v, rich):
    return W.fmt_money(R, v, ['plain', 'dot', 'k', 'dotd', 'tr'] if rich else ['plain', 'dot'])


def quy_doi_txt(R, it, style):
    big = [(u, f) for u, f in it['units'].items() if f > 1]
    if style == 2:          # --b1311: quy đổi ghi theo bậc (rulebook §10)
        if it.get('chain'):
            return '; '.join('1 %s = %d %s' % (a, f, b) for a, b, f in it['chain'])
        style = 0
    if style == 0:
        return '; '.join('1 %s = %d %s' % (u, f, it['base']) for u, f in big)
    return ';'.join('%s=%d' % (u, f) for u, f in big)


# ------------------------------------------------------------------ bộ ghi
class Ghi:
    def __init__(self, R, S, d):
        self.R, self.S, self.d = R, S, d
        self.C = ten_cot(R)
        self.layout = R.choice(['excel_thang', 'csv_tach', 'phang', 'sqlite'] +
                               ((['file_thang', 'xlsx_nhieu_file'] + ([] if args.luat_doi == 'B' else ['chi_hoa_don']))
                                if args.layout_public else []))
        if S.get('_layout'):            # --b1311: kiểu sổ ghi sẵn trong file mô tả shop
            self.layout = S['_layout']
        self.skip = set()
        self.status_in_note = self.layout in ('excel_thang', 'file_thang') and R.random() < 0.6
        self.st = {k: R.choice(v) for k, v in ST_POOL.items()}
        self.rich = R.random() < 0.6
        self.files = []          # (tên file, [(cột, khoá)]) cho README và nhãn cột
        self.notes = []          # quy ước README
        self.readme_style = R.choice(['cot', 'van', 'it'])

    # nhãn
    def status(self, o):
        return W.status_label(self.R, o['status'], NOTE_ST if self.status_in_note else self.st)

    def cust(self, o):
        c = self.S['cmap'].get(o['cust'])
        if c and self.S.get('sua_xe'):
            return MR.bien_so_nhan(self.R, c['name'])
        return W.cust_label(self.R, c) if c else self.R.choice(W.WALKIN)

    def order_cols(self, with_date=True):
        S, ks = self.S, []
        if with_date:
            ks.append('datetime')
        ks.append('oid')
        ks += ['cid'] if S['cust_code'] else ['cust']
        if S.get('chans'):
            ks.append('chan')
        if S.get('pays'):
            ks.append('pay')
        if S.get('staff'):
            ks.append('staff')
        ks += [k for k, f in (('thu_cu', 'dien_thoai'), ('diem', 'diem'), ('han', 'han_tt')) if S.get(f)]
        ks.append('note' if self.status_in_note else 'status')
        return ks

    def order_vals(self, o, ks, dt_styles):
        R, out = self.R, []
        for k in ks:
            if k == 'datetime':
                out.append(W.fmt_date(R, o['date'], dt_styles, o['t'][:2]))
            elif k == 'oid':
                out.append(o['id'])
            elif k == 'cid':
                out.append(o['cust'] or '')
            elif k == 'cust':
                out.append(self.cust(o))
            elif k == 'chan':
                out.append(R.choice(W.CHAN_VN[o['chan']]))
            elif k == 'pay':
                out.append(R.choice(W.PAY_VN[o['pay']]))
            elif k == 'staff':
                out.append(o['staff'])
            elif k in ('status', 'note'):
                out.append(self.status(o) or '')
            elif k == 'odisc':
                out.append(tien(R, o['odisc'], False))
            elif k == 'ship':
                out.append(tien(R, o['ship'], self.rich))
            elif k == 'due':
                out.append(tien(R, o['due'], self.rich))
            elif k == 'total':
                out.append(tien(R, sum(l['amt'] for l in o['lines']), self.rich))
            elif k in ('thu_cu', 'diem'):
                out.append(tien(R, o.get(k, 0), self.rich) if o.get(k) else '')
            elif k == 'han':
                out.append(W.fmt_date(R, o['han'], ['dmy', 'iso']) if o.get('han') else '')
        return out

    def line_vals(self, l, ks):
        R, it, out = self.R, self.S['imap'][l['code']], []
        for k in ks:
            out.append({'icode': lambda: W.dirty_id(R, l['code']), 'iname': lambda: W.item_label(R, it), 'unit': lambda: l['unit'],
                        'qty': lambda: l['qty'], 'price': lambda: tien(R, l['price'], self.rich),
                        'ldisc': lambda: tien(R, l['disc'], False), 'amt': lambda: tien(R, l['amt'], self.rich),
                        'imei': lambda: l.get('imei', '')}[k]())
        return out

    def hdr(self, ks):
        return [self.C[k] for k in ks]

    # sổ bán theo kiểu
    def so_ban(self):
        S, R, d = self.S, self.R, self.d
        if MR and self.layout in MR.LAYOUT:
            return MR.LAYOUT[self.layout](self)
        line_ks = (['icode'] if R.random() < 0.5 or self.layout in ('csv_tach', 'sqlite') else []) + ['iname'] * (self.layout != 'csv_tach') \
            + ['unit', 'qty', 'price'] + (['ldisc'] if S.get('p_ldisc') else []) + ['amt'] + (['imei'] if S.get('dien_thoai') else [])
        extra = (['odisc'] if S.get('odisc') else []) + (['ship'] if S.get('delivery') else [])
        if self.layout == 'excel_thang':
            S['shift_ok'] = True
            oks = ['date', 'time'] + self.order_cols(False)[0:] + []
            hdr_ks = oks + line_ks
            by_year = {}
            for o in S['orders']:
                by_year.setdefault(o['date'].year, []).append(o)
            for y, os_ in by_year.items():
                sheets = []
                for m in range(1, 13):
                    mo = [o for o in os_ if o['date'].month == m]
                    if not mo:
                        continue
                    rows = [['SỔ BÁN HÀNG THÁNG %d/%d' % (m, y)], [], self.hdr(hdr_ks)]
                    tot = 0
                    for o in mo:
                        for i, l in enumerate(o['lines']):
                            lv = self.line_vals(l, line_ks)
                            if i == 0:
                                tfmt = R.choice(['%02d:%02d', '%dh%02d', '%02d:%02d'])
                                head = ['%02d/%02d' % (o['date'].day, o['date'].month), tfmt % o['t'][:2]] + self.order_vals(o, oks[2:], [])
                            else:
                                head = [''] * len(oks)
                            rows.append(head + lv)
                            if i > 0 and R.random() < 0.004:
                                rows.append(head + lv)
                            tot += l['amt']
                    rows.append([''] * (len(oks) - 1) + ['CỘNG THÁNG'] + [''] * (len(line_ks) - 1) + [tot])
                    sheets.append(('T%d' % m, rows))
                fn = 'SoBanHang_%d.xlsx' % y
                W.xl(os.path.join(d, fn), sheets)
                self.files.append((fn, hdr_ks))
            self.notes += ['Mỗi năm một file `SoBanHang_<năm>.xlsx`, mỗi tháng một sheet; hai dòng đầu mỗi sheet là tiêu đề, dòng cuối là '
                           'dòng `CỘNG THÁNG` (tổng tự cộng, không phải đơn).',
                           'Cột ngày chỉ ghi `dd/mm`, năm theo tên file.',
                           'Thông tin đơn (ngày, giờ, số đơn, khách, ...) chỉ ghi ở dòng đầu mỗi đơn; các dòng sau của đơn để trống các ô này.']
            if extra:
                self.don_rieng(extra, 'ThongTinDon.xlsx')
        elif self.layout == 'file_thang':      # mỗi tháng một file xlsx, banner + header lặp giữa file
            S['shift_ok'] = True
            oks = ['date', 'time'] + self.order_cols(False)
            hdr_ks = oks + line_ks
            by_m = {}
            for o in S['orders']:
                by_m.setdefault((o['date'].year, o['date'].month), []).append(o)
            for (y, m), mo in sorted(by_m.items()):
                rows = [['BÁO CÁO BÁN HÀNG THÁNG %02d/%d' % (m, y)], ['Từ ngày 01/%02d/%d đến ngày cuối tháng' % (m, y)], [], self.hdr(hdr_ks)]
                for k, o in enumerate(mo):
                    if k and k % 130 == 0:
                        rows.append(self.hdr(hdr_ks))
                    for i, l in enumerate(o['lines']):
                        lv = self.line_vals(l, line_ks)
                        head = (['%02d/%02d/%d' % (o['date'].day, m, y), '%02d:%02d' % o['t'][:2]] + self.order_vals(o, oks[2:], [])) if i == 0 else [''] * len(oks)
                        rows.append(head + lv)
                        if i > 0 and R.random() < 0.004:
                            rows.append(head + lv)
                    if R.random() < 0.08:
                        rows.append(['Tổng ngày %02d/%02d' % (o['date'].day, m)] + [''] * (len(hdr_ks) - 2) + [sum(l['amt'] for l in o['lines'])])
                fn = R.choice(['BanHang_T%d_%d.xlsx', 'BanHang_Thang%02d_%d.xlsx']) % (m, y)
                W.xl(os.path.join(d, fn), [('Sheet1', rows)])
                self.files.append((fn, hdr_ks))
            self.notes += ['Mỗi tháng một file `BanHang_T<tháng>_<năm>.xlsx`; ba dòng đầu là tiêu đề báo cáo, dòng tiêu đề cột lặp lại giữa file (ngắt trang).',
                           'Dòng `Tổng ngày dd/mm` là dòng cộng tự động, không phải đơn.',
                           'Thông tin đơn chỉ ghi ở dòng đầu mỗi đơn; các dòng sau của đơn để trống các ô này.']
            if extra:
                self.don_rieng(extra, 'ThongTinDon.xlsx')
        elif self.layout == 'xlsx_nhieu_file':    # cùng một bảng chi tiết hoá đơn tách thành nhiều file _1, _2
            S['shift_ok'] = True
            oks = self.order_cols(True) + extra
            hdr_ks = oks + line_ks
            rows = []
            for o in S['orders']:
                ov = self.order_vals(o, oks, ['dmy', 'iso', 'obj'])
                for l in o['lines']:
                    r = ov + self.line_vals(l, line_ks)
                    rows.append(r)
                    if R.random() < 0.004:
                        rows.append(list(r))
            n_file = 2 if len(rows) < 40000 else 3
            per = (len(rows) + n_file - 1) // n_file
            for i in range(n_file):
                fn = 'ChiTietHoaDon_%d.xlsx' % (i + 1)
                W.xl(os.path.join(d, fn), [('Data', [self.hdr(hdr_ks)] + rows[i * per:(i + 1) * per])])
                self.files.append((fn, hdr_ks))
            self.notes += ['Chi tiết hoá đơn xuất thành nhiều file `ChiTietHoaDon_<n>.xlsx` cùng cột, nối tiếp nhau theo thời gian; mỗi dòng một dòng hàng, thông tin đơn lặp lại ở mọi dòng.',
                           'Ngày giờ có thể là ô ngày của Excel hoặc chữ `dd/mm/yyyy hh:mm` / `yyyy-mm-dd hh:mm`.']
        elif self.layout == 'chi_hoa_don':       # như biz_110: chỉ danh sách hoá đơn, không có dòng hàng
            S['shift_ok'] = True
            S['no_lines'] = True
            oks = self.order_cols(True) + extra + ['total']
            rows, cur, mtot = [], None, 0
            for o in S['orders']:
                m = (o['date'].year, o['date'].month)
                if cur and m != cur:
                    rows.append(['Tổng tháng %d/%d' % (cur[1], cur[0])] + [''] * (len(oks) - 2) + [tien(R, mtot, False)]); mtot = 0
                cur = m; tot = sum(l['amt'] for l in o['lines']); mtot += tot
                r = self.order_vals(o, oks[:-1], ['dmy', 'iso']) + [tien(R, tot, self.rich)]
                rows.append(r)
                if R.random() < 0.004:
                    rows.append(list(r))
            rows.append(['Tổng tháng %d/%d' % (cur[1], cur[0])] + [''] * (len(oks) - 2) + [tien(R, mtot, False)])
            W.wcsv(os.path.join(d, 'danh_sach_hoa_don.csv'), self.hdr(oks), rows)
            self.files.append(('danh_sach_hoa_don.csv', oks))
            self.notes += ['Chỉ có danh sách hoá đơn `danh_sach_hoa_don.csv`: mỗi dòng một đơn với tổng tiền đơn, KHÔNG có chi tiết từng mặt hàng.',
                           'Có dòng `Tổng tháng m/yyyy` tự cộng, không phải đơn.']
        elif self.layout == 'phang':
            S['shift_ok'] = True
            oks = self.order_cols(True) + extra
            hdr_ks = oks + line_ks
            rows = [[S['name'].upper() + ' - CHI TIẾT BÁN HÀNG'], ['Xuất lúc %s 23:59' % S['end'].strftime('%d/%m/%Y')], [], self.hdr(hdr_ks)]
            for k, o in enumerate(S['orders']):
                if k and k % 1500 == 0:
                    rows.append(self.hdr(hdr_ks))
                ov = self.order_vals(o, oks, ['obj', 'dmy', 'serial'])
                for l in o['lines']:
                    r = ov + self.line_vals(l, line_ks)
                    rows.append(r)
                    if R.random() < 0.004:
                        rows.append(list(r))
            W.xl(os.path.join(d, 'BanHang.xlsx'), [('Data', rows)])
            self.files.append(('BanHang.xlsx', hdr_ks))
            self.notes += ['`BanHang.xlsx`: 3 dòng đầu là tiêu đề xuất file; dòng tiêu đề cột lặp lại giữa file. Mỗi dòng một dòng hàng, '
                           'thông tin đơn lặp lại ở mọi dòng.',
                           'Ngày giờ có thể là ô ngày của Excel, số ngày kiểu Excel (serial) hoặc chữ `dd/mm/yyyy hh:mm`.']
        elif self.layout == 'csv_tach':
            S['shift_ok'] = True
            oks = self.order_cols(True) + extra
            rows, det, cur, mtot = [], [], None, 0
            for o in S['orders']:
                m = (o['date'].year, o['date'].month)
                if cur and m != cur:
                    rows.append(['Tổng tháng %d/%d' % (cur[1], cur[0])] + [''] * (len(oks) - 2) + [tien(R, mtot, False)]); mtot = 0
                    if R.random() < 0.3:
                        rows.append(self.hdr(oks))
                cur = m; mtot += sum(l['amt'] for l in o['lines'])
                rows.append(self.order_vals(o, oks, ['dmy', 'dmy', 'iso']))
                for i, l in enumerate(o['lines'], 1):
                    r = [W.dirty_id(R, o['id']), i] + self.line_vals(l, line_ks)
                    det.append(r)
                    if R.random() < 0.004:
                        det.append(list(r))
            rows.append(['Tổng tháng %d/%d' % (cur[1], cur[0])] + [''] * (len(oks) - 2) + [tien(R, mtot, False)])
            W.wcsv(os.path.join(d, 'don_hang.csv'), self.hdr(oks), rows)
            W.wcsv(os.path.join(d, 'chi_tiet_don.csv'), self.hdr(['oid', 'stt'] + line_ks), det)
            self.files += [('don_hang.csv', oks), ('chi_tiet_don.csv', ['oid', 'stt'] + line_ks)]
            self.notes += ['`don_hang.csv` có dòng tổng tháng tự cộng (`Tổng tháng m/yyyy`, cột cuối là tổng thành tiền dòng của tháng) và đôi khi lặp lại dòng tiêu đề.',
                           'Các file xuất thủ công nên mã có thể dính khoảng trắng thừa ở đầu, cuối.',
                           'Ngày ghi `dd/mm/yyyy` (ngày trước tháng) hoặc `yyyy-mm-dd`.']
        else:   # sqlite
            S['shift_ok'] = True
            oks = self.order_cols(True) + extra
            con = sqlite3.connect(os.path.join(d, 'cuahang.sqlite'))
            snake = lambda ks: [self.snake(k) for k in ks]
            ocols, lcols = snake(oks), snake(['oid', 'stt'] + line_ks)
            con.execute('CREATE TABLE don_ban (%s)' % ', '.join('"%s"' % c for c in ocols))
            con.execute('CREATE TABLE dong_ban (%s)' % ', '.join('"%s"' % c for c in lcols))
            for o in S['orders']:
                con.execute('INSERT INTO don_ban VALUES (%s)' % ','.join('?' * len(ocols)),
                            [str(v) if isinstance(v, D.datetime) else v for v in self.order_vals(o, oks, ['iso', 'dmy'])])
                for i, l in enumerate(o['lines'], 1):
                    con.execute('INSERT INTO dong_ban VALUES (%s)' % ','.join('?' * len(lcols)), [o['id'], i] + self.line_vals(l, line_ks))
            con.commit(); con.close()
            self.sql_cols = {'don_ban': ocols, 'dong_ban': lcols}
            self.files += [('cuahang.sqlite: don_ban', oks), ('cuahang.sqlite: dong_ban', ['oid', 'stt'] + line_ks)]
            self.notes += ['Phần mềm bán hàng xuất một file SQLite `cuahang.sqlite`; bảng `don_ban` (mỗi đơn một dòng) nối `dong_ban` (mỗi dòng hàng) qua mã đơn.',
                           'Ngày giờ ghi `yyyy-mm-dd hh:mm` hoặc `dd/mm/yyyy hh:mm`.']

    def snake(self, k):
        n = W.strip_acc(self.C[k]).lower()
        return ''.join(ch if ch.isalnum() else '_' for ch in n).strip('_')

    def don_rieng(self, extra, fn):
        """Sổ theo tháng không có chỗ cho giảm giá đơn / phí ship: thêm một file thông tin đơn."""
        R = self.R
        ks = ['oid'] + extra
        rows = [self.hdr(ks)] + [self.order_vals(o, ks, []) for o in self.S['orders'] if o['odisc'] or o['ship']]
        W.xl(os.path.join(self.d, fn), [('Don', rows)])
        self.files.append((fn, ks))

    # bảng phụ
    def danh_muc(self):
        S, R = self.S, self.R
        if S.get('no_lines'):
            return
        has_alias = any(it.get('alias') for it in S['items']) and R.random() < 0.85
        style = R.randint(0, 1)
        if MR and any(it.get('chain') for it in S['items']) and R.random() < 0.5:
            style = 2
        rx = any('rx' in it for it in S['items'])
        RX = {True: ['Có', 'x', 'TRUE', '1'], False: ['Không', '', 'FALSE', '0']}
        hdr = ['Mã hàng', 'Tên hàng'] + (['Tên gọi khác'] if has_alias else []) + ['Nhóm', 'ĐV cơ bản', 'Quy đổi'] + (['Giá vốn'] if S.get('stock') else []) \
            + (['Kê đơn', 'Hoạt chất'] if rx else [])
        rows = [hdr]
        for it in S['items']:
            rows.append([it['code'], it['name']] + ([', '.join(it.get('alias', []))] if has_alias else []) +
                        [it['group'], it['base'], quy_doi_txt(R, it, style)] + ([it['cost']] if S.get('stock') else [])
                        + ([R.choice(RX[bool(it.get('rx'))]), it.get('ing', '')] if rx else []))
        if self.layout == 'csv_tach':
            W.wcsv(os.path.join(self.d, 'san_pham.csv'), hdr, rows[1:]); fn = 'san_pham.csv'
        else:
            W.xl(os.path.join(self.d, 'DanhMuc.xlsx'), [('DanhMuc', rows)]); fn = 'DanhMuc.xlsx'
        self.files.append((fn, None))
        self.notes.append('**Quy đổi**: đơn vị lớn theo danh mục (%s); hàng không có quy đổi chỉ bán theo đơn vị cơ bản.'
                          % ('vd `1 thùng = 24 chai`' if style == 0 else '`đơn vị lớn=hệ số`, số đơn vị cơ bản trong 1 đơn vị lớn' if style == 1
                             else 'ghi theo bậc, vd `1 thùng = 10 vỉ; 1 vỉ = 30 quả`: mỗi bậc là số đơn vị ngay dưới'))
        if rx:
            self.notes.append('**Kê đơn** (`Có`, `x`, `TRUE`, `1` là thuốc kê đơn); **Hoạt chất** nhiều chất nối bằng ` + `.')
        if has_alias:
            self.notes.append('Tên hàng trong sổ có thể ghi theo **Tên gọi khác** trong danh mục.')

    def khach(self):
        S = self.S
        if not S['cust_code']:
            self.notes.append('Không có mã khách; khách lẻ ghi `Khách lẻ` hoặc viết tắt.')
            return
        rows = [['Mã KH', 'Tên khách', 'SĐT', 'Nhóm KH']] + [[c['id'], c['name'], c['phone'], c['group']] for c in S['custs']]
        W.xl(os.path.join(self.d, 'KhachHang.xlsx'), [('KH', rows)])
        self.files.append(('KhachHang.xlsx', None))
        self.notes.append('Mã khách trống là khách lẻ. **Nhóm KH** là nhóm khách.')

    def thu_tien(self):
        S, R = self.S, self.R
        if not (S.get('deposit') or any(p == 'debt' for p, _ in S.get('pays') or [])):
            return
        rows = [['Mã phiếu', 'Mã đơn', 'Ngày giờ thu', 'Số tiền', 'Loại']]
        k = 0
        for o in S['orders']:
            for dt_, a, kk in o['payments']:
                k += 1
                lab = {'cọc': 'Cọc', 'cod': 'COD', 'trả': 'Trả nợ' if dt_ > o['date'] and not S.get('deposit') else 'Thanh toán'}.get(kk, 'Thu tại quầy')
                rows.append(['PT%06d' % k, W.dirty_id(R, o['id']), W.fmt_date(R, dt_, ['dmy', 'iso'], (R.randint(8, 21), R.randint(0, 59))),
                             tien(R, a, self.rich), lab])
        W.xl(os.path.join(self.d, 'PhieuThu.xlsx'), [('PhieuThu', rows)])
        self.files.append(('PhieuThu.xlsx', None))
        if S.get('deposit'):
            self.notes.append('**Tiền cọc**: mọi đơn thu cọc lúc đặt (loại `Cọc` trong `PhieuThu.xlsx`), phần còn lại trả khi lấy hàng, có thể '
                              'trả nhiều lần. Cọc là một phần tiền khách trả cho đơn. Đơn huỷ không hoàn cọc.')
        else:
            self.notes.append('Thanh toán `Ghi nợ` là bán chịu; `PhieuThu.xlsx` ghi mọi lần thu tiền của đơn, kể cả các lần trả nợ sau ngày bán.')

    def kho(self):
        S, R = self.S, self.R
        if args.luat_doi == 'B' and not S.get('stock') and not S.get('no_lines'):
            rets = [['Mã đơn', 'Ngày trả', 'Mã hàng', 'SL trả (ĐV cơ bản)']]
            for o in S['orders']:
                if o['status'] == 'return':
                    for i, q in o['ret_lines']:
                        rets.append([o['id'], W.fmt_date(R, o['ret_date'], ['dmy']), o['lines'][i]['code'], num_out(q)])
            W.xl(os.path.join(self.d, 'TraHang.xlsx'), [('TraHang', rets)])
            self.files.append(('TraHang.xlsx', None))
            self.notes.append('`TraHang.xlsx`: các dòng hàng khách trả (mã đơn, ngày trả, mã hàng, số lượng trả theo đơn vị cơ bản).')
            return
        if not S.get('stock') or S.get('no_lines'):
            return
        lo = bool(S.get('lots'))
        prow = [['Số phiếu', 'Ngày nhập', 'Nhà cung cấp', 'Mã hàng'] + (['Số lô', 'Hạn dùng'] if lo else []) +
                ['ĐVT nhập', 'SL nhập', 'Giá nhập', 'Thành tiền', 'Trạng thái', 'Ghi chú']]
        for p in S['purchases']:
            for l in p['lines']:
                prow.append([p['id'], W.fmt_date(R, p['date'], ['dmy', 'iso']), p['sup'], l['code']] +
                            ([l['lot'], W.fmt_date(R, l['exp'], ['dmy', 'iso'])] if lo else []) +
                            [l['unit'], l['qty'], l['price'], l['amt'], 'Huỷ phiếu' if p['cancel'] else 'Đã nhập', 'nhập đầu kỳ' if p['first'] else ''])
        if lo:
            xl_ = [['Mã đơn', 'Mã hàng', 'Số lô', 'SL xuất (ĐVCB)', 'SL trả (ĐVCB)']]
            for o in S['orders']:
                for l in o['lines']:
                    for a in l.get('alloc', []):
                        xl_.append([o['id'], l['code'], a[0], num_out(a[1]), num_out(a[2]) if len(a) > 2 and o['status'] == 'return' else 0])
            W.xl(os.path.join(self.d, 'XuatTheoLo.xlsx'), [('XuatLo', xl_)])
            self.files.append(('XuatTheoLo.xlsx', None))
            self.notes.append('Mỗi dòng nhập là một **lô** (`Số lô`, `Hạn dùng`). `XuatTheoLo.xlsx`: mỗi dòng bán lấy từ một hay nhiều lô '
                              '(`SL xuất`), `SL trả` là hàng khách trả về lại đúng lô đó; số lượng theo đơn vị cơ bản.')
        rets = [['Mã đơn', 'Ngày trả', 'Mã hàng', 'SL trả (ĐV cơ bản)']]
        for o in S['orders']:
            if o['status'] == 'return':
                for i, q in o['ret_lines']:
                    rets.append([o['id'], W.fmt_date(R, o['ret_date'], ['dmy']), o['lines'][i]['code'], num_out(q)])
        W.xl(os.path.join(self.d, 'NhapHang.xlsx'), [('NhapHang', prow)])
        W.xl(os.path.join(self.d, 'TraHang.xlsx'), [('TraHang', rets)])
        self.files += [('NhapHang.xlsx', None), ('TraHang.xlsx', None)]
        self.notes.append('**Tồn kho**: tồn tại một thời điểm = tổng nhập (phiếu không huỷ) − tổng xuất theo đơn không huỷ + hàng khách trả '
                          '(theo ngày trả), tính từ đầu dữ liệu. Phiếu `nhập đầu kỳ` là tồn đầu.')

    def readme(self):
        S = self.S
        intro = {'cot': '%s ghi sổ bán hàng; dưới đây là các file và cột.', 'van': '%s quản lý bán hàng bằng các file sau.',
                 'it': '%s gửi các file sổ sách dưới đây.'}[self.readme_style] % S['name']
        parts = [intro, '', '## File']
        for fn, ks in self.files:
            if ks is None or self.readme_style == 'it':
                parts.append('- `%s`' % fn)
            elif self.readme_style == 'van':
                parts.append('- `%s`: ' % fn + ', '.join('`%s` (%s)' % (self.C[k], DESC[k]) for k in ks))
            else:
                parts.append('- `%s`' % fn)
        if self.readme_style == 'cot':
            groups = {}
            for fn, ks in self.files:
                if ks:
                    groups.setdefault(tuple(ks), []).append(fn)
            for ks, fns in groups.items():
                parts += ['', '## Cột trong %s' % ', '.join('`%s`' % f for f in fns)] + ['- **%s**: %s' % (self.C[k], DESC[k]) for k in ks]
        if self.status_in_note:
            self.notes.append('Sổ không có cột trạng thái: trạng thái đơn (huỷ, trả hàng, đang giao) ghi trong cột ghi chú.')
        parts += ['', '## Quy ước', '- Dữ liệu từ %s đến hết %s.' % (S['start'].strftime('%d/%m/%Y'), S['end'].strftime('%d/%m/%Y'))]
        parts += ['- ' + n for n in self.notes]
        W.readme(os.path.join(self.d, 'README.md'), 'Dữ liệu %s' % S['id'], '\n'.join(parts))

    def chay(self):
        self.so_ban()
        for f in ('danh_muc', 'khach', 'thu_tien'):
            if f not in self.skip:
                getattr(self, f)()
        self.kho(); self.readme()
        return {'layout': self.layout, 'readme': self.readme_style, 'status_in_note': self.status_in_note,
                'cols': [(fn, [(self.C[k], k) for k in ks] if ks else None) for fn, ks in self.files]}


# ------------------------------------------------------------------ chạy
def lam_giau(R, S):
    """Bật đủ tính năng cho shop để mọi họ câu đều sinh được (công nợ, nhân viên, kho, kênh, giảm giá đơn)."""
    S['chans'] = CHANS[:4]
    S['delivery'] = tuple(c for c, _ in S['chans'] if c != 'store')
    S.pop('deposit', None)
    S['pays'] = [('cash', 45), ('transfer', 35), ('ewallet', 10), ('cod', 10), ('debt', R.choice([4, 8, 12]))]
    S['staff'] = ['NV%02d' % i for i in range(1, R.randint(3, 6))]
    S['odisc'] = (R.choice([300000, 500000, 1000000]), R.choice([10000, 20000, 50000]))
    if sum(1 for it in S['items'] if not it.get('made')) >= 4:
        S['stock'] = True
        S['suppliers'] = ['NCC %s' % R.choice(TEN_RIENG) for _ in range(R.randint(2, 4))]


def sinh_cau(R, S, n, deu):
    """Như qgen.gen_questions (shop bán lẻ), thêm tên họ câu (`ho`) cho mỗi câu; deu: mọi họ cùng trọng số."""
    fams = qgen.RETAIL + ([qgen.SPECIAL[S['id']]] if S['id'] in qgen.SPECIAL else [])
    if MR:
        fams = MR.trong_so(S, fams + MR.ho_them(S))
    if S.get('no_lines'):      # sổ chỉ có hoá đơn: bỏ họ câu cần dòng hàng / danh mục / kho
        bo = {'F_top_item', 'F_top_rev_group', 'F_qty_item', 'F_rev_item', 'F_units', 'F_group', 'F_itemsin', 'F_purch', 'F_stock', 'F_hike', 'F_table'}
        fams = [(f, wt) for f, wt in fams if f.__name__ not in bo]
    if LD:
        fams = LD.ho_cau(fams)
    w = [1 if deu else wt for _, wt in fams]
    res, seen, tries = [], set(), 0
    vet = VET
    while len(res) < n and tries < n * 40:
        tries += 1
        t = qgen.asof_dates(R, S, 1)[0]
        f = R.choices([f for f, _ in fams], w)[0]
        goc = None
        if LD:                  # cùng câu, tính theo luật gốc (cùng trạng thái ngẫu nhiên) để biết đáp án có đổi không
            st = R.getstate()
            LD.dat(S, False)
            try:
                goc = f(R, S, t)
            except (qgen.E.Unans, ZeroDivisionError, IndexError, ValueError, TypeError):
                goc = None
            LD.dat(S, True)
            R.setstate(st)
        if vet:
            vet.moi()
        try:
            out = f(R, S, t)
        except (qgen.E.Unans, ZeroDivisionError, IndexError, ValueError, TypeError):
            continue
        if not out:
            continue
        q, typ, ans, alias = out
        if (q, t) in seen:
            continue
        seen.add((q, t))
        x = dict(q=(van_public(R, q) if args.van_public else noisy(R, q[0].upper() + q[1:], R.uniform(0.15, 0.85))),
                 raw=q, t=t, type=typ, answer=ans, alias=alias, ho=f.__name__[2:])
        if vet:
            x["ke_hoach"], x["ghi_chu"] = loi_giai.ke_hoach(x["ho"], list(vet.goi), S, t, typ)
            if LD:
                kh, gc = luat_doi.doi_ke_hoach(args.luat_doi, x["ke_hoach"])
                x["ke_hoach"], x["ghi_chu"] = kh, (gc or x["ghi_chu"])
        if LD:
            x["goc"] = (goc[1], goc[2]) if goc and goc[0] == q else None
        res.append(x)
    return res


VET = None

VIET_TAT = [('doanh thu', ['dthu', 'doanh thu', 'dt']), ('bao nhiêu', ['bao nhiêu', 'bnhiu', 'bn', 'nhiêu']), ('đơn hàng', ['đơn hàng', 'đh', 'đơn']),
            ('không', ['không', 'ko', 'k']), ('được', ['được', 'đc', 'dc']), ('khách hàng', ['khách hàng', 'kh', 'khách']),
            ('tháng này', ['tháng này', 'th này', 'tháng nay']), ('mặt hàng', ['mặt hàng', 'mh', 'món']), ('sản phẩm', ['sản phẩm', 'sp']),
            ('nhân viên', ['nhân viên', 'nv']), ('trung bình', ['trung bình', 'tb']), ('cửa hàng', ['cửa hàng', 'shop', 'tiệm'])]
PHUONG_NGU = [('bao nhiêu', 'mấy'), ('bao nhiêu', 'nhiêu'), ('hôm nay', 'bữa nay'), ('hôm qua', 'bữa qua'), ('hôm nay', 'bữa ni'),
              ('như thế nào', 'răng'), ('cái gì', 'cái chi'), ('là gì', 'là chi')]
MO_DAU = ['Cho hỏi ', 'Cho mình hỏi ', 'Xem giúp ', 'Coi giúp ', 'E ơi ', 'Ad ơi ', 'Shop ơi ', 'Nhờ xem giúp: ']


def van_public(R, q):
    """Làm bẩn câu theo phân bố đo trên public test: 92 % kết thúc bằng '?', 6 % không dấu, 6 % chữ thường đầu,
    38 % có viết tắt, ~5 % phương ngữ, vài % câu mở đầu, hiếm emoji; cụm tháng viết nhiều kiểu (T5/2025, 3/26, 6-2025)."""
    s = q
    if R.random() < 0.55:
        for a, bs in VIET_TAT:
            if a in s and R.random() < 0.7:
                s = s.replace(a, R.choice(bs), 1)
    if R.random() < 0.05:
        for a, b in PHUONG_NGU:
            if a in s and R.random() < 0.6:
                s = s.replace(a, b, 1); break
    if R.random() < 0.08:
        s = re.sub(r'tháng (\d{1,2})/(\d{4})', lambda m: R.choice(['T%s/%s', '%s/%s', 'th%s/%s']) % (m.group(1), m.group(2)), s, count=1)
    if R.random() < 0.06:
        s = re.sub(r'tháng (\d{1,2})/20(\d{2})', lambda m: R.choice(['%s/%s', 'th%s/%s', '%s-20%s']) % (m.group(1), m.group(2)), s, count=1)
    if R.random() < 0.12:
        w = s.split(' '); i = R.randrange(len(w))
        if len(w[i]) > 3 and w[i].isalpha():
            j = R.randrange(len(w[i]) - 1); w[i] = w[i][:j] + w[i][j + 1] + w[i][j] + w[i][j + 2:]
        s = ' '.join(w)
    if R.random() < 0.03:
        s = R.choice(MO_DAU) + s[0].lower() + s[1:]
    s = s[0].upper() + s[1:] if R.random() > 0.06 else s[0].lower() + s[1:]
    s = s.rstrip('?.! ')
    if R.random() < 0.92:
        s += R.choice(['?', '?', '?', ' ?', ' vậy?', ' ạ?', ' z?', ' nhỉ?'])
    elif R.random() < 0.3:
        s += R.choice([' 🙏', ' nha', ' hen'])
    if R.random() < 0.07:          # bỏ dấu sau cùng để cả câu không dấu (public: 6 %)
        s = strip_acc(s)
    return s


def main():
    global VET
    if args.loi_giai:
        VET = loi_giai.Vet(qgen.E)
    lg = []
    R = random.Random(args.seed)
    keys = args.nganh or sorted(NGANH)
    picks = [keys[i % len(keys)] for i in range(args.n)]
    R.shuffle(picks)
    spec = None
    if MR:                  # --b1311: shop theo đúng thứ tự file mô tả (ngành, loại shop, kiểu sổ, đủ tính năng)
        spec = json.load(open(args.b1311, encoding='utf-8'))
        picks = [x['nganh'] for x in spec]
        DESC.update(MR.DESC)
    all_S = []
    if os.path.exists(args.out):
        shutil.rmtree(args.out)
    os.makedirs(os.path.join(args.out, 'data'))
    qs, ans, meta = [], [], []
    for i, key in enumerate(picks):
        sid = 'biz_%d' % (args.start + i)
        r = random.Random('%s-%s' % (args.seed, sid))
        sp = spec[i] if spec else {}
        rq = random.Random('%s-q-%s' % (args.seed, sid))
        n_cau = args.cau
        if args.cau_lech:       # 20-130 câu / shop, tổng xấp xỉ --cau × --n
            n_cau = max(20, min(130, int(random.Random('%s-c-%s' % (args.seed, sid)).lognormvariate(math.log(args.cau * 0.85), 0.55))))
        if sp.get('kieu') in ('sac', 'thue'):       # shop dịch vụ (mo_rong_1311): mô phỏng, sổ, câu hỏi riêng
            S = MR.cau_hinh_dich_vu(r, sp, sid, TEN_RIENG)
            MR.sim_dich_vu(r, S)
            d = os.path.join(args.out, 'data', sid); os.makedirs(d)
            info = MR.ghi_dich_vu(random.Random('%s-w-%s' % (args.seed, sid)), S, d)
            cau = MR.cau_hoi_dich_vu(rq, S, n_cau, lambda R_, q: van_public(R_, q) if args.van_public else noisy(R_, q[0].upper() + q[1:], R_.uniform(0.15, 0.85)))
        else:
            S = cau_hinh(r, key, sid)
            gi = sp['giau'] if 'giau' in sp else (args.giau and random.Random('%s-g-%s' % (args.seed, sid)).random() < args.giau)
            if gi:
                lam_giau(random.Random('%s-gg-%s' % (args.seed, sid)), S)
            if LD:
                luat_doi.chinh_shop(args.luat_doi, S, args.seed, sid)
            if MR:
                S['kieu'] = sp.get('kieu', '')
                S['_layout'] = sp.get('layout') or None
                S['_tang_ho'] = sp.get('tang_ho') or {}
                MR.cau_hinh_them(random.Random('%s-k-%s' % (args.seed, sid)), S, S['kieu'], S['_layout'])
            sim.sim_retail(r, S)
            S['imap'] = {it['code']: it for it in S['items']}
            S['cmap'] = {c['id']: c for c in S.get('custs', [])}
            if MR:
                MR.sau_sim(random.Random('%s-s-%s' % (args.seed, sid)), S)
            if LD:
                LD.sau_sim(S, args.seed, sid)
            d = os.path.join(args.out, 'data', sid); os.makedirs(d)
            info = Ghi(random.Random('%s-w-%s' % (args.seed, sid)), S, d).chay()
            if MR:
                MR.sau_ghi(S, info)
            if LD:
                LD.chuan_bi(S)
            cau = sinh_cau(rq, S, n_cau, args.deu)
        all_S.append(S)
        for x in cau:
            h = hashlib.md5(('%s|%s|%s' % (sid, x['raw'], x['t'])).encode()).hexdigest()[:12]
            qs.append(dict(id='gq_' + h, business_id=sid, question=x['q'], as_of_date=x['t'].isoformat()))
            ans.append(dict(id='gq_' + h, type=x['type'], answer=x['answer'], alias=x['alias'], raw=x['raw'], ho=x['ho']))
            if args.loi_giai:
                lg.append(dict(id='gq_' + h, business_id=sid, as_of_date=x['t'].isoformat(), ho=x['ho'], cau_goc=x['raw'],
                               type=x['type'], ke_hoach=x['ke_hoach'], ghi_chu=x['ghi_chu']))
                if LD:
                    g = x['goc']
                    lg[-1].update(luat=args.luat_doi, dap_an_luat_goc=(None if g is None else {'type': g[0], 'answer': g[1]}),
                                  doi_dap_an=(None if g is None else (g[0], g[1]) != (x['type'], x['answer'])))
        meta.append(dict(id=sid, nganh=key, name=S['name'], start=str(S['start']), end=str(S['end']), cust_code=S.get('cust_code'),
                         options=[k for k in ('chans', 'pays', 'deposit', 'staff', 'odisc', 'stock', 'lots') if S.get(k)], **info))
        if MR:
            meta[-1]['kieu'] = sp.get('kieu', '')
        if LD:
            meta[-1]['luat_doi'] = args.luat_doi
        print(sid, key, info['layout'], info['readme'], len(S.get('orders', S.get('sessions', S.get('contracts', [])))), len(cau), flush=True)
    order = list(range(len(qs))); R.shuffle(order)
    with open(os.path.join(args.out, 'questions.jsonl'), 'w', encoding='utf-8', newline='\n') as f:
        for i in order:
            f.write(json.dumps(qs[i], ensure_ascii=False) + '\n')
    with open(os.path.join(args.out, 'answers.jsonl'), 'w', encoding='utf-8', newline='\n') as f:
        for i in order:
            f.write(json.dumps(ans[i], ensure_ascii=False, default=str) + '\n')
    json.dump(meta, open(os.path.join(args.out, '_shops.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    if LD:
        sids = [m['id'] for m in meta]
        cau = luat_doi.cau_cho_shop(args.luat_doi, sids, args.seed)
        luat_doi.viet_rulebook(os.path.join(args.gen, 'rulebook.md'), os.path.join(args.out, 'rulebook.md'), args.luat_doi,
                               [(m['id'], m['name']) for m in meta], cau)
        for m in meta:
            m['cau_luat'] = cau[m['id']]
        json.dump(meta, open(os.path.join(args.out, '_shops.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    else:
        shutil.copy(os.path.join(args.gen, 'rulebook.md'), os.path.join(args.out, 'rulebook.md'))
    if MR:
        MR.them_muc6(os.path.join(args.out, 'rulebook.md'), all_S)
    with open(os.path.join(args.out, 'calendar.csv'), 'w', encoding='utf-8', newline='') as f:
        w = csv.writer(f); cols = list(CAL_ROWS[0].keys()); w.writerow(cols)
        for r in CAL_ROWS:
            w.writerow([CAL[D.date.fromisoformat(r['date'])][c] for c in cols])
    if args.loi_giai:
        with open(os.path.join(args.out, 'loi_giai.jsonl'), 'w', encoding='utf-8', newline='\n') as f:
            for i in order:
                f.write(json.dumps(lg[i], ensure_ascii=False, default=str) + '\n')
    print(len(qs), 'câu')


main()
