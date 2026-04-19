@echo off
title NSE Trading Bot — Setup
color 0A
echo.
echo  ================================================
echo   NSE Trading Bot — Windows Setup Script
echo  ================================================
echo.

REM Check Python
python --version >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Python not found! Install from https://python.org
    pause & exit /b 1
)

echo [1/4] Creating virtual environment...
python -m venv venv
call venv\Scripts\activate.bat

echo [2/4] Installing core dependencies...
pip install --upgrade pip -q
pip install yfinance pandas numpy requests pyotp flask flask-cors -q

echo [3/4] Creating logs directory...
if not exist logs mkdir logs

echo [4/4] Running config validation...
python config.py

echo.
echo  ================================================
echo   Setup Complete!
echo  ================================================
echo.
echo  Next steps:
echo    1. Edit config.py - add your Angel One API keys
echo    2. Setup Telegram - run: python telegram_bot.py
echo    3. Test scanner  - run: python main.py --test
echo    4. Start bot     - run: python main.py
echo    5. Dashboard     - run: python api_server.py
echo                       then open dashboard\index.html
echo.
echo  Quick test (no API keys needed):
echo    python main.py --test
echo.
pause
