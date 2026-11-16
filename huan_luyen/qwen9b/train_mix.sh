#!/bin/bash
#SBATCH --gres=gpu:1
#SBATCH -t 0-16:00:00
#SBATCH -J dm_ft_mix
# Lượt 2: học tiếp adapter lượt 1 bằng 2.200 mẫu (mix_train.jsonl: 700 JSON + 1.100 SQL + 400 rulebook đổi luật A, C), 1 epoch.
# Chết giữa chừng (hết bộ nhớ GPU) thì chạy lại từ checkpoint gần nhất, tối đa 5 lần.
W=$(cd "$(dirname "$0")" && pwd); BASE=${BASE:-models/Qwen3.5-9B}; PY=${PY:-/opt/train_venv/bin/python3}; [ -x "$PY" ] || PY=python3
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True,garbage_collection_threshold:0.6
cd "$W"; nvidia-smi --query-gpu=name,memory.used --format=csv
ok=0
for lan in 1 2 3 4 5; do
  echo "== lần chạy $lan $(date +%T)"
  $PY train_kehoach.py --model "$BASE" --train mix_train.jsonl --init-lora "$W/run800/lora" --out "$W/runmix" && { ok=1; break; }
  sleep 20
done
[ "$ok" = "1" ] || exit 1
echo TRAIN_XONG
