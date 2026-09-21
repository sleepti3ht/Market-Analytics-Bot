import asyncio
import logging
from telegram import Bot
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger(__name__)

bot = Bot(token=TELEGRAM_BOT_TOKEN)

async def send_arbitrage_signal(signal: dict):
    # Warn loudly if a signal can't be delivered (missing token/chat)
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning(
            "Signal NOT sent to Telegram: missing "
            f"TELEGRAM_BOT_TOKEN={bool(TELEGRAM_BOT_TOKEN)}, "
            f"TELEGRAM_CHAT_ID={bool(TELEGRAM_CHAT_ID)}"
        )
        return

    message = (
        f"🔥 ARBITRAGE SIGNAL 🔥\n"
        f"Skin: {signal['item_name']}\n"
        f"LIS-SKINS: €{signal['lis_price']}\n"
        f"Market.CSGO: €{signal['market_price']}\n"
        f"Net sale price: €{signal['net_sale_price']:.2f}\n"
        f"Profit: €{signal['profit_eur']:.2f} ({signal['profit_percent']:.2f}%)"
    )

    try:
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message)
        logger.info(f"Signal sent to Telegram: {signal['item_name']} | {signal['profit_percent']:.2f}%")
    except Exception as e:
        logger.error(f"Error sending Telegram message: {e}")