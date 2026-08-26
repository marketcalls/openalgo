"""Regression tests for SensitiveDataFilter's redaction patterns.

These patterns are a security control: they are the last thing standing between
a broker credential and log/errors.jsonl. They had no tests, and two brokers
were found defeating the Bearer rule in different ways, so the shapes that
matter are pinned here.
"""

import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.logging import SENSITIVE_PATTERNS  # noqa: E402

SECRET = "SEKRETVALUE"


def redact(text: str) -> str:
    for pattern, replacement in SENSITIVE_PATTERNS:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text


@pytest.mark.parametrize(
    ("label", "message"),
    [
        # Bearer, including the two composite forms that defeated [\w\-\.]+.
        ("bearer plain", "{'Authorization': 'Bearer " + SECRET + "'}"),
        # tradejini sends "Bearer <api_key>:<access_token>".
        ("bearer colon composite", "{'Authorization': 'Bearer APIKEY123:" + SECRET + "'}"),
        # aliceblue sends "Bearer <user_id> <session_id>".
        ("bearer space composite", "{'Authorization': 'Bearer USER1234 " + SECRET + "'}"),
        # Cookies are credentials; an auth endpoint's response headers carry them.
        ("set-cookie", "{'set-cookie': 'JSESSIONID=" + SECRET + "; Path=/'}"),
        ("cookie header", "Cookie: session=" + SECRET),
        # Key-value shapes the brokers actually emit.
        ("query param", "wss://host/ws?susertoken=" + SECRET + "&uid=a"),
        ("api_key dict", "{'api_key': '" + SECRET + "', 'mode': 'live'}"),
        ("password with symbols", "password=" + SECRET + "@!#$"),
        ("access_token colon", "access_token: " + SECRET),
        ("feed token json", '{"feed_token":"' + SECRET + '"}'),
    ],
)
def test_secret_never_survives_redaction(label, message):
    assert SECRET not in redact(message), f"{label}: secret survived redaction"


def test_bearer_does_not_swallow_the_rest_of_a_headers_dict():
    """Over-redaction has a cost: the Bearer rule must stop at the quote.

    The composite fix continues across ':' and single spaces, so this pins that
    it still cannot run past the closing quote and eat neighbouring fields.
    """
    out = redact("{'Authorization': 'Bearer " + SECRET + "', 'Accept': 'application/json'}")

    assert SECRET not in out
    assert "'Accept': 'application/json'" in out


def test_non_secret_text_is_left_alone():
    """A message with no credential in it must pass through untouched."""
    message = "Placed order 250826000123456 for SBIN-EQ on NSE, qty 100"

    assert redact(message) == message
