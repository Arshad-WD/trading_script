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
                timestamp=sim_time
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
    Connects to Angel One SmartAPI and streams live market quotes, volume & OI at zero cost.
    """
    print("\n" + "="*65, flush=True)
    print("   CONNECTING TO LIVE ANGEL ONE SMARTAPI (FREE LIVE DATA)", flush=True)
    print("="*65 + "\n", flush=True)

    client = AngelClientManager()
    if not client.is_connected():
        print("[ERROR] Angel One authentication failed. Check credentials in .env.", flush=True)
        return

    print(f"[SUCCESS] Connected to Angel One SmartAPI! User: {client.user_profile.get('name')}", flush=True)
    display_economic_news()

    notifier = TelegramNotifier()
    logger = SignalLogger()
    nifty_vwap = VWAPTracker("NIFTY")
    bn_vwap = VWAPTracker("BANKNIFTY")
    lead_lag = LeadLagMonitor(divergence_threshold_pct=0.20)
    iceberg_detector = IcebergAbsorptionDetector(
        volume_threshold=config.WHALE_VOLUME_THRESHOLD,
        price_tolerance_points=config.ABSORPTION_PRICE_POINTS,
        window_seconds=config.EVALUATION_WINDOW_SECONDS
    )

    data = client.get_spot_and_futures()
    nifty_spot = data.get(config.ANGEL_TOKENS["NIFTY_SPOT"]["token"], {})
    bn_spot = data.get(config.ANGEL_TOKENS["BANKNIFTY_SPOT"]["token"], {})
    nifty_fut = data.get(config.ANGEL_TOKENS["NIFTY_FUT"]["token"], {})

    print(f"\n[LIVE REAL-TIME SNAPSHOT]")
    print(f"NIFTY SPOT:      LTP {nifty_spot.get('ltp')} | Open: {nifty_spot.get('open')} | Chg: {nifty_spot.get('percent_change')}%")
    print(f"BANKNIFTY SPOT:  LTP {bn_spot.get('ltp')} | Open: {bn_spot.get('open')} | Chg: {bn_spot.get('percent_change')}%")
    print(f"NIFTY FUTURES:   LTP {nifty_fut.get('ltp')} | Vol: {nifty_fut.get('volume'):,} | OI: {nifty_fut.get('oi'):,} | VWAP: {nifty_fut.get('avg_price')}\n")

    if nifty_spot.get("open", 0) > 0 and bn_spot.get("open", 0) > 0:
        lead_lag.set_day_open(nifty_spot["open"], bn_spot["open"])

    print("[INFO] Monitoring live stream & tape reading. Press Ctrl+C to exit.\n", flush=True)

    prev_fut_vol = nifty_fut.get("volume", 0)
    prev_fut_oi = nifty_fut.get("oi", 0)
    prev_fut_price = nifty_fut.get("ltp", 0.0)
    last_whale_alert = None

    # Estimated nearby walls
    levels = {"call_wall": 25200.0, "put_wall": 25000.0}

    try:
        while True:
            quotes = client.get_spot_and_futures()
            n_spot = quotes.get(config.ANGEL_TOKENS["NIFTY_SPOT"]["token"], {})
            b_spot = quotes.get(config.ANGEL_TOKENS["BANKNIFTY_SPOT"]["token"], {})
            n_fut = quotes.get(config.ANGEL_TOKENS["NIFTY_FUT"]["token"], {})

            n_ltp = n_spot.get("ltp", 0.0)
            b_ltp = b_spot.get("ltp", 0.0)
            fut_ltp = n_fut.get("ltp", 0.0)
            fut_vol = n_fut.get("volume", 0)
            fut_oi = n_fut.get("oi", 0)
            fut_vwap = n_fut.get("avg_price", 0.0)

            # Guard against network timeouts or empty quotes
            if not quotes or not n_fut or fut_ltp <= 0:
                time.sleep(2)
                continue

            now = datetime.now()
            
            # Only compute incremental volume if previous volume was valid
            inc_vol = (fut_vol - prev_fut_vol) if (prev_fut_vol > 0 and fut_vol >= prev_fut_vol) else 0
            prev_fut_vol = fut_vol

            # Check OI Build-up if OI changed and valid
            if fut_oi != prev_fut_oi and prev_fut_oi > 0 and prev_fut_price > 0 and fut_ltp > 0:
                oi_analysis = OIAnalyzer.classify_oi_buildup(prev_fut_price, fut_ltp, prev_fut_oi, fut_oi, symbol="NSE:NIFTY-I")
                if oi_analysis.get("formatted_message"):
                    notifier.send_alert("OI BUILD-UP", oi_analysis["formatted_message"])
            
            if fut_oi > 0:
                prev_fut_oi = fut_oi
            if fut_ltp > 0:
                prev_fut_price = fut_ltp

            # Feed to Iceberg / Absorption detector only if valid incremental volume
            if inc_vol > 0:
                resolved_whale_alerts = iceberg_detector.on_tick(
                    timestamp=now, price=fut_ltp, incremental_volume=inc_vol,
                    symbol="NSE:NIFTY-I", call_wall=levels["call_wall"], put_wall=levels["put_wall"]
                )
                for alert in resolved_whale_alerts:
                    last_whale_alert = alert
                    notifier.send_alert("WHALE ORDER ABSORPTION", alert["formatted_message"])

            if n_ltp > 0 and b_ltp > 0:
                n_state = nifty_vwap.update(now, n_ltp, 1000)
                b_state = bn_vwap.update(now, b_ltp, 2000)
                ll_state = lead_lag.update(n_ltp, n_state["vwap"], b_ltp, b_state["vwap"])

                # Confluence evaluation
                confluence = ConfluenceEngine.evaluate_setup(
                    current_price=n_ltp, symbol="NIFTY",
                    vwap_state=n_state, levels=levels,
                    whale_alert=last_whale_alert, lead_lag_state=ll_state,
                    timestamp=now
                )
                if confluence and confluence["score"] >= ConfluenceEngine.MIN_A_PLUS_SCORE:
                    notifier.send_alert("A+ INSTITUTIONAL SETUP", confluence["formatted_message"])
                    logger.log_trade(
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
                    last_whale_alert = None

                print(
                    f"[{now.strftime('%H:%M:%S')}] "
                    f"NIFTY: {n_ltp:.2f} | BANKNIFTY: {b_ltp:.2f} | "
                    f"FUTURES: {fut_ltp:.2f} (VWAP: {fut_vwap:.2f}) | "
                    f"Lead-Lag: {ll_state['signal']}",
                    flush=True
                )

                if ll_state["banknifty_leads"] and ll_state["signal"] in ["BANKNIFTY_LEADING_BULLISH", "BANKNIFTY_LEADING_BEARISH"]:
                    lead_msg = (
                        f"Signal: {ll_state['signal']}\n"
                        f"BankNifty % Chg: {ll_state['banknifty_pct_chg']}%\n"
                        f"Nifty % Chg: {ll_state['nifty_pct_chg']}%\n"
                        f"Spread: {ll_state['spread_pct']}%\n"
                        f"Action: {ll_state['action_recommendation']}"
                    )
                    notifier.send_alert("LIVE LEAD-LAG SIGNAL", lead_msg)

            time.sleep(2)

    except KeyboardInterrupt:
        print("\n[INFO] Stopped live monitoring.", flush=True)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Institutional Orderflow & Lead-Lag Trading Engine")
    parser.add_argument("--simulate", action="store_true", help="Run with simulated market feed")
    parser.add_argument("--broker", choices=["angel", "dhan"], default="angel", help="Broker to use (default: angel)")
    args = parser.parse_args()

    if args.simulate:
        run_simulation()
    elif args.broker == "angel":
        run_angel_live()
    elif args.broker == "dhan":
        run_simulation()
