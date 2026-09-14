"""`/chart` and `/quote` must accept an omitted argument without shifting the rest.

Reported as issue #2011: `/chart RELIANCE intraday 15m 10` failed with a generic
"Failed to generate charts" plus a pandas stack trace, while the same command
with an explicit exchange worked. The handler read its arguments purely by
position, so "intraday" landed in the exchange slot, "15m" in the chart type and
"10" in the interval. Every argument after the omitted one was off by one.

`/chart NIFTY` failed for a second, unrelated reason: the default exchange was
NSE, but NIFTY is listed on NSE_INDEX. The usage text documented
`/chart NIFTY NSE_INDEX`, so the requirement was known, but the bare form is the
natural thing to type and it failed rather than resolving.

The tests below drive the three helpers directly rather than a Telegram update.
The parsing and the exchange resolution are the parts that can regress; building
an Update and a Context to reach them would test python-telegram-bot instead.

The working and failing lists are taken verbatim from the issue, so a regression
that reintroduces either cause fails here.
"""

import pytest

from services.telegram_bot_service import (
    history_to_dataframe,
    parse_symbol_arguments,
    resolve_exchange,
)


class _Listing:
    """Stand-in for a SymToken row, which carries only these two fields here."""

    def __init__(self, symbol, exchange):
        self.symbol = symbol
        self.exchange = exchange


# Every invocation the issue lists as working, with what it must still produce.
# An explicit exchange is never overridden, so these pin that the token-shaped
# parsing did not change behaviour that was already correct.
@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (["RELIANCE"], ("RELIANCE", None, None, None, None)),
        (
            ["RELIANCE", "NSE", "intraday", "15m", "10"],
            ("RELIANCE", "NSE", "intraday", "15m", 10),
        ),
        (["RELIANCE", "NSE", "daily", "D", "100"], ("RELIANCE", "NSE", "daily", "D", 100)),
        (["RELIANCE", "NSE", "both"], ("RELIANCE", "NSE", "both", None, None)),
        (["RELIANCE", "BSE"], ("RELIANCE", "BSE", None, None, None)),
        (
            ["RELIANCE", "BSE", "intraday", "15m", "10"],
            ("RELIANCE", "BSE", "intraday", "15m", 10),
        ),
        (["NIFTY", "NSE_INDEX"], ("NIFTY", "NSE_INDEX", None, None, None)),
        (["SENSEX", "BSE_INDEX"], ("SENSEX", "BSE_INDEX", None, None, None)),
    ],
)
def test_previously_working_invocations_parse_unchanged(args, expected):
    parsed, error = parse_symbol_arguments(args)
    assert error is None
    assert (
        parsed["symbol"],
        parsed["exchange"],
        parsed["chart_type"],
        parsed["interval"],
        parsed["days"],
    ) == expected


# The two failing forms from the issue that are caused by positional parsing.
# The exchange is left for the caller to resolve, which is the second cause.
@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (["RELIANCE", "intraday", "15m", "10"], ("RELIANCE", None, "intraday", "15m", 10)),
        (["RELIANCE", "daily", "D", "100"], ("RELIANCE", None, "daily", "D", 100)),
    ],
)
def test_omitted_exchange_no_longer_shifts_later_arguments(args, expected):
    parsed, error = parse_symbol_arguments(args)
    assert error is None
    assert (
        parsed["symbol"],
        parsed["exchange"],
        parsed["chart_type"],
        parsed["interval"],
        parsed["days"],
    ) == expected


def test_daily_alias_is_not_mistaken_for_the_interval():
    """"daily D" supplies both a chart type and an interval that share a letter."""
    parsed, error = parse_symbol_arguments(["RELIANCE", "daily", "D", "100"])
    assert error is None
    assert parsed["chart_type"] == "daily"
    assert parsed["interval"] == "D"


def test_non_numeric_days_is_reported_not_raised():
    """int(context.args[4]) used to raise ValueError straight out of the handler."""
    parsed, error = parse_symbol_arguments(["RELIANCE", "NSE", "intraday", "15m", "ten"])
    assert parsed is None
    assert "ten" in error


def test_zero_days_is_rejected():
    parsed, error = parse_symbol_arguments(["RELIANCE", "NSE", "intraday", "15m", "0"])
    assert parsed is None
    assert "positive" in error


def test_index_symbol_resolves_to_its_index_segment(monkeypatch):
    """`/chart NIFTY` is the case the issue opens with."""
    monkeypatch.setattr(
        "services.telegram_bot_service.enhanced_search_symbols",
        lambda *a, **k: [_Listing("NIFTY", "NSE_INDEX"), _Listing("NIFTY28OCT25FUT", "NFO")],
    )
    assert resolve_exchange("NIFTY") == "NSE_INDEX"


def test_cash_symbol_on_two_exchanges_still_prefers_nse(monkeypatch):
    """RELIANCE is listed on both, and NSE was the previous behaviour."""
    monkeypatch.setattr(
        "services.telegram_bot_service.enhanced_search_symbols",
        lambda *a, **k: [_Listing("RELIANCE", "BSE"), _Listing("RELIANCE", "NSE")],
    )
    assert resolve_exchange("RELIANCE") == "NSE"


def test_partial_matches_alone_do_not_decide_the_exchange(monkeypatch):
    """A derivative merely starting with the symbol must not pick the segment."""
    monkeypatch.setattr(
        "services.telegram_bot_service.enhanced_search_symbols",
        lambda *a, **k: [_Listing("NIFTYBEES", "NSE"), _Listing("NIFTY28OCT25FUT", "NFO")],
    )
    assert resolve_exchange("NIFTY") == "NSE"


def test_unknown_symbol_falls_back_to_the_old_assumption(monkeypatch):
    monkeypatch.setattr(
        "services.telegram_bot_service.enhanced_search_symbols", lambda *a, **k: []
    )
    assert resolve_exchange("NOSUCHSYMBOL") == "NSE"


def test_a_lookup_failure_does_not_cost_the_user_their_chart(monkeypatch):
    def explode(*a, **k):
        raise RuntimeError("database is down")

    monkeypatch.setattr("services.telegram_bot_service.enhanced_search_symbols", explode)
    assert resolve_exchange("NIFTY") == "NSE"


def test_status_dict_is_refused_instead_of_crashing_pandas():
    """pd.DataFrame(status_dict) raised "you must pass an index" as a stack trace."""
    rejected = {"status": "error", "message": "symbol not found"}
    assert history_to_dataframe(rejected, "NIFTY", "NSE") is None


def test_empty_and_missing_history_are_refused():
    import pandas as pd

    assert history_to_dataframe(None, "NIFTY", "NSE_INDEX") is None
    assert history_to_dataframe(pd.DataFrame(), "NIFTY", "NSE_INDEX") is None


def test_a_real_frame_is_passed_through():
    import pandas as pd

    frame = pd.DataFrame({"close": [1.0, 2.0]})
    assert history_to_dataframe(frame, "RELIANCE", "NSE") is frame
