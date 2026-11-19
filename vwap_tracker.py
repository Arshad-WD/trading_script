import math
from datetime import datetime, date

class VWAPTracker:
    """
    Intraday Volume-Weighted Average Price (VWAP) Tracker
    with Standard Deviation Bands (+1σ, +2σ, -1σ, -2σ).
    Resets automatically on a new trading date.
    """

    def __init__(self, symbol: str):
        self.symbol = symbol
        self.current_date: date | None = None
        self.cum_pv: float = 0.0      # Sum of (Price * Volume)
        self.cum_p2v: float = 0.0     # Sum of (Price^2 * Volume) for StdDev
        self.cum_vol: int = 0         # Sum of Volume
        self.last_price: float = 0.0
        self.last_tick_time: datetime | None = None

    def reset(self, new_date: date):
        self.current_date = new_date
        self.cum_pv = 0.0
        self.cum_p2v = 0.0
        self.cum_vol = 0
        self.last_price = 0.0

    def update(self, timestamp: datetime, price: float, volume: int) -> dict:
        """
        Update VWAP with a newly traded price and incremental volume.
        Returns dictionary with current VWAP and SD bands.
        """
        tick_date = timestamp.date()
        if self.current_date != tick_date:
            self.reset(tick_date)

        if volume <= 0 or price <= 0:
            return self.get_state()

        self.cum_pv += price * volume
        self.cum_p2v += (price ** 2) * volume
        self.cum_vol += volume
        self.last_price = price
        self.last_tick_time = timestamp

        return self.get_state()

    def get_state(self) -> dict:
        if self.cum_vol == 0:
            return {
                "symbol": self.symbol,
                "price": self.last_price,
                "vwap": self.last_price,
                "vwap_upper_1sd": self.last_price,
                "vwap_lower_1sd": self.last_price,
                "vwap_upper_2sd": self.last_price,
                "vwap_lower_2sd": self.last_price,
                "total_volume": 0,
                "trend": "NEUTRAL"
            }

        vwap = self.cum_pv / self.cum_vol
        
        # Variance = E[P^2] - (E[P])^2
        variance = (self.cum_p2v / self.cum_vol) - (vwap ** 2)
        std_dev = math.sqrt(max(0.0, variance))

        trend = "BULLISH" if self.last_price > vwap else "BEARISH" if self.last_price < vwap else "NEUTRAL"

        return {
            "symbol": self.symbol,
            "price": round(self.last_price, 2),
            "vwap": round(vwap, 2),
            "vwap_upper_1sd": round(vwap + std_dev, 2),
            "vwap_lower_1sd": round(vwap - std_dev, 2),
            "vwap_upper_2sd": round(vwap + (2 * std_dev), 2),
            "vwap_lower_2sd": round(vwap - (2 * std_dev), 2),
            "total_volume": self.cum_vol,
            "trend": trend
        }
