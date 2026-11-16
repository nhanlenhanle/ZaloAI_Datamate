"""Gộp adapter LoRA vào model gốc bằng tay (không cần peft / transformers): W += (alpha / r) * B @ A cho mỗi ma trận có LoRA.
python gop_lora.py <model gốc> <adapter> <thư mục ra>"""
import glob
import json
import os
import shutil
import sys

import torch
from safetensors.torch import load_file, save_file

base, lora, out = sys.argv[1:4]
cfg = json.load(open(f"{lora}/adapter_config.json"))
scale = cfg["lora_alpha"] / cfg["r"]
pairs = {}
for k, v in load_file(f"{lora}/adapter_model.safetensors").items():
    n = k[len("base_model.model."):] if k.startswith("base_model.model.") else k
    if ".lora_A." in n:
        pairs.setdefault(n.replace(".lora_A.weight", ".weight"), [None, None])[0] = v
    elif ".lora_B." in n:
        pairs.setdefault(n.replace(".lora_B.weight", ".weight"), [None, None])[1] = v
os.makedirs(out, exist_ok=True)
used = set()
def _ten(name):
    # adapter học trên bản chỉ có phần chữ (model.layers.X) còn checkpoint đầy đủ ghi model.language_model.layers.X
    if name in pairs:
        return name
    alt = name.replace("model.language_model.", "model.", 1)
    return alt if alt in pairs else None
for f in sorted(glob.glob(f"{base}/*.safetensors")):
    w = load_file(f)
    for name in list(w):
        key = _ten(name)
        if key is not None:
            a, b = pairs[key]
            name_used = key
            w[name] = (w[name].float() + scale * (b.float() @ a.float())).to(w[name].dtype)
            used.add(name_used)
    save_file(w, os.path.join(out, os.path.basename(f)), metadata={"format": "pt"})
for f in os.listdir(base):
    p = os.path.join(base, f)
    if os.path.isfile(p) and not f.endswith(".safetensors"):
        shutil.copy(p, out)
thieu = sorted(set(pairs) - used)
print(f"hệ số {scale} | gộp {len(used)} / {len(pairs)} ma trận | không tìm thấy {len(thieu)}: {thieu[:3]}")
if thieu:
    sys.exit(1)
open(os.path.join(out, ".gop_ok"), "w").write("ok")
print("XONG", out)
