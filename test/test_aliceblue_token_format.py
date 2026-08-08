"""AliceBlue master-contract tokens must be integer strings, not floats.

pd.read_csv infers the Token column as float64 whenever it carries a NaN, so
values arrived as 2885.0 and landed in the VARCHAR token column as "2885.0" -
165,576 of 165,690 rows on a live database. Every tradable exchange was
affected; only the index feeds, which load through a different path, were clean:

    NSE  2710 rows   float-form 2710   sample '16921.0'
    NFO 75856 rows   float-form 75856  sample '35130.0'
    ...
    NSE_INDEX 57 rows  float-form 0    sample '26017'

Nothing broke outright because three call sites defend with
str(int(float(token))): transform_data for order placement, the streaming
adapter, and _normalize_token in api/data.py. Those remain as belt and braces,
but any new path using the token directly would have sent AliceBlue "2885.0".
"""

import os
import re
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

mc = pytest.importorskip("broker.aliceblue.database.master_contract_db")

INTEGER_STRING = re.compile(r"^\d+$")


def test_a_float_inferred_column_becomes_integer_strings():
    """The exact shape pandas produces: one NaN makes the whole column float64."""
    raw = pd.Series([2885, 1594, None, 438])
    assert raw.dtype == "float64", "precondition: pandas infers float when a NaN is present"

    cleaned = mc._clean_tokens(raw)

    assert list(cleaned) == ["2885", "1594", "", "438"]
    assert all(INTEGER_STRING.match(t) for t in cleaned if t)


def test_no_token_keeps_a_dot_zero_suffix():
    cleaned = mc._clean_tokens(pd.Series([2885.0, 500325.0, 26017.0]))
    assert not any("." in t for t in cleaned), f"float suffix survived: {list(cleaned)}"


def test_already_clean_integer_tokens_are_untouched():
    """Index feeds already load clean; the cleaner must not disturb them."""
    assert list(mc._clean_tokens(pd.Series([26017, 36, 500201]))) == ["26017", "36", "500201"]


def test_string_tokens_are_handled():
    assert list(mc._clean_tokens(pd.Series(["2885", "1594.0"]))) == ["2885", "1594"]


def test_unparseable_tokens_become_empty_not_a_sentinel():
    """-1 would look like a real instrument to a downstream token lookup."""
    cleaned = mc._clean_tokens(pd.Series(["", None, "N/A", 2885]))
    assert list(cleaned) == ["", "", "", "2885"]
    assert "-1" not in list(cleaned)


def test_large_tokens_do_not_go_scientific():
    """float64 renders big values as 1.03862e+06 if stringified naively."""
    cleaned = mc._clean_tokens(pd.Series([1038620.0, 834566.0, 568829.0]))
    assert list(cleaned) == ["1038620", "834566", "568829"]


def test_every_assignment_site_is_covered():
    """8 sites assign Token; a missed one silently reintroduces the bug."""
    source = open(mc.__file__, encoding="utf-8").read()
    # Capture what each assignment is set to, then check the expression - a
    # lookahead here backtracks over the whitespace and matches everything.
    assigned = re.findall(r'token_df\["token"\]\s*=\s*(.+)', source)
    assert assigned, "no Token assignments found - did the file move?"

    bypassing = [expr for expr in assigned if not expr.lstrip().startswith("_clean_tokens(")]
    assert not bypassing, f"{len(bypassing)} Token assignment(s) bypass _clean_tokens: {bypassing}"
    assert len(assigned) == 8, f"expected 8 assignment sites, found {len(assigned)}"
