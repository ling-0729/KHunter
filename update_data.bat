@echo off
chcp 65001 >nul
title A股量化选股系统 - 更新数据
cls

echo ========================================
echo    A股量化选股系统 - 更新数据
echo ========================================
echo.

:: 检查Python环境
echo [1/3] 检查Python环境...
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到Python环境，请确保Python已安装并添加到PATH
    pause
    exit /b 1
)
for /f "tokens=2" %%a in ('python --version 2^>^&1') do echo [OK] Python版本: %%a

:: 检查虚拟环境
echo.
echo [2/3] 检查虚拟环境...
if exist "venv\Scripts\activate.bat" (
    echo [OK] 发现虚拟环境，正在激活...
    call venv\Scripts\activate.bat
) else if exist "env\Scripts\activate.bat" (
    echo [OK] 发现虚拟环境，正在激活...
    call env\Scripts\activate.bat
) else if exist ".venv\Scripts\activate.bat" (
    echo [OK] 发现虚拟环境，正在激活...
    call .venv\Scripts\activate.bat
) else (
    echo [提示] 未找到虚拟环境，使用系统Python
)

:: 更新数据
echo.
echo [3/3] 更新股票数据...
echo 正在执行数据更新，请稍候...
echo.
python main.py update
if errorlevel 1 (
    echo [错误] 数据更新失败
    pause
    exit /b 1
)

echo.
echo ========================================
echo  [OK] 数据更新完成！
echo ========================================
echo.
pause
