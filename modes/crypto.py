"""
modes/crypto.py
Crypto scalping and swing analysis engine using Binance public API.
15-minute 24/7 scanning for high-probability momentum and mean-reversion signals
featuring dynamic ATR-based risk management.
"""

import logging
import requests
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Optional, List
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
try:
    from signals.crypto_ml import predict_crypto
except ImportError:
    predict_crypto = None

logger = logging.getLogger(__name__)

BINANCE_BASE = "https://api.binance.com/api/v3"

TOP_COINS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
    "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "MATICUSDT", "DOTUSDT",
    "LINKUSDT", "UNIUSDT", "LTCUSDT", "ATOMUSDT", "NEARUSDT",
]

def get_fear_greed() -> int:
    try:
        r = requests.get("https://api.alternative.me/fng/?limit=1", timeout=5).json()
        return int(r["data"][0]["value"])
    except:
        return 50

def detect_pattern(df: pd.DataFrame) -> tuple:
    if len(df) < 3: return "", 0
    c1, c2 = df.iloc[-1], df.iloc[-2]
    body1 = abs(c1["close"] - c1["open"])
    
    # Bullish Engulfing
    if c2["close"] < c2["open"] and c1["close"] > c1["open"] and c1["close"] > c2["open"] and c1["open"] < c2["close"]:
        return "BULLISH_ENGULFING", 85
    # Bearish Engulfing
    elif c2["close"] > c2["open"] and c1["close"] < c1["open"] and c1["close"] < c2["open"] and c1["open"] > c2["close"]:
        return "BEARISH_ENGULFING", 85
        
    # Hammer
    lower_wick = c1["open"] - c1["low"] if c1["close"] > c1["open"] else c1["close"] - c1["low"]
    if lower_wick > body1 * 2 and (c1["high"] - max(c1["close"], c1["open"])) < body1 * 0.2:
        return "HAMMER", 75
        
    return "", 0

def get_klines(symbol: str, interval: str = "15m", limit: int = 200) -> Optional[pd.DataFrame]:
    """Fetch OHLCV candlestick data from Binance."""
    try:
        url = f"{BINANCE_BASE}/klines"
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        raw = resp.json()

        df = pd.DataFrame(raw, columns=[
            "open_time", "open", "high", "low", "close", "volume",
            "close_time", "quote_vol", "trades", "taker_buy_base",
            "taker_buy_quote", "ignore"
        ])
        df = df[["open_time", "open", "high", "low", "close", "volume"]].copy()
        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
        df.set_index("open_time", inplace=True)
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = df[col].astype(float)
        return df
    except Exception as e:
        logger.error(f"Binance klines error ({symbol}): {e}")
        return None

def calc_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate EMA, MACD, RSI, Bollinger Bands, and ATR."""
    c = df["close"]
    h = df["high"]
    l = df["low"]

    # EMA 50
    df["ema_50"] = c.ewm(span=50, adjust=False).mean()

    # MACD (12, 26, 9)
    macd_fast = c.ewm(span=12, adjust=False).mean()
    macd_slow = c.ewm(span=26, adjust=False).mean()
    df["macd_line"] = macd_fast - macd_slow
    df["macd_signal"] = df["macd_line"].ewm(span=9, adjust=False).mean()
    df["macd_hist"] = df["macd_line"] - df["macd_signal"]

    # RSI (14)
    delta = c.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(com=13, min_periods=14, adjust=False).mean()
    avg_loss = loss.ewm(com=13, min_periods=14, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, 1e-10)
    df["rsi_14"] = 100 - (100 / (1 + rs))

    # Bollinger Bands (20, 2)
    bb_mid = c.rolling(20).mean()
    bb_std = c.rolling(20).std()
    df["bb_upper"] = bb_mid + (2 * bb_std)
    df["bb_lower"] = bb_mid - (2 * bb_std)

    # ATR (14)
    tr = pd.concat([
        h - l,
        (h - c.shift(1)).abs(),
        (l - c.shift(1)).abs()
    ], axis=1).max(axis=1)
    df["atr_14"] = tr.ewm(com=13, min_periods=14, adjust=False).mean()

    return df

def generate_signal(symbol: str, df: pd.DataFrame) -> Optional[dict]:
    """Run strategies and generate standard signal dictionary."""
    if df is None or len(df) < 50:
        return None

    df = calc_indicators(df)
    last = df.iloc[-1]
    prev = df.iloc[-2]
    
    price = last["close"]
    atr = last["atr_14"]
    if pd.isna(atr) or atr == 0:
        return None

    signal_type = None
    reason = None
    confidence = 0

    # ─────────────────────────────────────────────────
    # STRATEGY 1: Momentum Breakout (Bullish)
    # ─────────────────────────────────────────────────
    if price > last["ema_50"] and prev["macd_hist"] <= 0 and last["macd_hist"] > 0:
        signal_type = "BUY"
        reason = "MACD Breakout ABOVE EMA50"
        confidence = 85
    
    # STRATEGY 1: Momentum Breakdown (Bearish)
    elif price < last["ema_50"] and prev["macd_hist"] >= 0 and last["macd_hist"] < 0:
        signal_type = "SELL"
        reason = "MACD Breakdown BELOW EMA50"
        confidence = 85

    # ─────────────────────────────────────────────────
    # STRATEGY 2: Mean Reversion (RSI + Bollinger)
    # ─────────────────────────────────────────────────
    elif price < last["bb_lower"] and last["rsi_14"] < 30 and last["rsi_14"] > prev["rsi_14"]:
        signal_type = "BUY"
        reason = "Oversold BB Pierce + RSI Hook"
        confidence = 78
        
    elif price > last["bb_upper"] and last["rsi_14"] > 70 and last["rsi_14"] < prev["rsi_14"]:
        signal_type = "SELL"
        reason = "Overbought BB Rejection"
        confidence = 78

    if not signal_type:
        return None

    # Risk Management (Dynamic ATR-based SL & TP)
    if signal_type == "BUY":
        sl = price - (1.5 * atr)
        target = price + (3.0 * atr)
    else:  # SELL
        sl = price + (1.5 * atr)
        target = price - (3.0 * atr)

    pattern_name, pattern_score = detect_pattern(df)
    news_score = get_fear_greed()
    
    ml_score = 0
    if predict_crypto:
        ml_res = predict_crypto(df)
        if (signal_type == "BUY" and ml_res["bias"] == "BULLISH") or (signal_type == "SELL" and ml_res["bias"] == "BEARISH"):
            ml_score = ml_res["score"]

    # Format return dict to match standard Dashboard signal format
    return {
        "symbol": symbol.replace("USDT",""),
        "signal_type": signal_type,
        "entry": round(price, 4),
        "target": round(target, 4),
        "stop_loss": round(sl, 4),
        "risk_reward": 2.0,
        "strategy": "CRYPTO_MOMENTUM" if "MACD" in reason else "CRYPTO_REVERSION",
        "pattern": pattern_name,
        "reason": reason,
        "overall_score": confidence,
        "technical_score": confidence,
        "ml_score": ml_score,
        "sentiment_score": news_score,
        "pattern_score": pattern_score,
        "fundamental_score": 50,
        "indicators": {
            "rsi": round(last["rsi_14"], 2),
            "macd": round(last["macd_hist"], 4),
            "volume_24h": last["volume"]
        }
    }

def scan_crypto_signals(coins: List[str] = None) -> List[dict]:
    """Scan top crypto coins and return actionable signals."""
    coins = coins or TOP_COINS
    signals = []
    logger.info(f"Scanning {len(coins)} crypto pairs sequentially (15m)...")
    
    for symbol in coins:
        try:
            df = get_klines(symbol, "15m", 100)
            sig = generate_signal(symbol, df)
            if sig:
                signals.append(sig)
        except Exception as e:
            logger.debug(f"Error scanning {symbol}: {e}")

    logger.info(f"Crypto scan complete: {len(signals)} signals found.")
    return sorted(signals, key=lambda x: x["overall_score"], reverse=True)

def scan_crypto() -> dict:
    """Fetch 24h ticker data for heatmap and fear/greed."""
    logger.info("Fetching crypto heatmap data...")
    fg = get_fear_greed()
    
    coins_data = {}
    try:
        r = requests.get(f"{BINANCE_BASE}/ticker/24hr", timeout=10)
        r.raise_for_status()
        tickers = {item["symbol"]: item for item in r.json()}
        
        for coin in TOP_COINS:
            if coin in tickers:
                coins_data[coin] = {
                    "change_pct": float(tickers[coin]["priceChangePercent"]),
                    "price_usdt": float(tickers[coin]["lastPrice"]),
                    "volume": float(tickers[coin]["volume"])
                }
    except Exception as e:
        logger.error(f"Error fetching 24hr tickers: {e}")
        
    return {
        "fear_greed": {"value": fg, "state": "GREED" if fg > 55 else "FEAR" if fg < 45 else "NEUTRAL"},
        "coins": coins_data
    }

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    print("=" * 55)
    print("  CRYPTO SCALPING ENGINE — Live Test")
    print("=" * 55)
    sigs = scan_crypto_signals()
    for s in sigs:
        print(f"\n{s['signal_type']} {s['symbol']} [{s['strategy']}]")
        print(f"  Score: {s['overall_score']} | Entry: ${s['entry']}")
        print(f"  Target: ${s['target']} | SL: ${s['stop_loss']}")
        print(f"  Reason: {s['reason']}")
    print("\nScan Finished.")
