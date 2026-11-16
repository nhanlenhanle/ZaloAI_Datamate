# DataMate — Zalo AI Challenge 2026 (Team: fall to fly)

DataMate là hệ thống tự động đọc hiểu sổ sách bán hàng hỗn hợp (CSV, XLSX, SQLite), chuẩn hóa dữ liệu và trả lời câu hỏi nghiệp vụ bán lẻ bằng kiến trúc **Hybrid Reasoning** (kết hợp JSON Plan và DuckDB SQL Tier), hoạt động **100% offline** trên nền `vLLM v0.17.0`.

---

## 1. Approach (Phương pháp tiếp cận)

Luồng xử lý tự động từ đầu đến cuối (`/code/predict.sh` $\rightarrow$ `/app/run.sh`) gồm 3 giai đoạn tuần tự:

1. **Đọc & Chuẩn hóa dữ liệu cửa hàng (`datamate/loader`, `python3 -m datamate.run_all`)**:
   - Đọc mọi định dạng file trong `/data/data/<business_id>/` (`.csv`, `.xlsx` qua `python-calamine`, `.sqlite`).
   - Tự động phát hiện dòng tiêu đề cột, loại bỏ dòng tổng cộng/ghi chú, gộp các sheet cùng cấu trúc sổ.
   - Chuẩn hóa tiền tệ (`1tr5`, `250k`), ngày tháng, trạng thái đơn hàng (`hoan_thanh`, `huy`, `tra_hang`, `dang_giao`), đơn vị quy đổi (thùng/lốc $\rightarrow$ đơn vị cơ bản) và ánh xạ tên cột về schema chuẩn thông qua `README.md`, từ điển quy ước và mô hình **Qwen3.5-9B** (`temperature=0`).
   - Xây dựng cơ sở dữ liệu DuckDB độc lập cho từng cửa hàng kèm các bảng view chuẩn (`v_dong_ban`, `v_don`, `v_ton`, `v_no`, ...).

2. **Chuẩn hóa & Làm sạch câu hỏi (`datamate/query/normalize_all.py`)**:
   - Tắt server 9B, giải phóng hoàn toàn VRAM và khởi chạy mô hình **Qwen3.5-4B** (`/models/qwen_norm4b`, `temperature=0`, `seed=2026`).
   - Nhận diện và gắn thẻ thực thể `<ENT_k>` khớp với danh mục thực tế trong DuckDB của cửa hàng, đính kèm các dòng quy tắc liên quan trong `rulebook.md`, sửa lỗi viết tắt/không dấu/phương ngữ tiếng Việt.
   - Kiểm tra an toàn qua bộ Guardrail (bảo toàn 100% con số, năm tháng và thẻ `<ENT_k>`; nếu vi phạm tự động quay về câu hỏi gốc).

3. **Suy luận Hybrid, Thực thi Code & Chọn đáp án (`datamate/query/answer.py`)**:
   - Tắt server 4B, khởi chạy lại **Qwen3.5-9B** (`/models/qwen`) và giải từng câu hỏi qua 2 đường độc lập:
     - **Đường JSON Plan (`compose.py` + `plan.py`)**: LLM sinh kế hoạch truy vấn cấu trúc JSON, thực thi bằng `datamate/query/plan.py::execute` trên các view chuẩn.
     - **Đường DuckDB SQL (`sql_tier.py`)**: LLM sinh câu truy vấn DuckDB SQL, thực thi trực tiếp trên DuckDB (đơn luồng `threads=1`) và tự động sửa lỗi nếu truy vấn gặp ngoại lệ.
   - **Chọn đáp án & Tái lập (`hybrid.py`)**: Biểu quyết đa số qua chuỗi nhiệt độ cố định `(0.0, 0.5, 0.9)` với `seed=2026`, `PYTHONHASHSEED=0`, kiểm tra điều kiện `unanswerable` / `abstain`, ghi tức thời từng câu ra `/result/submission.jsonl` và `/result/logs/logs.jsonl`.

---

## 2. Models (Khai báo mô hình sử dụng)

Toàn bộ mô hình sử dụng trong inference đều là mã nguồn mở giấy phép **Apache-2.0**, phát hành ngày `2026-02-27` (trước mốc `2026-10-26`), đóng gói sẵn trong image và chạy tuần tự:

| Tên mô hình | Nguồn công khai (HuggingFace) | Fixed Revision (Git Commit Hash) | Ngày phát hành gốc | Giấy phép | Số tham số (gồm cả Vision & MTP) | Vai trò trong hệ thống |
| :--- | :--- | :--- | :---: | :---: | :---: | :--- |
| **Qwen/Qwen3.5-9B** *(đã gộp LoRA `adapter_mix`)* | `https://huggingface.co/Qwen/Qwen3.5-9B` | `c202236235762e1c871ad0ccb60c8ee5ba337b9a` | `2026-02-27` | `Apache-2.0` | **9.653B** (`9,653,000,000`) | Ánh xạ cột dựng DuckDB & Suy luận JSON Plan + SQL (`/models/qwen`) |
| **Qwen/Qwen3.5-4B** *(đã gộp LoRA `adapter_v2`)* | `https://huggingface.co/Qwen/Qwen3.5-4B` | `851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a` | `2026-02-27` | `Apache-2.0` | **4.660B** (`4,660,000,000`) | Chuẩn hóa và làm sạch câu hỏi tiếng Việt (`/models/qwen_norm4b`) |
| **Tổng cộng** | | | | | **14.313B ($\le$ 15B)** | Chạy tuần tự, không chạy đồng thời |

---

## 3. Data (Dữ liệu huấn luyện & Kiểm chứng)

- **Cam kết tuân thủ quy chế (Rule 6)**: Hệ thống **chỉ sử dụng tập dữ liệu `train` do BTC cung cấp (`biz_101`..`biz_130`) và dữ liệu cửa hàng tự sinh (`bo_sinh/sinh.py`, `biz_301`..`biz_536`)**. Tuyệt đối **không** sử dụng bất kỳ dữ liệu hay nhãn nào từ tập `public_test` hoặc `private_test` trong quá trình huấn luyện.
- **Chi tiết các tập dữ liệu huấn luyện & validation** (đóng gói đầy đủ tại `/code/training_code/` tức `/app/huan_luyen/`):
  1. **Fine-tune Qwen3.5-9B (`training_code/qwen9b/`)**:
     - Lượt 1 (`thu_train.jsonl`): **800 mẫu train** kế hoạch JSON; tập validation (`thu_val.jsonl`): **40 mẫu validation**.
     - Lượt 2 (`mix_train.jsonl`): **2.200 mẫu train** kết hợp (700 mẫu JSON Plan + 1.100 mẫu SQL từ `sql_gen_train.jsonl` [3.040 mẫu] & `sql_pv2.jsonl` [1.303 mẫu] + 400 mẫu rulebook đổi luật từ `rbd_sql_A.jsonl` [231 mẫu] & `rbd_sql_C.jsonl` [159 mẫu]); tập validation (`thu_val.jsonl`): **40 mẫu validation**.
  2. **Fine-tune Qwen3.5-4B (`training_code/qwen4b_norm/`)**:
     - Tập huấn luyện chuẩn hóa câu hỏi (`full_gold_norm_v2_chatml_cleaned.jsonl`): **4.669 mẫu train**; tập validation (`val_norm_v2.jsonl`): **100 mẫu validation** (tạo từ câu hỏi tập `train` của BTC + bộ cửa hàng tự sinh `biz_501`..`biz_536` + mẫu biến đổi phương ngữ/viết tắt tổng hợp).

---

## 4. Folder Layout in the Image (Cấu trúc thư mục)

```text
/code/
├── predict.sh                        # Entry point chuẩn của BTC (gọi /app/run.sh)
├── README.md                         # Tài liệu mô tả giải pháp, mô hình và dữ liệu
├── requirements.txt                  # Danh sách thư viện Python ghim phiên bản
├── Dockerfile                        # Dockerfile đóng gói toàn bộ hệ thống
├── src/ -> /app/datamate             # Mã nguồn inference (loader, query, plan, sql_tier, hybrid)
├── models/ -> /models                # Trọng số inference offline (qwen 9B & qwen_norm4b 4B)
└── training_code/ -> /app/huan_luyen # Toàn bộ mã nguồn, dữ liệu, adapter huấn luyện & manifest
    ├── README.md                     # Hướng dẫn chi tiết tái lập sinh dữ liệu, phần cứng & thời gian
    ├── requirements.txt              # Thư viện huấn luyện đã cài sẵn trong image (peft, bitsandbytes, accelerate...)
    ├── train.sh                      # Script chạy toàn bộ luồng huấn luyện & gộp LoRA
    ├── configs/                      # Cấu hình huấn luyện và sinh dữ liệu (.json)
    ├── logs/                         # Nhật ký huấn luyện thực tế (.log & trainer_state.json)
    ├── bo_sinh/                      # Mã nguồn bộ sinh cửa hàng & câu hỏi tự động (sinh.py)
    ├── qwen9b/                       # Code, dữ liệu (.jsonl) và adapter_mix của Qwen3.5-9B
    ├── qwen4b_norm/                  # Code, dữ liệu (.jsonl) và adapter_v2 của Qwen3.5-4B
    └── data_manifest.json            # Danh mục đường dẫn local, kích thước, SHA-256 và revision model gốc
```

---

## 5. Run Instructions (Hướng dẫn chạy chấm bài)

Làm theo *Docker Submission Guide – Zalo AI Challenge 2026 DataMate* (mục 10–11).

### 5.1. Yêu cầu máy chạy

| Thành phần | Yêu cầu |
| :--- | :--- |
| GPU | 2 × NVIDIA RTX 5090 (32 GB VRAM mỗi card), driver R570 trở lên |
| Phần mềm | Docker (đã bật BuildKit) + NVIDIA Container Toolkit |
| Kiến trúc image | `linux/amd64`, base `vllm/vllm-openai:v0.17.0` (có hỗ trợ Blackwell / compute capability 12.0) |
| Mạng | Không cần. Image chạy **100% offline** (`HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`) |
| Bộ nhớ chia sẻ | `--shm-size=16g` (mặc định 64 MiB không đủ cho NCCL) |
| Ổ đĩa | Đủ chỗ cho file `.tar.gz` và image sau khi `docker load` |

### 5.2. Tải và nạp image

**Docker image** (đã đóng gói sẵn code, trọng số mô hình, mã và dữ liệu huấn luyện): [Tải từ Google Drive](https://drive.google.com/file/d/1TbEGKDA55_Z6gLgIwTfZStheVROH7ItT/view?usp=sharing)

File tải về là `zaic2026_datamate_fall_to_fly.tar.gz`, được tạo bằng `docker save zaic2026_datamate_fall_to_fly:final | gzip`.

```bash
# (Tuỳ chọn) Kiểm tra file nguyên vẹn nếu có kèm file .md5; kết quả phải là OK
md5sum -c zaic2026_datamate_fall_to_fly.tar.gz.md5

# Nạp image (docker load đọc trực tiếp file .tar.gz)
docker load -i zaic2026_datamate_fall_to_fly.tar.gz

# Kiểm tra image: kết quả phải là linux/amd64
docker image inspect -f '{{.Os}}/{{.Architecture}} {{.Size}}' zaic2026_datamate_fall_to_fly:final

# Xem cấu trúc thư mục /code trong image
docker run --rm --network none --entrypoint ""   zaic2026_datamate_fall_to_fly:final find /code -maxdepth 2
```

### 5.3. Chạy chấm bài

Dùng đúng lệnh chấm chuẩn của BTC (Mục 10 của Docker Submission Guide): 2 GPU, không mạng, `/data` chỉ đọc, 16 GiB shared memory.

```bash
docker run --rm --gpus '"device=0,1"' --network none --shm-size=16g   --entrypoint bash   -v /path/to/test_split:/data:ro   -v /path/to/output:/result   zaic2026_datamate_fall_to_fly:final /code/predict.sh
```

- `/path/to/test_split` là thư mục test theo đúng cấu trúc BTC: `data/<business_id>/`, `rulebook.md`, `calendar.csv`, `questions.jsonl`.
- `/code/predict.sh` chạy không cần tham số. Mọi thiết lập (mô hình, `seed=2026`, `temperature`, batch...) đã được cố định sẵn, không cần chỉnh.
- File tạm được ghi vào `/tmp` trong container, không ghi vào `/data`.

### 5.4. Kết quả đầu ra

Thư mục `/result` (tự tạo nếu chưa có) chứa:
- `/result/submission.jsonl`: mỗi dòng là một câu trả lời (`id`, `type`, `answer`) cho từng câu trong `/data/questions.jsonl`. Câu nào xong là ghi ngay, nên nếu bị dừng giữa chừng thì các câu đã ghi vẫn được tính.
- `/result/logs/logs.jsonl`: mỗi câu hỏi một bản ghi gồm `id`, `answer`, `elapsed_ms`, `thinking` (nguyên văn reasoning của mô hình, theo thứ tự các lần gọi), `code` và `output` (truy vấn JSON Plan / DuckDB SQL đã thực thi cùng kết quả).
