"""RMoney's smart orders find the open position by its instrument, not its name.

XTS names a position in its position book its own way, "NIFTY 27OCT2026 CE
22400", while the contract list's broker symbol for the same option is
"NIFTY26OCT22400CE". get_open_position compared the two names, so it found no
F&O position at all: every smart exit was refused with "No OpenPosition Found.
Not placing Exit order." while the position stayed open. The position book and
close all already match on ExchangeInstrumentID; the open position now does
too, and falls back to the name only for a position that carries no
instrument id.

XTS's position book is faked with a position row as XTS sends it.
"""

from __future__ import annotations

import pytest

import broker.rmoney.api.order_api as rmoney_api

OPTION = "NIFTY27OCT2622400CE"


def _book(*positions):
    return {"type": "success", "result": {"positionList": list(positions)}}


def _position(**fields):
    position = {
        "TradingSymbol": "NIFTY 27OCT2026 CE 22400",  # XTS's own name for the option
        "ExchangeSegment": "NSEFO",
        "ExchangeInstrumentID": 51326,
        "ProductType": "NRML",
        "Quantity": "65",
    }
    position.update(fields)
    return position


@pytest.fixture
def contract(monkeypatch):
    """The contract list's entry for the option: its broker symbol and token."""
    monkeypatch.setattr(rmoney_api, "get_br_symbol", lambda symbol, exchange: "NIFTY26OCT22400CE")
    monkeypatch.setattr(rmoney_api, "get_token", lambda symbol, exchange: "51326")


def _positions(monkeypatch, *positions):
    monkeypatch.setattr(rmoney_api, "_get_cached_positions", lambda auth: _book(*positions))


def test_an_option_position_is_found_by_its_instrument_whatever_xts_calls_it(contract, monkeypatch):
    _positions(monkeypatch, _position())

    assert rmoney_api.get_open_position(OPTION, "NFO", "NRML", "token") == "65"


def test_the_instrument_id_matches_however_xts_types_it(contract, monkeypatch):
    _positions(monkeypatch, _position(ExchangeInstrumentID="51326"))

    assert rmoney_api.get_open_position(OPTION, "NFO", "NRML", "token") == "65"


def test_another_product_of_the_same_option_is_not_this_position(contract, monkeypatch):
    _positions(monkeypatch, _position(ProductType="MIS"))

    assert rmoney_api.get_open_position(OPTION, "NFO", "NRML", "token") == "0"


def test_another_instrument_is_not_this_position(contract, monkeypatch):
    _positions(
        monkeypatch,
        _position(ExchangeInstrumentID=51327, TradingSymbol="NIFTY 27OCT2026 CE 22450"),
    )

    assert rmoney_api.get_open_position(OPTION, "NFO", "NRML", "token") == "0"


def test_a_position_with_no_instrument_id_is_matched_by_name(contract, monkeypatch):
    position = _position(TradingSymbol="NIFTY26OCT22400CE")
    del position["ExchangeInstrumentID"]
    _positions(monkeypatch, position)

    assert rmoney_api.get_open_position(OPTION, "NFO", "NRML", "token") == "65"


def test_a_smart_exit_sells_the_whole_position(contract, monkeypatch):
    # Closing a position with a smart order: quantity 0, position_size 0.
    _positions(monkeypatch, _position())
    sent = []
    monkeypatch.setattr(
        rmoney_api,
        "place_order_api",
        lambda data, auth: sent.append(data) or ("answer", {"status": "success"}, "1"),
    )

    rmoney_api.place_smartorder_api(
        {
            "strategy": "Python",
            "symbol": OPTION,
            "exchange": "NFO",
            "action": "SELL",
            "pricetype": "LIMIT",
            "price": "177.2",
            "product": "NRML",
            "quantity": "0",
            "position_size": "0",
        },
        "token",
    )

    assert [(o["action"], o["quantity"]) for o in sent] == [("SELL", "65")]
