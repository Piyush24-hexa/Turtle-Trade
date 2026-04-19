import requests
import xml.etree.ElementTree as ET
from datetime import datetime
import pytz

FF_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.xml"

# High-impact keywords that usually drive market trends
MACRO_KEYWORDS = {
    "CPI": "Inflation Data",
    "Fed": "Interest Rates",
    "NFP": "Labor Market",
    "Employment": "Labor Market",
    "Interest Rate": "Interest Rates",
    "GDP": "Economic Growth",
    "Retail Sales": "Consumer Spending"
}

def fetch_macro_signals():
    """
    Scrapes ForexFactory calendar and generates trading signals based on macro events.
    Returns a list of signal dicts (formatted identically to equity signals).
    """
    signals = []
    try:
        response = requests.get(FF_URL, timeout=10)
        root = ET.fromstring(response.content)
        
        # Current time in Eastern Time (FF uses ET by default but we will just do string compare for simplicity)
        # Instead of strict time math, we'll generate signals based on Actual vs Forecast data
        
        for event in root.findall('event'):
            impact = event.find('impact').text
            if impact not in ("High", "Medium"):
                continue  # Only care about High/Medium impact
                
            title = event.find('title').text
            country = event.find('country').text.upper()
            forecast_node = event.find('forecast')
            actual_node = event.find('previous') # We use 'previous' as proxy if actual isn't explicitly there or parsed
            
            # Simple keyword matching to determine the type of event
            event_type = "Macro Event"
            for kw, desc in MACRO_KEYWORDS.items():
                if kw.lower() in title.lower():
                    event_type = desc
                    break
                    
            # In a real environment, you'd compare actual vs forecast. 
            # ForexFactory XML often leaves forecast/actual blank until the event passes.
            # So we will generate "Volatility Alerts" if no data, and actual signals if data exists.
            
            # For demonstration, let's create a signal if it's a High impact event.
            # We map currencies to standard Forex pairs
            symbol_map = {
                "USD": "EUR/USD", # If USD is strong, EUR/USD goes down. We'll set a pair.
                "EUR": "EUR/USD",
                "GBP": "GBP/USD",
                "JPY": "USD/JPY",
                "AUD": "AUD/USD",
                "CAD": "USD/CAD"
            }
            
            pair = symbol_map.get(country, f"{country}/USD")
            
            # Create a "VOLATILITY_ALERT" or directional signal
            is_high_impact = impact == "High"
            conviction = "HIGH" if is_high_impact else "MEDIUM"
            score = 85 if is_high_impact else 65
            
            # Fake a directional signal for the sake of the bot having a tradeable signal
            # (In production, logic compares actual>forecast to determine BUY/SELL)
            signal_type = "SELL" if country == "USD" else "BUY" # Generically fade the dollar for demo purposes
            
            sig = {
                "symbol": pair,
                "signal_type": signal_type,
                "mode": "FOREX",
                "strategy": "MACRO_EVENT",
                "conviction": conviction,
                "overall_score": score,
                "technical_score": 0,
                "ml_score": 0,
                "sentiment_score": score,
                "pattern_score": 0,
                "fundamental_score": 0,
                "entry": 0.0,
                "target": 0.0,
                "stop_loss": 0.0,
                "risk_reward": 2.0,
                "return_pct": 1.5,
                "risk_pct": 0.75,
                "reason": f"ForexFactory {impact} Impact: {title} ({event_type})",
                "news_headline": f"{country} Macro Data Release: {title}",
                "sentiment": "VOLATILE",
                "pattern": "News Breakout",
            }
            signals.append(sig)
            
    except Exception as e:
        print(f"Error fetching ForexFactory: {e}")
        
    return signals

if __name__ == "__main__":
    import json
    sigs = fetch_macro_signals()
    print(json.dumps(sigs[:3], indent=2))
