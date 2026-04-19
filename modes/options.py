"""
modes/options.py
NSE Options (F&O) Analysis Engine
Free data from NSE public API — no authentication needed.
Generates CALL/PUT signals with max pain, PCR, OI analysis.
"""

import logging
import requests
import json
from datetime import datetime, date
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}


@dataclass
class OptionsSnapshot:
    symbol: str = "NIFTY"
    expiry: str = ""
    spot_price: float = 0.0
    max_pain: float = 0.0
    pcr: float = 0.0              # Put-Call Ratio (>1 = bullish, <1 = bearish)
    pcr_state: str = "NEUTRAL"
    total_call_oi: int = 0
    total_put_oi: int = 0
    iv_atm: float = 0.0           # Implied Volatility at-the-money
    support_from_oi: float = 0.0  # Highest put OI strike = strong support
    resistance_from_oi: float = 0.0  # Highest call OI strike = strong resistance
    unusual_activity: list = field(default_factory=list)
    signal: str = "NEUTRAL"       # BULLISH / BEARISH / NEUTRAL
    summary: str = ""


def _nse_session() -> requests.Session:
    """Create a session with NSE cookies."""
    session = requests.Session()
    session.headers.update(NSE_HEADERS)
    try:
        session.get("https://www.nseindia.com", timeout=10)
    except Exception:
        pass
    return session


def get_option_chain(symbol: str = "NIFTY", expiry: str = None) -> Optional[dict]:
    """
    Fetch option chain from NSE public API.
    symbol: NIFTY, BANKNIFTY, or stock symbol
    """
    session = _nse_session()
    url = f"https://www.nseindia.com/api/option-chain-indices?symbol={symbol}"
    if symbol not in ("NIFTY", "BANKNIFTY", "FINNIFTY"):
        url = f"https://www.nseindia.com/api/option-chain-equities?symbol={symbol}"

    try:
        resp = session.get(url, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error(f"Option chain fetch error ({symbol}): {e}")
        return None


def calculate_max_pain(chain_data: dict) -> float:
    """
    Max Pain = the strike price where option sellers (writers) lose least money.
    Typically price gravitates towards max pain at expiry.
    """
    try:
        records = chain_data["records"]["data"]
        strikes = {}

        for item in records:
            strike = item["strikePrice"]
            ce_oi = item.get("CE", {}).get("openInterest", 0) or 0
            pe_oi = item.get("PE", {}).get("openInterest", 0) or 0
            strikes[strike] = {"call_oi": ce_oi, "put_oi": pe_oi}

        strike_prices = sorted(strikes.keys())
        min_pain = float("inf")
        max_pain_strike = strike_prices[len(strike_prices) // 2]

        for test_strike in strike_prices:
            pain = 0
            for s, oi in strikes.items():
                # Call pain (calls ITM above test_strike)
                if s < test_strike:
                    pain += oi["call_oi"] * (test_strike - s)
                # Put pain (puts ITM below test_strike)
                if s > test_strike:
                    pain += oi["put_oi"] * (s - test_strike)
            if pain < min_pain:
                min_pain = pain
                max_pain_strike = test_strike

        return float(max_pain_strike)
    except Exception as e:
        logger.debug(f"Max pain calculation error: {e}")
        return 0.0


def analyze_options(symbol: str = "NIFTY") -> OptionsSnapshot:
    """Full options analysis for a symbol."""
    snap = OptionsSnapshot(symbol=symbol)

    data = get_option_chain(symbol)
    if not data:
        snap.summary = "NSE options data unavailable"
        return snap

    try:
        records = data["records"]  # chain_data alias removed — was unused
        filtered = data.get("filtered", {})

        snap.spot_price = float(records.get("underlyingValue", 0))

        # Get nearest expiry
        expiries = records.get("expiryDates", [])
        snap.expiry = expiries[0] if expiries else "N/A"

        # Filter to nearest expiry
        expiry_data = [d for d in records.get("data", [])
                       if d.get("expiryDate") == snap.expiry]

        total_call_oi = 0
        total_put_oi = 0
        call_oi_by_strike = {}
        put_oi_by_strike = {}

        for item in expiry_data:
            strike = item["strikePrice"]
            ce = item.get("CE", {})
            pe = item.get("PE", {})
            call_oi = ce.get("openInterest", 0) or 0
            put_oi  = pe.get("openInterest",  0) or 0
            total_call_oi += call_oi
            total_put_oi  += put_oi
            call_oi_by_strike[strike] = call_oi
            put_oi_by_strike[strike]  = put_oi

        snap.total_call_oi = total_call_oi
        snap.total_put_oi  = total_put_oi

        # PCR
        if total_call_oi > 0:
            snap.pcr = round(total_put_oi / total_call_oi, 2)
        if snap.pcr > 1.3:
            snap.pcr_state = "BULLISH"  # High put writing = bullish
        elif snap.pcr < 0.7:
            snap.pcr_state = "BEARISH"
        else:
            snap.pcr_state = "NEUTRAL"

        # Max Pain
        snap.max_pain = calculate_max_pain(data)

        # Key OI levels near spot
        spot = snap.spot_price
        nearby_strikes = [s for s in call_oi_by_strike if abs(s - spot) / spot < 0.05]

        if call_oi_by_strike:
            snap.resistance_from_oi = max(
                (s for s in call_oi_by_strike if s >= spot),
                key=lambda s: call_oi_by_strike[s],
                default=spot
            )
        if put_oi_by_strike:
            snap.support_from_oi = max(
                (s for s in put_oi_by_strike if s <= spot),
                key=lambda s: put_oi_by_strike[s],
                default=spot
            )

        # Unusual activity (large OI concentration near spot)
        for strike in nearby_strikes:
            call_oi = call_oi_by_strike.get(strike, 0)
            put_oi  = put_oi_by_strike.get(strike, 0)
            if call_oi > total_call_oi * 0.15:  # >15% of total in one strike
                snap.unusual_activity.append(f"{strike}CE: {call_oi:,} OI (heavy resistance)")
            if put_oi > total_put_oi * 0.15:
                snap.unusual_activity.append(f"{strike}PE: {put_oi:,} OI (strong support)")

        # Overall signal
        if snap.pcr_state == "BULLISH" and spot > snap.max_pain:
            snap.signal = "BULLISH"
        elif snap.pcr_state == "BEARISH" and spot < snap.max_pain:
            snap.signal = "BEARISH"
        else:
            snap.signal = "NEUTRAL"

        snap.summary = (
            f"{symbol} | Spot: {snap.spot_price:,.0f} | "
            f"Max Pain: {snap.max_pain:,.0f} | PCR: {snap.pcr} ({snap.pcr_state}) | "
            f"Support: {snap.support_from_oi:,.0f} | Resistance: {snap.resistance_from_oi:,.0f}"
        )
        logger.info(f"Options: {snap.summary}")

    except Exception as e:
        logger.error(f"Options analysis error: {e}")
        snap.summary = f"Error: {e}"

    return snap


def generate_options_signal(snap: OptionsSnapshot) -> Optional[dict]:
    """Generate a CALL or PUT signal from options analysis."""
    if snap.signal == "NEUTRAL" or snap.spot_price == 0:
        return None

    spot = snap.spot_price
    if snap.signal == "BULLISH":
        # Buy CALL near ATM
        strike = round(spot / 50) * 50  # Round to nearest 50
        if strike < spot:
            strike += 50
        return {
            "signal_type": "BUY_CALL",
            "symbol": snap.symbol,
            "strategy": "OPTIONS_OI_ANALYSIS",
            "strike": strike,
            "expiry": snap.expiry,
            "entry_note": f"Buy {snap.symbol} {strike} CE",
            "target_note": f"Target when price moves to {snap.resistance_from_oi:,.0f}",
            "sl_note": f"SL if price breaks below {snap.support_from_oi:,.0f}",
            "reason": (
                f"PCR {snap.pcr} (bullish) | Max Pain {snap.max_pain:,.0f} above spot | "
                f"Strong put support at {snap.support_from_oi:,.0f}"
            ),
            "confidence": 72,
            "risk_reward": 1.8,
        }
    else:
        # Buy PUT
        strike = round(spot / 50) * 50
        if strike > spot:
            strike -= 50
        return {
            "signal_type": "BUY_PUT",
            "symbol": snap.symbol,
            "strategy": "OPTIONS_OI_ANALYSIS",
            "strike": strike,
            "expiry": snap.expiry,
            "entry_note": f"Buy {snap.symbol} {strike} PE",
            "target_note": f"Target when price drops to {snap.support_from_oi:,.0f}",
            "sl_note": f"SL if price breaks above {snap.resistance_from_oi:,.0f}",
            "reason": (
                f"PCR {snap.pcr} (bearish) | Max Pain {snap.max_pain:,.0f} below spot | "
                f"Heavy call resistance at {snap.resistance_from_oi:,.0f}"
            ),
            "confidence": 68,
            "risk_reward": 1.8,
        }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Fetching NIFTY options chain...")
    snap = analyze_options("NIFTY")
    print(f"\n{snap.summary}")
    print(f"Signal: {snap.signal}")
    if snap.unusual_activity:
        print(f"Unusual Activity:")
        for a in snap.unusual_activity:
            print(f"  * {a}")
    sig = generate_options_signal(snap)
    if sig:
        print(f"\nOptions Signal: {sig['signal_type']} — {sig['entry_note']}")
        print(f"Reason: {sig['reason']}")
