"""The operator who paired the device is a recipient, without a /link round trip.

OpenAlgo is single user. The rest of the WhatsApp bot already treats the paired
operator as the identity: ``_sdk_client_for_owner`` looks their API key up from
the owner recorded at pair time, and says why in its own comment, "so the
operator never has to /link or paste credentials from the phone".

``/api/v1/whatsapp/notify`` did not follow that rule. It resolved a username
only through ``whatsapp_users``, which is filled by a phone sending ``/link``.
So an operator who had paired their device and never messaged the bot was told
their own username was "not found or not linked to WhatsApp" while the
/whatsapp page showed the device paired and connected. A chart alert from
/trading asks for exactly that username, which is how it was found.

The second test is the one that matters more. A self-send with no captured
owner address used to be reported as delivered: the single-arg "route to owner"
form of the underlying library returns without error and nothing arrives, and
the send loop appended the recipient to ``sent`` anyway. For an alert that is
the failure worse than not sending, because the trader is told it went.
"""

import ast
from pathlib import Path

ROUTE = Path(__file__).resolve().parents[1] / "restx_api" / "whatsapp_bot.py"
SERVICE = Path(__file__).resolve().parents[1] / "services" / "whatsapp_bot_service.py"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _function(path: Path, name: str) -> str:
    """The source of one function, by name, anywhere in the file."""
    tree = ast.parse(_source(path))
    lines = _source(path).splitlines()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return "\n".join(lines[node.lineno - 1 : node.end_lineno])
    raise AssertionError(f"{name} is not defined in {path.name}")


def test_the_route_can_recognise_the_paired_owner():
    """PORTED DEFECT: the username path consulted only the linked-users table.

    The helper reads ``owner_username`` from the bot config, which is a
    different fact from the linked-users table: that table says who has
    messaged the bot, and a single-user operator has no reason to have done so.
    """
    helper = _function(ROUTE, "_is_paired_owner")
    assert "owner_username" in helper, (
        "the owner check must read owner_username from the paired config"
    )
    assert "get_bot_config" in helper, "it must read the bot config, not the linked users"
    # Case must not decide whether a trader's own alert is delivered.
    assert "casefold" in helper or "lower" in helper, "the comparison must not be case sensitive"


def test_the_username_path_falls_back_to_the_owner_before_refusing():
    """The 404 must be reachable only after the owner has been ruled out."""
    source = _source(ROUTE)
    body = source[source.index('elif data.get("username")') :]
    refusal = body.index("Username not found or not linked to WhatsApp")
    fallback = body.index("_is_paired_owner")
    assert fallback < refusal, (
        "the paired owner must be tried before the route refuses the username"
    )


def test_the_self_send_uses_the_documented_route_to_owner_form():
    """The single-arg send is a real path, not a last resort.

    A comment here once called it unreliable, against wars 0.1.3. The library
    installed is 0.1.4, whose ``send`` documents ``wa.send("Hello there")``
    as "text to owner" and raises ``ValueError`` when no owner is configured,
    so a failure is loud. Refusing it blocked the only self-send an install
    has before its first inbound message, because ``own_jid`` is captured
    from an ``is_from_me`` message and 0.1.4 exposes no attribute to ask for
    it, so pairing alone never fills it in.
    """
    send = _source(SERVICE)
    assert 'ret = self._wa.send(text or "")' in send, (
        "the documented route-to-owner send must still be attempted"
    )


def _has(path: Path, name: str) -> bool:
    tree = ast.parse(_source(path))
    return any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
        for node in ast.walk(tree)
    )


def test_a_send_that_reached_nobody_is_not_reported_as_success():
    """PORTED DEFECT: every send answered "status": "success".

    "Delivered to 0, failed 1" went back under the same status as a message
    that arrived. Callers key on the status: the chart alert in /trading
    records the channel as accepted, so the trader is told the alert went out
    when nobody received it.
    """
    source = _source(ROUTE)
    # Anchored on the condition rather than on a byte window: the phrase
    # "Delivered to" now also appears in the comment explaining this, and a
    # window around the first hit silently measured the wrong lines.
    assert "delivered == 0 and refused > 0" in source, (
        "the route must decide on nothing having been delivered"
    )
    at = source.index("delivered == 0 and refused > 0")
    answered = source[at : at + 700]
    assert '"status": "error"' in answered, (
        "a report with no deliveries must answer with an error status"
    )
    # And the reason must travel, not be replaced by a summary.
    assert "said" in answered or "error" in answered, (
        "the failure text the service wrote must reach the caller"
    )
