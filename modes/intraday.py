"""
modes/intraday.py
=================
Intraday scalping engine — runs 4 strategies on 5-minute candles.
Completely separate from signal_generator.py (daily equity pipeline).

Strategies:
  1. VWAP Band Reversal  (mean-reversion at 2-sigma bands)
  2. Opening Range Breakout  (ORB with Supertrend confirmation)
  3. Supertrend Flip  (trend-following with EMA & VWAP confluence)
  4. ML Confluence  (LightGBM + at least 1 rule-based strategy agrees)

Data: 5-minute candles via Yahoo Finance (free, no API key)
Risk: 0.5% SL, 1% TP, max 3 positions, no entries after 2:30 PM
"""

import logging
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, time as dtime
from typing import Optional, List
from pathlib import Path
import sys

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR / "signals"))

import config

logger = logging.getLogger(__name__)

# Import our intraday ML and calculator utilities
from intraday_ml import (
    calc_supertrend, calc_vwap, compute_intraday_features, predict_intraday,
)


# =====================================================
# CONFIGURATION (uses config.py values with defaults)
# =====================================================

INTRADAY_WATCHLIST    = getattr(config, "INTRADAY_WATCHLIST", config.NIFTY_10)
INTRADAY_SL_PCT      = getattr(config, "INTRADAY_SL_PCT", 0.5)
INTRADAY_TP_PCT      = getattr(config, "INTRADAY_TP_PCT", 1.0)
INTRADAY_MAX_POS     = getattr(config, "INTRADAY_MAX_POSITIONS", 3)
NO_ENTRY_BEFORE      = getattr(config, "INTRADAY_NO_ENTRY_BEFORE", (9, 30))
NO_ENTRY_AFTER       = getattr(config, "INTRADAY_NO_ENTRY_AFTER", (14, 30))
SQUARE_OFF_TIME      = getattr(config, "INTRADAY_SQUARE_OFF", (15, 10))
ML_THRESHOLD         = getattr(config, "INTRADAY_ML_THRESHOLD", 0.70)
ACTIVE = getattr(config, "INTRADAY_STRATEGIES", ["VWAP_BAND", "ORB", "SUPERTREND", "ML_CONFLUENCE"])


# =====================================================
# DATA FETCHING (self-contained, no data_collector.py)
# =====================================================

def fetch_intraday_data(symbol: str, period: str = "5d") -> Optional[pd.DataFrame]:
    """Fetch 5-minute candles from Yahoo Finance."""
    try:
        yf_sym = f"{symbol}.NS" if not symbol.endswith(".NS") else symbol
        ticker = yf.Ticker(yf_sym)
        df = ticker.history(period=period, interval="5m")

        if df is None or len(df) < 20:
            return None

        df.columns = df.columns.str.lower()
        df = df[["open", "high", "low", "close", "volume"]].copy()
        df = df[df["volume"] > 0]
        return df

    except Exception as e:
        logger.debug(f"Intraday fetch error {symbol}: {e}")
        return None


def split_by_day(df: pd.DataFrame) -> list:
    """Split intraday dataframe into individual trading day dataframes."""
    df = df.copy()
    df["_date"] = df.index.date
    days = []
    for date, group in df.groupby("_date"):
        day_df = group.drop(columns=["_date"])
        if len(day_df) >= 10:
            days.append((date, day_df))
    return days


# =====================================================
# INDICATOR CALCULATIONS
# =====================================================

def _calc_rsi(series, period=14):
    """Fast RSI computation."""
    delta = series.diff()
    gain = delta.clip(lower=0).ewm(com=period - 1, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(com=period - 1, adjust=False).mean()
    rs = gain / loss.replace(0, 1e-10)
    return 100 - 100 / (1 + rs)


def compute_indicators(df: pd.DataFrame):
    """
    Compute all technical indicators needed by the strategies.
    Returns a dict of indicator values at the LATEST bar.
    """
    c = df["close"]
    h = df["high"]
    l = df["low"]
    v = df["volume"]
    ltp = float(c.iloc[-1])

    # VWAP + bands
    try:
        vwap, vwap_u1, vwap_l1, vwap_u2, vwap_l2 = calc_vwap(df)
        vwap_val = float(vwap.iloc[-1])
        vwap_u2_val = float(vwap_u2.iloc[-1])
        vwap_l2_val = float(vwap_l2.iloc[-1])
        vwap_slope_val = float(vwap.pct_change(3).iloc[-1]) if len(vwap) > 3 else 0
    except Exception:
        vwap_val = ltp
        vwap_u2_val = ltp * 1.01
        vwap_l2_val = ltp * 0.99
        vwap_slope_val = 0

    # RSI (fast)
    rsi7 = float(_calc_rsi(c, 7).iloc[-1])
    rsi14 = float(_calc_rsi(c, 14).iloc[-1])

    # EMA
    ema5 = c.ewm(span=5, adjust=False).mean()
    ema13 = c.ewm(span=13, adjust=False).mean()
    ema5_val = float(ema5.iloc[-1])
    ema13_val = float(ema13.iloc[-1])

    # EMA cross (current bar)
    ema_cross = 0
    if len(ema5) >= 2:
        prev_diff = float(ema5.iloc[-2] - ema13.iloc[-2])
        curr_diff = float(ema5.iloc[-1] - ema13.iloc[-1])
        if prev_diff <= 0 and curr_diff > 0:
            ema_cross = 1  # Bullish cross
        elif prev_diff >= 0 and curr_diff < 0:
            ema_cross = -1  # Bearish cross

    # Supertrend
    try:
        st, st_dir = calc_supertrend(df, period=10, multiplier=3.0)
        st_val = float(st.iloc[-1]) if not np.isnan(st.iloc[-1]) else ltp
        st_dir_val = int(st_dir.iloc[-1])
        # Was there a flip recently (last 3 candles)?
        st_flipped = 0
        if len(st_dir) >= 4:
            # Check if it flipped in any of the last 3 transitions
            if st_dir.iloc[-1] == 1 and any(st_dir.iloc[-i] == -1 for i in range(2, 5)):
                st_flipped = 1
            elif st_dir.iloc[-1] == -1 and any(st_dir.iloc[-i] == 1 for i in range(2, 5)):
                st_flipped = -1
    except Exception:
        st_val = ltp
        st_dir_val = 0
        st_flipped = 0

    # Volume
    vol_avg = float(v.rolling(20).mean().iloc[-1]) if len(v) >= 20 else float(v.mean())
    vol_ratio = float(v.iloc[-1]) / vol_avg if vol_avg > 0 else 1.0

    # ATR
    tr = pd.concat([h - l, (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1).max(axis=1)
    atr_5 = float(tr.ewm(com=4, adjust=False).mean().iloc[-1])
    atr_20 = float(tr.ewm(com=19, adjust=False).mean().iloc[-1])

    # ORB (first 3 candles = 15 minutes)
    orb_bars = min(3, len(df))
    orb_high = float(h.iloc[:orb_bars].max())
    orb_low = float(l.iloc[:orb_bars].min())

    # MACD histogram
    macd_fast = c.ewm(span=12, adjust=False).mean()
    macd_slow = c.ewm(span=26, adjust=False).mean()
    macd_sig = (macd_fast - macd_slow).ewm(span=9, adjust=False).mean()
    macd_hist = float((macd_fast - macd_slow - macd_sig).iloc[-1])

    return {
        "ltp": ltp,
        "vwap": vwap_val,
        "vwap_u2": vwap_u2_val,
        "vwap_l2": vwap_l2_val,
        "vwap_slope": vwap_slope_val,
        "rsi7": rsi7,
        "rsi14": rsi14,
        "ema5": ema5_val,
        "ema13": ema13_val,
        "ema_cross": ema_cross,
        "supertrend": st_val,
        "st_direction": st_dir_val,
        "st_flipped": st_flipped,
        "vol_ratio": vol_ratio,
        "atr_5": atr_5,
        "atr_20": atr_20,
        "orb_high": orb_high,
        "orb_low": orb_low,
        "macd_hist": macd_hist,
    }


# =====================================================
# SIGNAL BUILDER
# =====================================================

def _build_signal(symbol, signal_type, strategy, reason, confidence, ind, atr):
    """Build a signal dict in the same format as signal_generator.py."""
    ltp = ind["ltp"]
    sl_pct = max(INTRADAY_SL_PCT, (atr / ltp) * 100)
    tp_pct = max(INTRADAY_TP_PCT, sl_pct * 2)

    if signal_type == "BUY":
        sl = ltp * (1 - sl_pct / 100)
        tp = ltp * (1 + tp_pct / 100)
    else:
        sl = ltp * (1 + sl_pct / 100)
        tp = ltp * (1 - tp_pct / 100)

    rr = tp_pct / sl_pct if sl_pct > 0 else 0

    # Position sizing
    try:
        from execution.order_manager import get_available_capital
        cap_data = get_available_capital()
        capital = cap_data["available_capital"]
    except Exception:
        capital = config.TOTAL_CAPITAL
        
    risk_amt = capital * config.RISK_PER_TRADE_PCT / 100
    risk_per_share = abs(ltp - sl)
    qty = max(1, int(risk_amt / risk_per_share)) if risk_per_share > 0 else 1
    investment = qty * ltp

    # Cap at 20% of capital per intraday trade
    if investment > capital * 0.20:
        qty = max(1, int(capital * 0.20 / ltp))
        investment = qty * ltp

    return {
        "symbol": symbol,
        "signal_type": signal_type,
        "strategy": strategy,
        "reason": reason,
        "confidence": confidence,
        "overall_score": confidence,
        "mode": "INTRADAY",
        "entry": round(ltp, 2),
        "target": round(tp, 2),
        "stop_loss": round(sl, 2),
        "risk_reward": round(rr, 2),
        "return_pct": round(tp_pct, 2),
        "risk_pct": round(sl_pct, 2),
        "quantity": qty,
        "investment": round(investment, 2),
        "risk_amount": round(qty * risk_per_share, 2),
        "vwap": round(ind["vwap"], 2),
        "orb_high": round(ind["orb_high"], 2),
        "orb_low": round(ind["orb_low"], 2),
        "supertrend_dir": ind["st_direction"],
        "rsi": round(ind["rsi7"], 1),
        "vol_ratio": round(ind["vol_ratio"], 2),
        "paper_trade": config.PAPER_TRADING,
        "timestamp": datetime.now().strftime("%H:%M"),
        "conviction": "HIGH" if confidence >= 80 else ("MEDIUM" if confidence >= 65 else "LOW"),
        # Empty fields for signal card compatibility
        "technical_score": confidence,
        "ml_score": 0,
        "sentiment_score": 50,
        "pattern_score": 50,
        "fundamental_score": 50,
        "sentiment": "",
        "news_headline": "",
        "pattern": "",
        "rf_label": "",
        "lstm_direction": "",
    }


# =====================================================
# STRATEGIES
# =====================================================

def strategy_vwap_band(symbol: str, df: pd.DataFrame, ind: dict) -> List[dict]:
    """
    VWAP Band Reversal (mean-reversion).
    BUY when price touches VWAP -2sigma with RSI oversold + volume.
    SELL when price touches VWAP +2sigma with RSI overbought + volume.
    """
    signals = []
    ltp = ind["ltp"]

    # BUY: price near lower 2-sigma band
    if (ltp <= ind["vwap_l2"] * 1.002
            and ind["rsi7"] < 38          # RSI(7) <38 is reliably oversold on 5m NSE candles
            and ind["vol_ratio"] >= 1.2):
        confidence = min(85, 60 + (38 - ind["rsi7"]) * 0.8 + (ind["vol_ratio"] - 1) * 10)
        sig = _build_signal(
            symbol, "BUY", "VWAP_BAND",
            f"VWAP -2σ reversal | RSI(7) {ind['rsi7']:.0f} | Vol {ind['vol_ratio']:.1f}x",
            confidence, ind, ind["atr_5"],
        )
        signals.append(sig)

    # SELL: price near upper 2-sigma band
    if (ltp >= ind["vwap_u2"] * 0.998
            and ind["rsi7"] > 62          # RSI(7) >62 is reliably overbought on 5m NSE candles
            and ind["vol_ratio"] >= 1.2):
        confidence = min(85, 60 + (ind["rsi7"] - 62) * 0.8 + (ind["vol_ratio"] - 1) * 10)
        sig = _build_signal(
            symbol, "SELL", "VWAP_BAND",
            f"VWAP +2σ reversal | RSI(7) {ind['rsi7']:.0f} | Vol {ind['vol_ratio']:.1f}x",
            confidence, ind, ind["atr_5"],
        )
        signals.append(sig)

    return signals


def strategy_orb(symbol: str, df: pd.DataFrame, ind: dict) -> List[dict]:
    """
    Opening Range Breakout.
    BUY on breakout above ORB high with volume + Supertrend UP.
    SELL on breakdown below ORB low with volume + Supertrend DOWN.
    """
    signals = []
    ltp = ind["ltp"]

    # Need at least 4 candles (past the opening range = 3 candles)
    if len(df) < 4:
        return signals

    orb_width = ind["orb_high"] - ind["orb_low"]
    if orb_width <= 0:
        return signals

    # BUY: breakout above ORB high
    if (ltp > ind["orb_high"] * 1.001
            and ind["vol_ratio"] >= 1.5
            and ind["st_direction"] == 1):
        breakout_pct = (ltp - ind["orb_high"]) / ind["orb_high"] * 100
        confidence = min(88, 65 + breakout_pct * 10 + (ind["vol_ratio"] - 1) * 5)
        sig = _build_signal(
            symbol, "BUY", "ORB",
            f"ORB breakout above {ind['orb_high']:.0f} | Vol {ind['vol_ratio']:.1f}x | Supertrend UP",
            confidence, ind, ind["atr_5"],
        )
        signals.append(sig)

    # SELL: breakdown below ORB low
    if (ltp < ind["orb_low"] * 0.999
            and ind["vol_ratio"] >= 1.5
            and ind["st_direction"] == -1):
        breakdown_pct = (ind["orb_low"] - ltp) / ind["orb_low"] * 100
        confidence = min(85, 63 + breakdown_pct * 10 + (ind["vol_ratio"] - 1) * 5)
        sig = _build_signal(
            symbol, "SELL", "ORB",
            f"ORB breakdown below {ind['orb_low']:.0f} | Vol {ind['vol_ratio']:.1f}x | Supertrend DOWN",
            confidence, ind, ind["atr_5"],
        )
        signals.append(sig)

    return signals


def strategy_supertrend(symbol: str, df: pd.DataFrame, ind: dict) -> List[dict]:
    """
    Supertrend Flip with EMA + VWAP confluence.
    BUY when Supertrend flips UP + EMA5 > EMA13 + VWAP slope positive.
    SELL when Supertrend flips DOWN + EMA5 < EMA13 + VWAP slope negative.
    """
    signals = []

    # Only trigger on flips
    if ind["st_flipped"] == 0:
        return signals

    # BUY: Supertrend flipped UP
    if (ind["st_flipped"] == 1
            and ind["ema5"] > ind["ema13"]
            and ind["vwap_slope"] > 0):
        confidence = min(82, 65 + ind["vol_ratio"] * 5)
        sig = _build_signal(
            symbol, "BUY", "SUPERTREND",
            f"Supertrend flip UP | EMA5>{int(ind['ema13'])} | VWAP rising",
            confidence, ind, ind["atr_5"],
        )
        signals.append(sig)

    # SELL: Supertrend flipped DOWN
    if (ind["st_flipped"] == -1
            and ind["ema5"] < ind["ema13"]
            and ind["vwap_slope"] < 0):
        confidence = min(80, 63 + ind["vol_ratio"] * 5)
        sig = _build_signal(
            symbol, "SELL", "SUPERTREND",
            f"Supertrend flip DOWN | EMA5<{int(ind['ema13'])} | VWAP falling",
            confidence, ind, ind["atr_5"],
        )
        signals.append(sig)

    return signals


def strategy_ml_confluence(
    symbol: str, df: pd.DataFrame, ind: dict,
    ml_result: dict, rule_signals: List[dict],
) -> List[dict]:
    """
    ML Confluence: LightGBM prediction + at least 1 rule-based strategy agrees.
    Prevents the ML from trading alone in unpredictable regimes.
    """
    signals = []

    if not ml_result or ml_result.get("confidence", 0) < ML_THRESHOLD:
        return signals

    ml_label = ml_result["label"]
    ml_conf = ml_result["confidence"]

    # Check if any rule-based strategy agrees
    rule_directions = [s["signal_type"] for s in rule_signals]

    if ml_label == "BUY" and "BUY" in rule_directions:
        agreeing = [s for s in rule_signals if s["signal_type"] == "BUY"][0]
        confidence = int(min(92, ml_conf * 100 * 0.6 + agreeing["confidence"] * 0.4))
        sig = _build_signal(
            symbol, "BUY", "ML_CONFLUENCE",
            f"LightGBM BUY {ml_conf:.0%} + {agreeing['strategy']} agrees",
            confidence, ind, ind["atr_5"],
        )
        sig["ml_score"] = int(ml_conf * 100)
        sig["ml_label"] = ml_label
        signals.append(sig)

    elif ml_label == "SELL" and "SELL" in rule_directions:
        agreeing = [s for s in rule_signals if s["signal_type"] == "SELL"][0]
        confidence = int(min(90, ml_conf * 100 * 0.6 + agreeing["confidence"] * 0.4))
        sig = _build_signal(
            symbol, "SELL", "ML_CONFLUENCE",
            f"LightGBM SELL {ml_conf:.0%} + {agreeing['strategy']} agrees",
            confidence, ind, ind["atr_5"],
        )
        sig["ml_score"] = int(ml_conf * 100)
        sig["ml_label"] = ml_label
        signals.append(sig)

    return signals


# =====================================================
# SCANNER
# =====================================================

def _time_check() -> dict:
    """Check if intraday trading is allowed right now."""
    now = datetime.now()
    t = now.time()

    market_open = dtime(9, 15)
    entry_start = dtime(*NO_ENTRY_BEFORE)
    entry_end = dtime(*NO_ENTRY_AFTER)
    square_off = dtime(*SQUARE_OFF_TIME)
    market_close = dtime(15, 30)

    is_weekday = now.weekday() < 5
    is_market_open = is_weekday and market_open <= t <= market_close
    can_enter = is_weekday and entry_start <= t <= entry_end
    should_square_off = is_weekday and t >= square_off

    return {
        "is_market_open": is_market_open,
        "can_enter": can_enter,
        "should_square_off": should_square_off,
        "current_time": now.strftime("%H:%M"),
        "session": (
            "PRE_MARKET" if t < market_open else
            "OPENING" if t < entry_start else
            "ACTIVE" if t <= entry_end else
            "CLOSING" if t <= market_close else
            "AFTER_HOURS"
        ),
    }


def analyze_stock_intraday(symbol: str) -> dict:
    """
    Run full intraday analysis on one stock.
    Returns: {symbol, indicators, signals, ml_result, status}
    """
    result = {
        "symbol": symbol,
        "signals": [],
        "indicators": {},
        "ml_result": {},
        "status": "OK",
    }

    # Fetch data
    df = fetch_intraday_data(symbol, period="5d")
    if df is None or len(df) < 20:
        result["status"] = f"NO_DATA ({symbol})"
        return result

    # Split into days
    days = split_by_day(df)
    if not days:
        result["status"] = "NO_TRADING_DAYS"
        return result

    # Use last (current/most recent) trading day
    today_date, today_df = days[-1]
    prev_day_df = days[-2][1] if len(days) >= 2 else None

    if len(today_df) < 10:
        result["status"] = "INSUFFICIENT_BARS"
        return result

    # Compute indicators
    ind = compute_indicators(today_df)
    result["indicators"] = ind

    # Pattern Detection on 5-min candles (candlestick patterns are timeframe-agnostic)
    pattern_result = None
    pattern_name = ""
    try:
        from analysis.pattern_detector import detect_all_patterns
        pattern_result = detect_all_patterns(symbol, today_df)
        pattern_name = pattern_result.primary_pattern or ""
        if pattern_name:
            logger.debug(f"  {symbol}: pattern={pattern_name} ({pattern_result.direction} {pattern_result.reliability:.0%})")
    except Exception as e:
        logger.debug(f"  {symbol}: pattern error: {e}")

    # ML prediction (separate from rule-based)
    try:
        ml_result = predict_intraday(today_df, prev_day_df)
        result["ml_result"] = ml_result
    except Exception as e:
        logger.debug(f"ML error {symbol}: {e}")
        ml_result = {}

    # Run rule-based strategies
    rule_signals = []

    if "VWAP_BAND" in ACTIVE:
        rule_signals.extend(strategy_vwap_band(symbol, today_df, ind))

    if "ORB" in ACTIVE:
        rule_signals.extend(strategy_orb(symbol, today_df, ind))

    if "SUPERTREND" in ACTIVE:
        rule_signals.extend(strategy_supertrend(symbol, today_df, ind))

    # ML confluence (needs rule signals first)
    if "ML_CONFLUENCE" in ACTIVE:
        ml_sigs = strategy_ml_confluence(symbol, today_df, ind, ml_result, rule_signals)
        rule_signals.extend(ml_sigs)

    # Apply pattern boost/penalty to all signals
    if pattern_result and pattern_result.primary_pattern:
        for sig in rule_signals:
            patt_dir = pattern_result.direction
            patt_conf = pattern_result.reliability
            sig_direction = sig["signal_type"]

            if (sig_direction == "BUY" and patt_dir == "BULLISH") or \
               (sig_direction == "SELL" and patt_dir == "BEARISH"):
                # Pattern CONFIRMS the signal — boost by up to 8 points
                boost = round(patt_conf * 8, 1)
                sig["overall_score"] = min(95, sig["overall_score"] + boost)
                sig["confidence"]    = min(95, sig["confidence"] + boost)
                sig["pattern"] = pattern_name
                sig["pattern_score"] = round(patt_conf * 100, 1)
            elif (sig_direction == "BUY" and patt_dir == "BEARISH") or \
                 (sig_direction == "SELL" and patt_dir == "BULLISH"):
                # Pattern CONTRADICTS the signal — penalize by up to 6 points
                penalty = round(patt_conf * 6, 1)
                sig["overall_score"] = max(0, sig["overall_score"] - penalty)
                sig["confidence"]    = max(0, sig["confidence"] - penalty)
                sig["pattern"] = pattern_name + "_CONFLICT"
                sig["pattern_score"] = round((1 - patt_conf) * 100, 1)
            else:
                # Neutral pattern — attach for display only
                sig["pattern"] = pattern_name
                sig["pattern_score"] = 50.0

    # Sort by confidence
    rule_signals.sort(key=lambda s: s.get("overall_score", 0), reverse=True)
    result["signals"] = rule_signals

    return result


def scan_intraday_stocks(watchlist: list = None) -> dict:
    """
    Scan all watchlist stocks for intraday signals.
    Returns: {signals: [...], market_status: {...}, stocks: {...}}
    """
    watchlist = watchlist or INTRADAY_WATCHLIST
    time_info = _time_check()

    logger.info(f"Intraday scan: {len(watchlist)} stocks | Session: {time_info['session']}")

    all_signals = []
    stock_data = {}

    for symbol in watchlist:
        try:
            result = analyze_stock_intraday(symbol)
            stock_data[symbol] = {
                "indicators": result["indicators"],
                "ml_result": result["ml_result"],
                "status": result["status"],
                "signal_count": len(result["signals"]),
            }

            if result["signals"]:
                # Only take the best signal per stock
                best = result["signals"][0]
                all_signals.append(best)
                logger.info(
                    f"  {symbol}: {best['signal_type']} {best['strategy']} "
                    f"score={best['overall_score']:.0f}"
                )
            else:
                logger.info(f"  {symbol}: no signals")

        except Exception as e:
            logger.error(f"  {symbol}: scan error - {e}")
            stock_data[symbol] = {"status": f"ERROR: {e}", "indicators": {}, "ml_result": {}}

    # Sort all signals by score
    all_signals.sort(key=lambda s: s.get("overall_score", 0), reverse=True)

    # Cap at max positions
    all_signals = all_signals[:INTRADAY_MAX_POS]

    logger.info(f"Intraday scan complete: {len(all_signals)} signals from {len(watchlist)} stocks")

    return {
        "signals": all_signals,
        "market_status": time_info,
        "stocks": stock_data,
        "scan_time": datetime.now().isoformat(),
    }


# =====================================================
# STANDALONE TEST
# =====================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    print("=" * 55)
    print("  INTRADAY SCALPING ENGINE — Live Test")
    print("=" * 55)

    # Test with a few liquid stocks
    test_stocks = ["RELIANCE", "TCS", "INFY", "SBIN", "HDFCBANK"]

    results = scan_intraday_stocks(test_stocks)

    print(f"\nSession: {results['market_status']['session']}")
    print(f"Time: {results['market_status']['current_time']}")
    print(f"Signals: {len(results['signals'])}")

    for sig in results["signals"]:
        print(f"\n  {sig['signal_type']} {sig['symbol']} [{sig['strategy']}]")
        print(f"    Score: {sig['overall_score']:.0f} | Entry: Rs.{sig['entry']:,.2f}")
        print(f"    Target: Rs.{sig['target']:,.2f} | SL: Rs.{sig['stop_loss']:,.2f}")
        print(f"    R:R = 1:{sig['risk_reward']:.1f} | Reason: {sig['reason']}")

    print("\nStock Indicators:")
    for sym, data in results["stocks"].items():
        ind = data.get("indicators", {})
        ml = data.get("ml_result", {})
        if ind:
            print(f"  {sym}: LTP={ind.get('ltp',0):,.2f} VWAP={ind.get('vwap',0):,.2f} "
                  f"RSI(7)={ind.get('rsi7',0):.0f} ST={ind.get('st_direction',0):+d} "
                  f"ML={ml.get('label','?')} ({ml.get('confidence',0):.0%})")
