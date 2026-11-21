"""
position_sizer.py
─────────────────
Calculates proper F&O lot size and capital at risk before each trade.

Indian F&O rules:
  - Nifty 50 lot size    : 25 (as of late 2026)
  - Bank Nifty lot size  : 15
  - Max risk per trade   : user-configurable (default 1% of capital)
  - Max lots per trade   : configurable cap (default 3 lots)

Usage:
    from position_sizer import PositionSizer
    sizing = PositionSizer(account_capital=500000, risk_pct=1.0)
    result = sizing.calculate("NIFTY", entry=24950, sl=24910)
    print(result["formatted_message"])
"""

import os
from dotenv import load_dotenv

load_dotenv()

# Lot sizes per instrument (NSE circular)
LOT_SIZES = {
    "NIFTY":    25,
    "BANKNIFTY": 15,
    "FINNIFTY":  40,
}

# Default account size if not set in .env
DEFAULT_CAPITAL   = 500_000   # ₹5 lakhs
DEFAULT_RISK_PCT  = 1.0       # 1% per trade
DEFAULT_MAX_LOTS  = 3


class PositionSizer:

    def __init__(
        self,
        account_capital: float = None,
        risk_pct: float = None,
        max_lots: int = None
    ):
        self.capital   = account_capital or float(os.getenv("ACCOUNT_CAPITAL", DEFAULT_CAPITAL))
        self.risk_pct  = risk_pct        or float(os.getenv("RISK_PCT_PER_TRADE", DEFAULT_RISK_PCT))
        self.max_lots  = max_lots        or int(os.getenv("MAX_LOTS_PER_TRADE",   DEFAULT_MAX_LOTS))

    def calculate(self, symbol: str, entry: float, sl: float) -> dict:
        """
        Returns lot size, capital at risk, and a formatted summary.

        Args:
            symbol : "NIFTY" or "BANKNIFTY"
            entry  : entry price (index points)
            sl     : stop-loss price (index points)

        Returns dict with keys:
            lots, lot_size, risk_per_lot, total_risk, capital_pct,
            margin_estimate, formatted_message
        """
        symbol_upper = symbol.upper().replace(" ", "")
        lot_size     = LOT_SIZES.get(symbol_upper, LOT_SIZES["NIFTY"])

        risk_per_point = abs(entry - sl)
        if risk_per_point <= 0:
            return self._empty_result(symbol, "Entry == SL — cannot size position.")

        risk_per_lot   = risk_per_point * lot_size
        max_risk_rupees = self.capital * (self.risk_pct / 100.0)

        # Ideal lots based on risk budget
        ideal_lots = int(max_risk_rupees / risk_per_lot)
        lots = max(1, min(ideal_lots, self.max_lots))

        total_risk    = lots * risk_per_lot
        capital_pct   = round((total_risk / self.capital) * 100, 2)

        # Approximate SPAN margin (Nifty futures ≈ ₹55,000/lot; options premium varies)
        margin_estimate = lots * lot_size * entry * 0.085   # ~8.5% of notional (rough SPAN)

        status = "✅ OK"
        if capital_pct > self.risk_pct * 1.1:
            status = "⚠️ Slightly over risk limit"
        if lots == 0:
            status = "🚫 Risk too high — skip this trade"
            lots = 0

        formatted = (
            f"📐 POSITION SIZING — {symbol}\n"
            f"Account Capital  : ₹{self.capital:,.0f}\n"
            f"Risk per Trade   : {self.risk_pct}% = ₹{max_risk_rupees:,.0f}\n"
            f"Entry            : {entry}\n"
            f"Stop-Loss        : {sl}  (risk {risk_per_point:.1f} pts)\n"
            f"─────────────────────────────\n"
            f"Lot Size         : {lot_size} units\n"
            f"Risk per Lot     : ₹{risk_per_lot:,.0f}\n"
            f"Recommended Lots : {lots}\n"
            f"Total Risk       : ₹{total_risk:,.0f} ({capital_pct}% of capital)\n"
            f"Margin Required  : ~₹{margin_estimate:,.0f}\n"
            f"Status           : {status}"
        )

        return {
            "symbol":           symbol,
            "lots":             lots,
            "lot_size":         lot_size,
            "risk_per_lot":     risk_per_lot,
            "total_risk":       total_risk,
            "capital_pct":      capital_pct,
            "margin_estimate":  margin_estimate,
            "status":           status,
            "formatted_message": formatted,
        }

    def _empty_result(self, symbol: str, reason: str) -> dict:
        return {
            "symbol": symbol, "lots": 0, "lot_size": 0,
            "risk_per_lot": 0, "total_risk": 0, "capital_pct": 0,
            "margin_estimate": 0, "status": f"ERROR: {reason}",
            "formatted_message": f"❌ Position sizing error: {reason}"
        }


if __name__ == "__main__":
    sizer = PositionSizer(account_capital=500_000, risk_pct=1.0, max_lots=3)

    print("\n--- NIFTY LONG ---")
    r = sizer.calculate("NIFTY", entry=24950.0, sl=24910.0)
    print(r["formatted_message"])

    print("\n--- BANKNIFTY SHORT ---")
    r = sizer.calculate("BANKNIFTY", entry=52000.0, sl=52080.0)
    print(r["formatted_message"])
