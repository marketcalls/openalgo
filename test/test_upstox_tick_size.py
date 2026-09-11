"""Upstox master contract tick size units.

Upstox ships ``tick_size`` in paise on every tradeable segment, so rupees is
that value over 100. Sampled from the live instrument master: NSE_EQ arrives as
1/5/10, NSE_FO and BSE_FO as 5, MCX_FO as 50, and the currency segments
BCD_FO/NCD_FO as 0.25.

Left raw, ``/api/v1/symbol`` reported a BSE_FO SENSEX option tick as Rs 5.00
instead of Rs 0.05. Any code rounding a price to that tick then works at 100x
the intended granularity, which is how an SL-L limit price came out equal to
its trigger instead of a percentage above it.

Index rows need no exception here. Upstox sends null for NSE_INDEX and
BSE_INDEX rather than a rupee value, so they coerce to NaN and divide
harmlessly -- the opposite of Dhan, which ships indices already in rupees and
therefore needs one (see ``test_dhan_tick_size.py``).

These pin the rule because the failure is silent: nothing raises, the number is
simply wrong by two orders of magnitude in a column nobody reads directly.
"""

import pandas as pd
import pytest


def convert(frame: pd.DataFrame) -> pd.Series:
    """The conversion as ``process_upstox_json`` performs it."""
    return pd.to_numeric(frame["tick_size"], errors="coerce") / 100


@pytest.mark.parametrize(
    ("segment", "raw", "expected"),
    [
        # The reported bug: SENSEX weekly options on BSE F&O.
        ("BSE_FO", 5.0, 0.05),
        ("BSE_FO", 100.0, 1.0),
        # Equity, both ticks NSE and BSE actually quote.
        ("NSE_EQ", 1.0, 0.01),
        ("NSE_EQ", 5.0, 0.05),
        ("NSE_EQ", 10.0, 0.10),
        ("BSE_EQ", 1.0, 0.01),
        # Derivatives.
        ("NSE_FO", 5.0, 0.05),
        ("NSE_FO", 1.0, 0.01),
        # Commodities quote coarser.
        ("MCX_FO", 50.0, 0.50),
        ("MCX_FO", 10.0, 0.10),
        # Currency genuinely quotes in four decimals, and must keep them.
        ("BCD_FO", 0.25, 0.0025),
        ("NCD_FO", 0.25, 0.0025),
    ],
)
def test_tick_size_units(segment, raw, expected):
    frame = pd.DataFrame({"exchange": [segment], "tick_size": [raw]})
    assert convert(frame).iloc[0] == pytest.approx(expected)


def test_a_sensex_option_tick_is_five_paise_not_five_rupees():
    """The regression itself, in the units a trader would recognise."""
    frame = pd.DataFrame({"exchange": ["BSE_FO"], "tick_size": [5.0]})
    assert convert(frame).iloc[0] == pytest.approx(0.05)
    assert convert(frame).iloc[0] != pytest.approx(5.0)


def test_an_index_without_a_tick_stays_missing():
    """Upstox sends null for index rows; that must not become a silent zero."""
    frame = pd.DataFrame({"exchange": ["NSE_INDEX", "BSE_INDEX"], "tick_size": [None, None]})
    assert convert(frame).isna().all()


def test_a_missing_tick_becomes_nan_not_a_silent_zero():
    frame = pd.DataFrame({"exchange": ["NSE_EQ", "BSE_FO"], "tick_size": ["", None]})
    assert convert(frame).isna().all()


def test_the_conversion_the_module_ships_matches_this_rule():
    """Guards against the source drifting away from what is asserted above.

    Read rather than imported: ``process_upstox_json`` wants a JSON file on disk
    and the whole broker package behind it, and the unit rule is one expression.
    """
    from pathlib import Path

    source = Path("broker/upstox/database/master_contract_db.py").read_text(encoding="utf-8")
    assert 'df["tick_size"] = pd.to_numeric(df["tick_size"], errors="coerce") / 100' in source
