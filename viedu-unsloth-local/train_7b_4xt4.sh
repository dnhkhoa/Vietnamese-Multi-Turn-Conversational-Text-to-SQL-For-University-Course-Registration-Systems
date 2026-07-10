#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
source .venv/bin/activate

MODE="${1:-sanity}"
CONFIG="configs/t4x4_qwen25_coder_7b_state_tracking_qlora.yaml"
TRAIN_FILE="../data/v9/qwen_state_tracking_train_v9.jsonl"
DEV_FILE="../data/v9/qwen_state_tracking_dev_v9.jsonl"
OUTPUT_DIR="outputs/adapters/viedu_qwen7b_4xt4_state_tracking_lora"

export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0,1,2,3}"
export PYTHONIOENCODING=utf-8
export TOKENIZERS_PARALLELISM=false

if [[ ! -f "$TRAIN_FILE" ]]; then
  echo "Missing train file: $TRAIN_FILE" >&2
  echo "Fetch TNhan data first, for example:" >&2
  echo "  git fetch origin" >&2
  echo "  git checkout origin/TNhan -- data/v9 data/ctdt_sis_v3.db config/course_glossary_k23.json" >&2
  exit 1
fi

COMMON_ARGS=(
  --num_processes 4
  --mixed_precision fp16
  scripts/train_qlora_qwen.py
  --config "$CONFIG"
  --train_file "$TRAIN_FILE"
  --dev_file "$DEV_FILE"
  --output_dir "$OUTPUT_DIR"
)

case "$MODE" in
  sanity)
    accelerate launch "${COMMON_ARGS[@]}" --max_steps 20
    ;;
  full)
    accelerate launch "${COMMON_ARGS[@]}"
    ;;
  resume)
    CHECKPOINT="${2:-}"
    if [[ -z "$CHECKPOINT" ]]; then
      echo "Usage: bash train_7b_4xt4.sh resume outputs/adapters/.../checkpoints/checkpoint-XXXX" >&2
      exit 1
    fi
    accelerate launch "${COMMON_ARGS[@]}" --resume_from_checkpoint "$CHECKPOINT"
    ;;
  *)
    echo "Usage: bash train_7b_4xt4.sh [sanity|full|resume CHECKPOINT]" >&2
    exit 1
    ;;
esac
