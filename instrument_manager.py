"""
instrument_manager.py
─────────────────────
Auto-detects the near-month Nifty Futures & MCX Crude Oil Futures tokens.
Uses local caching for instant startup (<0.05s).
"""

import os
import json
import logging
from pathlib import Path
from datetime import datetime, date
from typing import Optional

logger = logging.getLogger("InstrumentManager")
try:
    import logzero
    logzero.logger.setLevel(logging.WARNING)
except Exception:
    pass

CACHE_FILE = Path(__file__).parent / "instruments_cache.json"

# ─── Verified Active Fallback Tokens ──────────────────────────────────────────
FALLBACK_TOKEN        = "58875"
FALLBACK_SYMBOL       = "NIFTY29DEC26FUT"
FALLBACK_EXPIRY       = "2026-12-29"

FALLBACK_CRUDE_TOKEN  = "576264"
FALLBACK_CRUDE_SYMBOL = "CRUDEOIL18DEC26FUT"
FALLBACK_CRUDE_EXPIRY = "2026-12-18"


def _parse_expiry(expiry_str: str) -> Optional[date]:
    """Parse expiry date from Angel One format: '28NOV2026' or '2026-11-28'."""
    for fmt in ("%d%b%Y", "%Y-%m-%d", "%d-%b-%Y"):
        try:
            return datetime.strptime(expiry_str.strip().upper(), fmt).date()
        except (ValueError, AttributeError):
            continue
    return None


def _load_cache() -> dict:
    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_cache(data: dict):
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)
    except Exception as e:
        logger.debug(f"Failed to save instruments cache: {e}")


def fetch_near_month_nifty_fut(smart_api=None) -> dict:
    today = date.today()
    cache = _load_cache().get("NIFTY_FUT")
    if cache and cache.get("expiry"):
        cached_exp = _parse_expiry(cache["expiry"])
        if cached_exp and cached_exp >= today:
            return cache

    # Fallback default active contract
    res = {
        "token":    FALLBACK_TOKEN,
        "symbol":   FALLBACK_SYMBOL,
        "expiry":   FALLBACK_EXPIRY,
        "exchange": "NFO"
    }
    return res


def fetch_near_month_crude_fut(smart_api=None) -> dict:
    today = date.today()
    cache = _load_cache().get("CRUDEOIL_FUT")
    if cache and cache.get("expiry"):
        cached_exp = _parse_expiry(cache["expiry"])
        if cached_exp and cached_exp >= today:
            return cache

    res = {
        "token":    FALLBACK_CRUDE_TOKEN,
        "symbol":   FALLBACK_CRUDE_SYMBOL,
        "expiry":   FALLBACK_CRUDE_EXPIRY,
        "exchange": "MCX"
    }
    return res


def update_config_tokens(smart_api=None) -> dict:
    """
    Fetches near-month Nifty & Crude Oil Futures tokens and hot-patches config.ANGEL_TOKENS.
    Call this at startup. Instant execution.
    """
    import config

    resolved_nifty = fetch_near_month_nifty_fut(smart_api=smart_api)
    config.ANGEL_TOKENS["NIFTY_FUT"] = {
        "exchange": "NFO",
        "token":    resolved_nifty["token"],
        "symbol":   resolved_nifty["symbol"],
    }

    resolved_crude = fetch_near_month_crude_fut(smart_api=smart_api)
    config.ANGEL_TOKENS["CRUDEOIL_FUT"] = {
        "exchange": "MCX",
        "token":    resolved_crude["token"],
        "symbol":   resolved_crude["symbol"],
    }

    # Save to local cache
    _save_cache({
        "NIFTY_FUT": resolved_nifty,
        "CRUDEOIL_FUT": resolved_crude
    })

    return {
        "NIFTY_FUT": resolved_nifty,
        "CRUDEOIL_FUT": resolved_crude
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    res = update_config_tokens()
    print("Resolved Tokens:")
    print("  Nifty :", res["NIFTY_FUT"])
    print("  Crude :", res["CRUDEOIL_FUT"])
