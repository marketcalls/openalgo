"""Ibulls sends a MARKET order as a native MARKET order (issue #2392).

The plugin used to try to turn MARKET into a LIMIT priced off a quote. To
fetch that quote it looked up the feed token of a fixed username, because it
read the signed-in user from a session key that a signed-in session does not
carry. On every install whose user had another name, no token was found and
a native MARKET order went out, so that is what Ibulls traders have been
sending all along; the conversion only ever ran for the one account the name
belonged to, priced a BUY off the bid and a SELL off the ask, and ignored
the tick size.

Ibulls now sends MARKET natively on every path, like its XTS siblings
(fivepaisaxts, jainamxts, compositedge, rmoney, wisdom) and like close-all
already did, and an order never looks up anybody's token or fetches a quote.
"""

import pytest
from flask import Flask, session

import broker.ibulls.mapping.transform_data as td
from broker.ibulls.api.data import BrokerData

ORDER = {
    "symbol": "SBIN",
    "exchange": "NSE",
    "action": "BUY",
    "product": "MIS",
    "quantity": "1",
    "price": "0",
    "trigger_price": "0",
}


@pytest.fixture
def lookups(monkeypatch):
    """Record every token lookup and quote fetch an order makes. A token is
    always found, as on the install whose user the old fallback named."""
    seen = []

    def token(name):
        seen.append(("token", name))
        return "a-stored-token"

    def quote(self, symbol, exchange):
        seen.append(("quote", symbol))
        return {"bid": 800.0, "ask": 801.0, "ltp": 800.5}

    monkeypatch.setattr(td, "get_feed_token", token, raising=False)
    monkeypatch.setattr(td, "get_auth_token", token, raising=False)
    monkeypatch.setattr(BrokerData, "get_quotes", quote)
    monkeypatch.setattr(td, "get_br_symbol", lambda symbol, exchange: symbol)
    return seen


def _place(order, sess):
    if sess is None:  # a strategy or scheduler thread: no request at all
        return td.transform_data(dict(order), "3045")
    app = Flask(__name__)
    app.secret_key = "test"
    with app.test_request_context("/"):
        session.update(sess)
        return td.transform_data(dict(order), "3045")


@pytest.mark.parametrize(
    "sess",
    [{"user": "alice"}, {}, None],
    ids=["signed-in browser", "API order without a cookie", "outside a request"],
)
@pytest.mark.parametrize("action", ["BUY", "SELL"])
def test_a_market_order_goes_out_as_native_market(lookups, sess, action):
    sent = _place({**ORDER, "action": action, "pricetype": "MARKET"}, sess)

    assert sent["orderType"] == "MARKET"
    assert sent["orderSide"] == action
    assert sent["limitPrice"] == "0"
    assert lookups == []


@pytest.mark.parametrize(
    ("pricetype", "price", "trigger", "order_type"),
    [
        ("LIMIT", "801.5", "0", "LIMIT"),
        ("SL", "801.5", "800", "STOPLIMIT"),
        ("SL-M", "0", "800", "STOPMARKET"),
    ],
)
def test_other_order_types_keep_their_prices(lookups, pricetype, price, trigger, order_type):
    sent = _place(
        {**ORDER, "pricetype": pricetype, "price": price, "trigger_price": trigger},
        {"user": "alice"},
    )

    assert sent["orderType"] == order_type
    assert sent["limitPrice"] == price
    assert sent["stopPrice"] == trigger
    assert lookups == []
