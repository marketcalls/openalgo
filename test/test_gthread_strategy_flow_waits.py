"""A Flow workflow that waits does not hold a gthread request thread.

A webhook or Run Now executes the workflow on the request that triggered it,
and a Delay node sleeps up to five minutes, a Wait Until node up to thirty.
Under eventlet a sleeping greenlet costs nothing. Under the gthread worker it
holds one of a fixed number of request threads for the whole wait, and a few
waiting workflows starve every other request, order routes included.

So under gthread, and only there, a workflow that can wait longer than a few
seconds is started on a shared pool and the trigger is answered at once with
202; when every waiting slot is taken it is answered 429, nothing starts, and
the refusal is written to the workflow's history. A workflow with no wait or a
short one, and every workflow under eventlet or the development server, runs on
its request exactly as before, so TradingView still gets the broker's answer.
"""

import threading
import time
from types import SimpleNamespace

import pytest
from flask import Flask

import blueprints.flow as flow
import database.flow_db as flow_db
import services.flow_executor_service as fes
import utils.runtime as runtime

WAITING_NODES = [
    {"id": "t", "type": "webhookTrigger", "data": {}},
    {"id": "d", "type": "delay", "data": {"delayValue": 60}},
]
PLAIN_NODES = [{"id": "t", "type": "webhookTrigger", "data": {}}]


def _workflow(workflow_id, nodes):
    return SimpleNamespace(
        id=workflow_id,
        name=f"wf-{workflow_id}",
        nodes=nodes,
        edges=[],
        webhook_enabled=True,
        is_active=True,
        webhook_secret=None,
        webhook_auth_type="payload",
    )


@pytest.fixture
def app():
    return Flask(__name__)


@pytest.fixture
def workflows(monkeypatch):
    """Workflows by token, with the database and validation stubbed out."""
    registry = {}
    monkeypatch.setattr(flow_db, "get_workflow_by_webhook_token", lambda token: registry[token])
    monkeypatch.setattr(flow_db, "get_workflow_api_key", lambda workflow: "k")
    monkeypatch.setattr(flow, "_execution_blocked", lambda workflow: None)
    return registry


@pytest.fixture
def runs(monkeypatch):
    """The workflow body, held until released, with every call recorded."""
    record = SimpleNamespace(started=[], finished=[], release=threading.Event())

    def body(workflow_id, webhook_data=None, api_key=None):
        record.started.append((workflow_id, threading.get_ident()))
        record.release.wait(10)
        record.finished.append(workflow_id)
        return {"status": "success", "message": "Workflow executed successfully"}

    monkeypatch.setattr(fes, "_execute_workflow_locked", body)
    yield record
    record.release.set()


@pytest.fixture
def gthread(monkeypatch):
    monkeypatch.setattr(runtime, "gthread_active", lambda: True)


def _trigger(app, token, data=None):
    with app.test_request_context("/", method="POST"):
        response, code = flow._execute_webhook(token, dict(data or {}))
        return response.get_json(), code


def _wait_until(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def test_the_waiting_node_types_are_recognised():
    assert fes.workflow_waits(WAITING_NODES)
    assert fes.workflow_waits([{"type": "waitUntil"}])
    assert not fes.workflow_waits(PLAIN_NODES)
    assert not fes.workflow_waits(None)


def test_under_gthread_a_waiting_workflow_is_answered_at_once(app, workflows, runs, gthread):
    workflows["tok"] = _workflow(101, WAITING_NODES)

    began = time.monotonic()
    body, code = _trigger(app, "tok")
    elapsed = time.monotonic() - began

    assert code == 202, body
    assert body["status"] == "accepted"
    assert "background" in body["message"]
    assert elapsed < 1.0
    assert _wait_until(lambda: runs.started)
    assert runs.started[0][1] != threading.get_ident(), "it ran on the request thread"

    # A second trigger while it waits is refused as already running, at once.
    again, again_code = _trigger(app, "tok")
    assert again_code == 409 and "already running" in again["message"].lower()

    runs.release.set()
    assert _wait_until(lambda: runs.finished == [101])
    # The lock and the slot were given back.
    assert _wait_until(lambda: not fes.get_workflow_lock(101).locked())
    assert _wait_until(lambda: fes._waiting_slots._value == fes.FLOW_WAITING_WORKERS)


def test_under_gthread_a_full_pool_refuses_rather_than_queues(
    app, workflows, runs, gthread, monkeypatch
):
    monkeypatch.setattr(fes, "_waiting_slots", threading.BoundedSemaphore(1))
    refused = []
    monkeypatch.setattr(fes, "_record_refused_run", refused.append)
    workflows["one"] = _workflow(201, WAITING_NODES)
    workflows["two"] = _workflow(202, WAITING_NODES)

    first, first_code = _trigger(app, "one")
    second, second_code = _trigger(app, "two")

    assert first_code == 202, first
    assert second_code == 429, second
    assert second["message"] == fes.FLOW_WAITING_BUSY_MESSAGE
    assert _wait_until(lambda: len(runs.started) == 1)
    assert [workflow_id for workflow_id, _ in runs.started] == [201]
    # The refused workflow's lock was not left taken, and its history says so.
    assert not fes.get_workflow_lock(202).locked()
    assert refused == [202]


def test_under_gthread_a_workflow_without_a_wait_still_answers_with_its_result(
    app, workflows, runs, gthread
):
    workflows["plain"] = _workflow(301, PLAIN_NODES)
    runs.release.set()

    body, code = _trigger(app, "plain")

    assert code == 200, body
    assert body["status"] == "success"
    assert runs.started[0][1] == threading.get_ident(), "a plain workflow left its request"


def test_without_gthread_a_waiting_workflow_runs_on_its_request_as_before(
    app, workflows, runs, monkeypatch
):
    monkeypatch.setattr(runtime, "gthread_active", lambda: False)
    workflows["tok"] = _workflow(401, WAITING_NODES)
    runs.release.set()

    body, code = _trigger(app, "tok")

    assert code == 200, body
    assert body["status"] == "success"
    assert body["message"] == "Workflow 'wf-401' triggered"
    assert runs.started[0][1] == threading.get_ident()


def test_run_now_takes_the_same_path(monkeypatch, runs, gthread):
    import utils.session as session_utils

    monkeypatch.setattr(session_utils, "is_session_valid", lambda: True)
    monkeypatch.setattr(flow_db, "get_workflow", lambda workflow_id: _workflow(501, WAITING_NODES))
    monkeypatch.setattr(flow, "get_current_api_key", lambda: "k")
    monkeypatch.setattr(flow, "_execution_blocked", lambda workflow: None)
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(flow.flow_bp)
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user"] = "u"

    response = client.post("/flow/api/workflows/501/execute")

    assert response.status_code == 202, response.get_json()
    runs.release.set()
    assert _wait_until(lambda: runs.finished == [501])
