"""
backtester.py
─────────────
Historical backtesting module for signals logged in signals_history.csv.

For each A+ signal logged:
  1. Fetches 1-minute OHLC candles from Angel One getCandleData() REST API
     (available free, up to 60 days of history)
  2. Simulates forward from entry candle — checks if T1, T2, or SL is hit first
  3. Computes per-signal result: WIN_T1 / WIN_T2 / LOSS / OPEN
  4. Prints a summary table with win rate, avg R:R, max drawdown, best/worst setup
  5. Appends 'result' and 'actual_rr' columns to signals_history.csv

Usage:
    python backtester.py                      # backtest all signals in CSV
    python backtester.py --last 20            # only last 20 signals
    python backtester.py --show-trades        # verbose per-signal output
"""

import argparse
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
import csv

logger = logging.getLogger("Backtester")

SIGNALS_CSV = Path(__file__).parent / "signals_history.csv"
CANDLE_SLEEP_SECONDS = 0.3   # Throttle API calls (Angel One rate limit ~10/sec)
FORWARD_CANDLES      = 60    # Look ahead max 60 candles (60 minutes) after entry


# ─── Angel One candle fetch ────────────────────────────────────────────────────

def _fetch_candles(smart_api, token: str, exchange: str, from_dt: datetime, to_dt: datetime) -> list:
    """
    Calls Angel One getCandleData for 1-minute OHLCV bars.
    Returns list of dicts: {time, open, high, low, close, volume}
    """
    try:
        params = {
            "exchange":    exchange,
            "symboltoken": token,
            "interval":    "ONE_MINUTE",
            "fromdate":    from_dt.strftime("%Y-%m-%d %H:%M"),
            "todate":      to_dt.strftime("%Y-%m-%d %H:%M"),
        }
        resp = smart_api.getCandleData(params)
        if resp and resp.get("status") is True:
            candles = []
            for row in resp.get("data", []):
                # row = [datetime_str, open, high, low, close, volume]
                if len(row) < 6:
                    continue
                candles.append({
                    "time":   row[0],
                    "open":   float(row[1]),
                    "high":   float(row[2]),
                    "low":    float(row[3]),
                    "close":  float(row[4]),
                    "volume": int(row[5]),
                })
            return candles
        else:
            logger.debug(f"getCandleData returned: {resp}")
            return []
    except Exception as e:
        logger.warning(f"getCandleData error: {e}")
        return []


# ─── Signal simulation ─────────────────────────────────────────────────────────

def _simulate_trade(candles: list, entry: float, sl: float, t1: float, t2: float,
                    direction: str) -> dict:
    """
    Walks candles forward from entry and returns the first target/SL hit.
    direction: 'LONG' or 'SHORT'
    """
    result = "OPEN"
    exit_price = None
    exit_candle_idx = None

    for i, c in enumerate(candles):
        high = c["high"]
        low  = c["low"]

        if direction == "LONG":
            if low <= sl:
                result = "LOSS"
                exit_price = sl
                exit_candle_idx = i
                break
            if high >= t2:
                result = "WIN_T2"
                exit_price = t2
                exit_candle_idx = i
                break
            if high >= t1:
                result = "WIN_T1"
                exit_price = t1
                exit_candle_idx = i
                break
        else:  # SHORT
            if high >= sl:
                result = "LOSS"
                exit_price = sl
                exit_candle_idx = i
                break
            if low <= t2:
                result = "WIN_T2"
                exit_price = t2
                exit_candle_idx = i
                break
            if low <= t1:
                result = "WIN_T1"
                exit_price = t1
                exit_candle_idx = i
                break

    if exit_price is None:
        exit_price = candles[-1]["close"] if candles else entry

    # Actual R:R achieved
    risk   = abs(entry - sl)
    reward = abs(exit_price - entry)
    actual_rr = round(reward / risk, 2) if risk > 0 else 0.0

    return {
        "result":       result,
        "exit_price":   round(exit_price, 2),
        "actual_rr":    actual_rr,
        "candles_held": exit_candle_idx if exit_candle_idx is not None else len(candles),
    }


# ─── Main backtest runner ──────────────────────────────────────────────────────

def run_backtest(limit: Optional[int] = None, verbose: bool = False):
    """
    Main entrypoint. Authenticates Angel One, reads signals CSV, backtests each signal.
    """
    # ── Auth ──────────────────────────────────────────────────────────────────
    import config
    from SmartApi.smartConnect import SmartConnect
    import pyotp

    smart = SmartConnect(api_key=config.ANGEL_API_KEY)
    totp  = pyotp.TOTP(config.ANGEL_TOTP_SECRET).now()
    session = smart.generateSession(config.ANGEL_CLIENT_CODE, config.ANGEL_PIN, totp)
    if session.get("status") is not True:
        logger.error(f"Authentication failed: {session.get('message')}")
        print("❌ Could not authenticate with Angel One. Check .env credentials.")
        return

    logger.info(f"Authenticated as {session['data'].get('name')}.")

    # ── Read signals ──────────────────────────────────────────────────────────
    if not SIGNALS_CSV.exists():
        print(f"❌ {SIGNALS_CSV} not found. Run the main engine first to log signals.")
        return

    rows = []
    with open(SIGNALS_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        for row in reader:
            rows.append(row)

    if not rows:
        print("No signals found in signals_history.csv.")
        return

    if limit:
        rows = rows[-limit:]

    print(f"\n{'='*65}")
    print(f"  BACKTESTER  |  Signals to test: {len(rows)}")
    print(f"{'='*65}\n")

    results = []
    updated_rows = []

    for idx, row in enumerate(rows):
        signal_id = idx + 1
        symbol    = row.get("symbol", "NIFTY")
        direction = row.get("direction", "LONG").upper()
        timestamp_str = row.get("timestamp", "")
        entry_str = row.get("entry", "")
        sl_str    = row.get("sl", "")
        t1_str    = row.get("t1", "")
        t2_str    = row.get("t2", "")

        try:
            entry = float(entry_str)
            sl    = float(sl_str)
            t1    = float(t1_str)
            t2    = float(t2_str)
        except (ValueError, TypeError):
            if verbose:
                print(f"  [{signal_id}] SKIP — could not parse prices. Row: {row}")
            updated_rows.append({**row, "result": "SKIP", "actual_rr": "0"})
            continue

        # Parse entry timestamp
        try:
            entry_dt = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            try:
                entry_dt = datetime.fromisoformat(timestamp_str)
            except Exception:
                if verbose:
                    print(f"  [{signal_id}] SKIP — unparseable timestamp '{timestamp_str}'")
                updated_rows.append({**row, "result": "SKIP", "actual_rr": "0"})
                continue

        from_dt = entry_dt
        to_dt   = entry_dt + timedelta(minutes=FORWARD_CANDLES + 5)

        # Map symbol → token (use Nifty futures token for index signals)
        token    = config.ANGEL_TOKENS["NIFTY_FUT"]["token"]
        exchange = "NFO"

        if verbose:
            print(f"  [{signal_id}] {symbol} {direction} @ {entry} | SL={sl} T1={t1} T2={t2} | Entry: {entry_dt}")

        # Fetch historical candles
        candles = _fetch_candles(smart, token, exchange, from_dt, to_dt)
        time.sleep(CANDLE_SLEEP_SECONDS)   # throttle

        if not candles:
            if verbose:
                print(f"           → No candle data (market closed or old data). Marking OPEN.")
            trade_result = {"result": "NO_DATA", "exit_price": entry, "actual_rr": 0.0, "candles_held": 0}
        else:
            trade_result = _simulate_trade(candles, entry, sl, t1, t2, direction)

        result = trade_result["result"]
        actual_rr = trade_result["actual_rr"]

        if verbose:
            print(f"           → Result: {result} | Actual R:R: {actual_rr} | Held: {trade_result['candles_held']} candles")

        results.append({
            "id":        signal_id,
            "symbol":    symbol,
            "direction": direction,
            "entry":     entry,
            "sl":        sl,
            "t1":        t1,
            "t2":        t2,
            "result":    result,
            "actual_rr": actual_rr,
        })
        updated_rows.append({**row, "result": result, "actual_rr": str(actual_rr)})

    # ── Write results back to CSV ─────────────────────────────────────────────
    new_fieldnames = list(fieldnames)
    if "result" not in new_fieldnames:
        new_fieldnames.append("result")
    if "actual_rr" not in new_fieldnames:
        new_fieldnames.append("actual_rr")

    with open(SIGNALS_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=new_fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(updated_rows)

    # ── Summary statistics ────────────────────────────────────────────────────
    _print_summary(results)


def _print_summary(results: list):
    if not results:
        print("No results to summarize.")
        return

    tradeable = [r for r in results if r["result"] not in ("SKIP", "NO_DATA", "OPEN")]
    wins_t1   = [r for r in tradeable if r["result"] == "WIN_T1"]
    wins_t2   = [r for r in tradeable if r["result"] == "WIN_T2"]
    losses    = [r for r in tradeable if r["result"] == "LOSS"]
    total     = len(tradeable)

    win_rate  = round((len(wins_t1) + len(wins_t2)) / total * 100, 1) if total else 0
    avg_rr    = round(sum(r["actual_rr"] for r in tradeable) / total, 2) if total else 0
    best_rr   = max((r["actual_rr"] for r in tradeable), default=0)
    worst_rr  = min((r["actual_rr"] for r in tradeable), default=0)

    # Max drawdown: consecutive losses
    max_dd   = 0
    cur_dd   = 0
    for r in tradeable:
        if r["result"] == "LOSS":
            cur_dd += 1
            max_dd = max(max_dd, cur_dd)
        else:
            cur_dd = 0

    # Setup breakdown
    setup_counts: dict = {}
    for r in results:
        sym = r.get("symbol", "?")
        dir_ = r.get("direction", "?")
        key = f"{sym} {dir_}"
        if key not in setup_counts:
            setup_counts[key] = {"total": 0, "wins": 0}
        setup_counts[key]["total"] += 1
        if r["result"] in ("WIN_T1", "WIN_T2"):
            setup_counts[key]["wins"] += 1

    print(f"\n{'='*55}")
    print(f"  BACKTEST SUMMARY")
    print(f"{'='*55}")
    print(f"  Total signals tested : {len(results)}")
    print(f"  Tradeable (closed)   : {total}")
    print(f"  WIN (T1)             : {len(wins_t1)}")
    print(f"  WIN (T2)             : {len(wins_t2)}")
    print(f"  LOSS                 : {len(losses)}")
    print(f"  OPEN / No data       : {len(results) - total}")
    print(f"  ─────────────────────────────────────────────")
    print(f"  Win Rate             : {win_rate}%")
    print(f"  Avg Actual R:R       : {avg_rr}")
    print(f"  Best R:R             : {best_rr}")
    print(f"  Worst R:R            : {worst_rr}")
    print(f"  Max Consecutive Loss : {max_dd}")
    print(f"  ─────────────────────────────────────────────")
    print(f"  Setup Breakdown:")
    for setup, data in setup_counts.items():
        wr = round(data["wins"] / data["total"] * 100, 1) if data["total"] else 0
        print(f"    {setup:30s}  {data['wins']}/{data['total']}  ({wr}% win)")
    print(f"{'='*55}\n")
    print("  ✅ Results written back to signals_history.csv")


# ─── CLI entry ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    parser = argparse.ArgumentParser(description="Backtest A+ signals from signals_history.csv")
    parser.add_argument("--last",        type=int, default=None, help="Only backtest the last N signals")
    parser.add_argument("--show-trades", action="store_true",    help="Print per-trade details")
    args = parser.parse_args()

    run_backtest(limit=args.last, verbose=args.show_trades)
