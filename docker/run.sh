#!/bin/bash
# Chạy trong Docker lúc chấm: dựng DB từ dữ liệu đề ở /data, trả lời mọi câu, ghi /result/submission.jsonl.
# Mỗi GPU một server vLLM; code chia lượt hỏi cho các server. Ghi từng câu ngay khi xong: bị dừng giữa chừng thì
# câu chưa ghi tính là bỏ trống.
# Chạy thử ngoài Docker: đặt sẵn DATAMATE_LLM_URL (server có sẵn) thì không bật vLLM; APP, DATA, RESULT, WORK đổi được.
set -u
START=$(date +%s)
# giờ thi 6 tiếng: quá BUDGET giây (tính từ lúc container chạy) thì câu chưa làm ghi bỏ trống, chừa thời gian ghi file
BUDGET=${BUDGET:-19800}
APP=${APP:-/app}
DATA=${DATA:-/data}
RESULT=${RESULT:-/result}
WORK=${WORK:-/tmp/datamate}
MODEL=${MODEL:-/models/qwen}
WORKERS=${WORKERS:-16}
mkdir -p "$RESULT" "$WORK"
cd "$APP"
# thứ tự duyệt set chuỗi của Python cố định giữa các lần chạy (thể lệ: chạy lại lệch tối đa 0.03)
export PYTHONIOENCODING=utf-8 PYTHONHASHSEED=0
# trình Python có đủ thư viện: ảnh vLLM chỉ có python3 (Dockerfile đặt PY), máy Windows thường chỉ có python
if [ -z "${PY:-}" ]; then
  for p in python3 python; do $p -c "import duckdb" 2>/dev/null && { PY=$p; break; }; done
fi
PY=${PY:-python3}

Q=$(find "$DATA" -name questions.jsonl | head -1)
if [ -z "$Q" ]; then echo "không thấy questions.jsonl trong $DATA"; exit 1; fi
SPLIT=$(dirname "$Q")
# thư mục shop: data/ cạnh questions.jsonl như train / public; không có thì shop nằm ngay cạnh questions.jsonl
SHOPS="$SPLIT/data"; [ -d "$SHOPS" ] || SHOPS="$SPLIT"
OUT="$RESULT/submission.jsonl"
touch "$OUT"

if [ -z "${DATAMATE_LLM_URL:-}" ]; then
  NGPU=${NGPU:-$(nvidia-smi -L 2>/dev/null | wc -l)}
  # BATCH_INVARIANT=1: kết quả vLLM không phụ thuộc cách gộp batch (VLLM_BATCH_INVARIANT, beta, chậm hơn) -> chạy lại khớp
  # hơn. Mặc định tắt đến khi đo trên máy thật (docker/thu_may_that.sh)
  BI=${BATCH_INVARIANT:-0}
  echo "bộ đề: $SPLIT, GPU: $NGPU, Python: $PY, batch invariance: $BI"
  # Qwen3.5 có lớp linear-attention (bộ đệm kiểu Mamba): prefix caching cho loại này còn thử nghiệm -> mặc định tắt
  # (PREFIX_CACHE=1 để bật). Chế độ suy nghĩ tắt theo từng request (loader/llm.py gửi enable_thinking=false).
  CACHE_FLAG="--no-enable-prefix-caching"; [ "${PREFIX_CACHE:-0}" = "1" ] && CACHE_FLAG="--enable-prefix-caching"
  FAST="--max-model-len 32768 --gpu-memory-utilization 0.90 $CACHE_FLAG"
  # server chết lúc khởi động (thiếu bộ nhớ, CUDA graph, cờ lạ, batch invariance...) thì bật lại một lần với cấu hình ít
  # đòi hỏi hơn, không batch invariance
  SAFE="--max-model-len 16384 --gpu-memory-utilization 0.85 --enforce-eager"
  declare -a PIDS
  serve() {     # GPU, batch invariance 0/1, cờ vLLM thêm
    CUDA_VISIBLE_DEVICES=$1 VLLM_BATCH_INVARIANT=$2 vllm serve "$MODEL" --served-model-name qwen --port $((8000 + $1)) \
        --seed 2026 --max-num-seqs 64 "${@:3}" >> "$WORK/vllm_$1.log" 2>&1 &
    PIDS[$1]=$!
  }
  up() { $PY -c "import sys, urllib.request; urllib.request.urlopen(sys.argv[1] + '/v1/models', timeout=5)" "$1" 2>/dev/null; }
  wait_up() {   # URL, PID: thành công khi server trả lời; thất bại khi tiến trình chết hoặc quá 20 phút
    for i in $(seq 1 240); do
      up "$1" && return 0
      kill -0 "$2" 2>/dev/null || return 1
      sleep 5
    done
    return 1
  }
  GPUS=$(seq 0 $((NGPU > 0 ? NGPU - 1 : 0)))
  for g in $GPUS; do serve $g "$BI" $FAST; done
  LIVE=""
  for g in $GPUS; do
    u="http://127.0.0.1:$((8000 + g))"
    if ! wait_up "$u" "${PIDS[$g]}"; then
      echo "vLLM GPU $g không lên, bật lại với: $SAFE, không batch invariance"; tail -n 20 "$WORK/vllm_$g.log"
      kill "${PIDS[$g]}" 2>/dev/null; sleep 15
      serve $g 0 $SAFE
      # server nào vẫn không lên thì bỏ, chạy với các server còn lại
      wait_up "$u" "${PIDS[$g]}" || { echo "vLLM GPU $g vẫn không lên:"; tail -n 30 "$WORK/vllm_$g.log"; continue; }
    fi
    LIVE="${LIVE:+$LIVE,}$u"
  done
  echo "vLLM sẵn sàng sau $(($(date +%s) - START))s"
  # lấy mẫu chỉ theo nhiệt độ như lúc đo (ollama: top_p 1, top_k 0, repeat_penalty 1): không để vLLM lấy top_k / top_p
  # mặc định trong generation_config.json của model
  export DATAMATE_LLM_URL="$LIVE" DATAMATE_LLM_KEY=none DATAMATE_LLM_MODEL=qwen \
         DATAMATE_LLM_EXTRA='{"top_p": 1, "top_k": -1, "min_p": 0, "repetition_penalty": 1}'
fi
echo "LLM: ${DATAMATE_LLM_URL:-không có}"

# 1. dữ liệu: đọc file shop, đặt tên cột chuẩn (LLM), dựng DuckDB mỗi shop. Từ điển tên cột lấy từ README các shop khác
# của đề; README train (assets/readme_train) chỉ bổ sung tên mà README của đề chưa từng mô tả (đề có README không mô tả cột)
LLM_FLAG=""; [ -n "$DATAMATE_LLM_URL" ] && LLM_FLAG="--llm"
BASE=""; [ -d assets/readme_train ] && BASE="--base-readmes assets/readme_train"
$PY -m datamate.run_all "$SHOPS" --out "$WORK/db" $LLM_FLAG --skip-tables $BASE
DB=$(find "$WORK/db" -mindepth 1 -maxdepth 1 -type d | head -1)
echo "dựng DB xong sau $(($(date +%s) - START))s: $DB"

# 2. câu hỏi: LLM lập kế hoạch JSON / viết SQL; code chạy, bỏ phiếu, định dạng §9
LEFT=$((BUDGET - ($(date +%s) - START))); [ "$LEFT" -lt 1 ] && LEFT=1
if [ -n "$DATAMATE_LLM_URL" ] && [ -n "$DB" ]; then
  $PY -m datamate.query.answer "$SPLIT" "$DB" --out "$OUT" --workers "$WORKERS" --han-giay "$LEFT" \
      --examples assets/examples_train.jsonl --luat-examples assets/examples_luat.jsonl --sql-examples assets/examples_sql_train.jsonl
fi

# viết lại file nộp theo thứ tự câu hỏi: câu nào chưa có dòng (lỗi bất ngờ) thì bỏ trống, dòng ghi dở thì bỏ
$PY - "$Q" "$OUT" <<'EOF'
import json, os, sys
ids = [json.loads(l)["id"] for l in open(sys.argv[1], encoding="utf-8") if l.strip()]
recs = {}
for l in open(sys.argv[2], encoding="utf-8"):
    try:
        r = json.loads(l)
        recs.setdefault(r["id"], r)
    except (ValueError, KeyError, TypeError):
        pass
with open(sys.argv[2] + ".tmp", "w", encoding="utf-8") as fh:
    for i in ids:
        fh.write(json.dumps(recs.get(i, {"id": i, "type": "abstain"}), ensure_ascii=False) + "\n")
os.replace(sys.argv[2] + ".tmp", sys.argv[2])
print("đủ", len(ids), "câu, trả lời", sum(recs.get(i, {}).get("type", "abstain") != "abstain" for i in ids))
EOF
echo "xong sau $(($(date +%s) - START))s"
