"""
market_hours.py
───────────────
Centralised market hours guard for Indian F&O (NSE/NFO).
All timing logic lives here — no scattered datetime checks across files.

Trading calendar:
  - Market Open  : 09:15 IST
  - Market Close : 15:30 IST
  - Pre-open     : 09:00 – 09:14 (order collection, no signals)
  - Opening noise: 09:15 – 09:24 (wild spreads, signals penalised)
  - Prime window : 09:30 – 11:30 and 13:30 – 15:15
  - Lunch chop   : 11:45 – 13:15 (low volume, signals penalised)
  - Power hour   : 14:45 – 15:30 (high volume expiry moves)
  - Closed       : Weekends and national holidays (basic list)

Usage:
    from market_hours import MarketHours
    if not MarketHours.is_market_open():
        # skip tick processing
"""

from datetime import datetime, time, date, timezone, timedelta
try:
    from zoneinfo import ZoneInfo
    IST = ZoneInfo("Asia/Kolkata")
except Exception:
    IST = timezone(timedelta(hours=5, minutes=30))

# NSE declared holidays 2026 (add more as announced)
NSE_HOLIDAYS_2026 = {
    date(2026, 1, 26),   # Republic Day
    date(2026, 3, 25),   # Holi
    date(2026, 4, 2),    # Ram Navami / Good Friday region
    date(2026, 4, 14),   # Dr Ambedkar Jayanti
    date(2026, 5, 1),    # Maharashtra Day
    date(2026, 8, 15),   # Independence Day
    date(2026, 10, 2),   # Gandhi Jayanti
    date(2026, 11, 4),   # Diwali Laxmi Puja (eve)
    date(2026, 11, 5),   # Diwali (Balipratipada)
    date(2026, 12, 25),  # Christmas
}

MARKET_OPEN  = time(9, 15)
MARKET_CLOSE = time(15, 30)

# MCX Commodity Market Hours (09:00 AM to 11:30 PM IST)
MCX_OPEN  = time(9, 0)
MCX_CLOSE = time(23, 30)


class MarketHours:

    @staticmethod
    def now_ist() -> datetime:
        return datetime.now(IST)

    @staticmethod
    def is_holiday(d: date = None) -> bool:
        d = d or MarketHours.now_ist().date()
        return d in NSE_HOLIDAYS_2026

    @staticmethod
    def is_weekend(d: date = None) -> bool:
        d = d or MarketHours.now_ist().date()
        return d.weekday() >= 5   # 5=Sat, 6=Sun

    @staticmethod
    def is_market_open(now: datetime = None, exchange: str = "NSE") -> bool:
        """Returns True if market is currently open for trading (NSE or MCX)."""
        now = now or MarketHours.now_ist()
        d = now.date()
        t = now.time()
        if MarketHours.is_weekend(d) or MarketHours.is_holiday(d):
            return False
        if exchange.upper() == "MCX":
            return MCX_OPEN <= t <= MCX_CLOSE
        return MARKET_OPEN <= t <= MARKET_CLOSE

    @staticmethod
    def is_pre_open(now: datetime = None) -> bool:
        """09:00–09:14 — order matching, no signals."""
        now = now or MarketHours.now_ist()
        return time(9, 0) <= now.time() < MARKET_OPEN

    @staticmethod
    def is_opening_noise(now: datetime = None) -> bool:
        """09:15–09:24 — wild spreads, penalise signals."""
        now = now or MarketHours.now_ist()
        return MARKET_OPEN <= now.time() <= time(9, 24)

    @staticmethod
    def is_lunch_chop(now: datetime = None) -> bool:
        """11:45–13:15 — low volume, penalise signals."""
        now = now or MarketHours.now_ist()
        return time(11, 45) <= now.time() <= time(13, 15)

    @staticmethod
    def is_prime_window(now: datetime = None) -> bool:
        """09:30–11:30 or 13:30–15:15 — highest institutional activity."""
        now = now or MarketHours.now_ist()
        t = now.time()
        return (time(9, 30) <= t <= time(11, 30)) or (time(13, 30) <= t <= time(15, 15))

    @staticmethod
    def is_power_hour(now: datetime = None) -> bool:
        """14:45–15:30 — expiry/EOD moves."""
        now = now or MarketHours.now_ist()
        return time(14, 45) <= now.time() <= MARKET_CLOSE

    @staticmethod
    def session_phase(now: datetime = None, exchange: str = "NSE") -> str:
        """Human-readable phase name for logging."""
        now = now or MarketHours.now_ist()
        if not MarketHours.is_market_open(now, exchange=exchange):
            return "CLOSED"
        if exchange.upper() == "MCX":
            t = now.time()
            if time(18, 30) <= t <= time(22, 30):
                return "US_NYMEX_PEAK_HOURS"
            return "MCX_COMMODITY_ACTIVE"
        if MarketHours.is_opening_noise(now):
            return "OPENING_NOISE"
        if MarketHours.is_lunch_chop(now):
            return "LUNCH_CHOP"
        if MarketHours.is_power_hour(now):
            return "POWER_HOUR"
        if MarketHours.is_prime_window(now):
            return "PRIME_WINDOW"
        return "NORMAL"

    @staticmethod
    def seconds_to_open(exchange: str = "NSE") -> int:
        """Returns seconds until next market open (0 if already open)."""
        now = MarketHours.now_ist()
        if MarketHours.is_market_open(now, exchange=exchange):
            return 0
        open_time = MCX_OPEN if exchange.upper() == "MCX" else MARKET_OPEN
        today_open = now.replace(hour=open_time.hour, minute=open_time.minute, second=0, microsecond=0)
        if now < today_open and not MarketHours.is_weekend() and not MarketHours.is_holiday():
            return int((today_open - now).total_seconds())
        # Tomorrow
        from datetime import timedelta
        next_day = now + timedelta(days=1)
        while MarketHours.is_weekend(next_day.date()) or MarketHours.is_holiday(next_day.date()):
            next_day += timedelta(days=1)
        next_open = next_day.replace(hour=open_time.hour, minute=open_time.minute, second=0, microsecond=0)
        return int((next_open - now).total_seconds())


if __name__ == "__main__":
    mh = MarketHours()
    print(f"Current IST       : {mh.now_ist().strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"Market Open       : {mh.is_market_open()}")
    print(f"Session Phase     : {mh.session_phase()}")
    print(f"Seconds to Open   : {mh.seconds_to_open()}")
