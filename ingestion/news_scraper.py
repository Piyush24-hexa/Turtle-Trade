"""
ingestion/news_scraper.py
Scrapes 10+ financial RSS feeds and scores each article using FinBERT.
FinBERT is a BERT model fine-tuned on financial text — far more accurate
than VADER for stock market news.
"""

import time
import logging
import hashlib
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import feedparser
import re

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────
# RSS FEEDS (all free, no API key needed)
# ─────────────────────────────────────────────────
RSS_FEEDS = {
    "economic_times": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "moneycontrol":   "https://www.moneycontrol.com/rss/MCtopnews.xml",
    "livemint":       "https://www.livemint.com/rss/markets",
    "business_std":   "https://www.business-standard.com/rss/markets-106.rss",
    "nse_news":       "https://www.nseindia.com/api/rss-feed?category=latest-circular",
    "rbi":            "https://www.rbi.org.in/Scripts/bs_viewbulletin.aspx?Id=rss",
    "pib_finance":    "https://pib.gov.in/RssMain.aspx?ModId=6&Lang=1&Regid=3",
    "hindu_business": "https://www.thehindubusinessline.com/markets/?service=rss",
    "financial_exp":  "https://www.financialexpress.com/market/feed/",
    "zeebiz":         "https://www.zeebiz.com/markets/rss",
    "cointelegraph":  "https://cointelegraph.com/rss",
    "coindesk":       "https://www.coindesk.com/arc/outboundfeeds/rss/",
}

# Political/macro figures to watch
POLITICAL_KEYWORDS = {
    "HIGH": [
        "rate hike", "rate cut", "repo rate", "interest rate", "monetary policy",
        "rbi policy", "budget", "fiscal deficit", "gst", "fdi", "ban", "sanction",
        "emergency", "lockdown", "recession", "gdp", "inflation", "cpi", "iip",
        "sebi", "stock ban", "circuit breaker", "market halt",
        "war", "geopolitics", "supply chain", "crude oil", "opec", "missile", 
        "conflict", "treasury yields", "elections", "tariffs", "fed rate"
    ],
    "MEDIUM": [
        "tax", "subsidy", "reform", "policy", "regulation", "initiative",
        "investment", "trade", "export", "import", "tariff", "duty",
        "trade war", "diplomacy"
    ],
}

POLITICAL_FIGURES = [
    "shaktikanta das", "rbi governor", "nirmala sitharaman", "finance minister",
    "narendra modi", "prime minister", "piyush goyal", "ajay bhushan",
    "sebi chairman", "madhabi puri buch",
    "jerome powell", "fed chair", "joe biden", "donald trump", "xi jinping"
]

# ─────────────────────────────────────────────────
# FINBERT LOADER (lazy — loads only when needed)
# ─────────────────────────────────────────────────
_finbert_pipeline = None
_finbert_failed = False

def load_finbert():
    """Load FinBERT model (downloads ~440MB on first run, cached after)."""
    global _finbert_pipeline, _finbert_failed
    if _finbert_pipeline is not None or _finbert_failed:
        return _finbert_pipeline

    try:
        from transformers import pipeline
        logger.info("Loading FinBERT model (first run downloads ~440MB)...")
        _finbert_pipeline = pipeline(
            "text-classification",
            model="ProsusAI/finbert",
            top_k=None,
            truncation=True,
            max_length=512,
        )
        logger.info("FinBERT loaded successfully")
        return _finbert_pipeline
    except Exception as e:
        _finbert_failed = True
        logger.warning(f"FinBERT unavailable ({e}) — falling back to VADER. Install 'transformers' and 'torch' for better accuracy.")
        return None


def _vader_sentiment(text: str) -> tuple[str, float]:
    """Fallback sentiment using VADER."""
    try:
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
        sia = SentimentIntensityAnalyzer()
        score = sia.polarity_scores(text)["compound"]
        if score >= 0.05:
            return "positive", score
        elif score <= -0.05:
            return "negative", abs(score)
        return "neutral", 0.5
    except Exception:
        return "neutral", 0.5


def score_sentiment(text: str) -> tuple[str, float]:
    """
    Score text sentiment using FinBERT (or VADER fallback).
    Returns: (label, confidence) — label = positive/negative/neutral
    """
    nlp = load_finbert()

    if nlp is not None:
        try:
            results = nlp(text[:512])[0]
            best = max(results, key=lambda x: x["score"])
            return best["label"].lower(), round(best["score"], 3)
        except Exception as e:
            logger.debug(f"FinBERT inference error: {e}")

    return _vader_sentiment(text)


# ─────────────────────────────────────────────────
# ARTICLE CACHE (avoid re-processing same articles)
# ─────────────────────────────────────────────────
CACHE_FILE = "ingestion/news_cache.json"
_cache: dict = {}


def _load_cache():
    global _cache
    try:
        if Path(CACHE_FILE).exists():
            with open(CACHE_FILE, "r") as f:
                _cache = json.load(f)
    except Exception:
        _cache = {}


def _save_cache():
    try:
        Path("ingestion").mkdir(exist_ok=True)
        # Keep only last 24h
        cutoff = (datetime.now() - timedelta(hours=24)).isoformat()
        _cache_clean = {k: v for k, v in _cache.items() if v.get("ts", "") > cutoff}
        with open(CACHE_FILE, "w") as f:
            json.dump(_cache_clean, f)
    except Exception:
        pass


def _article_id(title: str) -> str:
    return hashlib.md5(title.encode()).hexdigest()


# ─────────────────────────────────────────────────
# SYMBOL MATCHER
# ─────────────────────────────────────────────────
def _find_symbols(text: str, watchlist: list) -> list:
    """Find which watchlist symbols are mentioned in the text."""
    text_lower = text.lower()
    # Full company name mapping
    NAME_MAP = {
        "RELIANCE": ["reliance", "ril", "reliance industries"],
        "TCS": ["tcs", "tata consultancy"],
        "INFY": ["infosys", "infy"],
        "HDFCBANK": ["hdfc bank", "hdfcbank"],
        "ICICIBANK": ["icici bank", "icicibank"],
        "SBIN": ["sbi", "state bank", "sbin"],
        "ITC": ["itc limited", "itc ltd"],
        "WIPRO": ["wipro"],
        "AXISBANK": ["axis bank", "axisbank"],
        "LT": ["larsen", "l&t", "lt "],
        "BAJFINANCE": ["bajaj finance", "bajfinance"],
        "MARUTI": ["maruti", "suzuki", "msil"],
        "TATAMOTORS": ["tata motors", "tatamotors"],
        "TATASTEEL": ["tata steel", "tatasteel"],
        "ADANIENT": ["adani enterprises", "adanient"],
        "SUNPHARMA": ["sun pharma", "sunpharma", "sun pharmaceutical"],
        "BHARTIARTL": ["airtel", "bharti airtel", "bhartiartl"],
        "HCLTECH": ["hcl tech", "hcltech"],
        "KOTAKBANK": ["kotak mahindra", "kotak bank", "kotakbank"],
        "NTPC": ["ntpc"],
        "ONGC": ["ongc", "oil natural gas"],
        "POWERGRID": ["power grid", "powergrid"],
        "DRREDDY": ["dr reddy", "drreddy"],
        "CIPLA": ["cipla"],
        "DIVISLAB": ["divi's", "divislab"],
        # Crypto
        "BTCUSDT": ["bitcoin", "btc", "satoshi"],
        "ETHUSDT": ["ethereum", "eth", "vitalik"],
        "BNBUSDT": ["binance coin", "bnb"],
        "SOLUSDT": ["solana", "sol "],
        "XRPUSDT": ["ripple", "xrp"],
        "ADAUSDT": ["cardano", "ada "],
        "DOGEUSDT": ["dogecoin", "doge"],
        "AVAXUSDT": ["avalanche", "avax"],
        "MATICUSDT": ["polygon", "matic"],
        "DOTUSDT": ["polkadot", "dot "],
        "LINKUSDT": ["chainlink", "link "],
        "UNIUSDT": ["uniswap", "uni "],
        "LTCUSDT": ["litecoin", "ltc "],
        "ATOMUSDT": ["cosmos", "atom "],
        "NEARUSDT": ["near protocol", "near "],
    }
    found = []
    for sym in watchlist:
        aliases = NAME_MAP.get(sym, [sym.lower()])
        if any(alias in text_lower for alias in aliases):
            found.append(sym)
    return found


# ─────────────────────────────────────────────────
# MAIN SCRAPER
# ─────────────────────────────────────────────────

def scrape_all_feeds(watchlist: list) -> dict:
    """
    Scrape all RSS feeds and return sentiment per symbol.
    Returns: {symbol: {sentiment, score, articles[], impact, political_alert}}
    """
    _load_cache()
    results = {}
    political_alerts = []
    all_articles = []

    # Scrape all feeds
    for source, url in RSS_FEEDS.items():
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:15]:  # Latest 15 per feed
                title = entry.get("title", "")
                summary = entry.get("summary", "")
                text = f"{title}. {summary}"
                pub_date = entry.get("published", datetime.now().isoformat())

                article_id = _article_id(title)
                if article_id in _cache:
                    cached = _cache[article_id]
                    all_articles.append({**cached, "source": source})
                    continue

                # Score sentiment
                label, confidence = score_sentiment(text)

                article = {
                    "id": article_id,
                    "title": title,
                    "sentiment": label,
                    "score": confidence,
                    "source": source,
                    "ts": datetime.now().isoformat(),
                    "symbols": _find_symbols(text, watchlist),
                }

                _cache[article_id] = article
                all_articles.append(article)

                # Check political/macro impact
                text_lower = text.lower()
                for fig in POLITICAL_FIGURES:
                    if fig in text_lower:
                        article["political_figure"] = fig
                        break

                for impact, keywords in POLITICAL_KEYWORDS.items():
                    if any(kw in text_lower for kw in keywords):
                        article["macro_impact"] = impact
                        if impact == "HIGH":
                            political_alerts.append(article)
                        break

            time.sleep(0.3)  # Rate limit
        except Exception as e:
            logger.debug(f"Feed error {source}: {e}")

    _save_cache()

    # Aggregate per symbol
    for sym in watchlist:
        sym_articles = [a for a in all_articles if sym in a.get("symbols", [])]
        if not sym_articles:
            results[sym] = {"sentiment": "neutral", "score": 0.5, "articles": [], "impact": "LOW"}
            continue

        pos = sum(1 for a in sym_articles if a["sentiment"] == "positive")
        neg = sum(1 for a in sym_articles if a["sentiment"] == "negative")
        avg_score = sum(a["score"] for a in sym_articles) / len(sym_articles)

        if pos > neg:
            overall = "positive"
        elif neg > pos:
            overall = "negative"
        else:
            overall = "neutral"

        impact = "HIGH" if (len(sym_articles) >= 3 or avg_score >= 0.80) else \
                 "MEDIUM" if len(sym_articles) >= 1 else "LOW"

        results[sym] = {
            "sentiment": overall,
            "score": round(avg_score, 3),
            "articles": sym_articles[-5:],  # Latest 5
            "impact": impact,
            "pos_count": pos,
            "neg_count": neg,
        }

    logger.info(f"News scan: {len(all_articles)} articles | {len(political_alerts)} political alerts")

    # Add political alerts to result
    results["_political_alerts"] = political_alerts
    results["_all_articles"] = all_articles[:20]

    return results


def get_market_sentiment_summary(news_results: dict) -> str:
    """Overall market sentiment from all news."""
    symbols = [v for k, v in news_results.items() if not k.startswith("_")]
    if not symbols:
        return "NEUTRAL"
    pos = sum(1 for s in symbols if s["sentiment"] == "positive")
    neg = sum(1 for s in symbols if s["sentiment"] == "negative")
    if pos > neg * 1.5:
        return "BULLISH"
    elif neg > pos * 1.5:
        return "BEARISH"
    return "MIXED"


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    import sys
    sys.path.insert(0, "..")
    import config
    print(f"Scanning news for {len(config.WATCHLIST)} stocks...")
    results = scrape_all_feeds(config.WATCHLIST)
    for sym, data in results.items():
        if sym.startswith("_"):
            continue
        if data["articles"]:
            print(f"\n{sym}: {data['sentiment'].upper()} ({data['score']:.0%}) — {len(data['articles'])} articles")
            for a in data["articles"][:2]:
                print(f"  [{a['sentiment'].upper()}] {a['title'][:80]}")
    alerts = results.get("_political_alerts", [])
    if alerts:
        print(f"\n!!! {len(alerts)} HIGH-IMPACT POLITICAL/MACRO ALERTS !!!")
        for a in alerts:
            print(f"  [{a.get('macro_impact')}] {a['title']}")
