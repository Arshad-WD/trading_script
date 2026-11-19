import requests
import logging
import config

logger = logging.getLogger("TelegramNotifier")

class TelegramNotifier:
    """
    Sends real-time trading alerts directly to a Telegram bot or channel.
    If credentials are not provided, it prints formatted banners to console.
    """

    def __init__(self, bot_token: str = None, chat_id: str = None):
        self.bot_token = bot_token or config.TELEGRAM_BOT_TOKEN
        self.chat_id = chat_id or config.TELEGRAM_CHAT_ID
        self.enabled = bool(self.bot_token and self.chat_id)

        if not self.enabled:
            logger.info("Telegram notifications disabled (No Bot Token / Chat ID configured). Alerts will print directly to console.")

    def send_alert(self, title: str, message: str) -> bool:
        print(f"\n" + "-"*55)
        print(message)
        print("-"*55 + "\n", flush=True)

        if not self.enabled:
            return False

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": message
        }

        try:
            res = requests.post(url, json=payload, timeout=5)
            return res.status_code == 200
        except Exception as e:
            logger.error(f"Failed to deliver Telegram alert: {e}")
            return False
