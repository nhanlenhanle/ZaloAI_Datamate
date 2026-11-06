#!/bin/bash
# Gom đủ thứ Dockerfile cần vào docker/ trước khi build (chạy từ thư mục "code solve data"):
#   docker/assets/  ba kho ví dụ bản cuối (đổi tên về tên run.sh dùng)
#   docker/models/qwen/  trọng số Qwen/Qwen3.5-9B (bf16, từ Hugging Face; lúc chấm không có mạng nên phải có sẵn trong image)
# Rồi: docker build -f docker/Dockerfile -t datamate .
set -eu
Q="${Q:-../solve data/query}"
mkdir -p docker/assets
cp "$Q/examples_train.jsonl" docker/assets/examples_train.jsonl              # câu train -> kế hoạch JSON đã kiểm
cp "$Q/examples_sql_train_v2.jsonl" docker/assets/examples_sql_train.jsonl   # câu train -> SQL đã kiểm
# dòng luật tự đặt -> cách tính đã kiểm: kho R + R2. Kho R1-R4 (examples_luat_r1234) kém hơn trên R5 ở cả Q8 lẫn Q4
# (SQL7: +0.734 vs +0.789, +0.743 vs +0.761; luật chọn chốt trước khi đo)
cp "$Q/examples_luat_r12.jsonl" docker/assets/examples_luat.jsonl
md5sum docker/assets/*.jsonl
# README train (chỉ README, không dữ liệu): từ điển tên cột nền cho đề mà README không mô tả cột (run.sh: --base-readmes)
T="${T:-../train/train/data}"
for d in "$T"/*/; do
  s=$(basename "$d"); mkdir -p "docker/assets/readme_train/$s"; cp "$d/README.md" "docker/assets/readme_train/$s/README.md"
done
echo "README train: $(ls docker/assets/readme_train | wc -l) shop"
# máy build là Linux: bỏ \r cuối dòng (file soạn trên Windows), không thì bash ở đó không chạy được các script này
sed -i 's/\r$//' docker/run.sh docker/thu_may_that.sh docker/Dockerfile

if [ ! -f docker/models/qwen/config.json ]; then
  echo "chưa có trọng số ở docker/models/qwen: docker/thu_may_that.sh tự tải trên máy build"
  exit 1
fi
du -sh docker/models/qwen
