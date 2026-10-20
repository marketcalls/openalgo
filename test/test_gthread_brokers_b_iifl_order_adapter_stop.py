"""IIFL's order-update adapter stops even when the stop lands mid-connect.

disconnect() closes whichever MQTT client the adapter holds at that moment.
The adapter's thread checked for a stop, then made an HTTP profile request,
and only then created, stored and connected its client, blocking on a
disconnect event with no timeout. A stop during the profile request (a token
change, a logout, the boot scan racing a login) found no client to close, so
the thread connected anyway and waited forever: an orphaned thread and TLS
session, publishing duplicate order updates until IIFL dropped it.

The MQTT client is a fake; nothing reaches the network.
"""

from __future__ import annotations

import base64
import json
import threading
import time

import pytest

from broker.iiflcapital.streaming import iiflcapital_order_adapter as adapter_module


def _token() -> str:
    claims = base64.urlsafe_b64encode(json.dumps({"preferred_username": "U1"}).encode())
    return f"h.{claims.decode().rstrip('=')}.s"


class FakeMqtt:
    instances: list[FakeMqtt] = []

    def __init__(self, **kwargs):
        self.connected = False
        self.disconnects = 0
        self.connect_gate: threading.Event | None = None
        self.on_connect = self.on_disconnect = self.on_message = self.on_error = None
        FakeMqtt.instances.append(self)

    def connect(self, timeout=15.0):
        if self.connect_gate is not None:
            assert self.connect_gate.wait(5)
        self.connected = True
        return adapter_module.CONNACK_ACCEPTED

    def disconnect(self):
        self.disconnects += 1
        # A client that never finished connecting reports no disconnect, which
        # is the case the adapter used to wait on forever.
        if self.connected and self.on_disconnect is not None:
            self.connected = False
            self.on_disconnect(None)


@pytest.fixture
def adapter(monkeypatch):
    FakeMqtt.instances = []
    monkeypatch.setattr(adapter_module, "IiflMqttClient", FakeMqtt)
    monkeypatch.setattr(adapter_module, "get_auth_token", lambda *a, **k: _token())
    instance = adapter_module.IiflCapitalOrderUpdateAdapter("u1", _token())
    yield instance
    instance.disconnect()


def _stopped(thread, seconds=5.0) -> bool:
    deadline = time.monotonic() + seconds
    while thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.02)
    return not thread.is_alive()


def test_a_stop_during_the_profile_request_opens_no_session(adapter):
    entered, release = threading.Event(), threading.Event()

    def slow_profile():
        entered.set()
        assert release.wait(5)

    adapter._fetch_client_id_if_needed = slow_profile
    adapter.connect()
    assert entered.wait(5)
    adapter.disconnect()
    release.set()

    assert _stopped(adapter._thread), "the adapter thread outlived its stop"
    assert all(not client.connected for client in FakeMqtt.instances)


def test_a_stop_during_the_handshake_closes_the_session_it_opens(adapter):
    adapter._fetch_client_id_if_needed = lambda: None
    gate = threading.Event()
    original_init = FakeMqtt.__init__

    def gated_init(self, **kwargs):
        original_init(self, **kwargs)
        self.connect_gate = gate

    FakeMqtt.__init__ = gated_init
    try:
        adapter.connect()
        deadline = time.monotonic() + 5
        while not FakeMqtt.instances and time.monotonic() < deadline:
            time.sleep(0.01)
        adapter.disconnect()  # the client is stored but not yet connected
        gate.set()  # the handshake completes after the stop
        assert _stopped(adapter._thread)
    finally:
        FakeMqtt.__init__ = original_init

    assert FakeMqtt.instances and all(not c.connected for c in FakeMqtt.instances)


def test_an_ordinary_stop_still_closes_a_live_session(adapter):
    adapter._fetch_client_id_if_needed = lambda: None
    adapter.connect()
    deadline = time.monotonic() + 5
    while not (FakeMqtt.instances and FakeMqtt.instances[0].connected):
        assert time.monotonic() < deadline
        time.sleep(0.01)

    adapter.disconnect()

    assert _stopped(adapter._thread, seconds=2.0)
    assert FakeMqtt.instances[0].disconnects >= 1
