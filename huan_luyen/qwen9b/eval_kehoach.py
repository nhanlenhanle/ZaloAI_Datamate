"""So model gốc với model + adapter LoRA trên câu kiểm (shop không có trong tập huấn luyện): kế hoạch khớp nguyên văn đáp án?
python eval_kehoach.py --model <Qwen3.5-9B> --lora <adapter> --val thu_val.jsonl [--n 40]"""
import argparse
import json
import time

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

ap = argparse.ArgumentParser()
ap.add_argument("--model", required=True)
ap.add_argument("--lora", required=True)
ap.add_argument("--val", required=True)
ap.add_argument("--n", type=int, default=40)
ap.add_argument("--out", default=None)
a = ap.parse_args()
tok = AutoTokenizer.from_pretrained(a.model)
bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.bfloat16,
                         bnb_4bit_use_double_quant=True)
model = AutoModelForCausalLM.from_pretrained(a.model, quantization_config=bnb, dtype=torch.bfloat16, device_map={"": 0})
model = PeftModel.from_pretrained(model, a.lora)
model.eval()


def norm(t):
    s = t.find("{")
    try:
        return json.dumps(json.JSONDecoder().raw_decode(t, s)[0], sort_keys=True, ensure_ascii=False) if s >= 0 else None
    except Exception:
        return None


def gen(ex):
    prompt = tok.apply_chat_template(ex["messages"][:-1], tokenize=False, add_generation_prompt=True, enable_thinking=False)
    ids = tok(prompt, return_tensors="pt").to("cuda")
    with torch.no_grad():
        out = model.generate(**ids, max_new_tokens=400, do_sample=False, logits_to_keep=1)
    return tok.decode(out[0][ids["input_ids"].shape[1]:], skip_special_tokens=True)


vals = [json.loads(l) for l in open(a.val, encoding="utf-8")][:a.n]
fo = open(a.out, "w", encoding="utf-8") if a.out else None
khop = {"lora": 0, "goc": 0, "ca_hai": 0, "chi_lora": 0, "chi_goc": 0}
for i, ex in enumerate(vals):
    t0 = time.time()
    gold = norm(ex["messages"][-1]["content"])
    tl = gen(ex)
    x = norm(tl) == gold
    with model.disable_adapter():
        tg = gen(ex)
    y = norm(tg) == gold
    if fo:
        fo.write(json.dumps({"id": ex.get("id"), "shop": ex.get("shop"), "lora": tl, "goc": tg}, ensure_ascii=False) + chr(10))
        fo.flush()
    khop["lora"] += x
    khop["goc"] += y
    khop["ca_hai"] += x and y
    khop["chi_lora"] += x and not y
    khop["chi_goc"] += y and not x
    print(f"{i} lora {x} | gốc {y} | {time.time() - t0:.0f}s", flush=True)
    torch.cuda.empty_cache()
print(f"khớp nguyên văn kế hoạch / {len(vals)}: {khop}", flush=True)
