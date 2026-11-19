from datetime import datetime

class OIAnalyzer:
    """
    Derivatives Analytics & Gamma Exposure Engine:
    1. Institutional Build-up Classification (Long/Short build-up, covering, unwinding).
    2. Option Walls (Call Wall, Put Wall, 2nd Wall).
    3. Gamma Exposure (Gamma + Wall, Gamma - Wall, Zero-Gamma Level, GEX Regime).
    4. Wall Shift & Pinning Zone alerts.
    """

    @staticmethod
    def classify_oi_buildup(prev_price: float, curr_price: float, prev_oi: int, curr_oi: int, 
                            symbol: str = "NSE:NIFTY-I", timeframe: str = "5m") -> dict:
        """
        Classifies institutional build-up and formats the message matching Telegram screenshots.
        """
        price_diff = curr_price - prev_price
        price_pct = (price_diff / prev_price) * 100 if prev_price > 0 else 0.0
        
        oi_diff = curr_oi - prev_oi
        oi_pct = (oi_diff / prev_oi) * 100 if prev_oi > 0 else 0.0

        if price_diff > 0 and oi_diff > 0:
            classification = "LONG BUILD-UP"
            icon = "📈"
            meaning = "fresh buying - new longs entering"
            sentiment = "BULLISH"
        elif price_diff < 0 and oi_diff > 0:
            classification = "SHORT BUILD-UP"
            icon = "📉"
            meaning = "fresh selling - new shorts entering"
            sentiment = "BEARISH"
        elif price_diff > 0 and oi_diff < 0:
            classification = "SHORT COVERING"
            icon = "📈"
            meaning = "shorts exiting - rally may fade once covering ends"
            sentiment = "BULLISH"
        elif price_diff < 0 and oi_diff < 0:
            classification = "LONG UNWINDING"
            icon = "📉"
            meaning = "longs exiting - profit taking / weakness"
            sentiment = "BEARISH"
        else:
            return {"classification": "NEUTRAL", "formatted_message": None}

        formatted = (
            f"{icon} {classification}\n"
            f"Symbol : {symbol}\n"
            f"Time   : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"Price  : {curr_price:,.2f} ({price_pct:+.2f}% in {timeframe})\n"
            f"OI     : {curr_oi/1_000_000:.2f}M ({oi_pct:+.2f}% in {timeframe})\n"
            f"Meaning : {meaning}"
        )

        return {
            "classification": classification,
            "sentiment": sentiment,
            "price_diff": price_diff,
            "oi_diff": oi_diff,
            "formatted_message": formatted
        }

    @staticmethod
    def format_levels_report(symbol: str, spot_price: float, call_wall: float, call_oi: float,
                             second_call_wall: float, put_wall: float, put_oi: float, second_put_wall: float,
                             max_pain: float, pcr: float, gamma_plus: float, gamma_minus: float,
                             zero_gamma: float, gex_regime: str = "POSITIVE - pinning / mean reversion") -> str:
        """
        Formats the full LEVELS snapshot matching Telegram screenshot format.
        """
        now_str = datetime.now().strftime("%H:%M:%S")
        report = (
            f"📍 LEVELS\n"
            f"{symbol} spot {spot_price:,.2f} ({now_str})\n"
            f"Call wall   : {call_wall:,.0f}  OI {call_oi/1_000_000:.2f}M | 2nd {second_call_wall:,.0f}\n"
            f"Put wall    : {put_wall:,.0f}  OI {put_oi/1_000_000:.2f}M | 2nd {second_put_wall:,.0f}\n"
            f"Max pain    : {max_pain:,.0f}     PCR {pcr:.2f}\n"
            f"Gamma + wall: {gamma_plus:,.0f}\n"
            f"Gamma - wall: {gamma_minus:,.0f}\n"
            f"Zero-gamma  : ~{zero_gamma:,.2f} (spot {'below' if spot_price < zero_gamma else 'above'})\n"
            f"GEX regime  : {gex_regime}\n"
        )
        return report

    @staticmethod
    def check_gamma_pinning_warning(symbol: str, spot_price: float, gamma_wall: float) -> str | None:
        """
        Issues pinning warning when price approaches Gamma + wall (as seen in Image 12).
        """
        if abs(spot_price - gamma_wall) <= 25.0:
            return (
                f"⚠️ {symbol} {spot_price:.1f} is near Gamma + wall {gamma_wall:,.0f}\n"
                f"pinning zone - price tends to stall / mean-revert"
            )
        return None

    @staticmethod
    def format_wall_shift(symbol: str, spot_price: float, wall_type: str, old_strike: float, new_strike: float) -> str:
        """
        Formats WALL SHIFT alert (as seen in Image 6).
        """
        return (
            f"🧱 WALL SHIFT {symbol} (spot {spot_price:,.1f})\n"
            f"{wall_type} - wall: {old_strike:,.0f} -> {new_strike:,.0f}"
        )
