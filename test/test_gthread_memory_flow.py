"""Flow release failures must leave enough ownership to retry safely."""

from types import SimpleNamespace

import pytest
from flask import Flask


@pytest.fixture(autouse=True)
def isolated_flow_subscription_registry(monkeypatch):
    from services import flow_executor_service as flow

    monkeypatch.setattr(flow, "_workflow_subscriptions", {})
    monkeypatch.setattr(flow, "_workflow_subscription_versions", {})
    monkeypatch.setattr(flow, "_workflow_subscription_owners", {})


def test_failed_flow_unsubscribe_keeps_each_owner_until_retry(monkeypatch):
    from services import flow_executor_service as flow
    from services import websocket_service

    monkeypatch.setattr(flow, "_subscription_owner", lambda _id: ("trader", "broker"))
    available = {"value": False}
    calls = []

    def unsubscribe(_username, _broker, symbols, _mode):
        calls.append(symbols[0]["symbol"])
        return available["value"], {}, 200 if available["value"] else 503

    monkeypatch.setattr(websocket_service, "unsubscribe_from_symbols", unsubscribe)
    for workflow_id in range(100_000, 100_100):
        flow.record_workflow_subscription(workflow_id, f"SYM{workflow_id}", "NSE", "LTP")
        assert flow.release_workflow_subscriptions(workflow_id) == 0
        assert flow._workflow_subscriptions[workflow_id] == {(f"SYM{workflow_id}", "NSE", "LTP")}
        available["value"] = True
        assert flow.release_workflow_subscriptions(workflow_id) == 1
        assert workflow_id not in flow._workflow_subscriptions
        available["value"] = False

    assert len(calls) == 200
    assert not any(100_000 <= key < 100_100 for key in flow._workflow_subscriptions)
    assert not any(100_000 <= key < 100_100 for key in flow._workflow_subscription_versions)
    assert not any(100_000 <= key < 100_100 for key in flow._workflow_subscription_owners)


def test_partial_release_keeps_only_failed_entries_and_captured_owner(monkeypatch):
    from services import flow_executor_service as flow
    from services import websocket_service

    workflow_id = 100_150
    monkeypatch.setattr(flow, "_subscription_owner", lambda _id: (None, "unknown"))
    failed = {"FAIL"}
    owners = []

    def unsubscribe(username, broker, symbols, _mode):
        symbol = symbols[0]["symbol"]
        owners.append((username, broker))
        return symbol not in failed, {}, 200 if symbol not in failed else 503

    monkeypatch.setattr(websocket_service, "unsubscribe_from_symbols", unsubscribe)
    flow.record_workflow_subscription(workflow_id, "PASS", "NSE", "LTP", "trader", "broker")
    flow.record_workflow_subscription(workflow_id, "FAIL", "NSE", "LTP", "trader", "broker")

    assert flow.release_workflow_subscriptions(workflow_id) == 1
    assert flow._workflow_subscriptions[workflow_id] == {("FAIL", "NSE", "LTP")}
    failed.clear()
    assert flow.release_workflow_subscriptions(workflow_id) == 1
    assert workflow_id not in flow._workflow_subscriptions
    assert workflow_id not in flow._workflow_subscription_owners
    assert owners == [("trader", "broker"), ("trader", "broker"), ("trader", "broker")]


def test_release_does_not_forget_a_new_subscription_with_the_same_key(monkeypatch):
    from services import flow_executor_service as flow
    from services import websocket_service

    workflow_id = 100_151
    calls = []

    def unsubscribe(*_args):
        calls.append(1)
        if len(calls) == 1:
            flow.record_workflow_subscription(workflow_id, "SYM", "NSE", "LTP", "trader", "broker")
        return True, {}, 200

    monkeypatch.setattr(websocket_service, "unsubscribe_from_symbols", unsubscribe)
    flow.record_workflow_subscription(workflow_id, "SYM", "NSE", "LTP", "trader", "broker")

    assert flow.release_workflow_subscriptions(workflow_id) == 1
    assert flow._workflow_subscriptions[workflow_id] == {("SYM", "NSE", "LTP")}
    assert flow.release_workflow_subscriptions(workflow_id) == 1
    assert workflow_id not in flow._workflow_subscriptions


def test_one_flow_owner_does_not_unsubscribe_another_flows_feed(monkeypatch):
    from services import flow_executor_service as flow
    from services import websocket_service

    calls = []
    monkeypatch.setattr(
        websocket_service,
        "unsubscribe_from_symbols",
        lambda *args: (calls.append(args) or True, {}, 200),
    )
    flow.record_workflow_subscription(100_160, "SYM", "NSE", "LTP", "trader", "broker")
    flow.record_workflow_subscription(100_161, "SYM", "NSE", "LTP", "trader", "broker")

    assert flow.release_workflow_subscriptions(100_160) == 1
    assert 100_160 not in flow._workflow_subscriptions
    assert 100_161 in flow._workflow_subscriptions
    assert calls == []
    assert flow.release_workflow_subscriptions(100_161) == 1
    assert len(calls) == 1


def test_delete_waits_for_subscription_release(monkeypatch):
    from blueprints import flow as routes
    from database import flow_db
    from services import flow_executor_service as flow

    workflow_id = 100_200
    workflow = SimpleNamespace(is_active=False)
    deleted = []
    monkeypatch.setattr(flow_db, "get_workflow", lambda _id: workflow)
    monkeypatch.setattr(flow_db, "delete_workflow", lambda _id: deleted.append(_id) or True)
    monkeypatch.setattr(flow, "_subscription_owner", lambda _id: ("trader", "broker"))
    monkeypatch.setattr(
        "services.websocket_service.unsubscribe_from_symbols",
        lambda *args: (False, {"message": "Feed unavailable"}, 503),
    )
    flow.record_workflow_subscription(workflow_id, "SYM", "NSE", "LTP")

    with Flask(__name__).test_request_context():
        result = routes.delete_workflow.__wrapped__(workflow_id)

    status = result[1] if isinstance(result, tuple) else result.status_code
    assert status == 503
    assert deleted == []
    assert workflow_id in flow._workflow_subscriptions


def test_deactivate_waits_for_subscription_release(monkeypatch):
    from blueprints import flow as routes
    from database import flow_db
    from services import flow_executor_service as flow
    from services import (
        flow_order_update_monitor_service,
        flow_price_monitor_service,
        flow_scheduler_service,
    )

    workflow_id = 100_201
    workflow = SimpleNamespace(is_active=True, schedule_job_id=None)
    deactivated = []
    removed = []
    monkeypatch.setattr(flow_db, "get_workflow", lambda _id: workflow)
    monkeypatch.setattr(flow_db, "deactivate_workflow", lambda _id: deactivated.append(_id) or True)
    monkeypatch.setattr(
        flow_scheduler_service, "get_flow_scheduler",
        lambda: SimpleNamespace(remove_workflow_job=lambda *_a, **_k: removed.append("schedule") or True),
    )
    monkeypatch.setattr(
        flow_price_monitor_service, "get_flow_price_monitor",
        lambda: SimpleNamespace(remove_alert=lambda _id: removed.append("price")),
    )
    monkeypatch.setattr(
        flow_order_update_monitor_service, "get_flow_order_update_monitor",
        lambda: SimpleNamespace(remove_watch=lambda _id: removed.append("order")),
    )
    monkeypatch.setattr(flow, "_subscription_owner", lambda _id: ("trader", "broker"))
    monkeypatch.setattr(
        "services.websocket_service.unsubscribe_from_symbols",
        lambda *args: (False, {"message": "Feed unavailable"}, 503),
    )
    flow.record_workflow_subscription(workflow_id, "SYM", "NSE", "LTP")

    with Flask(__name__).test_request_context():
        result = routes.deactivate_workflow.__wrapped__(workflow_id)

    status = result[1] if isinstance(result, tuple) else result.status_code
    assert status == 503
    assert deactivated == []
    assert removed == [], "a failed feed release must leave active triggers intact"
    assert workflow_id in flow._workflow_subscriptions


def test_already_inactive_deactivate_retries_held_subscription(monkeypatch):
    from blueprints import flow as routes
    from database import flow_db
    from services import flow_executor_service as flow

    workflow_id = 100_202
    monkeypatch.setattr(
        flow_db, "get_workflow", lambda _id: SimpleNamespace(is_active=False)
    )
    monkeypatch.setattr(flow, "_subscription_owner", lambda _id: ("trader", "broker"))
    available = {"value": False}
    monkeypatch.setattr(
        "services.websocket_service.unsubscribe_from_symbols",
        lambda *args: (available["value"], {}, 200 if available["value"] else 503),
    )
    flow.record_workflow_subscription(workflow_id, "SYM", "NSE", "LTP")

    with Flask(__name__).test_request_context():
        first = routes.deactivate_workflow.__wrapped__(workflow_id)
        available["value"] = True
        second = routes.deactivate_workflow.__wrapped__(workflow_id)

    assert first[1] == 503
    assert second.status_code == 200
    assert workflow_id not in flow._workflow_subscriptions


@pytest.mark.parametrize("action", ["delete", "deactivate"])
def test_cleanup_refuses_a_workflow_still_executing(monkeypatch, action):
    from blueprints import flow as routes
    from database import flow_db
    from services import flow_executor_service as flow

    workflow_id = 100_203
    changed = []
    monkeypatch.setattr(
        flow_db,
        "get_workflow",
        lambda _id: SimpleNamespace(is_active=False, schedule_job_id=None),
    )
    monkeypatch.setattr(flow_db, "delete_workflow", lambda _id: changed.append("delete") or True)
    monkeypatch.setattr(
        flow_db, "deactivate_workflow", lambda _id: changed.append("deactivate") or True
    )
    lock = flow.get_workflow_lock(workflow_id)
    assert lock.acquire(blocking=False)
    try:
        with Flask(__name__).test_request_context():
            route = routes.delete_workflow if action == "delete" else routes.deactivate_workflow
            result = route.__wrapped__(workflow_id)
    finally:
        lock.release()

    status = result[1] if isinstance(result, tuple) else result.status_code
    assert status == 409
    assert changed == []
