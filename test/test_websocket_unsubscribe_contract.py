"""Regression contracts for mode-aware WebSocket unsubscription.

These tests are deliberately self-contained.  They exercise the production
proxy/client methods without opening a port, socket, thread or ZMQ context.
"""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from typing import Any

import pytest

from services.websocket_client import WebSocketClient
from websocket_proxy.server import WebSocketProxy


class _Adapter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, int]] = []

    def unsubscribe(self, symbol: str, exchange: str, mode: int) -> dict[str, str]:
        self.calls.append((symbol, exchange, mode))
        return {"status": "success"}


class _RejectingAdapter:
    def subscribe(
        self, symbol: str, exchange: str, mode: int, depth: int
    ) -> dict[str, str]:
        assert (symbol, exchange, mode, depth) == ("RELIANCE", "NSE", 3, 50)
        return {
            "status": "error",
            "message": "Depth level 50 is not supported by this broker",
        }


def _proxy_with_subscription(mode: int) -> tuple[WebSocketProxy, _Adapter, list[dict[str, Any]]]:
    proxy = WebSocketProxy.__new__(WebSocketProxy)
    adapter = _Adapter()
    subscription = {
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "mode": mode,
        "depth_level": 5,
        "broker": "sandbox",
    }
    proxy.user_mapping = {7: "alice"}
    proxy.broker_adapters = {"alice": adapter}
    proxy.user_broker_mapping = {"alice": "sandbox"}
    proxy.subscriptions = {7: {json.dumps(subscription)}}
    proxy.subscription_index = defaultdict(set)
    proxy.subscription_index[("RELIANCE", "NSE", mode)].add(7)
    responses: list[dict[str, Any]] = []

    async def capture(_client_id: int, response: dict[str, Any]) -> None:
        responses.append(response)

    proxy.send_message = capture
    return proxy, adapter, responses


@pytest.mark.parametrize(("request_mode", "expected_mode"), [("LTP", 1), ("Depth", 3)])
def test_array_unsubscribe_uses_the_top_level_mode_and_removes_the_exact_subscription(
    request_mode: str, expected_mode: int
) -> None:
    proxy, adapter, responses = _proxy_with_subscription(expected_mode)

    asyncio.run(
        proxy.unsubscribe_client(
            7,
            {
                "action": "unsubscribe",
                "mode": request_mode,
                "symbols": [{"symbol": "RELIANCE", "exchange": "NSE"}],
                "request_id": "req-7",
            },
        )
    )

    assert adapter.calls == [("RELIANCE", "NSE", expected_mode)]
    assert proxy.subscriptions[7] == set()
    assert ("RELIANCE", "NSE", expected_mode) not in proxy.subscription_index
    assert responses == [
        {
            "type": "unsubscribe",
            "status": "success",
            "message": "Unsubscription processing complete",
            "successful": [
                {
                    "symbol": "RELIANCE",
                    "exchange": "NSE",
                    "status": "success",
                    "broker": "sandbox",
                }
            ],
            "failed": [],
            "broker": "sandbox",
            "request_id": "req-7",
        }
    ]


def test_array_unsubscribe_prefers_each_symbol_mode_and_otherwise_defaults_to_quote() -> None:
    proxy, adapter, _responses = _proxy_with_subscription(1)

    asyncio.run(
        proxy.unsubscribe_client(
            7,
            {
                "action": "unsubscribe",
                "symbols": [
                    {"symbol": "RELIANCE", "exchange": "NSE", "mode": "LTP"}
                ],
            },
        )
    )
    assert adapter.calls == [("RELIANCE", "NSE", 1)]

    quote_proxy, quote_adapter, _responses = _proxy_with_subscription(2)
    asyncio.run(
        quote_proxy.unsubscribe_client(
            7,
            {
                "action": "unsubscribe",
                "symbols": [{"symbol": "RELIANCE", "exchange": "NSE"}],
            },
        )
    )
    assert quote_adapter.calls == [("RELIANCE", "NSE", 2)]


def test_internal_client_sends_explicit_item_modes_and_cleans_only_acknowledged_modes() -> None:
    client = WebSocketClient("test-key")
    client.connected = True
    client.authenticated = True
    client.loop = object()
    client.ws = object()
    client.active_subscriptions = {
        "NSE:RELIANCE": {"Depth", "LTP"},
        "NSE:INFY": {"LTP"},
    }
    sent: list[dict[str, Any]] = []

    async def acknowledge(message: dict[str, Any], _request_id: str, timeout: float) -> dict[str, Any]:
        assert timeout == 10
        sent.append(message)
        return {
            "type": "unsubscribe",
            "status": "partial",
            "message": "Unsubscription processing complete",
            "successful": [
                {"symbol": "RELIANCE", "exchange": "NSE", "status": "success"}
            ],
            "failed": [
                {"symbol": "INFY", "exchange": "NSE", "status": "error"}
            ],
        }

    client._send_and_await_ack = acknowledge
    client._run_on_loop = lambda coroutine, timeout: asyncio.run(coroutine)

    result = client.unsubscribe(
        [
            {"symbol": "RELIANCE", "exchange": "NSE", "mode": "Depth"},
            {"symbol": "INFY", "exchange": "NSE"},
        ],
        mode="LTP",
    )

    assert result["status"] == "partial"
    assert result["successful"] == [
        {"symbol": "RELIANCE", "exchange": "NSE", "status": "success"}
    ]
    assert result["failed"] == [
        {"symbol": "INFY", "exchange": "NSE", "status": "error"}
    ]
    assert len(sent) == 1
    assert sent[0]["action"] == "unsubscribe"
    assert sent[0]["mode"] == "LTP"
    assert sent[0]["symbols"] == [
        {"symbol": "RELIANCE", "exchange": "NSE", "mode": "Depth"},
        {"symbol": "INFY", "exchange": "NSE", "mode": "LTP"},
    ]
    assert sent[0]["request_id"]
    assert client.active_subscriptions == {
        "NSE:RELIANCE": {"LTP"},
        "NSE:INFY": {"LTP"},
    }


def test_subscribe_rejection_is_a_partial_ack_with_a_per_symbol_error() -> None:
    proxy = WebSocketProxy.__new__(WebSocketProxy)
    proxy.user_mapping = {7: "alice"}
    proxy.broker_adapters = {"alice": _RejectingAdapter()}
    proxy.user_broker_mapping = {"alice": "angel"}
    proxy.subscriptions = {7: set()}
    proxy.subscription_index = defaultdict(set)
    responses: list[dict[str, Any]] = []

    async def capture(_client_id: int, response: dict[str, Any]) -> None:
        responses.append(response)

    proxy.send_message = capture
    asyncio.run(
        proxy.subscribe_client(
            7,
            {
                "action": "subscribe",
                "mode": "Depth",
                "depth": 50,
                "symbols": [{"symbol": "RELIANCE", "exchange": "NSE"}],
            },
        )
    )

    assert responses == [
        {
            "type": "subscribe",
            "status": "partial",
            "subscriptions": [
                {
                    "symbol": "RELIANCE",
                    "exchange": "NSE",
                    "status": "error",
                    "message": "Depth level 50 is not supported by this broker",
                    "broker": "angel",
                }
            ],
            "message": "Subscription processing complete",
            "broker": "angel",
        }
    ]
