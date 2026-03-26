@echo off
chcp 65001 >nul
title A股量化选股系统 - 启动并更新数据
cls

echo ========================================
echo    A股量化选股系统 - 启动并更新数据
echo ========================================
echo.

:: 设置当前目录为脚本所在目录
cd /d "%~dp0"

:: 检查Python环境
echo [1/5] 检查Python环境...
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到Python环境，请确保Python已安装并添加到PATH
    pause
    exit /b 1
)
for /f "tokens=2" %%a in ('python --version 2^>^&1') do echo [OK] Python版本: %%a

:: 检查虚拟环境
echo.
echo [2/5] 检查虚拟环境...
if exist "venv\Scripts\activate.bat" (
    echo [OK] 发现虚拟环境venv，正在激活...
    call venv\Scripts\activate.bat
) else if exist "env\Scripts\activate.bat" (
    echo [OK] 发现虚拟环境env，正在激活...
    call env\Scripts\activate.bat
) else if exist ".venv\Scripts\activate.bat" (
    echo [OK] 发现虚拟环境.venv，正在激活...
    call .venv\Scripts\activate.bat
) else (
    echo [提示] 未找到虚拟环境，使用系统Python
)

:: 检查依赖
echo.
echo [3/5] 检查依赖包...
python -c "import flask" >nul 2>&1
if errorlevel 1 (
    echo [警告] 缺少依赖包，正在安装...
    if exist "requirements.txt" (
        pip install -r requirements.txt
        if errorlevel 1 (
            echo [错误] 依赖包安装失败
            pause
            exit /b 1
        )
    ) else (
        echo [错误] 未找到requirements.txt文件
        pause
        exit /b 1
    )
) else (
    echo [OK] 依赖包检查通过
)

:: 更新股票数据
echo.
echo [4/5] 更新股票数据...
echo 正在执行数据更新，请稍候...
python main.py update
if errorlevel 1 (
    echo [警告] 数据更新可能未完成，继续启动Web服务器...
) else (
    echo [OK] 数据更新完成
)

:: 启动Web服务器
echo.
echo [5/5] 启动Web服务器...
echo.
echo ========================================
echo  系统正在启动，请稍候...
echo  访问地址: http://localhost:5000
echo  按 Ctrl+C 停止服务
echo ========================================
echo.

:: 启动Web服务器
python web_server.py

:: 如果服务器异常退出
echo.
echo [错误] 服务器已停止运行
pause
