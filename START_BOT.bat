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
    venv\Scripts\python.exe main.py
)
if "%choice%"=="2" (
    echo Running Quick Crypto Test Scan...
    venv\Scripts\python.exe -c "import sys; sys.stdout.reconfigure(encoding='utf-8'); import logging; logging.basicConfig(level=logging.INFO, format='%%(asctime)s [%%(levelname)s] %%(message)s'); from scanners.crypto_scanner import run_crypto_scan; import telegram_bot as tb; from execution import order_manager as om; import signal_generator as sg; from ingestion import news_scraper as news; print('--- Starting Test ---'); run_crypto_scan(tb, om, sg, news)"
    pause
)
if "%choice%"=="3" (
    echo Starting dashboard API at http://localhost:5001
    start "" "e:\TRADEING\dashboard\index.html"
    venv\Scripts\python.exe api_server.py
)
if "%choice%"=="4" exit

pause
