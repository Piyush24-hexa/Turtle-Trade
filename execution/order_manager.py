"""
execution/order_manager.py
Tracks full order lifecycle: SIGNAL → PENDING → PLACED → FILLED → CLOSED
Accounts for news-driven entries, position updates, and P&L tracking.
"""

import sqlite3
import logging
from datetime import datetime, date
from typing import Optional
from pathlib import Path

logger = logging.getLogger(__name__)

DB_PATH = "trading_bot.db"


def init_orders_db():
    """Create orders and order_events tables if they don't exist."""
    conn = sqlite3.connect(DB_PATH)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS orders (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol          TEXT NOT NULL,
            signal_type     TEXT NOT NULL,   -- BUY / SELL / BUY_CALL / BUY_PUT
            mode            TEXT DEFAULT 'EQUITY',
            strategy        TEXT,
            reason          TEXT,

            -- Price levels
            entry_price     REAL,
            target_price    REAL,
            stop_loss       REAL,
            quantity        INTEGER DEFAULT 0,
            investment      REAL DEFAULT 0,
            risk_amount     REAL DEFAULT 0,
            risk_reward     REAL DEFAULT 0,

            -- Intelligence scores at signal time
            overall_score   REAL DEFAULT 0,
            technical_score REAL DEFAULT 0,
            ml_score        REAL DEFAULT 0,
            sentiment_score REAL DEFAULT 0,
            pattern_score   REAL DEFAULT 0,
            fundamental_score REAL DEFAULT 0,
            news_headline   TEXT,
            pattern         TEXT,
            conviction      TEXT DEFAULT 'MEDIUM',

            -- Status tracking
            status          TEXT DEFAULT 'PENDING',
            -- PENDING = signal, PLACED = order sent, FILLED = confirmed,
            -- PARTIAL = partially filled, CLOSED = done, CANCELLED = rejected

            -- Fill data
            fill_price      REAL,
            fill_time       TEXT,
            exit_price      REAL,
            exit_time       TEXT,
            exit_reason     TEXT,   -- TARGET_HIT / SL_HIT / MANUAL / TIME_EXIT

            -- P&L
            realized_pnl    REAL DEFAULT 0,
            unrealized_pnl  REAL DEFAULT 0,
            current_price   REAL DEFAULT 0,
            current_pnl_pct REAL DEFAULT 0,

            -- Meta
            paper_trade     INTEGER DEFAULT 1,
            created_at      TEXT DEFAULT (datetime('now','localtime')),
            updated_at      TEXT DEFAULT (datetime('now','localtime')),
            notes           TEXT
        );

        CREATE TABLE IF NOT EXISTS order_events (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id    INTEGER REFERENCES orders(id),
            event_type  TEXT,    -- STATUS_CHANGE / PRICE_UPDATE / NOTE
            old_value   TEXT,
            new_value   TEXT,
            timestamp   TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS news_signals (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol      TEXT,
            headline    TEXT,
            sentiment   TEXT,
            score       REAL,
            source      TEXT,
            linked_order_id INTEGER,
            created_at  TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE INDEX IF NOT EXISTS idx_orders_symbol ON orders(symbol);
        CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
        CREATE INDEX IF NOT EXISTS idx_orders_date ON orders(created_at);
    """)
    conn.commit()
    conn.close()
    logger.info("Orders DB initialized")


def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def create_order(signal: dict, paper_trade: bool = True) -> int:
    """
    Create a new order from an enriched signal dict.
    Returns the order ID.
    """
    conn = _conn()
    cursor = conn.execute("""
        INSERT INTO orders (
            symbol, signal_type, mode, strategy, reason,
            entry_price, target_price, stop_loss, quantity, investment, risk_amount, risk_reward,
            overall_score, technical_score, ml_score, sentiment_score,
            pattern_score, fundamental_score, news_headline, pattern, conviction,
            status, paper_trade
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        signal.get("symbol"),
        signal.get("signal_type", "BUY"),
        signal.get("mode", "EQUITY"),
        signal.get("strategy", ""),
        signal.get("reason", ""),
        signal.get("entry", 0),
        signal.get("target", 0),
        signal.get("stop_loss", 0),
        signal.get("quantity", 0),
        signal.get("investment", 0),
        signal.get("risk_amount", 0),
        signal.get("risk_reward", 0),
        signal.get("overall_score", 0),
        signal.get("technical_score", 0),
        signal.get("ml_score", 0),
        signal.get("sentiment_score", 0),
        signal.get("pattern_score", 0),
        signal.get("fundamental_score", 0),
        signal.get("news_headline", ""),
        signal.get("pattern", ""),
        signal.get("conviction", "MEDIUM"),
        "PENDING",
        1 if paper_trade else 0,
    ))
    order_id = cursor.lastrowid

    # Log news if present
    if signal.get("news_headline"):
        conn.execute("""
            INSERT INTO news_signals (symbol, headline, sentiment, score, source, linked_order_id)
            VALUES (?,?,?,?,?,?)
        """, (
            signal.get("symbol"), signal.get("news_headline"),
            signal.get("sentiment", "neutral"), signal.get("sentiment_score", 0) / 100,
            "finbert", order_id
        ))

    _log_event(conn, order_id, "STATUS_CHANGE", "NEW", "PENDING")
    conn.commit()
    conn.close()
    logger.info(f"Order created: #{order_id} {signal.get('signal_type')} {signal.get('symbol')} @ {signal.get('entry')}")
    return order_id


def update_status(order_id: int, new_status: str, notes: str = "") -> bool:
    """Update order status and log the event."""
    conn = _conn()
    old = conn.execute("SELECT status FROM orders WHERE id=?", (order_id,)).fetchone()
    if not old:
        conn.close()
        return False
    conn.execute("""
        UPDATE orders SET status=?, updated_at=datetime('now','localtime'), notes=?
        WHERE id=?
    """, (new_status, notes, order_id))
    _log_event(conn, order_id, "STATUS_CHANGE", old["status"], new_status)
    conn.commit()
    conn.close()
    logger.info(f"Order #{order_id}: {old['status']} → {new_status}")
    return True


def fill_order(order_id: int, fill_price: float):
    """Mark order as filled at a price."""
    conn = _conn()
    conn.execute("""
        UPDATE orders SET
            status='FILLED', fill_price=?, fill_time=datetime('now','localtime'),
            current_price=?, updated_at=datetime('now','localtime')
        WHERE id=?
    """, (fill_price, fill_price, order_id))
    _log_event(conn, order_id, "STATUS_CHANGE", "PLACED", "FILLED")
    conn.commit()
    conn.close()
    logger.info(f"Order #{order_id} filled @ {fill_price}")


def close_order(order_id: int, exit_price: float, exit_reason: str = "MANUAL"):
    """Close an order and calculate realized P&L."""
    conn = _conn()
    order = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    if not order:
        conn.close()
        return

    entry = order["fill_price"] or order["entry_price"]
    qty = order["quantity"] or 1
    signal_type = order["signal_type"]

    if signal_type in ("BUY", "BUY_CALL", "BUY_PUT"):
        gross_pnl = (exit_price - entry) * qty
        pnl_pct = (exit_price - entry) / entry * 100
    else:
        gross_pnl = (entry - exit_price) * qty
        pnl_pct = (entry - exit_price) / entry * 100

    brokerage = 40 # 20 buy, 20 sell
    stt = (exit_price * qty * 0.00025)
    exchange_charges = ((entry + exit_price) * qty * 0.0000325)
    gst = (brokerage + exchange_charges) * 0.18
    sebi_charges = ((entry + exit_price) * qty / 10000000) * 10
    total_costs = brokerage + stt + exchange_charges + gst + sebi_charges
    pnl = gross_pnl - total_costs

    conn.execute("""
        UPDATE orders SET
            status='CLOSED', exit_price=?, exit_time=datetime('now','localtime'),
            exit_reason=?, realized_pnl=?, current_pnl_pct=?,
            updated_at=datetime('now','localtime')
        WHERE id=?
    """, (exit_price, exit_reason, round(pnl, 2), round(pnl_pct, 2), order_id))
    _log_event(conn, order_id, "STATUS_CHANGE", order["status"], f"CLOSED:{exit_reason}")
    conn.commit()
    conn.close()
    logger.info(f"Order #{order_id} closed @ {exit_price} | P&L: Rs.{pnl:.2f} ({pnl_pct:.2f}%)")
    return pnl


def update_unrealized_pnl(order_id: int, current_price: float):
    """Update live unrealized P&L for open orders."""
    conn = _conn()
    order = conn.execute("SELECT * FROM orders WHERE id=? AND status IN ('FILLED','PLACED')", (order_id,)).fetchone()
    if not order:
        conn.close()
        return

    entry = order["fill_price"] or order["entry_price"]
    qty = order["quantity"] or 1
    signal_type = order["signal_type"]

    if signal_type in ("BUY", "BUY_CALL", "BUY_PUT"):
        gross_pnl = (current_price - entry) * qty
        pnl_pct = (current_price - entry) / entry * 100
    else:
        gross_pnl = (entry - current_price) * qty
        pnl_pct = (entry - current_price) / entry * 100

    brokerage = 40 # 20 buy, 20 sell
    stt = (current_price * qty * 0.00025)
    exchange_charges = ((entry + current_price) * qty * 0.0000325)
    gst = (brokerage + exchange_charges) * 0.18
    sebi_charges = ((entry + current_price) * qty / 10000000) * 10
    total_costs = brokerage + stt + exchange_charges + gst + sebi_charges
    pnl = gross_pnl - total_costs

    # Check SL/TP
    auto_close = None
    if signal_type in ("BUY", "BUY_CALL", "BUY_PUT"):
        if current_price <= order["stop_loss"]:
            auto_close = ("SL_HIT", order["stop_loss"])
        elif current_price >= order["target_price"]:
            auto_close = ("TARGET_HIT", order["target_price"])
    else:
        if current_price >= order["stop_loss"]:
            auto_close = ("SL_HIT", order["stop_loss"])
        elif current_price <= order["target_price"]:
            auto_close = ("TARGET_HIT", order["target_price"])

    conn.execute("""
        UPDATE orders SET unrealized_pnl=?, current_price=?, current_pnl_pct=?,
        updated_at=datetime('now','localtime') WHERE id=?
    """, (round(pnl, 2), current_price, round(pnl_pct, 2), order_id))
    conn.commit()
    conn.close()

    if auto_close:
        reason, price = auto_close
        close_order(order_id, price, reason)
        logger.info(f"Auto-closed order #{order_id}: {reason} @ {price}")
        return reason

    return None


def get_open_orders() -> list:
    """Get all open orders (PENDING + PLACED + FILLED)."""
    conn = _conn()
    rows = conn.execute("""
        SELECT * FROM orders WHERE status IN ('PENDING','PLACED','FILLED')
        ORDER BY created_at DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_today_orders() -> list:
    """All orders created today."""
    conn = _conn()
    today = date.today().isoformat()
    rows = conn.execute("""
        SELECT * FROM orders WHERE created_at LIKE ? ORDER BY created_at DESC
    """, (f"{today}%",)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_daily_pnl() -> float:
    """Sum of today's closed trades P&L."""
    conn = _conn()
    today = date.today().isoformat()
    row = conn.execute("""
        SELECT COALESCE(SUM(realized_pnl), 0) FROM orders
        WHERE status='CLOSED' AND exit_time LIKE ?
    """, (f"{today}%",)).fetchone()
    conn.close()
    return float(row[0])


def get_stats() -> dict:
    """Overall performance statistics."""
    conn = _conn()
    rows = conn.execute("SELECT * FROM orders WHERE status='CLOSED'").fetchall()
    conn.close()

    if not rows:
        return {"total_trades": 0, "wins": 0, "losses": 0, "win_rate": 0,
                "total_pnl": 0, "avg_win": 0, "avg_loss": 0, "profit_factor": 0}

    wins   = [r["realized_pnl"] for r in rows if r["realized_pnl"] > 0]
    losses = [r["realized_pnl"] for r in rows if r["realized_pnl"] <= 0]
    total_pnl = sum(r["realized_pnl"] for r in rows)

    return {
        "total_trades":   len(rows),
        "wins":           len(wins),
        "losses":         len(losses),
        "win_rate":       round(len(wins) / len(rows) * 100, 1),
        "total_pnl":      round(total_pnl, 2),
        "avg_win":        round(sum(wins) / len(wins), 2) if wins else 0,
        "avg_loss":       round(sum(losses) / len(losses), 2) if losses else 0,
        "profit_factor":  round(sum(wins) / abs(sum(losses)), 2) if losses and wins else 0,
    }


def _log_event(conn, order_id: int, event_type: str, old: str, new: str):
    conn.execute("""
        INSERT INTO order_events (order_id, event_type, old_value, new_value)
        VALUES (?,?,?,?)
    """, (order_id, event_type, str(old), str(new)))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    init_orders_db()
    print("Orders DB initialized")
    print("Stats:", get_stats())
