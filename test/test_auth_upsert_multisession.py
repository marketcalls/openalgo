"""Regression tests for multi-session / multi-device broker-token persistence.

Covers issue #1591: a second device logging in (session resume) re-persists the
SAME broker token via ``upsert_auth``. That must NOT tear down the shared broker
WebSocket feed (ZeroMQ cache-invalidation + connection-pool cleanup), otherwise
the already-connected first device loses its live stream (Shoonya) or the broker
session is dropped on single-session Noren brokers (Flattrade).

Only a genuine token change (real login, daily token rollover, logout/revoke)
should trigger the teardown — preserving the #1394/#765/#851 behaviour.
"""

import atexit
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Env must be set before importing auth_db (engine + PEPPER bind at import time).
TEST_DB = Path(__file__).resolve().parents[1] / "tmp" / "test_auth_upsert_multisession.db"
TEST_DB.parent.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("DATABASE_URL", f"sqlite:///{TEST_DB.as_posix()}")
os.environ.setdefault("API_KEY_PEPPER", "a" * 64)
atexit.register(lambda: TEST_DB.unlink(missing_ok=True))

import database.auth_db as auth_db  # noqa: E402


@pytest.fixture()
def fresh_db():
    auth_db.init_db()
    # Start each test from a clean auth table.
    auth_db.Auth.query.delete()
    auth_db.db_session.commit()
    auth_db.auth_cache.clear()
    auth_db.feed_token_cache.clear()
    auth_db.broker_cache.clear()
    yield
    auth_db.Auth.query.delete()
    auth_db.db_session.commit()


@pytest.fixture()
def spy_teardown(monkeypatch):
    """Record calls to the two feed-tearing-down side effects."""
    calls = {"publish": [], "cleanup": []}
    monkeypatch.setattr(
        "database.cache_invalidation.publish_all_cache_invalidation",
        lambda name: calls["publish"].append(name) or True,
    )
    monkeypatch.setattr(
        "websocket_proxy.broker_factory.cleanup_pools_for_user",
        lambda name, broker_name=None: calls["cleanup"].append((name, broker_name)) or 0,
    )
    return calls


def test_first_login_tears_down(fresh_db, spy_teardown):
    """Initial insert is a real session change — teardown must fire."""
    auth_db.upsert_auth("rajandran", "tok-1", "shoonya")
    assert spy_teardown["publish"] == ["rajandran"]
    assert spy_teardown["cleanup"] == [("rajandran", "shoonya")]


def test_same_token_resume_preserves_feed(fresh_db, spy_teardown):
    """Second device re-persisting the SAME token must NOT tear down the feed."""
    auth_db.upsert_auth("rajandran", "tok-1", "shoonya")
    spy_teardown["publish"].clear()
    spy_teardown["cleanup"].clear()

    # Multi-session resume — identical token.
    auth_db.upsert_auth("rajandran", "tok-1", "shoonya")

    assert spy_teardown["publish"] == []
    assert spy_teardown["cleanup"] == []


def test_changed_token_tears_down(fresh_db, spy_teardown):
    """A genuinely new token (re-login / daily rollover) must tear down."""
    auth_db.upsert_auth("rajandran", "tok-1", "flattrade")
    spy_teardown["publish"].clear()
    spy_teardown["cleanup"].clear()

    auth_db.upsert_auth("rajandran", "tok-2", "flattrade")

    assert spy_teardown["publish"] == ["rajandran"]
    assert spy_teardown["cleanup"] == [("rajandran", "flattrade")]


def test_changed_feed_token_tears_down(fresh_db, spy_teardown):
    """Same auth token but a new feed token still counts as a change."""
    auth_db.upsert_auth("rajandran", "tok-1", "angel", feed_token="feed-1")
    spy_teardown["publish"].clear()
    spy_teardown["cleanup"].clear()

    auth_db.upsert_auth("rajandran", "tok-1", "angel", feed_token="feed-2")

    assert spy_teardown["publish"] == ["rajandran"]
    assert spy_teardown["cleanup"] == [("rajandran", "angel")]


def test_revoke_always_tears_down(fresh_db, spy_teardown):
    """Logout/revoke must always tear down, even with an unchanged token."""
    auth_db.upsert_auth("rajandran", "tok-1", "shoonya")
    spy_teardown["publish"].clear()
    spy_teardown["cleanup"].clear()

    auth_db.upsert_auth("rajandran", "tok-1", "shoonya", revoke=True)

    assert spy_teardown["publish"] == ["rajandran"]
    assert spy_teardown["cleanup"] == [("rajandran", "shoonya")]
