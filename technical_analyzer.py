"""
technical_analyzer.py - Technical analysis engine
Calculates: RSI, MACD, Bollinger Bands, ATR, EMA, ADX,
            Support/Resistance levels, Volume analysis, Trend detection
"""

import logging
import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import Optional

import config

logger = logging.getLogger(__name__)


@dataclass
class Analysis:
    symbol: str
    close: float
    change_pct: float
    trend: str           # UPTREND / DOWNTREND / SIDEWAYS

    # Indicators
    rsi: float
    macd: float
    macd_signal: float
    macd_hist: float
    bb_upper: float
    bb_mid: float
    bb_lower: float
    bb_pct: float        # Where price is in BB (0=lower, 1=upper)

    ema_fast: float
    ema_med: float
    ema_slow: float
    atr: float
    adx: float
    volume: int
    volume_avg: float
    volume_ratio: float  # current / avg (>1.5 = spike)

    # Support/Resistance
    resistance: float
    support: float

    # Signal hints (filled by signal_generator)
    breakout_up: bool = False
    breakout_down: bool = False
    near_support: bool = False
    near_resistance: bool = False


# ─────────────────────────────────────────────────
# INDICATOR CALCULATIONS (pure pandas/numpy — no TA-Lib dependency)
# ─────────────────────────────────────────────────

def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def calc_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, adjust=False).mean()
    avg_loss = loss.ewm(com=period - 1, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, 1e-10)
    return 100 - (100 / (1 + rs))


def calc_macd(close: pd.Series, fast=12, slow=26, signal=9):
    fast_ema = _ema(close, fast)
    slow_ema = _ema(close, slow)
    macd_line = fast_ema - slow_ema
    signal_line = _ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def calc_bollinger_bands(close: pd.Series, period=20, std_mult=2.0):
    mid = close.rolling(period).mean()
    std = close.rolling(period).std()
    upper = mid + std_mult * std
    lower = mid - std_mult * std
    return upper, mid, lower


def calc_atr(high: pd.Series, low: pd.Series, close: pd.Series, period=14) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(com=period - 1, adjust=False).mean()


def calc_adx(high: pd.Series, low: pd.Series, close: pd.Series, period=14) -> pd.Series:
    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)

    atr = calc_atr(high, low, close, period)
    plus_di = 100 * _ema(plus_dm, period) / atr.replace(0, 1e-10)
    minus_di = 100 * _ema(minus_dm, period) / atr.replace(0, 1e-10)

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-10)
    return _ema(dx, period)


def find_support_resistance(close: pd.Series, high: pd.Series, low: pd.Series,
                             n_bars: int = 30) -> tuple[float, float]:
    """
    Simple swing high/low S/R detection.
    Returns (support, resistance) near current price.
    """
    recent_highs = high.rolling(window=5, center=True).max()
    recent_lows = low.rolling(window=5, center=True).min()

    current = close.iloc[-1]

    # Find levels from last n_bars
    highs = high.iloc[-n_bars:].values
    lows = low.iloc[-n_bars:].values

    # Resistance = closest swing high ABOVE current price
    above = sorted([h for h in highs if h > current])
    resistance = above[0] if above else current * 1.03

    # Support = closest swing low BELOW current price
    below = sorted([l for l in lows if l < current], reverse=True)
    support = below[0] if below else current * 0.97

    return round(support, 2), round(resistance, 2)


def detect_trend(ema_fast: float, ema_med: float, ema_slow: float, adx: float) -> str:
    """Determine market trend from EMA alignment."""
    if ema_fast > ema_med > ema_slow and adx > config.ADX_TREND_THRESHOLD:
        return "UPTREND"
    elif ema_fast < ema_med < ema_slow and adx > config.ADX_TREND_THRESHOLD:
        return "DOWNTREND"
    else:
        return "SIDEWAYS"


# ─────────────────────────────────────────────────
# MAIN ANALYSIS FUNCTION
# ─────────────────────────────────────────────────

def analyze(symbol: str, df: pd.DataFrame, quote: Optional[dict] = None) -> Optional[Analysis]:
    """
    Run full technical analysis on a symbol's OHLCV data.
    Returns an Analysis dataclass or None if data is insufficient.
    """
    if df is None or len(df) < 30:
        logger.warning(f"  {symbol}: insufficient data ({len(df) if df is not None else 0} rows)")
        return None

    try:
        close = df["close"]
        high = df["high"]
        low = df["low"]
        volume = df["volume"]

        # ── Price
        current_close = float(close.iloc[-1])
        prev_close = float(close.iloc[-2]) if len(close) > 1 else current_close
        change_pct = (current_close - prev_close) / prev_close * 100

        # If we have live quote, use that LTP
        if quote and quote.get("ltp"):
            ltp = float(quote["ltp"])
            change_pct = quote.get("change_pct", change_pct)
        else:
            ltp = current_close

        # ── RSI
        rsi_series = calc_rsi(close, config.RSI_PERIOD)
        rsi_val = float(rsi_series.iloc[-1])

        # ── MACD
        macd_line, signal_line, histogram = calc_macd(
            close, config.MACD_FAST, config.MACD_SLOW, config.MACD_SIGNAL
        )
        macd_val = float(macd_line.iloc[-1])
        macd_sig = float(signal_line.iloc[-1])
        macd_hist = float(histogram.iloc[-1])

        # ── Bollinger Bands
        bb_upper, bb_mid, bb_lower = calc_bollinger_bands(close, config.BB_PERIOD, config.BB_STD)
        bb_u = float(bb_upper.iloc[-1])
        bb_m = float(bb_mid.iloc[-1])
        bb_l = float(bb_lower.iloc[-1])
        bb_width = bb_u - bb_l
        bb_pct = ((ltp - bb_l) / bb_width) if bb_width > 0 else 0.5

        # ── EMAs
        ema_f = float(_ema(close, config.EMA_FAST).iloc[-1])
        ema_m = float(_ema(close, config.EMA_MED).iloc[-1])
        ema_s = float(_ema(close, config.EMA_SLOW).iloc[-1])

        # ── ATR
        atr_series = calc_atr(high, low, close)
        atr_val = float(atr_series.iloc[-1])

        # ── ADX
        adx_series = calc_adx(high, low, close)
        adx_val = float(adx_series.iloc[-1])

        # ── Volume
        vol_now = int(volume.iloc[-1])
        vol_avg = float(volume.rolling(20).mean().iloc[-1])
        vol_ratio = (vol_now / vol_avg) if vol_avg > 0 else 1.0

        # ── Support / Resistance
        support, resistance = find_support_resistance(close, high, low)

        # ── Trend
        trend = detect_trend(ema_f, ema_m, ema_s, adx_val)

        # ── Proximity flags (within 1% of S/R)
        near_support = ltp < support * 1.01
        near_resistance = ltp > resistance * 0.99
        breakout_up = ltp > resistance * (1 + config.BREAKOUT_PCT / 100)
        breakout_down = ltp < support * (1 - config.BREAKOUT_PCT / 100)

        return Analysis(
            symbol=symbol,
            close=round(ltp, 2),
            change_pct=round(change_pct, 2),
            trend=trend,
            rsi=round(rsi_val, 1),
            macd=round(macd_val, 4),
            macd_signal=round(macd_sig, 4),
            macd_hist=round(macd_hist, 4),
            bb_upper=round(bb_u, 2),
            bb_mid=round(bb_m, 2),
            bb_lower=round(bb_l, 2),
            bb_pct=round(bb_pct, 3),
            ema_fast=round(ema_f, 2),
            ema_med=round(ema_m, 2),
            ema_slow=round(ema_s, 2),
            atr=round(atr_val, 2),
            adx=round(adx_val, 1),
            volume=vol_now,
            volume_avg=round(vol_avg, 0),
            volume_ratio=round(vol_ratio, 2),
            resistance=resistance,
            support=support,
            breakout_up=breakout_up,
            breakout_down=breakout_down,
            near_support=near_support,
            near_resistance=near_resistance,
        )

    except Exception as e:
        logger.error(f"  Analysis error for {symbol}: {e}", exc_info=True)
        return None


def analyze_all(market_data: dict) -> dict:
    """
    Analyze all symbols in market data dict.
    Returns {symbol: Analysis}
    """
    results = {}
    for symbol, data in market_data.items():
        logger.debug(f"  Analyzing {symbol}...")
        analysis = analyze(symbol, data.get("df"), data.get("quote"))
        if analysis:
            results[symbol] = analysis
    logger.info(f"✅  Analyzed {len(results)} symbols")
    return results


# ─────────────────────────────────────────────────
# QUICK SUMMARY PRINTER
# ─────────────────────────────────────────────────

def print_analysis(a: Analysis):
    trend_icon = {"UPTREND": "📈", "DOWNTREND": "📉", "SIDEWAYS": "➡️"}.get(a.trend, "")
    chg_icon = "🟢" if a.change_pct >= 0 else "🔴"
    print(f"\n{'='*50}")
    print(f"  {a.symbol} — ₹{a.close:,.2f} {chg_icon} {a.change_pct:+.2f}%")
    print(f"  Trend: {trend_icon} {a.trend}   ADX: {a.adx:.0f}")
    print(f"  RSI: {a.rsi:.0f}   MACD hist: {a.macd_hist:+.4f}")
    print(f"  BB: ₹{a.bb_lower:.0f} — ₹{a.bb_upper:.0f}  (pos: {a.bb_pct:.0%})")
    print(f"  EMA {config.EMA_FAST}/{config.EMA_MED}/{config.EMA_SLOW}: {a.ema_fast:.0f}/{a.ema_med:.0f}/{a.ema_slow:.0f}")
    print(f"  S: ₹{a.support:,.0f}   R: ₹{a.resistance:,.0f}   ATR: {a.atr:.2f}")
    print(f"  Volume ratio: {a.volume_ratio:.2f}x avg")
    flags = []
    if a.breakout_up:   flags.append("🚀 BREAKOUT UP")
    if a.breakout_down: flags.append("📉 BREAKOUT DOWN")
    if a.near_support:  flags.append("🟢 NEAR SUPPORT")
    if a.near_resistance: flags.append("🔴 NEAR RESISTANCE")
    if flags:
        print(f"  Flags: {' | '.join(flags)}")


if __name__ == "__main__":
    import yfinance as yf
    logging.basicConfig(level=logging.INFO)

    print("Testing analyzer with RELIANCE live data...")
    ticker = yf.Ticker("RELIANCE.NS")
    df = ticker.history(period="3mo", interval="1d")
    df = df.rename(columns={"Open": "open", "High": "high", "Low": "low",
                              "Close": "close", "Volume": "volume"})

    a = analyze("RELIANCE", df)
    if a:
        print_analysis(a)
    else:
        print("Analysis failed")
