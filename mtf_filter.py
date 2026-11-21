"""
mtf_filter.py
─────────────
Multi-Timeframe (MTF) Trend Filter for Nifty 50.

Professional institutional rule:
- Intraday A+ trades must align with the higher timeframe (15-Minute) macro trend.
- Going LONG when the 15-minute trend is strongly BEARISH gets trapped.
- Going SHORT when the 15-minute trend is strongly BULLISH gets squeezed.

This module:
1. Periodically (every 5-15 min) fetches 15m OHLC candles via Angel One getCandleData.
2. Computes 15m EMA 9, EMA 21, and trend slope.
3. Classifies bias: "BULLISH", "BEARISH", or "NEUTRAL".
4. Feeds into ConfluenceEngine:
   - Aligned trend: +15 bonus points
   - Counter-trend: -20 penalty points (or blocks setup unless score is overwhelmingly high)
"""

import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import config

logger = logging.getLogger("MTFFilter")

INTERVAL_15M = "FIFTEEN_MINUTE"
REFRESH_INTERVAL_SECONDS = 300  # Refresh every 5 minutes


class MultiTimeframeFilter:
    """
    Tracks Higher Timeframe (15-Minute) Trend Bias for Nifty.
    Runs asynchronously in the background so it never slows down tick processing.
    """

    def __init__(self, smart_api=None, refresh_interval: int = REFRESH_INTERVAL_SECONDS):
        self.smart_api = smart_api
        self.refresh_interval = refresh_interval
        self._lock = threading.Lock()
        self._bias_state: Dict[str, Any] = {
            "trend": "NEUTRAL",
            "strength": "UNKNOWN",
            "ema_fast": 0.0,
            "ema_slow": 0.0,
            "last_close": 0.0,
            "updated_at": "NEVER"
        }
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start_background_tracker(self):
        """Starts background loop to update 15m trend bias every 5 minutes."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._tracker_loop, daemon=True, name="MTFFilterLoop")
        self._thread.start()
        logger.info(f"MTF 15m Filter background tracker started (every {self.refresh_interval}s).")

    def stop(self):
        self._running = False

    def get_bias(self) -> Dict[str, Any]:
        """Returns the current 15m trend state (thread-safe)."""
        with self._lock:
            return dict(self._bias_state)

    def update_bias_now(self) -> Dict[str, Any]:
        """Fetches candles and computes bias immediately."""
        bias = self._calculate_15m_bias()
        if bias:
            with self._lock:
                self._bias_state = bias
        return self.get_bias()

    def _tracker_loop(self):
        while self._running:
            try:
                self.update_bias_now()
            except Exception as e:
                logger.warning(f"Error in MTF tracker loop: {e}")
            time.sleep(self.refresh_interval)

    def _calculate_15m_bias(self) -> Optional[Dict[str, Any]]:
        """
        Fetches 15-minute candles from Angel One for Nifty Spot or Futures,
        computes EMA 9 and EMA 21, and determines trend bias.
        """
        if not self.smart_api:
            return None

        now = datetime.now()
        # Look back 5 days to get enough 15m candles for accurate EMA 21
        from_dt = now - timedelta(days=5)

        token = config.ANGEL_TOKENS["NIFTY_FUT"]["token"]
        exchange = "NFO"

        params = {
            "exchange": exchange,
            "symboltoken": token,
            "interval": INTERVAL_15M,
            "fromdate": from_dt.strftime("%Y-%m-%d %H:%M"),
            "todate": now.strftime("%Y-%m-%d %H:%M")
        }

        try:
            resp = self.smart_api.getCandleData(params)
            if not resp or resp.get("status") is not True:
                return None

            candles = resp.get("data", [])
            if len(candles) < 25:
                # Need at least 25 candles for reliable EMA 21
                return None

            closes = [float(c[4]) for c in candles]
            ema_fast = self._calculate_ema(closes, period=9)
            ema_slow = self._calculate_ema(closes, period=21)
            last_close = closes[-1]

            # Determine Trend Direction & Strength
            if last_close > ema_fast > ema_slow:
                trend = "BULLISH"
                strength = "STRONG_BULLISH" if (last_close - ema_fast) > (ema_fast - ema_slow) else "MODERATE_BULLISH"
            elif last_close < ema_fast < ema_slow:
                trend = "BEARISH"
                strength = "STRONG_BEARISH" if (ema_fast - last_close) > (ema_slow - ema_fast) else "MODERATE_BEARISH"
            else:
                trend = "NEUTRAL"
                strength = "CHOPPY_OR_PULLBACK"

            res = {
                "trend": trend,
                "strength": strength,
                "ema_fast": round(ema_fast, 2),
                "ema_slow": round(ema_slow, 2),
                "last_close": round(last_close, 2),
                "updated_at": now.strftime("%H:%M:%S")
            }
            logger.info(f"[MTF 15M] Trend: {trend} ({strength}) | Close: {last_close} | EMA9: {res['ema_fast']} | EMA21: {res['ema_slow']}")
            return res

        except Exception as e:
            logger.debug(f"Failed to fetch/calculate 15m candles: {e}")
            return None

    @staticmethod
    def _calculate_ema(values: list, period: int) -> float:
        """Standard Exponential Moving Average calculation."""
        if len(values) < period:
            return values[-1] if values else 0.0

        multiplier = 2 / (period + 1)
        # Start with SMA for first 'period' values
        ema = sum(values[:period]) / period

        for val in values[period:]:
            ema = (val - ema) * multiplier + ema

        return ema


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    import pyotp
    from SmartApi.smartConnect import SmartConnect

    smart = SmartConnect(api_key=config.ANGEL_API_KEY)
    totp = pyotp.TOTP(config.ANGEL_TOTP_SECRET).now()
    session = smart.generateSession(config.ANGEL_CLIENT_CODE, config.ANGEL_PIN, totp)
    if session.get("status") is True:
        print("Authenticated with Angel One. Calculating MTF 15M Bias...")
        mtf = MultiTimeframeFilter(smart_api=smart)
        bias = mtf.update_bias_now()
        print("\nMTF 15M Trend Result:")
        for k, v in bias.items():
            print(f"  {k}: {v}")
    else:
        print("Auth failed:", session.get("message"))
