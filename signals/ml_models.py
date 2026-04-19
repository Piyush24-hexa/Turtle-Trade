"""
signals/ml_models.py
Machine Learning signal enhancement.
Model 1: Random Forest Classifier (BUY/SELL/HOLD)
Model 2: LSTM Price Direction Predictor (UP/DOWN/FLAT)
Both models are trained on historical NSE data using yfinance.
"""

import os
import logging
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

MODELS_DIR = Path("models")
MODELS_DIR.mkdir(exist_ok=True)

RF_MODEL_PATH  = MODELS_DIR / "random_forest.pkl"
LSTM_MODEL_PATH = MODELS_DIR / "lstm_model.keras"
SCALER_PATH    = MODELS_DIR / "scaler.pkl"

# ─────────────────────────────────────────────────
# FEATURE ENGINEERING
# ─────────────────────────────────────────────────

def compute_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Build 30+ features from OHLCV for ML models.
    All features are normalized ratios/percentages to be scale-independent.
    """
    f = pd.DataFrame(index=df.index)
    c = df["close"]
    h = df["high"]
    l = df["low"]
    v = df["volume"]

    # Price momentum
    for p in [1, 3, 5, 10, 20]:
        f[f"ret_{p}d"] = c.pct_change(p)

    # EMAs
    for span in [9, 21, 50]:
        ema = c.ewm(span=span, adjust=False).mean()
        f[f"ema{span}_dist"] = (c - ema) / ema  # % distance from EMA

    # RSI
    delta = c.diff()
    gain = delta.clip(lower=0).ewm(com=13, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(com=13, adjust=False).mean()
    rs = gain / loss.replace(0, 1e-10)
    f["rsi"] = (100 - 100 / (1 + rs)) / 100  # Normalize to 0-1

    # MACD
    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    f["macd_hist"] = (macd - signal) / c  # Normalized

    # Bollinger Band position
    bb_mid = c.rolling(20).mean()
    bb_std = c.rolling(20).std()
    f["bb_position"] = (c - bb_mid) / (2 * bb_std + 1e-10)  # -1 to +1

    # ATR (normalized)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(com=13, adjust=False).mean()
    f["atr_pct"] = atr / c

    # Volume features
    vol_avg = v.rolling(20).mean()
    f["vol_ratio"] = v / vol_avg.replace(0, 1)
    f["vol_trend"] = vol_avg.pct_change(5)

    # Candle features
    f["body_pct"]  = (c - df["open"]) / (h - l + 1e-10)  # -1 (full bear) to +1 (full bull)
    f["upper_wick"] = (h - pd.concat([c, df["open"]], axis=1).max(axis=1)) / (h - l + 1e-10)
    f["lower_wick"] = (pd.concat([c, df["open"]], axis=1).min(axis=1) - l) / (h - l + 1e-10)

    # High/Low of range
    f["dist_52w_high"] = (c / h.rolling(252, min_periods=50).max()) - 1
    f["dist_52w_low"]  = (c / l.rolling(252, min_periods=50).min()) - 1

    # VWAP (normalized distance)
    typical_price = (h + l + c) / 3
    vwap = (typical_price * v).cumsum() / v.cumsum().replace(0, 1)
    f["vwap_dist"] = (c - vwap) / vwap

    # Stochastic Oscillator
    low_14 = l.rolling(14).min()
    high_14 = h.rolling(14).max()
    f["stoch_k"] = (c - low_14) / (high_14 - low_14 + 1e-10)
    f["stoch_d"] = f["stoch_k"].rolling(3).mean()

    # On-Balance Volume (normalized delta)
    obv = (np.sign(c.diff()) * v).cumsum()
    f["obv_trend"] = obv.pct_change(5)

    return f.fillna(0)


def create_labels(df: pd.DataFrame, forward_days: int = 5, base_threshold: float = 0.015) -> pd.Series:
    """
    Create classification labels for RF model using ATR-dynamic thresholding.
    BUY=2 if future return > ATR-adjusted threshold
    SELL=0 if future return < -ATR-adjusted threshold
    HOLD=1 otherwise
    """
    future_ret = df["close"].shift(-forward_days) / df["close"] - 1
    
    # Calculate rolling ATR percentage for volatility context
    c, h, l = df["close"], df["high"], df["low"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()
    atr_pct = atr / c
    
    # Dynamic threshold: base threshold + a fraction of volatility, min capped at 1%
    dynamic_threshold = (base_threshold + atr_pct * 0.5).clip(lower=0.01)
    
    labels = pd.Series(1, index=df.index)  # Default HOLD
    labels[future_ret > dynamic_threshold] = 2     # BUY
    labels[future_ret < -dynamic_threshold] = 0    # SELL
    return labels


# ─────────────────────────────────────────────────
# RANDOM FOREST MODEL
# ─────────────────────────────────────────────────

def train_random_forest(symbols: list = None, retrain: bool = False):
    """
    Train Random Forest on historical NSE data.
    Uses Nifty 50 stocks by default.
    """
    try:
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.preprocessing import StandardScaler
        from sklearn.model_selection import train_test_split
        from sklearn.metrics import classification_report
        import joblib
        import yfinance as yf
    except ImportError as e:
        logger.error(f"scikit-learn not installed: {e}")
        return None

    if RF_MODEL_PATH.exists() and not retrain:
        logger.info("Loading existing RF model...")
        return joblib.load(RF_MODEL_PATH)

    symbols = symbols or [
        "RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS", "ICICIBANK.NS",
        "SBIN.NS", "ITC.NS", "WIPRO.NS", "AXISBANK.NS", "LT.NS",
        "BAJFINANCE.NS", "MARUTI.NS", "TATAMOTORS.NS", "SUNPHARMA.NS",
        "BHARTIARTL.NS", "HCLTECH.NS", "KOTAKBANK.NS", "NTPC.NS",
    ]

    logger.info(f"Training Random Forest on {len(symbols)} stocks (3 years data)...")
    all_X, all_y = [], []

    for sym in symbols:
        try:
            df = yf.Ticker(sym).history(period="3y")
            if len(df) < 100:
                continue
            df.columns = df.columns.str.lower()
            df = df[["open","high","low","close","volume"]]

            features = compute_features(df)
            labels = create_labels(df)

            # Align
            valid = features.notna().all(axis=1) & labels.notna()
            X = features[valid].values[:-5]  # Remove last 5 (no future label)
            y = labels[valid].values[:-5]

            all_X.append(X)
            all_y.append(y)
        except Exception as e:
            logger.debug(f"  Skip {sym}: {e}")

    if not all_X:
        logger.error("No training data collected")
        return None

    X = np.vstack(all_X)
    y = np.concatenate(all_y)

    # Train/test split (time-based to prevent leakage)
    split_idx = int(len(X) * 0.8)
    X_train = X[:split_idx]
    X_test = X[split_idx:]
    y_train = y[:split_idx]
    y_test = y[split_idx:]

    # Scale features
    scaler = StandardScaler()
    X_train_s = scaler.fit_transform(X_train)
    X_test_s  = scaler.transform(X_test)

    # Train model
    model = RandomForestClassifier(
        n_estimators=300,
        max_depth=15,
        min_samples_leaf=15,
        n_jobs=-1,
        random_state=42,
        class_weight="balanced_subsample",
    )
    model.fit(X_train_s, y_train)

    # Evaluate
    y_pred = model.predict(X_test_s)
    accuracy = (y_pred == y_test).mean()
    logger.info(f"RF Model trained: {accuracy:.1%} accuracy on test set")

    # Save
    import joblib
    joblib.dump(model, RF_MODEL_PATH)
    joblib.dump(scaler, SCALER_PATH)
    logger.info(f"RF model saved to {RF_MODEL_PATH}")
    return model


def predict_rf(df: pd.DataFrame) -> dict:
    """
    Predict BUY/SELL/HOLD for a stock using the RF model.
    Returns: {label, probability, confidence}
    """
    try:
        import joblib
        if not RF_MODEL_PATH.exists():
            logger.info("RF model not trained yet — training now (one time)...")
            train_random_forest()

        model  = joblib.load(RF_MODEL_PATH)
        scaler = joblib.load(SCALER_PATH)

        features = compute_features(df).fillna(0)
        X = scaler.transform(features.values[-1:])
        proba = model.predict_proba(X)[0]  # [SELL, HOLD, BUY] probabilities
        pred_class = model.predict(X)[0]

        label_map = {0: "SELL", 1: "HOLD", 2: "BUY"}
        label = label_map[pred_class]
        confidence = float(max(proba))

        return {
            "label": label,
            "confidence": round(confidence, 3),
            "sell_prob": round(float(proba[0]), 3),
            "hold_prob": round(float(proba[1]), 3),
            "buy_prob":  round(float(proba[2]), 3),
        }
    except Exception as e:
        logger.debug(f"RF prediction error: {e}")
        return {"label": "HOLD", "confidence": 0.5, "buy_prob": 0.33, "sell_prob": 0.33, "hold_prob": 0.34}


# ─────────────────────────────────────────────────
# LSTM MODEL
# ─────────────────────────────────────────────────

def train_lstm(symbols: list = None, retrain: bool = False):
    """Train LSTM for price direction prediction."""
    try:
        import tensorflow as tf
        from tensorflow import keras
        import yfinance as yf
        from sklearn.preprocessing import MinMaxScaler
    except ImportError as e:
        logger.warning(f"TensorFlow not installed — LSTM unavailable: {e}")
        return None

    if LSTM_MODEL_PATH.exists() and not retrain:
        logger.info("Loading existing LSTM model...")
        try:
            return keras.models.load_model(str(LSTM_MODEL_PATH))
        except Exception:
            pass

    seq_len = 60
    symbols = symbols or ["^NSEI", "RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS"]
    logger.info(f"Training LSTM model (this takes 10-20 minutes)...")

    all_X, all_y = [], []
    
    scaler = MinMaxScaler()
    import joblib

    all_features = []
    symbol_data = {}

    for sym in symbols:
        try:
            df = yf.Ticker(sym).history(period="5y")
            if len(df) < seq_len + 10:
                continue
            df.columns = df.columns.str.lower()
            
            # Use the entire suite of 30+ features instead of just price
            features = compute_features(df)
            
            # Mix out any uncomputable infinity data or NaNs to 0
            features = features.replace([np.inf, -np.inf], np.nan).fillna(0)
            
            f_values = features.values
            all_features.append(f_values)
            symbol_data[sym] = (df, f_values)
        except Exception as e:
            logger.debug(f"LSTM skip {sym}: {e}")

    if not all_features:
        logger.error("Not enough LSTM training data")
        return None

    # Fit scaler globally on all training data
    global_features = np.vstack(all_features)
    scaler.fit(global_features)
    joblib.dump(scaler, str(MODELS_DIR / "lstm_scaler.pkl"))
    
    num_features = global_features.shape[1]

    for sym, (df, f_values) in symbol_data.items():
        scaled = scaler.transform(f_values)
        for i in range(seq_len, len(scaled) - 5):
            X_seq = scaled[i - seq_len:i, :] # Take all features for sequence window
            future_ret = (df["close"].iloc[i+5] - df["close"].iloc[i]) / df["close"].iloc[i]
            label = 1 if future_ret > 0.015 else (0 if future_ret < -0.015 else 2)
            all_X.append(X_seq)
            all_y.append(label)

    if len(all_X) < 100:
        logger.error("Not enough LSTM training data extracted")
        return None

    X = np.array(all_X) # Shape: (samples, seq_len, num_features)
    y = keras.utils.to_categorical(all_y, 3)

    # Re-architect deep neural net with Bidirectional & BatchNormalization
    model = keras.Sequential([
        keras.layers.Input(shape=(seq_len, num_features)),
        keras.layers.BatchNormalization(),
        keras.layers.Bidirectional(keras.layers.LSTM(64, return_sequences=True)),
        keras.layers.Dropout(0.3),
        keras.layers.BatchNormalization(),
        keras.layers.Bidirectional(keras.layers.LSTM(32)),
        keras.layers.Dropout(0.3),
        keras.layers.Dense(32, activation="relu"),
        keras.layers.BatchNormalization(),
        keras.layers.Dense(3, activation="softmax"),
    ])
    model.compile(optimizer="adam", loss="categorical_crossentropy", metrics=["accuracy"])

    split = int(len(X) * 0.8)
    model.fit(X[:split], y[:split], epochs=20, batch_size=32,
              validation_data=(X[split:], y[split:]), verbose=1)

    model.save(str(LSTM_MODEL_PATH))
    logger.info(f"LSTM model saved to {LSTM_MODEL_PATH}")
    return model


def predict_lstm(df: pd.DataFrame) -> dict:
    """Predict price direction using LSTM."""
    try:
        import tensorflow as tf
        from tensorflow import keras
        from sklearn.preprocessing import MinMaxScaler

        if not LSTM_MODEL_PATH.exists():
            return {"direction": "UNKNOWN", "up_prob": 0.33, "down_prob": 0.33, "flat_prob": 0.34}

        model = keras.models.load_model(str(LSTM_MODEL_PATH))
        seq_len = 60

        if len(df) < seq_len:
            return {"direction": "UNKNOWN", "up_prob": 0.33, "down_prob": 0.33, "flat_prob": 0.34}

        features = compute_features(df).replace([np.inf, -np.inf], np.nan).fillna(0)
        f_values = features.values[-seq_len:]
        
        import joblib
        lstm_scaler_pkl = MODELS_DIR / "lstm_scaler.pkl"
        if not lstm_scaler_pkl.exists():
            return {"direction": "UNKNOWN", "up_prob": 0.33, "down_prob": 0.33, "flat_prob": 0.34}
        scaler = joblib.load(str(lstm_scaler_pkl))
        
        try:
            scaled = scaler.transform(f_values)
        except ValueError as ve:
            # Scaler configuration mismatch (old scaler with single feature vs new 30+ features)
            logger.warning(f"LSTM scaler mismatch - model architecture likely updated. Please let it retrain. {ve}")
            return {"direction": "UNKNOWN", "up_prob": 0.33, "down_prob": 0.33, "flat_prob": 0.34}

        num_features = scaled.shape[1]
        X = scaled.reshape(1, seq_len, num_features)

        proba = model.predict(X, verbose=0)[0]
        dirs = ["DOWN", "UP", "FLAT"]
        pred = dirs[np.argmax(proba)]

        return {
            "direction": pred,
            "up_prob":   round(float(proba[1]), 3),
            "down_prob": round(float(proba[0]), 3),
            "flat_prob": round(float(proba[2]), 3),
        }
    except Exception as e:
        logger.debug(f"LSTM prediction error: {e}")
        return {"direction": "UNKNOWN", "up_prob": 0.33, "down_prob": 0.33, "flat_prob": 0.34}


# ─────────────────────────────────────────────────
# COMBINED ML SCORE
# ─────────────────────────────────────────────────

def ml_signal_score(df: pd.DataFrame) -> dict:
    """
    Combine RF + LSTM into a single ML conviction score (0-1).
    >0.6 = bullish, <0.4 = bearish, 0.4-0.6 = neutral
    """
    rf  = predict_rf(df)
    lstm = predict_lstm(df)

    # RF score: BUY=1, HOLD=0.5, SELL=0
    rf_score = {"BUY": 1.0, "HOLD": 0.5, "SELL": 0.0}.get(rf["label"], 0.5)
    rf_weighted = rf_score * rf["confidence"]

    # LSTM score
    lstm_score = lstm["up_prob"] if lstm["direction"] in ("UP", "UNKNOWN") else lstm["down_prob"]
    if lstm["direction"] == "DOWN":
        lstm_score = 1 - lstm["up_prob"]
    else:
        lstm_score = lstm["up_prob"]

    # Weighted combination
    combined = rf_weighted * 0.55 + lstm_score * 0.45

    return {
        "score": round(combined, 3),
        "rf": rf,
        "lstm": lstm,
        "signal": "BUY" if combined > 0.6 else ("SELL" if combined < 0.4 else "HOLD"),
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    import yfinance as yf

    # Train RF model (downloads data, takes a few minutes)
    print("Training Random Forest model...")
    train_random_forest()

    # Test prediction
    print("\nTesting predictions for RELIANCE...")
    df = yf.Ticker("RELIANCE.NS").history(period="3mo")
    df.columns = df.columns.str.lower()
    df = df[["open","high","low","close","volume"]]

    result = ml_signal_score(df)
    print(f"  RF:   {result['rf']['label']} ({result['rf']['confidence']:.0%})")
    print(f"  LSTM: {result['lstm']['direction']} (up_prob={result['lstm']['up_prob']:.0%})")
    print(f"  Combined score: {result['score']:.2f} -> {result['signal']}")
