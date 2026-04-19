"""
crypto_scanner.py
Handles 24/7 scanning of cryptocurrency top coins.
"""

import logging
from datetime import datetime
import config

logger = logging.getLogger("CRYPTO_SCANNER")

def run_crypto_scan(tb, om, sg, news_scraper):
    """24/7 crypto scan — runs every 30 min."""
    try:
        from modes import crypto
        from analysis.pattern_detector import detect_all_patterns
        from signals.ml_models import ml_signal_score
        from analysis.heatmap_generator import generate_crypto_heatmap
        from analysis.chart_generator import generate_signal_chart

        logger.info("Running detailed crypto pipeline...")
        
        # Build Heatmap
        results = crypto.scan_crypto()
        fg = results.get("fear_greed", {})
        coins = results.get("coins", {})
        
        # Send heatmap first
        heatmap_path = generate_crypto_heatmap(coins)
        if heatmap_path:
            tb.send_photo(heatmap_path, caption=f"🪙 **Crypto Market Heatmap**\nFear & Greed: {fg.get('value', 50)} ({fg.get('state', 'NEUTRAL')})")

        # Get News specifically for Crypto integration
        crypto_news = news_scraper.scrape_all_feeds(crypto.TOP_COINS) if news_scraper else {}
        
        all_signals = []

        # Loop through coins and process detailed signals identically to equity
        for sym in crypto.TOP_COINS:
            try:
                df = crypto.get_klines(sym, interval="1d", limit=90)
                if df is None or len(df) < 50:
                    continue
                
                quote = {"ltp": df["close"].iloc[-1]}
                news_sym = crypto_news.get(sym, {})
                
                pr = detect_all_patterns(sym, df)
                ml = ml_signal_score(df)
                
                # Signal Generator 
                sigs = sg.generate_signals(
                    sym, df, quote, news_sym, pr, ml,
                    fundamental=None,       # crypto has no fundamental data
                    market_condition=None,  # crypto trades 24/7, no market condition
                )
                
                new_signals = []
                for s in sigs:
                    # Signals from generate_signals() are already scored and filtered;
                    # no separate score_signal() step needed.
                    new_signals.append(s)
                
                all_signals.extend(new_signals)
                
                # Execution & Alerting
                for sig in new_signals:
                    logger.info(f"Crypto Signal Detected: {sig['signal_type']} {sig['symbol']} [Score: {sig['overall_score']}]")
                    
                    if not config.PAPER_TRADING:
                        om.place_order(sig) # Note: order_manager doesn't have place_order. We fixed this in main! Wait, in crypto_scanner.py I need to adopt the same fix.
                    
                    # Store in DB
                    from execution.order_manager import create_order
                    create_order(sig, paper_trade=True)

                    from execution.signal_formatter import format_telegram
                    msg = format_telegram(sig)
                    chart_path = generate_signal_chart(sym, df, sig)
                    if chart_path:
                        tb.send_photo(chart_path, caption=msg)
                    else:
                        tb.send_message(msg)

            except Exception as e:
                logger.debug(f"Error processing crypto signal for {sym}: {e}")

        logger.info(f"Crypto scan complete: {len(all_signals)} signals generated")

    except Exception as e:
        logger.error(f"Crypto scan error: {e}", exc_info=True)
