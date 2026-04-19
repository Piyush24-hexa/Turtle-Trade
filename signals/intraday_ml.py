"""
signals/intraday_ml.py
=====================
Intraday-specific ML model using LightGBM.
Completely separate from ml_models.py (daily RF/LSTM).

Features:  40+ intraday indicators (VWAP, ORB, Supertrend, time-of-day, etc.)
Labels:    Triple-barrier method (target hit first = BUY, stop hit first = SELL)
Validate:  Walk-forward cross-validation
Model:     LightGBM Classifier (fast, regularized, handles noisy 5m data)
"""

import os
import logging
import math
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

MODELS_DIR = Path(__file__).parent.parent / "models"
MODELS_DIR.mkdir(exist_ok=True)

LGBM_MODEL_PATH = MODELS_DIR / "intraday_lgbm.pkl"
LGBM_SCALER_PATH = MODELS_DIR / "intraday_scaler.pkl"
LGBM_FEATURES_PATH = MODELS_DIR / "intraday_features.pkl"


# =====================================================
# SUPERTREND CALCULATION (used in features + strategy)
# =====================================================

def calc_supertrend(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0):
    """
    Compute Supertrend indicator.
    Returns DataFrame with 'supertrend' and 'st_direction' columns.
    st_direction: +1 = UP (bullish), -1 = DOWN (bearish)
    """
    hl2 = (df["high"] + df["low"]) / 2

    # ATR
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - df["close"].shift(1)).abs(),
        (df["low"] - df["close"].shift(1)).abs(),
    ], axis=1).max(axis=1)
    atr = tr.ewm(com=period - 1, adjust=False).mean()

    upper_band = hl2 + multiplier * atr
    lower_band = hl2 - multiplier * atr

    supertrend = pd.Series(np.nan, index=df.index)
    direction = pd.Series(1, index=df.index)

    for i in range(1, len(df)):
        # Carry forward bands
        if df["close"].iloc[i - 1] > upper_band.iloc[i - 1]:
            direction.iloc[i] = 1
        elif df["close"].iloc[i - 1] < lower_band.iloc[i - 1]:
            direction.iloc[i] = -1
        else:
            direction.iloc[i] = direction.iloc[i - 1]

        if direction.iloc[i] == 1:
            supertrend.iloc[i] = lower_band.iloc[i]
            # Don't let support drop below previous support in uptrend
            if i > 1 and not np.isnan(supertrend.iloc[i - 1]):
                supertrend.iloc[i] = max(supertrend.iloc[i], supertrend.iloc[i - 1])
        else:
            supertrend.iloc[i] = upper_band.iloc[i]
            # Don't let resistance rise above previous resistance in downtrend
            if i > 1 and not np.isnan(supertrend.iloc[i - 1]):
                supertrend.iloc[i] = min(supertrend.iloc[i], supertrend.iloc[i - 1])

    return supertrend, direction


# =====================================================
# VWAP CALCULATION
# =====================================================

def calc_vwap(df: pd.DataFrame):
    """
    Calculate VWAP and VWAP standard deviation bands.
    Assumes df contains one trading day of intraday data.
    Returns: vwap, vwap_upper (1 sigma), vwap_lower (1 sigma),
             vwap_upper2 (2 sigma), vwap_lower2 (2 sigma)
    """
    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    cum_tp_vol = (typical_price * df["volume"]).cumsum()
    cum_vol = df["volume"].cumsum().replace(0, 1)
    vwap = cum_tp_vol / cum_vol

    # VWAP standard deviation bands
    cum_tp2_vol = (typical_price ** 2 * df["volume"]).cumsum()
    variance = (cum_tp2_vol / cum_vol) - vwap ** 2
    variance = variance.clip(lower=0)
    std = np.sqrt(variance)

    return vwap, vwap + std, vwap - std, vwap + 2 * std, vwap - 2 * std


# =====================================================
# INTRADAY FEATURE ENGINEERING
# =====================================================

def compute_intraday_features(df: pd.DataFrame, prev_day: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """
    Build 40+ intraday features from 5-minute OHLCV.
    All features are scale-independent (ratios, percentages, normalized).
    """
    f = pd.DataFrame(index=df.index)
    c = df["close"]
    h = df["high"]
    l = df["low"]
    o = df["open"]
    v = df["volume"]

    # ── PRICE MOMENTUM ──
    for p in [3, 6, 12, 24]:
        f[f"ret_{p}c"] = c.pct_change(p)

    f["close_vs_open_today"] = (c - o.iloc[0]) / o.iloc[0]
    f["candle_body"] = (c - o) / (h - l + 1e-10)  # Normalized body
    f["upper_wick"] = (h - pd.concat([c, o], axis=1).max(axis=1)) / (h - l + 1e-10)
    f["lower_wick"] = (pd.concat([c, o], axis=1).min(axis=1) - l) / (h - l + 1e-10)

    # ── VWAP ──
    try:
        vwap, vwap_u1, vwap_l1, vwap_u2, vwap_l2 = calc_vwap(df)
        f["vwap_distance"] = (c - vwap) / vwap
        f["vwap_upper1_dist"] = (c - vwap_u1) / vwap
        f["vwap_lower1_dist"] = (c - vwap_l1) / vwap
        f["vwap_upper2_dist"] = (c - vwap_u2) / vwap
        f["vwap_lower2_dist"] = (c - vwap_l2) / vwap
        f["vwap_slope"] = vwap.pct_change(3)
    except Exception:
        for col in ["vwap_distance", "vwap_upper1_dist", "vwap_lower1_dist",
                     "vwap_upper2_dist", "vwap_lower2_dist", "vwap_slope"]:
            f[col] = 0

    # ── OPENING RANGE (first 3 candles = 15 min for 5m data) ──
    orb_bars = min(3, len(df))
    orb_high = h.iloc[:orb_bars].max()
    orb_low = l.iloc[:orb_bars].min()
    orb_width = (orb_high - orb_low) / orb_low if orb_low > 0 else 0

    f["orb_high_dist"] = (c - orb_high) / orb_high if orb_high > 0 else 0
    f["orb_low_dist"] = (c - orb_low) / orb_low if orb_low > 0 else 0
    f["orb_width"] = orb_width
    f["orb_breakout_up"] = (c > orb_high).astype(float)
    f["orb_breakout_down"] = (c < orb_low).astype(float)

    # ── TIME-OF-DAY (cyclical encoding) ──
    try:
        if hasattr(df.index, 'hour'):
            minutes_since_open = (df.index.hour - 9) * 60 + (df.index.minute - 15)
        else:
            minutes_since_open = pd.Series(range(len(df)), index=df.index)
        total_minutes = 375  # 9:15 to 15:30
        time_frac = minutes_since_open / total_minutes
        f["time_sin"] = np.sin(2 * math.pi * time_frac)
        f["time_cos"] = np.cos(2 * math.pi * time_frac)

        # Session phase (0-4)
        f["session_phase"] = pd.cut(
            minutes_since_open,
            bins=[-1, 30, 120, 240, 330, 400],
            labels=[0, 1, 2, 3, 4],
        ).astype(float)
    except Exception:
        f["time_sin"] = 0
        f["time_cos"] = 0
        f["session_phase"] = 2

    # ── VOLATILITY ──
    tr = pd.concat([h - l, (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1).max(axis=1)
    atr_5 = tr.ewm(com=4, adjust=False).mean()
    atr_20 = tr.ewm(com=19, adjust=False).mean()
    f["atr_5c_pct"] = atr_5 / c
    f["atr_20c_pct"] = atr_20 / c
    f["atr_ratio"] = atr_5 / atr_20.replace(0, 1e-10)

    # Bollinger Band position (5m, 20-period)
    bb_mid = c.rolling(20).mean()
    bb_std = c.rolling(20).std()
    f["bb_position"] = (c - bb_mid) / (2 * bb_std + 1e-10)

    # ── VOLUME DYNAMICS ──
    vol_avg = v.rolling(20).mean().replace(0, 1)
    f["vol_ratio"] = v / vol_avg
    f["vol_acceleration"] = f["vol_ratio"].diff(3)
    f["cumulative_delta_proxy"] = (c - l) / (h - l + 1e-10)  # OBV-like pressure

    # ── RSI (fast and standard) ──
    for period, name in [(7, "rsi_7"), (14, "rsi_14")]:
        delta = c.diff()
        gain = delta.clip(lower=0).ewm(com=period - 1, adjust=False).mean()
        loss = (-delta.clip(upper=0)).ewm(com=period - 1, adjust=False).mean()
        rs = gain / loss.replace(0, 1e-10)
        f[name] = (100 - 100 / (1 + rs)) / 100  # Normalize to 0-1

    # ── EMA ──
    ema5 = c.ewm(span=5, adjust=False).mean()
    ema13 = c.ewm(span=13, adjust=False).mean()
    f["ema5_dist"] = (c - ema5) / ema5
    f["ema13_dist"] = (c - ema13) / ema13

    # EMA cross direction
    ema_diff = ema5 - ema13
    ema_diff_prev = ema_diff.shift(1)
    f["ema5_cross_ema13"] = 0
    f.loc[(ema_diff > 0) & (ema_diff_prev <= 0), "ema5_cross_ema13"] = 1
    f.loc[(ema_diff < 0) & (ema_diff_prev >= 0), "ema5_cross_ema13"] = -1

    # ── MACD (5m) ──
    macd_fast = c.ewm(span=12, adjust=False).mean()
    macd_slow = c.ewm(span=26, adjust=False).mean()
    macd_line = macd_fast - macd_slow
    macd_sig = macd_line.ewm(span=9, adjust=False).mean()
    f["macd_hist_5m"] = (macd_line - macd_sig) / c

    # ── SUPERTREND ──
    try:
        st, st_dir = calc_supertrend(df, period=10, multiplier=3.0)
        f["supertrend_signal"] = st_dir.astype(float)
        f["supertrend_distance"] = (c - st) / c
    except Exception:
        f["supertrend_signal"] = 0
        f["supertrend_distance"] = 0

    # ── PREVIOUS DAY REFERENCE ──
    if prev_day is not None and len(prev_day) > 0:
        prev_close = prev_day["close"].iloc[-1]
        prev_high = prev_day["high"].max()
        prev_low = prev_day["low"].min()
        f["prev_close_dist"] = (c - prev_close) / prev_close
        f["prev_high_dist"] = (c - prev_high) / prev_high
        f["prev_low_dist"] = (c - prev_low) / prev_low
        f["gap_pct"] = (o.iloc[0] - prev_close) / prev_close if prev_close > 0 else 0
    else:
        f["prev_close_dist"] = 0
        f["prev_high_dist"] = 0
        f["prev_low_dist"] = 0
        f["gap_pct"] = 0

    return f.fillna(0).replace([np.inf, -np.inf], 0)


# =====================================================
# TRIPLE-BARRIER LABELING
# =====================================================

def create_triple_barrier_labels(
    df: pd.DataFrame,
    tp_pct: float = 0.005,
    sl_pct: float = 0.005,
    max_bars: int = 12,
) -> pd.Series:
    """
    Triple-barrier method for intraday labels.
    For each bar, look forward up to max_bars:
      - If price hits +tp_pct first  -> BUY  (2)
      - If price hits -sl_pct first  -> SELL (0)
      - If neither within max_bars   -> HOLD (1)
    """
    close = df["close"].values
    high = df["high"].values
    low = df["low"].values
    labels = np.ones(len(close), dtype=int)  # Default HOLD

    for i in range(len(close) - 1):
        entry = close[i]
        tp_level = entry * (1 + tp_pct)
        sl_level = entry * (1 - sl_pct)

        end = min(i + max_bars + 1, len(close))
        for j in range(i + 1, end):
            if high[j] >= tp_level:
                labels[i] = 2  # BUY — target hit first
                break
            if low[j] <= sl_level:
                labels[i] = 0  # SELL — stop hit first
                break

    # Last max_bars rows: no future data, mark as HOLD
    labels[-max_bars:] = 1

    return pd.Series(labels, index=df.index)


# =====================================================
# TRAINING
# =====================================================

def train_intraday_model(symbols: list = None, retrain: bool = False):
    """
    Train LightGBM on 5-minute intraday data (60 days).
    Uses walk-forward cross-validation.
    """
    try:
        import lightgbm as lgb
        from sklearn.preprocessing import StandardScaler
        import joblib
        import yfinance as yf
    except ImportError as e:
        logger.error(f"Missing dependency: {e}. Run: pip install lightgbm")
        return None

    if LGBM_MODEL_PATH.exists() and not retrain:
        logger.info("Loading existing intraday LightGBM model...")
        return joblib.load(LGBM_MODEL_PATH)

    symbols = symbols or [
        "RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS", "ICICIBANK.NS",
        "SBIN.NS", "ITC.NS", "WIPRO.NS", "AXISBANK.NS", "LT.NS",
    ]

    logger.info(f"Training Intraday LightGBM on {len(symbols)} stocks (5m data, 60 days)...")
    all_X, all_y = [], []
    feature_names = None

    for sym in symbols:
        try:
            # Download 5m data (yfinance max 60 days for 5m)
            ticker = yf.Ticker(sym)
            df = ticker.history(period="60d", interval="5m")
            if df is None or len(df) < 200:
                logger.debug(f"  Skip {sym}: insufficient data ({len(df) if df is not None else 0} rows)")
                continue

            df.columns = df.columns.str.lower()
            df = df[["open", "high", "low", "close", "volume"]].copy()
            df = df[df["volume"] > 0]  # Remove zero-volume bars

            # Split into individual trading days
            df["date"] = df.index.date
            day_groups = list(df.groupby("date"))

            for day_idx, (date, day_df) in enumerate(day_groups):
                if len(day_df) < 30:  # Skip short days
                    continue

                # Get previous day data for reference features
                prev_day = day_groups[day_idx - 1][1] if day_idx > 0 else None

                features = compute_intraday_features(day_df, prev_day)
                labels = create_triple_barrier_labels(day_df)

                # Align and collect
                valid = features.notna().all(axis=1) & labels.notna()
                X = features[valid].values
                y = labels[valid].values

                if len(X) > 10:
                    all_X.append(X)
                    all_y.append(y)

                    if feature_names is None:
                        feature_names = features.columns.tolist()

            logger.info(f"  {sym}: processed {len(day_groups)} trading days")

        except Exception as e:
            logger.warning(f"  Skip {sym}: {e}")

    if not all_X:
        logger.error("No intraday training data collected")
        return None

    X = np.vstack(all_X)
    y = np.concatenate(all_y)

    logger.info(f"Training data: {len(X)} samples, {X.shape[1]} features")
    logger.info(f"Label distribution: BUY={np.sum(y==2)}, HOLD={np.sum(y==1)}, SELL={np.sum(y==0)}")

    # Scale features
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    # Walk-forward validation (last 20% for final test)
    split_idx = int(len(X) * 0.8)
    X_train, X_test = X_scaled[:split_idx], X_scaled[split_idx:]
    y_train, y_test = y[:split_idx], y[split_idx:]

    # LightGBM training with sample weights to fight HOLD dominance
    # Weight BUY/SELL 3x more than HOLD so model learns actionable patterns
    sample_weights_train = np.ones(len(y_train))
    sample_weights_train[y_train == 2] = 3.0  # BUY weight
    sample_weights_train[y_train == 0] = 3.0  # SELL weight

    train_data = lgb.Dataset(
        X_train, label=y_train, weight=sample_weights_train,
        feature_name=feature_names,
    )
    test_data = lgb.Dataset(
        X_test, label=y_test, feature_name=feature_names,
        reference=train_data,
    )

    params = {
        "objective": "multiclass",
        "num_class": 3,
        "metric": "multi_logloss",
        "boosting_type": "gbdt",
        "num_leaves": 20,
        "learning_rate": 0.03,
        "feature_fraction": 0.7,
        "bagging_fraction": 0.7,
        "bagging_freq": 5,
        "min_child_samples": 50,
        "reg_alpha": 0.5,
        "reg_lambda": 0.5,
        "is_unbalance": True,
        "verbose": -1,
        "n_jobs": -1,
        "seed": 42,
    }

    callbacks = [
        lgb.log_evaluation(period=50),
        lgb.early_stopping(stopping_rounds=30, verbose=True),
    ]
    model = lgb.train(
        params,
        train_data,
        num_boost_round=500,
        valid_sets=[test_data],
        callbacks=callbacks,
    )

    # Evaluate
    y_pred_proba = model.predict(X_test)
    y_pred = np.argmax(y_pred_proba, axis=1)
    accuracy = (y_pred == y_test).mean()
    logger.info(f"Intraday LightGBM accuracy: {accuracy:.1%}")

    # Feature importance
    importance = model.feature_importance(importance_type="gain")
    if feature_names:
        top_features = sorted(zip(feature_names, importance), key=lambda x: x[1], reverse=True)[:10]
        logger.info("Top 10 features:")
        for fname, imp in top_features:
            logger.info(f"  {fname}: {imp:.0f}")

    # Save
    joblib.dump(model, LGBM_MODEL_PATH)
    joblib.dump(scaler, LGBM_SCALER_PATH)
    joblib.dump(feature_names, LGBM_FEATURES_PATH)
    logger.info(f"Intraday model saved to {LGBM_MODEL_PATH}")

    return model


# =====================================================
# PREDICTION
# =====================================================

def predict_intraday(df: pd.DataFrame, prev_day: Optional[pd.DataFrame] = None) -> dict:
    """
    Predict intraday BUY/SELL/HOLD using the LightGBM model.
    Returns: {label, confidence, buy_prob, sell_prob, hold_prob}
    """
    default_result = {
        "label": "HOLD", "confidence": 0.33,
        "buy_prob": 0.33, "sell_prob": 0.33, "hold_prob": 0.34,
    }

    try:
        import joblib

        if not LGBM_MODEL_PATH.exists():
            logger.info("Intraday model not trained yet - training now...")
            model = train_intraday_model()
            if model is None:
                return default_result
        else:
            model = joblib.load(LGBM_MODEL_PATH)

        scaler = joblib.load(LGBM_SCALER_PATH)

        features = compute_intraday_features(df, prev_day)
        X = scaler.transform(features.values[-1:])

        proba = model.predict(X)[0]  # [SELL, HOLD, BUY] probabilities
        pred_class = int(np.argmax(proba))

        label_map = {0: "SELL", 1: "HOLD", 2: "BUY"}
        label = label_map[pred_class]
        confidence = float(max(proba))

        return {
            "label": label,
            "confidence": round(confidence, 3),
            "sell_prob": round(float(proba[0]), 3),
            "hold_prob": round(float(proba[1]), 3),
            "buy_prob": round(float(proba[2]), 3),
        }

    except Exception as e:
        logger.debug(f"Intraday ML prediction error: {e}")
        return default_result


# =====================================================
# MAIN (standalone test)
# =====================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    import yfinance as yf

    print("=" * 55)
    print("  INTRADAY ML MODEL — LightGBM Training")
    print("=" * 55)

    # Train
    model = train_intraday_model(retrain=True)

    if model:
        # Test prediction on live data
        print("\nTesting prediction on RELIANCE 5m data...")
        ticker = yf.Ticker("RELIANCE.NS")
        df_5m = ticker.history(period="5d", interval="5m")
        df_5m.columns = df_5m.columns.str.lower()
        df_5m = df_5m[["open", "high", "low", "close", "volume"]]

        # Get last trading day
        df_5m["date"] = df_5m.index.date
        days = list(df_5m.groupby("date"))
        if len(days) >= 2:
            prev_day_data = days[-2][1].drop(columns=["date"])
            today_data = days[-1][1].drop(columns=["date"])
            if len(today_data) > 10:
                import joblib
                
                features = compute_intraday_features(today_data, prev_day_data)
                raw_vector = features.values[-1:]
                print(f"Raw features end: {raw_vector[0][:5]}")
                
                scaler = joblib.load(LGBM_SCALER_PATH)
                scaled_x = scaler.transform(raw_vector)
                print(f"Scaled features end: {scaled_x[0][:5]}")
                
                result = predict_intraday(today_data, prev_day_data)
                print(f"  Prediction: {result['label']}")
                print(f"  Confidence: {result['confidence']:.0%}")
                print(f"  BUY prob:   {result['buy_prob']:.0%}")
                print(f"  SELL prob:  {result['sell_prob']:.0%}")
                print(f"  HOLD prob:  {result['hold_prob']:.0%}")
            else:
                print("  Not enough intraday data for today")
        else:
            print("  Not enough days for testing")
    else:
        print("Training failed - check logs")
