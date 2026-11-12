"""Kotak adapter against Kotak's docs and SDK (issue #2365).

Four gaps found comparing the adapter with Kotak's API docs and its Python SDK
(v3.0.13):

1. Holdings looked symbols up by instrumentToken, Kotak's own id, instead of
   exchangeIdentifier, the exchange token the master contract stores.
2. A margin error read "errMsg", but Kotak's error field is "emsg".
3. The position average was always rounded to 2 places, not to the row's
   "precision".
4. A carried cash-segment position was valued at Kotak's previous-settlement
   valuation even though its cost is in Holdings.
"""

import copy

import pytest

import broker.kotak.api.order_api as order_api
import broker.kotak.mapping.order_data as order_mapping
from broker.kotak.mapping.margin_data import parse_margin_response

AUTH = "sess:::sid-2365:::https://gw-napi.kotaksecurities.com:::acc"


# --- 1. Holdings symbol lookup -------------------------------------------------


def _holding(**overrides):
    # Kotak's documented example row: ITBEES, instrumentToken 18974,
    # exchangeIdentifier 19084. The NSE cash master stores pSymbol 19084.
    row = {
        "instrumentType": "Equity",
        "instrumentToken": 18974,
        "exchangeIdentifier": "19084",
        "displaySymbol": "ITBEES",
        "symbol": "ITBEES",
        "exchangeSegment": "nse_cm",
        "quantity": 45,
        "averagePrice": 38.7162,
        "holdingCost": 1742.2293,
        "mktValue": 1771.2,
    }
    row.update(overrides)
    return row


@pytest.fixture
def master(monkeypatch):
    lookups = []
    table = {("19084", "NSE"): "ITBEES", ("18974", "NSE"): "SOMEOTHERSCRIP"}

    def get_symbol(token, exchange):
        lookups.append((token, exchange))
        return table.get((str(token), exchange))

    monkeypatch.setattr(order_mapping, "get_symbol", get_symbol)
    return lookups


def test_holdings_look_up_the_exchange_token(master):
    holdings = order_mapping.map_portfolio_data({"data": [_holding()]})
    assert master == [("19084", "NSE")]
    [row] = order_mapping.transform_holdings_data(holdings)
    assert row["symbol"] == "ITBEES"


def test_holdings_report_the_openalgo_symbol_when_kotak_spells_it_differently(master):
    holdings = order_mapping.map_portfolio_data({"data": [_holding(displaySymbol="ITBEES-EQ")]})
    [row] = order_mapping.transform_holdings_data(holdings)
    assert row["symbol"] == "ITBEES"


def test_holdings_keep_the_display_symbol_when_the_master_has_no_row(master):
    holdings = order_mapping.map_portfolio_data(
        {"data": [_holding(exchangeIdentifier="99999", displaySymbol="NEWLISTING")]}
    )
    [row] = order_mapping.transform_holdings_data(holdings)
    assert row["symbol"] == "NEWLISTING"


# --- 2. Margin error text ------------------------------------------------------


def test_margin_error_reports_kotaks_reason():
    response = parse_margin_response({"stat": "Not_Ok", "emsg": "Invalid session", "stCode": 1003})
    assert response == {"status": "error", "message": "Invalid session"}


def test_margin_error_without_a_reason_keeps_the_generic_text():
    response = parse_margin_response({"stat": "Not_Ok", "stCode": 1003})
    assert response["message"] == "Failed to calculate margin"


# --- 3. Average price precision -------------------------------------------------


def _intraday(**overrides):
    row = {
        "trdSym": "USDINR26NOVFUT",
        "exSeg": "cde_fo",
        "prod": "NRML",
        "flBuyQty": "3",
        "flSellQty": "0",
        "cfBuyQty": "0",
        "cfSellQty": "0",
        "buyAmt": "250.3375",  # 83.4458333... per unit
        "sellAmt": "0",
    }
    row.update(overrides)
    return row


def test_average_is_rounded_to_the_row_precision():
    [row] = order_mapping.transform_positions_data([_intraday(precision="4")])
    assert row["average_price"] == 83.4458


def test_average_defaults_to_two_places_without_a_precision():
    [row] = order_mapping.transform_positions_data([_intraday()])
    assert row["average_price"] == 83.45


# --- 4. Carried cash-segment cost from Holdings ---------------------------------

# 100 SBIN carried overnight at Kotak's settlement valuation of 800.00 a share,
# none traded today. It was bought at 750.00, which only Holdings knows.
_CARRIED_EQUITY = {
    "trdSym": "SBIN-EQ",
    "exSeg": "nse_cm",
    "tok": "3045",
    "prod": "CNC",
    "flBuyQty": "0",
    "flSellQty": "0",
    "cfBuyQty": "100",
    "cfSellQty": "0",
    "buyAmt": "0",
    "sellAmt": "0",
    "cfBuyAmt": "80000.00",
    "cfSellAmt": "0",
    "upldPrc": "0.00",
}
# A carried option, which has no cost anywhere in Kotak's API.
_CARRIED_OPTION = {
    "trdSym": "NIFTY27OCT2622600CE",
    "exSeg": "nse_fo",
    "tok": "45001",
    "prod": "NRML",
    "flBuyQty": "0",
    "flSellQty": "0",
    "cfBuyQty": "0",
    "cfSellQty": "65",
    "buyAmt": "0",
    "sellAmt": "0",
    "cfBuyAmt": "0",
    "cfSellAmt": "13832.00",
    "upldPrc": "0.00",
}
_HOLDINGS = {
    "data": [
        {"exchangeIdentifier": "3045", "averagePrice": 750.0, "instrumentToken": 1},
        {"exchangeIdentifier": "11915", "averagePrice": 21.0, "instrumentToken": 2},
    ]
}


@pytest.fixture
def kotak(monkeypatch):
    """Positions and holdings endpoints stubbed; LTP backfill switched off."""
    calls = []
    responses = {
        "/quick/user/positions": {"stat": "Ok", "data": [_CARRIED_EQUITY, _CARRIED_OPTION]},
        "/portfolio/v1/holdings": _HOLDINGS,
    }

    def get_api_response(endpoint, auth_token, *args, **kwargs):
        calls.append(endpoint)
        response = responses[endpoint]
        if isinstance(response, Exception):
            raise response
        return copy.deepcopy(response)

    monkeypatch.setattr(order_api, "get_api_response", get_api_response)
    monkeypatch.setattr(order_api, "_backfill_ltp", lambda response, auth_token: None)
    order_api._holding_cost_cache.clear()
    yield calls, responses
    order_api._holding_cost_cache.clear()


def _book():
    raw = order_api.get_positions(AUTH)
    return {row["trdSym"]: row for row in raw["data"]}, raw


def test_carried_equity_is_valued_at_its_holdings_cost(kotak):
    rows, raw = _book()
    assert rows["SBIN-EQ"]["_holding_avg"] == 750.0

    [equity, _] = order_mapping.transform_positions_data(raw["data"])
    assert equity["average_price"] == 750.0
    assert "average_price_basis" not in equity


def test_carried_option_keeps_the_carry_forward_valuation(kotak):
    rows, raw = _book()
    assert "_holding_avg" not in rows["NIFTY27OCT2622600CE"]

    [_, option] = order_mapping.transform_positions_data(raw["data"])
    assert option["average_price"] == 212.8
    assert option["average_price_basis"] == "carry_forward_valuation"


def test_holdings_are_read_once_per_session_while_cached(kotak):
    calls, _ = kotak
    _book()
    _book()
    assert calls.count("/portfolio/v1/holdings") == 1


def test_holdings_are_not_read_without_a_carried_cash_row(kotak):
    calls, responses = kotak
    responses["/quick/user/positions"] = {"stat": "Ok", "data": [_CARRIED_OPTION]}
    _book()
    assert "/portfolio/v1/holdings" not in calls


def test_a_holdings_failure_leaves_the_carry_forward_valuation(kotak):
    _, responses = kotak
    responses["/portfolio/v1/holdings"] = RuntimeError("holdings down")
    rows, raw = _book()
    assert "_holding_avg" not in rows["SBIN-EQ"]

    [equity, _] = order_mapping.transform_positions_data(raw["data"])
    assert equity["average_price"] == 800.0
    assert equity["average_price_basis"] == "carry_forward_valuation"


def test_an_uploaded_price_still_wins_over_holdings(kotak):
    _, responses = kotak
    responses["/quick/user/positions"] = {
        "stat": "Ok",
        "data": [dict(_CARRIED_EQUITY, upldPrc="760.00")],
    }
    rows, raw = _book()
    assert "_holding_avg" not in rows["SBIN-EQ"]
    [equity] = order_mapping.transform_positions_data(raw["data"])
    assert equity["average_price"] == 760.0
