@echo off
setlocal
cd /d "%~dp0"
set CUDA_VISIBLE_DEVICES=0
set PYTHONIOENCODING=utf-8
".venv\Scripts\python.exe" "scripts\run_train.py" %*
endlocal
