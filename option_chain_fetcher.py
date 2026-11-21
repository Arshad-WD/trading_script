"""
option_chain_fetcher.py
───────────────────────
Fetches live Nifty Option Chain from Angel One every 5 minutes (or on-demand).
Extracts dynamic Call Wall, Put Wall, PCR, and Max Pain.
Feeds the results into confluence_engine and iceberg_detector at runtime.

No paid subscription needed — uses SmartAPI getMarketData with NFO option tokens.
"""

import logging
import threading
import time
from datetime import datetime, date
from typing import Optional
import requests

logger = logging.getLogger("OptionChainFetcher")

# Angel One ScripMaster — public endpoint
SCRIP_MASTER_URL = (
    "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
)

# How many OTM/ITM strikes each side to scan (keeps API call manageable)
STRIKES_PER_SIDE = 15
REFRESH_INTERVAL_SECONDS = 300  # 5 minutes


class OptionChainFetcher:
    """
    Periodically fetches the Nifty option chain and computes:
      - call_wall  : strike with highest Call OI
      - put_wall   : strike with highest Put OI
      - max_pain   : strike where total option writer loss is minimised
      - pcr        : Put-Call Ratio (total put OI / total call OI)
      - gamma_plus : second-highest Call OI strike
      - gamma_minus: second-highest Put OI strike
    """

    def __init__(self, smart_api, interval: int = REFRESH_INTERVAL_SECONDS):
        self.smart_api = smart_api          # SmartConnect instance (already authenticated)
        self.interval = interval
        self._lock = threading.Lock()
        self._levels: dict = {}
        self._last_fetched: Optional[datetime] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None

        # Option strike tokens cache (built from ScripMaster once)
        self._nifty_option_tokens: dict = {}   # {strike: {"CE": token, "PE": token}}
        self._near_expiry: Optional[date] = None

    # ─── Public interface ─────────────────────────────────────────────────────

    @property
    def levels(self) -> dict:
        """Returns the latest computed option chain levels (thread-safe)."""
        with self._lock:
            return dict(self._levels)

    def start_background_refresh(self):
        """Starts a daemon thread that refreshes option chain every `interval` seconds."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._refresh_loop, daemon=True, name="OptionChainRefresh")
        self._thread.start()
        logger.info(f"Option chain background refresh started (every {self.interval}s).")

    def stop(self):
        self._running = False

    def fetch_once(self) -> dict:
        """Fetches option chain now and returns the computed levels dict."""
        return self._compute_levels()

    # ─── Internal ─────────────────────────────────────────────────────────────

    def _refresh_loop(self):
        while self._running:
            levels = self._compute_levels()
            if levels:
                with self._lock:
                    self._levels = levels
                self._last_fetched = datetime.now()
                logger.info(
                    f"[OC] Call Wall: {levels.get('call_wall')} | "
                    f"Put Wall: {levels.get('put_wall')} | "
                    f"PCR: {levels.get('pcr', 0):.2f} | "
                    f"Max Pain: {levels.get('max_pain')}"
                )
            time.sleep(self.interval)

    def _build_strike_token_map(self, spot_price: float) -> dict:
        """
        Downloads ScripMaster and builds a map of near-expiry Nifty option tokens.
        Only called once (or when expiry rolls over).
        Returns {strike_int: {"CE": token_str, "PE": token_str}}.
        """
        try:
            resp = requests.get(SCRIP_MASTER_URL, timeout=12)
            resp.raise_for_status()
            instruments = resp.json()
        except Exception as e:
            logger.warning(f"ScripMaster download failed: {e}")
            return {}

        today = date.today()

        # Find the nearest expiry for Nifty options
        expiries = set()
        for inst in instruments:
            if (
                inst.get("exch_seg", "").upper() == "NFO"
                and inst.get("instrumenttype", "").upper() in ("OPTIDX",)
                and inst.get("name", "").upper() == "NIFTY"
            ):
                exp_str = inst.get("expiry", "")
                from instrument_manager import _parse_expiry
                exp = _parse_expiry(exp_str)
                if exp and exp >= today:
                    expiries.add(exp)

        if not expiries:
            logger.warning("No Nifty option expiries found in ScripMaster.")
            return {}

        near_expiry = min(expiries)
        self._near_expiry = near_expiry
        logger.info(f"[OC] Using Nifty option expiry: {near_expiry}")

        # ATM strike = round spot to nearest 50
        atm = round(spot_price / 50) * 50
        low_strike  = atm - STRIKES_PER_SIDE * 50
        high_strike = atm + STRIKES_PER_SIDE * 50

        token_map: dict = {}
        for inst in instruments:
            if (
                inst.get("exch_seg", "").upper() == "NFO"
                and inst.get("instrumenttype", "").upper() == "OPTIDX"
                and inst.get("name", "").upper() == "NIFTY"
            ):
                from instrument_manager import _parse_expiry
                exp = _parse_expiry(inst.get("expiry", ""))
                if exp != near_expiry:
                    continue
                try:
                    strike = int(float(inst.get("strike", "0"))) // 100   # Angel stores strike*100
                except (ValueError, TypeError):
                    continue
                if not (low_strike <= strike <= high_strike):
                    continue
                opt_type = inst.get("symbol", "")[-2:].upper()   # last 2 chars: CE or PE
                if opt_type not in ("CE", "PE"):
                    continue
                if strike not in token_map:
                    token_map[strike] = {}
                token_map[strike][opt_type] = inst.get("token", "")

        logger.info(f"[OC] Loaded {len(token_map)} strikes around ATM {atm} for expiry {near_expiry}.")
        return token_map

    def _fetch_oi_for_tokens(self, token_map: dict) -> dict:
        """
        Calls Angel One getMarketData in LTP mode (fastest) for all CE+PE tokens.
        Returns {strike: {"CE_OI": int, "PE_OI": int}}.
        """
        # Build exchange→tokens list
        nfo_tokens = []
        for strike, opts in token_map.items():
            for opt_type, token in opts.items():
                if token:
                    nfo_tokens.append(token)

        if not nfo_tokens:
            return {}

        oi_map: dict = {}

        # Angel One getMarketData accepts max ~50 tokens per call
        CHUNK = 50
        for i in range(0, len(nfo_tokens), CHUNK):
            chunk = nfo_tokens[i: i + CHUNK]
            try:
                resp = self.smart_api.getMarketData(
                    mode="LTP",
                    exchangeTokens={"NFO": chunk}
                )
                if not resp or resp.get("status") is not True:
                    continue
                for item in resp.get("data", {}).get("fetched", []):
                    tkn = item.get("symbolToken", "")
                    oi  = int(item.get("opnInterest", 0))
                    # Map token back to strike and type
                    for strike, opts in token_map.items():
                        for opt_type, opt_token in opts.items():
                            if opt_token == tkn:
                                if strike not in oi_map:
                                    oi_map[strike] = {"CE_OI": 0, "PE_OI": 0}
                                oi_map[strike][f"{opt_type}_OI"] = oi
            except Exception as e:
                logger.warning(f"getMarketData chunk failed: {e}")

        return oi_map

    def _compute_levels(self) -> dict:
        """
        Full pipeline: spot price → strike map → OI fetch → wall calculation.
        Returns the levels dict or empty dict on failure.
        """
        try:
            # Step 1: Get current Nifty spot
            import config
            spot_resp = self.smart_api.getMarketData(
                mode="LTP",
                exchangeTokens={"NSE": [config.ANGEL_TOKENS["NIFTY_SPOT"]["token"]]}
            )
            if not spot_resp or spot_resp.get("status") is not True:
                logger.warning("[OC] Could not fetch Nifty spot price.")
                return {}
            spot_items = spot_resp.get("data", {}).get("fetched", [])
            if not spot_items:
                return {}
            spot_price = float(spot_items[0].get("ltp", 0))
            if spot_price <= 0:
                return {}

            # Step 2: Build strike/token map (once per session or on expiry change)
            if not self._nifty_option_tokens:
                self._nifty_option_tokens = self._build_strike_token_map(spot_price)
            if not self._nifty_option_tokens:
                return {}

            # Step 3: Fetch OI for all strikes
            oi_map = self._fetch_oi_for_tokens(self._nifty_option_tokens)
            if not oi_map:
                logger.warning("[OC] OI data returned empty — market may be closed.")
                return {}

            # Step 4: Compute walls
            strikes_sorted = sorted(oi_map.keys())
            call_ois = {s: oi_map[s].get("CE_OI", 0) for s in strikes_sorted}
            put_ois  = {s: oi_map[s].get("PE_OI", 0) for s in strikes_sorted}

            # Sort by OI descending
            call_sorted = sorted(call_ois.items(), key=lambda x: x[1], reverse=True)
            put_sorted  = sorted(put_ois.items(),  key=lambda x: x[1], reverse=True)

            call_wall    = call_sorted[0][0]  if len(call_sorted) > 0 else 0
            call_wall_oi = call_sorted[0][1]  if len(call_sorted) > 0 else 0
            gamma_plus   = call_sorted[1][0]  if len(call_sorted) > 1 else call_wall

            put_wall     = put_sorted[0][0]   if len(put_sorted) > 0 else 0
            put_wall_oi  = put_sorted[0][1]   if len(put_sorted) > 0 else 0
            gamma_minus  = put_sorted[1][0]   if len(put_sorted) > 1 else put_wall

            total_call_oi = sum(call_ois.values())
            total_put_oi  = sum(put_ois.values())
            pcr = round(total_put_oi / total_call_oi, 2) if total_call_oi > 0 else 0.0

            # Max Pain: strike where writers lose the least
            max_pain = self._calculate_max_pain(strikes_sorted, call_ois, put_ois)

            levels = {
                "call_wall":    float(call_wall),
                "call_wall_oi": call_wall_oi,
                "put_wall":     float(put_wall),
                "put_wall_oi":  put_wall_oi,
                "gamma_plus":   float(gamma_plus),
                "gamma_minus":  float(gamma_minus),
                "pcr":          pcr,
                "max_pain":     float(max_pain),
                "spot_price":   spot_price,
                "expiry":       str(self._near_expiry),
                "updated_at":   datetime.now().strftime("%H:%M:%S"),
            }
            return levels

        except Exception as e:
            logger.error(f"[OC] Error computing option chain levels: {e}")
            return {}

    @staticmethod
    def _calculate_max_pain(strikes: list, call_ois: dict, put_ois: dict) -> float:
        """
        Max Pain = expiry price that minimises total loss for option writers.
        For each candidate strike S:
          - Call writer loss = sum of (S' - S) * CE_OI  for all S' > S
          - Put  writer loss = sum of (S - S') * PE_OI  for all S' < S
        """
        min_loss = float("inf")
        max_pain_strike = strikes[len(strikes) // 2] if strikes else 0

        for candidate in strikes:
            call_loss = sum(
                max(0, s - candidate) * call_ois.get(s, 0)
                for s in strikes
            )
            put_loss = sum(
                max(0, candidate - s) * put_ois.get(s, 0)
                for s in strikes
            )
            total = call_loss + put_loss
            if total < min_loss:
                min_loss = total
                max_pain_strike = candidate

        return float(max_pain_strike)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    import config
    from SmartApi.smartConnect import SmartConnect
    import pyotp

    smart = SmartConnect(api_key=config.ANGEL_API_KEY)
    totp  = pyotp.TOTP(config.ANGEL_TOTP_SECRET).now()
    session = smart.generateSession(config.ANGEL_CLIENT_CODE, config.ANGEL_PIN, totp)
    if session.get("status") is not True:
        print("Authentication failed:", session.get("message"))
    else:
        print("Authenticated. Fetching option chain…")
        fetcher = OptionChainFetcher(smart_api=smart)
        levels  = fetcher.fetch_once()
        if levels:
            print(f"\n  Call Wall  : {levels['call_wall']}  (OI: {levels['call_wall_oi']:,})")
            print(f"  Put Wall   : {levels['put_wall']}  (OI: {levels['put_wall_oi']:,})")
            print(f"  Max Pain   : {levels['max_pain']}")
            print(f"  PCR        : {levels['pcr']}")
            print(f"  Gamma+     : {levels['gamma_plus']}")
            print(f"  Gamma-     : {levels['gamma_minus']}")
            print(f"  Expiry     : {levels['expiry']}")
        else:
            print("No data returned (market may be closed).")
