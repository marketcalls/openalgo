"""Agent streams inside the gthread thread budget, and a single-flight ChatGPT sign-in.

Under the gthread worker every agent turn holds a pool thread for as long as it
streams, which with tool calls and a reasoning model can be minutes. So the
chat and confirm streams are counted in ``utils.stream_registry``, capped, and
given a longest turn, the last two only under gthread. The slot is returned
however the stream ends, including a client that leaves before the first byte.

The ChatGPT subscription sign-in used to claim its slot only after the device
code request came back, so a double click requested two codes and started two
poll threads; the older one could later overwrite the newer login's state.
"""

from __future__ import annotations

import inspect
import threading
import time
import types

import pytest
from flask import Flask

import blueprints.agent as agent_bp
from services.agent import chatgpt_oauth as oauth
from services.agent import stream as agent_stream
from utils import runtime, stream_registry


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setattr(runtime, "_registered", None)
    monkeypatch.setattr(runtime, "_worker_ref", None)
    monkeypatch.delenv("OPENALGO_EFFECTIVE_THREADS", raising=False)
    stream_registry._reset_for_tests()
    yield
    stream_registry._reset_for_tests()


def _as_gthread(threads: int = 64) -> None:
    cls = type("FakeWorker", (), {})
    cls.__module__ = "gunicorn.workers.gthread"
    worker = cls()
    worker.cfg = types.SimpleNamespace(
        worker_class_str="gthread", threads=threads, workers=1, graceful_timeout=30
    )
    runtime.register_gunicorn_worker(worker)


def _open_count() -> int:
    return stream_registry.snapshot().get(agent_bp.AGENT_STREAM_KIND, {"open": 0})["open"]


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setattr(agent_bp, "_persist_turn", lambda *args: None)
    flask_app = Flask(__name__)
    return flask_app


def _streaming_body(chunks):
    def body(ticket):
        return agent_bp._stream_response(
            iter(chunks), agent_bp._TurnRecorder(), 1, "trader", ticket
        )

    return body


# --- messaging-11: counting, releasing, capping ----------------------------------


def test_a_stream_is_counted_and_released_when_it_ends(app):
    with app.test_request_context("/agent/api/chat/stream", method="POST"):
        response = agent_bp._with_stream_slot(_streaming_body([": heartbeat\n\n"]))
        assert response.is_streamed
        assert _open_count() == 1
        assert b"".join(response.iter_encoded()) == b": heartbeat\n\n"
        response.close()
    assert _open_count() == 0


def test_a_client_that_leaves_before_the_first_byte_frees_the_slot(app):
    with app.test_request_context("/agent/api/chat/stream", method="POST"):
        response = agent_bp._with_stream_slot(_streaming_body(["data: {}\n\n"]))
        assert _open_count() == 1
        response.close()  # the generator never started
    assert _open_count() == 0


def test_an_error_answer_or_a_raise_gives_the_slot_back(app):
    with app.test_request_context("/agent/api/chat/stream", method="POST"):
        body, status = agent_bp._with_stream_slot(lambda ticket: agent_bp._error("bad", 400))
        assert status == 400
        assert _open_count() == 0

        def explode(ticket):
            raise RuntimeError("build failed")

        with pytest.raises(RuntimeError):
            agent_bp._with_stream_slot(explode)
        assert _open_count() == 0


def test_under_gthread_a_stream_over_the_cap_is_refused_before_any_work(app, monkeypatch):
    _as_gthread()
    held = [
        stream_registry.admit(agent_bp.AGENT_STREAM_KIND)
        for _ in range(agent_bp.MAX_CONCURRENT_STREAMS)
    ]

    def must_not_run():
        raise AssertionError("a refused turn reached the preconditions")

    monkeypatch.setattr(agent_bp, "_chat_preconditions", must_not_run)
    for view in (agent_bp.chat_stream, agent_bp.chat_confirm):
        with app.test_request_context("/agent/api/chat/stream", method="POST", json={}):
            body, status = inspect.unwrap(view)()
        assert status == 429
        assert body.get_json()["message"] == agent_bp.STREAMS_BUSY_MESSAGE
        assert "Wait for one to finish" in agent_bp.STREAMS_BUSY_MESSAGE

    for ticket in held:
        ticket.release()
    assert _open_count() == 0


def test_off_gthread_streams_are_counted_but_never_refused(app, monkeypatch):
    held = [stream_registry.admit(agent_bp.AGENT_STREAM_KIND) for _ in range(20)]
    calls = []
    monkeypatch.setattr(
        agent_bp,
        "_chat_preconditions",
        lambda: calls.append(1) or (None, None, agent_bp._error("Not authenticated", 401)),
    )
    with app.test_request_context("/agent/api/chat/stream", method="POST", json={}):
        _body, status = inspect.unwrap(agent_bp.chat_stream)()
    assert status == 401 and calls == [1]
    assert _open_count() == 20
    for ticket in held:
        ticket.release()


# --- messaging-11: the longest turn ------------------------------------------------


class _IdleAgent:
    """An agno stand-in whose run emits events nobody translates, forever."""

    def __init__(self):
        self.cancelled = []

    def cancel_run(self, run_id):
        self.cancelled.append(run_id)


def _idle_events():
    for _ in range(10_000):
        time.sleep(0.02)
        yield types.SimpleNamespace(event="NotAnAgnoEvent", run_id="run-1", session_id="s")


def test_under_gthread_a_turn_past_its_limit_ends_cleanly(monkeypatch):
    _as_gthread()
    monkeypatch.setattr(agent_stream, "MAX_TURN_SECONDS", 0.3)
    agent = _IdleAgent()
    translator = agent_stream.EventTranslator(1)
    started = time.monotonic()
    chunks = list(agent_stream._pump(agent, _idle_events, translator, label="test"))
    took = time.monotonic() - started

    frames = "".join(chunks)
    assert agent_stream.TURN_TOO_LONG_MESSAGE in frames
    assert '"type":"done","reason":"incomplete"' in frames
    assert took < agent_stream.JOIN_TIMEOUT_SECONDS
    assert agent.cancelled == ["run-1"], "the run was not cancelled"


def test_a_turn_ends_when_the_server_begins_shutting_down():
    agent = _IdleAgent()
    translator = agent_stream.EventTranslator(1)
    timer = threading.Timer(0.3, stream_registry.request_drain)
    timer.start()
    chunks = list(agent_stream._pump(agent, _idle_events, translator, label="test"))
    timer.join()
    assert agent_stream.SERVER_STOPPING_MESSAGE in "".join(chunks)


def test_off_gthread_a_turn_has_no_limit():
    assert agent_stream._ending_message(None) is None
    assert agent_stream._ending_message(time.monotonic() + 60) is None
    assert agent_stream._ending_message(time.monotonic() - 1) == agent_stream.TURN_TOO_LONG_MESSAGE


# --- messaging-12: single-flight ChatGPT sign-in -----------------------------------


class _Transport:
    """A caller-owned transport; the device-code request and poll are stubbed."""

    def post(self, url, **kwargs):  # pragma: no cover - never reached
        raise AssertionError("the stubbed login made a real request")


@pytest.fixture
def login_env(monkeypatch, tmp_path):
    """Isolate the module's one login and stub LiteLLM's provider pieces."""
    monkeypatch.setattr(oauth, "_login", oauth.LoginStatus())
    monkeypatch.setattr(oauth, "_thread", None)
    monkeypatch.setattr(oauth, "_cancel", None)
    monkeypatch.setattr(oauth, "_claim", None)
    monkeypatch.setattr(oauth, "configure_token_dir", lambda *a, **k: tmp_path)
    monkeypatch.setattr(
        oauth,
        "_authenticator",
        lambda: types.SimpleNamespace(_record_device_code_request=lambda: None),
    )
    yield
    oauth.cancel_login()


def test_concurrent_starts_request_one_device_code(login_env, monkeypatch):
    """PORTED DEFECT: a double click requested two codes and started two pollers."""
    requests = []

    def fake_request_device_code(transport, bits):
        requests.append(threading.get_ident())
        time.sleep(0.1)
        return {"device_auth_id": "dev-1", "user_code": "ABCD-EFGH", "interval": "5"}

    polls = []

    def fake_poll_worker(device, cancel, deadline, interval, transport):
        polls.append(1)
        cancel.wait(5)
        oauth._retire(cancel)

    monkeypatch.setattr(oauth, "_request_device_code", fake_request_device_code)
    monkeypatch.setattr(oauth, "_poll_worker", fake_poll_worker)
    monkeypatch.setattr(
        oauth,
        "_bits",
        lambda: types.SimpleNamespace(timeout_seconds=900, poll_seconds=5, verify_url="https://x"),
    )

    callers = 6
    barrier = threading.Barrier(callers)
    snapshots = []

    def start():
        barrier.wait()
        snapshots.append(oauth.start_login(transport=_Transport()))

    threads = [threading.Thread(target=start) for _ in range(callers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)

    assert len(requests) == 1, f"{len(requests)} device codes were requested"
    assert len(polls) == 1
    assert all(s.state == oauth.LOGIN_PENDING for s in snapshots)
    assert oauth.login_status().user_code == "ABCD-EFGH"
    assert oauth._claim is None


def test_a_replaced_worker_cannot_overwrite_the_newer_login(login_env):
    stale = threading.Event()
    live = threading.Event()
    oauth._cancel = live
    oauth._set_login(state=oauth.LOGIN_AUTHORISED, message="authorised")

    assert oauth._set_login_if_current(stale, state=oauth.LOGIN_EXPIRED, message="old") is False
    assert oauth.login_status().state == oauth.LOGIN_AUTHORISED
    assert oauth._set_login_if_current(live, state=oauth.LOGIN_FAILED, message="new") is True
    assert oauth.login_status().state == oauth.LOGIN_FAILED
    oauth._cancel = None


def test_a_failed_code_request_releases_the_claim(login_env, monkeypatch):
    def refuse(transport, bits):
        raise oauth.ChatGptOAuthError("ChatGPT did not issue a sign-in code. Try again.")

    monkeypatch.setattr(oauth, "_request_device_code", refuse)
    monkeypatch.setattr(
        oauth,
        "_bits",
        lambda: types.SimpleNamespace(timeout_seconds=900, poll_seconds=5, verify_url="https://x"),
    )
    with pytest.raises(oauth.ChatGptOAuthError):
        oauth.start_login(transport=_Transport())
    assert oauth._claim is None
    assert oauth.login_status().state == oauth.LOGIN_FAILED
