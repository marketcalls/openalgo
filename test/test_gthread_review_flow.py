"""Flow findings from the gthread review (strategy-02).

Under gthread any workflow with a Delay or Wait Until node, even a 1-second
Delay, took one of only four background slots. A fifth trigger at the same
candle close was refused with 429 before an execution record existed, so a
TradingView or Chartink signal was lost with no trace in OpenAlgo, and four
Wait Until square-offs waiting half an hour held every slot from the short
delays.

Now a workflow whose waits add up to a few seconds runs on its request as it
does everywhere else, longer Delay workflows share sixteen slots, Wait Until
workflows have four of their own, and a refused trigger is written to the
workflow's execution history.
"""

from __future__ import annotations

import threading
from datetime import datetime
from types import SimpleNamespace

import pytest
from flask import Flask
from test_gthread_strategy_flow_waits import _trigger, _wait_until, _workflow

import blueprints.flow as flow
import database.flow_db as flow_db
import services.flow_executor_service as fes
import utils.runtime as runtime


def _delay(seconds, unit="seconds"):
    return [
        {"id": "t", "type": "webhookTrigger", "data": {}},
        {"id": "d", "type": "delay", "data": {"delayValue": seconds, "delayUnit": unit}},
    ]


def _wait_until_node(target):
    return [
        {"id": "t", "type": "webhookTrigger", "data": {}},
        {"id": "w", "type": "waitUntil", "data": {"targetTime": target}},
    ]


@pytest.fixture
def app():
    return Flask(__name__)


@pytest.fixture
def workflows(monkeypatch):
    registry = {}
    monkeypatch.setattr(flow_db, "get_workflow_by_webhook_token", lambda token: registry[token])
    monkeypatch.setattr(flow_db, "get_workflow_api_key", lambda workflow: "k")
    monkeypatch.setattr(flow, "_execution_blocked", lambda workflow: None)
    return registry


@pytest.fixture
def runs(monkeypatch):
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


@pytest.fixture
def fresh_pools(monkeypatch):
    """Slots of the configured sizes, independent of any other test's runs."""
    monkeypatch.setattr(fes, "_waiting_slots", threading.BoundedSemaphore(fes.FLOW_WAITING_WORKERS))
    monkeypatch.setattr(
        fes, "_wait_until_slots", threading.BoundedSemaphore(fes.FLOW_WAIT_UNTIL_WORKERS)
    )


def test_the_wait_is_read_from_the_graph_as_the_nodes_would_sleep():
    now = datetime(2026, 9, 23, 14, 45, 0)
    assert fes.workflow_wait_seconds(_delay(2), now) == (2.0, 0.0)
    assert fes.workflow_wait_seconds(_delay(2, "minutes"), now) == (120.0, 0.0)
    # Capped as the node caps it.
    assert (
        fes.workflow_wait_seconds(_delay(2, "hours"), now)[0] == fes.NodeExecutor.DELAY_MAX_SECONDS
    )
    assert fes.workflow_wait_seconds([{"type": "delay", "data": {"delayMs": 1500}}], now) == (
        1.5,
        0.0,
    )
    # Unreadable counts as long, never as short.
    assert (
        fes.workflow_wait_seconds([{"type": "delay", "data": {"delayValue": "soon"}}], now)[0]
        == fes.NodeExecutor.DELAY_MAX_SECONDS
    )
    # Two delays add up.
    both = _delay(4) + [{"id": "d2", "type": "delay", "data": {"delayValue": 8}}]
    assert fes.workflow_wait_seconds(both, now) == (12.0, 0.0)
    # Wait Until: the distance from now, nothing once passed, capped at the node's limit.
    assert fes.workflow_wait_seconds(_wait_until_node("14:45:05"), now) == (0.0, 5.0)
    assert fes.workflow_wait_seconds(_wait_until_node("15:15"), now) == (0.0, 1800.0)
    assert fes.workflow_wait_seconds(_wait_until_node("09:30"), now) == (0.0, 0.0)
    assert fes.workflow_wait_seconds(_wait_until_node("23:00"), now)[1] == (
        fes.NodeExecutor.WAIT_UNTIL_MAX_SECONDS
    )


def test_under_gthread_a_short_delay_runs_on_its_request(app, workflows, runs, gthread):
    """A two-second Delay no longer takes a background slot or answers 202."""
    workflows["short"] = _workflow(601, _delay(2))
    runs.release.set()

    body, code = _trigger(app, "short")

    assert code == 200, body
    assert body["status"] == "success"
    assert runs.started[0][1] == threading.get_ident(), "a short wait left its request"


def test_under_gthread_six_delay_workflows_on_one_candle_all_start(
    app, workflows, runs, gthread, fresh_pools
):
    """The finding's burst: six workflows with a Delay over the inline limit."""
    for n in range(6):
        workflows[f"sym{n}"] = _workflow(700 + n, _delay(60))

    answers = [_trigger(app, f"sym{n}") for n in range(6)]

    assert [code for _, code in answers] == [202] * 6, answers
    assert _wait_until(lambda: len(runs.started) == 6)
    runs.release.set()
    assert _wait_until(lambda: sorted(runs.finished) == [700 + n for n in range(6)])
    assert _wait_until(lambda: fes._waiting_slots._value == fes.FLOW_WAITING_WORKERS)


def test_under_gthread_wait_until_workflows_cannot_starve_the_delays(
    app, workflows, runs, gthread, fresh_pools, monkeypatch
):
    """Every Wait Until slot taken: a Delay workflow still starts, the next
    Wait Until workflow is refused, and the refusal is in its history."""
    monkeypatch.setattr(fes, "_wait_until_node_seconds", lambda data, now: 1800.0)
    refused = []
    monkeypatch.setattr(fes, "_record_refused_run", refused.append)
    for n in range(fes.FLOW_WAIT_UNTIL_WORKERS + 1):
        workflows[f"sq{n}"] = _workflow(800 + n, _wait_until_node("15:15"))
    workflows["delay"] = _workflow(900, _delay(60))

    square_offs = [_trigger(app, f"sq{n}") for n in range(fes.FLOW_WAIT_UNTIL_WORKERS)]
    extra, extra_code = _trigger(app, f"sq{fes.FLOW_WAIT_UNTIL_WORKERS}")
    delay, delay_code = _trigger(app, "delay")

    assert [code for _, code in square_offs] == [202] * fes.FLOW_WAIT_UNTIL_WORKERS
    assert extra_code == 429 and extra["message"] == fes.FLOW_WAITING_BUSY_MESSAGE
    assert refused == [800 + fes.FLOW_WAIT_UNTIL_WORKERS]
    assert delay_code == 202, delay
    assert _wait_until(lambda: 900 in [workflow_id for workflow_id, _ in runs.started])
    runs.release.set()
    assert _wait_until(lambda: fes._wait_until_slots._value == fes.FLOW_WAIT_UNTIL_WORKERS)


def test_a_refused_trigger_is_written_to_the_execution_history(monkeypatch):
    created = []
    updated = []

    monkeypatch.setattr(
        fes,
        "create_execution",
        lambda workflow_id, status="pending": (
            created.append((workflow_id, status)) or SimpleNamespace(id=77)
        ),
    )
    monkeypatch.setattr(
        fes,
        "update_execution_status",
        lambda execution_id, status, error=None, logs=None: updated.append(
            (execution_id, status, error, logs)
        ),
    )
    monkeypatch.setattr(fes, "_waiting_slots", threading.BoundedSemaphore(1))
    assert fes._waiting_slots.acquire(blocking=False)

    result = fes.start_workflow_in_background(1001, api_key="k", nodes=_delay(60))

    assert result["busy"] is True and result["message"] == fes.FLOW_WAITING_BUSY_MESSAGE
    assert created == [(1001, "running")]
    assert updated[0][:3] == (77, "failed", fes.FLOW_WAITING_REFUSED_RECORD)
    assert not fes.get_workflow_lock(1001).locked()


def test_without_gthread_every_waiting_workflow_still_runs_on_its_request(
    app, workflows, runs, monkeypatch
):
    monkeypatch.setattr(runtime, "gthread_active", lambda: False)
    workflows["long"] = _workflow(1101, _wait_until_node("15:15"))
    runs.release.set()

    body, code = _trigger(app, "long")

    assert code == 200, body
    assert runs.started[0][1] == threading.get_ident()
