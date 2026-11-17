"""The agent-wide hook that turns a refused argument set into a correction.

Before it, a call that reached a tool with its arguments missing came back to
the model as pydantic's own text (``5 validation errors for
MarketToolkit.get_history ... input_value=ArgsKwargs(()) ... errors.pydantic.dev``)
and agno logged a traceback for an ordinary correction. These drive agno's real
``FunctionCall`` chain, so the hook is proven against the ``validate_call``
wrapper production uses rather than a stand-in.
"""

import pytest

pytest.importorskip("agno")

from agno.exceptions import RetryAgentRun, StopAgentRun
from agno.tools.function import Function, FunctionCall
from pydantic import BaseModel

from services.agent.tool_guard import argument_guard


class MarketToolkit:
    def get_history(self, symbol: str, exchange: str, days: int = 5) -> str:
        return f"{symbol}:{exchange}:{days}"

    def inner_model_fails(self, symbol: str) -> str:
        class Inner(BaseModel):
            value: int

        Inner(value="not a number")
        return symbol

    def stops(self, symbol: str) -> str:
        raise StopAgentRun("stop here")


def _call(method, arguments):
    function = Function.from_callable(method)
    function.tool_hooks = [argument_guard]
    function.process_entrypoint()
    return FunctionCall(function=function, arguments=arguments).execute()


def test_empty_arguments_become_a_named_correction():
    with pytest.raises(RetryAgentRun) as caught:
        _call(MarketToolkit().get_history, {})

    message = str(caught.value)
    assert "get_history" in message
    assert "did not arrive" in message
    assert "Missing: symbol, exchange." in message
    assert "pydantic" not in message and "ArgsKwargs" not in message


def test_a_wrong_type_names_the_argument():
    with pytest.raises(RetryAgentRun) as caught:
        _call(MarketToolkit().get_history, {"symbol": "TCS", "exchange": "NSE", "days": "x"})

    message = str(caught.value)
    assert "days" in message
    assert "did not arrive" not in message


def test_an_unknown_argument_is_named():
    with pytest.raises(RetryAgentRun) as caught:
        _call(MarketToolkit().get_history, {"symbol": "TCS", "exchange": "NSE", "ticker": "TCS"})

    assert "ticker" in str(caught.value)


def test_a_valid_call_runs_untouched():
    result = _call(MarketToolkit().get_history, {"symbol": "TCS", "exchange": "NSE"})

    assert result.status == "success"
    assert result.result == "TCS:NSE:5"


def test_a_validation_error_inside_the_tool_body_is_not_disguised():
    # A model failing deep inside a tool is a defect to see in the log, not a
    # correction to hand the model, so the guard lets it through.
    result = _call(MarketToolkit().inner_model_fails, {"symbol": "TCS"})

    assert result.status == "failure"
    assert "Inner" in (result.error or "")


def test_the_tool_s_own_run_exceptions_pass_through():
    with pytest.raises(StopAgentRun):
        _call(MarketToolkit().stops, {"symbol": "TCS"})


class TestMissingArgumentsBeforeApproval:
    """A paused call is decided before pydantic sees it, so the approval card is
    told which required arguments are absent. A tool with none required must
    never be reported as incomplete: cancel_all_orders takes no arguments."""

    def test_an_order_with_no_arguments_names_what_is_missing(self):
        from services.agent.tool_guard import missing_arguments

        missing = missing_arguments("place_order", {})
        assert {"symbol", "exchange", "action", "quantity"} <= set(missing)

    def test_null_and_empty_values_count_as_missing(self):
        from services.agent.tool_guard import missing_arguments

        missing = missing_arguments("place_order", {"symbol": "", "exchange": None})
        assert {"symbol", "exchange"} <= set(missing)

    def test_tools_that_take_no_arguments_are_complete(self):
        from services.agent.tool_guard import missing_arguments

        assert missing_arguments("cancel_all_orders", {}) == []
        assert missing_arguments("close_all_positions", {}) == []

    def test_an_unknown_tool_reports_nothing_missing(self):
        from services.agent.tool_guard import missing_arguments

        assert missing_arguments("no_such_tool", {}) == []

    def test_the_pause_payload_carries_the_missing_list(self):
        from types import SimpleNamespace

        from services.agent.stream import _requirement_payloads

        execution = SimpleNamespace(
            tool_call_id="c1",
            tool_name="place_order",
            tool_args={},
            requires_confirmation=True,
        )
        event = SimpleNamespace(requirements=[SimpleNamespace(id="r1", tool_execution=execution)])

        (payload,) = _requirement_payloads(event)
        assert "symbol" in payload["missing"]
