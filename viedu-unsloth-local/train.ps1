$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$env:CUDA_VISIBLE_DEVICES = "0"
$env:PYTHONIOENCODING = "utf-8"
& ".\.venv\Scripts\python.exe" "scripts\run_train.py" @args
