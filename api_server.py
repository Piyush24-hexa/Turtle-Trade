"""
api_server.py - Flask API server for the Turtle Trade Bloomberg Dashboard
Serves trading data + static dashboard files at http://localhost:5001
Run: python api_server.py

Endpoints:
  GET  /                → Dashboard HTML
  GET  /market          → Nifty, VIX, market state
  GET  /signals         → Today's generated signals
  GET  /news            → Live news + FinBERT sentiment
  GET  /heatmap         → Stock price heatmap data
  GET  /risk            → Portfolio risk metrics
  GET  /positions       → Open positions
  GET  /orders          → All orders (with status filter)
  POST /orders/<id>/close → Close an order manually
  GET  /performance     → Win rate, P&L stats
  GET  /ml              → ML predictions
  GET  /options         → NSE options analysis
  GET  /crypto          → Crypto prices
"""

import logging
import sqlite3
import json
import os
import sys
from datetime import datetime, date
from pathlib import Path

logger = logging.getLogger(__name__)

import pandas as pd

try:
    from flask import Flask, jsonify, send_from_directory
    from flask_cors import CORS
except ImportError:
    print("Install: pip install flask flask-cors")
    sys.exit(1)

import config
import data_collector as dc

BASE_DIR = Path(__file__).parent
DASH_DIR = BASE_DIR / "dashboard"

app = Flask(__name__, static_folder=str(DASH_DIR), static_url_path="")
CORS(app)


# ════════════════════════════════════════
# DASHBOARD STATIC FILES
# ════════════════════════════════════════
@app.route("/")
def serve_dashboard():
    return send_from_directory(str(DASH_DIR), "index.html")

@app.route("/<path:path>")
def serve_static(path):
    if (DASH_DIR / path).exists():
        return send_from_directory(str(DASH_DIR), path)
    return jsonify({"error": "not found"}), 404


# ════════════════════════════════════════
# DB HELPER
# ════════════════════════════════════════
def get_db():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ════════════════════════════════════════
# MARKET CONDITION
# ════════════════════════════════════════
@app.route("/market")
def market():
    try:
        sys.path.insert(0, str(BASE_DIR / "analysis"))
        from market_condition import get_market_condition
        mc = get_market_condition()
        return jsonify({
            "nifty_ltp": mc.nifty_ltp,
            "nifty_change": mc.nifty_change,
            "nifty_trend": mc.nifty_trend,
            "vix": mc.vix,
            "vix_state": mc.vix_state,
            "market_state": mc.market_state,
            "trade_filter": mc.trade_filter,
            "bias": mc.bias,
            "top_sectors": mc.top_sectors,
            "weak_sectors": mc.weak_sectors,
        })
    except Exception as e:
        return jsonify({"error": str(e), "nifty_ltp": 0, "vix": 15.0, "market_state": "NEUTRAL", "vix_state": "CALM"})


# ════════════════════════════════════════
# SIGNALS
# ════════════════════════════════════════
@app.route("/signals")
def signals():
    from flask import request
    mode = request.args.get("mode", "equity").lower()
    
    if mode == "intraday":
        return intraday()
        
    if mode == "crypto":
        return crypto_sig()

    if mode == "forex":
        try:
            sys.path.insert(0, str(BASE_DIR / "ingestion"))
            import forex_factory
            return jsonify(forex_factory.fetch_macro_signals())
        except Exception as e:
            return jsonify([])

    try:
        conn = get_db()
        today = date.today().isoformat()
        rows = conn.execute(
            "SELECT * FROM orders WHERE created_at LIKE ? ORDER BY created_at DESC LIMIT 30",
            (f"{today}%",)
        ).fetchall()
        conn.close()
        result = []
        for r in rows:
            d = dict(r)
            # Parse ai_committee if we want to send it to the frontend
            if "ai_reasoning" in d and d["ai_reasoning"]:
                try:
                    d["ai_committee"] = json.loads(d["ai_reasoning"])
                except Exception:
                    pass
            result.append(d)

        # If no DB signals, empty block (no longer spoofing demo)
        if not result:
            return jsonify([])
        return jsonify(result)
    except Exception as e:
        print(f"Error fetching signals: {e}")
        return jsonify([])



# ════════════════════════════════════════
# NEWS
# ════════════════════════════════════════
@app.route("/news")
def news():
    news_file = BASE_DIR / "ingestion" / "news_cache.json"
    articles = []
    alerts = []
    
    if news_file.exists():
        try:
            with open(news_file, "r") as f:
                data = json.load(f)
            
            sorted_articles = sorted(data.values(), key=lambda x: x.get("ts", ""), reverse=True)
            for a in sorted_articles:
                if a.get("macro_impact") == "HIGH":
                    alerts.append(a)
            articles = sorted_articles[:20]
        except Exception as e:
            from utils.demo_data import _demo_news
            articles = _demo_news()
    else:
        from utils.demo_data import _demo_news
        articles = _demo_news()

    return jsonify({"articles": articles, "political_alerts": alerts})

# ════════════════════════════════════════
# HEATMAP
# ════════════════════════════════════════
@app.route("/heatmap")
def heatmap():
    try:
        import yfinance as yf
        stocks = []
        # Sanitize: yfinance uses BAJAJ-AUTO.NS but column name may differ; map carefully
        sym_to_yf = {s: s.replace("_", "-") + ".NS" for s in config.WATCHLIST}
        tickers = list(sym_to_yf.values())
        data = yf.download(tickers, period="2d", auto_adjust=True, progress=False)
        closes = data["Close"] if "Close" in data else pd.DataFrame()
        for sym, t in sym_to_yf.items():
            try:
                ltp = float(closes[t].iloc[-1])
                prev = float(closes[t].iloc[-2])
                chg = (ltp - prev) / prev * 100
                stocks.append({"symbol": sym, "ltp": round(ltp, 2), "change": round(chg, 2)})
            except Exception:
                stocks.append({"symbol": sym, "ltp": 0, "change": 0})
        return jsonify({"stocks": stocks})
    except Exception as e:
        return jsonify({"stocks": [
            {"symbol": "RELIANCE.NS", "ltp": 1343, "change": 1.2},
            {"symbol": "TCS.NS", "ltp": 3542, "change": -0.4},
            {"symbol": "INFY.NS", "ltp": 1319, "change": 2.1},
            {"symbol": "HDFCBANK.NS", "ltp": 795, "change": 0.3},
            {"symbol": "ICICIBANK.NS", "ltp": 1345, "change": -1.1},
            {"symbol": "SBIN.NS", "ltp": 1067, "change": 0.7},
            {"symbol": "ITC.NS", "ltp": 303, "change": 1.5},
            {"symbol": "WIPRO.NS", "ltp": 210, "change": -0.2},
            {"symbol": "AXISBANK.NS", "ltp": 1349, "change": 0.9},
            {"symbol": "LT.NS", "ltp": 4120, "change": 1.8},
        ]})


# ════════════════════════════════════════
# RISK / PORTFOLIO
# ════════════════════════════════════════
@app.route("/risk")
def risk():
    try:
        conn = get_db()
        today = date.today().isoformat()
        open_trades = conn.execute(
            "SELECT * FROM orders WHERE status IN ('PENDING','PLACED','FILLED')"
        ).fetchall()
        closed = conn.execute(
            "SELECT realized_pnl FROM orders WHERE status='CLOSED'"
        ).fetchall()
        day_pnl = conn.execute(
            "SELECT COALESCE(SUM(realized_pnl),0) FROM orders WHERE exit_time LIKE ? AND status='CLOSED'",
            (f"{today}%",)
        ).fetchone()[0]
        deployed = sum((t["entry_price"] or 0) * (t["quantity"] or 0) for t in open_trades)
        wins = sum(1 for r in closed if (r["realized_pnl"] or 0) > 0)
        total_closed = len(closed)
        conn.close()
        return jsonify({
            "capital": config.TOTAL_CAPITAL,
            "deployed": round(deployed, 2),
            "day_pnl": float(day_pnl),
            "drawdown": 0.0,
            "win_rate": round(wins / total_closed * 100, 1) if total_closed else None,
            "open_trades": len(open_trades),
        })
    except Exception as e:
        return jsonify({"capital": config.TOTAL_CAPITAL, "deployed": 0,
                        "day_pnl": 0, "drawdown": 0, "win_rate": None, "open_trades": 0})


# ════════════════════════════════════════
# POSITIONS
# ════════════════════════════════════════
@app.route("/positions")
def positions():
    try:
        conn = get_db()
        rows = conn.execute(
            "SELECT * FROM orders WHERE status IN ('PENDING','PLACED','FILLED') ORDER BY created_at DESC"
        ).fetchall()
        conn.close()
        return jsonify([dict(r) for r in rows])
    except Exception as e:
        return jsonify([])


# ════════════════════════════════════════
# AI REASONING
# ════════════════════════════════════════
@app.route("/api/orders/<int:order_id>/reasoning")
def order_reasoning(order_id):
    try:
        conn = get_db()
        row = conn.execute("SELECT ai_decision, ai_reasoning FROM orders WHERE id = ?", (order_id,)).fetchone()
        conn.close()
        
        if not row:
            return jsonify({"error": "Order not found"}), 404
            
        reasoning = row["ai_reasoning"]
        try:
            import json
            reasoning = json.loads(reasoning) if reasoning else None
        except json.JSONDecodeError:
            pass
            
        return jsonify({
            "order_id": order_id,
            "decision": row["ai_decision"],
            "reasoning": reasoning
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ════════════════════════════════════════
# NATURAL LANGUAGE QUERY (NLQ)
# ════════════════════════════════════════
@app.route("/api/nlq", methods=["POST"])
def execute_nlq():
    data = request.json
    query = data.get("query", "")
    if not query:
        return jsonify({"error": "No query provided"}), 400
        
    try:
        from ai_agents.committee import query_trade_history
        result = query_trade_history(query)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ════════════════════════════════════════
# EXTERNAL SIGNAL WEBHOOK INGESTION
# ════════════════════════════════════════
@app.route("/api/webhook/external", methods=["POST"])
def webhook_external():
    """
    Accepts generic JSON signals from TradingView, MT4/5, or custom bots.
    Expected JSON: {"symbol": "BTCUSDT", "action": "BUY", "price": 65000, "strategy": "TV Trend", "score": 85, "message": "My custom script."}
    """
    try:
        payload = request.json
        if not payload:
            return jsonify({"error": "No JSON payload provided"}), 400
            
        symbol = payload.get("symbol", "UNKNOWN").upper()
        action = payload.get("action", payload.get("signal_type", "BUY")).upper()
        price = float(payload.get("price", 0.0))
        
        # Build standard enriched signal format
        signal = {
            "symbol": symbol,
            "signal_type": action,
            "mode": "WEBHOOK",
            "strategy": payload.get("strategy", "External Script"),
            "reason": payload.get("message", "Ingested from external webhook"),
            "overall_score": float(payload.get("score", 75.0)),
            "conviction": "HIGH" if float(payload.get("score", 75.0)) > 80 else "MEDIUM",
            "entry": price,
            "target": price * 1.05 if action == "BUY" else price * 0.95, # Basic 5% default target
            "stop_loss": price * 0.98 if action == "BUY" else price * 1.02, # Basic 2% default SL
            "paper_trade": True,
            "technical_score": float(payload.get("score", 75.0))
        }

        # 1. Ask AI Committee to evaluate it
        try:
            from ai_agents import committee
            import logging
            logging.info(f"Passing Webhook Signal {symbol} to AI Committee...")
            ai_verdict = committee.evaluate_signal(signal)
            signal["ai_committee"] = ai_verdict
        except Exception as e:
            logging.error(f"AI Committee Webhook Error: {e}")
            
        # 2. Save Trade to Database
        from execution import order_manager
        order_id = order_manager.create_order(signal, paper_trade=True)
        
        # 3. Alert Telegram
        try:
            import telegram_bot as tb
            from execution.signal_formatter import format_telegram
            msg = f"🌐 <b>EXTERNAL WEBHOOK SIGNAL</b> 🌐\n\n" + format_telegram(signal)
            tb.send_message(msg)
        except Exception as e:
            logging.error(f"Telegram Webhook Alert Error: {e}")

        return jsonify({"status": "success", "order_id": order_id, "message": f"Ingested {action} for {symbol}"}), 201

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


# ════════════════════════════════════════
# ML PREDICTIONS
# ════════════════════════════════════════
@app.route("/ml")
def ml():
    ml_file = BASE_DIR / "models" / "ml_cache.json"
    if ml_file.exists():
        try:
            with open(ml_file, "r") as f:
                return jsonify(json.load(f))
        except Exception:
            pass

    return jsonify({"predictions": [
        {"symbol": "INFY", "rf_label": "BUY", "rf_confidence": 0.88, "lstm_direction": "UP", "lstm_up_prob": 0.72, "score": 0.81},
        {"symbol": "TCS", "rf_label": "HOLD", "rf_confidence": 0.64, "lstm_direction": "UP", "lstm_up_prob": 0.58, "score": 0.60},
        {"symbol": "SBIN", "rf_label": "SELL", "rf_confidence": 0.71, "lstm_direction": "DOWN", "lstm_up_prob": 0.31, "score": 0.36},
        {"symbol": "ITC", "rf_label": "BUY", "rf_confidence": 0.62, "lstm_direction": "FLAT", "lstm_up_prob": 0.51, "score": 0.57},
        {"symbol": "LT", "rf_label": "BUY", "rf_confidence": 0.79, "lstm_direction": "UP", "lstm_up_prob": 0.68, "score": 0.74},
    ]})


# ════════════════════════════════════════
# OPTIONS
# ════════════════════════════════════════
@app.route("/options")
def options():
    try:
        sys.path.insert(0, str(BASE_DIR / "modes"))
        from options import analyze_options
        
        nifty = analyze_options("NIFTY")
        banknifty = analyze_options("BANKNIFTY")
        
        def snap_to_dict(snap, name):
            return {
                "symbol":              name,
                "spot_price":          snap.spot_price,
                "max_pain":            snap.max_pain,
                "pcr":                 snap.pcr,
                "pcr_state":           snap.pcr_state,
                "support_from_oi":     snap.support_from_oi,
                "resistance_from_oi":  snap.resistance_from_oi,
                "signal":              snap.signal,
                "unusual":             snap.unusual_activity,
                "iv_atm":              snap.iv_atm,
                "total_call_oi":       snap.total_call_oi,
                "total_put_oi":        snap.total_put_oi,
                "expiry":              snap.expiry,
                "summary":             snap.summary,
            }
        
        return jsonify({
            **snap_to_dict(nifty, "NIFTY"),     # top level for backwards compat
            "nifty":     snap_to_dict(nifty, "NIFTY"),
            "banknifty": snap_to_dict(banknifty, "BANKNIFTY"),
        })
    except Exception as e:
        return jsonify({"max_pain": 24050, "pcr": 1.24, "pcr_state": "BULLISH",
                        "support_from_oi": 23900, "resistance_from_oi": 24200,
                        "signal": "BULLISH", "spot_price": 24100,
                        "nifty":     {"symbol": "NIFTY",    "pcr": 1.24, "signal": "BULLISH", "max_pain": 24050, "support_from_oi": 23900, "resistance_from_oi": 24200},
                        "banknifty": {"symbol": "BANKNIFTY", "pcr": 0.98, "signal": "NEUTRAL", "max_pain": 51500, "support_from_oi": 51000, "resistance_from_oi": 52000},
                        })


# ════════════════════════════════════════
# CRYPTO
# ════════════════════════════════════════
@app.route("/crypto")
def crypto():
    try:
        import requests
        url = "https://api.binance.com/api/v3/ticker/24hr"
        symbols = ["BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT",
                   "ADAUSDT","DOGEUSDT","AVAXUSDT","MATICUSDT","DOTUSDT"]
        coins = []
        for sym in symbols:
            try:
                r = requests.get(url, params={"symbol": sym}, timeout=5).json()
                coins.append({
                    "symbol": sym,
                    "price": float(r["lastPrice"]),
                    "change": float(r["priceChangePercent"]),
                    "volume": float(r["quoteVolume"]),
                })
            except Exception:
                pass
        return jsonify({"coins": coins})
    except Exception as e:
        return jsonify({"coins": [
            {"symbol": "BTCUSDT", "price": 62840, "change": 1.2},
            {"symbol": "ETHUSDT", "price": 3480, "change": 0.8},
            {"symbol": "BNBUSDT", "price": 582, "change": -0.3},
            {"symbol": "SOLUSDT", "price": 152, "change": 3.1},
        ]})


# ════════════════════════════════════════
# ORDERS
# ════════════════════════════════════════
@app.route("/orders")
def orders():
    from flask import request
    status_filter = request.args.get("status", None)
    conn = get_db()
    if status_filter:
        rows = conn.execute(
            "SELECT * FROM orders WHERE status=? ORDER BY created_at DESC LIMIT 100",
            (status_filter,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM orders ORDER BY created_at DESC LIMIT 100"
        ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/orders/today")
def orders_today():
    today = date.today().isoformat()
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM orders WHERE created_at LIKE ? ORDER BY created_at DESC",
        (f"{today}%",)
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/orders/<int:order_id>/close", methods=["POST"])
def close_order(order_id):
    from flask import request
    try:
        sys.path.insert(0, str(BASE_DIR / "execution"))
        from execution.order_manager import close_order as _close
        data = request.get_json(force=True) or {}
        exit_price  = data.get("exit_price", 0)
        exit_reason = data.get("reason", "MANUAL")
        pnl = _close(order_id, exit_price, exit_reason)
        return jsonify({"success": True, "pnl": pnl, "order_id": order_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/orders/news")
def news_signals():
    """News-linked orders (signals triggered by news)."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM news_signals ORDER BY created_at DESC LIMIT 50"
        ).fetchall()
        conn.close()
        return jsonify([dict(r) for r in rows])
    except Exception:
        conn.close()
        return jsonify([])


# ════════════════════════════════════════
# PERFORMANCE
# ════════════════════════════════════════
@app.route("/performance")
def performance():
    try:
        sys.path.insert(0, str(BASE_DIR / "execution"))
        from execution.order_manager import get_stats, get_daily_pnl
        stats   = get_stats()
        day_pnl = get_daily_pnl()
        return jsonify({**stats, "day_pnl": day_pnl})
    except Exception as e:
        return jsonify({"error": str(e), "total_trades": 0, "win_rate": 0, "total_pnl": 0, "day_pnl": 0})


# ════════════════════════════════════════
# INTRADAY (separate engine — does NOT touch equity/crypto)
# ════════════════════════════════════════
@app.route("/intraday")
def intraday():
    try:
        sys.path.insert(0, str(BASE_DIR / "modes"))
        from intraday import scan_intraday_stocks
        result = scan_intraday_stocks()
        return jsonify(result)
    except Exception as e:
        from utils.demo_data import _demo_intraday_signals
        return jsonify({
            "signals": _demo_intraday_signals(),
            "market_status": {"session": "DEMO", "current_time": datetime.now().strftime("%H:%M")},
            "stocks": {},
            "error": str(e),
        })

# ════════════════════════════════════════
# AI AGENT TERMINAL
# ════════════════════════════════════════
@app.route("/api/chat", methods=["POST"])
def ai_chat():
    from flask import request
    try:
        sys.path.insert(0, str(BASE_DIR))
        from ai_agents.committee import debate_query
        data = request.get_json(force=True) or {}
        query = data.get("query", "")
        if not query:
            return jsonify({"error": "No query provided"}), 400

        result = debate_query(query)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/agents/evaluate", methods=["POST"])
def agents_evaluate():
    """Manual trigger to evaluate a signal payload via Postman"""
    from flask import request
    try:
        sys.path.insert(0, str(BASE_DIR))
        from ai_agents.committee import evaluate_signal
        signal_data = request.get_json(force=True) or {}
        if not signal_data:
            return jsonify({"error": "No signal data provided"}), 400
            
        result = evaluate_signal(signal_data)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ════════════════════════════════════════
# HEALTH
# ════════════════════════════════════════
@app.route("/health")
def health():
    return jsonify({"status": "ok", "time": datetime.now().isoformat(),
                    "paper_trading": config.PAPER_TRADING})


# ════════════════════════════════════════
# LEGACY COMPAT & CRYPTO
# ════════════════════════════════════════
def crypto_sig():
    try:
        sys.path.insert(0, str(BASE_DIR / "modes"))
        from crypto import scan_crypto_signals
        result = scan_crypto_signals()
        return jsonify(result)
    except Exception as e:
        import traceback
        logger.error(f"Crypto engine error: {traceback.format_exc()}")
        return jsonify([])

@app.route("/api/dashboard")
def api_dashboard():
    return jsonify({"status": "ok", "redirect": "use /signals, /news, /heatmap etc."})

@app.route("/api/signals")
def api_signals():
    return signals()

@app.route("/api/pnl")
def api_pnl():
    try:
        sys.path.insert(0, str(BASE_DIR / "execution"))
        from execution.order_manager import get_daily_pnl
        return jsonify({"pnl": get_daily_pnl(), "date": date.today().isoformat()})
    except Exception:
        return jsonify({"pnl": 0.0, "date": date.today().isoformat()})

@app.route("/api/health")
def api_health():
    return health()


if __name__ == "__main__":
    dc.init_db()
    print("=" * 50)
    print("  TURTLE TRADE — Dashboard API Server")
    print("=" * 50)
    print(f"  Dashboard: http://localhost:5001")
    print(f"  API:       http://localhost:5001/signals")
    print(f"  Paper:     {config.PAPER_TRADING}")
    print("=" * 50)
    app.run(host="0.0.0.0", port=5001, debug=False)
