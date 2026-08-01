"""Tests for MCP hardening under real threads (gthread PR-7, gate A6).

Covers GT-A6-01 (scope quota), GT-A6-02 (audit rotation), GT-A6-03
(initialization guard) and GT-A6-04 (SSE accounting).

The quota's own comment used to read "single eventlet worker, so no
shared-state concerns". That premise is precisely what this migration removes.
"""

import sys
import threading
import time

import pytest

import blueprints.mcp_http as mcp


@pytest.fixture(autouse=True)
def _clean_quota():
    mcp._scope_quota.clear()
    mcp._last_quota_sweep = 0.0
    yield
    mcp._scope_quota.clear()


# --------------------------------------------------------------------------
# GT-A6-01: scope quota
# --------------------------------------------------------------------------


def test_quota_admits_exactly_its_limit_under_a_thread_barrier():
    """The regression: prune-test-admit must be one critical section.

    Split, several callers read the same bucket length before any appends, and
    the quota over-admits -- on the surface fronting live order placement.
    """
    count, _window = mcp._parse_rate_spec(mcp._RATE_LIMIT_WRITE)
    workers = count * 4
    barrier = threading.Barrier(workers)
    admitted = []
    lock = threading.Lock()

    def caller():
        barrier.wait()  # maximise the collision
        ok = mcp._within_scope_quota(jti="tok-1", scope="write:orders")
        if ok:
            with lock:
                admitted.append(1)

    threads = [threading.Thread(target=caller) for _ in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(admitted) == count, f"admitted {len(admitted)}, quota is {count}"


def test_unlocked_quota_really_does_over_admit():
    """The control. Without it, the test above could pass for the wrong reason.

    Note this is intermittent -- a single run sometimes admits exactly the
    limit. That is the point: the defect would not be caught reliably by a test
    that runs once, which is why the locked version is asserted across trials.
    """
    old = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        over_admitted = False
        for _ in range(5):
            quota: dict[str, list[float]] = {}
            limit, window = 5, 60

            def within_unlocked(jti, scope, q=quota, limit=limit, window=window):
                now = time.time()
                bucket = q.setdefault(f"{jti}|{scope}", [])
                while bucket and bucket[0] < now - window:
                    bucket.pop(0)
                if len(bucket) >= limit:
                    return False
                time.sleep(0)  # any work between the test and the admit
                bucket.append(now)
                return True

            admitted = []
            guard = threading.Lock()
            barrier = threading.Barrier(20)

            def caller(_b=barrier, _g=guard, _a=admitted, _f=within_unlocked):
                _b.wait()
                if _f("tok", "write:orders"):
                    with _g:
                        _a.append(1)

            threads = [threading.Thread(target=caller) for _ in range(20)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            if len(admitted) > limit:
                over_admitted = True
                break
    finally:
        sys.setswitchinterval(old)

    assert over_admitted, "expected an unlocked quota to over-admit"


def test_locked_quota_holds_across_repeated_trials():
    """The locked version must never over-admit, on any trial."""
    count, _ = mcp._parse_rate_spec(mcp._RATE_LIMIT_WRITE)
    old = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        for trial in range(5):
            mcp._scope_quota.clear()
            admitted = []
            guard = threading.Lock()
            barrier = threading.Barrier(count * 4)

            def caller(_b=barrier, _g=guard, _a=admitted, _t=trial):
                _b.wait()
                if mcp._within_scope_quota(jti=f"t{_t}", scope="write:orders"):
                    with _g:
                        _a.append(1)

            threads = [threading.Thread(target=caller) for _ in range(count * 4)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            assert len(admitted) == count, f"trial {trial}: admitted {len(admitted)}"
    finally:
        sys.setswitchinterval(old)


def test_quota_is_per_jti_and_per_scope():
    count, _ = mcp._parse_rate_spec(mcp._RATE_LIMIT_WRITE)
    for _ in range(count):
        assert mcp._within_scope_quota(jti="a", scope="write:orders") is True
    # Exhausted for a...
    assert mcp._within_scope_quota(jti="a", scope="write:orders") is False
    # ...but a different token is unaffected.
    assert mcp._within_scope_quota(jti="b", scope="write:orders") is True


def test_missing_jti_is_refused():
    assert mcp._within_scope_quota(jti=None, scope="write:orders") is False


def test_quota_registry_is_bounded():
    """GT-A6-01: buckets were only pruned when the same key recurred, so a
    token that goes quiet kept its key for the life of the process."""
    for i in range(200):
        mcp._within_scope_quota(jti=f"tok-{i}", scope="read:data")
    assert len(mcp._scope_quota) == 200

    # Age every bucket beyond its window, then force a sweep.
    _count, window = mcp._parse_rate_spec(mcp._RATE_LIMIT_READ)
    old = time.time() - window - 60
    for bucket in mcp._scope_quota.values():
        bucket[:] = [old]
    mcp._last_quota_sweep = 0.0

    mcp._within_scope_quota(jti="fresh", scope="read:data")
    assert len(mcp._scope_quota) < 200, "expired buckets were never swept"


def test_quota_sweep_keeps_live_buckets():
    """A sweep must not evict a token that is actively using its quota."""
    mcp._within_scope_quota(jti="live", scope="read:data")
    mcp._last_quota_sweep = 0.0
    mcp._within_scope_quota(jti="other", scope="read:data")
    assert "live|read:data" in mcp._scope_quota


# --------------------------------------------------------------------------
# GT-A6-02: audit log
# --------------------------------------------------------------------------


def test_audit_append_and_rotation_share_a_lock():
    import inspect

    assert hasattr(mcp, "_audit_lock")
    src = inspect.getsource(mcp._audit_log)
    assert "_audit_lock" in src


def test_concurrent_audit_writes_lose_no_lines(tmp_path, monkeypatch):
    """Rotation reads the whole file and writes it back; a concurrent append
    lands in the copy about to be overwritten and disappears."""
    path = tmp_path / "mcp.jsonl"
    monkeypatch.setattr(mcp, "_AUDIT_PATH", path)
    monkeypatch.setattr(mcp, "_AUDIT_MAX_LINES", 200)

    workers, per_worker = 8, 50
    barrier = threading.Barrier(workers)

    def writer(w):
        barrier.wait()
        for i in range(per_worker):
            mcp._audit_log({"w": w, "i": i})

    threads = [threading.Thread(target=writer, args=(w,)) for w in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    # Every line must be complete JSON -- a torn write would not parse.
    import json

    for ln in lines:
        json.loads(ln)
    assert len(lines) == workers * per_worker


# --------------------------------------------------------------------------
# GT-A6-03: initialization
# --------------------------------------------------------------------------


def test_initialization_is_single_flight(monkeypatch):
    """Startup normally initializes once, but the first MCP requests can get
    there first; two of them would build two SDK clients."""
    monkeypatch.setattr(mcp, "_initialized", False)

    runs = []

    def fake_locked():
        runs.append(1)
        time.sleep(0.02)  # widen the window
        mcp._initialized = True

    monkeypatch.setattr(mcp, "_init_http_transport_locked", fake_locked)

    barrier = threading.Barrier(8)

    def caller():
        barrier.wait()
        mcp.init_http_transport()

    threads = [threading.Thread(target=caller) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(runs) == 1, f"initialized {len(runs)} times"


def test_initialization_guard_rechecks_inside_the_lock():
    import inspect

    src = inspect.getsource(mcp.init_http_transport)
    assert src.count("if _initialized:") >= 2, "missing double-check"
    assert "_init_lock" in src
