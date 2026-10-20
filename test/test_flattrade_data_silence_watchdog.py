"""A Flattrade session that answers heartbeats but sends no ticks must be recycled.

Issue #2075: the feed goes silent mid-session while the app keeps reporting a
healthy connection. Prices freeze on their last value, position MTM stops
updating, and everything that runs on ticks - scalping stop losses, sandbox
order and GTT triggers, Flow price conditions - quietly stops firing with no
error anywhere.

The cause is that `_on_message` stamps `_last_message_time` for every inbound
frame before classifying it, heartbeat acks included. A Noren gateway that
keeps acking every 30s while delivering no market data therefore looked
perfectly alive to `_check_connection_health`, and the socket was never
recycled. Market-data liveness now has its own clock.

The awkward part is the arming rule, and most of these tests are about it.
Flattrade answers every subscribe with a snapshot frame, so a session opened
outside market hours receives a burst of them - one per subscribed scrip -
and then nothing until the next session. Arming on frame count would recycle
the socket every few minutes all night, and Flattrade answers reconnect churn
with a server-side session cooldown. Arming requires data spread across
several buckets instead, which a burst cannot produce.

These are pure in-memory checks against a fake clock. No broker session, no
sockets, no market hours.
"""

import json

import pytest

# websocket_proxy first: its package __init__ imports the Flattrade adapter,
# which imports back into websocket_proxy. Reaching the streaming package
# first leaves that adapter half-built and the import fails. Pre-existing
# cycle, unrelated to what is tested here.
import websocket_proxy  # noqa: F401  isort:skip

from broker.flattrade.streaming import flattrade_websocket as fws
from broker.flattrade.streaming.flattrade_websocket import FlattradeWebSocket

# A touchline update, and the snapshot Noren sends when a scrip is subscribed.
TICK = json.dumps({"t": "tf", "e": "NFO", "tk": "65872", "lp": "142.50"})
SNAPSHOT = json.dumps({"t": "tk", "e": "NFO", "tk": "65872", "lp": "142.50"})
HEARTBEAT_ACK = json.dumps({"t": "hk"})


class FakeClock:
    """Stands in for the module's `time`, so silence costs no wall time."""

    def __init__(self, start: float = 1_700_000_000.0):
        self.now = start

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeWs:
    """Just enough of a socket for _on_open to send its auth frame."""

    def __init__(self):
        self.sent = []

    def send(self, payload):
        self.sent.append(payload)


@pytest.fixture
def clock(monkeypatch):
    fake = FakeClock()
    monkeypatch.setattr(fws, "time", fake)
    return fake


@pytest.fixture
def client(clock):
    """A connected client whose socket close is recorded rather than performed."""
    ws = FlattradeWebSocket(user_id="FT0001", actid="FT0001", accesstoken="token")
    ws.closed = []
    ws._close_websocket = lambda: ws.closed.append(clock.time())
    ws._update_last_message_time()
    return ws


def feed_live_ticks(client, clock, seconds: int = 120, every: int = 5) -> None:
    """Ticks the way an open market delivers them: steadily, over time."""
    for _ in range(seconds // every):
        client._on_message(None, TICK)
        clock.advance(every)


# ---------------------------------------------------------------------------
# The defect
# ---------------------------------------------------------------------------


def test_a_session_that_only_answers_heartbeats_is_recycled(client, clock):
    """THE DEFECT: heartbeat acks kept a dead feed looking alive indefinitely."""
    feed_live_ticks(client, clock)
    assert client._data_watchdog_armed is True

    # The feed dies. The gateway keeps acking heartbeats every 30s.
    verdicts = []
    for _ in range(6):
        clock.advance(client.HEARTBEAT_INTERVAL)
        client._on_message(None, HEARTBEAT_ACK)
        verdicts.append(client._check_connection_health())

    assert verdicts[:5] == [True] * 5, "must not recycle before the silence threshold"
    assert verdicts[5] is False, "tick silence past the threshold must recycle the socket"
    assert client.closed, "the socket has to actually be closed for reconnect to engage"

    # The point of the fix: on the old measure this connection looked perfect
    # at the very moment it was declared dead, because the ack had just landed.
    assert client._last_message_time == clock.time()


def test_total_silence_still_trips_the_original_heartbeat_timeout(client, clock):
    """The pre-existing check must keep working; the new one is additive."""
    clock.advance(client.HEARTBEAT_TIMEOUT + 1)

    assert client._data_watchdog_armed is False, "nothing armed it, so this is the old path"
    assert client._check_connection_health() is False
    assert client.closed


def test_a_feed_that_keeps_delivering_is_left_alone(client, clock):
    feed_live_ticks(client, clock)

    for _ in range(10):
        clock.advance(client.HEARTBEAT_INTERVAL)
        client._on_message(None, TICK)
        assert client._check_connection_health() is True

    assert client.closed == []


# ---------------------------------------------------------------------------
# Arming: spread over time, not volume
# ---------------------------------------------------------------------------


def test_a_subscribe_time_snapshot_burst_does_not_arm_the_watchdog(client, clock):
    """The overnight case. Fifty scrips subscribed, fifty snapshots, one second.

    Arming here would recycle the socket every DATA_SILENCE_TIMEOUT until the
    market opened, and Flattrade meets reconnect churn with a session cooldown.
    """
    for _ in range(50):
        client._on_message(None, SNAPSHOT)
        clock.advance(0.02)

    assert client._data_watchdog_armed is False

    # Hours of quiet, with the gateway still acking. Nothing may be recycled.
    for _ in range(200):
        clock.advance(client.HEARTBEAT_INTERVAL)
        client._on_message(None, HEARTBEAT_ACK)
        assert client._check_connection_health() is True

    assert client.closed == []


def test_arming_needs_spread_not_volume(client, clock):
    """Five hundred frames in one instant say nothing; three buckets do."""
    for _ in range(500):
        client._on_message(None, TICK)
    assert client._data_watchdog_armed is False

    clock.advance(client.DATA_ARM_BUCKET + 1)
    client._on_message(None, TICK)
    assert client._data_watchdog_armed is False, "two buckets is not yet flow"

    clock.advance(client.DATA_ARM_BUCKET + 1)
    client._on_message(None, TICK)
    assert client._data_watchdog_armed is True


def test_stray_ticks_hours_apart_do_not_arm(client, clock):
    """Buckets far outside the window cannot accumulate into a false arm."""
    for _ in range(5):
        client._on_message(None, TICK)
        clock.advance(3600)

    assert client._data_watchdog_armed is False


# ---------------------------------------------------------------------------
# Arming is per connection
# ---------------------------------------------------------------------------


def test_a_reconnect_starts_the_watchdog_disarmed(client, clock):
    """Bounds the cost of a wrong guess at one reconnect.

    If the market closes while the watchdog is armed, the socket is recycled
    once; the replacement must then sit quietly until data flows again rather
    than recycling on a loop.
    """
    feed_live_ticks(client, clock)
    assert client._data_watchdog_armed is True

    fake_ws = FakeWs()
    client.ws = fake_ws
    try:
        client._on_open(fake_ws)
    finally:
        client._stop_heartbeat()

    assert client._data_watchdog_armed is False
    assert client._last_data_message_time is None
    assert fake_ws.sent, "_on_open still authenticates"

    for _ in range(20):
        clock.advance(client.HEARTBEAT_INTERVAL)
        client._on_message(None, HEARTBEAT_ACK)
        assert client._check_connection_health() is True

    assert client.closed == []
