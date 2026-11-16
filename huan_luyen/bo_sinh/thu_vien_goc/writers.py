"""Xuất dữ liệu bẩn: mỗi shop một kiểu file, ghi chép riêng. Mọi giá trị đều đọc lại được đúng."""
import os, csv, sqlite3, random, datetime as D, re
import openpyxl
from core import *

def xl(path, sheets):
    wb = openpyxl.Workbook(); wb.remove(wb.active)
    for name, rows in sheets:
        ws = wb.create_sheet(name)
        for r in rows: ws.append(list(r))
    wb.save(path)

def wcsv(path, header, rows, bom=True):
    with open(path, 'w', encoding='utf-8-sig' if bom else 'utf-8', newline='') as f:
        w = csv.writer(f); w.writerow(header)
        for r in rows: w.writerow(r)

WALKIN = ['Khách lẻ', 'khách lẻ', 'kl', 'lẻ', 'KHÁCH LẺ', 'Khach le']

def cust_label(R, c, with_phone=True):
    n = c['name']
    opts = [n, n, n, n.upper(), n.lower(), n + '  ', '  ' + n.replace(' ', '  ')]
    if with_phone: opts += [n + ' - ' + c['phone'], n + ' (' + c['phone'] + ')', n + ' ' + c['phone'][:4] + ' ' + c['phone'][4:7] + ' ' + c['phone'][7:]]
    return R.choice(opts)

def item_label(R, it):
    al = it.get('alias') or []
    if al and R.random() < 0.35: return R.choice(al)
    return R.choice([it['name'], it['name'], it['name'].lower(), it['name'] + ' '])

def status_label(R, st, table):
    return R.choice(table[st])

def readme(path, title, body):
    open(path, 'w', encoding='utf-8').write('# %s\n\n%s\n' % (title, body.strip()))

def item_order_lines(o): return [l for l in o['lines']]

# ======================================================================= 201 tiệm hoa
def w_flower(R, S, d):
    ST = {'done': [None, None, None, 'khách lấy tại tiệm', 'gói giấy kraft'], 'cancel': ['khách huỷ', 'hủy đơn', 'Huỷ - hết hoa'],
          'return': ['khách trả lại hoa', 'trả hàng - hoa héo'], 'ship': ['đang giao', 'shipper đang chở']}
    cm = S['cmap']
    by_year = {}
    for o in S['orders']: by_year.setdefault(o['date'].year, []).append(o)
    for y, os_ in by_year.items():
        sheets = []
        for m in range(1, 13):
            mo = [o for o in os_ if o['date'].month == m]
            if not mo: continue
            rows = [['SỔ BÁN HÀNG THÁNG %d' % m], [], ['Ngày', 'Giờ', 'Số HĐ', 'Khách', 'Hàng', 'ĐVT', 'SL', 'Đơn giá', 'Thành tiền', 'Ghi chú']]
            tot = 0
            for o in mo:
                c = cm.get(o['cust'])
                for i, l in enumerate(o['lines']):
                    it = S['imap'][l['code']]
                    vals = [item_label(R, it), l['unit'], l['qty'], fmt_money(R, l['price'], ['dot', 'plain', 'k']), fmt_money(R, l['amt'], ['dot', 'plain', 'k', 'dotd'])]
                    if i == 0:
                        row = ['%02d/%02d' % (o['date'].day, o['date'].month), '%02d:%02d' % o['t'][:2], o['id'],
                               cust_label(R, c) if c else R.choice(WALKIN)] + vals + [status_label(R, o['status'], ST)]
                    else:
                        row = ['', '', '', ''] + vals + ['']
                    rows.append(row)
                    if i > 0 and R.random() < 0.006: rows.append(list(row))
                    tot += l['amt']
            rows.append(['', '', '', 'CỘNG THÁNG', '', '', '', '', tot, ''])
            sheets.append(('T%d' % m, rows))
        xl(os.path.join(d, 'SoBanHang_%d.xlsx' % y), sheets)
    rows = [['Tên hàng', 'Tên gọi khác', 'Nhóm', 'ĐV cơ bản', 'Quy đổi']]
    for it in S['items']:
        rows.append([it['name'], ', '.join(it.get('alias', [])), it['group'], it['base'],
                     '; '.join('1 %s = %d %s' % (u, f, it['base']) for u, f in it['units'].items() if f > 1)])
    xl(os.path.join(d, 'DanhMuc.xlsx'), [('DanhMuc', rows)])
    rows = [['Hàng', 'Ngày áp dụng', 'Giá cũ', 'Giá mới']]
    for c, h in S['ph'].items():
        prev = None
        for dt_, p in h:
            rows.append([S['imap'][c]['name'], fmt_date(R, dt_, ['dmy', 'obj']), prev if prev else '', p]); prev = p
    xl(os.path.join(d, 'BangGia.xlsx'), [('BangGia', rows)])
    readme(os.path.join(d, 'README.md'), 'Dữ liệu biz_201', """
Tiệm hoa ghi sổ bán hàng tay trên Excel: mỗi năm một file `SoBanHang_<năm>.xlsx`, mỗi tháng một sheet (`T1`…`T12`). Hai dòng đầu mỗi sheet là tiêu đề; dòng cuối mỗi sheet là dòng `CỘNG THÁNG` (tổng tự cộng của chủ tiệm, không phải đơn).

## File
- `SoBanHang_2025.xlsx`, `SoBanHang_2026.xlsx` (xlsx)
- `DanhMuc.xlsx` (xlsx): danh mục hàng, tên gọi khác, nhóm hàng, đơn vị cơ bản, quy đổi
- `BangGia.xlsx` (xlsx): lịch sử giá bán

## Cột trong `SoBanHang_<năm>.xlsx`
- **Ngày**: ngày bán dạng `dd/mm`, không ghi năm
- **Giờ**: giờ tạo đơn
- **Số HĐ**: số hoá đơn
- **Khách**: tên khách (khách không lưu ghi Khách lẻ hoặc viết tắt); có lúc ghi kèm số điện thoại
- **Hàng**: tên hàng, có thể ghi theo tên gọi khác trong danh mục
- **ĐVT**, **SL**, **Đơn giá**, **Thành tiền**: thành tiền dòng (đã trừ giảm giá dòng)
- **Ghi chú**: ghi chú của đơn

## Quy ước
- Dữ liệu từ 01/01/2025 đến hết 30/06/2026.
- Ngày, giờ, số HĐ, khách, ghi chú chỉ ghi ở dòng đầu mỗi đơn; các dòng sau của đơn để trống các ô này.
- Sổ không có cột trạng thái: trạng thái đơn ghi trong **Ghi chú**.
- Không có mã khách.
- **Quy đổi**: đơn vị lớn theo `DanhMuc.xlsx` (vd `1 bó = 20 cành`); hàng không có dòng quy đổi chỉ bán theo đơn vị cơ bản.
- **Giá bán**: `Giá mới` (theo đơn vị cơ bản) áp dụng từ `Ngày áp dụng` đến trước lần đổi giá sau; dòng đầu mỗi hàng là giá lúc bắt đầu dữ liệu.
""")

# ======================================================================= 202 cá cảnh
CHAN_VN = {'store': ['Tại cửa hàng', 'tai cua hang', 'Cửa hàng'], 'zalo': ['Zalo'], 'facebook': ['Facebook', 'FB'], 'shopee': ['Shopee', 'Sàn Shopee'],
           'grab': ['GrabFood'], 'shopeefood': ['ShopeeFood']}
PAY_VN = {'cash': ['Tiền mặt', 'TM', 'tien mat'], 'transfer': ['Chuyển khoản', 'CK'], 'ewallet': ['Ví điện tử', 'Momo'], 'cod': ['COD', 'Thu hộ COD'],
          'debt': ['Ghi nợ', 'Nợ']}

def dirty_id(R, s):
    return R.choice([s, s, s, ' ' + s, s + ' ', '  ' + s, s + '  '])

def w_fish(R, S, d):
    ST = {'done': ['Hoàn thành', 'Đã giao', 'hoàn thành'], 'cancel': ['Đã huỷ', 'Huỷ'], 'return': ['Trả hàng', 'Khách trả'], 'ship': ['Đang giao']}
    rows = []; det = []; pays = []; rets = []
    pid = 0; cur_m = None; mtot = 0
    for o in S['orders']:
        m = (o['date'].year, o['date'].month)
        if cur_m and m != cur_m:
            rows.append(['Tổng tháng %d/%d' % (cur_m[1], cur_m[0]), '', '', '', '', '', '', '', fmt_money(R, mtot, ['dot'])]); mtot = 0
            if R.random() < 0.3: rows.append(['Mã đơn', 'Thời gian', 'Mã KH', 'Kênh', 'Thanh toán', 'Trạng thái', 'Giảm giá đơn', 'Phí ship', 'Tổng phải trả'])
        cur_m = m; mtot += o['due']
        rows.append([o['id'], fmt_date(R, o['date'], ['dmy', 'dmy', 'iso'], o['t'][:2]), o['cust'] or '', R.choice(CHAN_VN[o['chan']]),
                     R.choice(PAY_VN[o['pay']]), R.choice(ST[o['status']]), fmt_money(R, o['odisc'], ['plain', 'dot']),
                     fmt_money(R, o['ship'], ['plain', 'dot', 'k']), fmt_money(R, o['due'], ['plain', 'dot', 'dotd'])])
        for i, l in enumerate(o['lines'], 1):
            r = [dirty_id(R, o['id']), i, dirty_id(R, l['code']), l['unit'], l['qty'], fmt_money(R, l['price'], ['plain', 'dot', 'k']),
                 fmt_money(R, l['disc'], ['plain', 'dot']), fmt_money(R, l['amt'], ['plain', 'dot', 'dotd', 'k']),
                 'đổi cá chết (bảo hành 3 ngày)' if l['kind'] == 'exchange' else '']
            det.append(r)
            if R.random() < 0.004: det.append(list(r))
        for dt_, a, k in o['payments']:
            pid += 1
            pays.append(['PT%06d' % pid, dirty_id(R, o['id']), fmt_date(R, dt_, ['dmy', 'iso'], (R.randint(8, 21), R.randint(0, 59))),
                         fmt_money(R, a, ['plain', 'dot', 'k', 'tr', 'dotd']), {'cod': 'COD', 'trả': 'Trả nợ' if dt_ > o['date'] else 'Thu tại quầy'}.get(k, R.choice(PAY_VN.get(k, ['Tiền mặt'])))])
        if o['status'] == 'return':
            for i, q in o['ret_lines']:
                rets.append([o['id'], fmt_date(R, o['ret_date'], ['dmy']), o['lines'][i]['code'], num_out(q)])
    rows.append(['Tổng tháng %d/%d' % (cur_m[1], cur_m[0]), '', '', '', '', '', '', '', fmt_money(R, mtot, ['dot'])])
    wcsv(os.path.join(d, 'don_hang.csv'), ['Mã đơn', 'Thời gian', 'Mã KH', 'Kênh', 'Thanh toán', 'Trạng thái', 'Giảm giá đơn', 'Phí ship', 'Tổng phải trả'], rows)
    wcsv(os.path.join(d, 'chi_tiet_don.csv'), ['Mã đơn', 'STT', 'Mã SP', 'ĐVT', 'SL', 'Đơn giá', 'Chiết khấu', 'Thành tiền', 'Ghi chú'], det)
    wcsv(os.path.join(d, 'thanh_toan.csv'), ['Mã phiếu', 'Mã đơn', 'Ngày giờ thu', 'Số tiền', 'Loại'], pays)
    wcsv(os.path.join(d, 'tra_hang.csv'), ['Mã đơn', 'Ngày trả', 'Mã SP', 'SL trả (ĐV cơ bản)'], rets)
    wcsv(os.path.join(d, 'san_pham.csv'), ['Mã SP', 'Tên sản phẩm', 'Nhóm', 'ĐV cơ bản', 'Giá vốn (ĐV cơ bản)', 'Quy đổi'],
         [[it['code'], it['name'], it['group'], it['base'], it['cost'], ';'.join('%s=%d' % (u, f) for u, f in it['units'].items() if f > 1)] for it in S['items']])
    wcsv(os.path.join(d, 'khach_hang.csv'), ['Mã KH', 'Tên khách', 'SĐT', 'Nhóm KH', 'Ngày tham gia'],
         [[c['id'], c['name'], c['phone'], c['group'], fmt_date(R, c['reg'], ['dmy'])] for c in S['custs']])
    prow = []
    for p in S['purchases']:
        for l in p['lines']:
            prow.append([p['id'], fmt_date(R, p['date'], ['dmy', 'iso']), p['sup'], l['code'], l['unit'], l['qty'], fmt_money(R, l['price'], ['plain', 'dot']),
                         fmt_money(R, l['amt'], ['plain', 'dot']), 'Huỷ phiếu' if p['cancel'] else 'Đã nhập', 'nhập đầu kỳ' if p['first'] else ''])
    wcsv(os.path.join(d, 'nhap_hang.csv'), ['Số phiếu', 'Ngày nhập', 'Nhà cung cấp', 'Mã SP', 'ĐVT nhập', 'SL nhập', 'Giá nhập', 'Thành tiền', 'Trạng thái', 'Ghi chú'], prow)
    readme(os.path.join(d, 'README.md'), 'Dữ liệu biz_202', """
Phần mềm bán hàng của trại cá cảnh xuất ra nhiều file CSV, nối với nhau qua mã đơn, mã sản phẩm, mã khách. Các file xuất thủ công nên mã có thể dính khoảng trắng thừa ở đầu, cuối.

## File
- `don_hang.csv`: **Mã đơn**, **Thời gian** (ngày giờ đặt), **Mã KH** (trống: khách lẻ), **Kênh**, **Thanh toán** (hình thức ghi trên đơn), **Trạng thái**, **Giảm giá đơn** (giảm trên cả đơn), **Phí ship**, **Tổng phải trả** (= tổng thành tiền dòng − giảm giá đơn + phí ship). File có dòng tổng tháng tự cộng (`Tổng tháng m/yyyy`) và đôi khi lặp lại dòng tiêu đề.
- `chi_tiet_don.csv`: mỗi dòng một dòng hàng: **SL** theo **ĐVT** của dòng, **Đơn giá**, **Chiết khấu** (giảm của dòng), **Thành tiền** (sau chiết khấu), **Ghi chú**.
- `thanh_toan.csv`: mỗi lần thu tiền của một đơn một dòng: **Ngày giờ thu**, **Số tiền**.
- `tra_hang.csv`: hàng khách trả: **Ngày trả**, **SL trả** theo đơn vị cơ bản.
- `san_pham.csv`: **Giá vốn** theo đơn vị cơ bản; **Quy đổi** `đơn vị lớn=hệ số` (số đơn vị cơ bản trong 1 đơn vị lớn).
- `khach_hang.csv`: **Nhóm KH** là nhóm khách.
- `nhap_hang.csv`: mỗi dòng một dòng của phiếu nhập; **Thành tiền** là tiền nhập của dòng; **Trạng thái** `Huỷ phiếu` là phiếu huỷ.

## Quy ước
- Dữ liệu từ 01/03/2025 đến hết 15/09/2026.
- Ngày ghi `dd/mm/yyyy` (ngày trước tháng) hoặc `yyyy-mm-dd`.
- **Đổi cá chết**: cá chết trong 3 ngày được đổi con khác cùng loại; dòng đổi ghi chú `đổi cá chết`, đơn giá 0. Dòng đổi xuất kho nhưng không phải lượt bán.
- **Tồn kho**: tồn tại một thời điểm = tổng nhập (phiếu không huỷ) − tổng xuất theo đơn không huỷ (kể cả dòng đổi cá) + hàng khách trả (theo ngày trả), tính từ đầu dữ liệu. Phiếu `nhập đầu kỳ` là tồn đầu.
""")

# ======================================================================= 205 in 3D
def w_print3d(R, S, d):
    ST = {'done': ['Đã giao', 'Hoàn tất', 'xong'], 'cancel': ['Huỷ', 'Khách hủy'], 'return': ['Trả lại', 'Khách trả'], 'ship': ['Đang giao', 'Đang giao hàng']}
    hdr = ['Ngày đặt', 'Mã đơn', 'Mã KH', 'Khách', 'Kênh', 'Thợ phụ trách', 'Trạng thái', 'Mã hàng', 'Tên hàng', 'ĐVT', 'SL', 'Đơn giá', 'Giảm', 'Thành tiền',
           'Giá vốn/ĐV', 'Tổng đơn']
    rows = [['XƯỞNG IN 3D LỚP NHỰA - CHI TIẾT ĐƠN HÀNG'], ['Xuất lúc 20/08/2026 23:59'], [], hdr]
    pay = [['Ngày', 'Mã đơn', 'Loại', 'Số tiền']]
    cm = S['cmap']
    for k, o in enumerate(S['orders']):
        if k and k % 1500 == 0: rows.append(hdr)
        c = cm.get(o['cust'])
        for l in o['lines']:
            it = S['imap'][l['code']]
            r = [fmt_date(R, o['date'], ['obj', 'dmy', 'serial'], o['t'][:2]), o['id'], o['cust'] or '', c['name'] if c else R.choice(WALKIN), R.choice(CHAN_VN[o['chan']]),
                 o['staff'], R.choice(ST[o['status']]), l['code'], it['name'], l['unit'], l['qty'], l['price'], l['disc'], l['amt'], l['cost'], o['due']]
            rows.append(r)
            if R.random() < 0.004: rows.append(list(r))
        for dt_, a, kk in o['payments']:
            pay.append([fmt_date(R, dt_, ['dmy', 'obj']), dirty_id(R, o['id']), 'Cọc' if kk == 'cọc' else R.choice(['Thanh toán', 'Trả nốt', 'TT']), fmt_money(R, a, ['plain', 'dot', 'k', 'tr'])])
    xl(os.path.join(d, 'DonHang_ChiTiet.xlsx'), [('Data', rows)])
    xl(os.path.join(d, 'PhieuThu.xlsx'), [('PhieuThu', pay)])
    xl(os.path.join(d, 'KhachHang.xlsx'), [('KH', [['Mã KH', 'Tên', 'SĐT', 'Nhóm khách']] + [[c['id'], c['name'], c['phone'], c['group']] for c in S['custs']])])
    xl(os.path.join(d, 'DanhMuc.xlsx'), [('DM', [['Mã hàng', 'Tên hàng', 'Nhóm', 'ĐVT', 'Quy đổi']] +
        [[it['code'], it['name'], it['group'], it['base'], '; '.join('1 %s = %d %s' % (u, f, it['base']) for u, f in it['units'].items() if f > 1)] for it in S['items']])])
    readme(os.path.join(d, 'README.md'), 'Dữ liệu biz_205', """
Xưởng in 3D nhận đơn in theo khối lượng nhựa, bán sản phẩm in sẵn và làm dịch vụ. Mọi đơn đều thu **tiền cọc** lúc đặt, phần còn lại trả khi lấy hàng (có thể trả nhiều lần).

## File
- `DonHang_ChiTiet.xlsx`, sheet `Data`: 3 dòng đầu là tiêu đề xuất file; dòng tiêu đề cột lặp lại giữa file. Mỗi dòng một dòng hàng, thông tin đơn lặp lại ở mọi dòng: **Ngày đặt** (ngày giờ), **Mã đơn**, **Mã KH** (trống: khách lẻ), **Khách**, **Kênh**, **Thợ phụ trách** (mã thợ), **Trạng thái**, **Mã hàng**, **Tên hàng**, **ĐVT**, **SL**, **Đơn giá**, **Giảm** (giảm của dòng), **Thành tiền** (sau giảm), **Giá vốn/ĐV** (giá vốn một đơn vị bán của dòng), **Tổng đơn** (số khách phải trả cả đơn).
- `PhieuThu.xlsx`: mỗi lần thu tiền một dòng; **Loại** `Cọc` là tiền cọc lúc đặt, loại khác là tiền trả sau.
- `KhachHang.xlsx`, `DanhMuc.xlsx`.

## Quy ước
- Dữ liệu từ 01/02/2025 đến hết 20/08/2026. Ngày có thể là ô ngày của Excel, số ngày kiểu Excel (serial) hoặc chữ `dd/mm/yyyy hh:mm`.
- **Tiền cọc**: cọc là một phần tiền khách trả cho đơn. Đơn huỷ không hoàn cọc.
""")

# ======================================================================= 206 tạp hoá
def w_grocery(R, S, d):
    ST = {'done': ['', '', 'đã thanh toán', 'xong'], 'cancel': ['huỷ', 'khách không lấy nữa - huỷ'], 'return': ['trả lại', 'khách đem trả'], 'ship': ['đang chở lên bản']}
    cm = S['cmap']
    for y in (2025, 2026):
        rows = [['Ngày', 'Số phiếu', 'Khách hàng', 'Mã hàng', 'Tên hàng', 'Đơn vị', 'SL', 'Giá', 'Thành tiền', 'Tình trạng']]
        for o in S['orders']:
            if o['date'].year != y: continue
            c = cm.get(o['cust']); lab = cust_label(R, c) if c else R.choice(WALKIN); stl = R.choice(ST[o['status']])
            dd = fmt_date(R, o['date'], ['obj', 'serial', 'dmy1', 'thg'])
            for l in o['lines']:
                it = S['imap'][l['code']]
                r = [dd, o['id'], lab, l['code'], item_label(R, it), l['unit'], l['qty'], fmt_money(R, l['price'], ['plain', 'dot', 'k', 'space']),
                     fmt_money(R, l['amt'], ['plain', 'dot', 'k', 'space', 'tr']), stl]
                rows.append(r)
                if R.random() < 0.008: rows.append(list(r))
        xl(os.path.join(d, 'So_ban_hang_%d.xlsx' % y), [('Sheet1', rows)])
    rr = [['Số phiếu', 'Ngày trả', 'Mã hàng', 'SL trả', 'Đơn vị']]
    for o in S['orders']:
        if o['status'] == 'return':
            for i, q in o['ret_lines']:
                l = o['lines'][i]; it = S['imap'][l['code']]
                rr.append([o['id'], fmt_date(R, o['ret_date'], ['dmy1']), l['code'], num_out(q), it['base']])
    xl(os.path.join(d, 'TraHang.xlsx'), [('TraHang', rr)])
    dm = [['Mã hàng', 'Tên hàng', 'Nhóm', 'ĐV nhỏ nhất', 'Giá vốn', 'Quy đổi']]
    for it in S['items']:
        dm.append([it['code'], it['name'], it['group'], it['base'], it['cost'], '; '.join('1 %s = %d %s' % (c[0], c[2], c[1]) for c in it.get('chain', []))])
    xl(os.path.join(d, 'DanhMuc.xlsx'), [('DanhMuc', dm)])
    pr = [['Ngày nhập', 'Số phiếu', 'Nơi lấy hàng', 'Mã hàng', 'Đơn vị', 'SL', 'Giá nhập', 'Thành tiền', 'Ghi chú']]
    for p in S['purchases']:
        for l in p['lines']:
            pr.append([fmt_date(R, p['date'], ['dmy1', 'obj']), p['id'], p['sup'], l['code'], l['unit'], l['qty'], l['price'], l['amt'],
                       'phiếu huỷ, không nhập' if p['cancel'] else ('nhập đầu kỳ' if p['first'] else '')])
    xl(os.path.join(d, 'NhapHang.xlsx'), [('NhapHang', pr)])
    bg = [['Mã hàng', 'Từ ngày', 'Giá (ĐV nhỏ nhất)']]
    for c, h in S['ph'].items():
        for dt_, p in h: bg.append([c, fmt_date(R, dt_, ['dmy1']), p])
    xl(os.path.join(d, 'BangGia.xlsx'), [('BangGia', bg)])
    readme(os.path.join(d, 'README.md'), 'Dữ liệu biz_206', """
Tạp hoá ở chợ phiên vùng cao, sổ bán hàng tách theo năm. Mỗi dòng một mặt hàng của một phiếu; thông tin phiếu lặp lại ở mọi dòng.

## File
- `So_ban_hang_2025.xlsx`, `So_ban_hang_2026.xlsx`: **Ngày**, **Số phiếu**, **Khách hàng** (tên khách; khách không lưu ghi khách lẻ, kl, lẻ…; có khi kèm số điện thoại), **Mã hàng**, **Tên hàng** (có thể viết thường), **Đơn vị** (đơn vị của dòng), **SL**, **Giá**, **Thành tiền** (thành tiền dòng), **Tình trạng** (trống là đã xong).
- `TraHang.xlsx`: hàng khách đem trả: **SL trả** theo đơn vị nhỏ nhất.
- `DanhMuc.xlsx`: **ĐV nhỏ nhất** là đơn vị cơ bản; **Giá vốn** theo đơn vị cơ bản; **Quy đổi** ghi theo bậc, mỗi bậc là số đơn vị **ngay dưới** trong 1 đơn vị lớn (vd `1 thùng = 4 lốc; 1 lốc = 6 lon`).
- `NhapHang.xlsx`: mỗi dòng một dòng phiếu nhập; ghi chú `phiếu huỷ` là phiếu huỷ; `nhập đầu kỳ` là hàng có sẵn lúc bắt đầu sổ.
- `BangGia.xlsx`: giá bán theo đơn vị nhỏ nhất áp dụng từ ngày ghi đến trước lần đổi sau.

## Quy ước
- Dữ liệu từ 01/01/2025 đến hết 15/07/2026.
- **Ngày** có nhiều cách ghi: ô ngày Excel, số serial Excel, `d/m/yyyy` (ngày trước tháng), `d thg m yyyy`.
- Tiền có thể ghi `12.000`, `12 000`, `12k`, `1,2tr`.
- **Tồn kho** tại một thời điểm = nhập (phiếu không huỷ, gồm nhập đầu kỳ) − bán theo phiếu không huỷ + hàng trả (theo ngày trả), quy về đơn vị nhỏ nhất.
""")

# ======================================================================= 207 sách ký gửi
def w_books(R, S, d):
    ST = {'done': ['Hoàn tất', 'Đã bán'], 'cancel': ['Huỷ'], 'return': ['Trả lại'], 'ship': ['Đang giao']}
    rows = []
    for o in S['orders']:
        for l in o['lines']:
            it = S['imap'][l['code']]
            r = [o['id'], fmt_date(R, o['date'], ['dmy', 'dmy']), '%02d:%02d' % o['t'][:2], o['cust'] or '', R.choice(CHAN_VN[o['chan']]),
                 R.choice(PAY_VN[o['pay']]), R.choice(ST[o['status']]), dirty_id(R, l['code']), R.choice([it['name'], it['name'].upper(), it['name'] + ' (cũ)']),
                 l['qty'], fmt_money(R, l['price'], ['plain', 'dot', 'k']), fmt_money(R, l['disc'], ['plain']), fmt_money(R, l['amt'], ['plain', 'dot', 'k']),
                 fmt_money(R, o['ship'], ['plain', 'k']), fmt_date(R, o['ret_date'], ['dmy']) if o['status'] == 'return' and any(o['lines'][i] is l for i, _ in o['ret_lines']) else '']
            rows.append(r)
            if R.random() < 0.005: rows.append(list(r))
    wcsv(os.path.join(d, 'ban_hang.csv'), ['ma_hd', 'ngay', 'gio', 'the_thanh_vien', 'kenh', 'thanh_toan', 'trang_thai', 'ma_sach', 'ten_sach', 'sl', 'gia', 'giam',
                                           'thanh_tien', 'phi_ship_don', 'ngay_khach_tra'], rows)
    wcsv(os.path.join(d, 'sach.csv'), ['ma_sach', 'ten_sach', 'the_loai', 'nguon', 'gia_von'],
         [[it['code'], it['name'], it['group'], 'Tiệm' if it['owner'] == 'Tiệm' else 'Ký gửi - ' + it['owner'], it['cost']] for it in S['items']])
    wcsv(os.path.join(d, 'chu_ky_gui.csv'), ['chu_ky_gui', 'hoa_hong_tiem_phan_tram'], [[k, v] for k, v in S['owners'].items()])
    wcsv(os.path.join(d, 'thanh_vien.csv'), ['the_thanh_vien', 'ho_ten', 'sdt', 'hang_the'], [[c['id'], c['name'], c['phone'], c['group']] for c in S['custs']])
    pr = []
    for p in S['purchases']:
        for l in p['lines']:
            it = S['imap'][l['code']]
            pr.append([p['id'], fmt_date(R, p['date'], ['dmy']), p['sup'] if it['owner'] == 'Tiệm' else it['owner'], l['code'], l['qty'], l['price'], l['amt'],
                       'huỷ' if p['cancel'] else ('nhận ký gửi' if it['owner'] != 'Tiệm' else 'mua vào'), 'x' if p['first'] else ''])
    wcsv(os.path.join(d, 'nhap_sach.csv'), ['so_phieu', 'ngay', 'nguon_nhap', 'ma_sach', 'sl', 'gia_nhap', 'thanh_tien', 'loai', 'dau_ky'], pr)
    readme(os.path.join(d, 'README.md'), 'Dữ liệu biz_207', """
Tiệm sách cũ vừa bán sách của tiệm vừa nhận sách **ký gửi**: chủ ký gửi để sách ở tiệm, tiệm bán hộ và giữ lại phần trăm hoa hồng, phần còn lại trả cho chủ.

## File
- `ban_hang.csv`: mỗi dòng một cuốn/dòng sách của một hoá đơn; thông tin hoá đơn lặp lại ở mọi dòng. `the_thanh_vien` trống là khách lẻ. `phi_ship_don` là phí giao của cả hoá đơn (lặp lại). `ngay_khach_tra` ghi ở dòng sách bị khách trả.
- `sach.csv`: `nguon` là `Tiệm` hoặc `Ký gửi - <chủ>`; `gia_von` theo cuốn (sách ký gửi: 0).
- `chu_ky_gui.csv`: phần trăm hoa hồng tiệm giữ lại trên tiền bán sách của từng chủ.
- `thanh_vien.csv`: thẻ thành viên, `hang_the` là nhóm khách.
- `nhap_sach.csv`: dòng phiếu nhập; `loai` = `mua vào`, `nhận ký gửi` (không mất tiền) hoặc `huỷ`; `dau_ky` = `x` là tồn đầu kỳ.

## Quy ước
- Dữ liệu từ 01/05/2025 đến hết 10/09/2026. Ngày `dd/mm/yyyy`.
- Mã sách có thể dính khoảng trắng thừa. Tên sách có thể viết hoa toàn bộ hoặc kèm chữ `(cũ)`.
- **Tồn kho** = nhập (không huỷ) − bán theo hoá đơn không huỷ + sách khách trả (theo ngày trả).
""")

# ======================================================================= 208 chè
def w_dessert(R, S, d):
    ST = {'done': ['Hoàn thành', 'Đã xong'], 'cancel': ['Đã hủy', 'Huỷ đơn'], 'return': ['Hoàn tiền'], 'ship': ['Đang giao']}
    by = {}
    for o in S['orders']: by.setdefault((o['date'].year, o['date'].month), []).append(o)
    cm = S['cmap']
    for (y, m), os_ in by.items():
        rows = [['Mã đơn', 'Ngày', 'Giờ', 'Khách', 'Kênh', 'Thanh toán', 'Trạng thái', 'Món', 'SL', 'Đơn giá', 'Thành tiền']]
        for o in os_:
            c = cm.get(o['cust']); lab = c['name'] if c else R.choice(['Khách lẻ', 'kl', ''])
            head = [o['id'], fmt_date(R, o['date'], ['dmy']), '%02d:%02d' % o['t'][:2], lab, R.choice(CHAN_VN[o['chan']]), R.choice(PAY_VN[o['pay']]),
                    R.choice(ST[o['status']])]
            ls = o['lines']; used = set()
            for i, l in enumerate(ls):
                if i in used: continue
                it = S['imap'][l['code']]
                if l['kind'] == 'topping':
                    rows.append(head + [it['name'], l['qty'], l['price'], fmt_money(R, l['amt'], ['plain', 'dot'])]); continue
                kids = [j for j, x in enumerate(ls) if x['kind'] == 'topping' and x['parent'] == i]
                inline = [j for j in kids if R.random() < 0.65]
                name = it['name']; amt = l['amt']
                for j in inline:
                    t_ = ls[j]; tn = S['imap'][t_['code']]['name'].replace('Topping ', '')
                    name += ' + ' + ('%d ' % t_['qty'] if t_['qty'] > 1 else '') + tn + ' (%s)' % ('{:,}'.format(t_['amt']).replace(',', '.') + 'đ')
                    amt += t_['amt']; used.add(j)
                rows.append(head + [name, l['qty'], l['price'], fmt_money(R, amt, ['plain', 'dot', 'k'])])
        xl(os.path.join(d, 'BanHang_T%d_%d.xlsx' % (m, y)), [('DonHang', rows)])
    xl(os.path.join(d, 'DanhSachMon.xlsx'), [('Mon', [['Mã món', 'Tên món', 'Nhóm', 'ĐVT', 'Giá']] + [[it['code'], it['name'], it['group'], it['base'], it['price']] for it in S['items']])])
    rows = [['Món', 'Ngày áp dụng', 'Giá mới']]
    for c, h in S['ph'].items():
        for dt_, p in h: rows.append([S['imap'][c]['name'], fmt_date(R, dt_, ['dmy']), p])
    xl(os.path.join(d, 'LichSuGia.xlsx'), [('Gia', rows)])
    readme(os.path.join(d, 'README.md'), 'Dữ liệu biz_208', """
Quán chè xuất đơn hàng theo tháng, mỗi tháng một file `BanHang_T<tháng>_<năm>.xlsx` (sheet `DonHang`). Mỗi dòng một món của đơn, thông tin đơn lặp lại ở mọi dòng.

## Cột
- **Mã đơn**, **Ngày** (`dd/mm/yyyy`), **Giờ** (giờ tạo đơn), **Khách** (thường để trống hoặc Khách lẻ), **Kênh**, **Thanh toán**, **Trạng thái**.
- **Món**: tên món; topping có thể ghi chung ô với món, nối bằng ` + `; số đứng trước tên topping là số phần (không ghi là 1 phần), tiền topping ghi trong ngoặc và **đã cộng** vào **Thành tiền** của dòng. Tên topping ghi chung ô không kèm chữ `Topping`. Topping cũng có thể ghi dòng riêng.
- **SL**, **Đơn giá**: của món (không gồm topping ghi chung ô). **Thành tiền**: tiền dòng.
- `DanhSachMon.xlsx`: danh mục món; size ghi trong tên món `(M)`, `(L)`. `LichSuGia.xlsx`: giá áp dụng từ ngày ghi.

## Quy ước
- Dữ liệu từ 01/01/2025 đến hết 31/05/2026.
- Trạng thái `Hoàn tiền` là đơn khách trả hàng.
""")

# ======================================================================= 209 thú y
def w_vet(R, S, d):
    ST = {'done': ['Hoàn thành', 'completed'], 'cancel': ['Đã huỷ', 'cancelled'], 'return': ['Trả hàng', 'returned'], 'ship': ['Đang giao']}
    hd = [['Mã HĐ', 'Ngày giờ', 'Mã KH', 'Nhân viên', 'Thanh toán', 'Trạng thái', 'Tổng tiền', 'Ngày trả hàng']]
    ct = [['Mã HĐ', 'Dòng', 'Mã SP', 'ĐVT', 'SL', 'SL quy đổi', 'Đơn giá', 'Giảm', 'Thành tiền']]
    xl_ = [['Mã HĐ', 'Dòng', 'Số lô', 'SL xuất (ĐVCB)', 'SL trả (ĐVCB)']]
    pays = [['Mã HĐ', 'Ngày thu', 'Số tiền']]
    for o in S['orders']:
        hd.append([o['id'], fmt_date(R, o['date'], ['obj', 'dmy'], o['t'][:2]), o['cust'] or '', o['staff'], R.choice(PAY_VN[o['pay']]), R.choice(ST[o['status']]),
                   o['due'], fmt_date(R, o['ret_date'], ['dmy']) if o['ret_date'] else ''])
        for i, l in enumerate(o['lines'], 1):
            ct.append([o['id'], i, l['code'], l['unit'], l['qty'], num_out(l['qb']), l['price'], l['disc'], l['amt']])
            for a in l.get('alloc', []):
                xl_.append([o['id'], i, a[0], num_out(a[1]), num_out(a[2]) if len(a) > 2 and o['status'] == 'return' else 0])
        if o['pay'] == 'debt':
            for dt_, a, k in o['payments']: pays.append([o['id'], fmt_date(R, dt_, ['dmy']), fmt_money(R, a, ['plain', 'dot', 'k'])])
    xl(os.path.join(d, 'HoaDon.xlsx'), [('HoaDon', hd)])
    xl(os.path.join(d, 'HoaDonChiTiet.xlsx'), [('ChiTiet', ct)])
    xl(os.path.join(d, 'XuatTheoLo.xlsx'), [('XuatLo', xl_)])
    xl(os.path.join(d, 'ThuNo.xlsx'), [('ThuNo', pays)])
    RX = {True: ['Có', 'x', 'TRUE', '1'], False: ['Không', '', 'FALSE', '0']}
    sp = [['Mã SP', 'Tên sản phẩm', 'Nhóm', 'ĐVCB', 'Giá vốn (ĐVCB)', 'Kê đơn', 'Hoạt chất']]
    for it in S['items']: sp.append([it['code'], it['name'], it['group'], it['base'], it['cost'], R.choice(RX[bool(it.get('rx'))]), it.get('ing', '')])
    xl(os.path.join(d, 'SanPham.xlsx'), [('SanPham', sp)])
    qd = [['Mã SP', 'Đơn vị', 'Hệ số']] + [[it['code'], u, f] for it in S['items'] for u, f in it['units'].items() if f > 1]
    xl(os.path.join(d, 'QuyDoi.xlsx'), [('QuyDoi', qd)])
    nl = [['Số phiếu', 'Ngày nhập', 'Nhà cung cấp', 'Mã SP', 'Số lô', 'Hạn dùng', 'ĐV nhập', 'SL nhập', 'Giá nhập', 'Thành tiền', 'Trạng thái']]
    for p in S['purchases']:
        for l in p['lines']:
            nl.append([p['id'], fmt_date(R, p['date'], ['dmy', 'obj']), p['sup'], l['code'], l['lot'], fmt_date(R, l['exp'], ['dmy', 'iso']), l['unit'], l['qty'],
                       l['price'], l['amt'], 'Huỷ' if p['cancel'] else ('Tồn đầu kỳ' if p['first'] else 'Đã nhập')])
    xl(os.path.join(d, 'NhapHangTheoLo.xlsx'), [('NhapLo', nl)])
    xl(os.path.join(d, 'KhachHang.xlsx'), [('KH', [['Mã KH', 'Chủ nuôi', 'SĐT', 'Nhóm khách']] + [[c['id'], c['name'], c['phone'], c['group']] for c in S['custs']])])
    readme(os.path.join(d, 'README.md'), 'Dữ liệu biz_209', """
Nhà thuốc thú y quản lý thuốc theo lô và hạn dùng. Các file nối nhau qua mã hoá đơn, mã sản phẩm, số lô.

## File
- `HoaDon.xlsx`: **Tổng tiền** là số khách phải trả cả hoá đơn; **Ngày trả hàng** ghi ở hoá đơn khách trả hàng.
- `HoaDonChiTiet.xlsx`: **SL quy đổi** là số lượng theo đơn vị cơ bản; **Thành tiền** đã trừ **Giảm** của dòng.
- `XuatTheoLo.xlsx`: mỗi dòng bán lấy từ một hay nhiều lô: **SL xuất**, **SL trả** (hàng khách trả về lại đúng lô đã xuất) theo đơn vị cơ bản.
- `ThuNo.xlsx`: các lần thu tiền của hoá đơn ghi nợ (cả lần trả ngay lúc mua).
- `SanPham.xlsx`: **Kê đơn** (`Có`, `x`, `TRUE`, `1` là thuốc kê đơn), **Hoạt chất** (nhiều chất nối bằng ` + `), **Giá vốn** theo đơn vị cơ bản.
- `QuyDoi.xlsx`: hệ số = số đơn vị cơ bản trong 1 đơn vị lớn.
- `NhapHangTheoLo.xlsx`: mỗi dòng nhập là một lô; **Giá nhập** theo **ĐV nhập** của dòng; **Trạng thái** `Huỷ` là phiếu huỷ (không vào kho); `Tồn đầu kỳ` là hàng có sẵn.

## Quy ước
- Dữ liệu từ 01/04/2025 đến hết 31/08/2026.
""")

# ======================================================================= 203 phòng net
def w_net(R, S, d):
    p = os.path.join(d, 'pixel.sqlite')
    if os.path.exists(p): os.remove(p)
    db = sqlite3.connect(p); c = db.cursor()
    c.execute('create table may_tram (ma_may text, khu text)')
    c.executemany('insert into may_tram values (?,?)', [(m['id'], m['zone']) for m in S['machines']])
    c.execute('create table bang_gia_gio (khu text, ap_dung_tu text, gia_moi_gio integer)')
    for z, v in {'thường': 8000, 'VIP': 12000, 'thi đấu': 18000}.items():
        c.execute('insert into bang_gia_gio values (?,?,?)', (z, S['start'].isoformat(), v))
        c.execute('insert into bang_gia_gio values (?,?,?)', (z, S['rate_change'][0].isoformat(), S['rate_change'][1][z]))
    c.execute('create table hoi_vien (ma_hv text, ho_ten text)')
    c.executemany('insert into hoi_vien values (?,?)', [(m['id'], m['name']) for m in S['members']])
    c.execute('create table phien_choi (ma_phien text, ma_may text, ma_hv text, bat_dau text, ket_thuc text, so_phut integer, tien_gio integer, thanh_toan text, tinh_trang text)')
    c.executemany('insert into phien_choi values (?,?,?,?,?,?,?,?,?)',
                  [(s['id'], s['machine'], s['mem'], s['st'].strftime('%Y-%m-%d %H:%M'), s['en'].strftime('%d/%m/%Y %H:%M'), s['mins'], s['gross'], s['pay'], s['status'])
                   for s in S['sessions']])
    c.execute('create table nap_tien (ma_nap text, ma_hv text, thoi_gian text, so_tien_nap integer, tien_tang integer, hinh_thuc text)')
    c.executemany('insert into nap_tien values (?,?,?,?,?,?)', [(t['id'], t['mem'], t['ts'].strftime('%Y-%m-%d %H:%M'), t['amt'], t['bonus'], t['method']) for t in S['topups']])
    c.execute('create table mon (ma_mon text, ten_mon text, nhom text, gia integer)')
    c.executemany('insert into mon values (?,?,?,?)', [(it['code'], it['name'], it['group'], it['price']) for it in S['menu']])
    c.execute('create table don_do_an (ma_don text, ma_phien text, ma_may text, thoi_gian text, tinh_trang text)')
    c.executemany('insert into don_do_an values (?,?,?,?,?)', [(f['id'], f['sess'], f['machine'], f['ts'].strftime('%Y-%m-%d %H:%M'), f['status']) for f in S['food']])
    c.execute('create table chi_tiet_do_an (ma_don text, ma_mon text, so_luong integer, don_gia integer, thanh_tien integer)')
    c.executemany('insert into chi_tiet_do_an values (?,?,?,?,?)', [(f['id'], l['code'], l['qty'], l['price'], l['amt']) for f in S['food'] for l in f['lines']])
    db.commit(); db.close()
    readme(os.path.join(d, 'README.md'), 'Dữ liệu biz_203', """
Phần mềm quản lý phòng máy xuất ra một file SQLite `pixel.sqlite`.

## Bảng
- `may_tram`: máy và khu (`thường`, `VIP`, `thi đấu`).
- `bang_gia_gio`: giá một giờ chơi của từng khu, áp dụng từ ngày ghi đến trước lần đổi sau.
- `hoi_vien`: hội viên có tài khoản nạp tiền.
- `phien_choi`: mỗi lượt ngồi máy một dòng: `bat_dau` (`yyyy-mm-dd hh:mm`), `ket_thuc` (`dd/mm/yyyy hh:mm`), `so_phut` (số phút chơi), `tien_gio` (tiền giờ của phiên), `thanh_toan` (`tài khoản` là trừ vào tài khoản hội viên), `tinh_trang` (`xong`; `hoàn tiền` là phiên lỗi máy, quán hoàn lại toàn bộ tiền giờ). `ma_hv` trống là khách vãng lai.
- `nap_tien`: hội viên nạp tiền vào tài khoản: `so_tien_nap` là tiền khách đưa, `tien_tang` là tiền khuyến mãi quán cộng thêm vào tài khoản.
- `mon`, `don_do_an`, `chi_tiet_do_an`: đồ ăn uống gọi tại máy; `tinh_trang` `huỷ` là đơn huỷ.

## Quy ước
- Dữ liệu từ 01/06/2025 đến hết 31/08/2026.
- Số dư tài khoản hội viên = tổng nạp + tiền tặng − tiền giờ các phiên `xong` trả bằng `tài khoản`, tính từ đầu dữ liệu.
""")

# ======================================================================= 204 giặt sấy
def w_laundry(R, S, d):
    sheets = {}
    for t in S['tickets']:
        q = (t['date'].month - 1) // 3 + 1
        sheets.setdefault('Q%d-%d' % (q, t['date'].year), []).append(t)
    out = []
    for nm, ts in sheets.items():
        rows = [['Ngày nhận', 'Giờ', 'Số phiếu', 'Tên khách', 'SĐT', 'Dịch vụ', 'Số lượng', 'Đơn giá', 'Thành tiền', 'Hẹn trả', 'Ngày trả', 'Ghi chú']]
        for t in ts:
            if t['unit'] == 'kg':
                qv = R.choice([('%s kg' % t['q']).replace('.', ','), ('%skg' % t['q']).replace('.', ','), t['q'], ('%s ký' % t['q']).replace('.', ',')])
            else: qv = R.choice(['%d %s' % (t['q'], t['unit']), t['q']])
            notes = []
            if t['status'] == 'huỷ': notes.append(R.choice(['huỷ', 'khách hủy không giặt']))
            if t['disc']: notes.append('khách quen giảm 10%')
            if t['ship']: notes.append('giao tận nhà, ship %dk' % (t['ship'] // 1000))
            if t['ret'] is None and t['status'] != 'huỷ' and R.random() < 0.3: notes.append('chưa lấy')
            rows.append([fmt_date(R, t['date'], ['dmy1', 'obj']), '%dh%02d' % t['t'], t['id'], R.choice([t['cust']['name'], t['cust']['name'].lower(), 'chị ' + t['cust']['name'].split()[-1]]),
                         R.choice([t['cust']['phone'], t['cust']['phone'][:4] + '.' + t['cust']['phone'][4:7] + '.' + t['cust']['phone'][7:], '+84' + t['cust']['phone'][1:]]),
                         R.choice([t['svc'], t['svc'].upper(), t['svc'].capitalize()]), qv, fmt_money(R, t['price'], ['plain', 'k', 'dot']),
                         fmt_money(R, t['amt'], ['plain', 'k', 'dot']), fmt_date(R, t['due'], ['dmy1']), fmt_date(R, t['ret'], ['dmy1']) if t['ret'] else '', '; '.join(notes)])
        out.append((nm, rows))
    xl(os.path.join(d, 'SoGiat.xlsx'), out)
    readme(os.path.join(d, 'README.md'), 'Dữ liệu biz_204', """
Sổ nhận đồ của tiệm giặt sấy, mỗi quý một sheet (`Q1-2025`…). Mỗi dòng là một **phiếu** (một lần khách gửi đồ, một dịch vụ).

## Cột
- **Ngày nhận** (ngày khách gửi đồ, `d/m/yyyy` hoặc ô ngày), **Giờ** (`7h05`), **Số phiếu**, **Tên khách** (tên gọi tuỳ lúc ghi), **SĐT** (nhiều cách ghi), **Dịch vụ** (`giặt sấy` tính theo kg, `giặt hấp` và `ủi` theo món, `chăn mền` theo cái, `giày` theo đôi).
- **Số lượng**: số kg (vd `3,5 kg`, `3,5 ký`) hoặc số món/cái/đôi.
- **Đơn giá**; **Thành tiền**: tiền dịch vụ của phiếu (đã trừ giảm giá, không gồm phí giao).
- **Hẹn trả**: ngày hẹn; **Ngày trả**: ngày khách nhận lại đồ (trống: chưa trả).
- **Ghi chú**: `huỷ` là phiếu huỷ; phí giao tận nhà ghi ở đây (vd `ship 15k`).

## Quy ước
- Dữ liệu từ 01/04/2025 đến hết 31/07/2026.
- Giặt sấy tính tiền tối thiểu 3 kg: phiếu dưới 3 kg vẫn thu bằng 3 kg (đã tính sẵn ở **Thành tiền**); số kg thực giặt là **Số lượng**.
- Tiệm không có mã khách: mỗi **số điện thoại** là một khách.
""")

# ======================================================================= 210 trạm sạc
def w_charge(R, S, d):
    def plate_v(p):
        return R.choice([p, p, p.replace('.', ''), p.replace('-', ' '), p.lower(), p.replace('-', '').replace('.', ''), p.replace('.', '-')])
    rows = []
    for s in S['sessions']:
        rows.append([s['id'], s['post'], plate_v(s['plate']), s['st'].strftime(R.choice(['%d/%m/%Y %H:%M:%S', '%Y-%m-%d %H:%M:%S'])),
                     s['en'].strftime('%d/%m/%Y %H:%M:%S'), ('%.3f' % s['kwh']).replace('.', R.choice([',', '.'])), s['price'], s['amt'], s['pay'], s['status']])
    wcsv(os.path.join(d, 'phien_sac.csv'), ['ma_phien', 'tru', 'bien_so', 'bat_dau', 'ket_thuc', 'kwh', 'don_gia_kwh', 'thanh_tien', 'thanh_toan', 'trang_thai'], rows)
    wcsv(os.path.join(d, 'tru_sac.csv'), ['tru', 'loai', 'cong_suat_kw'], [[p['id'], p['kind'], p['kw']] for p in S['posts']])
    g = []
    for k in ('AC', 'DC'):
        for tier in ('thấp điểm', 'cao điểm'):
            g.append([k, tier, S['start'].strftime('%d/%m/%Y'), S['prices'][k][tier]])
            g.append([k, tier, S['price_change'][0].strftime('%d/%m/%Y'), S['price_change'][1][k][tier]])
    wcsv(os.path.join(d, 'bang_gia.csv'), ['loai_tru', 'khung', 'ap_dung_tu', 'gia_kwh'], g)
    readme(os.path.join(d, 'README.md'), 'Dữ liệu biz_210', """
Trạm sạc xe điện công cộng có 8 trụ (AC và DC). Hệ thống xuất mỗi lượt sạc một dòng.

## File
- `phien_sac.csv`: `ma_phien`, `tru` (mã trụ), `bien_so` (biển số xe, nhân viên gõ tay nên cách ghi không thống nhất), `bat_dau`, `ket_thuc`, `kwh` (điện năng sạc, dấu thập phân có thể là `,` hoặc `.`), `don_gia_kwh`, `thanh_tien`, `thanh_toan`, `trang_thai` (`hoàn tất`; `lỗi` là phiên lỗi, không thu tiền).
- `tru_sac.csv`: loại trụ và công suất.
- `bang_gia.csv`: giá mỗi kWh theo loại trụ và khung giờ, áp dụng từ ngày ghi.

## Quy ước
- Dữ liệu từ 01/07/2025 đến hết 20/09/2026.
- Khung **cao điểm** 17:00–21:59, còn lại là **thấp điểm**; phiên tính theo giờ bắt đầu.
""")

WRITERS = {k: v for k, v in globals().items() if k.startswith('w_')}
