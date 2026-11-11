@echo off
setlocal
cd /d "%~dp0"

set "PYTHON_CMD="
where py >nul 2>nul
if not errorlevel 1 set "PYTHON_CMD=py -3"
if not defined PYTHON_CMD (
  where python >nul 2>nul
  if not errorlevel 1 set "PYTHON_CMD=python"
)
if not defined PYTHON_CMD (
  echo [ERROR] Python 3.10 or newer was not found.
  echo Install CPython for Windows, then run this file again.
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating .venv...
  %PYTHON_CMD% -m venv ".venv"
  if errorlevel 1 (
    echo [ERROR] Failed to create .venv. Use standard CPython for Windows.
    exit /b 1
  )
)

echo Installing the project and pinned dependencies...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m pip install -e "."
if errorlevel 1 exit /b 1

echo Environment ready. Run start_gui.cmd.
