from datetime import UTC, datetime

from app.usage import day_window_utc


def test_day_window_follows_the_user_time_zone() -> None:
    # 03:00 UTC on Nov 23 is still Nov 22 (22:00) in Bogota (UTC-5).
    now = datetime(2026, 11, 23, 3, 0, tzinfo=UTC)
    start, end = day_window_utc(now, "America/Bogota")
    assert start == datetime(2026, 11, 22, 5, 0, tzinfo=UTC)
    assert end == datetime(2026, 11, 23, 5, 0, tzinfo=UTC)


def test_unknown_time_zone_falls_back_to_utc() -> None:
    now = datetime(2026, 11, 23, 15, 0, tzinfo=UTC)
    start, end = day_window_utc(now, "Not/AZone")
    assert start == datetime(2026, 11, 23, 0, 0, tzinfo=UTC)
    assert end == datetime(2026, 11, 24, 0, 0, tzinfo=UTC)
