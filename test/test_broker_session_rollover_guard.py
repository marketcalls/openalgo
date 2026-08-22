"""Regression tests for the broker-credential rollover guard (issue #1858).

Indian broker tokens die at the daily session boundary (SESSION_EXPIRY_TIME,
default 03:00 IST). OpenAlgo's expiry sweep runs from a ``before_request`` hook
that skips ``/api/`` (``app.py:509``) and reads the Flask cookie, so an
API-key-authenticated caller -- a strategy, TradingView, a scheduled script --
never triggers it. Between the rollover and the next *browser* request the
stored token is dead but still marked ``is_revoked=False``, so every quote and
history call is sent to the broker with yesterday's credential and comes back
as an HTTP 500 plus a full traceback.

``services/order_update_service.py:238`` already guards its boot scan with
``has_login_this_trading_session()`` and documents the gap. These tests pin the
same rule at the shared credential-resolution boundary
(``database.auth_db.get_auth_token_broker``) so every API caller inherits it.

No broker credentials and no network access: the database is in-memory and the
session rows are synthesised relative to the real boundary helper.
"""

import os
import sys
from datetime import timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# DATABASE_URL is left alone deliberately: conftest.py already points it at a
# test database, and assigning it here would leak into every module imported
# after this one and break tests that expect their own tables. Isolation comes
# from rebinding auth_db's session to a private in-memory engine below.

import utils.session as session_utils  # noqa: E402

TEST_USER = "test_trader"
TEST_API_KEY = "test_api_key_for_rollover_guard"
TEST_BROKER = "zerodha"


def _fresh_auth_db():
    """Return database.auth_db bound to a throwaway in-memory database.

    Mirrors test_orphaned_apikey.setup_test_db(): rebinding the module's
    scoped_session keeps each test isolated without a migration or a file on
    disk.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import scoped_session, sessionmaker

    import database.auth_db as auth_mod

    engine = create_engine("sqlite:///:memory:")
    auth_mod.db_session = scoped_session(
        sessionmaker(autocommit=False, autoflush=False, bind=engine)
    )
    auth_mod.Base.query = auth_mod.db_session.query_property()
    auth_mod.Base.metadata.create_all(engine)

    # A caller-visible token cache would mask the guard on the second call, and
    # the once-per-session teardown marker would carry a previous test's entry
    # into this one.
    auth_mod.auth_cache.clear()
    auth_mod._rollover_teardown_done.clear()
    return auth_mod


def _seed_connected_broker(auth_mod):
    """Create a valid API key plus a non-revoked auth row for TEST_USER.

    This is the state the reporter was in: OpenAlgo believes the broker is
    connected because nothing has flipped is_revoked yet.
    """
    auth_mod.upsert_auth(TEST_USER, "broker-token-from-yesterday", TEST_BROKER)
    auth_mod.upsert_api_key(TEST_USER, TEST_API_KEY)


def _session_rows(offset):
    """One active_sessions row whose login_time sits ``offset`` from today's
    boundary.

    Deriving from _todays_rollover_boundary() rather than a hardcoded clock is
    how the existing rollover tests stay deterministic without freezegun, which
    this repo does not depend on. SQLite strips tzinfo on storage, so the value
    is stored naive exactly as the production reader expects it.
    """
    login_at = session_utils._todays_rollover_boundary() + offset
    return [{"session_id": "device-1", "login_time": login_at.replace(tzinfo=None).isoformat()}]


@pytest.fixture
def auth_mod(monkeypatch):
    """auth_db on a clean in-memory DB, with expiry enabled (non-crypto broker)."""
    monkeypatch.delenv("DISABLE_SESSION_EXPIRY", raising=False)
    mod = _fresh_auth_db()
    _seed_connected_broker(mod)
    return mod


class TestRolloverGuard:
    """The stale credential must never reach a broker adapter."""

    def test_stale_login_is_rejected(self, auth_mod, monkeypatch):
        """The reported bug: a pre-boundary login still resolves a credential.

        This is the failing test to write first. Today get_auth_token_broker()
        checks only is_revoked, so it hands back yesterday's token and the
        caller goes on to build a BrokerData handler with it.
        """
        monkeypatch.setattr(
            auth_mod, "get_active_sessions", lambda u: _session_rows(-timedelta(hours=5))
        )

        auth_token, broker = auth_mod.get_auth_token_broker(TEST_API_KEY)

        assert auth_token is None, (
            "a login before today's rollover means the stored broker token is "
            "dead; resolving it sends the previous session's credential to the broker"
        )
        assert broker is None

    def test_fresh_login_still_resolves(self, auth_mod, monkeypatch):
        """The guard must not break the normal case: logged in after the boundary."""
        monkeypatch.setattr(
            auth_mod, "get_active_sessions", lambda u: _session_rows(timedelta(hours=2))
        )

        auth_token, broker = auth_mod.get_auth_token_broker(TEST_API_KEY)

        assert auth_token == "broker-token-from-yesterday"
        assert broker == TEST_BROKER

    def test_login_exactly_at_boundary_counts_as_fresh(self, auth_mod, monkeypatch):
        """A login landing on 03:00:00.000 is inside the new session, not outside.

        _has_fresher_session() compares with >=, so the boundary instant belongs
        to the session it opens. Pinning it stops a later refactor from
        silently turning that into > and logging out anyone who authenticated
        on the exact second.
        """
        monkeypatch.setattr(auth_mod, "get_active_sessions", lambda u: _session_rows(timedelta(0)))

        auth_token, _ = auth_mod.get_auth_token_broker(TEST_API_KEY)

        assert auth_token == "broker-token-from-yesterday"

    def test_no_sessions_at_all_is_stale(self, auth_mod, monkeypatch):
        """An empty active_sessions table cannot prove a login happened today."""
        monkeypatch.setattr(auth_mod, "get_active_sessions", lambda u: [])

        auth_token, _ = auth_mod.get_auth_token_broker(TEST_API_KEY)

        assert auth_token is None

    def test_feed_token_variant_is_guarded_too(self, auth_mod, monkeypatch):
        """include_feed_token=True is the path quotes take; it must not leak past."""
        monkeypatch.setattr(
            auth_mod, "get_active_sessions", lambda u: _session_rows(-timedelta(hours=5))
        )

        auth_token, feed_token, broker = auth_mod.get_auth_token_broker(
            TEST_API_KEY, include_feed_token=True
        )

        assert (auth_token, feed_token, broker) == (None, None, None)


class TestCryptoBypass:
    """DISABLE_SESSION_EXPIRY=true brokers trade 24/7 and never roll over."""

    def test_disabled_expiry_keeps_resolving(self, monkeypatch):
        monkeypatch.setenv("DISABLE_SESSION_EXPIRY", "true")
        mod = _fresh_auth_db()
        _seed_connected_broker(mod)
        monkeypatch.setattr(mod, "get_active_sessions", lambda u: _session_rows(-timedelta(days=3)))

        auth_token, broker = mod.get_auth_token_broker(TEST_API_KEY)

        assert auth_token == "broker-token-from-yesterday", (
            "a crypto instance has no 3 AM boundary; guarding it would break "
            "Delta Exchange every night"
        )
        assert broker == TEST_BROKER


class TestTeardownIsIdempotent:
    """A polling client must not turn one rollover into a teardown storm."""

    def test_teardown_runs_once_per_trading_session(self, auth_mod, monkeypatch):
        """A strategy polling every 5s would otherwise publish 720 ZMQ
        invalidations an hour, each one disconnecting the WebSocket adapter in
        the proxy process."""
        monkeypatch.setattr(
            auth_mod, "get_active_sessions", lambda u: _session_rows(-timedelta(hours=5))
        )

        teardowns = []
        monkeypatch.setattr(
            session_utils,
            "revoke_user_tokens",
            lambda username=None, **kwargs: teardowns.append(username),
        )

        for _ in range(5):
            auth_mod.get_auth_token_broker(TEST_API_KEY)

        assert len(teardowns) == 1, f"expected one teardown, got {len(teardowns)}"


class TestServiceResponses:
    """Quote and history must report a reconnect, not a bad API key or a 500."""

    def test_quotes_returns_broker_session_expired(self, monkeypatch):
        """403 'Invalid openalgo apikey' is wrong twice over here: the API key is
        valid, and the caller needs the reconnect signal Dashboard.tsx:84 reads."""
        import services.quotes_service as quotes_service

        monkeypatch.setattr(
            quotes_service, "get_auth_token_broker", lambda *a, **k: (None, None, None)
        )
        monkeypatch.setattr(
            quotes_service, "is_broker_session_stale", lambda api_key: True, raising=False
        )

        success, response, status = quotes_service.get_quotes("SBIN", "NSE", api_key=TEST_API_KEY)

        assert success is False
        assert status == 401
        assert response["code"] == "BROKER_SESSION_EXPIRED"

    def test_history_returns_broker_session_expired(self, monkeypatch):
        import services.history_service as history_service

        monkeypatch.setattr(
            history_service, "get_auth_token_broker", lambda *a, **k: (None, None, None)
        )
        monkeypatch.setattr(
            history_service, "is_broker_session_stale", lambda api_key: True, raising=False
        )

        success, response, status = history_service.get_history(
            "SBIN", "NSE", "1d", "2026-08-01", "2026-08-20", api_key=TEST_API_KEY
        )

        assert success is False
        assert status == 401
        assert response["code"] == "BROKER_SESSION_EXPIRED"

    def test_invalid_api_key_still_returns_403(self, monkeypatch):
        """Only the stale-session case changes; a genuinely bad key keeps its
        existing 403 so callers are not told to reconnect a broker that is fine."""
        import services.quotes_service as quotes_service

        monkeypatch.setattr(
            quotes_service, "get_auth_token_broker", lambda *a, **k: (None, None, None)
        )
        monkeypatch.setattr(
            quotes_service, "is_broker_session_stale", lambda api_key: False, raising=False
        )

        success, response, status = quotes_service.get_quotes(
            "SBIN", "NSE", api_key="not-a-real-key"
        )

        assert success is False
        assert status == 403
        assert "code" not in response


class TestLogHygiene:
    """Nothing about the rejection may reveal the credential it rejected."""

    def test_rejection_logs_no_token_material(self, auth_mod, monkeypatch, caplog):
        monkeypatch.setattr(
            auth_mod, "get_active_sessions", lambda u: _session_rows(-timedelta(hours=5))
        )

        with caplog.at_level("DEBUG"):
            auth_mod.get_auth_token_broker(TEST_API_KEY)

        logged = caplog.text
        assert "broker-token-from-yesterday" not in logged
        assert TEST_API_KEY not in logged
        assert TEST_API_KEY[:8] not in logged, "not even a prefix of the key"
