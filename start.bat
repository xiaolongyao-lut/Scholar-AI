@echo off
chcp 65001 >nul 2>&1
title 文献助手
echo.
echo   ╔══════════════════════════════════════════╗
echo   ║   文献助手 — 桌面版                      ║
echo   ╚══════════════════════════════════════════╝
echo.

set "VENV_PYTHONW=%~dp0.venv-1\Scripts\pythonw.exe"
if exist "%VENV_PYTHONW%" (
    start "" "%VENV_PYTHONW%" "%~dp0start_desktop.py" %*
    exit /b 0
)

where pythonw.exe >nul 2>&1
if not errorlevel 1 (
    start "" pythonw.exe "%~dp0start_desktop.py" %*
    exit /b 0
)

echo.
echo 启动失败，请检查 Python 环境和 pywebview 依赖
echo 修复: pip install pywebview pythonnet
pause
exit /b 1
