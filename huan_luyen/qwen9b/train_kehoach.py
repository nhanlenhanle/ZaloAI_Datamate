"""Fine-tune tầng kế hoạch (QLoRA 4-bit, compute bf16) trên 1 GPU 24 GB.
python train_kehoach.py --model <thư mục Qwen3.5-9B> --train thu_train.jsonl --val thu_val.jsonl --out lora [--max-steps N] [--smoke]
--smoke: nạp model, chạy 3 bước, in thời gian một bước và bộ nhớ, ước thời gian cả lượt, rồi thoát."""
import argparse
import json
import os
import time

import torch
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
from transformers import (AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig, DataCollatorForSeq2Seq, Trainer,
                          TrainerCallback, TrainingArguments)

ap = argparse.ArgumentParser()
ap.add_argument("--model", required=True)
ap.add_argument("--train", required=True)
ap.add_argument("--val")
ap.add_argument("--out", required=True)
ap.add_argument("--max-len", type=int, default=12288)
ap.add_argument("--epochs", type=float, default=1)
ap.add_argument("--max-steps", type=int, default=-1)
ap.add_argument("--accum", type=int, default=8)
ap.add_argument("--lr", type=float, default=1e-4)
ap.add_argument("--smoke", action="store_true")
ap.add_argument("--init-lora", default=None, help="adapter để học tiếp")
a = ap.parse_args()

tok = AutoTokenizer.from_pretrained(a.model)
END = "<|im_end|>" if "<|im_end|>" in tok.get_vocab() else tok.eos_token


def encode(ex):
    msgs = ex["messages"]
    prompt = tok.apply_chat_template(msgs[:-1], tokenize=False, add_generation_prompt=True, enable_thinking=False)
    full = prompt + msgs[-1]["content"] + END
    p = tok(prompt, add_special_tokens=False)["input_ids"]
    f = tok(full, add_special_tokens=False)["input_ids"]
    assert f[:len(p)] == p, "prompt không phải tiền tố của bài đầy đủ"
    if len(f) > a.max_len:
        return None
    return {"input_ids": f, "labels": [-100] * len(p) + f[len(p):]}


train = [x for x in (encode(json.loads(l)) for l in open(a.train, encoding="utf-8")) if x]
lens = sorted(len(x["input_ids"]) for x in train)
print(f"{len(train)} mẫu | token trung vị {lens[len(lens) // 2]} max {lens[-1]} tổng {sum(lens)}", flush=True)

bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.bfloat16,
                         bnb_4bit_use_double_quant=True)
t0 = time.time()
try:
    model = AutoModelForCausalLM.from_pretrained(a.model, quantization_config=bnb, dtype=torch.bfloat16, device_map={"": 0})
except Exception as e:      # bản đa phương thức (Qwen3_5ForConditionalGeneration): nạp cả lớp ảnh, LoRA chỉ phần ngôn ngữ
    print("AutoModelForCausalLM lỗi:", e, flush=True)
    from transformers import AutoModelForImageTextToText
    model = AutoModelForImageTextToText.from_pretrained(a.model, quantization_config=bnb, dtype=torch.bfloat16,
                                                        device_map={"": 0})
print(f"nạp model {time.time() - t0:.0f}s | {type(model).__name__} | {torch.cuda.memory_allocated() / 2**30:.1f} GB", flush=True)
model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
if a.init_lora:            # học tiếp từ adapter đã có (vd lượt 800 mẫu JSON) thay vì từ đầu
    from peft import PeftModel
    model = PeftModel.from_pretrained(model, a.init_lora, is_trainable=True)
else:
    model = get_peft_model(model, LoraConfig(r=16, lora_alpha=32, lora_dropout=0.05, task_type="CAUSAL_LM",
                                             target_modules="all-linear", exclude_modules=r".*(visual|vision|mtp|lm_head).*"))
model.print_trainable_parameters()


class Gio(TrainerCallback):
    def __init__(self):
        self.t = None

    def on_step_begin(self, args, state, control, **kw):
        self.t = time.time()

    def on_step_end(self, args, state, control, **kw):
        dt = time.time() - self.t
        tong = state.max_steps
        print(f"bước {state.global_step}/{tong}: {dt:.0f}s | còn ~{dt * (tong - state.global_step) / 3600:.1f} giờ | "
              f"bộ nhớ đỉnh {torch.cuda.max_memory_allocated() / 2**30:.1f} GB", flush=True)
        if a.smoke and state.global_step >= 3:
            control.should_training_stop = True
        torch.cuda.empty_cache()        # trả bộ nhớ đệm sau mỗi bước: bớt hết bộ nhớ do phân mảnh (đỉnh ~22 / 24 GB)


args = TrainingArguments(
    output_dir=os.path.join(a.out, "ckpt"), per_device_train_batch_size=1, gradient_accumulation_steps=a.accum,
    num_train_epochs=a.epochs, max_steps=a.max_steps, learning_rate=a.lr, lr_scheduler_type="cosine", warmup_steps=5,
    logging_steps=1, save_strategy="steps", save_steps=10, save_total_limit=2, bf16=True, report_to="none",
    gradient_checkpointing=True, gradient_checkpointing_kwargs={"use_reentrant": False}, optim="paged_adamw_8bit",
    dataloader_num_workers=0)
class TraLoiCuoi(Trainer):
    """Phần trả lời nằm ở cuối chuỗi: chỉ tính logits cho đoạn đó (logits_to_keep), không cho cả ~10k vị trí x 248k từ
    vựng (~9 GB). Loss = cross-entropy trên các token trả lời."""
    def compute_loss(self, model, inputs, return_outputs=False, num_items_in_batch=None):
        labels = inputs.pop("labels")
        n = int((labels[0] != -100).sum())
        out = model(input_ids=inputs["input_ids"], attention_mask=inputs.get("attention_mask"), logits_to_keep=n + 1)
        logits = out.logits[:, :-1, :].float()
        tgt = labels[:, -n:]
        loss = torch.nn.functional.cross_entropy(logits.reshape(-1, logits.size(-1)), tgt.reshape(-1), ignore_index=-100)
        return (loss, out) if return_outputs else loss

    bo_qua = 0

    def training_step(self, model, inputs, num_items_in_batch=None):
        """Mẫu làm hết bộ nhớ GPU (chuỗi dài nhất): bỏ qua mẫu đó, giải phóng bộ nhớ, đi tiếp (đếm số mẫu bỏ)."""
        try:
            return super().training_step(model, inputs, num_items_in_batch)
        except (torch.OutOfMemoryError, RuntimeError) as e:
            if "out of memory" not in str(e):
                raise
            TraLoiCuoi.bo_qua += 1
            print(f"bỏ qua 1 mẫu ({len(inputs['input_ids'][0])} token) vì hết bộ nhớ; đã bỏ {TraLoiCuoi.bo_qua}", flush=True)
            model.zero_grad(set_to_none=True)
            torch.cuda.empty_cache()
            try:                        # hết bộ nhớ giữa kernel có thể làm hỏng trạng thái GPU: hỏng thì thoát,
                torch.cuda.synchronize()    # job tự chạy lại từ checkpoint gần nhất (train_mix.sh)
            except Exception as e2:     # noqa: BLE001
                print("GPU hỏng sau khi hết bộ nhớ, thoát để chạy lại từ checkpoint:", e2, flush=True)
                os._exit(3)
            return torch.zeros((), device=inputs["input_ids"].device)


trainer = TraLoiCuoi(model=model, args=args, train_dataset=train, callbacks=[Gio()],
                  data_collator=DataCollatorForSeq2Seq(tok, padding=True, label_pad_token_id=-100))
ckpts = sorted(d for d in os.listdir(args.output_dir) if d.startswith("checkpoint-")) if os.path.isdir(args.output_dir) else []
trainer.train(resume_from_checkpoint=bool(ckpts) and not a.smoke)
if a.smoke:
    raise SystemExit(0)
model.save_pretrained(os.path.join(a.out, "lora"))
tok.save_pretrained(os.path.join(a.out, "lora"))
print("đã lưu", os.path.join(a.out, "lora"), flush=True)

if a.val:       # thử nhanh: kế hoạch khớp nguyên văn đáp án, so với model gốc (tắt adapter)
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
            out = model.generate(**ids, max_new_tokens=400, do_sample=False)
        return tok.decode(out[0][ids["input_ids"].shape[1]:], skip_special_tokens=True)
    model.eval()
    khop = {"lora": 0, "goc": 0}
    vals = [json.loads(l) for l in open(a.val, encoding="utf-8")][:20]
    for i, ex in enumerate(vals):
        gold = norm(ex["messages"][-1]["content"])
        x = norm(gen(ex)) == gold
        with model.disable_adapter():
            y = norm(gen(ex)) == gold
        khop["lora"] += x
        khop["goc"] += y
        print(i, "lora", x, "| gốc", y, flush=True)
    print("khớp nguyên văn kế hoạch /", len(vals), ":", khop, flush=True)
