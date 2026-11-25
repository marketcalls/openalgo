"""5paisa XTS reads XTS answers the way the XTS v2 docs describe them.

https://symphonyfintech.com/xts-trading-front-end-api-v2/ and
https://symphonyfintech.com/xts-market-data-front-end-api-v2/

- A smart order finds the open position (it read "status"/"data" keys XTS
  never sends, so every position read as 0).
- Each trade-book row is one fill (LastTradedQuantity / LastTradedPrice).
- Replaced, PartiallyFilled and the Pending order states are open, and cancel
  all cancels them.
- Cancel and modify read XTS's {"type": ...} answer.
- Funds use the ALL|ALL|ALL balance entry.
- Futures master rows have 21 fields, options 23; spreads are not contracts.
- Streaming reads Touchline whatever the message code.
"""

import csv
import logging

import pytest

from broker.fivepaisaxts.api import funds as fp_funds
from broker.fivepaisaxts.api import order_api as fp_orders
from broker.fivepaisaxts.database import master_contract_db as fp_master
from broker.fivepaisaxts.mapping import order_data as fp_mapping


class _Response:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def json(self):
        return self._payload


class _Client:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code
        self.calls = []

    def _answer(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return _Response(self.payload, self.status_code)

    def get(self, url, **kwargs):
        return self._answer("GET", url, **kwargs)

    def put(self, url, **kwargs):
        return self._answer("PUT", url, **kwargs)

    def delete(self, url, **kwargs):
        return self._answer("DELETE", url, **kwargs)


# ------------------------------------------------------------- open position


def _positions(*rows):
    return {"type": "success", "result": {"positionList": list(rows)}}


def _position(**overrides):
    row = {
        "TradingSymbol": "NIFTY 27OCT2026 CE 22400",
        "ExchangeSegment": "NSEFO",
        "ExchangeInstrumentId": "48225",
        "ProductType": "NRML",
        "Quantity": "-75",
    }
    row.update(overrides)
    return row


@pytest.fixture
def open_position(monkeypatch):
    def run(book, token="48225", exchange="NFO", product="NRML"):
        monkeypatch.setattr(fp_orders, "_get_cached_positions", lambda auth: book)
        monkeypatch.setattr(fp_orders, "get_token", lambda symbol, exch: token)
        monkeypatch.setattr(fp_orders, "get_br_symbol", lambda symbol, exch: "NIFTY26OCT22400CE")
        return fp_orders.get_open_position("NIFTY27OCT2622400CE", exchange, product, "auth")

    return run


def test_open_position_matches_the_instrument_not_the_name(open_position):
    assert open_position(_positions(_position())) == "-75"


def test_open_position_accepts_the_docs_spelling_of_the_instrument_id(open_position):
    row = _position()
    row["ExchangeInstrumentID"] = row.pop("ExchangeInstrumentId")
    assert open_position(_positions(row)) == "-75"


@pytest.mark.parametrize(
    "row",
    [
        _position(ProductType="MIS"),
        _position(ExchangeSegment="BSEFO"),
        _position(ExchangeInstrumentId="99999"),
    ],
    ids=["other product", "other exchange", "other instrument"],
)
def test_open_position_ignores_other_rows(open_position, row):
    assert open_position(_positions(row)) == "0"


def test_open_position_reads_zero_from_an_error_answer(open_position):
    assert open_position({"type": "error", "description": "x"}) == "0"


# -------------------------------------------------------------- trade book


def test_trade_book_row_is_one_fill():
    fill = {
        "TradingSymbol": "SBIN",
        "ExchangeSegment": "NSECM",
        "OrderSide": "BUY",
        "ProductType": "MIS",
        "AppOrderID": "1100126316",
        "OrderQuantity": 100,
        "OrderAverageTradedPrice": 801.0,
        "LastTradedQuantity": 40,
        "LastTradedPrice": 800.5,
        "LastExecutionTransactTime": "17-11-2026 10:00:05",
        "OrderGeneratedDateTime": "17-11-2026 10:00:00",
    }

    [row] = fp_mapping.transform_tradebook_data([fill])

    assert row["quantity"] == 40
    assert row["average_price"] == 800.5
    assert row["trade_value"] == pytest.approx(40 * 800.5)
    assert row["timestamp"] == "17-11-2026 10:00:05"


def test_trade_book_row_without_fill_fields_keeps_order_fields():
    order = {
        "ExchangeSegment": "NSECM",
        "AppOrderID": "1",
        "OrderQuantity": 10,
        "OrderAverageTradedPrice": 5.0,
        "OrderGeneratedDateTime": "t",
    }

    [row] = fp_mapping.transform_tradebook_data([order])

    assert (row["quantity"], row["average_price"], row["timestamp"]) == (10, 5.0, "t")


# ------------------------------------------------------------ order status


@pytest.mark.parametrize(
    "status,expected",
    [
        ("New", "open"),
        ("PartiallyFilled", "open"),
        ("Replaced", "open"),
        ("PendingNew", "open"),
        ("PendingReplace", "open"),
        ("PendingCancel", "open"),
        ("Filled", "complete"),
        ("Rejected", "rejected"),
        ("Cancelled", "cancelled"),
    ],
)
def test_order_status_maps_every_documented_state(status, expected):
    [row] = fp_mapping.transform_order_data([{"OrderStatus": status, "AppOrderID": "1"}])
    assert row["order_status"] == expected


def test_order_statistics_count_part_filled_and_modified_orders_as_open():
    orders = [
        {"OrderSide": "BUY", "OrderStatus": "PartiallyFilled"},
        {"OrderSide": "BUY", "OrderStatus": "Replaced"},
        {"OrderSide": "SELL", "OrderStatus": "Filled"},
    ]
    stats = fp_mapping.calculate_order_statistics(orders)
    assert stats["total_open_orders"] == 2
    assert stats["total_completed_orders"] == 1


def test_cancel_all_cancels_modified_and_part_filled_orders(monkeypatch):
    book = {
        "type": "success",
        "result": [
            {"AppOrderID": 1, "OrderStatus": "New"},
            {"AppOrderID": 2, "OrderStatus": "Replaced"},
            {"AppOrderID": 3, "OrderStatus": "PartiallyFilled"},
            {"AppOrderID": 4, "OrderStatus": "PendingCancel"},
            {"AppOrderID": 5, "OrderStatus": "Filled"},
        ],
    }
    cancelled = []
    monkeypatch.setattr(fp_orders, "get_order_book", lambda auth: book)
    monkeypatch.setattr(
        fp_orders,
        "cancel_order",
        lambda orderid, auth: (cancelled.append(orderid) or {"status": "success"}, 200),
    )
    monkeypatch.setattr(fp_orders.time, "sleep", lambda seconds: None)

    done, failed = fp_orders.cancel_all_orders_api({}, "auth")

    assert done == ["1", "2", "3"] and failed == []


# ------------------------------------------------------- cancel and modify


def test_cancel_reads_the_xts_success_answer(monkeypatch):
    client = _Client({"type": "success", "result": [{"AppOrderID": 7}]})
    monkeypatch.setattr(fp_orders, "get_httpx_client", lambda: client)

    body, status = fp_orders.cancel_order("7", "auth")

    assert (body["status"], status) == ("success", 200)
    method, url, kwargs = client.calls[0]
    assert method == "DELETE" and url.endswith("/interactive/orders")
    assert kwargs["params"] == {"appOrderID": "7"}


def test_cancel_reports_the_xts_reason(monkeypatch):
    client = _Client({"type": "error", "description": "Order is already cancelled"})
    monkeypatch.setattr(fp_orders, "get_httpx_client", lambda: client)

    body, status = fp_orders.cancel_order("7", "auth")

    assert body == {"status": "error", "message": "Order is already cancelled"}
    assert status != 200


def test_modify_reads_the_xts_success_answer(monkeypatch):
    client = _Client({"type": "success", "result": {"AppOrderID": 10001253450000041478}})
    monkeypatch.setattr(fp_orders, "get_httpx_client", lambda: client)
    monkeypatch.setattr(fp_orders, "get_token", lambda symbol, exch: "2885")
    monkeypatch.setattr(fp_orders, "get_br_symbol", lambda symbol, exch: "RELIANCE-EQ")
    monkeypatch.setattr(fp_orders, "transform_modify_order_data", lambda data, token: {})

    body, status = fp_orders.modify_order(
        {"symbol": "RELIANCE", "exchange": "NSE", "orderid": "10001253450000041478"}, "auth"
    )

    assert body == {"status": "success", "orderid": "10001253450000041478"}
    assert status == 200


# ------------------------------------------------------------------- funds


def test_funds_use_the_consolidated_balance_entry(monkeypatch):
    def entry(header, cash):
        return {
            "limitHeader": header,
            "limitObject": {
                "RMSSubLimits": {
                    "netMarginAvailable": cash,
                    "collateral": 0,
                    "UnrealizedMTM": 0,
                    "RealizedMTM": 0,
                    "marginUtilized": 0,
                }
            },
        }

    answer = {
        "type": "success",
        "result": {"BalanceList": [entry("CASH|NSE|MTF", 0), entry("ALL|ALL|ALL", 12500.5)]},
    }
    monkeypatch.setattr(fp_funds, "get_httpx_client", lambda: _Client(answer))

    assert fp_funds.get_margin_data("auth")["availablecash"] == "12500.50"


# ---------------------------------------------------------- master contract

# The three example rows of the docs (option, future) plus a spread row.
_OPTION = "NSEFO|48225|2|NIFTY|NIFTY2621725700PE|OPTIDX|NIFTY-OPTIDX|2604800048225|588|114.5|1801|0.05|65|1|-1|Nifty 50|2026-02-17T14:30:00|25700|4|NIFTY 17FEB2026 PE 25700|1|1|NIFTY2621725700PE"
_FUTURE = "NSEFO|49229|1|NIFTY|NIFTY26JANFUT|FUTIDX|NIFTY-FUTIDX|2602700049229|28369.8|23211.8|1801|0.1|65|1|-1|Nifty 50|2026-01-27T14:30:00|NIFTY 27JAN2026|2|1|NIFTY26JANFUT"
_SPREAD = "NSEFO|60000|4|NIFTY|NIFTYSPD|FUTIDX|NIFTY-FUTIDX|1|1|1|1|0.1|65|1|-1|Nifty 50|2026-01-27T14:30:00|NIFTY SPD|1|1|NIFTYSPD"
_FO_HEADER = "ExchangeSegment,ExchangeInstrumentID,InstrumentType,Name,Description,Series,NameWithSeries,InstrumentID,PriceBand.High,PriceBand.Low,FreezeQty,TickSize,LotSize,Multiplier,UnderlyingInstrumentId,UnderlyingIndexName,ContractExpiration,StrikePrice,OptionType,DisplayName, PriceNumerator,PriceDenominator,DetailedDescription"


def test_futures_rows_are_read_in_their_own_layout(tmp_path):
    rows = [fp_master._fo_row_in_options_layout(r.split("|")) for r in (_OPTION, _FUTURE, _SPREAD)]
    with open(tmp_path / "NSEFO.csv", "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(_FO_HEADER.split(","))
        writer.writerows(rows)

    df = fp_master.process_compositedge_nfo_csv(str(tmp_path))
    by_token = {str(t): r for t, r in zip(df["token"], df.to_dict("records"), strict=True)}

    assert set(by_token) == {"48225", "49229"}  # the spread is not a contract
    future = by_token["49229"]
    # PriceNumerator 2 sat where the options header puts OptionType, which
    # made this future a put with strike 1 before.
    assert (future["symbol"], future["instrumenttype"], future["strike"]) == (
        "NIFTY27JAN26FUT",
        "FUT",
        0.0,
    )
    assert future["lotsize"] == 65
    option = by_token["48225"]
    assert (option["symbol"], option["instrumenttype"], option["strike"]) == (
        "NIFTY17FEB2625700PE",
        "PE",
        25700.0,
    )


# --------------------------------------------------------------- streaming


def test_streaming_quote_reads_touchline_for_1501():
    import websocket_proxy  # noqa: F401  (resolves the adapter import cycle)
    from broker.fivepaisaxts.streaming.fivepaisaxts_adapter import FivepaisaXTSWebSocketAdapter

    adapter = FivepaisaXTSWebSocketAdapter.__new__(FivepaisaXTSWebSocketAdapter)
    adapter.logger = logging.getLogger("test_fivepaisaxts_streaming")
    message = {
        "MessageCode": 1501,
        "Touchline": {"LastTradedPrice": 1723.0, "Open": 1696.8, "TotalTradedQuantity": 189238},
    }

    quote = adapter._normalize_market_data(message, 2)

    assert (quote["ltp"], quote["open"], quote["volume"]) == (1723.0, 1696.8, 189238)


# ------------------------------------------- one market data session (#2484)


def _jwt(user_id):
    import base64
    import json

    def part(obj):
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")

    return f"{part({'alg': 'HS256'})}.{part({'userID': user_id})}.sig"


class _FakeEio:
    def __init__(self):
        self.state = "disconnected"
        self.aborts = []

    def disconnect(self, abort=False):
        self.aborts.append(abort)
        self.state = "disconnected"


class _FakeSio:
    def __init__(self, error=None):
        self.connected = False
        self.eio = _FakeEio()
        self.error = error
        self.urls = []
        self.paths = []

    def connect(self, url, **kwargs):
        if self.error:
            raise self.error
        self.urls.append(url)
        self.paths.append(kwargs.get("socketio_path"))


def _feed_client(provider, sio=None):
    import websocket_proxy  # noqa: F401  (resolves the adapter import cycle)
    from broker.fivepaisaxts.streaming.fivepaisaxts_websocket import FivepaisaXTSWebSocketClient

    client = FivepaisaXTSWebSocketClient(
        api_key="k", api_secret="s", user_id="admin", feed_token_provider=provider
    )
    client.sio = sio or _FakeSio()
    return client


def test_market_data_user_id_is_the_claim_before_the_underscore():
    from broker.fivepaisaxts.streaming.fivepaisaxts_websocket import FivepaisaXTSWebSocketClient

    token = _jwt("1048131_856F2F2AF32542B762129")
    assert FivepaisaXTSWebSocketClient.market_data_user_id(token) == "1048131"
    assert FivepaisaXTSWebSocketClient.market_data_user_id("not-a-jwt") is None


def test_feed_connects_with_the_stored_token_and_never_logs_in(monkeypatch):
    token = _jwt("1048131_APP")
    client = _feed_client(lambda: token)
    monkeypatch.setattr(
        client, "marketdata_login", lambda: pytest.fail("the feed logged in on its own")
    )

    client.connect()

    [url] = client.sio.urls
    assert f"token={token}" in url and "userID=1048131&" in url
    assert client.sio.paths == ["/apimarketdata/socket.io"]
    assert client.market_data_token == token


def test_reconnect_reads_the_stored_token_again(monkeypatch):
    tokens = iter([_jwt("1_A"), _jwt("1_B")])
    client = _feed_client(lambda: next(tokens))
    monkeypatch.setattr(client, "marketdata_login", lambda: pytest.fail("logged in"))

    client.connect()
    client.connect()

    assert [u.split("token=")[1].split("&")[0] for u in client.sio.urls] == [
        _jwt("1_A"),
        _jwt("1_B"),
    ]


def test_a_failed_connect_with_a_stored_token_raises_instead_of_logging_in(monkeypatch):
    client = _feed_client(
        lambda: _jwt("1_A"), sio=_FakeSio(error=RuntimeError("Already connected"))
    )
    monkeypatch.setattr(client, "marketdata_login", lambda: pytest.fail("logged in"))

    with pytest.raises(RuntimeError):
        client.connect()


def test_without_a_stored_token_the_feed_logs_in_where_history_does(monkeypatch):
    from broker.fivepaisaxts.baseurl import MARKET_DATA_URL
    from broker.fivepaisaxts.streaming import fivepaisaxts_websocket as ws

    posted = []

    def fake_post(url, **kwargs):
        posted.append(url)
        return _Response({"type": "success", "result": {"token": "T", "userID": "1048131"}})

    monkeypatch.setattr(ws.requests, "post", fake_post)
    client = _feed_client(lambda: None)

    client.connect()

    assert posted == [f"{MARKET_DATA_URL}/auth/login"]
    assert "apibinarymarketdata" not in posted[0]


def test_feed_waits_for_the_previous_connection_to_close(monkeypatch):
    sio = _FakeSio()
    sio.eio.state = "connected"
    client = _feed_client(lambda: _jwt("1_A"), sio=sio)
    client.PREVIOUS_CONNECTION_CLOSE_WAIT = 0.3
    rebuilt = []
    monkeypatch.setattr(client, "_setup_socketio", lambda: rebuilt.append(True))

    client.connect()

    assert rebuilt == [True]  # gave up waiting and took a fresh client
    assert sio.eio.aborts == [True]  # and closed the old one instead of abandoning it


def test_adapter_hands_the_stored_feed_token_to_the_feed(monkeypatch):
    import websocket_proxy  # noqa: F401  (resolves the adapter import cycle)
    from broker.fivepaisaxts.streaming import fivepaisaxts_adapter as adapter_mod

    reads = []
    monkeypatch.setattr(adapter_mod, "get_auth_token", lambda user_id, bypass_cache=True: "auth")
    monkeypatch.setattr(
        adapter_mod, "get_feed_token", lambda user_id: reads.append(user_id) or _jwt("1_A")
    )
    monkeypatch.setenv("BROKER_API_KEY_MARKET", "k")
    monkeypatch.setenv("BROKER_API_SECRET_MARKET", "s")
    adapter = adapter_mod.FivepaisaXTSWebSocketAdapter.__new__(
        adapter_mod.FivepaisaXTSWebSocketAdapter
    )
    adapter.logger = logging.getLogger("test_fivepaisaxts_streaming")

    adapter.initialize("fivepaisaxts", "admin")
    reads.clear()

    assert adapter.ws_client.feed_token_provider() == _jwt("1_A")
    assert reads == ["admin"]


def test_history_logs_in_again_once_on_an_invalid_token(monkeypatch):
    import pandas as pd

    from broker.fivepaisaxts.api import data as fp_data

    answers = [
        {"type": "error", "code": "e-session-0007", "description": "Invalid Token"},
        {
            "type": "success",
            "result": {"dataReponse": "1737331200|1316|1316|1300.25|1305.45|14040244|0|"},
        },
    ]
    tokens_used = []

    def fake_api(endpoint, auth, method="GET", payload="", feed_token=None, params=None):
        tokens_used.append(feed_token)
        return answers.pop(0)

    class _Row:
        token = "26000"

    class _Query:
        def filter(self, *args):
            return self

        def first(self):
            return _Row()

    class _Session:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def query(self, model):
            return _Query()

    monkeypatch.setattr(fp_data, "get_api_response", fake_api)
    monkeypatch.setattr(fp_data, "get_br_symbol", lambda symbol, exchange: "NIFTY 50")
    monkeypatch.setattr(fp_data, "db_session", lambda: _Session())
    monkeypatch.setattr(fp_data, "refresh_feed_token", lambda: ("NEW", "1048131", None))

    handler = fp_data.BrokerData("auth", feed_token="OLD")
    df = handler.get_history("NIFTY", "NSE_INDEX", "D", "2025-01-20", "2025-01-20")

    assert tokens_used == ["OLD", "NEW"]
    assert len(df) == 1 and isinstance(df, pd.DataFrame)


# ------------------------------------- feed transport and subscriptions


def test_socketio_client_leaves_reconnecting_to_the_adapter():
    """The library's own reconnect raced the adapter's on one client and the
    loser failed with "Already connected" (issue #2484)."""
    client = _feed_client(lambda: None, sio=None)
    client._setup_socketio()

    assert client.sio.reconnection is False


class _HookEio:
    def __init__(self, interval, timeout, order):
        self.ping_interval = interval
        self.ping_timeout = timeout
        self.order = order
        self.handlers = {"connect": lambda: order.append(("socketio", self.ping_timeout))}

    def on(self, event, handler):
        self.handlers[event] = handler


def test_engineio_floor_is_set_before_the_write_loop_and_socketio_still_connects():
    client = _feed_client(lambda: None)
    order = []
    eio = _HookEio(25.0, 60.0, order)
    client._hook_engineio_timeout_floor(type("Sio", (), {"eio": eio})())

    eio.handlers["connect"]()  # what Engine.IO calls after its handshake

    floor = client.MIN_ENGINEIO_ACTIVITY_TIMEOUT
    assert max(eio.ping_interval, eio.ping_timeout) + 5 == floor  # was 65s
    assert order == [("socketio", floor - 5)]  # Socket.IO's handler ran, after


def test_engineio_floor_never_lowers_longer_server_timers():
    client = _feed_client(lambda: None)
    eio = _HookEio(25.0, 600.0, [])

    client._apply_engineio_timeout_floor(eio)

    assert (eio.ping_interval, eio.ping_timeout) == (25.0, 600.0)


def test_real_socketio_client_has_the_floor_hooked():
    client = _feed_client(lambda: None)
    client._setup_socketio()
    eio = client.sio.eio
    assert eio.handlers["connect"] != client.sio._handle_eio_connect
    eio.ping_interval, eio.ping_timeout = 25.0, 60.0

    eio.handlers["connect"]()  # no namespaces requested yet, so nothing is sent

    assert max(eio.ping_interval, eio.ping_timeout) + 5 >= client.MIN_ENGINEIO_ACTIVITY_TIMEOUT


def test_failed_connect_closes_the_transport_and_retries_on_a_new_client(monkeypatch):
    sio = _FakeSio(error=RuntimeError("Connection refused"))
    sio.eio.state = "connecting"
    client = _feed_client(lambda: _jwt("1_A"), sio=sio)
    sio.eio.state = "disconnected"  # let the pre-connect wait pass

    def failing_connect(url, **kwargs):
        sio.eio.state = "connecting"  # half-open when it fails
        raise RuntimeError("Connection refused")

    sio.connect = failing_connect

    with pytest.raises(RuntimeError):
        client.connect()

    assert sio.eio.aborts == [True]
    assert client.sio is not sio


def test_disconnect_closes_a_transport_that_is_not_marked_connected():
    sio = _FakeSio()
    sio.eio.state = "connecting"
    client = _feed_client(lambda: None, sio=sio)

    client.disconnect()

    assert sio.eio.aborts == [True]
    assert client.sio is None


def _subscribing_client(monkeypatch, replies):
    from broker.fivepaisaxts.streaming import fivepaisaxts_websocket as ws

    sent = []

    def fake_post(url, json=None, **kwargs):
        sent.append([i["exchangeInstrumentID"] for i in json["instruments"]])
        reply = replies(json["instruments"])
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(ws.requests, "post", fake_post)
    client = _feed_client(lambda: None)
    client.connected = True
    client.market_data_token = "T"
    return client, sent


def _inst(i):
    return {"exchangeSegment": 1, "exchangeInstrumentID": str(i)}


_OK = _Response({"type": "success", "result": {"listQuotes": []}})
_DUPLICATE = _Response(
    {"type": "error", "code": "e-session-0002", "description": "Instrument Already Subscribed !"},
    status_code=400,
)
_REFUSED = _Response({"type": "error", "code": "e-x", "description": "Invalid instrument"}, 400)


def test_a_refused_batch_is_sent_one_at_a_time(monkeypatch):
    """One instrument the server will not take used to cost every other
    instrument in the same request its subscription."""

    def replies(instruments):
        ids = [i["exchangeInstrumentID"] for i in instruments]
        if len(ids) > 1:
            return _DUPLICATE  # the server answers the request as a whole
        return {"1": _OK, "2": _DUPLICATE, "3": _REFUSED}[ids[0]]

    client, sent = _subscribing_client(monkeypatch, replies)

    confirmed = client.subscribe("batch_1", 2, [_inst(1), _inst(2), _inst(3)])

    assert sent == [["1", "2", "3"], ["1"], ["2"], ["3"]]
    assert [i["exchangeInstrumentID"] for i in confirmed] == ["1", "2"]
    assert sorted(k[2] for k in client.subscriptions) == ["1", "2"]


def test_a_single_already_subscribed_instrument_counts_as_subscribed(monkeypatch):
    client, sent = _subscribing_client(monkeypatch, lambda instruments: _DUPLICATE)

    assert client.subscribe("batch_1", 2, [_inst(7)]) == [_inst(7)]
    assert sent == [["7"]]


def test_replaying_the_book_on_every_reconnect_does_not_grow_it(monkeypatch):
    """Each reconnect resent the book under new batch ids, and each id stayed
    in the book: it grew all day, and every 1105 tick scanned all of it."""
    client, _ = _subscribing_client(monkeypatch, lambda instruments: _OK)

    for n in range(20):
        client.subscribe(f"batch_mode_2_{n}", 2, [_inst(1), _inst(2)])

    assert len(client.subscriptions) == 2


def test_unsubscribe_removes_the_instrument_from_the_book(monkeypatch):
    from broker.fivepaisaxts.streaming import fivepaisaxts_websocket as ws

    client, _ = _subscribing_client(monkeypatch, lambda instruments: _OK)
    monkeypatch.setattr(ws.requests, "put", lambda *a, **k: _OK)
    client.subscribe("batch_1", 2, [_inst(1), _inst(2)])

    client.unsubscribe("NIFTY_NSE_2", 2, [{"exchangeSegment": 1, "exchangeInstrumentID": 1}])

    assert [k[2] for k in client.subscriptions] == ["2"]


def test_a_network_error_reaches_the_adapter_so_it_queues_the_batch_again(monkeypatch):
    import requests as _requests

    client, _ = _subscribing_client(
        monkeypatch, lambda instruments: _requests.ConnectionError("reset")
    )

    with pytest.raises(_requests.ConnectionError):
        client.subscribe("batch_1", 2, [_inst(1)])
    assert client.subscriptions == {}


def test_1105_ticks_pass_only_for_confirmed_instruments(monkeypatch):
    client, _ = _subscribing_client(monkeypatch, lambda instruments: _OK)
    client.subscribe("batch_1", 2, [_inst(1140025)])
    ticks = []
    client.on_data = lambda _client, data: ticks.append(data["ExchangeInstrumentID"])

    client._process_1105_data("t:1_1140025,110:2067.75")
    client._process_1105_data("t:1_999,110:1.0")

    assert ticks == [1140025]
