"""An Action Center order reaches the broker at most once.

Approving a pending order used to be a read, a status check and a write, and
executing it checked ``status == 'approved'`` and nothing else. Two approvals
racing (a double click, Approve on a phone while Approve All runs on the
desktop) could both pass and both place the live order. Under eventlet the
approval never yielded between its read and its commit; under the gthread
worker the two requests run in parallel.

Approval is now compare-and-set (``database.action_center_db``), and execution
claims the order (broker_status ``submitting``) before anything is sent. The
routes report a lost approval or a lost claim as what it is, not as an
execution failure.
"""

import threading
import time
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.pool import NullPool

import database.action_center_db as action_center_db
import database.auth_db as auth_db

# restx_api before any order service: see test_strategy_module_order_dispatch.py.
import restx_api  # noqa: F401
import services.pending_order_execution_service as execution_service

USER = "gthread-action-center-user"


@pytest.fixture(autouse=True)
def isolated_action_center_database(tmp_path, monkeypatch):
    """A temporary action center database, never db/openalgo.db."""
    test_engine = create_engine(
        f"sqlite:///{tmp_path / 'action-center.db'}",
        poolclass=NullPool,
        connect_args={"check_same_thread": False},
    )
    session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=test_engine))
    original_query = action_center_db.Base.__dict__["query"]
    monkeypatch.setattr(action_center_db, "engine", test_engine)
    monkeypatch.setattr(action_center_db, "db_session", session)
    action_center_db.Base.query = session.query_property()
    action_center_db.Base.metadata.create_all(bind=test_engine)
    try:
        yield
    finally:
        session.remove()
        action_center_db.Base.query = original_query
        test_engine.dispose()


@pytest.fixture
def broker(monkeypatch):
    """Credentials resolve, and every placed order is counted, slowly."""
    placed = []
    placed_lock = threading.Lock()

    def place_order(order_data, api_key, auth_token, broker):
        time.sleep(0.02)
        with placed_lock:
            placed.append(order_data)
            number = len(placed)
        return True, {"status": "success", "orderid": f"GT-{number}"}, 200

    import services.orderstatus_service as orderstatus_service
    import services.place_order_service as place_order_service

    monkeypatch.setattr(place_order_service, "place_order", place_order)
    monkeypatch.setattr(
        orderstatus_service,
        "get_order_status",
        lambda **kwargs: (False, {"status": "error"}, 500),
    )
    monkeypatch.setattr(execution_service, "get_api_key_for_tradingview", lambda user: "k")
    monkeypatch.setattr(execution_service, "get_auth_token", lambda user: "t")

    class AuthQuery:
        def filter_by(self, **kwargs):
            return self

        def first(self):
            return SimpleNamespace(broker="zerodha")

    monkeypatch.setattr(auth_db, "Auth", SimpleNamespace(query=AuthQuery()))
    return placed


def _pending(**overrides):
    order = {"symbol": "SBIN", "exchange": "NSE", "action": "BUY", "quantity": 1}
    order.update(overrides)
    order_id = action_center_db.create_pending_order(USER, "placeorder", order)
    assert order_id
    return order_id


def _race(count, target):
    start = threading.Barrier(count)
    results = [None] * count

    def run(index):
        try:
            start.wait()
            results[index] = target()
        finally:
            action_center_db.db_session.remove()

    threads = [threading.Thread(target=run, args=(i,)) for i in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    return results


def test_racing_executions_of_one_approved_order_send_it_once(broker):
    order_id = _pending()
    assert action_center_db.approve_pending_order(order_id, USER, USER)

    results = _race(8, lambda: execution_service.execute_approved_order(order_id))

    assert len(broker) == 1, f"one approved order was sent {len(broker)} times"
    codes = sorted(code for _ok, _body, code in results)
    assert codes == [200] + [409] * 7
    refused = [body for ok, body, code in results if code == 409]
    assert all(body["message"] == execution_service.ALREADY_SUBMITTING_MESSAGE for body in refused)
    row = action_center_db.get_pending_order_by_id(order_id)
    assert row.broker_order_id == "GT-1"
    assert row.broker_status == "open"


def test_racing_approve_and_execute_pairs_send_it_once(broker):
    """Eight callers each approve and then execute the same pending order."""
    order_id = _pending()

    def approve_then_execute():
        if not action_center_db.approve_pending_order(order_id, USER, USER):
            return "lost the approval"
        return execution_service.execute_approved_order(order_id)

    results = _race(8, approve_then_execute)

    assert len(broker) == 1
    assert sum(1 for result in results if result != "lost the approval") == 1


def test_a_claimed_order_is_marked_submitting_before_it_is_sent(broker, monkeypatch):
    """The in-flight state is visible, and an order left in it is never resent."""
    order_id = _pending()
    assert action_center_db.approve_pending_order(order_id, USER, USER)
    seen = {}

    import services.place_order_service as place_order_service

    def place_order(order_data, api_key, auth_token, broker):
        action_center_db.db_session.remove()
        seen["status"] = action_center_db.get_pending_order_by_id(order_id).broker_status
        return True, {"status": "success", "orderid": "GT-SEEN"}, 200

    monkeypatch.setattr(place_order_service, "place_order", place_order)

    ok, _body, code = execution_service.execute_approved_order(order_id)

    assert ok and code == 200
    assert seen["status"] == action_center_db.SUBMITTING

    # A crash between the claim and the broker's answer leaves "submitting".
    # A later execution must refuse it rather than send it again.
    action_center_db.update_broker_status(order_id, None, action_center_db.SUBMITTING)
    again = execution_service.execute_approved_order(order_id)
    assert again[2] == 409


def test_an_unapproved_order_is_not_claimed(broker):
    order_id = _pending()

    ok, body, code = execution_service.execute_approved_order(order_id)

    assert not ok and code == 400
    assert action_center_db.get_pending_order_by_id(order_id).broker_status is None
    assert broker == []


def test_a_failure_after_the_claim_still_writes_a_final_status(broker, monkeypatch):
    order_id = _pending()
    assert action_center_db.approve_pending_order(order_id, USER, USER)
    monkeypatch.setattr(execution_service, "get_auth_token", lambda user: None)

    ok, _body, code = execution_service.execute_approved_order(order_id)

    assert not ok and code == 403
    assert action_center_db.get_pending_order_by_id(order_id).broker_status == "rejected"


def test_an_error_after_the_claim_does_not_leave_the_order_in_flight(broker, monkeypatch):
    order_id = _pending()
    assert action_center_db.approve_pending_order(order_id, USER, USER)

    def unreachable(user):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(execution_service, "get_api_key_for_tradingview", unreachable)

    ok, _body, code = execution_service.execute_approved_order(order_id)

    assert not ok and code == 500
    assert broker == []
    assert action_center_db.get_pending_order_by_id(order_id).broker_status == "rejected"


# ---------------------------------------------------------------------------
# The routes
# ---------------------------------------------------------------------------


@pytest.fixture
def emitted(monkeypatch):
    import extensions

    events = []
    monkeypatch.setattr(extensions.socketio, "emit", lambda *a, **k: events.append((a, k)))
    return events


@pytest.fixture
def new_client(monkeypatch, broker, emitted):
    """A factory: one logged-in test client per caller, so threads share nothing."""
    from flask import Flask

    import utils.session as session_utils
    from blueprints.orders import orders_bp

    monkeypatch.setattr(session_utils, "is_session_valid", lambda: True)
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(orders_bp)

    def make():
        test_client = app.test_client()
        with test_client.session_transaction() as sess:
            sess["user"] = USER
        return test_client

    return make


@pytest.fixture
def client(new_client):
    return new_client()


def test_racing_approve_clicks_send_one_order_and_say_why_the_rest_did_not(
    new_client, broker, emitted
):
    order_id = _pending()
    url = f"/action-center/approve/{order_id}"
    clients = [new_client() for _ in range(8)]
    handed_out = iter(clients)
    hand_out_lock = threading.Lock()

    def click():
        with hand_out_lock:
            mine = next(handed_out)
        return mine.post(url)

    responses = _race(8, click)

    assert len(broker) == 1
    codes = sorted(response.status_code for response in responses)
    assert codes == [200] + [409] * 7
    for response in responses:
        if response.status_code == 409:
            body = response.get_json()
            assert "already approved or rejected" in body["message"]
    approved_events = [a for a, _k in emitted if a and a[0] == "pending_order_updated"]
    assert len(approved_events) == 1


def test_approving_an_order_that_is_already_handled_is_a_conflict(client, broker):
    order_id = _pending()
    assert action_center_db.approve_pending_order(order_id, USER, USER)

    response = client.post(f"/action-center/approve/{order_id}")

    assert response.status_code == 409
    assert response.get_json()["status"] == "error"
    assert broker == []


def test_approving_an_unknown_order_still_fails_as_before(client, broker):
    response = client.post("/action-center/approve/987654")

    assert response.status_code == 400
    assert response.get_json() == {"status": "error", "message": "Failed to approve order"}


def test_approve_all_reports_orders_another_screen_took(client, broker, monkeypatch):
    first = _pending(symbol="SBIN")
    second = _pending(symbol="INFY")
    real_approve = action_center_db.approve_pending_order

    def approve(order_id, approved_by, user_id):
        if order_id == second:
            # Another screen approves it between the listing and this approval.
            real_approve(order_id, approved_by, user_id)
            return False
        return real_approve(order_id, approved_by, user_id)

    monkeypatch.setattr(action_center_db, "approve_pending_order", approve)

    response = client.post("/action-center/approve-all")
    body = response.get_json()

    assert response.status_code == 200
    assert body["approved_count"] == 1
    assert body["executed_count"] == 1
    assert body["failed_executions"] == []
    assert body["already_handled"] == [second]
    assert body["status"] == "success"
    assert "already handled from another screen" in body["message"]
    assert len(broker) == 1
    assert first != second


def test_approve_all_without_contention_reads_as_before(client, broker):
    _pending(symbol="SBIN")
    _pending(symbol="INFY")

    response = client.post("/action-center/approve-all")
    body = response.get_json()

    assert body["status"] == "success"
    assert body["message"] == "Successfully approved and executed all 2 orders"
    assert body["already_handled"] == []
    assert len(broker) == 2
