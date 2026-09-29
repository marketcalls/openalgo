"""A MARKET fill must not trust an LTP the same payload contradicts.

Issue #1638. A broker's REST quote carries `last_price` as the previous trade,
however old that trade is. For a symbol that has not printed a fresh tick the
number can be weeks stale while the same payload's day OHLC is current, so the
sandbox filled at it and recorded a fake gain. The reported case filled at
1047.60 on a day that traded 1262 to 1345, a +22% phantom position, with the
order book showing the correct price all along.

The guard is deliberately narrow: the only evidence available is the broker
contradicting itself, because the quote contract shared by all brokers carries
no timestamp. `test_a_symbol_that_has_not_traded_today_is_not_caught` pins the
resulting blind spot so it stays a known limitation rather than becoming a
surprise.
"""

from sandbox.execution_engine import quote_looks_stale

# The payload from the report: a five-week-old last price against a current
# day range.
REPORTED = {"ltp": 1047.60, "high": 1345.0, "low": 1262.0, "prev_close": 1296.4}


def test_the_reported_fill_is_deferred():
    assert quote_looks_stale(REPORTED) is True


def test_a_coherent_quote_still_fills():
    """The guard must not defer ordinary orders; that would stall the engine."""
    assert quote_looks_stale({"ltp": 1296.0, "high": 1345.0, "low": 1262.0}) is False


def test_either_side_of_the_range_counts():
    assert quote_looks_stale({"ltp": 900.0, "high": 1345.0, "low": 1262.0}) is True
    assert quote_looks_stale({"ltp": 1400.0, "high": 1345.0, "low": 1262.0}) is True


def test_the_range_is_inclusive():
    """An LTP exactly at the day high or low is the real trade, not a stale one.

    Both happen constantly: the high and the low were each somebody's last
    traded price at the moment they printed.
    """
    assert quote_looks_stale({"ltp": 1262.0, "high": 1345.0, "low": 1262.0}) is False
    assert quote_looks_stale({"ltp": 1345.0, "high": 1345.0, "low": 1262.0}) is False


def test_a_symbol_that_has_not_traded_today_is_not_caught():
    """The documented blind spot, asserted so it cannot regress silently.

    With no trades there is no day range to cross-check, so a stale price still
    passes. Closing this needs a quote timestamp, which the broker quote
    contract does not carry. Deferring instead would block every legitimate
    pre-first-trade order.
    """
    assert quote_looks_stale({"ltp": 1047.60, "high": 0, "low": 0}) is False


def test_a_tick_built_quote_without_ohlc_still_fills():
    """WebSocket quotes are live by construction and often carry no OHLC."""
    assert quote_looks_stale({"ltp": 1296.0}) is False


def test_a_malformed_quote_never_blocks_a_fill():
    """The guard runs on the order path; raising there would fail the order."""
    for bad in ({"ltp": None}, {"ltp": "abc", "high": 1, "low": 0}, {}, {"ltp": -5}):
        assert quote_looks_stale(bad) is False


def test_both_fill_paths_consult_the_guard():
    """Placement fills directly via _execute_order; the engines go through
    _process_order. A guard on only one of them leaves the reported case open.
    """
    import inspect

    from sandbox import execution_engine, order_manager

    assert "quote_looks_stale" in inspect.getsource(
        execution_engine.ExecutionEngine._process_order
    )
    assert "quote_looks_stale" in inspect.getsource(order_manager.OrderManager.place_order)
