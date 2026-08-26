"""Tests for /auth/session-status broker-freshness reporting (issue #1858).

`/auth/session-status` is in `check_session_expiry`'s skip list, so it is
reachable without the auto-expiry sweep ever running. Before this change it
reported a broker session as connected whenever a token row existed, which
between the daily rollover and the next sweep is exactly when the token is
dead.

It now asks the same three-valued freshness question the API path asks, so the
three cases below are the contract: confirmed stale reports the reconnect flag,
fresh reports normally, and an undecidable reading must not raise a false alarm
against a live session.

No network and no broker credentials: the database reads are monkeypatched and
the route is called inside a bare Flask request context.
"""

import os
import sys
from datetime import datetime

import pytest
import pytz
from flask import Flask, session

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import blueprints.auth as auth_bp_module  # noqa: E402
import database.auth_db as auth_db  # noqa: E402

TEST_USER = "test_trader"
TEST_BROKER = "zerodha"


@pytest.fixture()
def logged_in_request(monkeypatch):
    """A request context for a user with a live app session and a broker set."""
    # The heartbeat writes to active_sessions; irrelevant here and it would need
    # a real database.
    monkeypatch.setattr(auth_bp_module, "_touch_session_heartbeat", lambda: None)
    monkeypatch.setattr(auth_db, "get_api_key_for_tradingview", lambda user: "test-api-key")
    monkeypatch.setattr(auth_db, "get_active_sessions", lambda user: [{"session_id": "d1"}])

    app = Flask(__name__)
    app.secret_key = "test-secret"
    with app.test_request_context("/auth/session-status", method="GET"):
        session["user"] = TEST_USER
        session["logged_in"] = True
        session["broker"] = TEST_BROKER
        yield


def _payload(response):
    """get_session_status returns either a response or a (response, status) pair."""
    body, status = response if isinstance(response, tuple) else (response, 200)
    return body.get_json(), status


def test_stale_broker_session_reports_reconnect(logged_in_request, monkeypatch):
    """A token row is not proof of a live broker session.

    The sweep that flips is_revoked runs from a before_request hook that skips
    this endpoint, so without the freshness check the dashboard is told the
    broker is connected while every order fails.
    """
    monkeypatch.setattr(auth_db, "get_auth_token", lambda user: "token-from-yesterday")
    monkeypatch.setattr(auth_db, "is_broker_session_stale_for_user", lambda user: True)

    payload, status = _payload(auth_bp_module.get_session_status())

    assert status == 200
    assert payload["broker_session_expired"] is True
    # The APP session must survive: logged_in doubles as the app-session flag in
    # is_session_valid(), so downgrading it here hard-logs-out the user before
    # the reconnect UI can render (issue #1400).
    assert payload["logged_in"] is True
    assert payload["authenticated"] is True
    assert payload["broker"] == TEST_BROKER


def test_fresh_broker_session_reports_normally(logged_in_request, monkeypatch):
    """The common case must not gain a reconnect prompt."""
    monkeypatch.setattr(auth_db, "get_auth_token", lambda user: "todays-token")
    monkeypatch.setattr(auth_db, "is_broker_session_stale_for_user", lambda user: False)

    payload, status = _payload(auth_bp_module.get_session_status())

    assert status == 200
    assert "broker_session_expired" not in payload
    assert payload["api_key"] == "test-api-key"
    assert payload["active_sessions"] == 1


def test_undecidable_freshness_does_not_raise_a_false_alarm(logged_in_request, monkeypatch):
    """An empty active_sessions must not render Reconnect Broker.

    This calls the real is_broker_session_stale_for_user() rather than stubbing
    its answer -- stubbing False here would only restate the fresh case above.
    An empty table is the state a password change leaves behind
    (blueprints/auth.py clear_user_sessions) while deliberately keeping the
    broker token alive, and get_active_sessions() also returns [] on a failed
    read, so the verdict is unknown, not stale.

    Without this, every browser is told broker_session_expired against a live
    session while is_session_valid() still says the app session is fine, and
    nothing self-corrects: _touch_session_heartbeat updates last_seen, not
    login_time.
    """
    monkeypatch.delenv("DISABLE_SESSION_EXPIRY", raising=False)
    monkeypatch.setattr(auth_db, "get_auth_token", lambda user: "todays-token")
    monkeypatch.setattr(auth_db, "get_active_sessions", lambda user: [])
    auth_db._session_freshness_cache.clear()

    payload, _ = _payload(auth_bp_module.get_session_status())

    assert "broker_session_expired" not in payload, (
        "no session rows means the freshness of the broker token cannot be "
        "determined; that is not grounds for telling the user to reconnect"
    )


def test_missing_token_still_reports_reconnect(logged_in_request, monkeypatch):
    """The pre-existing case: no token row at all (revoked or logged out)."""
    monkeypatch.setattr(auth_db, "get_auth_token", lambda user: None)
    monkeypatch.setattr(auth_db, "is_broker_session_stale_for_user", lambda user: False)

    payload, _ = _payload(auth_bp_module.get_session_status())

    assert payload["broker_session_expired"] is True
    assert payload["logged_in"] is True


@pytest.fixture()
def dashboard_request(logged_in_request):
    """/auth/dashboard-data is wrapped in @check_session_validity.

    is_session_valid() requires session["login_time"]; without it the decorator
    revokes the broker token and clears the session before the route body ever
    runs, so the test would assert against the decorator rather than the route.
    "now" always passes: if the boundary has been crossed the login is after it,
    and if it has not, the expiry branch is not taken at all.
    """
    session["login_time"] = datetime.now(pytz.timezone("Asia/Kolkata")).isoformat()
    yield


class TestDashboardDataAgrees:
    """/auth/session-status and /auth/dashboard-data must not disagree about
    the same broker session.

    The review noted that the recovery contract described at get_session_status
    -- "dashboard-data returns BROKER_SESSION_EXPIRED and the dashboard renders
    the Reconnect Broker action" -- was not implemented for the state this guard
    creates. dashboard-data resolves through get_auth_token(), which is
    deliberately unguarded so the freshness inference never reaches the shared
    WebSocket feed (websocket_proxy/base_adapter.py:446), so a stale-but-present
    token read as connected and the route handed it to the broker. The dashboard
    then showed a broker error rather than the reconnect CTA that
    frontend/src/pages/Dashboard.tsx:84 already implements.
    """

    def test_stale_broker_session_answers_the_reconnect_code(
        self, dashboard_request, monkeypatch
    ):
        import database.settings_db as settings_db

        monkeypatch.setattr(auth_db, "get_auth_token", lambda user: "token-from-yesterday")
        monkeypatch.setattr(auth_db, "is_broker_session_stale_for_user", lambda user: True)
        monkeypatch.setattr(settings_db, "get_analyze_mode", lambda: False)

        def fail_if_called(*a, **k):
            raise AssertionError("the broker was called with a stale credential")

        monkeypatch.setattr("services.funds_service.get_funds", fail_if_called)

        payload, status = _payload(auth_bp_module.get_dashboard_data())

        assert status == 401
        assert payload["code"] == "BROKER_SESSION_EXPIRED"

    def test_fresh_broker_session_still_reaches_the_broker(
        self, dashboard_request, monkeypatch
    ):
        import database.settings_db as settings_db

        monkeypatch.setattr(auth_db, "get_auth_token", lambda user: "todays-token")
        monkeypatch.setattr(auth_db, "is_broker_session_stale_for_user", lambda user: False)
        monkeypatch.setattr(settings_db, "get_analyze_mode", lambda: False)
        monkeypatch.setattr(
            "services.funds_service.get_funds",
            lambda *a, **k: (True, {"data": {"availablecash": "1000"}}, 200),
        )

        payload, status = _payload(auth_bp_module.get_dashboard_data())

        assert status == 200
        assert payload["data"]["availablecash"] == "1000"

    def test_analyze_mode_is_not_gated_on_the_broker_session(
        self, dashboard_request, monkeypatch
    ):
        """The sandbox is isolated from live trading, so a rolled-over broker
        session must not take the sandbox dashboard down with it -- the same
        rule the order services apply before resolving a credential."""
        import database.settings_db as settings_db

        monkeypatch.setattr(auth_db, "get_auth_token", lambda user: "token-from-yesterday")
        monkeypatch.setattr(settings_db, "get_analyze_mode", lambda: True)

        def fail_if_called(user):
            raise AssertionError(
                "analyze mode must not ask whether the live broker session is fresh"
            )

        monkeypatch.setattr(auth_db, "is_broker_session_stale_for_user", fail_if_called)
        monkeypatch.setattr(
            "services.funds_service.get_funds",
            lambda *a, **k: (True, {"data": {"availablecash": "10000000"}}, 200),
        )

        payload, status = _payload(auth_bp_module.get_dashboard_data())

        assert status == 200
        assert payload["data"]["availablecash"] == "10000000"
