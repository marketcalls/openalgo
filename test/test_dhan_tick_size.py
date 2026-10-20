"""Dhan master contract tick size units.

Dhan ships ``SEM_TICK_SIZE`` in paise for every tradeable instrument, so rupees
is that value over 100: EQUITY arrives as 1..500, OPTIDX as 5, FUTCOM as
5..1000.

INDEX rows are the exception. Dhan ships those already in rupees (0.05 on NSE,
0.01 on BSE), and dividing them again produced 0.0005 and 0.0001. A tick that
fine drives four decimals of display precision, so NIFTY rendered as
24175.6500 on the chart's price axis instead of 24175.65.

These pin both halves of that rule, because the failure is silent: nothing
errors, the number is simply wrong by two orders of magnitude in a column
nobody reads directly.
"""

import pandas as pd
import pytest


def convert(frame: pd.DataFrame) -> pd.Series:
    """The conversion as ``process_dhan_csv`` performs it."""
    tick = pd.to_numeric(frame["SEM_TICK_SIZE"], errors="coerce")
    is_index = frame["SEM_INSTRUMENT_NAME"].astype(str).str.upper().eq("INDEX")
    return tick.where(is_index, tick / 100)


@pytest.mark.parametrize(
    ("instrument", "raw", "expected"),
    [
        # Paise, so divided.
        ("EQUITY", 5, 0.05),
        ("EQUITY", 1, 0.01),
        ("EQUITY", 500, 5.0),
        ("OPTIDX", 5, 0.05),
        ("OPTSTK", 1, 0.01),
        ("FUTCOM", 1000, 10.0),
        # Currency genuinely quotes in four decimals, and must keep them.
        ("OPTCUR", 0.25, 0.0025),
        ("FUTCUR", 0.01, 0.0001),
        # Already rupees, so left alone.
        ("INDEX", 0.05, 0.05),
        ("INDEX", 0.01, 0.01),
    ],
)
def test_tick_size_units(instrument, raw, expected):
    frame = pd.DataFrame({"SEM_INSTRUMENT_NAME": [instrument], "SEM_TICK_SIZE": [raw]})
    assert convert(frame).iloc[0] == pytest.approx(expected)


def test_an_index_tick_is_never_finer_than_a_paisa():
    """The regression itself: 0.0005 is what drove four decimals on the axis."""
    frame = pd.DataFrame(
        {
            "SEM_INSTRUMENT_NAME": ["INDEX", "INDEX", "INDEX"],
            "SEM_TICK_SIZE": [0.05, 0.01, 0.05],
        }
    )
    assert (convert(frame) >= 0.01).all()


def test_the_conversion_the_module_ships_matches_this_rule():
    """Guards against the source drifting away from what is asserted above.

    Read rather than imported: ``process_dhan_csv`` wants a CSV on disk and the
    whole broker package behind it, and the unit rule is one expression.
    """
    from pathlib import Path

    source = Path("broker/dhan/database/master_contract_db.py").read_text(encoding="utf-8")
    assert 'df["tick_size"] = _tick.where(_is_index, _tick / 100)' in source
    assert '_is_index = df["SEM_INSTRUMENT_NAME"].astype(str).str.upper().eq("INDEX")' in source
    # The unconditional division is what this replaced; it must not come back.
    assert 'pd.to_numeric(df["SEM_TICK_SIZE"], errors="coerce") / 100' not in source


def test_a_missing_tick_becomes_nan_not_a_silent_zero():
    frame = pd.DataFrame(
        {"SEM_INSTRUMENT_NAME": ["EQUITY", "INDEX"], "SEM_TICK_SIZE": ["", None]}
    )
    assert convert(frame).isna().all()
