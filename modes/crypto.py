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
    """Detect advanced technical patterns, falling back to basic candles if module missing."""
    try:
        # Import the advanced 17-pattern engine used by Equity
        from analysis.pattern_detector import analyze_patterns
        res = analyze_patterns(df)
        if res and hasattr(res, "primary_pattern") and res.primary_pattern:
            return res.primary_pattern, int(res.reliability * 100)
    except ImportError:
        pass
        
    # FALLBACK: Basic Candle Patterns
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
    if df is None or len(df) < 60:
        return None

    df = calc_indicators(df)
    last  = df.iloc[-1]
    prev  = df.iloc[-2]
    prev2 = df.iloc[-3]

    price = last["close"]
    atr   = last["atr_14"]
    if pd.isna(atr) or atr == 0:
        return None

    rsi      = last["rsi_14"]
    macd_h   = last["macd_hist"]
    ema50    = last["ema_50"]
    bb_upper = last["bb_upper"]
    bb_lower = last["bb_lower"]
    bb_mid   = (bb_upper + bb_lower) / 2
    vol      = last["volume"]
    vol_avg  = df["volume"].iloc[-20:].mean()
    vol_ratio = vol / vol_avg if vol_avg > 0 else 1.0
    bb_width_current = (bb_upper - bb_lower) / bb_mid if bb_mid > 0 else 0
    bb_width_prev = (prev["bb_upper"] - prev["bb_lower"]) / ((prev["bb_upper"] + prev["bb_lower"]) / 2) if (prev["bb_upper"] + prev["bb_lower"]) > 0 else 0
    
    # Calculate simple ADX approximation using ATR and directional movement
    up_move = last["high"] - prev["high"]
    down_move = prev["low"] - last["low"]
    plus_dm = up_move if (up_move > down_move and up_move > 0) else 0
    minus_dm = down_move if (down_move > up_move and down_move > 0) else 0

    signal_type = None
    reason      = None
    confidence  = 0
    strategy    = ""
    validity    = "Valid for 1-4 Hours (1H Candle Setup)"

    # ───────────────────────────────────────────────
    # STRATEGY 1: Trend Momentum (EMA50 + MACD bullish direction)
    # Fires whenever MACD hist has been positive for 1–2 bars AND price
    # is above EMA50 — no exact crossover tick required.
    # ───────────────────────────────────────────────
    if (price > ema50 * 1.002 and macd_h > 0
            and prev["macd_hist"] > prev2["macd_hist"]   # MACD hist accelerating upward
            and rsi > 45 and rsi < 72
            and vol_ratio >= 1.2):
        signal_type = "BUY"
        strategy    = "CRYPTO_MOMENTUM"
        reason      = f"Trend: Above EMA50 | MACD boosting | Vol {vol_ratio:.1f}x | {validity}"
        confidence  = int(min(88, 65 + (rsi - 45) * 0.5 + (vol_ratio - 1) * 8))

    # ───────────────────────────────────────────────
    # STRATEGY 2: Trend Breakdown (EMA50 + MACD bearish direction)
    # ───────────────────────────────────────────────
    elif (price < ema50 * 0.998 and macd_h < 0
            and prev["macd_hist"] < prev2["macd_hist"]   # MACD hist accelerating downward
            and rsi < 55 and rsi > 28
            and vol_ratio >= 1.2):
        signal_type = "SELL"
        strategy    = "CRYPTO_MOMENTUM"
        reason      = f"Breakdown: Below EMA50 | MACD dying | Vol {vol_ratio:.1f}x | {validity}"
        confidence  = int(min(88, 65 + (55 - rsi) * 0.5 + (vol_ratio - 1) * 8))

    # ───────────────────────────────────────────────
    # STRATEGY 3: RSI Oversold Hook (mean reversion, no BB pierce needed)
    # ───────────────────────────────────────────────
    elif (rsi < 35 and rsi > prev["rsi_14"]
            and rsi > prev2["rsi_14"]           # RSI hooking up for 2 bars
            and price >= bb_lower * 0.995
            and macd_h > prev["macd_hist"]):
        signal_type = "BUY"
        strategy    = "CRYPTO_REVERSION"
        reason      = f"Oversold Hook: RSI {rsi:.0f} turning up | {validity}"
        confidence  = int(min(82, 58 + (35 - rsi) * 1.2))

    # ───────────────────────────────────────────────
    # STRATEGY 4: RSI Overbought Roll (mean reversion)
    # ───────────────────────────────────────────────
    elif (rsi > 65 and rsi < prev["rsi_14"]
            and rsi < prev2["rsi_14"]           # RSI rolling over for 2 bars
            and price <= bb_upper * 1.005
            and macd_h < prev["macd_hist"]):
        signal_type = "SELL"
        strategy    = "CRYPTO_REVERSION"
        reason      = f"Overbought Roll: RSI {rsi:.0f} turning down | {validity}"
        confidence  = int(min(82, 58 + (rsi - 65) * 1.2))

    # ───────────────────────────────────────────────
    # STRATEGY 5: Volume Spike Breakout above EMA50
    # Large volume spike while price pushes above midband and EMA50
    # ───────────────────────────────────────────────
    elif (vol_ratio >= 2.5 and price > ema50
            and price > bb_mid
            and prev["close"] <= prev["ema_50"]
            and rsi < 75):
        signal_type = "BUY"
        strategy    = "CRYPTO_BREAKOUT"
        reason      = f"Vol Spike Breakout: {vol_ratio:.1f}x avg | {validity}"
        confidence  = int(min(90, 70 + (vol_ratio - 2.5) * 5))

    # ───────────────────────────────────────────────
    # STRATEGY 6: Volatility Squeeze Breakout (Bollinger Bands expanding)
    # BB width drops very low, then suddenly volume rushes in + ADX momentum.
    # ───────────────────────────────────────────────
    elif (bb_width_prev < 0.04 and bb_width_current > bb_width_prev * 1.15
            and vol_ratio > 1.5):
        # We broke out of a tight squeeze with volume
        if price > ema50 and plus_dm > minus_dm:
            signal_type = "BUY"
            strategy    = "CRYPTO_SQUEEZE"
            reason      = f"BB Squeeze Bull Breakout | Vol surge | {validity}"
            confidence  = int(min(89, 70 + (vol_ratio - 1.5) * 8))
        elif price < ema50 and minus_dm > plus_dm:
            signal_type = "SELL"
            strategy    = "CRYPTO_SQUEEZE"
            reason      = f"BB Squeeze Bear Breakdown | Vol surge | {validity}"
            confidence  = int(min(89, 70 + (vol_ratio - 1.5) * 8))

    if not signal_type:
        return None

    # Risk Management (Dynamic ATR-based SL & TP)
    if signal_type == "BUY":
        sl     = price - (1.5 * atr)
        target = price + (3.0 * atr)
    else:
        sl     = price + (1.5 * atr)
        target = price - (3.0 * atr)

    pattern_name, pattern_conf = detect_pattern(df)
    news_score = get_fear_greed()

    ml_score = 0
    if predict_crypto:
        try:
            ml_res = predict_crypto(df)
            if ((signal_type == "BUY"  and ml_res.get("bias") == "BULLISH") or
                (signal_type == "SELL" and ml_res.get("bias") == "BEARISH")):
                ml_score = ml_res.get("score", 0)
        except Exception:
            pass

    return {
        "symbol":           symbol.replace("USDT", ""),
        "signal_type":      signal_type,
        "entry":            round(price, 4),
        "target":           round(target, 4),
        "stop_loss":        round(sl, 4),
        "risk_reward":      2.0,
        "strategy":         strategy,
        "pattern":          pattern_name,
        "reason":           reason,
        "validity":         validity,
        "overall_score":    confidence,
        "technical_score":  confidence,
        "ml_score":         ml_score,
        "sentiment_score":  news_score,
        "pattern_score":    pattern_conf,
        "fundamental_score": 50,
        "mode":             "CRYPTO",
        "conviction":       "HIGH" if confidence >= 80 else "MEDIUM",
        "indicators": {
            "rsi":       round(rsi, 2),
            "macd":      round(macd_h, 6),
            "ema50":     round(ema50, 4),
            "vol_ratio": round(vol_ratio, 2),
        },
    }

def scan_crypto_signals(coins: List[str] = None) -> List[dict]:
    """Scan top crypto coins and return actionable signals."""
    coins = coins or TOP_COINS
    signals = []
    logger.info(f"Scanning {len(coins)} crypto pairs (1h candles, 200 bars)...")

    for symbol in coins:
        try:
            # 1h candles give EMA50 = 50 hours of history (mature enough)
            # 200 bars = ~8 days of context
            df = get_klines(symbol, "1h", 200)
            sig = generate_signal(symbol, df)
            if sig:
                logger.info(f"  Signal: {sig['signal_type']} {sig['symbol']} [{sig['strategy']}] score={sig['overall_score']}")
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
