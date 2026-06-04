import argparse
import json
import sys
import traceback
from pathlib import Path

import torch
import yaml
from datasets import Dataset
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
    Trainer,
    TrainingArguments,
    set_seed,
)


ROOT = Path(__file__).resolve().parents[1]


def load_jsonl(path):
    with Path(path).open("r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def tokenize_rows(rows, tokenizer, max_seq_length):
    def encode(row):
        encoded = tokenizer(
            row["text"],
            truncation=True,
            max_length=max_seq_length,
            padding=False,
        )
        encoded["labels"] = list(encoded["input_ids"])
        return encoded

    return Dataset.from_list(rows).map(encode, remove_columns=list(rows[0].keys()))


class CausalCollator:
    def __init__(self, tokenizer):
        self.tokenizer = tokenizer

    def __call__(self, features):
        labels = [feature.pop("labels") for feature in features]
        batch = self.tokenizer.pad(features, padding=True, return_tensors="pt")
        max_len = batch["input_ids"].shape[1]
        padded_labels = []
        for label in labels:
            padded = label + [-100] * (max_len - len(label))
            padded_labels.append(padded)
        batch["labels"] = torch.tensor(padded_labels, dtype=torch.long)
        return batch


def oom_help():
    return (
        "CUDA OOM fallback order:\n"
        "1. close GPU-heavy apps, then retry\n"
        "2. reduce max_seq_length to 512\n"
        "3. reduce LoRA rank to 4\n"
        "4. keep --disable_eval\n"
        "5. use Qwen/Qwen2.5-Coder-1.5B-Instruct\n"
        "6. keep batch size = 1"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(ROOT / "configs" / "windows_6gb_qwen3b_qlora.yaml"))
    parser.add_argument("--train_file", required=True)
    parser.add_argument("--dev_file")
    parser.add_argument("--output_dir", required=True)
    parser.add_argument("--max_steps", type=int)
    parser.add_argument("--resume_from_checkpoint")
    parser.add_argument("--disable_eval", action="store_true")
    args = parser.parse_args()

    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if not args.max_steps and not (output_dir / "SANITY_PASSED").exists():
        raise SystemExit(
            "Refusing full training because the 20-step sanity run has not passed yet. "
            "Run this script first with --max_steps 20 using the same --output_dir."
        )

    set_seed(int(cfg.get("seed", 3407)))
    tokenizer = AutoTokenizer.from_pretrained(cfg["model_name"], trust_remote_code=True, use_fast=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    use_eval = bool(args.dev_file and not args.disable_eval and not cfg.get("disable_eval_recommended"))
    train_rows = load_jsonl(args.train_file)
    dev_rows = load_jsonl(args.dev_file) if use_eval else None
    train_ds = tokenize_rows(train_rows, tokenizer, int(cfg["max_seq_length"]))
    dev_ds = tokenize_rows(dev_rows, tokenizer, int(cfg["max_seq_length"])) if dev_rows else None

    quant_config = BitsAndBytesConfig(
        load_in_4bit=bool(cfg.get("load_in_4bit", True)),
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=torch.float16,
    )
    print(f"Loading 4-bit model: {cfg['model_name']}")
    try:
        model = AutoModelForCausalLM.from_pretrained(
            cfg["model_name"],
            quantization_config=quant_config,
            device_map={"": 0},
            trust_remote_code=True,
            torch_dtype=torch.float16,
        )
        model.config.use_cache = False
        model.gradient_checkpointing_enable()
        model = prepare_model_for_kbit_training(model)
        lora_config = LoraConfig(
            r=int(cfg["lora_r"]),
            lora_alpha=int(cfg["lora_alpha"]),
            lora_dropout=float(cfg["lora_dropout"]),
            bias="none",
            task_type="CAUSAL_LM",
            target_modules=list(cfg["target_modules"]),
        )
        model = get_peft_model(model, lora_config)
        model.print_trainable_parameters()

        training_args = TrainingArguments(
            output_dir=str(output_dir / "checkpoints"),
            per_device_train_batch_size=int(cfg["per_device_train_batch_size"]),
            gradient_accumulation_steps=int(cfg["gradient_accumulation_steps"]),
            num_train_epochs=float(cfg["num_train_epochs"]),
            max_steps=args.max_steps if args.max_steps else -1,
            learning_rate=float(cfg["learning_rate"]),
            warmup_ratio=float(cfg["warmup_ratio"]),
            weight_decay=float(cfg["weight_decay"]),
            lr_scheduler_type=cfg["lr_scheduler_type"],
            optim=cfg["optim"],
            logging_steps=int(cfg["logging_steps"]),
            save_steps=int(cfg["save_steps"]),
            eval_steps=int(cfg["eval_steps"]),
            save_total_limit=int(cfg["save_total_limit"]),
            eval_strategy="steps" if use_eval else "no",
            fp16=True,
            bf16=False,
            max_grad_norm=float(cfg["max_grad_norm"]),
            report_to=[],
            seed=int(cfg["seed"]),
        )
        trainer = Trainer(
            model=model,
            args=training_args,
            train_dataset=train_ds,
            eval_dataset=dev_ds,
            data_collator=CausalCollator(tokenizer),
        )
        result = trainer.train(resume_from_checkpoint=args.resume_from_checkpoint)
        model.save_pretrained(str(output_dir))
        tokenizer.save_pretrained(str(output_dir))
        (output_dir / "run_config.yaml").write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True), encoding="utf-8")
        (output_dir / "train_metrics.json").write_text(json.dumps(result.metrics, indent=2), encoding="utf-8")
        if args.max_steps:
            (output_dir / "SANITY_PASSED").write_text("QLoRA sanity training completed.\n", encoding="utf-8")
        print(f"Saved adapter/tokenizer: {output_dir}")
    except RuntimeError as exc:
        if "out of memory" in str(exc).lower() or "cuda" in str(exc).lower():
            print(oom_help(), file=sys.stderr)
        traceback.print_exc()
        raise


if __name__ == "__main__":
    main()
