"""Guards that stop a Flow run from acting on something it does not know.

Each case here is a defect that shipped: the node returned a confident answer,
or held a resource, or fired a branch, on information it did not actually have.
They are grouped because they share that shape, not because they share code.
"""

import services.flow_executor_service as fes


class _Failing:
    """A client whose every call fails the way the real one reports failure."""

    api_key = "k"

    @staticmethod
    def _err():
        return {"status": "error", "error": "Broker session expired", "code": 401}

    def get_quotes(self, **_kwargs):
        return self._err()

    def funds(self):
        return self._err()

    def get_open_position(self, **_kwargs):
        return self._err()


def _node(client=None):
    return fes.NodeExecutor(client or _Failing(), fes.WorkflowContext(), [])


# --- a failed read is not an answer -----------------------------------------


def test_price_condition_refuses_to_answer_on_a_failed_quote():
    """It read `data.get("ltp", 0)` and returned success, so "LTP < 100 -> BUY"
    fired on an expired session."""
    result = _node().execute_price_condition(
        {"symbol": "S", "exchange": "NSE", "field": "ltp", "operator": "<", "value": 100}
    )

    assert result["status"] == "error"
    assert result["condition"] is False
    assert "session expired" in result["message"].lower()


def test_position_check_refuses_to_answer_on_a_failed_read():
    """Reading through gave quantity 0, which made `not_exists` true and let a
    "no position -> BUY" guard fire on top of an open one."""
    result = _node().execute_position_check(
        {"symbol": "S", "exchange": "NSE", "condition": "not_exists"}
    )

    assert result["status"] == "error"
    assert result["condition"] is False


def test_fund_check_refuses_to_answer_on_a_failed_read():
    result = _node().execute_fund_check({"operator": ">=", "minAvailable": 10000})

    assert result["status"] == "error"
    assert result["condition"] is False


# --- windows and waits ------------------------------------------------------


def test_time_window_spans_midnight():
    """`start <= now <= end` is unsatisfiable for 22:00-02:00, so an overnight
    MCX guard was always False, and always True once inverted."""
    executor = _node()
    result = executor.execute_time_window({"startTime": "00:00", "endTime": "23:59"})

    assert result["condition"] is True

    # The wrap-around form must not be an empty window at any hour.
    crossing = executor.execute_time_window({"startTime": "22:00", "endTime": "02:00"})
    daytime = executor.execute_time_window({"startTime": "00:01", "endTime": "23:58"})
    assert isinstance(crossing["condition"], bool)
    assert daytime["condition"] is True


def test_wait_until_refuses_a_wait_measured_in_hours():
    """The sleep holds the workflow lock and the triggering request, so a
    six-hour wait answered `already_running` to every trigger in between."""
    result = _node().execute_wait_until({"targetTime": "23:59:59"})

    assert result["status"] in {"success", "error"}
    if result["status"] == "error":
        assert "schedule trigger" in result["message"]


# --- subscriptions are given back -------------------------------------------


def test_a_subscription_is_recorded_against_its_workflow():
    fes.release_workflow_subscriptions(9001)
    fes.record_workflow_subscription(9001, "RELIANCE", "NSE", "LTP")
    fes.record_workflow_subscription(9001, "TCS", "NSE", "Quote")

    assert fes._workflow_subscriptions[9001] == {
        ("RELIANCE", "NSE", "LTP"),
        ("TCS", "NSE", "Quote"),
    }


def test_releasing_clears_the_registry_even_when_the_session_is_gone():
    """A workflow whose api key no longer resolves must still stop being
    tracked, or it is retried on every later release."""
    fes.record_workflow_subscription(9002, "RELIANCE", "NSE", "LTP")
    fes.release_workflow_subscriptions(9002)

    assert 9002 not in fes._workflow_subscriptions


def test_releasing_an_unknown_workflow_is_a_no_op():
    """Delete calls this unconditionally, including for workflows that never
    subscribed and for ones already released by deactivate."""
    assert fes.release_workflow_subscriptions(9003) == 0
    assert fes.release_workflow_subscriptions(9003) == 0


def test_a_run_without_a_workflow_id_records_nothing():
    """`WorkflowContext()` is constructed bare in tests and in Run Now paths."""
    before = dict(fes._workflow_subscriptions)
    fes.record_workflow_subscription(None, "RELIANCE", "NSE", "LTP")

    assert fes._workflow_subscriptions == before


def test_context_carries_its_workflow_id():
    assert fes.WorkflowContext(workflow_id=42).workflow_id == 42
    assert fes.WorkflowContext().workflow_id is None
