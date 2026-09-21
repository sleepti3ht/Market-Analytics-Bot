import asyncio
import logging
from config import MIN_PROFIT_PERCENT, MARKET_CSGO_FEE_PERCENT, SAFETY_PERCENT
from storage.db import get_market_price, create_signal_if_new, get_setting
from notifications.telegram_bot import send_arbitrage_signal

logger = logging.getLogger(__name__)

# --- Diagnostics: skip counters (filter reasons) ---
skips = {
    "deleted": 0,
    "no_name_id": 0,
    "bad_price": 0,
    "price_range": 0,
    "no_market_data": 0,
    "liquidity": 0,
    "no_demand": 0,
    "no_sale_price": 0,
    "anomaly_cap": 0,
    "low_percent": 0,
    "low_abs_euro": 0,
    "ok_signals": 0,
}


def _log_skip(reason: str, name: str, extra: str = ""):
    """Increments the skip counter and logs to DEBUG."""
    skips[reason] = skips.get(reason, 0) + 1
    logger.debug(f"Skip ({reason}): {name} {extra}")


async def log_skip_stats_loop():
    """Every 60s prints aggregate skip statistics."""
    while True:
        await asyncio.sleep(60)
        total = sum(skips.values())
        if total == 0:
            continue
        parts = ", ".join(f"{k}={v}" for k, v in skips.items() if v)
        logger.warning(f"SKIP STATS (60s): total={total} | {parts}")
        # reset counters for the new interval
        for k in skips:
            skips[k] = 0


def calculate_profit(buy_price: float, market_price: float):
    """Calculates net sale price, profit in EUR, and profit percentage."""
    if buy_price <= 0 or market_price <= 0:
        return 0, 0, 0

    fee = market_price * (MARKET_CSGO_FEE_PERCENT / 100)
    safety = market_price * (SAFETY_PERCENT / 100)
    net_sale_price = market_price - fee - safety
    profit_eur = net_sale_price - buy_price
    profit_percent = (profit_eur / buy_price) * 100 if buy_price > 0 else 0

    return net_sale_price, profit_eur, profit_percent


async def process_item(item: dict):
    """Processes a single item from the LIS-SKINS WebSocket."""
    try:
        event = item.get("event")
        name = item.get("name")
        lis_price = item.get("price")
        lis_item_id = item.get("id")

        # Skip deleted items
        if event == "obtained_skin_deleted":
            _log_skip("deleted", name or "?")
            return

        if not name or not lis_item_id:
            _log_skip("no_name_id", name or "?")
            return

        try:
            lis_price = float(lis_price)
        except (TypeError, ValueError):
            _log_skip("bad_price", name or "?", f"price={item.get('price')}")
            return

        if lis_price <= 0:
            _log_skip("bad_price", name, f"price={lis_price}")
            return

        # Price filters (from DB settings)
        min_price = float(get_setting("min_price") or 0)
        max_price = float(get_setting("max_price") or 1000)
        if not (min_price <= lis_price <= max_price):
            _log_skip("price_range", name, f"price={lis_price}")
            return

        # Get Market.CSGO price from cache
        market_data = get_market_price(name)
        if not market_data:
            _log_skip("no_market_data", name)
            return

        # --- Liquidity and sale price (flexible logic) ---
        popularity_raw = market_data.get("popularity_7d")   # None if there is no sales data
        buy_order = market_data.get("buy_order") or 0
        avg_price = market_data.get("avg_price")
        ask_price = market_data.get("price") or 0

        min_liquidity = int(get_setting("min_liquidity") or 1)
        max_liquidity = int(get_setting("max_liquidity") or 1000)

        # If 7-day sales stats exist -> filter STRICTLY by liquidity
        if popularity_raw is not None:
            popularity_7d = float(popularity_raw)
            if not (min_liquidity <= popularity_7d <= max_liquidity):
                _log_skip("liquidity", name, f"popularity_7d={popularity_7d}")
                return
        else:
            # No sales data — DO NOT filter out if there is demand (buy_order).
            # A buy_order might be placed by another player's bot, but it's a real signal.
            popularity_7d = 0.0
            if buy_order <= 0:
                _log_skip("no_demand", name, "no sales and no buy_order")
                return

        # Sale price — priority by reliability:
        # 1) avg_price — real sales over 7 days (most honest)
        # 2) buy_order — real buyer bids (even if lowered by bots)
        # 3) ask_price — last resort, seller's whim price
        market_price = avg_price or buy_order or ask_price
        if not market_price or market_price <= 0:
            _log_skip("no_sale_price", name)
            return

        # LOGICAL CAP: profit > 1000% is almost certainly bad data.
        # Previously it was >6 (500%) — but that cut off legitimate arbitrage.
        # A cheap skin $0.5 -> $3 is a legit +500%, not a whim.
        # Garbage like $0.78 -> $87k is blocked by min_abs_profit in € below.
        if market_price / lis_price > 10:
            _log_skip("anomaly_cap", name, f"LIS={lis_price} Market={market_price}")
            logger.warning(
                f"Skip (bad data): {name} | LIS: €{lis_price} | "
                f"Market: €{market_price} | looks like illiquid ask-price"
            )
            return

        # Calculate profit
        net_sale_price, profit_eur, profit_percent = calculate_profit(lis_price, market_price)

        # Filter: minimum RELATIVE profit (%) 
        min_profit = float(get_setting("min_profit_percent") or MIN_PROFIT_PERCENT)
        if profit_percent < min_profit:
            _log_skip("low_percent", name, f"profit {profit_percent:.1f}% < {min_profit}%")
            return

        # Filter: minimum ABSOLUTE profit (€) - rejects noise like €0.02 -> €0.35
        min_abs_profit = float(get_setting("min_abs_profit") or 0.3)
        if profit_eur < min_abs_profit:
            _log_skip("low_abs_euro", name, f"profit €{profit_eur:.2f} < €{min_abs_profit}")
            return

        # Which reference was used for the sale price — for transparency
        if market_price == avg_price:
            source_label = "avg"
        elif market_price == buy_order:
            source_label = "buy_order"
        else:
            source_label = "ask"

        logger.info(
            f"{name} | LIS: €{lis_price} | Market({source_label}): €{market_price} | "
            f"7d sales: {popularity_7d} | Profit: {profit_percent:.2f}% (€{profit_eur:.2f})"
        )

        skips["ok_signals"] = skips.get("ok_signals", 0) + 1

        # Create signal (deduplicate by lis_item_id)
        is_new = create_signal_if_new(
            name, str(lis_item_id), lis_price, market_price,
            net_sale_price, profit_eur, profit_percent
        )
        if is_new:
            await send_arbitrage_signal({
                "item_name": name,
                "lis_price": lis_price,
                "market_price": market_price,
                "net_sale_price": net_sale_price,
                "profit_eur": profit_eur,
                "profit_percent": profit_percent
            })
    except Exception:
        logger.exception("Error processing item")