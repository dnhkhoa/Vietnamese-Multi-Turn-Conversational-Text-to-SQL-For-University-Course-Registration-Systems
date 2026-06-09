import json
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
ENV_REPORT = ROOT / "outputs" / "logs" / "env_report.json"
AUTO_PROFILE = ROOT / "configs" / "auto_profile.yaml"


BASE = {
    "load_in_4bit": True,
    "lora_alpha": 32,
    "lora_dropout": 0,
    "target_modules": ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    "per_device_train_batch_size": 1,
    "num_train_epochs": 1,
    "learning_rate": 2e-4,
    "warmup_ratio": 0.03,
    "weight_decay": 0.0,
    "lr_scheduler_type": "cosine",
    "optim": "adamw_8bit",
    "logging_steps": 10,
    "save_steps": 100,
    "eval_steps": 100,
    "save_total_limit": 2,
    "seed": 3407,
    "packing": False,
    "eval_strategy": "steps",
    "max_grad_norm": 1.0,
}


def profile_from_status(status):
    if status == "OK_FOR_7B":
        return {
            "profile_name": "high_vram_qwen7b",
            "model_name": "unsloth/Qwen2.5-Coder-7B-Instruct-bnb-4bit",
            "fallback_model_name": "unsloth/Qwen2.5-Coder-3B-Instruct-bnb-4bit",
            "max_seq_length": 2048,
            "lora_r": 16,
            "gradient_accumulation_steps": 8,
            "disable_eval_recommended": False,
        }
    if status == "OK_FOR_3B":
        return {
            "profile_name": "medium_vram_qwen3b",
            "model_name": "unsloth/Qwen2.5-Coder-3B-Instruct-bnb-4bit",
            "fallback_model_name": "unsloth/Qwen2.5-Coder-1.5B-Instruct-bnb-4bit",
            "max_seq_length": 1536,
            "lora_r": 16,
            "gradient_accumulation_steps": 8,
            "disable_eval_recommended": False,
        }
    if status == "OK_FOR_1_5B":
        return {
            "profile_name": "low_vram_qwen15b",
            "model_name": "unsloth/Qwen2.5-Coder-1.5B-Instruct-bnb-4bit",
            "fallback_model_name": "Qwen/Qwen2.5-Coder-1.5B-Instruct",
            "max_seq_length": 1024,
            "lora_r": 8,
            "gradient_accumulation_steps": 16,
            "disable_eval_recommended": False,
        }
    if status == "LOW_VRAM_ONLY":
        return {
            "profile_name": "very_low_vram_qwen05b",
            "model_name": "Qwen/Qwen2.5-Coder-0.5B-Instruct",
            "fallback_model_name": "Qwen/Qwen2.5-Coder-1.5B-Instruct",
            "max_seq_length": 512,
            "lora_r": 8,
            "gradient_accumulation_steps": 32,
            "disable_eval_recommended": True,
        }
    raise RuntimeError("NO_CUDA: CUDA is unavailable. Do not run training on this machine yet.")


def main():
    if not ENV_REPORT.exists():
        raise SystemExit(f"Missing {ENV_REPORT}. Run scripts/check_env.py first.")
    report = json.loads(ENV_REPORT.read_text(encoding="utf-8"))
    rec = report.get("recommendation", {})
    status = rec.get("status", "NO_CUDA")
    chosen = BASE.copy()
    chosen.update(profile_from_status(status))
    chosen["environment_status"] = status
    chosen["selection_reason"] = rec.get("reason", "")
    chosen["bf16_supported"] = report.get("bf16_supported", False)
    chosen["selected_gpu"] = (report.get("gpus") or [{}])[0]
    AUTO_PROFILE.write_text(yaml.safe_dump(chosen, sort_keys=False, allow_unicode=True), encoding="utf-8")
    print(f"Chosen profile: {chosen['profile_name']}")
    print(f"Model: {chosen['model_name']}")
    print(f"Why: {chosen['selection_reason']}")
    print(f"Saved: {AUTO_PROFILE}")


if __name__ == "__main__":
    main()
