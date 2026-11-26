"""The /api/websocket/* routes honour the daily session rollover.

The app-wide expiry check in app.py skips /api/, and these routes, with the
/market Socket.IO handlers, accepted any cookie that carried a username. A
cookie from before the 03:00 IST rollover, which every page route turns away,
still read the live API key from GET /api/websocket/apikey, and Flask re-signed
it on every response, so replaying it kept it alive.

is_session_valid() also compared a login only against today's rollover, so
between midnight and 03:00 it accepted a login of any age.

The clock in utils.session is frozen; everything else is the real code.
"""

from __future__ import annotations

from datetime import datetime as real_datetime

import pytest
import pytz
from flask import Flask, session

import database.auth_db as auth_db
import utils.session as session_utils
from blueprints import websocket_example
from blueprints.websocket_example import websocket_bp

IST = pytz.timezone("Asia/Kolkata")
API_KEY = "live-api-key-of-trader"


def ist(*args) -> real_datetime:
    return IST.localize(real_datetime(*args))


@pytest.fixture(autouse=True)
def _default_rollover(monkeypatch):
    monkeypatch.setenv("DISABLE_SESSION_EXPIRY", "false")
    monkeypatch.delenv("SESSION_EXPIRY_TIME", raising=False)


@pytest.fixture
def clock(monkeypatch):
    """Set the IST wall clock that utils.session reads."""

    def set_to(moment: real_datetime) -> None:
        class Frozen(real_datetime):
            @classmethod
            def now(cls, tz=None):
                return moment.astimezone(tz) if tz else moment.replace(tzinfo=None)

        monkeypatch.setattr(session_utils, "datetime", Frozen)

    return set_to


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setattr(auth_db, "get_api_key_for_tradingview", lambda username: API_KEY)
    flask_app = Flask(__name__)
    flask_app.config.update(SECRET_KEY="test", TESTING=True)
    flask_app.register_blueprint(websocket_bp)
    return flask_app


def _client(app, login: real_datetime | None):
    client = app.test_client()
    if login is not None:
        with client.session_transaction() as s:
            s.permanent = True
            s["user"] = "trader"
            s["logged_in"] = True
            s["login_time"] = login.isoformat()
    return client


ROUTES = [
    ("get", "/api/websocket/apikey"),
    ("get", "/api/websocket/config"),
    ("get", "/api/websocket/status"),
    ("get", "/api/websocket/subscriptions"),
    ("get", "/api/websocket/market-data"),
    ("get", "/api/websocket/health"),
    ("get", "/api/websocket/trade-safe"),
    ("get", "/api/websocket/metrics"),
    ("post", "/api/websocket/subscribe"),
    ("post", "/api/websocket/unsubscribe"),
    ("post", "/api/websocket/unsubscribe-all"),
]


# --- is_session_valid: the most recent rollover, not only today's ----------


@pytest.mark.parametrize(
    ("now", "login", "valid"),
    [
        # Between midnight and 03:00 the last rollover was yesterday's.
        (ist(2026, 10, 30, 1, 0), ist(2026, 10, 27, 10, 0), False),  # three days old
        (ist(2026, 10, 30, 1, 0), ist(2026, 10, 29, 2, 0), False),  # before yesterday's 03:00
        (ist(2026, 10, 30, 1, 0), ist(2026, 10, 29, 10, 0), True),  # yesterday's trading day
        # After 03:00 the last rollover is today's.
        (ist(2026, 10, 30, 10, 0), ist(2026, 10, 29, 10, 0), False),
        (ist(2026, 10, 30, 10, 0), ist(2026, 10, 30, 9, 0), True),
    ],
)
def test_a_session_is_valid_only_since_the_last_rollover(app, clock, now, login, valid):
    clock(now)
    with app.test_request_context():
        session.update(user="trader", logged_in=True, login_time=login.isoformat())
        assert session_utils.is_session_valid() is valid


# --- the routes: a stale cookie is treated exactly like no cookie ------------


@pytest.mark.parametrize(("method", "path"), ROUTES)
@pytest.mark.parametrize(
    ("now", "login"),
    [
        (ist(2026, 10, 30, 10, 0), ist(2026, 10, 29, 10, 0)),  # after the rollover
        (ist(2026, 10, 30, 1, 0), ist(2026, 10, 27, 10, 0)),  # midnight to 03:00
    ],
)
def test_a_cookie_from_before_the_rollover_is_not_signed_in(app, clock, method, path, now, login):
    clock(now)
    stale = getattr(_client(app, login), method)(path)
    anonymous = getattr(_client(app, None), method)(path)

    assert API_KEY not in stale.get_data(as_text=True)
    assert (stale.status_code, stale.get_json()) == (anonymous.status_code, anonymous.get_json())


def test_a_current_session_still_reads_its_api_key(app, clock):
    """The control: without it the tests above could pass on a broken route."""
    clock(ist(2026, 10, 30, 10, 0))
    response = _client(app, ist(2026, 10, 30, 9, 0)).get("/api/websocket/apikey")

    assert response.status_code == 200
    assert response.get_json() == {"status": "success", "api_key": API_KEY}


def test_a_stale_session_cannot_open_the_market_socket(app, clock):
    clock(ist(2026, 10, 30, 10, 0))
    with app.test_request_context():
        session.update(
            user="trader", logged_in=True, login_time=ist(2026, 10, 29, 10, 0).isoformat()
        )
        assert websocket_example.get_username_from_session() is None
        assert websocket_example.handle_connect(None) is False


def test_an_expired_session_revokes_nothing_from_these_routes(app, clock, monkeypatch):
    """Open tabs poll these routes; a stale one must not tear down a live token."""
    revoked = []
    monkeypatch.setattr(session_utils, "revoke_user_tokens", lambda *a, **k: revoked.append(1))
    clock(ist(2026, 10, 30, 10, 0))

    _client(app, ist(2026, 10, 29, 10, 0)).get("/api/websocket/status")

    assert revoked == []
