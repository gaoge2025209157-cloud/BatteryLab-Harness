@echo off
setlocal
cd /d "%~dp0"
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
echo Install Python with Tkinter and add it to PATH, then try again.
pause
exit /b 1
:done
if errorlevel 1 pause
