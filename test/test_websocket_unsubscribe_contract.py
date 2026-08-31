"""Regression contracts for mode-aware WebSocket unsubscription.

These tests are deliberately self-contained.  They exercise the production
proxy/client methods without opening a port, socket, thread or ZMQ context.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from collections import defaultdict
from typing import Any

import pytest

from services.websocket_client import WebSocketClient
from websocket_proxy.broker_factory import _PooledAdapterWrapper
from websocket_proxy.connection_manager import ConnectionPool
from websocket_proxy.server import WebSocketProxy


class _Adapter:
    def __init__(
        self,
        outcomes: list[Any] | None = None,
        *,
        unsubscribe_all_outcomes: list[Any] | None = None,
        disconnect_outcomes: list[Any] | None = None,
    ) -> None:
        self.calls: list[tuple[str, str, int]] = []
        self.outcomes = list(outcomes or [{"status": "success"}])
        self.unsubscribe_all_calls = 0
        self.unsubscribe_all_outcomes = list(
            unsubscribe_all_outcomes or [{"status": "success"}]
        )
        self.disconnect_calls = 0
        self.disconnect_outcomes = list(disconnect_outcomes or [None])

    def unsubscribe(self, symbol: str, exchange: str, mode: int) -> Any:
        self.calls.append((symbol, exchange, mode))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def disconnect(self) -> None:
        self.disconnect_calls += 1
        outcome = self.disconnect_outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome

    def unsubscribe_all(self) -> Any:
        self.unsubscribe_all_calls += 1
        outcome = self.unsubscribe_all_outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class _RejectingAdapter:
    def subscribe(
        self, symbol: str, exchange: str, mode: int, depth: int
    ) -> dict[str, str]:
        assert (symbol, exchange, mode, depth) == ("RELIANCE", "NSE", 3, 50)
        return {
            "status": "error",
            "message": "Depth level 50 is not supported by this broker",
        }


def _proxy_with_subscription(
    mode: int,
    *,
    adapter: _Adapter | None = None,
    client_ids: tuple[int, ...] = (7,),
) -> tuple[WebSocketProxy, _Adapter, list[dict[str, Any]]]:
    proxy = WebSocketProxy.__new__(WebSocketProxy)
    adapter = adapter or _Adapter()
    subscription = {
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "mode": mode,
        "depth_level": 5,
        "broker": "sandbox",
    }
    proxy.user_mapping = dict.fromkeys(client_ids, "alice")
    proxy.broker_adapters = {"alice": adapter}
    proxy.user_broker_mapping = {"alice": "sandbox"}
    proxy.clients = {client_id: object() for client_id in client_ids}
    proxy.order_subscribers = defaultdict(set)
    proxy.subscriptions = {
        client_id: {json.dumps(subscription)} for client_id in client_ids
    }
    proxy.subscription_index = defaultdict(set)
    proxy.subscription_index[("RELIANCE", "NSE", mode)].update(client_ids)
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
                    "mode": request_mode,
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


def test_last_subscriber_failure_preserves_both_registries_and_retry_success_removes_them() -> None:
    adapter = _Adapter(
        [
            {"status": "error", "message": "broker refused"},
            {"status": "success"},
        ]
    )
    proxy, _adapter, responses = _proxy_with_subscription(1, adapter=adapter)
    request = {
        "action": "unsubscribe",
        "mode": "LTP",
        "symbols": [{"symbol": "RELIANCE", "exchange": "NSE"}],
    }

    asyncio.run(proxy.unsubscribe_client(7, request))

    assert proxy.subscription_index[("RELIANCE", "NSE", 1)] == {7}
    assert len(proxy.subscriptions[7]) == 1
    assert responses[-1]["status"] == "error"
    assert responses[-1]["failed"][0]["mode"] == "LTP"

    asyncio.run(proxy.unsubscribe_client(7, request))

    assert adapter.calls == [
        ("RELIANCE", "NSE", 1),
        ("RELIANCE", "NSE", 1),
    ]
    assert ("RELIANCE", "NSE", 1) not in proxy.subscription_index
    assert proxy.subscriptions[7] == set()
    assert responses[-1]["successful"][0]["mode"] == "LTP"


def test_multi_client_unsubscribe_removes_only_the_caller_until_the_last_ack() -> None:
    proxy, adapter, responses = _proxy_with_subscription(3, client_ids=(7, 8))
    request = {
        "action": "unsubscribe",
        "mode": "Depth",
        "symbols": [{"symbol": "RELIANCE", "exchange": "NSE"}],
    }

    asyncio.run(proxy.unsubscribe_client(7, request))

    assert adapter.calls == []
    assert proxy.subscription_index[("RELIANCE", "NSE", 3)] == {8}
    assert proxy.subscriptions[7] == set()
    assert len(proxy.subscriptions[8]) == 1
    assert responses[-1]["successful"][0]["mode"] == "Depth"

    asyncio.run(proxy.unsubscribe_client(8, request))

    assert adapter.calls == [("RELIANCE", "NSE", 3)]
    assert ("RELIANCE", "NSE", 3) not in proxy.subscription_index
    assert proxy.subscriptions[8] == set()


@pytest.mark.parametrize(
    "outcome",
    [None, {}, {"status": "wat"}, RuntimeError("adapter exploded")],
)
def test_invalid_or_exceptional_broker_response_preserves_exact_ownership(
    outcome: Any,
) -> None:
    proxy, adapter, responses = _proxy_with_subscription(
        1, adapter=_Adapter([outcome])
    )

    asyncio.run(
        proxy.unsubscribe_client(
            7,
            {
                "action": "unsubscribe",
                "mode": "LTP",
                "symbols": [{"symbol": "RELIANCE", "exchange": "NSE"}],
            },
        )
    )

    assert adapter.calls == [("RELIANCE", "NSE", 1)]
    assert proxy.subscription_index[("RELIANCE", "NSE", 1)] == {7}
    assert len(proxy.subscriptions[7]) == 1
    assert responses[-1]["status"] == "error"
    assert responses[-1]["failed"][0]["mode"] == "LTP"


def test_unsubscribe_all_failure_preserves_ownership_until_retry_succeeds() -> None:
    adapter = _Adapter(
        [{"status": "error", "message": "still live"}, {"status": "success"}]
    )
    proxy, _adapter, responses = _proxy_with_subscription(1, adapter=adapter)
    request = {"action": "unsubscribe_all", "request_id": "all-7"}

    asyncio.run(proxy.unsubscribe_client(7, request))

    assert proxy.subscription_index[("RELIANCE", "NSE", 1)] == {7}
    assert len(proxy.subscriptions[7]) == 1
    assert responses[-1]["status"] == "error"
    assert responses[-1]["failed"][0]["mode"] == "LTP"

    asyncio.run(proxy.unsubscribe_client(7, request))

    assert ("RELIANCE", "NSE", 1) not in proxy.subscription_index
    assert proxy.subscriptions[7] == set()
    assert responses[-1]["status"] == "success"
    assert responses[-1]["successful"][0]["mode"] == "LTP"


def test_unsubscribe_all_multi_client_release_keeps_broker_until_last_owner() -> None:
    proxy, adapter, responses = _proxy_with_subscription(2, client_ids=(7, 8))
    request = {"action": "unsubscribe_all"}

    asyncio.run(proxy.unsubscribe_client(7, request))

    assert adapter.calls == []
    assert proxy.subscription_index[("RELIANCE", "NSE", 2)] == {8}
    assert proxy.subscriptions[7] == set()
    assert responses[-1]["successful"][0]["mode"] == "Quote"

    asyncio.run(proxy.unsubscribe_client(8, request))

    assert adapter.calls == [("RELIANCE", "NSE", 2)]
    assert ("RELIANCE", "NSE", 2) not in proxy.subscription_index
    assert proxy.subscriptions[8] == set()


@pytest.mark.parametrize("outcome", [None, RuntimeError("all exploded")])
def test_unsubscribe_all_invalid_or_exceptional_response_preserves_ownership(
    outcome: Any,
) -> None:
    proxy, adapter, responses = _proxy_with_subscription(
        3, adapter=_Adapter([outcome])
    )

    asyncio.run(proxy.unsubscribe_client(7, {"action": "unsubscribe_all"}))

    assert adapter.calls == [("RELIANCE", "NSE", 3)]
    assert proxy.subscription_index[("RELIANCE", "NSE", 3)] == {7}
    assert len(proxy.subscriptions[7]) == 1
    assert responses[-1]["status"] == "error"
    assert responses[-1]["failed"][0]["mode"] == "Depth"


@pytest.mark.parametrize(
    "outcome",
    [{"status": "error", "message": "still live"}, None, RuntimeError("boom")],
)
def test_single_disconnect_cleanup_falls_back_to_adapter_teardown_after_exact_release_failure(
    outcome: Any,
) -> None:
    adapter = _Adapter([outcome])
    proxy, _adapter, _responses = _proxy_with_subscription(1, adapter=adapter)

    asyncio.run(proxy.cleanup_client(7))

    assert ("RELIANCE", "NSE", 1) not in proxy.subscription_index
    assert 7 not in proxy.subscriptions
    assert 7 not in proxy.user_mapping
    assert "alice" not in proxy.broker_adapters
    assert adapter.disconnect_calls == 1


def test_explicit_refusal_remains_owned_until_the_real_disconnect_tears_it_down_once() -> None:
    adapter = _Adapter(
        [
            {"status": "error", "message": "explicit refusal"},
            {"status": "error", "message": "disconnect refusal"},
        ]
    )
    proxy, _adapter, responses = _proxy_with_subscription(1, adapter=adapter)
    request = {
        "action": "unsubscribe",
        "mode": "LTP",
        "symbols": [{"symbol": "RELIANCE", "exchange": "NSE"}],
    }

    asyncio.run(proxy.unsubscribe_client(7, request))

    assert responses[-1]["status"] == "error"
    assert proxy.subscription_index[("RELIANCE", "NSE", 1)] == {7}

    asyncio.run(proxy.cleanup_client(7))

    assert adapter.calls == [
        ("RELIANCE", "NSE", 1),
        ("RELIANCE", "NSE", 1),
    ]
    assert adapter.disconnect_calls == 1
    assert ("RELIANCE", "NSE", 1) not in proxy.subscription_index
    assert 7 not in proxy.subscriptions
    assert 7 not in proxy.user_mapping
    assert "alice" not in proxy.broker_adapters


def test_disconnect_exception_still_evicts_dead_adapter_and_registry_owner() -> None:
    adapter = _Adapter(
        [{"status": "error", "message": "exact refusal"}],
        disconnect_outcomes=[RuntimeError("disconnect exploded")],
    )
    proxy, _adapter, _responses = _proxy_with_subscription(1, adapter=adapter)

    asyncio.run(proxy.cleanup_client(7))

    assert adapter.disconnect_calls == 1
    assert "alice" not in proxy.broker_adapters
    assert "alice" not in proxy.user_broker_mapping
    assert ("RELIANCE", "NSE", 1) not in proxy.subscription_index
    assert 7 not in proxy.subscriptions
    assert 7 not in proxy.user_mapping


def test_failed_release_with_another_live_client_is_reclaimed_at_real_last_disconnect() -> None:
    adapter = _Adapter([{"status": "error", "message": "exact refusal"}])
    proxy, _adapter, _responses = _proxy_with_subscription(
        1, adapter=adapter, client_ids=(7, 8)
    )
    proxy.subscription_index[("RELIANCE", "NSE", 1)] = {7}
    proxy.subscriptions[8] = set()

    asyncio.run(proxy.cleanup_client(7))

    assert adapter.disconnect_calls == 0
    assert ("RELIANCE", "NSE", 1) not in proxy.subscription_index
    assert 7 not in proxy.subscriptions
    assert 7 not in proxy.user_mapping
    assert proxy.broker_adapters["alice"] is adapter

    asyncio.run(proxy.cleanup_client(8))

    assert adapter.disconnect_calls == 1
    assert "alice" not in proxy.broker_adapters
    assert 8 not in proxy.subscriptions
    assert 8 not in proxy.user_mapping


@pytest.mark.parametrize("broker_name", ["flattrade", "shoonya"])
def test_special_broker_disconnect_uses_successful_unsubscribe_all_and_keeps_pool(
    broker_name: str,
) -> None:
    adapter = _Adapter(
        [{"status": "error", "message": "exact refusal"}],
        unsubscribe_all_outcomes=[{"status": "success"}],
    )
    proxy, _adapter, _responses = _proxy_with_subscription(1, adapter=adapter)
    proxy.user_broker_mapping["alice"] = broker_name

    asyncio.run(proxy.cleanup_client(7))

    assert adapter.unsubscribe_all_calls == 1
    assert adapter.disconnect_calls == 0
    assert proxy.broker_adapters["alice"] is adapter
    assert ("RELIANCE", "NSE", 1) not in proxy.subscription_index
    assert 7 not in proxy.subscriptions
    assert 7 not in proxy.user_mapping


@pytest.mark.parametrize("broker_name", ["flattrade", "shoonya"])
@pytest.mark.parametrize(
    "unsubscribe_all_outcome",
    [{"status": "error", "message": "batch refusal"}, None, RuntimeError("batch exploded")],
)
def test_special_broker_unsubscribe_all_failure_falls_back_to_disconnect(
    broker_name: str,
    unsubscribe_all_outcome: Any,
) -> None:
    adapter = _Adapter(
        [{"status": "error", "message": "exact refusal"}],
        unsubscribe_all_outcomes=[unsubscribe_all_outcome],
    )
    proxy, _adapter, _responses = _proxy_with_subscription(1, adapter=adapter)
    proxy.user_broker_mapping["alice"] = broker_name

    asyncio.run(proxy.cleanup_client(7))

    assert adapter.unsubscribe_all_calls == 1
    assert adapter.disconnect_calls == 1
    assert "alice" not in proxy.broker_adapters
    assert ("RELIANCE", "NSE", 1) not in proxy.subscription_index
    assert 7 not in proxy.subscriptions
    assert 7 not in proxy.user_mapping


def test_special_broker_fallback_disconnect_exception_still_evicts_dead_adapter() -> None:
    adapter = _Adapter(
        [{"status": "error", "message": "exact refusal"}],
        unsubscribe_all_outcomes=[{"status": "error", "message": "batch refusal"}],
        disconnect_outcomes=[RuntimeError("disconnect exploded")],
    )
    proxy, _adapter, _responses = _proxy_with_subscription(1, adapter=adapter)
    proxy.user_broker_mapping["alice"] = "shoonya"

    asyncio.run(proxy.cleanup_client(7))

    assert adapter.unsubscribe_all_calls == 1
    assert adapter.disconnect_calls == 1
    assert "alice" not in proxy.broker_adapters
    assert "alice" not in proxy.user_broker_mapping
    assert ("RELIANCE", "NSE", 1) not in proxy.subscription_index
    assert 7 not in proxy.subscriptions
    assert 7 not in proxy.user_mapping


def _connection_pool_with_adapter(adapter: _Adapter) -> ConnectionPool:
    pool = ConnectionPool.__new__(ConnectionPool)
    pool.lock = threading.RLock()
    pool.logger = logging.getLogger("test.websocket.pool")
    pool.adapters = [adapter]
    pool.adapter_symbol_counts = [1]
    pool.max_symbols = 1000
    pool.subscription_map = {("RELIANCE", "NSE", 1): 0}
    pool.subscription_depths = {("RELIANCE", "NSE", 1): 5}
    return pool


def test_connection_pool_unsubscribe_all_propagates_failure_and_retains_tracking() -> None:
    adapter = _Adapter(
        unsubscribe_all_outcomes=[{"status": "error", "message": "still live"}]
    )
    pool = _connection_pool_with_adapter(adapter)

    result = pool.unsubscribe_all()

    assert result["status"] == "error"
    assert pool.subscription_map == {("RELIANCE", "NSE", 1): 0}
    assert pool.subscription_depths == {("RELIANCE", "NSE", 1): 5}
    assert pool.adapter_symbol_counts == [1]


def test_connection_pool_and_wrapper_propagate_success_before_clearing_tracking() -> None:
    adapter = _Adapter(unsubscribe_all_outcomes=[{"status": "success"}])
    pool = _connection_pool_with_adapter(adapter)
    wrapper = _PooledAdapterWrapper.__new__(_PooledAdapterWrapper)
    wrapper._pool = pool

    result = wrapper.unsubscribe_all()

    assert result["status"] == "success"
    assert pool.subscription_map == {}
    assert pool.subscription_depths == {}
    assert pool.adapter_symbol_counts == [0]


def test_shoonya_unsubscribe_all_reports_broker_failure_and_retains_tracking() -> None:
    from broker.shoonya.streaming.shoonya_adapter import ShoonyaWebSocketAdapter

    class _FailingSocket:
        def unsubscribe_touchline_scrips(self, _scrips: list[str]) -> None:
            raise RuntimeError("broker refused batch")

    class _Cache:
        def __init__(self) -> None:
            self.clear_calls = 0

        def clear(self) -> None:
            self.clear_calls += 1

    adapter = ShoonyaWebSocketAdapter.__new__(ShoonyaWebSocketAdapter)
    adapter.lock = threading.RLock()
    adapter.logger = logging.getLogger("test.websocket.shoonya")
    adapter.connected = True
    adapter.ws_client = _FailingSocket()
    adapter.subscriptions = {
        "NSE|2885": {"scrip": "NSE|2885", "mode": 1}
    }
    adapter.scrip_to_symbol = {"NSE|2885": "RELIANCE"}
    adapter.ws_subscription_refs = {"NSE|2885": {"NSE:RELIANCE"}}
    adapter._scrip_to_cids = {"NSE|2885": {1}}
    adapter._token_to_scrips = {"2885": {"NSE|2885"}}
    adapter.market_cache = _Cache()
    adapter.cleanup = lambda: None

    result = adapter.unsubscribe_all()

    assert result["status"] == "error"
    assert adapter.subscriptions == {
        "NSE|2885": {"scrip": "NSE|2885", "mode": 1}
    }
    assert adapter.scrip_to_symbol == {"NSE|2885": "RELIANCE"}
    assert adapter.ws_subscription_refs == {"NSE|2885": {"NSE:RELIANCE"}}
    assert adapter._scrip_to_cids == {"NSE|2885": {1}}
    assert adapter._token_to_scrips == {"2885": {"NSE|2885"}}
    assert adapter.market_cache.clear_calls == 0


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
                {
                    "symbol": "RELIANCE",
                    "exchange": "NSE",
                    "mode": "Depth",
                    "status": "success",
                }
            ],
            "failed": [
                {
                    "symbol": "INFY",
                    "exchange": "NSE",
                    "mode": "LTP",
                    "status": "error",
                }
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
        {
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "mode": "Depth",
            "status": "success",
        }
    ]
    assert result["failed"] == [
        {
            "symbol": "INFY",
            "exchange": "NSE",
            "mode": "LTP",
            "status": "error",
        }
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


def _ready_client(active: dict[str, set[str]]) -> WebSocketClient:
    client = WebSocketClient("test-key")
    client.connected = True
    client.authenticated = True
    client.loop = object()
    client.ws = object()
    client.active_subscriptions = active
    client._run_on_loop = lambda coroutine, timeout: asyncio.run(coroutine)
    return client


def test_client_normalizes_lowercase_mode_for_wire_and_tracking_cleanup() -> None:
    client = _ready_client({"NSE:RELIANCE": {"LTP"}})
    sent: list[dict[str, Any]] = []

    async def acknowledge(message: dict[str, Any], _request_id: str, timeout: float) -> dict[str, Any]:
        sent.append(message)
        return {
            "status": "success",
            "successful": [
                {
                    "symbol": "RELIANCE",
                    "exchange": "NSE",
                    "mode": "LTP",
                    "status": "success",
                }
            ],
            "failed": [],
        }

    client._send_and_await_ack = acknowledge
    result = client.unsubscribe(
        [{"symbol": "RELIANCE", "exchange": "NSE"}], mode="ltp"
    )

    assert result["status"] == "success"
    assert sent[0]["mode"] == "LTP"
    assert sent[0]["symbols"][0]["mode"] == "LTP"
    assert client.active_subscriptions == {}


def test_client_subscribe_normalizes_wire_and_active_tracking_mode() -> None:
    client = _ready_client({})
    sent: list[dict[str, Any]] = []

    async def acknowledge(message: dict[str, Any], _request_id: str, timeout: float) -> dict[str, Any]:
        sent.append(message)
        return {
            "status": "success",
            "subscriptions": [
                {
                    "symbol": "RELIANCE",
                    "exchange": "NSE",
                    "mode": "LTP",
                    "status": "success",
                }
            ],
        }

    client._send_and_await_ack = acknowledge
    result = client.subscribe(
        [{"symbol": "RELIANCE", "exchange": "NSE"}], mode="ltp"
    )

    assert sent[0]["mode"] == "LTP"
    assert result["mode"] == "LTP"
    assert client.active_subscriptions == {"NSE:RELIANCE": {"LTP"}}


def test_client_correlates_mixed_same_symbol_acknowledgements_by_canonical_mode() -> None:
    client = _ready_client({"NSE:RELIANCE": {"Depth", "LTP"}})

    async def acknowledge(message: dict[str, Any], _request_id: str, timeout: float) -> dict[str, Any]:
        assert [item["mode"] for item in message["symbols"]] == ["Depth", "LTP"]
        return {
            "status": "partial",
            "successful": [
                {
                    "symbol": "RELIANCE",
                    "exchange": "NSE",
                    "mode": "LTP",
                    "status": "success",
                }
            ],
            "failed": [
                {
                    "symbol": "RELIANCE",
                    "exchange": "NSE",
                    "mode": "Depth",
                    "status": "error",
                }
            ],
        }

    client._send_and_await_ack = acknowledge
    client.unsubscribe(
        [
            {"symbol": "RELIANCE", "exchange": "NSE", "mode": "depth"},
            {"symbol": "RELIANCE", "exchange": "NSE", "mode": "ltp"},
        ]
    )

    assert client.active_subscriptions == {"NSE:RELIANCE": {"Depth"}}


@pytest.mark.parametrize("ambiguous", [False, True])
def test_client_legacy_ack_without_mode_only_cleans_an_unambiguous_request(
    ambiguous: bool,
) -> None:
    client = _ready_client({"NSE:RELIANCE": {"Depth", "LTP"}})

    async def acknowledge(message: dict[str, Any], _request_id: str, timeout: float) -> dict[str, Any]:
        return {
            "status": "success",
            "successful": [
                {"symbol": "RELIANCE", "exchange": "NSE", "status": "success"}
            ],
            "failed": [],
        }

    client._send_and_await_ack = acknowledge
    symbols = [{"symbol": "RELIANCE", "exchange": "NSE", "mode": "LTP"}]
    if ambiguous:
        symbols.append(
            {"symbol": "RELIANCE", "exchange": "NSE", "mode": "Depth"}
        )
    client.unsubscribe(symbols)

    expected = {"Depth", "LTP"} if ambiguous else {"Depth"}
    assert client.active_subscriptions == {"NSE:RELIANCE": expected}


def test_client_unsubscribe_all_waits_for_ack_and_preserves_failed_modes() -> None:
    client = _ready_client({"NSE:RELIANCE": {"Depth", "LTP"}})
    sent: list[dict[str, Any]] = []

    async def acknowledge(message: dict[str, Any], _request_id: str, timeout: float) -> dict[str, Any]:
        sent.append(message)
        return {
            "status": "partial",
            "successful": [
                {
                    "symbol": "RELIANCE",
                    "exchange": "NSE",
                    "mode": "LTP",
                    "status": "success",
                }
            ],
            "failed": [
                {
                    "symbol": "RELIANCE",
                    "exchange": "NSE",
                    "mode": "Depth",
                    "status": "error",
                }
            ],
        }

    client._send_and_await_ack = acknowledge
    result = client.unsubscribe_all()

    assert sent[0]["action"] == "unsubscribe_all"
    assert sent[0]["request_id"]
    assert result["status"] == "partial"
    assert client.active_subscriptions == {"NSE:RELIANCE": {"Depth"}}


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
