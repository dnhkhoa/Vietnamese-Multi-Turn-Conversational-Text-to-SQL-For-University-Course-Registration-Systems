#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
pip install -r requirements-4xt4-linux.txt

python scripts/check_env.py --assume_free_vram

cat <<'MSG'

Setup done.
Before training, make sure the v9 files exist at:
  ../data/v9/qwen_state_tracking_train_v9.jsonl
  ../data/v9/qwen_state_tracking_dev_v9.jsonl

Run sanity:
  bash train_7b_4xt4.sh sanity

Run full training:
  bash train_7b_4xt4.sh full
MSG
