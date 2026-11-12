"""MCP server for Market Analytics Bot (portfolio project).

Exposes the bot's SQLite data and filter settings as MCP tools, so any
MCP-compatible agent (Claude Desktop, Continue, custom harness) can query
signals, stats and settings, or safely update a setting.

Run standalone (stdio):  python mcp_server.py
Self-test client:        python test_mcp_client.py
"""
import json
import sqlite3

from mcp.server.fastmcp import FastMCP

from storage.db import DB_PATH, get_setting, set_setting

mcp = FastMCP("market-analytics-bot")

# Whitelist + types: an agent (or a user) can touch only known settings,
# and only with values that actually parse. Same idea as the allowlist
# in notifications/telegram_app.py.
SETTING_TYPES = {
    "min_price": float,
    "max_price": float,
    "min_profit_percent": float,
    "min_abs_profit": float,
    "min_liquidity": int,
    "max_liquidity": int,
}


def _format_rows(rows) -> str:
    return "\n".join(
        f"{r['item_name']} | LIS €{r['lis_price']:.2f} -> market €{r['market_price']:.2f} "
        f"| profit €{r['profit_eur']:.2f} ({r['profit_percent']:.1f}%) | {r['notified_at_utc']}"
        for r in rows
    )


@mcp.tool()
def get_latest_signals(limit: int = 10) -> str:
    """Return the latest arbitrage signals, newest first (limit <= 50)."""
    limit = max(1, min(int(limit), 50))
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT item_name, lis_price, market_price,
                   profit_eur, profit_percent, notified_at_utc
            FROM arbitrage_signals ORDER BY id DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return _format_rows(rows) if rows else "No signals in DB yet."


@mcp.tool()
def find_signals(item_name: str, limit: int = 10) -> str:
    """Search signals by item name substring, case-insensitive (limit <= 50)."""
    limit = max(1, min(int(limit), 50))
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT item_name, lis_price, market_price,
                   profit_eur, profit_percent, notified_at_utc
            FROM arbitrage_signals
            WHERE item_name LIKE ? ORDER BY id DESC LIMIT ?
            """,
            (f"%{item_name}%", limit),
        ).fetchall()
    return _format_rows(rows) if rows else f"No signals matching '{item_name}'."


@mcp.tool()
def get_stats() -> str:
    """Aggregate stats: signal count, cached market prices, avg and total profit."""
    with sqlite3.connect(DB_PATH) as conn:
        signals, prices = conn.execute(
            "SELECT (SELECT COUNT(*) FROM arbitrage_signals), "
            "(SELECT COUNT(*) FROM market_prices)"
        ).fetchone()
        avg_profit, total_profit = conn.execute(
            "SELECT AVG(profit_percent), SUM(profit_eur) FROM arbitrage_signals"
        ).fetchone()
    return (
        f"Signals: {signals}\n"
        f"Market prices cached: {prices}\n"
        f"Avg profit: {avg_profit or 0:.2f}%\n"
        f"Total profit: €{total_profit or 0:.2f}"
    )


@mcp.tool()
def get_settings() -> str:
    """Current filter settings: price bounds, min profit % and EUR, liquidity bounds."""
    return json.dumps({k: get_setting(k) for k in SETTING_TYPES}, ensure_ascii=False, indent=2)


@mcp.tool()
def update_setting(key: str, value: str) -> str:
    """Safely update one filter setting.

    key must be one of: min_price, max_price, min_profit_percent,
    min_abs_profit, min_liquidity, max_liquidity.
    value must parse as the expected numeric type and be >= 0.
    """
    key = key.strip().lower()
    if key not in SETTING_TYPES:
        return f"Unknown setting '{key}'. Allowed: {', '.join(SETTING_TYPES)}"
    try:
        parsed = SETTING_TYPES[key](value)
    except (TypeError, ValueError):
        return f"Value '{value}' is not a valid {SETTING_TYPES[key].__name__} for {key}"
    if parsed < 0:
        return f"Value for {key} must be >= 0"
    set_setting(key, parsed)
    return f"OK: {key} = {parsed}"


if __name__ == "__main__":
    mcp.run()  # stdio transport by default