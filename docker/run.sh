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
# số câu hỏi song song (mỗi câu gọi LLM nhiều lần, lần lượt): 2 GPU x 64 chuỗi mỗi server vLLM -> 32 luồng
WORKERS=${WORKERS:-32}
# làm sạch câu hỏi bằng con 4B (Qwen3.5-4B + LoRA v2 đã gộp) trước khi trả lời; NORM=0 để tắt
NORM=${NORM:-1}
NORM_MODEL=${NORM_MODEL:-/models/qwen_norm4b}
mkdir -p "$RESULT" "$RESULT/logs" "$WORK"
cd "$APP"
# thứ tự duyệt set chuỗi của Python cố định giữa các lần chạy (thể lệ: chạy lại lệch tối đa 0.03)
export PYTHONIOENCODING=utf-8 PYTHONHASHSEED=0
# hạn chót chung: mọi lời gọi LLM (dựng DB, trả lời) tự cắt thời gian chờ theo giờ còn lại, quá hạn thì thôi
export DATAMATE_HAN_CHOT=$((START + BUDGET))
# nợ khi bảng đơn không có tổng đơn (NV2) + tồn = nhập - xuất + trả (TON_DONG): không đổi kho ví dụ
# train BTC -> bật mặc định
export DATAMATE_NV2=${DATAMATE_NV2:-1} DATAMATE_TON_DONG=${DATAMATE_TON_DONG:-1} DATAMATE_TU_SUA=${DATAMATE_TU_SUA:-1}
# trình Python có đủ thư viện: ảnh vLLM chỉ có python3 (Dockerfile đặt PY), máy Windows thường chỉ có python
if [ -z "${PY:-}" ]; then
  for p in python3 python; do $p -c "import duckdb" 2>/dev/null && { PY=$p; break; }; done
fi
PY=${PY:-python3}

Q=$(find "$DATA" -name questions.jsonl | head -1)
if [ -z "$Q" ]; then echo "không thấy questions.jsonl trong $DATA"; exit 1; fi
SPLIT=$(dirname "$Q")
# thư mục shop: data/ cạnh questions.jsonl như train; không có thì shop nằm ngay cạnh questions.jsonl
SHOPS="$SPLIT/data"; [ -d "$SHOPS" ] || SHOPS="$SPLIT"
OUT="$RESULT/submission.jsonl"
LOG_OUT="$RESULT/logs/logs.jsonl"
touch "$OUT" "$LOG_OUT"

TU_BAT=0     # 1: script tự bật server vLLM (trong Docker); 0: dùng server có sẵn (chạy thử)
if [ -z "${DATAMATE_LLM_URL:-}" ]; then
  TU_BAT=1
  NGPU=${NGPU:-$(nvidia-smi -L 2>/dev/null | wc -l)}
  # BATCH_INVARIANT=1: kết quả vLLM không phụ thuộc cách gộp batch (VLLM_BATCH_INVARIANT, beta, chậm hơn) -> chạy lại khớp
  # hơn. Mặc định tắt đến khi đo trên máy thật (docker/thu_may_that.sh)
  BI=${BATCH_INVARIANT:-0}
  echo "bộ đề: $SPLIT, GPU: $NGPU, Python: $PY, batch invariance: $BI"
  # Qwen3.5 có lớp linear-attention (bộ đệm kiểu Mamba): prefix caching cho loại này còn thử nghiệm -> mặc định tắt
  # (PREFIX_CACHE=1 để bật). Chế độ suy nghĩ tắt theo từng request (loader/llm.py gửi enable_thinking=false).
  CACHE_FLAG="--no-enable-prefix-caching"; [ "${PREFIX_CACHE:-0}" = "1" ] && CACHE_FLAG="--enable-prefix-caching"
  FAST="--max-model-len 32768 --gpu-memory-utilization 0.80 $CACHE_FLAG"
  # server chết lúc khởi động (thiếu bộ nhớ, CUDA graph, cờ lạ, batch invariance...) thì bật lại một lần với cấu hình ít
  # đòi hỏi hơn, không batch invariance
  SAFE="--max-model-len 16384 --gpu-memory-utilization 0.80 --enforce-eager"
  declare -a PIDS
  serve() {     # GPU, batch invariance 0/1, cờ vLLM thêm
    CUDA_VISIBLE_DEVICES=$1 VLLM_BATCH_INVARIANT=$2 vllm serve "$MODEL" --served-model-name qwen --port $((8000 + $1)) \
        --seed 2026 --max-num-seqs 32 "${@:3}" >> "$WORK/vllm_$1.log" 2>&1 &
    PIDS[$1]=$!
  }
  # tắt các server và ĐỢI tới khi thoát hẳn (nhả bộ nhớ GPU): dọn luôn tiến trình con (EngineCore) nếu cần
  stop_pids() {
    for p in "$@"; do pkill -TERM -P "$p" 2>/dev/null || true; kill "$p" 2>/dev/null || true; done
    for p in "$@"; do
      for i in $(seq 1 60); do kill -0 "$p" 2>/dev/null || break; sleep 2; done
      pkill -9 -P "$p" 2>/dev/null || true
      kill -9 "$p" 2>/dev/null || true
    done
    sleep 5
  }
  stop_all() { stop_pids "${PIDS[@]}"; }
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
  # bật lại 9B trên mọi GPU (sau bước làm sạch): như lần đầu, có cấu hình dự phòng
  start_9b() {
    LIVE=""
    for g in $GPUS; do serve $g "$BI" $FAST; done
    for g in $GPUS; do
      u="http://127.0.0.1:$((8000 + g))"
      if ! wait_up "$u" "${PIDS[$g]}"; then
        kill "${PIDS[$g]}" 2>/dev/null; sleep 15; serve $g 0 $SAFE
        wait_up "$u" "${PIDS[$g]}" || { echo "vLLM GPU $g vẫn không lên"; continue; }
      fi
      LIVE="${LIVE:+$LIVE,}$u"
    done
  }
  echo "vLLM sẵn sàng sau $(($(date +%s) - START))s"
  # lấy mẫu chỉ theo nhiệt độ như lúc đo (ollama: top_p 1, top_k 0, repeat_penalty 1): không để vLLM lấy top_k / top_p
  # mặc định trong generation_config.json của model
  export DATAMATE_LLM_URL="$LIVE" DATAMATE_LLM_KEY=none DATAMATE_LLM_MODEL=qwen \
         DATAMATE_LLM_EXTRA='{"top_p": 1, "top_k": -1, "min_p": 0, "repetition_penalty": 1}'
fi
echo "LLM: ${DATAMATE_LLM_URL:-không có}"
if [ "$TU_BAT" = "1" ] && [ -z "${DATAMATE_LLM_URL:-}" ]; then
  echo "ERROR: không có server vLLM nào khởi động được!" >&2
  exit 1
fi

# 1. dữ liệu: đọc file shop, đặt tên cột chuẩn (LLM), dựng DuckDB mỗi shop. Từ điển tên cột lấy từ README các shop khác
# của đề; README train (assets/readme_train) chỉ bổ sung tên mà README của đề chưa từng mô tả (đề có README không mô tả cột)
LLM_FLAG=""; [ -n "$DATAMATE_LLM_URL" ] && LLM_FLAG="--llm"
BASE=""; [ -d assets/readme_train ] && BASE="--base-readmes assets/readme_train"
$PY -m datamate.run_all "$SHOPS" --out "$WORK/db" $LLM_FLAG --skip-tables $BASE
DB=$(find "$WORK/db" -mindepth 1 -maxdepth 1 -type d | head -1)
echo "dựng DB xong sau $(($(date +%s) - START))s: $DB"

# 1b. làm sạch câu hỏi bằng 4B (thẻ <ENT_k> cho tên trong DB, luật liên quan của shop, kiểm an toàn; câu nào không qua
# kiểm thì giữ câu gốc). Lỗi gì cũng quay về câu gốc.
EX_TRAIN=assets/examples_train.jsonl; EX_LUAT=assets/examples_luat.jsonl; EX_SQL=assets/examples_sql_train.jsonl
QSPLIT="$SPLIT"; export DATAMATE_TELEX=1
if [ "$NORM" = "1" ] && [ -n "$DB" ] && [ -f assets/examples_train_norm.jsonl ]; then
  NURL=${DATAMATE_NORM_URL:-}
  if [ -z "$NURL" ] && [ "$TU_BAT" = "1" ] && [ -d "$NORM_MODEL" ]; then
    stop_all
    declare -a NPIDS
    for g in $GPUS; do
      CUDA_VISIBLE_DEVICES=$g vllm serve "$NORM_MODEL" --served-model-name qwen_norm --port $((8100 + g)) --seed 2026 \
          --max-model-len 4096 --max-num-seqs 64 --gpu-memory-utilization 0.80 \
          --limit-mm-per-prompt '{"image": 0, "video": 0}' >> "$WORK/norm_$g.log" 2>&1 &
      NPIDS[$g]=$!
    done
    for g in $GPUS; do wait_up "http://127.0.0.1:$((8100 + g))" "${NPIDS[$g]}" && NURL="http://127.0.0.1:$((8100 + g))" && break; done
    echo "4B làm sạch: ${NURL:-không lên} sau $(($(date +%s) - START))s"
  fi
  if [ -n "$NURL" ]; then
    mkdir -p "$WORK/de_norm"
    cp "$SPLIT"/rulebook.md "$SPLIT"/calendar.csv "$WORK/de_norm/" 2>/dev/null
    if $PY -m datamate.query.normalize_all --input "$Q" --output "$WORK/de_norm/questions.jsonl" --db-root "$DB" \
         --url "$NURL" --key "${DATAMATE_NORM_KEY:-none}" --model qwen_norm --cache "$WORK/norm_cache.jsonl" \
         --workers "${NORM_WORKERS:-32}" && [ -s "$WORK/de_norm/questions.jsonl" ]; then
      QSPLIT="$WORK/de_norm"; export DATAMATE_TELEX=0
      EX_TRAIN=assets/examples_train_norm.jsonl; EX_LUAT=assets/examples_luat_norm.jsonl; EX_SQL=assets/examples_sql_train_norm.jsonl
      echo "làm sạch xong sau $(($(date +%s) - START))s"
    else
      echo "làm sạch lỗi: dùng câu gốc"
    fi
  fi
  if [ "$TU_BAT" = "1" ] && [ -z "${DATAMATE_NORM_URL:-}" ] && [ -d "$NORM_MODEL" ]; then
    stop_pids "${NPIDS[@]}"
    start_9b
    # 9B không lên lại trên GPU nào (bộ nhớ chưa nhả kịp...): đợi thêm rồi bật lần nữa, không thì cả đề bỏ trống
    if [ -z "$LIVE" ]; then echo "9B chưa lên lại, thử lần nữa"; stop_all; sleep 30; start_9b; fi
    if [ -z "$LIVE" ]; then echo "ERROR: 9B không lên lại được sau bước làm sạch!" >&2; exit 1; fi
    export DATAMATE_LLM_URL="$LIVE"
    echo "bật lại 9B sau $(($(date +%s) - START))s: $LIVE"
  fi
fi

# 2. câu hỏi: LLM lập kế hoạch JSON / viết SQL; code chạy, bỏ phiếu, định dạng §9
# Tối đa 3 lượt: câu lỗi mạng / server chưa có dòng thì lượt sau làm lại (câu đã có dòng được bỏ qua), khi còn giờ
NQ=$(grep -c . "$Q")
if [ -n "$DATAMATE_LLM_URL" ] && [ -n "$DB" ]; then
  for LUOT in 1 2 3; do
    LEFT=$((BUDGET - ($(date +%s) - START))); [ "$LEFT" -lt 60 ] && break
    $PY -m datamate.query.answer "$QSPLIT" "$DB" --out "$OUT" --workers "$WORKERS" --han-giay "$LEFT" \
        --examples "$EX_TRAIN" --luat-examples "$EX_LUAT" --sql-examples "$EX_SQL"
    CO=$(grep -c . "$OUT"); echo "lượt $LUOT: $CO / $NQ câu có dòng sau $(($(date +%s) - START))s"
    [ "$CO" -ge "$NQ" ] && break
  done
fi

# viết lại file nộp và file log theo thứ tự câu hỏi: câu nào chưa có dòng (lỗi bất ngờ) thì bỏ trống, dòng ghi dở thì bỏ
$PY - "$Q" "$OUT" "$LOG_OUT" <<'EOF'
import json, os, sys
ids = [json.loads(l)["id"] for l in open(sys.argv[1], encoding="utf-8-sig") if l.strip()]
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

logs = {}
if os.path.exists(sys.argv[3]):
    for l in open(sys.argv[3], encoding="utf-8"):
        try:
            r = json.loads(l)
            logs.setdefault(r["id"], r)
        except (ValueError, KeyError, TypeError):
            pass
with open(sys.argv[3] + ".tmp", "w", encoding="utf-8") as lfh:
    for i in ids:
        rec = recs.get(i, {"id": i, "type": "abstain"})
        ans_obj = {k: v for k, v in rec.items() if k != "id"}
        default_log = {"id": i, "answer": ans_obj, "elapsed_ms": 0, "thinking": None, "code": None, "output": None}
        lfh.write(json.dumps(logs.get(i, default_log), ensure_ascii=False) + "\n")
os.replace(sys.argv[3] + ".tmp", sys.argv[3])
print("đủ", len(ids), "câu, trả lời", sum(recs.get(i, {}).get("type", "abstain") != "abstain" for i in ids))
EOF
echo "xong sau $(($(date +%s) - START))s"
