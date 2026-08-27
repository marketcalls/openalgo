"""Trading-calendar arithmetic, and the new-period flags built on it.

The point of these flags is that they are correct where the obvious tests are
not: `day == 1` misses a 1st that falls on a weekend or holiday, and
`weekday == Monday` misses a week whose Monday is a holiday. Those two cases
are asserted directly.

Run: uv run pytest test/test_trading_calendar.py -v
"""

from datetime import date

import pytest

from utils import trading_calendar as tc


@pytest.fixture(autouse=True)
def fixed_calendar(monkeypatch):
    """A known calendar, so these tests do not depend on the live holiday feed.

    Includes a Sunday special session, because the real feed has one every year
    (Diwali Muhurat trading) and it is the case that breaks a naive
    "weekend means closed" rule.
    """
    closed = {
        date(2026, 1, 26),  # Republic Day, a Monday
        date(2026, 3, 31),  # a Tuesday, month end
        date(2026, 4, 1),   # a Wednesday, quarter start
    }
    special = {date(2026, 11, 8)}  # a Sunday - Muhurat trading
    monkeypatch.setattr(
        tc,
        "_calendar_entries",
        lambda year: (
            frozenset(d for d in closed if d.year == year),
            frozenset(d for d in special if d.year == year),
        ),
    )


def test_weekends_are_not_trading_days():
    assert not tc.is_trading_day(date(2026, 8, 1))  # Saturday
    assert not tc.is_trading_day(date(2026, 8, 2))  # Sunday
    assert tc.is_trading_day(date(2026, 8, 3))      # Monday


def test_holidays_are_not_trading_days():
    assert not tc.is_trading_day(date(2026, 1, 26))
    assert tc.is_trading_day(date(2026, 1, 27))


def test_new_week_survives_a_holiday_monday():
    """The naive `weekday == Monday` test fails this case."""
    assert not tc.is_first_trading_day_of(date(2026, 1, 26), "week")  # holiday Monday
    assert tc.is_first_trading_day_of(date(2026, 1, 27), "week")      # Tuesday opens the week


def test_new_month_survives_a_weekend_first():
    """The naive `day == 1` test fails this case: 1 Aug 2026 is a Saturday."""
    assert not tc.is_first_trading_day_of(date(2026, 8, 1), "month")
    assert tc.is_first_trading_day_of(date(2026, 8, 3), "month")


def test_new_quarter_survives_a_holiday_first():
    """1 Apr 2026 is a holiday here, so Q2 opens on the 2nd."""
    assert not tc.is_first_trading_day_of(date(2026, 4, 1), "quarter")
    assert tc.is_first_trading_day_of(date(2026, 4, 2), "quarter")
    # A new quarter is also a new month.
    assert tc.is_first_trading_day_of(date(2026, 4, 2), "month")


def test_new_year():
    assert tc.is_first_trading_day_of(date(2026, 1, 1), "year")
    assert not tc.is_first_trading_day_of(date(2026, 1, 2), "year")


def test_last_trading_day_skips_a_holiday_month_end():
    """31 Mar 2026 is a holiday here, so March closes on the 30th."""
    assert not tc.is_last_trading_day_of(date(2026, 3, 31), "month")
    assert tc.is_last_trading_day_of(date(2026, 3, 30), "month")


def test_nothing_starts_or_ends_on_a_non_trading_day():
    for period in tc.PERIODS:
        assert not tc.is_first_trading_day_of(date(2026, 8, 2), period)  # Sunday
        assert not tc.is_last_trading_day_of(date(2026, 8, 2), period)


def test_adjacent_trading_days_skip_weekends_and_holidays():
    assert tc.prev_trading_day(date(2026, 8, 3)) == date(2026, 7, 31)  # back over a weekend
    assert tc.next_trading_day(date(2026, 7, 31)) == date(2026, 8, 3)
    assert tc.next_trading_day(date(2026, 1, 23)) == date(2026, 1, 27)  # over Republic Day


@pytest.mark.parametrize(
    "day,quarter",
    [
        (date(2026, 1, 15), 1),
        (date(2026, 3, 31), 1),
        (date(2026, 4, 1), 2),
        (date(2026, 7, 30), 3),
        (date(2026, 12, 31), 4),
    ],
)
def test_quarter_of(day, quarter):
    assert tc.quarter_of(day) == quarter


def test_describe_covers_every_flag_a_workflow_reads():
    info = tc.describe(date(2026, 8, 3))
    for key in (
        "is_trading_day", "is_trading_holiday", "is_weekend", "weekday", "weekday_num",
        "quarter", "week_of_year", "day_of_year",
        "is_new_day", "is_new_week", "is_new_month", "is_new_quarter", "is_new_year",
        "is_last_day_of_week", "is_last_day_of_month", "is_last_day_of_quarter",
        "prev_trading_day", "next_trading_day",
    ):
        assert key in info, key
    assert info["weekday_num"] == 1  # Monday
    assert info["quarter"] == 3


def test_a_trading_holiday_is_distinguished_from_a_weekend():
    holiday = tc.describe(date(2026, 1, 26))
    weekend = tc.describe(date(2026, 8, 2))
    assert holiday["is_trading_holiday"] and not holiday["is_weekend"]
    assert weekend["is_weekend"] and not weekend["is_trading_holiday"]


def test_unknown_period_is_rejected():
    with pytest.raises(ValueError):
        tc.is_first_trading_day_of(date(2026, 8, 3), "fortnight")


def test_a_special_session_trades_even_on_a_sunday():
    """Diwali Muhurat trading is held on a Sunday.

    Flattening it into the holiday set, or short-circuiting on the weekend,
    hides a real session and shifts every adjacent-day answer around it.
    """
    muhurat = date(2026, 11, 8)
    assert tc.is_trading_day(muhurat)
    info = tc.describe(muhurat)
    assert info["is_special_session"]
    # `is_weekend` stays a calendar property: it is a Sunday, and it trades.
    assert info["is_weekend"]
    assert not info["is_trading_holiday"]


def test_a_special_session_is_reachable_by_navigation():
    assert tc.next_trading_day(date(2026, 11, 7)) == date(2026, 11, 8)
    assert tc.prev_trading_day(date(2026, 11, 9)) == date(2026, 11, 8)


def test_a_trading_holiday_is_not_a_special_session():
    info = tc.describe(date(2026, 1, 26))
    assert info["is_trading_holiday"]
    assert not info["is_special_session"]
    assert not info["is_trading_day"]
