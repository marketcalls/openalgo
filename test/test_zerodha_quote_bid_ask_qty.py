"""Zerodha quotes carry the size at the best bid and ask.

Kite's /quote response reports the top of the book under depth.buy[0] and
depth.sell[0], price and quantity together. get_quotes and
_process_quotes_batch read only the prices, so /api/v1/quotes,
/api/v1/multiquotes and every /api/v1/optionchain leg reported bid_qty and
ask_qty as 0 on Zerodha (issue #2045). The Option Chain page hid it, because
its live depth feed overwrites both fields on every tick; any API client
polling the REST endpoints saw the zeros.

The HTTP call and the symbol lookups are replaced, so this runs without a Kite
session or a master contract.
"""

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

import broker.zerodha.api.data as zdata

# A Kite /quote entry, trimmed to the fields the mapping reads. Taken from the
# GOLDM25SEP26154000CE depth quoted in the issue.
KITE_QUOTE = {
    "last_price": 3035.5,
    "volume": 1200,
    "oi": 340,
    "ohlc": {"open": 3000.0, "high": 3050.0, "low": 2990.0, "close": 3010.0},
    "depth": {
        "buy": [
            {"price": 2982.5, "quantity": 1, "orders": 1},
            {"price": 2982.0, "quantity": 3, "orders": 2},
        ],
        "sell": [
            {"price": 2999.5, "quantity": 6, "orders": 3},
            {"price": 3000.0, "quantity": 2, "orders": 1},
        ],
    },
}


class FakeSession:
    """Answers the one-row SymToken lookups both code paths make."""

    def __init__(self, row):
        self._row = row

    def query(self, *args, **kwargs):
        return self

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self._row


def patch_lookups(monkeypatch, row, quote_key, quote):
    @contextmanager
    def fake_db_session():
        yield FakeSession(row)

    monkeypatch.setattr(zdata, "db_session", fake_db_session)
    monkeypatch.setattr(zdata, "get_br_symbol", lambda symbol, exchange: symbol)
    monkeypatch.setattr(zdata, "_kite_quote_exchange", lambda exchange, brexchange: exchange)
    monkeypatch.setattr(
        zdata,
        "get_api_response",
        lambda endpoint, auth, **kwargs: {"status": "success", "data": {quote_key: quote}},
    )


def test_get_quotes_reports_top_of_book_size(monkeypatch):
    row = SimpleNamespace(token="123::::456", brexchange="MCX")
    patch_lookups(monkeypatch, row, "MCX:GOLDM25SEP26154000CE", KITE_QUOTE)

    quote = zdata.BrokerData("token").get_quotes("GOLDM25SEP26154000CE", "MCX")

    assert quote["bid"] == 2982.5
    assert quote["ask"] == 2999.5
    assert quote["bid_qty"] == 1
    assert quote["ask_qty"] == 6


def test_multiquotes_batch_reports_top_of_book_size(monkeypatch):
    patch_lookups(monkeypatch, ("NFO",), "NFO:NIFTY25SEP2624000CE", KITE_QUOTE)

    (result,) = zdata.BrokerData("token")._process_quotes_batch(
        [{"symbol": "NIFTY25SEP2624000CE", "exchange": "NFO"}]
    )

    assert result["data"]["bid"] == 2982.5
    assert result["data"]["ask"] == 2999.5
    assert result["data"]["bid_qty"] == 1
    assert result["data"]["ask_qty"] == 6


@pytest.mark.parametrize(
    "depth",
    [
        {},  # no depth at all
        {"buy": [], "sell": []},  # empty book, e.g. an illiquid strike
    ],
)
def test_missing_depth_reports_zero_instead_of_raising(depth):
    top = zdata._best_bid_ask({"depth": depth})

    assert top == {"bid": 0, "ask": 0, "bid_qty": 0, "ask_qty": 0}


def test_other_quote_fields_are_unchanged(monkeypatch):
    """The fix adds two keys; everything the mapping returned before stays put."""
    row = SimpleNamespace(token="123::::456", brexchange="MCX")
    patch_lookups(monkeypatch, row, "MCX:GOLDM25SEP26154000CE", KITE_QUOTE)

    quote = zdata.BrokerData("token").get_quotes("GOLDM25SEP26154000CE", "MCX")

    assert quote == {
        "ask": 2999.5,
        "bid": 2982.5,
        "ask_qty": 6,
        "bid_qty": 1,
        "high": 3050.0,
        "low": 2990.0,
        "ltp": 3035.5,
        "open": 3000.0,
        "prev_close": 3010.0,
        "volume": 1200,
        "oi": 340,
    }
