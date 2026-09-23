"""A smart order must place nothing when the broker's position read fails.

Every broker plugin's place_smartorder_api reads the open position, compares it
with the target and places the difference. Most of them used to read a failed
position read (a network error, an HTTP error, an error envelope in the body,
a body that would not parse) as a net quantity of 0, which is what an empty
book reads as, so the order was sized against a flat position the account did
not have: an entry or a flip placed the full quantity on top of the real
position, doubling or reversing it.

These tests drive each plugin's real smart-order code against a mocked HTTP
layer (the shared httpx client is swapped for one on an httpx.MockTransport),
with no broker account and no network. Only place_order_api is replaced, by a
recorder, so the tests see exactly which order would have been sent. For every
broker:

- each failure kind sends nothing and returns the trader-facing sentence,
- an empty position book is still flat, exactly as before,
- a real position produces the same order as before.
"""

import importlib
import os
import time
from dataclasses import dataclass, field, replace
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest

import utils.httpx_client as httpx_client
from utils.position_read import (
    EMPTY_BOOK_MESSAGE_FIELDS,
    PositionReadError,
    position_read_failed_message,
    read_position_book,
    refuse_smart_order_on_read_failure,
    says_no_positions,
)

BROKERS = sorted(
    name
    for name in os.listdir("broker")
    if os.path.exists(os.path.join("broker", name, "api", "order_api.py"))
)

FAILURES = ("exception", "http_error", "error_status", "unparseable")

TOKEN = "3045"
HELD = 10  # the position the account really holds
TARGET = -5  # the smart order's position_size: flip from long 10 to short 5


def _xts_book(qty):
    rows = []
    if qty is not None:
        rows = [
            {
                "TradingSymbol": "SBIN",
                "ExchangeSegment": "NSECM",
                "ProductType": "MIS",
                "Quantity": str(qty),
            }
        ]
    return {
        "type": "success",
        "code": "s-portfolio-0005",
        "description": "Get Net Position successfully!",
        "result": {"positionList": rows},
    }


XTS_ERROR = {
    "type": "error",
    "code": "e-session-0007",
    "description": "Invalid Token",
    "result": {},
}


def _noren_book(qty):
    if qty is None:
        return {"stat": "Not_Ok", "emsg": "no data"}
    return [{"stat": "Ok", "tsym": "SBIN-EQ", "exch": "NSE", "prd": "I", "netqty": str(qty)}]


NOREN_ERROR = {"stat": "Not_Ok", "emsg": "Session Expired :  Invalid Session Key"}


@dataclass
class Spec:
    """How one broker answers its position book, and what its session needs."""

    path: str  # a substring of the position-book URL
    book: Any  # book(qty) -> response body; qty None means an empty book
    error: Any  # the broker's own error envelope, sent with HTTP 200
    br_symbol: str = "SBIN"
    symbol: str = "SBIN"
    exchange: str = "NSE"
    auth: str = "access-token"
    # Pre-existing and not changed here: the plugin reads every position as
    # flat, even when the read works. test_held_position_is_read documents it.
    reads_flat: bool = False
    patches: dict = field(default_factory=dict)  # module attribute -> replacement
    fail_path: str | None = None  # narrower failure target than `path`


def _groww_book(request, qty):
    segment = parse_qs(request.url.query.decode()).get("segment", ["CASH"])[0]
    rows = []
    if qty is not None and segment == "CASH":
        rows = [
            {
                "trading_symbol": "SBIN",
                "segment": "CASH",
                "exchange": "NSE",
                "product": "MIS",
                "quantity": qty,
            }
        ]
    return {"status": "SUCCESS", "payload": {"positions": rows}}


def _indmoney_book(request, qty):
    params = parse_qs(request.url.query.decode())
    rows = []
    wanted = params.get("segment") == ["equity"] and params.get("product") == ["intraday"]
    if qty is not None and wanted:
        rows = [{"security_id": TOKEN, "symbol": "SBIN", "net_qty": qty, "exchange": "NSE"}]
    return {"status": "success", "data": rows}


def _delta_book(request, qty):
    if "/v2/wallet/balances" in str(request.url):
        return {"success": True, "result": []}
    rows = [] if qty is None else [{"product_symbol": "BTCUSD", "size": qty}]
    return {"success": True, "result": rows}


class _Limiter:
    def acquire(self, *args, **kwargs):
        return None


def _no_rate_limit(*args, **kwargs):
    return None


def _plain_request(client, method, url, **kwargs):
    return client.request(method, url, **kwargs)


SPECS = {
    "aliceblue": Spec(
        path="/positions",
        br_symbol="SBIN-EQ",
        book=lambda q: (
            {"status": "Not_Ok", "message": "EC920"}
            if q is None
            else {
                "status": "Ok",
                "result": [
                    {
                        "tradingSymbol": "SBIN-EQ",
                        "exchange": "NSE",
                        "product": "INTRADAY",
                        "netQuantity": q,
                    }
                ],
            }
        ),
        error={"status": "Not_Ok", "message": "EC087"},
        patches={"apply_rate_limit": _no_rate_limit},
    ),
    "angel": Spec(
        path="getPosition",
        br_symbol="SBIN-EQ",
        book=lambda q: {
            "status": True,
            "message": "SUCCESS",
            "errorcode": "",
            "data": None
            if q is None
            else [
                {
                    "tradingsymbol": "SBIN-EQ",
                    "exchange": "NSE",
                    "producttype": "INTRADAY",
                    "netqty": str(q),
                }
            ],
        },
        error={"status": False, "message": "Invalid Token", "errorcode": "AG8001", "data": None},
    ),
    "arrow": Spec(
        path="/user/positions",
        br_symbol="SBIN-EQ",
        book=lambda q: {
            "status": "success",
            "data": []
            if q is None
            else [{"symbol": "SBIN-EQ", "exchange": "NSE", "product": "I", "qty": q}],
        },
        error={"status": "error", "message": "Invalid session"},
    ),
    "compositedge": Spec(
        path="/portfolio/positions", book=_xts_book, error=XTS_ERROR, reads_flat=True
    ),
    "definedge": Spec(
        path="/positions",
        br_symbol="SBIN-EQ",
        auth="session:::susertoken:::apitoken",
        book=lambda q: {
            "status": "SUCCESS",
            "positions": []
            if q is None
            else [
                {
                    "tradingsymbol": "SBIN-EQ",
                    "exchange": "NSE",
                    "product_type": "INTRADAY",
                    "net_quantity": str(q),
                }
            ],
        },
        error={"status": "ERROR", "message": "Session expired"},
        patches={"rate_limited_request": _plain_request},
    ),
    "deltaexchange": Spec(
        path="/v2/",
        fail_path="/v2/positions/margined",
        symbol="BTCUSD",
        br_symbol="BTCUSD",
        exchange="CRYPTO",
        book=_delta_book,
        error={"success": False, "error": {"code": "invalid_api_key"}},
        patches={"consume": _no_rate_limit},
    ),
    "dhan": Spec(
        path="/v2/positions",
        book=lambda q: (
            []
            if q is None
            else [
                {
                    "securityId": TOKEN,
                    "tradingSymbol": "SBIN",
                    "exchangeSegment": "NSE_EQ",
                    "productType": "INTRADAY",
                    "netQty": q,
                }
            ]
        ),
        error={
            "errorType": "Invalid_Authentication",
            "errorCode": "DH-901",
            "errorMessage": "Client ID or user generated access token is invalid or expired.",
        },
    ),
    "firstock": Spec(
        path="/positionBook",
        br_symbol="SBIN-EQ",
        book=lambda q: {
            "status": "success",
            "data": []
            if q is None
            else [
                {
                    "tradingSymbol": "SBIN-EQ",
                    "exchange": "NSE",
                    "product": "I",
                    "netQuantity": str(q),
                }
            ],
        },
        error={"status": "failed", "code": "401", "error": {"message": "Invalid jKey"}},
    ),
    "fivepaisa": Spec(
        path="NetPositionNetWise",
        book=lambda q: {
            "head": {"status": "0", "statusDescription": "Success"},
            "body": {
                "Message": "Success",
                "Status": 0,
                "NetPositionDetail": []
                if q is None
                else [
                    {
                        "ScripCode": int(TOKEN),
                        "Exch": "N",
                        "ExchType": "C",
                        "OrderFor": "I",
                        "NetQty": q,
                    }
                ],
            },
        },
        error={"head": {"status": "2", "statusDescription": "Invalid Session"}, "body": None},
    ),
    "fivepaisaxts": Spec(
        path="/portfolio/positions", book=_xts_book, error=XTS_ERROR, reads_flat=True
    ),
    "flattrade": Spec(
        path="PositionBook",
        br_symbol="SBIN-EQ",
        book=_noren_book,
        error=NOREN_ERROR,
        patches={"DATA_LIMITER": _Limiter()},
    ),
    "fyers": Spec(
        path="/api/v3/positions",
        br_symbol="NSE:SBIN-EQ",
        book=lambda q: {
            "s": "ok",
            "code": 200,
            "netPositions": []
            if q is None
            else [{"symbol": "NSE:SBIN-EQ", "productType": "INTRADAY", "netQty": q}],
        },
        error={"s": "error", "code": -16, "message": "Could not authenticate the user"},
        patches={"apply_rate_limit": _no_rate_limit},
    ),
    "groww": Spec(
        path="/v1/positions/user",
        book=_groww_book,
        error={"status": "FAILURE", "error": {"code": "GA005", "message": "Invalid token"}},
        reads_flat=True,
    ),
    "hdfcsecurities": Spec(
        path="cumulative-positions",
        book=lambda q: {
            "status": "success",
            "data": {
                "net": []
                if q is None
                else [
                    {
                        "security_id": "SBIN",
                        "exchange": "NSE",
                        "product": "INTRADAY",
                        "net_qty": q,
                    }
                ]
            },
        },
        error={"status": "error", "message": "Session expired"},
        patches={"_enrich_with_ltp": _no_rate_limit},
    ),
    "hdfcsky": Spec(
        path="/oapi/v1/positions",
        book=lambda q: {
            "status": "success",
            "data": []
            if q is None
            else [
                {
                    "trading_symbol": "SBIN",
                    "exchange": "NSE",
                    "product": "MIS",
                    "net_quantity": q,
                }
            ],
        },
        error={"error": "invalid credentials"},
    ),
    "ibulls": Spec(path="/portfolio/positions", book=_xts_book, error=XTS_ERROR),
    "iifl": Spec(path="/portfolio/positions", book=_xts_book, error=XTS_ERROR, reads_flat=True),
    "iiflcapital": Spec(
        path="/positions",
        br_symbol="SBIN-EQ",
        book=lambda q: {
            "status": "Ok",
            "message": "Success",
            "result": [] if q is None else [{"tradingSymbol": "SBIN-EQ", "netQuantity": q}],
        },
        error={"status": "Error", "message": "Session is invalid"},
        patches={"apply_rate_limit": _no_rate_limit},
    ),
    "indmoney": Spec(
        path="/portfolio/positions",
        book=_indmoney_book,
        error={"status": "failure", "error": {"msg": "Invalid access token"}},
        patches={
            "rate_limited_request": _plain_request,
            "_position_exchange": lambda position: "NSE",
        },
    ),
    "jainamxts": Spec(path="/portfolio/positions", book=_xts_book, error=XTS_ERROR),
    "kotak": Spec(
        path="/quick/user/positions",
        br_symbol="SBIN-EQ",
        auth="session:::sid:::https://kotak.invalid:::access",
        book=lambda q: {
            "stat": "Ok",
            "stCode": 200,
            "data": []
            if q is None
            else [
                {
                    "trdSym": "SBIN-EQ",
                    "exSeg": "nse_cm",
                    "prod": "MIS",
                    "flBuyQty": str(q),
                    "flSellQty": "0",
                    "cfBuyQty": "0",
                    "cfSellQty": "0",
                }
            ],
        },
        error={"stat": "Not_Ok", "emsg": "Invalid session", "stCode": 1003},
        patches={"_backfill_ltp": _no_rate_limit},
    ),
    "motilal": Spec(
        path="/getposition",
        book=lambda q: {
            "status": "SUCCESS",
            "message": "",
            "errorcode": "",
            "data": None
            if q is None
            else [
                {
                    "symboltoken": int(TOKEN),
                    "exchange": "NSE",
                    "productname": "VALUEPLUS",
                    "buyquantity": q,
                    "sellquantity": 0,
                }
            ],
        },
        error={"status": "FAILURE", "message": "Invalid Auth Token", "errorcode": "MO8002"},
    ),
    "mstock": Spec(
        path="/portfolio/positions",
        book=lambda q: {
            "status": True,
            "message": "SUCCESS",
            "data": None
            if q is None
            else [
                {
                    "symboltoken": TOKEN,
                    "exchange": "NSE",
                    "producttype": "INTRADAY",
                    "netqty": str(q),
                }
            ],
        },
        error={"status": False, "message": "Invalid token", "errorcode": "AB1010", "data": None},
    ),
    "nubra": Spec(
        path="/sentinel/portfolio/positions",
        book=lambda q: {
            "portfolio": {
                "positions": []
                if q is None
                else [{"symbol": "SBIN", "deliveryType": "IDAY", "netQty": q}]
            }
        },
        error={"error": "Invalid session"},
        patches={"resolve_position": lambda position: ("SBIN", "NSE")},
    ),
    "paytm": Spec(
        path="/orders/v1/position",
        book=lambda q: {
            "status": "success",
            "message": "",
            "data": []
            if q is None
            else [
                {
                    "security_id": TOKEN,
                    "exchange": "NSE",
                    "product": "I",
                    "instrument": "EQUITY",
                    "display_name": "SBIN",
                    "net_qty": q,
                }
            ],
        },
        error={"status": "error", "message": "Invalid token"},
    ),
    "pocketful": Spec(
        path="/api/v1/positions",
        br_symbol="SBIN-EQ",
        book=lambda q: {
            "status": "success",
            "data": []
            if q is None
            else [{"tradingsymbol": "SBIN-EQ", "exchange": "NSE", "product": "MIS", "quantity": q}],
        },
        error={"status": "error", "message": "Invalid token"},
        patches={"get_client_id": lambda auth: "CLIENT01"},
    ),
    "rmoney": Spec(path="/portfolio/positions", book=_xts_book, error=XTS_ERROR),
    "samco": Spec(
        path="/position/getPositions",
        br_symbol="SBIN-EQ",
        book=lambda q: {
            "status": "Success",
            "positionDetails": []
            if q is None
            else [
                {
                    "tradingSymbol": "SBIN-EQ",
                    "exchange": "NSE",
                    "productCode": "MIS",
                    "netQuantity": str(q),
                    "transactionType": "BUY",
                }
            ],
        },
        error={"status": "Failure", "statusMessage": "Session Expired"},
    ),
    "shoonya": Spec(path="PositionBook", br_symbol="SBIN-EQ", book=_noren_book, error=NOREN_ERROR),
    "tradejini": Spec(
        path="/api/oms/positions",
        book=lambda q: (
            {"s": "no-data"}
            if q is None
            else {
                "s": "ok",
                "d": [
                    {
                        "netQty": q,
                        "symId": "EQT_SBIN_EQ_NSE",
                        "product": "intraday",
                        "netAvgPrice": 0,
                        "sym": {"id": "EQT_SBIN_EQ_NSE", "symbol": "SBIN", "exchange": "NSE"},
                    }
                ],
            }
        ),
        error={"s": "error", "msg": "Invalid session"},
    ),
    "tradesmart": Spec(
        path="/PositionBook", br_symbol="SBIN-EQ", book=_noren_book, error=NOREN_ERROR
    ),
    "upstox": Spec(
        path="/v2/portfolio/short-term-positions",
        br_symbol="SBIN-EQ",
        book=lambda q: {
            "status": "success",
            "data": []
            if q is None
            else [{"tradingsymbol": "SBIN-EQ", "exchange": "NSE", "product": "I", "quantity": q}],
        },
        error={
            "status": "error",
            "errors": [{"errorCode": "UDAPI100050", "message": "Invalid token used"}],
        },
        patches={"apply_rate_limit": _no_rate_limit},
    ),
    "wisdom": Spec(path="/portfolio/positions", book=_xts_book, error=XTS_ERROR, reads_flat=True),
    "zebu": Spec(path="PositionBook", br_symbol="SBIN-EQ", book=_noren_book, error=NOREN_ERROR),
    "zerodha": Spec(
        path="/portfolio/positions",
        book=lambda q: {
            "status": "success",
            "data": {
                "net": []
                if q is None
                else [
                    {"tradingsymbol": "SBIN", "exchange": "NSE", "product": "MIS", "quantity": q}
                ],
                "day": [],
            },
        },
        error={
            "status": "error",
            "message": "Incorrect `api_key` or `access_token`.",
            "error_type": "TokenException",
        },
    ),
}

# Dhan's sandbox speaks the same API as Dhan.
SPECS["dhan_sandbox"] = SPECS["dhan"]

# Plugins whose book builder needs the request (several calls to one path).
REQUEST_AWARE = {"groww", "indmoney", "deltaexchange"}


def test_every_broker_plugin_is_covered():
    assert set(SPECS) == set(BROKERS)


class _NoSleep:
    """The time module, minus sleep: retries in the plugins must not slow the suite."""

    def __getattr__(self, name):
        return getattr(time, name)

    @staticmethod
    def sleep(_seconds):
        return None


@dataclass
class Harness:
    broker: str
    spec: Spec
    module: Any
    monkeypatch: Any = None
    requests: list = field(default_factory=list)
    orders: list = field(default_factory=list)

    def serve(self, respond):
        """Answer every request with respond(url) instead of the scenario's book."""

        def handler(request):
            url = str(request.url)
            self.requests.append((request.method, url))
            return respond(url)

        client = httpx.Client(transport=httpx.MockTransport(handler))
        self.monkeypatch.setattr(httpx_client, "_httpx_client", client)

    def smart_order(self, position_size=TARGET, quantity=abs(TARGET)):
        data = {
            "strategy": "test",
            "symbol": self.spec.symbol,
            "exchange": self.spec.exchange,
            "product": "MIS",
            "action": "SELL",
            "quantity": str(quantity),
            "position_size": str(position_size),
            "pricetype": "MARKET",
            "price": "0",
            "trigger_price": "0",
            "disclosed_quantity": "0",
        }
        return self.module.place_smartorder_api(data, self.spec.auth)

    def position_reads(self):
        return [url for method, url in self.requests if self.spec.path in url]

    def other_requests(self):
        return [(method, url) for method, url in self.requests if self.spec.path not in url]


@pytest.fixture
def harness(monkeypatch):
    monkeypatch.setenv("BROKER_API_KEY", "USER01:::CLIENT01:::CODE01")
    monkeypatch.setenv("BROKER_API_SECRET", "SECRET01")

    def build(broker, scenario, held=HELD):
        spec = SPECS[broker]
        module = importlib.import_module(f"broker.{broker}.api.order_api")

        # Symbol master lookups, everywhere a plugin might reach them.
        import database.token_db as token_db

        lookups = {
            "get_br_symbol": lambda symbol, exchange: spec.br_symbol,
            "get_token": lambda symbol, exchange: TOKEN,
            "get_oa_symbol": lambda *args, **kwargs: spec.symbol,
            "get_symbol": lambda *args, **kwargs: spec.symbol,
        }
        for name, fake in lookups.items():
            monkeypatch.setattr(token_db, name, fake)
            if hasattr(module, name):
                monkeypatch.setattr(module, name, fake)
        if broker == "hdfcsecurities":
            import broker.hdfcsecurities.mapping.order_data as hdfc_mapping

            monkeypatch.setattr(hdfc_mapping, "get_oa_symbol", lookups["get_oa_symbol"])

        for name, fake in spec.patches.items():
            monkeypatch.setattr(module, name, fake)
        if getattr(module, "time", None) is time:
            monkeypatch.setattr(module, "time", _NoSleep())

        # Nothing may carry over from another test: no cached book.
        cache = getattr(module, "_position_cache", None)
        if isinstance(cache, dict):
            monkeypatch.setattr(module, "_position_cache", {})

        h = Harness(broker=broker, spec=spec, module=module, monkeypatch=monkeypatch)

        def place_order_api(order_data, auth):
            h.orders.append((order_data["action"], int(float(order_data["quantity"]))))
            response = SimpleNamespace(status=200, status_code=200)
            return response, {"status": "success", "orderid": "OID1"}, "OID1"

        monkeypatch.setattr(module, "place_order_api", place_order_api)

        def body_for(request, qty):
            if broker in REQUEST_AWARE:
                return spec.book(request, qty)
            return spec.book(qty)

        def handler(request):
            url = str(request.url)
            h.requests.append((request.method, url))
            if spec.path not in url:
                return httpx.Response(404, json={"message": "not mocked"})
            fails_here = spec.fail_path is None or spec.fail_path in url
            if scenario in FAILURES and fails_here:
                if scenario == "exception":
                    raise httpx.ConnectError("connection refused", request=request)
                if scenario == "http_error":
                    return httpx.Response(500, json={"message": "Internal Server Error"})
                if scenario == "error_status":
                    return httpx.Response(200, json=spec.error)
                return httpx.Response(
                    200,
                    text="<html><body>502 Bad Gateway</body></html>",
                    headers={"content-type": "text/html"},
                )
            qty = held if scenario == "held" else None
            return httpx.Response(200, json=body_for(request, qty))

        client = httpx.Client(transport=httpx.MockTransport(handler))
        monkeypatch.setattr(httpx_client, "_httpx_client", client)
        return h

    return build


# ---------------------------------------------------------------------------
# The three behaviours, for every broker
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("failure", FAILURES)
@pytest.mark.parametrize("broker", BROKERS)
def test_failed_read_sends_no_order(harness, broker, failure):
    h = harness(broker, failure)

    res, data, orderid = h.smart_order()

    assert h.orders == [], "no order may be sized against a position that was never read"
    assert orderid is None
    assert res is None
    assert data == {"status": "error", "message": position_read_failed_message(broker)}
    assert h.position_reads(), "the plugin never asked for the position book"
    assert h.other_requests() == [], "nothing but the position read may reach the broker"


@pytest.mark.parametrize("broker", BROKERS)
def test_failed_read_refuses_an_exit_too(harness, broker):
    """A close with the read down used to report "no open position" and walk away."""
    h = harness(broker, "error_status")

    res, data, orderid = h.smart_order(position_size=0, quantity=0)

    assert h.orders == []
    assert data["status"] == "error"
    assert data["message"] == position_read_failed_message(broker)


@pytest.mark.parametrize("broker", BROKERS)
def test_empty_book_is_still_flat(harness, broker):
    h = harness(broker, "empty")

    h.smart_order()

    assert h.orders == [("SELL", abs(TARGET))]


@pytest.mark.parametrize("broker", BROKERS)
def test_held_position_gives_the_same_order_as_before(harness, broker):
    h = harness(broker, "held")

    h.smart_order()

    if SPECS[broker].reads_flat:
        # Unchanged by this fix: see test_held_position_is_read.
        expected = ("SELL", abs(TARGET))
    else:
        expected = ("SELL", HELD - TARGET)
    assert h.orders == [expected]


@pytest.mark.parametrize("broker", [b for b in BROKERS if SPECS[b].reads_flat])
@pytest.mark.xfail(
    strict=True,
    reason=(
        "Pre-existing, not changed by this fix: the plugin reads every position as "
        "flat even when the read works (XTS brokers match on keys the XTS book does "
        "not carry; Groww's get_open_position never unwraps get_positions' tuple)."
    ),
)
def test_held_position_is_read(harness, broker):
    h = harness(broker, "held")

    h.smart_order()

    assert h.orders == [("SELL", HELD - TARGET)]


@pytest.mark.parametrize("broker", BROKERS)
def test_a_failed_read_is_not_cached(harness, broker):
    """The next smart order must read again, not replay the failure or a stale book."""
    h = harness(broker, "error_status")
    h.smart_order()
    reads_after_failure = len(h.position_reads())

    h.smart_order()

    assert len(h.position_reads()) > reads_after_failure


# ---------------------------------------------------------------------------
# Specific plugins
# ---------------------------------------------------------------------------


def test_aliceblue_404_is_not_an_empty_book(harness):
    """get_positions reads "not found" as AliceBlue's empty-book answer; an HTTP
    404 from our own request says "Not Found" too and must not qualify."""
    h = harness("aliceblue", "held")
    h.serve(lambda url: httpx.Response(404, text="Not Found"))

    res, data, orderid = h.smart_order()

    assert h.orders == []
    assert data["message"] == position_read_failed_message("aliceblue")


@pytest.mark.parametrize(
    ("message", "placed"),
    [
        # AliceBlue's documented codes decide by meaning: EC920 is "No positions
        # found for this user", EC919 is "Failed to retrieve the position book".
        ("EC920", [("SELL", abs(TARGET))]),
        ("No positions found for this user.", [("SELL", abs(TARGET))]),
        ("EC919", []),
        # The prose is the text of EC919, so it is decided the same way as the
        # bare code: a read that failed. It used to be read as an empty book,
        # and with +10 held an exit then closed nothing.
        ("Failed to retrieve the position book.", []),
        ("EC919: Failed to retrieve the position book.", []),
    ],
)
def test_aliceblue_codes_by_meaning(harness, message, placed):
    h = harness("aliceblue", "held")
    h.serve(lambda url: httpx.Response(200, json={"status": "Not_Ok", "message": message}))

    h.smart_order()

    assert h.orders == placed


def test_aliceblue_failed_to_retrieve_refuses_an_exit(harness):
    h = harness("aliceblue", "held")
    h.serve(
        lambda url: httpx.Response(
            200, json={"status": "Not_Ok", "message": "Failed to retrieve the position book."}
        )
    )

    res, data, orderid = h.smart_order(position_size=0, quantity=0)

    assert h.orders == []
    assert data["message"] == position_read_failed_message("aliceblue")


def test_aliceblue_positions_page_keeps_its_reading_of_the_prose(harness):
    """Only the smart order reads the prose strictly; the Positions page and
    close all keep showing it as an empty book, as they always have."""
    h = harness("aliceblue", "held")
    h.serve(
        lambda url: httpx.Response(
            200, json={"status": "Not_Ok", "message": "Failed to retrieve the position book."}
        )
    )

    assert h.module.get_positions("token") == []
    assert h.module.get_positions("token", strict=True) == {
        "stat": "Not_Ok",
        "emsg": "Failed to retrieve the position book.",
    }


DHAN_DH907 = {
    "errorType": "Data_Error",
    "errorCode": "DH-907",
    "errorMessage": (
        "System is unable to fetch data due to incorrect parameters or no data present."
    ),
}


@pytest.mark.parametrize("broker", ["dhan", "dhan_sandbox"])
def test_dhan_dh907_is_a_failed_read_not_an_empty_book(harness, broker):
    """Dhan's empty book is a bare []. Its DH-907 envelope says "no data present",
    and matching that phrase used to read the envelope as flat: with +10 held a
    flip to -5 sold 5 instead of 15, and an exit closed nothing."""
    h = harness(broker, "held")
    h.serve(lambda url: httpx.Response(200, json=DHAN_DH907))

    res, data, orderid = h.smart_order()
    assert h.orders == []
    assert data["message"] == position_read_failed_message(broker)

    res, data, orderid = h.smart_order(position_size=0, quantity=0)
    assert h.orders == []
    assert data["message"] == position_read_failed_message(broker)
    assert len(h.position_reads()) == 2, "a failed read must not be cached"


@pytest.mark.parametrize(
    ("broker", "envelope"),
    [
        ("zerodha", {"status": "error", "message": "No data available", "error_type": "General"}),
        ("fyers", {"s": "error", "code": -99, "message": "No data found"}),
        ("angel", {"status": False, "message": "No Data", "errorcode": "AB2001", "data": None}),
        ("upstox", {"status": "error", "errors": [{"message": "No data"}]}),
        ("ibulls", {"type": "error", "code": "e-portfolio-0001", "description": "No data"}),
    ],
)
def test_error_envelope_saying_no_data_refuses_where_the_empty_book_is_a_success(
    harness, broker, envelope
):
    """These brokers answer an empty book with a success envelope, which their own
    check already accepts, so an error envelope is a failed read whatever it says."""
    assert broker not in EMPTY_BOOK_MESSAGE_FIELDS
    h = harness(broker, "held")
    h.serve(lambda url: httpx.Response(200, json=envelope))

    res, data, orderid = h.smart_order()

    assert h.orders == []
    assert data["message"] == position_read_failed_message(broker)


@pytest.mark.parametrize("broker", ["flattrade", "shoonya", "zebu", "tradesmart"])
def test_noren_empty_book_is_read_from_its_message_only(harness, broker):
    """The Noren family's empty book is {"stat": "Not_Ok", "emsg": "no data"}. A
    failure that only mentions "no data" outside emsg is still a failure."""
    h = harness(broker, "held")
    h.serve(
        lambda url: httpx.Response(
            200,
            json={
                "stat": "Not_Ok",
                "emsg": "Session Expired :  Invalid Session Key",
                "request_time": "no data",
            },
        )
    )

    res, data, orderid = h.smart_order()

    assert h.orders == []
    assert data["message"] == position_read_failed_message(broker)


def test_every_broker_with_an_empty_book_message_exists():
    assert set(EMPTY_BOOK_MESSAGE_FIELDS) <= set(BROKERS)


def test_delta_exchange_wallet_failure_refuses(harness):
    """A spot holding lives in the wallet half of the book; losing it reads as flat."""
    h = harness("deltaexchange", "held")

    def respond(url):
        if "/v2/wallet/balances" in url:
            return httpx.Response(200, json={"success": False, "error": {"code": "internal"}})
        return httpx.Response(200, json={"success": True, "result": []})

    h.serve(respond)

    res, data, orderid = h.smart_order()

    assert h.orders == []
    assert data["message"] == position_read_failed_message("deltaexchange")


def _indmoney_derivative_queries_fail(url):
    params = parse_qs(httpx.URL(url).query.decode())
    if params.get("segment") == ["derivative"]:
        return httpx.Response(403, json={"status": "error", "message": "Segment not enabled"})
    rows = []
    if params.get("product") == ["intraday"]:
        rows = [{"security_id": TOKEN, "symbol": "SBIN", "net_qty": HELD, "exchange": "NSE"}]
    return httpx.Response(200, json={"status": "success", "data": rows})


def test_indmoney_equity_order_survives_a_failed_derivative_query(harness):
    """An account without F&O must keep its equity smart orders: the equity rows
    were read in full, so they are the whole answer for an equity symbol."""
    h = harness("indmoney", "held")
    h.serve(_indmoney_derivative_queries_fail)

    h.smart_order()

    assert h.orders == [("SELL", HELD - TARGET)]


def test_indmoney_derivative_order_refuses_on_a_failed_derivative_query(harness):
    h = harness("indmoney", "held")
    h.serve(_indmoney_derivative_queries_fail)
    h.spec = replace(SPECS["indmoney"], exchange="NFO")

    res, data, orderid = h.smart_order()

    assert h.orders == []
    assert data["message"] == position_read_failed_message("indmoney")


def test_indmoney_book_with_a_failed_derivative_query_is_cached(harness):
    """An account without F&O reads its book once per second, as before, instead of
    paying for all four queries on every equity smart order."""
    h = harness("indmoney", "held")
    h.serve(_indmoney_derivative_queries_fail)

    for _ in range(5):
        res, data, orderid = h.smart_order(position_size=HELD, quantity=abs(TARGET))
        assert data["status"] == "success"

    assert h.orders == []
    assert len(h.position_reads()) == 4, "one read of the four queries, then the cached book"

    # A derivative order in the same second is still refused from that book.
    h.spec = replace(SPECS["indmoney"], exchange="NFO")
    res, data, orderid = h.smart_order()
    assert h.orders == []
    assert data["message"] == position_read_failed_message("indmoney")


def test_groww_cash_order_survives_a_failed_fno_query(harness):
    """Groww's own code expects the FNO read to fail on some accounts; only a
    failed CASH read refuses."""
    h = harness("groww", "held")

    def respond(url):
        if "segment=FNO" in url:
            return httpx.Response(403, json={"status": "FAILURE", "error": {"code": "GA001"}})
        return httpx.Response(200, json={"status": "SUCCESS", "payload": {"positions": []}})

    h.serve(respond)

    h.smart_order()

    assert h.orders == [("SELL", abs(TARGET))]


def _groww_fno_fails(kind):
    def respond(url):
        if "segment=FNO" in url:
            if kind == "exception":
                raise httpx.ConnectError("connection refused")
            if kind == "http_error":
                return httpx.Response(500, text="<html>502 Bad Gateway</html>")
            return httpx.Response(401, json={"status": "FAILURE", "error": {"code": "GA005"}})
        return httpx.Response(200, json={"status": "SUCCESS", "payload": {"positions": []}})

    return respond


@pytest.mark.parametrize("kind", ["error_status", "http_error", "exception"])
@pytest.mark.parametrize("exchange", ["NFO", "BFO"])
def test_groww_fno_order_refuses_on_a_failed_fno_query(harness, kind, exchange):
    """A failed FNO read used to come back as a successful book with no FNO rows,
    so an F&O smart order would read the position as flat."""
    h = harness("groww", "held")
    h.serve(_groww_fno_fails(kind))
    h.spec = replace(SPECS["groww"], exchange=exchange)

    res, data, orderid = h.smart_order()

    assert h.orders == []
    assert data["message"] == position_read_failed_message("groww")


def test_groww_empty_fno_book_is_not_a_failure(harness):
    h = harness("groww", "empty")
    h.spec = replace(SPECS["groww"], exchange="NFO")

    h.smart_order()

    assert h.orders == [("SELL", abs(TARGET))]


def _tradejini_row(symbol, qty, avg=0):
    sym_id = f"EQT_{symbol}_EQ_NSE"
    return {
        "netQty": qty,
        "symId": sym_id,
        "product": "intraday",
        "netAvgPrice": avg,
        "sym": {"id": sym_id, "symbol": symbol, "exchange": "NSE"},
    }


def _tradejini_book(rows, monkeypatch, h):
    monkeypatch.setattr(
        h.module, "get_oa_symbol", lambda sym, exchange: sym.split("_")[1] if "_" in sym else sym
    )
    h.serve(lambda url: httpx.Response(200, json={"s": "ok", "d": rows}))


def test_tradejini_malformed_row_of_another_symbol_is_skipped(harness, monkeypatch):
    """A row that cannot be read no longer turns every symbol flat: with INFY's
    quantity missing ahead of SBIN +10, a flip to -5 sold 5 instead of 15."""
    h = harness("tradejini", "held")
    _tradejini_book([_tradejini_row("INFY", None), _tradejini_row("SBIN", HELD)], monkeypatch, h)

    h.smart_order()

    assert h.orders == [("SELL", HELD - TARGET)]


def test_tradejini_malformed_row_of_this_symbol_refuses(harness, monkeypatch):
    h = harness("tradejini", "held")
    _tradejini_book([_tradejini_row("SBIN", None)], monkeypatch, h)

    res, data, orderid = h.smart_order()

    assert h.orders == []
    assert data["message"] == position_read_failed_message("tradejini")


def test_tradejini_row_that_cannot_be_transformed_refuses(harness, monkeypatch):
    """get_positions used to drop such a row, which read that symbol as flat."""
    h = harness("tradejini", "held")
    _tradejini_book([_tradejini_row("SBIN", HELD, avg=None)], monkeypatch, h)

    res, data, orderid = h.smart_order()

    assert h.orders == []
    assert data["message"] == position_read_failed_message("tradejini")
    # The Positions page keeps leaving the row out, as before.
    assert h.module.get_positions("token") == {"status": "success", "data": []}


def test_tradejini_unexpected_error_after_the_read_refuses(harness, monkeypatch):
    h = harness("tradejini", "held")
    monkeypatch.setattr(
        h.module,
        "_get_cached_positions",
        lambda auth: {"status": "success", "data": [_Exploding()]},
    )

    res, data, orderid = h.smart_order()

    assert h.orders == []
    assert data["message"] == position_read_failed_message("tradejini")


class _Exploding(dict):
    def get(self, *args, **kwargs):
        raise RuntimeError("row cannot be read")


def test_position_book_page_still_shows_an_empty_book_on_failure(harness):
    """The strict reads are for the smart order only: the plugins' own get_positions
    keep answering the position book page exactly as before."""
    h = harness("fivepaisa", "exception")
    assert h.module.get_positions("token") == {"body": {"NetPositionDetail": []}}

    h = harness("indmoney", "error_status")
    assert h.module.get_positions("token", include_ltp=False) == []

    h = harness("deltaexchange", "error_status")
    assert h.module.get_positions("token") == []


def test_service_layer_reports_the_sentence(harness, monkeypatch):
    """The refusal reaches the API caller as a failed order carrying the sentence."""
    import services.place_smart_order_service as service

    harness("zerodha", "exception")
    published = []
    monkeypatch.setattr(service, "get_analyze_mode", lambda: False)
    monkeypatch.setattr(service.bus, "publish", published.append)

    ok, body, status = service.place_smart_order_with_auth(
        {
            "apikey": "k",
            "strategy": "test",
            "symbol": "SBIN",
            "exchange": "NSE",
            "action": "SELL",
            "product": "MIS",
            "pricetype": "MARKET",
            "quantity": "5",
            "position_size": "-5",
        },
        "token",
        "zerodha",
        {"apikey": "k"},
    )

    assert ok is False
    assert body == {"status": "error", "message": position_read_failed_message("zerodha")}
    assert status == 500
    assert [type(event).__name__ for event in published] == ["OrderFailedEvent"]


# ---------------------------------------------------------------------------
# The shared helper
# ---------------------------------------------------------------------------


def test_message_names_the_broker_and_the_next_step():
    message = position_read_failed_message("iiflcapital")
    assert message == (
        "OpenAlgo could not read your open position from IIFL Capital, so no order "
        "was sent. Check your positions and try again."
    )


def test_unknown_broker_falls_back_to_its_plugin_name():
    assert "from newbroker," in position_read_failed_message("newbroker")


@pytest.mark.parametrize(
    "response",
    [
        {"stat": "Not_Ok", "emsg": "no data"},
        {"status": "Failure", "statusMessage": "No Positions Found"},
        {"status": "error", "message": "You do not have any positions"},
        {"s": "no-data"},
    ],
)
def test_empty_book_answers_are_recognised(response):
    assert says_no_positions(response)


@pytest.mark.parametrize(
    "response",
    [
        {"stat": "Not_Ok", "emsg": "Session Expired :  Invalid Session Key"},
        {"status": "error", "message": "HTTP error: Server error '500 Internal Server Error'"},
        {"type": "error", "description": "Invalid Token"},
        None,
        "<html>" + "no data " * 500 + "</html>",
    ],
)
def test_failures_are_not_mistaken_for_an_empty_book(response):
    assert not says_no_positions(response)


def test_read_position_book_returns_a_good_read_unchanged():
    book = {"status": "success", "data": [1]}
    assert read_position_book("zerodha", lambda: book, lambda d: True) is book


def test_read_position_book_raises_on_an_exception():
    def fetch():
        raise ValueError("boom")

    with pytest.raises(PositionReadError) as exc:
        read_position_book("zerodha", fetch, lambda d: True)
    assert str(exc.value) == position_read_failed_message("zerodha")
    assert "ValueError: boom" in exc.value.detail


def test_says_no_positions_reads_only_the_message_fields():
    # The phrase outside a message field: a failure, not an empty book.
    assert not says_no_positions({"status": "error", "message": "Busy", "detail": "no data"})
    assert not says_no_positions({"stat": "Not_Ok", "emsg": "Invalid session"}, ("message",))
    # Only the named fields count.
    assert says_no_positions({"stat": "Not_Ok", "emsg": "no data"}, ("emsg",))
    assert not says_no_positions({"stat": "Not_Ok", "emsg": "no data"}, ("message",))
    # A nested message.
    assert says_no_positions(
        {"status": "failed", "error": {"message": "No Data"}}, ("error.message",)
    )
    # A long message is not a one-line "no data" answer.
    assert not says_no_positions({"emsg": "no data " * 500}, ("emsg",))


def test_read_position_book_uses_the_empty_book_check_only_where_registered():
    envelope = {"stat": "Not_Ok", "emsg": "no data"}
    assert read_position_book("shoonya", lambda: envelope, lambda d: False) is envelope
    with pytest.raises(PositionReadError):
        read_position_book("zerodha", lambda: envelope, lambda d: False)
    with pytest.raises(PositionReadError):
        read_position_book("dhan", lambda: DHAN_DH907, lambda d: isinstance(d, list))


def test_read_position_book_takes_an_explicit_empty_book_check():
    envelope = {"status": "error", "message": "nothing here"}
    assert (
        read_position_book("zerodha", lambda: envelope, lambda d: False, is_empty=lambda d: True)
        is envelope
    )

    def broken(data):
        raise KeyError("x")

    with pytest.raises(PositionReadError):
        read_position_book("shoonya", lambda: envelope, lambda d: False, is_empty=broken)


def test_read_position_book_raises_when_the_check_fails_or_raises():
    with pytest.raises(PositionReadError):
        read_position_book("zerodha", lambda: {"status": "error"}, lambda d: False)

    def broken_check(data):
        raise KeyError("x")

    with pytest.raises(PositionReadError):
        read_position_book("zerodha", lambda: {"status": "error"}, broken_check)


def test_refusal_decorator_keeps_the_three_part_shape():
    @refuse_smart_order_on_read_failure
    def smart(data, auth):
        raise PositionReadError("angel", "detail")

    assert smart({}, "t") == (
        None,
        {"status": "error", "message": position_read_failed_message("angel")},
        None,
    )


def test_refusal_decorator_leaves_other_errors_alone():
    @refuse_smart_order_on_read_failure
    def smart(data, auth):
        raise RuntimeError("not ours")

    with pytest.raises(RuntimeError):
        smart({}, "t")
