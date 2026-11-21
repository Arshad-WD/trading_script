from datetime import datetime, time, timedelta
from market_hours import MarketHours
from position_sizer import PositionSizer


class ConfluenceEngine:
    """
    Institutional Confluence & Quality Scoring Engine:
    Filters out low-probability noise and grades trading setups (A+, B, or Avoid).

    Scoring Model (0 to 100 Points):
    1. Key Level / Wall Proximity: 25 Points
    2. Order Flow Absorption / Whale Confirmation: 25 Points
    3. VWAP Band Stretch / Mean Reversion: 25 Points
    4. BankNifty Lead-Lag Alignment: 25 Points
    5. Higher Timeframe (15M) Macro Trend Alignment: +15 Bonus / -20 Penalty
    6. Time-of-Day Filter Penalty: -15 Points during low-volume lunch chop / noise
    """

    MIN_A_PLUS_SCORE = 75
    _last_signal_time = {}

    @classmethod
    def evaluate_setup(cls, current_price: float, symbol: str,
                       vwap_state: dict, levels: dict,
                       whale_alert: dict | None, lead_lag_state: dict,
                       timestamp: datetime | None = None,
                       cooldown_minutes: int = 3,
                       mtf_state: dict | None = None,
                       is_simulated: bool = False) -> dict | None:
        if timestamp is None:
            timestamp = datetime.now()

        # ── 0. Market Hours Guard ─────────────────────────────────────────────
        if not is_simulated and not MarketHours.is_market_open(timestamp):
            return None

        # ── Cooldown Check ────────────────────────────────────────────────────
        last_time = cls._last_signal_time.get(symbol)
        if last_time and (timestamp - last_time).total_seconds() < (cooldown_minutes * 60):
            return None

        score = 0
        factors = []
        direction = "NEUTRAL"

        call_wall = levels.get("call_wall", 0.0)
        put_wall = levels.get("put_wall", 0.0)
        vwap = vwap_state.get("vwap", current_price)
        upper_1sd = vwap_state.get("vwap_upper_1sd", current_price)
        lower_1sd = vwap_state.get("vwap_lower_1sd", current_price)

        # -------------------------------------------------------------
        # 1. Key Level / Wall Proximity Check (25 Pts)
        # -------------------------------------------------------------
        near_call_wall = call_wall > 0 and abs(current_price - call_wall) <= 25.0
        near_put_wall = put_wall > 0 and abs(current_price - put_wall) <= 25.0

        if near_call_wall:
            score += 25
            direction = "SHORT"
            factors.append(f"At Call Wall Resistance ({call_wall:,.0f})")
        elif near_put_wall:
            score += 25
            direction = "LONG"
            factors.append(f"At Put Wall Support ({put_wall:,.0f})")

        # -------------------------------------------------------------
        # 2. Orderflow / Whale Absorption Check (25 Pts)
        # -------------------------------------------------------------
        if whale_alert:
            result = whale_alert.get("result", "")
            bias = whale_alert.get("bias", "")

            if "ABSORBED" in result or bias == "REVERSAL_LIKELY":
                score += 25
                factors.append(f"Volume Absorption ({whale_alert.get('volume', 0):,} lots absorbed)")
                if direction == "NEUTRAL":
                    direction = "SHORT" if current_price > vwap else "LONG"
            elif "REJECTED" in result:
                score += 20
                factors.append("Whale Rejection (aggressive counter-party)")
            elif "BREAKOUT" in result and near_call_wall is False and near_put_wall is False:
                score += 20
                direction = "LONG" if current_price > vwap else "SHORT"
                factors.append("Whale Breakout Momentum")

        # -------------------------------------------------------------
        # 3. VWAP Band Stretch / Mean Reversion (25 Pts)
        # -------------------------------------------------------------
        if direction == "SHORT" and current_price >= upper_1sd:
            score += 25
            factors.append(f"Stretched above +1σ VWAP band ({upper_1sd:.1f})")
        elif direction == "LONG" and current_price <= lower_1sd:
            score += 25
            factors.append(f"Stretched below -1σ VWAP band ({lower_1sd:.1f})")
        elif (direction == "SHORT" and current_price < vwap) or (direction == "LONG" and current_price > vwap):
            score += 15
            factors.append(f"Trending in direction of VWAP ({vwap:.1f})")

        # -------------------------------------------------------------
        # 4. BankNifty Lead-Lag Momentum Check (25 Pts)
        # -------------------------------------------------------------
        signal = lead_lag_state.get("signal", "")
        if direction == "LONG" and signal in ["BANKNIFTY_LEADING_BULLISH", "BULLISH_SYNC"]:
            score += 25
            factors.append("BankNifty surging / leading bullish")
        elif direction == "SHORT" and signal in ["BANKNIFTY_LEADING_BEARISH", "BEARISH_SYNC"]:
            score += 25
            factors.append("BankNifty dragging / leading bearish")
        elif signal == "DIVERGENT":
            score -= 10
            factors.append("Caution: BankNifty & Nifty diverging")

        # -------------------------------------------------------------
        # 5. Multi-Timeframe (15M) Macro Trend Filter (+15 / -20 Pts)
        # -------------------------------------------------------------
        if mtf_state:
            macro_trend = mtf_state.get("trend", "NEUTRAL")
            if direction == "LONG" and macro_trend == "BULLISH":
                score += 15
                factors.append(f"15M Macro Trend Confirmed: BULLISH (EMA: {mtf_state.get('ema_fast')})")
            elif direction == "SHORT" and macro_trend == "BEARISH":
                score += 15
                factors.append(f"15M Macro Trend Confirmed: BEARISH (EMA: {mtf_state.get('ema_fast')})")
            elif direction == "LONG" and macro_trend == "BEARISH":
                score -= 20
                factors.append("Counter-Trend Penalty: Trading LONG against 15M BEARISH trend (-20 pts)")
            elif direction == "SHORT" and macro_trend == "BULLISH":
                score -= 20
                factors.append("Counter-Trend Penalty: Trading SHORT against 15M BULLISH trend (-20 pts)")

        # -------------------------------------------------------------
        # 6. Time-of-Day Filter (Chop penalty / Prime hours bonus)
        # -------------------------------------------------------------
        if MarketHours.is_lunch_chop(timestamp) or MarketHours.is_opening_noise(timestamp):
            score = max(0, score - 15)
            factors.append("Penalty: Low-volume chop / open noise window")
        elif MarketHours.is_prime_window(timestamp):
            score = min(100, score + 5)
            factors.append("Bonus: Prime institutional trading hours")

        score = max(0, min(100, score))

        if score < cls.MIN_A_PLUS_SCORE or direction == "NEUTRAL":
            return None

        # Record signal time for cooldown
        cls._last_signal_time[symbol] = timestamp

        # -------------------------------------------------------------
        # 7. Calculate Invalidation (Stop Loss) and Targets
        # -------------------------------------------------------------
        if direction == "SHORT":
            sl_price = round(max(current_price + 8.0, call_wall + 5.0 if near_call_wall else current_price + 10.0), 2)
            risk = sl_price - current_price
            target_1 = round(vwap if current_price > vwap else current_price - (risk * 2), 2)
            target_2 = round(put_wall if put_wall > 0 and put_wall < current_price else current_price - (risk * 3.5), 2)
        else:
            sl_price = round(min(current_price - 8.0, put_wall - 5.0 if near_put_wall else current_price - 10.0), 2)
            risk = current_price - sl_price
            target_1 = round(vwap if current_price < vwap else current_price + (risk * 2), 2)
            target_2 = round(call_wall if call_wall > 0 and call_wall > current_price else current_price + (risk * 3.5), 2)

        risk = max(1.0, abs(current_price - sl_price))
        reward = abs(target_1 - current_price)
        rr_ratio = f"1 : {reward / risk:.1f}"

        # -------------------------------------------------------------
        # 8. Institutional Position Sizing (Risk Management)
        # -------------------------------------------------------------
        sizer = PositionSizer()
        sizing = sizer.calculate(symbol=symbol, entry=current_price, sl=sl_price)

        grade = "A+ INSTITUTIONAL SETUP"
        icon = "🔥"

        formatted_msg = (
            f"{icon} {grade} (Score: {score}/100)\n"
            f"Asset      : {symbol}\n"
            f"Direction  : {'PUT / SHORT (Reversal)' if direction == 'SHORT' else 'CALL / LONG (Bounce)'}\n"
            f"Entry      : {current_price:.2f}\n"
            f"Stop-Loss  : {sl_price:.2f} (Risk: {risk:.1f} pts)\n"
            f"Target 1   : {target_1:.2f} (Mean Reversion)\n"
            f"Target 2   : {target_2:.2f} (Macro Target)\n"
            f"Risk/Reward: {rr_ratio}\n\n"
            f"📐 Position Sizing (1% Risk Budget):\n"
            f"  • Recommended Lots : {sizing['lots']} ({sizing['lots'] * sizing['lot_size']} Qty)\n"
            f"  • Max Capital Risk : ₹{sizing['total_risk']:,} ({sizing['capital_pct']}% of Capital)\n"
            f"  • Approx Margin    : ~₹{sizing['margin_estimate']:,}\n\n"
            f"Confluence Factors:\n" + "\n".join([f"  • {f}" for f in factors])
        )

        return {
            "symbol": symbol,
            "direction": direction,
            "grade": grade,
            "score": score,
            "entry": current_price,
            "stop_loss": sl_price,
            "target_1": target_1,
            "target_2": target_2,
            "risk_reward": rr_ratio,
            "position_sizing": sizing,
            "formatted_message": formatted_msg
        }
