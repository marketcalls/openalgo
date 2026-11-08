"""Sahi TOTP-key login (#2387): the code is sent only when typed, and a key
that needs it sends the trader to the TOTP form.

Sahi issues two kinds of API key. A Regular key mints the day's token with
key id and secret alone; sending ``totp`` with it is rejected. A TOTP key is
refused without its six-digit code (InvalidRequest), and the first correct
code of the day approves it (a wrong one is InvalidTotp).
"""

import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from broker.sahi.api import auth_api  # noqa: E402


@pytest.fixture(autouse=True)
def _credentials(monkeypatch):
    monkeypatch.setenv("BROKER_API_KEY", "pk_test_key")
    monkeypatch.setenv("BROKER_API_SECRET", "sahi_sk_test_secret")


def _mock_sahi(monkeypatch, status_code=200, body=None, recorder=None):
    """Answer the token mint in place of Sahi, recording the payload sent."""

    class Response:
        def __init__(self):
            self.status_code = status_code

        def json(self):
            return body or {"access_token": "tok-123", "expires_at": "...", "scope": "orders.write"}

    def fake_sahi_request(client, method, url, tag, json=None, headers=None, timeout=None):
        if recorder is not None:
            recorder.update(json or {})
        return Response()

    monkeypatch.setattr(auth_api, "sahi_request", fake_sahi_request)
    monkeypatch.setattr(auth_api, "get_httpx_client", lambda: object())


def test_regular_key_never_sends_totp(monkeypatch):
    sent = {}
    _mock_sahi(monkeypatch, recorder=sent)

    token, error = auth_api.authenticate_broker()

    assert token == "tok-123"
    assert error is None
    assert sent == {"key_id": "pk_test_key", "secret": "sahi_sk_test_secret"}
    assert "totp" not in sent


def test_totp_login_sends_the_typed_code(monkeypatch):
    sent = {}
    _mock_sahi(monkeypatch, recorder=sent)

    token, error = auth_api.authenticate_broker_totp("483920")

    assert token == "tok-123"
    assert error is None
    assert sent["totp"] == "483920"


def test_totp_key_without_code_points_to_the_form(monkeypatch):
    """A TOTP key refused for a missing code yields TOTP_REQUIRED_MESSAGE, the
    signal the login route uses to redirect to the TOTP form."""
    _mock_sahi(
        monkeypatch,
        status_code=400,
        body={"code": "InvalidRequest", "message": "This API key needs a six-digit totp code."},
    )

    token, error = auth_api.authenticate_broker()

    assert token is None
    assert error == auth_api.TOTP_REQUIRED_MESSAGE


def test_wrong_code_is_explained_without_a_status_code(monkeypatch):
    _mock_sahi(monkeypatch, status_code=400, body={"code": "InvalidTotp", "message": "The TOTP code is not valid"})

    token, error = auth_api.authenticate_broker_totp("000000")

    assert token is None
    assert "did not accept that code" in error
    assert "400" not in error


def test_other_refusals_keep_their_existing_messages(monkeypatch):
    _mock_sahi(monkeypatch, status_code=403, body={"code": "Forbidden", "message": "key not approved"})

    token, error = auth_api.authenticate_broker()

    assert token is None
    assert "not approved for today" in error
    assert "403" not in error
