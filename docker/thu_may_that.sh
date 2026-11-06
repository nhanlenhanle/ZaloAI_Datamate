#!/bin/bash
# Thử image trên máy có GPU thật (nên là RTX 5090 như máy chấm), trước khi nộp. Chạy từ thư mục "code solve data":
#   bash docker/thu_may_that.sh <thư mục đề có questions.jsonl> [số lần chạy, mặc định 2]
#   BATCH_INVARIANT=1 bash docker/thu_may_that.sh ...    # thử chế độ batch invariance của vLLM (run.sh): lệch ít hơn, chậm hơn
# Cần: docker + nvidia-container-toolkit, ~70 GB đĩa trống, mạng lúc tải trọng số và build (lúc chạy thì không cần).
# Không cần Python / pip trên máy: trọng số tải bằng Python trong ảnh vLLM, so các lần chạy bằng chính image vừa build.
# Ra: thu_that/bi<0|1>_lan_<k>/{submission.jsonl, run.log}; cuối cùng so các lần chạy cùng chế độ (thể lệ: lệch tối đa 0.03).
set -euo pipefail
DE=$(realpath "$1"); N=${2:-2}; BI=${BATCH_INVARIANT:-0}
[ -f docker/assets/examples_luat.jsonl ] || { echo "thiếu docker/assets: chạy docker/chuan_bi.sh trên máy có thư mục solve data"; exit 1; }
nvidia-smi -L
df -h . | tail -1
# trọng số Qwen/Qwen3.5-9B (bf16) vào docker/models/qwen: bị ngắt thì chạy lại tải tiếp, đủ rồi thì chỉ kiểm lại
IMG=$(sed -n 's/^ARG VLLM_IMAGE=//p' docker/Dockerfile | tr -d '\r')
mkdir -p docker/models
docker run --rm -v "$PWD/docker/models":/models --entrypoint python3 "$IMG" \
    -c "from huggingface_hub import snapshot_download as d; d('Qwen/Qwen3.5-9B', local_dir='/models/qwen')"
# pipefail: build lỗi thì dừng ở đây, không chạy tiếp bằng image cũ
docker build -f docker/Dockerfile -t datamate . 2>&1 | tail -n 20
for k in $(seq 1 "$N"); do
  o="$PWD/thu_that/bi${BI}_lan_$k"; rm -rf "$o"; mkdir -p "$o"
  echo "== batch invariance $BI, lần $k bắt đầu $(date +%T)"
  # như máy chấm: không mạng, đề chỉ đọc
  docker run --rm --gpus all --network none -e BATCH_INVARIANT="$BI" -v "$DE":/data:ro -v "$o":/result datamate \
      > "$o/run.log" 2>&1 || true
  grep -E "GPU|sẵn sàng|không lên|dựng DB xong|đủ .* câu|xong sau" "$o/run.log" || tail -n 20 "$o/run.log"
done
docker run --rm -e PYTHONIOENCODING=utf-8 -v "$PWD":/w -w /w --entrypoint python3 datamate \
    docker/so_lan_chay.py thu_that/bi${BI}_lan_*/submission.jsonl
