@echo off
chcp 65001 >nul 2>&1
title 文献助手
echo.
echo   ╔══════════════════════════════════════════╗
echo   ║   文献助手 — 桌面版                      ║
echo   ╚══════════════════════════════════════════╝
echo.

set "VENV_PYTHON=%~dp0.venv-1\Scripts\python.exe"
if exist "%VENV_PYTHON%" (
    "%VENV_PYTHON%" "%~dp0start_desktop.py" %*
) else (
    python "%~dp0start_desktop.py" %*
)

if errorlevel 1 (
    echo.
    echo 启动失败，请检查 Python 环境和 pywebview 依赖
    echo 修复: pip install pywebview pythonnet
    pause
)
