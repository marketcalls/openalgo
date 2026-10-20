"""Kotak reference rows that never expire must not look like contracts.

Kotak marks a row carrying no expiry with a non-positive lExpiryDate, and the
segments disagree on which value: MCX uses 0 and CDS uses -1. Converted as a
timestamp each became a date, so the master contract advertised 40 MCX rows
expiring 01-JAN-70 and 14 CDS rows expiring 31-DEC-79, with combine_details
baking the date into the symbol: GOLD01JAN70, EURINR31DEC79FUT (QA MC-05).

The CDS rows also read pOptionType XX, which the XX-to-FUT rewrite turns into a
future, so emptying only the expiry would leave a future with no expiry date --
a worse row than the one it replaced, and MC-05 failing from the other side.
"""

import pandas as pd
import pytest

from broker.kotak.database.master_contract_db import _demote_non_expiring, combine_details


def _frame(expiry, instrumenttype, name="GOLD"):
    return pd.DataFrame(
        [{"name": name, "expiry": expiry, "instrumenttype": instrumenttype, "strike": 0.0}]
    )


@pytest.mark.parametrize("sentinel", [0, -1, "0", "-1", None])
def test_every_sentinel_a_segment_uses_is_recognised(sentinel):
    # MCX sends 0 and CDS sends -1; reading the raw column keeps one rule.
    df = _demote_non_expiring(_frame("01-JAN-70", "FUT"), pd.Series([sentinel]))

    assert df.loc[0, "expiry"] == ""
    assert df.loc[0, "instrumenttype"] == ""


def test_a_real_expiry_is_untouched():
    df = _demote_non_expiring(_frame("29-OCT-26", "CE"), pd.Series([1_793_000_000]))

    assert df.loc[0, "expiry"] == "29-OCT-26"
    assert df.loc[0, "instrumenttype"] == "CE"


def test_the_type_goes_with_the_expiry():
    # A future with no expiry date fails MC-05's derivative clause, so leaving
    # the type behind would trade one failure for another.
    df = _demote_non_expiring(_frame("31-DEC-79", "FUT", name="EURINR"), pd.Series([-1]))

    assert df.loc[0, "instrumenttype"] == "", "a thing with no expiry is not a future"


@pytest.mark.parametrize(
    "name,expiry,itype,expected",
    [
        ("GOLD", "", "", "GOLD"),                       # demoted MCX reference row
        ("EURINR", "", "", "EURINR"),                   # demoted CDS currency pair
        ("NIFTY", "29-OCT-26", "FUT", "NIFTY29OCT26FUT"),
    ],
)
def test_the_symbol_follows_from_the_cleared_fields(name, expiry, itype, expected):
    # combine_details builds the symbol out of name + expiry, which is why the
    # fake date reached the symbol in the first place.
    row = {"name": name, "expiry": expiry, "instrumenttype": itype, "strike": 0.0}

    assert combine_details(row) == expected


def test_a_frame_with_no_sentinel_rows_is_returned_unchanged():
    df = _frame("29-OCT-26", "PE")
    before = df.copy()

    assert _demote_non_expiring(df, pd.Series([1_793_000_000])).equals(before)
