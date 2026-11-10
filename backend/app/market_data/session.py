"""India cash/F&O market-session helper for feed-health evaluation."""
from datetime import datetime, time
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def nse_regular_session_active(now: datetime | None = None) -> bool:
    current = (now or datetime.now(IST)).astimezone(IST)
    if current.weekday() >= 5:
        return False
    return time(9, 15) <= current.time().replace(tzinfo=None) <= time(15, 30)
