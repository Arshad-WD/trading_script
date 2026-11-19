import logging
import pyotp
from SmartApi.smartConnect import SmartConnect
import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("AngelClient")

class AngelClientManager:
    """
    Manages Angel One SmartAPI connection, automated TOTP 2FA,
    and market data retrieval (Spot Indices, Futures Volume, OI & Depth).
    """

    def __init__(self):
        self.api_key = config.ANGEL_API_KEY
        self.client_code = config.ANGEL_CLIENT_CODE
        self.pin = config.ANGEL_PIN
        self.totp_secret = config.ANGEL_TOTP_SECRET
        
        self.smart_api = None
        self.jwt_token = None
        self.refresh_token = None
        self.feed_token = None
        self.user_profile = None

        if self.api_key and self.client_code and self.pin and self.totp_secret:
            self._authenticate()
        else:
            logger.warning("Angel One credentials incomplete in .env.")

    def _authenticate(self) -> bool:
        """
        Generates dynamic TOTP and logs in to SmartAPI.
        """
        try:
            self.smart_api = SmartConnect(api_key=self.api_key)
            totp = pyotp.TOTP(self.totp_secret).now()
            session = self.smart_api.generateSession(self.client_code, self.pin, totp)
            
            if session.get("status") is True:
                data = session.get("data", {})
                self.jwt_token = data.get("jwtToken")
                self.refresh_token = data.get("refreshToken")
                self.feed_token = data.get("feedToken")
                self.user_profile = data
                logger.info(f"Successfully authenticated with Angel One SmartAPI (User: {data.get('name')})")
                return True
            else:
                logger.error(f"Angel One authentication failed: {session.get('message')}")
                return False
        except Exception as e:
            logger.error(f"Error during Angel One login: {e}")
            return False

    def is_connected(self) -> bool:
        return bool(self.smart_api and self.jwt_token)

    def get_market_data(self, mode: str = "FULL", exchange_tokens: dict = None) -> list:
        """
        Fetches live market data (OHLC, LTP, Volume, Depth).
        """
        if not self.is_connected():
            if not self._authenticate():
                return []

        if exchange_tokens is None:
            exchange_tokens = {
                "NSE": [config.ANGEL_TOKENS["NIFTY_SPOT"]["token"], config.ANGEL_TOKENS["BANKNIFTY_SPOT"]["token"]],
                "NFO": [config.ANGEL_TOKENS["NIFTY_FUT"]["token"]]
            }

        try:
            data = self.smart_api.getMarketData(mode=mode, exchangeTokens=exchange_tokens)
            if data and data.get("status") is True:
                return data.get("data", {}).get("fetched", [])
            return []
        except Exception as e:
            # Network hiccup or timeout; return empty and let retry happen cleanly
            return []

    def get_spot_and_futures(self) -> dict:
        """
        Returns processed data for Nifty Spot, BankNifty Spot, and Nifty Futures (Volume + OI).
        """
        quotes = self.get_market_data()
        result = {}
        for q in quotes:
            token = q.get("symbolToken")
            result[token] = {
                "symbol": q.get("tradingSymbol"),
                "token": token,
                "exchange": q.get("exchange"),
                "ltp": float(q.get("ltp", 0.0)),
                "open": float(q.get("open", 0.0)),
                "high": float(q.get("high", 0.0)),
                "low": float(q.get("low", 0.0)),
                "close": float(q.get("close", 0.0)),
                "percent_change": float(q.get("percentChange", 0.0)),
                "volume": int(q.get("tradeVolume", 0)),
                "oi": int(q.get("opnInterest", 0)),
                "avg_price": float(q.get("avgPrice", 0.0)),
                "depth": q.get("depth", {})
            }
        return result
