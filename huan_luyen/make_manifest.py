"""Generate /code/training_code/data_manifest.json with local paths, sizes, SHA-256 checksums,
dataset counts/splits, and base model public URLs + fixed revisions + required file SHA-256 checksums."""
import hashlib
import json
from pathlib import Path


def main():
    root = Path(__file__).resolve().parent
    files_info = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.name != "data_manifest.json" and "__pycache__" not in p.parts:
            rel = p.relative_to(root).as_posix()
            h = hashlib.sha256(p.read_bytes()).hexdigest()
            src_name = "synthetic_bo_sinh" if any(k in rel for k in ("sql_", "rbd_", "thu_", "mix_")) else "btc_train_and_synthetic"
            entry = {
                "path": f"/code/training_code/{rel}",
                "source": src_name,
                "version": "1.0",
                "size_bytes": p.stat().st_size,
                "sha256": h,
            }
            if p.suffix == ".jsonl":
                with open(p, encoding="utf-8") as fh:
                    entry["num_samples"] = sum(1 for l in fh if l.strip())
                entry["split"] = "validation" if "val" in rel else "train"
            files_info.append(entry)

    assets_dir = root.parent / "assets"
    if assets_dir.is_dir():
        for p in sorted(assets_dir.rglob("*")):
            if p.is_file():
                rel = p.relative_to(assets_dir).as_posix()
                entry = {
                    "path": f"/app/assets/{rel}",
                    "source": "btc_train_few_shot_assets",
                    "version": "1.0",
                    "split": "train_few_shot",
                    "size_bytes": p.stat().st_size,
                    "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                }
                if p.suffix == ".jsonl":
                    with open(p, encoding="utf-8") as fh:
                        entry["num_samples"] = sum(1 for l in fh if l.strip())
                files_info.append(entry)

    manifest = {
        "team_name": "fall to fly",
        "base_models": [
            {
                "name": "Qwen/Qwen3.5-9B",
                "public_url": "https://huggingface.co/Qwen/Qwen3.5-9B",
                "revision": "c202236235762e1c871ad0ccb60c8ee5ba337b9a",
                "release_date": "2026-02-27",
                "license": "Apache-2.0",
                "parameters": 9653000000,
                "packaged_merged_path": "/models/qwen",
                "adapter_path": "/code/training_code/qwen9b/adapter_mix",
                "required_files": [
                    {"filename": "model.safetensors-00001-of-00004.safetensors", "size_bytes": 5276436216, "sha256": "db6f444b43d318c92f360a13a25561a6a65b10c0631b8ed305a426dbaa6c380e"},
                    {"filename": "model.safetensors-00002-of-00004.safetensors", "size_bytes": 5335161512, "sha256": "31c7d7e2dd5d207840b31cc59083c8f4c4718959149e0358c0364052bb9a0330"},
                    {"filename": "model.safetensors-00003-of-00004.safetensors", "size_bytes": 5368717440, "sha256": "7ec36ba3a4176a44c3c0876ad80c56a2f70c84bf008d82e9501df642f17dadec"},
                    {"filename": "model.safetensors-00004-of-00004.safetensors", "size_bytes": 3325995712, "sha256": "b62b0c4cd7e44edee103ee8f4fe225f246d5e768e07bfd5f25b63a8aa1fdd0c6"},
                    {"filename": "tokenizer.json", "size_bytes": 12807982, "sha256": "5f9e4d4901a92b997e463c1f46055088b6cca5ca61a6522d1b9f64c4bb81cb42"}
                ]
            },
            {
                "name": "Qwen/Qwen3.5-4B",
                "public_url": "https://huggingface.co/Qwen/Qwen3.5-4B",
                "revision": "851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a",
                "release_date": "2026-02-27",
                "license": "Apache-2.0",
                "parameters": 4660000000,
                "packaged_merged_path": "/models/qwen_norm4b",
                "adapter_path": "/code/training_code/qwen4b_norm/adapter_v2",
                "required_files": [
                    {"filename": "model.safetensors-00001-of-00002.safetensors", "size_bytes": 5329398688, "sha256": "26a93f066e1916adb13453dae5a0c707c0fbc71299ed98779571a907b8e74c61"},
                    {"filename": "model.safetensors-00002-of-00002.safetensors", "size_bytes": 3990429408, "sha256": "cb544bd9bfae93dc59b0f22b292f5933573854a7f9b97835c67060d7d910e188"},
                    {"filename": "tokenizer.json", "size_bytes": 12807982, "sha256": "5f9e4d4901a92b997e463c1f46055088b6cca5ca61a6522d1b9f64c4bb81cb42"}
                ]
            }
        ],
        "total_inference_parameters": 14313000000,
        "datasets_summary": {
            "qwen9b_stage1_train": {"path": "/code/training_code/qwen9b/thu_train.jsonl", "source": "synthetic_bo_sinh", "version": "1.0", "samples": 800, "split": "train"},
            "qwen9b_stage1_val": {"path": "/code/training_code/qwen9b/thu_val.jsonl", "source": "synthetic_bo_sinh", "version": "1.0", "samples": 40, "split": "validation"},
            "qwen9b_stage2_mix_train": {"path": "/code/training_code/qwen9b/mix_train.jsonl", "source": "synthetic_bo_sinh+rule_drift", "version": "1.0", "samples": 2200, "split": "train"},
            "qwen9b_sql_gen_train": {"path": "/code/training_code/qwen9b/sql_gen_train.jsonl", "source": "synthetic_bo_sinh", "version": "1.0", "split": "train"},
            "qwen9b_sql_pv2": {"path": "/code/training_code/qwen9b/sql_pv2.jsonl", "source": "synthetic_bo_sinh", "version": "1.0", "split": "train"},
            "qwen9b_rbd_sql_A": {"path": "/code/training_code/qwen9b/rbd_sql_A.jsonl", "source": "synthetic_rule_drift", "version": "1.0", "split": "train"},
            "qwen9b_rbd_sql_C": {"path": "/code/training_code/qwen9b/rbd_sql_C.jsonl", "source": "synthetic_rule_drift", "version": "1.0", "split": "train"},
            "qwen4b_norm_train": {"path": "/code/training_code/qwen4b_norm/full_gold_norm_v2_chatml_cleaned.jsonl", "source": "btc_train+bo_tu_sinh_v2", "version": "2.0", "samples": 4669, "split": "train"},
            "qwen4b_norm_val": {"path": "/code/training_code/qwen4b_norm/val_norm_v2.jsonl", "source": "btc_train+bo_tu_sinh_v2", "version": "2.0", "samples": 100, "split": "validation"}
        },
        "files": files_info,
    }
    out_file = root / "data_manifest.json"
    out_file.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Generated {out_file} with {len(files_info)} files.")


if __name__ == "__main__":
    main()
