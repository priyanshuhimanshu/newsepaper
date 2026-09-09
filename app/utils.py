"""Common utilities."""
from datetime import datetime, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))


def now_ist() -> datetime:
    """Return current time in IST."""
    return datetime.now(IST)


def today_ist() -> datetime:
    """Return today's date in IST (midnight)."""
    return now_ist().replace(hour=0, minute=0, second=0, microsecond=0)
