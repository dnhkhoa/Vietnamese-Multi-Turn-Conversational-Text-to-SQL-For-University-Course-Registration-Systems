import argparse
import json
import os
import shutil
import sys
import traceback
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def load_jsonl(path):
    rows = []
    with Path(path).open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def training_args_cls():
    try:
        from trl import SFTConfig

        return SFTConfig
    except Exception:
        from transformers import TrainingArguments

        return TrainingArguments


def oom_help():
    return (
        "CUDA OOM fallback order:\n"
        "1. reduce max_seq_length\n"
        "2. reduce LoRA rank\n"
        "3. disable eval\n"
        "4. use smaller model\n"
        "5. increase gradient accumulation\n"
        "6. keep batch size = 1"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(ROOT / "configs" / "auto_profile.yaml"))
    parser.add_argument("--train_file", required=True)
    parser.add_argument("--dev_file")
    parser.add_argument("--output_dir", required=True)
    parser.add_argument("--max_steps", type=int)
    parser.add_argument("--resume_from_checkpoint")
    parser.add_argument("--disable_eval", action="store_true")
    args = parser.parse_args()

    try:
        import torch
        from datasets import Dataset
        from trl import SFTTrainer
        from unsloth import FastLanguageModel
    except Exception as exc:
        raise SystemExit(f"Missing training dependency: {exc}\nInstall with: pip install -r requirements.txt")

    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    if not cfg.get("model_name"):
        raise SystemExit("configs/auto_profile.yaml is not selected. Run check_env.py and choose_training_profile.py first.")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if not args.max_steps and not (output_dir / "SANITY_PASSED").exists():
        raise SystemExit(
            "Refusing full training because the 20-step sanity run has not passed yet. "
            "Run this script first with --max_steps 20 using the same --output_dir."
        )
    (output_dir / "run_config.yaml").write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True), encoding="utf-8")

    train_ds = Dataset.from_list(load_jsonl(args.train_file))
    dev_ds = None
    use_eval = bool(args.dev_file and not args.disable_eval and not cfg.get("disable_eval_recommended"))
    if use_eval:
        dev_ds = Dataset.from_list(load_jsonl(args.dev_file))

    bf16 = bool(torch.cuda.is_available() and torch.cuda.is_bf16_supported())
    fp16 = bool(torch.cuda.is_available() and not bf16)
    print(f"Loading model: {cfg['model_name']}")
    print(f"bf16={bf16} fp16={fp16} eval={use_eval}")

    try:
        model, tokenizer = FastLanguageModel.from_pretrained(
            model_name=cfg["model_name"],
            max_seq_length=int(cfg["max_seq_length"]),
            dtype=None,
            load_in_4bit=bool(cfg["load_in_4bit"]),
        )
        model = FastLanguageModel.get_peft_model(
            model,
            r=int(cfg["lora_r"]),
            target_modules=list(cfg["target_modules"]),
            lora_alpha=int(cfg["lora_alpha"]),
            lora_dropout=float(cfg["lora_dropout"]),
            bias="none",
            use_gradient_checkpointing="unsloth",
            random_state=int(cfg.get("seed", 3407)),
        )

        ArgsClass = training_args_cls()
        kwargs = {
            "output_dir": str(output_dir / "checkpoints"),
            "per_device_train_batch_size": int(cfg["per_device_train_batch_size"]),
            "gradient_accumulation_steps": int(cfg["gradient_accumulation_steps"]),
            "num_train_epochs": float(cfg["num_train_epochs"]),
            "learning_rate": float(cfg["learning_rate"]),
            "warmup_ratio": float(cfg["warmup_ratio"]),
            "weight_decay": float(cfg["weight_decay"]),
            "lr_scheduler_type": cfg["lr_scheduler_type"],
            "optim": cfg["optim"],
            "logging_steps": int(cfg["logging_steps"]),
            "save_steps": int(cfg["save_steps"]),
            "eval_steps": int(cfg["eval_steps"]),
            "save_total_limit": int(cfg["save_total_limit"]),
            "seed": int(cfg["seed"]),
            "bf16": bf16,
            "fp16": fp16,
            "max_grad_norm": float(cfg["max_grad_norm"]),
            "report_to": [],
        }
        if args.max_steps:
            kwargs["max_steps"] = args.max_steps
        if use_eval:
            kwargs["eval_strategy"] = cfg.get("eval_strategy", "steps")
            kwargs["load_best_model_at_end"] = True
            kwargs["metric_for_best_model"] = "eval_loss"
            kwargs["greater_is_better"] = False
        else:
            kwargs["eval_strategy"] = "no"

        training_args = ArgsClass(**kwargs)
        trainer = SFTTrainer(
            model=model,
            tokenizer=tokenizer,
            train_dataset=train_ds,
            eval_dataset=dev_ds,
            dataset_text_field="text",
            max_seq_length=int(cfg["max_seq_length"]),
            packing=bool(cfg["packing"]),
            args=training_args,
        )
        result = trainer.train(resume_from_checkpoint=args.resume_from_checkpoint)
        trainer.save_model(str(output_dir))
        tokenizer.save_pretrained(str(output_dir))
        metrics = result.metrics if hasattr(result, "metrics") else {}
        (output_dir / "train_metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
        sanity_marker = output_dir / "SANITY_PASSED"
        if args.max_steps:
            sanity_marker.write_text("20-step sanity training completed.\n", encoding="utf-8")
        print(f"Saved adapter/tokenizer: {output_dir}")
        print(json.dumps(metrics, indent=2))
    except RuntimeError as exc:
        if "out of memory" in str(exc).lower() or "cuda" in str(exc).lower():
            print(oom_help(), file=sys.stderr)
        traceback.print_exc()
        raise


if __name__ == "__main__":
    main()
