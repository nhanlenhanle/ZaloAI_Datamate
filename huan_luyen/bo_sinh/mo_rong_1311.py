"""Bộ Gen_1311 (sinh.py --b1311 <file mô tả shop>): mở rộng bộ sinh cho dữ liệu train.

1. Ngành mới hoàn toàn (NGANH_1311): đơn vị, quy đổi nhiều bậc, cách đặt tên lạ (trứng quả / vỉ / thùng, gas bình,
   nhôm mét / cây, vàng chỉ / lượng, gạch viên / thùng, đá kg / bao...).
2. Năm kiểu sổ public mà bộ sinh chưa có (LAYOUT): SQLite máy POS, sổ trộn nhiều nguồn, sổ chuyên ngành tự ghi
   (sửa xe, điện thoại, mẹ và bé), sổ ghi tay kèm sổ phụ, sổ một sheet không có mã đơn.
3. Luật riêng theo ngành ở §6 (KIEU): thuốc kê đơn + lô hạn dùng, tiền cọc, phiếu sửa chữa / bảo hành, điện thoại thu cũ /
   trả góp, điểm tích luỹ, phiên sạc, cho thuê.
5. Câu "không trả lời được" đa dạng (F_khong_tl).
Mọi thứ chỉ chạy khi sinh.py bật --b1311; không bật thì sinh.py sinh y như cũ.
"""
import calendar
import collections
import datetime as D
import os
import random
import sqlite3

from core import *          # noqa: F401,F403  (thư viện gốc: money, r2, num_out, month, make_names, phone, fmt_money...)
import qgen
import sim
import writers as W

E = qgen.E

# ------------------------------------------------------------------ 1. ngành mới
# (tên, nhóm, đơn vị cơ bản, {đơn vị lớn: hệ số}, giá theo đơn vị cơ bản, thêm). chain: quy đổi theo bậc (rulebook §10)
NGANH_1311 = {
    'trung_gia_cam': ('Đại lý trứng gia cầm', 'TR', [
        ('Trứng gà công nghiệp loại 1', 'trứng gà', 'quả', {'vỉ': 30, 'thùng': 300}, 2600,
         {'alias': ['Trứng gà CN L1', 'trung ga cn'], 'chain': [('thùng', 'vỉ', 10), ('vỉ', 'quả', 30)], 'pop': 3}),
        ('Trứng gà ta', 'trứng gà', 'quả', {'chục': 10}, 4200, {'alias': ['Gà ta'], 'pop': 1.5}),
        ('Trứng gà Omega 3 hộp 10 quả', 'trứng gà', 'hộp', {'thùng': 20}, 45000, {'alias': ['Omega 3'], 'pop': 0.7}),
        ('Trứng vịt', 'trứng vịt', 'quả', {'chục': 10, 'vỉ': 30}, 3600, {'alias': ['Hột vịt'], 'pop': 2}),
        ('Trứng vịt lộn', 'trứng vịt', 'quả', {'chục': 10}, 6000, {'alias': ['Hột vịt lộn', 'HVL'], 'pop': 1.2}),
        ('Trứng vịt muối', 'trứng chế biến', 'quả', {'hộp': 4}, 7000, {'alias': ['Hột vịt muối'], 'pop': 0.8}),
        ('Trứng cút', 'trứng cút', 'quả', {'hộp': 30, 'thùng': 600}, 700,
         {'alias': ['Cút'], 'chain': [('thùng', 'hộp', 20), ('hộp', 'quả', 30)], 'pop': 1.5}),
        ('Trứng bắc thảo', 'trứng chế biến', 'quả', {'hộp': 6}, 9000, {'alias': ['Bắc thảo'], 'pop': 0.4})]),
    'gas_bep': ('Cửa hàng gas và bếp', 'GB', [
        ('Gas Petrolimex 12kg', 'gas', 'bình', {}, 480000, {'alias': ['PETRO 12', 'Gas Petro xám'], 'pop': 3}),
        ('Gas Saigon Petro 12kg', 'gas', 'bình', {}, 460000, {'alias': ['SP 12kg', 'Gas đỏ'], 'pop': 2}),
        ('Gas công nghiệp 45kg', 'gas', 'bình', {}, 1750000, {'alias': ['Bình 45', 'Gas CN 45'], 'pop': 0.4}),
        ('Gas mini lon 250g', 'gas', 'lon', {'lốc': 4, 'thùng': 28}, 25000,
         {'alias': ['Lon gas mini'], 'chain': [('thùng', 'lốc', 7), ('lốc', 'lon', 4)], 'pop': 1.2}),
        ('Bếp gas đôi Rinnai', 'bếp', 'cái', {}, 1450000, {'alias': ['Bếp Rinnai đôi'], 'pop': 0.4}),
        ('Bếp hồng ngoại Sunhouse', 'bếp', 'cái', {}, 990000, {'pop': 0.3}),
        ('Van điều áp ngắt gas tự động', 'phụ kiện', 'cái', {}, 180000, {'alias': ['Van an toàn'], 'pop': 0.8}),
        ('Dây dẫn gas lõi thép', 'phụ kiện', 'mét', {'cuộn': 50}, 25000, {'alias': ['Dây gas'], 'pop': 1})]),
    'nuoc_da_binh': ('Đại lý nước đá và nước bình', 'ND', [
        ('Nước bình Lavie 19L', 'nước bình', 'bình', {}, 65000, {'alias': ['Lavie 19 lít', 'LV19'], 'pop': 3}),
        ('Nước bình Aquafina 19L', 'nước bình', 'bình', {}, 60000, {'alias': ['Aqua 19L'], 'pop': 2}),
        ('Nước tinh khiết bình 20L', 'nước bình', 'bình', {}, 18000, {'alias': ['Bình 20L thường'], 'pop': 2.5}),
        ('Đá viên tinh khiết', 'nước đá', 'kg', {'bao': 20}, 2000, {'alias': ['Đá viên'], 'pop': 3}),
        ('Đá cây', 'nước đá', 'cây', {}, 35000, {'alias': ['Cây đá'], 'pop': 1}),
        ('Đá bi', 'nước đá', 'kg', {'bao': 10}, 2500, {'pop': 1}),
        ('Nước suối Lavie 500ml', 'nước chai', 'chai', {'thùng': 24}, 5000, {'alias': ['Lavie 500'], 'pop': 1.5}),
        ('Vòi nước bình', 'phụ kiện', 'cái', {}, 15000, {'pop': 0.3})]),
    'gach_op_lat': ('Cửa hàng gạch ốp lát', 'GO', [
        ('Gạch 60x60 bóng kiếng Viglacera', 'gạch lát nền', 'viên', {'thùng': 4}, 62000, {'alias': ['6060 bóng kiếng', 'GL6060'], 'pop': 2}),
        ('Gạch 80x80 vân đá Đồng Tâm', 'gạch lát nền', 'viên', {'thùng': 3}, 135000, {'alias': ['8080 vân đá'], 'pop': 1}),
        ('Gạch 30x60 ốp tường Prime', 'gạch ốp tường', 'viên', {'thùng': 8}, 28000, {'alias': ['3060 ốp'], 'pop': 1.5}),
        ('Gạch thẻ 6x24 trang trí', 'gạch ốp tường', 'viên', {'hộp': 44}, 3500, {'alias': ['Gạch thẻ'], 'pop': 1}),
        ('Gạch sân vườn 40x40', 'gạch sân', 'viên', {'thùng': 6}, 25000, {'pop': 0.8}),
        ('Keo dán gạch Weber 25kg', 'vật tư', 'bao', {}, 210000, {'alias': ['Keo Weber'], 'pop': 1}),
        ('Keo chà ron', 'vật tư', 'kg', {'bao': 5}, 30000, {'alias': ['Ron'], 'pop': 0.8}),
        ('Ke nhựa cân bằng', 'vật tư', 'cái', {'gói': 100}, 400, {'alias': ['Ke cân bằng'], 'pop': 0.8})]),
    'dau_nhot': ('Cửa hàng dầu nhớt', 'DN', [
        ('Nhớt Castrol Power1 0.8L', 'nhớt xe máy', 'chai', {'thùng': 24}, 115000, {'alias': ['Castrol 0,8', 'Power 1'], 'pop': 2}),
        ('Nhớt Motul 3100 1L', 'nhớt xe máy', 'chai', {'thùng': 12}, 135000, {'alias': ['Motul 3100'], 'pop': 2}),
        ('Nhớt Shell Advance 0.8L', 'nhớt xe máy', 'chai', {'thùng': 24}, 95000, {'alias': ['Shell AX'], 'pop': 1.5}),
        ('Nhớt ô tô Castrol Magnatec 4L', 'nhớt ô tô', 'can', {'thùng': 4}, 720000, {'alias': ['Magnatec 4L'], 'pop': 0.5}),
        ('Dầu thuỷ lực 46', 'dầu công nghiệp', 'lít', {'can': 18, 'phuy': 200}, 52000, {'alias': ['Thuỷ lực 46', 'HD46'], 'pop': 1}),
        ('Nhớt hộp số xe tay ga 120ml', 'nhớt xe máy', 'tuýp', {'hộp': 50}, 35000, {'alias': ['Nhớt láp'], 'pop': 1.5}),
        ('Nước làm mát Prestone 1L', 'phụ gia', 'chai', {'thùng': 6}, 85000, {'pop': 0.6}),
        ('Mỡ bò chịu nhiệt 0.5kg', 'phụ gia', 'hộp', {'thùng': 24}, 45000, {'alias': ['Mỡ bò'], 'pop': 0.6})]),
    'vang_bac': ('Tiệm vàng bạc', 'VB', [
        ('Nhẫn trơn vàng 9999', 'vàng 9999', 'chỉ', {'lượng': 10}, 8400000, {'alias': ['Nhẫn tròn trơn', 'NT9999'], 'pop': 2}),
        ('Vàng miếng SJC', 'vàng 9999', 'chỉ', {'lượng': 10}, 9200000, {'alias': ['SJC'], 'pop': 1}),
        ('Dây chuyền vàng 18K', 'vàng tây', 'chỉ', {}, 6100000, {'alias': ['DC 18K'], 'pop': 1}),
        ('Bông tai vàng 18K', 'vàng tây', 'đôi', {}, 2400000, {'pop': 0.8}),
        ('Lắc tay bạc 925', 'bạc', 'cái', {}, 650000, {'alias': ['Lắc bạc'], 'pop': 1}),
        ('Nhẫn bạc ta', 'bạc', 'cái', {}, 250000, {'pop': 1.2}),
        ('Công khắc tên', 'dịch vụ', 'lần', {}, 100000, {'made': True, 'pop': 0.4}),
        ('Hộp đựng trang sức', 'phụ kiện', 'cái', {}, 30000, {'made': True, 'pop': 0.5})]),
    'do_nhua': ('Đại lý đồ nhựa dùng một lần', 'DP', [
        ('Ly nhựa PET 500ml', 'ly', 'cái', {'cây': 50, 'thùng': 1000}, 650,
         {'alias': ['Ly 500', 'Ly PET 16oz'], 'chain': [('thùng', 'cây', 20), ('cây', 'cái', 50)], 'pop': 3}),
        ('Ly giấy 12oz', 'ly', 'cái', {'cây': 50, 'thùng': 1000}, 900,
         {'alias': ['Ly giấy 360ml'], 'chain': [('thùng', 'cây', 20), ('cây', 'cái', 50)], 'pop': 1.5}),
        ('Nắp cầu ly 500ml', 'nắp ống hút', 'cái', {'cây': 50, 'thùng': 2000}, 300,
         {'chain': [('thùng', 'cây', 40), ('cây', 'cái', 50)], 'pop': 1.5}),
        ('Ống hút trân châu', 'nắp ống hút', 'gói', {'bịch': 10}, 18000, {'alias': ['Ống hút to'], 'pop': 1}),
        ('Hộp xốp 3 ngăn', 'hộp', 'cái', {'lốc': 50, 'thùng': 400}, 1100,
         {'alias': ['Hộp xốp cơm'], 'chain': [('thùng', 'lốc', 8), ('lốc', 'cái', 50)], 'pop': 2}),
        ('Túi nilon trắng', 'túi', 'kg', {'bao': 10}, 48000, {'alias': ['Bao xốp trắng'], 'pop': 1.5}),
        ('Màng bọc thực phẩm 30cm', 'màng bọc', 'cuộn', {'thùng': 24}, 38000, {'alias': ['Màng bọc'], 'pop': 0.8}),
        ('Muỗng nhựa', 'muỗng nĩa', 'cái', {'bịch': 100}, 120, {'pop': 1})]),
    'nhom_kinh': ('Cửa hàng nhôm kính', 'NK', [
        ('Nhôm hệ 700 trắng sữa', 'nhôm thanh', 'mét', {'cây': 6}, 52000, {'alias': ['Nhôm 700'], 'pop': 2}),
        ('Nhôm Xingfa hệ 55', 'nhôm thanh', 'mét', {'cây': 6}, 145000, {'alias': ['Xingfa 55', 'XF55'], 'pop': 1.2}),
        ('Kính cường lực 8 ly', 'kính', 'm2', {}, 420000, {'alias': ['Kính CL 8mm'], 'pop': 1}),
        ('Kính trắng 5 ly', 'kính', 'm2', {}, 190000, {'alias': ['Kính 5mm'], 'pop': 1}),
        ('Ron cao su cửa', 'phụ kiện', 'mét', {'cuộn': 100}, 6000, {'pop': 1}),
        ('Bản lề sàn', 'phụ kiện', 'cái', {}, 650000, {'pop': 0.3}),
        ('Keo silicon A500', 'phụ kiện', 'chai', {'thùng': 25}, 55000, {'alias': ['Silicon A500'], 'pop': 1.2}),
        ('Công lắp đặt cửa', 'dịch vụ', 'bộ', {}, 500000, {'made': True, 'pop': 0.5})]),
    'than_cui': ('Đại lý than củi', 'TC', [
        ('Than đá cục', 'than', 'kg', {'bao': 25}, 9000, {'alias': ['Than đá'], 'pop': 1.5}),
        ('Than hoa không khói', 'than', 'kg', {'bao': 10}, 22000, {'alias': ['Than hoa', 'than binh'], 'pop': 2}),
        ('Than tổ ong', 'than', 'viên', {'chục': 10}, 3500, {'alias': ['Than 12 lỗ'], 'pop': 2.5}),
        ('Củi khô', 'củi', 'bó', {}, 25000, {'pop': 1}),
        ('Mùn cưa ép', 'củi', 'kg', {'bao': 20}, 5000, {'alias': ['Củi mùn cưa'], 'pop': 0.8}),
        ('Bếp than tổ ong', 'bếp', 'cái', {}, 120000, {'pop': 0.3}),
        ('Cồn khô', 'phụ kiện', 'cục', {'hộp': 12}, 3000, {'alias': ['Cồn thạch'], 'pop': 1.2}),
        ('Bật lửa', 'phụ kiện', 'cái', {'hộp': 50}, 4000, {'pop': 1})]),
    'hoa_pham': ('Đại lý hoá phẩm tẩy rửa', 'HP', [
        ('Nước rửa chén Sunlight 3.6kg', 'nước rửa chén', 'can', {'thùng': 4}, 98000, {'alias': ['Sunlight can'], 'pop': 2}),
        ('Nước giặt Omo túi 3.6kg', 'nước giặt', 'túi', {'thùng': 4}, 185000, {'alias': ['Omo túi'], 'pop': 1.5}),
        ('Nước tẩy Javel', 'tẩy rửa', 'lít', {'can': 20}, 9000, {'alias': ['Javen'], 'pop': 1.5}),
        ('Bột giặt Viso', 'bột giặt', 'kg', {'bao': 9}, 32000, {'alias': ['Viso'], 'pop': 1}),
        ('Nước lau sàn Gift 4kg', 'lau sàn', 'can', {'thùng': 4}, 89000, {'alias': ['Gift lau sàn'], 'pop': 1}),
        ('Nước rửa tay Lifebuoy 500g', 'rửa tay', 'chai', {'thùng': 24}, 62000, {'pop': 1}),
        ('Xút vảy NaOH', 'hoá chất', 'kg', {'bao': 25}, 18000, {'alias': ['Xút', 'NaOH'], 'pop': 0.5}),
        ('Cồn 70 độ', 'hoá chất', 'lít', {'can': 30}, 35000, {'alias': ['Cồn y tế'], 'pop': 0.7})]),
    # ---- ngành cho luật riêng (mục 3) và sổ chuyên ngành (mục 2)
    'nha_thuoc': ('Nhà thuốc', 'NT', [
        ('Amoxicillin 500mg', 'kháng sinh', 'viên', {'vỉ': 10, 'hộp': 100}, 1500, {'rx': True, 'ing': 'Amoxicillin', 'pop': 2}),
        ('Augmentin 625mg', 'kháng sinh', 'viên', {'vỉ': 7, 'hộp': 14}, 16000, {'rx': True, 'ing': 'Amoxicillin + Acid clavulanic'}),
        ('Cefuroxim 500mg', 'kháng sinh', 'viên', {'vỉ': 10}, 6000, {'rx': True, 'ing': 'Cefuroxim'}),
        ('Paracetamol 500mg', 'giảm đau hạ sốt', 'viên', {'vỉ': 10, 'hộp': 100}, 500, {'rx': False, 'ing': 'Paracetamol', 'pop': 3}),
        ('Panadol Extra', 'giảm đau hạ sốt', 'viên', {'vỉ': 12, 'hộp': 180}, 1500, {'rx': False, 'ing': 'Paracetamol + Caffeine', 'pop': 2}),
        ('Ibuprofen 400mg', 'giảm đau hạ sốt', 'viên', {'vỉ': 10}, 1200, {'rx': False, 'ing': 'Ibuprofen'}),
        ('Omeprazol 20mg', 'tiêu hoá', 'viên', {'vỉ': 14, 'hộp': 28}, 1800, {'rx': True, 'ing': 'Omeprazol'}),
        ('Smecta', 'tiêu hoá', 'gói', {'hộp': 30}, 4000, {'rx': False, 'ing': 'Diosmectit'}),
        ('Siro ho Prospan 100ml', 'hô hấp', 'chai', {}, 85000, {'rx': False, 'ing': 'Cao lá thường xuân'}),
        ('Amlodipin 5mg', 'tim mạch', 'viên', {'vỉ': 10, 'hộp': 30}, 800, {'rx': True, 'ing': 'Amlodipin'}),
        ('Metformin 850mg', 'tiểu đường', 'viên', {'vỉ': 10, 'hộp': 100}, 900, {'rx': True, 'ing': 'Metformin'}),
        ('Vitamin C 500mg', 'vitamin', 'viên', {'tuýp': 10, 'hộp': 100}, 1200, {'rx': False, 'ing': 'Acid ascorbic'}),
        ('Nước muối sinh lý 0.9%', 'vật tư', 'chai', {'thùng': 30}, 5000, {'rx': False, 'ing': 'Natri clorid', 'pop': 2}),
        ('Khẩu trang y tế', 'vật tư', 'cái', {'hộp': 50}, 1000, {'rx': False, 'pop': 1.5})]),
    'tiem_may': ('Tiệm may đo', 'TM', [
        ('May áo dài', 'may đo', 'bộ', {}, 650000, {'made': True, 'pop': 2}),
        ('May vest nam', 'may đo', 'bộ', {}, 2200000, {'made': True, 'pop': 0.8}),
        ('May đầm dạ hội', 'may đo', 'cái', {}, 1200000, {'made': True, 'pop': 0.7}),
        ('May sơ mi', 'may đo', 'cái', {}, 350000, {'made': True, 'pop': 1.5}),
        ('Sửa đồ', 'sửa đồ', 'món', {}, 50000, {'made': True, 'pop': 2}),
        ('Vải lụa tơ tằm', 'vải', 'mét', {}, 280000, {'pop': 0.8}),
        ('Vải kate', 'vải', 'mét', {}, 60000, {'pop': 1})]),
    'sua_xe_may': ('Tiệm sửa xe máy', 'SX', [
        ('Nhớt Motul 3100 0.8L', 'phụ tùng', 'chai', {}, 120000, {'alias': ['Nhớt Motul'], 'pop': 3}),
        ('Bugi NGK', 'phụ tùng', 'cái', {}, 45000, {'pop': 1.2}),
        ('Má phanh trước', 'phụ tùng', 'bộ', {}, 80000, {'alias': ['Bố thắng trước'], 'pop': 1}),
        ('Lốp Michelin 80/90-17', 'phụ tùng', 'cái', {}, 520000, {'alias': ['Vỏ Michelin 80/90'], 'pop': 0.6}),
        ('Săm xe máy', 'phụ tùng', 'cái', {}, 65000, {'alias': ['Ruột xe'], 'pop': 1.2}),
        ('Ắc quy GS 12V-5Ah', 'phụ tùng', 'bình', {}, 450000, {'alias': ['Bình GS'], 'pop': 0.5}),
        ('Dây curoa tay ga', 'phụ tùng', 'sợi', {}, 280000, {'pop': 0.5}),
        ('Lọc gió', 'phụ tùng', 'cái', {}, 90000, {'pop': 0.8}),
        ('Công thay nhớt', 'tiền công', 'lần', {}, 20000, {'made': True, 'pop': 3}),
        ('Công vá xe', 'tiền công', 'lần', {}, 30000, {'made': True, 'pop': 1.5}),
        ('Công bảo dưỡng tổng quát', 'tiền công', 'lần', {}, 150000, {'made': True, 'pop': 1}),
        ('Công sửa phanh', 'tiền công', 'lần', {}, 50000, {'made': True, 'pop': 1}),
        ('Công thay lốp', 'tiền công', 'lần', {}, 30000, {'made': True, 'pop': 0.8}),
        ('Công vệ sinh nồi xe tay ga', 'tiền công', 'lần', {}, 120000, {'made': True, 'pop': 0.6})]),
    'dien_thoai_may': ('Cửa hàng điện thoại', 'DT', [
        ('iPhone 13 128GB cũ', 'điện thoại', 'máy', {}, 9800000, {'alias': ['IP13 128 cũ'], 'pop': 1.2}),
        ('iPhone 15 Pro 256GB', 'điện thoại', 'máy', {}, 27500000, {'alias': ['IP15 Pro 256'], 'pop': 0.6}),
        ('Samsung Galaxy A55 5G', 'điện thoại', 'máy', {}, 8900000, {'alias': ['SS A55'], 'pop': 1}),
        ('Xiaomi Redmi Note 13', 'điện thoại', 'máy', {}, 4600000, {'alias': ['Redmi N13'], 'pop': 1.2}),
        ('OPPO Reno11 F', 'điện thoại', 'máy', {}, 8200000, {'pop': 0.8}),
        ('Ốp lưng silicon', 'phụ kiện', 'cái', {}, 80000, {'pop': 2.5}),
        ('Kính cường lực', 'phụ kiện', 'miếng', {}, 100000, {'alias': ['Cường lực'], 'pop': 2.5}),
        ('Cáp sạc nhanh Type-C', 'phụ kiện', 'sợi', {}, 150000, {'pop': 1.5}),
        ('Củ sạc 20W', 'phụ kiện', 'cái', {}, 350000, {'pop': 1}),
        ('Tai nghe Bluetooth', 'phụ kiện', 'cái', {}, 450000, {'pop': 0.8}),
        ('Công dán cường lực', 'dịch vụ', 'lần', {}, 20000, {'made': True, 'pop': 1})]),
}

# tên cột thêm (chỉ khi --b1311: không đổi dòng ngẫu nhiên của các bộ cũ)
POOL = {
    'thu_cu': ['Thu máy cũ', 'Trừ máy cũ', 'Giá thu cũ'],
    'diem': ['Dùng điểm', 'Trừ điểm', 'Điểm quy đổi (đ)'],
    'han': ['Hạn TT', 'Hạn thanh toán', 'han_tt'],
    'imei': ['IMEI', 'Số IMEI', 'imei'],
}
DESC = {'thu_cu': 'giá trị máy cũ khách đổi, trừ vào số tiền khách trả', 'diem': 'số tiền khách dùng điểm tích luỹ để trừ',
        'han': 'hạn thanh toán của đơn ghi nợ', 'imei': 'số IMEI của máy (mỗi máy một số)'}
W.PAY_VN.setdefault('tra_gop', ['Trả góp', 'Trả góp HD Saison', 'Góp FE Credit'])
qgen.PAY_TXT.setdefault('tra_gop', 'trả góp')


def tien(R, v, rich=True):
    return W.fmt_money(R, v, ['plain', 'dot', 'k', 'dotd', 'tr'] if rich else ['plain', 'dot'])


def tien_tay(R, v):
    """Tiền ghi tay: 640k, 1tr2, 1.250.000."""
    v = int(v)
    if v >= 1000000 and v % 100000 == 0 and R.random() < 0.5:
        tr, du = divmod(v, 1000000)
        return '%dtr%s' % (tr, ('%d' % (du // 100000)) if du else '')
    return W.fmt_money(R, v, ['k', 'k', 'dot', 'plain'])


# ------------------------------------------------------------------ 3. cấu hình loại shop (trước mô phỏng)
KIEU_BAN_LE = ('', 'rx_lo', 'coc', 'sua_xe', 'dien_thoai', 'diem')
KIEU_DICH_VU = ('sac', 'thue')


def cau_hinh_them(R, S, kieu, layout):
    if kieu == 'rx_lo':
        S['stock'] = True
        S['lots'] = True
        S['suppliers'] = ['Cty Dược Hậu Giang', 'Cty CP Traphaco', 'Nhà phân phối Zuellig', 'Cty Dược phẩm Imexpharm'][:R.randint(2, 4)]
        S.pop('odisc', None)
    elif kieu == 'coc':
        S['deposit'] = True
        S.pop('pays', None)
    elif kieu == 'sua_xe':
        S['sua_xe'] = True
        for k in ('stock', 'chans', 'delivery', 'odisc', 'deposit'):
            S.pop(k, None)
        S['qdist'] = [1, 1, 1, 2]
        S['kdist'] = [30, 35, 20, 10, 5]
        S['p_walkin'] = round(R.uniform(0.05, 0.12), 2)
        S['cust_code'] = False
        S['p_big'] = 0
        S['pays'] = [('cash', 55), ('transfer', 35), ('debt', 10)]
    elif kieu == 'dien_thoai':
        S['dien_thoai'] = True
        S['qdist'] = [1]
        S['kdist'] = [50, 35, 15, 0, 0]
        S['p_big'] = 0
        S.pop('deposit', None)
        S['pays'] = [('cash', 40), ('transfer', 45), ('ewallet', 15)]
    elif kieu == 'diem':
        S['diem'] = True
        S['cust_code'] = True
        S.pop('deposit', None)
    # điều kiện của kiểu sổ
    if layout == 'tron_nguon':
        S['cust_code'] = False
        S['chans'] = [('store', 55), ('shopee', 20), ('zalo', 13), ('facebook', 12)]
        S['delivery'] = ('shopee', 'zalo', 'facebook')
        S['pays'] = [('cash', 45), ('transfer', 35), ('ewallet', 10), ('cod', 10)]
        S.pop('deposit', None)
    elif layout == 'ghi_tay_so_phu':
        S['cust_code'] = False
        for k in ('chans', 'delivery', 'staff', 'odisc', 'deposit', 'stock'):
            S.pop(k, None)
        S['pays'] = [('cash', 55), ('transfer', 30), ('debt', 15)]
        S['p_ldisc'] = 0
    elif layout == 'mot_sheet_khong_ma':
        S.pop('deposit', None)
        S.pop('stock', None)
        if S.get('pays'):
            S['pays'] = [(p, w) for p, w in S['pays'] if p != 'debt']


def _bien_so(R, used):
    tinh = ['59H1', '59X2', '51F3', '43B1', '29E2', '30L5', '60B4', '72C1', '65G1', '92D1']
    while True:
        p = '%s-%03d.%02d' % (R.choice(tinh), R.randint(100, 999), R.randint(10, 99))
        if p not in used:
            used.add(p)
            return p


def sau_sim(R, S):
    """Sau mô phỏng, trước khi ghi file: biển số, phiếu bảo hành, IMEI, thu máy cũ, trả góp, điểm."""
    if S.get('sua_xe'):
        used = set()
        for c in S['custs']:
            c['owner'] = c['name']
            c['name'] = _bien_so(R, used)
        for o in S['orders']:
            if o['cust'] and o['status'] == 'done' and R.random() < 0.05:
                o['bh'] = True
                for l in o['lines']:
                    l.update(price=0, disc=0, amt=0, kind='warranty')
                o['odisc'] = o['ship'] = o['due'] = 0
                o['payments'] = []
                if o['pay'] == 'debt':
                    o['pay'] = 'cash'
    if S.get('dien_thoai'):
        used = set()
        for o in S['orders']:
            phones = [l for l in o['lines'] if S['imap'][l['code']]['group'] == 'điện thoại']
            for l in phones:
                while True:
                    im = '35' + ''.join(R.choice('0123456789') for _ in range(13))
                    if im not in used:
                        used.add(im)
                        break
                l['imei'] = im
            o['thu_cu'] = 0
            if not phones or o['status'] == 'cancel':
                continue
            if R.random() < 0.2:
                o['thu_cu'] = max(500000, sim.r100(phones[0]['amt'] * R.uniform(0.08, 0.35)))
                o['due'] -= o['thu_cu']
            if R.random() < 0.15:
                o['pay'] = 'tra_gop'
            o['payments'] = [(o['date'], o['due'], o['pay'])]
    if S.get('diem'):
        for o in S['orders']:
            o['diem'] = 0
            if not o['cust'] or o['pay'] == 'debt' or R.random() >= 0.25:
                continue
            sub = sum(l['amt'] for l in o['lines'])
            o['diem'] = max(1000, sim.r100(sub * R.uniform(0.03, 0.12)))
            o['due'] -= o['diem']
            if len(o['payments']) == 1:
                dt_, _, k = o['payments'][0]
                o['payments'] = [(dt_, o['due'], k)]


def sau_ghi(S, info):
    """Sau khi ghi file: phiếu bảo hành không phải đơn bán (luật §6 của shop sửa xe)."""
    S['_ghi'] = info
    if S.get('sua_xe'):
        S['_bh'] = [o for o in S['orders'] if o.get('bh')]
        S['orders'] = [o for o in S['orders'] if not o.get('bh')]


def bien_so_nhan(R, p):
    return R.choice([p, p, p.replace('.', ''), p.replace('-', ' '), p.lower(), p.replace('-', '').replace('.', '')])


# ------------------------------------------------------------------ 2. năm kiểu sổ mới (g: sinh.Ghi)
def l_sqlite_pos(g):
    S, R, d = g.S, g.R, g.d
    S['shift_ok'] = True
    fn = R.choice(['pos_export.db', 'POS_data.sqlite', 'may_pos.db'])
    con = sqlite3.connect(os.path.join(d, fn))
    st_id = {'done': 1, 'cancel': 2, 'return': 3, 'ship': 4}
    con.execute('CREATE TABLE order_status (id INTEGER PRIMARY KEY, name TEXT)')
    con.executemany('INSERT INTO order_status VALUES (?,?)', [(1, 'Hoàn thành'), (2, 'Đã huỷ'), (3, 'Trả hàng'), (4, 'Đang giao')])
    payn = {'cash': 'Tiền mặt', 'transfer': 'Chuyển khoản', 'ewallet': 'Ví điện tử', 'cod': 'Thu hộ COD', 'debt': 'Ghi nợ',
            'tra_gop': 'Trả góp'}
    pays = sorted({o['pay'] for o in S['orders'] if o['pay']})
    pid = {p: i + 1 for i, p in enumerate(pays)}
    con.execute('CREATE TABLE payment_methods (id INTEGER PRIMARY KEY, name TEXT)')
    con.executemany('INSERT INTO payment_methods VALUES (?,?)', [(pid[p], payn[p]) for p in pays])
    chn = {'store': 'Tại quầy', 'zalo': 'Zalo', 'facebook': 'Facebook', 'shopee': 'Shopee'}
    chans = sorted({o['chan'] for o in S['orders'] if o['chan']})
    cid_ = {c: i + 1 for i, c in enumerate(chans)}
    if chans:
        con.execute('CREATE TABLE channels (id INTEGER PRIMARY KEY, name TEXT)')
        con.executemany('INSERT INTO channels VALUES (?,?)', [(cid_[c], chn.get(c, c)) for c in chans])
    prod = {it['code']: i + 1 for i, it in enumerate(S['items'])}
    rx = any('rx' in it for it in S['items'])
    con.execute('CREATE TABLE products (id INTEGER PRIMARY KEY, sku TEXT, name TEXT, alias TEXT, category TEXT, base_unit TEXT, '
                'unit_conversion TEXT%s)' % (', is_prescription INTEGER, active_ingredient TEXT' if rx else ''))
    for it in S['items']:
        conv = '; '.join('1 %s = %d %s' % (u, f, it['base']) for u, f in it['units'].items() if f > 1)
        row = [prod[it['code']], it['code'], it['name'], ', '.join(it.get('alias') or []), it['group'], it['base'], conv]
        if rx:
            row += [int(bool(it.get('rx'))), it.get('ing', '')]
        con.execute('INSERT INTO products VALUES (%s)' % ','.join('?' * len(row)), row)
    cust = {}
    if S['cust_code']:
        con.execute('CREATE TABLE customers (id INTEGER PRIMARY KEY, code TEXT, name TEXT, phone TEXT, group_name TEXT)')
        for i, c in enumerate(S['custs'], 1):
            cust[c['id']] = i
            con.execute('INSERT INTO customers VALUES (?,?,?,?,?)', (i, c['id'], c['name'], c['phone'], c['group']))
    extra = [k for k in ('thu_cu', 'diem') if S.get({'thu_cu': 'dien_thoai', 'diem': 'diem'}[k])]
    ocols = ['id INTEGER PRIMARY KEY', 'order_code TEXT', 'created_at INTEGER',
             'customer_id INTEGER' if S['cust_code'] else 'customer_name TEXT'] + \
        (['channel_id INTEGER'] if chans else []) + ['payment_method_id INTEGER'] + (['staff_code TEXT'] if S.get('staff') else []) + \
        ['status_id INTEGER', 'discount INTEGER', 'shipping_fee INTEGER'] + ['%s INTEGER' % k for k in extra] + ['note TEXT']
    con.execute('CREATE TABLE orders (%s)' % ', '.join(ocols))
    con.execute('CREATE TABLE order_items (id INTEGER PRIMARY KEY, order_id INTEGER, product_id INTEGER, unit TEXT, quantity REAL, '
                'unit_price INTEGER, discount INTEGER, line_total INTEGER%s)' % (', imei TEXT' if S.get('dien_thoai') else ''))
    con.execute('CREATE TABLE payments (id INTEGER PRIMARY KEY, order_id INTEGER, paid_at INTEGER, amount INTEGER, kind TEXT)')
    li = pi = 0
    oid = {}
    for k, o in enumerate(S['orders'], 1):
        oid[o['id']] = k
        local = D.datetime(o['date'].year, o['date'].month, o['date'].day, *o['t'])
        ts = calendar.timegm((local - D.timedelta(hours=7)).timetuple())
        row = [k, o['id'], ts, cust.get(o['cust']) if S['cust_code'] else (g.cust(o) if o['cust'] else None)]
        if chans:
            row.append(cid_.get(o['chan']))
        row.append(pid.get(o['pay']))
        if S.get('staff'):
            row.append(o['staff'])
        row += [st_id[o['status']], int(o['odisc']), int(o['ship'])] + [int(o.get(x, 0)) for x in extra] + [None]
        con.execute('INSERT INTO orders VALUES (%s)' % ','.join('?' * len(row)), row)
        for l in o['lines']:
            li += 1
            r = [li, k, prod[l['code']], l['unit'], l['qty'], int(l['price']), int(l['disc']), int(l['amt'])]
            if S.get('dien_thoai'):
                r.append(l.get('imei'))
            con.execute('INSERT INTO order_items VALUES (%s)' % ','.join('?' * len(r)), r)
        for dt_, a, kk in o['payments']:
            pi += 1
            when = D.datetime(dt_.year, dt_.month, dt_.day, R.randint(8, 21), R.randint(0, 59))
            lab = {'cọc': 'deposit', 'trả': 'debt_payment' if dt_ > o['date'] else 'payment', 'cod': 'cod'}.get(kk, 'payment')
            con.execute('INSERT INTO payments VALUES (?,?,?,?,?)', (pi, k, calendar.timegm((when - D.timedelta(hours=7)).timetuple()), int(a), lab))
    con.commit()
    con.close()
    g.skip = {'danh_muc', 'khach', 'thu_tien'}
    g.files.append(('%s (bảng orders, order_items, products%s, payments, order_status, payment_methods%s)'
                    % (fn, ', customers' if S['cust_code'] else '', ', channels' if chans else ''), None))
    g.notes += ['Máy POS xuất nguyên cơ sở dữ liệu SQLite `%s`. `orders` mỗi đơn một dòng, `order_items` mỗi dòng hàng (nối qua '
                '`order_items.order_id = orders.id`), `products` là danh mục (nối qua `product_id`).' % fn,
                '`created_at`, `paid_at` là **Unix timestamp** (số giây, giờ UTC); giờ Việt Nam = UTC + 7.',
                '`status_id` tra bảng `order_status`; `payment_method_id` tra `payment_methods`%s.' % ('; `channel_id` tra `channels`' if chans else ''),
                'Tiền là số nguyên đồng. `discount` của `orders` là giảm giá trên cả đơn, của `order_items` là giảm của dòng; '
                '`line_total` đã trừ giảm của dòng.',
                '`payments` ghi mọi lần thu tiền của đơn (`kind`: `payment` trả lúc mua, `debt_payment` trả nợ sau ngày mua, `cod`, `deposit` cọc).']
    if extra:
        g.notes.append('Cột thêm của `orders`: ' + ', '.join('`%s` (%s)' % (x, DESC[x]) for x in extra) + '.')
    if S['cust_code']:
        g.notes.append('`customers.group_name` là nhóm khách; đơn có `customer_id` trống là khách lẻ.')
    else:
        g.notes.append('`orders.customer_name` trống là khách lẻ.')


def l_tron_nguon(g):
    S, R, d = g.S, g.R, g.d
    S['shift_ok'] = True
    g.status_in_note = False
    line_ks = ['iname', 'unit', 'qty', 'price'] + (['ldisc'] if S.get('p_ldisc') else []) + ['amt']
    by = collections.defaultdict(list)
    for o in S['orders']:
        by[o['chan']].append(o)
    # 1. máy tính tiền tại quầy
    oks = ['datetime', 'oid', 'cust'] + (['pay'] if S.get('pays') else []) + (['staff'] if S.get('staff') else []) + ['status'] + \
        (['odisc'] if S.get('odisc') else [])
    rows = [g.hdr(oks + line_ks)]
    for o in by['store']:
        ov = g.order_vals(o, oks, ['obj', 'dmy'])
        for l in o['lines']:
            rows.append(ov + g.line_vals(l, line_ks))
    W.xl(os.path.join(d, 'BanTaiQuay.xlsx'), [('POS', rows)])
    g.files.append(('BanTaiQuay.xlsx', oks + line_ks))
    # 2. Shopee: bản xuất của sàn, mỗi dòng một sản phẩm, thông tin đơn lặp lại
    sst = {'done': 'Hoàn thành', 'cancel': 'Đã hủy', 'return': 'Trả hàng/Hoàn tiền', 'ship': 'Đang giao'}
    spay = {'cash': 'Tiền mặt', 'transfer': 'Chuyển khoản ngân hàng', 'ewallet': 'ShopeePay', 'cod': 'Thanh toán khi nhận hàng'}
    hdr = ['Mã đơn hàng', 'Ngày đặt hàng', 'Trạng Thái Đơn Hàng', 'Tên Người mua', 'Tên sản phẩm', 'Phân loại hàng', 'Số lượng', 'Giá gốc',
           'Người bán trợ giá', 'Tổng giá bán (sản phẩm)', 'Mã giảm giá của Shop', 'Phí vận chuyển (dự kiến)', 'Phương thức thanh toán']
    rows, used = [], set()
    for o in by['shopee']:
        while True:
            ext = o['date'].strftime('%y%m%d') + ''.join(R.choice('0123456789ABCDEFGHJKMNPQRSTUVWXYZ') for _ in range(8))
            if ext not in used:
                used.add(ext)
                break
        buyer = g.cust(o)
        for l in o['lines']:
            rows.append([ext, '%s %02d:%02d' % (o['date'].isoformat(), o['t'][0], o['t'][1]), sst[o['status']], buyer,
                         W.item_label(R, S['imap'][l['code']]), l['unit'], l['qty'], int(l['price']), int(l['disc']), int(l['amt']),
                         int(o['odisc']), int(o['ship']), spay[o['pay']]])
    W.wcsv(os.path.join(d, 'Shopee_DonHang.csv'), hdr, rows)
    g.files.append(('Shopee_DonHang.csv', None))
    # 3. đơn nhắn tin Zalo / Facebook ghi tay vào Excel, mỗi kênh một sheet
    sheets = []
    for ch, nm in (('zalo', 'Zalo'), ('facebook', 'Facebook')):
        rs = [['STT', 'Ngày', 'Giờ', 'Khách', 'Hàng', 'SL', 'ĐVT', 'Giá', 'Thành tiền', 'Ship', 'Thanh toán', 'Ghi chú']]
        for k, o in enumerate(by[ch], 1):
            for i, l in enumerate(o['lines']):
                head = [k, o['date'].strftime('%d/%m/%Y'), '%02d:%02d' % o['t'][:2], g.cust(o)] if i == 0 else ['', '', '', '']
                tail = [tien(R, o['ship'], g.rich), R.choice(W.PAY_VN[o['pay']]), W.status_label(R, o['status'], qgen_note())] \
                    if i == 0 else ['', '', '']
                rs.append(head + [W.item_label(R, S['imap'][l['code']]), l['qty'], l['unit'], tien(R, l['price'], g.rich),
                                  tien(R, l['amt'], g.rich)] + tail)
        sheets.append((nm, rs))
    W.xl(os.path.join(d, 'DonOnline_Zalo_Facebook.xlsx'), sheets)
    g.files.append(('DonOnline_Zalo_Facebook.xlsx', None))
    g.notes += ['Đơn đến từ ba nguồn, mỗi nguồn một kiểu file: `BanTaiQuay.xlsx` (máy tính tiền, đơn bán tại quầy), '
                '`Shopee_DonHang.csv` (bản xuất của sàn Shopee), `DonOnline_Zalo_Facebook.xlsx` (đơn nhắn tin, mỗi kênh một sheet). '
                'Cộng cả ba nguồn mới là toàn bộ đơn của shop; kênh của đơn là nguồn của nó.',
                '`Shopee_DonHang.csv`: mỗi dòng một sản phẩm; mã đơn, ngày, trạng thái, người mua, `Mã giảm giá của Shop` (giảm giá '
                'trên cả đơn, tính bằng tiền), `Phí vận chuyển (dự kiến)`, phương thức thanh toán lặp lại ở mọi dòng của đơn. '
                '`Phân loại hàng` là đơn vị bán; `Giá gốc` là đơn giá, `Người bán trợ giá` là giảm của dòng, '
                '`Tổng giá bán (sản phẩm)` là thành tiền dòng.',
                '`DonOnline_Zalo_Facebook.xlsx`: không có mã đơn, `STT` là số thứ tự đơn trong sheet; thông tin đơn chỉ ghi ở dòng đầu '
                'mỗi đơn; trạng thái huỷ / trả / đang giao ghi ở `Ghi chú` (trống: hoàn thành).',
                'Khách xác định theo tên ghi trên đơn ở cả ba nguồn.']


def qgen_note():
    return {'done': [None, None, None, 'khách quen', 'gói quà'], 'cancel': ['khách huỷ', 'hủy đơn', 'khách bom hàng'],
            'return': ['khách trả lại hàng', 'trả hàng'], 'ship': ['đang giao', 'shipper đang chở']}


def l_so_chuyen_nganh(g):
    S = g.S
    if S.get('sua_xe'):
        return _so_sua_xe(g)
    if S.get('dien_thoai'):
        return _so_ban_may(g)
    return _so_don_me_be(g)


def _so_sua_xe(g):
    S, R, d = g.S, g.R, g.d
    S['shift_ok'] = True
    note = {'cancel': ['khách không sửa nữa', 'huỷ phiếu'], 'return': ['khách trả lại phụ tùng, hoàn tiền', 'trả phụ tùng'],
            'ship': ['xe để lại chưa lấy'], 'done': ['']}
    rows = [['SỔ SỬA XE - ' + S['name'].upper()], [],
            ['Ngày', 'Giờ nhận', 'Số phiếu', 'Biển số', 'Chủ xe', 'SĐT', 'Hạng mục sửa', 'Phụ tùng thay', 'Tiền phụ tùng', 'Tiền công',
             'Tổng', 'Thanh toán', 'Ghi chú']]
    for o in S['orders']:
        c = S['cmap'].get(o['cust'])
        labor = [l for l in o['lines'] if S['imap'][l['code']]['group'] == 'tiền công']
        parts = [l for l in o['lines'] if S['imap'][l['code']]['group'] != 'tiền công']
        hm = '; '.join('%s%s (%s)' % (S['imap'][l['code']]['name'].replace('Công ', ''), ' x%d' % l['qty'] if l['qty'] > 1 else '',
                                      tien_tay(R, l['amt'])) for l in labor)
        pt = ', '.join('%s x%s (%s)' % (W.item_label(R, S['imap'][l['code']]).strip(), num_out(l['qty']), tien_tay(R, l['amt']))
                       for l in parts)
        a_pt, a_c = sum(l['amt'] for l in parts), sum(l['amt'] for l in labor)
        gc = R.choice(['BH', 'bảo hành', 'bảo hành lần trước']) if o.get('bh') else R.choice(note[o['status']])
        rows.append([o['date'].strftime('%d/%m/%Y'), '%02d:%02d' % o['t'][:2], o['id'], bien_so_nhan(R, c['name']) if c else '',
                     c['owner'] if c else R.choice(W.WALKIN), c['phone'] if c else '', hm, pt, tien_tay(R, a_pt), tien_tay(R, a_c),
                     tien_tay(R, a_pt + a_c), R.choice(W.PAY_VN[o['pay']]), gc])
    W.xl(os.path.join(d, 'SoSuaXe.xlsx'), [('So', rows)])
    g.files.append(('SoSuaXe.xlsx', None))
    g.notes += ['`SoSuaXe.xlsx`: mỗi dòng một phiếu sửa (hai dòng đầu là tiêu đề). `Hạng mục sửa` liệt kê tiền công từng việc '
                '`tên việc (tiền)`, thêm ` x2` nếu làm hai lần; `Phụ tùng thay` liệt kê `tên phụ tùng xSố lượng (thành tiền)`, cách nhau dấu phẩy.',
                'Tiền ghi tay: `640k`, `1tr2` (1.200.000), `1.250.000`.',
                'Xe không ghi biển số là khách vãng lai. Trạng thái phiếu ghi ở `Ghi chú` (trống: hoàn thành); phiếu ghi `BH` / `bảo hành` '
                'có tiền 0 đồng là phiếu bảo hành.']


def _so_ban_may(g):
    S, R, d = g.S, g.R, g.d
    S['shift_ok'] = True
    rows = [['Ngày', 'Giờ', 'Số HĐ', 'Khách', 'SĐT', 'Sản phẩm', 'IMEI', 'SL', 'Giá bán', 'Thành tiền', 'Thu máy cũ', 'Hình thức TT',
             'BH đến', 'Ghi chú']]
    note = {'done': [''], 'cancel': ['khách huỷ', 'không lấy máy'], 'return': ['trả máy, hoàn tiền', 'khách trả hàng'],
            'ship': ['đang giao']}
    for o in S['orders']:
        c = S['cmap'].get(o['cust'])
        ls = sorted(o['lines'], key=lambda l: S['imap'][l['code']]['group'] != 'điện thoại')
        for i, l in enumerate(ls):
            it = S['imap'][l['code']]
            bh = (o['date'] + D.timedelta(days=365)).strftime('%d/%m/%Y') if it['group'] == 'điện thoại' else ''
            if i == 0:
                head = [o['date'].strftime('%d/%m/%Y'), '%02d:%02d' % o['t'][:2], o['id'], g.cust(o), c['phone'] if c else '']
                tail = [tien(R, o.get('thu_cu', 0), g.rich) if o.get('thu_cu') else '', R.choice(W.PAY_VN[o['pay']]), bh,
                        R.choice(note[o['status']])]
            else:
                head = ['', '', '', '', '']
                tail = ['', '', bh, '']
            rows.append(head + [W.item_label(R, it), l.get('imei', ''), l['qty'], tien(R, l['price'], g.rich), tien(R, l['amt'], g.rich)]
                        + tail[:2] + tail[2:])
    W.xl(os.path.join(d, 'SoBanMay.xlsx'), [('SoBan', rows)])
    g.files.append(('SoBanMay.xlsx', None))
    g.notes += ['`SoBanMay.xlsx`: mỗi dòng một sản phẩm; thông tin đơn (ngày, số HĐ, khách, thu máy cũ, hình thức thanh toán, ghi chú) '
                'chỉ ghi ở dòng đầu mỗi đơn. Máy ghi `IMEI` riêng từng chiếc.',
                '`Thu máy cũ`: giá trị máy cũ khách đổi, trừ vào số tiền khách trả. `Hình thức TT` có `Trả góp` (qua công ty tài chính).',
                'Trạng thái đơn ghi ở `Ghi chú` (trống: hoàn thành).']


def _so_don_me_be(g):
    S, R, d = g.S, g.R, g.d
    S['shift_ok'] = True
    rows = [['Ngày giờ', 'Mã đơn', 'Mã KH', 'Kênh', 'Sản phẩm', 'ĐVT', 'SL', 'Đơn giá', 'Thành tiền', 'Mã voucher', 'Giảm voucher',
             'Dùng điểm (đ)', 'Phí ship', 'Thanh toán', 'Trạng thái']]
    for o in S['orders']:
        for i, l in enumerate(o['lines']):
            it = S['imap'][l['code']]
            if i == 0:
                head = [W.fmt_date(R, o['date'], ['obj', 'dmy'], o['t'][:2]), o['id'], o['cust'] or '',
                        R.choice(W.CHAN_VN[o['chan']]) if o['chan'] else '']
                tail = ['MB%dK' % (o['odisc'] // 1000) if o['odisc'] else '', int(o['odisc']) or '', int(o.get('diem', 0)) or '',
                        int(o['ship']) or '', R.choice(W.PAY_VN[o['pay']]), g.status(o) or '']
            else:
                head, tail = ['', '', '', ''], [''] * 6
            rows.append(head + [W.item_label(R, it), l['unit'], l['qty'], tien(R, l['price'], g.rich), tien(R, l['amt'], g.rich)] + tail)
    W.xl(os.path.join(d, 'SoDonHang.xlsx'), [('Don', rows)])
    g.files.append(('SoDonHang.xlsx', None))
    g.notes += ['`SoDonHang.xlsx`: mỗi dòng một sản phẩm; thông tin đơn chỉ ghi ở dòng đầu mỗi đơn.',
                '`Giảm voucher` là tiền giảm trên cả đơn theo mã voucher; `Dùng điểm (đ)` là số tiền khách dùng điểm tích luỹ để trừ; '
                'cả hai trừ vào số tiền khách trả.']


def l_ghi_tay_so_phu(g):
    S, R, d = g.S, g.R, g.d
    S['shift_ok'] = False
    g.status_in_note = False
    ttn = {'cash': ['tm', 'TM', 'tiền mặt'], 'transfer': ['ck', 'CK', 'chuyển khoản'], 'debt': ['nợ', 'ghi nợ', 'chưa trả']}
    by_m = collections.defaultdict(list)
    for o in S['orders']:
        by_m[(o['date'].year, o['date'].month)].append(o)
    sheets, so = [], {}
    for (y, m), os_ in sorted(by_m.items()):
        rows = [['SỔ BÁN HÀNG THÁNG %d/%d' % (m, y)], ['Đơn', 'Khách', 'Hàng', 'SL', 'Giá', 'Thành tiền', 'TT']]
        by_d = collections.defaultdict(list)
        for o in os_:
            by_d[o['date']].append(o)
        for day in sorted(by_d):
            rows.append(['Ngày %02d/%02d' % (day.day, day.month)])
            tot = 0
            for k, o in enumerate(by_d[day], 1):
                so[o['id']] = (day, k)
                for i, l in enumerate(o['lines']):
                    it = S['imap'][l['code']]
                    sl = '%s %s' % (num_out(l['qty']), l['unit'])
                    if i == 0:
                        rows.append([k, g.cust(o) if o['cust'] else R.choice(['khách lẻ', 'kl', 'khách vãng lai']), W.item_label(R, it), sl,
                                     tien_tay(R, l['price']), tien_tay(R, l['amt']), R.choice(ttn[o['pay']])])
                    else:
                        rows.append(['', '', W.item_label(R, it), sl, tien_tay(R, l['price']), tien_tay(R, l['amt']), ''])
                    tot += l['amt']
            if R.random() < 0.3:
                rows.append(['Cộng ngày', '', '', '', '', tien_tay(R, tot), ''])
        sheets.append(('T%d-%d' % (m, y), rows))
    W.xl(os.path.join(d, 'SoGhiTay.xlsx'), sheets)
    viec = {'cancel': ['huỷ', 'khách bỏ không lấy'], 'return': ['trả hàng', 'khách trả lại'], 'ship': ['chưa giao', 'đang giao']}
    ht = [['Ngày đơn', 'Đơn số', 'Việc', 'Ngày trả', 'Ghi chú']]
    no = [['Ngày', 'Khách', 'Đơn', 'Ghi nợ (tổng đơn)', 'Trả']]
    for o in S['orders']:
        day, k = so[o['id']]
        if o['status'] != 'done':
            ht.append([day.strftime('%d/%m/%Y'), k, R.choice(viec[o['status']]),
                       o['ret_date'].strftime('%d/%m/%Y') if o['status'] == 'return' else '', ''])
        if o['pay'] == 'debt' and o['status'] != 'cancel':
            ref = '%02d/%02d-%d' % (day.day, day.month, k)
            same = sum(a for dt_, a, kk in o['payments'] if dt_ == o['date'])
            no.append([day.strftime('%d/%m/%Y'), g.cust(o), ref, tien_tay(R, o['due']), tien_tay(R, same) if same else ''])
            for dt_, a, kk in o['payments']:
                if dt_ > o['date']:
                    no.append([dt_.strftime('%d/%m/%Y'), g.cust(o), ref, '', tien_tay(R, a)])
    no = no[:1] + sorted(no[1:], key=lambda r: (D.datetime.strptime(r[0], '%d/%m/%Y'), r[2]))
    W.xl(os.path.join(d, 'SoPhu.xlsx'), [('Huy_Tra', ht), ('So_No', no)])
    g.files += [('SoGhiTay.xlsx', None), ('SoPhu.xlsx', None)]
    g.skip = {'thu_tien'}          # tiền khách trả nợ nằm ở sổ phụ, không có phiếu thu theo mã đơn
    g.notes += ['Sổ ghi tay chép lại vào Excel: `SoGhiTay.xlsx` mỗi tháng một sheet; dòng `Ngày dd/mm` mở đầu các đơn của ngày đó '
                '(năm theo tên sheet); không ghi giờ bán.',
                '`Đơn` là số thứ tự đơn trong ngày (ngày + số đơn xác định một đơn); khách, thanh toán (`TT`: tm, ck, nợ) chỉ ghi ở dòng '
                'đầu mỗi đơn. `SL` ghi kèm đơn vị (`2 thùng`, `5 kg`). Tiền ghi tay: `640k`, `1tr2` (1.200.000), `1.250.000`.',
                'Dòng `Cộng ngày` là tổng tự cộng, không phải đơn.',
                '`SoPhu.xlsx` là sổ phụ: sheet `Huy_Tra` ghi đơn huỷ, đơn trả hàng (kèm ngày trả), đơn chưa giao, theo ngày + số đơn; '
                'đơn không có trong sheet này là hoàn thành. Sheet `So_No` ghi đơn bán chịu: `Ghi nợ (tổng đơn)` là số khách phải trả '
                'cả đơn, `Trả` là tiền khách trả (cùng ngày mua là trả lúc mua), `Đơn` dạng `dd/mm-số đơn`.']


def l_mot_sheet_khong_ma(g):
    S, R, d = g.S, g.R, g.d
    S['shift_ok'] = True
    # không có mã đơn: một đơn = các dòng cùng thời điểm (đến giây) và cùng khách -> làm thời điểm của mỗi đơn khác nhau
    seen = set()
    for o in S['orders']:
        h, mi, se = o['t']
        free = [x for x in range(60) if (o['date'], h, mi, x) not in seen]
        if (o['date'], h, mi, se) in seen:
            se = R.choice(free)
        o['t'] = (h, mi, se)
        seen.add((o['date'], h, mi, se))
    oks = ['cid'] if S['cust_code'] else ['cust']
    oks += (['chan'] if S.get('chans') else []) + (['pay'] if S.get('pays') else []) + (['staff'] if S.get('staff') else [])
    oks += ['note' if g.status_in_note else 'status'] + (['odisc'] if S.get('odisc') else []) + (['ship'] if S.get('delivery') else [])
    oks += [k for k in ('thu_cu', 'diem') if S.get({'thu_cu': 'dien_thoai', 'diem': 'diem'}[k])]
    line_ks = ['iname', 'unit', 'qty', 'price'] + (['ldisc'] if S.get('p_ldisc') else []) + ['amt'] + (['imei'] if S.get('dien_thoai') else [])
    cot_tg = R.choice(['Thời gian', 'Ngày giờ', 'Thời điểm'])
    rows = [[cot_tg] + g.hdr(oks + line_ks)]
    lvl = [k for k in oks if k in ('odisc', 'ship', 'thu_cu', 'diem')]
    for o in S['orders']:
        ov = g.order_vals(o, oks, [])
        when = R.choice(['%02d/%02d/%d %02d:%02d:%02d' % (o['date'].day, o['date'].month, o['date'].year, *o['t']),
                         D.datetime(o['date'].year, o['date'].month, o['date'].day, *o['t'])])
        for i, l in enumerate(o['lines']):
            v = list(ov)
            if i > 0:
                for k in lvl:
                    v[oks.index(k)] = ''
            rows.append([when] + v + g.line_vals(l, line_ks))
    W.xl(os.path.join(d, 'SoBan.xlsx'), [('Sheet1', rows)])
    g.files.append(('SoBan.xlsx', [k for k in oks] + line_ks))
    g.notes += ['`SoBan.xlsx` chỉ có một sheet, mỗi dòng một dòng hàng, **không có mã đơn**: các dòng liền nhau có cùng `%s` '
                '(ngày giờ đến từng giây) và cùng khách là một đơn.' % cot_tg]
    if lvl:
        g.notes.append('%s chỉ ghi ở dòng đầu của mỗi đơn.' % ', '.join('`%s`' % g.C[k] for k in lvl))


LAYOUT = {'sqlite_pos': l_sqlite_pos, 'tron_nguon': l_tron_nguon, 'so_chuyen_nganh': l_so_chuyen_nganh,
          'ghi_tay_so_phu': l_ghi_tay_so_phu, 'mot_sheet_khong_ma': l_mot_sheet_khong_ma}


# ------------------------------------------------------------------ họ câu riêng (mục 3) và câu không trả lời được (mục 5)
from qgen import U, pick_month, mphrase, dphrase, item_name   # noqa: E402


def F_coc(R, S, t):
    x = pick_month(R, S, t)
    p = month(*x)
    w = mphrase(R, *x, t)
    k = R.random()
    if k < 0.4:
        v = sum(o['deposit'] for o in E.orders_in(S, t, p, statuses=('done', 'ship', 'return', 'cancel')))
        return R.choice(['%s tiệm thu tiền cọc tổng cộng bao nhiêu?', 'Tổng tiền cọc khách đặt %s là bao nhiêu?']) % w, 'number', money(v), []
    if k < 0.75:
        v = sum(o['deposit'] for o in E.orders_in(S, t, p, statuses=('cancel',)))
        return R.choice(['%s tiền cọc của các đơn bị huỷ cộng lại bao nhiêu?', 'Đơn huỷ %s để lại bao nhiêu tiền cọc?']) % w, 'number', money(v), []
    n = sum(1 for o in E.orders_in(S, t, p, statuses=('cancel',)) if o['deposit'] > 0)
    return '%s có mấy đơn huỷ bị mất cọc?' % w, 'number', n, []


def F_sua_xe(R, S, t):
    x = pick_month(R, S, t)
    p = month(*x)
    w = mphrase(R, *x, t)
    a, b = E.clamp(S, t, p)
    k = R.random()
    if k < 0.2:
        return R.choice(['%s tiền công sửa xe thu được bao nhiêu?', 'Tiền công %s là bao nhiêu?']) % w, 'number', E.rev(S, t, p, group='tiền công'), []
    if k < 0.33:
        return '%s tiền phụ tùng bán được bao nhiêu?' % w, 'number', E.rev(S, t, p, group='phụ tùng'), []
    if k < 0.48:
        n = sum(1 for o in S['orders'] + S['_bh'] if a <= o['date'] <= b and o['status'] != 'cancel')
        return R.choice(['%s có bao nhiêu lượt xe vào xưởng, tính cả xe bảo hành?', 'Tính cả xe bảo hành, %s xưởng nhận bao nhiêu lượt xe?']) % w, 'number', n, []
    if k < 0.6:
        n = sum(1 for o in S['_bh'] if a <= o['date'] <= b and o['status'] != 'cancel')
        return '%s có mấy phiếu bảo hành?' % w, 'number', n, []
    if k < 0.72:
        return 'Tiền công chiếm bao nhiêu %% doanh thu %s?' % w, 'percent', r2(E.rev(S, t, p, group='tiền công') / E.rev(S, t, p) * 100), []
    if k < 0.86:
        cs = sorted({o['cust'] for o in E.orders_in(S, t, p) if o['cust']})
        if not cs:
            return None
        c = S['cmap'][R.choice(cs)]
        return '%s xe biển %s sửa hết bao nhiêu tiền?' % (w, bien_so_nhan(R, c['name'])), 'number', E.rev(S, t, p, cust=c['id']), []
    r, tie = E.top_items(S, t, p, None, 'qty', group='phụ tùng')
    if tie:
        return None
    return '%s phụ tùng nào thay nhiều nhất (không tính bảo hành)?' % w, 'string', item_name(S, r), [r]


def F_dien_thoai(R, S, t):
    x = pick_month(R, S, t)
    p = month(*x)
    w = mphrase(R, *x, t)
    k = R.random()
    if k < 0.22:
        v = sum(o.get('thu_cu', 0) for o in E.orders_in(S, t, p))
        return R.choice(['%s tiền thu máy cũ của khách cộng lại bao nhiêu?', '%s cửa hàng thu cũ đổi mới hết bao nhiêu tiền?']) % w, 'number', money(v), []
    if k < 0.4:
        return '%s có bao nhiêu đơn mua trả góp?' % w, 'number', E.nord(S, t, p, pay='tra_gop'), []
    if k < 0.55:
        return 'Doanh thu các đơn trả góp %s là bao nhiêu?' % w, 'number', E.rev(S, t, p, pay='tra_gop'), []
    if k < 0.72:
        return R.choice(['%s bán được bao nhiêu máy điện thoại?', '%s bán ra mấy máy?']) % w, 'number', E.units_of(S, t, p, 'máy'), []
    if k < 0.86:
        cand = [(o, l) for o in E.orders_in(S, t, (S['start'], t)) for l in o['lines'] if l.get('imei') and o['cust']]
        if not cand:
            return None
        o, l = R.choice(cand)
        c = S['cmap'][o['cust']]
        return 'Máy có IMEI %s bán cho khách nào?' % l['imei'], 'string', c['name'], ([c['id']] if S['cust_code'] else [])
    return 'Phụ kiện chiếm bao nhiêu %% doanh thu %s?' % w, 'percent', r2(E.rev(S, t, p, group='phụ kiện') / E.rev(S, t, p) * 100), []


def F_diem(R, S, t):
    x = pick_month(R, S, t)
    p = month(*x)
    w = mphrase(R, *x, t)
    os_ = E.orders_in(S, t, p)
    k = R.random()
    if k < 0.5:
        return R.choice(['%s khách dùng điểm trừ tổng cộng bao nhiêu tiền?', 'Tiền khách đổi điểm %s là bao nhiêu?']) % w, 'number', \
            money(sum(o.get('diem', 0) for o in os_)), []
    if k < 0.8:
        return '%s có bao nhiêu đơn có dùng điểm tích luỹ?' % w, 'number', sum(1 for o in os_ if o.get('diem')), []
    v = collections.Counter()
    for o in os_:
        if o.get('diem') and o['cust']:
            v[o['cust']] += o['diem']
    r = sorted(v, key=lambda c: (-v[c], c))
    if not r or (len(r) > 1 and v[r[0]] == v[r[1]]):
        return None
    c = S['cmap'][r[0]]
    return '%s khách nào dùng điểm nhiều nhất?' % w, 'string', c['name'], [c['id']]


def F_khong_tl(R, S, t):
    """Câu không trả lời được (rulebook §7): thông tin file không ghi, shop không ghi loại thông tin, kỳ ngoài dữ liệu."""
    x = pick_month(R, S, t)
    w = mphrase(R, *x, t)
    info = S.get('_ghi') or {}
    qs = ['%s khách nữ chi bao nhiêu tiền?' % w, '%s khách trên 40 tuổi mua bao nhiêu đơn?' % w,
          'Khách ở quận Bình Thạnh %s mua bao nhiêu tiền?' % w, '%s có bao nhiêu khách biết shop qua quảng cáo?' % w,
          '%s khách chấm trung bình mấy sao?' % w, 'Mức độ hài lòng của khách %s là bao nhiêu %%?' % w,
          '%s tiền điện nước của tiệm là bao nhiêu?' % w, 'Lương nhân viên %s tổng cộng bao nhiêu?' % w,
          'Tiền thuê mặt bằng %s là bao nhiêu?' % w, 'Lãi ròng %s sau khi trừ mọi chi phí là bao nhiêu?' % w,
          '%s có bao nhiêu khách vào xem mà không mua?' % w, 'Đơn giao %s mất trung bình bao lâu mới tới tay khách?' % w,
          'Những ngày trời mưa %s doanh thu giảm bao nhiêu?' % w, '%s nhân viên nào được khách khen nhiều nhất?' % w,
          'Khách đi ô tô tới mua %s chi bao nhiêu tiền?' % w, 'Bao nhiêu khách có sinh nhật trong %s?' % w,
          '%s khách hàng thuộc độ tuổi nào mua nhiều nhất?' % w, 'Khách mới %s biết tới cửa hàng qua kênh nào nhiều nhất?' % w]
    if not info.get('status_in_note'):
        qs += ['%s lý do khách huỷ đơn nhiều nhất là gì?' % w, '%s khách trả hàng chủ yếu vì lý do gì?' % w]
    if not S.get('chans'):
        qs += ['Doanh thu đơn online %s là bao nhiêu?' % w, '%s bán qua Shopee được bao nhiêu tiền?' % w]
    if not S.get('staff'):
        qs += ['Nhân viên nào bán được nhiều tiền nhất %s?' % w, '%s mỗi nhân viên bán được bao nhiêu đơn?' % w]
    if not S.get('stock'):
        qs += ['Hết hôm nay cửa hàng còn tồn bao nhiêu hàng?', '%s nhập hàng hết bao nhiêu tiền?' % w,
               'Nhà cung cấp nào bán cho cửa hàng nhiều nhất %s?' % w]
    if not S.get('lots'):
        qs += ['Lô hàng nào sắp hết hạn sử dụng?', 'Hiện còn bao nhiêu hàng hết hạn trong 30 ngày tới?']
    if not (S.get('deposit') or any(p_ == 'debt' for p_, _ in S.get('pays') or [])):
        qs += ['Khách nào đang nợ nhiều nhất?', 'Đến hết hôm nay khách còn nợ bao nhiêu tiền?']
    if not S.get('shift_ok', True):
        qs += ['Ca sáng %s bán được bao nhiêu tiền?' % w, 'Giờ cao điểm %s là mấy giờ?' % w]
    if not S['cust_code']:
        qs += ['Khách nhóm sỉ %s mua bao nhiêu tiền?' % w, 'Nhóm khách thân thiết %s chiếm bao nhiêu %% doanh thu?' % w]
    # kỳ nằm hoàn toàn ngoài khoảng dữ liệu
    y, m = S['start'].year, S['start'].month - R.randint(2, 6)
    while m < 1:
        y, m = y - 1, m + 12
    qs += [R.choice(['Doanh thu %s là bao nhiêu?', '%s bán được bao nhiêu đơn?', '%s mặt hàng nào bán chạy nhất?']) % say_month(R, y, m)]
    if t >= S['end']:
        y, m = (S['end'].year + (S['end'].month + 2 - 1) // 12, (S['end'].month + 2 - 1) % 12 + 1)
        qs.append('Doanh thu %s là bao nhiêu?' % say_month(R, y, m))
    return (R.choice(qs),) + U


def F_unans(R, S, t):
    """qgen.F_unans, bỏ câu hỏi lý do huỷ / trả ở shop ghi trạng thái trong ghi chú (ghi chú có lý do: "Huỷ - hết hàng")."""
    for _ in range(5):
        out = qgen.F_unans(R, S, t)
        if not ((S.get('_ghi') or {}).get('status_in_note') and 'lý do' in out[0]):
            return out
    return None


def trong_so(S, fams):
    """Nhân trọng số họ câu theo file mô tả shop (`tang_ho`: {họ: hệ số}), để dồn câu vào phần cần học của từng bộ."""
    t = S.get('_tang_ho') or {}
    return [(F_unans if f is qgen.F_unans else f, w * t.get(f.__name__[2:], 1)) for f, w in fams]


def ho_them(S):
    out = [(F_khong_tl, 3)]
    if S.get('lots'):
        out.append((qgen.F_vet, 7))
    if S.get('deposit'):
        out.append((F_coc, 6))
    if S.get('sua_xe'):
        out.append((F_sua_xe, 8))
    if S.get('dien_thoai'):
        out.append((F_dien_thoai, 7))
    if S.get('diem'):
        out.append((F_diem, 5))
    return out


# ------------------------------------------------------------------ shop dịch vụ: trạm sạc, cho thuê
THUE = {
    'thue_do_cuoi': ('Tiệm cho thuê đồ cưới', 'CT', [('Váy cưới đuôi dài', 'váy cưới', 800000, 2000000), ('Váy cưới ngắn', 'váy cưới', 500000, 1500000),
                                                     ('Vest chú rể', 'vest', 250000, 500000), ('Áo dài bưng quả', 'áo dài', 80000, 200000),
                                                     ('Mâm quả rồng phượng', 'mâm quả', 300000, 500000), ('Cổng hoa cưới', 'trang trí', 900000, 1000000)],
                     (1, 3), [1, 1, 1, 2, 4, 6]),
    'thue_xe_may': ('Cửa hàng cho thuê xe máy', 'XM', [('Xe số Wave', 'xe số', 120000, 2000000), ('Xe số Sirius', 'xe số', 130000, 2000000),
                                                       ('Xe ga Vision', 'xe ga', 180000, 3000000), ('Xe ga Air Blade', 'xe ga', 200000, 3000000),
                                                       ('Xe côn tay Exciter', 'xe côn', 250000, 5000000), ('Mũ bảo hiểm thêm', 'phụ kiện', 10000, 0)],
                    (1, 7), [1, 1, 1, 1, 2]),
    'thue_cam_trai': ('Tiệm cho thuê đồ cắm trại', 'CM', [('Lều 4 người', 'lều', 120000, 300000), ('Lều 2 người', 'lều', 80000, 200000),
                                                          ('Túi ngủ', 'đồ ngủ', 40000, 100000), ('Bếp gas mini', 'nấu ăn', 50000, 100000),
                                                          ('Ghế xếp', 'bàn ghế', 20000, 50000), ('Đèn cắm trại', 'đèn', 30000, 50000)],
                      (1, 4), [1, 1, 2, 2, 3, 4]),
}


def cau_hinh_dich_vu(R, spec, sid, ten_rieng):
    kieu = spec['kieu']
    start = D.date(2025, R.randint(1, 7), 1)
    end = min(start + D.timedelta(days=R.randint(420, 600)), D.date(2026, 9, 30))
    if kieu == 'sac':
        return dict(id=sid, nganh='tram_sac', kieu='sac', kind='charge', name='Trạm sạc xe điện %s' % R.choice(ten_rieng), start=start, end=end,
                    lam=round(R.uniform(25, 45), 1))
    title, prefix, items, days, qd = THUE[spec['nganh']]
    its = [dict(code='%s%03d' % (prefix, i), name=n, group=g_, rate=r_, coc=c_) for i, (n, g_, r_, c_) in enumerate(items, 1)]
    return dict(id=sid, nganh=spec['nganh'], kieu='thue', kind='rental', name='%s %s' % (title, R.choice(ten_rieng)), start=start, end=end,
                lam=round(R.uniform(4, 9), 1), items=its, days=days, qdist=qd)


def sim_thue(R, S):
    used = set()
    S['custs'] = [dict(id='KH%04d' % i, name=n, phone=phone(R), w=R.paretovariate(1.3)) for i, n in enumerate(make_names(R, 180, used), 1)]
    cw = [c['w'] for c in S['custs']]
    pop = [R.uniform(0.4, 2.5) for _ in S['items']]
    hd, n_ = [], 0
    for d in daterange(S['start'], S['end']):
        lam = S['lam'] * (1.5 if d.weekday() >= 5 else 1)
        for _ in range(sim.poisson(R, lam)):
            n_ += 1
            it = R.choices(S['items'], pop)[0]
            c = R.choices(S['custs'], cw)[0]
            q = R.choice(S['qdist'])
            plan = R.randint(*S['days'])
            st = D.datetime(d.year, d.month, d.day, R.randint(7, 19), R.randint(0, 59))
            hen = d + D.timedelta(days=plan)
            x = R.random()
            status, tra, hong = 'ok', None, 0
            if x < 0.03:
                status = 'huy'
            else:
                tre = 0 if R.random() < 0.85 else R.randint(1, 3)
                som = 1 if (plan > 1 and R.random() < 0.06) else 0
                tra = hen + D.timedelta(days=tre - som)
                if R.random() < 0.04:
                    hong = R.choice([100000, 200000, 300000, 500000])
            hd.append(dict(id='HD%05d' % n_, date=d, st=st, cust=c['id'], item=it['code'], qty=q, rate=it['rate'], coc=it['coc'] * q, hen=hen,
                           tra=tra, hong=hong, status=status, pay=R.choice(['tiền mặt', 'chuyển khoản', 'chuyển khoản', 'ví điện tử'])))
    S['contracts'] = hd
    S['imap'] = {it['code']: it for it in S['items']}
    S['cmap'] = {c['id']: c for c in S['custs']}


def tien_thue(h):
    """Theo §6 của shop cho thuê: tiền thuê theo số ngày thực tế (tối thiểu 1), phụ thu trễ 50% giá ngày, phí hư hỏng."""
    days = max(1, (h['tra'] - h['date']).days)
    tre = max(0, (h['tra'] - h['hen']).days)
    return h['rate'] * h['qty'] * days + money(h['rate'] * h['qty'] * tre * 0.5) + h['hong']


def thue_q(R, S, t):
    x = pick_month(R, S, t)
    a, b = E.clamp(S, t, month(*x))
    w = mphrase(R, *x, t)
    hd = [h for h in S['contracts'] if h['date'] <= t]
    nhan = [h for h in hd if a <= h['date'] <= b and h['status'] != 'huy']
    tra = [h for h in hd if h['tra'] and a <= h['tra'] <= min(b, t)]
    k = R.randrange(10)
    if k == 0:
        return R.choice(['Doanh thu cho thuê %s là bao nhiêu?', '%s tiệm thu được bao nhiêu tiền thuê?']) % w, 'number', money(sum(tien_thue(h) for h in tra)), []
    if k == 1:
        return '%s có bao nhiêu hợp đồng thuê?' % w, 'number', len(nhan), []
    if k == 2:
        c = collections.Counter()
        for h in nhan:
            c[h['item']] += 1
        r = sorted(c, key=lambda i: (-c[i], i))
        if not r or (len(r) > 1 and c[r[0]] == c[r[1]]):
            return None
        return '%s món nào được thuê nhiều lượt nhất?' % w, 'string', S['imap'][r[0]]['name'], [r[0]]
    if k == 3:
        X = t if R.random() < 0.5 else S['start'] + D.timedelta(days=R.randint(30, (t - S['start']).days))
        n = sum(h['qty'] for h in hd if h['status'] != 'huy' and h['date'] <= X and (h['tra'] is None or h['tra'] > X))
        return 'Hết ngày %s có bao nhiêu món đang cho thuê (chưa trả)?' % dphrase(R, X), 'number', n, []
    if k == 4:
        X = t if R.random() < 0.5 else S['start'] + D.timedelta(days=R.randint(30, (t - S['start']).days))
        v = sum(h['coc'] for h in hd if h['status'] != 'huy' and h['date'] <= X and (h['tra'] is None or h['tra'] > X))
        return 'Hết ngày %s tiệm đang giữ bao nhiêu tiền cọc của khách?' % dphrase(R, X), 'number', money(v), []
    if k == 5:
        return '%s có mấy hợp đồng trả đồ trễ hẹn?' % w, 'number', sum(1 for h in tra if h['tra'] > h['hen']), []
    if k == 6:
        v = sum(money(h['rate'] * h['qty'] * max(0, (h['tra'] - h['hen']).days) * 0.5) for h in tra)
        return '%s thu được bao nhiêu tiền phụ thu trễ hạn?' % w, 'number', money(v), []
    if k == 7:
        if not tra:
            return None
        return 'Trung bình mỗi hợp đồng trả đồ %s thuê mấy ngày?' % w, 'number', r2(sum(max(1, (h['tra'] - h['date']).days) for h in tra) / len(tra)), []
    if k == 8:
        c = collections.Counter()
        for h in nhan:
            c[h['cust']] += 1
        r = sorted(c, key=lambda i: (-c[i], i))
        if not r or (len(r) > 1 and c[r[0]] == c[r[1]]):
            return None
        return '%s khách nào thuê nhiều lần nhất?' % w, 'string', S['cmap'][r[0]]['name'], [r[0]]
    return (R.choice(['%s khách thuê đồ để đi đám cưới ở tỉnh nào nhiều nhất?' % w, '%s món nào bị khách chê nhiều nhất?' % w,
                      '%s khách thuê bao nhiêu lần vì đồ cũ bị bẩn?' % w]),) + U


def sac_q(R, S, t):
    if R.random() < 0.08:
        x = pick_month(R, S, t)
        w = mphrase(R, *x, t)
        return (R.choice(['%s xe hãng VinFast sạc bao nhiêu kWh?' % w, '%s tài xế nào đợi sạc lâu nhất?' % w,
                          '%s xe ô tô hay xe máy điện sạc nhiều hơn?' % w, '%s trạm mất điện lưới bao nhiêu giờ?' % w]),) + U
    return qgen.charge_q(R, S, t)


def ghi_dich_vu(R, S, d):
    if S['kieu'] == 'sac':
        return _ghi_sac(R, S, d)
    return _ghi_thue(R, S, d)


def _ghi_sac(R, S, d):
    def bs(p):
        return R.choice([p, p, p.replace('.', ''), p.replace('-', ' '), p.lower(), p.replace('-', '').replace('.', '')])
    cot = R.choice([['ma_phien', 'tru', 'bien_so', 'bat_dau', 'ket_thuc', 'kwh', 'don_gia_kwh', 'thanh_tien', 'thanh_toan', 'trang_thai'],
                    ['Mã phiên', 'Trụ', 'Biển số', 'Bắt đầu', 'Kết thúc', 'Điện năng (kWh)', 'Đơn giá/kWh', 'Thành tiền', 'Thanh toán', 'Trạng thái']])
    rows = []
    for s in S['sessions']:
        rows.append([s['id'], s['post'], bs(s['plate']), s['st'].strftime(R.choice(['%d/%m/%Y %H:%M:%S', '%Y-%m-%d %H:%M:%S'])),
                     s['en'].strftime('%d/%m/%Y %H:%M:%S'), ('%.3f' % s['kwh']).replace('.', R.choice([',', '.'])), s['price'], s['amt'], s['pay'],
                     s['status']])
    if R.random() < 0.5:
        W.wcsv(os.path.join(d, 'phien_sac.csv'), cot, rows)
        fn = 'phien_sac.csv'
    else:
        W.xl(os.path.join(d, 'PhienSac.xlsx'), [('Phien', [cot] + rows)])
        fn = 'PhienSac.xlsx'
    W.wcsv(os.path.join(d, 'tru_sac.csv'), ['tru', 'loai', 'cong_suat_kw'], [[p['id'], p['kind'], p['kw']] for p in S['posts']])
    gia = []
    for k_ in ('AC', 'DC'):
        for tier in ('thấp điểm', 'cao điểm'):
            gia.append([k_, tier, S['start'].strftime('%d/%m/%Y'), S['prices'][k_][tier]])
            gia.append([k_, tier, S['price_change'][0].strftime('%d/%m/%Y'), S['price_change'][1][k_][tier]])
    W.wcsv(os.path.join(d, 'bang_gia.csv'), ['loai_tru', 'khung', 'ap_dung_tu', 'gia_kwh'], gia)
    W.readme(os.path.join(d, 'README.md'), 'Dữ liệu %s' % S['id'], """
%s có %d trụ (AC và DC). Hệ thống xuất mỗi lượt sạc một dòng.

## File
- `%s`: %s (mã phiên, mã trụ, biển số xe do nhân viên gõ tay nên cách ghi không thống nhất, giờ bắt đầu, giờ kết thúc, điện năng sạc
  (dấu thập phân có thể là `,` hoặc `.`), đơn giá mỗi kWh, thành tiền, thanh toán, trạng thái: `hoàn tất`; `lỗi` là phiên lỗi, không thu tiền).
- `tru_sac.csv`: loại trụ và công suất.
- `bang_gia.csv`: giá mỗi kWh theo loại trụ và khung giờ, áp dụng từ ngày ghi.

## Quy ước
- Dữ liệu từ %s đến hết %s.
- Khung **cao điểm** 17:00–21:59, còn lại là **thấp điểm**; phiên tính theo giờ bắt đầu.
""" % (S['name'], len(S['posts']), fn, ', '.join('`%s`' % c for c in cot), S['start'].strftime('%d/%m/%Y'), S['end'].strftime('%d/%m/%Y')))
    return {'layout': 'phien_sac', 'readme': 'cot', 'status_in_note': False, 'cols': [(fn, None)]}


def _ghi_thue(R, S, d):
    st = {'ok': lambda h: 'Đã trả' if h['tra'] and h['tra'] <= S['end'] else 'Đang thuê', 'huy': lambda h: R.choice(['Huỷ', 'Khách huỷ'])}
    rows = [['Mã HĐ', 'Ngày nhận', 'Khách', 'SĐT', 'Món thuê', 'SL', 'Giá thuê/ngày', 'Hẹn trả', 'Ngày trả', 'Tiền cọc', 'Phí hư hỏng',
             'Thanh toán', 'Trạng thái']]
    for h in S['contracts']:
        c = S['cmap'][h['cust']]
        tra = h['tra'] if h['tra'] and h['tra'] <= S['end'] else None
        rows.append([h['id'], W.fmt_date(R, h['date'], ['obj', 'dmy'], (h['st'].hour, h['st'].minute)), W.cust_label(R, c, False), c['phone'],
                     W.item_label(R, S['imap'][h['item']]), h['qty'], W.fmt_money(R, h['rate'], ['plain', 'dot', 'k']), h['hen'].strftime('%d/%m/%Y'),
                     tra.strftime('%d/%m/%Y') if tra else '', W.fmt_money(R, h['coc'], ['plain', 'dot', 'k']) if h['coc'] else 0,
                     W.fmt_money(R, h['hong'], ['plain', 'dot', 'k']) if h['hong'] else '', h['pay'], st[h['status']](h)])
    W.xl(os.path.join(d, 'SoChoThue.xlsx'), [('HopDong', rows)])
    dm = [['Mã món', 'Tên món', 'Nhóm', 'Giá thuê/ngày', 'Cọc mỗi món']] + [[it['code'], it['name'], it['group'], it['rate'], it['coc']] for it in S['items']]
    W.xl(os.path.join(d, 'DanhMucDoThue.xlsx'), [('DanhMuc', dm)])
    W.readme(os.path.join(d, 'README.md'), 'Dữ liệu %s' % S['id'], """
%s ghi mỗi hợp đồng thuê một dòng.

## File
- `SoChoThue.xlsx`: `Mã HĐ`, `Ngày nhận` (ngày giờ khách nhận đồ), `Khách`, `SĐT`, `Món thuê`, `SL`, `Giá thuê/ngày` (một món), `Hẹn trả`
  (ngày hẹn trả), `Ngày trả` (ngày trả thực tế; trống là chưa trả), `Tiền cọc` (cả hợp đồng, trả lại khách khi trả đồ), `Phí hư hỏng`
  (thu thêm khi đồ hư), `Thanh toán`, `Trạng thái` (`Đã trả`, `Đang thuê`, `Huỷ`: huỷ trước khi nhận đồ, không thu gì).
- `DanhMucDoThue.xlsx`: giá thuê mỗi ngày và tiền cọc mỗi món.

## Quy ước
- Dữ liệu từ %s đến hết %s.
""" % (S['name'], S['start'].strftime('%d/%m/%Y'), S['end'].strftime('%d/%m/%Y')))
    return {'layout': 'so_cho_thue', 'readme': 'cot', 'status_in_note': False, 'cols': [('SoChoThue.xlsx', None), ('DanhMucDoThue.xlsx', None)]}


def sim_dich_vu(R, S):
    if S['kieu'] == 'sac':
        sim.sim_charge(R, S)
        S['items'] = []
    else:
        sim_thue(R, S)


def cau_hoi_dich_vu(R, S, n, van):
    f = sac_q if S['kieu'] == 'sac' else thue_q
    res, seen, tries = [], set(), 0
    while len(res) < n and tries < n * 40:
        tries += 1
        t = qgen.asof_dates(R, S, 1)[0]
        try:
            out = f(R, S, t)
        except (E.Unans, ZeroDivisionError, IndexError, ValueError, TypeError):
            continue
        if not out:
            continue
        q, typ, ans, alias = out
        if (q, t) in seen:
            continue
        seen.add((q, t))
        res.append(dict(q=van(R, q), raw=q, t=t, type=typ, answer=ans, alias=alias, ho=S['kieu'], ke_hoach=None,
                        ghi_chu='shop dịch vụ (%s): ngôn ngữ kế hoạch chưa có bảng này' % S['kieu']))
    return res


# ------------------------------------------------------------------ rulebook §6 cho từng shop có luật riêng
def muc6(S):
    k = S.get('kieu') or ''
    if S.get('lots'):
        return ['Thuốc kê đơn theo cột **Kê đơn** của danh mục (`Có`, `x`, `TRUE`, `1` là kê đơn). Doanh thu theo hoạt chất: chỉ sản phẩm có '
                'hoạt chất ghi **đúng như vậy**; thuốc phối hợp (nhiều chất nối bằng ` + `) là một loại riêng.',
                'Hàng bán xuất theo lô ghi ở `XuatTheoLo`; hàng khách trả về lại đúng lô đã xuất. Lô hàng tính theo §5.']
    if S.get('deposit'):
        return ['Mọi đơn thu **cọc** lúc đặt. Cọc là một phần tiền khách trả cho đơn, **không** phải doanh thu riêng; cọc của đơn huỷ '
                'không hoàn và **không** phải doanh thu.',
                '"Thu tiền cọc trong kỳ" = cọc của mọi đơn đặt trong kỳ, kể cả đơn huỷ, trả. "Đơn huỷ mất cọc" = đơn huỷ có cọc > 0.']
    if S.get('sua_xe'):
        return ['Mỗi phiếu sửa là một đơn. Doanh thu gồm **tiền công** và **tiền phụ tùng** của phiếu không huỷ, không trả.',
                'Phiếu **bảo hành** (tổng 0 đồng, ghi `BH` / `bảo hành`) **không** phải đơn bán: không tính vào số đơn, số lượng phụ tùng bán, '
                'doanh thu; nhưng vẫn là một **lượt xe vào xưởng** (lượt xe vào xưởng = mọi phiếu không huỷ, kể cả bảo hành, trả).',
                'Xe xác định theo **biển số** (bỏ dấu `-`, `.`, khoảng trắng, không phân biệt hoa thường); câu hỏi "xe nào" trả lời biển số '
                'dạng `59H1-123.45`. Phiếu không ghi biển số là khách vãng lai.']
    if S.get('dien_thoai'):
        return ['Mỗi máy có **IMEI** riêng; câu hỏi theo IMEI trả lời theo đúng máy đó.',
                '**Thu máy cũ**: giá trị máy cũ khách đổi được trừ vào số tiền khách trả, **không** trừ doanh thu và không phải hàng bán ra. '
                '"Tiền thu máy cũ" cộng của đơn không huỷ, không trả.',
                '**Trả góp**: công ty tài chính trả shop đủ tiền; đơn trả góp tính doanh thu đủ vào ngày bán, **không** phải công nợ của khách.']
    if S.get('diem'):
        return ['Tiền khách dùng **điểm tích luỹ** để trừ **không** trừ doanh thu (như giảm giá trên cả đơn). "Tiền dùng điểm" cộng của đơn '
                'không huỷ, không trả.']
    if k == 'sac':
        return ['Doanh thu, kWh, số xe, số phiên… chỉ tính phiên `hoàn tất`, trừ câu đếm phiên lỗi. kWh làm tròn 2 chữ số.',
                'Biển số chỉ khác dấu `-`, `.`, khoảng trắng, hoa thường là cùng một xe. Trả lời biển số dạng `51H-123.45`.',
                'Khung cao điểm 17:00–21:59 theo giờ bắt đầu.']
    if k == 'thue':
        return ['Mỗi hợp đồng thuê là một đơn. **Số hợp đồng** trong kỳ tính theo **ngày nhận đồ**, bỏ hợp đồng huỷ.',
                '**Doanh thu** ghi nhận khi khách **trả đồ**, theo **ngày trả**: tiền thuê = giá thuê một ngày × số lượng × số ngày thuê thực tế '
                '(ngày trả − ngày nhận, tối thiểu 1); trả trễ so với ngày hẹn thì cộng **phụ thu trễ** = 50% giá thuê một ngày × số lượng × số '
                'ngày trễ (làm tròn đồng); cộng **phí hư hỏng** nếu có. Tiền cọc **không** phải doanh thu.',
                '**Đang cho thuê** lúc hết ngày X: hợp đồng không huỷ, nhận đồ đến hết X, chưa trả hoặc trả sau X. **Tiền cọc đang giữ** lúc hết '
                'ngày X: cọc của các hợp đồng đang cho thuê lúc đó.',
                '**Trả trễ hẹn**: ngày trả sau ngày hẹn trả. Món thuê nhiều lượt nhất: nhiều hợp đồng nhất (theo ngày nhận).']
    return None


def them_muc6(path, shops):
    """Thêm luật riêng từng shop vào §6 của rulebook (trước §7)."""
    them = ''
    for S in shops:
        ls = muc6(S)
        if ls:
            them += '### %s (%s)\n' % (S['name'], S['id']) + ''.join('- %s\n' % x for x in ls) + '\n'
    if not them:
        return
    txt = open(path, encoding='utf-8').read()
    mark = '## 7. Không trả lời được'
    assert mark in txt
    open(path, 'w', encoding='utf-8', newline='\n').write(txt.replace(mark, them + mark))
