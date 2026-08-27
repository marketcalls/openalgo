"""
Guards the timezone contract of the option-expiry helpers.

`parse_option_symbol` returns a naive datetime that every caller reads as IST,
and several of them compare it against naive timestamps of their own. Making it
timezone-aware breaks those comparisons: `iv_chart_service` raises
"can't compare offset-naive and offset-aware datetimes" outright, while
`vol_surface_service` swallows the same TypeError in a broad except and silently
reports a days-to-expiry of 0.

`get_expiry_datetime` is the opposite: it must stay aware, because
`option_chain_service` converts it to an epoch for the browser.
"""

import os
import sys
from datetime import datetime
from pathlib import Path

os.environ.setdefault("API_KEY_PEPPER", "test-pepper-value-at-least-32-chars")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402

from services.iv_chart_service import calculate_time_to_expiry_at  # noqa: E402
from services.option_greeks_service import (  # noqa: E402
    calculate_time_to_expiry,
    get_exchange_expiry_time,
    get_expiry_datetime,
    parse_option_symbol,
)

SYMBOL = "NIFTY11AUG2624600CE"


def test_parse_option_symbol_returns_naive_expiry():
    _, expiry, _, _ = parse_option_symbol(SYMBOL, "NFO")
    assert expiry.tzinfo is None, "callers compare this against naive datetimes"
    assert expiry == datetime(2026, 8, 11, 15, 30)


def test_expiry_compares_against_a_naive_datetime():
    """The vol_surface_service pattern, which fails silently when this breaks."""
    _, expiry, _, _ = parse_option_symbol(SYMBOL, "NFO")
    delta = expiry - datetime(2026, 8, 10, 9, 20)
    assert delta.total_seconds() > 0


def test_expiry_compares_against_a_pandas_candle_timestamp():
    """The iv_chart_service path that raised on the /ivchart page."""
    _, expiry, _, _ = parse_option_symbol(SYMBOL, "NFO")
    years, days = calculate_time_to_expiry_at(pd.Timestamp("2026-08-10 09:20:00"), expiry)
    assert years > 0
    assert 1.0 < days < 2.0


def test_expiry_at_or_after_the_candle_is_worthless_not_an_error():
    _, expiry, _, _ = parse_option_symbol(SYMBOL, "NFO")
    assert calculate_time_to_expiry_at(pd.Timestamp("2026-08-11 15:30:00"), expiry) == (0.0, 0.0)
    assert calculate_time_to_expiry_at(pd.Timestamp("2026-08-12 09:20:00"), expiry) == (0.0, 0.0)


def test_get_expiry_datetime_stays_timezone_aware():
    """option_chain_service turns this into an epoch, which needs an offset."""
    aware = get_expiry_datetime("11AUG26", "NFO")
    assert aware.tzinfo is not None
    assert aware.utcoffset().total_seconds() == 5.5 * 3600
    assert int(aware.timestamp()) == 1786442400


def test_naive_and_aware_expiries_agree_on_tenor():
    """calculate_time_to_expiry localizes the naive form, so both paths match."""
    _, naive_expiry, _, _ = parse_option_symbol(SYMBOL, "NFO")
    aware_expiry = get_expiry_datetime("11AUG26", "NFO")

    naive_years, _ = calculate_time_to_expiry(naive_expiry)
    aware_years, _ = calculate_time_to_expiry(aware_expiry)
    assert abs(naive_years - aware_years) < 1e-9


def test_exchange_expiry_times_are_shared_by_both_helpers():
    """One source of truth, so the chain and the Greeks cannot disagree."""
    assert get_exchange_expiry_time("NFO") == (15, 30)
    assert get_exchange_expiry_time("BFO") == (15, 30)
    assert get_exchange_expiry_time("CDS") == (12, 30)
    assert get_exchange_expiry_time("MCX") == (23, 30)
    assert get_exchange_expiry_time("NFO", "19:00") == (19, 0)

    for exchange, (hour, minute) in (("NFO", (15, 30)), ("CDS", (12, 30)), ("MCX", (23, 30))):
        _, parsed, _, _ = parse_option_symbol(SYMBOL, exchange)
        assert (parsed.hour, parsed.minute) == (hour, minute)
        built = get_expiry_datetime("11AUG26", exchange)
        assert (built.hour, built.minute) == (hour, minute)
