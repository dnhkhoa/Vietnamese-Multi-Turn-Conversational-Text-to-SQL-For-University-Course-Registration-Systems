$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

if (-not (Test-Path ".\.venv\Scripts\streamlit.exe")) {
  throw "Missing .venv. Run: py -3.12 -m venv .venv; .\.venv\Scripts\pip.exe install -r requirements.txt; .\.venv\Scripts\pip.exe install -r requirements-infer.txt"
}

if (-not $env:CUDA_VISIBLE_DEVICES) {
  $env:CUDA_VISIBLE_DEVICES = "0"
}

$env:PYTHONIOENCODING = "utf-8"
$env:NL2SQL_PARSER_MODE = "hybrid"
$env:NL2SQL_LORA_PATH = Join-Path $PSScriptRoot "models\qwen3b-lora-state-tracking"

& ".\.venv\Scripts\streamlit.exe" run ".\app.py"
