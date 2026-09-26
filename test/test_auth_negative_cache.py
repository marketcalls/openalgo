"""Regression tests for the negative entry in ``auth_cache`` (issue #2086).

``get_auth_token_broker`` caches ``(None, None[, None])`` for a user whose
session is revoked so that the background services which keep asking for a
token do not query the database and warn on every tick. The entry did not
survive a second lookup. The cache-hit path re-checks ``is_revoked`` and, on
seeing it set, popped the entry and warned; the next caller took the miss path,
cached the negative again and warned again; the one after that landed back on
the hit path and popped it again. For as long as the session stayed revoked
the log alternated::

    Cached auth token was revoked for user_id '<u>'.
    No valid auth token or broker found for user_id '<u>'. Cached negative result.

once per caller per tick, which a Fyers user saw as a 403 repeating every ~3 s.

These tests drive ``get_auth_token_broker`` against a real SQLite ``Auth`` row
and count the warnings, so they need no broker session.
"""

import atexit
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Env must be set before importing auth_db (engine + PEPPER bind at import time).
TEST_DB = Path(__file__).resolve().parents[1] / "tmp" / "test_auth_negative_cache.db"
TEST_DB.parent.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("DATABASE_URL", f"sqlite:///{TEST_DB.as_posix()}")
os.environ.setdefault("API_KEY_PEPPER", "a" * 64)
atexit.register(lambda: TEST_DB.unlink(missing_ok=True))

import database.auth_db as auth_db  # noqa: E402

USER = "revoked-user"
API_KEY = "any-api-key"
POLLS = 6


@pytest.fixture()
def fresh_db(monkeypatch):
    auth_db.init_db()
    auth_db.Auth.query.delete()
    auth_db.db_session.commit()
    auth_db.auth_cache.clear()
    auth_db.feed_token_cache.clear()
    auth_db.broker_cache.clear()
    monkeypatch.setattr(auth_db, "verify_api_key", lambda _key: USER)
    yield
    auth_db.Auth.query.delete()
    auth_db.db_session.commit()
    auth_db.auth_cache.clear()
    auth_db.feed_token_cache.clear()


@pytest.fixture()
def warnings(monkeypatch):
    """Every warning ``get_auth_token_broker`` logs, in order."""
    seen = []
    monkeypatch.setattr(auth_db.logger, "warning", lambda msg, *a, **k: seen.append(str(msg)))
    return seen


def negative(include_feed_token):
    return (None, None, None) if include_feed_token else (None, None)


# ---------------------------------------------------------------------------


@pytest.mark.parametrize("include_feed_token", [False, True])
def test_a_revoked_session_polled_repeatedly_warns_once(fresh_db, warnings, include_feed_token):
    # Revoking through upsert_auth clears the cache, exactly as a logout or a
    # broker-side rotation does. Every poll after that used to warn.
    auth_db.upsert_auth(USER, "tok-1", "fyers")
    auth_db.upsert_auth(USER, "tok-1", "fyers", revoke=True)

    results = [auth_db.get_auth_token_broker(API_KEY, include_feed_token) for _ in range(POLLS)]

    assert results == [negative(include_feed_token)] * POLLS
    assert len(warnings) == 1, warnings
    assert "Cached negative result" in warnings[0]


def test_the_negative_entry_survives_the_revocation_re_check(fresh_db, warnings):
    # The cache must still hold the negative after the hit path has looked at
    # it. Popping it is what turned one revocation into a storm.
    auth_db.upsert_auth(USER, "tok-1", "fyers")
    auth_db.upsert_auth(USER, "tok-1", "fyers", revoke=True)

    auth_db.get_auth_token_broker(API_KEY)  # miss: caches the negative
    auth_db.get_auth_token_broker(API_KEY)  # hit: re-checks is_revoked

    assert list(auth_db.auth_cache.values()) == [(None, None)]


@pytest.mark.parametrize("include_feed_token", [False, True])
def test_a_live_token_revoked_underneath_the_cache_is_reported_once(
    fresh_db, warnings, include_feed_token
):
    # The row is flipped directly so the positive entry stays cached, which is
    # the case the hit path's revocation check exists for. The first poll must
    # still refuse and say why; the ones after it must not say it again.
    auth_db.upsert_auth(USER, "tok-1", "fyers")
    assert auth_db.get_auth_token_broker(API_KEY, include_feed_token)[0] == "tok-1"

    auth_db.Auth.query.filter_by(name=USER).first().is_revoked = True
    auth_db.db_session.commit()

    results = [auth_db.get_auth_token_broker(API_KEY, include_feed_token) for _ in range(POLLS)]

    assert results == [negative(include_feed_token)] * POLLS
    assert len(warnings) == 1, warnings
    assert "was revoked" in warnings[0]


def test_a_fresh_login_after_the_storm_is_served_the_new_token(fresh_db, warnings):
    # The negative entry must not outlive the re-login it was waiting for.
    auth_db.upsert_auth(USER, "tok-1", "fyers")
    auth_db.upsert_auth(USER, "tok-1", "fyers", revoke=True)
    for _ in range(POLLS):
        auth_db.get_auth_token_broker(API_KEY, include_feed_token=True)

    auth_db.upsert_auth(USER, "tok-2", "fyers", feed_token="feed-2")

    assert auth_db.get_auth_token_broker(API_KEY, include_feed_token=True) == (
        "tok-2",
        "feed-2",
        "fyers",
    )
    assert auth_db.get_auth_token_broker(API_KEY) == ("tok-2", "fyers")


def test_a_valid_cached_token_is_still_served_from_the_cache(fresh_db, warnings):
    # The fix touches only the revoked branch of the hit path.
    auth_db.upsert_auth(USER, "tok-1", "zerodha")

    assert auth_db.get_auth_token_broker(API_KEY) == ("tok-1", "zerodha")
    assert auth_db.get_auth_token_broker(API_KEY) == ("tok-1", "zerodha")
    assert warnings == []
