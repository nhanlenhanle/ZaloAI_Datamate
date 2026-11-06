# Tên cột chuẩn và file DuckDB (DataMate — lớp xử lý data)

Bản để cả nhóm thống nhất. Code nguồn: `loader/mapping.py` (`DESC_RULES`), `loader/build.py`, `loader/shopmeta.py`.

## Dùng thế nào (phía query đọc phần này trước)

- **Mỗi shop là một file riêng.** Đường dẫn là `solve data/<split>/<shop>/<shop>.duckdb`. Câu hỏi có `business_id` thì mở đúng file đó; không có bảng nào dùng chung cho nhiều shop.
- **Tên chuẩn là bộ từ vựng chung, không phải một bảng chung.**
  - Mỗi shop chỉ có những cột mà data của nó thực sự có.
  - Cột theo ngành (`imei`, `active_ingredient`, `table_no`, `delivery_round`, `plate`…) chỉ có ở shop thuộc ngành đó.
  - Cột chưa map được giữ **tên gốc**.
- **Khi nhận câu hỏi, đọc theo thứ tự:**
  1. `_meta_shop`: ngày cuối có dữ liệu, ngành, mục §6 của rulebook.
  2. `_meta_tables`: các bảng và vai trò.
  3. `_meta_columns`: các cột, tên gốc, mô tả README.
  4. `_rulebook`: lấy mục luật cần dùng (§1–§10 và mục ngành).
- **Có tên chuẩn thì luật rulebook viết được thành một mẫu SQL dùng cho mọi shop.** Ví dụ doanh thu là tổng `line_amount`, bỏ `status_norm IN ('huy','tra_hang')`, bỏ dòng `line_type` không phải hàng. Mẫu này đã được kiểm trên 30 shop train (xem mục Kiểm chứng).

## Nguyên tắc

- **Chỉ đổi tên những cột chắc chắn.** Không chắc thì giữ tên gốc, vì tên sai còn tệ hơn tên lạ.
- **Tên chuẩn chung cho mọi bảng.** `qty` ở bảng bán và bảng nhập đều là "số lượng theo đơn vị của dòng". Bảng nào là bảng gì thì xem *vai trò bảng*.
- **Giá trị đã chuẩn hoá.**
  - Tiền là số VND (`"1tr440"` thành `1440000`).
  - Ngày là `TIMESTAMP`.
  - Cột nào parse từ chuỗi có thêm cột `<tên>__raw` giữ nguyên giá trị gốc.
- **Không lọc nghiệp vụ ở lớp data.** Đơn huỷ/trả, kỳ thời gian, phí phục vụ… vẫn nằm nguyên; chỉ thêm cột để phía query lọc theo rulebook.
- **Truy vết được.** Mỗi dòng có `_src_file`, `_src_sheet`, `_src_row` (số dòng trong Excel/CSV).

## Danh sách tên chuẩn

### Mã

| Tên chuẩn | Ý nghĩa |
|---|---|
| `order_id` | mã đơn / số hoá đơn |
| `line_no` | số thứ tự dòng trong đơn / phiếu nhập |
| `product_id` | mã hàng |
| `customer_id` | mã khách; trống là khách lẻ |
| `purchase_id` | mã phiếu nhập |
| `payment_id` | mã phiếu thu |
| `return_id` | mã phiếu trả hàng |
| `supplier_id` | mã nhà cung cấp |
| `staff_id` | mã nhân viên |
| `shift_id`, `promo_id` | mã ca, mã khuyến mãi |
| `batch_id` | số lô |
| `imei` | IMEI máy |

### Tên, phân loại

| Tên chuẩn | Ý nghĩa |
|---|---|
| `product_name` | tên hàng (như ghi trong file) |
| `customer_name` | tên khách (có thể kèm SĐT như trong file) |
| `supplier_name` | tên nhà cung cấp |
| `staff_name` | tên nhân viên / thợ (như ghi trong file) |
| `name` | tên chung, khi bảng không cho biết là tên của gì |
| `category` | nhóm hàng |
| `customer_group` | nhóm khách |
| `channel` | kênh bán |
| `payment_method` | hình thức thanh toán |
| `active_ingredient`, `is_prescription` | hoạt chất, thuốc kê đơn |
| `expense_item` | khoản / mục chi (sổ chi phí) |
| `active` | còn kinh doanh |
| `vehicle`, `service_desc` | xe (dòng xe và biển số ghi chung), các việc đã làm (shop dịch vụ) |

### Đơn vị, số lượng

| Tên chuẩn | Ý nghĩa |
|---|---|
| `unit` | đơn vị của dòng (bán hoặc nhập) |
| `base_unit` | đơn vị cơ bản |
| `big_unit` | đơn vị lớn |
| `conv_factor` | số đơn vị cơ bản trong 1 đơn vị lớn |
| `qty` | số lượng theo đơn vị của dòng |
| `qty_base` | số lượng quy ra đơn vị cơ bản |
| `qty_returned_base` | số lượng khách trả lại (đơn vị cơ bản) |
| `qty_returned` | số lượng trả lại (theo đơn vị của dòng) |
| `stock_qty` | tồn kho (đơn vị cơ bản) tại ngày cuối dữ liệu |
| `stock_after` | tồn sau mỗi lần nhập/bán/trả (thẻ kho) |
| `guests` | số khách của đơn (nhà hàng) |

### Tiền

| Tên chuẩn | Ý nghĩa |
|---|---|
| `unit_price` | đơn giá trên dòng (bán, hoặc giá nhập một đơn vị trong bảng nhập) |
| `line_amount` | thành tiền của dòng, đã trừ giảm giá dòng |
| `line_discount` | tiền giảm của dòng |
| `unit_cost` | giá vốn một đơn vị bán, ghi trên dòng bán |
| `price` | giá bán hiện tại (danh mục) |
| `new_price`, `old_price`, `price_from` | lịch sử giá |
| `order_subtotal` | tổng tiền hàng của đơn, trước giảm giá đơn |
| `order_discount` | giảm giá cả đơn |
| `order_total` | khách phải trả cho cả đơn / cả phiếu (phiếu dịch vụ: tiền cả phiếu) |
| `shipping_fee` | phí giao |
| `paid`, `debt` | khách đã trả, còn nợ |
| `payment_amount` | tiền một lần thu |
| `purchase_total` | tổng tiền cả phiếu nhập |
| `commission_pct` | % hoa hồng của nhân viên / thợ |
| `expense_amount` | tiền một khoản chi (sổ chi phí) |

Cột nào có ô ghi `%` thì có thêm cột `<cột>_is_pct`: ô đó là số phần trăm, không phải tiền.

### Ngày giờ

| Tên chuẩn | Ý nghĩa |
|---|---|
| `order_date` | ngày bán / ngày đặt / ngày làm phiếu dịch vụ |
| `order_time` | thời điểm đặt đơn (ngày giờ) |
| `purchase_date` | ngày nhập hàng |
| `payment_date` | thời điểm thu |
| `return_date` | ngày trả hàng |
| `expiry_date` | hạn sử dụng |
| `delivery_date` | ngày giao |
| `due_date` | hạn thanh toán |
| `created_date` | ngày tạo trên phần mềm |
| `start_date` | ngày vào làm (nhân viên) |
| `expense_date` | ngày chi (sổ chi phí) |

### Trạng thái, ghi chú

| Tên chuẩn | Ý nghĩa |
|---|---|
| `status` | trạng thái đơn gốc (trạng thái thanh toán, hoá đơn điện tử, khách thì **không** map vào đây) |
| `purchase_status` | trạng thái phiếu nhập |
| `order_note` | ghi chú của đơn. Một số shop ghi đơn huỷ / trả / đang giao ở đây |
| `note` | ghi chú khác |

### Khác

| Tên chuẩn | Ý nghĩa |
|---|---|
| `delivery_round`, `driver`, `plate` | đợt giao, tài xế, biển số xe |
| `credit_days` | số ngày được nợ |
| `table_no`, `area` | bàn, khu vực (nhà hàng) |
| `phone`, `address` | liên hệ |

## File DuckDB

### Bảng dữ liệu

- **Tên bảng** là tên gốc bỏ dấu, viết thường, nối bằng `_`. Tên gốc xem ở `_meta_tables.label`.
- **Bảng chia nhiều file/sheet cùng bộ cột được gộp lại** thành một bảng, ví dụ sổ bán theo tháng/năm. Cột `_src_file`, `_src_sheet` cho biết dòng đến từ đâu.
- **Ô trống ở các dòng sau của một đơn đã được điền** (rulebook §8), không tràn qua ranh giới file/sheet. Các cột cấp đơn (mã đơn, ngày, khách, trạng thái, ghi chú, kênh, tiền của đơn) có **cùng giá trị ở mọi dòng của đơn**. Vì vậy:
  - Tính theo đơn thì lấy **một giá trị mỗi đơn** (`ANY_VALUE` hoặc `DISTINCT ON (order_id)`).
  - **Không** cộng các cột này qua các dòng.
- **Dòng trùng cùng đơn đã bị bỏ** (rulebook §8). Bảng không ghi theo đơn thì giữ nguyên. Dòng đã bỏ ghi trong `_meta_dropped`.
- **Dòng tổng đã bị bỏ**, kể cả dòng tổng không có chữ "Tổng" (dòng cuối sheet mà mọi số bằng tổng cột).

### Cột build thêm

| Cột | Có ở | Ý nghĩa |
|---|---|---|
| `status_norm` | `sales_lines`, `orders` | **trạng thái cuối** của đơn, một giá trị cho cả đơn, giống nhau ở mọi bảng của shop: `hoan_thanh` / `huy` / `tra_hang` / `dang_giao`. Cách lấy: (1) cùng một mặt hàng ghi nhiều lần (lịch sử) thì lấy lần muộn nhất theo cột thời điểm, huỷ / trả là kết thúc nên luôn thắng; (2) các mặt hàng khác nhau, hoặc bảng đơn và bảng dòng ghi khác nhau: huỷ > trả > đang giao > hoàn thành (trả một phần là đơn trả, §1); (3) trả hàng chỉ ghi ở bảng khác (số lượng trả > 0 ở bảng lô / dòng, phiếu trả có mã đơn) thì đơn là `tra_hang`, trừ đơn huỷ. Không có cột trạng thái thì suy từ `order_note`; ghi chú trống nghĩa là hoàn thành. Trạng thái luật không nhận ra thì để trống (chỗ nối LLM: `loader/llm.py`). Trạng thái gốc vẫn giữ ở cột `status` / `order_note`; sự kiện theo ngày (giao, trả, thu tiền) ở các bảng và cột ngày tương ứng |
| `is_latest_row` | bảng bán ghi lịch sử trạng thái | chỉ có khi cùng (đơn, mặt hàng) được ghi **khác trạng thái ở khác thời điểm** (lịch sử của một dòng hàng): TRUE ở dòng muộn nhất, FALSE ở các dòng cũ. **Cộng tiền / số lượng thì lọc `is_latest_row`** (bảng không có cột này thì mọi dòng đều tính). Nhiều dòng cùng trạng thái (gọi thêm cùng món) là các lần bán thật, đều TRUE |
| `is_walk_in` | `sales_lines`, `orders` | khách lẻ. Shop có mã khách: không ghi mã. Không có mã: tên trống hoặc bắt đầu bằng "khách lẻ / vãng lai / KL" |
| `customer_key`, `product_key` | nơi có tên | khoá tên đã bỏ dấu, hoa thường, khoảng trắng, dấu câu; dùng gộp "tên chỉ khác cách viết". `product_key` tính theo `product_full` nếu có. `customer_key` giữ cả số ghi kèm tên (tên khác số là hai khách, §3) |
| `customer_name_clean`, `phone_in_name` | nơi tên khách ghi kèm SĐT | tên đã bỏ số điện thoại ("Lê Hải Hà - 0327 210 166" -> "Lê Hải Hà") để khớp tên khách trong câu hỏi; số tách ra. Đáp án ghi tên kèm SĐT như trong file cũng được chấm đúng (§9) |
| `product_full` | dòng bán / nhập của sổ ghi tắt | tên đầy đủ tra từ bảng ghi tắt; không tra được thì giữ tên đã ghi |
| `category` | dòng bán của sổ ghi tắt | nhóm hàng lấy từ cột nhóm của bảng ghi tắt (nếu dòng bán chưa có) |
| `line_type` | `sales_lines` | `hang` / `phi_phuc_vu` / `voucher` / `giam_gia` / `dung_diem` / `phi_giao` / `thue` / `phi_khac`. Khác `hang` thì không phải mặt hàng. Rulebook: phí phục vụ vẫn tính doanh thu; giảm giá đơn, phí giao, VAT thì không |
| `qty_base`, `qty_base_src`, `base_unit` | dòng bán / nhập thiếu `qty_base` | `qty` × hệ số trong `_unit_conversions`. `qty_base_src`: `quy_doi`, `co_ban`, `mac_dinh` (không có dòng quy đổi: hệ số 1, rulebook §10), `khong_ro` (thiếu SL), `khong_khop` (hàng có quy đổi nhưng đơn vị dòng lạ: để trống, **không** đoán) |
| `purchase_cancelled` | nơi có `purchase_status` | phiếu nhập bị huỷ |
| `plate`, `staff_key`, `is_warranty` | shop dịch vụ | biển số tách từ ô xe; tên gọi người làm (bỏ "A.", "anh"…); phiếu bảo hành |

### Bảng meta và bảng dùng chung

| Bảng | Nội dung |
|---|---|
| `_meta_shop` | shop, `data_end`, `has_customer_id`, mô tả, `industry` (ngành suy ra), `industry_evidence`, `rulebook_section` (tên mục §6 tương ứng), `conventions` (JSON, chỉ khi build `--llm`: quy ước README đã đọc — `money_scale` đã nhân về đồng, `status_column` cột README nói chứa trạng thái, `walk_in_labels`, `not_recorded` thông tin README viết rõ là sổ không ghi (đã bỏ mục mâu thuẫn với cột có thật), `other` quy ước khác) |
| `_meta_tables` | `table_name`, `role`, `role_desc`, tên gốc, file nguồn, số dòng, số dòng trùng đã bỏ, số ô đã điền |
| `_meta_columns` | mỗi cột: tên trong DB, tên gốc, tên chuẩn, nguồn bằng chứng (`map_source`: `readme_col`, `name_dict`, `builtin`, `value_pattern`, `value_rule`, `llm`), kiểu, mô tả README, ghi chú. Khi build có LLM, cột lạ (không map) có ghi chú `LLM: <nghĩa cột>` |
| `_meta_conventions` | mục Quy ước của README |
| `_meta_dropped` | dòng bị bỏ: dòng tổng (có/không nhãn), header lặp, dòng trùng cùng đơn |
| `_unit_conversions` | `product_id`, `product_name`, `product_key`, `unit` (đơn vị lớn), `factor` (về đơn vị cơ bản), `base_unit`, `source`. Dòng quy đổi chỉ ghi tên (README, bảng quy đổi không mã) được điền `product_id` từ danh mục khi tên ứng với đúng một mã, và ngược lại |
| `_product_aliases` | `alias`, `product_name`, `source`: cách gọi khác (chữ viết tắt trong sổ, cột "Tên gọi khác" của danh mục), để khớp tên trong câu hỏi |
| `_calendar` | `calendar.csv` của split: ngày dương, thứ, ngày/tháng/năm âm, nhuận, ngày lễ |
| `_tet_periods` | `tet_year`, `start_date`, `end_date`: dịp Tết theo rulebook §2 (23 tháng Chạp → hết mùng 10 tháng Giêng) |
| `_rulebook` | rulebook của split cắt theo mục: `level`, `heading`, `path`, `text` |

### Vai trò bảng (`_meta_tables.role`)

| Vai trò | Ý nghĩa |
|---|---|
| `sales_lines` | dòng hàng bán |
| `orders` | đơn bán, mỗi dòng một đơn (kể cả sổ phiếu dịch vụ không ghi mã) |
| `order_info` | thông tin thêm của đơn |
| `sales_batches` | dòng bán theo lô |
| `payments` | các lần thu tiền |
| `purchases` | phiếu nhập |
| `purchase_lines` | dòng hàng nhập |
| `batches` | lô hàng nhập |
| `products` | danh mục hàng |
| `drug_info` | thông tin thuốc |
| `customers` | danh sách khách |
| `suppliers` | nhà cung cấp |
| `staff` | nhân viên |
| `expenses` | sổ chi phí: `expense_amount`, `expense_date`. Lãi ròng tháng = lãi gộp − mọi khoản chi của tháng (§5) |
| `stock` | tồn kho |
| `stock_moves` | thẻ kho |
| `unit_conversions` | đơn vị quy đổi |
| `price_history` | lịch sử giá |
| `deliveries` | giao hàng theo đợt |
| `debt_terms` | hạn nợ của đơn |
| `debts` | sổ nợ |
| `other` | bảng khác |

Vai trò do luật gán theo các cột chuẩn có trong bảng. Đây là gợi ý, không phải đảm bảo tuyệt đối.

## Kiểm chứng

- `python -m pytest datamate/tests -q`: unit test, gồm hai test mốc khoá nghĩa của mọi giá trị trạng thái và mọi mô tả cột README của train.
- `python -m datamate.tests.audit_mapping <data> <out> --leave family [--llm]`: độ chính xác mapping khi gặp khuôn file chưa thấy (bỏ cả họ shop khỏi từ điển); `--llm` thêm lượt LLM.
- `python -m datamate.tests.verify_answers ../train/train "../solve data/train"`: SQL chung, chỉ dựa vào tên chuẩn, vai trò bảng và cột build thêm, chạy các câu train dạng thuần rồi so với đáp án. Gồm doanh thu, số đơn, huỷ, tỉ lệ huỷ, bán chạy (cả dịp Tết), khách top, tiền nhập, số đợt giao, công nợ (tổng, số khách nợ, tuổi nợ, 3 nhóm tuổi, top khách nợ, thu nợ trong tháng, nợ thêm / trả nợ của một khách), tồn cuối ngày (số đơn vị cơ bản, và [đơn vị lớn chẵn, cơ bản lẻ]), lô / hạn dùng (lô gần hết hạn, tiền vốn, số lô, hàng sắp hết hạn), hàng hết hàng, giá nhập bình quân, giá trị tồn theo giá vốn, lãi gộp / ròng, hàng lời nhất, thuốc kê đơn (doanh thu, tỉ lệ), giá trị trung bình một đơn, ngày / tháng doanh thu cao nhất, doanh thu và tỉ trọng theo nhóm hàng / nhóm khách, số lượng bán (một hàng, size M/L, theo đơn vị cơ bản), giá bán ngày D, hiệu ứng tăng giá; kỳ theo §2 (tuần, quý, N ngày gần nhất, từ X đến Y…). Câu không trả lời được: kiểm DB **không** dựng được nguồn. Các công thức trong script là cách đọc DB đã kiểm với đáp án, phía query dùng làm mẫu được:
  - công nợ: tổng đơn trừ khoản thu ở **sổ thu** đến hết ngày X (không dùng cột "đã trả" của đơn), bỏ đơn huỷ, đơn COD / sàn (`payment_method`, `channel`); "hơn N ngày" là tuổi nợ > N
  - tồn: bảng tồn (`stock_qty`, ảnh chụp ngày cuối dữ liệu) -> thẻ kho (`stock_after` lần cuối) -> lô (nhập theo lô − bán theo lô + `qty_returned_base`)
  - số đợt giao: số cặp (mã đơn, lần giao) có ngày giao trong kỳ
  - lô còn tồn = nhập theo lô − bán theo lô + `qty_returned_base`; tiền vốn theo giá nhập của chính lô (thành tiền dòng nhập / SL cơ bản của lô)
  - lãi gộp = doanh thu §1 − `qty` × `unit_cost` **ghi trên dòng bán**; lãi ròng trừ thêm `expense_amount` của bảng `expenses` cùng tháng; giá trị tồn dùng `unit_cost` **của danh mục**
  - kê đơn: `is_prescription` ở `drug_info` theo mã; dòng bán chỉ ghi tên thì nối mã -> tên danh mục -> `product_key`
  - giá bán ngày D: `unit_price` × `qty` / `qty_base` (một đơn vị cơ bản, trước chiết khấu dòng), cả dòng của đơn huỷ / trả
  - tỉ trọng nhóm: mẫu số là doanh thu cả shop cùng kỳ (gồm phí phục vụ, đơn vãng lai); nhóm khách theo `customer_group`, đơn vãng lai không thuộc nhóm nào

## Còn mở

- Có nên dựng sẵn view `v_sales` (dòng bán đã nối đơn, đủ ngày, `status_norm`, `qty_base`) cho mọi shop không.
- LLM map cột (Qwen3.5-9B, `run_all --llm`, cần `DATAMATE_LLM_URL` / `DATAMATE_LLM_KEY`): đã nối và đo, chưa bật mặc định. LLM chỉ nhận cột luật để trống; kết quả phải có trong bảng tên chuẩn ở trên (đọc thẳng từ file này), đúng kiểu và giá trị, tên cụ thể trong họ (số lượng / thời điểm) do ngữ cảnh bảng quyết, và không được biến bảng chưa rõ thành bảng bán / nhập hay đổi vai trò bảng về người.
- LLM xếp nhãn luật không nhận ra (`loader/labels.py`, bật cùng `run_all --llm`): trạng thái đơn / phiếu nhập (4 mã §8),
  ghi chú có nói trạng thái, hình thức thanh toán, kênh bán, nhãn khách lẻ riêng của shop. Gửi theo nhãn khác nhau (không
  theo dòng), chỉ nhận mã hợp lệ; nhãn chiếm quá nửa số dòng không được xếp huỷ / trả / đang giao. Không chắc thì để trống
  (`status_norm` NULL, `payment_norm` 'khac'): phía query nên bỏ trống câu phụ thuộc thay vì coi là hoàn thành.
- LLM đọc quy ước README (`loader/conventions.py`, bật cùng `--llm`): tiền theo nghìn / triệu đồng (chỉ nhân khi dữ liệu
  khớp: trung vị tiền bán < 1.000), trạng thái ghi ở cột khác, nhãn khách lẻ, thông tin sổ không ghi. Ghi vào
  `_meta_shop.conventions`.
- LLM sửa ô số / ngày luật không đọc được (`loader/repair.py`, bật cùng `--llm`): "hai trăm nghìn", "x2", ngày
  viết kiểu lạ... gom theo giá trị khác nhau, LLM viết lại dạng chuẩn, bộ đọc của luật đọc lại và chỉ nhận khi cùng cỡ
  với các ô khác của cột; cột chữ mà >= 60% ô là số / ngày được cứu thành cột số / ngày nếu sửa xong còn <= 5% ô lạ.
  `_columns.csv` cột `repaired` = số ô đã sửa.
- Bỏ dòng trùng cùng đơn (§8): khi so, ô trống ở dòng sau của đơn coi như giống dòng trên (kể cả cột chưa có tên
  chuẩn), trừ cột cấp dòng (hàng, số lượng, tiền dòng...); chỉ để so, dữ liệu không bị ghi đè.
- `DATAMATE_LLM_CACHE=<file.jsonl>`: lưu câu trả lời LLM theo prompt, chạy lại không hỏi lại.
- Bộ shop lạ giả lập (`python -m datamate.stress.run ../train/train <out> --shops ... [--llm]`): đổi cách ghi của shop
  train (nhãn, tên cột, README, tiền nghìn, trạng thái trong ghi chú, ô trống theo nhóm, dòng tiêu đề / dòng tổng), giữ
  nội dung, chấm đúng / sai / trống bằng SQL mẫu đã kiểm. Đo lớp data mà không cần nhìn public.
- Dữ liệu fine-tune (`python -m datamate.finetune.make_data`, notebook `finetune/finetune_colab.ipynb`): prompt giống
  pipeline, đáp án từ train; loại mọi nhãn / tên cột / câu quy ước bộ giả lập dùng; 5 họ shop giữ riêng (HOLDOUT).
