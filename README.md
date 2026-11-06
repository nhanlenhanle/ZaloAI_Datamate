# DataMate — Hệ thống AI Trả Lời Câu Hỏi Quản Lý Bán Hàng

DataMate là giải pháp tự động xử lý và trả lời các truy vấn kinh doanh, doanh thu, hàng tồn kho, công nợ trên sổ sách bán hàng hỗn hợp (Excel, CSV, SQLite) của các cửa hàng bán lẻ nhỏ tại Việt Nam.

Hệ thống được thiết kế theo kiến trúc **Hybrid Reasoning** kết hợp Rule-based sạch dữ liệu, Kế hoạch JSON và Sinh truy vấn SQL thông qua mô hình ngôn ngữ lớn (LLM **Qwen/Qwen3.5-9B**).

---

## 📌 Điểm Nổi Bật Về Kỹ Thuật

1. **Chuẩn hóa dữ liệu đa định dạng (`datamate/loader`)**:
   - Tự động nhận diện dòng tiêu đề, lọc bỏ dòng tổng/ghi chú, xử lý encoding, gộp các sheet cùng sổ sách.
   - Cơ chế Mapping cột chuẩn kết hợp đối chiếu mô tả từ `README.md`, từ điển quy ước, regex nghiệp vụ và LLM.
   - Đồng bộ và chuẩn hóa trạng thái đơn hàng (`hoan_thanh`, `huy`, `tra_hang`, `dang_giao`) theo Rulebook.
   - Quy đổi tự động đơn vị đo lường (lốc/thùng $\rightarrow$ đơn vị cơ bản) và xây dựng cơ sở dữ liệu DuckDB tối ưu cho từng shop.

2. **Hai luồng suy luận độc lập (`datamate/query`)**:
   - **Đường JSON Plan (`compose.py` + `plan.py`)**: LLM lập kế hoạch dạng cấu trúc JSON chuyên biệt, code Python thực thi truy vấn trực tiếp trên các bảng view chuẩn `v_*`. Thế mạnh: các mẫu câu hỏi quen thuộc, tính toán tỷ lệ, tăng trưởng kỳ.
   - **Đường SQL Tier (`sql_tier.py`)**: LLM sinh câu truy vấn DuckDB SQL một dòng. Thế mạnh: các câu hỏi logic phức tạp, luật ngành nghề mới lạ.

3. **Cơ chế kiểm soát & Tái lập (Reproducibility)**:
   - Cơ chế biểu quyết đa số (Majority Voting qua 3 mức nhiệt độ: 0.0, 0.5, 0.9).
   - Tự động kiểm tra tính hợp lệ về logic (kỳ thời gian, đối tượng, ngưỡng tiền, phát hiện trường hợp thiếu dữ liệu `unanswerable`).
   - Cố định seed, chạy DuckDB đơn luồng nhằm triệt tiêu hoàn toàn sai số tráo đổi dòng ngẫu nhiên giữa các lần chạy.

---

## 📂 Cấu Trúc Mã Nguồn

```text
code solve data/
├── datamate/
│   ├── loader/               # Tầng xử lý, làm sạch file thô & build DuckDB
│   │   ├── read_files.py     # Đọc csv, xlsx (calamine), sqlite
│   │   ├── header.py         # Phát hiện tiêu đề, gộp sheet, bỏ dòng tổng
│   │   ├── parsers.py        # Parse tiền, ngày, trạng thái, phân cách nghìn
│   │   ├── mapping.py        # Map tên cột gốc sang tên chuẩn schema
│   │   ├── build.py          # Áp dụng rulebook, forward-fill, ghi file DuckDB
│   │   └── ...
│   ├── query/                # Tầng suy luận & trả lời câu hỏi
│   │   ├── facts.py          # Định nghĩa các bảng chuẩn (dong_ban, don, ton...)
│   │   ├── compose.py        # LLM lập kế hoạch JSON & Prompt Builder
│   │   ├── plan.py           # Engine thực thi kế hoạch JSON
│   │   ├── sql_tier.py       # Luồng LLM viết DuckDB SQL
│   │   ├── hybrid.py         # Cơ chế dung hợp (ca_hai) giữa JSON và SQL
│   │   └── answer.py         # Điều phối đa luồng xuất ra file nộp
│   ├── schema.md             # Định nghĩa danh mục cột chuẩn
│   └── run_all.py            # Script chạy toàn bộ pipeline dựng DB
├── docker/
│   ├── Dockerfile            # Image chạy offline kèm vLLM
│   ├── run.sh                # Entrypoint tự động khởi chạy vLLM & pipeline
│   ├── chuan_bi.sh           # Script chuẩn bị assets & weight model
│   └── assets/               # Kho câu mẫu JSON & SQL để few-shot prompt
├── .dockerignore
├── .gitignore
└── README.md
```

---

## 🚀 Hướng Dẫn Triển Khai Docker

### 1. Yêu cầu hệ thống
- Linux OS (Ubuntu 20.04/22.04 khuyến nghị)
- GPU NVIDIA (Hỗ trợ tốt nhất kiến trúc Ada Lovelace / Blackwell như RTX 4090, RTX 5090; VRAM $\ge$ 24GB)
- Đã cài đặt Docker và `nvidia-container-toolkit`.

### 2. Chuẩn bị Trọng số Model
Hệ thống sử dụng model `Qwen/Qwen3.5-9B` (hoặc bản lượng hóa phù hợp) không kết nối Internet trong lúc chấm thi.

Tải trọng số model từ Hugging Face về thư mục `docker/models/qwen`:
```bash
git lfs install
git clone https://huggingface.co/Qwen/Qwen3.5-9B docker/models/qwen
```
*(Đảm bảo trong thư mục `docker/models/qwen/` có đầy đủ file `config.json`, tokenizer và các file weights safetensors).*

### 3. Build Docker Image
Chạy lệnh build tại thư mục gốc `code solve data`:
```bash
docker build -f docker/Dockerfile -t datamate .
```

### 4. Chạy Container Chấm Thi / Suy Luận
Container nhận 2 thư mục mount:
- `/data`: Thư mục chứa đề thi (gồm `questions.jsonl`, `rulebook.md`, `calendar.csv` và thư mục `data/` chứa các shop).
- `/result`: Thư mục lưu kết quả `submission.jsonl`.

```bash
docker run --gpus all \
  -v /path/to/test_data:/data \
  -v /path/to/output_dir:/result \
  datamate
```

Sau khi hoàn tất, kết quả dự đoán sẽ được ghi tại: `/path/to/output_dir/submission.jsonl`.

---

## 🛠️ Chạy Thử Nghiệm Ngoài Docker (Local Development)

Nếu bạn đã có sẵn vLLM hoặc OpenAI-compatible API endpoint đang chạy model Qwen:

```bash
# 1. Thiết lập biến môi trường kết nối LLM
export DATAMATE_LLM_URL="http://localhost:8000"
export DATAMATE_LLM_MODEL="qwen"

# 2. Xây dựng CSDL DuckDB từ dữ liệu shop
python -m datamate.run_all path/to/split/data --out solve_data/db --llm --skip-tables

# 3. Trả lời tập câu hỏi
python -m datamate.query.answer path/to/split solve_data/db/split \
  --out submission.jsonl \
  --policy ca_hai \
  --examples docker/assets/examples_train.jsonl \
  --sql-examples docker/assets/examples_sql_train.jsonl \
  --luat-examples docker/assets/examples_luat.jsonl \
  --workers 4
```
