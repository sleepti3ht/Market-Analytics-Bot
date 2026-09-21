import asyncio
import logging
import threading
from storage.db import init_db
from api.lis_skins_ws import lis_skins_websocket_loop
from api.market_csgo import market_price_polling_loop
from analyzer.metrics import log_skip_stats_loop
from notifications.telegram_app import run_telegram_app

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")

# Mask Telegram token in logs: httpx/telegram libraries log the full request URL, 
# including bot<TOKEN>. Exposing the token in logs is a secret leak. 
# Set to WARNING to capture only actual errors.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

def start_telegram_bot():
    logger.info("Starting Telegram bot...")
    run_telegram_app()

async def main():
    init_db()
    logger.info("Starting Arbitrage Analytics...")

    # Run Telegram bot in a separate thread
    telegram_thread = threading.Thread(target=start_telegram_bot, daemon=True)
    telegram_thread.start()

    # Start concurrent tasks
    await asyncio.gather(
        lis_skins_websocket_loop(),
        market_price_polling_loop(),
        log_skip_stats_loop()
    )

if __name__ == "__main__":
    asyncio.run(main())