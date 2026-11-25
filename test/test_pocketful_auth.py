"""Pocketful login: the sign-in address, the code exchange, the account and the refusals.

No request leaves the test: the shared HTTP client is replaced in both
modules that use it (auth_api for the code exchange, baseurl for the account
lookup). Answers are shaped as RFC 6749 and the OAuth server Pocketful runs
(the error texts are fosite's) return them, and as Pocketful's JSON envelope.
"""

import base64
import inspect
import logging
from datetime import UTC, datetime
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from flask import Flask, session

import broker.pocketful.api.auth_api as auth_api
import broker.pocketful.api.baseurl as baseurl
import utils.broker_login as broker_login
from blueprints import brlogin
from utils.broker_keys import BrokerKeys

APP_ID = "APPID7Vf"
CODE = "CODE_SENTINEL_5f1e"
SECRET = "SECRET_SENTINEL_9a2c"
ACCESS = "ACCESS_SENTINEL_77c0"
REDIRECT = "http://127.0.0.1:5000/pocketful/callback"
SENTINELS = (CODE, SECRET, ACCESS)

# fosite's own texts (errors.go, flow_authorize_code_token.go): the description
# of every invalid_grant mentions the "redirection URI"; only the hint of a
# real mismatch names redirect_uri. Double quotes come back as single quotes.
GRANT_DESCRIPTION = (
    "The provided authorization grant (e.g., authorization code, resource owner "
    "credentials) or refresh token is invalid, expired, revoked, does not match the "
    "redirection URI used in the authorization request, or was issued to another client."
)
REDIRECT_HINT = (
    "The 'redirect_uri' from this request does not match the one from the authorize request."
)
CLIENT_DESCRIPTION = (
    "Client authentication failed (e.g., unknown client, no client authentication "
    "included, or unsupported authentication method)."
)


def _answer(status_code, body):
    def parse():
        if isinstance(body, (dict, list)):
            return body
        raise ValueError("not JSON")

    return SimpleNamespace(status_code=status_code, json=parse, text=str(body))


TOKEN_OK = _answer(
    200,
    {
        "access_token": ACCESS,
        "token_type": "bearer",
        "expires_in": 3599,
        "scope": "orders holdings",
    },
)
ACCOUNT_OK = _answer(200, {"status": "success", "message": "", "data": {"client_id": "YA0002"}})


class FakeClient:
    """The shared httpx client: records every request and answers from a script."""

    def __init__(self, token=TOKEN_OK, account=ACCOUNT_OK):
        self.token = token
        self.account = account
        self.posts = []
        self.requests = []

    def post(self, url, headers=None, content=None, timeout=None, **kwargs):
        assert not kwargs, f"unexpected arguments {sorted(kwargs)}"
        self.posts.append({"url": url, "headers": headers, "content": content, "timeout": timeout})
        if isinstance(self.token, Exception):
            raise self.token
        return self.token

    def request(self, method, url, headers=None, content=None, params=None, timeout=None):
        self.requests.append(
            {"method": method, "url": url, "headers": headers, "params": params, "timeout": timeout}
        )
        if isinstance(self.account, Exception):
            raise self.account
        return self.account


class CaptureLogger:
    """Every message a module logs, formatted, before any redaction filter."""

    def __init__(self):
        self.lines = []

    def _record(self, message, *args, **_kwargs):
        self.lines.append(str(message) % args if args else str(message))

    debug = info = warning = error = exception = critical = _record


@pytest.fixture
def logs(monkeypatch, caplog):
    capture = CaptureLogger()
    for module in (auth_api, baseurl, brlogin):
        monkeypatch.setattr(module, "logger", capture)
    caplog.set_level(logging.DEBUG)

    def text():
        return "\n".join(capture.lines) + "\n" + caplog.text

    return SimpleNamespace(lines=capture.lines, text=text)


@pytest.fixture
def keys(monkeypatch):
    monkeypatch.setenv("BROKER_API_KEY", APP_ID)
    monkeypatch.setenv("BROKER_API_SECRET", SECRET)
    monkeypatch.setenv("REDIRECT_URL", REDIRECT)


@pytest.fixture
def client(monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr(auth_api, "get_httpx_client", lambda: fake)
    monkeypatch.setattr(baseurl, "get_httpx_client", lambda: fake)
    return fake


def _pocketful_keys(api_key=APP_ID, redirect_url=REDIRECT):
    return BrokerKeys(
        broker="pocketful",
        api_key=api_key,
        api_secret=SECRET,
        api_key_market="",
        api_secret_market="",
        redirect_url=redirect_url,
        source="saved",
    )


# The sign-in address


def test_the_sign_in_starts_on_the_new_host_as_pocketfuls_portal_opens_it():
    url = broker_login.login_url(_pocketful_keys(), "st-1")

    assert url == (
        "https://algo.pocketful.in/oauth2/auth?client_id=APPID7Vf"
        "&redirect_uri=http://127.0.0.1:5000/pocketful/callback"
        "&response_type=code&scope=orders%20holdings&state=st-1"
    )
    query = parse_qs(urlsplit(url).query)
    assert query == {
        "client_id": [APP_ID],
        "redirect_uri": [REDIRECT],
        "response_type": ["code"],
        "scope": ["orders holdings"],
        "state": ["st-1"],
    }
    assert SECRET not in url


def test_a_value_that_could_add_a_parameter_is_encoded():
    url = broker_login.login_url(_pocketful_keys(api_key="A&state=evil"), "st-2")

    assert parse_qs(urlsplit(url).query)["client_id"] == ["A&state=evil"]
    assert parse_qs(urlsplit(url).query)["state"] == ["st-2"]


def test_the_answer_must_carry_the_state_of_a_login_started_here(monkeypatch):
    """Pocketful echoes the state, so its answer is matched by the state alone,
    never by the browser's marker, and a missing state is refused before any
    database read."""
    assert "pocketful" in broker_login.STATE_BROKERS
    looked_up = []
    monkeypatch.setattr(
        broker_login, "find_login_state", lambda *a, **k: looked_up.append(k) or None
    )

    app = Flask(__name__)
    app.secret_key = "test-only"
    with app.test_request_context():
        session["broker_login"] = {"broker": "pocketful", "nonce": "n", "state": "s"}
        assert broker_login.has_pending_login("pocketful") is False
        assert looked_up == []
        assert broker_login.has_pending_login("pocketful", state="forged") is False
        assert looked_up == [{"state": "forged"}]


# The code exchange and the account


def test_the_code_is_exchanged_on_the_new_host_with_the_apps_keys(keys, client, logs):
    auth_api.authenticate_broker(CODE, "st-1")

    [sent] = client.posts
    assert sent["url"] == "https://algo.pocketful.in/oauth2/token"
    expected = base64.b64encode(f"{APP_ID}:{SECRET}".encode()).decode()
    assert sent["headers"]["Authorization"] == f"Basic {expected}"
    assert sent["headers"]["Content-Type"] == "application/x-www-form-urlencoded"
    assert parse_qs(sent["content"]) == {
        "grant_type": ["authorization_code"],
        "code": [CODE],
        "redirect_uri": [REDIRECT],
    }
    assert sent["timeout"] == baseurl.REQUEST_TIMEOUT


def test_the_account_is_read_with_the_new_access_token(keys, client, logs):
    auth_api.authenticate_broker(CODE)

    [read] = client.requests
    assert read["method"] == "GET"
    assert read["url"] == "https://algo.pocketful.in/api/v1/user/trading_info"
    assert read["headers"]["Authorization"] == f"Bearer {ACCESS}"
    assert read["headers"]["x-authorization-token"] == ACCESS
    assert read["timeout"] == baseurl.REQUEST_TIMEOUT


def test_the_token_carries_the_account_and_the_account_is_handed_back(keys, client, logs):
    token, feed_token, user_id, error = auth_api.authenticate_broker(CODE)

    assert error is None and feed_token is None
    assert user_id == "YA0002"
    assert token == f"YA0002:::{ACCESS}"
    assert baseurl.client_id(token) == "YA0002"
    assert baseurl.access_token(token) == ACCESS


def test_the_keys_and_redirect_are_read_at_each_login(keys, client, logs, monkeypatch):
    """A login's callback reads its own broker's staged keys: nothing may keep
    the keys of whichever broker was in place when the module was imported."""
    auth_api.authenticate_broker(CODE)
    monkeypatch.setenv("BROKER_API_KEY", "OTHERAPP")
    monkeypatch.setenv("BROKER_API_SECRET", "other-secret")
    monkeypatch.setenv("REDIRECT_URL", "https://algo.example/pocketful/callback")
    auth_api.authenticate_broker(CODE)

    first, second = client.posts
    other = base64.b64encode(b"OTHERAPP:other-secret").decode()
    assert second["headers"]["Authorization"] == f"Basic {other}"
    assert first["headers"]["Authorization"] != second["headers"]["Authorization"]
    assert parse_qs(second["content"])["redirect_uri"] == [
        "https://algo.example/pocketful/callback"
    ]


def test_without_a_redirect_url_the_exchange_repeats_the_default_one(
    keys, client, logs, monkeypatch
):
    """Saved keys without a redirect URL sign in with the default address
    (utils.broker_keys.resolve), so the exchange must send that one."""
    monkeypatch.delenv("REDIRECT_URL")
    monkeypatch.setenv("HOST_SERVER", "https://trader.example")

    auth_api.authenticate_broker(CODE)

    assert parse_qs(client.posts[0]["content"])["redirect_uri"] == [
        "https://trader.example/pocketful/callback"
    ]


# Every refusal: a sentence, nothing stored, nothing secret in the log


FAILURES = [
    pytest.param({"code": None}, auth_api.MISSING_CODE, 0, id="no-code"),
    pytest.param({"code": "   "}, auth_api.MISSING_CODE, 0, id="blank-code"),
    pytest.param({"env": {"BROKER_API_KEY": ""}}, auth_api.MISSING_KEYS, 0, id="no-app-id"),
    pytest.param({"env": {"BROKER_API_SECRET": ""}}, auth_api.MISSING_KEYS, 0, id="no-secret"),
    pytest.param(
        {"token": httpx.ConnectError("connection refused")},
        auth_api.UNREACHABLE,
        1,
        id="token-unreachable",
    ),
    pytest.param(
        {
            "token": _answer(
                401, {"error": "invalid_client", "error_description": CLIENT_DESCRIPTION}
            )
        },
        auth_api.KEYS_REFUSED,
        1,
        id="keys-refused",
    ),
    pytest.param(
        {
            "token": _answer(
                400,
                {
                    "error": "invalid_grant",
                    "error_description": f"{GRANT_DESCRIPTION} {REDIRECT_HINT}",
                },
            )
        },
        auth_api.REDIRECT_MISMATCH,
        1,
        id="redirect-mismatch",
    ),
    pytest.param(
        {
            "token": _answer(
                400,
                {
                    "error": "invalid_grant",
                    "error_description": GRANT_DESCRIPTION,
                    "error_hint": REDIRECT_HINT,
                },
            )
        },
        auth_api.REDIRECT_MISMATCH,
        1,
        id="redirect-mismatch-legacy-hint",
    ),
    pytest.param(
        {"token": _answer(400, {"error": "invalid_grant", "error_description": GRANT_DESCRIPTION})},
        auth_api.CODE_REFUSED,
        1,
        id="code-expired",
    ),
    pytest.param(
        {"token": _answer(503, "<html>upstream unavailable</html>")},
        auth_api.BROKER_UNAVAILABLE,
        1,
        id="broker-down",
    ),
    pytest.param(
        {"token": _answer(400, {"error": "invalid_request", "error_description": "malformed"})},
        auth_api.LOGIN_REFUSED,
        1,
        id="other-refusal",
    ),
    pytest.param(
        {"token": _answer(200, {"token_type": "bearer", "expires_in": 3599})},
        auth_api.NO_SESSION,
        1,
        id="no-access-token",
    ),
    pytest.param(
        {"account": httpx.ReadTimeout("timed out")},
        auth_api.UNREACHABLE,
        2,
        id="account-unreachable",
    ),
    pytest.param(
        {
            "account": _answer(
                401,
                {
                    "status": "error",
                    "message": "Request Unauthorised",
                    "error_code": 40000,
                    "data": {},
                },
            )
        },
        auth_api.NO_ACCOUNT,
        2,
        id="account-refused",
    ),
    pytest.param(
        {"account": _answer(200, {"status": "success", "message": "", "data": {}})},
        auth_api.NO_ACCOUNT,
        2,
        id="account-missing",
    ),
    pytest.param(
        {"account": _answer(200, {"status": "success", "data": {"client_id": "YA:::0002"}})},
        auth_api.NO_ACCOUNT,
        2,
        id="account-breaks-the-token-layout",
    ),
    pytest.param(
        {"account": _answer(200, {"status": "success", "data": {"client_id": "../orders"}})},
        auth_api.NO_ACCOUNT,
        2,
        id="account-not-an-id",
    ),
    pytest.param(
        {"account": _answer(200, "<html>maintenance</html>")},
        auth_api.NO_ACCOUNT,
        2,
        id="account-not-json",
    ),
]


@pytest.mark.parametrize(("case", "message", "calls"), FAILURES)
def test_every_failure_is_a_sentence_and_stores_nothing(
    keys, client, logs, monkeypatch, case, message, calls
):
    for name, value in case.get("env", {}).items():
        monkeypatch.setenv(name, value)
    if "token" in case:
        client.token = case["token"]
    if "account" in case:
        client.account = case["account"]

    result = auth_api.authenticate_broker(case.get("code", CODE))

    # The access token is never handed back with an error: the callback
    # treats any token as a completed login.
    assert result == (None, None, None, message)
    assert len(client.posts) + len(client.requests) == calls
    for word in ("OAuth", "HTTP", "status", "error_code", "invalid_", "Exception"):
        assert word not in message
    leaked = [s for s in SENTINELS if s in logs.text()]
    assert leaked == []


def test_a_successful_login_logs_no_secret(keys, client, logs):
    auth_api.authenticate_broker(CODE)

    assert logs.lines, "the login logs that it completed"
    assert [s for s in SENTINELS if s in logs.text()] == []


@pytest.mark.parametrize(
    ("error", "message"),
    [
        ("access_denied", auth_api.LOGIN_CANCELLED),
        ("invalid_scope", auth_api.SCOPE_REFUSED),
        ("server_error", auth_api.LOGIN_REFUSED),
    ],
)
def test_a_sign_in_sent_back_with_an_error_reads_as_a_sentence(logs, error, message):
    assert auth_api.callback_refusal(error, "The resource owner denied the request.") == message
    assert "denied the request" in logs.text()


# The callback


def _callback(monkeypatch, query, auth_function):
    """Run /pocketful/callback with the login already matched to this browser."""
    app = Flask(__name__)
    app.secret_key = "test-only"
    app.broker_auth_functions = {"pocketful_auth": auth_function}
    stored, refused = [], []
    monkeypatch.setattr(brlogin, "begin_broker_login", lambda *a, **k: _pocketful_keys())
    monkeypatch.setattr(brlogin, "has_pending_login", lambda *a, **k: True)
    monkeypatch.setattr(brlogin, "verify_broker_return", lambda *a, **k: datetime.now(UTC))

    def store(auth_token, username, broker, feed_token=None, user_id=None):
        stored.append(
            {
                "token": auth_token,
                "user": username,
                "broker": broker,
                "feed": feed_token,
                "user_id": user_id,
            }
        )
        return "stored"

    def refuse(message, forward_url="broker.html"):
        refused.append(message)
        return "refused"

    monkeypatch.setattr(brlogin, "handle_auth_success", store)
    monkeypatch.setattr(brlogin, "handle_auth_failure", refuse)
    with app.test_request_context(f"/pocketful/callback?{query}"):
        session["user"] = "alice"
        answer = inspect.unwrap(brlogin.broker_callback)("pocketful")
    return answer, stored, refused


def test_the_callback_stores_the_packed_token_and_the_account(keys, client, logs, monkeypatch):
    answer, stored, refused = _callback(
        monkeypatch, f"code={CODE}&state=st-1&scope=orders+holdings", auth_api.authenticate_broker
    )

    assert answer == "stored" and refused == []
    assert stored == [
        {
            "token": f"YA0002:::{ACCESS}",
            "user": "alice",
            "broker": "pocketful",
            "feed": None,
            "user_id": "YA0002",
        }
    ]
    assert [s for s in SENTINELS if s in logs.text()] == []


def test_a_failed_exchange_stores_nothing(keys, client, logs, monkeypatch):
    client.token = _answer(400, {"error": "invalid_grant", "error_description": GRANT_DESCRIPTION})

    answer, stored, refused = _callback(
        monkeypatch, f"code={CODE}&state=st-1", auth_api.authenticate_broker
    )

    assert answer == "refused" and stored == []
    assert refused == [auth_api.CODE_REFUSED]


@pytest.mark.parametrize(
    ("query", "message"),
    [
        (
            "error=access_denied&error_description=The+resource+owner+denied+the+request.&state=st-1",
            auth_api.LOGIN_CANCELLED,
        ),
        ("error=invalid_scope&state=st-1", auth_api.SCOPE_REFUSED),
        ("state=st-1", auth_api.MISSING_CODE),
    ],
)
def test_an_answer_without_a_code_is_refused_in_plain_words(logs, monkeypatch, query, message):
    called = []

    answer, stored, refused = _callback(monkeypatch, query, lambda *a: called.append(a))

    assert answer == "refused" and stored == [] and called == []
    assert refused == [message]


def test_an_answer_for_no_login_started_here_never_reaches_pocketful(logs, monkeypatch):
    """The real check: a state this server did not issue is refused before the
    code is exchanged."""
    app = Flask(__name__)
    app.secret_key = "test-only"
    called = []
    app.broker_auth_functions = {"pocketful_auth": lambda *a: called.append(a)}
    monkeypatch.setattr(broker_login, "find_login_state", lambda *a, **k: None)

    with app.test_request_context(f"/pocketful/callback?code={CODE}&state=forged"):
        session["user"] = "alice"
        answer = inspect.unwrap(brlogin.broker_callback)("pocketful")

    assert called == []
    assert answer.status_code == 302
    assert "error=login_not_started" in answer.headers["Location"]
