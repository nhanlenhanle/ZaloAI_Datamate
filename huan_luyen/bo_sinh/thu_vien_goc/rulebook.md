# DataMate Hard — Rulebook (bộ private tự sinh)

Mọi đáp án chuẩn tính theo các luật dưới đây. Câu hỏi nói khác thì làm theo câu hỏi; không nói thì áp luật mặc định. Khi luật ngành (§6) khác luật chung, theo luật ngành.

**Hôm nay** của mỗi câu là trường `as_of_date` trong `questions.jsonl`. Mọi cách nói tương đối tính theo ngày này. Bản ghi có ngày sau hôm nay coi như chưa xảy ra, trừ trạng thái huỷ / trả hàng của đơn: lấy theo trạng thái ghi trên đơn.

## 1. Đơn hàng và doanh thu
| Luật | Mặc định |
|---|---|
| Trạng thái đơn | mỗi đơn có đúng một trong bốn trạng thái: **hoàn thành**, **huỷ**, **trả hàng**, **đang giao**. Sổ không có cột trạng thái thì trạng thái ghi ở ghi chú; ghi chú không nhắc trạng thái là hoàn thành |
| Đơn tính doanh thu | đơn **không huỷ** và **không trả hàng**; đơn có trả hàng, kể cả trả một phần, bỏ **cả đơn**. Đơn đang giao vẫn tính |
| Doanh thu một đơn | tổng **thành tiền các dòng hàng** (đã trừ giảm giá dòng). **Không** trừ giảm giá trên cả đơn, **không** gồm phí giao. "Bán được bao nhiêu tiền", "tiền hàng", "tiền bán" cùng nghĩa doanh thu |
| Không phải doanh thu | tiền cọc, tiền khách nạp vào tài khoản, tiền tặng khuyến mãi, phí giao, tiền khách trả nợ |
| Đơn thuộc kỳ nào | theo **ngày đặt** (ngày nhận đồ, giờ bắt đầu phiên với §6), không theo ngày giao hay ngày thu tiền |
| Số đơn | chỉ đơn không huỷ, không trả; cả khi đếm đơn có một nhóm hàng, đơn của một khách. **Khách đã mua** trong kỳ là khách có ít nhất một đơn như vậy |
| Tỉ lệ đơn huỷ | phần trăm đơn huỷ trong **mọi đơn đặt trong kỳ** (mọi trạng thái) |
| Doanh thu theo kênh, hình thức thanh toán, nhóm khách | theo giá trị **ghi trên đơn**. Đơn khách lẻ không thuộc nhóm khách nào. Tỉ trọng chia cho doanh thu **cả cửa hàng** cùng kỳ |
| Giá trị trung bình một đơn | doanh thu kỳ / số đơn kỳ |
| Phần trăm thay đổi | so với **kỳ so**: (kỳ hỏi − kỳ so) / kỳ so × 100; giảm ra số âm. "So ca chiều với ca sáng", "cao điểm so với thấp điểm": mốc là vế sau |

## 2. Thời gian
| Cách nói | Nghĩa |
|---|---|
| Hôm nay, hôm qua, ngày X | phát sinh **trong** ngày đó |
| Đến hết ngày X, tính đến hôm nay | **tình trạng lúc hết ngày đó**, cộng mọi phát sinh từ đầu dữ liệu |
| Từ X đến Y | gồm cả X và Y |
| N ngày gần nhất | N ngày liền nhau, ngày cuối là hôm nay |
| Quá N, hơn N, trên N | **không** gồm N; **từ N trở lên** gồm N |
| Tuần | bắt đầu thứ Hai. **Tuần này**: thứ Hai đến hết hôm nay. **Tuần trước**: cả tuần liền trước |
| Tháng M/Y, quý Q/Y | cả tháng / cả quý dương lịch |
| Tháng này | ngày 1 đến hết hôm nay; so với tháng trước thì lấy ngày 1 đến ngày trùng số hôm nay của tháng trước (tháng trước ngắn hơn thì đến hết tháng trước) |
| Từ đầu năm | 01/01 năm nay đến hết hôm nay |
| Tháng M không ghi năm | năm nay nếu tháng đó không sau hôm nay, ngược lại năm trước |
| Tết năm Y, dịp Tết | từ ngày dương của **23 tháng Chạp** (năm âm Y − 1) đến hết **mùng 10 tháng Giêng** (năm âm Y). **So với N ngày trước Tết**: N ngày liền ngay trước 23 tháng Chạp |
| Mùng 1, rằm tháng M âm lịch năm Y | đúng **một ngày** dương ứng với ngày 1 / ngày 15 tháng M (không nhuận) năm âm Y, tra `calendar.csv` |
| Dịp lễ dương lịch (14/2, 8/3, 20/10, 20/11) năm Y | từ **2 ngày trước** ngày lễ đến **hết** ngày lễ (3 ngày) |
| Ca | ca sáng 06:00–13:59, ca chiều 14:00–21:59, ca đêm 22:00–05:59 sáng hôm sau; tính theo giờ tạo đơn / giờ bắt đầu phiên |
| Giờ cao điểm | khung một giờ tròn (h:00 đến trước h+1:00) có **nhiều đơn / phiên bắt đầu nhất**; đáp án là giờ bắt đầu khung, type `number` |
| Ngày đắt khách nhất | ngày có nhiều đơn nhất. Ngày bán nhiều tiền nhất: ngày có doanh thu cao nhất |

## 3. Xếp hạng và xác định đối tượng
| Luật | Mặc định |
|---|---|
| Mặt hàng | hàng, món, sản phẩm, sách cùng nghĩa. **Topping** là mặt hàng riêng |
| Bán chạy, bán nhiều nhất, hot nhất | theo **số lượng quy về đơn vị cơ bản**; bỏ đơn huỷ, trả |
| Bán được bao nhiêu <đơn vị> | cộng số lượng quy về đơn vị cơ bản của các mặt hàng **có đơn vị cơ bản là <đơn vị>** |
| Được ưa chuộng nhất | có mặt trong nhiều đơn nhất |
| Hàng lời nhất | theo tổng lãi gộp (§5) |
| Nhân viên bán giỏi nhất | theo doanh thu |
| Khách trung thành nhất | nhiều **ngày** có mua nhất. **Khách sộp nhất**: giá trị trung bình một đơn cao nhất, chỉ xét khách có từ 3 đơn. **Khách hay đổi ý nhất**: nhiều đơn huỷ nhất |
| Xác định khách | shop có mã khách: mỗi mã một khách, đơn không mã là khách lẻ. Shop không có mã khách: theo tên ghi trên đơn; hai tên **chỉ khác hoa thường, khoảng trắng, hoặc có / không kèm số điện thoại** (dãy từ 9 chữ số) là cùng một khách; hai tên **khác chữ, khác dấu hoặc khác số khác** (ví dụ thêm "2") là hai khách. Khách lẻ (Khách lẻ, kl, lẻ…) không phải khách |
| Bằng nhau | xếp theo **mã** tăng dần; không có mã thì theo tên |
| Top k, liệt kê | danh sách đúng thứ tự giảm dần theo tiêu chí |

## 4. Công nợ
| Luật | Mặc định |
|---|---|
| Đơn tính vào nợ | đơn **ghi nợ**, không huỷ; đơn trả hàng vẫn tính nếu còn nợ. Đơn COD không phải nợ |
| Nợ một đơn tại ngày X | **tổng phải trả** của đơn (sau giảm giá đơn, gồm phí giao) trừ các khoản đã trả đến hết ngày X; cộng các đơn còn nợ > 0 |
| Nợ theo khách | xác định khách như §3; đơn khách lẻ vẫn tính vào tổng nợ nhưng không có dòng trong bảng theo khách |
| Tuổi nợ | số ngày từ **ngày đặt** tới ngày X (đặt hôm nay: 0 ngày) |
| Nợ thêm / trả nợ trong kỳ | **Nợ thêm**: phần tổng phải trả chưa trả **ngay trong ngày mua** của đơn ghi nợ đặt trong kỳ. **Trả nợ**: các khoản trả có ngày trong kỳ và **sau ngày mua**, của mọi đơn ghi nợ không huỷ |
| Shop thu tiền cọc (§6) | mọi đơn không huỷ đều là đơn tính nợ: còn nợ = tổng phải trả − cọc − các lần trả sau, đến hết ngày X. Trả nợ trong kỳ = các lần trả sau ngày đặt có ngày trong kỳ |

## 5. Kho, nhập hàng, giá vốn
| Luật | Mặc định |
|---|---|
| Tiền nhập trong kỳ | tổng thành tiền các dòng của phiếu nhập có ngày trong kỳ, bỏ phiếu huỷ; phiếu nhập đầu kỳ cũng tính |
| Nhà cung cấp nhập nhiều nhất | tiền nhập cao nhất. **Nhà cung cấp chính**: nhiều **phiếu** nhập nhất |
| Tồn kho lúc hết ngày X | nhập (phiếu không huỷ) − xuất theo đơn không huỷ (kể cả dòng đổi bảo hành) + hàng khách trả (theo ngày trả), tất cả quy về đơn vị cơ bản, từ đầu dữ liệu đến hết ngày X |
| Giá trị hàng tồn | tồn lúc hết ngày X × **giá vốn đơn vị cơ bản ghi trong danh mục**; chỉ cộng hàng còn tồn > 0 |
| Hiệu ứng tăng giá | so số lượng (đơn vị cơ bản) **N ngày kể từ ngày tăng** (tính cả ngày đó) với **N ngày ngay trước**; bỏ đơn huỷ, trả. "Từ khi X tăng lên giá P": lần đầu giá mới bằng P và cao hơn giá liền trước |
| Lãi gộp | doanh thu trừ Σ (số lượng × **giá vốn ghi trên dòng bán**) |
| Hàng hết hạn trong N ngày tới | tại hôm nay D: các lô còn tồn có hạn dùng từ D đến hết D + N. **Tiền vốn** = phần còn tồn × giá nhập của chính lô quy về đơn vị cơ bản. **Lô gần hết hạn nhất**: lô còn tồn, chưa quá hạn, hạn sớm nhất |

## 6. Theo ngành
### Tiệm hoa (biz_201)
- Bó, xấp là đơn vị lớn theo danh mục. Câu hỏi số **bó** bán theo đơn vị bó chỉ đếm các dòng ghi đơn vị bó.

### Cá cảnh (biz_202)
- Dòng **đổi cá chết** (đơn giá 0) là đổi bảo hành: không phải lượt bán, không tính vào số lượng bán, có xuất kho. "Đổi bao nhiêu con cá chết" = số dòng đổi trong các đơn không huỷ, không trả của kỳ.

### In 3D (biz_205)
- Mọi đơn thu cọc lúc đặt. Cọc của đơn huỷ không hoàn, **không** phải doanh thu. "Thu tiền cọc trong kỳ" = cọc của mọi đơn đặt trong kỳ, kể cả đơn huỷ, trả.
- In theo khối lượng: số lượng là gram (ml với resin).

### Sách ký gửi (biz_207)
- Doanh thu tính cả sách ký gửi. **Tiền trả chủ ký gửi** trong kỳ = doanh thu sách của chủ đó × (100 − phần trăm hoa hồng) / 100, làm tròn đồng theo **từng chủ, từng kỳ**. **Hoa hồng tiệm** = doanh thu sách của từng chủ × phần trăm, làm tròn theo từng chủ rồi cộng.
- Phiếu `nhận ký gửi` không mất tiền (tiền nhập 0) nhưng vẫn vào kho.

### Quán chè (biz_208)
- Size M, L: món có tên kết thúc `(M)`, `(L)`.
- Topping ghi chung ô với món là **mặt hàng topping** riêng (cùng mặt hàng với topping ghi dòng riêng): số phần, tiền của topping tính cho topping, không tính cho món.

### Thú y (biz_209)
- Thuốc kê đơn theo cột Kê đơn của danh mục. Doanh thu theo hoạt chất: chỉ sản phẩm có hoạt chất ghi **đúng như vậy**; thuốc phối hợp là một loại riêng.

### Phòng máy (biz_203)
- **Doanh thu** = tiền giờ các phiên `xong` + tiền đồ ăn uống của đơn không huỷ. Tiền nạp, tiền tặng không phải doanh thu. Phiên `hoàn tiền` không có doanh thu.
- Mọi câu về phiên chơi (giờ chơi, máy, hội viên ra chơi, phiên qua nửa đêm…) chỉ tính phiên `xong`, trừ câu đếm phiên hoàn tiền. **Giờ chơi** = số phút / 60, làm tròn 2 chữ số.
- **Tiền giờ ca đêm**: phiên `xong` bắt đầu từ 22:00 đến 05:59.
- **Số dư tài khoản** đến hết ngày X = nạp + tặng − tiền giờ phiên `xong` trả bằng tài khoản, tính theo ngày nạp / ngày bắt đầu phiên.

### Giặt sấy (biz_204)
- Mỗi phiếu là một đơn, thuộc kỳ theo **ngày nhận**. Phiếu huỷ bỏ khỏi mọi câu hỏi.
- Số kg là kg thực ghi ở Số lượng (không phải 3 kg tối thiểu).
- **Phiếu chưa trả** lúc hết ngày X: phiếu không huỷ, nhận đến hết X, chưa có ngày trả hoặc ngày trả sau X. **Trả trễ hẹn**: ngày trả sau ngày hẹn.
- Khách xác định theo **số điện thoại** (bỏ dấu chấm, khoảng trắng; `+84` thay cho số 0 đầu). Câu hỏi "khách nào" trả lời số điện thoại dạng 10 chữ số liền.
- Phí giao ghi ở ghi chú: không phải doanh thu; câu hỏi phí giao cộng phí của phiếu không huỷ.

### Trạm sạc (biz_210)
- Doanh thu, kWh, số xe, số phiên… chỉ tính phiên `hoàn tất`, trừ câu đếm phiên lỗi. kWh làm tròn 2 chữ số.
- Biển số chỉ khác dấu `-`, `.`, khoảng trắng, hoa thường là cùng một xe. Trả lời biển số dạng `51H-123.45`.
- Khung cao điểm 17:00–21:59 theo giờ bắt đầu.

## 7. Không trả lời được
Câu **không trả lời được** khi dữ liệu phát hành không đủ: thông tin file không ghi (giới tính, địa chỉ, lý do, đánh giá, cảm nhận…), shop không ghi loại thông tin câu hỏi cần (kênh, nhân viên, công nợ, tồn kho, ca), hoặc kỳ hỏi nằm **hoàn toàn** ngoài khoảng ngày có dữ liệu. Không có dữ liệu khác với bằng 0. Kỳ có một phần trong dữ liệu thì tính trên phần có dữ liệu. Nộp `{"type": "unanswerable"}`.

## 8. Cách ghi trong file
| Cách ghi | Hiểu là |
|---|---|
| Ô trống ở các dòng sau của cùng một đơn | giống ô đó ở dòng đầu đơn |
| Hai dòng của **cùng một đơn** giống nhau ở mọi ô | lỗi xuất file, tính một lần |
| Dòng tổng cộng, dòng tiêu đề lặp lại, dòng tiêu đề file | không phải dữ liệu |
| Mã dính khoảng trắng ở đầu, cuối | cùng mã đó |
| Ngày dạng `d/m/y` | luôn là ngày trước, tháng sau. Ngày không ghi năm: năm của file/sheet chứa dòng |
| Tiền `12.000`, `12 000`, `12,000`, `12k`, `1,2tr`, `12.000đ` | 12000, 12000, 12000, 12000, 1200000, 12000 |
| Tên gọi khác, ghi tắt, viết hoa / thường | cùng một thứ; file có mã thì theo mã |

## 9. Đáp án và chấm điểm
Mỗi dòng `{"id", "type", "answer"}`. **Câu hỏi hỏi nhiều số** (lần lượt từng tháng, từng nhóm tuổi nợ, nợ thêm và trả nợ…) trả lời bằng `list` theo đúng thứ tự câu hỏi nêu; chỉ dùng `table` khi câu hỏi bảo lập bảng hoặc hỏi nhiều đối tượng kèm số đo của từng đối tượng. Đúng **+1**, sai **−1**, bỏ trống (`{"type": "abstain"}` hoặc không có dòng) **0**.

| type | Format |
|---|---|
| number | JSON number. Tiền là số nguyên VND, làm tròn về đồng (nửa đồng lên). Số khác làm tròn 2 chữ số thập phân |
| percent | JSON number là số phần trăm, làm tròn 2 chữ số |
| date | `"YYYY-MM-DD"`; câu hỏi theo tháng `"YYYY-MM"` |
| boolean | `true` / `false` |
| string | tên như trong dữ liệu (danh mục); nhận cả mã nếu có |
| list | mảng JSON đúng thứ tự |
| table | `{"columns": [...], "rows": [[...]]}`, cột đầu là tên đối tượng; thứ tự dòng không chấm |
| unanswerable | `{"type": "unanswerable"}` |

Số, phần trăm khớp tuyệt đối (bỏ qua sai số dấu phẩy động). Chuỗi không phân biệt hoa thường, khoảng trắng. Trường `alias` trong `answers.jsonl` liệt kê cách ghi khác được chấp nhận (mã).

## 10. Đơn vị
Mỗi mặt hàng có **đơn vị cơ bản** và có thể có đơn vị lớn. Hệ số đọc ở danh mục / bảng quy đổi / README của shop. Khi quy đổi ghi theo bậc (`1 thùng = 4 lốc; 1 lốc = 6 lon`), mỗi bậc là số đơn vị **ngay dưới**.
