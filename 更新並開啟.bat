@echo off
rem 點兩下就會：抓取最新持股 → 產生儀表板 → 自動開啟（Windows 版）
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1

echo 正在更新 ETF 持股資料...
python etf_tracker.py
if errorlevel 1 (
    echo.
    echo [錯誤] 更新失敗，請把上面訊息截圖給 Claude。
    pause
    exit /b 1
)

echo.
echo 開啟儀表板...
start "" "docs\index.html"
echo 完成，可關閉此視窗。
pause
