@echo off
chcp 65001 >nul
title KHunter - Start

cd /d "%~dp0"

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found
    pause
    exit /b 1
)

:: Use system Python
echo Using system Python...

:: Install dependencies
if exist "requirements.txt" (
    echo Installing dependencies...
    pip install -r requirements.txt -q
)

:: Start server
echo.
echo Starting KHunter...
python web_server.py

pause
