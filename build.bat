@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo [1/3] 检查依赖...
if not exist ".venv\Scripts\python.exe" (
    echo 未找到虚拟环境，先创建...
    python -m venv .venv
    .venv\Scripts\python.exe -m pip install -r requirements.txt
)

echo [2/3] 安装 PyInstaller...
.venv\Scripts\python.exe -m pip install pyinstaller -q

echo [3/3] 开始打包...
.venv\Scripts\pyinstaller --noconfirm --clean --onefile --windowed ^
    --name "照片印迹" ^
    --icon "assets\app.ico" ^
    --add-data "assets;assets" ^
    --exclude-module tkinter ^
    --exclude-module numpy ^
    app.py

if exist "dist\照片印迹.exe" (
    rem config.json 里的 Key 是 DPAPI 密文，只对本机本账户有效，拷给别人也解不开
    if exist "config.json" copy /y "config.json" "dist\config.json" >nul
    echo.
    echo 打包完成：dist\照片印迹.exe
) else (
    echo.
    echo 打包失败，请查看上面的日志
)
pause
