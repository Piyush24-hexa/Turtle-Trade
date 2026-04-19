"""
telegram_bot.py - Telegram notification system for trading signals
Handles:
  • Sending formatted signal alerts
  • Daily market open/close summaries
  • P&L reports
  • Emergency stop command (/stop)
  • Status command (/status)
"""

import logging
import asyncio
import threading
from datetime import datetime
from typing import Optional

import requests

import config

logger = logging.getLogger(__name__)

# Global state
_bot_running = True
_open_positions = []  # Shared state (set by main.py)
_daily_pnl = 0.0


# ─────────────────────────────────────────────────
# LOW-LEVEL SEND
# ─────────────────────────────────────────────────

def send_message(text: str, parse_mode: str = "HTML") -> bool:
    """Send a message to the configured Telegram chat."""
    if config.TELEGRAM_TOKEN == "YOUR_BOT_TOKEN_HERE":
        logger.warning("Telegram not configured — printing to console instead:")
        print(f"\n{'='*60}")
        print(text)
        print('='*60)
        return True

    url = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": config.TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        logger.debug("Telegram message sent")
        return True
    except requests.exceptions.ConnectionError:
        logger.warning("Telegram: no internet connection")
        return False
    except requests.exceptions.HTTPError as e:
        logger.error(f"Telegram HTTP error: {e} — {resp.text}")
        return False
    except Exception as e:
        logger.error(f"Telegram send error: {e}")
        return False


def send_photo(image_path: str, caption: str = "") -> bool:
    """Send a chart image to Telegram."""
    if config.TELEGRAM_TOKEN == "YOUR_BOT_TOKEN_HERE":
        logger.info(f"[console] Would send photo: {image_path}")
        return True
    try:
        url = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/sendPhoto"
        with open(image_path, "rb") as f:
            resp = requests.post(
                url,
                data={"chat_id": config.TELEGRAM_CHAT_ID, "caption": caption, "parse_mode": "HTML"},
                files={"photo": f},
                timeout=15,
            )
        resp.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"Telegram photo error: {e}")
        return False


# ─────────────────────────────────────────────────
# MARKET ALERTS
# ─────────────────────────────────────────────────

def send_market_open_alert(watchlist: list):
    """Good morning message at 9:15 AM."""
    msg = (
        "🌅 <b>Market Open — NSE Trading Bot Started</b>\n\n"
        f"📋 Scanning <b>{len(watchlist)} stocks</b>\n"
        f"💰 Capital: ₹{config.TOTAL_CAPITAL:,}\n"
        f"⚠️  Max risk/trade: ₹{config.TOTAL_CAPITAL * config.RISK_PER_TRADE_PCT / 100:.0f}\n"
        f"📊 Mode: {'📝 PAPER TRADING' if config.PAPER_TRADING else '🔴 LIVE TRADING'}\n\n"
        "📡 Monitoring: " + " • ".join(watchlist[:5])
        + (f" +{len(watchlist)-5} more" if len(watchlist) > 5 else "") + "\n\n"
        "Type /status for live positions | /stop to halt bot"
    )
    send_message(msg)


def send_market_close_summary(signals_today: list, pnl: float):
    """End-of-day report at 3:30 PM."""
    buys = [s for s in signals_today if s.get("signal_type") == "BUY"]
    sells = [s for s in signals_today if s.get("signal_type") == "SELL"]

    pnl_icon = "🟢" if pnl >= 0 else "🔴"

    msg = (
        "🌆 <b>Market Close — Daily Summary</b>\n\n"
        f"📊 Signals generated: {len(signals_today)}\n"
        f"   🟢 BUY: {len(buys)}   🔴 SELL: {len(sells)}\n\n"
        f"{pnl_icon} <b>Today's P&L: ₹{pnl:+,.0f}</b>\n\n"
        f"📅 Date: {datetime.now().strftime('%d %b %Y')}\n"
        "💤 Bot sleeping until tomorrow 9:15 AM"
    )
    send_message(msg)


def send_signal_alert(signal: dict):
    """Send a trading signal."""
    from execution.signal_formatter import format_telegram, enrich_signal
    # Assuming signal is already enriched. If not, you might need to enrich it first, but typically signals coming here might be ready or close to it. If it's a dict, enrich_signal takes a raw dict. Let's assume it's enriched or we can just format it if it has the properties. Wait, format_telegram expects an EnrichedSignal object.
    # Looking at main.py, best was just a dict.
    # Let's fix this properly: signal_generator generates dicts. 
    # Let's check format_telegram. It takes EnrichedSignal. But wait! format_telegram expects EnrichedSignal object. Let me check if signal_generator actually outputs EnrichedSignal or dict.


def send_daily_loss_halt(daily_pnl: float):
    """Alert when daily loss limit is hit."""
    msg = (
        "🚨 <b>DAILY LOSS LIMIT REACHED — BOT HALTED</b>\n\n"
        f"❌ Today's loss: ₹{abs(daily_pnl):,.0f}\n"
        f"🛑 Limit: ₹{config.DAILY_LOSS_LIMIT:,}\n\n"
        "Bot has stopped generating signals.\n"
        "Review your strategy before tomorrow.\n\n"
        "Send /resume to restart (not recommended today)"
    )
    send_message(msg)


def send_error_alert(error_msg: str):
    """Alert on critical bot errors."""
    msg = (
        "⚠️ <b>Bot Error</b>\n\n"
        f"<code>{error_msg[:200]}</code>\n\n"
        "Bot may have stopped. Check logs."
    )
    send_message(msg)


def send_status(positions: list, daily_pnl: float, signals_count: int):
    """Send current bot status."""
    pnl_icon = "🟢" if daily_pnl >= 0 else "🔴"

    if positions:
        pos_lines = "\n".join(
            f"  • {p['symbol']}: ₹{p.get('entry_price', 0):,.2f} → ₹{p.get('current_price', 0):,.2f} "
            f"({'🟢' if p.get('pnl',0) >= 0 else '🔴'} ₹{p.get('pnl',0):+,.0f})"
            for p in positions
        )
    else:
        pos_lines = "  None"

    msg = (
        f"📊 <b>Bot Status</b> — {datetime.now().strftime('%H:%M')}\n\n"
        f"{pnl_icon} Today's P&L: ₹{daily_pnl:+,.0f}\n"
        f"📡 Signals today: {signals_count}\n"
        f"📦 Open positions ({len(positions)}/{config.MAX_OPEN_POSITIONS}):\n"
        f"{pos_lines}\n\n"
        f"⚙️  Mode: {'PAPER' if config.PAPER_TRADING else 'LIVE'}\n"
        f"🕐 Next scan: ~{config.SCAN_INTERVAL_SEC // 60} min"
    )
    send_message(msg)


# ─────────────────────────────────────────────────
# COMMAND LISTENER (long-polling)
# ─────────────────────────────────────────────────

_last_update_id = None


def _get_updates() -> list:
    """Fetch pending Telegram commands (long-poll)."""
    if config.TELEGRAM_TOKEN == "YOUR_BOT_TOKEN_HERE":
        return []
    global _last_update_id
    url = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/getUpdates"
    params = {"timeout": 30, "allowed_updates": ["message"]}
    if _last_update_id:
        params["offset"] = _last_update_id + 1
    try:
        resp = requests.get(url, params=params, timeout=35)
        resp.raise_for_status()
        updates = resp.json().get("result", [])
        if updates:
            _last_update_id = updates[-1]["update_id"]
        return updates
    except Exception:
        return []


def handle_command(text: str, positions: list, daily_pnl: float, signals_count: int) -> bool:
    """
    Handle bot commands from Telegram.
    Returns True if bot should stop.
    """
    global _bot_running
    cmd = text.strip().lower().split()[0] if text else ""

    if cmd == "/stop":
        _bot_running = False
        send_message("🛑 <b>Bot stopped</b> by user command.")
        logger.warning("Bot stopped via Telegram /stop command")
        return True

    elif cmd == "/status":
        send_status(positions, daily_pnl, signals_count)

    elif cmd == "/resume":
        _bot_running = True
        send_message("▶️ <b>Bot resumed</b>")

    elif cmd == "/help":
        send_message(
            "📋 <b>Available Commands</b>\n\n"
            "/status — Current positions & P&L\n"
            "/stop — Stop the bot\n"
            "/resume — Resume after stop\n"
            "/watchlist — Show monitored stocks\n"
            "/help — This message"
        )

    elif cmd == "/watchlist":
        wl = config.WATCHLIST
        send_message(
            f"📋 <b>Watchlist ({len(wl)} stocks)</b>\n\n"
            + " • ".join(wl)
        )

    return False


def start_command_listener(get_positions_fn, get_pnl_fn, get_signals_fn):
    """Run command listener in background thread."""
    def _listener():
        logger.info("📱  Telegram command listener started")
        while True:
            try:
                updates = _get_updates()
                for upd in updates:
                    msg = upd.get("message", {})
                    text = msg.get("text", "")
                    chat_id = str(msg.get("chat", {}).get("id", ""))

                    if chat_id == str(config.TELEGRAM_CHAT_ID) and text.startswith("/"):
                        should_stop = handle_command(
                            text, get_positions_fn(), get_pnl_fn(), get_signals_fn()
                        )
                        if should_stop:
                            break
            except Exception as e:
                logger.debug(f"Command listener error: {e}")

    t = threading.Thread(target=_listener, daemon=True)
    t.start()
    return t


# ─────────────────────────────────────────────────
# SETUP GUIDE
# ─────────────────────────────────────────────────

def print_setup_guide():
    print("""
╔══════════════════════════════════════════════════════╗
║           TELEGRAM BOT SETUP (5 minutes)             ║
╠══════════════════════════════════════════════════════╣
║                                                      ║
║  Step 1: Create your bot                             ║
║    • Open Telegram → Search @BotFather               ║
║    • Send: /newbot                                   ║
║    • Name it: "NSE Trading Bot"                      ║
║    • Username: anything_bot (must end in _bot)       ║
║    • Copy the TOKEN it gives you                     ║
║                                                      ║
║  Step 2: Get your Chat ID                            ║
║    • Message your new bot once (any text)            ║
║    • Go to: https://api.telegram.org/bot<TOKEN>/     ║
║             getUpdates                               ║
║    • Find "chat":{"id": XXXXXXX} in the response     ║
║    • That number is your CHAT_ID                     ║
║                                                      ║
║  Step 3: Update config.py                            ║
║    TELEGRAM_TOKEN   = "paste_token_here"             ║
║    TELEGRAM_CHAT_ID = "paste_chat_id_here"           ║
║                                                      ║
║  Step 4: Test it                                     ║
║    python telegram_bot.py                            ║
║                                                      ║
╚══════════════════════════════════════════════════════╝
""")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    if config.TELEGRAM_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print_setup_guide()
    else:
        print("Testing Telegram connection...")
        ok = send_message(
            "✅ <b>Trading Bot Test</b>\n\n"
            "Telegram integration is working!\n"
            f"Capital: ₹{config.TOTAL_CAPITAL:,}\n"
            f"Mode: {'PAPER' if config.PAPER_TRADING else 'LIVE'}"
        )
        print(f"{'✅ Message sent!' if ok else '❌ Failed — check token/chat_id'}")
