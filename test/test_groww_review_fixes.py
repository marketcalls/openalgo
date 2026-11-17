"""Groww fixes from the cubic review of the Groww API alignment PR.

Each test pins one finding:
- login failures get advice that matches why Groww refused, and a rate-limit
  refusal by OpenAlgo itself is not reported as Groww being unreachable;
- BrokerBusyError (OpenAlgo's own pacing refusal) reaches the services, which
  answer it with a busy/retry response, instead of being turned into a
  generic Groww error;
- a multiquote symbol Groww priced is returned even when its OHLC entry is a
  bare number;
- an order for a bond whose Groww trading symbol is shared by several series is
  refused rather than sent to a series Groww would have to guess.
"""

import json
from types import SimpleNamespace

import pytest

import broker.groww.api.auth_api as auth_api
import broker.groww.api.data as data_api
import broker.groww.api.order_api as order_api
import broker.groww.api.rate_limiter as rl
from utils.broker_backpressure import BrokerBusyError


class Resp:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body
        self.text = json.dumps(body)
        self.headers = {}

    def json(self):
        return self._body

    def raise_for_status(self):
        pass


@pytest.fixture(autouse=True)
def no_pacing(monkeypatch):
    monkeypatch.setattr(rl.time, "sleep", lambda *_: None)


# --- login -----------------------------------------------------------------

REFUSED = {"status": "FAILURE", "error": {"code": "GA003", "message": "Unable to serve request currently"}}


@pytest.mark.parametrize(
    "status,expect,avoid",
    [
        (429, "Wait a minute", "API key and secret"),
        (503, "not the problem", "API key and secret"),
        (401, "API key and secret", "Wait a minute"),
    ],
)
def test_login_advice_matches_why_groww_refused(monkeypatch, status, expect, avoid):
    monkeypatch.setattr(auth_api, "groww_request", lambda *a, **k: Resp(status, REFUSED))
    token, error = auth_api.get_access_token_via_checksum("key", "secret")
    assert token is None
    assert expect in error and avoid not in error


def test_login_rate_limit_refusal_is_not_reported_as_unreachable(monkeypatch):
    def busy(*a, **k):
        raise BrokerBusyError("Too many requests are waiting for Groww. Try again shortly.")

    monkeypatch.setattr(auth_api, "groww_request", busy)
    token, error = auth_api.get_access_token_via_checksum("key", "secret")
    assert token is None
    assert error == "Too many requests are waiting for Groww. Try again shortly."


# --- BrokerBusyError passes through --------------------------------------

def _busy(*a, **k):
    raise BrokerBusyError()


def test_get_api_response_passes_broker_busy_through(monkeypatch):
    monkeypatch.setattr(data_api, "groww_request", _busy)
    with pytest.raises(BrokerBusyError):
        data_api.get_api_response("/v1/live-data/quote", "token", params={})


def test_place_order_passes_broker_busy_through(monkeypatch):
    record = SimpleNamespace(brsymbol="RELIANCE")
    _fake_symtoken(monkeypatch, record, sharing=1)
    monkeypatch.setattr(order_api, "groww_request", _busy)
    with pytest.raises(BrokerBusyError):
        order_api.place_order_api(
            {"symbol": "RELIANCE", "exchange": "NSE", "action": "BUY", "quantity": "1",
             "pricetype": "MARKET", "product": "MIS"},
            "token",
        )


# --- multiquotes: priced symbol with a bare-number OHLC entry --------------

def test_multiquote_keeps_a_priced_symbol_whose_ohlc_is_a_bare_number(monkeypatch):
    def api(endpoint, auth_token, method="GET", params=None, **k):
        if endpoint.endswith("/ohlc"):
            return {"status": "SUCCESS", "payload": {"NSE_ABC": 101.5}}
        return {"status": "SUCCESS", "payload": {"NSE_ABC": 101.5}}

    monkeypatch.setattr(data_api, "get_api_response", api)
    bd = data_api.BrokerData("token")
    results = bd._fetch_ohlc_batch(["NSE_ABC"], "CASH", {"NSE_ABC": {"symbol": "ABC", "exchange": "NSE"}})
    assert results[0]["data"]["ltp"] == 101.5
    assert "error" not in results[0]


def test_multiquote_without_any_price_is_an_error(monkeypatch):
    monkeypatch.setattr(data_api, "get_api_response",
                        lambda *a, **k: {"status": "SUCCESS", "payload": {}})
    bd = data_api.BrokerData("token")
    results = bd._fetch_ohlc_batch(["NSE_ABC"], "CASH", {"NSE_ABC": {"symbol": "ABC", "exchange": "NSE"}})
    assert "error" in results[0]


# --- orders for a trading symbol shared by several series ------------------

def _fake_symtoken(monkeypatch, record, sharing):
    import broker.groww.database.master_contract_db as mc

    class Query:
        def filter_by(self, **kw):
            self.kw = kw
            return self

        def first(self):
            return record

        def count(self):
            return sharing

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def query(self, model):
            return Query()

    monkeypatch.setattr(mc, "db_session", lambda: Session())


def test_order_for_a_shared_series_trading_symbol_is_refused(monkeypatch):
    _fake_symtoken(monkeypatch, SimpleNamespace(brsymbol="IMC1"), sharing=3)
    sent = []
    monkeypatch.setattr(order_api, "groww_request", lambda *a, **k: sent.append(a) or Resp(200, {}))
    res, body, orderid = order_api.place_order_api(
        {"symbol": "IMC1-N2", "exchange": "NSE", "action": "BUY", "quantity": "1",
         "pricetype": "MARKET", "product": "CNC"},
        "token",
    )
    assert res.status == 400 and orderid is None
    assert "IMC1" in body["message"] and "series" in body["message"]
    assert not sent
