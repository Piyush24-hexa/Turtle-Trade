"""
analysis/pattern_detector.py
Detects 20+ candlestick and chart patterns from OHLCV data.
Pure pandas/numpy — no TA-Lib dependency.
"""

import logging
import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class PatternResult:
    symbol: str
    candlestick: list = field(default_factory=list)  # List of detected candle patterns
    chart: list = field(default_factory=list)          # List of detected chart patterns
    primary_pattern: Optional[str] = None
    direction: str = "NEUTRAL"    # BULLISH / BEARISH / NEUTRAL
    reliability: float = 0.0      # 0-1 confidence
    description: str = ""


# ─────────────────────────────────────────────────
# CANDLESTICK PATTERNS
# ─────────────────────────────────────────────────

def _body(o, c): return abs(c - o)
def _upper_wick(o, c, h): return h - max(o, c)
def _lower_wick(o, c, l): return min(o, c) - l
def _is_bullish(o, c): return c > o
def _is_bearish(o, c): return c < o
def _avg_body(df): return _body(df["open"], df["close"]).rolling(10).mean().iloc[-1]


def detect_doji(df: pd.DataFrame) -> Optional[dict]:
    o, h, l, c = df["open"].iloc[-1], df["high"].iloc[-1], df["low"].iloc[-1], df["close"].iloc[-1]
    body = _body(o, c)
    total_range = h - l
    if total_range > 0 and body / total_range < 0.1:
        return {"pattern": "DOJI", "direction": "NEUTRAL", "reliability": 0.55,
                "desc": "Indecision candle — potential reversal"}
    return None


def detect_hammer(df: pd.DataFrame) -> Optional[dict]:
    o, h, l, c = df["open"].iloc[-1], df["high"].iloc[-1], df["low"].iloc[-1], df["close"].iloc[-1]
    body = _body(o, c)
    lower = _lower_wick(o, c, l)
    upper = _upper_wick(o, c, h)
    avg = _avg_body(df)
    if body > 0 and lower >= 2 * body and upper < body * 0.3 and body < avg:
        # Check downtrend before
        if df["close"].iloc[-5] > df["close"].iloc[-1]:
            return {"pattern": "HAMMER", "direction": "BULLISH", "reliability": 0.72,
                    "desc": "Bullish reversal after downtrend — buying pressure"}
    return None


def detect_shooting_star(df: pd.DataFrame) -> Optional[dict]:
    o, h, l, c = df["open"].iloc[-1], df["high"].iloc[-1], df["low"].iloc[-1], df["close"].iloc[-1]
    body = _body(o, c)
    upper = _upper_wick(o, c, h)
    lower = _lower_wick(o, c, l)
    if body > 0 and upper >= 2 * body and lower < body * 0.3:
        if df["close"].iloc[-5] < df["close"].iloc[-1]:  # After uptrend
            return {"pattern": "SHOOTING_STAR", "direction": "BEARISH", "reliability": 0.70,
                    "desc": "Bearish reversal after uptrend — selling pressure"}
    return None


def detect_engulfing(df: pd.DataFrame) -> Optional[dict]:
    o1, c1 = df["open"].iloc[-2], df["close"].iloc[-2]
    o2, c2 = df["open"].iloc[-1], df["close"].iloc[-1]
    prev_body = _body(o1, c1)
    curr_body = _body(o2, c2)
    if curr_body > prev_body * 1.2:
        if _is_bearish(o1, c1) and _is_bullish(o2, c2) and c2 > o1 and o2 < c1:
            return {"pattern": "BULLISH_ENGULFING", "direction": "BULLISH", "reliability": 0.78,
                    "desc": "Bulls overwhelm bears — strong reversal signal"}
        if _is_bullish(o1, c1) and _is_bearish(o2, c2) and c2 < o1 and o2 > c1:
            return {"pattern": "BEARISH_ENGULFING", "direction": "BEARISH", "reliability": 0.78,
                    "desc": "Bears overwhelm bulls — strong reversal signal"}
    return None


def detect_morning_star(df: pd.DataFrame) -> Optional[dict]:
    o1, c1 = df["open"].iloc[-3], df["close"].iloc[-3]
    o2, c2 = df["open"].iloc[-2], df["close"].iloc[-2]
    o3, c3 = df["open"].iloc[-1], df["close"].iloc[-1]
    if (_is_bearish(o1, c1) and
            _body(o2, c2) < _body(o1, c1) * 0.3 and
            _is_bullish(o3, c3) and
            c3 > (o1 + c1) / 2):
        return {"pattern": "MORNING_STAR", "direction": "BULLISH", "reliability": 0.82,
                "desc": "3-candle bullish reversal — very reliable signal"}
    return None


def detect_evening_star(df: pd.DataFrame) -> Optional[dict]:
    o1, c1 = df["open"].iloc[-3], df["close"].iloc[-3]
    o2, c2 = df["open"].iloc[-2], df["close"].iloc[-2]
    o3, c3 = df["open"].iloc[-1], df["close"].iloc[-1]
    if (_is_bullish(o1, c1) and
            _body(o2, c2) < _body(o1, c1) * 0.3 and
            _is_bearish(o3, c3) and
            c3 < (o1 + c1) / 2):
        return {"pattern": "EVENING_STAR", "direction": "BEARISH", "reliability": 0.82,
                "desc": "3-candle bearish reversal — very reliable signal"}
    return None


def detect_three_white_soldiers(df: pd.DataFrame) -> Optional[dict]:
    rows = [df.iloc[-(i+1)] for i in range(3)]
    if all(_is_bullish(r["open"], r["close"]) for r in rows):
        bodies = [_body(r["open"], r["close"]) for r in rows]
        avg = _avg_body(df)
        if all(b > avg * 0.7 for b in bodies):
            if rows[2]["close"] > rows[1]["close"] > rows[0]["close"]:
                return {"pattern": "THREE_WHITE_SOLDIERS", "direction": "BULLISH", "reliability": 0.85,
                        "desc": "3 strong bullish candles — sustained buying pressure"}
    return None


def detect_three_black_crows(df: pd.DataFrame) -> Optional[dict]:
    rows = [df.iloc[-(i+1)] for i in range(3)]
    if all(_is_bearish(r["open"], r["close"]) for r in rows):
        bodies = [_body(r["open"], r["close"]) for r in rows]
        avg = _avg_body(df)
        if all(b > avg * 0.7 for b in bodies):
            if rows[2]["close"] < rows[1]["close"] < rows[0]["close"]:
                return {"pattern": "THREE_BLACK_CROWS", "direction": "BEARISH", "reliability": 0.85,
                        "desc": "3 strong bearish candles — sustained selling pressure"}
    return None


def detect_marubozu(df: pd.DataFrame) -> Optional[dict]:
    o, h, l, c = df["open"].iloc[-1], df["high"].iloc[-1], df["low"].iloc[-1], df["close"].iloc[-1]
    body = _body(o, c)
    total = h - l
    if total > 0 and body / total > 0.92:
        if _is_bullish(o, c):
            return {"pattern": "BULLISH_MARUBOZU", "direction": "BULLISH", "reliability": 0.68,
                    "desc": "Full bullish candle — strong momentum"}
        else:
            return {"pattern": "BEARISH_MARUBOZU", "direction": "BEARISH", "reliability": 0.68,
                    "desc": "Full bearish candle — strong selling"}
    return None


CANDLESTICK_DETECTORS = [
    detect_doji, detect_hammer, detect_shooting_star, detect_engulfing,
    detect_morning_star, detect_evening_star, detect_three_white_soldiers,
    detect_three_black_crows, detect_marubozu,
]


# ─────────────────────────────────────────────────
# CHART PATTERNS (require more history)
# ─────────────────────────────────────────────────

def detect_double_top(df: pd.DataFrame, lookback: int = 30) -> Optional[dict]:
    highs = df["high"].iloc[-lookback:]
    max1_idx = highs.idxmax()
    max1_val = highs[max1_idx]
    # Find second peak
    after = highs[highs.index > max1_idx]
    if len(after) < 5:
        return None
    max2_val = after.max()
    if abs(max2_val - max1_val) / max1_val < 0.02:  # Within 2%
        neckline = df["low"].iloc[-lookback:].min()
        current = df["close"].iloc[-1]
        if current < neckline * 1.01:
            return {"pattern": "DOUBLE_TOP", "direction": "BEARISH", "reliability": 0.80,
                    "desc": f"Double top at {max1_val:.0f} — bearish reversal confirmed"}
    return None


def detect_double_bottom(df: pd.DataFrame, lookback: int = 30) -> Optional[dict]:
    lows = df["low"].iloc[-lookback:]
    min1_idx = lows.idxmin()
    min1_val = lows[min1_idx]
    after = lows[lows.index > min1_idx]
    if len(after) < 5:
        return None
    min2_val = after.min()
    if abs(min2_val - min1_val) / min1_val < 0.02:
        neckline = df["high"].iloc[-lookback:].max()
        current = df["close"].iloc[-1]
        if current > neckline * 0.99:
            return {"pattern": "DOUBLE_BOTTOM", "direction": "BULLISH", "reliability": 0.80,
                    "desc": f"Double bottom at {min1_val:.0f} — bullish reversal confirmed"}
    return None


def detect_bull_flag(df: pd.DataFrame, lookback: int = 20) -> Optional[dict]:
    """Bull flag: strong upward move (pole) followed by consolidation."""
    closes = df["close"].iloc[-lookback:]
    pole_end = lookback // 2
    pole_move = (closes.iloc[pole_end] - closes.iloc[0]) / closes.iloc[0]
    flag_move = (closes.iloc[-1] - closes.iloc[pole_end]) / closes.iloc[pole_end]

    if pole_move > 0.05 and -0.05 < flag_move < 0.01:  # Up 5%+ then flat/slight pullback
        vol = df["volume"].iloc[-lookback:]
        if vol.iloc[:pole_end].mean() > vol.iloc[pole_end:].mean():  # Volume drops in flag
            return {"pattern": "BULL_FLAG", "direction": "BULLISH", "reliability": 0.77,
                    "desc": f"Bull flag: {pole_move:.1%} pole, flag consolidating — breakout pending"}
    return None


def detect_bear_flag(df: pd.DataFrame, lookback: int = 20) -> Optional[dict]:
    closes = df["close"].iloc[-lookback:]
    pole_end = lookback // 2
    pole_move = (closes.iloc[pole_end] - closes.iloc[0]) / closes.iloc[0]
    flag_move = (closes.iloc[-1] - closes.iloc[pole_end]) / closes.iloc[pole_end]

    if pole_move < -0.05 and -0.01 < flag_move < 0.05:
        return {"pattern": "BEAR_FLAG", "direction": "BEARISH", "reliability": 0.75,
                "desc": f"Bear flag: {abs(pole_move):.1%} pole drop, flag — breakdown pending"}
    return None


def detect_triangle(df: pd.DataFrame, lookback: int = 25) -> Optional[dict]:
    highs = df["high"].iloc[-lookback:]
    lows = df["low"].iloc[-lookback:]
    x = np.arange(len(highs))

    high_slope = np.polyfit(x, highs.values, 1)[0]
    low_slope  = np.polyfit(x, lows.values,  1)[0]

    if high_slope < -0.1 and low_slope > 0.1:
        return {"pattern": "SYMMETRICAL_TRIANGLE", "direction": "NEUTRAL", "reliability": 0.65,
                "desc": "Symmetrical triangle — breakout imminent, direction unknown"}
    elif abs(high_slope) < 0.1 and low_slope > 0.1:
        return {"pattern": "ASCENDING_TRIANGLE", "direction": "BULLISH", "reliability": 0.72,
                "desc": "Ascending triangle — bullish breakout likely"}
    elif high_slope < -0.1 and abs(low_slope) < 0.1:
        return {"pattern": "DESCENDING_TRIANGLE", "direction": "BEARISH", "reliability": 0.72,
                "desc": "Descending triangle — bearish breakdown likely"}
    return None


def detect_cup_handle(df: pd.DataFrame, lookback: int = 40) -> Optional[dict]:
    if len(df) < lookback:
        return None
    closes = df["close"].iloc[-lookback:].values
    mid = lookback // 2
    left_peak  = closes[:mid//2].max()
    cup_bottom = closes[mid//4: 3*mid//4].min()
    right_peak = closes[3*mid//4: mid].max()
    handle     = closes[mid:].max()

    depth = (left_peak - cup_bottom) / left_peak
    if (abs(left_peak - right_peak) / left_peak < 0.05 and
            depth > 0.10 and depth < 0.50 and
            handle < right_peak and handle > cup_bottom):
        return {"pattern": "CUP_AND_HANDLE", "direction": "BULLISH", "reliability": 0.83,
                "desc": "Cup and handle — high-reliability bullish continuation"}
    return None


CHART_DETECTORS = [
    detect_double_top, detect_double_bottom,
    detect_bull_flag, detect_bear_flag,
    detect_triangle, detect_cup_handle,
]


# ─────────────────────────────────────────────────
# MASTER DETECTOR
# ─────────────────────────────────────────────────

def detect_all_patterns(symbol: str, df: pd.DataFrame) -> PatternResult:
    """Run all pattern detectors on OHLCV data."""
    if df is None or len(df) < 10:
        return PatternResult(symbol=symbol)

    result = PatternResult(symbol=symbol)

    # Candlestick patterns (need at least 3 candles)
    if len(df) >= 3:
        for detector in CANDLESTICK_DETECTORS:
            try:
                p = detector(df)
                if p:
                    result.candlestick.append(p)
            except Exception:
                pass

    # Chart patterns (need more history)
    if len(df) >= 20:
        for detector in CHART_DETECTORS:
            try:
                p = detector(df)
                if p:
                    result.chart.append(p)
            except Exception:
                pass

    all_patterns = result.candlestick + result.chart
    if not all_patterns:
        return result

    # Pick best pattern (highest reliability)
    best = max(all_patterns, key=lambda p: p["reliability"])
    result.primary_pattern = best["pattern"]
    result.direction = best["direction"]
    result.reliability = best["reliability"]
    result.description = best["desc"]

    # Overall direction vote
    bull = sum(1 for p in all_patterns if p["direction"] == "BULLISH")
    bear = sum(1 for p in all_patterns if p["direction"] == "BEARISH")
    if bull > bear:
        result.direction = "BULLISH"
    elif bear > bull:
        result.direction = "BEARISH"

    return result


def pattern_score(result: PatternResult) -> float:
    """Convert pattern result to 0-1 score for signal combination."""
    if not result.primary_pattern:
        return 0.5
    if result.direction == "BULLISH":
        return result.reliability
    elif result.direction == "BEARISH":
        return 1 - result.reliability
    return 0.5


if __name__ == "__main__":
    import yfinance as yf
    logging.basicConfig(level=logging.INFO)
    ticker = yf.Ticker("RELIANCE.NS")
    df = ticker.history(period="3mo")
    df.columns = df.columns.str.lower()
    df = df[["open","high","low","close","volume"]]
    result = detect_all_patterns("RELIANCE", df)
    print(f"\nRELIANCE Patterns:")
    print(f"  Candlestick: {[p['pattern'] for p in result.candlestick]}")
    print(f"  Chart:       {[p['pattern'] for p in result.chart]}")
    print(f"  Primary:     {result.primary_pattern} ({result.direction}, {result.reliability:.0%})")
    print(f"  Score:       {pattern_score(result):.2f}")
