"""
main.py — Turtle Trade Intelligence Platform v2.0
Full integrated pipeline:
  Data → News → Patterns → ML → Fundamentals → Market Condition → Signals → Orders → Telegram

Runs continuously 24/7. During market hours: full scan every 5 min.
After hours: news + crypto scan every 30 min.
"""

import sys
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

import time
import logging
import threading
from datetime import datetime, time as dtime
from pathlib import Path

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "analysis"))
sys.path.insert(0, str(BASE / "signals"))
sys.path.insert(0, str(BASE / "execution"))
sys.path.insert(0, str(BASE / "ingestion"))
sys.path.insert(0, str(BASE / "modes"))

import config

# Logging — file + console
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
    handlers=[
        logging.FileHandler("trading_bot.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("MAIN")

# ─────────────────────────────────────────────────
# LAZY IMPORTS (loaded once, reused)
# ─────────────────────────────────────────────────
_modules_loaded = False
_dc = _ta = _sg = _tb = _om = None
_news = _patt = _fund = _mc = _ml = None


def _load_modules():
    global _modules_loaded, _dc, _ta, _sg, _tb, _om
    global _news, _patt, _fund, _mc, _ml
    if _modules_loaded:
        return

    logger.info("Loading platform modules...")

    import data_collector as _dc_m;             _dc = _dc_m
    import technical_analyzer as _ta_m;         _ta = _ta_m
    import signal_generator as _sg_m;           _sg = _sg_m
    import telegram_bot as _tb_m;               _tb = _tb_m
    from execution import order_manager as _om_m; _om = _om_m

    try:
        from ingestion import news_scraper as _n; _news = _n
        logger.info("  News scraper loaded (FinBERT will load on first scan)")
    except Exception as e:
        logger.warning(f"  News scraper unavailable: {e}")

    try:
        from analysis import pattern_detector as _p; _patt = _p
        logger.info("  Pattern detector loaded")
    except Exception as e:
        logger.warning(f"  Pattern detector unavailable: {e}")

    try:
        from analysis import fundamental_screener as _f; _fund = _f
        logger.info("  Fundamental screener loaded")
    except Exception as e:
        logger.warning(f"  Fundamental screener unavailable: {e}")

    try:
        from analysis import market_condition as _mc_m; _mc = _mc_m
        logger.info("  Market condition engine loaded")
    except Exception as e:
        logger.warning(f"  Market condition unavailable: {e}")

    try:
        from signals import ml_models as _ml_m; _ml = _ml_m
        logger.info("  ML models loaded")
    except Exception as e:
        logger.warning(f"  ML models unavailable: {e}")

    _modules_loaded = True
    logger.info("All modules ready")


# ─────────────────────────────────────────────────
# MARKET HOURS
# ─────────────────────────────────────────────────
MARKET_OPEN  = dtime(9, 15)
MARKET_CLOSE = dtime(15, 30)


def is_market_open() -> bool:
    if config.PAPER_TRADING:  # Allow scan anytime in paper mode
        return True
    now = datetime.now()
    if now.weekday() >= 5:   # Saturday/Sunday
        return False
    t = now.time()
    return MARKET_OPEN <= t <= MARKET_CLOSE


def is_weekday() -> bool:
    return datetime.now().weekday() < 5





# ─────────────────────────────────────────────────
# MAIN LOOP
# ─────────────────────────────────────────────────

def main():
    logger.info("=" * 55)
    logger.info("  TURTLE TRADE INTELLIGENCE PLATFORM v2.0")
    logger.info("=" * 55)

    _load_modules()

    # Initialize DBs
    _dc.init_db()
    _om.init_orders_db()

    # Angel One connection
    _dc.connect_angel()

    # Send startup message
    _tb.send_message(
        "🐢 <b>Turtle Trade v2.0 STARTED</b>\n"
        f"Mode: {'Paper Trading' if config.PAPER_TRADING else '🔴 LIVE TRADING'}\n"
        f"Capital: Rs.{config.TOTAL_CAPITAL:,.0f}\n"
        f"Watchlist: {len(config.WATCHLIST)} stocks\n"
        "Intelligence: News + Patterns + ML + Fundamentals + Technical ✅"
    )

    logger.info(f"Mode: {'PAPER' if config.PAPER_TRADING else 'LIVE'}")
    logger.info(f"Capital: Rs.{config.TOTAL_CAPITAL:,}")

    scan_count = 0
    options_scan_count = 0
    last_crypto_time = 0

    while True:
        try:
            now = datetime.now()
            market_open = is_market_open()
            current_time = time.time()
            
            # Crypto scan runs globally 24/7 every 30 minutes
            if current_time - last_crypto_time >= 1800:
                from scanners.crypto_scanner import run_crypto_scan
                run_crypto_scan(_tb, _om, _sg, _news)
                last_crypto_time = current_time

            if market_open:
                logger.info(f"Market OPEN — running full scan")
                from scanners.equity_scanner import run_scan_cycle
                run_scan_cycle(_dc, _sg, _tb, _om, {
                    "news": _news, "crypto": None, "mc": _mc,
                    "fund": _fund, "ml": _ml, "patt": _patt
                })
                scan_count += 1

                # Options scan every 2 hours
                if scan_count % 24 == 1:
                    from scanners.options_scanner import run_options_scan
                    run_options_scan(_tb)

                # Wait 5 minutes before next scan
                time.sleep(300)

            elif is_weekday():
                # After/before market hours on weekdays
                t = now.time()
                if dtime(8, 0) <= t < MARKET_OPEN:
                    logger.info("Pre-market: gathering news + options data")
                    from scanners.equity_scanner import gather_news, gather_market_condition
                    gather_news(_news, _tb, None)
                    gather_market_condition(_mc, _tb)
                    from scanners.options_scanner import run_options_scan
                    run_options_scan(_tb)
                    time.sleep(900)  # 15 min
                elif t > MARKET_CLOSE:
                    logger.info("After-market: checking news")
                    from scanners.equity_scanner import gather_news
                    gather_news(_news, _tb, None)
                    # Send daily summary once
                    if options_scan_count == 0:
                        _send_daily_summary()
                        options_scan_count = 1
                    time.sleep(1800)  # 30 min
                else:
                    time.sleep(60)
            else:
                # Weekend
                logger.info("Weekend — news scan only (crypto handled by global timer)")
                from scanners.equity_scanner import gather_news
                gather_news(_news, _tb, None)
                options_scan_count = 0
                time.sleep(1800)  # 30 min

        except KeyboardInterrupt:
            logger.info("Stopping bot (Ctrl+C)")
            _tb.send_message("🛑 Turtle Trade bot stopped by user")
            break
        except Exception as e:
            logger.error(f"Main loop error: {e}", exc_info=True)
            time.sleep(60)


def _send_daily_summary():
    """Send end-of-day performance summary."""
    try:
        stats    = _om.get_stats()
        day_pnl  = _om.get_daily_pnl()
        today_orders = _om.get_today_orders()
        msg = (
            f"📊 <b>Daily Summary — {datetime.now().strftime('%d %b')}</b>\n\n"
            f"Signals today: {len(today_orders)}\n"
            f"Day P&L: <b>Rs.{day_pnl:+.0f}</b>\n\n"
            f"All-time stats:\n"
            f"• Trades: {stats['total_trades']}\n"
            f"• Win Rate: {stats['win_rate']:.0f}%\n"
            f"• Total P&L: Rs.{stats['total_pnl']:+.0f}\n"
            f"• Profit Factor: {stats['profit_factor']:.2f}"
        )
        _tb.send_message(msg)
    except Exception as e:
        logger.error(f"Daily summary error: {e}")


if __name__ == "__main__":
    main()
