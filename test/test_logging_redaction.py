"""Regression tests for SensitiveDataFilter's redaction patterns.

These patterns are a security control: they are the last thing standing between
a broker credential and log/errors.jsonl. They had no tests, and two brokers
were found defeating the Bearer rule in different ways, so the shapes that
matter are pinned here.
"""

import json
import logging
import os
import re
import sys

import pytest
from flask import Flask

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.logging import SENSITIVE_PATTERNS, JSONErrorFormatter, SensitiveDataFilter  # noqa: E402
from utils.url_redaction import redact_url_credentials  # noqa: E402

SECRET = "SEKRETVALUE"
URL_CREDENTIAL = "SENTINEL_URL_CREDENTIAL"


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
        ("ICICI callback apisession", "apisession=" + SECRET),
        ("Dhan callback tokenId", "{'tokenId': '" + SECRET + "'}"),
        ("broker requestToken", '"requestToken":"' + SECRET + '"'),
        ("broker authCode", "authCode: " + SECRET),
        ("prose authorization code", "Received authorization code: " + SECRET),
        ("prose request token", "The request token is " + SECRET),
        ("prose OAuth code", "OAuth callback with code: " + SECRET),
        ("prose generic code", "The code is " + SECRET),
        ("prose tokenId", "Received tokenId: " + SECRET),
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


def test_normal_status_codes_are_not_redacted_as_callback_credentials():
    message = "Broker response status code=200; retry status_code=429"

    assert redact(message) == message


# ---------------------------------------------------------------------------
# The filter itself, not just the patterns.
#
# Redaction used to run over the template and each argument separately, which
# broke formatting in three distinct ways while still redacting. These pin the
# rendered output, which is what an operator actually reads.
# ---------------------------------------------------------------------------


def _emit(msg, args):
    """One record through the filter, returning what a handler would print."""
    import logging

    record = logging.LogRecord("t", logging.INFO, __file__, 1, msg, args, None)
    assert SensitiveDataFilter().filter(record) is True
    return record.getMessage()


def test_a_numeric_argument_survives_redaction():
    """Every argument used to be str()'d, so %d could not format.

    The record then reached the operator with the placeholder still in it:
    "Strategy module recovered %d run(s)" could not say whether it had
    recovered none or twelve, which is the one thing that line exists to say.
    """
    assert _emit("Strategy module recovered %d run(s)", (12,)) == (
        "Strategy module recovered 12 run(s)"
    )
    assert _emit("Pruned %d rows in %.2f s", (5, 1.5)) == "Pruned 5 rows in 1.50 s"


def test_a_mapping_argument_survives_redaction():
    """%(key)s logging: iterating the mapping yielded its keys."""
    assert _emit("mapping %(n)d and %(k)s", {"n": 3, "k": "plain"}) == "mapping 3 and plain"


def test_a_secret_in_an_argument_is_still_redacted():
    out = _emit("api_key=%s and a number %d", (SECRET, 7))

    assert SECRET not in out
    assert out.endswith("and a number 7"), "the number formatted alongside the redaction"


def test_a_secret_written_into_the_template_is_still_redacted():
    out = _emit(f"a literal api_key={SECRET} in the text", ())

    assert SECRET not in out


def test_a_record_whose_arguments_do_not_match_is_still_emitted():
    """A developer mistake must not cost the line, or the redaction."""
    out = _emit(f"api_key={SECRET} with a stray %s and no argument", ())

    assert SECRET not in out
    assert "stray" in out


@pytest.mark.parametrize(
    ("path", "visible_tail"),
    [
        (f"/strategy/webhook/{URL_CREDENTIAL}", None),
        (f"/flow/webhook/{URL_CREDENTIAL}/NIFTY", "NIFTY"),
        (f"/chartink/webhook/{URL_CREDENTIAL}", None),
    ],
)
def test_shared_url_redactor_masks_every_shipped_url_secret_route(path, visible_tail):
    redacted = redact_url_credentials(f"https://openalgo.example{path}?source=test")

    assert URL_CREDENTIAL not in redacted
    assert "<redacted>" in redacted
    assert "source=test" in redacted
    if visible_tail:
        assert visible_tail in redacted


def test_shared_url_redactor_masks_callback_query_credentials_but_not_status_codes():
    url = (
        "https://openalgo.example/dhan/callback?status_code=200"
        f"&tokenId={SECRET}&apisession={SECRET}&code={SECRET}"
    )

    redacted = redact_url_credentials(url)

    assert SECRET not in redacted
    assert "status_code=200" in redacted
    assert redacted.count("[REDACTED]") == 3


@pytest.mark.parametrize(
    "path",
    [
        f"/strategy/webhook/{URL_CREDENTIAL}",
        f"/flow/webhook/{URL_CREDENTIAL}/NIFTY",
        f"/chartink/webhook/{URL_CREDENTIAL}",
    ],
)
def test_json_error_formatter_never_emits_a_request_url_credential(path):
    app = Flask(__name__)
    record = logging.LogRecord("t", logging.ERROR, __file__, 1, "failed", (), None)

    with app.test_request_context(path, method="POST"):
        output = JSONErrorFormatter().format(record)

    assert URL_CREDENTIAL not in output
    assert json.loads(output)["request"]["path"].count("<redacted>") == 1


def test_standard_log_filter_masks_a_webhook_url_in_the_message():
    output = _emit(
        f"Request failed at https://openalgo.example/strategy/webhook/{URL_CREDENTIAL}",
        (),
    )

    assert URL_CREDENTIAL not in output
    assert "<redacted>" in output


def test_callback_credentials_never_reach_the_json_error_sink():
    try:
        raise RuntimeError(
            "callback refused at "
            f"https://openalgo.example/dhan/callback?tokenId={SECRET}"
        )
    except RuntimeError:
        exc_info = sys.exc_info()

    record = logging.LogRecord(
        "broker.callback",
        logging.ERROR,
        __file__,
        1,
        "apisession=%s authCode=%s",
        (SECRET, SECRET),
        exc_info,
    )
    assert SensitiveDataFilter().filter(record) is True

    output = JSONErrorFormatter().format(record)

    assert SECRET not in output
    payload = json.loads(output)
    assert "[REDACTED]" in payload["message"]
    assert "[REDACTED]" in "".join(payload["exception"])
