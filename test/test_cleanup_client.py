"""Regression tests for WebSocketProxy.cleanup_client teardown/keep-alive (issue #1490).

Covers the five paths through cleanup_client's adapter-disposal logic:

1. Normal full-disconnect (Zerodha, Angel, etc.)
2. Full-disconnect when adapter.disconnect() raises
3. Flattrade/Shoonya keep-alive normal path
4. Flattrade/Shoonya keep-alive when unsubscribe_all() raises
5. Multi-client: adapter not torn down while sibling clients remain
6. Defensive sweep: stale subscription_index entries purged

These construct a WebSocketProxy via __new__ to bypass __init__ (which binds
a port and opens ZeroMQ sockets), and exercise only the state-mapping logic.

Run with: uv run pytest test/test_cleanup_client.py -v
"""

import asyncio
import os
import sys
from collections import defaultdict
from unittest.mock import Mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from websocket_proxy.server import WebSocketProxy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ws_proxy():
    """Create a minimal WebSocketProxy without binding a port or ZeroMQ."""
    proxy = WebSocketProxy.__new__(WebSocketProxy)
    proxy.clients = {}
    proxy.subscriptions = {}
    proxy.broker_adapters = {}
    proxy.user_mapping = {}
    proxy.user_broker_mapping = {}
    proxy.subscription_index = defaultdict(set)
    return proxy


def _seed_client(proxy, client_id, user_id, broker_name, adapter):
    """Register a fake client in the proxy's internal state maps."""
    proxy.clients[client_id] = object()
    proxy.subscriptions[client_id] = set()
    proxy.user_mapping[client_id] = user_id
    proxy.broker_adapters[user_id] = adapter
    proxy.user_broker_mapping[user_id] = broker_name


# ---------------------------------------------------------------------------
# Full-disconnect branch (Zerodha, Angel, etc.)
# ---------------------------------------------------------------------------

def test_full_disconnect_removes_mappings_even_when_disconnect_raises():
    """adapter.disconnect() raises — mappings must still be cleaned up."""
    proxy = _make_ws_proxy()
    adapter = Mock()
    adapter.disconnect.side_effect = RuntimeError("adapter died mid-disconnect")
    _seed_client(proxy, "c1", "u1", "zerodha", adapter)

    asyncio.run(proxy.cleanup_client("c1"))

    adapter.disconnect.assert_called_once()
    assert "c1" not in proxy.clients
    assert "c1" not in proxy.subscriptions
    assert "c1" not in proxy.user_mapping
    assert "u1" not in proxy.broker_adapters
    assert "u1" not in proxy.user_broker_mapping


def test_full_disconnect_normal_path():
    """Normal broker disconnect clears adapter and user-broker mappings."""
    proxy = _make_ws_proxy()
    adapter = Mock()
    _seed_client(proxy, "c1", "u1", "angel", adapter)

    asyncio.run(proxy.cleanup_client("c1"))

    adapter.disconnect.assert_called_once()
    adapter.unsubscribe_all.assert_not_called()
    assert "u1" not in proxy.broker_adapters
    assert "u1" not in proxy.user_broker_mapping


# ---------------------------------------------------------------------------
# Keep-alive branch (Flattrade, Shoonya)
# ---------------------------------------------------------------------------

def test_flattrade_keeps_mapping_even_when_unsubscribe_all_raises():
    """unsubscribe_all() raises — adapter mapping must survive (keep-alive)."""
    proxy = _make_ws_proxy()
    adapter = Mock()
    adapter.unsubscribe_all.side_effect = RuntimeError("unsubscribe_all failed")
    _seed_client(proxy, "c1", "u1", "flattrade", adapter)

    asyncio.run(proxy.cleanup_client("c1"))

    assert "u1" in proxy.broker_adapters
    assert proxy.user_broker_mapping.get("u1") == "flattrade"
    adapter.unsubscribe_all.assert_called_once()
    adapter.disconnect.assert_not_called()


def test_shoonya_keep_alive_normal_path():
    """Shoonya adapter stays alive after last client disconnects."""
    proxy = _make_ws_proxy()
    adapter = Mock()
    _seed_client(proxy, "c1", "u1", "shoonya", adapter)

    asyncio.run(proxy.cleanup_client("c1"))

    adapter.unsubscribe_all.assert_called_once()
    adapter.disconnect.assert_not_called()
    assert "u1" in proxy.broker_adapters
    assert "u1" in proxy.user_broker_mapping


# ---------------------------------------------------------------------------
# Multi-client scenarios
# ---------------------------------------------------------------------------

def test_no_teardown_when_other_client_still_connected():
    """Adapter must not disconnect when another client for the same user exists."""
    proxy = _make_ws_proxy()
    adapter = Mock()
    _seed_client(proxy, "c1", "u1", "zerodha", adapter)
    proxy.user_mapping["c2"] = "u1"

    asyncio.run(proxy.cleanup_client("c1"))

    adapter.disconnect.assert_not_called()
    assert "u1" in proxy.broker_adapters
    assert "u1" in proxy.user_broker_mapping
    assert "c2" in proxy.user_mapping


# ---------------------------------------------------------------------------
# Defensive subscription_index sweep
# ---------------------------------------------------------------------------

def test_purges_subscription_index_and_unsubscribes_adapter_for_unparseable_subscription():
    """Stale index entries for unparseable subscriptions must be unsubscribed at adapter before purging."""
    proxy = _make_ws_proxy()
    adapter = Mock()
    _seed_client(proxy, "c1", "u1", "zerodha", adapter)
    proxy.subscriptions["c1"] = {"not-json"}
    proxy.subscription_index[("SBIN", "NSE", 2)].add("c1")

    asyncio.run(proxy.cleanup_client("c1"))

    assert ("SBIN", "NSE", 2) not in proxy.subscription_index
    adapter.unsubscribe.assert_called_once_with("SBIN", "NSE", 2)
    adapter.disconnect.assert_called_once()


def test_defensive_sweep_unsubscribes_adapter_when_sibling_client_remains():
    """Unparseable subscription dropped in defensive sweep must unsubscribe adapter even when another client stays connected."""
    proxy = _make_ws_proxy()
    adapter = Mock()
    _seed_client(proxy, "c1", "u1", "zerodha", adapter)
    proxy.user_mapping["c2"] = "u1"
    proxy.subscriptions["c1"] = {"bad-json"}
    proxy.subscription_index[("TATASTEEL", "NSE", 1)].add("c1")

    asyncio.run(proxy.cleanup_client("c1"))

    assert ("TATASTEEL", "NSE", 1) not in proxy.subscription_index
    adapter.unsubscribe.assert_called_once_with("TATASTEEL", "NSE", 1)
    adapter.disconnect.assert_not_called()

