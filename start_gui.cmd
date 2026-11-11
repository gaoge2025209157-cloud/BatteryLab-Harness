@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] The project environment is missing.
  echo Run setup_env.cmd first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" "run_gui.py"
