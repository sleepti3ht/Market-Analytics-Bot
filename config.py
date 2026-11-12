
import os

from dotenv import load_dotenv

load_dotenv()

# API Keys
LIS_SKINS_API_KEY = os.getenv("LIS_SKINS_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Telegram access control: comma-separated list of allowed user IDs.
# Anyone not listed here is ignored by the bot. Leave empty to disable the
# allowlist (NOT recommended for a live bot in a shared chat).
ALLOWED_USER_IDS = [
    int(x.strip())
    for x in os.getenv("ALLOWED_USER_IDS", "").split(",")
    if x.strip()
]

# Optional public URL for the Streamlit dashboard (e.g. an ngrok/cloudflared
# tunnel). If set, the bot shows a "Open Dashboard" button in the main menu.
DASHBOARD_URL = os.getenv("DASHBOARD_URL", "").strip()


def get_dashboard_url() -> str:
    """Re-read DASHBOARD_URL from .env on every call.

    The tunnel URL changes every time start_dashboard.py runs, so we read it
    lazily instead of caching it at import time — otherwise the Telegram button
    would keep pointing to a stale URL until the bot restarts.
    """
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    try:
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("DASHBOARD_URL="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return DASHBOARD_URL

# Settings
MARKET_CSGO_CURRENCY = os.getenv("MARKET_CSGO_CURRENCY", "EUR")
MIN_PROFIT_PERCENT = float(os.getenv("MIN_PROFIT_PERCENT", "15"))
MARKET_CSGO_FEE_PERCENT = float(os.getenv("MARKET_CSGO_FEE_PERCENT", "5"))
SAFETY_PERCENT = float(os.getenv("SAFETY_PERCENT", "3"))
MARKET_REFRESH_SECONDS = int(os.getenv("MARKET_REFRESH_SECONDS", "60"))

# URLs
LIS_WS_URL = "wss://ws.lis-skins.com/connection/websocket"
LIS_WS_TOKEN_URL = "https://api.lis-skins.com/v1/user/get-ws-token"
LIS_CHANNEL = "public:obtained-skins"
MARKET_CSGO_PRICES_URL = f"https://market.csgo.com/api/v2/prices/class_instance/{MARKET_CSGO_CURRENCY}.json"