"""
crypto_ml.py
Dedicated LightGBM Classifier to predict short-term momentum on Binance 15m intervals.
Downloads the last ~10 days of data across 15 coins (15k samples) and trains 
a probabilistic directional model auto-tuning for crypto volatility.
"""

import os
import sys
import logging
import requests
import joblib
import pandas as pd
import numpy as np
from datetime import datetime
from pathlib import Path
from sklearn.model_selection import train_test_split
import lightgbm as lgb
import warnings

warnings.filterwarnings("ignore")

BASE_DIR = Path(__file__).resolve().parent.parent
MODEL_PATH = BASE_DIR / "models" / "crypto_lgbm.pkl"
MODEL_PATH.parent.mkdir(exist_ok=True)

logger = logging.getLogger(__name__)

BINANCE_BASE = "https://api.binance.com/api/v3"

def fetch_bulk_historical(symbol: str, limit: int = 1000) -> pd.DataFrame:
    """Fetch maximum recent data for training (1000 candles)."""
    try:
        url = f"{BINANCE_BASE}/klines"
        params = {"symbol": symbol, "interval": "15m", "limit": limit}
        res = requests.get(url, params=params, timeout=10)
        res.raise_for_status()
        raw = res.json()
        
        df = pd.DataFrame(raw, columns=[
            "open_time", "open", "high", "low", "close", "volume",
            "close_time", "quote_vol", "trades", "taker_buy_base",
            "taker_buy_quote", "ignore"
        ])
        df = df[["open", "high", "low", "close", "volume"]].astype(float)
        return df
    except Exception as e:
        logger.debug(f"Failed to fetch bulk for {symbol}: {e}")
        return pd.DataFrame()

def extract_features(df: pd.DataFrame) -> pd.DataFrame:
    """Feature Engineering for 15-min crypto trading."""
    c = df["close"]
    h = df["high"]
    l = df["low"]
    v = df["volume"]

    out = pd.DataFrame(index=df.index)
    
    # Core Trends
    out["returns_1"] = c.pct_change(1)
    out["returns_3"] = c.pct_change(3)
    out["returns_5"] = c.pct_change(5)
    out["volatility_5"] = out["returns_1"].rolling(5).std()
    
    # Distance from EMA
    ema20 = c.ewm(span=20).mean()
    ema50 = c.ewm(span=50).mean()
    out["dist_ema20"] = (c - ema20) / c
    out["dist_ema50"] = (c - ema50) / c
    
    # Momentum (RSI surrogate logic)
    delta = c.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / (loss + 1e-9)
    out["rsi_14_mock"] = 100 - (100 / (1 + rs))
    
    # Bollinger Width
    bb_std = c.rolling(20).std()
    out["bb_width"] = (bb_std * 4) / c
    
    # Volume dynamics
    vol_ema = v.ewm(span=20).mean()
    out["vol_ratio"] = v / (vol_ema + 1e-9)
    
    return out.ffill().fillna(0)

def generate_labels(df: pd.DataFrame, lookahead: int = 4) -> pd.Series:
    """Label: 1 if UP > 0.5%, -1 if DOWN < -0.5%, else 0."""
    future_returns = df["close"].shift(-lookahead) / df["close"] - 1
    
    conditions = [
        (future_returns > 0.005),
        (future_returns < -0.005)
    ]
    choices = [1, -1]
    return np.select(conditions, choices, default=0)

def _train_model(coins: list):
    """Downloads fresh 15m data for top coins and trains LightGBM."""
    logger.info("Initializing Crypto ML Pipeline...")
    all_X = []
    all_y = []
    
    for coin in coins:
        df = fetch_bulk_historical(coin, limit=1000)
        if len(df) < 100: continue
            
        X = extract_features(df)
        y = generate_labels(df)
        
        # Drop last `lookahead` rows where future is unknown
        X = X.iloc[50:-4]
        y = y[50:-4]
        
        all_X.append(X)
        all_y.append(y)
        
    if not all_X:
        logger.error("No data fetched for ML training.")
        return None
        
    X_full = pd.concat(all_X, ignore_index=True)
    y_full = np.concatenate(all_y)
    
    feature_names = list(X_full.columns)
    
    # Sample Weights: heavily weight 1 and -1 (BUY/SELL) against dominant 0 (HOLD)
    weights = np.ones(len(y_full))
    weights[y_full == 1] = 3.0
    weights[y_full == -1] = 3.0
    
    params = {
        "objective": "multiclass",
        "num_class": 3,
        "metric": "multi_logloss",
        "boosting_type": "gbdt",
        "learning_rate": 0.05,
        "max_depth": 5,
        "num_leaves": 31,
        "verbose": -1,
        "random_state": 42
    }
    
    X_train, X_test, y_train, y_test, w_train, w_test = train_test_split(
        X_full, y_full, weights, test_size=0.2, shuffle=True, random_state=42
    )
    
    # Remap labels (-1, 0, 1) -> (0, 1, 2)
    y_train_mapped = y_train + 1
    y_test_mapped = y_test + 1
    
    ds_train = lgb.Dataset(X_train, label=y_train_mapped, weight=w_train, feature_name=feature_names)
    ds_test  = lgb.Dataset(X_test, label=y_test_mapped, weight=w_test, feature_name=feature_names)
    
    logger.info(f"Training LightGBM on {len(X_train)} samples...")
    model = lgb.train(
        params,
        ds_train,
        num_boost_round=150,
        valid_sets=[ds_train, ds_test],
        callbacks=[lgb.early_stopping(stopping_rounds=20, verbose=False)]
    )
    
    joblib.dump({"model": model, "features": feature_names}, MODEL_PATH)
    logger.info("Crypto LightGBM trained and saved successfully.")
    return model

# GLobal instance
_LGB_MODEL = None
_LGB_FEATURES = None

def load_or_train_crypto_ml(coins: list = None):
    global _LGB_MODEL, _LGB_FEATURES
    if _LGB_MODEL is not None:
        return True
        
    if MODEL_PATH.exists():
        try:
            data = joblib.load(MODEL_PATH)
            _LGB_MODEL = data["model"]
            _LGB_FEATURES = data["features"]
            return True
        except Exception:
            pass
            
    # Auto-train if offline model missing or corrupted
    if coins:
        _train_model(coins)
        if MODEL_PATH.exists():
            data = joblib.load(MODEL_PATH)
            _LGB_MODEL = data["model"]
            _LGB_FEATURES = data["features"]
            return True
    return False

def predict_crypto(df: pd.DataFrame) -> dict:
    """Returns predictive probabilities for the latest tick."""
    if not load_or_train_crypto_ml():
        return {"buy": 0.0, "sell": 0.0, "hold": 1.0, "score": 50, "bias": "NEUTRAL"}
        
    try:
        if len(df) < 55:
            return {"buy": 0.0, "sell": 0.0, "hold": 1.0, "score": 50, "bias": "NEUTRAL"}
            
        X = extract_features(df).iloc[[-1]]
        # Ensure column order matches training
        X = X[_LGB_FEATURES]
        
        # Predict
        probs = _LGB_MODEL.predict(X)[0] # [P(down), P(hold), P(up)]
        
        # We mapped -1 -> 0(down), 0 -> 1(hold), 1 -> 2(up)
        p_sell = probs[0] * 100
        p_hold = probs[1] * 100
        p_buy  = probs[2] * 100
        
        score = 50
        if p_buy > p_sell and p_buy > 40:
            score = 50 + (p_buy / 2)
            bias = "BULLISH"
        elif p_sell > p_buy and p_sell > 40:
            score = 50 - (p_sell / 2)
            bias = "BEARISH"
        else:
            bias = "NEUTRAL"
            
        return {
            "buy": round(p_buy, 1),
            "sell": round(p_sell, 1),
            "hold": round(p_hold, 1),
            "score": round(score),
            "bias": bias
        }
    except Exception as e:
        logger.debug(f"Crypto ML prediction error: {e}")
        return {"buy": 0.0, "sell": 0.0, "hold": 1.0, "score": 50, "bias": "NEUTRAL"}

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    coins_list = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]
    _train_model(coins_list)
    
    # Test predict
    df_test = fetch_bulk_historical("BTCUSDT", 200)
    print("\nTest Predict BTC:")
    print(predict_crypto(df_test))
