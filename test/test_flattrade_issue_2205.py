"""Regression contracts for GitHub issue #2205 (Flattrade log line every 5 seconds).

On a flat Flattrade account the terminal printed
"WARNING in order_data: No data available." every five seconds. The source is
the order-update poller: PiConnect allows one WebSocket session per user, so
Flattrade order updates come from websocket_proxy/order_adapter.py's
PollingOrderUpdateAdapter, which reads the order book every
ORDER_POLL_INTERVAL seconds (5 by default) through
services/orderbook_service.py -> map_order_data.

PiConnect answers an empty book with {"stat": "Not_Ok", "emsg": "no data"}.
#2206 demoted the second of the two lines each poll printed (transform_order_data's
"No orders found - empty list") and left map_order_data's warning, so one line
remained. The same branch also treated an expired session exactly like an empty
book, under the same message, which hid the one case worth a warning.

These tests pin both halves for the order, trade and position books: an empty
book is logged at debug only and maps to an empty result, and any other Not_Ok
is a warning that carries the broker's emsg.
"""

from __future__ import annotations

from unittest import mock

import pytest

from broker.flattrade.mapping import order_data as mapping

EMPTY_BOOK = {"stat": "Not_Ok", "emsg": "no data"}
SESSION_EXPIRED = {"stat": "Not_Ok", "emsg": "Session Expired :  Invalid Session Key"}

MAPPERS = [
    pytest.param(mapping.map_order_data, "order book", id="order_book"),
    pytest.param(mapping.map_trade_data, "trade book", id="trade_book"),
    pytest.param(mapping.map_position_data, "position book", id="position_book"),
]


@pytest.fixture
def log(monkeypatch):
    fake = mock.Mock()
    monkeypatch.setattr(mapping, "logger", fake)
    return fake


@pytest.mark.parametrize("mapper, book", MAPPERS)
def test_empty_book_logs_at_debug_only_and_maps_to_empty(log, mapper, book):
    assert not mapper(dict(EMPTY_BOOK))
    log.warning.assert_not_called()
    log.info.assert_not_called()
    log.debug.assert_called_once()
    assert book in log.debug.call_args.args[0]


@pytest.mark.parametrize("mapper, book", MAPPERS)
def test_session_expired_is_a_warning_carrying_the_emsg(log, mapper, book):
    assert not mapper(dict(SESSION_EXPIRED))
    log.warning.assert_called_once()
    message = log.warning.call_args.args[0]
    assert "Session Expired :  Invalid Session Key" in message
    assert book in message


@pytest.mark.parametrize("mapper, book", MAPPERS)
def test_none_response_is_a_warning(log, mapper, book):
    assert not mapper(None)
    log.warning.assert_called_once()
    assert book in log.warning.call_args.args[0]


def test_order_book_list_is_mapped_without_a_warning(log, monkeypatch):
    monkeypatch.setattr(mapping, "get_symbol", lambda token, exch: "SBIN")
    rows = [
        {
            "token": "3045",
            "exch": "NSE",
            "tsym": "SBIN-EQ",
            "prd": "I",
            "prctyp": "LMT",
            "prc": "800.00",
            "trantype": "B",
            "status": "OPEN",
        }
    ]

    [order] = mapping.map_order_data(rows)

    assert order["tsym"] == "SBIN"
    log.warning.assert_not_called()


@pytest.mark.parametrize(
    "mapper", [mapping.map_trade_data, mapping.map_position_data], ids=["trade", "position"]
)
def test_trade_and_position_lists_are_mapped_without_a_warning(log, monkeypatch, mapper):
    monkeypatch.setattr(mapping, "get_oa_symbol", lambda symbol, exch: "SBIN")
    rows = [{"tsym": "SBIN-EQ", "exch": "NSE", "prd": "C", "trantype": "B"}]

    [row] = mapper(rows)

    assert row["tsym"] == "SBIN"
    assert row["prd"] == "CNC"
    log.warning.assert_not_called()
