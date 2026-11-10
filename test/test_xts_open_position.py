"""Compositedge, 5paisa XTS, IIFL and Wisdom smart orders find the open position.

XTS answers ``GET /portfolio/positions`` with
``{"type": "success", "result": {"positionList": [...]}}`` and rows keyed
``TradingSymbol`` / ``ExchangeSegment`` / ``ProductType``. These four plugins
read it as ``{"status": ..., "data": [...]}`` with lowercase keys, a shape XTS
never sends, so ``get_open_position`` reported "0" for every position. A smart
exit was refused with "No OpenPosition Found" while the position stayed open,
a smart order to hold N bought N more, and /api/v1/openposition read 0.

RMoney had the same code and was fixed (#2292); the four now read the position
book as RMoney does, matching the instrument by ExchangeInstrumentID.

XTS's position book is faked with rows as XTS sends them.
"""

from __future__ import annotations

import importlib

import pytest

BROKERS = ["compositedge", "fivepaisaxts", "iifl", "wisdom"]
OPTION = "NIFTY27OCT2622400CE"


@pytest.fixture(params=BROKERS)
def api(request, monkeypatch):
    module = importlib.import_module(f"broker.{request.param}.api.order_api")
    # The contract list's entry for the option: its broker symbol and token.
    monkeypatch.setattr(module, "get_br_symbol", lambda symbol, exchange: "NIFTY26OCT22400CE")
    monkeypatch.setattr(module, "get_token", lambda symbol, exchange: "51326")
    return module


def _book(*positions):
    return {
        "type": "success",
        "code": "s-portfolio-0009",
        "description": "Success get position",
        "result": {"positionList": list(positions)},
    }


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


def _positions(api, monkeypatch, *positions):
    monkeypatch.setattr(api, "_get_cached_positions", lambda auth: _book(*positions))


def _smart(position_size, quantity, action="BUY"):
    return {
        "strategy": "Python",
        "symbol": OPTION,
        "exchange": "NFO",
        "action": action,
        "pricetype": "MARKET",
        "price": "0",
        "product": "NRML",
        "quantity": str(quantity),
        "position_size": str(position_size),
    }


def _record_orders(api, monkeypatch):
    sent = []
    monkeypatch.setattr(
        api,
        "place_order_api",
        lambda data, auth: sent.append(data) or ("answer", {"status": "success"}, "1"),
    )
    return sent


def test_a_long_position_is_found(api, monkeypatch):
    _positions(api, monkeypatch, _position())

    assert api.get_open_position(OPTION, "NFO", "NRML", "token") == "65"


def test_a_short_position_keeps_its_sign(api, monkeypatch):
    _positions(api, monkeypatch, _position(Quantity="-65"))

    assert api.get_open_position(OPTION, "NFO", "NRML", "token") == "-65"


def test_another_product_or_instrument_is_not_this_position(api, monkeypatch):
    _positions(
        api,
        monkeypatch,
        _position(ProductType="MIS"),
        _position(ExchangeInstrumentID=51327, TradingSymbol="NIFTY 27OCT2026 CE 22450"),
    )

    assert api.get_open_position(OPTION, "NFO", "NRML", "token") == "0"


def test_a_position_with_no_instrument_id_is_matched_by_name(api, monkeypatch):
    position = _position(TradingSymbol="NIFTY26OCT22400CE")
    del position["ExchangeInstrumentID"]
    _positions(api, monkeypatch, position)

    assert api.get_open_position(OPTION, "NFO", "NRML", "token") == "65"


def test_a_smart_exit_sells_the_whole_position(api, monkeypatch):
    _positions(api, monkeypatch, _position())
    sent = _record_orders(api, monkeypatch)

    api.place_smartorder_api(_smart(position_size=0, quantity=0, action="SELL"), "token")

    assert [(o["action"], o["quantity"]) for o in sent] == [("SELL", "65")]


def test_a_smart_order_already_at_its_size_places_nothing(api, monkeypatch):
    _positions(api, monkeypatch, _position())
    sent = _record_orders(api, monkeypatch)

    api.place_smartorder_api(_smart(position_size=65, quantity=65), "token")

    assert sent == []


def test_a_smart_reversal_sells_the_difference(api, monkeypatch):
    _positions(api, monkeypatch, _position())
    sent = _record_orders(api, monkeypatch)

    api.place_smartorder_api(_smart(position_size=-65, quantity=65, action="SELL"), "token")

    assert [(o["action"], o["quantity"]) for o in sent] == [("SELL", "130")]
