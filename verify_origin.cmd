@echo off
rem ---------------------------------------------------------------------------
rem  This file must stay pure ASCII.
rem
rem  cmd.exe decodes a .cmd file with the active OEM/ANSI code page (936 on
rem  Chinese Windows). UTF-8 Chinese text therefore turns into mojibake and the
rem  broken fragments get executed as commands. All Chinese output is produced by
rem  verify_origin.py instead: CPython on Windows writes to the console through
rem  the Unicode API, so it is unaffected by the code page.
rem ---------------------------------------------------------------------------
setlocal
cd /d "%~dp0"

rem Resolve the interpreter with labels instead of setting a variable inside an
rem "if (...)" block: variables assigned inside a parenthesised block are expanded
rem before the block runs, which silently produces an empty command line.
where py >nul 2>nul
if not errorlevel 1 goto :use_py
where python >nul 2>nul
if not errorlevel 1 goto :use_python
goto :no_python

:use_py
set "PYCMD=py -3"
goto :run

:use_python
set "PYCMD=python"
goto :run

:no_python
echo.
echo [ERROR] Python 3.10 or newer was not found.
echo         Install Python and tick "Add python.exe to PATH",
echo         then run this file again.
echo.
pause
exit /b 1

:run
echo.
echo ===============================================================
echo  Step 1 of 2: Origin installations found on this machine
echo ===============================================================
echo.
%PYCMD% "%~dp0verify_origin.py" --list

echo.
echo ===============================================================
echo  Step 2 of 2: run one full workflow per version
echo ===============================================================
echo.
echo  Each version may take 10 to 60 seconds including Origin startup.
echo  Do not close this window.
echo.
%PYCMD% "%~dp0verify_origin.py" --all

rem Exit code 2 means "no usable Origin found" - that is an environment
rem problem, not a quality failure, so it gets its own message.
if errorlevel 2 goto :no_origin
if errorlevel 1 goto :failed

echo.
echo ---------------------------------------------------------------
echo  All listed versions passed.
echo ---------------------------------------------------------------
echo.
echo  Results folder:
echo    %~dp0origin_verification\
echo.
echo  Next:
echo    1. Send the whole origin_verification folder to the developer.
echo    2. Open the two PNG files under artifacts\ and check by eye that
echo       fonts are not garbled and axis units are correct.
echo.
pause
exit /b 0

:no_origin
echo.
echo ---------------------------------------------------------------
echo  No usable Origin installation was found.
echo ---------------------------------------------------------------
echo.
echo  Nothing was verified, and no result folder was written.
echo.
echo  What to do:
echo    1. Confirm Origin 2021 or newer (64-bit) is installed.
echo    2. Run   verify_origin.py --list   to see what was detected.
echo    3. If Origin is installed somewhere unusual, pass the full path:
echo         verify_origin.py --origin-exe "C:\path\to\Origin64.exe"
echo.
echo  See START-HERE.md for more troubleshooting.
echo.
pause
exit /b 2

:failed
echo.
echo ---------------------------------------------------------------
echo  At least one version did not pass.
echo ---------------------------------------------------------------
echo.
echo  Open the newest verification.md under:
echo    %~dp0origin_verification\
echo.
echo  It lists every check with PASS / FAIL and the reason.
echo  Send the whole origin_verification folder to the developer.
echo.
pause
exit /b 1
