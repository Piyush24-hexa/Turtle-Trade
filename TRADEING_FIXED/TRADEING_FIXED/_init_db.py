import sys
sys.path.insert(0, 'execution')
from execution.order_manager import init_orders_db
init_orders_db()
print("Orders DB initialized")

import sqlite3
conn = sqlite3.connect('trading_bot.db')
tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
print("Tables:", [t[0] for t in tables])
conn.close()
