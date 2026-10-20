"""FivePaisa XTS data-stall watchdog.

XTS sends no heartbeat and its feed is silent outside trading hours, so the
watchdog must only count silence while a subscribed exchange's session is open.
"""

import threading
from datetime import datetime, timedelta, timezone

import pytest

from broker.fivepaisaxts.streaming.fivepaisaxts_websocket import FivepaisaXTSWebSocketClient

IST = timezone(timedelta(hours=5, minutes=30))


def ist(y, mo, d, h, mi):
    return datetime(y, mo, d, h, mi, tzinfo=IST).timestamp()


# 2026-09-30 is a Wednesday, 2026-10-03 a Saturday.
WEEKDAY = (2026, 9, 30)
SATURDAY = (2026, 10, 3)

NSE = {"exchangeSegment": 2, "exchangeInstrumentID": "1"}
MCX = {"exchangeSegment": 51, "exchangeInstrumentID": "2"}


@pytest.fixture
def client():
    c = FivepaisaXTSWebSocketClient("key", "secret", "user")
    yield c
    c._stop_health_check()


def subscribe(client, *instruments):
    client.subscriptions = {
        f"id{i}": {"mode": 2, "instruments": [inst]} for i, inst in enumerate(instruments)
    }


def test_no_reference_without_subscriptions(client):
    assert client._stall_reference(ist(*WEEKDAY, 11, 0)) is None


def test_no_reference_on_weekend(client):
    subscribe(client, NSE)
    assert client._stall_reference(ist(*SATURDAY, 11, 0)) is None


def test_no_reference_outside_equity_session(client):
    subscribe(client, NSE)
    assert client._stall_reference(ist(*WEEKDAY, 8, 0)) is None
    assert client._stall_reference(ist(*WEEKDAY, 16, 0)) is None


def test_mcx_session_runs_late(client):
    subscribe(client, MCX)
    assert client._stall_reference(ist(*WEEKDAY, 20, 0)) is not None
    assert client._stall_reference(ist(*WEEKDAY, 23, 45)) is None


def test_stale_pre_open_message_does_not_count_against_the_open(client):
    """Connected at 08:00, first check at 09:20: silence runs from the 09:15
    open, not from 08:00, or the watchdog reconnects the instant trading starts."""
    subscribe(client, NSE)
    client.last_message_time = ist(*WEEKDAY, 8, 0)
    reference = client._stall_reference(ist(*WEEKDAY, 9, 20))
    assert reference == ist(*WEEKDAY, 9, 15)


def test_recent_message_is_the_reference(client):
    subscribe(client, NSE)
    client.last_message_time = ist(*WEEKDAY, 11, 0)
    assert client._stall_reference(ist(*WEEKDAY, 11, 1)) == ist(*WEEKDAY, 11, 0)


def test_stamped_handler_records_arrival_and_passes_through(client):
    seen = []
    wrapped = client._stamped(lambda payload: seen.append(payload) or "ok")
    client.last_message_time = None

    assert wrapped({"x": 1}) == "ok"
    assert seen == [{"x": 1}]
    assert client.last_message_time is not None


def test_stall_drops_the_transport_but_keeps_subscriptions(client, monkeypatch):
    subscribe(client, NSE)
    client.connected = True
    client.HEALTH_CHECK_INTERVAL = 0.01
    client.DATA_TIMEOUT = 0
    monkeypatch.setattr(client, "_stall_reference", lambda now: now - 1000)

    dropped = threading.Event()

    class FakeSio:
        def disconnect(self):
            dropped.set()

    client.sio = FakeSio()
    client._start_health_check()

    assert dropped.wait(2), "watchdog never dropped the stalled connection"
    assert client.subscriptions, "reconnect needs the subscription book intact"


def test_closed_session_never_drops_the_connection(client, monkeypatch):
    client.connected = True
    client.HEALTH_CHECK_INTERVAL = 0.01
    monkeypatch.setattr(client, "_stall_reference", lambda now: None)

    dropped = threading.Event()

    class FakeSio:
        def disconnect(self):
            dropped.set()

    client.sio = FakeSio()
    client._start_health_check()

    assert not dropped.wait(0.2)


def test_restart_replaces_a_stopping_worker(client):
    client.connected = True
    client.HEALTH_CHECK_INTERVAL = 10
    client._start_health_check()
    first = client._health_thread

    client._stop_health_check()
    client._start_health_check()

    assert client._health_thread is not first
    assert not client._health_stop.is_set()
