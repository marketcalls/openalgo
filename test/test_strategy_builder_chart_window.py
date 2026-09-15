"""The Strategy Builder charts can ask for an explicit window of history.

Counting back from today is enough for a first view but cannot express what
scrolling left asks for, which is the range before whatever the chart already
holds. Without a window the endpoint answers every page with the same recent
slice and the chart stops at wherever it first landed.
"""

from datetime import datetime, timedelta
from unittest.mock import Mock

import pytest
import pytz

from services import multi_strike_oi_service, strategy_chart_service

LEG = {
    "symbol": "TEST27AUG26100CE",
    "exchange": "NFO",
    "side": "BUY",
    "segment": "OPTION",
    "active": True,
    "price": 10,
    "strike": 100,
    "optionType": "CE",
    "expiry": "27AUG26",
}

# Three IST dates, so a request capped to the newest one keeps a third of them.
# 1_700_000_000 is 2023-11-15 03:03 IST.
DAY = 86_400
TIMES = [1_700_000_000, 1_700_000_000 + DAY, 1_700_000_000 + 2 * DAY]

SERVICES = [
    (strategy_chart_service, strategy_chart_service.get_strategy_chart_data),
    (multi_strike_oi_service, multi_strike_oi_service.get_multi_strike_oi_data),
]


def history_response(*, symbol, exchange, **_kwargs):
    rows = [{"timestamp": t, "close": 100} for t in TIMES]
    if symbol == LEG["symbol"]:
        for row in rows:
            row["oi"] = 1_000
    return True, {"status": "success", "data": rows}, 200


def series_of(response):
    """The time series, whichever of the two payloads this is."""
    data = response["data"]
    return data["series"] if "series" in data else data["underlying_series"]


def run(service, module, monkeypatch, **kwargs):
    history = Mock(side_effect=history_response)
    monkeypatch.setattr(module, "get_history", history)
    monkeypatch.setattr(module, "get_quotes", Mock(return_value=(True, {"data": {"ltp": 101}}, 200)))
    success, response, status = service(
        underlying="NIFTY",
        exchange="NFO",
        underlying_symbol="NIFTY27AUG26FUT",
        underlying_exchange="NFO",
        legs=[LEG],
        interval="5m",
        api_key="key",
        **kwargs,
    )
    return history, success, response, status


@pytest.mark.parametrize(("module", "service"), SERVICES)
def test_an_explicit_window_is_passed_to_the_broker_verbatim(monkeypatch, module, service):
    history, success, _response, status = run(
        service,
        module,
        monkeypatch,
        start_date="2023-11-01",
        end_date="2023-11-10",
    )

    assert success is True
    assert status == 200
    for call in history.call_args_list:
        assert call.kwargs["start_date"] == "2023-11-01"
        assert call.kwargs["end_date"] == "2023-11-10"


@pytest.mark.parametrize(("module", "service"), SERVICES)
def test_an_explicit_window_is_not_trimmed_to_the_newest_dates(monkeypatch, module, service):
    _history, success, response, _status = run(
        service,
        module,
        monkeypatch,
        days=1,
        start_date="2023-11-01",
        end_date="2023-11-20",
    )

    assert success is True
    # `days=1` would keep only the newest date. For a chart paging backwards the
    # older dates are the entire point of the request, so the cap is skipped
    # whenever a window was named.
    series = series_of(response)
    assert len(series) == len(TIMES)


@pytest.mark.parametrize(("module", "service"), SERVICES)
def test_without_a_window_the_day_count_still_caps_the_answer(monkeypatch, module, service):
    _history, success, response, _status = run(service, module, monkeypatch, days=1)

    assert success is True
    # The unchanged behaviour: no window named, so "the last trading day" wins
    # over the generous calendar range actually fetched from the broker.
    series = series_of(response)
    assert len(series) == 1


@pytest.mark.parametrize(("module", "service"), SERVICES)
@pytest.mark.parametrize(
    "bad",
    [
        {"start_date": "not-a-date"},
        {"start_date": "2023-02-31"},
        {"start_date": "2023-11-01 OR 1=1"},
        {"start_date": "2023/11/01"},
        # Inverted, so the broker would be asked for a window that runs backwards.
        {"start_date": "2023-11-20", "end_date": "2023-11-01"},
        # Before the earliest date these markets have any history for.
        {"start_date": "1900-01-01", "end_date": "1900-06-01"},
    ],
)
def test_a_malformed_window_is_refused_without_reaching_the_broker(
    monkeypatch, module, service, bad
):
    history, success, response, status = run(service, module, monkeypatch, **bad)

    # These dates are handed to broker adapters that interpolate them into
    # upstream URLs. `/api/v1/history` validates its own with a schema; these
    # endpoints call the history service directly, so the check has to be here.
    assert success is False
    assert status == 400
    assert history.call_count == 0
    assert response["status"] == "error"


@pytest.mark.parametrize(("module", "service"), SERVICES)
def test_an_absurdly_wide_window_is_refused(monkeypatch, module, service):
    history, success, _response, status = run(
        service, module, monkeypatch, start_date="2005-01-01", end_date="2025-01-01"
    )

    # One request fans out into a broker call per leg, so an unbounded range is
    # an amplifier: ten legs over twenty years is two centuries of history from
    # a single click.
    assert success is False
    assert status == 400
    assert history.call_count == 0


@pytest.mark.parametrize(("module", "service"), SERVICES)
def test_a_window_with_no_end_runs_to_today(monkeypatch, module, service):
    # Relative to today, because an absolute start date drifts past the width
    # limit as time passes and the test would rot into a failure.
    start = (datetime.now(pytz.timezone("Asia/Kolkata")).date() - timedelta(days=30)).isoformat()
    history, success, _response, _status = run(service, module, monkeypatch, start_date=start)

    assert success is True
    first = history.call_args_list[0].kwargs
    assert first["start_date"] == start
    # A request may name only where to start; the window then runs to today.
    assert first["end_date"] > start
