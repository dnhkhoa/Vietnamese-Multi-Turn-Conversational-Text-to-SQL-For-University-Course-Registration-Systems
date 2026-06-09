import argparse
import os
import subprocess
import sys
from pathlib import Path

import torch
from bitsandbytes.nn import Linear4bit


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT.parent / "data" / "processed" / "university_v02"
DEFAULT_CONFIG = ROOT / "configs" / "windows_6gb_qwen3b_qlora.yaml"
DEFAULT_OUTPUT = ROOT / "outputs" / "adapters" / "viedu_qwen3b_lora"


def run(cmd, *, env=None):
    print("\n$ " + " ".join(str(part) for part in cmd), flush=True)
    subprocess.run([str(part) for part in cmd], cwd=ROOT, env=env, check=True)


def require_file(path, label):
    path = Path(path)
    if not path.exists():
        raise SystemExit(f"Missing {label}: {path}")
    return path


def smoke_check_cuda():
    print("Checking CUDA and bitsandbytes 4-bit...", flush=True)
    if not torch.cuda.is_available():
        raise SystemExit("CUDA is not available in this .venv. Training cannot run.")
    name = torch.cuda.get_device_name(0)
    free_bytes, total_bytes = torch.cuda.mem_get_info(0)
    print(f"GPU: {name}")
    print(f"VRAM free/total: {free_bytes / 1024**3:.2f}GB / {total_bytes / 1024**3:.2f}GB")
    layer = Linear4bit(8, 4, bias=False, compute_dtype=torch.float16, quant_type="nf4").cuda()
    x = torch.randn(2, 8, device="cuda", dtype=torch.float16)
    with torch.no_grad():
        _ = layer(x)
    print("bitsandbytes 4-bit smoke test: OK", flush=True)


def main():
    parser = argparse.ArgumentParser(description="One-command Qwen 3B QLoRA training pipeline.")
    parser.add_argument("--dataset_path", default=str(DEFAULT_DATASET))
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--output_dir", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--skip_sanity", action="store_true", help="Skip sanity run only if SANITY_PASSED already exists.")
    parser.add_argument("--sanity_steps", type=int, default=20)
    parser.add_argument("--disable_eval", action="store_true", default=True)
    parser.add_argument("--dry_run", action="store_true")
    args = parser.parse_args()

    dataset_path = require_file(args.dataset_path, "dataset path")
    config = require_file(args.config, "training config")
    output_dir = Path(args.output_dir)
    env = os.environ.copy()
    env["CUDA_VISIBLE_DEVICES"] = env.get("CUDA_VISIBLE_DEVICES", "0")
    env.setdefault("PYTHONIOENCODING", "utf-8")

    print(f"Project: {ROOT}")
    print(f"Dataset: {dataset_path}")
    print(f"Config: {config}")
    print(f"Output: {output_dir}")
    print(f"CUDA_VISIBLE_DEVICES={env['CUDA_VISIBLE_DEVICES']}")

    if args.dry_run:
        print("Dry run only. No training command executed.")
        return

    smoke_check_cuda()

    run([sys.executable, "scripts/prepare_sft_dataset.py", "--dataset_path", dataset_path, "--mode", "direct_sql"], env=env)

    train_file = require_file(ROOT / "data" / "processed" / "train_sft.jsonl", "train SFT file")
    dev_file = require_file(ROOT / "data" / "processed" / "dev_sft.jsonl", "dev SFT file")

    output_dir.mkdir(parents=True, exist_ok=True)
    sanity_marker = output_dir / "SANITY_PASSED"
    if not sanity_marker.exists():
        run(
            [
                sys.executable,
                "scripts/train_qlora_qwen.py",
                "--config",
                config,
                "--train_file",
                train_file,
                "--dev_file",
                dev_file,
                "--output_dir",
                output_dir,
                "--max_steps",
                str(args.sanity_steps),
                "--disable_eval",
            ],
            env=env,
        )
    elif args.skip_sanity:
        print(f"Skipping sanity run because marker exists: {sanity_marker}")
    else:
        print(f"Sanity marker already exists: {sanity_marker}")

    run(
        [
            sys.executable,
            "scripts/train_qlora_qwen.py",
            "--config",
            config,
            "--train_file",
            train_file,
            "--dev_file",
            dev_file,
            "--output_dir",
            output_dir,
            "--disable_eval",
        ],
        env=env,
    )

    print("\nTraining pipeline completed.")
    print(f"Adapter saved at: {output_dir}")


if __name__ == "__main__":
    main()
