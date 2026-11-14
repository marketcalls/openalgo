"""Broker token changes must make already connected clients reconnect."""

import asyncio
import json
import threading
from unittest.mock import AsyncMock, Mock, patch

from services.websocket_client import WebSocketClient
from websocket_proxy.server import WebSocketProxy


def test_cache_invalidation_closes_only_affected_clients():
    async def run():
        proxy = WebSocketProxy.__new__(WebSocketProxy)
        affected = AsyncMock()
        other = AsyncMock()
        adapter = Mock()
        proxy.clients = {1: affected, 2: other}
        proxy.user_mapping = {1: "alice", 2: "bob"}
        proxy._invalidated_clients = set()
        proxy.broker_adapters = {"alice": adapter}

        with patch("websocket_proxy.broker_factory.cleanup_pools_for_user"):
            proxy._handle_cache_invalidation(
                "CACHE_INVALIDATE_ALL_alice",
                json.dumps({"user_id": "alice", "cache_type": "ALL"}),
            )
            await asyncio.sleep(0)

        adapter.disconnect.assert_called_once_with()
        affected.close.assert_awaited_once()
        other.close.assert_not_awaited()
        assert proxy._invalidated_clients == {1}

    asyncio.run(run())


def test_invalidated_client_does_not_disconnect_replacement_adapter():
    async def run():
        proxy = WebSocketProxy.__new__(WebSocketProxy)
        replacement = Mock()
        proxy.clients = {1: AsyncMock()}
        proxy.user_mapping = {1: "alice"}
        proxy.broker_adapters = {"alice": replacement}
        proxy._invalidated_clients = {1}
        proxy.order_subscribers = {}
        proxy.subscriptions = {}
        proxy.subscription_index = {}

        await proxy.cleanup_client(1)

        replacement.disconnect.assert_not_called()
        assert proxy.broker_adapters["alice"] is replacement
        assert proxy._invalidated_clients == set()

    asyncio.run(run())


def test_internal_client_restores_subscriptions_after_reauthentication():
    async def run():
        client = WebSocketClient.__new__(WebSocketClient)
        client.ws = AsyncMock()
        client.lock = threading.Lock()
        client.authenticated = False
        client.active_subscriptions = {
            "NSE:RELIANCE": {"LTP", "Quote"},
            "NSE:TCS": {"Quote"},
        }
        client._dispatch = Mock()

        await client._handle_message(json.dumps({"type": "auth", "status": "success"}))

        assert client.authenticated
        requests = [json.loads(call.args[0]) for call in client.ws.send.await_args_list]
        assert requests == [
            {
                "action": "subscribe",
                "symbols": [{"symbol": "RELIANCE", "exchange": "NSE"}],
                "mode": "LTP",
            },
            {
                "action": "subscribe",
                "symbols": [
                    {"symbol": "RELIANCE", "exchange": "NSE"},
                    {"symbol": "TCS", "exchange": "NSE"},
                ],
                "mode": "Quote",
            },
        ]

    asyncio.run(run())
