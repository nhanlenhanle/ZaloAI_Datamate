#!/bin/bash
#SBATCH --gres=gpu:1
#SBATCH -t 0-08:00:00
#SBATCH -J dm_ft_800
# Lượt 1: LoRA trên 800 mẫu kế hoạch JSON (thu_train.jsonl), kiểm trên thu_val.jsonl.
# BASE: thư mục Qwen/Qwen3.5-9B gốc; PY: Python có torch / transformers / peft (xem HUONG_DAN.md).
W=$(cd "$(dirname "$0")" && pwd); BASE=${BASE:-models/Qwen3.5-9B}; PY=${PY:-/opt/train_venv/bin/python3}; [ -x "$PY" ] || PY=python3
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
cd "$W"; nvidia-smi --query-gpu=name,memory.used --format=csv
$PY train_kehoach.py --model "$BASE" --train thu_train.jsonl --val thu_val.jsonl --out "$W/run800" && echo TRAIN_XONG
