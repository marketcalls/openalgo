"""Strategy-module order dispatch.

What matters here is which pipe an order goes down, what happens when
authorisation is missing, and that a rule-driven exit closes a position rather
than adding to it.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

# Imported for their side effect: patch() resolves a dotted target by importing
# it, and "services.place_order_service" is only an attribute of the services
# package once the submodule has been imported somewhere.
#
# restx_api goes first deliberately. services.place_order_service imports
# restx_api.schemas, and restx_api imports options_multiorder, which imports
# place_order_service straight back - so making place_order_service the entry
# point of that cycle fails with a partially initialised module. The app never
# hits it because restx_api is always loaded first; this mirrors that order.
import restx_api  # noqa: F401
import services.cancel_order_service  # noqa: F401
import services.orderstatus_service  # noqa: F401
import services.place_order_service  # noqa: F401
import services.sandbox_service  # noqa: F401
from services.strategy_module import order_dispatch as od

# ---------------------------------------------------------------------------
# Exit action
# ---------------------------------------------------------------------------


def test_an_exit_reverses_the_side_the_leg_actually_holds():
    assert od.exit_action("B") == "SELL"
    assert od.exit_action("S") == "BUY"
    assert od.exit_action("b") == "SELL"


def test_an_exit_refuses_to_guess_a_side():
    # PORTED DEFECT. The original derives the exit action from the leg's
    # CONFIGURED side, which defaults to "B" for every leg including short ones.
    # A rule-driven exit on a short leg therefore placed another SELL and
    # doubled the position instead of covering it. Refusing beats defaulting.
    for bad in (None, "", "LONG", "SHORT", "x"):
        with pytest.raises(ValueError):
            od.exit_action(bad)


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


def _order():
    return od.build_order(
        symbol="NIFTY28MAY2624000CE",
        exchange="NFO",
        action="SELL",
        quantity=75,
        product="NRML",
        strategy_name="Iron condor weekly",
    )


def test_a_sandbox_run_goes_to_the_sandbox_pipe():
    with patch("services.sandbox_service.sandbox_place_order") as sandbox:
        sandbox.return_value = (True, {"status": "success", "orderid": "SB-1"}, 200)

        result = od.dispatch_order(mode="sandbox", api_key="k", order=_order())

    assert result.ok is True
    assert result.broker_order_id == "SB-1"
    assert sandbox.call_count == 1


def test_a_sandbox_retry_cancel_uses_the_run_pipe_not_the_global_toggle():
    with patch("services.sandbox_service.sandbox_cancel_order") as sandbox:
        sandbox.return_value = (True, {"status": "success", "orderid": "SB-RETRY"}, 200)

        result = od.cancel_exit_order(
            mode="sandbox",
            api_key="k",
            broker_order_id="SB-RETRY",
        )

    assert result.ok is True
    assert result.broker_order_id == "SB-RETRY"
    assert sandbox.call_args.args[0] == {"orderid": "SB-RETRY"}


def test_a_live_run_goes_to_the_broker_pipe_with_resolved_auth():
    with (
        patch("database.auth_db.get_auth_token_broker", return_value=("tok", "zerodha")),
        patch("services.place_order_service.place_order_with_auth") as live,
    ):
        live.return_value = (True, {"status": "success", "orderid": "250101000123"}, 200)

        result = od.dispatch_order(mode="live", api_key="k", order=_order())

    assert result.ok is True
    assert result.broker_order_id == "250101000123"
    args = live.call_args[0]
    assert args[1] == "tok"
    assert args[2] == "zerodha"


def test_a_live_retry_cancel_calls_the_resolved_broker_directly():
    with (
        patch("database.auth_db.get_auth_token_broker", return_value=("tok", "zerodha")),
        patch("services.cancel_order_service.import_broker_module") as import_broker,
    ):
        broker_module = import_broker.return_value
        broker_module.cancel_order.return_value = ({"status": "success"}, 200)

        result = od.cancel_exit_order(
            mode="live",
            api_key="k",
            broker_order_id="LIVE-RETRY",
        )

    assert result.ok is True
    assert result.broker_order_id == "LIVE-RETRY"
    broker_module.cancel_order.assert_called_once_with("LIVE-RETRY", "tok")


def test_a_sandbox_status_poll_uses_the_sandbox_orderstatus_pipe():
    broker_fact = {
        "orderid": "SB-WORKING",
        "order_status": "cancelled",
        "filled_quantity": 0,
    }
    with patch("services.sandbox_service.sandbox_get_order_status") as sandbox:
        sandbox.return_value = (True, {"status": "success", "data": broker_fact}, 200)

        result = od.fetch_order_status(
            mode="sandbox",
            api_key="k",
            broker_order_id="SB-WORKING",
        )

    assert result.ok is True
    assert result.order == broker_fact
    assert sandbox.call_args.args[0] == {"orderid": "SB-WORKING"}
    assert sandbox.call_args.args[1] == "k"


def test_a_live_status_poll_uses_resolved_auth_and_the_shared_orderbook_path():
    broker_fact = {
        "orderid": "LIVE-WORKING",
        "order_status": "complete",
        "filled_quantity": 25,
        "average_price": 101.25,
    }
    with (
        patch("database.auth_db.get_auth_token_broker", return_value=("tok", "zerodha")),
        patch("services.orderstatus_service.get_order_status") as status,
    ):
        status.return_value = (True, {"status": "success", "data": broker_fact}, 200)

        result = od.fetch_order_status(
            mode="live",
            api_key="k",
            broker_order_id="LIVE-WORKING",
        )

    assert result.ok is True
    assert result.order == broker_fact
    status.assert_called_once_with(
        {"orderid": "LIVE-WORKING"},
        auth_token="tok",
        broker="zerodha",
    )


def test_an_unknown_mode_is_refused_rather_than_defaulted():
    # Defaulting an unrecognised mode to live would place a real order for a
    # run the operator believed was on paper.
    result = od.dispatch_order(mode="", api_key="k", order=_order())

    assert result.ok is False
    assert "Unknown run mode" in result.error


def test_a_live_order_is_not_attempted_when_the_broker_session_is_gone():
    # Refusing and saying so leaves a recoverable situation. Attempting it
    # without auth and reporting success would not.
    with (
        patch("database.auth_db.get_auth_token_broker", return_value=(None, None)),
        patch("services.place_order_service.place_order_with_auth") as live,
    ):
        result = od.dispatch_order(mode="live", api_key="k", order=_order())

    assert result.ok is False
    assert "expired" in result.error or "not available" in result.error
    assert live.call_count == 0


def test_dispatch_does_not_go_through_the_semi_automatic_approval_queue():
    # place_order() routes API-key orders into Action Center when semi-auto is
    # on. A stop-loss exit that waits for a human to approve it is not a stop
    # loss, so this module calls place_order_with_auth instead.
    with (
        patch("database.auth_db.get_auth_token_broker", return_value=("tok", "zerodha")),
        patch("services.place_order_service.place_order_with_auth") as live,
        patch("services.place_order_service.place_order") as queued,
    ):
        live.return_value = (True, {"status": "success", "orderid": "1"}, 200)

        od.dispatch_order(mode="live", api_key="k", order=_order())

    assert live.call_count == 1
    assert queued.call_count == 0


# ---------------------------------------------------------------------------
# Failure handling
# ---------------------------------------------------------------------------


def test_a_rejection_is_reported_with_its_reason_and_any_reference():
    with patch("services.sandbox_service.sandbox_place_order") as sandbox:
        sandbox.return_value = (
            False,
            {"status": "error", "message": "Insufficient margin", "orderid": "SB-9"},
            400,
        )

        result = od.dispatch_order(mode="sandbox", api_key="k", order=_order())

    assert result.ok is False
    assert result.error == "Insufficient margin"
    # A rejected order can still carry a reference, and the audit row is more
    # useful with it than without.
    assert result.broker_order_id == "SB-9"


def test_a_raising_pipe_becomes_a_failed_result_not_an_exception():
    # The engine places orders in a loop across legs. One raising placement
    # must not abort the others or unwind the run.
    with patch("services.sandbox_service.sandbox_place_order", side_effect=RuntimeError("boom")):
        result = od.dispatch_order(mode="sandbox", api_key="k", order=_order())

    assert result.ok is False
    assert result.error


def test_a_pipe_answering_with_something_other_than_a_dict_does_not_crash():
    with patch("services.sandbox_service.sandbox_place_order", return_value=(True, None, 200)):
        result = od.dispatch_order(mode="sandbox", api_key="k", order=_order())

    assert result.ok is True
    assert result.broker_order_id is None


# ---------------------------------------------------------------------------
# Payload
# ---------------------------------------------------------------------------


def test_the_payload_matches_what_the_rest_of_the_order_path_sends():
    order = od.build_order(
        symbol="RELIANCE",
        exchange="NSE",
        action="buy",
        quantity=10,
        product="MIS",
        strategy_name="Test",
    )

    assert order["action"] == "BUY"
    assert order["quantity"] == "10"  # string, like every other caller
    assert order["price"] == "0"
    assert order["trigger_price"] == "0"
    assert order["strategy"] == "Test"
    assert order["pricetype"] == "MARKET"


# ---------------------------------------------------------------------------
# The analyzer toggle must not decide a run's pipe
# ---------------------------------------------------------------------------


def test_a_live_order_is_not_diverted_by_the_platform_analyzer_toggle():
    # The one control this module is built around, exercised against the real
    # place_order_with_auth rather than a mock of it. That distinction matters:
    # every other test here mocks that function, so the diversion it is meant
    # to prevent was invisible.
    #
    # place_order_with_auth consults the global toggle BEFORE it looks at the
    # broker arguments. Without force_live, an operator turning the analyzer on
    # to try something elsewhere would send a live run's exits to the sandbox,
    # which reports success, so the engine would close the leg and finalise the
    # run while the real broker position stayed open with nothing managing it.
    with (
        patch("database.auth_db.get_auth_token_broker", return_value=("tok", "zerodha")),
        patch("services.place_order_service.get_analyze_mode", return_value=True),
        patch("services.sandbox_service.sandbox_place_order") as sandbox,
        patch("services.place_order_service.import_broker_module") as import_broker,
        # The symbol is not in this suite's throwaway master contract, and an
        # order that fails validation never reaches the branch under test.
        patch(
            "services.place_order_service.validate_order_data",
            return_value=(True, {}, None),
        ),
    ):
        broker_module = import_broker.return_value
        broker_module.place_order_api.return_value = (
            SimpleNamespace(status=200),
            {},
            "BROKER-1",
        )

        result = od.dispatch_order(mode="live", api_key="k", order=_order())

    # The broker was called and the sandbox was not, despite the toggle.
    assert sandbox.call_count == 0, "a live run must not be diverted into the sandbox"
    assert result.ok is True, f"dispatch failed: {result}"
    assert broker_module.place_order_api.call_count == 1
    assert result.ok is True
    assert result.broker_order_id == "BROKER-1"


def test_a_sandbox_order_still_goes_to_the_sandbox_with_the_toggle_off():
    # The other direction: a sandbox run must never reach a real broker,
    # whatever the platform toggle says.
    with (
        patch("services.place_order_service.get_analyze_mode", return_value=False),
        patch("services.sandbox_service.sandbox_place_order") as sandbox,
        patch("services.place_order_service.place_order_with_auth") as live,
    ):
        sandbox.return_value = (True, {"status": "success", "orderid": "SB-1"}, 200)

        result = od.dispatch_order(mode="sandbox", api_key="k", order=_order())

    assert sandbox.call_count == 1
    assert live.call_count == 0
    assert result.broker_order_id == "SB-1"
