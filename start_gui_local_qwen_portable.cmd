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

where py >nul 2>nul
if not errorlevel 1 (
  py -3 "%~dp0run_gui.py"
  goto :done
)
where python >nul 2>nul
if not errorlevel 1 (
  python "%~dp0run_gui.py"
  goto :done
)

echo Python 3.10 or newer was not found.
echo Download it from: https://www.python.org/downloads/windows/
pause
exit /b 6

:done
if errorlevel 1 pause
endlocal
