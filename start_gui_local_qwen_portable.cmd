@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "MODEL=qwen3:4b-q4_K_M"
set "ELECTROCHEM_LLM_BASE_URL=http://127.0.0.1:11434/v1"
set "ELECTROCHEM_LLM_MODEL=%MODEL%"
set "ELECTROCHEM_LLM_API_KEY="

set "OLLAMA_EXE="
for %%I in (ollama.exe) do if not "%%~$PATH:I"=="" set "OLLAMA_EXE=%%~$PATH:I"
if not defined OLLAMA_EXE if exist "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" set "OLLAMA_EXE=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
if not defined OLLAMA_EXE if exist "%ProgramFiles%\Ollama\ollama.exe" set "OLLAMA_EXE=%ProgramFiles%\Ollama\ollama.exe"

if not defined OLLAMA_EXE (
  echo Ollama was not found.
  echo Download it from: https://ollama.com/download/windows
  echo After installation, run this file again.
  pause
  exit /b 2
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$listening = Get-NetTCPConnection -LocalPort 11434 -State Listen -ErrorAction SilentlyContinue; if (-not $listening) { Start-Process -FilePath $env:OLLAMA_EXE -ArgumentList @('serve') -WindowStyle Hidden }"
if errorlevel 1 (
  echo Failed to start Ollama.
  pause
  exit /b 3
)

timeout /t 3 /nobreak >nul
"%OLLAMA_EXE%" list | findstr /I /C:"%MODEL%" >nul
if errorlevel 1 (
  echo The local model %MODEL% is not installed.
  echo Download size is approximately 2.6 GB and additional disk space is required.
  choice /C YN /N /M "Download the model now? [Y/N] "
  if errorlevel 2 exit /b 4
  "%OLLAMA_EXE%" pull "%MODEL%"
  if errorlevel 1 (
    echo Model download failed. Check the network and free disk space.
    pause
    exit /b 5
  )
)

set "PYTHON_CMD="
where py >nul 2>nul
if not errorlevel 1 set "PYTHON_CMD=py -3"
if not defined PYTHON_CMD (
  where python >nul 2>nul
  if not errorlevel 1 set "PYTHON_CMD=python"
)
if not defined PYTHON_CMD (
  echo Python 3.10 or newer was not found.
  echo Download it from: https://www.python.org/downloads/windows/
  pause
  exit /b 6
)

%PYTHON_CMD% -c "import sys; sys.path.insert(0, r'%~dp0.deps'); import pypdf" >nul 2>nul
if errorlevel 1 (
  echo PDF learning requires pypdf 5.0.0 in the project-local .deps folder.
  echo The download is below 1 MB; installed files use only a few MB.
  choice /C YN /N /M "Install the PDF reader into this project now? [Y/N] "
  if errorlevel 2 exit /b 7
  set "TMP=%~dp0.pip-tmp"
  set "TEMP=%~dp0.pip-tmp"
  set "PIP_CACHE_DIR=%~dp0.pip-tmp"
  if not exist "%~dp0.pip-tmp" mkdir "%~dp0.pip-tmp"
  %PYTHON_CMD% -m pip install --disable-pip-version-check --no-cache-dir --target "%~dp0.deps" pypdf==5.0.0
  if errorlevel 1 (
    echo PDF reader installation failed. Install pypdf 5.0.0 into .deps and try again.
    pause
    exit /b 8
  )
  if exist "%~dp0.pip-tmp" rmdir /s /q "%~dp0.pip-tmp"
)

%PYTHON_CMD% "%~dp0run_gui.py"
goto :done

:done
if errorlevel 1 pause
endlocal
