import os
import pandas as pd
from datetime import datetime
import logging

import matplotlib
matplotlib.use('Agg')  # Headless mode
import mplfinance as mpf

logger = logging.getLogger(__name__)

def generate_signal_chart(symbol: str, df: pd.DataFrame, signal: dict) -> str:
    """
    Generate a candlestick chart marking entry, stop loss, and target.
    Returns the absolute path to the saved image, or empty string on failure.
    """
    if df is None or len(df) < 20:
        logger.warning(f"Insufficient data to generate chart for {symbol}")
        return ""
    
    try:
        # 1. Directory Setup
        base_dir = os.path.dirname(os.path.dirname(__file__))
        img_dir = os.path.join(base_dir, "signals", "images")
        os.makedirs(img_dir, exist_ok=True)
            
        filename = f"{symbol}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        filepath = os.path.join(img_dir, filename)
        
        # 2. Prepare Data
        # Take the last 50 candles for the chart
        plot_df = df.tail(50).copy()
        
        # Ensure it has a datetime index (mplfinance requirement)
        if 'date' in plot_df.columns:
            plot_df.set_index('date', inplace=True)
        elif 'Date' in plot_df.columns:
            plot_df.set_index('Date', inplace=True)
            
        if not isinstance(plot_df.index, pd.DatetimeIndex):
            plot_df.index = pd.to_datetime(plot_df.index)
            
        # mplfinance requires columns to be capitalized: Open, High, Low, Close, Volume
        col_map = {
            'open': 'Open',
            'high': 'High',
            'low': 'Low',
            'close': 'Close',
            'volume': 'Volume'
        }
        plot_df.rename(columns=col_map, inplace=True)
        
        # 3. Add Lines for Trade Setup
        entry = signal.get("entry")
        sl = signal.get("stop_loss")
        tp = signal.get("target")
        
        lines_to_add = []
        if entry: lines_to_add.append((entry, 'blue'))
        if sl: lines_to_add.append((sl, 'red'))
        if tp: lines_to_add.append((tp, 'green'))
        
        # 4. Add custom markers for detected patterns if any
        pattern = signal.get('pattern')
        title_suffix = f" | Pattern: {pattern.replace('_', ' ')}" if pattern else ""
        title = f"{symbol} - {signal.get('signal_type', 'SIGNAL')}{title_suffix}"
        
        kwargs = dict(
            type='candle',
            style='charles',
            title=title,
            volume=True,
            savefig=filepath,
            warn_too_much_data=100
        )
        
        if lines_to_add:
            hlines_vals = [val for val, _ in lines_to_add]
            hlines_cols = [col for _, col in lines_to_add]
            kwargs['hlines'] = dict(hlines=hlines_vals, colors=hlines_cols, linestyle='--', linewidths=1.5)
            
        # 5. Plot and Save
        mpf.plot(plot_df, **kwargs)
        
        logger.info(f"Chart generated and saved to {filepath}")
        return filepath
        
    except Exception as e:
        logger.error(f"Error generating chart for {symbol}: {e}", exc_info=True)
        return ""
