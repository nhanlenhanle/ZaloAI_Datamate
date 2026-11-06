# Bản nháp, CHƯA build thử: cần máy có Docker và GPU đời mới (RTX 5090 là Blackwell sm_120, cần CUDA 12.8 trở lên).
# Ảnh vLLM phải chạy được Qwen3.5-9B trên Blackwell. Tra cứu 2026-11-02: bài viết ngoài nói vLLM 0.17.0 hỗ trợ đủ Qwen3.5;
# hướng dẫn chính thức chỉ gợi ý vllm/vllm-openai:cu130-nightly cho Blackwell. Ghim một tag cố định (không dùng latest / nightly)
# sau khi chạy thử được trên máy Blackwell: thể lệ yêu cầu chạy lại ra cùng kết quả.
ARG VLLM_IMAGE=vllm/vllm-openai:v0.17.0
FROM ${VLLM_IMAGE}

WORKDIR /app
# đúng bản đã dùng lúc phát triển và đo (bản khác có thể đổi kết quả SQL / cách đọc file). Ảnh vLLM chỉ có python3,
# không có lệnh python: cài và chạy cùng một trình (run.sh đọc PY).
ENV PY=python3 PIP_BREAK_SYSTEM_PACKAGES=1
RUN python3 -m pip install --no-cache-dir duckdb==1.5.6 pandas==2.3.3 python-calamine==0.8.3 \
 && python3 -c "import duckdb, pandas, python_calamine, importlib.metadata as m; print('duckdb', duckdb.__version__, 'vllm', m.version('vllm'))"

# trọng số model (tải sẵn khi build, lúc chấm không có mạng): đặt ở docker/models/qwen trước khi build
COPY docker/models/qwen /models/qwen
COPY datamate /app/datamate
COPY docker/assets /app/assets
COPY docker/run.sh /app/run.sh
# file soạn trên Windows có thể mang \r cuối dòng: bash trong container sẽ không chạy được
RUN sed -i 's/\r$//' /app/run.sh && chmod +x /app/run.sh

ENV HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
ENTRYPOINT ["/app/run.sh"]
