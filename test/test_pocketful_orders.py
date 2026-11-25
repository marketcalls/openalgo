"""Pocketful orders, books, positions and holdings on the new API (algo.pocketful.in).

Every request goes through baseurl.pocketful_request, which these tests replace
with an in-memory Pocketful answering with the examples from Pocketful's API
documentation (offline copy of 2026-11-17). No account, no network.

What is pinned:

- the client id every call carries comes from the stored token, never from
  the browser session (an API or strategy order has none);
- Pocketful takes only LIMIT and SL from the API (annexure.md), so MARKET goes
  out as a protected LIMIT and SL-M as an SL whose limit sits beyond its own
  trigger, and an order OpenAlgo cannot price is refused before it is sent;
- positions are read netwise (type=historical), and a smart order never sizes
  itself against a position it could not read;
- the order book's pending and completed lists merge into OpenAlgo's statuses,
  and the books come out in the documented common shapes;
- close-all prices every square-off, and one that fails stops neither the
  others nor the report of it.
"""

import json
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
from flask import Flask, session

import broker.pocketful.api.baseurl as base
import broker.pocketful.api.order_api as oa
import broker.pocketful.mapping.order_data as od
import broker.pocketful.mapping.transform_data as td
from broker.pocketful.api.baseurl import PocketfulResponse
from broker.pocketful.api.data import BrokerData
from utils.position_read import position_read_failed_message
from utils.smart_order_guard import PositionBookCache

CLIENT = "DEMO1"
AUTH = base.pack_token(CLIENT, "jwt.access.token")
OPTION = "NIFTY25NOV2524000CE"

# OpenAlgo symbol -> (broker symbol, token, tick size)
MASTER = {
    ("SBIN", "NSE"): ("SBIN-EQ", "3045", 0.05),
    ("YESBANK", "NSE"): ("YESBANK-EQ", "11915", 0.01),
    ("IDEA", "NSE"): ("IDEA-EQ", "14366", 0.01),
    ("PENNY", "NSE"): ("PENNY-EQ", "777", 0.01),
    (OPTION, "NFO"): ("NIFTY25NOV24000CE", "45000", 0.05),
    ("COFORGE24MAR5700PE", "NFO"): ("COFORGE24MAR5700PE", "100803", 0.05),
    ("PNB", "BSE"): ("PNB-A", "532461", 0.05),
    ("GOLDGUINEA20NOVFUT", "MCX"): ("GOLDGUINEA20NOVFUT", "222895", 1.0),
    ("UNTICKED", "NSE"): ("UNTICKED-EQ", "999", None),
}
BY_BRSYMBOL = {(br, ex): sym for (sym, ex), (br, _, _) in MASTER.items()}
BY_TOKEN = {(tok, ex): sym for (sym, ex), (_, tok, _) in MASTER.items()}


# --------------------------------------------------------------------------
# The documentation's examples
# --------------------------------------------------------------------------

PLACE_OK = {
    "data": {"oms_order_id": "200018000000003"},
    "message": "Order place successfully",
    "status": "success",
}
PLACE_ERROR = {
    "data": {},
    "error_code": 44000,
    "message": "`product` is invalid",
    "status": "error",
}
MODIFY_OK = {
    "data": {"oms_order_id": "202403111778"},
    "message": "Order modification request submitted",
    "status": "success",
}
CANCEL_OK = {
    "data": {"oms_order_id": "202403111506"},
    "message": "Order cancellation request submitted for OMS Order: 202403111506",
    "status": "success",
}
UNAUTHORISED = {
    "status": "error",
    "message": "Request Unauthorised",
    "error_code": 40000,
    "data": {},
}
FORBIDDEN = {"status": "error", "message": "Request forbidden", "error_code": 40000, "data": {}}

_ORDER_ROW = {
    "mode": "NEW",
    "segment": "",
    "login_id": CLIENT,
    "deposit": 0,
    "rejection_reason": "",
    "nnf_id": 333333333333100,
    "client_id": CLIENT,
    "underlying_token": None,
    "disclosed_quantity": 0,
    "source": "pacetrader.pacefin.in",
    "device": "android",
    "exchange_order_id": "",
    "validity": "DAY",
    "leg_order_indicator": None,
    "trade_price": 0,
    "spread_token": None,
    "market_protection_percentage": 0,
    "order_tag": "",
    "sl_trigger_price": 0.0,
    "square_off": False,
    "order_status_info": "",
    "square_off_value": 0.0,
    "tags": None,
    "last_activity_reference": 0,
    "sl_order_price": 0.0,
    "stop_loss_value": 0.0,
    "rejection_code": 0,
    "trailing_stop_loss": 0.0,
    "is_trailing": False,
    "pro_cli": "CLIENT",
    "contract_description": {},
    "target_price_type": "absolute",
    "sl_order_quantity": 0,
}

# fetch-pending-orders.md
PENDING_ORDER = {
    **_ORDER_ROW,
    "exchange": "NFO",
    "order_status": "AMO_MODIFY_CONFIRMED",
    "product": "NRML",
    "order_type": "LIMIT",
    "order_side": "BUY",
    "instrument_token": 100803,
    "exchange_time": 1709996020,
    "quantity": 1500,
    "trading_symbol": "COFORGE24MAR5700PE",
    "average_trade_price": 0,
    "oms_order_id": "2024030943",
    "lot_size": 150,
    "isin": "",
    "execution_type": "AMO",
    "filled_quantity": 0,
    "order_entry_time": 1709995984,
    "trigger_price": 0,
    "average_price": 0,
    "price": 30.7,
    "user_order_id": "12780",
    "symbol": "COFORGE",
    "remaining_quantity": 1500,
    "series": "OPTSTK",
}

# fetch-completed-orders.md
COMPLETED_ORDER = {
    **_ORDER_ROW,
    "exchange": "BSE",
    "order_status": "AMO_CANCEL_CONFIRMED",
    "product": "CNC",
    "order_type": "LIMIT",
    "order_side": "BUY",
    "instrument_token": 532461,
    "exchange_time": 0,
    "quantity": 1,
    "trading_symbol": "PNB-A",
    "average_trade_price": 0,
    "oms_order_id": "2024030935",
    "lot_size": 1,
    "isin": "INE160A01022",
    "execution_type": "AMO",
    "filled_quantity": 0,
    "order_entry_time": 1709992420,
    "trigger_price": 0,
    "average_price": 0,
    "price": 125.0,
    "user_order_id": "12776",
    "symbol": "PNB",
    "remaining_quantity": 0,
    "series": "A",
}

# trade-book.md (its rows sit under data.orders)
TRADE_ROW = {
    **_ORDER_ROW,
    "exchange": "NSE",
    "order_status": "CONFIRMED",
    "product": "MIS",
    "order_type": "LIMIT",
    "rejection_reason": "NONE",
    "order_side": "BUY",
    "instrument_token": 14366,
    "exchange_time": 1710485885,
    "nnf_id": 111111111111100,
    "quantity": 1,
    "trading_symbol": "IDEA-EQ",
    "average_trade_price": 0,
    "oms_order_id": "202403152052",
    "lot_size": 1,
    "isin": "INE669E01016",
    "execution_type": "REGULAR",
    "source": "",
    "device": "",
    "exchange_order_id": "1100000029886168",
    "trade_price": 0,
    "filled_quantity": 0,
    "order_entry_time": 1710485885,
    "last_activity_reference": 1394972885476889600,
    "trigger_price": 0,
    "average_price": 0,
    "price": 11.9,
    "user_order_id": "10002",
    "symbol": "IDEA",
    "remaining_quantity": 1,
    "series": "EQ",
}

# fetch-position-daywise.md
DAYWISE_ROW = {
    "average_buy_price": 14.7,
    "average_price": 0,
    "average_sell_price": 0,
    "buy_amount": 14.7,
    "buy_quantity": 1,
    "cf_buy_amount": 0,
    "cf_buy_quantity": 0,
    "cf_sell_amount": 0,
    "cf_sell_quantity": 0,
    "client_id": CLIENT,
    "close_price": 0,
    "exchange": "NSE",
    "instrument_token": 11915,
    "ltp": 14.6,
    "multiplier": 1,
    "net_amount": -14.7,
    "net_quantity": 1,
    "previous_close": 14.65,
    "pro_cli": "CLIENT",
    "prod_type": 2,
    "product": "MIS",
    "realized_mtm": 0,
    "segment": "Capital",
    "sell_amount": 0,
    "sell_quantity": 0,
    "symbol": "YESBANK",
    "token": 11915,
    "trading_symbol": "YESBANK-EQ",
    "v_login_id": CLIENT,
}

# fetch-position-netwise.md
NETWISE_ROW = {
    "average_buy_price": 40520,
    "average_price": 0,
    "average_sell_price": 40538,
    "buy_amount": 40520,
    "buy_quantity": 1,
    "cf_buy_amount": 0,
    "cf_buy_quantity": 0,
    "cf_sell_amount": 0,
    "cf_sell_quantity": 0,
    "client_id": CLIENT,
    "close_price": 0,
    "exchange": "MCX",
    "instrument_token": 222895,
    "ltp": 40520,
    "multiplier": 1,
    "net_amount": 18,
    "net_quantity": 0,
    "previous_close": 40697,
    "pro_cli": "CLIENT",
    "prod_type": 0,
    "product": "NRML",
    "realized_mtm": 0,
    "segment": "FutOpt",
    "sell_amount": 40538,
    "sell_quantity": 1,
    "symbol": "GOLDGUINEA",
    "token": 222895,
    "trading_symbol": "GOLDGUINEA20NOVFUT",
    "v_login_id": CLIENT,
}

# fetch-demat-holdings.md
HOLDING_ROW = {
    "branch_code": "",
    "buy_avg": 240.2,
    "buy_avg_mtm": 277.7500000000006,
    "client_id": CLIENT,
    "exchange": "NSE",
    "free_quantity": 55,
    "instrument_details": {
        "exchange": 1,
        "instrument_name": "EQ",
        "instrument_token": 3045,
        "trading_symbol": "SBIN-EQ",
    },
    "isin": "INE062A01020",
    "ltp": 245.25,
    "pending_quantity": 0,
    "pledge_quantity": 0,
    "previous_close": 240.2,
    "quantity": 55,
    "symbol": "SBIN",
    "t0_price": 0,
    "t0_quantity": 0,
    "t1_price": 0,
    "t1_quantity": 0,
    "t2_price": 0,
    "t2_quantity": 0,
    "today_pledge_quantity": 0,
    "token": 3045,
    "trading_symbol": "SBIN",
    "transaction_type": "",
    "used_quantity": 0,
}


def _ok(data):
    return {"data": data, "message": "", "status": "success"}


def _position(symbol, exchange, net, product="MIS", **extra):
    br, token, _ = MASTER[(symbol, exchange)]
    return {
        **DAYWISE_ROW,
        "exchange": exchange,
        "trading_symbol": br,
        "instrument_token": int(token),
        "token": int(token),
        "product": product,
        "net_quantity": net,
        **extra,
    }


# --------------------------------------------------------------------------
# The in-memory Pocketful
# --------------------------------------------------------------------------


class FakePocketful:
    """Stands in for baseurl.pocketful_request: answers by (method, path,
    type) and records every request."""

    def __init__(self):
        self.calls = []
        self.routes = {}

    def on(self, method, path, body, status=200, kind=None):
        self.routes[(method, path, kind)] = (status, body)

    def fail(self, method, path, error, kind=None):
        self.routes[(method, path, kind)] = error

    def __call__(self, method, path, token, params=None, payload=None, timeout=None):
        call = SimpleNamespace(
            method=method.upper(), path=path, token=token, params=params or {}, payload=payload
        )
        self.calls.append(call)
        kind = call.params.get("type")
        answer = self.routes.get(
            (call.method, path, kind), self.routes.get((call.method, path, None))
        )
        if answer is None:
            return PocketfulResponse(404, {"status": "error", "message": "not mocked"}, "")
        if isinstance(answer, Exception):
            raise answer
        status, body = answer
        text = json.dumps(body) if body is not None else "<html>502 Bad Gateway</html>"
        return PocketfulResponse(status, body, text)

    def sent(self, method, path=None):
        return [c for c in self.calls if c.method == method and (path is None or c.path == path)]


@pytest.fixture
def pf(monkeypatch):
    fake = FakePocketful()
    monkeypatch.setattr(oa, "pocketful_request", fake)
    monkeypatch.setattr(oa, "_POSITION_BOOK", PositionBookCache())
    return fake


@pytest.fixture
def market(monkeypatch):
    """The master contract and Pocketful's LTPs; records every LTP request."""
    state = SimpleNamespace(ltp={}, ltp_calls=[], info_calls=[])

    def symbol_info(symbol, exchange):
        state.info_calls.append((symbol, exchange))
        row = MASTER.get((symbol, exchange))
        return SimpleNamespace(tick_size=row[2]) if row else None

    def token(symbol, exchange):
        row = MASTER.get((symbol, exchange))
        return row[1] if row else None

    def br_symbol(symbol, exchange):
        row = MASTER.get((symbol, exchange))
        return row[0] if row else None

    def get_ltp(self, symbol, exchange):
        state.ltp_calls.append((self.auth_token, symbol, exchange))
        return state.ltp.get(symbol, 0.0)

    monkeypatch.setattr(td, "get_symbol_info", symbol_info)
    monkeypatch.setattr(td, "get_token", token)
    monkeypatch.setattr(oa, "get_token", token)
    monkeypatch.setattr(oa, "get_br_symbol", br_symbol)
    monkeypatch.setattr(
        od, "get_oa_symbol", lambda brsymbol, exchange: BY_BRSYMBOL.get((brsymbol, exchange))
    )
    monkeypatch.setattr(od, "get_symbol", lambda tok, exchange: BY_TOKEN.get((str(tok), exchange)))
    monkeypatch.setattr(BrokerData, "get_ltp", get_ltp)
    return state


def _order(symbol="SBIN", exchange="NSE", action="BUY", pricetype="MARKET", **extra):
    return {
        "apikey": "app-key",
        "strategy": "test",
        "symbol": symbol,
        "exchange": exchange,
        "action": action,
        "pricetype": pricetype,
        "product": "MIS",
        "quantity": "1",
        "price": "0",
        "trigger_price": "0",
        "disclosed_quantity": "0",
        **extra,
    }


def _on_tick(price, tick):
    return Decimal(str(price)) % Decimal(str(tick)) == 0


def _d(value):
    return Decimal(str(value))


# --------------------------------------------------------------------------
# MARKET -> protected LIMIT off the LTP
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("symbol", "exchange", "ltp", "action", "limit"),
    [
        # Equity above 500: 0.5%. 800.5 x 1.005 = 804.5025, up to 804.55.
        ("SBIN", "NSE", 800.5, "BUY", 804.55),
        # 800.5 x 0.995 = 796.4975, down to 796.45.
        ("SBIN", "NSE", 800.5, "SELL", 796.45),
        # Options below 10: 5%, wider than equity.
        (OPTION, "NFO", 5.0, "BUY", 5.25),
        (OPTION, "NFO", 5.0, "SELL", 4.75),
        # 5% of 0.05 is less than a tick: at least one tick past the LTP.
        (OPTION, "NFO", 0.05, "BUY", 0.1),
        # A SELL cannot go below the smallest price there is.
        (OPTION, "NFO", 0.05, "SELL", 0.05),
    ],
)
def test_a_market_order_goes_out_as_a_protected_limit(market, symbol, exchange, ltp, action, limit):
    market.ltp[symbol] = ltp

    sent = td.transform_data(_order(symbol, exchange, action), CLIENT, AUTH)

    tick = MASTER[(symbol, exchange)][2]
    assert sent["order_type"] == "LIMIT"
    assert sent["price"] == limit
    assert sent["trigger_price"] == 0
    assert _on_tick(sent["price"], tick)
    if action == "BUY":
        assert _d(sent["price"]) >= _d(ltp) + _d(tick)
    elif ltp > tick:
        assert _d(sent["price"]) <= _d(ltp) - _d(tick)
    assert market.ltp_calls == [(AUTH, symbol, exchange)]


def test_a_market_order_without_an_ltp_is_refused_not_sent_as_market(market):
    with pytest.raises(td.OrderFieldError, match="live price"):
        td.transform_data(_order(), CLIENT, AUTH)


def test_a_market_order_without_a_tick_size_is_refused_without_a_quote(market):
    market.ltp["UNTICKED"] = 100.0

    with pytest.raises(td.OrderFieldError, match="tick size"):
        td.transform_data(_order("UNTICKED"), CLIENT, AUTH)
    assert market.ltp_calls == []


def test_an_ltp_read_that_raises_counts_as_no_price(market, monkeypatch):
    def broken(self, symbol, exchange):
        raise RuntimeError("feed down")

    monkeypatch.setattr(BrokerData, "get_ltp", broken)

    with pytest.raises(td.OrderFieldError, match="live price"):
        td.transform_data(_order(), CLIENT, AUTH)


# --------------------------------------------------------------------------
# SL-M -> SL beyond its own trigger
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("symbol", "exchange", "trigger", "action", "limit"),
    [
        ("SBIN", "NSE", 800.0, "BUY", 804.0),
        ("SBIN", "NSE", 800.0, "SELL", 796.0),
        # Equity below 100: 2%.
        ("PENNY", "NSE", 50.0, "BUY", 51.0),
        ("PENNY", "NSE", 50.0, "SELL", 49.0),
        (OPTION, "NFO", 5.0, "SELL", 4.75),
        # 5% of 0.10 is less than a tick: one tick past the trigger.
        (OPTION, "NFO", 0.10, "BUY", 0.15),
        (OPTION, "NFO", 0.10, "SELL", 0.05),
        # A trigger off the tick grid still gets a full tick of room.
        (OPTION, "NFO", 0.06, "BUY", 0.15),
        (OPTION, "NFO", 0.14, "SELL", 0.05),
    ],
)
def test_an_sl_m_order_goes_out_as_an_sl_beyond_its_trigger(
    market, symbol, exchange, trigger, action, limit
):
    market.ltp[symbol] = 1.0  # far from the trigger: must not be used

    sent = td.transform_data(
        _order(symbol, exchange, action, "SL-M", trigger_price=str(trigger)), CLIENT, AUTH
    )

    tick = MASTER[(symbol, exchange)][2]
    assert sent["order_type"] == "SL"
    assert sent["price"] == limit
    assert sent["trigger_price"] == trigger
    assert _on_tick(sent["price"], tick)
    if action == "BUY":
        assert _d(sent["price"]) >= _d(trigger) + _d(tick)
    else:
        assert _d(sent["price"]) <= _d(trigger) - _d(tick)
    assert market.ltp_calls == []


def test_an_sl_m_sell_too_low_to_protect_is_refused(market):
    with pytest.raises(td.OrderFieldError, match="too low"):
        td.transform_data(_order(OPTION, "NFO", "SELL", "SL-M", trigger_price="0.05"), CLIENT, AUTH)


def test_an_sl_m_without_a_tick_size_is_refused(market):
    with pytest.raises(td.OrderFieldError, match="tick size"):
        td.transform_data(
            _order("UNTICKED", "NSE", "BUY", "SL-M", trigger_price="100"), CLIENT, AUTH
        )


def test_an_sl_m_without_a_trigger_is_refused(market):
    with pytest.raises(td.OrderFieldError, match="trigger price"):
        td.transform_data(_order(pricetype="SL-M"), CLIENT, AUTH)


def test_a_tick_size_that_cannot_be_read_is_treated_as_missing(market, monkeypatch):
    def unreadable(symbol, exchange):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(td, "get_symbol_info", unreadable)
    market.ltp["SBIN"] = 800.5

    with pytest.raises(td.OrderFieldError, match="tick size"):
        td.transform_data(_order(), CLIENT, AUTH)
    with pytest.raises(td.OrderFieldError, match="tick size"):
        td.transform_data(_order(pricetype="SL-M", trigger_price="800"), CLIENT, AUTH)


@pytest.mark.parametrize(
    ("pricetype", "price", "trigger", "order_type", "sent_trigger"),
    [("LIMIT", "801.5", "0", "LIMIT", 0.0), ("SL", "801.5", "800", "SL", 800.0)],
)
def test_limit_and_sl_orders_keep_their_own_prices(
    market, pricetype, price, trigger, order_type, sent_trigger
):
    sent = td.transform_data(
        _order(pricetype=pricetype, price=price, trigger_price=trigger), CLIENT, AUTH
    )

    assert (sent["order_type"], sent["price"], sent["trigger_price"]) == (
        order_type,
        801.5,
        sent_trigger,
    )
    assert market.ltp_calls == [] and market.info_calls == []


def test_a_symbol_missing_from_the_master_contract_is_refused(market):
    with pytest.raises(td.OrderFieldError, match="master contract"):
        td.transform_data(_order("NOSUCH", pricetype="LIMIT", price="10"), CLIENT, AUTH)


# --------------------------------------------------------------------------
# Place, modify, cancel
# --------------------------------------------------------------------------


def test_place_sends_the_documented_body_with_the_tokens_client_id(market, pf):
    market.ltp["IDEA"] = 13.0
    pf.on("POST", "/api/v1/orders", PLACE_OK)

    res, body, orderid = oa.place_order_api(
        _order("IDEA", "NSE", "BUY", product="CNC", quantity="1"), AUTH
    )

    assert (res.status, orderid) == (200, "200018000000003")
    assert body["status"] == "success"
    (call,) = pf.sent("POST", "/api/v1/orders")
    assert call.token == AUTH
    # place-regular-order.md, field for field.
    assert set(call.payload) == {
        "exchange",
        "instrument_token",
        "client_id",
        "order_type",
        "amo",
        "price",
        "quantity",
        "disclosed_quantity",
        "validity",
        "product",
        "order_side",
        "device",
        "user_order_id",
        "trigger_price",
        "execution_type",
    }
    # 13.0 x 1.02 = 13.26 on a 0.01 tick.
    assert call.payload == {
        "exchange": "NSE",
        "instrument_token": "14366",
        "client_id": CLIENT,
        "order_type": "LIMIT",
        "amo": False,
        "price": 13.26,
        "quantity": 1,
        "disclosed_quantity": 0,
        "validity": "DAY",
        "product": "CNC",
        "order_side": "BUY",
        "device": "WEB",
        "user_order_id": 1,
        "trigger_price": 0.0,
        "execution_type": "REGULAR",
    }


@pytest.mark.parametrize(
    "sess",
    [{"username": "someone-else", "user": "admin"}, None],
    ids=["browser session holding another name", "API or strategy order with no session"],
)
def test_the_client_id_never_comes_from_the_browser_session(market, pf, sess):
    pf.on("POST", "/api/v1/orders", PLACE_OK)
    order = _order(pricetype="LIMIT", price="801.5")

    if sess is None:
        oa.place_order_api(order, AUTH)
    else:
        app = Flask(__name__)
        app.secret_key = "test"
        with app.test_request_context("/"):
            session.update(sess)
            oa.place_order_api(order, AUTH)

    assert pf.sent("POST")[0].payload["client_id"] == CLIENT


def test_an_order_without_a_client_id_is_refused_before_sending(market, pf, monkeypatch):
    monkeypatch.setattr(base, "client_id", lambda token: None)

    res, body, orderid = oa.place_order_api(_order(pricetype="LIMIT", price="10"), "bare-token")

    assert res.status == 400 and orderid is None
    assert "client ID" in body["message"]
    assert pf.calls == []


def test_place_refuses_an_order_it_cannot_price_before_sending(market, pf):
    res, body, orderid = oa.place_order_api(
        _order("UNTICKED", "NSE", "SELL", "SL-M", trigger_price="100"), AUTH
    )

    assert res.status == 400
    assert body["status"] == "error" and "tick size" in body["message"]
    assert orderid is None
    assert pf.calls == []


def test_an_error_answered_with_a_200_is_a_refusal(market, pf):
    pf.on("POST", "/api/v1/orders", PLACE_ERROR)

    res, body, orderid = oa.place_order_api(_order(pricetype="LIMIT", price="801.5"), AUTH)

    assert res.status == 400 and orderid is None
    assert body == {
        "status": "error",
        "message": "Pocketful refused the order: `product` is invalid",
    }


@pytest.mark.parametrize("status", [401, 403])
def test_a_session_refusal_tells_the_trader_to_log_in_again(market, pf, status):
    pf.on("POST", "/api/v1/orders", UNAUTHORISED, status=status)

    res, body, _ = oa.place_order_api(_order(pricetype="LIMIT", price="801.5"), AUTH)

    assert res.status == status
    assert "Log in to Pocketful again" in body["message"]
    assert str(status) not in body["message"]


def test_an_unreadable_answer_to_an_order_says_to_check_the_order_book(market, pf):
    pf.on("POST", "/api/v1/orders", None, status=502)

    res, body, orderid = oa.place_order_api(_order(pricetype="LIMIT", price="801.5"), AUTH)

    assert res.status == 502 and orderid is None
    assert "Check the order book" in body["message"]


def test_a_transport_error_on_place_reaches_the_service(market, pf):
    """The service marks the order as possibly placed; it must see the error."""
    pf.fail("POST", "/api/v1/orders", httpx.ReadTimeout("no answer"))

    with pytest.raises(httpx.ReadTimeout):
        oa.place_order_api(_order(pricetype="LIMIT", price="801.5"), AUTH)


def test_a_modify_to_market_is_priced_by_the_openalgo_symbol(market, pf):
    market.ltp["SBIN"] = 800.5
    pf.on("PUT", "/api/v1/orders", MODIFY_OK)

    answer, status = oa.modify_order({**_order(), "orderid": "202403111778"}, AUTH)

    assert (answer, status) == ({"status": "success", "orderid": "202403111778"}, 200)
    (call,) = pf.sent("PUT", "/api/v1/orders")
    assert call.payload["oms_order_id"] == "202403111778"
    assert call.payload["client_id"] == CLIENT
    assert (call.payload["order_type"], call.payload["price"]) == ("LIMIT", 804.55)
    assert call.payload["execution_type"] == "REGULAR"
    assert "amo" not in call.payload
    assert ("SBIN", "NSE") in market.info_calls
    assert ("SBIN-EQ", "NSE") not in market.info_calls


def test_a_modify_to_an_sl_m_it_cannot_price_is_refused(market, pf):
    answer, status = oa.modify_order(
        {**_order("UNTICKED", "NSE", "BUY", "SL-M", trigger_price="100"), "orderid": "1"}, AUTH
    )

    assert status == 400 and "tick size" in answer["message"]
    assert pf.calls == []


def test_a_modify_pocketful_refuses_reports_its_reason(market, pf):
    pf.on(
        "PUT",
        "/api/v1/orders",
        {"data": {}, "error_code": 45010, "message": "Something went wrong", "status": "error"},
    )

    answer, status = oa.modify_order(
        {**_order(pricetype="LIMIT", price="801"), "orderid": "1"}, AUTH
    )

    assert status == 400
    assert answer["message"] == "Pocketful refused the change to the order: Something went wrong"


def test_cancel_sends_the_documented_body_and_the_sdks_query(pf):
    pf.on("DELETE", "/api/v1/orders/202403111778", CANCEL_OK)

    answer, status = oa.cancel_order("202403111778", AUTH)

    assert (answer, status) == ({"status": "success", "orderid": "202403111778"}, 200)
    (call,) = pf.sent("DELETE")
    assert call.payload == {
        "oms_order_id": "202403111778",
        "client_id": CLIENT,
        "execution_type": "REGULAR",
    }
    assert call.params == {"client_id": CLIENT, "execution_type": "REGULAR"}


def test_a_cancel_pocketful_refuses_is_an_error(pf):
    pf.on("DELETE", "/api/v1/orders/1", UNAUTHORISED)

    answer, status = oa.cancel_order("1", AUTH)

    assert status == 400
    assert answer == {
        "status": "error",
        "message": "Pocketful refused the cancel: Request Unauthorised",
    }


def test_an_order_id_cannot_leave_the_orders_path(pf):
    oa.cancel_order("../holdings?x=1", AUTH)

    (call,) = pf.sent("DELETE")
    assert call.path == "/api/v1/orders/..%2Fholdings%3Fx%3D1"


def test_cancel_all_cancels_every_pending_order_with_its_execution_type(pf):
    regular = {**PENDING_ORDER, "oms_order_id": "R1", "execution_type": "REGULAR"}
    cover = {**PENDING_ORDER, "oms_order_id": "C1", "execution_type": "CO"}
    pf.on("GET", "/api/v1/orders", _ok({"orders": [PENDING_ORDER, regular, cover]}), kind="pending")
    pf.on("DELETE", "/api/v1/orders/2024030943", CANCEL_OK)
    pf.on("DELETE", "/api/v1/orders/R1", CANCEL_OK)

    canceled, failed = oa.cancel_all_orders_api({}, AUTH)

    assert canceled == ["2024030943", "R1"]
    assert failed == ["C1"]
    (read,) = pf.sent("GET")
    assert read.params == {"client_id": CLIENT, "type": "pending"}
    types = {c.path: c.payload["execution_type"] for c in pf.sent("DELETE")}
    assert types == {"/api/v1/orders/2024030943": "AMO", "/api/v1/orders/R1": "REGULAR"}


def test_cancel_all_fails_loudly_when_the_pending_list_cannot_be_read(pf):
    pf.on("GET", "/api/v1/orders", FORBIDDEN, kind="pending")

    with pytest.raises(RuntimeError, match="Pocketful refused the order book"):
        oa.cancel_all_orders_api({}, AUTH)
    assert pf.sent("DELETE") == []


# --------------------------------------------------------------------------
# The order book and the trade book
# --------------------------------------------------------------------------


def test_the_order_book_is_the_pending_and_completed_lists(market, pf):
    pf.on("GET", "/api/v1/orders", _ok({"orders": [PENDING_ORDER]}), kind="pending")
    pf.on("GET", "/api/v1/orders", _ok({"orders": [COMPLETED_ORDER]}), kind="completed")

    book = oa.get_order_book(AUTH)

    assert book["status"] == "success"
    assert [o["oms_order_id"] for o in book["data"]] == ["2024030943", "2024030935"]
    assert [c.params for c in pf.sent("GET")] == [
        {"type": "pending", "client_id": CLIENT},
        {"type": "completed", "client_id": CLIENT},
    ]


def test_an_order_in_both_lists_is_shown_once_as_finished(market, pf):
    working = {**PENDING_ORDER, "oms_order_id": "X1", "order_status": "PENDING"}
    done = {**COMPLETED_ORDER, "oms_order_id": "X1", "order_status": "COMPLETE"}
    pf.on("GET", "/api/v1/orders", _ok({"orders": [working]}), kind="pending")
    pf.on("GET", "/api/v1/orders", _ok({"orders": [done]}), kind="completed")

    orders = od.transform_order_data(od.map_order_data(oa.get_order_book(AUTH)))

    assert [(o["orderid"], o["order_status"]) for o in orders] == [("X1", "complete")]


@pytest.mark.parametrize("failing", ["pending", "completed"])
def test_a_half_of_the_order_book_that_fails_fails_the_book(market, pf, failing):
    other = "completed" if failing == "pending" else "pending"
    pf.on("GET", "/api/v1/orders", FORBIDDEN, kind=failing)
    pf.on("GET", "/api/v1/orders", _ok({"orders": [PENDING_ORDER]}), kind=other)

    book = oa.get_order_book(AUTH)

    assert book["status"] == "error"
    assert book["message"] == "Pocketful refused the order book: Request forbidden"


def test_the_order_book_in_openalgos_shape(market, pf):
    trigger_wait = {
        **PENDING_ORDER,
        "oms_order_id": "T1",
        "order_status": "TRIGGER_PENDING",
        "order_type": "SL",
        "trigger_price": 30.0,
    }
    filled = {
        **COMPLETED_ORDER,
        "oms_order_id": "F1",
        "order_status": "COMPLETE",
        "order_type": "SLM",
        "order_side": "SELL",
        "filled_quantity": 1,
        "average_trade_price": 124.5,
    }
    rejected = {**COMPLETED_ORDER, "oms_order_id": "J1", "order_status": "REJECTED"}
    pf.on("GET", "/api/v1/orders", _ok({"orders": [PENDING_ORDER, trigger_wait]}), kind="pending")
    pf.on(
        "GET",
        "/api/v1/orders",
        _ok({"orders": [COMPLETED_ORDER, filled, rejected]}),
        kind="completed",
    )

    mapped = od.map_order_data(order_data=oa.get_order_book(AUTH))
    stats = od.calculate_order_statistics(mapped)
    orders = {o["orderid"]: o for o in od.transform_order_data(mapped)}

    assert orders["2024030943"] == {
        "symbol": "COFORGE24MAR5700PE",
        "exchange": "NFO",
        "action": "BUY",
        "quantity": 1500,
        "price": 30.7,
        "trigger_price": 0.0,
        "pricetype": "LIMIT",
        "product": "NRML",
        "orderid": "2024030943",
        "order_status": "open",
        # 1709995984 is 2024-03-09 14:53:04 UTC.
        "timestamp": "09-03-2024 20:23:04",
        "filled_quantity": 0,
        "pending_quantity": 1500,
        "average_price": 0.0,
    }
    assert orders["T1"]["order_status"] == "trigger pending"
    assert orders["2024030935"]["order_status"] == "cancelled"
    assert orders["2024030935"]["symbol"] == "PNB"
    assert orders["2024030935"]["product"] == "CNC"
    assert orders["F1"]["order_status"] == "complete"
    assert orders["F1"]["pricetype"] == "SL-M"
    assert orders["F1"]["action"] == "SELL"
    assert orders["F1"]["average_price"] == 124.5
    assert orders["J1"]["order_status"] == "rejected"
    assert stats == {
        "total_buy_orders": 4,
        "total_sell_orders": 1,
        "total_completed_orders": 1,
        "total_open_orders": 2,
        "total_rejected_orders": 1,
    }


@pytest.mark.parametrize("word", ["CANCEL_REJECTED", "MODIFY_REJECTED", "PARTIALLY_COMPLETE"])
def test_an_order_still_in_the_pending_list_is_working_whatever_its_word(market, pf, word):
    """The docs do not list every status, so the list decides. An order shown
    as cancelled or rejected while it can still fill is the dangerous error.
    These words are not in Pocketful's docs; they stand for any word that
    sounds finished on an order Pocketful still lists as pending."""
    pf.on(
        "GET",
        "/api/v1/orders",
        _ok({"orders": [{**PENDING_ORDER, "order_status": word}]}),
        kind="pending",
    )
    pf.on("GET", "/api/v1/orders", _ok({"orders": []}), kind="completed")

    mapped = od.map_order_data(oa.get_order_book(AUTH))

    assert [o["order_status"] for o in od.transform_order_data(mapped)] == ["open"]
    assert od.calculate_order_statistics(mapped)["total_open_orders"] == 1


def test_a_finished_order_with_a_word_the_docs_do_not_name(market, pf):
    filled = {**COMPLETED_ORDER, "order_status": "EXECUTED", "filled_quantity": 1}
    lapsed = {**COMPLETED_ORDER, "oms_order_id": "L1", "order_status": "EXPIRED"}
    pf.on("GET", "/api/v1/orders", _ok({"orders": []}), kind="pending")
    pf.on("GET", "/api/v1/orders", _ok({"orders": [filled, lapsed]}), kind="completed")

    orders = od.transform_order_data(od.map_order_data(oa.get_order_book(AUTH)))

    # Filled in full reads complete; otherwise Pocketful's own word is shown.
    assert [o["order_status"] for o in orders] == ["complete", "expired"]


def test_mapping_the_order_book_twice_changes_nothing(market, pf):
    pf.on("GET", "/api/v1/orders", _ok({"orders": [PENDING_ORDER]}), kind="pending")
    pf.on("GET", "/api/v1/orders", _ok({"orders": [COMPLETED_ORDER]}), kind="completed")
    book = oa.get_order_book(AUTH)

    once = od.transform_order_data(od.map_order_data(book))
    twice = od.transform_order_data(od.map_order_data(book))

    assert once == twice


def test_the_trade_book_reads_data_orders_and_comes_out_in_openalgos_shape(market, pf):
    fill = {
        **TRADE_ROW,
        "oms_order_id": "202403152099",
        "order_side": "SELL",
        "filled_quantity": 5,
        "trade_price": 12.05,
    }
    pf.on("GET", "/api/v1/trades", _ok({"orders": [TRADE_ROW, fill]}))

    raw = oa.get_trade_book(AUTH)
    trades = od.transform_tradebook_data(od.map_trade_data(trade_data=raw))

    (call,) = pf.sent("GET", "/api/v1/trades")
    assert call.params == {"client_id": CLIENT}
    assert trades[1] == {
        "symbol": "IDEA",
        "exchange": "NSE",
        "product": "MIS",
        "action": "SELL",
        "quantity": 5,
        "average_price": 12.05,
        "trade_value": 60.25,
        "orderid": "202403152099",
        # 1710485885 is 2024-03-15 06:58:05 UTC.
        "timestamp": "15-03-2024 12:28:05",
    }
    # The docs' own row: no fill quantity or trade price yet.
    assert (trades[0]["quantity"], trades[0]["average_price"]) == (1, 0.0)


def test_a_book_in_an_unknown_shape_is_an_error_not_an_empty_book(market, pf):
    pf.on("GET", "/api/v1/trades", _ok({"orders": {"unexpected": True}}))

    book = oa.get_trade_book(AUTH)

    assert book["status"] == "error"
    assert "does not recognise" in book["message"]


def test_a_book_that_cannot_be_reached_is_an_error(market, pf):
    pf.fail("GET", "/api/v1/holdings", httpx.ConnectError("refused"))

    book = oa.get_holdings(AUTH)

    assert book == {
        "status": "error",
        "message": "OpenAlgo could not reach Pocketful for the holdings. "
        "Check your connection and try again.",
    }


# --------------------------------------------------------------------------
# Positions and holdings
# --------------------------------------------------------------------------


def test_positions_are_read_netwise(market, pf):
    pf.on("GET", "/api/v1/positions", _ok([NETWISE_ROW]))

    positions = oa.get_positions(AUTH)

    assert positions == {"status": "success", "data": [NETWISE_ROW]}
    (call,) = pf.sent("GET", "/api/v1/positions")
    assert call.params == {"client_id": CLIENT, "type": "historical"}


def test_the_position_book_in_openalgos_shape(market, pf):
    short = _position(
        "SBIN",
        "NSE",
        -10,
        product="NRML",
        average_sell_price=805.0,
        average_buy_price=0,
        ltp=800.0,
        net_amount=8050.0,
    )
    pf.on("GET", "/api/v1/positions", _ok([DAYWISE_ROW, NETWISE_ROW, short]))

    rows = od.transform_positions_data(od.map_position_data(oa.get_positions(AUTH)))

    assert rows[0] == {
        "symbol": "YESBANK",
        "exchange": "NSE",
        "product": "MIS",
        "quantity": 1,
        "average_price": "14.70",
        "ltp": 14.6,
        # Bought at 14.70, now 14.60.
        "pnl": -0.1,
    }
    assert rows[1] == {
        "symbol": "GOLDGUINEA20NOVFUT",
        "exchange": "MCX",
        "product": "NRML",
        "quantity": 0,
        "average_price": "0.00",
        "ltp": 40520.0,
        # Bought at 40520, sold at 40538.
        "pnl": 18.0,
    }
    # Sold 10 at 805, now 800.
    assert (rows[2]["quantity"], rows[2]["average_price"], rows[2]["pnl"]) == (-10, "805.00", 50.0)


def test_the_annexures_product_names_read_back_as_openalgos(market, pf):
    pf.on(
        "GET",
        "/api/v1/positions",
        _ok(
            [
                _position("SBIN", "NSE", 1, product="INTRADAY"),
                _position("SBIN", "NSE", 2, product="MARGIN"),
            ]
        ),
    )

    rows = od.transform_positions_data(od.map_position_data(oa.get_positions(AUTH)))

    assert [r["product"] for r in rows] == ["MIS", "NRML"]


def test_holdings_in_openalgos_shape(market, pf):
    pf.on("GET", "/api/v1/holdings", _ok({"holdings": [HOLDING_ROW]}))

    raw = oa.get_holdings(AUTH)
    mapped = od.map_portfolio_data(raw)
    stats = od.calculate_portfolio_statistics(mapped)
    holdings = od.transform_holdings_data(mapped)

    (call,) = pf.sent("GET", "/api/v1/holdings")
    assert call.params == {"client_id": CLIENT}
    assert holdings == [
        {
            "symbol": "SBIN",
            "exchange": "NSE",
            "quantity": 55,
            "product": "CNC",
            "average_price": 240.2,
            "ltp": 245.25,
            "pnl": 277.75,
            "pnlpercent": 2.1,
        }
    ]
    assert stats == {
        "totalholdingvalue": 13488.75,
        "totalinvvalue": 13211.0,
        "totalprofitandloss": 277.75,
        "totalpnlpercentage": 2.1,
    }


def test_a_holding_missing_from_the_master_contract_keeps_its_own_name(market, pf):
    stranger = {
        **HOLDING_ROW,
        "instrument_details": {"trading_symbol": "ZZZ-EQ", "instrument_token": 1},
        "token": 1,
        "trading_symbol": "ZZZ",
    }
    pf.on("GET", "/api/v1/holdings", _ok({"holdings": [stranger]}))

    (row,) = od.transform_holdings_data(od.map_portfolio_data(oa.get_holdings(AUTH)))

    assert row["symbol"] == "ZZZ-EQ"


# --------------------------------------------------------------------------
# Smart orders
# --------------------------------------------------------------------------


def _smart(position_size, quantity=5, action="SELL", product="MIS", **extra):
    return {
        **_order("SBIN", "NSE", action, quantity=str(quantity), product=product),
        "position_size": str(position_size),
        **extra,
    }


def test_a_smart_order_flips_the_net_position_with_a_protected_order(market, pf):
    market.ltp["SBIN"] = 800.5
    pf.on(
        "GET",
        "/api/v1/positions",
        _ok([_position("SBIN", "NSE", 10), _position("SBIN", "NSE", 99, product="NRML")]),
    )
    pf.on("POST", "/api/v1/orders", PLACE_OK)

    res, _, orderid = oa.place_smartorder_api(_smart(-5), AUTH)

    assert (res.status, orderid) == (200, "200018000000003")
    (read,) = pf.sent("GET", "/api/v1/positions")
    assert read.params["type"] == "historical"
    (order,) = pf.sent("POST", "/api/v1/orders")
    assert (order.payload["order_side"], order.payload["quantity"]) == ("SELL", 15)
    assert (order.payload["order_type"], order.payload["price"]) == ("LIMIT", 796.45)


def test_a_position_is_matched_by_token_when_its_symbol_differs(market, pf):
    held = _position("SBIN", "NSE", 10)
    held["trading_symbol"] = "SBIN"  # not the master contract's SBIN-EQ
    pf.on("GET", "/api/v1/positions", _ok([held]))

    assert oa.get_open_position("SBIN", "NSE", "MIS", AUTH) == "10"


def test_another_products_position_is_not_this_one(market, pf):
    pf.on("GET", "/api/v1/positions", _ok([_position("SBIN", "NSE", 10, product="NRML")]))

    assert oa.get_open_position("SBIN", "NSE", "MIS", AUTH) == "0"


@pytest.mark.parametrize(
    "answer",
    [
        (200, FORBIDDEN),
        (403, FORBIDDEN),
        (502, None),
        (200, _ok({"positions": "unexpected"})),
    ],
    ids=["error envelope", "http error", "unreadable", "unknown shape"],
)
def test_a_smart_order_never_sizes_itself_against_an_unread_position(market, pf, answer):
    status, body = answer
    pf.on("GET", "/api/v1/positions", body, status=status)

    res, data, orderid = oa.place_smartorder_api(_smart(-5), AUTH)

    assert (res, orderid) == (None, None)
    assert data == {"status": "error", "message": position_read_failed_message("pocketful")}
    assert pf.sent("POST") == []


def test_a_position_row_without_a_net_quantity_refuses_the_smart_order(market, pf):
    row = _position("SBIN", "NSE", 10)
    del row["net_quantity"]
    pf.on("GET", "/api/v1/positions", _ok([row]))

    res, data, orderid = oa.place_smartorder_api(_smart(0, quantity=0), AUTH)

    assert data["status"] == "error"
    assert pf.sent("POST") == []


def test_a_smart_order_whose_order_gets_no_answer_still_drops_the_cached_book(market, pf):
    """The order may have reached Pocketful: the next smart order on the
    symbol must read the book again, not the cached one from before it."""
    market.ltp["SBIN"] = 800.5
    pf.on("GET", "/api/v1/positions", _ok([_position("SBIN", "NSE", 10)]))
    pf.fail("POST", "/api/v1/orders", httpx.ReadTimeout("no answer"))

    with pytest.raises(httpx.ReadTimeout):
        oa.place_smartorder_api(_smart(-5), AUTH)
    oa.get_open_position("SBIN", "NSE", "MIS", AUTH)

    assert len(pf.sent("GET", "/api/v1/positions")) == 2


def test_an_empty_position_book_is_flat(market, pf):
    market.ltp["SBIN"] = 800.5
    pf.on("GET", "/api/v1/positions", _ok([]))
    pf.on("POST", "/api/v1/orders", PLACE_OK)

    oa.place_smartorder_api(_smart(-5), AUTH)

    (order,) = pf.sent("POST")
    assert (order.payload["order_side"], order.payload["quantity"]) == ("SELL", 5)


# --------------------------------------------------------------------------
# Close all
# --------------------------------------------------------------------------


def test_close_all_squares_off_with_protected_limits(market, pf):
    market.ltp.update({"SBIN": 800.5, "YESBANK": 14.6})
    pf.on(
        "GET",
        "/api/v1/positions",
        _ok(
            [
                NETWISE_ROW,
                _position("SBIN", "NSE", 10),
                _position("YESBANK", "NSE", -5, product="NRML"),
            ]
        ),
    )
    pf.on("POST", "/api/v1/orders", PLACE_OK)

    answer, status = oa.close_all_positions("app-key", AUTH)

    assert status == 200 and answer["status"] == "success"
    first, second = (c.payload for c in pf.sent("POST"))
    assert (first["order_side"], first["quantity"], first["product"]) == ("SELL", 10, "MIS")
    assert (first["order_type"], first["price"]) == ("LIMIT", 796.45)
    # 14.6 x 1.02 = 14.892, up to 14.90 on a 0.01 tick.
    assert (second["order_side"], second["quantity"], second["product"]) == ("BUY", 5, "NRML")
    assert (second["order_type"], second["price"]) == ("LIMIT", 14.9)


def test_a_square_off_that_cannot_be_priced_does_not_stop_the_others(market, pf):
    market.ltp["SBIN"] = 800.5  # none for YESBANK
    pf.on(
        "GET",
        "/api/v1/positions",
        _ok([_position("YESBANK", "NSE", 5), _position("SBIN", "NSE", 10)]),
    )
    pf.on("POST", "/api/v1/orders", PLACE_OK)

    answer, status = oa.close_all_positions("app-key", AUTH)

    (sent,) = (c.payload for c in pf.sent("POST"))
    assert sent["instrument_token"] == "3045"
    assert status == 500
    assert answer["status"] == "error"
    assert "1 of 2 positions were not closed" in answer["message"]
    assert "YESBANK-EQ" in answer["message"] and "live price" in answer["message"]


def test_a_square_off_whose_order_gets_no_answer_does_not_stop_the_others(market, pf, monkeypatch):
    market.ltp.update({"SBIN": 800.5, "YESBANK": 14.6})
    pf.on(
        "GET",
        "/api/v1/positions",
        _ok([_position("YESBANK", "NSE", 5), _position("SBIN", "NSE", 10)]),
    )
    real = oa.place_order_api

    def flaky(order, auth):
        if order["symbol"] == "YESBANK":
            raise httpx.ReadTimeout("no answer")
        return real(order, auth)

    pf.on("POST", "/api/v1/orders", PLACE_OK)
    monkeypatch.setattr(oa, "place_order_api", flaky)

    answer, status = oa.close_all_positions("app-key", AUTH)

    assert len(pf.sent("POST")) == 1
    assert status == 500 and "may have been placed" in answer["message"]


def test_close_all_sends_nothing_when_the_positions_cannot_be_read(market, pf):
    pf.on("GET", "/api/v1/positions", FORBIDDEN)

    answer, status = oa.close_all_positions("app-key", AUTH)

    assert status == 500
    assert answer["message"] == position_read_failed_message("pocketful")
    assert pf.sent("POST") == []


def test_close_all_with_nothing_open(market, pf):
    pf.on("GET", "/api/v1/positions", _ok([NETWISE_ROW]))

    assert oa.close_all_positions("app-key", AUTH) == ({"message": "No Open Positions Found"}, 200)
    assert pf.sent("POST") == []
