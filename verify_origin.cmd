@echo off
setlocal
cd /d "%~dp0"

echo ================================================================
echo  Origin 真机验证
echo ================================================================
echo.
echo  本脚本会列出本机所有受支持的 Origin，然后对每个版本各跑
echo  一次完整流程，并逐条自检产物是否真的生成。
echo.
echo  全程不联网，不会发送任何实验数据。
echo.

where py >nul 2>nul
if not errorlevel 1 (
    set "PYCMD=py -3"
    goto :found
)
where python >nul 2>nul
if not errorlevel 1 (
    set "PYCMD=python"
    goto :found
)
echo [错误] 未找到 Python 3.10 或更新版本。
echo        请先安装 Python（勾选 Add to PATH），然后重新运行本脚本。
pause
exit /b 1

:found
echo ---------------- 第一步：本机有哪些 Origin ----------------
echo.
%PYCMD% "%~dp0verify_origin.py" --list
if errorlevel 1 goto :failed

echo.
echo ---------------- 第二步：逐个版本验证 ----------------
echo.
echo  每个版本大约需要 10-60 秒（含 Origin 启动时间），请勿关闭窗口。
echo.
%PYCMD% "%~dp0verify_origin.py" --all
if errorlevel 1 goto :failed

echo.
echo ================================================================
echo  全部版本验证通过
echo ================================================================
echo.
echo  产出目录：%~dp0origin_verification\
echo.
echo  请把整个 origin_verification 文件夹打包发给开发者，
echo  并打开 artifacts 里的两张图，确认字体没有乱码、坐标轴单位正确。
echo.
pause
exit /b 0

:failed
echo.
echo ================================================================
echo  有版本未通过
echo ================================================================
echo.
echo  请打开下面目录里最新的 verification.md 查看具体是哪一条没过：
echo    %~dp0origin_verification\
echo.
echo  把整个 origin_verification 文件夹打包发给开发者即可，
echo  里面包含了定位问题需要的全部信息。
echo.
pause
exit /b 1
