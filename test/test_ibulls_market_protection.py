"""Ibulls MARKET orders: feed token of the logged-in user, slab off the LTP, tick-aligned (issue #2392).

The protection used to fall back to a hard-coded username for every order
without a browser session (API, strategy, webhook), priced a BUY off the bid
and a SELL off the ask, and rounded to 2 decimals instead of the tick.
"""

from types import SimpleNamespace
from unittest import mock

import pytest
from flask import Flask

from broker.ibulls.mapping import transform_data as td

ORDER = {
    "symbol": "SBIN",
    "exchange": "NSE",
    "quantity": "1",
    "pricetype": "MARKET",
    "product": "MIS",
    "price": "0",
}


@pytest.fixture
def broker(monkeypatch):
    quotes = mock.Mock()
    quotes.return_value.get_quotes.return_value = {"ltp": 812.4, "bid": 812.3, "ask": 812.5}
    feed_token = mock.Mock(side_effect=lambda name: "feed" if name else None)
    stored = mock.Mock()
    stored.query.filter_by.return_value.first.return_value = SimpleNamespace(name="trader")
    monkeypatch.setattr(td, "BrokerData", quotes)
    monkeypatch.setattr(td, "get_feed_token", feed_token)
    monkeypatch.setattr(td, "Auth", stored)
    monkeypatch.setattr(td, "get_br_symbol", lambda s, e: "SBIN-EQ")
    monkeypatch.setattr(td, "get_symbol_info", lambda s, e: SimpleNamespace(tick_size=0.05))
    return SimpleNamespace(quotes=quotes, feed_token=feed_token, stored=stored)


def test_order_without_a_browser_session_uses_the_stored_ibulls_user(broker):
    td.transform_data({**ORDER, "action": "BUY"}, "3045")

    broker.feed_token.assert_called_once_with("trader")
    broker.stored.query.filter_by.assert_called_once_with(broker="ibulls", is_revoked=False)


def test_browser_order_uses_the_session_user(broker):
    app = Flask(__name__)
    app.secret_key = "test"
    with app.test_request_context():
        from flask import session

        session["user"] = "browser-user"
        td.transform_data({**ORDER, "action": "BUY"}, "3045")

    broker.feed_token.assert_called_once_with("browser-user")
    broker.stored.query.filter_by.assert_not_called()


def test_setup_only_username_key_is_not_the_logged_in_user(broker):
    # session["username"] is set only on the first-run setup page; the login
    # stores the user under session["user"], so it must not be read instead.
    app = Flask(__name__)
    app.secret_key = "test"
    with app.test_request_context():
        from flask import session

        session["username"] = "setup-page"
        td.transform_data({**ORDER, "action": "BUY"}, "3045")

    broker.feed_token.assert_called_once_with("trader")


def test_no_fixed_username_is_ever_used(broker):
    broker.stored.query.filter_by.return_value.first.return_value = None
    out = td.transform_data({**ORDER, "action": "BUY"}, "3045")

    broker.feed_token.assert_called_once_with(None)
    assert out["orderType"] == "MARKET"


@pytest.mark.parametrize(
    "action, expected",
    # LTP 812.4 on NSE equity: 0.5% slab, 0.05 tick.
    [("BUY", "816.45"), ("SELL", "808.35")],
)
def test_limit_is_the_slab_off_the_ltp_on_the_tick(broker, action, expected):
    out = td.transform_data({**ORDER, "action": action}, "3045")

    assert out["orderType"] == "LIMIT"
    assert out["limitPrice"] == expected
    assert round(float(out["limitPrice"]) / 0.05, 6).is_integer()


def test_buy_limit_is_above_the_ask_and_sell_limit_below_the_bid(broker):
    buy = td.transform_data({**ORDER, "action": "BUY"}, "3045")
    sell = td.transform_data({**ORDER, "action": "SELL"}, "3045")

    assert float(buy["limitPrice"]) > 812.5
    assert float(sell["limitPrice"]) < 812.3


def test_no_ltp_sends_the_market_order_unchanged(broker):
    broker.quotes.return_value.get_quotes.return_value = {"ltp": 0}
    out = td.transform_data({**ORDER, "action": "BUY"}, "3045")

    assert out["orderType"] == "MARKET"
    assert out["limitPrice"] == "0"
