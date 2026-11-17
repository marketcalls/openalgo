"""Which days get a dated sandbox P&L snapshot (issue #876).

Indian markets: trading days only, so a weekend does not clone Friday's numbers
into new rows. A 24/7 crypto instance trades every day, so it keeps a row for
Saturday and Sunday instead of folding their P&L into Monday's.

Run inside the project root:
    uv run pytest test/test_sandbox_pnl_snapshot_days.py -v
"""

import os
import sys
from datetime import date
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FRIDAY = date(2026, 2, 6)
SATURDAY = date(2026, 2, 7)
SUNDAY = date(2026, 2, 8)


def _weekend_is_holiday(day, exchange=None):
    return day.weekday() >= 5


@pytest.mark.parametrize(
    ("expiry_disabled", "day", "expected"),
    [
        # Indian markets: the dates reported in #876.
        ("false", FRIDAY, True),
        ("false", SATURDAY, False),
        ("false", SUNDAY, False),
        # A 24/7 crypto instance snapshots every day.
        ("true", FRIDAY, True),
        ("true", SATURDAY, True),
        ("true", SUNDAY, True),
    ],
)
def test_snapshot_days(monkeypatch, expiry_disabled, day, expected):
    from sandbox.catch_up_processor import is_pnl_snapshot_day

    monkeypatch.setenv("DISABLE_SESSION_EXPIRY", expiry_disabled)
    with patch("database.market_calendar_db.is_market_holiday", _weekend_is_holiday):
        assert is_pnl_snapshot_day(day) is expected


def test_indian_holiday_on_a_weekday_is_still_skipped(monkeypatch):
    from sandbox.catch_up_processor import is_pnl_snapshot_day

    monkeypatch.setenv("DISABLE_SESSION_EXPIRY", "false")
    with patch("database.market_calendar_db.is_market_holiday", return_value=True):
        assert is_pnl_snapshot_day(FRIDAY) is False


def test_both_writers_use_the_shared_check():
    """The 23:59 cron and the startup backfill decide the same way."""
    import inspect

    from sandbox import catch_up_processor, squareoff_thread

    assert "is_pnl_snapshot_day(yesterday)" in inspect.getsource(
        catch_up_processor.catch_up_daily_pnl_snapshot
    )
    assert "is_pnl_snapshot_day(today)" in inspect.getsource(squareoff_thread)
