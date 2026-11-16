FROM datamate_base:s26n

ENTRYPOINT []
ENV PY=python3 \
    PYTHONPATH=/app \
    PIP_BREAK_SYSTEM_PACKAGES=1 \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    PIP_NO_CACHE_DIR=1 \
    NCCL_P2P_DISABLE=1

WORKDIR /app
RUN python3 -m pip install --no-cache-dir --no-deps \
    peft==0.18.0 accelerate==1.4.0 bitsandbytes==0.46.1 \
 && python3 -m venv --system-site-packages /opt/train_venv \
 && /opt/train_venv/bin/pip install --no-cache-dir "transformers>=5.2.0" \
 && rm -rf /app/datamate /app/assets /app/huan_luyen /app/run.sh /code && mkdir -p /code

COPY datamate /app/datamate
COPY docker/assets /app/assets
COPY huan_luyen /app/huan_luyen
COPY docker/run.sh /app/run.sh
COPY README.md /app/README.md
COPY requirements.txt /app/requirements.txt

COPY docker/predict.sh /code/predict.sh
COPY README.md /code/README.md
COPY requirements.txt /code/requirements.txt
COPY Dockerfile /code/Dockerfile

RUN /opt/train_venv/bin/python3 -c "import importlib.metadata as m; pkgs=['torch','transformers','peft','accelerate','bitsandbytes','safetensors','duckdb','pandas','python-calamine']; txt='\n'.join(f'{p}=={m.version(p)}' for p in pkgs)+'\n'; open('/app/huan_luyen/requirements.txt','w').write(txt)" \
 && sed -i 's/\r$//' /app/run.sh /code/predict.sh /app/huan_luyen/train.sh \
 && chmod +x /app/run.sh /code/predict.sh /app/huan_luyen/train.sh \
 && python3 /app/huan_luyen/make_manifest.py \
 && ln -s /app/datamate /code/src \
 && ln -s /models /code/models \
 && ln -s /app/huan_luyen /code/training_code \
 && python3 -c "import vllm, transformers, duckdb, pandas, python_calamine; print('INFER OK:', vllm.__version__, transformers.__version__)" \
 && /opt/train_venv/bin/python3 -c "import torch, transformers, peft, accelerate, bitsandbytes; from transformers import AutoConfig, AutoModelForCausalLM, Trainer, TrainingArguments; cfg = AutoConfig.from_pretrained('/models/qwen_norm4b'); print('TRAIN OK:', transformers.__version__, cfg.model_type)" \
 && test -f /models/qwen/config.json && test -f /models/qwen_norm4b/config.json \
 && test -f /app/assets/examples_train_norm.jsonl && test -f /app/assets/rulebook_train.md \
 && test -f /code/training_code/data_manifest.json

WORKDIR /code
CMD ["bash", "/code/predict.sh"]
