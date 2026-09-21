import aiohttp
import asyncio
import logging
from config import MARKET_CSGO_PRICES_URL, MARKET_REFRESH_SECONDS
from storage.db import upsert_market_prices

logger = logging.getLogger(__name__)

def parse_price_list(payload: dict) -> dict:
    """Parses the Market.CSGO price list response and returns a dict with prices.

    Response structure:
    {
      "items": {
        "classid_instanceid": {
          "market_hash_name": "AK-47 | Redline (Field-Tested)",
          "price": "12.50",          # price set by the seller
          "buy_order": "11.80",      # price buyers are willing to pay (buy order)
          "avg_price": "12.10",      # average price based on actual sales over 7 days
          "popularity_7d": "47"      # number of units sold in 7 days (liquidity)
        }
      }
    }
    """
    items = payload.get("items", {})
    result = {}
    for key, data in items.items():
        name = data.get("market_hash_name")
        if name:
            # Convert to float, as the API returns strings
            def _to_float(val):
                try:
                    return float(val)
                except (TypeError, ValueError):
                    return None

            result[name] = {
                "price": _to_float(data.get("price")),
                "buy_order": _to_float(data.get("buy_order")),
                "avg_price": _to_float(data.get("avg_price")),
                "popularity_7d": _to_float(data.get("popularity_7d")),
            }
    return result

async def refresh_market_prices():
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(MARKET_CSGO_PRICES_URL) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    prices = parse_price_list(data)
                    upsert_market_prices(prices)
                    logger.info(f"Loaded {len(prices)} Market.CSGO prices")
                else:
                    logger.error(f"Error loading prices: {resp.status}")
    except Exception as e:
        logger.error(f"Error refreshing prices: {e}")

async def market_price_polling_loop():
    while True:
        await refresh_market_prices()
        await asyncio.sleep(MARKET_REFRESH_SECONDS)