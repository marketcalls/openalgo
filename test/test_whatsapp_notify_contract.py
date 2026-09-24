"""The shape `/api/v1/whatsapp/notify` answers with, pinned.

This endpoint is public and has a large installed base of callers that nobody
working in this repository can survey: scripts, alert forwarders, and the
platform's own chart alerts. A change to what it returns is a change to all of
them at once, and the ones that break are the ones nobody hears about.

So the success shape is pinned here rather than trusted to review. These tests
read the route's source instead of driving a live WhatsApp session, because a
test that needs a paired device runs nowhere: they are cheap, they run in CI,
and what they protect is the part that a refactor silently moves.

**What is deliberately allowed to differ from the old behaviour** is one thing,
and it is recorded in `test_whatsapp_owner_recipient.py`: a report where
nothing was delivered used to answer `"status": "success"`, and now answers
`"status": "error"`. The HTTP code stays 200 for that case precisely so the
change reaches callers through the field they read rather than through a
transport error they have never had to handle from this path.
"""

import ast
from pathlib import Path

ROUTE = Path(__file__).resolve().parents[1] / "restx_api" / "whatsapp_bot.py"


def _source() -> str:
    return ROUTE.read_text(encoding="utf-8")


def _post_body() -> str:
    """The source of WhatsAppNotify.post."""
    tree = ast.parse(_source())
    lines = _source().splitlines()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "WhatsAppNotify":
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "post":
                    return "\n".join(lines[item.lineno - 1 : item.end_lineno])
    raise AssertionError("WhatsAppNotify.post is not defined")


def test_a_delivered_send_still_answers_exactly_what_it_always_did():
    """The success shape is the contract: status, message, data.

    The wording of the message is part of it. A caller parsing "Delivered to
    N, failed M" is doing something inadvisable, but it has worked for a long
    time and there is no reason to take it away.
    """
    body = _post_body()
    assert '"status": "success"' in body
    assert 'f"Delivered to {delivered}, failed {refused}"' in body, (
        "the delivered/failed summary is what callers have always been given"
    )
    assert '"data": report' in body, "the per-recipient report must stay in data"


def test_a_partly_delivered_send_is_still_a_success():
    """Some arrived, some did not: unchanged, and still 200.

    Only a report with NO deliveries changed. A send to five numbers where
    four arrive must not start failing.
    """
    body = _post_body()
    at = body.index("delivered == 0 and refused > 0")
    assert "and refused > 0" in body[at : at + 40], (
        "the error answer must require that nothing at all was delivered"
    )


def test_the_failure_answer_keeps_the_http_code_callers_already_get():
    """PORTED DEFECT, and its compatibility fix.

    Nothing delivered used to answer "success". It answers "error" now, which
    is the point. What it must NOT do is answer with a transport code this
    path has never returned: a caller that raises on non-2xx, or retries on
    5xx, would turn a fixed message into a new outage.
    """
    body = _post_body()
    at = body.index("delivered == 0 and refused > 0")
    answer = body[at : at + 1600]
    assert '"status": "error"' in answer, "nothing delivered must not read as success"
    assert "502" not in answer, (
        "this path must not introduce a 5xx that existing callers have never seen"
    )
    assert "200" in answer, "the request was accepted and processed, which is 200"


def test_the_recipient_forms_are_all_still_accepted():
    """self, phone, phones and username: none may be dropped.

    The owner fallback was added inside the username branch. It must not have
    displaced any of the other three, each of which is documented and in use.
    """
    body = _post_body()
    for form in (
        'data.get("self")',
        'data.get("phones")',
        'data.get("phone")',
        'data.get("username")',
    ):
        assert form in body, f"the {form} recipient form must still be accepted"


def test_an_unknown_username_is_still_refused_with_404():
    """The owner fallback is additive: it only catches what already failed."""
    body = _post_body()
    assert "Username not found or not linked to WhatsApp" in body
    at = body.index("Username not found or not linked to WhatsApp")
    assert "404" in body[at : at + 200], "an unknown username must still be a 404"


def test_queued_sends_still_answer_queued():
    """wait_for_delivery=false keeps its own shape, which is a different one."""
    body = _post_body()
    assert '"queued"' in body, "the fire-and-forget answer must keep its queued count"
    assert 'f"Queued for {len(recipients)} recipient(s)"' in body
