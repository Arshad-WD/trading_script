import argparse
import time
import random
from datetime import datetime, timedelta
import config
from angel_client import AngelClientManager
from vwap_tracker import VWAPTracker
from oi_analyzer import OIAnalyzer
from iceberg_detector import IcebergAbsorptionDetector
from lead_lag_monitor import LeadLagMonitor
from telegram_notifier import TelegramNotifier
from news_feed import ForexFactoryCalendar
from confluence_engine import ConfluenceEngine
from trade_logger import SignalLogger
from instrument_manager import update_config_tokens
from option_chain_fetcher import OptionChainFetcher
from websocket_feed import WebSocketFeed, build_callbacks
from market_hours import MarketHours
from mtf_filter import MultiTimeframeFilter
from position_sizer import PositionSizer

def display_economic_news():
    """
    Fetches and displays upcoming high-impact economic news from ForexFactory.
    """
    cal = ForexFactoryCalendar()
    events = cal.get_upcoming_high_impact(hours_ahead=48)
    if events:
        print("\n📅 [UPCOMING HIGH-IMPACT ECONOMIC EVENTS - FOREXFACTORY]")
        for e in events[:4]:
            print(f"   ⚡ {e['country']} | {e['title']} | Forecast: {e['forecast']} | Time: {e['time_ist']}")
        print()

def run_simulation():
    """
    Simulates real market conditions with Nifty & BankNifty live ticks,
    whale volume surges, iceberg absorption, sliced orders, and option chain levels.
    """
    print("\n" + "="*65, flush=True)
    print("   STARTING REALISTIC MARKET ENGINE (SIMULATION MODE)", flush=True)
    print("="*65 + "\n", flush=True)

    display_economic_news()

    notifier = TelegramNotifier()
    logger = SignalLogger()
    nifty_vwap = VWAPTracker("NIFTY")
    bn_vwap = VWAPTracker("BANKNIFTY")
    iceberg_detector = IcebergAbsorptionDetector(
        volume_threshold=10000,
        price_tolerance_points=3.0,
        window_seconds=15
    )
    lead_lag = LeadLagMonitor(divergence_threshold_pct=0.20)

    # Simulated starting levels matching Telegram screenshots
    call_wall = 25000.0
    put_wall = 24900.0
    gamma_plus_wall = 25100.0
    gamma_minus_wall = 24900.0
    levels = {
        "call_wall": call_wall,
        "put_wall": put_wall,
        "gamma_plus": gamma_plus_wall,
        "gamma_minus": gamma_minus_wall
    }

    nifty_price = 24995.0
    bn_price = 59012.0
    lead_lag.set_day_open(nifty_price, bn_price)

    # Initial LEVELS snapshot
    levels_msg = OIAnalyzer.format_levels_report(
        symbol="NIFTY", spot_price=nifty_price,
        call_wall=call_wall, call_oi=27810000, second_call_wall=25100,
        put_wall=put_wall, put_oi=24580000, second_put_wall=24800,
        max_pain=24900, pcr=0.81, gamma_plus=gamma_plus_wall,
        gamma_minus=gamma_minus_wall, zero_gamma=25162.22
    )
    notifier.send_alert("LEVELS", levels_msg)

    print("[INFO] Simulated market stream running. Press Ctrl+C to exit.\n", flush=True)

    sim_time = datetime.now().replace(hour=10, minute=15, second=0)
    step = 0
    cum_delta = 5390.0
    last_whale_alert = None

    try:
        while True:
            step += 1
            sim_time += timedelta(seconds=2)

            # Price action drift
            if step in [1, 2, 3]:
                # Simulate absorption at Call wall (price hovers near 24,995 - 25,000)
                nifty_delta = random.choice([0.0, 0.5])
                bn_delta = -35.0  # BankNifty dragging bearish strongly
                tick_vol = 60000 if step == 1 else random.randint(400, 1500)
                side = "BUY"
            elif step == 10:
                # BankNifty Whale Breakout
                bn_delta = -25.0
                nifty_delta = -1.0
                tick_vol = 1320
                side = "SELL"
            else:
                nifty_delta = random.choice([-2.0, -1.0, 0.0, 1.0, 2.0])
                bn_delta = random.choice([-15.0, -5.0, 5.0, 15.0])
                tick_vol = random.randint(500, 2500)
                side = "BUY" if nifty_delta >= 0 else "SELL"

            nifty_price = round(nifty_price + nifty_delta, 2)
            bn_price = round(bn_price + bn_delta, 2)
            cum_delta += tick_vol if side == "BUY" else -tick_vol

            # Update VWAPs
            n_state = nifty_vwap.update(sim_time, nifty_price, tick_vol)
            bn_state = bn_vwap.update(sim_time, bn_price, tick_vol * 2)

            # Process ticks for Whale & Absorption detection
            resolved_whale_alerts = iceberg_detector.on_tick(
                timestamp=sim_time, price=nifty_price, incremental_volume=tick_vol,
                side=side, cum_delta=cum_delta, symbol="NSE:NIFTY-I",
                call_wall=call_wall, put_wall=put_wall
            )
            for alert in resolved_whale_alerts:
                last_whale_alert = alert
                notifier.send_alert("WHALE ALERT", alert["formatted_message"])

            # Check for Sliced Order pattern
            sliced_alert = iceberg_detector.check_sliced_order(symbol="NSE:NIFTY-I")
            if sliced_alert:
                notifier.send_alert("SLICED ORDER", sliced_alert["formatted_message"])

            # Update Lead-Lag Monitor
            ll_state = lead_lag.update(nifty_price, n_state["vwap"], bn_price, bn_state["vwap"])

            # Evaluate Confluence Engine (A+ High Probability Setup)
            confluence_setup = ConfluenceEngine.evaluate_setup(
                current_price=nifty_price, symbol="NIFTY",
                vwap_state=n_state, levels=levels,
                whale_alert=last_whale_alert, lead_lag_state=ll_state,
                timestamp=sim_time,
                is_simulated=True
            )
            if confluence_setup and confluence_setup["score"] >= ConfluenceEngine.MIN_A_PLUS_SCORE:
                # Deliver A+ setup alert
                notifier.send_alert("A+ INSTITUTIONAL SETUP", confluence_setup["formatted_message"])
                # Log to CSV
                logger.log_trade(
                    symbol=confluence_setup["symbol"],
                    direction=confluence_setup["direction"],
                    setup_type=confluence_setup["grade"],
                    score=confluence_setup["score"],
                    entry=confluence_setup["entry"],
                    sl=confluence_setup["stop_loss"],
                    t1=confluence_setup["target_1"],
                    t2=confluence_setup["target_2"],
                    rr=confluence_setup["risk_reward"]
                )
                last_whale_alert = None  # Reset so it doesn't re-trigger continuously

            # Periodic Status Line
            if step % 4 == 0:
                print(
                    f"[{sim_time.strftime('%H:%M:%S')}] "
                    f"NIFTY: {nifty_price:.2f} (VWAP: {n_state['vwap']:.2f}) | "
                    f"BANKNIFTY: {bn_price:.2f} | "
                    f"Lead-Lag: {ll_state['signal']}",
                    flush=True
                )

            time.sleep(1)

    except KeyboardInterrupt:
        print("\n[INFO] Simulation stopped by user.", flush=True)

def run_angel_live():
    """
    Connects to Angel One SmartAPI with:
      - Auto-rollover Nifty & MCX Crude Oil Futures tokens (instrument_manager)
      - Real-time WebSocket tick-by-tick streaming for NSE & MCX
      - Live option chain levels refreshed every 5 min (option_chain_fetcher)
      - Multi-Asset VWAP, Iceberg & Whale absorption monitoring
    """
    print("\n" + "="*65, flush=True)
    print("   CONNECTING TO LIVE ANGEL ONE SMARTAPI (MULTI-ASSET FEED)", flush=True)
    print("="*65 + "\n", flush=True)

    client = AngelClientManager()
    if not client.is_connected():
        print("[ERROR] Angel One authentication failed. Check credentials in .env.", flush=True)
        return

    print(f"[SUCCESS] Connected to Angel One! User: {client.user_profile.get('name')}", flush=True)
    display_economic_news()

    # ── STEP 1: Auto-rollover Futures tokens (Nifty + MCX Crude Oil) ───────
    resolved_tokens = update_config_tokens(smart_api=client.smart_api)
    nifty_fut = resolved_tokens.get("NIFTY_FUT", {})
    crude_fut = resolved_tokens.get("CRUDEOIL_FUT", {})
    print(
        f"[AUTO-ROLLOVER] Nifty Futures    → Token: {nifty_fut.get('token')} | "
        f"Symbol: {nifty_fut.get('symbol')} | Expiry: {nifty_fut.get('expiry')}",
        flush=True
    )
    print(
        f"[AUTO-ROLLOVER] MCX Crude Oil   → Token: {crude_fut.get('token')} | "
        f"Symbol: {crude_fut.get('symbol')} | Expiry: {crude_fut.get('expiry')}",
        flush=True
    )

    notifier   = TelegramNotifier()
    sig_logger = SignalLogger()
    nifty_vwap = VWAPTracker("NIFTY")
    bn_vwap    = VWAPTracker("BANKNIFTY")
    crude_vwap = VWAPTracker("CRUDEOIL")
    lead_lag   = LeadLagMonitor(divergence_threshold_pct=0.20)
    iceberg_detector = IcebergAbsorptionDetector(
        volume_threshold=config.WHALE_VOLUME_THRESHOLD,
        price_tolerance_points=config.ABSORPTION_PRICE_POINTS,
        window_seconds=config.EVALUATION_WINDOW_SECONDS
    )
    crude_iceberg = IcebergAbsorptionDetector(
        volume_threshold=config.ASSET_CONFIGS["CRUDEOIL"]["whale_volume"],
        price_tolerance_points=config.ASSET_CONFIGS["CRUDEOIL"]["absorption_points"],
        window_seconds=20
    )

    # Initial REST snapshot
    data       = client.get_spot_and_futures()
    n_spot0    = data.get(config.ANGEL_TOKENS["NIFTY_SPOT"]["token"], {})
    bn_spot0   = data.get(config.ANGEL_TOKENS["BANKNIFTY_SPOT"]["token"], {})
    nifty_fut0 = data.get(config.ANGEL_TOKENS["NIFTY_FUT"]["token"], {})
    crude_fut0 = data.get(config.ANGEL_TOKENS["CRUDEOIL_FUT"]["token"], {})

    print(f"\n[SNAPSHOT]")
    print(f"  NIFTY SPOT:    LTP {n_spot0.get('ltp')} | Open: {n_spot0.get('open')} | Chg: {n_spot0.get('percent_change')}%")
    print(f"  BANKNIFTY:     LTP {bn_spot0.get('ltp')} | Open: {bn_spot0.get('open')} | Chg: {bn_spot0.get('percent_change')}%")
    print(f"  NIFTY FUTURES: LTP {nifty_fut0.get('ltp')} | Vol: {nifty_fut0.get('volume', 0):,} | OI: {nifty_fut0.get('oi', 0):,}")
    print(f"  CRUDE OIL FUT: LTP {crude_fut0.get('ltp')} | Vol: {crude_fut0.get('volume', 0):,} | OI: {crude_fut0.get('oi', 0):,} | VWAP: {crude_fut0.get('avg_price', 0):,}\n")

    if n_spot0.get("open", 0) > 0 and bn_spot0.get("open", 0) > 0:
        lead_lag.set_day_open(n_spot0["open"], bn_spot0["open"])

    # ── STEP 2: Option chain fetcher (5-min background refresh) ───────────
    levels_ref = {
        "call_wall":  25200.0,
        "put_wall":   25000.0,
        "gamma_plus": 25300.0,
        "gamma_minus": 24900.0,
        "max_pain":   25100.0,
        "pcr":        0.95,
    }
    oc_fetcher = OptionChainFetcher(smart_api=client.smart_api)
    if MarketHours.is_market_open(exchange="NSE"):
        initial_levels = oc_fetcher.fetch_once()
        if initial_levels:
            levels_ref.update(initial_levels)
            print(f"[OC] Call Wall: {initial_levels['call_wall']} | Put Wall: {initial_levels['put_wall']} | PCR: {initial_levels['pcr']}", flush=True)
    else:
        print("[OC] NSE equity session closed — option chain in standby mode.", flush=True)

    def _oc_sync_loop():
        while True:
            time.sleep(oc_fetcher.interval)
            if MarketHours.is_market_open(exchange="NSE"):
                new_levels = oc_fetcher.fetch_once()
                if new_levels:
                    levels_ref.update(new_levels)

    import threading
    _oc_thread = threading.Thread(target=_oc_sync_loop, daemon=True, name="OptionChainSync")
    _oc_thread.start()

    # ── STEP 3: Multi-Timeframe (15M) Trend Filter ─────────────────────────
    mtf_filter = MultiTimeframeFilter(smart_api=client.smart_api)
    mtf_filter.start_background_tracker()

    # ── STEP 4: Market Hours Check (NSE & MCX) ─────────────────────────────
    nse_phase = MarketHours.session_phase(exchange="NSE")
    mcx_phase = MarketHours.session_phase(exchange="MCX")
    nse_open  = MarketHours.is_market_open(exchange="NSE")
    mcx_open  = MarketHours.is_market_open(exchange="MCX")

    print(f"[MARKET STATUS] Current IST: {MarketHours.now_ist().strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
    print(f"  • NSE (Equity / F&O): {nse_phase} ({'OPEN' if nse_open else 'CLOSED'})", flush=True)
    print(f"  • MCX (Commodities) : {mcx_phase} ({'OPEN' if mcx_open else 'CLOSED'})\n", flush=True)

    # ── STEP 5: WebSocket real-time feed ───────────────────────────────────
    state_ref = {}
    callbacks = build_callbacks(
        vwap_tracker_nifty=nifty_vwap,
        vwap_tracker_bn=bn_vwap,
        iceberg_detector=iceberg_detector,
        lead_lag_monitor=lead_lag,
        confluence_engine_cls=ConfluenceEngine,
        oi_analyzer_cls=OIAnalyzer,
        notifier=notifier,
        logger_obj=sig_logger,
        levels_ref=levels_ref,
        state_ref=state_ref,
        mtf_filter=mtf_filter,
        vwap_tracker_crude=crude_vwap,
        iceberg_detector_crude=crude_iceberg,
    )
    feed = WebSocketFeed(angel_client=client, callbacks=callbacks)

    print("[INFO] Starting real-time WebSocket tick stream. Press Ctrl+C to exit.\n", flush=True)
    notifier.send_alert("SYSTEM", (
        f"🚀 Trading Engine LIVE (Multi-Asset)\n"
        f"Mode: WebSocket (Tick-by-Tick Feed)\n"
        f"NSE Session: {nse_phase} | MCX Session: {mcx_phase}\n"
        f"Crude Oil FUT: {crude_fut.get('symbol')} (MCX)\n"
        f"Nifty FUT: {nifty_fut.get('symbol')} (NFO)\n"
        f"Live Ticks Streaming Active!"
    ))

    try:
        feed.start()
        # Main thread stays alive — WebSocket runs in its daemon thread
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[INFO] Stopping…", flush=True)
        feed.stop()
        print("[INFO] WebSocket feed stopped. Goodbye.", flush=True)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Institutional Orderflow & Lead-Lag Trading Engine")
    parser.add_argument("--simulate",  action="store_true", help="Run with simulated market feed")
    parser.add_argument("--backtest",  action="store_true", help="Run backtester on signals_history.csv")
    parser.add_argument("--last",      type=int, default=None, help="(backtest) Only last N signals")
    parser.add_argument("--show-trades", action="store_true",  help="(backtest) Verbose per-trade output")
    parser.add_argument("--broker",    choices=["angel", "dhan"], default="angel", help="Broker to use (default: angel)")
    args = parser.parse_args()

    if args.backtest:
        from backtester import run_backtest
        run_backtest(limit=args.last, verbose=args.show_trades)
    elif args.simulate:
        run_simulation()
    elif args.broker == "angel":
        run_angel_live()
    elif args.broker == "dhan":
        run_simulation()
