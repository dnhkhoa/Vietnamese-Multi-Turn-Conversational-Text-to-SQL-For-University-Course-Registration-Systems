# VieEdu Unsloth Local Fine-tuning

Local, hardware-adaptive Unsloth SFT pipeline for Vietnamese multi-turn Text-to-SQL over a university course registration database.

The phase-1 objective is `direct_sql`: given schema, dialogue history, and the current Vietnamese question, generate only the gold SQLite `SELECT` query.

## Project Layout

```text
viedu-unsloth-local/
├── README.md
├── requirements.txt
├── setup_env.md
├── data/
│   ├── raw/
│   ├── processed/
│   └── cache/
├── configs/
├── scripts/
├── outputs/
└── notebooks/
```

Large local files are ignored by Git: virtualenv, raw/cache data, processed JSONL, adapters, predictions, eval reports, and logs.

## Environment

```powershell
cd viedu-unsloth-local
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

If Unsloth or bitsandbytes fails on native Windows, use WSL2 with CUDA. Dataset preparation and SQL evaluation can run without CUDA.

## Workflow

Set your dataset path first. For this repo, the current processed dataset is one level up:

```powershell
$DATASET_PATH = "..\data\processed\university_v02"
```

Run environment detection:

```bash
python scripts/check_env.py
python scripts/choose_training_profile.py
```

On the RTX 2060 6GB machine, use this when you plan to close GPU-heavy apps before training:

```bash
python scripts/check_env.py --assume_free_vram
```

Inspect and convert dataset:

```bash
python scripts/inspect_dataset.py --dataset_path "<PUT_DATASET_PATH_HERE>"
python scripts/prepare_sft_dataset.py --dataset_path "<PUT_DATASET_PATH_HERE>" --mode direct_sql
```

20-step sanity training:

```bash
CUDA_VISIBLE_DEVICES=0 python scripts/train_unsloth_qwen.py \
  --config configs/auto_profile.yaml \
  --train_file data/processed/train_sft.jsonl \
  --dev_file data/processed/dev_sft.jsonl \
  --output_dir outputs/adapters/viedu_qwen_lora \
  --max_steps 20
```

Sanity inference on 5 test samples:

```bash
CUDA_VISIBLE_DEVICES=0 python scripts/infer_adapter.py \
  --adapter_dir outputs/adapters/viedu_qwen_lora \
  --test_file data/processed/test_sft.jsonl \
  --output_file outputs/predictions/pred_sanity_5.jsonl \
  --limit 5
```

Full training is gated. The script refuses to run full training until the same output directory contains `SANITY_PASSED`.

```bash
CUDA_VISIBLE_DEVICES=0 python scripts/train_unsloth_qwen.py \
  --config configs/auto_profile.yaml \
  --train_file data/processed/train_sft.jsonl \
  --dev_file data/processed/dev_sft.jsonl \
  --output_dir outputs/adapters/viedu_qwen_lora
```

Test inference:

```bash
CUDA_VISIBLE_DEVICES=0 python scripts/infer_adapter.py \
  --adapter_dir outputs/adapters/viedu_qwen_lora \
  --test_file data/processed/test_sft.jsonl \
  --output_file outputs/predictions/pred_test.jsonl
```

Evaluation:

```bash
python scripts/evaluate_sql.py \
  --pred_file outputs/predictions/pred_test.jsonl \
  --gold_file data/processed/test_sft.jsonl \
  --sqlite_db "<OPTIONAL_SQLITE_DB_PATH>"
```

For the current repo dataset:

```powershell
python scripts/inspect_dataset.py --dataset_path "..\data\processed\university_v02"
python scripts/prepare_sft_dataset.py --dataset_path "..\data\processed\university_v02" --mode direct_sql
python scripts/evaluate_sql.py --pred_file outputs/predictions/pred_test.jsonl --sqlite_db "..\data\processed\university_v02\database\university_registration.sqlite"
```

## Hardware Profiles

`scripts/check_env.py` writes `outputs/logs/env_report.json`. `scripts/choose_training_profile.py` reads it and writes `configs/auto_profile.yaml`.

Selection rules:

- Free VRAM >= 15GB: `unsloth/Qwen2.5-Coder-7B-Instruct-bnb-4bit`
- Free VRAM 10-15GB: `unsloth/Qwen2.5-Coder-3B-Instruct-bnb-4bit`
- Free VRAM 6-10GB: `unsloth/Qwen2.5-Coder-1.5B-Instruct-bnb-4bit`
- Free VRAM 4-6GB: Qwen 0.5B/1.5B only, short context, eval may be disabled
- No CUDA: no training, only dataset preparation/evaluation

The pipeline defaults to one GPU: set `CUDA_VISIBLE_DEVICES=0`.

For RTX 2060 6GB, `configs/experimental_6gb_qwen3b.yaml` is available if you want to try Qwen 3B anyway. Use short context, close GPU-heavy apps, disable eval, and run the 20-step sanity check first:

```bash
CUDA_VISIBLE_DEVICES=0 python scripts/train_unsloth_qwen.py \
  --config configs/experimental_6gb_qwen3b.yaml \
  --train_file data/processed/train_sft.jsonl \
  --dev_file data/processed/dev_sft.jsonl \
  --output_dir outputs/adapters/viedu_qwen3b_lora \
  --max_steps 20 \
  --disable_eval
```

Native Windows note: Unsloth/Triton did not load reliably on this machine, while PyTorch CUDA and bitsandbytes 4-bit do work. The active Windows setup uses QLoRA with Transformers + PEFT:

One-command training:

```powershell
.\train.bat
```

This command prepares the latest SFT JSONL files, checks CUDA and bitsandbytes, runs the required 20-step sanity train if needed, then starts full Qwen 3B QLoRA training.

```bash
CUDA_VISIBLE_DEVICES=0 python scripts/train_qlora_qwen.py \
  --config configs/windows_6gb_qwen3b_qlora.yaml \
  --train_file data/processed/train_sft.jsonl \
  --dev_file data/processed/dev_sft.jsonl \
  --output_dir outputs/adapters/viedu_qwen3b_lora \
  --max_steps 20 \
  --disable_eval
```

After the sanity run passes:

```bash
CUDA_VISIBLE_DEVICES=0 python scripts/train_qlora_qwen.py \
  --config configs/windows_6gb_qwen3b_qlora.yaml \
  --train_file data/processed/train_sft.jsonl \
  --dev_file data/processed/dev_sft.jsonl \
  --output_dir outputs/adapters/viedu_qwen3b_lora \
  --disable_eval
```
