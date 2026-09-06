"""Integration contract: Depth topics delivered to Quote subscribers.

The proxy deliberately downgrades higher-mode ticks to lower-mode
subscribers (a Depth tick reaches a Quote subscriber relabeled as mode 2),
so the guaranteed Quote field contract must hold on that delivery path too —
not only on native QUOTE topics. These tests exercise the production
_handle_market_data path without opening a port, socket, thread or ZMQ
context (same approach as test_websocket_unsubscribe_contract.py).
"""

import asyncio
import json
from collections import defaultdict
from typing import Any

import pytest

from websocket_proxy import server as proxy_server
from websocket_proxy.server import WebSocketProxy
from websocket_proxy.tick_contract import QUOTE_REQUIRED_FIELDS


class _StubMDS:
    """Stands in for MarketDataService so no app/database machinery starts."""

    def __init__(self) -> None:
        self.seen: list[dict[str, Any]] = []

    def process_market_data(self, payload: dict[str, Any]) -> None:
        self.seen.append(payload)


def _make_proxy(subscribed_mode: int) -> tuple[WebSocketProxy, list[dict[str, Any]]]:
    proxy = WebSocketProxy.__new__(WebSocketProxy)
    proxy.clients = {101: object()}
    proxy.user_mapping = {101: "user1"}
    proxy.user_broker_mapping = {"user1": "zerodha"}
    proxy.subscription_index = defaultdict(set)
    proxy.subscription_index[("SBIN", "NSE", subscribed_mode)] = {101}
    proxy.last_message_time = {}
    proxy.last_tick_time = {}
    proxy._messages_processed = 0
    sent: list[dict[str, Any]] = []

    async def fake_send(client_id, message):
        sent.append(message)

    proxy.send_message = fake_send
    return proxy, sent


def _deliver(proxy, topic: str, payload: dict, monkeypatch) -> _StubMDS:
    stub = _StubMDS()
    monkeypatch.setattr(proxy_server, "get_market_data_service", lambda: stub)
    asyncio.run(proxy._handle_market_data(topic, json.dumps(payload)))
    return stub


class TestDepthDeliveredToQuoteSubscriber:
    def test_depth_tick_reaches_quote_subscriber_with_contract_fields(self, monkeypatch):
        # Zerodha-style depth payload: ltp present, OHLC/volume/timestamp absent.
        depth_tick = {
            "symbol": "SBIN",
            "exchange": "NSE",
            "ltp": 625.5,
            "last_qty": 50,
            "bid_price": 625.4,
            "ask_price": 625.6,
            "depth": {"buy": [{"price": 625.4, "quantity": 100}], "sell": []},
        }
        proxy, sent = _make_proxy(subscribed_mode=2)

        _deliver(proxy, "NSE_SBIN_DEPTH", depth_tick, monkeypatch)

        assert len(sent) == 1
        message = sent[0]
        # Relabeled to the subscriber's mode: clients see a mode 2 message.
        assert message["mode"] == 2
        assert message["symbol"] == "SBIN"
        assert message["exchange"] == "NSE"
        data = message["data"]
        for field in QUOTE_REQUIRED_FIELDS:
            assert field in data, f"contract field {field} missing on depth->quote path"
        # Absent fields are null, never a fabricated 0.
        for field in ("open", "high", "low", "close", "volume", "timestamp"):
            assert data[field] is None
        # Broker-supplied values are preserved verbatim, depth fields intact.
        assert data["ltp"] == 625.5
        assert data["depth"] == depth_tick["depth"]

    def test_market_data_service_receives_normalized_depth_tick(self, monkeypatch):
        depth_tick = {"symbol": "SBIN", "exchange": "NSE", "ltp": 625.5}
        proxy, _ = _make_proxy(subscribed_mode=2)

        stub = _deliver(proxy, "NSE_SBIN_DEPTH", depth_tick, monkeypatch)

        # Backend consumers sit behind the same normalizer, so they observe
        # the contract too — with the original topic mode preserved.
        assert len(stub.seen) == 1
        assert stub.seen[0]["mode"] == 3
        assert stub.seen[0]["data"]["open"] is None
        assert stub.seen[0]["data"]["ltp"] == 625.5


class TestNativeQuoteTopicUnchanged:
    def test_quote_tick_still_normalized_for_quote_subscriber(self, monkeypatch):
        quote_tick = {"symbol": "SBIN", "exchange": "NSE", "ltp": 625.5, "volume": 100}
        proxy, sent = _make_proxy(subscribed_mode=2)

        _deliver(proxy, "NSE_SBIN_QUOTE", quote_tick, monkeypatch)

        assert len(sent) == 1
        assert sent[0]["mode"] == 2
        data = sent[0]["data"]
        for field in ("open", "high", "low", "close", "timestamp"):
            assert data[field] is None
        assert data["volume"] == 100  # supplied zeros/values never overwritten


class TestLtpTopicUnaffected:
    def test_ltp_tick_forwarded_without_quote_fields(self, monkeypatch):
        ltp_tick = {"symbol": "SBIN", "exchange": "NSE", "ltp": 625.5}
        proxy, sent = _make_proxy(subscribed_mode=1)

        _deliver(proxy, "NSE_SBIN_LTP", ltp_tick, monkeypatch)

        assert len(sent) == 1
        assert sent[0]["mode"] == 1
        # The contract is a Quote-mode guarantee; LTP delivery stays lean.
        assert "open" not in sent[0]["data"]
        assert sent[0]["data"]["ltp"] == 625.5
