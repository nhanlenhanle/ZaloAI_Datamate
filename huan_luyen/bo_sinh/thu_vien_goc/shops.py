"""Cấu hình 10 cơ sở hư cấu (ngành lạ)."""
import datetime as D
from sim import mk_items

H_DAY = [(7, 3), (8, 5), (9, 7), (10, 7), (11, 6), (12, 4), (13, 3), (14, 4), (15, 5), (16, 6), (17, 7), (18, 8), (19, 7), (20, 5), (21, 3)]
H_EVE = [(9, 2), (10, 3), (11, 4), (12, 4), (13, 3), (14, 5), (15, 7), (16, 8), (17, 8), (18, 7), (19, 9), (20, 9), (21, 6)]

def shops():
    S = []
    S.append(dict(id='biz_201', name='Tiệm hoa Mộc Lan', kind='retail', writer='w_flower', start=D.date(2025, 1, 1), end=D.date(2026, 6, 30),
        lam=16, hours=H_DAY, p_walkin=0.45, ncust=150, cust_code=False, accent_trap=True, digit_trap=True, oid_fmt='%05d',
        holiday_boost=[('Valentine', 4), ('Quốc tế Phụ nữ', 3.5), ('Phụ nữ Việt Nam', 3), ('Nhà giáo Việt Nam', 3), ('Vu Lan', 2)], lunar_mult=1.8,
        p_big=0.25, items=mk_items([
            ('Hoa hồng đỏ Đà Lạt', 'hoa cành', 'cành', {'bó': 20}, 9000, {'alias': ['Hồng đỏ', 'hong do DL']}),
            ('Hoa hồng trắng', 'hoa cành', 'cành', {'bó': 20}, 10000, {'alias': ['Hồng trắng']}),
            ('Hoa hồng phấn', 'hoa cành', 'cành', {'bó': 20}, 10000, {'alias': ['Hồng phấn']}),
            ('Cẩm chướng', 'hoa cành', 'cành', {'bó': 10}, 6000, {'alias': ['CC', 'Cẩm chướng ĐL']}),
            ('Hoa ly trắng', 'hoa cành', 'cành', {'bó': 5}, 30000, {'alias': ['Ly trắng']}),
            ('Hướng dương', 'hoa cành', 'cành', {'bó': 3}, 25000, {'alias': ['HD', 'Hoa hướng dương']}),
            ('Cúc họa mi', 'hoa cành', 'bó', {}, 60000, {'alias': ['Họa mi']}),
            ('Cúc vàng', 'hoa cành', 'cành', {'bó': 10}, 4000, {'alias': ['Cúc vàng cúng'], 'pop': 2.5}),
            ('Lan hồ điệp trắng', 'hoa chậu', 'chậu', {}, 450000, {'alias': ['Lan HĐ trắng'], 'pop': 0.3}),
            ('Sen đá mix', 'hoa chậu', 'chậu', {}, 45000, {'alias': ['Sen đá']}),
            ('Giỏ hoa chúc mừng', 'hoa thiết kế', 'giỏ', {}, 550000, {'pop': 0.4, 'made': True}),
            ('Bó hoa sinh nhật', 'hoa thiết kế', 'bó', {}, 350000, {'pop': 0.7, 'made': True}),
            ('Kệ hoa khai trương', 'hoa thiết kế', 'kệ', {}, 1500000, {'pop': 0.12, 'made': True}),
            ('Giấy gói Hàn Quốc', 'phụ kiện', 'tờ', {'xấp': 20}, 3000, {'alias': ['Giấy HQ']}),
            ('Thiệp chúc mừng', 'phụ kiện', 'cái', {}, 10000, {'alias': ['Thiệp']}),
            ('Nến thơm mini', 'phụ kiện', 'hũ', {}, 65000, {'pop': 0.4})], 'HM')))
    S.append(dict(id='biz_202', name='Trại cá cảnh Thủy Sinh Ba Tơ', kind='retail', writer='w_fish', start=D.date(2025, 3, 1), end=D.date(2026, 9, 15),
        lam=22, hours=H_EVE, p_walkin=0.35, ncust=220, cust_code=True, oid_fmt='CA%06d', stock=True, exchange=0.03,
        chans=[('store', 70), ('zalo', 12), ('facebook', 10), ('shopee', 8)], delivery=('zalo', 'facebook', 'shopee'),
        pays=[('cash', 40), ('transfer', 30), ('ewallet', 10), ('cod', 15), ('debt', 5)], odisc=(500000, 20000),
        suppliers=['Trại cá Bến Lức', 'Thủy sinh Sài Gòn Xanh', 'Tổng kho Aqua Miền Tây', 'Cty Thức ăn Tôm Cá Việt'],
        items=mk_items([
            ('Cá Betta Halfmoon', 'cá', 'con', {}, 45000, {'live': True}),
            ('Cá bảy màu Full Red', 'cá', 'con', {'cặp': 2, 'đàn': 10}, 12000, {'live': True, 'pop': 2}),
            ('Cá Neon Vua', 'cá', 'con', {'đàn': 10}, 6000, {'live': True, 'pop': 2}),
            ('Cá vàng Ranchu', 'cá', 'con', {'cặp': 2}, 85000, {'live': True}),
            ('Cá Koi mini', 'cá', 'con', {}, 120000, {'live': True, 'pop': 0.6}),
            ('Tép Red Cherry', 'tép ốc', 'con', {'đàn': 10}, 5000, {'live': True}),
            ('Ốc Nerita', 'tép ốc', 'con', {}, 15000, {'live': True}),
            ('Thức ăn Tetra Bits 100g', 'thức ăn', 'hộp', {'thùng': 24}, 75000, {'pop': 1.5}),
            ('Trùn chỉ sấy 50g', 'thức ăn', 'gói', {'thùng': 40}, 25000, {'pop': 1.5}),
            ('Bể kính 60cm', 'bể và phụ kiện', 'cái', {}, 650000, {'pop': 0.3}),
            ('Lọc thác mini', 'bể và phụ kiện', 'cái', {}, 180000, {'pop': 0.5}),
            ('Đèn LED thủy sinh 60cm', 'bể và phụ kiện', 'cái', {}, 350000, {'pop': 0.3}),
            ('Phân nền ADA 3L', 'thủy sinh', 'bao', {}, 420000, {'pop': 0.3}),
            ('Rêu Java', 'thủy sinh', 'vỉ', {'hộp': 6}, 30000),
            ('Cây Ráy Nana', 'thủy sinh', 'bụi', {}, 40000),
            ('Muối khoáng cá cảnh 1kg', 'thuốc và hoá chất', 'gói', {'thùng': 20}, 30000),
            ('Thuốc Methylene Blue', 'thuốc và hoá chất', 'chai', {}, 35000)], 'SP')))
    S.append(dict(id='biz_203', name='Phòng máy Pixel 24h', kind='net', writer='w_net', start=D.date(2025, 6, 1), end=D.date(2026, 8, 31), lam=95))
    S.append(dict(id='biz_204', name='Tiệm giặt sấy Cô Ba', kind='laundry', writer='w_laundry', start=D.date(2025, 4, 1), end=D.date(2026, 7, 31), lam=24))
    S.append(dict(id='biz_205', name='Xưởng in 3D Lớp Nhựa', kind='retail', writer='w_print3d', start=D.date(2025, 2, 1), end=D.date(2026, 8, 20),
        lam=11, hours=H_DAY, p_walkin=0.15, ncust=170, cust_code=True, oid_fmt='3D-%05d', deposit=True, staff=['TP01', 'TP02', 'TP03', 'TP04'],
        chans=[('store', 50), ('zalo', 30), ('facebook', 20)], kdist=[55, 30, 10, 4, 1], p_cancel=0.04, p_return=0.015,
        items=mk_items([
            ('In PLA theo gram', 'in theo khối lượng', 'gram', {}, 900, {'cr': 0.35, 'made': True, 'pop': 2.5, 'qrange': (25, 900)}),
            ('In PETG theo gram', 'in theo khối lượng', 'gram', {}, 1200, {'cr': 0.4, 'made': True, 'qrange': (25, 600)}),
            ('In resin theo ml', 'in theo khối lượng', 'ml', {}, 2500, {'cr': 0.45, 'made': True, 'qrange': (10, 300)}),
            ('Mô hình nhân vật 15cm', 'sản phẩm có sẵn', 'cái', {}, 280000, {'cr': 0.5, 'made': True}),
            ('Móc khóa in tên', 'sản phẩm có sẵn', 'cái', {'hộp': 10}, 25000, {'cr': 0.3, 'made': True, 'pop': 2}),
            ('Vỏ hộp mạch điện tử', 'sản phẩm có sẵn', 'cái', {}, 150000, {'cr': 0.4, 'made': True}),
            ('Thiết kế file 3D', 'dịch vụ', 'lần', {}, 300000, {'cr': 0.1, 'made': True, 'pop': 0.7}),
            ('Sơn hoàn thiện mô hình', 'dịch vụ', 'lần', {}, 120000, {'cr': 0.2, 'made': True}),
            ('Quét 3D vật thể', 'dịch vụ', 'lần', {}, 450000, {'cr': 0.15, 'made': True, 'pop': 0.3})], 'IN'),
        qdist=[1, 1, 1, 2, 3], gram_items=('IN001', 'IN002', 'IN003')))
    S.append(dict(id='biz_206', name='Tạp hoá chợ phiên A Páo', kind='retail', writer='w_grocery', start=D.date(2025, 1, 1), end=D.date(2026, 7, 15),
        lam=34, hours=H_DAY, p_walkin=0.5, ncust=120, cust_code=False, oid_fmt='P%06d', stock=True, p_big=0.18, shift_ok=False,
        suppliers=['Đại lý Hùng Mạnh Hà Giang', 'Kho bia nước ngọt Tuấn Hoa', 'Chợ đầu mối Yên Minh', 'Cty TNHH Thuốc lá Đông Bắc'],
        items=mk_items([
            ('Bia Hà Nội lon 330ml', 'đồ uống', 'lon', {'lốc': 6, 'thùng': 24}, 11000, {'chain': [('thùng', 'lốc', 4), ('lốc', 'lon', 6)], 'pop': 2}),
            ('Coca Cola lon 320ml', 'đồ uống', 'lon', {'lốc': 6, 'thùng': 24}, 10000, {'chain': [('thùng', 'lốc', 4), ('lốc', 'lon', 6)]}),
            ('Rượu ngô Bản Phố', 'đồ uống', 'lít', {'can': 5}, 60000, {'chain': [('can', 'lít', 5)]}),
            ('Mì Hảo Hảo tôm chua cay', 'thực phẩm khô', 'gói', {'thùng': 30}, 4500, {'chain': [('thùng', 'gói', 30)], 'pop': 2}),
            ('Gạo nếp nương', 'thực phẩm khô', 'kg', {'bao': 25}, 28000, {'chain': [('bao', 'kg', 25)]}),
            ('Muối hột', 'gia vị', 'gói', {'bịch': 10}, 5000, {'chain': [('bịch', 'gói', 10)]}),
            ('Dầu ăn Neptune 1L', 'gia vị', 'chai', {'thùng': 12}, 52000, {'chain': [('thùng', 'chai', 12)]}),
            ('Bột ngọt Ajinomoto 400g', 'gia vị', 'gói', {'thùng': 20}, 32000, {'chain': [('thùng', 'gói', 20)]}),
            ('Thuốc lá Thăng Long', 'thuốc lá', 'bao', {'cây': 10}, 15000, {'chain': [('cây', 'bao', 10)], 'pop': 1.5}),
            ('Pin con thỏ AA', 'đồ dùng', 'viên', {'vỉ': 2, 'hộp': 40}, 4000, {'chain': [('hộp', 'vỉ', 20), ('vỉ', 'viên', 2)]}),
            ('Bột giặt Omo 800g', 'đồ dùng', 'gói', {'bao': 12}, 38000, {'chain': [('bao', 'gói', 12)]}),
            ('Xà bông cục Lifebuoy', 'đồ dùng', 'cục', {'lốc': 4, 'thùng': 48}, 14000, {'chain': [('thùng', 'lốc', 12), ('lốc', 'cục', 4)]}),
            ('Trứng gà ta', 'thực phẩm tươi', 'quả', {'vỉ': 10}, 4000, {'chain': [('vỉ', 'quả', 10)]}),
            ('Kẹo lạc Cu Đơ', 'bánh kẹo', 'gói', {'thùng': 50}, 12000, {'chain': [('thùng', 'gói', 50)]}),
            ('Bánh quy Cosy', 'bánh kẹo', 'hộp', {'thùng': 12}, 45000, {'chain': [('thùng', 'hộp', 12)]})], 'TH')))
    S.append(dict(id='biz_207', name='Gác sách cũ ký gửi', kind='retail', writer='w_books', start=D.date(2025, 5, 1), end=D.date(2026, 9, 10),
        lam=14, hours=H_EVE, p_walkin=0.4, ncust=140, cust_code=True, oid_fmt='GS%05d', stock=True, kdist=[60, 25, 10, 5, 0], qdist=[1],
        chans=[('store', 75), ('facebook', 25)], delivery=('facebook',), pays=[('cash', 45), ('transfer', 40), ('cod', 15)],
        suppliers=['Đồng nát sách Bà Chiểu', 'Phát hành sách Nhân Văn', 'Thanh lý thư viện Hội An'],
        owners={'Cô Hạnh': 25, 'Anh Tú Hội An': 30, 'Nhà sách Gió': 20}, items=books_items()))
    S.append(dict(id='biz_208', name='Quán chè Bà Tư Cần Thơ', kind='retail', writer='w_dessert', start=D.date(2025, 1, 1), end=D.date(2026, 5, 31),
        lam=55, hours=[(9, 2), (10, 4), (11, 5), (12, 4), (13, 5), (14, 8), (15, 10), (16, 10), (17, 8), (18, 9), (19, 11), (20, 10), (21, 6)],
        p_walkin=0.85, ncust=80, cust_code=False, oid_fmt='CH%06d', tet_mult=1.8, kdist=[45, 35, 12, 6, 2],
        chans=[('store', 70), ('grab', 18), ('shopeefood', 12)], delivery=('grab', 'shopeefood'), pays=[('cash', 55), ('transfer', 30), ('ewallet', 15)],
        items=mk_items(dessert_items(), 'CB')))
    S.append(dict(id='biz_209', name='Nhà thuốc thú y Pet An', kind='retail', writer='w_vet', start=D.date(2025, 4, 1), end=D.date(2026, 8, 31),
        lam=20, hours=H_DAY, p_walkin=0.3, ncust=260, cust_code=True, oid_fmt='TY%06d', stock=True, lots=True, staff=['BS01', 'BS02', 'NV03'],
        pays=[('cash', 45), ('transfer', 40), ('debt', 4), ('ewallet', 11)],
        suppliers=['Cty Thuốc thú y Hanvet', 'Cty Virbac Việt Nam', 'Nhà phân phối PetHouse', 'Cty Royal Canin VN'],
        items=mk_items([
            ('Amoxicillin thú y 500mg', 'kháng sinh', 'viên', {'vỉ': 10, 'hộp': 100}, 3000, {'rx': True, 'ing': 'Amoxicillin'}),
            ('Doxycycline thú y 100mg', 'kháng sinh', 'viên', {'vỉ': 10}, 4500, {'rx': True, 'ing': 'Doxycycline'}),
            ('Enrofloxacin 10% 100ml', 'kháng sinh', 'chai', {}, 95000, {'rx': True, 'ing': 'Enrofloxacin'}),
            ('Thuốc tẩy giun Drontal', 'ký sinh trùng', 'viên', {'vỉ': 2}, 45000, {'rx': False, 'ing': 'Praziquantel + Pyrantel + Febantel', 'pop': 1.5}),
            ('Nhỏ gáy Frontline Plus', 'ký sinh trùng', 'tuýp', {'hộp': 3}, 120000, {'rx': False, 'ing': 'Fipronil + Methoprene'}),
            ('Bravecto viên nhai 10-20kg', 'ký sinh trùng', 'viên', {}, 650000, {'rx': True, 'ing': 'Fluralaner', 'pop': 0.4}),
            ('Ivermectin 1% 20ml', 'ký sinh trùng', 'chai', {}, 40000, {'rx': True, 'ing': 'Ivermectin'}),
            ('Meloxicam thú y 1mg', 'giảm đau kháng viêm', 'viên', {'vỉ': 10}, 6000, {'rx': True, 'ing': 'Meloxicam'}),
            ('Men tiêu hóa Pet Biotic', 'dinh dưỡng', 'gói', {'hộp': 20}, 12000, {'rx': False, 'ing': 'Lactobacillus', 'pop': 1.5}),
            ('Vitamin tổng hợp Nutri-Plus Gel', 'dinh dưỡng', 'tuýp', {}, 260000, {'rx': False, 'ing': 'Vitamin tổng hợp'}),
            ('Canxi Calci-Pet', 'dinh dưỡng', 'viên', {'lọ': 60}, 2500, {'rx': False, 'ing': 'Calci carbonat'}),
            ('Sữa tắm trị nấm Ketomed', 'vệ sinh', 'chai', {'thùng': 24}, 150000, {'rx': False, 'ing': 'Ketoconazol + Chlorhexidin'}),
            ('Nước nhỏ tai Otiderm', 'vệ sinh', 'chai', {}, 110000, {'rx': False, 'ing': 'Chlorhexidin'}),
            ('Vòng chống liếm size M', 'dụng cụ', 'cái', {}, 55000, {'rx': False}),
            ('Bơm tiêm 3ml', 'dụng cụ', 'cái', {'hộp': 100}, 1500, {'rx': False})], 'TY')))
    S.append(dict(id='biz_210', name='Trạm sạc xe điện Volt Xanh', kind='charge', writer='w_charge', start=D.date(2025, 7, 1), end=D.date(2026, 9, 20), lam=38))
    return S

def books_items():
    owners = [None, None, None, 'Cô Hạnh', 'Anh Tú Hội An', 'Nhà sách Gió']
    titles = [('Dế Mèn phiêu lưu ký', 'thiếu nhi', 45000), ('Số đỏ', 'văn học', 55000), ('Tắt đèn', 'văn học', 40000),
              ('Nhà giả kim', 'văn học', 60000), ('Đắc nhân tâm', 'kỹ năng', 50000), ('Cha giàu cha nghèo', 'kinh tế', 65000),
              ('Doraemon tập 12', 'truyện tranh', 18000), ('Conan tập 45', 'truyện tranh', 20000), ('Harry Potter và Hòn đá Phù thủy', 'thiếu nhi', 90000),
              ('Truyện Kiều bản 1965', 'văn học', 250000), ('The Old Man and the Sea', 'ngoại văn', 80000), ('Norwegian Wood', 'ngoại văn', 110000),
              ('Tuổi thơ dữ dội', 'văn học', 70000), ('Kính vạn hoa tập 3', 'thiếu nhi', 25000), ('Nghĩ giàu làm giàu', 'kinh tế', 55000),
              ('Bố già', 'văn học', 75000), ('Hai vạn dặm dưới đáy biển', 'thiếu nhi', 60000), ('Slam Dunk tập 1', 'truyện tranh', 35000),
              ('Sapiens lược sử loài người', 'kinh tế', 120000), ('Việt Nam sử lược', 'lịch sử', 150000), ('Đất rừng phương Nam', 'văn học', 65000),
              ('Atomic Habits', 'ngoại văn', 140000), ('Lược sử thời gian', 'khoa học', 85000), ('Tạp chí Thế giới mới 1998', 'tạp chí', 30000)]
    R_ = __import__('random').Random(77)
    spec = []
    for i, (t, g, p) in enumerate(titles):
        ow = owners[i % len(owners)]
        spec.append((t, g, 'cuốn', {}, p, {'owner': ow or 'Tiệm', 'cr': 0.0 if ow else 0.35}))
    return mk_items(spec, 'S')

def dessert_items():
    out = []
    for nm, p in [('Chè Thái', 25000), ('Chè bưởi', 22000), ('Sương sa hột lựu', 20000), ('Chè khúc bạch', 30000), ('Trà sữa nướng', 28000),
                  ('Chè đậu đỏ', 18000)]:
        out.append((nm + ' (M)', 'chè' if 'Trà' not in nm else 'trà sữa', 'ly', {}, p, {'drink': True, 'made': True, 'pop': 1.6}))
        out.append((nm + ' (L)', 'chè' if 'Trà' not in nm else 'trà sữa', 'ly', {}, p + 7000, {'drink': True, 'made': True}))
    out += [('Sữa chua nếp cẩm', 'sữa chua', 'hũ', {}, 18000, {'made': True}), ('Bánh flan', 'bánh', 'cái', {}, 12000, {'made': True}),
            ('Rau câu dừa', 'bánh', 'cái', {}, 15000, {'made': True}),
            ('Topping Trân châu trắng', 'topping', 'phần', {}, 5000, {'topping': True, 'made': True}),
            ('Topping Thạch dừa', 'topping', 'phần', {}, 5000, {'topping': True, 'made': True}),
            ('Topping Pudding trứng', 'topping', 'phần', {}, 7000, {'topping': True, 'made': True}),
            ('Topping Kem cheese', 'topping', 'phần', {}, 8000, {'topping': True, 'made': True})]
    return out
