"""Huấn luyện LoRA Qwen/Qwen3.5-4B làm sạch câu hỏi (dùng trực tiếp transformers.Trainer + peft có sẵn trong image).

    python3 train_4b.py --model Qwen/Qwen3.5-4B --train full_gold_norm_v2_chatml_cleaned.jsonl --val val_norm_v2.jsonl --out adapter_v2
"""
import argparse
import json
import torch
from peft import LoraConfig, get_peft_model
from transformers import AutoModelForCausalLM, AutoTokenizer, DataCollatorForSeq2Seq, Trainer, TrainingArguments


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="Qwen/Qwen3.5-4B")
    ap.add_argument("--train", default="full_gold_norm_v2_chatml_cleaned.jsonl")
    ap.add_argument("--val", default="val_norm_v2.jsonl")
    ap.add_argument("--out", default="adapter_v2")
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--max-seq-len", type=int, default=768)
    ap.add_argument("--seed", type=int, default=2026)
    a = ap.parse_args()

    tok = AutoTokenizer.from_pretrained(a.model)
    model = AutoModelForCausalLM.from_pretrained(a.model, torch_dtype=torch.bfloat16, device_map="auto")
    lora_cfg = LoraConfig(
        r=16,
        lora_alpha=32,
        lora_dropout=0.0,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    )
    model = get_peft_model(model, lora_cfg)

    def load_split(path):
        items = []
        for line in open(path, encoding="utf-8"):
            if line.strip():
                r = json.loads(line)
                txt = tok.apply_chat_template(r["messages"], tokenize=False, add_generation_prompt=False, enable_thinking=False)
                ids = tok(txt, truncation=True, max_length=a.max_seq_len)["input_ids"]
                items.append({"input_ids": ids, "labels": list(ids)})
        return items

    train_ds = load_split(a.train)
    val_ds = load_split(a.val)
    args = TrainingArguments(
        output_dir=a.out + "_ckpt",
        per_device_train_batch_size=16,
        gradient_accumulation_steps=2,
        learning_rate=a.lr,
        num_train_epochs=a.epochs,
        lr_scheduler_type="cosine",
        warmup_ratio=0.05,
        bf16=True,
        logging_steps=20,
        seed=a.seed,
        report_to="none",
    )
    trainer = Trainer(model=model, args=args, train_dataset=train_ds, eval_dataset=val_ds, data_collator=DataCollatorForSeq2Seq(tok))
    trainer.train()
    model.save_pretrained(a.out)
    tok.save_pretrained(a.out)
    print("ĐÃ LƯU ADAPTER:", a.out)


if __name__ == "__main__":
    main()
