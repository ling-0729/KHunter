@echo off
chcp 65001 >nul
title KHunter - Production (waitress)

cd /d "%~dp0"

:: ---------- 环境变量（避免中文乱码 / 生产标识）----------
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
set KHUNTER_ENV=production

:: ---------- 监听地址 / 端口 / 线程数（可按需修改）----------
if "%HOST%"=="" set HOST=0.0.0.0
if "%PORT%"=="" set PORT=5001
if "%THREADS%"=="" set THREADS=16

:: ---------- 依赖检查：waitress（生产 WSGI 服务器）----------
python -c "import waitress" >nul 2>&1
if errorlevel 1 (
    echo [INFO] 未检测到 waitress，正在安装...
    pip install waitress -q
    if errorlevel 1 (
        echo [ERROR] waitress 安装失败，请手动执行: pip install waitress
        pause
        exit /b 1
    )
)

echo.
echo ============================================================
echo  KHunter 生产模式（waitress · 单进程单worker）
echo   监听: %HOST%:%PORT%    HTTP线程: %THREADS%
echo    日志: logs\ 目录（utils/log_config.py）
echo    停止: 在本窗口按 Ctrl+C（服务方式见 nssm 说明）
echo ============================================================
echo.

python wsgi.py

echo.
echo [WARN] 服务已退出（异常退出请查看上方日志）
pause
