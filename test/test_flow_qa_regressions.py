"""Regression tests for the 2026-08-21 Flow production QA audit findings.

Each test pins one defect that was confirmed against the source and fixed. They
run without a broker, market data, or a live scheduler: the collaborators are
stubbed at the seams the executor already imports through.
"""

import io
import threading
import time
import types

import pytest

import services.flow_executor_service as fes
import services.flow_openalgo_client as foac
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


# ---------------------------------------------------------------------------
# Telegram alerts: the workflow API key, never legacy node data, owns delivery
# ---------------------------------------------------------------------------


def test_telegram_alert_ignores_legacy_username_and_delivers_to_api_key_owner(monkeypatch):
    """A stale imported ``username`` cannot redirect another user's alert."""
    verified_api_keys = []
    looked_up_usernames = []
    deliveries = []

    fake_auth_db = types.ModuleType("database.auth_db")

    def verify_api_key(api_key):
        verified_api_keys.append(api_key)
        return "owner_user"

    fake_auth_db.verify_api_key = verify_api_key
    monkeypatch.setitem(__import__("sys").modules, "database.auth_db", fake_auth_db)

    fake_telegram_db = types.ModuleType("database.telegram_db")

    def get_telegram_user_by_username(username):
        looked_up_usernames.append(username)
        return {
            "telegram_id": {
                "owner_user": 101,
                "other_user": 202,
            }[username],
            "notifications_enabled": True,
        }

    fake_telegram_db.get_telegram_user_by_username = get_telegram_user_by_username
    monkeypatch.setitem(__import__("sys").modules, "database.telegram_db", fake_telegram_db)

    fake_alert_service = types.SimpleNamespace(
        is_bot_active=lambda: True,
        send_alert_sync=lambda telegram_id, message: deliveries.append((telegram_id, message)),
    )
    fake_executor = types.SimpleNamespace(submit=lambda fn, *args: fn(*args))
    fake_service_module = types.ModuleType("services.telegram_alert_service")
    fake_service_module.telegram_alert_service = fake_alert_service
    fake_service_module.alert_executor = fake_executor
    monkeypatch.setitem(
        __import__("sys").modules,
        "services.telegram_alert_service",
        fake_service_module,
    )

    client = foac.FlowOpenAlgoClient("owner-api-key")
    real_telegram = client.telegram
    client_calls = []

    def record_telegram_call(*args, **kwargs):
        client_calls.append((args, kwargs))
        return real_telegram(*args, **kwargs)

    client.telegram = record_telegram_call
    executor = fes.NodeExecutor(client, fes.WorkflowContext(), [])

    result = executor.execute_telegram_alert(
        {"message": "Owner-only notice", "username": "other_user"}
    )

    assert result["status"] == "success"
    assert client_calls == [((), {"message": "Owner-only notice"})]
    assert verified_api_keys == ["owner-api-key"]
    assert looked_up_usernames == ["owner_user"]
    assert len(deliveries) == 1
    telegram_id, formatted_message = deliveries[0]
    assert telegram_id == 101
    assert "Owner-only notice" in formatted_message
    assert "other_user" not in formatted_message


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
        return {"status": "success", "quantity": 0, "pnl": 0}


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


# ---------------------------------------------------------------------------
# Unresolved {{variables}} must not become order defaults
# ---------------------------------------------------------------------------

_ORDER_NODE = {
    "symbol": "SBIN",
    "exchange": "NSE",
    "action": "BUY",
    "product": "MIS",
    "priceType": "LIMIT",
    "price": "{{webhook.px}}",
    "quantity": "{{webhook.qty}}",
}


class _RecordingClient:
    def __init__(self):
        self.orders = []
        self.smart_orders = []
        self.split_orders = []
        self.baskets = []

    def place_order(self, **kwargs):
        self.orders.append(kwargs)
        return {"status": "success", "orderid": "X1"}

    def place_smart_order(self, **kwargs):
        self.smart_orders.append(kwargs)
        return {"status": "success", "orderid": "S1"}

    def split_order(self, **kwargs):
        self.split_orders.append(kwargs)
        return {"status": "success", "orderid": "SP1"}

    def basket_order(self, **kwargs):
        self.baskets.append(kwargs)
        return {"status": "success", "orderids": ["B1"]}


@pytest.fixture
def order_env(executor_env, monkeypatch):
    """executor_env, plus a client that records what reached the broker."""
    client = _RecordingClient()
    monkeypatch.setattr(fes, "get_flow_client", lambda api_key: client)
    return types.SimpleNamespace(client=client, statuses=executor_env.statuses)


def _graph(node_type, data):
    return [
        {"id": "n1", "type": "start", "data": {}},
        {"id": "n2", "type": node_type, "data": data},
        {"id": "n3", "type": "log", "data": {"message": "downstream ran"}},
    ]


def _run_graph(monkeypatch, node_type, data, webhook):
    workflow = types.SimpleNamespace(
        id=1, name="t", nodes=_graph(node_type, data), edges=_EDGES, is_active=True
    )
    monkeypatch.setattr(fes, "get_workflow", lambda wid: workflow)
    result = fes.execute_workflow(1, webhook_data=webhook, api_key="k")
    return result, [entry["message"] for entry in result["logs"]]


def test_unresolved_order_field_never_reaches_the_broker(order_env, monkeypatch):
    """A webhook that omits a key used to produce a successful wrong order.

    `get_int` cannot parse `{{webhook.qty}}`, so it returned its default of 1,
    and the unresolved price type fell through the broker mapper to MARKET. The
    node now fails before the call is made.
    """
    result, messages = _run_graph(monkeypatch, "placeOrder", _ORDER_NODE, {"symbol": "SBIN"})

    assert order_env.client.orders == [], "an order was sent with substituted values"
    assert result["status"] == "error"
    assert order_env.statuses[-1][0] == "failed"
    assert not any("downstream ran" in m for m in messages)
    assert "quantity" in result["errors"][0]["message"]


def test_resolved_order_fields_are_sent_normally(order_env, monkeypatch):
    """The guard must not disturb the case where the variables do resolve."""
    result, messages = _run_graph(monkeypatch, "placeOrder", _ORDER_NODE, {"qty": 50, "px": 812.5})

    assert result["status"] == "success"
    assert order_env.client.orders[0]["quantity"] == 50
    assert order_env.client.orders[0]["price"] == 812.5
    assert any("downstream ran" in m for m in messages)


def test_label_fields_stay_permissive(order_env, monkeypatch):
    """strategyTag is a label; an unresolved reference there is untidy, not unsafe."""
    data = {**_ORDER_NODE, "price": 800, "quantity": 10, "strategyTag": "{{missing.tag}}"}

    result, _ = _run_graph(monkeypatch, "placeOrder", data, {})

    assert result["status"] == "success"
    assert order_env.client.orders[0]["strategy"] == "{{missing.tag}}"


def test_non_order_nodes_keep_passing_variables_through(order_env, monkeypatch):
    """Interpolation stays forgiving everywhere the value cannot reach a broker."""
    result, messages = _run_graph(monkeypatch, "log", {"message": "value is {{missing.thing}}"}, {})

    assert result["status"] == "success"
    assert any("{{missing.thing}}" in m for m in messages)


def test_cancel_order_with_an_unresolved_id_fails(order_env, monkeypatch):
    """Cancelling "{{prev.orderid}}" literally would target nothing, silently."""
    result, _ = _run_graph(monkeypatch, "cancelOrder", {"orderId": "{{prev.orderid}}"}, {})

    assert result["status"] == "error"
    assert "orderId" in result["errors"][0]["message"]


# ---------------------------------------------------------------------------
# FLOW-024: order numeric fields must retain explicit zero and broker pricing
# ---------------------------------------------------------------------------


def test_numeric_accessors_preserve_zero():
    """A numeric zero is supplied data, not a missing value to replace."""
    executor = fes.NodeExecutor(None, fes.WorkflowContext(), [])
    executor.context.set_variable("bad_number", "not-a-number")

    assert executor.get_int({"quantity": 0}, "quantity", 1) == 0
    assert executor.get_float({"price": 0}, "price", 1.0) == 0.0
    assert executor.get_int({}, "quantity", 1) == 1
    assert executor.get_float({}, "price", 1.0) == 1.0
    assert executor.get_int({"quantity": "{{bad_number}}"}, "quantity", 1) == 1
    assert executor.get_float({"price": "{{bad_number}}"}, "price", 1.0) == 1.0


@pytest.mark.parametrize(
    ("method", "node_data", "expected"),
    [
        (
            "execute_smart_order",
            {
                "symbol": "SBIN",
                "exchange": "NSE",
                "action": "BUY",
                "quantity": 0,
                "positionSize": 5,
                "product": "MIS",
                "priceType": "LIMIT",
                "price": 625,
                "triggerPrice": 0,
            },
            {"price": 625.0, "trigger_price": 0.0},
        ),
        (
            "execute_split_order",
            {
                "symbol": "SBIN",
                "exchange": "NSE",
                "action": "SELL",
                "quantity": 4,
                "splitSize": 2,
                "product": "MIS",
                "priceType": "SL",
                "price": 625,
                "triggerPrice": 624,
            },
            {"price": 625.0, "trigger_price": 624.0},
        ),
    ],
)
def test_smart_and_split_order_price_reaches_the_broker(method, node_data, expected):
    """These nodes used to discard price data and place a different order type."""
    client = _RecordingClient()
    executor = fes.NodeExecutor(client, fes.WorkflowContext(), [])

    result = getattr(executor, method)(node_data)

    sent = client.smart_orders if method == "execute_smart_order" else client.split_orders
    assert result["status"] == "success"
    assert sent[0]["quantity"] == node_data["quantity"]
    assert sent[0]["price"] == expected["price"]
    assert sent[0]["trigger_price"] == expected["trigger_price"]


@pytest.mark.parametrize(
    ("method", "node_data"),
    [
        (
            "execute_smart_order",
            {
                "symbol": "SBIN",
                "quantity": 1,
                "priceType": "LIMIT",
                "price": "{{runtime.price}}",
            },
        ),
        (
            "execute_split_order",
            {
                "symbol": "SBIN",
                "quantity": 1,
                "splitSize": 1,
                "priceType": "SL",
                "price": 625,
                "triggerPrice": "{{runtime.trigger}}",
            },
        ),
    ],
)
def test_smart_and_split_order_price_templates_that_resolve_to_zero_fail_closed(method, node_data):
    """A resolved zero must be rejected before the broker can reinterpret it."""
    client = _RecordingClient()
    context = fes.WorkflowContext()
    context.set_variable("runtime", {"price": 0, "trigger": 0})
    executor = fes.NodeExecutor(client, context, [])

    result = getattr(executor, method)(node_data)

    assert result["status"] == "error"
    assert client.smart_orders == []
    assert client.split_orders == []


def test_basket_order_price_applies_common_fields_to_csv_rows():
    """CSV basket rows inherit the node price fields in the client's payload spelling."""
    client = _RecordingClient()
    executor = fes.NodeExecutor(client, fes.WorkflowContext(), [])

    result = executor.execute_basket_order(
        {
            "orders": "SBIN,NSE,BUY,2",
            "product": "MIS",
            "priceType": "SL",
            "price": 625,
            "triggerPrice": 624,
        }
    )

    assert result["status"] == "success"
    sent = client.baskets[0]["orders"]
    assert sent[0] == {
        "symbol": "SBIN",
        "exchange": "NSE",
        "action": "BUY",
        "quantity": 2,
        "product": "MIS",
        "pricetype": "SL",
        "price": 625.0,
        "triggerprice": 624.0,
    }


def test_basket_order_price_preserves_imported_leg_values_and_fills_missing_values():
    """Imported legs own their explicit fields and the editor's saved list stays untouched."""
    client = _RecordingClient()
    context = fes.WorkflowContext()
    context.set_variable("runtime", {"price": 626, "trigger": 625})
    executor = fes.NodeExecutor(client, context, [])
    orders = [
        {
            "symbol": "SBIN",
            "exchange": "NSE",
            "action": "BUY",
            "quantity": 2,
            "product": "CNC",
            "priceType": "LIMIT",
            "price": "{{runtime.price}}",
            "triggerPrice": "{{runtime.trigger}}",
        },
        {"symbol": "INFY", "exchange": "NSE", "action": "SELL", "quantity": 1},
    ]
    original_orders = [dict(order) for order in orders]

    result = executor.execute_basket_order(
        {
            "orders": orders,
            "product": "MIS",
            "priceType": "SL",
            "price": 625,
            "triggerPrice": 624,
        }
    )

    assert result["status"] == "success"
    assert orders == original_orders
    assert client.baskets[0]["orders"] == [
        {
            "symbol": "SBIN",
            "exchange": "NSE",
            "action": "BUY",
            "quantity": 2,
            "product": "CNC",
            "pricetype": "LIMIT",
            "price": 626.0,
            "triggerprice": 625.0,
        },
        {
            "symbol": "INFY",
            "exchange": "NSE",
            "action": "SELL",
            "quantity": 1,
            "product": "MIS",
            "pricetype": "SL",
            "price": 625.0,
            "triggerprice": 624.0,
        },
    ]


@pytest.mark.parametrize(
    "node_data",
    [
        {
            "orders": "SBIN,NSE,BUY,2",
            "priceType": "LIMIT",
            "price": "{{runtime.price}}",
        },
        {
            "orders": [
                {
                    "symbol": "SBIN",
                    "exchange": "NSE",
                    "action": "BUY",
                    "quantity": 2,
                    "priceType": "SL",
                    "price": 625,
                    "triggerPrice": 0,
                }
            ],
            "priceType": "MARKET",
        },
    ],
)
def test_basket_order_price_rejects_invalid_common_or_imported_prices(node_data):
    """One unusable row must stop the whole basket before any broker request."""
    client = _RecordingClient()
    context = fes.WorkflowContext()
    context.set_variable("runtime", {"price": 0})
    executor = fes.NodeExecutor(client, context, [])

    result = executor.execute_basket_order(node_data)

    assert result["status"] == "error"
    assert client.baskets == []


@pytest.mark.parametrize(
    ("orders", "field"),
    [
        ([{"exchange": "NSE", "action": "BUY", "quantity": 1}], "symbol"),
        ([{"symbol": "SBIN", "exchange": None, "action": "BUY", "quantity": 1}], "exchange"),
        ([{"symbol": "SBIN", "exchange": "NSE", "action": "", "quantity": 1}], "action"),
    ],
)
def test_basket_order_rejects_missing_required_text_before_the_client(orders, field):
    """Missing text must not be stringified into a broker-valid-looking value."""
    client = _RecordingClient()
    executor = fes.NodeExecutor(client, fes.WorkflowContext(), [])

    result = executor.execute_basket_order({"orders": orders})

    assert result["status"] == "error"
    assert field in result["message"]
    assert client.baskets == []


@pytest.mark.parametrize(
    ("node_data", "field"),
    [
        ({"orders": "SBIN,BAD,BUY,1"}, "exchange"),
        (
            {
                "orders": [
                    {"symbol": "SBIN", "exchange": "NSE", "action": "HOLD", "quantity": 1}
                ]
            },
            "action",
        ),
        ({"orders": "SBIN,NSE,BUY,1", "product": "BAD"}, "product"),
        (
            {
                "orders": [
                    {
                        "symbol": "SBIN",
                        "exchange": "NSE",
                        "action": "BUY",
                        "quantity": 1,
                        "priceType": "BAD",
                    }
                ]
            },
            "pricetype",
        ),
    ],
)
def test_basket_order_rejects_invalid_normalized_values_before_the_client(node_data, field):
    """Executor validation must reject values the live basket service would skip."""
    client = _RecordingClient()
    executor = fes.NodeExecutor(client, fes.WorkflowContext(), [])

    result = executor.execute_basket_order(node_data)

    assert result["status"] == "error"
    assert field in result["message"]
    assert client.baskets == []


def test_basket_order_rejects_a_later_invalid_row_without_partial_submission():
    """A valid first leg cannot reach the broker when a later leg is invalid."""
    client = _RecordingClient()
    executor = fes.NodeExecutor(client, fes.WorkflowContext(), [])

    result = executor.execute_basket_order(
        {
            "orders": [
                {"symbol": "SBIN", "exchange": "NSE", "action": "BUY", "quantity": 1},
                {"symbol": "INFY", "exchange": "INVALID", "action": "SELL", "quantity": 1},
            ]
        }
    )

    assert result["status"] == "error"
    assert "row 2" in result["message"]
    assert client.baskets == []


# ---------------------------------------------------------------------------
# Deferred option expiry values must be safe after interpolation
# ---------------------------------------------------------------------------


class _OptionExpiryClient:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def optionsymbol(self, **kwargs):
        self.calls.append(("optionSymbol", kwargs))
        return {"status": "success"}

    def optionchain(self, **kwargs):
        self.calls.append(("optionChain", kwargs))
        return {"status": "success"}

    def syntheticfuture(self, **kwargs):
        self.calls.append(("syntheticFuture", kwargs))
        return {"status": "success"}


@pytest.fixture
def option_expiry_env(executor_env, monkeypatch):
    """A real workflow execution with only the external option client recorded."""
    client = _OptionExpiryClient()
    monkeypatch.setattr(fes, "get_flow_client", lambda api_key: client)
    return types.SimpleNamespace(client=client, statuses=executor_env.statuses)


_OPTION_EXPIRY_TEMPLATE = {
    "underlying": "{{webhook.underlying}}",
    "expiryDate": "{{webhook.expiry}}",
}


@pytest.mark.parametrize("node_type", ["optionSymbol", "optionChain", "syntheticFuture"])
@pytest.mark.parametrize(
    "webhook",
    [
        {"underlying": "NIFTY", "expiry": ""},
        {"underlying": "NIFTY", "expiry": "not-a-date"},
        {"underlying": "NIFTY"},
    ],
)
def test_option_expiry_templates_fail_before_the_client_when_resolved_invalidly(
    option_expiry_env, monkeypatch, node_type, webhook
):
    """Interpolated expiry values must not degrade into empty or literal client inputs."""
    result, _ = _run_graph(monkeypatch, node_type, _OPTION_EXPIRY_TEMPLATE, webhook)

    assert result["status"] == "error"
    assert option_expiry_env.client.calls == []


@pytest.mark.parametrize("node_type", ["optionSymbol", "optionChain", "syntheticFuture"])
def test_option_expiry_templates_call_the_client_after_resolving_validly(
    option_expiry_env, monkeypatch, node_type
):
    """The runtime guard must preserve successful dynamic option requests."""
    result, _ = _run_graph(
        monkeypatch,
        node_type,
        _OPTION_EXPIRY_TEMPLATE,
        {"underlying": "NIFTY", "expiry": "27AUG26"},
    )

    assert result["status"] == "success"
    assert option_expiry_env.client.calls[0][0] == node_type


@pytest.mark.parametrize("node_type", ["optionSymbol", "optionChain"])
def test_explicit_dynamic_expiry_overrides_an_embedded_expiry_and_must_be_valid(
    option_expiry_env, monkeypatch, node_type
):
    """Option clients prefer expiryDate over an expiry embedded in the underlying."""
    result, _ = _run_graph(
        monkeypatch,
        node_type,
        {"underlying": "NIFTY27AUG26", "expiryDate": "{{webhook.expiry}}"},
        {"expiry": "not-a-date"},
    )

    assert result["status"] == "error"
    assert option_expiry_env.client.calls == []


@pytest.mark.parametrize("node_type", ["optionSymbol", "optionChain"])
def test_embedded_expiry_is_the_option_node_fallback_when_no_expiry_is_supplied(
    option_expiry_env, monkeypatch, node_type
):
    """An embedded expiry is valid only when an explicit expiryDate is absent."""
    result, _ = _run_graph(monkeypatch, node_type, {"underlying": "NIFTY27AUG26"}, {})

    assert result["status"] == "success"
    assert option_expiry_env.client.calls[0][0] == node_type


# ---------------------------------------------------------------------------
# Execution history: recorded with a start time, and bounded
# ---------------------------------------------------------------------------


@pytest.fixture
def flow_database():
    """The test database, initialised once, with a workflow per test.

    Everything a test creates here is deleted again on teardown. Without that
    the rows outlive the run: one pass through this file leaves seven
    workflows and their executions behind, and eight passes left fifty-six of
    them sitting in the operator's Flow Editor, every card reading "running"
    because the fixtures never complete an execution. Isolating the database
    (test/conftest.py) stops those rows landing in real data; cleaning up here
    means the file leaves nothing behind even when pointed somewhere it
    should not have been.

    Cleanup is by difference rather than by tracking each call, so a workflow
    created through any path is still removed. delete_workflow cascades to the
    executions.
    """
    import database.flow_db as flow_db

    flow_db.init_db()
    pre_existing = {workflow.id for workflow in flow_db.get_all_workflows()}

    yield flow_db

    for workflow in flow_db.get_all_workflows():
        if workflow.id not in pre_existing:
            flow_db.delete_workflow(workflow.id)


def test_execution_records_its_start_time(flow_database):
    """started_at was only set by a status nothing ever passed, so it was NULL.

    The history query ordered on that column; with every value NULL the sort
    collapsed to insertion order ascending, so the panel listed the oldest runs
    and the dashboard's "last run" showed the first run the workflow ever had.
    """
    workflow = flow_database.create_workflow("started_at test", nodes=[], edges=[])

    execution = flow_database.create_execution(workflow.id, status="running")

    assert execution is not None
    assert execution.started_at is not None


def test_execution_history_is_newest_first(flow_database):
    workflow = flow_database.create_workflow("ordering test", nodes=[], edges=[])
    for _ in range(5):
        flow_database.create_execution(workflow.id, status="running")

    rows = flow_database.get_workflow_executions(workflow.id, limit=5)
    ids = [row.id for row in rows]

    assert ids == sorted(ids, reverse=True), "history is not newest-first"


def test_retention_keeps_only_the_newest_runs(flow_database):
    """Each row carries the full node trace, so history has to be bounded."""
    workflow = flow_database.create_workflow("retention test", nodes=[], edges=[])
    for _ in range(30):
        flow_database.create_execution(workflow.id, status="running")
        flow_database.prune_workflow_executions(workflow.id, max_count=10, max_age_days=0)

    rows = flow_database.get_workflow_executions(workflow.id, limit=200)

    assert len(rows) == 10
    assert [r.id for r in rows] == sorted((r.id for r in rows), reverse=True)


def test_retention_removes_rows_past_the_age_limit(flow_database):
    from datetime import UTC, datetime, timedelta

    workflow = flow_database.create_workflow("age test", nodes=[], edges=[])
    keep = flow_database.create_execution(workflow.id, status="running")
    stale = flow_database.create_execution(workflow.id, status="running")
    stale.started_at = datetime.now(UTC) - timedelta(days=99)
    flow_database.db_session.commit()
    # Read the ids before pruning: the delete synchronizes the session, so the
    # removed instance is detached afterwards and cannot be queried for its id.
    keep_id, stale_id = keep.id, stale.id

    flow_database.prune_workflow_executions(workflow.id, max_count=0, max_age_days=30)

    remaining = {row.id for row in flow_database.get_workflow_executions(workflow.id, limit=200)}
    assert keep_id in remaining
    assert stale_id not in remaining


def test_retention_leaves_other_workflows_alone(flow_database):
    mine = flow_database.create_workflow("mine", nodes=[], edges=[])
    theirs = flow_database.create_workflow("theirs", nodes=[], edges=[])
    for _ in range(4):
        flow_database.create_execution(theirs.id, status="running")
    for _ in range(20):
        flow_database.create_execution(mine.id, status="running")

    flow_database.prune_workflow_executions(mine.id, max_count=2, max_age_days=0)

    assert len(flow_database.get_workflow_executions(theirs.id, limit=200)) == 4


def test_retention_can_be_switched_off(flow_database):
    workflow = flow_database.create_workflow("no retention", nodes=[], edges=[])
    for _ in range(6):
        flow_database.create_execution(workflow.id, status="running")

    deleted = flow_database.prune_workflow_executions(workflow.id, max_count=0, max_age_days=0)

    assert deleted == 0
    assert len(flow_database.get_workflow_executions(workflow.id, limit=200)) == 6


# ---------------------------------------------------------------------------
# Condition nodes must not answer confidently when they cannot evaluate
# ---------------------------------------------------------------------------


class _QuoteClient:
    def __init__(self, **fields):
        self.fields = fields
        self.cancelled = False

    def get_quotes(self, symbol, exchange):
        return {"status": "success", "data": self.fields}

    def get_open_position(self, **kwargs):
        # Shaped like the real client, which carries `status` on every return
        # path. Position Check refuses to answer without it, because a response
        # it cannot vouch for used to read as a flat position and let the
        # "no position -> BUY" guard fire on top of an open one.
        return {"status": "success", "quantity": 5, "pnl": 100}

    def cancel_all_orders(self):
        self.cancelled = True
        return {"status": "success", "cancelled": 3}


def _node(client=None):
    return fes.NodeExecutor(client or _QuoteClient(ltp=100.0), fes.WorkflowContext(), [])


@pytest.mark.parametrize(
    "node_data,reason",
    [
        ({"symbol": "S", "field": "close", "operator": ">", "value": 50}, "unknown field"),
        ({"symbol": "S", "field": "ltp", "operator": "~=", "value": 50}, "unknown operator"),
        ({"symbol": "S", "field": "ltp", "operator": ">", "value": "abc"}, "unparseable value"),
    ],
)
def test_price_condition_fails_rather_than_guessing(node_data, reason):
    """Each of these used to produce a confident answer from a substituted value.

    An unknown field read 0.0 out of the quote dict; an unknown operator fell
    through the comparison to a silent False, which the graph then treated as
    "the condition did not hold" rather than "the check never ran"; and a
    non-numeric threshold became 0.0.
    """
    result = _node().execute_price_condition(node_data)

    assert result["status"] == "error", reason
    assert result["condition"] is False


@pytest.mark.parametrize(
    "operator,value,expected",
    [(">", 50, True), ("<", 50, False), (">=", 100, True), ("!=", 100, False)],
)
def test_price_condition_still_evaluates_valid_configuration(operator, value, expected):
    result = _node().execute_price_condition(
        {"symbol": "S", "field": "ltp", "operator": operator, "value": value}
    )

    assert result["condition"] is expected


def test_price_condition_change_percent_is_computed():
    result = _node(_QuoteClient(ltp=110.0, prev_close=100.0)).execute_price_condition(
        {"symbol": "S", "field": "change_percent", "operator": ">", "value": 5}
    )

    assert result["condition"] is True


def test_position_check_rejects_an_unknown_condition():
    """It used to log "returning False", which is indistinguishable downstream."""
    result = _node().execute_position_check(
        {"symbol": "S", "exchange": "NSE", "condition": "qty_gt"}
    )

    assert result["status"] == "error"
    assert result["condition"] is False


def test_position_check_still_evaluates_a_known_condition():
    result = _node().execute_position_check(
        {"symbol": "S", "exchange": "NSE", "condition": "exists"}
    )

    assert result["status"] == "success"
    assert result["condition"] is True


def test_time_condition_honours_seconds():
    """Truncating seconds fired "after 15:29:59" a minute early.

    Both target times below sit inside the same minute as now, so the two
    assertions can only disagree if the seconds survive parsing. waitUntil
    already honoured them, so the two nodes disagreed on one string.
    """
    from datetime import datetime, timedelta

    now = datetime.now()
    passed = (now - timedelta(seconds=20)).strftime("%H:%M:%S")
    upcoming = (now + timedelta(seconds=20)).strftime("%H:%M:%S")

    assert _node().execute_time_condition({"targetTime": passed, "operator": ">="})["condition"]
    assert not _node().execute_time_condition({"targetTime": upcoming, "operator": ">="})[
        "condition"
    ]


def test_time_condition_rejects_an_unknown_operator():
    result = _node().execute_time_condition({"targetTime": "09:30:00", "operator": "after"})

    assert result["status"] == "error"
    assert result["condition"] is False


def test_cancel_all_orders_stores_its_result():
    """Every other action node does; without it the variable stayed undefined."""
    client = _QuoteClient()
    executor = _node(client)

    executor.execute_cancel_all_orders({"outputVariable": "cancelled"})

    assert client.cancelled is True
    assert executor.context.interpolate("{{cancelled.cancelled}}") == "3"


# ---------------------------------------------------------------------------
# Variable nodes preserve raw values and report failed operations honestly
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("operation", "initial", "data", "expected"),
    [
        ("set", {}, {"value": '{"ok": true}'}, {"ok": True}),
        (
            "get",
            {"portfolio": {"orders": [{"price": 101}, {"price": 102.5}]}},
            {"sourceVariable": "portfolio", "jsonPath": "orders[1].price"},
            102.5,
        ),
        ("add", {"target": 2}, {"value": "3"}, 5.0),
        ("subtract", {"target": 9}, {"value": "4"}, 5.0),
        ("multiply", {"target": 3}, {"value": "2.5"}, 7.5),
        ("divide", {"target": 9}, {"value": "2"}, 4.5),
        ("increment", {"target": 3}, {}, 4.0),
        ("decrement", {"target": 3}, {}, 2.0),
        ("parse_json", {}, {"value": '{"ok": true}'}, {"ok": True}),
        ("stringify", {"source": {"ok": True}}, {"sourceVariable": "source"}, '{"ok": true}'),
        ("append", {}, {"value": "done"}, "done"),
    ],
)
def test_variable_operation_success(operation, initial, data, expected):
    """Each supported operation stores its specified raw result."""
    executor = _node()
    executor.context.variables.update(initial)

    result = executor.execute_variable({"variableName": "target", "operation": operation, **data})

    assert result == {"status": "success", "variable": "target", "value": expected}
    assert executor.context.get_variable("target") == expected


def test_variable_operation_get_preserves_a_stored_none_value():
    """A stored None is a source value, rather than evidence the source is missing."""
    executor = _node()
    executor.context.set_variable("source", None)

    result = executor.execute_variable(
        {"variableName": "target", "operation": "get", "sourceVariable": "source"}
    )

    assert result == {"status": "success", "variable": "target", "value": None}
    assert executor.context.get_variable("target") is None


@pytest.mark.parametrize(
    ("operation", "initial", "data", "original"),
    [
        ("unknown", {"target": "sentinel"}, {}, "sentinel"),
        ("get", {"target": "sentinel"}, {}, "sentinel"),
        (
            "get",
            {"target": "sentinel", "source": {"orders": []}},
            {"sourceVariable": "source", "jsonPath": "orders[1].price"},
            "sentinel",
        ),
        ("add", {"target": "not numeric"}, {"value": "1"}, "not numeric"),
        ("add", {"target": "sentinel"}, {"value": "not numeric"}, "sentinel"),
        ("parse_json", {"target": "sentinel"}, {"value": "not json"}, "sentinel"),
        ("stringify", {"target": "sentinel", "source": {1, 2}}, {"sourceVariable": "source"}, "sentinel"),
    ],
)
def test_variable_operation_error_does_not_mutate_target(operation, initial, data, original):
    """Invalid work must preserve the output variable rather than partly succeeding."""
    executor = _node()
    executor.context.variables.update(initial)

    result = executor.execute_variable({"variableName": "target", "operation": operation, **data})

    assert result["status"] == "error"
    assert executor.context.get_variable("target") == original


def test_variable_divide_by_zero_reaches_the_zero_guard_without_mutating_target():
    """A numeric target proves the explicit divisor guard, not an earlier coercion error."""
    executor = _node()
    executor.context.set_variable("target", 9)

    result = executor.execute_variable(
        {"variableName": "target", "operation": "divide", "value": 0}
    )

    assert result["status"] == "error"
    assert "divide by zero" in result["message"].lower()
    assert executor.context.get_variable("target") == 9


@pytest.mark.parametrize(
    ("expression", "expected"),
    [("floor(3.9)", 3.0), ("floor(2 + 2.8)", 4.0)],
)
def test_safe_math_floor(expression, expected):
    assert _node()._safe_eval_math(expression) == expected


@pytest.mark.parametrize(
    "expression",
    [
        "ceil(1.1)",
        "math.floor(2.2)",
        "floor()",
        "floor(1, 2)",
        "floor(x=1)",
        "floor(unknown(1))",
        "__import__('os').system('echo unsafe')",
    ],
)
def test_safe_math_floor_rejects_every_other_call_shape(expression):
    with pytest.raises(ValueError):
        _node()._safe_eval_math(expression)


# ---------------------------------------------------------------------------
# Monitor shutdown is reachable, idempotent and recoverable
# ---------------------------------------------------------------------------


def test_price_monitor_shutdown_is_idempotent(monkeypatch):
    """atexit may fire after an explicit call; neither should raise.

    The pool is swapped for a throwaway one: shutdown releases the module-level
    executor, and killing the shared instance would break every later test that
    queues a run.
    """
    from concurrent.futures import ThreadPoolExecutor

    monkeypatch.setattr(fpm, "_WORKFLOW_POOL", ThreadPoolExecutor(max_workers=1))

    monitor = fpm.FlowPriceMonitor()
    monitor._shutdown_done = False
    monitor.shutdown()
    monitor.shutdown()

    assert monitor.is_running() is False
    monitor._shutdown_done = False


def test_order_monitor_shutdown_allows_resubscription(monkeypatch):
    """__init__ returns early on _initialized, so shutdown must clear it.

    Without that the singleton was unrecoverable: nothing could ever re-attach
    to the order-update bus for the rest of the process.
    """
    from concurrent.futures import ThreadPoolExecutor

    import services.flow_order_update_monitor_service as oum

    monkeypatch.setattr(oum, "_WORKFLOW_POOL", ThreadPoolExecutor(max_workers=1))

    monitor = oum.get_flow_order_update_monitor()
    monitor._shutdown_done = False
    monitor.shutdown()

    assert monitor._initialized is False
    monitor._shutdown_done = False


def test_both_monitors_release_their_pool_at_exit():
    """Neither shutdown had a caller, so the pools outlived every process.

    Checked at the source level: CPython's atexit is C-implemented and exposes
    no way to enumerate what is registered.
    """
    import inspect

    import services.flow_order_update_monitor_service as oum

    assert "atexit.register(_shutdown_at_exit)" in inspect.getsource(fpm)
    assert "atexit.register(_shutdown_at_exit)" in inspect.getsource(oum)
    assert "flow_price_monitor.shutdown()" in inspect.getsource(fpm)
    assert "flow_order_update_monitor.shutdown()" in inspect.getsource(oum)


# ---------------------------------------------------------------------------
# FLOW-031: a trigger is spent only by a run that actually happened
# ---------------------------------------------------------------------------


def test_already_running_does_not_consume_a_one_shot_alert(price_monitor, monkeypatch):
    """Retirement ran in `finally`, so a collision spent the event.

    A one-shot alert firing while a previous run was still in flight was
    retired and its workflow deactivated, even though the graph never saw the
    event. The alert must stay armed so the next tick can deliver it.
    """
    import sys

    sys.modules["services.flow_executor_service"].execute_workflow = (
        lambda wid, webhook_data=None, api_key=None: (
            price_monitor.fired.append(wid),
            price_monitor.done.set(),
            {"status": "error", "already_running": True},
        )[-1]
    )

    alert = _arm(price_monitor.monitor, 7001)
    price_monitor.monitor._check_alert(alert)
    assert price_monitor.done.wait(5)
    time.sleep(0.05)

    assert price_monitor.monitor.get_alert(7001) is not None, "the alert was consumed"
    assert price_monitor.deactivated == [], "the workflow was deactivated without running"
    assert alert.triggered is False, "the latch was left set, so it can never fire again"


def test_submit_failure_leaves_the_alert_armed(price_monitor, monkeypatch):
    """The latch is set before submitting; a failed submit must clear it.

    Otherwise _check_all_alerts skips the alert for the rest of the process and
    the trigger is silently dead.
    """

    def refuse(fn):
        raise RuntimeError("pool is full")

    monkeypatch.setattr(fpm._WORKFLOW_POOL, "submit", refuse)

    alert = _arm(price_monitor.monitor, 7002)
    # _check_alert logs and swallows the failure rather than propagating it, so
    # the observable outcome is the latch, not an exception.
    price_monitor.monitor._check_alert(alert)

    assert alert.triggered is False
    assert price_monitor.monitor.get_alert(7002) is not None


def test_a_broker_rejection_still_consumes_the_one_shot(price_monitor):
    """The workflow ran; the broker refusing the order is not a lost event."""
    import sys

    sys.modules["services.flow_executor_service"].execute_workflow = (
        lambda wid, webhook_data=None, api_key=None: (
            price_monitor.fired.append(wid),
            price_monitor.done.set(),
            {"status": "error", "message": "insufficient margin"},
        )[-1]
    )

    price_monitor.monitor._check_alert(_arm(price_monitor.monitor, 7003))
    assert price_monitor.done.wait(5)
    time.sleep(0.05)

    assert price_monitor.monitor.get_alert(7003) is None
    assert price_monitor.deactivated == [7003]


# ---------------------------------------------------------------------------
# FLOW-032: a condition that cannot be evaluated fails the run
# ---------------------------------------------------------------------------


def _condition_graph(operator):
    return [
        {"id": "n1", "type": "start", "data": {}},
        {
            "id": "n2",
            "type": "priceCondition",
            "data": {
                "symbol": "SBIN",
                "exchange": "NSE",
                "field": "ltp",
                "operator": operator,
                "value": 50,
            },
        },
        {"id": "n3", "type": "log", "data": {"message": "true branch"}},
    ]


_COND_EDGES = [
    {"id": "e1", "source": "n1", "target": "n2"},
    {"id": "e2", "source": "n2", "sourceHandle": "true", "target": "n3"},
]


def _run_condition(monkeypatch, executor_env, operator, value=50):
    nodes = _condition_graph(operator)
    nodes[1]["data"]["value"] = value
    workflow = types.SimpleNamespace(id=1, name="t", nodes=nodes, edges=_COND_EDGES, is_active=True)
    monkeypatch.setattr(fes, "get_workflow", lambda wid: workflow)
    monkeypatch.setattr(fes, "get_flow_client", lambda api_key: _QuoteClient(ltp=100.0))
    result = fes.execute_workflow(1, api_key="k")
    return result, [entry["message"] for entry in result["logs"]]


def test_unevaluatable_condition_fails_the_run(executor_env, monkeypatch):
    """Condition errors were exempt from executor.errors, so the run passed.

    The node logged an error and took neither branch, yet execute_workflow
    returned success and persisted `completed` -- the exact dishonesty the
    error list exists to prevent.
    """
    result, messages = _run_condition(monkeypatch, executor_env, "~=")

    assert result["status"] == "error"
    assert executor_env.statuses[-1][0] == "failed"
    assert not any("true branch" in m for m in messages)
    assert result["errors"][0]["type"] == "priceCondition"


def test_a_condition_that_is_merely_false_is_not_an_error(executor_env, monkeypatch):
    """False is a real answer and must stay distinguishable from "cannot evaluate"."""
    result, messages = _run_condition(monkeypatch, executor_env, ">", value=500)

    assert result["status"] == "success"
    assert executor_env.statuses[-1][0] == "completed"
    assert not any("true branch" in m for m in messages)


def test_a_condition_that_holds_still_routes_its_branch(executor_env, monkeypatch):
    result, messages = _run_condition(monkeypatch, executor_env, ">", value=50)

    assert result["status"] == "success"
    assert any("true branch" in m for m in messages)


# ---------------------------------------------------------------------------
# FLOW-012: the editor must not ship values that override the live order
# ---------------------------------------------------------------------------


def test_modify_order_defaults_carry_no_order_attributes():
    """The backend lookup cannot tell a shipped default from an intended value.

    DEFAULT_NODE_DATA.modifyOrder carried exchange 'NSE' and action 'BUY', so
    every node created in the editor sent them as explicit overrides and a live
    NFO SELL order was modified into an NSE BUY.
    """
    import re

    source = open("frontend/src/lib/flow/constants.ts", encoding="utf-8").read()
    block = re.search(r"  modifyOrder: \{(.*?)\n  \},", source, re.S).group(1)

    for field in ("symbol", "exchange", "action", "product", "priceType"):
        assert re.search(rf"^\s+{field}:", block, re.M) is None, f"ships {field}"
    assert re.search(r"^\s+orderId:", block, re.M) is not None


def test_modify_order_from_a_default_node_preserves_the_live_contract():
    live = {
        "orderid": "25082800018",
        "symbol": "NIFTY28MAR2420800CE",
        "exchange": "NFO",
        "action": "SELL",
        "product": "NRML",
        "pricetype": "LIMIT",
        "quantity": "150",
        "price": 42.5,
        "trigger_price": 0,
    }
    client, _ = _modify({"orderId": "25082800018", "newPrice": "44.0"}, order=live)

    assert client.sent["exchange"] == "NFO"
    assert client.sent["action"] == "SELL"
    assert client.sent["product_type"] == "NRML"
    assert client.sent["quantity"] == 150


# ---------------------------------------------------------------------------
# FLOW-016 / FLOW-013: order constants and node shapes checked before run time
# ---------------------------------------------------------------------------

_VALID_ORDER = {
    "symbol": "SBIN",
    "exchange": "NSE",
    "action": "BUY",
    "quantity": 10,
    "product": "MIS",
    "priceType": "MARKET",
}


def _validate(node_type, data):
    from services.flow_workflow_validator import validate_workflow

    position = {"x": 0, "y": 0}
    workflow = {
        "name": "t",
        "nodes": [
            {"id": "n1", "type": "start", "position": position, "data": {}},
            {"id": "n2", "type": node_type, "position": position, "data": data},
        ],
        "edges": [{"id": "e1", "source": "n1", "target": "n2"}],
    }
    return [e["code"] for e in validate_workflow(workflow, strict=True)]


def test_a_valid_order_node_validates_clean():
    assert _validate("placeOrder", _VALID_ORDER) == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("exchange", "NSEE"),
        ("action", "BUYY"),
        ("product", "INTRADAY"),
        ("priceType", "LIMT"),
    ],
)
def test_invalid_order_constants_are_refused(field, value):
    """Several broker mappers substitute a default for an unrecognised value
    rather than rejecting it, so a typo became a different order."""
    assert "invalid_constant" in _validate("placeOrder", {**_VALID_ORDER, field: value})


@pytest.mark.parametrize("quantity", [0, -5, "abc"])
def test_non_positive_quantities_are_refused(quantity):
    assert "invalid_quantity" in _validate("placeOrder", {**_VALID_ORDER, "quantity": quantity})


@pytest.mark.parametrize("field", ["exchange", "action", "quantity"])
def test_variables_are_left_for_the_executor_to_resolve(field):
    """These are only knowable at run time, where the order-node check applies."""
    assert _validate("placeOrder", {**_VALID_ORDER, field: "{{webhook.value}}"}) == []


def test_constants_are_case_insensitive():
    assert _validate("placeOrder", {**_VALID_ORDER, "exchange": "nse", "action": "buy"}) == []


@pytest.mark.parametrize(
    "data,code",
    [
        ({"url": "https://x.com", "headers": "{not json}"}, "invalid_headers"),
        ({"url": "https://x.com", "headers": '["a"]'}, "invalid_headers"),
        ({"url": "https://x.com", "timeout": 999999}, "invalid_timeout"),
        ({"url": "https://x.com", "timeout": 0}, "invalid_timeout"),
    ],
)
def test_http_request_shape_is_checked_before_run_time(data, code):
    """These previously only failed once the node executed."""
    assert code in _validate("httpRequest", data)


def test_valid_http_request_validates_clean():
    assert (
        _validate(
            "httpRequest",
            {"url": "https://x.com", "headers": '{"A": "b"}', "timeout": 30000},
        )
        == []
    )


def test_no_scheduler_path_persists_the_api_key():
    """The custom-callback branch still passed self._api_key into job args."""
    import inspect

    from services.flow_scheduler_service import FlowScheduler

    source = inspect.getsource(FlowScheduler.add_workflow_job)

    assert "self._api_key" not in source.split("args=(")[1].split("),")[0]


# ---------------------------------------------------------------------------
# FLOW-016 / FLOW-013 / FLOW-015: value rules the audit found still open
# ---------------------------------------------------------------------------


def _validate_lenient(node_type, data):
    """The path an ordinary editor save takes."""
    from services.flow_workflow_validator import validate_workflow

    position = {"x": 0, "y": 0}
    workflow = {
        "name": "t",
        "nodes": [
            {"id": "n1", "type": "start", "position": position, "data": {}},
            {"id": "n2", "type": node_type, "position": position, "data": data},
        ],
        "edges": [{"id": "e1", "source": "n1", "target": "n2"}],
    }
    return [e["code"] for e in validate_workflow(workflow, require_name=False, strict=False)]


def test_an_ordinary_save_rejects_an_invalid_constant():
    """Value checks were gated on `strict`, and the editor saves non-strict.

    A save therefore stored exactly the node the importer would have refused.
    """
    assert "invalid_constant" in _validate_lenient(
        "placeOrder", {**_VALID_ORDER, "exchange": "NSEE"}
    )


def test_an_ordinary_save_still_accepts_a_half_built_node():
    """Presence checks must stay strict-only, or the editor cannot save at all."""
    assert _validate_lenient("placeOrder", {}) == []


@pytest.mark.parametrize("value", [123, True, 4.5])
def test_a_non_string_constant_is_the_wrong_type(value):
    """The check skipped non-strings, so `"exchange": 123` reached the mapper."""
    assert "invalid_constant" in _validate("placeOrder", {**_VALID_ORDER, "exchange": value})


@pytest.mark.parametrize(
    "price_type,field,value",
    [
        ("LIMIT", "price", 0),
        ("LIMIT", "price", -10),
        ("SL", "price", 0),
        ("SL-M", "triggerPrice", 0),
    ],
)
def test_a_priced_order_needs_a_price(price_type, field, value):
    """A LIMIT at 0 is not "unset" -- it is an order nobody priced."""
    data = {**_VALID_ORDER, "priceType": price_type, field: value}
    assert "invalid_price" in _validate("placeOrder", data)


def test_a_market_order_may_leave_price_at_zero():
    assert _validate("placeOrder", {**_VALID_ORDER, "priceType": "MARKET", "price": 0}) == []


def test_a_priced_order_with_a_variable_is_left_to_the_executor():
    data = {**_VALID_ORDER, "priceType": "LIMIT", "price": "{{webhook.px}}"}
    assert _validate("placeOrder", data) == []


@pytest.mark.parametrize("method", ["TRACE", "CONNECT", "OPTIONS"])
def test_unimplemented_http_methods_are_refused(method):
    """These reached the node and returned "Unsupported method" at run time."""
    assert "invalid_method" in _validate("httpRequest", {"url": "https://x.com", "method": method})


def test_implemented_http_methods_are_accepted():
    for method in ("GET", "POST", "PUT", "PATCH", "DELETE"):
        assert _validate("httpRequest", {"url": "https://x.com", "method": method}) == []


@pytest.mark.parametrize("timeout", [1, 10, 999])
def test_an_unusably_short_timeout_is_refused(timeout):
    """1 ms is not a fast request, it is a request that can only ever fail."""
    assert "invalid_timeout" in _validate(
        "httpRequest", {"url": "https://x.com", "timeout": timeout}
    )


_INDICATOR = {"symbol": "SBIN", "exchange": "NSE", "indicatorName": "rsi"}


def test_object_form_indicator_params_are_refused_at_import():
    """The object form imported cleanly and then failed the run on json.loads."""
    assert "invalid_params" in _validate("indicator", {**_INDICATOR, "params": {"period": 14}})


def test_string_form_indicator_params_are_accepted():
    assert _validate("indicator", {**_INDICATOR, "params": '{"period": 14}'}) == []


def test_the_executor_normalises_legacy_object_params():
    """Already-stored graphs must keep working; the validator stops new ones.

    Asserted against the source rather than by running the node: importing the
    indicator service pulls in `openalgo.ta`, and under pytest the repository
    directory shadows that package.
    """
    import inspect

    source = inspect.getsource(fes.NodeExecutor.execute_indicator)

    assert "isinstance(params_value, dict)" in source
    normalise_at = source.index("isinstance(params_value, dict)")
    parse_at = source.index("json.loads(params_raw)")
    assert normalise_at < parse_at, "a dict must be handled before it reaches json.loads"


# ---------------------------------------------------------------------------
# FLOW-003: the jobstore and the database are reconciled at startup
# ---------------------------------------------------------------------------


class _FakeJob:
    def __init__(self, job_id):
        self.id = job_id


class _FakeScheduler:
    def __init__(self, jobs, existing=()):
        self._jobs = [_FakeJob(j) for j in jobs]
        self._existing = set(existing)
        self.removed = []
        self.added = []

    def get_all_jobs(self):
        return list(self._jobs)

    def remove_job(self, job_id, strict=False):
        self.removed.append(job_id)
        return True

    def get_workflow_job(self, workflow_id):
        return _FakeJob(f"flow_workflow_{workflow_id}") if workflow_id in self._existing else None

    def add_workflow_job(self, workflow_id, **kwargs):
        self.added.append(workflow_id)
        return f"flow_workflow_{workflow_id}"


def _schedule_workflow(workflow_id, is_active=True, schedule_type="daily"):
    return types.SimpleNamespace(
        id=workflow_id,
        is_active=is_active,
        nodes=[{"type": "start", "data": {"scheduleType": schedule_type, "time": "09:15"}}],
    )


def _reconcile(monkeypatch, scheduler, workflows):
    import database.flow_db as flow_db
    import services.flow_scheduler_service as sched

    by_id = {w.id: w for w in workflows}
    monkeypatch.setattr(sched, "get_flow_scheduler", lambda: scheduler)
    monkeypatch.setattr(flow_db, "get_workflow", lambda wid: by_id.get(wid))
    monkeypatch.setattr(
        flow_db, "get_active_workflows", lambda: [w for w in workflows if w.is_active]
    )
    monkeypatch.setattr(flow_db, "set_schedule_job_id", lambda wid, job_id: True)
    return sched.reconcile_scheduler_jobs()


def test_reconciliation_removes_a_job_whose_workflow_is_inactive(monkeypatch):
    """The jobstore is persistent, so a stale job is restored at every boot and
    keeps trading a workflow the user believes is switched off."""
    scheduler = _FakeScheduler(["flow_workflow_7"])

    result = _reconcile(monkeypatch, scheduler, [_schedule_workflow(7, is_active=False)])

    assert scheduler.removed == ["flow_workflow_7"]
    assert result["removed"] == 1


def test_reconciliation_removes_a_job_whose_workflow_is_gone(monkeypatch):
    scheduler = _FakeScheduler(["flow_workflow_9"])

    result = _reconcile(monkeypatch, scheduler, [])

    assert scheduler.removed == ["flow_workflow_9"]
    assert result["removed"] == 1


def test_reconciliation_restores_a_missing_job_for_an_active_workflow(monkeypatch):
    """Active with nothing registered reports Active and never fires, and
    activate refuses it as already_active."""
    scheduler = _FakeScheduler([])

    result = _reconcile(monkeypatch, scheduler, [_schedule_workflow(3)])

    assert scheduler.added == [3]
    assert result["restored"] == 1


def test_reconciliation_leaves_a_consistent_pair_alone(monkeypatch):
    scheduler = _FakeScheduler(["flow_workflow_5"], existing={5})

    result = _reconcile(monkeypatch, scheduler, [_schedule_workflow(5)])

    assert scheduler.removed == []
    assert scheduler.added == []
    assert result == {"removed": 0, "restored": 0}


def test_reconciliation_ignores_manual_workflows(monkeypatch):
    """A manual workflow has no schedule, so it is not a missing job."""
    scheduler = _FakeScheduler([])

    result = _reconcile(monkeypatch, scheduler, [_schedule_workflow(4, schedule_type="manual")])

    assert scheduler.added == []
    assert result["restored"] == 0


def test_reconciliation_ignores_jobs_it_does_not_own(monkeypatch):
    """The jobstore is shared; only flow_workflow_* ids belong to Flow."""
    scheduler = _FakeScheduler(["squareoff_12", "flow_workflow_notanint"])

    result = _reconcile(monkeypatch, scheduler, [])

    assert scheduler.removed == []
    assert result["removed"] == 0


def test_startup_runs_the_reconciliation():
    """Wired next to the other Flow restorations, or it never runs."""
    source = open("app.py", encoding="utf-8").read()

    assert "reconcile_scheduler_jobs" in source
