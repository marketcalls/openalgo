"""Pocketful market price protection (#2391): the place-order path must hand
its auth token to transform_data, or the MARKET-to-LIMIT protection never
runs and every market order goes out unprotected.
"""

import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from broker.pocketful.api import order_api  # noqa: E402
from broker.pocketful.mapping import transform_data as transform_module  # noqa: E402


class TestPlaceOrderPassesAuthToken:
    """Regression: place_order_api dropped its auth token before transform_data."""

    def test_auth_token_reaches_transform_data(self, monkeypatch):
        seen = {}

        def fake_transform(data, client_id=None, auth_token=None):
            seen["auth_token"] = auth_token
            return {"order_type": "LIMIT", "price": 1.0}

        monkeypatch.setattr(order_api, "transform_data", fake_transform)
        monkeypatch.setattr(
            order_api,
            "get_api_response",
            lambda *a, **k: {"status": "success", "data": {"oms_order_id": "1", "client_id": "c1"}},
        )
        # The session and Auth query feed the client_id lookup; keep them inert.
        monkeypatch.setattr(order_api, "session", {})
        monkeypatch.setattr(
            order_api,
            "Auth",
            SimpleNamespace(
                query=SimpleNamespace(
                    filter_by=lambda **k: SimpleNamespace(first=lambda: None)
                )
            ),
        )

        order_api.place_order_api(
            {
                "symbol": "SBIN",
                "exchange": "NSE",
                "action": "BUY",
                "pricetype": "MARKET",
                "product": "MIS",
                "quantity": "1",
            },
            "the-day-token",
        )

        assert seen["auth_token"] == "the-day-token"


class TestTransformDataProtection:
    """With the token in hand, a MARKET order becomes LIMIT at the slab price."""

    @pytest.fixture(autouse=True)
    def _wiring(self, monkeypatch):
        monkeypatch.setattr(transform_module, "get_br_symbol", lambda s, e: "SBIN-EQ")
        monkeypatch.setattr(transform_module, "get_token", lambda s, e: "12345")
        monkeypatch.setattr(
            transform_module,
            "get_symbol_info",
            lambda s, e: SimpleNamespace(tick_size=0.05),
        )

        class FakeBrokerData:
            def __init__(self, auth_token):
                self.auth_token = auth_token

            def get_quotes(self, symbol, exchange):
                return {"ltp": 100.0, "bid": 99.95, "ask": 100.05}

        monkeypatch.setattr(transform_module, "BrokerData", FakeBrokerData)

    def _order(self):
        return {
            "symbol": "SBIN",
            "exchange": "NSE",
            "action": "BUY",
            "pricetype": "MARKET",
            "product": "MIS",
            "quantity": "1",
            "price": "0",
        }

    def test_market_becomes_limit_at_protected_price(self):
        out = transform_module.transform_data(self._order(), client_id="c1", auth_token="tok")
        assert out["order_type"] == "LIMIT"
        # EQ at LTP 100 is in the 1% slab: a BUY is protected at 101.00.
        assert out["price"] == 101.0

    def test_without_token_the_order_stays_market(self):
        out = transform_module.transform_data(self._order(), client_id="c1")
        assert out["order_type"] == "MARKET"
