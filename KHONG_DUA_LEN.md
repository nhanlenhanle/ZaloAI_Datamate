# Files not included in this repository

The solution submitted to Zalo AI Challenge 2026 (DataMate) shipped as a Docker image
(`zaic2026_datamate_fall_to_fly:final`). This repository holds the code, scripts, configs, logs
and small data files from that image. Large files were left out:

| File | Size | Reason |
|---|---|---|
| `huan_luyen/qwen9b/adapter_mix/adapter_model.safetensors` | 173 MB | LoRA adapter for Qwen3.5-9B (weights) |
| `huan_luyen/qwen4b_norm/adapter_v2/adapter_model.safetensors` | 85 MB | LoRA adapter for Qwen3.5-4B (weights) |
| `huan_luyen/*/adapter_*/tokenizer.json` | 20 MB each | Same as the base model's tokenizer |
| `huan_luyen/qwen9b/sql_gen_train.jsonl` | 94 MB | 9B training data (3,040 samples) |
| `huan_luyen/qwen9b/mix_train.jsonl` | 69 MB | 9B round 2 training data (2,200 samples) |
| `huan_luyen/qwen9b/sql_pv2.jsonl` | 40 MB | SQL data source (1,303 samples) |
| `huan_luyen/qwen9b/thu_train.jsonl` | 27 MB | 9B round 1 training data (800 samples) |
| `data/norm_cache_qwen_norm_4b_v2.jsonl` | — | Runtime cache of questions, not code |
| `models/` (in the image) | ~28 GB | Merged model weights (Qwen3.5-9B + Qwen3.5-4B) |

The full SHA-256 checksums are in `huan_luyen/data_manifest.json`.
