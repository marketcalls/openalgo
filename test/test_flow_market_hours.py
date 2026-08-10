"""The Flow scheduler's market-hours gate.

The window used to be a hardcoded 09:15-15:30, which was wrong for every
non-equity workflow (MCX trades to 23:55, CRYPTO never closes) and gave a
strategy no way to ask for a few minutes past the close to square off. It also
only skipped weekends, so a workflow happily traded through Diwali.

Hours now come from the market calendar, and a workflow can narrow or extend
them from its own trigger node in the flow JSON.
"""

from datetime import date, datetime
from types import SimpleNamespace
from unittest import mock

import pytest
import pytz

from services.flow_scheduler_service import (
    get_market_hours_config,
    is_within_market_hours,
)

IST = pytz.timezone("Asia/Kolkata")
# Patched at its source: is_within_market_hours imports it inside the call, so
# there is no module-level name on the scheduler to replace.
CAL = "database.market_calendar_db.get_effective_session_window"


def at(hour, minute, day=4):
    """2026-08-04 is a Tuesday; 08 a Saturday."""
    return IST.localize(datetime(2026, 8, day, hour, minute))


def session(start_hhmm, end_hhmm, day=4):
    """A calendar window, expressed the way the calendar expresses it."""
    def ms(hhmm):
        h, m = (int(p) for p in hhmm.split(":"))
        return int(IST.localize(datetime(2026, 8, day, h, m)).timestamp() * 1000)

    return {"start_ms": ms(start_hhmm), "end_ms": ms(end_hhmm), "is_special": False}


NSE = session("09:15", "15:30")
MCX = session("09:00", "23:55")


class TestCalendarDrivesTheWindow:
    """With no override, the exchange's own hours apply - nothing is assumed."""

    @pytest.mark.parametrize(
        "hour,minute,expected",
        [(9, 14, False), (9, 15, True), (15, 30, True), (15, 31, False), (3, 0, False)],
    )
    def test_equity_session(self, hour, minute, expected):
        with mock.patch(CAL, return_value=NSE):
            assert is_within_market_hours(at(hour, minute)) is expected

    def test_mcx_evening_is_open_where_the_old_fixed_window_shut_it(self):
        """22:30 is the case the hardcoded 15:30 close got wrong."""
        with mock.patch(CAL, return_value=MCX):
            assert is_within_market_hours(at(22, 30), exchange="MCX") is True
        with mock.patch(CAL, return_value=NSE):
            assert is_within_market_hours(at(22, 30)) is False

    def test_exchange_is_passed_through_to_the_calendar(self):
        with mock.patch(CAL, return_value=MCX) as spy:
            is_within_market_hours(at(12, 0), exchange="mcx")
            assert spy.call_args[0][1] == "MCX"

    def test_defaults_to_nse_when_none_named(self):
        with mock.patch(CAL, return_value=NSE) as spy:
            is_within_market_hours(at(12, 0))
            assert spy.call_args[0][1] == "NSE"


class TestClosedDays:
    """The calendar returning None means shut - weekend or trading holiday."""

    def test_closed_day_blocks_execution(self):
        with mock.patch(CAL, return_value=None):
            assert is_within_market_hours(at(12, 0, day=8)) is False

    def test_an_override_cannot_reopen_a_closed_day(self):
        """A holiday is not something a workflow may configure its way out of."""
        with mock.patch(CAL, return_value=None):
            assert (
                is_within_market_hours(
                    at(12, 0, day=8), start="00:00", end="23:59"
                )
                is False
            )


class TestFlowJsonOverride:
    def test_end_extends_past_the_session_close(self):
        with mock.patch(CAL, return_value=NSE):
            assert is_within_market_hours(at(15, 40)) is False
            assert is_within_market_hours(at(15, 40), end="15:40") is True

    def test_start_narrows_the_open(self):
        with mock.patch(CAL, return_value=NSE):
            assert is_within_market_hours(at(9, 20)) is True
            assert is_within_market_hours(at(9, 20), start="09:30") is False

    def test_one_side_only_leaves_the_other_on_the_calendar(self):
        with mock.patch(CAL, return_value=NSE):
            # end overridden, start still the session open
            assert is_within_market_hours(at(9, 14), end="15:40") is False
            assert is_within_market_hours(at(15, 35), end="15:40") is True

    def test_boundaries_are_inclusive(self):
        with mock.patch(CAL, return_value=NSE):
            assert is_within_market_hours(at(10, 0), start="10:00", end="14:00") is True
            assert is_within_market_hours(at(14, 0), start="10:00", end="14:00") is True
            assert is_within_market_hours(at(14, 1), start="10:00", end="14:00") is False

    @pytest.mark.parametrize("bad", ["", "nonsense", "25:00", "12:99", "1530", "12:"])
    def test_malformed_override_falls_back_to_the_calendar(self, bad):
        """Garbage must not widen the window to 24x7."""
        with mock.patch(CAL, return_value=NSE):
            assert is_within_market_hours(at(23, 0), end=bad) is False
            assert is_within_market_hours(at(12, 0), end=bad) is True


class TestConfigFromGraph:
    def _wf(self, data):
        return SimpleNamespace(nodes=[{"type": "start", "data": data}])

    def test_reads_the_trigger_node(self):
        cfg = get_market_hours_config(
            self._wf(
                {
                    "marketHoursOnly": True,
                    "marketHoursStart": "09:15",
                    "marketHoursEnd": "15:40",
                    "marketHoursExchange": "NFO",
                }
            )
        )
        assert cfg == {
            "enabled": True,
            "start": "09:15",
            "end": "15:40",
            "exchange": "NFO",
        }

    def test_absent_keys_are_none_not_invented(self):
        cfg = get_market_hours_config(self._wf({"marketHoursOnly": True}))
        assert cfg["enabled"] is True
        assert cfg["start"] is None and cfg["end"] is None and cfg["exchange"] is None

    def test_workflow_without_a_start_node(self):
        cfg = get_market_hours_config(SimpleNamespace(nodes=[{"type": "getQuote"}]))
        assert cfg["enabled"] is False

    def test_workflow_with_no_nodes(self):
        assert get_market_hours_config(SimpleNamespace(nodes=None))["enabled"] is False


def _calendar_is_seeded() -> bool:
    """Whether this environment has market timings loaded.

    The unmocked checks below need seeded MarketTiming rows. A bare test
    database has none, and that is a property of the environment rather than a
    fault in the gate, so they skip rather than fail.
    """
    try:
        from database.market_calendar_db import get_effective_session_window

        return get_effective_session_window(date(2026, 8, 4), "NSE") is not None
    except Exception:
        return False


@pytest.mark.skipif(
    not _calendar_is_seeded(), reason="market calendar not seeded in this environment"
)
class TestRealCalendar:
    """Unmocked, so the wiring to the real calendar is exercised end to end."""

    def test_saturday_is_shut_for_nse(self):
        assert is_within_market_hours(at(12, 0, day=8)) is False

    def test_tuesday_midday_is_open_for_nse(self):
        assert is_within_market_hours(at(12, 0)) is True

    def test_end_override_extends_a_real_session(self):
        assert is_within_market_hours(at(15, 40)) is False
        assert is_within_market_hours(at(15, 40), end="15:40") is True
