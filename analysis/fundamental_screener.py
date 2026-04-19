"""
analysis/fundamental_screener.py
Fetches fundamental data from Yahoo Finance (free).
Screens for: P/E, P/B, EPS growth, Debt/Equity, FII holding, earnings surprise.
"""

import logging
import time
from datetime import datetime
from typing import Optional
from dataclasses import dataclass

import yfinance as yf

logger = logging.getLogger(__name__)

# Sector average P/E ratios (India NSE approximations)
SECTOR_PE = {
    "Technology": 28, "Financial Services": 18, "Banking": 16,
    "Pharma": 32, "FMCG": 52, "Auto": 22, "Energy": 12,
    "Infrastructure": 20, "Metal": 10, "Telecom": 25,
    "Default": 22,
}


@dataclass
class Fundamentals:
    symbol: str
    pe_ratio: Optional[float] = None
    pb_ratio: Optional[float] = None
    debt_equity: Optional[float] = None
    eps_growth: Optional[float] = None
    revenue_growth: Optional[float] = None
    roe: Optional[float] = None
    sector: Optional[str] = None
    sector_pe: Optional[float] = None
    pe_vs_sector: Optional[str] = None    # CHEAP / FAIR / EXPENSIVE
    market_cap: Optional[float] = None
    dividend_yield: Optional[float] = None
    score: float = 0.5                    # 0=bearish, 1=bullish
    summary: str = ""


def screen(symbol: str) -> Fundamentals:
    """Fetch and score fundamentals for a stock."""
    result = Fundamentals(symbol=symbol)
    try:
        ticker = yf.Ticker(f"{symbol}.NS")
        info = ticker.info

        result.pe_ratio = info.get("trailingPE") or info.get("forwardPE")
        result.pb_ratio = info.get("priceToBook")
        result.debt_equity = info.get("debtToEquity")
        result.roe = info.get("returnOnEquity")
        result.market_cap = info.get("marketCap")
        result.dividend_yield = info.get("dividendYield")
        result.sector = info.get("sector", "Default")

        # EPS & Revenue growth
        result.eps_growth = info.get("earningsGrowth")
        result.revenue_growth = info.get("revenueGrowth")

        # P/E vs sector
        result.sector_pe = SECTOR_PE.get(result.sector, SECTOR_PE["Default"])
        if result.pe_ratio and result.sector_pe:
            ratio = result.pe_ratio / result.sector_pe
            if ratio < 0.85:
                result.pe_vs_sector = "CHEAP"
            elif ratio > 1.15:
                result.pe_vs_sector = "EXPENSIVE"
            else:
                result.pe_vs_sector = "FAIR"

        # Score (0-1): higher = more fundamentally bullish
        score_parts = []
        if result.pe_vs_sector == "CHEAP":
            score_parts.append(0.8)
        elif result.pe_vs_sector == "EXPENSIVE":
            score_parts.append(0.3)
        else:
            score_parts.append(0.55)

        if result.eps_growth is not None:
            score_parts.append(min(1.0, 0.5 + result.eps_growth * 2))

        if result.roe is not None:
            score_parts.append(min(1.0, result.roe / 0.20))  # ROE > 20% is great

        if result.debt_equity is not None:
            score_parts.append(max(0.0, 1.0 - result.debt_equity / 200))  # Lower debt = better

        result.score = round(sum(score_parts) / len(score_parts), 3) if score_parts else 0.5

        # Summary
        parts = []
        if result.pe_ratio:
            parts.append(f"P/E {result.pe_ratio:.1f} ({result.pe_vs_sector})")
        if result.eps_growth is not None:
            parts.append(f"EPS growth {result.eps_growth:.1%}")
        if result.roe:
            parts.append(f"ROE {result.roe:.1%}")
        if result.debt_equity is not None:
            parts.append(f"D/E {result.debt_equity:.0f}%")
        result.summary = " | ".join(parts)

        logger.debug(f"  Fundamentals {symbol}: {result.summary} | score={result.score:.2f}")

    except Exception as e:
        logger.debug(f"  Fundamental error {symbol}: {e}")
        result.score = 0.5

    return result


def screen_all(watchlist: list) -> dict:
    """Screen all watchlist symbols. Returns {symbol: Fundamentals}."""
    results = {}
    for sym in watchlist:
        logger.debug(f"  Screening {sym}...")
        results[sym] = screen(sym)
        time.sleep(0.5)
    logger.info(f"Fundamental screening complete: {len(results)} stocks")
    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    for sym in ["RELIANCE", "INFY", "HDFCBANK"]:
        f = screen(sym)
        print(f"\n{f.symbol}: {f.summary}")
        print(f"  P/E vs sector: {f.pe_vs_sector} | Score: {f.score:.0%}")
