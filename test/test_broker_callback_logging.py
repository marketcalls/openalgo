"""Broker callbacks must not hand replayable credentials to application logs."""

import inspect
from types import SimpleNamespace

import pytest
from flask import Flask, session

from blueprints import brlogin

SENTINEL = "SENTINEL_CALLBACK_CREDENTIAL_7e949f"


class _CaptureLogger:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def _record(self, message, *args, **_kwargs) -> None:
        self.messages.append(str(message) % args if args else str(message))

    debug = _record
    info = _record
    warning = _record
    error = _record
    exception = _record


@pytest.mark.parametrize(
    ("broker", "query", "auth_result"),
    [
        ("aliceblue", f"authCode={SENTINEL}&userId=alice", (None, None, "authentication refused")),
        ("fyers", f"auth_code={SENTINEL}", (None, "authentication refused")),
        ("icici", f"apisession={SENTINEL}", (None, "authentication refused")),
        (
            "iiflcapital",
            f"authCode={SENTINEL}&clientId=alice",
            (None, "authentication refused"),
        ),
        ("dhan", f"tokenId={SENTINEL}", (None, "authentication refused")),
        ("zebu", f"code={SENTINEL}", (None, "authentication refused")),
        ("shoonya", f"code={SENTINEL}", (None, "authentication refused")),
        (
            "flattrade",
            f"code={SENTINEL}&client=alice",
            (None, "authentication refused"),
        ),
        ("tradesmart", f"code={SENTINEL}", (None, "authentication refused")),
        ("paytm", f"requestToken={SENTINEL}", (None, None, "authentication refused")),
        (
            "pocketful",
            f"code={SENTINEL}&state=opaque-state",
            (None, None, None, "authentication refused"),
        ),
        ("arrow", f"request-token={SENTINEL}", (None, "authentication refused")),
        ("hdfcsky", f"request_token={SENTINEL}", (None, "authentication refused")),
        (
            "hdfcsecurities",
            f"requestToken={SENTINEL}",
            (None, "authentication refused"),
        ),
        ("zerodha", f"code={SENTINEL}", (None, "authentication refused")),
    ],
)
def test_every_oauth_callback_keeps_raw_query_session_and_referrer_credentials_out_of_logs(
    monkeypatch, broker, query, auth_result
) -> None:
    app = Flask(__name__)
    app.secret_key = "test-only"
    app.broker_auth_functions = {f"{broker}_auth": lambda *_args: auth_result}
    capture = _CaptureLogger()
    monkeypatch.setattr(brlogin, "logger", capture)
    callback = inspect.unwrap(brlogin.broker_callback)

    with app.test_request_context(
        f"/{broker}/callback?{query}",
        headers={
            "Accept": "application/json",
            "Referer": f"https://broker.example/consent?{query}",
        },
    ):
        session["user"] = "alice"
        # Real callbacks can already hold a single-use OAuth/OTP credential in
        # Flask's signed session. The callback preamble must log keys, not the
        # session values.
        session["definedge_otp_token"] = SENTINEL
        response = callback(broker)

    assert response is not None
    assert SENTINEL not in "\n".join(capture.messages)


def test_callback_source_never_interpolates_raw_credential_variables_or_aggregates() -> None:
    """Pin every legacy callback log shape that previously exposed a secret."""
    source = inspect.getsource(inspect.unwrap(brlogin.broker_callback))
    forbidden = (
        "dict(session)",
        "{request.cookies}",
        "dict(request.args)",
        "request.query_string.decode()",
        "The code is {code}",
        "code: {code}",
        "with code: {code}",
        "request token is {request_token}",
        "authorization code: {auth_code}",
        "Received tokenId: {token_id}",
        "{code} for client {client}",
    )

    for fragment in forbidden:
        assert fragment not in source, f"callback logger still contains {fragment!r}"


def test_dhan_initiation_never_logs_the_single_use_consent_app_id(monkeypatch) -> None:
    """The redirect URL contains a credential even though it is not a callback."""
    from broker.dhan.api import auth_api

    app = Flask(__name__)
    app.secret_key = "test-only"
    capture = _CaptureLogger()
    monkeypatch.setattr(brlogin, "logger", capture)
    monkeypatch.setenv("BROKER_API_KEY", "dhan-client:::dhan-api-key")
    monkeypatch.setattr(auth_api, "generate_consent", lambda _client: (SENTINEL, None))
    monkeypatch.setattr(
        auth_api,
        "get_login_url",
        lambda consent: f"https://dhan.example/login?consentAppId={consent}",
    )

    initiate = inspect.unwrap(brlogin.dhan_initiate_oauth)
    with app.test_request_context("/dhan/initiate-oauth"):
        session["user"] = "alice"
        response = initiate()

    assert SENTINEL in response
    assert SENTINEL not in "\n".join(capture.messages)


def test_compositedge_malformed_session_is_not_reflected_to_the_client() -> None:
    """Browser or proxy diagnostics must not retain a broker token container."""
    app = Flask(__name__)
    app.secret_key = "test-only"
    app.broker_auth_functions = {"compositedge_auth": lambda *_args: (None, "unused")}
    callback = inspect.unwrap(brlogin.broker_callback)

    with app.test_request_context(
        "/compositedge/callback",
        method="POST",
        data=f"session={SENTINEL}",
        content_type="application/x-www-form-urlencoded",
    ):
        session["user"] = "alice"
        response, status = callback("compositedge")

    assert status == 400
    body = response.get_data(as_text=True)
    assert SENTINEL not in body
    assert "raw_data" not in body


def test_compositedge_auth_exception_does_not_reflect_a_valid_session_token() -> None:
    """Adapter exceptions can quote the request, so their text is not client-safe."""
    app = Flask(__name__)
    app.secret_key = "test-only"

    def raising_auth(*_args):
        raise RuntimeError(f"upstream echoed {SENTINEL}")

    app.broker_auth_functions = {"compositedge_auth": raising_auth}
    callback = inspect.unwrap(brlogin.broker_callback)

    with app.test_request_context(
        "/compositedge/callback",
        method="POST",
        json={"accessToken": SENTINEL},
    ):
        session["user"] = "alice"
        response, status = callback("compositedge")

    assert status == 500
    body = response.get_data(as_text=True)
    assert SENTINEL not in body
    assert "upstream echoed" not in body
