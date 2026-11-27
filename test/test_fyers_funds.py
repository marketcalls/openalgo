"""Fyers funds: availablecash includes realised P&L, and orders mark the cache stale (#2275)."""

import pytest

from broker.fyers.api import funds, order_api

TOKEN = "tok-fyers-funds"


def _ledger(clear, collaterals=0.0):
    return {
        "code": 200,
        "s": "ok",
        "fund_limit": [
            {"id": 3, "title": "Clear Balance", "equityAmount": clear, "commodityAmount": 0},
            {"id": 5, "title": "Collaterals", "equityAmount": collaterals, "commodityAmount": 0},
        ],
    }


class _Resp:
    def __init__(self, body, status=200):
        self._body, self.status_code, self.text = body, status, ""

    def raise_for_status(self):
        if self.status_code >= 400:
            raise funds.httpx.HTTPStatusError("x", request=None, response=self)

    def json(self):
        return self._body


class _Client:
    def __init__(self, body, on_get=None):
        self.body, self.on_get, self.calls = body, on_get, 0

    def get(self, *a, **k):
        self.calls += 1
        if self.on_get:
            self.on_get()
        return _Resp(self.body)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setenv("BROKER_API_KEY", "APPID")
    _clear_state()
    monkeypatch.setattr(funds, "get_positions", lambda auth: {"s": "ok", "netPositions": []})
    yield
    _clear_state()


def _clear_state():
    for name in ("_cache", "_rate_limit", "_generation"):
        getattr(funds, name, {}).clear()


def _use(monkeypatch, client, realised=0.0):
    monkeypatch.setattr(funds, "get_httpx_client", lambda: client)
    monkeypatch.setattr(
        funds,
        "map_position_data",
        lambda raw: [{"realized_profit": realised, "unrealized_profit": 0}] if realised else [],
    )


def test_availablecash_adds_realised_pnl(monkeypatch):
    _use(monkeypatch, _Client(_ledger(24985.1)), realised=10068.5)
    r = funds.get_margin_data(TOKEN)
    assert r["availablecash"] == "35053.60"
    assert r["m2mrealized"] == "10068.50"


def test_availablecash_subtracts_realised_loss(monkeypatch):
    _use(monkeypatch, _Client(_ledger(50000)), realised=-2000)
    assert funds.get_margin_data(TOKEN)["availablecash"] == "48000.00"


def test_collateral_not_added_to_cash(monkeypatch):
    _use(monkeypatch, _Client(_ledger(100000, collaterals=50000)))
    r = funds.get_margin_data(TOKEN)
    assert r["availablecash"] == "100000.00"
    assert r["collateral"] == "50000.00"


def test_error_code_returns_empty(monkeypatch):
    _use(monkeypatch, _Client({"code": 401, "message": "expired"}))
    assert funds.get_margin_data(TOKEN) == {}


def test_cache_served_until_an_order_call(monkeypatch):
    client = _Client(_ledger(1000))
    _use(monkeypatch, client)
    _orders(monkeypatch)
    funds.get_margin_data(TOKEN)
    funds.get_margin_data(TOKEN)
    assert client.calls == 1
    order_api.cancel_order("1", TOKEN)
    client.body = _ledger(400)
    assert funds.get_margin_data(TOKEN)["availablecash"] == "400.00"
    assert client.calls == 2


def test_fetch_in_flight_during_an_order_call_is_not_cached(monkeypatch):
    client = _Client(_ledger(1000), on_get=lambda: order_api.cancel_order("1", TOKEN))
    _use(monkeypatch, client)
    _orders(monkeypatch)
    assert funds.get_margin_data(TOKEN)["availablecash"] == "1000.00"
    client.on_get = None
    funds.get_margin_data(TOKEN)
    assert client.calls == 2


def test_429_after_an_order_call_serves_last_real_data(monkeypatch):
    client = _Client(_ledger(1000))
    _use(monkeypatch, client)
    _orders(monkeypatch)
    funds.get_margin_data(TOKEN)
    order_api.cancel_order("1", TOKEN)

    def limited(*a, **k):
        return _Resp({}, status=429)

    client.get = limited
    assert funds.get_margin_data(TOKEN)["availablecash"] == "1000.00"


def test_failed_position_read_is_not_cached_as_fresh(monkeypatch):
    client = _Client(_ledger(50000))
    monkeypatch.setattr(funds, "get_httpx_client", lambda: client)
    monkeypatch.setattr(funds, "get_positions", lambda auth: {"s": "error", "message": "503"})
    assert funds.get_margin_data(TOKEN)["availablecash"] == "50000.00"

    monkeypatch.setattr(funds, "get_positions", lambda auth: {"s": "ok", "netPositions": []})
    monkeypatch.setattr(
        funds, "map_position_data", lambda raw: [{"realized_profit": -2000, "unrealized_profit": 0}]
    )
    assert funds.get_margin_data(TOKEN)["availablecash"] == "48000.00"
    assert client.calls == 2


class _OrderClient:
    def __init__(self, reply):
        self.reply = reply

    def _r(self, *a, **k):
        return _Resp(self.reply)

    post = patch = _r

    def request(self, *a, **k):
        return self._r()


def _orders(monkeypatch, reply=None):
    reply = reply or {"s": "ok", "id": "1"}
    monkeypatch.setattr(order_api, "get_httpx_client", lambda: _OrderClient(reply))
    monkeypatch.setattr(order_api, "transform_data", lambda d: {})
    monkeypatch.setattr(order_api, "transform_modify_order_data", lambda d: {})


ORDER_CALLS = {
    "place": lambda: order_api.place_order_api({"symbol": "X"}, TOKEN),
    "modify": lambda: order_api.modify_order({"orderid": "1"}, TOKEN),
    "cancel": lambda: order_api.cancel_order("1", TOKEN),
    "close_all": lambda: order_api.close_all_positions("key", TOKEN),
}


@pytest.mark.parametrize("name", sorted(ORDER_CALLS))
@pytest.mark.parametrize("reply", [{"s": "ok", "id": "1"}, {"s": "error", "message": "no"}])
def test_every_order_path_marks_funds_stale(monkeypatch, name, reply):
    client = _Client(_ledger(1000))
    _use(monkeypatch, client)
    funds.get_margin_data(TOKEN)
    _orders(monkeypatch, reply)
    ORDER_CALLS[name]()
    funds.get_margin_data(TOKEN)
    assert client.calls == 2


def test_order_call_raising_past_its_handlers_still_marks_funds_stale(monkeypatch):
    class _Abort(BaseException):
        pass

    def abort():
        raise _Abort

    client = _Client(_ledger(1000))
    _use(monkeypatch, client)
    funds.get_margin_data(TOKEN)
    monkeypatch.setattr(order_api, "get_httpx_client", abort)
    with pytest.raises(_Abort):
        order_api.place_order_api({"symbol": "X"}, TOKEN)
    funds.get_margin_data(TOKEN)
    assert client.calls == 2


def test_order_unaffected_when_invalidation_raises(monkeypatch):
    def boom(auth):
        raise RuntimeError("boom")

    monkeypatch.setattr(funds, "invalidate_funds_cache", boom, raising=False)
    _orders(monkeypatch, {"s": "ok", "id": "7"})
    _, body, orderid = order_api.place_order_api({"symbol": "X"}, TOKEN)
    assert orderid == "7" and body["s"] == "ok"
