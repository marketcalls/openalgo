"""
Zerodha quotes must carry the size resting at the best bid and ask.

Issue #2045: `/api/v1/optionchain` returned `bid_qty: 0` and `ask_qty: 0` on
every leg for Zerodha while `bid` and `ask` were correct. Kite's `/quote`
carries the size beside the price in the same depth entry, and
`get_market_depth` in the same file already read it, but the quote mappings
read only `price`. The keys were therefore absent rather than wrong, so
`services/option_chain_service.py`'s `ce_quote.get("bid_qty", 0)` defaulted and
the chain reported a confident zero.

That distinction is the whole point: a zero reads as "nothing on offer" rather
than "not reported", so a strategy checking the book before sending an order
gets a wrong answer instead of a missing one. These tests pin the size, not
just the presence of the key.

The fixture is the shape Kite documents for a depth entry: quantity, price and
orders together (`zerodha-api-docs/10-websocket.md`, "Market Depth Entry").
"""

import pytest

from broker.zerodha.api.data import BrokerData, _best_depth


class _FakeRow:
    """One `SymToken` row, as much of it as the two mappings read."""

    token = "0::::12345"
    brexchange = "NFO"

    def __getitem__(self, i):  # `_process_quotes_batch` queries a single column
        return self.brexchange


class _FakeQuery:
    def filter(self, *a, **kw):
        return self

    def first(self):
        return _FakeRow()


class _FakeSession:
    """Stands in for `db_session()`; the instrument table is not what is under
    test here and requiring one would make this an integration test."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def query(self, *a, **kw):
        return _FakeQuery()


# One NFO option leg as Kite returns it, trimmed to the fields the mapping
# reads. The bid and ask sizes differ from each other and from any lot size so
# a transposed or hard-coded value cannot pass.
KITE_QUOTE = {
    "last_price": 154.8,
    "volume": 36097555,
    "oi": 9376575,
    "ohlc": {"open": 151.9, "high": 164.95, "low": 115.5, "close": 173.0},
    "depth": {
        "buy": [
            {"price": 154.45, "quantity": 1950, "orders": 6},
            {"price": 154.40, "quantity": 325, "orders": 2},
        ],
        "sell": [
            {"price": 154.70, "quantity": 2275, "orders": 9},
            {"price": 154.75, "quantity": 650, "orders": 3},
        ],
    },
}


class TestBestDepth:
    """The helper both quote mappings read the top of book through."""

    def test_returns_the_first_level_of_each_side(self):
        bid, ask = _best_depth(KITE_QUOTE)
        assert bid["price"] == 154.45
        assert bid["quantity"] == 1950
        assert ask["price"] == 154.70
        assert ask["quantity"] == 2275

    @pytest.mark.parametrize(
        "quote",
        [
            {},
            {"depth": {}},
            {"depth": {"buy": [], "sell": []}},
            # Kite sends null rather than an empty list on some instruments.
            {"depth": {"buy": None, "sell": None}},
        ],
        ids=["no-depth-key", "empty-depth", "empty-sides", "null-sides"],
    )
    def test_an_instrument_with_no_book_yields_empty_rather_than_raising(self, quote):
        """An index or a restricted feed has no depth. That must not raise:
        the caller's own `.get(..., 0)` supplies the zero, and there a zero is
        honest because there genuinely is no book."""
        bid, ask = _best_depth(quote)
        assert bid == {}
        assert ask == {}
        assert bid.get("quantity", 0) == 0
        assert ask.get("quantity", 0) == 0


class TestQuoteMappingCarriesSize:
    """
    Both mappings are exercised through the real methods, with only the HTTP
    call and the symbol lookup replaced. Asserting on the dict a caller
    receives is what pins the defect; asserting on the helper alone would pass
    even if the mapping never called it.
    """

    @pytest.fixture
    def broker(self, monkeypatch):
        """The real methods, with only the two edges replaced: the HTTP call
        and the instrument-table lookup. Everything between them, which is the
        mapping under test, runs unmodified."""
        data = BrokerData(auth_token="test-token")
        monkeypatch.setattr(
            "broker.zerodha.api.data.get_api_response",
            lambda *a, **kw: {"data": {"NFO:NIFTY22SEP2623200PE": KITE_QUOTE}},
        )
        monkeypatch.setattr(
            "broker.zerodha.api.data.get_br_symbol", lambda s, e: "NIFTY22SEP2623200PE"
        )
        monkeypatch.setattr("broker.zerodha.api.data.db_session", _FakeSession)
        return data

    def test_get_quotes_reports_the_size_at_each_side(self, broker):
        quote = broker.get_quotes("NIFTY22SEP2623200PE", "NFO")

        # The defect: these two keys were absent entirely.
        assert "bid_qty" in quote, "bid_qty missing, so every consumer's .get default fires"
        assert "ask_qty" in quote, "ask_qty missing, so every consumer's .get default fires"
        assert quote["bid_qty"] == 1950
        assert quote["ask_qty"] == 2275

        # The prices were always right and must stay right.
        assert quote["bid"] == 154.45
        assert quote["ask"] == 154.70
        assert quote["ltp"] == 154.8
        assert quote["oi"] == 9376575

    def test_multiquotes_agrees_with_single_quotes(self, broker):
        """A caller cannot tell whether it reached one symbol or many, so a
        field present in one path and absent in the other is a difference it
        cannot act on."""
        rows = broker._process_quotes_batch([{"symbol": "NIFTY22SEP2623200PE", "exchange": "NFO"}])
        assert len(rows) == 1
        data = rows[0]["data"]
        assert data["bid_qty"] == 1950
        assert data["ask_qty"] == 2275
        assert data["bid"] == 154.45
        assert data["ask"] == 154.70


class TestOptionChainNoLongerDefaults:
    """
    The consumer that surfaced the bug. `option_chain_service` reads
    `quote.get("bid_qty", 0)`, so the contract it depends on is that the key
    exists. This asserts the service's own read against the mapping's output
    rather than re-testing the mapping.
    """

    def test_the_service_read_finds_a_real_size(self):
        bid, ask = _best_depth(KITE_QUOTE)
        quote = {"bid_qty": bid.get("quantity", 0), "ask_qty": ask.get("quantity", 0)}

        assert quote.get("bid_qty", 0) == 1950
        assert quote.get("ask_qty", 0) == 2275
        assert quote.get("bid_qty", 0) != 0, "a zero here reads as 'nothing on offer'"
