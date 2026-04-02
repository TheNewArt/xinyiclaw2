@echo off
chcp 65001 > nul
title XinyiClaw Web - AI Assistant

echo.
echo  ╔════════════════════════════════════════════════════════════╗
echo  ║   XinyiClaw Web - MiniMax API                            ║
echo  ║   Web UI: http://localhost:5000                         ║
echo  ╚════════════════════════════════════════════════════════════╝
echo.

cd /d "%~dp0"

echo [1/2] 检查环境...
uv run python -c "import sys; print(f'Python {sys.version.split()[0]} OK')" 2>nul
if errorlevel 1 (
    echo [错误] 请先运行: uv sync
    pause
    exit /b 1
)

echo [2/2] 启动 Web 服务...
echo.
echo 按 Ctrl+C 停止服务
echo.

uv run python -m src.web_app

pause
