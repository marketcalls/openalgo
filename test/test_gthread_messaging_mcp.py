"""The remote MCP transport under the gthread worker, and unchanged elsewhere.

Under ``gunicorn --worker-class gthread`` every request holds a thread from a
fixed pool, so four things in ``blueprints/mcp_http.py`` that were harmless on
eventlet's greenlets have to hold:

* a ``GET /mcp`` stream is counted, capped and given a lifetime, and its slot
  comes back however it ends, including a client that leaves before the first
  byte;
* tool calls in flight are capped, and a tool's SDK call back into
  ``/api/v1/`` is served on the calling thread rather than by a second pool
  thread over HTTP;
* the audit log, the first-request init and the per-token write quota are each
  one critical section, because two request threads now really do run them at
  the same moment.

Every cap and lifetime applies only under gthread. The tests that simulate
gthread register a fake gthread worker with ``utils.runtime``, which is what
the launcher's post_worker_init hook does; the others run as the development
server, and assert that nothing changed there.
"""

from __future__ import annotations

import collections
import json
import threading
import time
import types

import httpx
import pytest
from flask import Flask, jsonify, request

import blueprints.mcp_http as mcp_http
from limiter import limiter
from utils import runtime, stream_registry

TOKEN = "test-bearer-token"


# --- fixtures ----------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    """Isolate the runtime registration, the stream counts and module state."""
    monkeypatch.setattr(runtime, "_registered", None)
    monkeypatch.setattr(runtime, "_worker_ref", None)
    monkeypatch.delenv("OPENALGO_EFFECTIVE_THREADS", raising=False)
    stream_registry._reset_for_tests()
    monkeypatch.setattr(mcp_http, "_tool_calls_open", 0)
    monkeypatch.setattr(mcp_http, "_scope_quota", {})
    monkeypatch.setattr(mcp_http, "_last_quota_sweep", 0.0)
    yield
    stream_registry._reset_for_tests()


def _as_gthread(threads: int = 64) -> None:
    """Register a fake gthread worker, as the launcher's hook does."""
    cls = type("FakeWorker", (), {})
    cls.__module__ = "gunicorn.workers.gthread"
    worker = cls()
    worker.cfg = types.SimpleNamespace(
        worker_class_str="gthread", threads=threads, workers=1, graceful_timeout=30
    )
    runtime.register_gunicorn_worker(worker)
    assert runtime.gthread_active()


@pytest.fixture
def app(monkeypatch, tmp_path):
    """A minimal app with only the MCP blueprint and a stubbed token check."""
    monkeypatch.setattr(mcp_http, "init_http_transport", lambda: None)
    monkeypatch.setattr(
        mcp_http,
        "verify_access_token",
        lambda token: {
            "jti": f"jti-{token}",
            "scope": "read:market write:orders",
            "client_id": "c",
        },
    )
    monkeypatch.setattr(mcp_http, "_AUDIT_PATH", tmp_path / "mcp.jsonl")
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.config["RATELIMIT_ENABLED"] = False
    limiter.init_app(flask_app)
    flask_app.register_blueprint(mcp_http.mcp_http_bp)
    return flask_app


def _get_stream(client, token=TOKEN):
    return client.get("/mcp", headers={"Authorization": f"Bearer {token}"}, buffered=False)


def _tool_call(client, name="blocking_tool", token=TOKEN):
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": name, "arguments": {}},
    }
    return client.post("/mcp", json=body, headers={"Authorization": f"Bearer {token}"})


# --- GET /mcp -----------------------------------------------------------------


class _StreamHolder:
    """Open one GET /mcp on its own thread, as a server would, and hold it.

    Each stream must be driven from its own thread: stream_with_context pushes
    the request's context whenever its generator resumes, and two streams
    interleaved on one thread pop each other's contexts.
    """

    def __init__(self, app, token):
        self.opened = threading.Event()
        self.go = threading.Event()
        self.status = None
        self.first = None
        self.body = b""
        self.elapsed = None
        self._consume = False
        self._thread = threading.Thread(target=self._run, args=(app, token), daemon=True)
        self._thread.start()
        assert self.opened.wait(10)

    def _run(self, app, token):
        response = _get_stream(app.test_client(), token=token)
        self.status = response.status_code
        chunks = iter(response.response)
        if self.status == 200:
            self.first = next(chunks)
        self.opened.set()
        self.go.wait(10)
        started = time.monotonic()
        try:
            if self._consume:
                self.body = b"".join(chunks)
        finally:
            self.elapsed = time.monotonic() - started
            response.close()

    def finish(self, consume=False):
        """Read to the end (consume) or hang up now, and wait for the thread."""
        self._consume = consume
        self.go.set()
        self._thread.join(15)
        assert not self._thread.is_alive()


def test_a_stream_off_gthread_is_counted_but_never_capped_or_ended(app):
    """The development server (and eventlet) keep the stream exactly as it was."""
    holders = [_StreamHolder(app, f"t{i}") for i in range(mcp_http.MCP_SSE_MAX_STREAMS + 3)]
    try:
        assert all(h.status == 200 for h in holders)
        # No reconnect hint: the stream has no lifetime here.
        assert holders[0].first == b": openalgo-mcp connected\n\n"
        assert stream_registry.snapshot()["mcp_sse"]["open"] == len(holders)
    finally:
        for holder in holders:
            holder.finish()
    assert stream_registry.snapshot()["mcp_sse"]["open"] == 0


def test_under_gthread_streams_are_capped_and_end_by_themselves(app, monkeypatch):
    _as_gthread()
    monkeypatch.setattr(mcp_http, "MCP_SSE_MAX_STREAMS", 2)
    monkeypatch.setattr(mcp_http, "MCP_SSE_MAX_SECONDS", 0.3)
    client = app.test_client()

    first = _StreamHolder(app, "a")
    second = _StreamHolder(app, "b")
    assert first.status == 200 and second.status == 200
    # Each stream advertises its reconnect delay before anything else.
    assert first.first.startswith(b"retry: 30000\n")

    refused = _get_stream(client, token="c")
    assert refused.status_code == 429
    assert refused.headers["Retry-After"] == "30"
    assert "Try again" in refused.get_data(as_text=True)
    refused.close()

    # Each stream then ends on its own, without the client hanging up.
    first.finish(consume=True)
    second.finish(consume=True)
    assert first.elapsed < 5 and second.elapsed < 5
    assert stream_registry.snapshot()["mcp_sse"]["open"] == 0

    again = _StreamHolder(app, "d")
    assert again.status == 200
    again.finish()


def test_a_client_that_leaves_before_the_first_byte_frees_its_slot(app, monkeypatch):
    """The generator never starts, so only call_on_close can release the slot.

    The view is called directly: the test client always pulls the first chunk,
    which starts the generator and would let its finally do the release.
    """
    _as_gthread()
    monkeypatch.setattr(mcp_http, "MCP_SSE_MAX_STREAMS", 1)
    view = app.view_functions["mcp_http_bp.mcp_sse"]
    for _ in range(3):
        with app.test_request_context("/mcp", headers={"Authorization": f"Bearer {TOKEN}"}):
            response = view()
            assert response.status_code == 200
            assert stream_registry.snapshot()["mcp_sse"]["open"] == 1
            response.close()  # never iterated
        assert stream_registry.snapshot()["mcp_sse"]["open"] == 0


def test_a_stream_dropped_mid_way_frees_its_slot(app, monkeypatch):
    _as_gthread()
    monkeypatch.setattr(mcp_http, "MCP_SSE_MAX_STREAMS", 1)
    for _ in range(3):
        holder = _StreamHolder(app, TOKEN)
        assert holder.status == 200
        holder.finish()
        assert stream_registry.snapshot()["mcp_sse"]["open"] == 0


def test_a_stream_ends_when_the_server_begins_shutting_down(app):
    holder = _StreamHolder(app, TOKEN)
    assert holder.first.startswith(b": openalgo-mcp connected")
    stream_registry.request_drain()
    holder.finish(consume=True)
    assert holder.elapsed < 3
    assert b"keepalive" not in holder.body
    assert stream_registry.snapshot()["mcp_sse"]["open"] == 0


def test_an_unauthenticated_get_is_still_challenged_and_not_counted(app, monkeypatch):
    _as_gthread()
    client = app.test_client()
    response = client.get("/mcp")
    assert response.status_code == 401
    assert "Bearer" in response.headers["WWW-Authenticate"]
    assert stream_registry.snapshot().get("mcp_sse", {"open": 0})["open"] == 0


# --- tools/call in flight -------------------------------------------------------


@pytest.fixture
def blocking_tool(monkeypatch):
    """A tool that parks on an Event, with scope checks stubbed open."""
    import utils.mcp_tool_registry as registry

    release = threading.Event()
    entered = []
    entered_lock = threading.Lock()

    def tool():
        with entered_lock:
            entered.append(threading.get_ident())
        release.wait(10)
        return "ok"

    monkeypatch.setattr(registry, "required_scope", lambda name: "read:market")
    monkeypatch.setattr(registry, "get_tool_callable", lambda name: tool)
    monkeypatch.setattr(mcp_http, "claims_have_scope", lambda claims, scope: True)
    return types.SimpleNamespace(release=release, entered=entered)


def _fire_parallel(app, count):
    barrier = threading.Barrier(count)
    results = [None] * count

    def call(index):
        client = app.test_client()
        barrier.wait()
        results[index] = _tool_call(client, token=f"tok{index}").get_json()

    threads = [threading.Thread(target=call, args=(i,)) for i in range(count)]
    for thread in threads:
        thread.start()
    return threads, results


def test_under_gthread_tool_calls_in_flight_are_capped(app, blocking_tool):
    _as_gthread(threads=24)  # 24 // 8 = 3 calls at once
    assert mcp_http._tool_call_limit() == 3
    threads, results = _fire_parallel(app, 6)

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        refused = [r for r in results if r is not None]
        if len(blocking_tool.entered) == 3 and len(refused) == 3:
            break
        time.sleep(0.02)
    assert len(blocking_tool.entered) == 3
    refused = [r for r in results if r is not None]
    assert len(refused) == 3
    for body in refused:
        assert body["error"]["message"] == "server_busy"
        assert body["error"]["data"]["retry_safe"] is True
        assert "nothing was sent" in body["error"]["data"]["reason"]

    blocking_tool.release.set()
    for thread in threads:
        thread.join(10)
    assert mcp_http.tool_calls_in_flight() == 0
    assert sum(1 for r in results if "result" in r) == 3

    # Every slot came back: a further call runs.
    after = _tool_call(app.test_client(), token="later").get_json()
    assert after["result"]["content"][0]["text"] == "ok"


def test_a_refused_call_uses_no_quota(app, blocking_tool, monkeypatch):
    _as_gthread(threads=8)  # the floor of two applies
    assert mcp_http._tool_call_limit() == 2
    quota_checks = []
    real_quota = mcp_http._within_scope_quota

    def counting_quota(**kwargs):
        quota_checks.append(kwargs)
        return real_quota(**kwargs)

    monkeypatch.setattr(mcp_http, "_within_scope_quota", counting_quota)
    threads, results = _fire_parallel(app, 4)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and sum(r is not None for r in results) < 2:
        time.sleep(0.02)
    blocking_tool.release.set()
    for thread in threads:
        thread.join(10)
    busy = [r for r in results if r.get("error", {}).get("message") == "server_busy"]
    assert len(busy) == 2
    assert len(quota_checks) == 2


def test_off_gthread_tool_calls_are_not_capped(app, blocking_tool):
    assert mcp_http._tool_call_limit() is None
    threads, results = _fire_parallel(app, 12)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and len(blocking_tool.entered) < 12:
        time.sleep(0.02)
    assert len(blocking_tool.entered) == 12
    blocking_tool.release.set()
    for thread in threads:
        thread.join(10)
    assert all("result" in r for r in results)
    assert mcp_http.tool_calls_in_flight() == 0


# --- the SDK served in process -----------------------------------------------


def _sdk_client_class():
    """The installed openalgo SDK's api class, or None when it cannot be reached."""
    try:
        from openalgo import api
    except Exception:
        return None
    return api if hasattr(api, "funds") else None


@pytest.fixture
def served_app(monkeypatch, tmp_path):
    """An app with a stand-in /api/v1/funds and a fake mcpserver whose SDK is real."""
    api_cls = _sdk_client_class()
    if api_cls is None:
        pytest.skip("the openalgo SDK is not importable here")
    import utils.mcp_tool_registry as registry

    seen = {"threads": [], "teardowns": 0, "outer_ok": []}
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.config["RATELIMIT_ENABLED"] = False
    limiter.init_app(flask_app)

    @flask_app.route("/api/v1/funds", methods=["POST"])
    def funds():
        seen["threads"].append(threading.get_ident())
        return jsonify({"status": "success", "data": {"key": request.get_json()["apikey"]}})

    @flask_app.teardown_appcontext
    def _teardown(_exc=None):
        seen["teardowns"] += 1

    flask_app.register_blueprint(mcp_http.mcp_http_bp)

    fake = types.ModuleType("fake_mcpserver")
    fake.client = None

    def init_for_http(key, host):
        # Port 9 on loopback is discard: nothing answers, so a request that
        # reached the network would fail rather than silently succeed.
        fake.client = api_cls(api_key=key, host="http://127.0.0.1:9")

    def funds_tool():
        seen["tool_thread"] = threading.get_ident()
        result = fake.client.funds()
        # The outer request's context is intact after the inner one.
        seen["outer_ok"].append(request.path == "/mcp")
        return json.dumps(result)

    fake.init_for_http = init_for_http
    fake.funds_tool = funds_tool
    monkeypatch.setattr(registry, "_load_mcpserver_module", lambda: fake)
    monkeypatch.setattr(registry, "audit_registry", lambda: None)
    monkeypatch.setattr(registry, "required_scope", lambda name: "read:market")
    monkeypatch.setattr(registry, "get_tool_callable", lambda name: getattr(fake, name, None))
    monkeypatch.setattr(mcp_http, "claims_have_scope", lambda claims, scope: True)
    monkeypatch.setattr(
        mcp_http,
        "verify_access_token",
        lambda token: {"jti": "j", "scope": "read:market", "client_id": "c"},
    )
    monkeypatch.setattr(mcp_http, "_AUDIT_PATH", tmp_path / "mcp.jsonl")
    monkeypatch.setattr(mcp_http, "_initialized", False)
    import database.auth_db as auth_db

    monkeypatch.setattr(auth_db, "get_first_available_api_key", lambda: "the-key")
    return types.SimpleNamespace(app=flask_app, seen=seen, fake=fake, tmp=tmp_path)


def test_under_gthread_a_tool_reaches_the_api_on_its_own_thread(served_app):
    _as_gthread()
    body = _tool_call(served_app.app.test_client(), name="funds_tool").get_json()

    text = body["result"]["content"][0]["text"]
    assert json.loads(text) == {"status": "success", "data": {"key": "the-key"}}
    seen = served_app.seen
    assert seen["threads"] == [seen["tool_thread"]], "the API call ran on another thread"
    assert seen["outer_ok"] == [True]
    # The inner request had its own application context and tore it down.
    assert seen["teardowns"] >= 2
    assert isinstance(served_app.fake.client.client._transport, httpx.WSGITransport)
    audit = (served_app.tmp / "mcp.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(audit[-1])["outcome"] == "success"


def test_off_gthread_the_sdk_keeps_its_http_loopback(served_app):
    """Eventlet and the development server reach /api/v1/ over HTTP, as before."""
    body = _tool_call(served_app.app.test_client(), name="funds_tool").get_json()
    # Port 9 answers nothing, so the tool reports the SDK's connection error.
    text = body["result"]["content"][0]["text"]
    assert json.loads(text)["error_type"] == "connection_error"
    assert served_app.seen["threads"] == []
    assert not isinstance(served_app.fake.client.client._transport, httpx.WSGITransport)


# --- audit log ------------------------------------------------------------------


def test_concurrent_audit_writes_lose_and_tear_no_lines(monkeypatch, tmp_path):
    path = tmp_path / "mcp.jsonl"
    monkeypatch.setattr(mcp_http, "_AUDIT_PATH", path)
    monkeypatch.setattr(mcp_http, "_AUDIT_TRIM_BYTES", 2000)
    monkeypatch.setattr(mcp_http, "_AUDIT_MAX_LINES", 50)

    # Widen the window between a trim's read and its rewrite.
    real_read_text = type(path).read_text

    def slow_read_text(self, *args, **kwargs):
        text = real_read_text(self, *args, **kwargs)
        time.sleep(0.005)
        return text

    monkeypatch.setattr(type(path), "read_text", slow_read_text)

    writers, per_writer = 8, 60
    barrier = threading.Barrier(writers)

    def write(worker):
        barrier.wait()
        for n in range(per_writer):
            mcp_http._audit_log({"worker": worker, "n": n, "pad": "x" * 40})

    threads = [threading.Thread(target=write, args=(w,)) for w in range(writers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)

    lines = path.read_text(encoding="utf-8").splitlines()
    entries = [json.loads(line) for line in lines]  # a torn line fails here
    assert 1 <= len(entries) <= 50 + writers
    # Nothing that was written last is missing: each writer's final entry is
    # the newest line of that writer and must have survived every trim.
    last = {(e["worker"], e["n"]) for e in entries}
    for worker in range(writers):
        assert (worker, per_writer - 1) in last
    assert not list(tmp_path.glob(".mcp-audit-*.tmp"))


# --- first-request init ---------------------------------------------------------


def test_initialization_is_single_flight(monkeypatch):
    import database.auth_db as auth_db
    import utils.mcp_tool_registry as registry

    calls = collections.Counter()
    fake = types.ModuleType("fake_mcpserver")

    def init_for_http(key, host):
        calls["init_for_http"] += 1
        fake.client = object()

    fake.init_for_http = init_for_http

    def slow_loader():
        calls["load"] += 1
        time.sleep(0.05)
        return fake

    monkeypatch.setattr(registry, "_load_mcpserver_module", slow_loader)
    monkeypatch.setattr(registry, "audit_registry", lambda: None)
    monkeypatch.setattr(auth_db, "get_first_available_api_key", lambda: "k")
    monkeypatch.setattr(mcp_http, "_initialized", False)

    count = 8
    barrier = threading.Barrier(count)
    saw_client = []

    def first_request():
        barrier.wait()
        mcp_http.init_http_transport()
        saw_client.append(getattr(fake, "client", None) is not None)

    threads = [threading.Thread(target=first_request) for _ in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
    assert calls == {"load": 1, "init_for_http": 1}
    assert saw_client == [True] * count


# --- write quota ------------------------------------------------------------------


class _SlowBucket(collections.deque):
    """A bucket whose length check yields, so a missing lock shows up at once."""

    def __len__(self):
        length = super().__len__()
        time.sleep(0.001)  # another caller runs between the count and the append
        return length

    def pop(self, index=None):  # the pre-fix code popped index 0 of a list
        return self.popleft() if index == 0 else super().pop()


def test_the_write_quota_admits_exactly_its_limit(monkeypatch):
    monkeypatch.setattr(mcp_http, "_RATE_LIMIT_WRITE", "5 per minute")
    key = "jti-race|write:orders"
    callers = 20
    for _trial in range(10):
        monkeypatch.setattr(mcp_http, "_scope_quota", {key: _SlowBucket()})
        barrier = threading.Barrier(callers)
        admitted = []

        def call(barrier=barrier, admitted=admitted):
            barrier.wait()
            if mcp_http._within_scope_quota(jti="jti-race", scope="write:orders"):
                admitted.append(1)

        threads = [threading.Thread(target=call) for _ in range(callers)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10)
        assert len(admitted) == 5


def test_the_quota_registry_forgets_tokens_that_went_quiet(monkeypatch):
    clock = [1_000_000.0]
    monkeypatch.setattr(mcp_http.time, "time", lambda: clock[0])
    for n in range(1000):
        assert mcp_http._within_scope_quota(jti=f"old-{n}", scope="read:market")
    assert len(mcp_http._scope_quota) == 1000

    # Past every window and the sweep interval, one new call sweeps the rest.
    clock[0] += mcp_http._QUOTA_SWEEP_SECONDS + mcp_http._longest_quota_window() + 1
    assert mcp_http._within_scope_quota(jti="new", scope="read:market")
    assert list(mcp_http._scope_quota) == ["new|read:market"]


def test_a_live_token_keeps_its_count_across_a_sweep(monkeypatch):
    clock = [2_000_000.0]
    monkeypatch.setattr(mcp_http.time, "time", lambda: clock[0])
    monkeypatch.setattr(mcp_http, "_RATE_LIMIT_WRITE", "2 per minute")
    assert mcp_http._within_scope_quota(jti="live", scope="write:orders")
    clock[0] += mcp_http._QUOTA_SWEEP_SECONDS  # sweep due, but the hit is not stale
    monkeypatch.setattr(mcp_http, "_RATE_LIMIT_WRITE", "2 per hour")
    assert mcp_http._within_scope_quota(jti="live", scope="write:orders")
    assert not mcp_http._within_scope_quota(jti="live", scope="write:orders")
