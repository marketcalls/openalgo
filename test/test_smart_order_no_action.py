"""A smart order that places nothing must not be reported as a placed order.

Issue #2054: closing a position the user does not hold - clicking the red X on
an empty positions page - sent "Smart Order Placed" to Telegram and WhatsApp
with "Order ID: N/A", for an order the engine had deliberately skipped. The
terminal logged "No OpenPosition Found. Not placing Exit order." at the same
moment, so the backend knew.

The cause is not the inverted control flow the report suspected. The alert
services are handed the broker response and run after it, and there is already
a dedicated `order.no_action` event that both channels subscribe to. The cause
is that a smart order has *two* do-nothing outcomes and only one was ever
recognised. Every broker adapter returns, with no API call made:

    "No action needed. Position size matches current position"   (quantity != 0)
    "No OpenPosition Found. Not placing Exit order."             (quantity == 0)

`services/sandbox_service.py` produces the same pair, and
`frontend/src/hooks/useSocket.ts` already treats both as informational. Only
the first was matched in `place_smart_order_service`, so the second fell
through: to `OrderPlacedEvent` in analyze mode (the false alert), and to
`OrderFailedEvent` with HTTP 500 in live mode (a benign no-op reported as a
failure).

These are static and pure-function checks. They do not need a broker session, a
running server or market hours.
"""

import ast
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SERVICE_PATH = REPO / "services" / "place_smart_order_service.py"
SANDBOX_PATH = REPO / "services" / "sandbox_service.py"
USESOCKET_PATH = REPO / "frontend" / "src" / "hooks" / "useSocket.ts"

NO_POSITION = "No OpenPosition Found. Not placing Exit order."
ALREADY_MATCHED = "No action needed. Position size matches current position"


# ---------------------------------------------------------------------------
# The predicate itself
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def is_no_action():
    from services.place_smart_order_service import is_no_action_response

    return is_no_action_response


@pytest.mark.parametrize(
    "message",
    [
        NO_POSITION,
        ALREADY_MATCHED,
        "Positions Already Matched. No Action needed.",
    ],
)
def test_every_do_nothing_message_is_recognised(is_no_action, message):
    """THE DEFECT: only the 'No action needed' wording used to count."""
    assert is_no_action({"status": "success", "message": message}) is True


def test_a_placed_order_is_not_no_action(is_no_action):
    assert is_no_action({"status": "success", "orderid": "251114000123"}) is False


def test_a_failure_is_not_no_action(is_no_action):
    """A failed response must not be read as a successful no-op.

    Written as an inline expression the status check bound only to the first
    marker, so `{"status": "error", "message": "... Already Matched ..."}`
    satisfied the whole condition through the trailing `or`.
    """
    assert is_no_action({"status": "error", "message": "Already Matched"}) is False
    assert is_no_action({"status": "error", "message": NO_POSITION}) is False


def test_malformed_responses_do_not_raise(is_no_action):
    assert is_no_action({}) is False
    assert is_no_action({"status": "success"}) is False
    assert is_no_action({"status": "success", "message": None}) is False
    assert is_no_action(None) is False


# ---------------------------------------------------------------------------
# The alert wording
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module", params=["telegram", "whatsapp"])
def alert_service(request):
    """Both channels, checked identically: they must not describe it differently.

    Returns the module (for its helpers) and the service singleton (for its
    templates and formatter).
    """
    if request.param == "telegram":
        from services import telegram_alert_service as module

        return module, module.telegram_alert_service

    from services import whatsapp_alert_service as module

    return module, module.whatsapp_alert_service


SMART_ORDER_REQUEST = {
    "symbol": "NIFTY25SEP2625000CE",
    "action": "SELL",
    "quantity": 0,
    "position_size": 0,
    "exchange": "NFO",
}


def _rendered_alert(alert_service, response):
    """The full alert text the user would receive, headline included.

    Mirrors the two steps send_order_alert() performs once it has resolved a
    recipient, which is the part that needs a linked account and a network.
    """
    module, service = alert_service
    template_key = (
        "placesmartorder_no_action"
        if module._placed_nothing("placesmartorder", response)
        else "placesmartorder"
    )
    template = service.alert_templates[template_key]
    details = service.format_order_details("placesmartorder", SMART_ORDER_REQUEST, response)
    return template.format(details=details)


def test_no_action_alert_does_not_claim_an_order_was_placed(alert_service):
    """THE DEFECT: the headline said Placed and the body said 'Order ID: N/A'."""
    response = {"status": "success", "message": NO_POSITION, "mode": "live"}
    message = _rendered_alert(alert_service, response)

    assert "Smart Order Placed" not in message
    assert "Order ID" not in message
    assert "N/A" not in message


def test_no_action_alert_states_the_reason(alert_service):
    """A trader must be told why nothing happened, not just that it didn't."""
    response = {"status": "success", "message": NO_POSITION, "mode": "live"}
    message = _rendered_alert(alert_service, response)

    assert NO_POSITION in message
    assert "No Action Taken" in message


def test_a_real_smart_order_still_reports_its_order_id(alert_service):
    """The fix must not swallow the order id on an order that did go in."""
    response = {"status": "success", "orderid": "251114000123", "mode": "live"}
    message = _rendered_alert(alert_service, response)

    assert "Smart Order Placed" in message
    assert "251114000123" in message
    assert "No Action Taken" not in message


def test_placed_nothing_only_applies_to_smart_orders(alert_service):
    """A plain placeorder success without an id must not take this path."""
    module, _ = alert_service
    assert module._placed_nothing("placeorder", {"status": "success"}) is False
    assert module._placed_nothing("placesmartorder", {"status": "error"}) is False


def test_a_lost_order_id_is_not_called_a_no_action(alert_service):
    """A success with neither an id nor a reason must not claim nothing happened.

    An adapter that returns 200 but whose order id failed to parse produces
    exactly that shape. Announcing "No order was placed" for it would be a
    false statement about a live order, which is worse than the vague line it
    replaced, so the message half of the shape test is required.
    """
    module, _ = alert_service
    lost_id = {"status": "success", "mode": "live"}

    assert module._placed_nothing("placesmartorder", lost_id) is False

    message = _rendered_alert(alert_service, lost_id)
    assert "Smart Order Placed" in message
    assert "No Action Taken" not in message
    assert "No order was placed" not in message
    assert "N/A" in message


# ---------------------------------------------------------------------------
# The contract with the rest of the platform
# ---------------------------------------------------------------------------


def test_the_service_no_longer_matches_one_message_inline():
    """Pins the shape of the fix: one predicate, not a literal per branch.

    The two call sites drifted apart precisely because each spelled the check
    out itself. If a third do-nothing message ever appears, it must be added to
    NO_ACTION_MARKERS and be picked up by both paths at once.
    """
    source = SERVICE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(SERVICE_PATH))

    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "is_no_action_response" in called

    body = source.split("def place_smart_order_with_auth", 1)[-1]
    assert body.count("is_no_action_response(") >= 2, (
        "both the analyze path and the live path must use the shared predicate"
    )


def test_markers_cover_every_message_the_adapters_emit():
    """The sandbox is the reference implementation every broker adapter mirrors."""
    from services.place_smart_order_service import NO_ACTION_MARKERS

    sandbox = SANDBOX_PATH.read_text(encoding="utf-8")
    assert NO_POSITION in sandbox

    for message in (NO_POSITION, "Positions Already Matched. No Action needed."):
        assert any(marker in message for marker in NO_ACTION_MARKERS), message


def test_frontend_and_backend_agree_on_what_no_action_looks_like():
    """The toast already treated both messages as info while the backend did not.

    That mismatch is what made the live case surface as "Error: No OpenPosition
    Found" rather than the informational toast the hook was written to show.

    Only the placesmartorder branch is read, and only for the two markers this
    module knows about. Scanning every `message.includes` in the hook would
    make an unrelated toast elsewhere in the file fail this test and point the
    blame at the backend.
    """
    from services.place_smart_order_service import NO_ACTION_MARKERS

    hook = USESOCKET_PATH.read_text(encoding="utf-8")
    branch = hook.split("apiType === 'placesmartorder'", 1)
    assert len(branch) == 2, "the hook no longer has a placesmartorder branch"
    branch = branch[1].split("} else {", 1)[0]

    frontend_markers = set(re.findall(r"message\.includes\('([^']+)'\)", branch))
    assert frontend_markers, "the placesmartorder branch matches no message"

    for marker in frontend_markers:
        assert any(marker in backend or backend in marker for backend in NO_ACTION_MARKERS), (
            f"the toast treats {marker!r} as no-action but the backend does not"
        )
    assert "No OpenPosition Found" in frontend_markers


def test_live_path_returns_success_not_a_failure():
    """A benign no-op must not reach the user as an error with HTTP 500.

    Before the fix "No OpenPosition Found" missed the guard, fell past the
    `res.status == 200` check with res None, and landed in the else branch that
    publishes OrderFailedEvent and returns 500.
    """
    source = SERVICE_PATH.read_text(encoding="utf-8")
    live = source.split("# Live Mode", 1)[-1]

    guard = "if res is None and is_no_action_response(response_data):"
    assert guard in live

    # Everything the guard covers, up to the return that closes it.
    block, _, _ = live.split(guard, 1)[-1].partition("return True, order_response_data, 200")
    assert block, "the no-action guard must return success"
    assert "SmartOrderNoActionEvent" in block
    assert "OrderFailedEvent" not in block
