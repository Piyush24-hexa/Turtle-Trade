"""
signal_generator.py  (FULLY INTEGRATED VERSION)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Combines ALL intelligence layers into one signal pipeline:
  1. Technical Analysis  (RSI, MACD, BB, EMA, ATR, ADX)
  2. Pattern Detection   (20+ candlestick + chart patterns)
  3. ML Prediction       (Random Forest + LSTM)
  4. News Sentiment      (FinBERT — article-level scoring)
  5. Fundamental Screen  (P/E, EPS growth, ROE, debt)
  6. Market Condition    (VIX, trend filter, sector bias)

Each signal gets a composite 0-100 score. Only signals above the
threshold are sent. All signals are logged as orders in the DB.
"""

import logging
import sys
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

# Path setup
BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR / "analysis"))
sys.path.insert(0, str(BASE_DIR / "signals"))
sys.path.insert(0, str(BASE_DIR / "execution"))
sys.path.insert(0, str(BASE_DIR / "ingestion"))

import config

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────
# SCORE WEIGHTS
# ─────────────────────────────────────────────────
WEIGHTS = {
    "technical":   0.35,
    "ml":          0.25,
    "sentiment":   0.15,
    "pattern":     0.15,
    "fundamental": 0.10,
}

MIN_SCORE_TO_SIGNAL = 62      # Only alert if score ≥ 62/100
MAX_OPEN_POSITIONS  = config.MAX_OPEN_POSITIONS

# ─────────────────────────────────────────────────
# TECHNICAL STRATEGIES (original logic, preserved)
# ─────────────────────────────────────────────────

def _calc_rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0).ewm(com=period-1, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(com=period-1, adjust=False).mean()
    rs = gain / loss.replace(0, 1e-10)
    return 100 - 100 / (1 + rs)


def _run_technical_strategies(symbol, df, quote):
    """Original rule-based strategies. Returns list of raw signal dicts."""
    import numpy as np
    signals = []
    if df is None or len(df) < 30:
        return signals

    # ── Compute indicators ──
    close  = df["close"]
    high   = df["high"]
    low    = df["low"]
    volume = df["volume"]

    rsi   = _calc_rsi(close).iloc[-1]
    ema9  = close.ewm(span=9,  adjust=False).mean()
    ema21 = close.ewm(span=21, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean()

    macd_fast = close.ewm(span=12, adjust=False).mean()
    macd_slow = close.ewm(span=26, adjust=False).mean()
    macd      = macd_fast - macd_slow
    macd_sig  = macd.ewm(span=9, adjust=False).mean()
    macd_hist = (macd - macd_sig).iloc[-1]

    bb_mid  = close.rolling(20).mean()
    bb_std  = close.rolling(20).std()
    bb_up   = (bb_mid + 2*bb_std).iloc[-1]
    bb_low  = (bb_mid - 2*bb_std).iloc[-1]
    bb_pos  = (close.iloc[-1] - bb_low) / (bb_up - bb_low + 1e-10)

    tr = abs(high - low).combine(abs(high - close.shift()), max).combine(abs(low - close.shift()), max)
    atr = tr.ewm(com=13, adjust=False).mean().iloc[-1]

    vol_avg   = volume.rolling(20).mean().iloc[-1]
    vol_ratio = volume.iloc[-1] / vol_avg if vol_avg > 0 else 1.0

    ltp     = quote.get("ltp", close.iloc[-1]) if quote else close.iloc[-1]
    prev20h = high.rolling(20).max().iloc[-2]
    prev20l = low.rolling(20).min().iloc[-2]

    # Support/Resistance
    highs = high.rolling(5).max()
    lows  = low.rolling(5).min()
    resistance = highs.iloc[-10:-1].max()
    support    = lows.iloc[-10:-1].min()

    trend = ("UPTREND"   if ema9.iloc[-1] > ema21.iloc[-1] > ema50.iloc[-1] else
             "DOWNTREND" if ema9.iloc[-1] < ema21.iloc[-1] < ema50.iloc[-1] else "SIDEWAYS")

    def _signal(stype, strategy, reason, confidence, entry=None, sl_pct=None, tp_pct=None):
        ep = entry or ltp
        sl_p = sl_pct or config.DEFAULT_SL_PCT
        tp_p = tp_pct or config.DEFAULT_TP_PCT
        if stype == "BUY":
            sl = ep * (1 - sl_p/100)
            tp = ep * (1 + tp_p/100)
        else:
            sl = ep * (1 + sl_p/100)
            tp = ep * (1 - tp_p/100)
        rr = tp_p / sl_p

        if rr < config.MIN_RISK_REWARD:
            return None

        risk_amount = config.TOTAL_CAPITAL * config.RISK_PER_TRADE_PCT / 100
        risk_per_share = abs(ep - sl)
        qty = max(1, int(risk_amount / risk_per_share)) if risk_per_share > 0 else 1
        investment = qty * ep

        if investment > config.TOTAL_CAPITAL * 0.55:
            qty = max(1, int(config.TOTAL_CAPITAL * 0.50 / ep))
            investment = qty * ep

        return {
            "symbol": symbol, "signal_type": stype, "strategy": strategy,
            "reason": reason, "confidence": confidence, "mode": "EQUITY",
            "entry": round(ep, 2), "target": round(tp, 2), "stop_loss": round(sl, 2),
            "risk_reward": round(rr, 2), "return_pct": round(tp_p, 2), "risk_pct": round(sl_p, 2),
            "quantity": qty, "investment": round(investment, 2),
            "risk_amount": round(qty * risk_per_share, 2),
            "trend": trend, "rsi": round(rsi, 1),
            "paper_trade": config.PAPER_TRADING,
        }

    # ── Strategy 1: Breakout ──
    if "BREAKOUT" in getattr(config, "ACTIVE_STRATEGIES", []) and (ltp > prev20h * 1.001 and vol_ratio >= 1.5
            and trend in ("UPTREND", "SIDEWAYS") and rsi < 75):
        s = _signal("BUY", "BREAKOUT",
                    f"Breakout above Rs.{prev20h:.0f} | Vol {vol_ratio:.1f}x | {trend}",
                    70, sl_pct=2.0, tp_pct=4.0)
        if s: signals.append(s)

    # ── Strategy 2: RSI Reversal ──
    if "RSI_REVERSAL" in getattr(config, "ACTIVE_STRATEGIES", []):
        # RSI oversold, MACD histogram is improving (curling up), price closed higher
        macd_improving = macd_hist > df["macd_hist"].iloc[-2]
        macd_worsening = macd_hist < df["macd_hist"].iloc[-2]
        
        if rsi < 35 and macd_improving and close.iloc[-1] > close.iloc[-2]:
            s = _signal("BUY", "RSI_REVERSAL",
                        f"RSI {rsi:.0f} oversold | MACD momentum shifting up",
                        68, sl_pct=1.8, tp_pct=3.5)
            if s: signals.append(s)
        elif rsi > 65 and macd_worsening and close.iloc[-1] < close.iloc[-2]:
            s = _signal("SELL", "RSI_REVERSAL",
                        f"RSI {rsi:.0f} overbought | MACD momentum shifting down",
                        65, sl_pct=1.8, tp_pct=3.5)
            if s: signals.append(s)

    # ── Strategy 3: EMA Crossover ──
    if "EMA_CROSSOVER" in getattr(config, "ACTIVE_STRATEGIES", []):
        # Check if crossed within the last 3 days
        bull_cross_recent = any((ema9.iloc[-i] > ema21.iloc[-i]) and (ema9.iloc[-i-1] <= ema21.iloc[-i-1]) for i in range(1, 4))
        bear_cross_recent = any((ema9.iloc[-i] < ema21.iloc[-i]) and (ema9.iloc[-i-1] >= ema21.iloc[-i-1]) for i in range(1, 4))
        
        if bull_cross_recent and ema9.iloc[-1] > ema21.iloc[-1] and rsi < 70 and macd_hist > 0:
            s = _signal("BUY", "EMA_CROSS",
                        f"EMA 9 > EMA 21 (recent cross) | RSI {rsi:.0f}",
                        72, sl_pct=2.0, tp_pct=4.0)
            if s: signals.append(s)
        elif bear_cross_recent and ema9.iloc[-1] < ema21.iloc[-1] and rsi > 35 and macd_hist < 0:
            s = _signal("SELL", "EMA_CROSS",
                        f"EMA 9 < EMA 21 (recent cross) | RSI {rsi:.0f}",
                        68, sl_pct=2.0, tp_pct=4.0)
            if s: signals.append(s)

    # ── Strategy 4: S/R Bounce ──
    dist_support    = abs(ltp - support) / ltp
    dist_resistance = abs(ltp - resistance) / ltp
    if "SR_BOUNCE" in getattr(config, "ACTIVE_STRATEGIES", []):
        macd_improving = macd_hist > df["macd_hist"].iloc[-2]
        macd_worsening = macd_hist < df["macd_hist"].iloc[-2]
        
        if dist_support < 0.015 and rsi < 55 and macd_improving:
            s = _signal("BUY", "SR_BOUNCE",
                        f"Support bounce near Rs.{support:.0f} | MACD curling up",
                        65, sl_pct=2.0, tp_pct=max(3.0, dist_resistance*100*0.9))
            if s: signals.append(s)
        elif dist_resistance < 0.015 and rsi > 50 and macd_worsening:
            s = _signal("SELL", "SR_BOUNCE",
                        f"Resistance rejection near Rs.{resistance:.0f} | MACD curling down",
                        62, sl_pct=1.8, tp_pct=max(3.0, dist_support*100*0.9))
            if s: signals.append(s)

    # ── Strategy 5: BB Squeeze breakout ──
    bb_width = (bb_up - bb_low) / close.iloc[-1]
    prev_bb_width = ((bb_mid + 2*bb_std).iloc[-6] - (bb_mid - 2*bb_std).iloc[-6]) / close.iloc[-6]
    if "BB_SQUEEZE" in getattr(config, "ACTIVE_STRATEGIES", []) and bb_width < prev_bb_width * 0.7 and vol_ratio > 2.0:
        if close.iloc[-1] > bb_mid.iloc[-1] and trend != "DOWNTREND":
            s = _signal("BUY", "BB_SQUEEZE",
                        f"BB squeeze breakout upward | Vol {vol_ratio:.1f}x surge",
                        73, sl_pct=2.0, tp_pct=4.0)
            if s: signals.append(s)

    return signals


# ─────────────────────────────────────────────────
# INTELLIGENCE ENRICHMENT
# ─────────────────────────────────────────────────

def _get_news_score(symbol: str, news_data: dict, signal_type: str) -> tuple[float, str, str]:
    """Extract sentiment score for this symbol. Returns (score_0_100, sentiment, headline)."""
    if not news_data:
        return 50.0, "neutral", ""
    sym_data = news_data.get(symbol, {})
    sentiment = sym_data.get("sentiment", "neutral")
    raw_score = sym_data.get("score", 0.5)  # 0-1
    articles  = sym_data.get("articles", [])
    headline  = articles[0].get("title", "") if articles else ""

    # Convert to 0-100 relative to signal direction
    if signal_type in ("BUY", "BUY_CALL"):
        if sentiment == "positive":
            score = 50 + raw_score * 50   # 50-100
        elif sentiment == "negative":
            score = 50 - raw_score * 50   # 0-50
        else:
            score = 50.0
    else:  # SELL
        if sentiment == "negative":
            score = 50 + raw_score * 50
        elif sentiment == "positive":
            score = 50 - raw_score * 50
        else:
            score = 50.0

    return round(score, 1), sentiment, headline[:100]


def _get_pattern_score(pattern_result, signal_type: str) -> tuple[float, str]:
    """Extract pattern score. Returns (score_0_100, pattern_name)."""
    if not pattern_result or not hasattr(pattern_result, "primary_pattern"):
        return 50.0, ""
    if not pattern_result.primary_pattern:
        return 50.0, ""

    rel = pattern_result.reliability * 100
    direction = pattern_result.direction

    if signal_type in ("BUY", "BUY_CALL"):
        score = rel if direction == "BULLISH" else (100 - rel if direction == "BEARISH" else 50)
    else:
        score = rel if direction == "BEARISH" else (100 - rel if direction == "BULLISH" else 50)

    return round(score, 1), pattern_result.primary_pattern


def _get_ml_score(ml_result: dict, signal_type: str) -> float:
    """Extract ML score. Returns 0-100."""
    if not ml_result:
        return 50.0
    raw = ml_result.get("score", 0.5)  # 0-1
    # raw > 0.6 = bullish, < 0.4 = bearish
    if signal_type in ("BUY", "BUY_CALL"):
        score = raw * 100
    else:
        score = (1 - raw) * 100
    return round(score, 1)


def _get_fundamental_score(fundamental) -> float:
    """Extract fundamental score. Returns 0-100."""
    if not fundamental:
        return 50.0
    return round(fundamental.score * 100, 1)


def _compute_overall_score(tech_score, ml_score, news_score, patt_score, fund_score):
    """Weighted composite score 0-100."""
    return round(
        tech_score   * WEIGHTS["technical"] +
        ml_score     * WEIGHTS["ml"] +
        news_score   * WEIGHTS["sentiment"] +
        patt_score   * WEIGHTS["pattern"] +
        fund_score   * WEIGHTS["fundamental"],
        1
    )


def _conviction(score: float) -> str:
    if score >= 80: return "HIGH"
    elif score >= 65: return "MEDIUM"
    return "LOW"


# ─────────────────────────────────────────────────
# NEWS-DRIVEN SIGNAL GENERATOR
# ─────────────────────────────────────────────────

def _generate_news_signal(symbol: str, news_data: dict, df, quote, ltp: float) -> Optional[dict]:
    """
    Generate a signal triggered primarily by a strong news catalyst.
    Requires FinBERT score >= 0.80 AND technical confirmation.
    """
    if not news_data:
        return None
    sym_data = news_data.get(symbol, {})
    sentiment = sym_data.get("sentiment", "neutral")
    score = sym_data.get("score", 0)
    impact = sym_data.get("impact", "LOW")
    articles = sym_data.get("articles", [])
    headline = articles[0].get("title", "") if articles else ""

    if score < 0.80 or impact not in ("HIGH", "MEDIUM"):
        return None
    if not articles:
        return None

    # Require basic technical confirmation
    if df is None or len(df) < 10:
        return None
    close = df["close"]
    rsi = _calc_rsi(close).iloc[-1]
    ema9  = close.ewm(span=9, adjust=False).mean().iloc[-1]
    ema21 = close.ewm(span=21, adjust=False).mean().iloc[-1]

    signal_type = None
    if sentiment == "positive" and rsi < 70 and ema9 >= ema21 * 0.995:
        signal_type = "BUY"
    elif sentiment == "negative" and rsi > 35 and ema9 <= ema21 * 1.005:
        signal_type = "SELL"

    if not signal_type:
        return None

    sl_pct = 2.0
    tp_pct = 4.0
    ep = ltp
    sl = ep * (1 - sl_pct/100) if signal_type == "BUY" else ep * (1 + sl_pct/100)
    tp = ep * (1 + tp_pct/100) if signal_type == "BUY" else ep * (1 - tp_pct/100)

    risk_amount = config.TOTAL_CAPITAL * config.RISK_PER_TRADE_PCT / 100
    risk_per_share = abs(ep - sl)
    qty = max(1, int(risk_amount / risk_per_share)) if risk_per_share > 0 else 1

    news_score_100 = score * 100
    overall = _compute_overall_score(60, 50, news_score_100, 50, 50)

    return {
        "symbol": symbol, "signal_type": signal_type,
        "strategy": "NEWS_CATALYST", "mode": "EQUITY",
        "reason": f"News catalyst: {headline[:80]} | Sentiment: {sentiment.upper()} ({score:.0%})",
        "confidence": int(overall), "overall_score": overall,
        "technical_score": 60, "ml_score": 50,
        "sentiment_score": news_score_100, "pattern_score": 50, "fundamental_score": 50,
        "conviction": _conviction(overall),
        "entry": round(ep, 2), "target": round(tp, 2), "stop_loss": round(sl, 2),
        "risk_reward": round(tp_pct/sl_pct, 2), "return_pct": tp_pct, "risk_pct": sl_pct,
        "quantity": qty, "investment": round(qty*ep, 2), "risk_amount": round(qty*risk_per_share, 2),
        "rsi": round(rsi, 1), "paper_trade": config.PAPER_TRADING,
        "news_headline": headline, "sentiment": sentiment.upper(),
    }


# ─────────────────────────────────────────────────
# MASTER SIGNAL GENERATOR
# ─────────────────────────────────────────────────

def generate_signals(
    symbol: str,
    df,
    quote: dict,
    news_data: dict = None,
    pattern_result=None,
    ml_result: dict = None,
    fundamental=None,
    market_condition=None,
    already_open: int = 0,
) -> list:
    """
    Full signal generation pipeline for one symbol.
    Returns list of enriched signal dicts (filtered by score).
    """
    signals = []

    if already_open >= MAX_OPEN_POSITIONS:
        logger.debug(f"  {symbol}: skipped — max positions open ({MAX_OPEN_POSITIONS})")
        return signals

    ltp = quote.get("ltp", df["close"].iloc[-1]) if quote and df is not None else 0

    # ── Market condition filter ──
    if market_condition:
        try:
            from market_condition import should_trade
            ok, reason = should_trade(market_condition, "BUY")
            if not ok:
                logger.debug(f"  {symbol}: market filter blocked — {reason}")
                return signals
        except Exception:
            pass

    # ── 1. Technical strategies ──
    raw_signals = _run_technical_strategies(symbol, df, quote)

    # ── 2. News-driven signal ──
    news_sig = _generate_news_signal(symbol, news_data, df, quote, ltp)
    if news_sig:
        raw_signals.append(news_sig)

    if not raw_signals:
        return signals

    # ── 3. Enrich each raw signal ──
    for raw in raw_signals:
        try:
            tech_score = float(raw.get("confidence", 60))

            ml_s     = _get_ml_score(ml_result, raw["signal_type"])
            news_s, sentiment, headline = _get_news_score(symbol, news_data, raw["signal_type"])
            patt_s, pattern_name = _get_pattern_score(pattern_result, raw["signal_type"])
            fund_s   = _get_fundamental_score(fundamental)

            overall  = _compute_overall_score(tech_score, ml_s, news_s, patt_s, fund_s)

            # Skip low-conviction signals
            if overall < MIN_SCORE_TO_SIGNAL:
                logger.debug(f"  {symbol} {raw['strategy']}: score {overall:.0f} < {MIN_SCORE_TO_SIGNAL} — skipped")
                continue

            # Merge enrichment into signal
            enriched = {
                **raw,
                "overall_score":      overall,
                "technical_score":    tech_score,
                "ml_score":           ml_s,
                "sentiment_score":    news_s,
                "pattern_score":      patt_s,
                "fundamental_score":  fund_s,
                "conviction":         _conviction(overall),
                "confidence":         int(overall),
                "sentiment":          sentiment.upper(),
                "news_headline":      headline or raw.get("news_headline", ""),
                "pattern":            pattern_name or raw.get("pattern", ""),
                "rf_label":           ml_result.get("rf", {}).get("label", "") if ml_result else "",
                "rf_confidence":      ml_result.get("rf", {}).get("confidence", 0) if ml_result else 0,
                "lstm_direction":     ml_result.get("lstm", {}).get("direction", "") if ml_result else "",
                "lstm_up_prob":       ml_result.get("lstm", {}).get("up_prob", 0) if ml_result else 0,
                "market_state":       getattr(market_condition, "market_state", "") if market_condition else "",
                "vix":                getattr(market_condition, "vix", 0) if market_condition else 0,
                "timestamp":          datetime.now().strftime("%H:%M"),
            }

            # ── 4. AI Committee Evaluation (Optional / Fallback to None if not configured) ──
            try:
                import ai_agents.committee as committee
                logger.info(f"  {symbol}: Requesting AI Committee evaluation...")
                # We copy the enriched dict without heavy references if any, but it's mostly primitives
                ai_verdict = committee.evaluate_signal(enriched)
                enriched["ai_committee"] = ai_verdict
                if ai_verdict.get("final_decision") == "REJECTED":
                    # We can penalize the score or drop it. Let's just drop it or mark it.
                    logger.warning(f"  {symbol}: AI Committee REJECTED the signal.")
                    enriched["conviction"] = "REJECTED_BY_AI"
                    overall = overall * 0.5  # Heavy penalty
                    enriched["overall_score"] = overall
                elif ai_verdict.get("final_decision") == "APPROVED":
                    logger.info(f"  {symbol}: AI Committee APPROVED the signal.")
            except Exception as ai_e:
                logger.error(f"  {symbol}: AI Committee failed: {ai_e}")
                enriched["ai_committee"] = None

            signals.append(enriched)
            logger.info(f"  SIGNAL {symbol} {raw['signal_type']} score={overall:.0f} [{enriched['conviction']}]")

        except Exception as e:
            logger.error(f"  Enrichment error {symbol}: {e}")

    # Sort by overall score
    signals.sort(key=lambda s: s.get("overall_score", 0), reverse=True)
    return signals




def calculate_position(entry: float, sl: float, capital: float = None, risk_pct: float = None) -> dict:
    capital  = capital  or config.TOTAL_CAPITAL
    risk_pct = risk_pct or config.RISK_PER_TRADE_PCT
    risk_amt = capital * risk_pct / 100
    risk_per_share = abs(entry - sl)
    qty = max(1, int(risk_amt / risk_per_share)) if risk_per_share > 0 else 1
    return {
        "quantity": qty,
        "investment": round(qty * entry, 2),
        "risk_amount": round(qty * risk_per_share, 2),
    }
