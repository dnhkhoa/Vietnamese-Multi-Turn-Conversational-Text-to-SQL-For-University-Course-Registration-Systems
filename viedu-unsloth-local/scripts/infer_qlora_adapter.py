import argparse
import json
import re
import time
from pathlib import Path

import torch
import yaml
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig


ROOT = Path(__file__).resolve().parents[1]


def load_jsonl(path):
    with Path(path).open("r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_jsonl(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def strip_fences(text):
    text = text.strip()
    text = re.sub(r"^```(?:sql)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def prompt_from_row(row):
    messages = row["messages"][:2]
    return (
        f"<|im_start|>system\n{messages[0]['content']}<|im_end|>\n"
        f"<|im_start|>user\n{messages[1]['content']}<|im_end|>\n"
        f"<|im_start|>assistant\n"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--adapter_dir", required=True)
    parser.add_argument("--test_file", required=True)
    parser.add_argument("--output_file", default="outputs/predictions/pred_test.jsonl")
    parser.add_argument("--base_model", default="Qwen/Qwen2.5-Coder-3B-Instruct")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    adapter_dir = Path(args.adapter_dir)
    run_config = adapter_dir / "run_config.yaml"
    base_model = args.base_model
    if run_config.exists():
        base_model = yaml.safe_load(run_config.read_text(encoding="utf-8")).get("model_name", base_model)

    tokenizer = AutoTokenizer.from_pretrained(adapter_dir, trust_remote_code=True, use_fast=True)
    quant_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=torch.float16,
    )
    base = AutoModelForCausalLM.from_pretrained(
        base_model,
        quantization_config=quant_config,
        device_map={"": 0},
        trust_remote_code=True,
        torch_dtype=torch.float16,
    )
    model = PeftModel.from_pretrained(base, adapter_dir)
    model.eval()

    rows = load_jsonl(args.test_file)
    if args.limit:
        rows = rows[: args.limit]
    outputs = []
    for row in rows:
        prompt = prompt_from_row(row)
        inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
        start = time.perf_counter()
        with torch.inference_mode():
            generated = model.generate(
                **inputs,
                max_new_tokens=512,
                do_sample=False,
                temperature=0.0,
                top_p=1.0,
                pad_token_id=tokenizer.eos_token_id,
            )
        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        new_tokens = generated[0][inputs["input_ids"].shape[1] :]
        pred = strip_fences(tokenizer.decode(new_tokens, skip_special_tokens=True))
        outputs.append(
            {
                "id": row["id"],
                "input": row["messages"][1]["content"],
                "gold_sql": row["gold_sql"],
                "pred_sql": pred,
                "latency_ms": latency_ms,
                "metadata": row.get("metadata", {}),
            }
        )
    write_jsonl(args.output_file, outputs)
    print(f"Saved predictions: {args.output_file}")


if __name__ == "__main__":
    main()
