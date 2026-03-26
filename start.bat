@echo off
chcp 936 >nul
title A-Share Quant System - Start
echo Starting A-Share Quant System...
echo.
cd /d "%~dp0"

:: Check Python
echo [1/3] Checking Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Please install Python and add to PATH.
    pause
    exit /b 1
)
echo [OK] Python found

:: Activate virtual environment
echo.
echo [2/3] Checking virtual environment...
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
    echo [OK] Activated venv
) else if exist "env\Scripts\activate.bat" (
    call env\Scripts\activate.bat
    echo [OK] Activated env
) else if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
    echo [OK] Activated .venv
) else (
    echo [INFO] No virtual environment found, using system Python
)

:: Start web server
echo.
echo [3/3] Starting web server...
echo.
echo ========================================
echo  Server starting...
echo  URL: http://localhost:5000
echo  Press Ctrl+C to stop
echo ========================================
echo.

python web_server.py

echo.
echo [ERROR] Server stopped
pause
