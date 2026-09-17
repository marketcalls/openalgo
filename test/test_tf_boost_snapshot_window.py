"""The recorder's session window — boundary minutes included.

The closing tick was lost every day because the window ended at 15:30:00.000000
while APScheduler dispatches the 15:30 cron a fraction after it.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from services.tf_boost_snapshot_service import _within_market_window

IST = ZoneInfo("Asia/Kolkata")


def at(h: int, m: int, s: int = 0, us: int = 0) -> datetime:
    return datetime(2026, 9, 17, h, m, s, us, tzinfo=IST)


def test_the_closing_tick_is_recorded():
    # The defect: dispatched a moment after 15:30:00, and rejected.
    assert _within_market_window(at(15, 30, 0, 150_000))
    assert _within_market_window(at(15, 30))
    assert _within_market_window(at(15, 30, 59, 999_999))


def test_the_opening_tick_is_recorded():
    assert _within_market_window(at(9, 15))
    assert not _within_market_window(at(9, 14, 59, 999_999))


def test_outside_the_session_is_skipped():
    assert not _within_market_window(at(15, 31))
    assert not _within_market_window(at(8, 0))
    assert not _within_market_window(at(16, 30))
