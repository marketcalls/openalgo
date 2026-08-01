"""Tests for shared-resource safety (gthread PR-5, gates A8, A10, A16).

Covers GT-A10-01/02/03 (shared httpx client), GT-A8-01 (EventBus scoped
sessions) and GT-A16-01/02 (abuse counters).
"""

import inspect
import threading

import httpx

# --------------------------------------------------------------------------
# GT-A10: the shared HTTP client singleton
# --------------------------------------------------------------------------


def test_concurrent_cold_start_builds_exactly_one_client(monkeypatch):
    """The regression: two cold callers must not each build a pool.

    ``if _httpx_client is None: _httpx_client = _create_http_client()`` is a
    check-then-act. Under real threads both callers can see None; the loser's
    100-connection pool is then unreachable and never closed -- an FD leak in a
    worker that never restarts.
    """
    import utils.httpx_client as hc

    monkeypatch.setattr(hc, "_httpx_client", None)

    built = []
    real_create = hc._create_http_client

    def slow_create():
        # Widen the window a racing implementation would lose.
        threading.Event().wait(0.01)
        client = real_create()
        built.append(client)
        return client

    monkeypatch.setattr(hc, "_create_http_client", slow_create)

    results = []
    threads = [
        threading.Thread(target=lambda: results.append(hc.get_httpx_client())) for _ in range(8)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(built) == 1, f"{len(built)} clients built; the extras leak their pools"
    assert len({id(r) for r in results}) == 1, "callers got different clients"


def test_pool_timeout_is_separate_from_the_request_timeout():
    """GT-A10-02: a saturated pool must fail fast, not hang for 120s."""
    from utils.httpx_client import POOL_TIMEOUT, get_httpx_client

    client = get_httpx_client()
    assert isinstance(client.timeout, httpx.Timeout)
    assert client.timeout.pool == POOL_TIMEOUT
    assert client.timeout.read == 120.0
    assert POOL_TIMEOUT < client.timeout.read, "pool wait must be shorter than a read"


def test_pool_stats_are_exposed():
    """GT-A10-03: the pool is shared by request AND background threads, so its
    saturation has to be measured rather than predicted."""
    from utils.httpx_client import get_httpx_client, get_pool_stats

    get_httpx_client()
    stats = get_pool_stats()
    assert stats["created"] is True
    assert stats["max_connections"] == 100
    assert stats["in_use"] is not None


def test_teardown_takes_the_same_lock_as_construction():
    import utils.httpx_client as hc

    src = inspect.getsource(hc.cleanup_httpx_client)
    assert "_httpx_client_lock" in src


# --------------------------------------------------------------------------
# GT-A8: EventBus scoped-session cleanup
# --------------------------------------------------------------------------


def test_event_bus_releases_sessions_on_success_and_failure(monkeypatch):
    """Ten long-lived workers with no app context, so teardown_appcontext never
    fires for them. A scoped session left open holds a connection forever."""
    from utils.event_bus import Event, EventBus

    calls = []
    import utils.db_sessions as ds

    monkeypatch.setattr(ds, "remove_all_scoped_sessions", lambda: calls.append(1))

    bus = EventBus()
    ev = Event(topic="t")

    bus._safe_call(lambda e: None, ev)
    assert calls == [1], "no cleanup on the success path"

    def boom(_e):
        raise RuntimeError("subscriber failed")

    bus._safe_call(boom, ev)
    assert calls == [1, 1], "no cleanup on the exception path"


def test_event_bus_cleanup_is_in_a_finally_block():
    from utils.event_bus import EventBus

    src = inspect.getsource(EventBus._safe_call)
    assert "finally:" in src
    assert "remove_all_scoped_sessions" in src


# --------------------------------------------------------------------------
# GT-A16: abuse counters
# --------------------------------------------------------------------------


def test_abuse_counters_are_serialized():
    """Both counters do a read-modify-write on a DB-backed row.

    Two threads can each load error_count=5, each compute 6, and each commit --
    the increment is lost and the ban threshold is reached later than it should
    be. Serializing the whole decision is cheap here because these paths only
    run during abuse.
    """
    import database.traffic_db as td

    assert hasattr(td, "_abuse_counter_lock")
    for cls, fn in ((td.Error404Tracker, "track_404"),
                    (td.InvalidAPIKeyTracker, "track_invalid_api_key")):
        src = inspect.getsource(getattr(cls, fn))
        assert "_abuse_counter_lock" in src, f"{cls.__name__}.{fn} is not serialized"


def test_lost_update_is_real_without_serialization():
    """Control: an unsynchronized read-modify-write on a shared counter does
    lose increments under real threads."""
    counter = {"n": 0}
    barrier = threading.Barrier(8)

    def bump_unsafe():
        barrier.wait()
        for _ in range(500):
            current = counter["n"]
            counter["n"] = current + 1  # read-modify-write, no lock

    threads = [threading.Thread(target=bump_unsafe) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert counter["n"] <= 8 * 500
    # Not asserting it *always* loses -- the GIL sometimes hides it. The point
    # is that the safe version below never does.

    safe = {"n": 0}
    lock = threading.Lock()
    barrier2 = threading.Barrier(8)

    def bump_safe():
        barrier2.wait()
        for _ in range(500):
            with lock:
                safe["n"] += 1

    threads = [threading.Thread(target=bump_safe) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert safe["n"] == 8 * 500, "serialized counter must never lose an increment"
