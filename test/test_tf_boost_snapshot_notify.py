"""The recorder must tell the panels the moment a snapshot exists.

A blind 60-second poll sat on a finished snapshot for 31 seconds on average and
up to a minute, so a badge the data supported at 10:04 could reach the screen at
10:05. These pin the notification and the fact that it can never cost the tick
its rows.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import services.tf_boost_snapshot_service as svc

IST = ZoneInfo("Asia/Kolkata")


class _Recorder:
    def __init__(self, explode=False):
        self.events = []
        self.explode = explode

    def emit(self, name, payload=None):
        if self.explode:
            raise RuntimeError("socket layer is down")
        self.events.append((name, payload))


def _run_tick(monkeypatch, sio, *, inserted=42, in_window=True):
    """Drive the tick with the network and database stubbed out."""
    monkeypatch.setattr(svc, "_within_market_window", lambda _now: in_window)
    monkeypatch.setattr(svc, "fetch_market_pulse", lambda: None)
    monkeypatch.setattr(svc, "fetch_sector_scope", lambda: None)
    beats = []
    monkeypatch.setattr(svc, "record_heartbeat", lambda *a, **k: beats.append(k or a))

    import extensions

    monkeypatch.setattr(extensions, "socketio", sio, raising=False)
    # The boost lists are stubbed to nothing, so drive the count directly: the
    # emit is gated on rows having been written, not on which list wrote them.
    monkeypatch.setattr(svc, "_enrich_boost_items", lambda items: None)
    svc._run_snapshot_tick()
    return beats


def test_a_tick_that_writes_nothing_does_not_claim_a_snapshot(monkeypatch):
    sio = _Recorder()
    beats = _run_tick(monkeypatch, sio)
    assert sio.events == []  # nothing fetched, nothing written, nothing announced
    assert beats  # but the heartbeat is still recorded


def test_outside_the_session_nothing_is_announced(monkeypatch):
    sio = _Recorder()
    _run_tick(monkeypatch, sio, in_window=False)
    assert sio.events == []


def test_a_broken_socket_never_costs_the_tick(monkeypatch):
    # The notification is a convenience. If it raises, the tick must still end
    # normally -- the snapshot rows are the actual product.
    sio = _Recorder(explode=True)
    beats = _run_tick(monkeypatch, sio)
    assert beats


def test_the_market_window_covers_the_closing_minute():
    # Guards the same boundary the recorder depends on for its last snapshot.
    assert svc._within_market_window(datetime(2026, 9, 18, 15, 30, 0, 150_000, tzinfo=IST))
    assert not svc._within_market_window(datetime(2026, 9, 18, 15, 31, tzinfo=IST))


class _FakeConn:
    def __init__(self):
        self.writes = 0

    def execute(self, *_args, **_kwargs):
        self.writes += 1
        return self


def test_a_tick_that_writes_rows_announces_them(monkeypatch):
    # The case the panel depends on: rows land, and the event goes out naming
    # the snapshot minute, so the badge appears within a second instead of
    # waiting out the poll.
    import contextlib

    sio = _Recorder()
    conn = _FakeConn()

    @contextlib.contextmanager
    def fake_connection(*_a, **_k):
        yield conn

    monkeypatch.setattr(svc, "_within_market_window", lambda _now: True)
    monkeypatch.setattr(svc, "_enrich_boost_items", lambda items: None)
    monkeypatch.setattr(svc, "get_connection", fake_connection)
    monkeypatch.setattr(svc, "record_heartbeat", lambda *a, **k: None)
    monkeypatch.setattr(svc, "fetch_sector_scope", lambda: None)
    monkeypatch.setattr(
        svc,
        "fetch_market_pulse",
        lambda: {
            "intraday_boost": [
                {
                    "symbol": "TESTSYM",
                    "ltp": 100.0,
                    "prev_close": 99.0,
                    "change_pct": 1.01,
                    "score": 5.0,
                }
            ]
        },
    )

    import extensions

    monkeypatch.setattr(extensions, "socketio", sio, raising=False)
    svc._run_snapshot_tick()

    assert conn.writes >= 1, "the row should have been written"
    assert len(sio.events) == 1, f"expected one announcement, got {sio.events}"
    name, payload = sio.events[0]
    assert name == "boost_snapshot"
    assert payload["rows"] == 1
    # The minute is carried so a client can tell a fresh snapshot from a replay.
    assert payload["snapshot_time"].startswith("20")
