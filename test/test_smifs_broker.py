"""SMIFS God Quant plugin: the behaviour the first review asked to see pinned.

Every test runs without a broker session. HTTP is replaced by a small fake
client, so the tests check what the plugin sends and how it reads replies,
including failed replies, which must never be shown as success.
"""

import uuid
from types import SimpleNamespace

import pytest

# Load the proxy first, as the other broker tests do.
import websocket_proxy  # noqa: F401  isort:skip

from broker.smifs.api import data as data_api
from broker.smifs.api import funds as funds_api
from broker.smifs.api import order_api
from broker.smifs.api.baseurl import REQUEST_TIMEOUT
from broker.smifs.database import master_contract_db as master
from broker.smifs.mapping.order_data import transform_order_data
from broker.smifs.mapping.transform_data import reverse_map_order_type, transform_modify_order_data
from utils import runtime


class _Reply:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body
        self.headers = {}

    def json(self):
        return self._body


class _Client:
    """Answers by path and records every call, including its timeout."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def _answer(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        for path, reply in self.routes.items():
            if path in url:
                return reply
        return _Reply(404, {"errorCode": "RS-4004", "errorMessage": "no such endpoint"})

    def get(self, url, **kwargs):
        return self._answer("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self._answer("POST", url, **kwargs)

    def request(self, method, url, **kwargs):
        return self._answer(method, url, **kwargs)


def _position(qty, product="INTRADAY"):
    return {
        "securityId": "3045",
        "tradingSymbol": "SBIN",
        "exchangeSegment": "NSE_EQ",
        "productType": product,
        "netQty": qty,
    }


# --- smart orders -------------------------------------------------------------


@pytest.fixture
def smart(monkeypatch):
    """place_smartorder_api against a position book the test sets."""
    state = SimpleNamespace(book=[], sent=[])
    monkeypatch.setattr(order_api, "get_token", lambda symbol, exchange: "3045")
    monkeypatch.setattr(order_api, "get_positions", lambda auth: state.book)

    def place(data, auth):
        state.sent.append(dict(data))
        return _Reply(200, {}), {"status": "success", "orderid": "1001"}, "1001"

    monkeypatch.setattr(order_api, "place_order_api", place)
    monkeypatch.setattr(runtime, "gthread_active", lambda: False)
    return state


def _smart_request(position_size, quantity=0, action="BUY"):
    return {
        "symbol": "SBIN",
        "exchange": "NSE",
        "product": "MIS",
        "pricetype": "MARKET",
        "action": action,
        "quantity": str(quantity),
        "position_size": str(position_size),
    }


def _auth():
    return f"tok-{uuid.uuid4().hex}"


def test_a_flat_account_with_no_target_places_the_requested_entry(smart):
    _, response, orderid = order_api.place_smartorder_api(_smart_request(0, 5), _auth())

    assert orderid == "1001"
    assert smart.sent == [_smart_request(0, 5)]
    assert response["status"] == "success"


def test_a_matched_target_places_nothing_and_says_so(smart):
    smart.book = [_position(10)]

    res, response, orderid = order_api.place_smartorder_api(_smart_request(10, 5), _auth())

    assert (res, orderid) == (None, None)
    assert response == {
        "status": "success",
        "message": "No action needed. Position size matches current position",
    }
    assert smart.sent == []


def test_an_exit_with_no_position_places_nothing(smart):
    res, response, orderid = order_api.place_smartorder_api(_smart_request(0, 0), _auth())

    assert (res, orderid) == (None, None)
    assert response["message"] == "No OpenPosition Found. Not placing Exit order."
    assert smart.sent == []


def test_a_reversal_sells_the_long_and_the_new_short_in_one_order(smart):
    smart.book = [_position(10)]

    order_api.place_smartorder_api(_smart_request(-5, 5), _auth())

    assert len(smart.sent) == 1
    assert smart.sent[0]["action"] == "SELL"
    assert smart.sent[0]["quantity"] == "15"


def test_a_position_held_in_another_product_is_not_counted(smart):
    smart.book = [_position(10, product="CNC")]

    order_api.place_smartorder_api(_smart_request(5, 5), _auth())

    assert smart.sent[0]["action"] == "BUY"
    assert smart.sent[0]["quantity"] == "5"


def test_a_failed_position_read_refuses_the_smart_order(smart):
    smart.book = {"status": "error", "message": "AU-1001: missing or invalid access token"}

    res, response, orderid = order_api.place_smartorder_api(_smart_request(-5, 5), _auth())

    assert (res, orderid) == (None, None)
    assert response["status"] == "error"
    assert smart.sent == []


# --- stop-loss round trip -----------------------------------------------------


def test_stop_loss_types_survive_a_read_modify_round_trip(monkeypatch):
    monkeypatch.setattr(
        "broker.smifs.mapping.order_data.get_symbol", lambda token, exchange: "SBIN"
    )
    book = transform_order_data(
        [
            {
                "orderId": "1",
                "securityId": "3045",
                "exchangeSegment": "NSE_EQ",
                "transactionType": "SELL",
                "productType": "INTRADAY",
                "orderType": order_type,
                "orderStatus": "PENDING",
                "quantity": 10,
                "price": 818.0 if order_type == "STOP_LOSS" else 0,
                "triggerPrice": 820.0,
            }
            for order_type in ("STOP_LOSS", "STOP_LOSS_MARKET")
        ]
    )

    assert [row["pricetype"] for row in book] == ["SL", "SL-M"]
    for row, expected in zip(book, ("STOP_LOSS", "STOP_LOSS_MARKET"), strict=True):
        edited = transform_modify_order_data(
            {
                "pricetype": row["pricetype"],
                "quantity": "10",
                "price": "818",
                "trigger_price": "819",
            }
        )
        assert edited["orderType"] == expected
        assert edited["triggerPrice"] == 819.0
    assert reverse_map_order_type("STOP_LOSS_MARKET") == "SL-M"


# --- master contract ------------------------------------------------------------


@pytest.mark.parametrize(
    "row, symbol, exchange, expiry, strike, itype",
    [
        (
            {
                "exchangeSegment": "NSE_FNO",
                "securityId": "37279",
                "symbol": "NIFTY",
                "instrumentType": "OPT",
                "expiry": "2026-10-27",
                "strike": 25000.0,
                "optionType": "CE",
                "lotSize": 75,
            },
            "NIFTY27OCT2625000CE",
            "NFO",
            "27-OCT-26",
            25000.0,
            "CE",
        ),
        (
            {
                "exchangeSegment": "NSE_FNO",
                "securityId": "49081",
                "symbol": "NIFTY",
                "instrumentType": "FUT",
                "expiry": "2026-10-27",
                "lotSize": 75,
            },
            "NIFTY27OCT26FUT",
            "NFO",
            "27-OCT-26",
            0.0,
            "FUT",
        ),
        (
            {
                "exchangeSegment": "MCX_COMM",
                "securityId": "426268",
                "symbol": "GOLDM",
                "instrumentType": "FUTCOM",
                "expiry": "2026-11-05",
                "lotSize": 10,
            },
            "GOLDM05NOV26FUT",
            "MCX",
            "05-NOV-26",
            0.0,
            "FUT",
        ),
        (
            {
                "exchangeSegment": "BSE_FNO",
                "securityId": "1155",
                "symbol": "SENSEX",
                "instrumentType": "OPT",
                "expiry": "2026-10-29",
                "strike": 8000000.0,
                "optionType": "PE",
                "lotSize": 20,
            },
            "SENSEX29OCT2680000PE",
            "BFO",
            "29-OCT-26",
            80000.0,
            "PE",
        ),
    ],
)
def test_derivative_rows_become_openalgo_symbols(row, symbol, exchange, expiry, strike, itype):
    rec = master.to_openalgo(row)

    assert rec["symbol"] == symbol
    assert rec["exchange"] == exchange
    assert rec["expiry"] == expiry
    assert rec["strike"] == strike
    assert rec["instrumenttype"] == itype


class _Session:
    def __init__(self, fail_on):
        self.fail_on = fail_on
        self.events = []

    def query(self, _model):
        session = self

        class _Query:
            def delete(self):
                session.events.append("delete")

        return _Query()

    def bulk_insert_mappings(self, _model, records):
        self.events.append("insert")
        if self.fail_on == "insert":
            raise RuntimeError("disk full")

    def commit(self):
        self.events.append("commit")
        if self.fail_on == "commit":
            raise RuntimeError("database is locked")

    def rollback(self):
        self.events.append("rollback")

    def remove(self):
        self.events.append("remove")


@pytest.mark.parametrize("fail_on", ["insert", "commit"])
def test_a_failed_save_rolls_back_and_releases_the_session(monkeypatch, fail_on):
    session = _Session(fail_on)
    monkeypatch.setattr(master, "db_session", session)
    monkeypatch.setattr(master, "SymToken", object())
    monkeypatch.setattr(master, "socketio", None)
    monkeypatch.setattr(master, "download_rows", lambda: [])

    result = master.master_contract_download()

    assert result["status"] == "error"
    assert session.events[-2:] == ["rollback", "remove"]


def test_a_successful_save_still_releases_the_session(monkeypatch):
    session = _Session(fail_on=None)
    monkeypatch.setattr(master, "db_session", session)
    monkeypatch.setattr(master, "SymToken", object())
    monkeypatch.setattr(master, "socketio", None)
    monkeypatch.setattr(master, "download_rows", lambda: [])

    assert master.master_contract_download()["status"] == "success"
    assert session.events == ["delete", "insert", "commit", "remove"]


# --- failures are errors, never fabricated success -------------------------------


@pytest.mark.parametrize("status", [401, 403, 500, 503])
def test_funds_raise_instead_of_reporting_a_zero_balance(monkeypatch, status):
    client = _Client(
        {
            "/v1/funds/limits": _Reply(
                status, {"errorCode": "AU-1001", "errorMessage": "missing or invalid access token"}
            )
        }
    )
    monkeypatch.setattr(funds_api, "get_httpx_client", lambda: client)

    with pytest.raises(Exception, match="funds/limits failed"):
        funds_api.get_margin_data("tok")


def test_funds_add_up_the_days_profit(monkeypatch):
    client = _Client(
        {
            "/v1/funds/limits": _Reply(
                200, {"availableBalance": 1000000.0, "utilizedAmount": 2500.0}
            ),
            "/v1/positions": _Reply(
                200,
                [
                    {**_position(10), "realizedProfit": 120.5, "unrealizedProfit": -20.0},
                    {**_position(0), "realizedProfit": 30.0, "unrealizedProfit": 0.0},
                ],
            ),
        }
    )
    monkeypatch.setattr(funds_api, "get_httpx_client", lambda: client)

    funds = funds_api.get_margin_data("tok")

    assert funds["availablecash"] == "1000000.00"
    assert funds["m2mrealized"] == "150.50"
    assert funds["m2munrealized"] == "-20.00"


@pytest.mark.parametrize("status", [401, 403, 500])
def test_a_failed_quote_raises_instead_of_reporting_a_zero_price(monkeypatch, status):
    client = _Client({"/v1/marketfeed/quote": _Reply(status, {"errorCode": "AU-1001"})})
    monkeypatch.setattr(data_api, "get_httpx_client", lambda: client)
    monkeypatch.setattr(data_api, "get_token", lambda symbol, exchange: "2885")

    with pytest.raises(Exception, match="marketfeed/quote failed"):
        data_api.BrokerData("tok").get_quotes("RELIANCE", "NSE")


def test_a_quote_carries_the_previous_close(monkeypatch):
    client = _Client(
        {
            "/v1/marketfeed/quote": _Reply(
                200,
                {
                    "data": {
                        "NSE_EQ": {
                            "2885": {
                                "last_price": 2955.75,
                                "ohlc": {"open": 2948, "high": 2960, "low": 2940, "close": 2950},
                                "depth": {"buy": [], "sell": []},
                            }
                        }
                    },
                    "status": "success",
                },
            )
        }
    )
    monkeypatch.setattr(data_api, "get_httpx_client", lambda: client)
    monkeypatch.setattr(data_api, "get_token", lambda symbol, exchange: "2885")

    quote = data_api.BrokerData("tok").get_quotes("RELIANCE", "NSE")

    assert quote["ltp"] == 2955.75
    assert quote["prev_close"] == 2950


def test_close_all_reports_failure_when_the_position_book_cannot_be_read(monkeypatch):
    monkeypatch.setattr(
        order_api, "get_positions", lambda auth: {"status": "error", "message": "AU-1001"}
    )
    placed = []
    monkeypatch.setattr(order_api, "_post_order", lambda payload, auth: placed.append(payload))

    response, status = order_api.close_all_positions("key", "tok")

    assert status == 500
    assert response["status"] == "error"
    assert placed == []


def test_close_all_reports_each_rejected_exit(monkeypatch):
    monkeypatch.setattr(order_api, "get_positions", lambda auth: [_position(10)])

    def reject(payload, auth):
        return _Reply(400, {}), {"status": "error", "message": "OD-1013: market closed"}, None

    monkeypatch.setattr(order_api, "_post_order", reject)

    response, status = order_api.close_all_positions("key", "tok")

    assert status == 500
    assert "SBIN" in response["message"] and "OD-1013" in response["message"]


# --- every call has a timeout ---------------------------------------------------


def test_every_http_call_sets_an_explicit_timeout(monkeypatch):
    client = _Client(
        {
            "/v1/funds/limits": _Reply(200, {"availableBalance": 1.0}),
            "/v1/positions": _Reply(200, []),
            "/v1/orders": _Reply(200, []),
            "/v1/marketfeed/quote": _Reply(200, {"data": {"NSE_EQ": {"2885": {"last_price": 1}}}}),
        }
    )
    for module in (funds_api, order_api, data_api):
        monkeypatch.setattr(module, "get_httpx_client", lambda: client)
    monkeypatch.setattr(data_api, "get_token", lambda symbol, exchange: "2885")

    funds_api.get_margin_data("tok")
    order_api.get_order_book("tok")
    data_api.BrokerData("tok").get_quotes("RELIANCE", "NSE")

    assert client.calls
    assert all(kwargs.get("timeout") == REQUEST_TIMEOUT for _m, _u, kwargs in client.calls)
