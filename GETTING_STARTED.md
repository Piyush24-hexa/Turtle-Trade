# 🚀 NSE Trading Bot — Getting Started Guide

> Complete setup in **15 minutes**. No coding experience needed for setup.

---

## What You've Got

```
e:\TRADEING\
├── config.py              ← Edit THIS first (API keys, capital, settings)
├── main.py                ← Start bot (runs 24/7)
├── data_collector.py      ← Fetches NSE market data
├── technical_analyzer.py  ← RSI, MACD, breakout detection
├── signal_generator.py    ← BUY/SELL signal engine
├── telegram_bot.py        ← Alerts to your phone
├── api_server.py          ← API for dashboard
├── requirements.txt
├── setup.bat              ← Run this first!
└── dashboard/
    └── index.html         ← Open in browser for dashboard
```

---

## Step 1: Run Setup (5 min)

Open **Command Prompt** in `e:\TRADEING\`:

```bat
setup.bat
```

This installs all Python packages automatically.

---

## Step 2: Setup Telegram (5 min)

1. **Open Telegram** → search for **@BotFather**
2. Send `/newbot` → follow instructions → copy the **TOKEN**
3. Message your new bot once (any text)
4. Visit: `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
5. Find `"chat": {"id": 123456789}` → that's your **CHAT_ID**

Then edit `config.py`:
```python
TELEGRAM_TOKEN   = "1234567890:ABCdef..."  # Your token
TELEGRAM_CHAT_ID = "123456789"             # Your chat ID
```

Test it:
```bash
python telegram_bot.py
```
You should receive a test message on Telegram ✅

---

## Step 3: Angel One API Setup (optional, 5 min)

> **Skip this for now** — Yahoo Finance works without any API key!

When ready:
1. Go to https://smartapi.angelbroking.com/
2. Create an app → get API Key
3. Enable TOTP in Angel One app settings  
4. Edit `config.py`:
```python
ANGEL_API_KEY     = "your_api_key"
ANGEL_CLIENT_ID   = "your_client_id"  
ANGEL_PASSWORD    = "your_password"
ANGEL_TOTP_SECRET = "your_totp_secret"
```

---

## Step 4: Test the Bot (2 min)

Run a single scan **without waiting for market hours**:

```bash
python main.py --test
```

Expected output:
```
✅  Config validated OK
📡  Scanning 10 symbols...
   [1/10] Fetching RELIANCE...
   ...
✅  Analyzed 10 symbols
📊  Generated 2 signals from 10 symbols

══════════════════════════════════════════
  ✅  2 SIGNAL(S) FOUND:
══════════════════════════════════════════

🟢 BUY Signal — RELIANCE
Strategy: BREAKOUT
Entry: ₹2847 ...
```

---

## Step 5: Start Bot Live

```bash
python main.py
```

The bot will:
- Sleep until 9:15 AM NSE open
- Send you a "Market Open" message on Telegram
- Scan every 5 minutes
- Send signals to your phone instantly
- Send daily summary at 3:30 PM

---

## Step 6: Open Dashboard

In a **separate** terminal:
```bash
pip install flask flask-cors
python api_server.py
```

Then open in browser:
```
e:\TRADEING\dashboard\index.html
```

> The dashboard also works without the API server using demo data.

---

## Capital & Risk Settings

Edit `config.py` to match your situation:

| Setting | Default | Meaning |
|---------|---------|---------|
| `TOTAL_CAPITAL` | 10,000 | Your trading capital (₹) |
| `RISK_PER_TRADE_PCT` | 2.5% | ₹250 risked per trade |
| `MAX_OPEN_POSITIONS` | 2 | Max simultaneous trades |
| `DAILY_LOSS_LIMIT` | 500 | Bot stops at ₹500 loss/day |
| `PAPER_TRADING` | True | Safe mode (no real orders) |

---

## Safety Rules (READ THIS)

1. **Keep PAPER_TRADING = True** for at least 2 weeks
2. **Never risk more than 3%** of capital per trade
3. **Always use Stop Loss** — the bot sets this automatically
4. **Review signals** before executing manually
5. **Don't trade F&O** with ₹10k — stick to NSE Cash intraday

---

## Commands During Bot Run

Send these to your Telegram bot:
- `/status` → Current positions & P&L
- `/stop` → Emergency halt
- `/resume` → Restart after halt
- `/watchlist` → See monitored stocks
- `/help` → All commands

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `ModuleNotFoundError` | Run `setup.bat` again |
| No Telegram messages | Check TOKEN and CHAT_ID in config.py |
| "No data for SYMBOL" | Yahoo Finance rate limit — wait 30s |
| Bot not generating signals | Normal! Good signals take time. Run `--test` |
| Dashboard shows no data | Start `api_server.py` first |

---

## Deploying to Cloud (Oracle Free Tier)

See `DEPLOYMENT.md` for the full Oracle Cloud setup guide.
One-time setup, bot runs 24/7 for **₹0/month**!

---

**Happy Trading! Remember: Start with paper trading, master the signals, then go live.**

⚠️ *This bot generates signals only. Trade execution is always manual. Not financial advice.*
