import os
import csv
from datetime import datetime
import logging

logger = logging.getLogger("TradeLogger")

class SignalLogger:
    """
    Logs every generated trading setup to CSV to track historical accuracy,
    win rates, and performance statistics over time.
    """

    FILE_PATH = "signals_history.csv"
    HEADERS = [
        "timestamp", "symbol", "direction", "setup_type", "confluence_score",
        "entry_price", "stop_loss", "target_1", "target_2", "risk_reward", "status"
    ]

    def __init__(self, file_path: str = None):
        self.file_path = file_path or self.FILE_PATH
        self._ensure_file()

    def _ensure_file(self):
        if not os.path.exists(self.file_path):
            try:
                with open(self.file_path, mode="w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow(self.HEADERS)
            except Exception as e:
                logger.error(f"Failed to initialize signals CSV: {e}")

    def log_trade(self, symbol: str, direction: str, setup_type: str, score: int,
                  entry: float, sl: float, t1: float, t2: float, rr: str) -> bool:
        """
        Appends a newly triggered setup to signals_history.csv.
        """
        row = [
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            symbol,
            direction,
            setup_type,
            score,
            round(entry, 2),
            round(sl, 2),
            round(t1, 2),
            round(t2, 2),
            rr,
            "OPEN"
        ]
        try:
            with open(self.file_path, mode="a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(row)
            return True
        except Exception as e:
            logger.error(f"Error logging trade to CSV: {e}")
            return False
