"""
analysis/market_condition.py
Determines overall market state: BULL/BEAR/SIDEWAYS/CRASH/RECOVERY
Monitors: Nifty 50 trend, India VIX, sector rotation, global cues
"""

import logging
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime

import yfinance as yf
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class MarketCondition:
    timestamp: str = ""
    nifty_ltp: float = 0.0
    nifty_change: float = 0.0
    nifty_trend: str = "SIDEWAYS"     # UPTREND / DOWNTREND / SIDEWAYS
    vix: float = 0.0
    vix_state: str = "CALM"           # CALM / ELEVATED / FEARFUL / EXTREME_FEAR
    market_state: str = "NEUTRAL"     # BULL / BEAR / SIDEWAYS / RECOVERY / CRASH
    trade_filter: str = "TRADE"       # TRADE / CAUTION / AVOID
    advance_decline: float = 1.0      # >1 = more advances
    global_cues: str = "NEUTRAL"      # POSITIVE / NEGATIVE / NEUTRAL
    top_sectors: list = field(default_factory=list)
    weak_sectors: list = field(default_factory=list)
    summary: str = ""
    bias: str = "NEUTRAL"             # BUY_BIAS / SELL_BIAS / NEUTRAL


SECTOR_SYMBOLS = {
    "Banking":      "^NSEBANK",
    "IT":           "^CNXIT",
    "Pharma":       "^CNXPHARMA",
    "Auto":         "^CNXAUTO",
    "FMCG":         "^CNXFMCG",
    "Energy":       "^CNXENERGY",
    "Metal":        "^CNXMETAL",
    "Realty":       "^CNXREALTY",
    "Infra":        "^CNXINFRA",
}

GLOBAL_INDICES = {
    "Dow":      "^DJI",
    "Nasdaq":   "^IXIC",
    "SGX Nifty":"^NSEBANK",  # Approximation
    "Asia":     "^HSI",
}


def _get_change(symbol: str, period: str = "2d") -> float:
    """Get % change for a symbol."""
    try:
        df = yf.Ticker(symbol).history(period=period)
        if len(df) >= 2:
            return float((df["Close"].iloc[-1] - df["Close"].iloc[-2]) / df["Close"].iloc[-2] * 100)
    except Exception:
        pass
    return 0.0


def _get_trend(symbol: str, days: int = 20) -> str:
    """Determine trend using EMA alignment."""
    try:
        df = yf.Ticker(symbol).history(period=f"{days+10}d")
        if len(df) < days:
            return "SIDEWAYS"
        c = df["Close"]
        ema9  = c.ewm(span=9,  adjust=False).mean().iloc[-1]
        ema21 = c.ewm(span=21, adjust=False).mean().iloc[-1]
        ema50 = c.ewm(span=50, adjust=False).mean().iloc[-1] if len(df) >= 50 else ema21
        if ema9 > ema21 > ema50:
            return "UPTREND"
        elif ema9 < ema21 < ema50:
            return "DOWNTREND"
        return "SIDEWAYS"
    except Exception:
        return "SIDEWAYS"


def get_market_condition() -> MarketCondition:
    """Full market condition assessment."""
    mc = MarketCondition(timestamp=datetime.now().isoformat())

    # ── Nifty 50
    try:
        nifty = yf.Ticker("^NSEI")
        nifty_info = nifty.fast_info
        mc.nifty_ltp = float(nifty_info.last_price or 0)
        mc.nifty_change = _get_change("^NSEI")
        mc.nifty_trend = _get_trend("^NSEI", 20)
    except Exception as e:
        logger.debug(f"Nifty fetch error: {e}")

    # ── India VIX
    try:
        vix_df = yf.Ticker("^INDIAVIX").history(period="2d")
        if not vix_df.empty:
            mc.vix = float(vix_df["Close"].iloc[-1])
            if mc.vix < 14:
                mc.vix_state = "CALM"
            elif mc.vix < 20:
                mc.vix_state = "ELEVATED"
            elif mc.vix < 28:
                mc.vix_state = "FEARFUL"
            else:
                mc.vix_state = "EXTREME_FEAR"
    except Exception:
        mc.vix = 15.0
        mc.vix_state = "CALM"

    # ── Market State
    if mc.nifty_trend == "UPTREND" and mc.vix_state in ("CALM", "ELEVATED"):
        mc.market_state = "BULL"
        mc.bias = "BUY_BIAS"
    elif mc.nifty_trend == "DOWNTREND" and mc.vix_state in ("FEARFUL", "EXTREME_FEAR"):
        mc.market_state = "CRASH"
        mc.bias = "SELL_BIAS"
    elif mc.nifty_trend == "DOWNTREND":
        mc.market_state = "BEAR"
        mc.bias = "SELL_BIAS"
    elif mc.nifty_change > 1.5 and mc.nifty_trend == "DOWNTREND":
        mc.market_state = "RECOVERY"
        mc.bias = "NEUTRAL"
    else:
        mc.market_state = "SIDEWAYS"
        mc.bias = "NEUTRAL"

    # ── Trade Filter
    if mc.vix_state == "EXTREME_FEAR":
        mc.trade_filter = "AVOID"
    elif mc.vix_state == "FEARFUL" or mc.market_state in ("BEAR", "CRASH"):
        mc.trade_filter = "CAUTION"
    else:
        mc.trade_filter = "TRADE"

    # ── Sector Rotation
    sector_changes = {}
    for name, sym in SECTOR_SYMBOLS.items():
        chg = _get_change(sym)
        if chg != 0:
            sector_changes[name] = round(chg, 2)

    if sector_changes:
        sorted_sectors = sorted(sector_changes.items(), key=lambda x: x[1], reverse=True)
        mc.top_sectors = [f"{s} +{c:.1f}%" for s, c in sorted_sectors[:3] if c > 0]
        mc.weak_sectors = [f"{s} {c:.1f}%" for s, c in sorted_sectors[-3:] if c < 0]

    # ── Global Cues
    try:
        dow_chg = _get_change("^DJI")
        nasdaq_chg = _get_change("^IXIC")
        avg_global = (dow_chg + nasdaq_chg) / 2
        if avg_global > 0.5:
            mc.global_cues = "POSITIVE"
        elif avg_global < -0.5:
            mc.global_cues = "NEGATIVE"
        else:
            mc.global_cues = "NEUTRAL"
    except Exception:
        pass

    # ── Summary
    mc.summary = (
        f"Nifty {mc.nifty_ltp:,.0f} ({mc.nifty_change:+.2f}%) | "
        f"{mc.market_state} | VIX {mc.vix:.1f} ({mc.vix_state}) | "
        f"Global: {mc.global_cues}"
    )

    logger.info(f"Market: {mc.summary}")
    return mc


def should_trade(mc: MarketCondition, signal_type: str) -> tuple[bool, str]:
    """
    Filter signals based on market conditions.
    Returns (should_trade, reason)
    """
    if mc.trade_filter == "AVOID":
        return False, f"VIX {mc.vix:.0f} — EXTREME FEAR, avoid all trades"

    if mc.trade_filter == "CAUTION" and signal_type == "BUY":
        if mc.market_state in ("BEAR", "CRASH"):
            return False, f"Market in {mc.market_state} — no longs"

    if signal_type == "BUY" and mc.bias == "SELL_BIAS":
        return True, "Buy signal in bearish market — reduce position size by 50%"

    return True, ""


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    mc = get_market_condition()
    print(f"\nMarket Condition:")
    print(f"  State:  {mc.market_state}")
    print(f"  Nifty:  {mc.nifty_ltp:,.0f} ({mc.nifty_change:+.2f}%) | Trend: {mc.nifty_trend}")
    print(f"  VIX:    {mc.vix:.1f} ({mc.vix_state})")
    print(f"  Filter: {mc.trade_filter}")
    print(f"  Bias:   {mc.bias}")
    print(f"  Sectors UP:   {mc.top_sectors}")
    print(f"  Sectors DOWN: {mc.weak_sectors}")
    print(f"  Global: {mc.global_cues}")
