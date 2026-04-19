"""
live_scan_test.py
Runs one complete intelligence scan cycle and shows you exactly what the bot evaluates:
  News → Patterns → ML → Technical → Composite Score → Order decision
"""

import sys, logging
from pathlib import Path

BASE = Path(__file__).parent
for p in [BASE, BASE/"analysis", BASE/"signals", BASE/"execution", BASE/"ingestion"]:
    sys.path.insert(0, str(p))

logging.basicConfig(level=logging.WARNING)  # suppress library noise

import config

print("=" * 60)
print("  TURTLE TRADE — LIVE INTELLIGENCE SCAN TEST")
print("=" * 60)
print(f"  Capital: Rs.{config.TOTAL_CAPITAL:,} | Watchlist: {len(config.WATCHLIST)} stocks")
print(f"  Mode: {'PAPER' if config.PAPER_TRADING else 'LIVE'}")
print("=" * 60)

# Step 1: Get market data
print("\n[1/5] Fetching live market data...")
import data_collector as dc
dc.init_db()
dc.connect_angel()

results = []

for symbol in config.WATCHLIST[:5]:  # Test first 5
    print(f"\n{'--'*25}")
    print(f"  Scanning: {symbol}")
    print(f"{'--'*25}")
    
    try:
        df  = dc.get_historical_data(symbol)
        quote = dc.get_live_quote(symbol) or {}
        if df is None or len(df) < 20:
            print(f"  No data for {symbol} — market may be closed")
            continue
        
        ltp = quote.get("ltp", df["close"].iloc[-1]) if quote else df["close"].iloc[-1]

        close = df["close"]
        
        # Quick indicator calc
        delta = close.diff()
        gain = delta.clip(lower=0).ewm(com=13, adjust=False).mean()
        loss = (-delta.clip(upper=0)).ewm(com=13, adjust=False).mean()
        rsi = (100 - 100/(1 + gain/loss.replace(0,1e-10))).iloc[-1]
        ema9  = close.ewm(span=9,  adjust=False).mean().iloc[-1]
        ema21 = close.ewm(span=21, adjust=False).mean().iloc[-1]
        trend = "UP" if ema9 > ema21 else "DOWN"
        vol_ratio = df["volume"].iloc[-1] / df["volume"].rolling(20).mean().iloc[-1]
        
        print(f"  Price: Rs.{ltp:,.2f}  |  RSI: {rsi:.1f}  |  Trend: {trend}  |  Vol: {vol_ratio:.1f}x avg")

        # Step 2: News sentiment
        print(f"  [NEWS] Checking FinBERT sentiment...")
        news_sentiment = "neutral"
        news_score = 0.5
        news_headline = ""
        try:
            from ingestion.news_scraper import scrape_all_feeds
            news_data = scrape_all_feeds([symbol])
            sym_data = news_data.get(symbol, {})
            news_sentiment = sym_data.get("sentiment", "neutral")
            news_score = sym_data.get("score", 0.5)
            articles = sym_data.get("articles", [])
            news_headline = articles[0].get("title", "")[:80] if articles else "No specific news"
            sentiment_label = {"positive":"🟢 BULLISH","negative":"🔴 BEARISH","neutral":"⚪ NEUTRAL"}.get(news_sentiment, "⚪")
            print(f"  [NEWS] {sentiment_label} ({news_score:.0%}) — \"{news_headline}\"")
        except Exception as e:
            print(f"  [NEWS] ⚪ NEUTRAL (scraper offline: {str(e)[:50]})")

        # Step 3: Pattern detection
        print(f"  [PATTERN] Detecting candlestick patterns...")
        pattern_name = ""
        pattern_score = 50
        pattern_direction = "NEUTRAL"
        try:
            from analysis.pattern_detector import detect_all_patterns
            pr = detect_all_patterns(symbol, df)
            if pr and pr.primary_pattern:
                pattern_name = pr.primary_pattern
                pattern_score = int(pr.reliability * 100)
                pattern_direction = pr.direction
                print(f"  [PATTERN] ✅ {pattern_name} ({pattern_direction}, reliability: {pattern_score}%)")
            else:
                print(f"  [PATTERN] No strong pattern detected")
        except Exception as e:
            print(f"  [PATTERN] ⚠️  Unavailable ({str(e)[:50]})")

        # Step 4: ML prediction
        print(f"  [ML] Running RandomForest + LSTM...")
        ml_label = "UNKNOWN"
        ml_score = 0.5
        try:
            from signals.ml_models import ml_signal_score
            ml = ml_signal_score(df)
            ml_label = ml.get("rf_label", "HOLD")
            ml_score = ml.get("score", 0.5)
            direction_emoji = "🟢" if ml_label == "BUY" else "🔴" if ml_label == "SELL" else "⚪"
            print(f"  [ML] {direction_emoji} RF: {ml_label} | Combined Score: {ml_score:.0%}")
        except Exception as e:
            print(f"  [ML] ⚠️  Not trained yet ({str(e)[:60]})")
            ml_score = 0.5

        # Step 5: Combined scoring
        WEIGHTS = {"technical":0.35, "ml":0.25, "sentiment":0.15, "pattern":0.15, "fundamental":0.10}
        
        # Technical score from RSI + trend
        tech_score = 65
        if rsi < 35: tech_score = 80
        elif rsi > 70: tech_score = 30
        if trend == "UP" and rsi < 65: tech_score = min(85, tech_score + 10)
        if vol_ratio > 1.5: tech_score = min(90, tech_score + 8)
        
        # News score conversion
        news_score_100 = (news_score * 100) if news_sentiment == "positive" else \
                         (100 - news_score * 100) if news_sentiment == "negative" else 50
        
        # ML score
        ml_score_100 = ml_score * 100
        
        # Pattern score
        patt_100 = pattern_score if pattern_direction == "BULLISH" else (100 - pattern_score if pattern_direction == "BEARISH" else 50)
        
        overall = (tech_score    * WEIGHTS["technical"] +
                   ml_score_100  * WEIGHTS["ml"] +
                   news_score_100* WEIGHTS["sentiment"] +
                   patt_100      * WEIGHTS["pattern"] +
                   50            * WEIGHTS["fundamental"])
        
        conviction = "HIGH" if overall >= 80 else "MEDIUM" if overall >= 65 else "LOW"
        will_signal = overall >= 62

        print(f"\n  ┌─ SCORE BREAKDOWN ──────────────────────────")
        print(f"  │  Technical:    {tech_score:>5.0f}/100  (weight 35%)")
        print(f"  │  ML Predict:   {ml_score_100:>5.0f}/100  (weight 25%)")
        print(f"  │  News Sent.:   {news_score_100:>5.0f}/100  (weight 15%)")
        print(f"  │  Pattern:      {patt_100:>5.0f}/100  (weight 15%)")
        print(f"  │  Fundamental:  {50:>5.0f}/100  (weight 10%)")
        print(f"  │  ─────────────────────────────────")
        print(f"  │  OVERALL:      {overall:>5.1f}/100  [{conviction}]")
        print(f"  └───────────────────────────────────────────")

        if will_signal:
            sl_pct = 2.0
            tp_pct = 4.0
            sl = ltp * (1 - sl_pct / 100)
            tp = ltp * (1 + tp_pct / 100)
            risk_amount = config.TOTAL_CAPITAL * config.RISK_PER_TRADE_PCT / 100
            risk_per_share = abs(ltp - sl)
            qty = max(1, int(risk_amount / risk_per_share))
            print(f"\n  🚀 SIGNAL GENERATED!")
            print(f"     Type: BUY {symbol}  [{conviction} CONVICTION]")
            print(f"     Entry:  Rs.{ltp:,.2f}")
            print(f"     Target: Rs.{tp:,.2f}  (+{tp_pct}%)")
            print(f"     SL:     Rs.{sl:,.2f}  (-{sl_pct}%)")
            print(f"     R:R:    1:{tp_pct/sl_pct:.1f}")
            print(f"     Qty:    {qty} shares  |  Investment: Rs.{qty*ltp:,.0f}")
            if news_headline:
                print(f"     News:   \"{news_headline}\"")
            results.append({"symbol": symbol, "score": overall, "conviction": conviction})
        else:
            print(f"\n  ⏭️  SKIP — Score {overall:.0f} below threshold (62)")
            print(f"     Reason: {'RSI overbought' if rsi > 70 else 'Weak momentum' if vol_ratio < 1.2 else 'Low composite score'}")

    except Exception as e:
        print(f"  ❌ Error: {e}")

print("\n" + "=" * 60)
print(f"  SCAN SUMMARY: {len(results)} signal(s) generated")
for r in results:
    print(f"  → {r['symbol']:10} Score: {r['score']:.0f}/100  [{r['conviction']}]")
print("=" * 60)
print("\n  ✅ This is what runs every 5 min during market hours")
print("     Orders are created in DB + sent to Telegram")
print("     Start with: python main.py")
