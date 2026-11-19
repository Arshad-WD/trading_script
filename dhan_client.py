import logging
import requests
from dhanhq import DhanContext, dhanhq, OptionChain
import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("DhanClient")

class DhanClientManager:
    """
    Manages DhanHQ REST API and WebSocket connection for real-time market data,
    depth, and option chain retrieval.
    """

    def __init__(self, client_id: str = None, access_token: str = None):
        self.client_id = client_id or config.DHAN_CLIENT_ID
        self.access_token = access_token or config.DHAN_ACCESS_TOKEN
        
        if not self.client_id or not self.access_token:
            logger.warning("Dhan credentials are not set. Please provide Client ID and Access Token.")
            self.context = None
            self.dhan = None
            self.option_chain_service = None
        else:
            self.context = DhanContext(self.client_id, self.access_token)
            self.dhan = dhanhq(self.context)
            self.option_chain_service = OptionChain(self.context)

    def test_connection(self) -> dict:
        """
        Tests the API credentials by fetching profile / fund limits.
        """
        if not self.dhan:
            return {"status": "error", "message": "Credentials missing in .env"}
        try:
            funds = self.dhan.get_fund_limits()
            if isinstance(funds, dict) and funds.get("status") == "success":
                return {"status": "success", "data": funds.get("data", {})}
            return {"status": "error", "message": funds}
        except Exception as e:
            logger.error(f"Failed to connect to Dhan API: {e}")
            return {"status": "error", "message": str(e)}

    def check_data_api_subscription(self) -> dict:
        """
        Checks whether the account has an active Dhan Data API subscription.
        """
        url = "https://api.dhan.co/v2/marketfeed/quote"
        headers = {
            "access-token": self.access_token,
            "client-id": self.client_id,
            "Content-Type": "application/json"
        }
        try:
            res = requests.post(url, json={"IDX_I": [13]}, headers=headers, timeout=5)
            data = res.json()
            if res.status_code == 200:
                return {"subscribed": True, "data": data}
            elif res.status_code == 401 and "Data APIs not Subscribed" in str(data):
                return {
                    "subscribed": False,
                    "error_code": "806",
                    "message": "Dhan Data API is not subscribed. To stream live quotes, depth & option chain, activate 'Data API' on https://dhanhq.co (₹499/month)."
                }
            return {"subscribed": False, "raw": data}
        except Exception as e:
            return {"subscribed": False, "error": str(e)}

    def fetch_expiry_list(self, security_id: int = 13, segment: str = "IDX_I") -> list:
        """
        Fetches active expiry dates for an index (e.g. 13 for NIFTY).
        """
        if not self.option_chain_service:
            return []
        try:
            expiries = self.option_chain_service.expiry_list(security_id, segment)
            return expiries.get("data", []) if isinstance(expiries, dict) else expiries
        except Exception as e:
            logger.error(f"Error fetching expiry list: {e}")
            return []

    def fetch_option_chain(self, security_id: int = 13, segment: str = "IDX_I", expiry: str = None) -> dict:
        """
        Fetches the option chain for the specified expiry.
        """
        if not self.option_chain_service:
            return {}
        try:
            if not expiry:
                exp_list = self.fetch_expiry_list(security_id, segment)
                if not exp_list:
                    return {}
                expiry = exp_list[0]
            chain = self.option_chain_service.option_chain(security_id, segment, expiry)
            return chain.get("data", {}) if isinstance(chain, dict) else chain
        except Exception as e:
            logger.error(f"Error fetching option chain: {e}")
            return {}
