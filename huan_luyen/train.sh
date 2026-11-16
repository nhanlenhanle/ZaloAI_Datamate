#!/usr/bin/env bash
# Entry point tái lập huấn luyện và gộp LoRA cho Qwen3.5-9B và Qwen3.5-4B
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
export PY="${PY:-/opt/train_venv/bin/python3}"
[ -x "$PY" ] || export PY=python3

echo "=== 1. Huấn luyện & gộp LoRA Qwen3.5-9B (qwen9b/) với $PY ==="
cd "$DIR/qwen9b"
export BASE="${BASE:-Qwen/Qwen3.5-9B}"
bash train_800.sh
bash train_mix.sh
OUT="${OUT_9B:-/tmp/repro_models/qwen}" bash gop_mix.sh

echo "=== 2. Huấn luyện & gộp LoRA Qwen3.5-4B (qwen4b_norm/) với $PY ==="
cd "$DIR/qwen4b_norm"
"$PY" train_4b.py --model "${BASE_4B:-Qwen/Qwen3.5-4B}" --train full_gold_norm_v2_chatml_cleaned.jsonl --val val_norm_v2.jsonl --out adapter_v2
"$PY" gop_lora.py "${BASE_4B:-Qwen/Qwen3.5-4B}" adapter_v2 "${OUT_4B:-/tmp/repro_models/qwen_norm4b}"
