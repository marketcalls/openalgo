"""A smart order that places nothing must not be reported as a placed order.

Issue #2054: closing a position the user does not hold - clicking the red X on
an empty positions page - sent "Smart Order Placed" to Telegram and WhatsApp
with "Order ID: N/A", for an order the engine had deliberately skipped. The
terminal logged "No OpenPosition Found. Not placing Exit order." at the same
moment, so the backend knew.

The cause is not the inverted control flow the report suspected. The alert
services are handed the broker response and run after it, and there is already
a dedicated `order.no_action` event that both channels subscribe to. The cause
is that the service recognised a do-nothing outcome by one wording, "No action
needed", and the adapters do not share a wording. The standard ones return
"No OpenPosition Found. Not placing Exit order." for the quantity == 0 case in
the report; definedge says "No position to square off", groww "No order action
needed", upstox lower-cases it, and tradejini sends no message at all. Every
unmatched wording fell through: to `OrderPlacedEvent` in analyze mode (the
false alert), and to `OrderFailedEvent` with HTTP 500 in live mode (a benign
no-op reported as a failure).

The fix reads the shape instead. An adapter that placed nothing made no API
call, so it returns `res` None and no order id; one that placed an order
returns the response object and the id. The sandbox is the same: a placed
sandbox order carries `orderid`, a no-action result does not.

The service is driven end to end with a stub adapter module and a fake event
bus, so nothing here needs a broker session, a running server or market hours.
"""

import ast
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SANDBOX_PATH = REPO / "services" / "sandbox_service.py"
USESOCKET_PATH = REPO / "frontend" / "src" / "hooks" / "useSocket.ts"

NO_POSITION = "No OpenPosition Found. Not placing Exit order."
SANDBOX_MATCHED = "Positions Already Matched. No Action needed."


# ---------------------------------------------------------------------------
# Every do-nothing shape a shipped adapter returns
# ---------------------------------------------------------------------------


class _Response:
    """What an adapter hands back after a real API call: an object with a status."""

    def __init__(self, status: int = 200):
        self.status = status


def _no_action(message):
    """(res, response, orderid) as returned when no API call was made."""
    return None, {"status": "success", "message": message}, None


#: Every distinct (res, response, orderid) triple a shipped adapter returns
#: from place_smartorder_api with no order placed, collected by walking every
#: smart-order function under broker/ (test_every_success_wording_in_the_tree_
#: is_listed keeps this current). None of them is matched by wording, so the
#: list is here to prove the shape rule holds for each real one, message or
#: not.
ADAPTER_NO_ACTION_RETURNS = {
    "standard_matched": _no_action("No action needed. Position size matches current position"),
    "standard_no_position": _no_action(NO_POSITION),
    "upstox_matched": _no_action("No action needed. Position size matches current position."),
    "upstox_no_position": _no_action("No open position found. Not placing exit order."),
    "zerodha_hdfcsky_arrow": _no_action("No action needed. Position already matched."),
    "iiflcapital": _no_action("No action needed. Position already aligned"),
    "deltaexchange_indmoney": _no_action("No action needed"),
    "ibulls_matched": _no_action("Position already matches target size of 100"),
    "definedge_fallback": _no_action("No action required"),
    "definedge_no_position": _no_action("No position to square off"),
    "definedge_matched": _no_action("Position already at target size"),
    "groww": _no_action("No order action needed. Position size matches current position"),
    # tradejini: no message at all, and an empty string where the id would be.
    "tradejini": (None, {"status": "success", "orderid": ""}, ""),
}

PLACED_ORDER_RETURN = (
    _Response(200),
    {"status": "success", "orderid": "251114000123"},
    "251114000123",
)

#: An order that went in, whose id the adapter failed to parse. It has a
#: response object, so it is not a no-action, whatever else it lacks.
LOST_ID_RETURN = (_Response(200), {"status": "success"}, None)

REJECTED_RETURN = (None, {"status": "error", "message": "Insufficient funds"}, None)


# ---------------------------------------------------------------------------
# The predicate itself
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def is_no_action():
    from services.place_smart_order_service import is_no_action_response

    return is_no_action_response


@pytest.mark.parametrize("name", sorted(ADAPTER_NO_ACTION_RETURNS))
def test_every_adapter_do_nothing_shape_is_recognised(is_no_action, name):
    """THE DEFECT: one wording was matched, and the adapters do not share one."""
    _res, response, orderid = ADAPTER_NO_ACTION_RETURNS[name]
    assert is_no_action(response, orderid) is True


def test_a_placed_order_is_not_no_action(is_no_action):
    _res, response, orderid = PLACED_ORDER_RETURN
    assert is_no_action(response, orderid) is False
    # The id beside the response counts even when the response omits it.
    assert is_no_action({"status": "success"}, "251114000123") is False


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
    assert is_no_action(None) is False
    assert is_no_action("success") is False


# ---------------------------------------------------------------------------
# The service, end to end, with a stub adapter and a fake bus
# ---------------------------------------------------------------------------


class _FakeBus:
    def __init__(self):
        self.events = []

    def publish(self, event):
        self.events.append(event)

    def topics(self):
        return [event.topic for event in self.events]


SMART_ORDER = {
    "apikey": "k",
    "symbol": "NIFTY25SEP2625000CE",
    "exchange": "NFO",
    "action": "SELL",
    "quantity": "0",
    "position_size": "0",
    "pricetype": "MARKET",
    "product": "MIS",
    "strategy": "test",
}


@pytest.fixture
def service(monkeypatch):
    """place_smart_order_with_auth with the broker, the bus and the mode stubbed.

    Returns a runner: give it the triple the adapter should return (or, in
    analyze mode, what the sandbox should return) and get back the service's
    (success, response, status) result and the bus that collected the events.
    """
    import types

    from services import place_smart_order_service as module

    def run(adapter_return, analyze=False, sandbox_return=None):
        bus = _FakeBus()
        monkeypatch.setattr(module, "bus", bus)
        monkeypatch.setattr(module, "get_analyze_mode", lambda: analyze)

        stub = types.SimpleNamespace(place_smartorder_api=lambda data, auth: adapter_return)
        monkeypatch.setattr(module, "import_broker_module", lambda name: stub)

        if analyze:
            import services.sandbox_service as sandbox

            monkeypatch.setattr(
                sandbox, "sandbox_place_smart_order", lambda data, key, original: sandbox_return
            )

        result = module.place_smart_order_with_auth(
            dict(SMART_ORDER), "token", "stub", dict(SMART_ORDER)
        )
        return result, bus

    return run


@pytest.mark.parametrize("name", sorted(ADAPTER_NO_ACTION_RETURNS))
def test_live_no_action_is_a_success_not_a_failure(service, name):
    """THE DEFECT in live mode: order.failed and HTTP 500 for a benign no-op."""
    (ok, response, status), bus = service(ADAPTER_NO_ACTION_RETURNS[name])

    assert (ok, status) == (True, 200)
    assert response["status"] == "success"
    assert "orderid" not in response
    assert bus.topics() == ["order.no_action"]

    event = bus.events[0]
    assert event.mode == "live"
    assert event.symbol == SMART_ORDER["symbol"]
    assert event.message == response["message"]
    assert event.response_data == response


def test_live_no_action_keeps_the_adapter_wording(service):
    """The adapter is the only party that knows why nothing was sent."""
    (_ok, response, _status), _bus = service(ADAPTER_NO_ACTION_RETURNS["definedge_no_position"])

    assert response["message"] == "No position to square off"


def test_live_no_action_without_a_message_still_says_why(service):
    """tradejini sends no message; the alerts and the toast need one."""
    (_ok, response, _status), bus = service(ADAPTER_NO_ACTION_RETURNS["tradejini"])

    assert response["message"]
    assert "No action needed" in response["message"]
    assert bus.events[0].message == response["message"]


def test_live_placed_order_is_still_a_placed_order(service):
    (ok, response, status), bus = service(PLACED_ORDER_RETURN)

    assert (ok, status) == (True, 200)
    assert response == {"status": "success", "orderid": "251114000123"}
    assert bus.topics() == ["order.placed"]
    assert bus.events[0].orderid == "251114000123"


def test_live_lost_order_id_is_not_called_a_no_action(service):
    """A response object with no id is an order that went in, not a no-op.

    Announcing "no order was placed" for it would be a false statement about
    a live order, so the shape rule needs res to be None as well.
    """
    _result, bus = service(LOST_ID_RETURN)

    assert bus.topics() == ["order.placed"]


def test_live_rejection_is_still_a_failure(service):
    (ok, response, status), bus = service(REJECTED_RETURN)

    assert (ok, status) == (False, 500)
    assert response == {"status": "error", "message": "Insufficient funds"}
    assert bus.topics() == ["order.failed"]


@pytest.mark.parametrize("message", [NO_POSITION, SANDBOX_MATCHED])
def test_analyze_no_action_is_not_announced_as_placed(service, message):
    """THE DEFECT in analyze mode: OrderPlacedEvent, and "Order ID: N/A" on the phone."""
    sandbox = (True, {"status": "success", "message": message, "mode": "analyze"}, 200)
    (ok, response, status), bus = service(None, analyze=True, sandbox_return=sandbox)

    assert (ok, status) == (True, 200)
    assert response["message"] == message
    assert bus.topics() == ["order.no_action"]
    assert bus.events[0].mode == "analyze"
    assert bus.events[0].message == message


def test_analyze_placed_order_is_still_a_placed_order(service):
    sandbox = (True, {"status": "success", "orderid": "SB0001", "mode": "analyze"}, 200)
    _result, bus = service(None, analyze=True, sandbox_return=sandbox)

    assert bus.topics() == ["order.placed"]
    assert bus.events[0].orderid == "SB0001"


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


def _smart_order_success_messages():
    """Every message literal returned beside a success status by a smart-order
    function in any adapter, keyed by adapter name.

    Walks the AST of every smart-order function (place_smartorder_api and the
    _place_smartorder_locked* helpers) with no keyword filter, so a wording
    that no assumption anticipated is reported rather than skipped. An
    f-string contributes its literal parts.
    """
    found = {}
    for path in sorted((REPO / "broker").glob("*/api/order_api.py")):
        broker = path.parent.parent.name
        tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        functions = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and "smartorder" in node.name.lower()
        ]
        for function in functions:
            for node in ast.walk(function):
                if not isinstance(node, ast.Dict):
                    continue
                keys = [key.value if isinstance(key, ast.Constant) else None for key in node.keys]
                if "status" not in keys or "message" not in keys:
                    continue
                status = node.values[keys.index("status")]
                if not (isinstance(status, ast.Constant) and status.value == "success"):
                    continue
                message = node.values[keys.index("message")]
                if isinstance(message, ast.Constant):
                    found.setdefault(broker, set()).add(message.value)
                elif isinstance(message, ast.JoinedStr):
                    prefix = "".join(
                        part.value for part in message.values if isinstance(part, ast.Constant)
                    )
                    found.setdefault(broker, set()).add(prefix)
    return found


def test_every_success_wording_in_the_tree_is_listed():
    """Keeps ADAPTER_NO_ACTION_RETURNS honest.

    A new adapter wording that the fixture above does not exercise fails
    here, at the point it is added, so the shape rule is proven against every
    real return and not against the ones someone remembered. Messages built
    from variables (iiflcapital, deltaexchange, upstox, ibulls' default) are
    listed by hand from the source.
    """
    listed = {
        response["message"]
        for _res, response, _orderid in ADAPTER_NO_ACTION_RETURNS.values()
        if "message" in response
    }
    found = _smart_order_success_messages()
    assert len(found) >= 20, "smart-order success messages went missing under broker/"

    unlisted = sorted(
        f"{broker}: {message}"
        for broker, messages in found.items()
        for message in messages
        if not any(message == item or item.startswith(message) for item in listed)
    )
    assert not unlisted, "adapter wordings the fixture does not exercise: " + "; ".join(unlisted)


def test_frontend_and_sandbox_agree_on_what_no_action_looks_like():
    """The analyzer toast reads the sandbox wording, and only that wording.

    In analyze mode the event carries the sandbox's message, and the hook
    decides from that text whether to show an info toast or announce an order
    placed. Both ends are in this repo, so pin them to each other. Only the
    placesmartorder branch is read: scanning every `message.includes` in the
    hook would make an unrelated toast fail this test.
    """
    sandbox = SANDBOX_PATH.read_text(encoding="utf-8")
    sandbox_messages = {NO_POSITION, SANDBOX_MATCHED}
    for message in sandbox_messages:
        assert message in sandbox, f"the sandbox no longer returns {message!r}"

    hook = USESOCKET_PATH.read_text(encoding="utf-8")
    branch = hook.split("apiType === 'placesmartorder'", 1)
    assert len(branch) == 2, "the hook no longer has a placesmartorder branch"
    branch = branch[1].split("} else {", 1)[0]

    frontend_markers = set(re.findall(r"message\.includes\('([^']+)'\)", branch))
    assert frontend_markers, "the placesmartorder branch matches no message"

    for marker in frontend_markers:
        assert any(marker in message for message in sandbox_messages), (
            f"the toast matches {marker!r} but the sandbox never sends it"
        )
    for message in sandbox_messages:
        assert any(marker in message for marker in frontend_markers), (
            f"the sandbox sends {message!r} but the toast would announce an order placed"
        )
