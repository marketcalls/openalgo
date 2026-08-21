"""Regression tests for the 2026-08-21 Flow production QA audit findings.

Each test pins one defect that was confirmed against the source and fixed. They
run without a broker, market data, or a live scheduler: the collaborators are
stubbed at the seams the executor already imports through.
"""

import threading
import time
import types

import pytest

import services.flow_executor_service as fes
import services.flow_price_monitor_service as fpm

# ---------------------------------------------------------------------------
# FLOW-001 / FLOW-009: a queued trigger run must survive, and claim by identity
# ---------------------------------------------------------------------------


@pytest.fixture
def price_monitor(monkeypatch):
    """A price monitor with its broker, executor and DB calls stubbed out."""
    monitor = fpm.get_flow_price_monitor()
    monitor._alerts.clear()

    fired: list[int] = []
    deactivated: list[int] = []
    done = threading.Event()

    fake_executor = types.ModuleType("services.flow_executor_service")

    def execute_workflow(workflow_id, webhook_data=None, api_key=None):
        fired.append(workflow_id)
        done.set()
        return {"status": "success"}

    fake_executor.execute_workflow = execute_workflow
    monkeypatch.setitem(__import__("sys").modules, "services.flow_executor_service", fake_executor)

    fake_db = types.ModuleType("database.flow_db")
    fake_db.deactivate_workflow = lambda wid: deactivated.append(wid)
    fake_db.get_workflow = lambda wid: types.SimpleNamespace(is_active=True)
    monkeypatch.setitem(__import__("sys").modules, "database.flow_db", fake_db)

    class FakeClient:
        def get_quotes(self, symbol, exchange):
            return {"status": "success", "data": {"ltp": 200.0}}

    monkeypatch.setattr(fpm, "get_flow_client", lambda api_key: FakeClient())
    monkeypatch.setattr(monitor, "_start_monitoring", lambda: None)
    monkeypatch.setattr(monitor, "_stop_monitoring", lambda: None)

    # Warm the pool. The very first submit in a process starts a worker thread,
    # which yields the GIL and hides the defect this test exists to catch.
    warm = threading.Event()
    fpm._WORKFLOW_POOL.submit(warm.set)
    assert warm.wait(5)

    yield types.SimpleNamespace(monitor=monitor, fired=fired, deactivated=deactivated, done=done)
    monitor._alerts.clear()


def _arm(monitor, workflow_id, trigger="once"):
    monitor.add_alert(
        workflow_id=workflow_id,
        symbol="SBIN",
        exchange="NSE",
        condition="above",
        target_price=100.0,
        api_key="k",
        trigger=trigger,
    )
    return monitor.get_alert(workflow_id)


@pytest.mark.parametrize("attempt", range(5))
def test_one_shot_price_alert_actually_executes(price_monitor, attempt):
    """FLOW-001: the alert was deleted before its own worker could claim it.

    The monitor thread removed a one-shot alert immediately after submitting the
    run, and the worker then dropped the run as "no longer registered". Because
    submit() usually keeps the GIL, this was the normal path rather than a race.
    """
    workflow_id = 4100 + attempt
    alert = _arm(price_monitor.monitor, workflow_id)

    price_monitor.monitor._check_alert(alert)

    assert price_monitor.done.wait(5), "the queued run never executed"
    assert price_monitor.fired == [workflow_id]


def test_one_shot_price_alert_retires_and_deactivates(price_monitor):
    """A consumed one-shot must drop its watch and clear is_active.

    Leaving is_active set made the UI report the workflow as armed, made the
    activate endpoint refuse it as already_active, and would have let startup
    restoration re-arm a spent alert and re-fire its order.
    """
    alert = _arm(price_monitor.monitor, 4200)

    price_monitor.monitor._check_alert(alert)
    assert price_monitor.done.wait(5)
    time.sleep(0.05)

    assert price_monitor.monitor.get_alert(4200) is None
    assert price_monitor.deactivated == [4200]


def test_every_time_price_alert_stays_armed(price_monitor):
    """A standing watch must not be retired or deactivated when it fires."""
    alert = _arm(price_monitor.monitor, 4300, trigger="every_time")

    price_monitor.monitor._check_alert(alert)
    assert price_monitor.done.wait(5)
    time.sleep(0.05)

    assert price_monitor.monitor.get_alert(4300) is not None
    assert price_monitor.deactivated == []


def test_superseded_price_alert_run_is_dropped(price_monitor, monkeypatch):
    """FLOW-009's third failure mode: removal by id clobbered a newer watch.

    A run queued before a deactivate/reactivate cycle must neither execute nor
    delete the registration that replaced its own.
    """
    held: list = []
    monkeypatch.setattr(fpm._WORKFLOW_POOL, "submit", lambda fn: held.append(fn))

    old = _arm(price_monitor.monitor, 4400)
    price_monitor.monitor._check_alert(old)

    price_monitor.monitor.remove_alert(4400)
    new = _arm(price_monitor.monitor, 4400)

    held[0]()

    assert price_monitor.fired == [], "a superseded run executed"
    assert price_monitor.monitor.get_alert(4400) is new, "the new alert was clobbered"


# ---------------------------------------------------------------------------
# FLOW-006 / FLOW-008: one run at a time, and an honest verdict
# ---------------------------------------------------------------------------

_NODES = [
    {"id": "n1", "type": "start", "data": {}},
    {
        "id": "n2",
        "type": "placeOrder",
        "data": {
            "symbol": "SBIN",
            "exchange": "NSE",
            "action": "BUY",
            "quantity": 1,
            "product": "MIS",
            "priceType": "MARKET",
        },
    },
    {"id": "n3", "type": "log", "data": {"message": "hedge placed"}},
]
_EDGES = [
    {"id": "e1", "source": "n1", "target": "n2"},
    {"id": "e2", "source": "n2", "target": "n3"},
]


@pytest.fixture
def executor_env(monkeypatch):
    """execute_workflow with its persistence and validation stubbed."""
    statuses: list[tuple] = []

    workflow = types.SimpleNamespace(id=1, name="t", nodes=_NODES, edges=_EDGES, is_active=True)
    monkeypatch.setattr(fes, "get_workflow", lambda wid: workflow)
    monkeypatch.setattr(fes, "create_execution", lambda *a, **k: types.SimpleNamespace(id=99))
    monkeypatch.setattr(
        fes,
        "update_execution_status",
        lambda eid, status, **kw: statuses.append((status, kw.get("error"))),
    )

    import services.flow_workflow_validator as validator

    monkeypatch.setattr(validator, "validate_workflow", lambda *a, **k: [])

    return types.SimpleNamespace(statuses=statuses)


class _Client:
    def __init__(self, order_result):
        self._order_result = order_result

    def place_order(self, **kwargs):
        return self._order_result


def test_broker_rejection_stops_the_branch_and_fails_the_run(executor_env, monkeypatch):
    """FLOW-008: a rejected order used to let the rest of the graph run.

    Traversal descended into children regardless of a handler's error status,
    and the run was recorded completed, so a rejected entry leg still placed the
    hedge, fired the "trade placed" alert, and answered HTTP 200 success.
    """
    monkeypatch.setattr(
        fes,
        "get_flow_client",
        lambda api_key: _Client({"status": "error", "message": "insufficient margin"}),
    )

    result = fes.execute_workflow(1, api_key="k")
    messages = [entry["message"] for entry in result["logs"]]

    assert result["status"] == "error"
    assert executor_env.statuses[-1][0] == "failed"
    assert "insufficient margin" in executor_env.statuses[-1][1]
    assert not any("hedge placed" in m for m in messages), "downstream node still ran"
    assert result["errors"][0]["type"] == "placeOrder"


def test_successful_run_still_completes(executor_env, monkeypatch):
    """The fail-closed change must not break the accepted-order path."""
    monkeypatch.setattr(
        fes,
        "get_flow_client",
        lambda api_key: _Client({"status": "success", "orderid": "X1"}),
    )

    result = fes.execute_workflow(1, api_key="k")
    messages = [entry["message"] for entry in result["logs"]]

    assert result["status"] == "success"
    assert executor_env.statuses[-1][0] == "completed"
    assert any("hedge placed" in m for m in messages)


def test_concurrent_triggers_run_the_workflow_once(executor_env, monkeypatch):
    """FLOW-006: locked() then a blocking acquire let both callers through.

    The loser waited on the lock and then ran the whole workflow again the
    moment the winner finished, duplicating every order, instead of returning
    already_running.
    """
    monkeypatch.setattr(
        fes,
        "get_flow_client",
        lambda api_key: _Client({"status": "success", "orderid": "X1"}),
    )
    real_chain = fes.execute_node_chain

    def slow_chain(*args, **kwargs):
        time.sleep(0.3)
        return real_chain(*args, **kwargs)

    monkeypatch.setattr(fes, "execute_node_chain", slow_chain)

    barrier = threading.Barrier(2)
    results: list[dict] = []

    def run():
        barrier.wait()
        results.append(fes.execute_workflow(1, api_key="k"))

    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sum(1 for r in results if r.get("already_running")) == 1
    assert sum(1 for r in results if r.get("status") == "success") == 1


def test_workflow_lock_is_released_after_an_exception(executor_env, monkeypatch):
    """A crashed run must not leave the workflow permanently already_running."""
    monkeypatch.setattr(fes, "get_flow_client", lambda api_key: _Client({"status": "success"}))

    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(fes, "execute_node_chain", boom)

    result = fes.execute_workflow(1, api_key="k")

    assert result["status"] == "error"
    assert not fes.get_workflow_lock(1).locked()


# ---------------------------------------------------------------------------
# FLOW-012: Modify Order must not invent the fields the editor never collects
# ---------------------------------------------------------------------------

_LIVE_ORDER = {
    "orderid": "25082800018",
    "symbol": "YESBANK",
    "exchange": "NSE",
    "action": "SELL",
    "product": "NRML",
    "pricetype": "LIMIT",
    "quantity": "500",
    "price": 18.5,
    "trigger_price": 0,
}


class _ModifyClient:
    def __init__(self, order):
        self.order = order
        self.sent = None

    def get_order_status(self, order_id):
        if self.order is None:
            return {"status": "error", "message": "order not found"}
        return {"status": "success", "data": dict(self.order)}

    def modify_order(self, **kwargs):
        self.sent = kwargs
        return {"status": "success", "orderid": kwargs["order_id"]}


def _modify(node_data, order=_LIVE_ORDER):
    client = _ModifyClient(order)
    executor = fes.NodeExecutor(client, fes.WorkflowContext(), [])
    result = executor.execute_modify_order(node_data)
    return client, result


def test_modify_order_preserves_the_live_order_attributes():
    """The editor collects only order id, new price and new quantity.

    The rest came from hardcoded defaults and went to the broker verbatim:
    action BUY converts a live SELL on brokers that carry it, product MIS makes
    an NRML position intraday, and the absent quantity became 1 because the UI
    writes newQuantity.
    """
    client, result = _modify({"orderId": "25082800018", "newPrice": "19.25"})

    assert result["status"] == "success"
    assert client.sent["action"] == "SELL"
    assert client.sent["product_type"] == "NRML"
    assert client.sent["quantity"] == 500
    assert client.sent["symbol"] == "YESBANK"
    assert client.sent["price_type"] == "LIMIT"
    assert client.sent["price"] == 19.25


def test_modify_order_leaves_unspecified_fields_unchanged():
    """ "Leave empty to keep" has to be literal, not a fallback to zero."""
    client, _ = _modify({"orderId": "25082800018", "newQuantity": "250"})

    assert client.sent["quantity"] == 250
    assert client.sent["price"] == 18.5


def test_modify_order_refuses_when_the_order_cannot_be_read():
    """Better to fail than to send a guessed side, product and quantity."""
    client, result = _modify({"orderId": "nope", "newPrice": "1"}, order=None)

    assert result["status"] == "error"
    assert client.sent is None


# ---------------------------------------------------------------------------
# FLOW-017: Close Positions honours the filter it advertises
# ---------------------------------------------------------------------------


class _CloseClient:
    def __init__(self):
        self.sent = None

    def close_all_positions(self):
        self.sent = {"call": "close_all"}
        return {"status": "success"}

    def close_position(self, **kwargs):
        self.sent = {"call": "close_one", **kwargs}
        return {"status": "success"}


@pytest.mark.parametrize(
    "node_data,expected",
    [
        ({"symbol": "", "exchange": "NSE", "product": "MIS"}, "close_all"),
        ({}, "close_all"),
        ({"symbol": "SBIN", "exchange": "NSE", "product": "MIS"}, "close_one"),
    ],
)
def test_close_positions_scope(node_data, expected):
    """exchange and product ship pre-filled, so only symbol may scope the close."""
    client = _CloseClient()
    executor = fes.NodeExecutor(client, fes.WorkflowContext(), [])

    executor.execute_close_positions(node_data)

    assert client.sent["call"] == expected


# ---------------------------------------------------------------------------
# FLOW-020: the HTTP node must not be steerable at internal hosts
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:5000/api/v1/funds",
        "http://localhost/admin",
        "http://169.254.169.254/latest/meta-data/",
        "http://192.168.1.1/",
        "http://10.0.0.5/",
        "file:///etc/passwd",
        "ftp://example.com/x",
    ],
)
def test_http_request_rejects_non_public_destinations(url):
    """url interpolates from context, and a webhook puts its caller's body there."""
    executor = fes.NodeExecutor(None, fes.WorkflowContext(), [])

    result = executor.execute_http_request({"url": url, "method": "GET"})

    assert result["status"] == "error"
    assert "refusing" in result["message"]


def test_http_request_rejects_unparseable_headers():
    """The editor writes headers as a JSON string; a bad one must not go out bare."""
    executor = fes.NodeExecutor(None, fes.WorkflowContext(), [])

    result = executor.execute_http_request({"url": "http://example.com", "headers": "{not json}"})

    assert result["status"] == "error"
    assert "not valid JSON" in result["message"]


def test_http_request_redacts_query_strings_in_logs():
    """Execution logs are persisted and rendered, so a token must not reach them."""
    redacted = fes.NodeExecutor._redact_url("https://api.example.com/send?token=SECRET")

    assert "SECRET" not in redacted
    assert redacted.startswith("https://api.example.com/send")


def test_http_timeout_is_milliseconds_and_capped():
    """The UI labels this box "Timeout (ms)"; it was passed to httpx as seconds."""
    assert fes.NodeExecutor.HTTP_TIMEOUT_DEFAULT_MS == 30_000
    assert fes.NodeExecutor.HTTP_TIMEOUT_MAX_MS == 60_000


# ---------------------------------------------------------------------------
# FLOW-016: guards that cannot guard must fail closed
# ---------------------------------------------------------------------------


class _GuardClient:
    def funds(self):
        return {"status": "success", "data": {"availablecash": 50}}

    def get_open_position(self, **kwargs):
        return {"quantity": 0, "pnl": 0}


def test_fund_check_without_a_minimum_fails_closed():
    """Defaulting to zero made the comparison availablecash >= 0: always true."""
    executor = fes.NodeExecutor(_GuardClient(), fes.WorkflowContext(), [])

    result = executor.execute_fund_check({})

    assert result["status"] == "error"
    assert result["condition"] is False


def test_fund_check_still_compares_against_a_configured_minimum():
    executor = fes.NodeExecutor(_GuardClient(), fes.WorkflowContext(), [])

    assert executor.execute_fund_check({"minAvailable": 10000})["condition"] is False
    assert executor.execute_fund_check({"minAvailable": 10})["condition"] is True


def test_position_check_without_a_symbol_fails_closed():
    """A blank symbol reads a zero-quantity position, making not_exists always true."""
    executor = fes.NodeExecutor(_GuardClient(), fes.WorkflowContext(), [])

    result = executor.execute_position_check({"condition": "not_exists"})

    assert result["status"] == "error"
    assert result["condition"] is False


def test_validator_requires_the_fields_those_guards_read():
    """The same two gates are refused at import and activation, not just at run time."""
    from services.flow_workflow_validator import (
        EITHER_REQUIRED_FIELDS,
        REQUIRED_NODE_FIELDS,
    )

    assert ("minAvailable", "threshold") in EITHER_REQUIRED_FIELDS["fundCheck"]
    assert "symbol" in REQUIRED_NODE_FIELDS["positionCheck"]
    assert "condition" in REQUIRED_NODE_FIELDS["positionCheck"]


# ---------------------------------------------------------------------------
# FLOW-011: the API key must not be persisted into the scheduler jobstore
# ---------------------------------------------------------------------------


def test_scheduler_job_args_carry_no_api_key():
    """APScheduler pickles these args into the same DB that encrypts the key."""
    import inspect

    from services.flow_scheduler_service import FlowScheduler

    source = inspect.getsource(FlowScheduler.add_workflow_job)

    assert "self._api_key, market_hours_only" not in source
    assert "[workflow_id, None, market_hours_only]" in source


# ---------------------------------------------------------------------------
# FLOW-019: the execution-history query must be bounded
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("requested", [-1, 0, None, 10_000_000])
def test_execution_history_limit_is_clamped(requested, monkeypatch):
    """SQLite reads a negative LIMIT as unlimited, so -1 loaded every row."""
    import database.flow_db as flow_db

    captured: list[int] = []

    class _Query:
        def filter_by(self, **kwargs):
            return self

        def order_by(self, *args):
            return self

        def limit(self, value):
            captured.append(value)
            return self

        def all(self):
            return []

    monkeypatch.setattr(flow_db.FlowWorkflowExecution, "query", _Query())

    flow_db.get_workflow_executions(1, limit=requested)

    assert 1 <= captured[0] <= flow_db.EXECUTIONS_QUERY_MAX
