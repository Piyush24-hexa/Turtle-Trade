import os
import math
from datetime import datetime
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

def generate_crypto_heatmap(coin_data: dict) -> str:
    """
    Generate a 5x3 heatmap grid for TOP_COINS based on 24h change %.
    Returns the absolute path to the generated image.
    coin_data format: {"BTCUSDT": {"change_pct": 1.2, "price_usdt": 62000}, ...}
    """
    if not coin_data:
        return ""
    
    coins = list(coin_data.keys())
    if not coins:
        return ""
    
    # Grid dimensions (e.g. 5 cols, 3 rows for 15 coins)
    n = len(coins)
    cols = 5
    rows = math.ceil(n / cols)
    
    fig, ax = plt.subplots(figsize=(cols * 2.5, rows * 1.5))
    fig.patch.set_facecolor('#1e1e1e')
    ax.set_facecolor('#1e1e1e')
    
    ax.set_xlim(0, cols)
    ax.set_ylim(0, rows)
    
    # Hide axes
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)
        
    for i, coin in enumerate(coins):
        row = rows - 1 - (i // cols)
        col = i % cols
        
        data = coin_data[coin]
        pct = data.get("change_pct", 0)
        price = data.get("price_usdt", 0)
        
        # Color mapping: dark red for <-5%, bright red for <0, bright green for >0, dark green for >5%
        if pct < -5:
            color = '#8b0000'
        elif pct < 0:
            color = '#ff4d4d'
        elif pct == 0:
            color = '#808080'
        elif pct <= 5:
            color = '#4dffa6'
        else:
            color = '#008b00'
            
        # Draw rectangle
        rect = plt.Rectangle((col + 0.05, row + 0.05), 0.9, 0.9, 
                             facecolor=color, edgecolor='#333333', linewidth=1, alpha=0.9)
        ax.add_patch(rect)
        
        # Text styling
        text_color = 'white' if pct < 0 else 'black'
        
        # Coin Name
        ax.text(col + 0.5, row + 0.65, coin.replace("USDT", ""), 
                color=text_color, ha='center', va='center', fontweight='bold', fontsize=12)
        
        # Percentage
        sign = "+" if pct > 0 else ""
        ax.text(col + 0.5, row + 0.45, f"{sign}{pct:.2f}%", 
                color=text_color, ha='center', va='center', fontweight='bold', fontsize=14)
                
        # Price
        # Formatting neatly depending on price scale
        if price < 1:
            price_str = f"${price:.4f}"
        elif price < 100:
            price_str = f"${price:.2f}"
        else:
            price_str = f"${price:,.0f}"
            
        ax.text(col + 0.5, row + 0.25, price_str, 
                color=text_color, ha='center', va='center', fontsize=10)

    fig.suptitle(f"Crypto Market Heatmap ({datetime.now().strftime('%Y-%m-%d %H:%M')})", 
                 color='white', fontsize=16, fontweight='bold', y=0.98)
    
    plt.tight_layout(rect=[0, 0, 1, 0.95])
    
    # Save Image
    base_dir = os.path.dirname(os.path.dirname(__file__))
    img_dir = os.path.join(base_dir, "signals", "images")
    os.makedirs(img_dir, exist_ok=True)
    
    filename = f"crypto_heatmap_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    filepath = os.path.join(img_dir, filename)
    plt.savefig(filepath, dpi=120, facecolor='#1e1e1e', edgecolor='none')
    plt.close()
    
    return filepath

