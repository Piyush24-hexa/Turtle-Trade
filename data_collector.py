"""
data_collector.py - Fetches live & historical market data
Primary: Angel One SmartAPI (free real-time)
Fallback: Yahoo Finance (free, slight delay)
"""

import time
import logging
import sqlite3
import json
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
import yfinance as yf

try:
    from SmartApi import SmartConnect
    import pyotp
    ANGEL_AVAILABLE = True
except ImportError:
    ANGEL_AVAILABLE = False
    logging.warning("SmartApi not installed — using Yahoo Finance fallback only")

import config

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────
# ANGEL ONE SESSION
# ─────────────────────────────────────────────────
_angel_session = None


def connect_angel() -> Optional[object]:
    """Establishes Angel One SmartAPI connection."""
    global _angel_session
    if not ANGEL_AVAILABLE:
        return None
    if config.ANGEL_API_KEY == "YOUR_API_KEY_HERE":
        logger.warning("Angel One API key not configured — using Yahoo Finance")
        return None

    try:
        obj = SmartConnect(api_key=config.ANGEL_API_KEY)
        totp = pyotp.TOTP(config.ANGEL_TOTP_SECRET).now()
        data = obj.generateSession(config.ANGEL_CLIENT_ID, config.ANGEL_PASSWORD, totp)

        if data["status"]:
            _angel_session = obj
            logger.info("✅  Angel One connected successfully")
            return obj
        else:
            logger.error(f"Angel One login failed: {data}")
            return None
    except Exception as e:
        logger.error(f"Angel One connection error: {e}")
        return None


# ─────────────────────────────────────────────────
# DATA FETCHERS
# ─────────────────────────────────────────────────

def _yf_symbol(symbol: str) -> str:
    """Convert NSE symbol to Yahoo Finance format."""
    return f"{symbol}.NS"


def get_historical_data(symbol: str, days: int = 90, interval: str = "1d") -> pd.DataFrame:
    """
    Fetch OHLCV historical data.
    Returns DataFrame with columns: open, high, low, close, volume
    """
    # Try Angel One first (real-time)
    if _angel_session and interval == "1d":
        df = _fetch_angel_historical(symbol, days)
        if df is not None and len(df) > 10:
            logger.debug(f"  Angel One data: {symbol} ({len(df)} candles)")
            return df

    # Fallback: Yahoo Finance
    return _fetch_yahoo_historical(symbol, days, interval)


def _fetch_yahoo_historical(symbol: str, days: int, interval: str) -> pd.DataFrame:
    """Yahoo Finance historical data (fallback)."""
    try:
        yf_sym = _yf_symbol(symbol)
        end = datetime.now()
        start = end - timedelta(days=days + 10)  # Extra buffer for weekends

        ticker = yf.Ticker(yf_sym)
        df = ticker.history(start=start, end=end, interval=interval)

        if df.empty:
            logger.warning(f"  No Yahoo data for {symbol}")
            return pd.DataFrame()

        # Standardize column names
        df = df.rename(columns={
            "Open": "open", "High": "high", "Low": "low",
            "Close": "close", "Volume": "volume"
        })
        df = df[["open", "high", "low", "close", "volume"]].copy()
        df.index = pd.to_datetime(df.index)
        df = df.sort_index().tail(days)

        logger.debug(f"  Yahoo Finance data: {symbol} ({len(df)} candles)")
        return df

    except Exception as e:
        logger.error(f"  Yahoo Finance error for {symbol}: {e}")
        return pd.DataFrame()


def _fetch_angel_historical(symbol: str, days: int) -> Optional[pd.DataFrame]:
    """Angel One historical data."""
    try:
        from_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M")
        to_date = datetime.now().strftime("%Y-%m-%d %H:%M")

        # Look up the token/exchange for this symbol
        token = _get_angel_token(symbol)
        if not token:
            return None

        params = {
            "exchange": "NSE",
            "symboltoken": token,
            "interval": "ONE_DAY",
            "fromdate": from_date,
            "todate": to_date,
        }
        resp = _angel_session.getCandleData(params)

        if resp["status"] and resp["data"]:
            rows = resp["data"]
            df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])
            df["date"] = pd.to_datetime(df["date"])
            df.set_index("date", inplace=True)
            df = df.astype(float)
            return df
        return None
    except Exception as e:
        logger.error(f"  Angel historical error {symbol}: {e}")
        return None


def _get_angel_token(symbol: str) -> Optional[str]:
    """Get Angel One instrument token for a symbol (cached)."""
    # Token map for Nifty 50 (common tokens — update from Angel scripmaster if needed)
    TOKEN_MAP = {
        "RELIANCE": "2885",  "TCS": "11536",  "INFY": "1594",
        "HDFCBANK": "1333",  "ICICIBANK": "4963", "SBIN": "3045",
        "ITC": "1660",       "WIPRO": "3787",  "AXISBANK": "5900",
        "LT": "11483",       "BHARTIARTL": "10604", "KOTAKBANK": "1922",
        "HINDUNILVR": "1394","MARUTI": "10999","SUNPHARMA": "3351",
        "BAJFINANCE": "317", "TITAN": "3506",  "NESTLEIND": "17963",
        "TECHM": "13538",    "NTPC": "11630",  "ONGC": "2475",
        "ADANIENT": "25",    "TATAMOTORS": "3432", "TATASTEEL": "3499",
        "HCLTECH": "7229",   "POWERGRID": "14977","COALINDIA": "20374",
        "DRREDDY": "881",    "CIPLA": "694",   "DIVISLAB": "10940",
    }
    return TOKEN_MAP.get(symbol.upper())


def get_live_quote(symbol: str) -> Optional[dict]:
    """
    Get current live price data.
    Returns: {ltp, open, high, low, volume, change_pct}
    """
    # Try Angel One
    if _angel_session:
        quote = _fetch_angel_quote(symbol)
        if quote:
            return quote

    # Yahoo Finance fallback
    return _fetch_yahoo_quote(symbol)


def _fetch_angel_quote(symbol: str) -> Optional[dict]:
    try:
        token = _get_angel_token(symbol)
        if not token:
            return None
        resp = _angel_session.getQuote("NSE", token)
        if resp and resp.get("status"):
            d = resp["data"]
            ltp = float(d.get("ltp", 0))
            close_prev = float(d.get("close", ltp))
            return {
                "ltp": ltp,
                "open": float(d.get("open", ltp)),
                "high": float(d.get("high", ltp)),
                "low": float(d.get("low", ltp)),
                "volume": int(d.get("tradedQty", 0)),
                "change_pct": ((ltp - close_prev) / close_prev * 100) if close_prev else 0,
            }
    except Exception as e:
        logger.debug(f"Angel quote error {symbol}: {e}")
    return None


def _fetch_yahoo_quote(symbol: str) -> Optional[dict]:
    try:
        yf_sym = _yf_symbol(symbol)
        ticker = yf.Ticker(yf_sym)
        info = ticker.fast_info
        ltp = float(info.last_price or 0)
        prev = float(info.previous_close or ltp)
        return {
            "ltp": ltp,
            "open": float(info.open or ltp),
            "high": float(info.day_high or ltp),
            "low": float(info.day_low or ltp),
            "volume": int(info.three_month_average_volume or 0),
            "change_pct": ((ltp - prev) / prev * 100) if prev else 0,
        }
    except Exception as e:
        logger.debug(f"Yahoo quote error {symbol}: {e}")
    return None


# ─────────────────────────────────────────────────
# BATCH MARKET SCAN
# ─────────────────────────────────────────────────

def scan_watchlist(symbols: list) -> dict:
    """
    Fetch historical + live data for all watchlist symbols.
    Returns dict: {symbol: {"df": DataFrame, "quote": dict}}
    """
    results = {}
    total = len(symbols)
    logger.info(f"📡  Scanning {total} symbols...")

    for i, sym in enumerate(symbols, 1):
        logger.info(f"   [{i}/{total}] Fetching {sym}...")
        try:
            df = get_historical_data(sym, days=config.HISTORICAL_DAYS)
            quote = get_live_quote(sym)

            if not df.empty:
                results[sym] = {"df": df, "quote": quote}
            else:
                logger.warning(f"   ⚠️  No data for {sym} — skipping")

            # Rate limit: be gentle on APIs
            time.sleep(0.5)

        except Exception as e:
            logger.error(f"   ❌  Error fetching {sym}: {e}")

    logger.info(f"✅  Scanned {len(results)}/{total} symbols successfully")
    return results


# ─────────────────────────────────────────────────
# DATABASE STORAGE
# ─────────────────────────────────────────────────

def init_db():
    """Create database tables if they don't exist."""
    conn = sqlite3.connect(config.DB_PATH)
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS ohlcv (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            date TEXT NOT NULL,
            open REAL, high REAL, low REAL, close REAL, volume INTEGER,
            UNIQUE(symbol, date)
        )
    """)

    conn.commit()
    conn.close()
    logger.info("✅  Database initialized")


def save_ohlcv(symbol: str, df: pd.DataFrame):
    """Save OHLCV data to SQLite."""
    try:
        conn = sqlite3.connect(config.DB_PATH)
        for date, row in df.iterrows():
            conn.execute(
                "INSERT OR REPLACE INTO ohlcv (symbol, date, open, high, low, close, volume) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (symbol, str(date.date()), row["open"], row["high"],
                 row["low"], row["close"], int(row["volume"]))
            )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"DB save error for {symbol}: {e}")





if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    init_db()

    # Quick test
    print("Testing Yahoo Finance fallback...")
    df = get_historical_data("RELIANCE", days=10)
    if not df.empty:
        print(f"✅  Got {len(df)} rows for RELIANCE")
        print(df.tail(3))
    else:
        print("❌  No data returned")

    quote = get_live_quote("RELIANCE")
    print(f"\nLive quote: {quote}")
