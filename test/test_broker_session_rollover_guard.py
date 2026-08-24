"""Regression tests for the broker-credential rollover guard (issue #1858).

Indian broker tokens die at the daily session boundary (SESSION_EXPIRY_TIME,
default 03:00 IST). OpenAlgo's expiry sweep runs from a ``before_request`` hook
that skips ``/api/`` (``app.py:510``) and reads the Flask cookie, so an
API-key-authenticated caller -- a strategy, TradingView, a scheduled script --
never triggers it. Between the rollover and the next *browser* request the
stored token is dead but still marked ``is_revoked=False``, so every quote and
history call is sent to the broker with yesterday's credential and comes back
as an HTTP 500 plus a full traceback.

The guard withholds such a credential at the shared resolution point
(``database.auth_db.get_auth_token_broker``) so every API caller inherits it.
It never destroys the credential: the freshness signal is an *inference* from
``active_sessions`` login times, and the states that inference cannot decide --
no rows, an unreadable row, a failed read -- must keep working exactly as
before. These tests pin both halves.

No broker credentials and no network access: the database is in-memory, every
side effect of ``upsert_auth`` that opens a socket or a thread is stubbed, and
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
STORED_TOKEN = "broker-token-from-yesterday"


@pytest.fixture(autouse=True)
def no_side_effects(monkeypatch):
    """Neutralise every socket-, thread- and process-touching side effect of
    upsert_auth.

    Without this, seeding a token reaches start_order_update_adapter
    (database/auth_db.py:624) and opens a real WebSocket to the broker -- the
    suite then depends on the network and prints a live 403 from Zerodha. The
    ZeroMQ publish and the pool cleanup create sockets and threads per fixture
    for the same reason. Same pattern as test_auth_upsert_multisession.py.
    """
    monkeypatch.setattr(
        "database.cache_invalidation.publish_all_cache_invalidation",
        lambda name: True,
    )
    monkeypatch.setattr(
        "websocket_proxy.broker_factory.cleanup_pools_for_user",
        lambda name, broker_name=None: 0,
    )
    monkeypatch.setattr(
        "services.order_update_service.start_order_update_adapter",
        lambda name, broker: None,
    )
    monkeypatch.setattr(
        "services.order_update_service.stop_order_update_adapter",
        lambda name: None,
    )


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
    # a cached freshness verdict would carry a previous test's answer into this
    # one.
    auth_mod.auth_cache.clear()
    auth_mod.verified_api_key_cache.clear()
    auth_mod.invalid_api_key_cache.clear()
    auth_mod._session_freshness_cache.clear()
    auth_mod._stale_log_throttle.clear()
    return auth_mod


def _seed_connected_broker(auth_mod):
    """Create a valid API key plus a non-revoked auth row for TEST_USER.

    This is the state the reporter was in: OpenAlgo believes the broker is
    connected because nothing has flipped is_revoked yet.
    """
    auth_mod.upsert_auth(TEST_USER, STORED_TOKEN, TEST_BROKER)
    auth_mod.upsert_api_key(TEST_USER, TEST_API_KEY)


def _session_rows(offset, session_id="device-1"):
    """One active_sessions row whose login_time sits ``offset`` from the current
    trading session's boundary.

    Deriving from _current_session_boundary() rather than a hardcoded clock is
    how the existing rollover tests stay deterministic without freezegun, which
    this repo does not depend on -- and unlike _todays_rollover_boundary() it is
    also correct when the suite runs between midnight and 03:00 IST. SQLite
    strips tzinfo on storage, so the value is stored naive exactly as the
    production reader expects it.
    """
    login_at = session_utils._current_session_boundary() + offset
    return [{"session_id": session_id, "login_time": login_at.replace(tzinfo=None).isoformat()}]


def _stored_auth_row(auth_mod):
    """The persisted credential, as the next login's resume path would read it."""
    return auth_mod.Auth.query.filter_by(name=TEST_USER).first()


@pytest.fixture
def auth_mod(monkeypatch):
    """auth_db on a clean in-memory DB, with expiry enabled (non-crypto broker)."""
    monkeypatch.delenv("DISABLE_SESSION_EXPIRY", raising=False)
    mod = _fresh_auth_db()
    _seed_connected_broker(mod)
    return mod


class TestBoundaryMath:
    """The boundary a login is judged against must be one that has been crossed."""

    def test_boundary_belongs_to_the_previous_day_until_it_is_reached(self, monkeypatch):
        """Walk a full day: before SESSION_EXPIRY_TIME the live session is
        yesterday's.

        _current_session_boundary() takes its "now" as an argument, so this
        needs no clock patching and gives the same answer whenever CI runs it.
        """
        monkeypatch.setenv("SESSION_EXPIRY_TIME", "03:00")
        ist = session_utils.pytz.timezone("Asia/Kolkata")

        for hour in range(24):
            now = ist.localize(session_utils.datetime(2026, 8, 24, hour, 0))
            boundary = session_utils._current_session_boundary(now)
            expected_day = 23 if hour < 3 else 24
            assert boundary.day == expected_day, (
                f"at {hour:02d}:00 the session boundary should be "
                f"Aug {expected_day} 03:00, got {boundary}"
            )
            assert boundary <= now, "a boundary in the future has not been crossed"

    def test_pre_boundary_window_is_not_stale(self, auth_mod, monkeypatch):
        """Between midnight and SESSION_EXPIRY_TIME, last evening's login is live.

        _todays_rollover_boundary() returns today's clock time unconditionally,
        so in that window it is a *future* instant and every healthy overnight
        session compares as pre-boundary. MCX runs to 23:30 IST, so this window
        contains live positions.

        The boundary is monkeypatched rather than derived from SESSION_EXPIRY_TIME
        so the window under test is chosen, not inherited from the wall clock.
        Setting the env var to now+2h wraps past midnight when the suite runs
        after 22:00 IST, and the day-subtraction branch is then never taken -- the
        assertion would hold with or without the fix, pinning nothing.
        """
        now_ist = session_utils.datetime.now(session_utils.pytz.timezone("Asia/Kolkata"))
        boundary_still_ahead = now_ist + timedelta(hours=2)
        monkeypatch.setattr(
            session_utils, "_todays_rollover_boundary", lambda now_ist=None: boundary_still_ahead
        )
        auth_mod._session_freshness_cache.clear()

        login_an_hour_ago = now_ist - timedelta(hours=1)
        monkeypatch.setattr(
            auth_mod,
            "get_active_sessions",
            lambda u: [
                {
                    "session_id": "device-1",
                    "login_time": login_an_hour_ago.replace(tzinfo=None).isoformat(),
                }
            ],
        )

        auth_token, broker = auth_mod.get_auth_token_broker(TEST_API_KEY)

        assert (auth_token, broker) == (STORED_TOKEN, TEST_BROKER), (
            "a login one hour ago cannot predate a boundary two hours in the "
            "future; today's clock time is not the session boundary before it "
            "has been crossed"
        )


class TestRolloverGuard:
    """The stale credential must never reach a broker adapter."""

    def test_stale_login_is_rejected(self, auth_mod, monkeypatch):
        """The reported bug: a pre-boundary login still resolves a credential."""
        monkeypatch.setattr(
            auth_mod, "get_active_sessions", lambda u: _session_rows(-timedelta(hours=5))
        )

        auth_token, broker = auth_mod.get_auth_token_broker(TEST_API_KEY)

        assert auth_token is None, (
            "a login before the current session boundary means the stored broker "
            "token is dead; resolving it sends the previous session's credential "
            "to the broker"
        )
        assert broker is None

    def test_fresh_login_still_resolves(self, auth_mod, monkeypatch):
        """The guard must not break the normal case: logged in after the boundary."""
        monkeypatch.setattr(
            auth_mod, "get_active_sessions", lambda u: _session_rows(timedelta(hours=2))
        )

        auth_token, broker = auth_mod.get_auth_token_broker(TEST_API_KEY)

        assert auth_token == STORED_TOKEN
        assert broker == TEST_BROKER

    def test_login_exactly_at_boundary_counts_as_fresh(self, auth_mod, monkeypatch):
        """A login landing on 03:00:00.000 is inside the new session, not outside.

        The comparison is >=, so the boundary instant belongs to the session it
        opens. Pinning it stops a later refactor from silently turning that into
        > and logging out anyone who authenticated on the exact second.
        """
        monkeypatch.setattr(auth_mod, "get_active_sessions", lambda u: _session_rows(timedelta(0)))

        auth_token, _ = auth_mod.get_auth_token_broker(TEST_API_KEY)

        assert auth_token == STORED_TOKEN

    def test_feed_token_variant_is_guarded_too(self, auth_mod, monkeypatch):
        """include_feed_token=True is the path quotes take; it must not leak past."""
        monkeypatch.setattr(
            auth_mod, "get_active_sessions", lambda u: _session_rows(-timedelta(hours=5))
        )

        auth_token, feed_token, broker = auth_mod.get_auth_token_broker(
            TEST_API_KEY, include_feed_token=True
        )

        assert (auth_token, feed_token, broker) == (None, None, None)

    def test_one_fresh_device_keeps_the_shared_token(self, auth_mod, monkeypatch):
        """The broker token is shared across devices; one fresh login revives it
        for all of them, so a stale sibling row must not veto."""
        rows = _session_rows(-timedelta(hours=5), session_id="stale-device") + _session_rows(
            timedelta(minutes=30), session_id="fresh-device"
        )
        monkeypatch.setattr(auth_mod, "get_active_sessions", lambda u: rows)

        auth_token, _ = auth_mod.get_auth_token_broker(TEST_API_KEY)

        assert auth_token == STORED_TOKEN


class TestUndecidableStateIsNotStale:
    """An inference that cannot decide must fall back to today's behaviour."""

    def test_cleared_sessions_keep_a_live_token(self, auth_mod, monkeypatch):
        """A password change clears active_sessions and *deliberately* keeps the
        broker token alive (blueprints/auth.py:811) so the user can log back in
        without redoing broker OAuth. An empty table is therefore not proof of a
        rollover, and must not cost the user a working credential mid-session.
        """
        auth_mod.clear_user_sessions(TEST_USER)
        auth_mod._session_freshness_cache.clear()

        auth_token, broker = auth_mod.get_auth_token_broker(TEST_API_KEY)

        assert (auth_token, broker) == (STORED_TOKEN, TEST_BROKER), (
            "no session rows means 'cannot tell', not 'stale'"
        )

    def test_unreadable_session_store_keeps_a_live_token(self, auth_mod, monkeypatch):
        """A transient SQLite lock must not read as a rollover.

        get_active_sessions() catches Exception and returns [] (auth_db.py:395),
        so a failed read is indistinguishable from an empty table; CLAUDE.md
        notes SQLite locking is stricter on Windows.
        """

        def locked(_username):
            raise RuntimeError("database is locked")

        monkeypatch.setattr(auth_mod, "get_active_sessions", locked)

        auth_token, broker = auth_mod.get_auth_token_broker(TEST_API_KEY)

        assert (auth_token, broker) == (STORED_TOKEN, TEST_BROKER)

    def test_unparseable_login_time_is_not_evidence(self, auth_mod, monkeypatch):
        """A row we cannot read does not count towards 'every login predates it'."""
        monkeypatch.setattr(
            auth_mod,
            "get_active_sessions",
            lambda u: [{"session_id": "device-1", "login_time": "not-a-timestamp"}],
        )

        auth_token, _ = auth_mod.get_auth_token_broker(TEST_API_KEY)

        assert auth_token == STORED_TOKEN


class TestCredentialSurvives:
    """Withholding is not revoking."""

    def test_stale_rejection_leaves_the_stored_token_intact(self, auth_mod, monkeypatch):
        """Revoking here would reach upsert_auth(name, "", "", revoke=True), which
        overwrites auth_obj.auth and auth_obj.broker. That is irreversible, and
        blueprints/auth.py:202 then refuses to resume, forcing full broker OAuth.
        The next login must still find its credential where it left it.
        """
        monkeypatch.setattr(
            auth_mod, "get_active_sessions", lambda u: _session_rows(-timedelta(hours=5))
        )

        for _ in range(5):
            assert auth_mod.get_auth_token_broker(TEST_API_KEY) == (None, None)

        row = _stored_auth_row(auth_mod)
        assert row is not None
        assert row.is_revoked is False, "the guard must not flip is_revoked"
        assert row.broker == TEST_BROKER, "the guard must not blank the broker"
        assert auth_mod.decrypt_token(row.auth) == STORED_TOKEN

    def test_repeated_rejection_publishes_no_teardown(self, auth_mod, monkeypatch):
        """A polling client must not turn one rollover into a teardown storm.

        The earlier shape of this guard revoked once per trading session, keyed
        by a TTLCache whose max(300, ...) clamp could expire mid-session and let
        the whole teardown -- a ZeroMQ CACHE_INVALIDATE_ALL, a pool cleanup, an
        adapter stop and a force_logout broadcast -- run again. Withholding has
        no side effects at all, which is the property to keep.
        """
        monkeypatch.setattr(
            auth_mod, "get_active_sessions", lambda u: _session_rows(-timedelta(hours=5))
        )

        published = []
        monkeypatch.setattr(
            "database.cache_invalidation.publish_all_cache_invalidation",
            lambda name: published.append(name) or True,
        )
        cleaned = []
        monkeypatch.setattr(
            "websocket_proxy.broker_factory.cleanup_pools_for_user",
            lambda name, broker_name=None: cleaned.append(name) or 0,
        )

        for _ in range(20):
            auth_mod.get_auth_token_broker(TEST_API_KEY)

        assert published == []
        assert cleaned == []

    def test_rejection_log_is_throttled(self, auth_mod, monkeypatch, caplog):
        """The rejection line must not scale with poll rate.

        A strategy polling every 5s after the 03:00 rollover would otherwise
        write ~720 identical lines an hour into log/, and the production worker
        is a single Gunicorn process that never restarts to truncate them.
        """
        monkeypatch.setattr(
            auth_mod, "get_active_sessions", lambda u: _session_rows(-timedelta(hours=5))
        )

        with caplog.at_level("INFO"):
            for _ in range(50):
                auth_mod.get_auth_token_broker(TEST_API_KEY)

        emitted = [r for r in caplog.records if "Broker session rollover" in r.getMessage()]
        assert len(emitted) == 1, f"expected one line for 50 rejections, got {len(emitted)}"


class TestCryptoBypass:
    """DISABLE_SESSION_EXPIRY=true brokers trade 24/7 and never roll over."""

    def test_disabled_expiry_keeps_resolving(self, monkeypatch):
        monkeypatch.setenv("DISABLE_SESSION_EXPIRY", "true")
        mod = _fresh_auth_db()
        _seed_connected_broker(mod)
        monkeypatch.setattr(mod, "get_active_sessions", lambda u: _session_rows(-timedelta(days=3)))

        auth_token, broker = mod.get_auth_token_broker(TEST_API_KEY)

        assert auth_token == STORED_TOKEN, (
            "a crypto instance has no 3 AM boundary; guarding it would break "
            "Delta Exchange every night"
        )
        assert broker == TEST_BROKER


class TestServiceResponses:
    """Quote and history must report a reconnect, not a bad API key or a 500."""

    def test_quotes_returns_broker_session_expired(self, monkeypatch):
        """403 'Invalid openalgo apikey' is wrong twice over here: the API key is
        valid, and the caller needs the reconnect signal the dashboard reads."""
        import services.quotes_service as quotes_service

        monkeypatch.setattr(
            quotes_service, "get_auth_token_broker", lambda *a, **k: (None, None, None)
        )
        monkeypatch.setattr(quotes_service, "is_broker_session_stale", lambda api_key: True)

        success, response, status = quotes_service.get_quotes("SBIN", "NSE", api_key=TEST_API_KEY)

        assert success is False
        assert status == 401
        assert response["code"] == "BROKER_SESSION_EXPIRED"

    def test_multiquotes_agrees_with_quotes(self, monkeypatch):
        """/quotes and /multiquotes must not disagree about the same condition."""
        import services.quotes_service as quotes_service

        monkeypatch.setattr(
            quotes_service, "get_auth_token_broker", lambda *a, **k: (None, None, None)
        )
        monkeypatch.setattr(quotes_service, "is_broker_session_stale", lambda api_key: True)

        success, response, status = quotes_service.get_multiquotes(
            [{"symbol": "SBIN", "exchange": "NSE"}], api_key=TEST_API_KEY
        )

        assert success is False
        assert status == 401
        assert response["code"] == "BROKER_SESSION_EXPIRED"

    def test_history_returns_broker_session_expired(self, monkeypatch):
        import services.history_service as history_service

        monkeypatch.setattr(
            history_service, "get_auth_token_broker", lambda *a, **k: (None, None, None)
        )
        monkeypatch.setattr(history_service, "is_broker_session_stale", lambda api_key: True)

        success, response, status = history_service.get_history(
            "SBIN", "NSE", "1d", "2026-08-01", "2026-08-20", api_key=TEST_API_KEY
        )

        assert success is False
        assert status == 401
        assert response["code"] == "BROKER_SESSION_EXPIRED"

    def test_depth_returns_broker_session_expired(self, monkeypatch):
        """Depth checked the tuple length, not the token.

        include_feed_token=True always yields a 3-tuple, so len(auth_info) == 3
        was true even for (None, None, None): broker_name became None,
        get_depth_with_auth reached import_broker_module(None), and the caller
        got 404 "Broker-specific module not found". The bug predates the guard
        but only fired on a bad key until the guard started returning empties
        every morning.
        """
        import services.depth_service as depth_service

        monkeypatch.setattr(
            depth_service, "get_auth_token_broker", lambda *a, **k: (None, None, None)
        )
        monkeypatch.setattr(depth_service, "is_broker_session_stale", lambda api_key: True)

        success, response, status = depth_service.get_depth("SBIN", "NSE", api_key=TEST_API_KEY)

        assert success is False
        assert status == 401
        assert response["code"] == "BROKER_SESSION_EXPIRED"

    def test_depth_invalid_api_key_returns_403_not_404(self, monkeypatch):
        """The length check made the 403 branch unreachable; a bad key answered
        404 from the broker-module import instead."""
        import services.depth_service as depth_service

        monkeypatch.setattr(
            depth_service, "get_auth_token_broker", lambda *a, **k: (None, None, None)
        )
        monkeypatch.setattr(depth_service, "is_broker_session_stale", lambda api_key: False)

        success, response, status = depth_service.get_depth(
            "SBIN", "NSE", api_key="not-a-real-key"
        )

        assert success is False
        assert status == 403, "a bad key must not surface as a missing broker module"
        assert "code" not in response

    def test_invalid_api_key_still_returns_403(self, monkeypatch):
        """Only the stale-session case changes; a genuinely bad key keeps its
        existing 403 so callers are not told to reconnect a broker that is fine."""
        import services.quotes_service as quotes_service

        monkeypatch.setattr(
            quotes_service, "get_auth_token_broker", lambda *a, **k: (None, None, None)
        )
        monkeypatch.setattr(quotes_service, "is_broker_session_stale", lambda api_key: False)

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
        assert STORED_TOKEN not in logged
        assert TEST_API_KEY not in logged
        assert TEST_API_KEY[:8] not in logged, "not even a prefix of the key"
