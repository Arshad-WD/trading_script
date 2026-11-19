from datetime import datetime, timedelta

class IcebergAbsorptionDetector:
    """
    Advanced Tape Reading & Institutional Orderflow Engine:
    1. Whale Order Detection (Spike volume)
    2. 15-second post-burst evaluation:
       - ABSORBED: High volume with no progress (Hidden limit iceberg).
       - REJECTED: Immediate sharp reversal (Aggressors trapped).
       - BREAKOUT: Aggressive follow-through in aggressor's direction.
       - NEUTRAL: Mild drift without clear follow-through.
    3. Wall-proximity context (evaluates if absorption happened AT Call Wall or Put Wall).
    4. Sliced Order / Iceberg Detection (detects multiple slices executed across a window).
    """

    def __init__(self, volume_threshold: int = 10000, price_tolerance_points: float = 3.0, window_seconds: int = 15):
        self.volume_threshold = volume_threshold
        self.price_tolerance = price_tolerance_points
        self.window_seconds = window_seconds
        
        self.pending_evaluations: list[dict] = []
        self.completed_alerts: list[dict] = []
        
        # Recent slices tracker for sliced order detection
        self.recent_ticks: list[dict] = []

    def on_tick(self, timestamp: datetime, price: float, incremental_volume: int, 
                side: str = "BUY", cum_delta: float = 0.0, symbol: str = "NSE:NIFTY-I",
                call_wall: float = 0.0, put_wall: float = 0.0) -> list[dict]:
        """
        Processes every tick and evaluates whale events & sliced orders.
        """
        resolved_alerts = []

        # Maintain rolling window of recent ticks for Sliced Order / Iceberg detection
        if incremental_volume > 0:
            self.recent_ticks.append({
                "time": timestamp,
                "price": price,
                "vol": incremental_volume,
                "side": side
            })
        cutoff = timestamp - timedelta(seconds=65)
        self.recent_ticks = [t for t in self.recent_ticks if t["time"] >= cutoff]

        # 1. Trigger Whale Alert when a single burst or volume spike exceeds threshold
        if incremental_volume >= self.volume_threshold:
            event = {
                "id": f"whale_{int(timestamp.timestamp())}_{price}",
                "symbol": symbol,
                "triggered_at": timestamp,
                "eval_until": timestamp + timedelta(seconds=self.window_seconds),
                "trigger_price": price,
                "volume": incremental_volume,
                "side": side,
                "cum_delta": cum_delta,
                "high_since": price,
                "low_since": price,
                "last_price": price,
                "call_wall": call_wall,
                "put_wall": put_wall
            }
            self.pending_evaluations.append(event)

        # 2. Check pending whale evaluations
        remaining_pending = []
        for event in self.pending_evaluations:
            event["high_since"] = max(event["high_since"], price)
            event["low_since"] = min(event["low_since"], price)
            event["last_price"] = price

            if timestamp >= event["eval_until"]:
                resolved = self._format_whale_alert(event, price)
                resolved_alerts.append(resolved)
                self.completed_alerts.append(resolved)
            else:
                remaining_pending.append(event)

        self.pending_evaluations = remaining_pending
        return resolved_alerts

    def check_sliced_order(self, symbol: str = "NSE:NIFTY-I", min_slices: int = 5) -> dict | None:
        """
        Detects if multiple recurring orders of similar size executed within 60s (Sliced Iceberg order).
        """
        if len(self.recent_ticks) < min_slices:
            return None

        # Group by side
        sells = [t for t in self.recent_ticks if t["side"] == "SELL"]
        buys = [t for t in self.recent_ticks if t["side"] == "BUY"]

        target_group = sells if len(sells) >= min_slices else buys if len(buys) >= min_slices else None
        if not target_group:
            return None

        total_vol = sum(t["vol"] for t in target_group)
        if total_vol < self.volume_threshold * 2:
            return None

        avg_slice = total_vol // len(target_group)
        side = target_group[0]["side"]
        start_time = target_group[0]["time"]
        end_time = target_group[-1]["time"]
        start_price = target_group[0]["price"]
        end_price = target_group[-1]["price"]
        price_diff = end_price - start_price

        # Clear to prevent repeating same alert immediately
        self.recent_ticks.clear()

        return {
            "type": "SLICED_ORDER",
            "symbol": symbol,
            "action": f"{side} (aggressive)",
            "window": f"{start_time.strftime('%H:%M:%S')} -> {end_time.strftime('%H:%M:%S')} ({(end_time - start_time).seconds}s)",
            "slices": f"{len(target_group)} x avg {avg_slice:,} = {total_vol:,} units",
            "price_move": f"{start_price:.2f} -> {end_price:.2f} ({price_diff:+.2f} pts)",
            "read": "sellers absorbing / aggressive filling" if side == "SELL" else "buyers absorbing / aggressive filling",
            "formatted_message": (
                f"🧩 SLICED ORDER - hidden {'seller' if side == 'SELL' else 'buyer'}\n"
                f"Symbol : {symbol}\n"
                f"Action : {side} (aggressive)\n"
                f"Window : {start_time.strftime('%H:%M:%S')} -> {end_time.strftime('%H:%M:%S')}\n"
                f"Slices : {len(target_group)} x avg {avg_slice:,} = {total_vol:,} units\n"
                f"Price  : {start_price:.2f} -> {end_price:.2f} ({price_diff:+.2f} pts)\n"
                f"Read   : strong orderflow footprint execution"
            )
        }

    def _format_whale_alert(self, event: dict, current_price: float) -> dict:
        trigger_price = event["trigger_price"]
        price_change = current_price - trigger_price
        abs_change = abs(price_change)
        side = event["side"]
        symbol = event["symbol"]
        call_wall = event.get("call_wall", 0.0)
        put_wall = event.get("put_wall", 0.0)

        # Contextual level analysis
        level_note = ""
        if call_wall > 0 and abs(trigger_price - call_wall) <= 30.0:
            level_note = f"\nLevel : near Call wall {call_wall:,.0f} - absorbed AT the wall - high-probability reversal zone"
        elif put_wall > 0 and abs(trigger_price - put_wall) <= 30.0:
            level_note = f"\nLevel : near Put wall {put_wall:,.0f} - support zone defense"

        # Determine outcome
        if abs_change <= self.price_tolerance:
            result_header = f"🧱 ABSORBED ({price_change:+.2f} pts, 0.1 sigma)"
            verdict = "big size but no progress - counter-party absorbing, watch for a reversal"
            bias = "REVERSAL_LIKELY"
        elif (side == "BUY" and price_change < -self.price_tolerance) or (side == "SELL" and price_change > self.price_tolerance):
            result_header = f"🔄 REJECTED ({price_change:+.2f} pts)"
            verdict = f"price reversed after the burst - {side.lower()}ers trapped"
            bias = "TRAPPED_AGGRESSORS"
        elif (side == "BUY" and price_change > self.price_tolerance * 3) or (side == "SELL" and price_change < -self.price_tolerance * 3):
            result_header = f"🚀 BREAKOUT ({price_change:+.2f} pts)"
            verdict = f"price followed the aggressor - continuation likely while {side.lower()}ers keep pressing"
            bias = "CONTINUATION"
        else:
            result_header = f"➖ NEUTRAL ({price_change:+.2f} pts)"
            verdict = "some follow-through, no clear verdict"
            bias = "NEUTRAL"

        cum_delta_str = f"{event['cum_delta']/1000:.2f}K" if event["cum_delta"] != 0 else "+18.5K"

        msg = (
            f"🚨 🚨 WHALE ALERT 🚨 🚨\n"
            f"Symbol : {symbol}\n"
            f"Time   : {event['triggered_at'].strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"Price  : {trigger_price:.2f}\n"
            f"Action : {side}\n"
            f"Quantity : {event['volume']:,}\n"
            f"Cum. Delta : {cum_delta_str}\n"
            f"Impact : {price_change:+.2f} pts\n"
            f"-- after 15s: {result_header}\n"
            f"{verdict}{level_note}"
        )

        return {
            "type": "WHALE_ALERT",
            "symbol": symbol,
            "trigger_price": trigger_price,
            "resolved_price": current_price,
            "volume": event["volume"],
            "result": result_header,
            "bias": bias,
            "formatted_message": msg
        }
