"""The shared Pocketful request helper: host, headers, token layout, answers."""

import json
from types import SimpleNamespace

import pytest

import broker.pocketful.api.baseurl as base
import database.auth_db as auth_db


def test_the_token_carries_the_client_id_and_the_access_token():
    token = base.pack_token("DEMO1", "jwt.abc.def")

    assert base.split_token(token) == ("DEMO1", "jwt.abc.def")
    assert base.access_token(token) == "jwt.abc.def"
    assert base.client_id(token) == "DEMO1"


def test_a_bare_token_takes_the_client_id_stored_with_the_session(monkeypatch):
    seen = []

    class Query:
        def filter_by(self, **kwargs):
            seen.append(kwargs)
            return SimpleNamespace(first=lambda: SimpleNamespace(user_id="DEMO2"))

    monkeypatch.setattr(auth_db, "Auth", SimpleNamespace(query=Query()))

    assert base.split_token("jwt.only") == (None, "jwt.only")
    assert base.client_id("jwt.only") == "DEMO2"
    assert seen == [{"broker": "pocketful", "is_revoked": False}]


def test_both_documented_header_forms_carry_the_bare_access_token():
    headers = base.build_headers(base.pack_token("DEMO1", "jwt.abc.def"))

    assert headers["Authorization"] == "Bearer jwt.abc.def"
    assert headers["x-authorization-token"] == "jwt.abc.def"
    assert headers["x-device-type"] == "WEB"


@pytest.mark.parametrize(
    ("status_code", "body", "ok"),
    [
        (200, {"status": "success", "message": "", "data": {}}, True),
        (200, {"status": True, "message": "SUCCESS", "errorcode": "", "data": {}}, True),
        (200, {"status": "error", "message": "Request Unauthorised", "data": {}}, False),
        (200, {"status": False, "message": "Invalid", "data": {}}, False),
        (401, {"status": "success"}, False),
        (200, None, False),
    ],
)
def test_either_success_envelope_is_ok(status_code, body, ok):
    assert base.PocketfulResponse(status_code, body, "").ok is ok


def test_a_request_goes_to_the_new_host_with_a_timeout(monkeypatch):
    sent = {}

    class Client:
        def request(self, method, url, headers=None, content=None, params=None, timeout=None):
            sent.update(
                method=method,
                url=url,
                headers=headers,
                body=content,
                params=params,
                timeout=timeout,
            )
            return SimpleNamespace(
                status_code=200, json=lambda: {"status": "success", "data": {"x": 1}}, text=""
            )

    monkeypatch.setattr(base, "get_httpx_client", lambda: Client())

    answer = base.pocketful_request(
        "post",
        "/api/v1/orders",
        base.pack_token("DEMO1", "jwt"),
        params={"a": 1},
        payload={"b": 2},
        headers={"clientid": "DEMO1"},
    )

    assert sent["url"] == "https://algo.pocketful.in/api/v1/orders"
    assert sent["method"] == "POST" and sent["timeout"] == base.REQUEST_TIMEOUT
    assert json.loads(sent["body"]) == {"b": 2} and sent["params"] == {"a": 1}
    assert sent["headers"]["x-authorization-token"] == "jwt"
    assert sent["headers"]["clientid"] == "DEMO1"
    assert answer.ok and answer.payload == {"x": 1}
