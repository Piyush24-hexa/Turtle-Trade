"""
signals/backtester.py
Historical backtesting engine.
Tests any signal strategy on 2-3 years of historical data.
Reports: Win rate, Sharpe ratio, Max drawdown, CAGR, Avg R:R
"""

import logging
import numpy as np
import pandas as pd
import yfinance as yf
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Optional

logger = logging.getLogger(__name__)


@dataclass
class BacktestResult:
    strategy_name: str
    symbol: str
    start_date: str
    end_date: str
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    avg_win_pct: float = 0.0
    avg_loss_pct: float = 0.0
    avg_rr: float = 0.0
    total_return: float = 0.0
    cagr: float = 0.0
    sharpe: float = 0.0
    max_drawdown: float = 0.0
    profit_factor: float = 0.0
    grade: str = "?"
    trades: list = field(default_factory=list)


def _grade(result: BacktestResult) -> str:
    """Grade the strategy A-F based on key metrics."""
    score = 0
    if result.win_rate >= 0.55: score += 2
    elif result.win_rate >= 0.45: score += 1
    if result.avg_rr >= 1.5: score += 2
    elif result.avg_rr >= 1.0: score += 1
    if result.sharpe >= 1.5: score += 2
    elif result.sharpe >= 0.8: score += 1
    if result.max_drawdown > -0.20: score += 1
    if result.profit_factor >= 1.5: score += 1
    grades = {8: "A+", 7: "A", 6: "B+", 5: "B", 4: "C", 3: "D", 2: "E"}
    return grades.get(score, "F")


def backtest(
    symbol: str,
    strategy_fn: Callable,
    capital: float = 10_000,
    risk_pct: float = 2.5,
    period: str = "2y",
    sl_pct: float = 2.0,
    tp_pct: float = 4.0,
) -> BacktestResult:
    """
    Backtest a strategy function on historical data.

    strategy_fn(df) should return "BUY", "SELL", or None for each candle.
    """
    import sys
    sys.path.insert(0, "..")

    # Fetch data
    df = yf.Ticker(f"{symbol}.NS").history(period=period)
    if len(df) < 50:
        logger.warning(f"Not enough data for backtesting {symbol}")
        return BacktestResult(strategy_name="?", symbol=symbol,
                              start_date="", end_date="")

    df.columns = df.columns.str.lower()
    df = df[["open","high","low","close","volume"]].copy()

    result = BacktestResult(
        strategy_name=strategy_fn.__name__,
        symbol=symbol,
        start_date=str(df.index[0].date()),
        end_date=str(df.index[-1].date()),
    )

    equity = [capital]
    current_capital = capital
    position = None

    for i in range(50, len(df) - 1):
        window = df.iloc[max(0, i-100):i+1].copy()

        if position is None:
            # Look for entry
            try:
                signal = strategy_fn(window)
            except Exception:
                signal = None

            if signal in ("BUY", "SELL"):
                entry_price = float(df["close"].iloc[i])
                if signal == "BUY":
                    sl = entry_price * (1 - sl_pct / 100)
                    tp = entry_price * (1 + tp_pct / 100)
                else:
                    sl = entry_price * (1 + sl_pct / 100)
                    tp = entry_price * (1 - tp_pct / 100)

                risk_amount = current_capital * risk_pct / 100
                qty = int(risk_amount / abs(entry_price - sl)) if abs(entry_price - sl) > 0 else 0
                if qty < 1:
                    qty = 1

                position = {
                    "type": signal,
                    "entry": entry_price,
                    "sl": sl,
                    "tp": tp,
                    "qty": qty,
                    "entry_idx": i,
                }
        else:
            # Check exit
            candle = df.iloc[i]
            exit_price = None
            exit_reason = None

            if position["type"] == "BUY":
                if candle["low"] <= position["sl"]:
                    exit_price = position["sl"]
                    exit_reason = "SL_HIT"
                elif candle["high"] >= position["tp"]:
                    exit_price = position["tp"]
                    exit_reason = "TARGET_HIT"
            else:  # SELL
                if candle["high"] >= position["sl"]:
                    exit_price = position["sl"]
                    exit_reason = "SL_HIT"
                elif candle["low"] <= position["tp"]:
                    exit_price = position["tp"]
                    exit_reason = "TARGET_HIT"

            # Max hold = 10 days
            if exit_price is None and (i - position["entry_idx"]) >= 10:
                exit_price = float(candle["close"])
                exit_reason = "TIME_EXIT"

            if exit_price:
                if position["type"] == "BUY":
                    pnl = (exit_price - position["entry"]) * position["qty"]
                    ret_pct = (exit_price - position["entry"]) / position["entry"]
                else:
                    pnl = (position["entry"] - exit_price) * position["qty"]
                    ret_pct = (position["entry"] - exit_price) / position["entry"]

                current_capital += pnl
                equity.append(current_capital)

                trade = {
                    "entry": position["entry"],
                    "exit": exit_price,
                    "type": position["type"],
                    "pnl": round(pnl, 2),
                    "return_pct": round(ret_pct * 100, 2),
                    "reason": exit_reason,
                }
                result.trades.append(trade)
                position = None

    # Close open position
    if position:
        exit_price = float(df["close"].iloc[-1])
        if position["type"] == "BUY":
            pnl = (exit_price - position["entry"]) * position["qty"]
        else:
            pnl = (position["entry"] - exit_price) * position["qty"]
        result.trades.append({"pnl": pnl, "reason": "OPEN_CLOSE"})
        current_capital += pnl

    if not result.trades:
        result.grade = "N/A (no trades)"
        return result

    # Calculate metrics
    pnls = [t["pnl"] for t in result.trades]
    returns = [t.get("return_pct", 0) for t in result.trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    result.total_trades = len(result.trades)
    result.wins = len(wins)
    result.losses = len(losses)
    result.win_rate = round(result.wins / result.total_trades, 3)
    result.avg_win_pct  = round(np.mean([r for r in returns if r > 0]), 2) if wins else 0
    result.avg_loss_pct = round(np.mean([r for r in returns if r <= 0]), 2) if losses else 0
    result.avg_rr = abs(result.avg_win_pct / result.avg_loss_pct) if result.avg_loss_pct else 0

    result.total_return = round((current_capital - capital) / capital * 100, 2)

    # CAGR
    days = (pd.to_datetime(result.end_date) - pd.to_datetime(result.start_date)).days
    if days > 0:
        years = days / 365.25
        result.cagr = round(((current_capital / capital) ** (1 / years) - 1) * 100, 2)

    # Sharpe ratio
    ret_series = pd.Series(pnls) / capital
    if ret_series.std() > 0:
        result.sharpe = round(ret_series.mean() / ret_series.std() * np.sqrt(252), 2)

    # Max drawdown
    equity_series = pd.Series(equity)
    rolling_max = equity_series.cummax()
    drawdown = (equity_series - rolling_max) / rolling_max
    result.max_drawdown = round(float(drawdown.min()) * 100, 2)

    # Profit factor
    gross_profit = sum(wins) if wins else 0
    gross_loss = abs(sum(losses)) if losses else 1
    result.profit_factor = round(gross_profit / gross_loss, 2)

    result.grade = _grade(result)
    return result


def print_report(r: BacktestResult):
    """Print a formatted backtest report."""
    print(f"\n{'='*55}")
    print(f"  BACKTEST: {r.symbol} | {r.strategy_name}")
    print(f"  Period: {r.start_date} to {r.end_date}")
    print(f"  Grade: {r.grade}")
    print(f"{'='*55}")
    print(f"  Total Trades:  {r.total_trades}")
    print(f"  Win Rate:      {r.win_rate:.1%}   ({r.wins}W / {r.losses}L)")
    print(f"  Avg Win:       +{r.avg_win_pct:.2f}%")
    print(f"  Avg Loss:      {r.avg_loss_pct:.2f}%")
    print(f"  Risk:Reward:   1:{r.avg_rr:.1f}")
    print(f"  Total Return:  {r.total_return:+.2f}%")
    print(f"  CAGR:          {r.cagr:+.2f}%/yr")
    print(f"  Sharpe Ratio:  {r.sharpe:.2f}")
    print(f"  Max Drawdown:  {r.max_drawdown:.2f}%")
    print(f"  Profit Factor: {r.profit_factor:.2f}")
    print(f"{'='*55}")


if __name__ == "__main__":
    import sys
    sys.path.insert(0, "..")
    logging.basicConfig(level=logging.WARNING)

    # Example: backtest RSI strategy
    def simple_rsi_strategy(df: pd.DataFrame) -> Optional[str]:
        from technical_analyzer import calc_rsi
        rsi = calc_rsi(df["close"]).iloc[-1]
        if rsi < 35:
            return "BUY"
        elif rsi > 65:
            return "SELL"
        return None

    print("Backtesting RSI strategy on RELIANCE (2 years)...")
    result = backtest("RELIANCE", simple_rsi_strategy, capital=10_000)
    print_report(result)
