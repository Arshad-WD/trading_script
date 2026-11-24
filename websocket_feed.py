"""
websocket_feed.py
─────────────────
Real-time tick-by-tick market data via Angel One SmartWebSocket v2.
Replaces the 2-second REST polling loop in run_angel_live().

Subscribed tokens (SNAP_QUOTE mode = full depth + OI):
  - 99926000  : Nifty 50 Spot  (NSE)
  - 99926009  : Nifty Bank Spot (NSE)
  - <dynamic> : Nifty Futures (NFO) — resolved by instrument_manager at startup

Usage (from main.py):
    feed = WebSocketFeed(angel_client, callbacks)
    feed.start()
    # callbacks fire on every tick — no polling needed
    feed.stop()
"""

import json
import logging
import threading
import time
from datetime import datetime
from typing import Callable, Optional

from market_hours import MarketHours

logger = logging.getLogger("WebSocketFeed")

# If no tick received for this many seconds → declare feed stale and reconnect
HEARTBEAT_TIMEOUT_SECONDS = 45

# Angel One SmartWebSocket subscription modes
MODE_LTP        = 1   # Last Traded Price only
MODE_QUOTE      = 2   # LTP + OHLC
MODE_SNAP_QUOTE = 3   # Full: LTP + OHLC + Volume + OI + Depth (we use this)

# Reconnect parameters
MAX_RECONNECT_ATTEMPTS = 10
RECONNECT_DELAY_SECONDS = 5


class WebSocketFeed:
    """
    Wraps Angel One SmartWebSocket v2 to deliver real-time ticks
    via registered callbacks instead of polling.

    Callbacks dict keys (all optional):
        "on_nifty_tick"    : fn(tick: dict)   — called for Nifty spot ticks
        "on_bn_tick"       : fn(tick: dict)   — called for BankNifty spot ticks
        "on_futures_tick"  : fn(tick: dict)   — called for Nifty Futures ticks
        "on_any_tick"      : fn(tick: dict)   — called for every tick regardless
        "on_connect"       : fn()             — called when WS connects
        "on_disconnect"    : fn(reason: str)  — called on disconnect
        "on_error"         : fn(err: str)     — called on WS error
    """

    def __init__(self, angel_client, callbacks: dict = None):
        """
        angel_client: AngelClientManager instance (must already be authenticated).
        callbacks: dict of optional callback functions (see class docstring).
        """
        self._client = angel_client
        self._callbacks = callbacks or {}
        self._ws = None
        self._running = False
        self._reconnect_count = 0
        self._thread: Optional[threading.Thread] = None
        self._watchdog_thread: Optional[threading.Thread] = None
        self._last_tick_time: Optional[datetime] = None

        # Token → instrument mapping (populated in start())
        self._token_map: dict = {}

    # ─── Public API ───────────────────────────────────────────────────────────

    def start(self):
        """Connects WebSocket and begins receiving ticks in a background thread."""
        import config
        self._token_map = {
            config.ANGEL_TOKENS["NIFTY_SPOT"]["token"]:    "NIFTY_SPOT",
            config.ANGEL_TOKENS["BANKNIFTY_SPOT"]["token"]: "BANKNIFTY_SPOT",
            config.ANGEL_TOKENS["NIFTY_FUT"]["token"]:      "NIFTY_FUT",
            config.ANGEL_TOKENS["CRUDEOIL_FUT"]["token"]:   "CRUDEOIL_FUT",
        }
        self._running = True
        self._last_tick_time = datetime.now()
        self._thread = threading.Thread(target=self._connect_loop, daemon=True, name="WebSocketFeed")
        self._thread.start()
        # Start heartbeat watchdog
        self._watchdog_thread = threading.Thread(target=self._watchdog_loop, daemon=True, name="WSWatchdog")
        self._watchdog_thread.start()
        logger.info("WebSocket feed + heartbeat watchdog started.")

    def stop(self):
        """Gracefully stops the WebSocket feed."""
        self._running = False
        if self._ws:
            try:
                self._ws.close_connection()
            except Exception:
                pass
        logger.info("WebSocket feed stopped.")

    def is_running(self) -> bool:
        return self._running and self._thread is not None and self._thread.is_alive()

    # ─── Internal ─────────────────────────────────────────────────────────────

    def _connect_loop(self):
        """Main loop — reconnects on failure up to MAX_RECONNECT_ATTEMPTS."""
        while self._running and self._reconnect_count <= MAX_RECONNECT_ATTEMPTS:
            try:
                self._establish_connection()
            except Exception as e:
                logger.warning(f"WebSocket connection error: {e}")
                self._fire("on_error", str(e))

            if not self._running:
                break

            self._reconnect_count += 1
            if self._reconnect_count > MAX_RECONNECT_ATTEMPTS:
                logger.error("Max WebSocket reconnect attempts reached. Feed stopped.")
                break

            delay = RECONNECT_DELAY_SECONDS * min(self._reconnect_count, 6)
            logger.info(f"Reconnecting in {delay}s (attempt {self._reconnect_count}/{MAX_RECONNECT_ATTEMPTS})…")
            time.sleep(delay)

    def _watchdog_loop(self):
        """Monitors tick activity and force-reconnects if feed stalls during market hours."""
        logger.info(f"[WATCHDOG] Tick watchdog active (timeout: {HEARTBEAT_TIMEOUT_SECONDS}s).")
        while self._running:
            time.sleep(10)
            if not self._running:
                break

            # Only enforce watchdog during active market hours
            if not MarketHours.is_market_open():
                continue

            if self._last_tick_time:
                elapsed = (datetime.now() - self._last_tick_time).total_seconds()
                if elapsed > HEARTBEAT_TIMEOUT_SECONDS:
                    logger.warning(
                        f"[WATCHDOG] Tick feed stale! No tick received for {elapsed:.1f}s. "
                        f"Forcing WebSocket reconnect..."
                    )
                    self._fire("on_error", f"Watchdog timeout: no tick for {elapsed:.1f}s")
                    if self._ws:
                        try:
                            self._ws.close_connection()
                        except Exception:
                            pass
                    self._last_tick_time = datetime.now()

    def _establish_connection(self):
        """Creates SmartWebSocket and sets up callbacks."""
        from SmartApi.smartWebSocketV2 import SmartWebSocketV2
        import config

        client = self._client
        if not client.is_connected():
            logger.error("Angel One client not authenticated. Cannot start WebSocket.")
            return

        self._ws = SmartWebSocketV2(
            auth_token=client.jwt_token,
            api_key=client.api_key,
            client_code=client.client_code,
            feed_token=client.feed_token,
            max_retry_attempt=3
        )

        def on_open(wsapp):
            logger.info("WebSocket connected. Subscribing to tokens…")
            self._reconnect_count = 0  # reset on successful connect
            self._fire("on_connect")
            self._subscribe()

        def on_data(wsapp, message):
            self._handle_tick(message)

        def on_error(wsapp, error):
            logger.warning(f"WebSocket error: {error}")
            self._fire("on_error", str(error))

        def on_close(wsapp, close_status_code, close_msg):
            reason = f"code={close_status_code} msg={close_msg}"
            logger.info(f"WebSocket closed: {reason}")
            self._fire("on_disconnect", reason)

        self._ws.on_open    = on_open
        self._ws.on_data    = on_data
        self._ws.on_error   = on_error
        self._ws.on_close   = on_close

        # Blocking call — returns when socket closes
        self._ws.connect()

    def _subscribe(self):
        """Sends subscription request for all configured tokens."""
        import config

        correlation_id = "trading_engine_v2"
        token_list = [
            {
                "exchangeType": 1,   # 1 = NSE
                "tokens": [
                    config.ANGEL_TOKENS["NIFTY_SPOT"]["token"],
                    config.ANGEL_TOKENS["BANKNIFTY_SPOT"]["token"],
                ]
            },
            {
                "exchangeType": 2,   # 2 = NFO
                "tokens": [
                    config.ANGEL_TOKENS["NIFTY_FUT"]["token"],
                ]
            },
            {
                "exchangeType": 5,   # 5 = MCX_FO (Commodity Futures)
                "tokens": [
                    config.ANGEL_TOKENS["CRUDEOIL_FUT"]["token"],
                ]
            }
        ]
        self._ws.subscribe(correlation_id, MODE_SNAP_QUOTE, token_list)
        logger.info(f"Subscribed to tokens: {[t for group in token_list for t in group['tokens']]}")

    def _handle_tick(self, message):
        """
        Parses incoming WebSocket tick and routes to the right callback.
        Angel One SNAP_QUOTE tick schema (v2):
          token, last_traded_price, open_price_of_the_day, high_price_of_the_day,
          low_price_of_the_day, close_price, volume_trade_for_the_day,
          open_interest, ...
        Prices are in paise (divide by 100 to get rupees).
        """
        try:
            self._last_tick_time = datetime.now()
            # message may be bytes or dict depending on SDK version
            if isinstance(message, (bytes, bytearray)):
                data = json.loads(message.decode("utf-8"))
            elif isinstance(message, str):
                data = json.loads(message)
            else:
                data = message  # already dict

            token = str(data.get("token", data.get("tk", "")))

            # Normalize prices (paise → rupees)
            tick = {
                "token":      token,
                "instrument": self._token_map.get(token, "UNKNOWN"),
                "timestamp":  datetime.now(),
                "ltp":        data.get("last_traded_price", data.get("lp", 0)) / 100,
                "open":       data.get("open_price_of_the_day",  data.get("op", 0)) / 100,
                "high":       data.get("high_price_of_the_day",  data.get("h",  0)) / 100,
                "low":        data.get("low_price_of_the_day",   data.get("lo", 0)) / 100,
                "close":      data.get("close_price",            data.get("c",  0)) / 100,
                "volume":     data.get("volume_trade_for_the_day", data.get("v", 0)),
                "oi":         data.get("open_interest",           data.get("oi", 0)),
                "avg_price":  data.get("average_trade_price",     data.get("ap", 0)) / 100,
                "raw":        data,
            }

            # Route to instrument-specific callbacks
            instrument = self._token_map.get(token, "")
            if instrument == "NIFTY_SPOT":
                self._fire("on_nifty_tick", tick)
            elif instrument == "BANKNIFTY_SPOT":
                self._fire("on_bn_tick", tick)
            elif instrument == "NIFTY_FUT":
                self._fire("on_futures_tick", tick)
            elif instrument == "CRUDEOIL_FUT":
                self._fire("on_crude_tick", tick)

            self._fire("on_any_tick", tick)

        except Exception as e:
            logger.debug(f"Tick parse error: {e} | raw={message}")

    def _fire(self, event: str, *args):
        """Safely calls a registered callback by event name."""
        cb = self._callbacks.get(event)
        if cb:
            try:
                cb(*args)
            except Exception as e:
                logger.warning(f"Callback '{event}' raised: {e}")


# ─── Convenience: build callbacks dict for main engine ────────────────────────

def build_callbacks(
    vwap_tracker_nifty,
    vwap_tracker_bn,
    iceberg_detector,
    lead_lag_monitor,
    confluence_engine_cls,
    oi_analyzer_cls,
    notifier,
    logger_obj,
    levels_ref: dict,
    state_ref: dict,
    mtf_filter=None,
    vwap_tracker_crude=None,
    iceberg_detector_crude=None,
) -> dict:
    """
    Returns a callbacks dict wired to all engine components.
    levels_ref  : mutable dict updated by OptionChainFetcher — passed by reference
    state_ref   : mutable dict for cross-tick state (prev_vol, prev_oi, etc.)
    mtf_filter  : MultiTimeframeFilter instance for higher timeframe (15M) bias
    """
    from confluence_engine import ConfluenceEngine

    state_ref.setdefault("prev_fut_vol",   0)
    state_ref.setdefault("prev_fut_oi",    0)
    state_ref.setdefault("prev_fut_price", 0.0)
    state_ref.setdefault("last_whale",     None)
    state_ref.setdefault("nifty_ltp",      0.0)
    state_ref.setdefault("bn_ltp",         0.0)
    state_ref.setdefault("nifty_vwap_state", {})
    state_ref.setdefault("bn_vwap_state",    {})
    state_ref.setdefault("crude_ltp",      0.0)
    state_ref.setdefault("prev_crude_vol", 0)
    state_ref.setdefault("crude_tick_count", 0)

    def on_nifty_tick(tick: dict):
        ltp = tick["ltp"]
        if ltp <= 0:
            return
        state_ref["nifty_ltp"] = ltp
        n_state = vwap_tracker_nifty.update(tick["timestamp"], ltp, 1000)
        state_ref["nifty_vwap_state"] = n_state

        # Lead-lag + confluence on each Nifty tick
        bn_ltp = state_ref["bn_ltp"]
        if bn_ltp > 0 and levels_ref:
            ll_state = lead_lag_monitor.update(ltp, n_state["vwap"], bn_ltp, state_ref["bn_vwap_state"].get("vwap", 0))
            if ll_state["banknifty_leads"] and ll_state["signal"] in ("BANKNIFTY_LEADING_BULLISH", "BANKNIFTY_LEADING_BEARISH"):
                msg = (
                    f"Signal: {ll_state['signal']}\n"
                    f"BankNifty %Chg: {ll_state['banknifty_pct_chg']}%\n"
                    f"Nifty %Chg: {ll_state['nifty_pct_chg']}%\n"
                    f"Action: {ll_state['action_recommendation']}"
                )
                notifier.send_alert("LIVE LEAD-LAG SIGNAL", msg)

            mtf_state = mtf_filter.get_bias() if mtf_filter else None
            confluence = ConfluenceEngine.evaluate_setup(
                current_price=ltp, symbol="NIFTY",
                vwap_state=n_state, levels=levels_ref,
                whale_alert=state_ref["last_whale"], lead_lag_state=ll_state,
                timestamp=tick["timestamp"],
                mtf_state=mtf_state,
                is_simulated=False
            )
            if confluence and confluence["score"] >= ConfluenceEngine.MIN_A_PLUS_SCORE:
                notifier.send_alert("A+ INSTITUTIONAL SETUP", confluence["formatted_message"])
                logger_obj.log_trade(
                    symbol=confluence["symbol"],
                    direction=confluence["direction"],
                    setup_type=confluence["grade"],
                    score=confluence["score"],
                    entry=confluence["entry"],
                    sl=confluence["stop_loss"],
                    t1=confluence["target_1"],
                    t2=confluence["target_2"],
                    rr=confluence["risk_reward"]
                )
                state_ref["last_whale"] = None

    def on_bn_tick(tick: dict):
        ltp = tick["ltp"]
        if ltp <= 0:
            return
        state_ref["bn_ltp"] = ltp
        b_state = vwap_tracker_bn.update(tick["timestamp"], ltp, 2000)
        state_ref["bn_vwap_state"] = b_state

    def on_futures_tick(tick: dict):
        fut_ltp = tick["ltp"]
        fut_vol = tick["volume"]
        fut_oi  = tick["oi"]
        if fut_ltp <= 0:
            return

        prev_vol   = state_ref["prev_fut_vol"]
        prev_oi    = state_ref["prev_fut_oi"]
        prev_price = state_ref["prev_fut_price"]

        # Incremental volume guard
        inc_vol = (fut_vol - prev_vol) if (prev_vol > 0 and fut_vol >= prev_vol) else 0
        state_ref["prev_fut_vol"] = fut_vol

        # OI build-up classification
        if fut_oi != prev_oi and prev_oi > 0 and prev_price > 0:
            oi_analysis = oi_analyzer_cls.classify_oi_buildup(
                prev_price, fut_ltp, prev_oi, fut_oi, symbol="NSE:NIFTY-I"
            )
            if oi_analysis.get("formatted_message"):
                notifier.send_alert("OI BUILD-UP", oi_analysis["formatted_message"])

        if fut_oi > 0:
            state_ref["prev_fut_oi"] = fut_oi
        state_ref["prev_fut_price"] = fut_ltp

        # Whale / iceberg detection
        if inc_vol > 0 and levels_ref:
            resolved = iceberg_detector.on_tick(
                timestamp=tick["timestamp"], price=fut_ltp,
                incremental_volume=inc_vol, symbol="NSE:NIFTY-I",
                call_wall=levels_ref.get("call_wall", 0),
                put_wall=levels_ref.get("put_wall", 0)
            )
            for alert in resolved:
                state_ref["last_whale"] = alert
                notifier.send_alert("WHALE ORDER ABSORPTION", alert["formatted_message"])

    def on_crude_tick(tick: dict):
        ltp = tick["ltp"]
        vol = tick["volume"]
        oi  = tick["oi"]
        vwap = tick["avg_price"]
        if ltp <= 0:
            return

        state_ref["crude_ltp"]  = ltp
        state_ref["crude_vol"]  = vol
        state_ref["crude_oi"]   = oi
        state_ref["crude_vwap"] = vwap

        now = tick["timestamp"]
        c_state = vwap_tracker_crude.update(now, ltp, 100) if vwap_tracker_crude else {"vwap": vwap or ltp}

        prev_vol = state_ref.get("prev_crude_vol", 0)
        inc_vol  = (vol - prev_vol) if (prev_vol > 0 and vol >= prev_vol) else 0
        state_ref["prev_crude_vol"] = vol

        # Whale / Iceberg absorption check for Crude Oil
        if inc_vol > 0 and iceberg_detector_crude:
            call_wall = round(ltp / 50) * 50 + 50
            put_wall  = round(ltp / 50) * 50 - 50
            resolved = iceberg_detector_crude.on_tick(
                timestamp=now, price=ltp,
                incremental_volume=inc_vol, symbol="MCX:CRUDEOIL",
                call_wall=call_wall, put_wall=put_wall
            )
            for alert in resolved:
                notifier.send_alert("CRUDE OIL WHALE ABSORPTION", alert["formatted_message"])

        step = state_ref.get("crude_tick_count", 0) + 1
        state_ref["crude_tick_count"] = step
        if step % 5 == 1:
            print(
                f"[{now.strftime('%H:%M:%S')}] [CRUDEOIL] LTP: {ltp:.2f} | "
                f"Vol: {vol:,} | OI: {oi:,} | VWAP: {vwap:.2f}",
                flush=True
            )

    def on_connect():
        logger.info("[WS] Connected to Angel One real-time feed.")
        notifier.send_alert("SYSTEM", "✅ WebSocket connected — real-time feed active.")

    def on_disconnect(reason: str):
        logger.warning(f"[WS] Disconnected: {reason}")

    def on_error(err: str):
        logger.warning(f"[WS] Error: {err}")

    return {
        "on_nifty_tick":    on_nifty_tick,
        "on_bn_tick":       on_bn_tick,
        "on_futures_tick":  on_futures_tick,
        "on_crude_tick":    on_crude_tick,
        "on_connect":       on_connect,
        "on_disconnect":    on_disconnect,
        "on_error":         on_error,
    }
