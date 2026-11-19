class LeadLagMonitor:
    """
    Monitors BankNifty and Nifty co-movement, intraday relative strength,
    and lead-lag signals to trade Nifty based on BankNifty momentum.
    """

    def __init__(self, divergence_threshold_pct: float = 0.25):
        self.divergence_threshold = divergence_threshold_pct
        self.nifty_open = 0.0
        self.banknifty_open = 0.0
        self.last_nifty = 0.0
        self.last_banknifty = 0.0
        self.nifty_vwap = 0.0
        self.banknifty_vwap = 0.0

    def set_day_open(self, nifty_open: float, banknifty_open: float):
        self.nifty_open = nifty_open
        self.banknifty_open = banknifty_open

    def update(self, nifty_price: float, nifty_vwap: float, banknifty_price: float, banknifty_vwap: float) -> dict:
        self.last_nifty = nifty_price
        self.nifty_vwap = nifty_vwap
        self.last_banknifty = banknifty_price
        self.banknifty_vwap = banknifty_vwap

        # If day open is not explicitly set, initialize with first ticks
        if self.nifty_open <= 0:
            self.nifty_open = nifty_price
        if self.banknifty_open <= 0:
            self.banknifty_open = banknifty_price

        # Percentage change from open
        nifty_pct = ((nifty_price - self.nifty_open) / self.nifty_open) * 100 if self.nifty_open > 0 else 0.0
        bn_pct = ((banknifty_price - self.banknifty_open) / self.banknifty_open) * 100 if self.banknifty_open > 0 else 0.0

        spread = bn_pct - nifty_pct  # positive when BankNifty is outperforming

        # VWAP status
        nifty_above_vwap = nifty_price > nifty_vwap
        bn_above_vwap = banknifty_price > banknifty_vwap

        signal = "NEUTRAL"
        action = "WAIT"

        # Signal Logic: BankNifty surging above VWAP while Nifty is lagging
        if bn_above_vwap and spread > self.divergence_threshold:
            if not nifty_above_vwap:
                signal = "BANKNIFTY_LEADING_BULLISH"
                action = "LOOK FOR NIFTY CALL / LONG (Catch-up setup)"
            else:
                signal = "BULLISH_SYNC"
                action = "STRONG BULLISH MOMENTUM"
        elif not bn_above_vwap and spread < -self.divergence_threshold:
            if nifty_above_vwap:
                signal = "BANKNIFTY_LEADING_BEARISH"
                action = "LOOK FOR NIFTY PUT / SHORT (Drag-down setup)"
            else:
                signal = "BEARISH_SYNC"
                action = "STRONG BEARISH MOMENTUM"
        elif (bn_above_vwap and not nifty_above_vwap) or (not bn_above_vwap and nifty_above_vwap):
            signal = "DIVERGENT"
            action = "CHOPPY / CAUTION (Indices conflicting)"
        else:
            signal = "SYNCHRONIZED"
            action = "RANGE / NORMAL MOVEMENT"

        return {
            "nifty_price": round(nifty_price, 2),
            "banknifty_price": round(banknifty_price, 2),
            "nifty_pct_chg": round(nifty_pct, 2),
            "banknifty_pct_chg": round(bn_pct, 2),
            "spread_pct": round(spread, 2),
            "banknifty_leads": abs(spread) >= self.divergence_threshold,
            "signal": signal,
            "action_recommendation": action
        }
