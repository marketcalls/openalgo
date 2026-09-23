"""Action Center findings from the gthread review (strategy-03, -05 and -06).

strategy-03. A smart order whose position already matched returns success
with no order id, and the execution claim ("submitting") was never replaced,
so the row read as a send that never finished.

strategy-05. A claim that failed on a database error returned False, which the
service reads as "another request is already sending it", so the trader was
told the order was on its way while nothing was sent, and it could never be
approved again.

strategy-06. Under gthread an order the broker pacer refused before sending
was recorded as rejected, so the trader could not approve it again although
the refusal's own sentence says to try again in a few seconds.
"""

import threading
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
from utils.broker_backpressure import BrokerBusyError

USER = "gthread-review-action-center-user"


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
    """Credentials resolve; each service call is answered by ``broker.answer``."""
    sent = []
    state = SimpleNamespace(sent=sent, answer=None)

    def default_answer(kind, data):
        sent.append((kind, data))
        return True, {"status": "success", "orderid": f"GT-{len(sent)}"}, 200

    state.answer = default_answer

    import services.orderstatus_service as orderstatus_service
    import services.place_order_service as place_order_service
    import services.place_smart_order_service as place_smart_order_service

    monkeypatch.setattr(
        place_order_service,
        "place_order",
        lambda order_data, api_key, auth_token, broker: state.answer("placeorder", order_data),
    )
    monkeypatch.setattr(
        place_smart_order_service,
        "place_smart_order",
        lambda order_data, api_key, auth_token, broker: state.answer("smartorder", order_data),
    )
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
    return state


def _approved(api_type="placeorder"):
    order_id = action_center_db.create_pending_order(
        USER, api_type, {"symbol": "SBIN", "exchange": "NSE", "action": "BUY", "quantity": 1}
    )
    assert order_id and action_center_db.approve_pending_order(order_id, USER, USER)
    return order_id


def _row(order_id):
    action_center_db.db_session.remove()
    return action_center_db.get_pending_order_by_id(order_id)


# ---------------------------------------------------------------------------
# strategy-03
# ---------------------------------------------------------------------------


def test_a_smart_order_that_needed_no_action_gets_a_final_status(broker):
    def matched(kind, data):
        return (
            True,
            {"status": "success", "message": "Positions Already Matched. No Action needed."},
            200,
        )

    broker.answer = matched
    order_id = _approved("smartorder")

    ok, _body, code = execution_service.execute_approved_order(order_id)

    assert ok and code == 200
    row = _row(order_id)
    assert row.status == "approved"
    assert row.broker_status == action_center_db.NO_ACTION
    assert row.broker_status != action_center_db.SUBMITTING


def test_no_answer_leaves_an_order_submitting(broker, monkeypatch):
    """Every way execute_approved_order returns replaces the claim."""
    answers = {
        "success with id": lambda k, d: (True, {"status": "success", "orderid": "1"}, 200),
        "success without id": lambda k, d: (True, {"status": "success"}, 200),
        "rejected": lambda k, d: (False, {"status": "error", "message": "no"}, 400),
        "throttled": lambda k, d: (False, {"status": "error", "message": "slow"}, 429),
    }

    def raises(kind, data):
        raise RuntimeError("boom")

    answers["raises"] = raises
    for name, answer in answers.items():
        broker.answer = answer
        order_id = _approved()
        execution_service.execute_approved_order(order_id)
        row = _row(order_id)
        assert row.broker_status != action_center_db.SUBMITTING, name


# ---------------------------------------------------------------------------
# strategy-05
# ---------------------------------------------------------------------------


def test_a_claim_that_cannot_be_written_is_not_reported_as_already_sending(broker, monkeypatch):
    order_id = _approved()

    def broken(_order_id):
        raise RuntimeError("database or disk is full")

    real_query = action_center_db.PendingOrder.query

    class FailingOnUpdate:
        """The claim's UPDATE fails; everything else reaches the database."""

        def __getattr__(self, name):
            return getattr(real_query, name)

        def filter(self, *args, **kwargs):
            return SimpleNamespace(update=lambda *a, **k: broken(order_id))

    with monkeypatch.context() as patch:
        patch.setattr(action_center_db.PendingOrder, "query", FailingOnUpdate())
        ok, body, code = execution_service.execute_approved_order(order_id)

    assert not ok and code == 500
    assert body["message"] != execution_service.ALREADY_SUBMITTING_MESSAGE
    assert "not sent" in body["message"]
    assert broker.sent == []


def test_a_failed_claim_puts_the_order_back_for_approval(broker, monkeypatch):
    order_id = _approved()
    with monkeypatch.context() as patch:
        patch.setattr(
            execution_service, "claim_pending_order_for_execution", lambda _order_id: None
        )
        ok, body, code = execution_service.execute_approved_order(order_id)

    assert not ok and code == 500
    assert body["message"] == execution_service.CLAIM_FAILED_MESSAGE
    assert _row(order_id).status == "pending"
    assert broker.sent == []
    # It can be approved and sent again.
    assert action_center_db.approve_pending_order(order_id, USER, USER)
    ok, _body, _code = execution_service.execute_approved_order(order_id)
    assert ok and len(broker.sent) == 1


# ---------------------------------------------------------------------------
# strategy-06
# ---------------------------------------------------------------------------


def _refused(kind, data):
    error = BrokerBusyError()  # the pacer's refusal, made before any HTTP call
    return False, {"status": "error", "message": str(error)}, 429


def test_an_order_the_pacer_refused_can_be_approved_again(broker):
    broker.answer = _refused
    order_id = _approved()

    ok, body, code = execution_service.execute_approved_order(order_id)

    assert not ok and code == 429
    assert body["message"] == execution_service.REFUSED_BACK_TO_PENDING_MESSAGE
    row = _row(order_id)
    assert row.status == "pending" and row.broker_status is None

    broker.answer = lambda kind, data: (True, {"status": "success", "orderid": "X9"}, 200)
    assert action_center_db.approve_pending_order(order_id, USER, USER)
    ok, _body, _code = execution_service.execute_approved_order(order_id)
    assert ok and _row(order_id).broker_order_id == "X9"


def test_a_broker_throttle_that_may_have_been_sent_stays_rejected(broker):
    """A 429 with no refusal behind it proves nothing about the order."""
    broker.answer = lambda kind, data: (
        False,
        {"status": "error", "message": "Check the order book before sending it again."},
        429,
    )
    order_id = _approved()

    execution_service.execute_approved_order(order_id)

    row = _row(order_id)
    assert row.status == "approved" and row.broker_status == "rejected"


def test_a_refused_basket_is_not_offered_back(broker, monkeypatch):
    """A batch may have sent some legs before one was refused."""
    import services.basket_order_service as basket

    monkeypatch.setattr(
        basket,
        "place_basket_order",
        lambda basket_data, api_key, auth_token, broker: _refused("basket", basket_data),
    )
    order_id = _approved("basketorder")

    execution_service.execute_approved_order(order_id)

    assert _row(order_id).status == "approved"


def test_the_refusal_record_is_per_thread():
    from utils.broker_backpressure import RefusalRecorder

    recorder = RefusalRecorder().start()
    try:
        worker = threading.Thread(target=BrokerBusyError)
        worker.start()
        worker.join(5)
        assert not recorder.refused
        BrokerBusyError()
        assert recorder.refused
    finally:
        recorder.stop()


def test_the_route_says_the_order_is_back_and_refreshes_the_page(broker, monkeypatch):
    from flask import Flask

    import extensions
    import utils.session as session_utils
    from blueprints.orders import orders_bp

    events = []
    monkeypatch.setattr(extensions.socketio, "emit", lambda *a, **k: events.append(a))
    monkeypatch.setattr(session_utils, "is_session_valid", lambda: True)
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(orders_bp)
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user"] = USER

    broker.answer = _refused
    order_id = action_center_db.create_pending_order(
        USER, "placeorder", {"symbol": "SBIN", "exchange": "NSE", "action": "BUY", "quantity": 1}
    )

    response = client.post(f"/action-center/approve/{order_id}")

    assert response.status_code == 429
    assert response.get_json() == {
        "status": "error",
        "message": execution_service.REFUSED_BACK_TO_PENDING_MESSAGE,
    }
    assert [a[0] for a in events] == ["pending_order_updated"]
    assert _row(order_id).status == "pending"
