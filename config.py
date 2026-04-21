"""
config.py - Central configuration for the NSE Trading Bot
Edit this file to customize your settings.
"""

import os
from dataclasses import dataclass, field
from typing import List

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ─────────────────────────────────────────
#  ANGEL ONE API (SmartAPI) — FREE
#  Get credentials from: https://smartapi.angelbroking.com/
#  ⚠️ SECURITY: Set these in .env file, NEVER hardcode!
# ─────────────────────────────────────────
ANGEL_API_KEY      = os.getenv("ANGEL_API_KEY")
ANGEL_CLIENT_ID    = os.getenv("ANGEL_CLIENT_ID")
ANGEL_PASSWORD     = os.getenv("ANGEL_PASSWORD")
ANGEL_TOTP_SECRET  = os.getenv("ANGEL_TOTP_SECRET")


# ─────────────────────────────────────────
#  TELEGRAM BOT — FREE
#  Steps:
#    1. Message @BotFather on Telegram → /newbot
#    2. Copy the token below
#    3. Message @userinfobot to get your chat ID
#  ⚠️ SECURITY: Set these in .env file, NEVER hardcode!
# ─────────────────────────────────────────
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
TELEGRAM_API_URL = os.getenv("TELEGRAM_API_URL", "https://api.telegram.org")


# ─────────────────────────────────────────
#  LLM AI AGENT SETTINGS (Deepseek, OpenAI, etc.)
#  Set these in your .env file
# ─────────────────────────────────────────
LLM_API_KEY      = os.getenv("LLM_API_KEY")
LLM_BASE_URL     = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1") # Use https://api.deepseek.com/v1 for Deepseek
LLM_MODEL        = os.getenv("LLM_MODEL", "gpt-3.5-turbo") # e.g. "deepseek-chat"


# ─────────────────────────────────────────
#  ENVIRONMENT VALIDATION
# ─────────────────────────────────────────
def check_env_vars():
    """Ensures all required credentials are set before bot starts."""
    required = [
        "ANGEL_API_KEY", "ANGEL_CLIENT_ID", "ANGEL_PASSWORD", "ANGEL_TOTP_SECRET",
        "TELEGRAM_TOKEN", "TELEGRAM_CHAT_ID", "LLM_API_KEY"
    ]
    missing = [var for var in required if not os.getenv(var)]
    
    if missing:
        print("\n" + "="*70)
        print("[!] CRITICAL ERROR: Missing Environment Variables")
        print("="*70)
        print("\nThe following credentials are NOT set:")
        for var in missing:
            print(f"  [X] {var}")
        print("\n[i] To fix:")
        print("  1. Create a file named '.env' in the project root")
        print("  2. Add these lines (with your actual credentials):")
        print()
        for var in missing:
            print(f"     {var}=your_value_here")
        print("\n[!] NEVER commit .env to Git!")
        print("   Add '.env' to your .gitignore file")
        print("="*70 + "\n")
        raise ValueError(f"Missing environment variables: {', '.join(missing)}")

# Check immediately on import
check_env_vars()


# ─────────────────────────────────────────
#  CAPITAL & RISK MANAGEMENT
# ─────────────────────────────────────────
TOTAL_CAPITAL        = 10_000   # Your total capital in ₹
RISK_PER_TRADE_PCT   = 2.5      # % of capital to risk per trade (₹250 on ₹10k)
MAX_OPEN_POSITIONS   = 2        # Never hold more than 2 stocks simultaneously
MIN_RISK_REWARD      = 1.5      # Only take trades with R:R ≥ 1:1.5
DAILY_LOSS_LIMIT     = 500      # Halt bot if daily loss exceeds ₹500
MAX_POSITION_PCT     = 50       # Max % of capital in a single position (₹5k)


# ─────────────────────────────────────────
#  PAPER TRADING MODE (default: ON for safety)
#  Set to False ONLY when you're ready for live trading
# ─────────────────────────────────────────
PAPER_TRADING = True


# ─────────────────────────────────────────
#  WATCHLIST — Stocks to Scan
# ─────────────────────────────────────────
NIFTY_50 = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
    "HINDUNILVR", "ITC", "SBIN", "BHARTIARTL", "KOTAKBANK",
    "LT", "AXISBANK", "ASIANPAINT", "MARUTI", "WIPRO",
    "ULTRACEMCO", "SUNPHARMA", "TITAN", "BAJFINANCE", "NESTLEIND",
    "TECHM", "POWERGRID", "NTPC", "ONGC", "HCLTECH",
    "ADANIENT", "TATAMOTORS", "BAJAJFINSV", "DIVISLAB", "CIPLA",
    "COALINDIA", "DRREDDY", "TATASTEEL", "JSWSTEEL", "GRASIM",
    "HINDALCO", "INDUSINDBK", "APOLLOHOSP", "EICHERMOT", "BRITANNIA",
    "BPCL", "TATACONSUM", "SBILIFE", "BAJAJAUTO", "HEROMOTOCO",
    "HDFCLIFE", "ADANIPORTS", "UPL", "VEDL", "M&M",
]

NIFTY_10 = [  # Smaller list for testing
    "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK",
    "SBIN", "ITC", "WIPRO", "AXISBANK", "LT",
]

# Active watchlist
WATCHLIST = NIFTY_50


# ─────────────────────────────────────────
#  TECHNICAL INDICATOR SETTINGS
# ─────────────────────────────────────────
RSI_PERIOD           = 14
RSI_OVERSOLD         = 35      # Buy signal threshold
RSI_OVERBOUGHT       = 65      # Sell signal threshold

MACD_FAST            = 12
MACD_SLOW            = 26
MACD_SIGNAL          = 9

BB_PERIOD            = 20
BB_STD               = 2.0

EMA_FAST             = 9
EMA_MED              = 21
EMA_SLOW             = 50

VOLUME_SPIKE_MULT    = 1.5     # Volume must be 1.5x average to confirm breakout
ADX_TREND_THRESHOLD  = 25      # ADX > 25 = trending market


# ─────────────────────────────────────────
#  SIGNAL SETTINGS
# ─────────────────────────────────────────
MIN_CONFIDENCE_PCT   = 60      # Minimum signal confidence to send alert
BREAKOUT_PCT         = 0.5     # Price must break level by 0.5% to confirm
SL_ATR_MULT          = 1.5     # Stop loss = 1.5x ATR below entry
TP_RISK_REWARD       = 2.0     # Target = 2x the risk (R:R = 1:2)

# Strategies to use (comment out to disable)
ACTIVE_STRATEGIES = [
    "BREAKOUT",
    "RSI_REVERSAL",
    "EMA_CROSSOVER",
    "SR_BOUNCE",
]


# ─────────────────────────────────────────
#  MARKET HOURS (IST)
# ─────────────────────────────────────────
MARKET_OPEN_HOUR     = 9
MARKET_OPEN_MIN      = 15
MARKET_CLOSE_HOUR    = 15
MARKET_CLOSE_MIN     = 30

# Don't trade in first/last 15 minutes (volatile)
AVOID_FIRST_MIN      = 15
AVOID_LAST_MIN       = 15


# ─────────────────────────────────────────
#  DATA SETTINGS
# ─────────────────────────────────────────
SCAN_INTERVAL_SEC    = 300     # Scan every 5 minutes
HISTORICAL_DAYS      = 90      # Days of history for indicators
INTRADAY_INTERVAL    = "5m"    # 5-minute candles for intraday analysis
DAILY_INTERVAL       = "1d"    # Daily candles for trend


# ─────────────────────────────────────────
#  INTRADAY SCALPING SETTINGS
#  (separate from equity/crypto — used by modes/intraday.py)
# ─────────────────────────────────────────
INTRADAY_WATCHLIST       = NIFTY_10     # 10 liquid stocks for speed
INTRADAY_CANDLE_INTERVAL = "5m"         # 5-minute candles
INTRADAY_SL_PCT          = 0.5          # 0.5% stop loss (tight for scalping)
INTRADAY_TP_PCT          = 1.0          # 1.0% target (minimum 1:2 R:R)
INTRADAY_MAX_POSITIONS   = 3            # Max concurrent intraday trades
INTRADAY_NO_ENTRY_BEFORE = (9, 30)      # Skip opening auction chaos
INTRADAY_NO_ENTRY_AFTER  = (14, 30)     # No new entries after 2:30 PM
INTRADAY_SQUARE_OFF      = (15, 10)     # Square off all at 3:10 PM
INTRADAY_ML_THRESHOLD    = 0.70         # LightGBM confidence threshold
INTRADAY_STRATEGIES      = ["VWAP_BAND", "ORB", "SUPERTREND", "ML_CONFLUENCE"]

DEFAULT_SL_PCT           = 2.0   # Default stop-loss percentage
DEFAULT_TP_PCT           = 4.0   # Default take-profit percentage


# ─────────────────────────────────────────
#  DATABASE
# ─────────────────────────────────────────
DB_PATH              = "trading_bot.db"


# ─────────────────────────────────────────
#  LOGGING
# ─────────────────────────────────────────
LOG_FILE             = "logs/trading_bot.log"
LOG_LEVEL            = "INFO"   # DEBUG, INFO, WARNING, ERROR


# ─────────────────────────────────────────
#  VALIDATION
# ─────────────────────────────────────────
def validate_config():
    """Checks config is sane before bot starts."""
    errors = []
    if TOTAL_CAPITAL < 5000:
        errors.append("TOTAL_CAPITAL should be at least ₹5,000 for meaningful trading")
    if RISK_PER_TRADE_PCT > 5:
        errors.append("RISK_PER_TRADE_PCT > 5% is very risky — recommended: 2-3%")
    if MAX_OPEN_POSITIONS > 5:
        errors.append("MAX_OPEN_POSITIONS > 5 spreads capital too thin with ₹10k")
    if MIN_RISK_REWARD < 1.0:
        errors.append("MIN_RISK_REWARD < 1.0 is negative expectancy — use ≥ 1.5")
    if errors:
        print("[!] Config Warnings:")
        for e in errors:
            print(f"   - {e}")
    else:
        print("[OK] Config validated")
    return len(errors) == 0


if __name__ == "__main__":
    validate_config()
    print(f"\nCapital: Rs.{TOTAL_CAPITAL:,}")
    print(f"Risk/trade: Rs.{TOTAL_CAPITAL * RISK_PER_TRADE_PCT / 100:.0f}")
    print(f"Watchlist: {len(WATCHLIST)} stocks")
    print(f"Paper trading: {'YES (safe mode)' if PAPER_TRADING else 'NO (live mode!)'}")
