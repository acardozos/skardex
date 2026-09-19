from datetime import UTC, date, datetime, timedelta, timezone

# Colombia is UTC-5 all year (no daylight saving). A fixed offset avoids
# needing the tz database, which the python:3.11-slim image does not ship.
LOCAL_TZ = timezone(timedelta(hours=-5), "COT")


def today(now: datetime | None = None) -> date:
    """Today's date in local time; `now` must be timezone-aware when given."""
    current = now if now is not None else datetime.now(UTC)
    return current.astimezone(LOCAL_TZ).date()
