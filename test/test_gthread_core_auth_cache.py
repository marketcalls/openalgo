"""The routing-mode and broker-token caches cannot serve a value a writer replaced.

Under eventlet a cache read, its database query and its store never yielded, so
a writer could not land between them. Under the gthread worker it can: the
SQLite call releases the GIL, a toggle or a re-login commits and clears the
cache, and the reader then stores the value it read before the commit. The
analyzer flag decides whether an order goes to the broker or the sandbox, the
order mode whether it waits in the Action Center, and the auth cache which
broker token every order carries, so each stale store is an order sent the
wrong way until the TTL runs out.

Each interleaving is staged deterministically: the reader's query returns the
old value and then blocks on an Event while the writer commits, exactly the
window the race needs. Before the fix the reader's late store wins and the
next read is stale; after it, the store is refused and the next read is fresh.
"""

from __future__ import annotations

import sys
import threading
import time
import uuid
from types import SimpleNamespace

import pytest
from flask import Flask
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.exc import NoInspectionAvailable

import database.auth_db as auth_db
import database.settings_db as settings_db
from database.cache_restoration import restore_auth_cache

BROKER = "zerodha"


@pytest.fixture(autouse=True)
def quiet_teardown(monkeypatch):
    """Keep upsert_auth's feed teardown away from ZeroMQ, pools and adapters."""
    import database.cache_invalidation as cache_invalidation
    import services.order_update_service as order_update_service
    import websocket_proxy.broker_factory as broker_factory

    monkeypatch.setattr(cache_invalidation, "publish_all_cache_invalidation", lambda *a, **k: True)
    monkeypatch.setattr(broker_factory, "cleanup_pools_for_user", lambda *a, **k: None)
    monkeypatch.setattr(order_update_service, "start_order_update_adapter", lambda *a, **k: None)
    monkeypatch.setattr(order_update_service, "stop_order_update_adapter", lambda *a, **k: None)


@pytest.fixture
def user():
    auth_db.init_db()
    settings_db.init_db()
    name = f"gt-core-{uuid.uuid4().hex[:10]}"
    yield name
    try:
        auth_db.Auth.query.filter_by(name=name).delete()
        auth_db.ApiKeys.query.filter_by(user_id=name).delete()
        auth_db.db_session.commit()
    finally:
        auth_db.db_session.remove()
        for cache in (
            auth_db.auth_cache,
            auth_db.feed_token_cache,
            auth_db.broker_cache,
            auth_db.verified_api_key_cache,
            auth_db.invalid_api_key_cache,
            auth_db.order_mode_cache,
        ):
            cache.clear()


class StagedQuery:
    """Stands in for ``Model.query``: the reader's query answers old, then waits.

    Every other thread gets the real query, so the writer commits for real.
    """

    def __init__(self, real_query, stale):
        self._real_query = real_query
        self._stale = stale
        self.reader = None
        self.read_done = threading.Event()
        self.release = threading.Event()

    def _is_reader(self):
        return threading.get_ident() == self.reader

    def filter_by(self, **kwargs):
        if self._is_reader():
            return self
        return self._real_query().filter_by(**kwargs)

    def filter(self, *args):
        if self._is_reader():
            return self
        return self._real_query().filter(*args)

    def first(self):
        if self._is_reader():
            value = self._stale()
            self.read_done.set()
            assert self.release.wait(10), "the test never released the reader"
            return value
        return self._real_query().first()

    def all(self):
        if self._is_reader():
            value = self._stale()
            self.read_done.set()
            assert self.release.wait(10), "the test never released the reader"
            return value
        return self._real_query().all()


def _run_reader(staged, target, session):
    result = {}

    def reader():
        staged.reader = threading.get_ident()
        try:
            result["value"] = target()
        finally:
            session.remove()

    thread = threading.Thread(target=reader)
    thread.start()
    assert staged.read_done.wait(10), "the reader never reached its query"
    return thread, result


# --- core-01: the analyzer (sandbox) flag -----------------------------------


def test_a_toggle_during_a_cache_fill_is_not_undone(monkeypatch):
    settings_db.init_db()
    settings_db.set_analyze_mode(False)
    settings_db.clear_settings_cache()

    staged = StagedQuery(
        lambda: settings_db.db_session.query(settings_db.Settings),
        stale=lambda: SimpleNamespace(analyze_mode=False),
    )
    monkeypatch.setattr(settings_db.Settings, "query", staged)
    try:
        thread, result = _run_reader(staged, settings_db.get_analyze_mode, settings_db.db_session)

        # The operator switches to analyzer mode while the read is in flight.
        settings_db.set_analyze_mode(True)
        staged.release.set()
        thread.join(10)

        # The in-flight read answers what it saw; nothing after it may.
        assert result["value"] is False
        assert settings_db.get_analyze_mode() is True
    finally:
        monkeypatch.undo()
        settings_db.set_analyze_mode(False)
        settings_db.clear_settings_cache()
        settings_db.db_session.remove()


def test_the_analyzer_flag_is_still_cached_when_nothing_races():
    settings_db.init_db()
    settings_db.set_analyze_mode(False)
    settings_db.clear_settings_cache()
    try:
        assert settings_db.get_analyze_mode() is False
        assert settings_db._settings_cache.get("analyze_mode") is False
        settings_db.set_analyze_mode(True)
        assert settings_db.get_analyze_mode() is True
    finally:
        settings_db.set_analyze_mode(False)
        settings_db.clear_settings_cache()
        settings_db.db_session.remove()


# --- core-01: the order approval mode ---------------------------------------


def test_a_switch_to_semi_auto_during_a_cache_fill_is_not_undone(user, monkeypatch):
    auth_db.upsert_api_key(user, f"key-{user}")
    auth_db.order_mode_cache.clear()

    staged = StagedQuery(
        lambda: auth_db.db_session.query(auth_db.ApiKeys),
        stale=lambda: SimpleNamespace(order_mode="auto"),
    )
    monkeypatch.setattr(auth_db.ApiKeys, "query", staged)
    thread, result = _run_reader(staged, lambda: auth_db.get_order_mode(user), auth_db.db_session)

    assert auth_db.update_order_mode(user, "semi_auto") is True
    staged.release.set()
    thread.join(10)
    monkeypatch.undo()

    assert result["value"] == "auto"
    # Before the fix 'auto' was stored after the clear, and orders skipped the
    # Action Center for the next 60 seconds.
    assert auth_db.get_order_mode(user) == "semi_auto"


# --- core-04: the broker token ----------------------------------------------


def test_a_relogin_during_a_token_fill_is_not_undone(user, monkeypatch):
    auth_db.upsert_auth(user, "tok-1", BROKER)
    auth_db.auth_cache.clear()

    real_dbquery = auth_db.get_auth_token_dbquery
    reader_ident = []
    read_done = threading.Event()
    release = threading.Event()

    def staged_dbquery(name):
        row = real_dbquery(name)
        if threading.get_ident() not in reader_ident:
            return row
        # A transient copy of the row as it stood, so the re-login's commit
        # cannot refresh it: this is the value the reader read before it.
        stale = auth_db.Auth(
            name=row.name,
            auth=row.auth,
            feed_token=row.feed_token,
            broker=row.broker,
            user_id=row.user_id,
            is_revoked=False,
        )
        read_done.set()
        assert release.wait(10), "the test never released the reader"
        return stale

    monkeypatch.setattr(auth_db, "get_auth_token_dbquery", staged_dbquery)
    result = {}

    def reader():
        reader_ident.append(threading.get_ident())
        try:
            result["token"] = auth_db.get_auth_token(user)
        finally:
            auth_db.db_session.remove()

    thread = threading.Thread(target=reader)
    thread.start()
    assert read_done.wait(10), "the reader never reached its query"

    auth_db.upsert_auth(user, "tok-2", BROKER)
    release.set()
    thread.join(10)

    assert result["token"] == "tok-1"
    # Before the fix the superseded token was cached and every order after the
    # re-login went out with it, until the next clear or the session-long TTL.
    assert auth_db.get_auth_token(user) == "tok-2"


def test_restoration_racing_a_login_keeps_the_new_token(user, monkeypatch):
    auth_db.upsert_auth(user, "tok-1", BROKER)
    auth_db.auth_cache.clear()

    def stale_rows():
        rows = auth_db.db_session.query(auth_db.Auth).filter_by(is_revoked=False).all()
        return [
            SimpleNamespace(
                name=r.name,
                auth=r.auth,
                feed_token=r.feed_token,
                broker=r.broker,
                user_id=r.user_id,
                is_revoked=r.is_revoked,
            )
            for r in rows
        ]

    staged = StagedQuery(lambda: auth_db.db_session.query(auth_db.Auth), stale=stale_rows)
    monkeypatch.setattr(auth_db.Auth, "query", staged)
    thread, result = _run_reader(staged, restore_auth_cache, auth_db.db_session)

    # A login commits while the boot-time restoration's SELECT is in flight.
    monkeypatch.undo()
    _quiet_again(monkeypatch)
    auth_db.upsert_auth(user, "tok-2", BROKER)
    staged.release.set()
    thread.join(10)

    assert result["value"]["success"] is True
    assert auth_db.get_auth_token(user) == "tok-2"


def _quiet_again(monkeypatch):
    import database.cache_invalidation as cache_invalidation
    import services.order_update_service as order_update_service
    import websocket_proxy.broker_factory as broker_factory

    monkeypatch.setattr(cache_invalidation, "publish_all_cache_invalidation", lambda *a, **k: True)
    monkeypatch.setattr(broker_factory, "cleanup_pools_for_user", lambda *a, **k: None)
    monkeypatch.setattr(order_update_service, "start_order_update_adapter", lambda *a, **k: None)
    monkeypatch.setattr(order_update_service, "stop_order_update_adapter", lambda *a, **k: None)


def test_the_token_caches_hold_frozen_records_not_orm_rows(user):
    auth_db.upsert_auth(user, "tok-1", BROKER, feed_token="feed-1")
    assert auth_db.get_auth_token(user) == "tok-1"
    assert auth_db.get_feed_token(user) == "feed-1"
    restore_auth_cache()

    for cache in (auth_db.auth_cache, auth_db.feed_token_cache):
        for value in cache.values():
            with pytest.raises(NoInspectionAvailable):
                sa_inspect(value)
            if not isinstance(value, tuple):
                assert isinstance(value, auth_db.AuthRecord)
                with pytest.raises(AttributeError):
                    value.auth = "changed"  # frozen


def test_the_revoke_path_and_the_multisession_gate_are_unchanged(user, monkeypatch):
    teardowns = []
    import websocket_proxy.broker_factory as broker_factory

    monkeypatch.setattr(
        broker_factory, "cleanup_pools_for_user", lambda *a, **k: teardowns.append(a)
    )
    auth_db.upsert_auth(user, "tok-1", BROKER)
    assert len(teardowns) == 1

    # A second device re-persisting the same token keeps the shared feed up
    # (#1591) and still leaves the caches readable.
    assert auth_db.get_auth_token(user) == "tok-1"
    auth_db.upsert_auth(user, "tok-1", BROKER)
    assert len(teardowns) == 1
    assert auth_db.get_auth_token(user) == "tok-1"

    auth_db.upsert_auth(user, "tok-1", BROKER, revoke=True)
    assert len(teardowns) == 2
    assert auth_db.get_auth_token(user) is None


def test_concurrent_token_reads_and_writers_raise_nothing(user, monkeypatch):
    auth_db.upsert_auth(user, "tok-0", BROKER, feed_token="feed-0")
    auth_db.upsert_api_key(user, f"key-{user}")
    monkeypatch.setattr(auth_db, "verify_api_key", lambda _key: user)

    stop = threading.Event()
    errors = []
    tokens = [f"tok-{n}" for n in range(1, 4)]

    def reader():
        try:
            while not stop.is_set():
                auth_db.get_auth_token(user)
                auth_db.get_feed_token(user)
                auth_db.get_auth_token_broker("any-key")
                auth_db.get_auth_token_broker("any-key", include_feed_token=True)
                auth_db.get_order_mode(user)
        except BaseException as exc:  # noqa: BLE001 - reported below
            errors.append(exc)
        finally:
            auth_db.db_session.remove()

    def writer():
        try:
            n = 0
            while not stop.is_set():
                auth_db.upsert_auth(user, tokens[n % 3], BROKER, feed_token="feed-x")
                auth_db.invalidate_user_cache(user)
                auth_db.invalidate_user_auth_cache(user)
                n += 1
        except BaseException as exc:  # noqa: BLE001 - reported below
            errors.append(exc)
        finally:
            auth_db.db_session.remove()

    old_interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-5)
    try:
        threads = [threading.Thread(target=reader) for _ in range(6)]
        threads.append(threading.Thread(target=writer))
        for thread in threads:
            thread.start()
        time.sleep(1.5)
        stop.set()
        for thread in threads:
            thread.join(30)
            assert not thread.is_alive()
    finally:
        sys.setswitchinterval(old_interval)

    assert errors == [], errors[:3]
    # Settled: the next read agrees with the database.
    final = auth_db.decrypt_token(auth_db.Auth.query.filter_by(name=user).first().auth)
    assert auth_db.get_auth_token(user) == final


# --- rest-07: logout cannot lose the revocation to a vanished entry ---------


class VanishingDelete(dict):
    """Claims to hold every key, then fails to delete it: the entry just went."""

    def __contains__(self, key):  # noqa: D105
        return True

    def __delitem__(self, key):  # noqa: D105
        raise KeyError(key)


def test_logout_revokes_even_when_the_cached_entry_vanishes(monkeypatch):
    import blueprints.auth as auth_bp_module

    revocations = []
    monkeypatch.setattr(
        auth_bp_module,
        "upsert_auth",
        lambda name, *args, **kwargs: revocations.append((name, kwargs.get("revoke"))),
    )
    monkeypatch.setattr(auth_db, "clear_user_sessions", lambda *args, **kwargs: None)
    monkeypatch.setattr(auth_bp_module.socketio, "emit", lambda *args, **kwargs: None)
    for module in (auth_db, auth_bp_module):
        monkeypatch.setattr(module, "auth_cache", VanishingDelete(), raising=False)
        monkeypatch.setattr(module, "feed_token_cache", VanishingDelete(), raising=False)

    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.register_blueprint(auth_bp_module.auth_bp)
    with app.test_client() as client:
        with client.session_transaction() as session:
            session["user"] = "rajandran"
            session["logged_in"] = True
            session["broker"] = "dhan"

        response = client.post("/auth/logout", headers={"Sec-Fetch-Site": "same-origin"})

    # Before the fix the KeyError escaped after the cookie was cleared and
    # before the broker token was revoked: a 500 and a live token.
    assert response.status_code == 200
    assert revocations == [("rajandran", True)]


def test_invalidate_user_auth_cache_reports_and_never_raises(user):
    auth_db.upsert_auth(user, "tok-1", BROKER, feed_token="feed-1")
    assert auth_db.get_auth_token(user) == "tok-1"
    assert auth_db.get_feed_token(user) == "feed-1"

    assert auth_db.invalidate_user_auth_cache(user) == ["auth_cache", "feed_token_cache"]
    assert auth_db.invalidate_user_auth_cache(user) == []
    assert auth_db.auth_cache.get(f"auth-{user}") is None
