"""
instrument_manager.py
─────────────────────
Auto-detects the near-month Nifty Futures token from Angel One ScripMaster JSON.
Runs at startup; updates config.ANGEL_TOKENS["NIFTY_FUT"] in-process.

No paid subscription needed — ScripMaster is fully public.
"""

import requests
import logging
from datetime import datetime, date
from typing import Optional

logger = logging.getLogger("InstrumentManager")

SCRIP_MASTER_URL = (
    "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
)

# ─── Fallback token used when ScripMaster is unreachable ──────────────────────
FALLBACK_TOKEN  = "61471"
FALLBACK_SYMBOL = "NIFTY23NOV26FUT"


def _parse_expiry(expiry_str: str) -> Optional[date]:
    """Parse expiry date from Angel One format: '28NOV2026' or '2026-11-28'."""
    for fmt in ("%d%b%Y", "%Y-%m-%d", "%d-%b-%Y"):
        try:
            return datetime.strptime(expiry_str.strip().upper(), fmt).date()
        except (ValueError, AttributeError):
            continue
    return None


def fetch_near_month_nifty_fut(timeout: int = 10) -> dict:
    """
    Downloads ScripMaster JSON and returns token + symbol for the nearest
    expiry Nifty Futures contract.

    Returns:
        {
            "token":   "61471",
            "symbol":  "NIFTY23NOV26FUT",
            "expiry":  date(2026, 11, 27),
            "exchange": "NFO"
        }
    """
    today = date.today()
    best: Optional[dict] = None

    try:
        logger.info("Fetching ScripMaster for Nifty Futures auto-rollover…")
        resp = requests.get(SCRIP_MASTER_URL, timeout=timeout)
        resp.raise_for_status()
        instruments = resp.json()

        candidates = []
        for inst in instruments:
            # Filter: NFO exchange, FUTIDX type, underlying NIFTY
            if (
                inst.get("exch_seg", "").upper() == "NFO"
                and inst.get("instrumenttype", "").upper() == "FUTIDX"
                and inst.get("name", "").upper() == "NIFTY"
            ):
                expiry = _parse_expiry(inst.get("expiry", ""))
                if expiry and expiry >= today:
                    candidates.append({
                        "token":   inst.get("token", ""),
                        "symbol":  inst.get("symbol", ""),
                        "expiry":  expiry,
                        "exchange": "NFO"
                    })

        if candidates:
            # Pick nearest expiry
            best = min(candidates, key=lambda x: x["expiry"])
            logger.info(
                f"[AUTO-ROLLOVER] Near-month Nifty Futures → "
                f"Token: {best['token']} | Symbol: {best['symbol']} | "
                f"Expiry: {best['expiry']}"
            )
        else:
            logger.warning("No valid NIFTY FUTIDX contracts found in ScripMaster.")

    except requests.RequestException as e:
        logger.warning(f"ScripMaster fetch failed ({e}). Using fallback token {FALLBACK_TOKEN}.")
    except Exception as e:
        logger.warning(f"Unexpected error in instrument_manager ({e}). Using fallback.")

    if not best:
        best = {
            "token":   FALLBACK_TOKEN,
            "symbol":  FALLBACK_SYMBOL,
            "expiry":  None,
            "exchange": "NFO"
        }

    return best


def update_config_tokens() -> dict:
    """
    Fetches near-month Nifty Futures token and hot-patches config.ANGEL_TOKENS.
    Call this ONCE at application startup before any market data fetch.

    Returns the resolved token dict.
    """
    import config
    resolved = fetch_near_month_nifty_fut()
    config.ANGEL_TOKENS["NIFTY_FUT"] = {
        "exchange": "NFO",
        "token":    resolved["token"],
        "symbol":   resolved["symbol"],
    }
    return resolved


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    result = fetch_near_month_nifty_fut()
    print(f"\nResolved Nifty Futures:")
    print(f"  Token  : {result['token']}")
    print(f"  Symbol : {result['symbol']}")
    print(f"  Expiry : {result['expiry']}")
