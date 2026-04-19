"""
options_scanner.py
Handles NSE options analysis at specific intervals.
"""

import logging

logger = logging.getLogger("OPTIONS_SCANNER")

def run_options_scan(tb):
    """Run NSE options analysis at market open and midday."""
    try:
        from modes import options as opt
        logger.info("Running options scan...")
        snap = opt.analyze_options("NIFTY")
        sig  = opt.generate_options_signal(snap)
        if sig:
            msg = (f"⚙️ <b>OPTIONS SIGNAL — {snap.symbol}</b>\n"
                   f"{snap.summary}\n\n"
                   f"Signal: <b>{sig['signal_type']}</b>\n"
                   f"{sig['entry_note']}\n"
                   f"Reason: {sig['reason']}")
            tb.send_message(msg)
            logger.info(f"Options signal: {sig['signal_type']}")
    except Exception as e:
        logger.error(f"Options scan error: {e}")
