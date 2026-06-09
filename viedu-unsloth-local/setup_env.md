# Local Environment Setup

Create the isolated environment from inside `viedu-unsloth-local`.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

On Linux or WSL:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

If Unsloth or bitsandbytes installation fails on native Windows, use WSL2 with an NVIDIA CUDA-enabled driver. Dataset preparation, inspection, SQL validation, and evaluation can still run without CUDA.
