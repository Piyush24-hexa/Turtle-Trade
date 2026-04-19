"""
execution/signal_formatter.py
Unified signal formatter for ALL modes (Equity, Options, Crypto, Forex).
Produces both console output and rich Telegram HTML messages.
Combines all layers: Technical + ML + Sentiment + Pattern + Fundamental.
"""

import logging
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class EnrichedSignal:
    """Master signal object combining all intelligence layers."""
    # Core
    symbol: str = ""
    mode: str = "EQUITY"          # EQUITY / OPTIONS / CRYPTO / FOREX
    signal_type: str = "BUY"      # BUY / SELL / BUY_CALL / BUY_PUT
    strategy: str = ""
    reason: str = ""

    # Price
    entry: float = 0.0
    target: float = 0.0
    stop_loss: float = 0.0
    risk_reward: float = 0.0
    return_pct: float = 0.0
    risk_pct: float = 0.0

    # Position
    quantity: int = 0
    investment: float = 0.0
    risk_amount: float = 0.0

    # Scores (0-100)
    technical_score: float = 0.0
    ml_score: float = 0.0
    sentiment_score: float = 0.0
    pattern_score: float = 0.0
    fundamental_score: float = 0.0
    overall_score: float = 0.0    # Combined final score

    # Labels
    trend: str = ""
    rsi: float = 0.0
    pattern: Optional[str] = None
    sentiment: Optional[str] = None
    news_headline: Optional[str] = None
    market_state: Optional[str] = None
    sector_trend: Optional[str] = None
    vix: float = 0.0

    # ML details
    rf_label: str = ""
    rf_confidence: float = 0.0
    lstm_direction: str = ""
    lstm_up_prob: float = 0.0

    # Meta
    confidence: int = 0          # Final 0-100 confidence
    paper_trade: bool = True
    timestamp: str = ""

    # Conviction tier
    conviction: str = "MEDIUM"   # HIGH / MEDIUM / LOW


TIER_EMOJI = {"HIGH": "🔥", "MEDIUM": "📊", "LOW": "📌"}
MODE_EMOJI  = {"EQUITY": "📈", "OPTIONS": "⚙️", "CRYPTO": "🪙", "FOREX": "💱"}
SIGNAL_EMOJI = {"BUY": "🟢", "SELL": "🔴", "BUY_CALL": "🟢", "BUY_PUT": "🔴"}


def _bar(score: float, width: int = 10) -> str:
    """Create a visual progress bar."""
    filled = round(score / 100 * width)
    return "█" * filled + "░" * (width - filled)


def compute_overall_score(sig: EnrichedSignal) -> float:
    """
    Weighted combination of all intelligence layers.
    Returns 0-100 score.
    """
    weights = {
        "technical":   0.35,
        "ml":          0.25,
        "sentiment":   0.15,
        "pattern":     0.15,
        "fundamental": 0.10,
    }
    score = (
        sig.technical_score   * weights["technical"] +
        sig.ml_score          * weights["ml"] +
        sig.sentiment_score   * weights["sentiment"] +
        sig.pattern_score     * weights["pattern"] +
        sig.fundamental_score * weights["fundamental"]
    )
    return round(score, 1)


def enrich_signal(
    raw_signal: dict,
    ml_result: dict = None,
    news_data: dict = None,
    pattern_result=None,
    fundamental=None,
    market_condition=None,
) -> EnrichedSignal:
    """
    Combine raw signal with all intelligence layers into EnrichedSignal.
    """
    sig = EnrichedSignal(
        symbol       = raw_signal.get("symbol", ""),
        mode         = raw_signal.get("mode", "EQUITY"),
        signal_type  = raw_signal.get("signal_type", "BUY"),
        strategy     = raw_signal.get("strategy", ""),
        reason       = raw_signal.get("reason", ""),
        entry        = raw_signal.get("entry", 0.0),
        target       = raw_signal.get("target", 0.0),
        stop_loss    = raw_signal.get("stop_loss", 0.0),
        risk_reward  = raw_signal.get("risk_reward", 0.0),
        return_pct   = raw_signal.get("return_pct", 0.0),
        risk_pct     = raw_signal.get("risk_pct", 0.0),
        quantity     = raw_signal.get("quantity", 0),
        investment   = raw_signal.get("investment", 0.0),
        risk_amount  = raw_signal.get("risk_amount", 0.0),
        trend        = raw_signal.get("trend", ""),
        rsi          = raw_signal.get("rsi", 0.0),
        confidence   = raw_signal.get("confidence", 60),
        paper_trade  = raw_signal.get("paper_trade", True),
        timestamp    = datetime.now().strftime("%H:%M"),
    )

    # Technical score from base confidence
    sig.technical_score = float(raw_signal.get("confidence", 60))

    # ML layer
    if ml_result:
        sig.rf_label = ml_result.get("rf", {}).get("label", "HOLD")
        sig.rf_confidence = ml_result.get("rf", {}).get("confidence", 0.5) * 100
        sig.lstm_direction = ml_result.get("lstm", {}).get("direction", "UNKNOWN")
        sig.lstm_up_prob   = ml_result.get("lstm", {}).get("up_prob", 0.5) * 100
        sig.ml_score       = ml_result.get("score", 0.5) * 100

    # Sentiment layer
    if news_data:
        news_sym = news_data.get(sig.symbol, {})
        sentiment = news_sym.get("sentiment", "neutral")
        sentiment_score = news_sym.get("score", 0.5)
        sig.sentiment = sentiment.upper()
        # Map to 0-100 relative to signal direction
        if sig.signal_type in ("BUY", "BUY_CALL"):
            sig.sentiment_score = sentiment_score * 100 if sentiment == "positive" else \
                                  50 if sentiment == "neutral" else (1 - sentiment_score) * 100
        else:
            sig.sentiment_score = sentiment_score * 100 if sentiment == "negative" else \
                                  50 if sentiment == "neutral" else (1 - sentiment_score) * 100

        articles = news_sym.get("articles", [])
        if articles:
            sig.news_headline = articles[0].get("title", "")[:80]

    # Pattern layer
    if pattern_result and hasattr(pattern_result, "primary_pattern"):
        sig.pattern = pattern_result.primary_pattern
        reliability = pattern_result.reliability * 100
        if pattern_result.direction == "BULLISH" and sig.signal_type == "BUY":
            sig.pattern_score = reliability
        elif pattern_result.direction == "BEARISH" and sig.signal_type == "SELL":
            sig.pattern_score = reliability
        else:
            sig.pattern_score = 100 - reliability

    # Fundamental layer
    if fundamental:
        sig.fundamental_score = fundamental.score * 100

    # Market condition
    if market_condition:
        sig.market_state = market_condition.market_state
        sig.vix = market_condition.vix

    # Overall score
    sig.overall_score = compute_overall_score(sig)

    # Conviction tier
    if sig.overall_score >= 80:
        sig.conviction = "HIGH"
    elif sig.overall_score >= 65:
        sig.conviction = "MEDIUM"
    else:
        sig.conviction = "LOW"

    # Update confidence
    sig.confidence = int(sig.overall_score)

    return sig


def format_telegram(sig: EnrichedSignal) -> str:
    """Format EnrichedSignal as rich Telegram HTML message."""
    s_emoji  = SIGNAL_EMOJI.get(sig.signal_type, "📊")
    m_emoji  = MODE_EMOJI.get(sig.mode, "📊")
    t_emoji  = TIER_EMOJI.get(sig.conviction, "📌")

    buy_sell = "BUY" if "BUY" in sig.signal_type else "SELL"

    lines = [
        f"{s_emoji} <b>{buy_sell} Signal — {sig.symbol}</b>",
        f"{t_emoji} <i>Conviction: {sig.conviction} | Score: {sig.overall_score:.0f}/100</i>",
        f"{m_emoji} Mode: <b>{sig.mode}</b> | Strategy: {sig.strategy}",
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
    ]

    # Score bars
    if sig.technical_score:
        lines.append(f"📐 Technical   <code>{_bar(sig.technical_score)}</code> {sig.technical_score:.0f}%")
    if sig.ml_score:
        lines.append(f"🧠 ML Model    <code>{_bar(sig.ml_score)}</code> {sig.ml_score:.0f}%")
    if sig.sentiment_score:
        lines.append(f"📰 Sentiment   <code>{_bar(sig.sentiment_score)}</code> {sig.sentiment_score:.0f}%")
    if sig.pattern_score:
        lines.append(f"🕯️ Pattern     <code>{_bar(sig.pattern_score)}</code> {sig.pattern_score:.0f}%")
    if sig.fundamental_score:
        lines.append(f"📊 Fundamental <code>{_bar(sig.fundamental_score)}</code> {sig.fundamental_score:.0f}%")

    lines += [
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"💰 Entry:     <b>Rs.{sig.entry:,.2f}</b>",
        f"🎯 Target:    <b>Rs.{sig.target:,.2f}</b> (<b>+{sig.return_pct:.2f}%</b>)",
        f"🛡️  Stop Loss: <b>Rs.{sig.stop_loss:,.2f}</b> (-{sig.risk_pct:.2f}%)",
        f"⚖️  R:R = 1:{sig.risk_reward:.1f}  |  Confidence: {sig.confidence}%",
    ]

    if sig.quantity:
        lines += [
            "",
            f"📦 Position: {sig.quantity} shares",
            f"💵 Investment: Rs.{sig.investment:,.0f}",
            f"⚠️  Risk: Rs.{sig.risk_amount:,.0f}",
        ]

    # Intelligence context
    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    if sig.reason:
        lines.append(f"📝 <i>{sig.reason}</i>")

    if sig.pattern:
        lines.append(f"🕯️ Pattern: <b>{sig.pattern.replace('_',' ')}</b>")

    if sig.rf_label:
        lines.append(f"🤖 RF: <b>{sig.rf_label}</b> ({sig.rf_confidence:.0f}%) | LSTM: <b>{sig.lstm_direction}</b> (↑{sig.lstm_up_prob:.0f}%)")

    if sig.news_headline:
        lines.append(f"📰 <i>\"{sig.news_headline}\"</i>")

    if sig.sentiment:
        sentiment_tag = {"POSITIVE": "🟢 Bullish", "NEGATIVE": "🔴 Bearish", "NEUTRAL": "⚪ Neutral"}.get(sig.sentiment, "")
        lines.append(f"📊 Sentiment: {sentiment_tag}")

    if sig.market_state:
        lines.append(f"🌐 Market: {sig.market_state} | VIX: {sig.vix:.1f}")

    # Footer
    lines += [
        "",
        f"🕐 {sig.timestamp}  |  {'⚠️ PAPER TRADE' if sig.paper_trade else '🔴 LIVE TRADE'}",
    ]

    return "\n".join(lines)


def format_console(sig: EnrichedSignal) -> str:
    """Format for terminal/console output."""
    sep = "=" * 58
    buy_sell = "BUY" if "BUY" in sig.signal_type else "SELL"
    lines = [
        sep,
        f"  {buy_sell} SIGNAL — {sig.symbol}  |  {sig.mode}  |  Score: {sig.overall_score:.0f}/100  [{sig.conviction}]",
        sep,
    ]
    if sig.technical_score:
        lines.append(f"  Technical   [{_bar(sig.technical_score)}] {sig.technical_score:.0f}%")
    if sig.ml_score:
        lines.append(f"  ML Model    [{_bar(sig.ml_score)}] {sig.ml_score:.0f}%")
    if sig.sentiment_score:
        lines.append(f"  Sentiment   [{_bar(sig.sentiment_score)}] {sig.sentiment_score:.0f}%")
    if sig.pattern_score:
        lines.append(f"  Pattern     [{_bar(sig.pattern_score)}] {sig.pattern_score:.0f}%")
    if sig.fundamental_score:
        lines.append(f"  Fundamental [{_bar(sig.fundamental_score)}] {sig.fundamental_score:.0f}%")
    lines += [
        "",
        f"  Entry: Rs.{sig.entry:,.2f}  |  Target: Rs.{sig.target:,.2f} (+{sig.return_pct:.1f}%)  |  SL: Rs.{sig.stop_loss:,.2f}",
        f"  R:R = 1:{sig.risk_reward:.1f}  |  Confidence: {sig.confidence}%  |  Qty: {sig.quantity} shares",
        "",
        f"  {sig.reason}",
        f"  {'[PAPER TRADE]' if sig.paper_trade else '[LIVE TRADE]'}  {sig.timestamp}",
        sep,
    ]
    return "\n".join(lines)
