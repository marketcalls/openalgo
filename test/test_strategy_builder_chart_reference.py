"""Auxiliary Strategy Builder charts use the exact backend-resolved reference."""

from unittest.mock import Mock

import pytest

from services import (
    multi_strike_oi_service,
    strategy_builder_reference_service,
    strategy_chart_service,
)

LEG = {
    "symbol": "TEST27AUG26100CE",
    "exchange": "MCX",
    "side": "BUY",
    "segment": "OPTION",
    "active": True,
    "price": 10,
    "strike": 100,
    "optionType": "CE",
    "expiry": "27AUG26",
}


def history_response(*, symbol, exchange, **_kwargs):
    row = {"timestamp": 1_700_000_000, "close": 100}
    if symbol == LEG["symbol"]:
        row["oi"] = 1_000
    return True, {"status": "success", "data": [row]}, 200


@pytest.mark.parametrize(
    ("module", "service"),
    [
        (strategy_chart_service, strategy_chart_service.get_strategy_chart_data),
        (multi_strike_oi_service, multi_strike_oi_service.get_multi_strike_oi_data),
    ],
)
def test_mcx_latest_quote_uses_the_same_resolved_future_as_history(monkeypatch, module, service):
    history = Mock(side_effect=history_response)
    quote = Mock(return_value=(True, {"data": {"ltp": 101}}, 200))
    monkeypatch.setattr(module, "get_history", history)
    monkeypatch.setattr(module, "get_quotes", quote)
    monkeypatch.setattr(
        strategy_builder_reference_service,
        "resolve_underlying_quote",
        lambda _base, _exchange: ("CRUDEOIL27AUG26FUT", "MCX"),
    )

    success, _response, status = service(
        underlying="CRUDEOIL",
        exchange="MCX",
        legs=[LEG],
        interval="5m",
        api_key="key",
        days=1,
    )

    assert success is True
    assert status == 200
    first_history = history.call_args_list[0].kwargs
    assert (first_history["symbol"], first_history["exchange"]) == (
        "CRUDEOIL27AUG26FUT",
        "MCX",
    )
    quote.assert_called_once_with(symbol="CRUDEOIL27AUG26FUT", exchange="MCX", api_key="key")


@pytest.mark.parametrize(
    ("module", "service"),
    [
        (strategy_chart_service, strategy_chart_service.get_strategy_chart_data),
        (multi_strike_oi_service, multi_strike_oi_service.get_multi_strike_oi_data),
    ],
)
def test_crypto_uses_option_chain_canonical_reference(monkeypatch, module, service):
    history = Mock(side_effect=history_response)
    quote = Mock(return_value=(True, {"data": {"ltp": 101}}, 200))
    monkeypatch.setattr(module, "get_history", history)
    monkeypatch.setattr(module, "get_quotes", quote)

    success, _response, status = service(
        underlying="BTC",
        exchange="CRYPTO",
        underlying_symbol="BTCUSDFUT",
        underlying_exchange="CRYPTO",
        legs=[{**LEG, "exchange": "CRYPTO"}],
        interval="5m",
        api_key="key",
        days=1,
    )

    assert success is True
    assert status == 200
    first_history = history.call_args_list[0].kwargs
    assert (first_history["symbol"], first_history["exchange"]) == (
        "BTCUSDFUT",
        "CRYPTO",
    )
    quote.assert_called_once_with(symbol="BTCUSDFUT", exchange="CRYPTO", api_key="key")


@pytest.mark.parametrize(
    ("module", "service"),
    [
        (strategy_chart_service, strategy_chart_service.get_strategy_chart_data),
        (multi_strike_oi_service, multi_strike_oi_service.get_multi_strike_oi_data),
    ],
)
def test_crypto_without_canonical_fields_resolves_perpetual_reference(monkeypatch, module, service):
    history = Mock(side_effect=history_response)
    quote = Mock(return_value=(True, {"data": {"ltp": 101}}, 200))
    perpetual_search = Mock(return_value=[{"symbol": "BTCUSDFUT", "exchange": "CRYPTO"}])
    monkeypatch.setattr(module, "get_history", history)
    monkeypatch.setattr(module, "get_quotes", quote)
    monkeypatch.setattr(
        strategy_builder_reference_service,
        "fno_search_symbols",
        perpetual_search,
        raising=False,
    )

    success, _response, status = service(
        underlying="BTC",
        exchange="CRYPTO",
        legs=[{**LEG, "exchange": "CRYPTO"}],
        interval="5m",
        api_key="key",
        days=1,
    )

    assert success is True
    assert status == 200
    first_history = history.call_args_list[0].kwargs
    assert (first_history["symbol"], first_history["exchange"]) == (
        "BTCUSDFUT",
        "CRYPTO",
    )
    quote.assert_called_once_with(symbol="BTCUSDFUT", exchange="CRYPTO", api_key="key")
    perpetual_search.assert_called_once_with(
        query="BTCUSDFUT",
        exchange="CRYPTO",
        instrumenttype="PERPFUT",
        limit=1,
    )
