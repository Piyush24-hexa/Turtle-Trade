"""
demo_data.py
Contains mock data previously embedded in the api_server.py
"""

def _demo_signals():
    return [
        {"symbol": "INFY", "signal_type": "BUY", "mode": "EQUITY",
         "strategy": "BREAKOUT", "conviction": "HIGH", "overall_score": 88,
         "technical_score": 82, "ml_score": 88, "sentiment_score": 84,
         "pattern_score": 90, "fundamental_score": 72,
         "entry": 1319.20, "target": 1369.02, "stop_loss": 1294.29,
         "risk_reward": 2.0, "return_pct": 3.78, "risk_pct": 1.89,
         "quantity": 3, "investment": 3957.6, "risk_amount": 74.73,
         "reason": "Bullish breakout above Rs.1,314 resistance with 2.1x volume surge",
         "pattern": "BULL_FLAG", "rf_label": "BUY", "lstm_direction": "UP",
         "lstm_up_prob": 0.88, "news_headline": "Infosys wins $500M US contract",
         "sentiment": "POSITIVE", "confidence": 88, "paper_trade": True},
        {"symbol": "HDFCBANK", "signal_type": "BUY", "mode": "EQUITY",
         "strategy": "SR_BOUNCE", "conviction": "MEDIUM", "overall_score": 74,
         "technical_score": 70, "ml_score": 68, "sentiment_score": 60,
         "pattern_score": 75, "fundamental_score": 65,
         "entry": 795.45, "target": 823.95, "stop_loss": 781.20,
         "risk_reward": 2.0, "return_pct": 3.58, "risk_pct": 1.79,
         "quantity": 6, "investment": 4772.7, "risk_amount": 85.5,
         "reason": "Support bounce at Rs.793 | RSI 46 | SIDEWAYS market",
         "pattern": "HAMMER", "rf_label": "BUY", "lstm_direction": "UP",
         "lstm_up_prob": 0.68, "confidence": 74, "paper_trade": True},
        {"symbol": "ITC", "signal_type": "BUY", "mode": "EQUITY",
         "strategy": "RSI_REVERSAL", "conviction": "MEDIUM", "overall_score": 70,
         "technical_score": 68, "sentiment_score": 52,
         "entry": 303.40, "target": 313.58, "stop_loss": 298.31,
         "risk_reward": 2.0, "return_pct": 3.36, "risk_pct": 1.68,
         "quantity": 16, "investment": 4854.4, "risk_amount": 81.44,
         "reason": "RSI reversal from oversold zone | Support at Rs.303",
         "confidence": 70, "paper_trade": True},
    ]

def _demo_news():
    return [
        {"title": "Infosys wins $500M digital transformation deal", "sentiment": "positive", "source": "ET Markets", "symbols": ["INFY"], "score": 0.91},
        {"title": "HDFC Bank Q4 profit beats estimates; NIM improves", "sentiment": "positive", "source": "MoneyControl", "symbols": ["HDFCBANK"], "score": 0.84},
        {"title": "RBI holds repo rate at 6.5%, stance accommodative", "sentiment": "neutral", "source": "Business Standard", "symbols": [], "score": 0.5},
        {"title": "Reliance Q4 profit up 18% YoY, Jio adds 8M subscribers", "sentiment": "positive", "source": "LiveMint", "symbols": ["RELIANCE"], "score": 0.88},
        {"title": "Global tech selloff drags Nifty IT lower", "sentiment": "negative", "source": "Financial Express", "symbols": ["TCS", "WIPRO"], "score": 0.73},
        {"title": "ITC Q4 results: Revenue grows 8%, margins stable", "sentiment": "positive", "source": "ET Markets", "symbols": ["ITC"], "score": 0.75},
    ]

def _demo_intraday_signals():
    return [
        {"symbol": "TCS", "signal_type": "BUY", "mode": "INTRADAY",
         "strategy": "ORB", "conviction": "MEDIUM", "overall_score": 73,
         "technical_score": 73, "ml_score": 65, "sentiment_score": 50,
         "entry": 3542.50, "target": 3577.93, "stop_loss": 3524.79,
         "risk_reward": 2.0, "return_pct": 1.0, "risk_pct": 0.5,
         "quantity": 1, "investment": 3542.5, "risk_amount": 17.71,
         "vwap": 3535.00, "orb_high": 3540.00, "orb_low": 3518.00,
         "supertrend_dir": 1, "rsi": 58, "vol_ratio": 2.1,
         "reason": "ORB breakout above 3540 | Vol 2.1x | Supertrend UP",
         "confidence": 73, "paper_trade": True, "pattern": "", "news_headline": ""},
    ]
