"""SIP behaviour around crisis windows.

The claim this panel makes -- that starting into a crash usually beats waiting
-- is a tendency in the data, not a law. These tests check the mechanics that
make the comparison fair, not the direction of the result.
"""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from portfolio.crisis import CrisisPeriod
from sip.crisis import MIN_SIP_DAYS, crisis_sip_analysis, crisis_summary


def series(start="2015-01-01", end="2025-06-30", seed=4, shock=None):
    rng = np.random.default_rng(seed)
    idx = pd.DatetimeIndex(pd.bdate_range(start, end))
    r = rng.normal(0.0004, 0.011, len(idx))
    if shock:
        mask = (idx >= shock[0]) & (idx <= shock[1])
        r[mask] -= 0.012
    return pd.Series(100 * np.cumprod(1 + r), index=idx)


CRASH = CrisisPeriod("test_crash", "Test Crash", "2020-02-19", "2020-03-23", "", "global")


def test_both_variants_run_to_the_same_end_date():
    """Only the start may differ, or the comparison is not like for like."""
    px = series(shock=("2020-02-19", "2020-03-23"))
    rows = crisis_sip_analysis(px, 10000, periods=(CRASH,))
    assert len(rows) == 1
    row = rows[0]
    assert row["started_into_it"]["start"] == "2020-02-19"
    assert row["waited_for_the_end"]["start"] == "2020-03-23"
    # Starting earlier means strictly more installments.
    assert row["started_into_it"]["installments"] > row["waited_for_the_end"]["installments"]


def test_starting_into_a_crash_buys_cheaper_units():
    """The mechanism behind the whole panel: a SIP running through the decline
    accumulates at lower prices than one that begins after the rebound."""
    px = series(shock=("2020-02-19", "2020-03-23"))
    row = crisis_sip_analysis(px, 10000, periods=(CRASH,))[0]
    assert row["started_into_it"]["average_cost"] < row["waited_for_the_end"]["average_cost"]


def test_market_context_is_reported():
    px = series(shock=("2020-02-19", "2020-03-23"))
    row = crisis_sip_analysis(px, 10000, periods=(CRASH,))[0]
    assert row["market_move"] < 0, "the shocked window should be down"
    assert row["market_trough"] <= row["market_move"]


def test_crises_outside_the_data_are_dropped_not_clipped():
    """A SIP that existed for three days of a crash did not live through it."""
    px = series(start="2022-01-01", end="2025-06-30")
    assert crisis_sip_analysis(px, 10000, periods=(CRASH,)) == []


def test_a_crisis_with_no_runway_after_it_is_dropped():
    """Both variants need time to accumulate; otherwise it is a lumpsum."""
    late = CrisisPeriod("late", "Late Crash", "2025-05-01", "2025-05-20", "", "global")
    px = series(start="2015-01-01", end="2025-06-30")
    days_after = (date(2025, 6, 30) - date(2025, 5, 20)).days
    assert days_after < MIN_SIP_DAYS
    assert crisis_sip_analysis(px, 10000, periods=(late,)) == []


def test_rows_are_newest_first():
    px = series()
    rows = crisis_sip_analysis(px, 10000)
    starts = [r["crisis_start"] for r in rows]
    assert starts == sorted(starts, reverse=True)


def test_summary_counts_rather_than_claims():
    px = series()
    rows = crisis_sip_analysis(px, 10000)
    s = crisis_summary(rows)
    assert s["crises"] == len([r for r in rows if r["xirr_advantage"] is not None])
    assert 0 <= s["early_wins"] <= s["crises"]
    assert s["share"] == pytest.approx(s["early_wins"] / s["crises"])


def test_empty_history_is_handled():
    assert crisis_sip_analysis(pd.Series(dtype=float), 10000) == []
    assert crisis_summary([])["crises"] == 0


def test_every_value_is_json_safe():
    import json
    px = series()
    text = json.dumps({"periods": crisis_sip_analysis(px, 10000)})
    assert "NaN" not in text and "Infinity" not in text
