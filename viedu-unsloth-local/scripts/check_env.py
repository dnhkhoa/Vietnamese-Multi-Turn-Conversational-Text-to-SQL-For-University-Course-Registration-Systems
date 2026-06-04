import importlib
import argparse
import json
import os
import platform
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "outputs" / "logs"
REPORT_PATH = LOG_DIR / "env_report.json"
IMPORTS = ["torch", "transformers", "datasets", "trl", "peft", "bitsandbytes", "unsloth"]


def import_status(name):
    try:
        module = importlib.import_module(name)
        return {"available": True, "version": getattr(module, "__version__", "unknown")}
    except Exception as exc:
        return {"available": False, "error": str(exc)}


def recommend(free_gb, cuda_available):
    if not cuda_available:
        return {
            "status": "NO_CUDA",
            "model_name": None,
            "max_seq_length": None,
            "lora_r": None,
            "per_device_train_batch_size": None,
            "gradient_accumulation_steps": None,
            "reason": "CUDA is unavailable. Run dataset preparation/evaluation only, or fix CUDA before training.",
        }
    if free_gb >= 15:
        return {
            "status": "OK_FOR_7B",
            "model_name": "unsloth/Qwen2.5-Coder-7B-Instruct-bnb-4bit",
            "max_seq_length": 2048,
            "lora_r": 16,
            "per_device_train_batch_size": 1,
            "gradient_accumulation_steps": 8,
            "reason": f"Free VRAM is {free_gb:.2f}GB, enough for the 7B 4-bit profile.",
        }
    if free_gb >= 10:
        return {
            "status": "OK_FOR_3B",
            "model_name": "unsloth/Qwen2.5-Coder-3B-Instruct-bnb-4bit",
            "max_seq_length": 1536,
            "lora_r": 16,
            "per_device_train_batch_size": 1,
            "gradient_accumulation_steps": 8,
            "reason": f"Free VRAM is {free_gb:.2f}GB, safer for the 3B profile than 7B.",
        }
    if free_gb >= 6:
        return {
            "status": "OK_FOR_1_5B",
            "model_name": "unsloth/Qwen2.5-Coder-1.5B-Instruct-bnb-4bit",
            "max_seq_length": 1024,
            "lora_r": 8,
            "per_device_train_batch_size": 1,
            "gradient_accumulation_steps": 16,
            "reason": f"Free VRAM is {free_gb:.2f}GB, use 1.5B with short context.",
        }
    if free_gb >= 4:
        return {
            "status": "LOW_VRAM_ONLY",
            "model_name": "Qwen/Qwen2.5-Coder-0.5B-Instruct",
            "max_seq_length": 512,
            "lora_r": 8,
            "per_device_train_batch_size": 1,
            "gradient_accumulation_steps": 32,
            "reason": f"Free VRAM is {free_gb:.2f}GB, use 0.5B/1.5B only and consider disabling eval.",
        }
    return {
        "status": "LOW_VRAM_ONLY",
        "model_name": None,
        "max_seq_length": 512,
        "lora_r": 8,
        "per_device_train_batch_size": 1,
        "gradient_accumulation_steps": 32,
        "reason": f"Free VRAM is {free_gb:.2f}GB, too low for a stable Unsloth training run.",
    }


def gpu_report(torch_module):
    if not torch_module or not torch_module.cuda.is_available():
        return []
    gpus = []
    for index in range(torch_module.cuda.device_count()):
        props = torch_module.cuda.get_device_properties(index)
        free_bytes = None
        total_bytes = props.total_memory
        try:
            free_bytes, total_bytes = torch_module.cuda.mem_get_info(index)
        except Exception:
            pass
        gpus.append(
            {
                "index": index,
                "name": props.name,
                "total_vram_gb": round(total_bytes / (1024**3), 2),
                "free_vram_gb": round((free_bytes if free_bytes is not None else total_bytes) / (1024**3), 2),
            }
        )
    return gpus


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--assume_free_vram",
        action="store_true",
        help="Use total VRAM as available VRAM for recommendation, useful when GPU-heavy apps will be closed before training.",
    )
    args = parser.parse_args()
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    statuses = {name: import_status(name) for name in IMPORTS}
    torch_module = importlib.import_module("torch") if statuses["torch"]["available"] else None
    cuda_available = bool(torch_module and torch_module.cuda.is_available())
    cuda_version = getattr(torch_module.version, "cuda", None) if torch_module else None
    gpus = gpu_report(torch_module)
    bf16_supported = False
    if cuda_available:
        major, _minor = torch_module.cuda.get_device_capability(0)
        bf16_supported = bool(major >= 8 and torch_module.cuda.is_bf16_supported())
    max_free_gb = max(
        (gpu["total_vram_gb" if args.assume_free_vram else "free_vram_gb"] for gpu in gpus),
        default=0.0,
    )
    rec = recommend(max_free_gb, cuda_available)

    report = {
        "os": platform.platform(),
        "python": sys.version,
        "python_executable": sys.executable,
        "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
        "imports": statuses,
        "torch_version": statuses["torch"].get("version"),
        "cuda_available": cuda_available,
        "cuda_version": cuda_version,
        "bf16_supported": bf16_supported,
        "gpus": gpus,
        "assume_free_vram": args.assume_free_vram,
        "recommendation": rec,
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"OS: {report['os']}")
    print(f"Python: {sys.version.split()[0]} ({sys.executable})")
    print(f"PyTorch: {report['torch_version']}")
    print(f"CUDA available: {cuda_available}")
    print(f"CUDA version: {cuda_version}")
    print(f"bf16 supported: {bf16_supported}")
    print(f"Assume free VRAM: {args.assume_free_vram}")
    for gpu in gpus:
        print(f"GPU {gpu['index']}: {gpu['name']} | total={gpu['total_vram_gb']}GB free={gpu['free_vram_gb']}GB")
    for name, status in statuses.items():
        marker = "OK" if status["available"] else "MISSING"
        print(f"{name}: {marker} {status.get('version', status.get('error', ''))}")
    print(f"Environment status: {rec['status']}")
    print(f"Recommended model: {rec['model_name']}")
    print(f"Reason: {rec['reason']}")
    print(f"Saved report: {REPORT_PATH}")


if __name__ == "__main__":
    main()
