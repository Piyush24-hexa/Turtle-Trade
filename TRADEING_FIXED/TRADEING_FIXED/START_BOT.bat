@echo off
title 🐢 Turtle Signal Bot
color 0A
cd /d e:\TRADEING

echo.
echo  =========================================
echo   TURTLE SIGNAL BOT - NSE Trading System
echo  =========================================
echo.
echo  [1] Start Bot (Live - waits for market)
echo  [2] Test Scan (runs now, any time)
echo  [3] Open Dashboard API
echo  [4] Exit
echo.
set /p choice="Enter choice (1-4): "

if "%choice%"=="1" (
    echo Starting bot... Press Ctrl+C to stop.
    python main.py
)
if "%choice%"=="2" (
    echo Running test scan...
    python -c "import sys; sys.stdout.reconfigure(encoding='utf-8'); import main; main.run_test()"
    pause
)
if "%choice%"=="3" (
    echo Starting dashboard API at http://localhost:5001
    start "" "e:\TRADEING\dashboard\index.html"
    python api_server.py
)
if "%choice%"=="4" exit

pause
