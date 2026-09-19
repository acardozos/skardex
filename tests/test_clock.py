from datetime import UTC, date, datetime

from skardex.clock import today


def test_today_is_still_the_previous_day_early_in_utc() -> None:
    # 02:00 UTC is 21:00 the previous day in Colombia (UTC-5).
    assert today(datetime(2026, 9, 20, 2, 0, tzinfo=UTC)) == date(2026, 9, 19)


def test_today_matches_utc_date_once_colombia_reaches_the_new_day() -> None:
    # 05:00 UTC is exactly 00:00 in Colombia.
    assert today(datetime(2026, 9, 20, 5, 0, tzinfo=UTC)) == date(2026, 9, 20)


def test_today_before_19_colombian_time_is_the_same_utc_day() -> None:
    # 18:59 in Colombia is 23:59 UTC the same day.
    assert today(datetime(2026, 9, 19, 23, 59, tzinfo=UTC)) == date(2026, 9, 19)


def test_today_after_19_colombian_time_differs_from_the_server_date() -> None:
    """The case that motivated the helper: the UTC server already says
    'tomorrow' while it is still evening in Colombia."""
    now = datetime(2026, 9, 20, 0, 30, tzinfo=UTC)  # 19:30 in Colombia
    assert now.date() == date(2026, 9, 20)
    assert today(now) == date(2026, 9, 19)


def test_today_without_argument_returns_a_date() -> None:
    assert isinstance(today(), date)
