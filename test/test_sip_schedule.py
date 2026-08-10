"""SIP schedule generation: holidays, month ends, step-up."""
from datetime import date

import pandas as pd
import pytest

from sip.schedule import (
    ScheduleError,
    apply_step_up,
    build_schedule,
    requested_dates,
)


def sessions(start="2020-01-01", end="2021-12-31"):
    """Weekdays only, standing in for a trading calendar."""
    return pd.DatetimeIndex(pd.bdate_range(start, end))


def test_monthly_dates_land_on_the_requested_day():
    d = requested_dates(date(2020, 1, 1), date(2020, 6, 30), "monthly", 15)
    assert [x.isoformat() for x in d] == [
        "2020-01-15", "2020-02-15", "2020-03-15", "2020-04-15", "2020-05-15", "2020-06-15"]


def test_quarterly_steps_three_months():
    d = requested_dates(date(2020, 1, 1), date(2020, 12, 31), "quarterly", 1)
    assert [x.month for x in d] == [1, 4, 7, 10]


@pytest.mark.parametrize("freq,expected_gap", [("weekly", 7), ("fortnightly", 14)])
def test_weekly_and_fortnightly_gaps(freq, expected_gap):
    d = requested_dates(date(2020, 1, 1), date(2020, 3, 1), freq)
    assert all((d[i + 1] - d[i]).days == expected_gap for i in range(len(d) - 1))


def test_days_after_the_28th_are_rejected_not_clamped():
    """Silently turning the 31st into the 28th in February would produce an
    irregular schedule the user never asked for."""
    with pytest.raises(ScheduleError, match="28"):
        requested_dates(date(2020, 1, 1), date(2020, 6, 1), "monthly", 31)


def test_step_up_raises_on_each_anniversary_not_calendar_year():
    d = [date(2020, 10, 1), date(2021, 4, 1), date(2021, 10, 5), date(2022, 10, 5)]
    amounts = apply_step_up(d, 10000, 10.0)
    assert amounts[0] == pytest.approx(10000)
    assert amounts[1] == pytest.approx(10000), "still inside year 1"
    assert amounts[2] == pytest.approx(11000), "first anniversary"
    assert amounts[3] == pytest.approx(12100), "second anniversary, compounding"


def test_zero_step_up_is_a_flat_amount():
    d = requested_dates(date(2020, 1, 1), date(2023, 1, 1), "monthly", 1)
    assert set(apply_step_up(d, 5000, 0.0)) == {5000}


def test_installment_on_a_holiday_moves_to_the_next_session():
    """2020-01-01 was a Wednesday holiday in this calendar (bdate_range starts
    2020-01-01, so use a weekend instead): the 5th is a Sunday."""
    s = build_schedule(sessions(), date(2020, 1, 1), date(2020, 3, 31), 5000,
                       frequency="monthly", day_of_month=5)
    jan = s[0]
    assert jan.requested == date(2020, 1, 5)
    assert jan.executed == date(2020, 1, 6), "Sunday rolls to Monday"
    assert jan.executed.weekday() < 5


def test_requested_and_executed_are_both_kept():
    """So the UI can show that a 1st-of-month SIP really transacted on the 2nd."""
    s = build_schedule(sessions(), date(2020, 1, 1), date(2020, 12, 31), 5000)
    assert any(i.requested != i.executed for i in s), "some months must have rolled"
    assert all(i.executed >= i.requested for i in s)


def test_installments_never_execute_after_the_window():
    s = build_schedule(sessions(), date(2020, 1, 1), date(2020, 6, 30), 5000)
    assert all(i.executed <= date(2020, 6, 30) for i in s)


def test_step_up_flows_through_to_installments():
    s = build_schedule(sessions("2020-01-01", "2022-12-31"),
                       date(2020, 1, 1), date(2022, 12, 31), 10000,
                       step_up_percent=10.0)
    assert s[0].amount == pytest.approx(10000)
    assert s[-1].amount == pytest.approx(12100), "third year"


@pytest.mark.parametrize("kwargs,match", [
    ({"amount": 0}, "positive"),
    ({"frequency": "daily"}, "frequency must be"),
])
def test_invalid_inputs_are_rejected(kwargs, match):
    base = {
        "sessions": sessions(), "start": date(2020, 1, 1),
        "end": date(2020, 6, 1), "amount": 5000,
    }
    base.update(kwargs)
    with pytest.raises(ScheduleError, match=match):
        build_schedule(**base)


def test_window_too_short_for_any_installment():
    with pytest.raises(ScheduleError):
        build_schedule(sessions(), date(2020, 1, 2), date(2020, 1, 3), 5000,
                       frequency="monthly", day_of_month=15)
