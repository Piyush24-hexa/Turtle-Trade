"""
equity_scanner.py
Handles regular market hour scans for equity signals.
"""

import sys
import time
import logging
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))

import config

logger = logging.getLogger("EQUITY_SCANNER")

# State tracking caches
_news_cache = {}
_news_cache_time = 0
_fundamental_cache = {}
_fundamental_cache_time = 0
_market_cond_cache = None
_market_cond_time = 0


def gather_news(news_scraper, tb, crypto_module) -> dict:
    global _news_cache, _news_cache_time
    if not news_scraper:
        return {}
    if time.time() - _news_cache_time < 1800:  # 30 min cache
        return _news_cache
    try:
        logger.info("Scanning news feeds (FinBERT)...")
        combined_watchlist = config.WATCHLIST + (crypto_module.TOP_COINS if crypto_module else [])
        results = news_scraper.scrape_all_feeds(combined_watchlist)
        _news_cache = results
        _news_cache_time = time.time()

        # Telegram alert for political news
        alerts = results.get("_political_alerts", [])
        for alert in alerts[:2]:
            msg = f"🏛️ <b>POLITICAL/MACRO ALERT</b>\n{alert.get('title','')}"
            tb.send_message(msg)

        logger.info(f"News scan complete: {len(results.get('_all_articles', []))} articles")
    except Exception as e:
        logger.error(f"News scan error: {e}")
    return _news_cache


def gather_market_condition(mc_module, tb):
    global _market_cond_cache, _market_cond_time
    if not mc_module:
        return None
    if time.time() - _market_cond_time < 900:  # 15 min
        return _market_cond_cache
    try:
        logger.info("Assessing market condition...")
        mc = mc_module.get_market_condition()
        _market_cond_cache = mc
        _market_cond_time = time.time()
        logger.info(f"Market: {mc.summary}")
        if mc.trade_filter == "AVOID":
            tb.send_message(f"⚠️ <b>MARKET ALERT</b>\nVIX {mc.vix:.0f} — Extreme fear. Trading paused.")
        return mc
    except Exception as e:
        logger.error(f"Market condition error: {e}")
    return None


def gather_fundamentals(fund_module) -> dict:
    global _fundamental_cache, _fundamental_cache_time
    if not fund_module:
        return {}
    if time.time() - _fundamental_cache_time < 21600:  # 6 hours
        return _fundamental_cache
    try:
        logger.info("Running fundamental screen...")
        results = fund_module.screen_all(config.WATCHLIST)
        _fundamental_cache = results
        _fundamental_cache_time = time.time()
    except Exception as e:
        logger.error(f"Fundamental screen error: {e}")
    return _fundamental_cache


def get_ml_prediction(ml_module, df, symbol: str) -> dict:
    if not ml_module:
        return {}
    try:
        return ml_module.ml_signal_score(df)
    except Exception as e:
        logger.debug(f"ML error {symbol}: {e}")
        return {}


def get_pattern(patt_module, symbol: str, df) -> object:
    if not patt_module:
        return None
    try:
        return patt_module.detect_all_patterns(symbol, df)
    except Exception as e:
        logger.debug(f"Pattern error {symbol}: {e}")
        return None


def run_scan_cycle(dc, sg, tb, om, modules):
    """
    Full intelligence scan cycle.
    """
    news_scraper = modules.get("news")
    crypto_module = modules.get("crypto")
    mc_module = modules.get("mc")
    fund_module = modules.get("fund")
    ml_module = modules.get("ml")
    patt_module = modules.get("patt")
    
    logger.info("=" * 55)
    logger.info(f"SCAN CYCLE — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 55)

    # ── Verify Daily Loss Limit ──
    day_pnl = om.get_daily_pnl()
    if day_pnl <= -config.DAILY_LOSS_LIMIT:
        logger.critical(f"🚨 DAILY LOSS LIMIT HIT: ₹{day_pnl:.2f}")
        tb.send_message(f"🛑 TRADING HALTED\nDaily loss limit hit: ₹{day_pnl:.2f}")
        return []

    # ── Gather shared intelligence ──
    market_cond  = gather_market_condition(mc_module, tb)
    news_data    = gather_news(news_scraper, tb, crypto_module)
    fundamentals = gather_fundamentals(fund_module)

    # ── Check how many positions already open ──
    open_orders  = om.get_open_orders()
    already_open = len(open_orders)

    # ── Update P&L on open positions ──
    for order in open_orders:
        try:
            sym = order["symbol"]
            df = dc.get_historical_data(sym, days=15, interval=config.INTRADAY_INTERVAL)
            quote = dc.get_live_quote(sym) or {}
            if quote:
                close_reason = om.update_unrealized_pnl(order["id"], quote.get("ltp", order["current_price"]))
                if close_reason:
                    msg = (f"{'✅' if close_reason=='TARGET_HIT' else '🛡'} <b>ORDER CLOSED: {close_reason}</b>\n"
                           f"{sym} — #{order['id']}\n"
                           f"{'Target' if close_reason == 'TARGET_HIT' else 'Stop Loss'} reached!")
                    tb.send_message(msg)
        except Exception as e:
            logger.error(f"P&L update error {order.get('symbol')}: {e}")

    # ── Scan each symbol ──
    all_signals = []
    ml_cache = []

    for symbol in config.WATCHLIST:
        try:
            logger.info(f"  Scanning {symbol}...")

            # Data collection
            df = dc.get_historical_data(symbol, days=15, interval=config.INTRADAY_INTERVAL)
            quote = dc.get_live_quote(symbol) or {}
            if df is None or len(df) < 20:
                logger.warning(f"    No data for {symbol}")
                continue

            # Intelligence for this symbol
            ml_result    = get_ml_prediction(ml_module, df, symbol)
            if ml_result:
                ml_cache.append({
                    "symbol": symbol,
                    "rf_label": ml_result.get("rf", {}).get("label", ""),
                    "rf_confidence": ml_result.get("rf", {}).get("confidence", 0),
                    "lstm_direction": ml_result.get("lstm", {}).get("direction", ""),
                    "lstm_up_prob": ml_result.get("lstm", {}).get("up_prob", 0),
                    "score": ml_result.get("score", 0)
                })
                
            pattern_res  = get_pattern(patt_module, symbol, df)
            fundamental  = fundamentals.get(symbol)

            # Generate signals (fully enriched)
            signals = sg.generate_signals(
                symbol=symbol, df=df, quote=quote,
                news_data=news_data,
                pattern_result=pattern_res,
                ml_result=ml_result,
                fundamental=fundamental,
                market_condition=market_cond,
                already_open=already_open,
            )

            if signals:
                best = signals[0]  # Highest scored signal
                all_signals.append(best)

                # Create order in DB
                order_id = om.create_order(best, paper_trade=config.PAPER_TRADING)
                logger.info(f"    Order #{order_id} created: {best['signal_type']} {symbol} score={best['overall_score']:.0f}")

                # Send Telegram alert
                from execution.signal_formatter import format_telegram
                msg = format_telegram(best)
                try:
                    from analysis.chart_generator import generate_signal_chart
                    img_path = generate_signal_chart(symbol, df, best)
                    if img_path:
                        tb.send_photo(img_path, caption=msg)
                    else:
                        tb.send_message(msg)
                except Exception as e:
                    logger.error(f"Failed to attach chart for {symbol}: {e}")
                    tb.send_message(msg)

                # Auto-accept paper trades as "placed"
                if config.PAPER_TRADING:
                    om.update_status(order_id, "PLACED", "Auto-placed in paper trading mode")

        except Exception as e:
            logger.error(f"  Error scanning {symbol}: {e}", exc_info=True)

    if ml_cache:  # Only overwrite if we have fresh data — never wipe with empty results
        try:
            import json
            ml_path = BASE / "models" / "ml_cache.json"
            with open(ml_path, "w") as f:
                json.dump({"predictions": ml_cache}, f)
        except Exception as e:
            logger.error(f"Failed to write ML cache: {e}")
    else:
        logger.warning("ML cache NOT updated — no ML results this scan (model may not be trained yet)")

    # ── Scan summary ──
    if all_signals:
        day_pnl = om.get_daily_pnl()
        stats   = om.get_stats()
        summary = (
            f"📊 <b>Scan Complete</b> — {datetime.now().strftime('%H:%M')}\n"
            f"Signals: {len(all_signals)} | Open: {already_open}/{config.MAX_OPEN_POSITIONS}\n"
            f"Day P&L: Rs.{day_pnl:+.0f} | Win Rate: {stats.get('win_rate',0):.0f}%\n"
            f"Market: {getattr(market_cond,'market_state','?')} | VIX: {getattr(market_cond,'vix',0):.1f}"
        )
        tb.send_message(summary)

    logger.info(f"Scan complete: {len(all_signals)} signals generated")
    return all_signals
