"""Sahi login: Regular and TOTP keys, and the refusals a trader reads.

The TOTP code comes from the login card (blank for a Regular key).

HTTP is patched; the shapes are those in broker-api-docs/sahi-api-docs
(03-authentication.md).
"""

import pytest

from broker.sahi.api import auth_api
from broker.sahi.mapping import transform_data


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
    monkeypatch.setenv("BROKER_API_SECRET", "sahi_sk_1")
    sent.reply = reply
    return sent


@pytest.mark.parametrize("blank", [None, "", "   "])
def test_regular_key_sends_no_totp(mint, blank):
    assert auth_api.authenticate_broker("sahi", totp=blank) == ("tokA", None)
    assert mint == [{"key_id": "pk_1", "secret": "sahi_sk_1"}]


def test_totp_key_sends_the_code_from_the_card(mint):
    assert auth_api.authenticate_broker("sahi", totp=" 042 917 ") == ("tokA", None)
    assert mint == [{"key_id": "pk_1", "secret": "sahi_sk_1", "totp": "042917"}]


@pytest.mark.parametrize("bad", ["12345", "1234567", "12a456", "abcdef"])
def test_a_code_that_is_not_six_digits_is_refused_before_sending(mint, bad):
    token, message = auth_api.authenticate_broker("sahi", totp=bad)
    assert token is None and "6-digit code" in message
    assert mint == []


def test_the_api_secret_is_sent_as_saved(mint, monkeypatch):
    # Nothing after ::: is read any more: the secret goes to Sahi unchanged.
    monkeypatch.setenv("BROKER_API_SECRET", "sahi_sk_1:::X")
    auth_api.authenticate_broker("sahi")
    assert mint[0]["secret"] == "sahi_sk_1:::X"


def test_a_wrong_code_says_so(mint):
    mint.reply["value"] = _Reply(
        401,
        {
            "code": "InvalidTotp",
            "message": "The TOTP code is not valid",
            "server_time": "2026-10-27T03:45:12Z",
        },
    )
    token, message = auth_api.authenticate_broker("sahi", totp="042917")
    assert token is None
    assert "did not accept the TOTP code" in message


@pytest.mark.parametrize(
    ("status", "code", "expected"),
    [
        (403, "Forbidden", "not approved for today"),
        (403, "Forbidden", "not enabled for your Sahi account"),
        (403, "Forbidden", "enter its code when you log in"),
        (400, "InvalidRequest", "leave the code blank"),
        (429, "TooManyRequests", "wrong TOTP codes"),
        (401, "Locked", "frozen or locked"),
        (401, "Unauthorized", "pk_"),
    ],
)
def test_login_refusals_name_the_cause(status, code, expected):
    assert expected in auth_api._login_error(status, {"code": code})


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
