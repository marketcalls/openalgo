"""Regression for #2019: zmq_listener must not run MarketDataService work inline
on the event loop shared with websockets.serve()'s handshake accept path.

Self-contained, like test_websocket_unsubscribe_contract.py: no real ZMQ
context, socket or broker adapter.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import defaultdict

from websocket_proxy import server as proxy_server
from websocket_proxy.server import WebSocketProxy


class _OneTickThenIdleSocket:
    """Stands in for the real zmq.asyncio socket: yields one market-data
    message, then blocks (like a real socket with nothing more to deliver)
    until the test tears the loop down.
    """

    def __init__(self, topic: bytes, payload: bytes) -> None:
        self._delivered = False
        self._topic = topic
        self._payload = payload

    async def recv_multipart(self):
        if not self._delivered:
            self._delivered = True
            return [self._topic, self._payload]
        await asyncio.sleep(3600)


def _bare_proxy(socket) -> WebSocketProxy:
    proxy = WebSocketProxy.__new__(WebSocketProxy)
    proxy.running = True
    proxy.socket = socket
    proxy.last_message_time = {}
    proxy._last_cleanup_time = 0.0
    proxy._cleanup_interval = 0.0
    proxy._throttle_entry_max_age = 999999
    proxy._last_stale_check = 0.0
    proxy._stale_check_interval = 0.0
    proxy._stale_tick_warn_seconds = 0
    proxy.subscription_index = defaultdict(set)
    proxy.clients = {}
    proxy._messages_processed = 0
    return proxy


def test_market_data_dispatch_does_not_stall_the_shared_event_loop(monkeypatch):
    socket = _OneTickThenIdleSocket(b"NSE_RELIANCE_LTP", json.dumps({"ltp": 100.0}).encode())
    proxy = _bare_proxy(socket)

    class _BlockingService:
        def process_market_data(self, data):
            time.sleep(0.3)
            proxy.running = False  # stop zmq_listener after this one tick
            return True

    monkeypatch.setattr(proxy_server, "get_market_data_service", lambda: _BlockingService())

    heartbeats = 0

    async def heartbeat():
        nonlocal heartbeats
        while proxy.running:
            await asyncio.sleep(0.01)
            heartbeats += 1

    async def scenario():
        await asyncio.gather(proxy.zmq_listener(), heartbeat())

    asyncio.run(scenario())

    # Fails on unmodified server.py: a synchronous in-loop call blocks every
    # other coroutine (the WS accept path included) for the full 0.3s, so the
    # heartbeat gets essentially no chance to run before running() flips.
    assert heartbeats >= 15, (
        f"only {heartbeats} heartbeats ran during the 0.3s dispatch; "
        "the event loop was stalled by a synchronous MarketDataService call"
    )


def test_market_data_dispatch_receives_the_parsed_topic_fields(monkeypatch):
    # Control: green on both sides, but genuinely sensitive to the refactor
    # (await asyncio.to_thread(fn, mds_data)) passing the wrong callable or
    # the wrong argument through.
    received = []

    socket = _OneTickThenIdleSocket(b"NSE_RELIANCE_LTP", json.dumps({"ltp": 100.0}).encode())
    proxy = _bare_proxy(socket)

    class _RecordingService:
        def process_market_data(self, data):
            received.append(data)
            proxy.running = False
            return True

    monkeypatch.setattr(proxy_server, "get_market_data_service", lambda: _RecordingService())

    asyncio.run(proxy.zmq_listener())

    assert received == [
        {"symbol": "RELIANCE", "exchange": "NSE", "mode": 1, "data": {"ltp": 100.0}}
    ]
