# Huấn luyện hai model dùng lúc chạy

Hai adapter LoRA dưới đây đã được gộp vào trọng số trong image (`/models/qwen`, `/models/qwen_norm4b`). Thư mục này chứa
code, dữ liệu đã dùng và chính adapter đó để kiểm hoặc làm lại. Lúc chạy bài không dùng thư mục này.

## qwen9b/: Qwen3.5-9B, LoRA tầng kế hoạch (JSON + SQL)
- Cách học: QLoRA 4-bit (nf4, compute bf16), r = 16, alpha = 32, dropout 0,05, mọi lớp tuyến tính (trừ phần ảnh / video,
  mtp, lm_head); chỉ tính loss trên phần trả lời. Một GPU 24 GB (RTX 3090 Ti), Python 3.12, torch 2.11 (cu128),
  transformers 5.2x, peft 0.21.
- Lượt 1 (`train_800.sh`): `thu_train.jsonl` (800 mẫu kế hoạch JSON), kiểm `thu_val.jsonl`.
- Lượt 2 (`train_mix.sh`): học tiếp adapter lượt 1 bằng `mix_train.jsonl` (2.200 mẫu: 700 kế hoạch JSON, 1.100 SQL,
  400 mẫu rulebook đổi luật), 1 epoch. `sql_gen_train.jsonl`, `sql_pv2.jsonl`, `rbd_sql_A.jsonl`, `rbd_sql_C.jsonl` là nguồn
  đã ghép thành phần SQL của mix.
- Gộp (`gop_mix.sh` -> `gop_lora.py`): W += (alpha / r) * B @ A cho từng ma trận có LoRA. Adapter đã dùng: `adapter_mix/`.
- Tạo dữ liệu: `make_plan_data.py`, `make_sql_data.py` (cần code `datamate/` của bài và các bộ shop tự sinh có lời giải).
  Prompt trong dữ liệu là đúng prompt pipeline gửi lúc chạy. `test_shops.txt`: shop giữ riêng để kiểm, không học.
- Kiểm: `eval_kehoach.py`, `cham_kiem_ft.py`.
- Nguồn dữ liệu: train của BTC và các bộ shop tự sinh của đội (shop, câu hỏi, đáp án do bộ sinh tạo).

## qwen4b_norm/: Qwen3.5-4B, LoRA làm sạch câu hỏi
- Dữ liệu: `build_norm_v2_dataset_ptv2.py --cleaned` -> `full_gold_norm_v2_chatml_cleaned.jsonl` (4.669 dòng).
  Nguồn: câu train của BTC (`biz_101`..`biz_130`), bộ tự sinh `bo_tu_sinh_v2` (`biz_501`..`biz_536`: câu nhiễu -> câu sạch do bộ sinh tạo), mẫu luật từ rulebook train, mẫu tổng hợp (đổi luật, ngành mới, giữ nguyên câu sạch).
- `A_train_lora_unsloth.ipynb` (Unsloth, bf16, max_seq_length 768) trên `full_gold_norm_v2_chatml_cleaned.jsonl`.
- Adapter đã dùng: `adapter_v2/`; gộp bằng `gop_lora.py` như trên.

Biến môi trường của các script: `BASE` (thư mục model gốc), `PY` (Python có đủ thư viện), `LORA`, `OUT`.
