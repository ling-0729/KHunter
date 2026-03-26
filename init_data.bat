@echo off
chcp 65001 >nul
title A股量化选股系统 - 初始化数据
cls

echo ========================================
echo    A股量化选股系统 - 初始化数据
echo ========================================
echo.
echo 本脚本将执行以下操作：
echo  1. 检查Python环境
echo  2. 激活虚拟环境（如果存在）
echo  3. 安装依赖包
echo  4. 全量抓取股票数据（首次运行）
echo.
echo 注意：首次初始化可能需要较长时间（30分钟-1小时）
echo.
pause
cls

:: 检查Python环境
echo [1/4] 检查Python环境...
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到Python环境，请确保Python已安装并添加到PATH
    pause
    exit /b 1
)
for /f "tokens=2" %%a in ('python --version 2^>^&1') do echo [OK] Python版本: %%a

:: 检查虚拟环境
echo.
echo [2/4] 检查虚拟环境...
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

:: 安装依赖
echo.
echo [3/4] 安装依赖包...
if exist "requirements.txt" (
    echo 正在安装依赖包，请稍候...
    pip install -r requirements.txt
    if errorlevel 1 (
        echo [错误] 依赖包安装失败
        pause
        exit /b 1
    )
    echo [OK] 依赖包安装完成
) else (
    echo [错误] 未找到requirements.txt文件
    pause
    exit /b 1
)

:: 全量抓取股票数据
echo.
echo [4/4] 全量抓取股票数据...
echo 正在执行全量数据抓取，这可能需要30分钟到1小时...
echo 请耐心等待，不要关闭窗口...
echo.
python main.py init
if errorlevel 1 (
    echo [错误] 数据初始化失败
    pause
    exit /b 1
)

echo.
echo ========================================
echo  [OK] 数据初始化完成！
echo ========================================
echo.
echo 现在您可以运行以下命令启动系统：
echo   start.bat          - 直接启动Web服务器
echo   start_with_data.bat - 启动并更新数据
echo.
pause
