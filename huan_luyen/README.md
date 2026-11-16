# Hướng dẫn Tái lập Sinh dữ liệu & Huấn luyện (`/code/training_code`)

Thư mục này chứa đầy đủ mã nguồn sinh dữ liệu giả lập (`bo_sinh/`), dữ liệu huấn luyện/kiểm thử (`.jsonl`), cấu hình (`configs/`), nhật ký huấn luyện thực tế (`logs/`), kịch bản huấn luyện QLoRA/LoRA và trọng số adapter đầu ra (`qwen9b/adapter_mix/` và `qwen4b_norm/adapter_v2/`) đã được gộp vào `/models/qwen` và `/models/qwen_norm4b`.

---

## 1. Môi trường, Phần cứng & Thời gian chạy (Hardware & Runtime)

| Giai đoạn | Mô hình gốc (Base Revision) | Phần cứng (Hardware) | Tập dữ liệu (Train / Val) | Thời gian chạy thực tế (Runtime) | Log & Trạng thái |
| :--- | :--- | :--- | :--- | :---: | :--- |
| **1. Sinh dữ liệu giả lập (`bo_sinh/`)** | Rule-based Simulator (`sinh.py`, `seed=7, 19`) | CPU (16 luồng) | `gen_train` (76 shop, 3.561 câu) + `bo_tu_sinh_v2` (36 shop, 2.473 câu) | ~18 phút (`1.080s`) | `logs/bo_sinh_generation.log` |
| **2. Fine-tune 9B Lượt 1 (`qwen9b/train_800.sh`)** | `Qwen/Qwen3.5-9B` (`c202236235762e1c871ad0ccb60c8ee5ba337b9a`) | `1x NVIDIA RTX 3090 Ti 24GB` | `thu_train.jsonl` (**800 mẫu**) / `thu_val.jsonl` (**40 mẫu**) | **2 giờ 15 phút** (`8.120s`, 100 steps) | `logs/qwen9b_stage1_run800_part2.log`, `logs/qwen9b_stage1_trainer_state.json` |
| **3. Fine-tune 9B Lượt 2 Mix (`qwen9b/train_mix.sh`)** | `Qwen/Qwen3.5-9B` + init từ `run800/lora` | `1x NVIDIA RTX 3090 Ti 24GB` | `mix_train.jsonl` (**2.200 mẫu**: 700 JSON + 1.100 SQL + 400 rule-drift) / `thu_val.jsonl` (**40 mẫu**) | **7 giờ 08 phút** (`25.670s`, 275 steps, `loss=0.06407`) | `logs/qwen9b_stage2_runmix.log`, `logs/qwen9b_stage2_trainer_state.json` |
| **4. Gộp LoRA 9B (`qwen9b/gop_mix.sh`)** | `Qwen/Qwen3.5-9B` + `adapter_mix` ($\alpha/r = 2.0$) | CPU RAM 64GB | 248 / 248 ma trận tuyến tính | ~4 phút (`240s`) | `logs/qwen9b_merge_lora_248.log` |
| **5. Fine-tune 4B Norm (`qwen4b_norm/A_train_lora_unsloth.ipynb`)** | `Qwen/Qwen3.5-4B` (`851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a`) | `1x GPU (Unsloth / TRL SFTTrainer, peft==0.21.2)` | `full_gold_norm_v2_chatml_cleaned.jsonl` (**4.669 mẫu**, `batch=4 x 4 = 16`, 3 epochs) | ~18 phút (đã gộp ngày 2026-11-14 vào `/models/qwen_norm4b`) | `qwen4b_norm/A_train_lora_unsloth.ipynb`, `qwen4b_norm/adapter_v2/` |
| **6. Script tái lập độc lập 4B (`qwen4b_norm/train_4b.py`, `gop_lora.py`)** | `Qwen/Qwen3.5-4B` (`851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a`) | `/opt/train_venv` (`transformers.Trainer`) | `full_gold_norm_v2_chatml_cleaned.jsonl` / `val_norm_v2.jsonl` | ~18 phút (tái lập thuần HF, không phụ thuộc Unsloth) | `logs/qwen4b_norm_v2_train.log` (bản tóm tắt đối chiếu) |

---

## 2. Lệnh thực thi chính xác (Exact Reproduction Commands)

Các thư viện huấn luyện (`torch`, `transformers>=5.2.0`, `peft`, `bitsandbytes`, `accelerate`) được cài sẵn trong môi trường cách ly `/opt/train_venv/bin/python3`, còn `openpyxl` và bộ công cụ chạy suy luận nằm ở `python3` hệ thống. *(Lưu ý: notebook gốc 4B dùng `unsloth`/`trl` trên máy train rời; trong container dùng `train_4b.py` thuần `transformers.Trainer`).*

### A. Chạy toàn bộ quá trình huấn luyện & gộp trọng số bằng 1 lệnh:
```bash
BASE=/path/to/Qwen3.5-9B BASE_4B=/path/to/Qwen3.5-4B bash /code/training_code/train.sh
```

### B. Hoặc chạy từng bước thành phần:
1. **Sinh dữ liệu cửa hàng giả lập (`bo_sinh/`):**
   ```bash
   cd /code/training_code/bo_sinh
   python3 -I sinh.py thu_vien_goc /tmp/gen_train --n 76 --seed 7 --start 301 --loi-giai
   python3 -I sinh.py thu_vien_goc /tmp/bo_tu_sinh_v2 --n 36 --seed 19 --start 501 --layout-public --van-public --cau-lech --loi-giai
   ```
2. **Tạo dữ liệu huấn luyện JSON Plan & SQL cho 9B (`qwen9b/`):**
   ```bash
   cd /code/training_code/qwen9b
   python3 make_plan_data.py --gen /tmp/gen_train --gen-db /tmp/gen_db --gen-cham /tmp/gen_cham.jsonl --out /tmp/plan_out --test-shops biz_801
   python3 make_sql_data.py --gen /tmp/gen_train --gen-db /tmp/gen_db --gen-cham /tmp/gen_cham.jsonl --out /tmp/sql_out.jsonl --test-shops biz_801
   ```
3. **Huấn luyện QLoRA 2 giai đoạn và gộp trọng số cho 9B (`qwen9b/`):**
   ```bash
   cd /code/training_code/qwen9b
   BASE=/path/to/Qwen3.5-9B bash train_800.sh
   BASE=/path/to/Qwen3.5-9B bash train_mix.sh
   BASE=/path/to/Qwen3.5-9B OUT=/models/qwen bash gop_mix.sh
   ```
4. **Dựng dữ liệu, huấn luyện LoRA và gộp trọng số cho 4B (`qwen4b_norm/`):**
   ```bash
   cd /code/training_code/qwen4b_norm
   python3 build_norm_v2_dataset_ptv2.py --cleaned
   python3 train_4b.py --model /path/to/Qwen3.5-4B --train full_gold_norm_v2_chatml_cleaned.jsonl --val val_norm_v2.jsonl --out adapter_v2
   python3 gop_lora.py /path/to/Qwen3.5-4B adapter_v2 /models/qwen_norm4b
   ```

---

## 3. Các bước ngẫu nhiên & Cố định Seed (Determinism Notes)

- Bộ sinh dữ liệu giả lập (`bo_sinh/sinh.py`) cố định `random.Random(f"{seed}-{shop_id}")` theo từng cửa hàng (`seed=7` và `seed=19`).
- Dựng dữ liệu chuẩn hóa câu hỏi (`build_norm_v2_dataset_ptv2.py`) cố định `random.Random(2026)`.
- Huấn luyện QLoRA 9B (`train_kehoach.py`) cố định `seed=42`; huấn luyện LoRA 4B (`train_4b.py`) cố định `seed=2026`. Sai số số học dấu phẩy động giữa các kiến trúc GPU khi huấn luyện lại không ảnh hưởng đến việc kiểm chứng vì toàn bộ dữ liệu `.jsonl` đã sinh và trọng số `adapter_mix/` + `adapter_v2/` đã được đóng gói nguyên vẹn trong image kèm mã băm SHA-256 tại `data_manifest.json`.
