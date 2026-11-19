import logging
from datetime import datetime, timezone
import requests
from dateutil import parser as dt_parser

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("NewsFeed")

class ForexFactoryCalendar:
    """
    Fetches real-time macroeconomic event calendar from ForexFactory's official feed.
    Filters for High Impact ('Red Folder') events (e.g., Fed Rates, CPI, GDP, NFP).
    """

    FEED_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

    def __init__(self, target_currencies: list = None):
        # High-impact news in USD, INR, EUR, GBP heavily moves Indian indices
        self.target_currencies = target_currencies or ["USD", "INR", "EUR", "GBP"]
        self.events = []
        self.last_fetch = None

    def fetch_calendar(self) -> list[dict]:
        """
        Fetches this week's economic events from ForexFactory.
        """
        try:
            res = requests.get(self.FEED_URL, timeout=8)
            if res.status_code == 200:
                self.events = res.json()
                self.last_fetch = datetime.now()
                logger.info(f"Successfully fetched {len(self.events)} economic events from ForexFactory.")
                return self.events
            else:
                logger.warning(f"ForexFactory calendar request returned status code: {res.status_code}")
                return []
        except Exception as e:
            logger.error(f"Error fetching ForexFactory calendar: {e}")
            return []

    def get_upcoming_high_impact(self, hours_ahead: int = 12) -> list[dict]:
        """
        Returns high-impact events scheduled within the next `hours_ahead` hours.
        """
        if not self.events:
            self.fetch_calendar()

        now = datetime.now(timezone.utc)
        upcoming = []

        for item in self.events:
            if item.get("impact") != "High":
                continue
            if item.get("country") not in self.target_currencies:
                continue

            try:
                event_time = dt_parser.parse(item.get("date"))
                # Difference in hours
                diff_hours = (event_time - now).total_seconds() / 3600.0

                if -1.0 <= diff_hours <= hours_ahead:
                    # Convert to local IST string
                    ist_time = event_time.astimezone()
                    upcoming.append({
                        "title": item.get("title"),
                        "country": item.get("country"),
                        "time_ist": ist_time.strftime("%d-%b %I:%M %p IST"),
                        "impact": item.get("impact"),
                        "forecast": item.get("forecast", "-"),
                        "previous": item.get("previous", "-"),
                        "diff_minutes": int(diff_hours * 60)
                    })
            except Exception as e:
                continue

        return upcoming
