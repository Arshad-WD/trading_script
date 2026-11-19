import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Angel One SmartAPI Credentials (100% Free Live Feed)
ANGEL_API_KEY = os.getenv("ANGEL_API_KEY", "")
ANGEL_CLIENT_CODE = os.getenv("ANGEL_CLIENT_CODE", "")
ANGEL_PIN = os.getenv("ANGEL_PIN", "")
ANGEL_TOTP_SECRET = os.getenv("ANGEL_TOTP_SECRET", "")

# DhanHQ Credentials (Backup)
DHAN_CLIENT_ID = os.getenv("DHAN_CLIENT_ID", "")
DHAN_ACCESS_TOKEN = os.getenv("DHAN_ACCESS_TOKEN", "")

# Telegram Alerts Configuration
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Whale & Iceberg detection thresholds
WHALE_VOLUME_THRESHOLD = int(os.getenv("WHALE_VOLUME_THRESHOLD", 50000))
ABSORPTION_PRICE_POINTS = float(os.getenv("ABSORPTION_PRICE_POINTS", 5.0))
EVALUATION_WINDOW_SECONDS = int(os.getenv("EVALUATION_WINDOW_SECONDS", 20))

# Angel One Instrument Tokens
# Spot indices
ANGEL_TOKENS = {
    "NIFTY_SPOT": {"exchange": "NSE", "token": "99926000", "symbol": "Nifty 50"},
    "BANKNIFTY_SPOT": {"exchange": "NSE", "token": "99926009", "symbol": "Nifty Bank"},
    # Near-month Futures with real Volume and Open Interest
    "NIFTY_FUT": {"exchange": "NFO", "token": "61471", "symbol": "NIFTY23NOV26FUT"},
}
