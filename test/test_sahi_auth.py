"""Sahi login: Regular and TOTP keys, and the refusals a trader reads.

HTTP is patched; the shapes are those in broker-api-docs/sahi-api-docs
(03-authentication.md).
"""

import time
from datetime import UTC, datetime, timezone

import pytest

from broker.sahi.api import auth_api
from broker.sahi.mapping import transform_data

# RFC 6238 appendix B: the SHA-1 seed "12345678901234567890" in base32.
RFC_SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"


class _Reply:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body

    def json(self):
        return self._body


class _Sent(list):
    """The JSON bodies sent, plus the reply the next call gets."""


@pytest.fixture
def mint(monkeypatch):
    """Patch the token call; returns the list of JSON bodies sent."""
    sent = _Sent()
    reply = {"value": _Reply(200, {"access_token": "tokA", "expires_at": "x", "scope": "s"})}

    def fake_request(client, method, url, category, **kwargs):
        sent.append(kwargs["json"])
        return reply["value"]

    monkeypatch.setattr(auth_api, "sahi_request", fake_request)
    monkeypatch.setattr(auth_api, "get_httpx_client", lambda: None)
    monkeypatch.setenv("BROKER_API_KEY", "pk_1")
    sent.reply = reply
    return sent


def test_totp_code_matches_rfc_6238_vectors():
    # RFC 6238 SHA-1 vectors, last 6 digits of the 8-digit values.
    assert auth_api.totp_code(RFC_SECRET, now=59) == "287082"
    assert auth_api.totp_code(RFC_SECRET, now=1111111109) == "081804"
    assert auth_api.totp_code(RFC_SECRET, now=1234567890) == "005924"
    # As authenticator apps show it: spaced, lower case, unpadded.
    spaced = " ".join(RFC_SECRET[i : i + 4] for i in range(0, len(RFC_SECRET), 4)).lower()
    assert auth_api.totp_code(spaced, now=59) == "287082"
    with pytest.raises(auth_api.TotpSecretError):
        auth_api.totp_code("not base32!", now=59)
    with pytest.raises(auth_api.TotpSecretError):
        auth_api.totp_code("   ", now=59)


def test_split_secret():
    assert auth_api.split_secret("sahi_sk_x") == ("sahi_sk_x", None)
    assert auth_api.split_secret(" sahi_sk_x ::: ABCD ") == ("sahi_sk_x", "ABCD")
    assert auth_api.split_secret("sahi_sk_x:::") == ("sahi_sk_x", None)
    assert auth_api.split_secret(None) == ("", None)


def test_regular_key_sends_no_totp(mint, monkeypatch):
    monkeypatch.setenv("BROKER_API_SECRET", "sahi_sk_1")
    assert auth_api.authenticate_broker() == ("tokA", None)
    assert mint == [{"key_id": "pk_1", "secret": "sahi_sk_1"}]


def test_totp_key_sends_the_current_code(mint, monkeypatch):
    monkeypatch.setenv("BROKER_API_SECRET", f"sahi_sk_1:::{RFC_SECRET}")
    monkeypatch.setattr(auth_api.time, "time", lambda: 59.0)
    assert auth_api.authenticate_broker() == ("tokA", None)
    assert mint == [{"key_id": "pk_1", "secret": "sahi_sk_1", "totp": "287082"}]


def test_a_bad_totp_secret_is_refused_before_sending(mint, monkeypatch):
    monkeypatch.setenv("BROKER_API_SECRET", "sahi_sk_1:::not base32!")
    token, message = auth_api.authenticate_broker()
    assert token is None and "not a valid authenticator secret" in message
    assert mint == []


def test_invalid_totp_names_the_clock_drift(mint, monkeypatch):
    monkeypatch.setenv("BROKER_API_SECRET", f"sahi_sk_1:::{RFC_SECRET}")
    server = datetime(2026, 10, 27, 3, 45, 12, tzinfo=UTC)
    now = server.timestamp() + 95
    monkeypatch.setattr(auth_api.time, "time", lambda: now)
    mint.reply["value"] = _Reply(
        401,
        {
            "code": "InvalidTotp",
            "message": "The TOTP code is not valid",
            "server_time": "2026-10-27T03:45:12Z",
        },
    )
    token, message = auth_api.authenticate_broker()
    assert token is None
    assert "95 seconds ahead of Sahi's" in message
    # Within one step of Sahi's clock the message points at the secret instead.
    monkeypatch.setattr(auth_api.time, "time", lambda: server.timestamp() + 5)
    _, message = auth_api.authenticate_broker()
    assert "TOTP secret Sahi showed" in message and "seconds ahead" not in message


@pytest.mark.parametrize(
    ("status", "code", "expected"),
    [
        (403, "Forbidden", "not approved for today"),
        (403, "Forbidden", "not enabled for your Sahi account"),
        (400, "InvalidRequest", "nothing after the secret"),
        (429, "TooManyRequests", "wrong TOTP codes"),
        (401, "Locked", "frozen or locked"),
        (401, "Unauthorized", "pk_"),
    ],
)
def test_login_refusals_name_the_cause(status, code, expected):
    assert expected in auth_api._login_error(status, {"code": code})


def test_drift_ignores_a_reply_without_server_time():
    assert auth_api._clock_drift_seconds({}) is None
    assert auth_api._clock_drift_seconds({"server_time": "not a time"}) is None
    assert auth_api._clock_drift_seconds(None) is None
    assert isinstance(auth_api._clock_drift_seconds({"server_time": "2026-10-27T03:45:12Z"}), int)
    assert time.time() > 0


@pytest.mark.parametrize(
    ("product", "exchange", "allowed"),
    [
        ("CNC", "NSE", True),
        ("CNC", "BSE", True),
        ("CNC", "NFO", False),
        ("NRML", "NFO", True),
        ("NRML", "BFO", True),
        ("NRML", "NSE", False),
        ("MIS", "NSE", True),
        ("MIS", "BFO", True),
    ],
)
def test_product_must_suit_the_segment(monkeypatch, product, exchange, allowed):
    monkeypatch.setattr(transform_data, "get_br_symbol", lambda s, e: "X")
    order = {
        "symbol": "X",
        "exchange": exchange,
        "action": "BUY",
        "quantity": "1",
        "pricetype": "LIMIT",
        "product": product,
        "price": "10",
    }
    if allowed:
        assert transform_data.transform_data(order)["exchange_segment"] == exchange
    else:
        with pytest.raises(transform_data.OrderMappingError, match="Use CNC or MIS on NSE"):
            transform_data.transform_data(order)
