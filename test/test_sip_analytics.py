"""Analytics output hygiene.

Chiefly: the metric functions must not emit warnings. A FutureWarning in a
Flask worker goes to the log on every request and trains people to ignore the
log -- and this particular one (object-dtype downcasting) was hiding a real
mistake, since `.replace(0, pd.NA)` silently promoted a float Series to object.
"""

import sys
import warnings
from contextlib import contextmanager
from datetime import date

import numpy as np
import pandas as pd
import pytest

from sip.analytics import (
    drawdown,
    frequency_comparison,
    headline,
    lumpsum_comparison,
    monthly_value_heatmap,
    rolling_xirr,
    sip_date_heatmap,
    start_date_heatmap,
    underwater,
    yearly_breakdown,
)
from sip.engine import run_sip


@contextmanager
def no_warnings():
    """Turn any warning into an error, reliably.

    ``catch_warnings`` restores the filter list but NOT each module's
    ``__warningregistry__``, which Python uses to emit a given warning only
    once per location. Without clearing it, the first test to trigger a
    warning silences it for every later test -- so the guard passes against
    code that still warns. Verified: without the clear, reintroducing the
    object-dtype bug did not fail this suite.
    """
    for module in list(sys.modules.values()):
        registry = getattr(module, "__warningregistry__", None)
        if registry:
            registry.clear()
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        yield


@pytest.fixture(scope="module")
def prices():
    rng = np.random.default_rng(11)
    n = 252 * 5
    idx = pd.DatetimeIndex(pd.bdate_range("2019-01-01", periods=n))
    return pd.Series(100 * np.cumprod(1 + rng.normal(0.0004, 0.012, n)), index=idx)


@pytest.fixture(scope="module")
def result(prices):
    return run_sip(prices, "ICICIBANK", "NSE", date(2019, 1, 1), date(2023, 12, 31), 10000)


@pytest.mark.parametrize("fn", [
    headline, underwater, drawdown, yearly_breakdown, monthly_value_heatmap,
])
def test_result_metrics_emit_no_warnings(fn, result):
    with no_warnings():
        fn(result)


def test_grid_metrics_emit_no_warnings(prices):
    with no_warnings():
        rolling_xirr(prices, 10000, years=(1,), step_months=12)
        start_date_heatmap(prices, 10000, durations=(1,))
        sip_date_heatmap(prices, date(2019, 1, 1), date(2023, 12, 31), 10000)
        frequency_comparison(prices, date(2019, 1, 1), date(2023, 12, 31), 10000)


def test_lumpsum_emits_no_warnings(prices, result):
    with no_warnings():
        lumpsum_comparison(prices, result, date(2019, 1, 1), date(2023, 12, 31))


def test_series_stay_numeric_not_object(result):
    """The root cause of the FutureWarning: `.replace(0, pd.NA)` promotes a
    float Series to object dtype. Assert the inputs the metrics divide by are
    still numeric, so the promotion cannot creep back."""
    for name, series in (
        ("value", result.value), ("invested", result.invested), ("units", result.units)
    ):
        assert pd.api.types.is_numeric_dtype(series), f"{name} is {series.dtype}"


def test_every_metric_is_json_safe(result, prices):
    """NaN and numpy scalars do not survive jsonify. Everything must already be
    a plain float or None by the time it leaves analytics."""
    import json

    payload = {
        "headline": headline(result),
        "underwater": underwater(result),
        "drawdown": drawdown(result),
        "yearly": yearly_breakdown(result),
        "monthly": monthly_value_heatmap(result),
        "frequency": frequency_comparison(
            prices, date(2019, 1, 1), date(2023, 12, 31), 10000
        ),
    }
    text = json.dumps(payload)          # raises on NaN=False? no -- check explicitly
    assert "NaN" not in text, "NaN leaked into the payload; jsonify would emit invalid JSON"
    assert "Infinity" not in text


# ---------------------------------------------------------------------------
# The zero-prior-close case, which is what actually triggered the FutureWarning
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def result_with_empty_first_month():
    """A SIP whose first installment lands in the SECOND month.

    Starting after the 1st with day_of_month=1 means January ends with zero
    units, so the shifted month-end close contains a real 0. That zero is what
    promoted the Series to object dtype and produced the FutureWarning in
    production -- the earlier fixture had no zero, so the guard passed against
    code that still warned.
    """
    rng = np.random.default_rng(5)
    idx = pd.DatetimeIndex(pd.bdate_range("2019-01-01", periods=252 * 3))
    px = pd.Series(100 * np.cumprod(1 + rng.normal(0.0004, 0.012, len(idx))), index=idx)
    return run_sip(px, "ICICIBANK", "NSE", date(2019, 1, 20), date(2021, 12, 31),
                   10000, day_of_month=1)


def test_zero_prior_close_does_not_warn(result_with_empty_first_month):
    with no_warnings():
        monthly_value_heatmap(result_with_empty_first_month)


def test_zero_prior_close_yields_a_gap_not_a_number(result_with_empty_first_month):
    """February follows a zero January close. There is no meaningful
    close-to-close return from zero, so the cell must be empty rather than
    infinite or a fabricated 0%."""
    grid = monthly_value_heatmap(result_with_empty_first_month)
    jan = grid["values"][0][0]
    feb = grid["values"][0][1]
    assert jan is None, "the first month has no prior close"
    assert feb is None, "a return measured from a zero base is not a number"


# ---------------------------------------------------------------------------
# Close-to-close, never open-to-close
# ---------------------------------------------------------------------------


def test_monthly_return_is_close_to_close(result):
    """Each cell must compare consecutive month-END closes.

    Recomputed independently here: if the implementation ever switched to an
    intramonth base (an open, or the first session of the month), these numbers
    would diverge.
    """
    grid = monthly_value_heatmap(result)
    monthly = pd.DataFrame(
        {"value": result.value, "invested": result.invested}
    ).resample("ME").last()

    prior_close = monthly["value"].shift(1)
    added = monthly["invested"] - monthly["invested"].shift(1)
    expected = ((monthly["value"] - prior_close) - added) / prior_close.where(
        prior_close != 0
    )

    flat = [v for row in grid["values"] for v in row if v is not None]
    wanted = [float(v) for v in expected.dropna()]
    assert len(flat) == len(wanted)
    for got, want in zip(flat, wanted, strict=True):
        assert got == pytest.approx(want, rel=1e-9)


def test_first_month_is_not_reported_as_flat(result):
    """No prior close means no return. Reporting 0% would claim a flat month
    that was never measured."""
    assert monthly_value_heatmap(result)["values"][0][0] is None


def test_the_basis_is_stated_in_the_payload(result):
    """So the UI never has to guess, and a future change has to update it."""
    assert "close-to-close" in monthly_value_heatmap(result)["basis"]


def test_contribution_is_removed_from_the_market_figure():
    """A flat price with monthly buys must show 0% market movement -- the value
    rises only because money was added."""
    idx = pd.DatetimeIndex(pd.bdate_range("2020-01-01", periods=300))
    flat_px = pd.Series([100.0] * len(idx), index=idx)
    r = run_sip(flat_px, "X", "NSE", date(2020, 1, 1), date(2020, 12, 31), 10000)
    cells = [v for row in monthly_value_heatmap(r)["values"] for v in row if v is not None]
    assert cells, "expected some months"
    for v in cells:
        assert v == pytest.approx(0.0, abs=1e-12)
