# Qwen 2.5 Coder 7B QLoRA on 4x Tesla T4

This profile fine-tunes the state-tracking parser, not direct SQL generation.
The model learns to output JSON state with `intent`, `edit_operation`, and `slots`.

## Target machine

- GPU: 4x Tesla T4
- VRAM: 15GB per GPU, about 60GB total
- Precision: fp16 because T4 does not support bf16 well
- Launcher: `accelerate launch --num_processes 4`
- Base model: `Qwen/Qwen2.5-Coder-7B-Instruct`
- Training method: 4-bit QLoRA + LoRA

## Config

File: `configs/t4x4_qwen25_coder_7b_state_tracking_qlora.yaml`

- Quantization: NF4 4-bit, double quant
- LoRA rank: 32
- LoRA alpha: 64
- LoRA dropout: 0.05
- Max sequence length: 2048
- Batch: 1 per GPU
- Gradient accumulation: 4
- Effective batch size: 16 sequences
- Epochs: 2
- Learning rate: 1e-4
- Scheduler: cosine
- Optimizer: paged AdamW 8-bit
- Eval/save every 100 steps

## SSH training commands

Clone and fetch the app branch plus v9 data:

```bash
git clone https://github.com/dnhkhoa/Vietnamese-Multi-Turn-Conversational-Text-to-SQL-For-University-Course-Registration-Systems.git
cd Vietnamese-Multi-Turn-Conversational-Text-to-SQL-For-University-Course-Registration-Systems
git checkout main
git pull origin main
git fetch origin
git checkout origin/TNhan -- data/v9 data/ctdt_sis_v3.db config/course_glossary_k23.json
```

Set up the Linux training environment:

```bash
cd viedu-unsloth-local
bash setup_4xt4_linux.sh
```

Run a 20-step sanity pass:

```bash
bash train_7b_4xt4.sh sanity
```

Run full fine-tuning:

```bash
bash train_7b_4xt4.sh full
```

Resume from a checkpoint:

```bash
bash train_7b_4xt4.sh resume outputs/adapters/viedu_qwen7b_4xt4_state_tracking_lora/checkpoints/checkpoint-100
```

## Outputs

Adapter output:

```text
viedu-unsloth-local/outputs/adapters/viedu_qwen7b_4xt4_state_tracking_lora
```

Important files after training:

- `adapter_model.safetensors`
- `adapter_config.json`
- `tokenizer.json`
- `run_config.yaml`
- `train_metrics.json`
- `checkpoints/checkpoint-*`

Check GPU usage while training:

```bash
watch -n 1 nvidia-smi
```
