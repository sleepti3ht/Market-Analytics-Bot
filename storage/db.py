import sqlite3
import os
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# Unified DB path: fixed in the ROOT of the project (arbitrage_bot/arbitrage_analytics.db).
# storage/db.py goes up one directory level.
# This ensures the bot and dashboard always work with the SAME database, 
# regardless of the current working directory.
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "arbitrage_analytics.db")
DB_PATH = os.path.abspath(DB_PATH)

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        # Drop the deprecated lis_events table: it stored every single WebSocket 
        # event (thousands per minute) and bloated the DB to gigabytes.
        # We keep only the final arbitrage_signals — this is sufficient.
        cursor.execute("DROP TABLE IF EXISTS lis_events")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS market_prices (
                item_name TEXT PRIMARY KEY,
                price REAL,
                buy_order REAL,
                avg_price REAL,
                popularity_7d REAL,
                updated_at_utc TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS arbitrage_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lis_item_id TEXT,
                item_name TEXT NOT NULL,
                lis_price REAL NOT NULL,
                market_price REAL NOT NULL,
                net_sale_price REAL NOT NULL,
                profit_eur REAL NOT NULL,
                profit_percent REAL NOT NULL,
                notified_at_utc TEXT NOT NULL,
                UNIQUE(lis_item_id)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        # Default settings
        defaults = {
            "min_price": "0",
            "max_price": "1000",
            "min_profit_percent": "15",
            "min_abs_profit": "0.3",
            "min_liquidity": "1",
            "max_liquidity": "1000",
        }
        for k, v in defaults.items():
            cursor.execute("""
                INSERT OR IGNORE INTO user_settings (key, value)
                VALUES (?, ?)
            """, (k, v))

        # Soft update: if the key value equals the old default, 
        # replace it with the new default (to avoid forcing the user to fix it manually)
        cursor.execute("""
            UPDATE user_settings SET value = '0.3'
            WHERE key = 'min_abs_profit' AND value = '1.0'
        """)

        # Auto-migration: add missing columns to market_prices
        # for DBs created before the introduction of avg_price / popularity_7d
        cursor.execute("PRAGMA table_info(market_prices)")
        existing_cols = {row[1] for row in cursor.fetchall()}
        for col, col_type in (("avg_price", "REAL"), ("popularity_7d", "REAL")):
            if col not in existing_cols:
                cursor.execute(f"ALTER TABLE market_prices ADD COLUMN {col} {col_type}")
                logger.info(f"Migration: added column {col} to market_prices")

        conn.commit()

    # Clean up anomalous signals (corrupted data: outlier seller price)
    cleanup_anomaly_signals()


def cleanup_anomaly_signals(max_profit_percent: float = 500.0) -> int:
    """Deletes signals with implausible profit (> max_profit_percent).

    Such signals occur when market_prices returns an outlier price 
    from a single seller, rather than the true market price (missing avg_price/buy_order).
    """
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            DELETE FROM arbitrage_signals
            WHERE profit_percent > ?
        """, (max_profit_percent,))
        deleted = cursor.rowcount
        conn.commit()
    if deleted:
        logger.info(f"Cleaned {deleted} anomalous signals (> {max_profit_percent:.0f}%)")
    return deleted

def get_setting(key: str) -> str:
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM user_settings WHERE key = ?", (key,))
        row = cursor.fetchone()
        return row[0] if row else None

def set_setting(key: str, value: str):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO user_settings (key, value)
            VALUES (?, ?)
        """, (key, str(value)))
        conn.commit()

def upsert_market_prices(prices: dict):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        now = datetime.utcnow().isoformat()
        for name, data in prices.items():
            cursor.execute("""
                INSERT OR REPLACE INTO market_prices
                (item_name, price, buy_order, avg_price, popularity_7d, updated_at_utc)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                name,
                data.get("price"),
                data.get("buy_order"),
                data.get("avg_price"),
                data.get("popularity_7d"),
                now
            ))
        conn.commit()

def get_market_price(item_name: str) -> dict:
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT price, buy_order, avg_price, popularity_7d FROM market_prices
            WHERE item_name = ?
        """, (item_name,))
        row = cursor.fetchone()
        if row:
            return {
                "price": row[0],
                "buy_order": row[1],
                "avg_price": row[2],
                "popularity_7d": row[3]
            }
    return None

def create_signal_if_new(item_name: str, lis_item_id: str, lis_price: float,
                         market_price: float, net_sale_price: float,
                         profit_eur: float, profit_percent: float) -> bool:
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id FROM arbitrage_signals
            WHERE lis_item_id = ?
        """, (lis_item_id,))
        if cursor.fetchone():
            return False
        cursor.execute("""
            INSERT INTO arbitrage_signals
            (lis_item_id, item_name, lis_price, market_price, net_sale_price,
             profit_eur, profit_percent, notified_at_utc)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            lis_item_id, item_name, lis_price, market_price, net_sale_price,
            profit_eur, profit_percent, datetime.utcnow().isoformat()
        ))
        conn.commit()
        return True