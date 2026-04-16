@echo off
chcp 65001 >nul 2>&1
title Modular Pipeline — 文献处理工作台
echo.
echo   ╔══════════════════════════════════════════╗
echo   ║   Modular Pipeline — 文献处理工作台     ║
echo   ╚══════════════════════════════════════════╝
echo.

:: Prefer venv Python
set "VENV_PYTHON=%~dp0.venv-1\Scripts\python.exe"
if exist "%VENV_PYTHON%" (
    "%VENV_PYTHON%" "%~dp0start.py" %*
) else (
    python "%~dp0start.py" %*
)

if errorlevel 1 (
    echo.
    echo 启动失败，请检查 Python 环境
    pause
)
