"""Regression tests for the auth cache read race.

``auth_cache`` and ``feed_token_cache`` are TTLCaches with a maxsize. An entry
can disappear between a membership test and the subscript that follows it: the
TTL can lapse, an LRU eviction can drop it (two different key schemes share
``auth_cache`` - ``auth-{name}`` and ``{sha256}_{bool}``), or another code path
can delete it.

The old shape was::

    if cache_key in auth_cache:
        cached_result = auth_cache[cache_key]   # KeyError if it just went

and inside ``get_auth_token_broker`` the recovery path made it worse::

    except Exception as e:
        logger.exception(...)
        del auth_cache[cache_key]               # a SECOND KeyError, uncaught

so a harmless cache miss escaped the function and reached ``/quotes`` and
``/multiquotes``, where it was reported to the user as "Broker Session Expired"
on a session that was perfectly valid. Observed in ``log/errors.jsonl`` as
``Error checking revocation status: '<cache key>'`` - the "error" being logged
was the key itself.

These tests drive that race directly rather than waiting for a TTL.
"""

import atexit
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Env must be set before importing auth_db (engine + PEPPER bind at import time).
TEST_DB = Path(__file__).resolve().parents[1] / "tmp" / "test_auth_cache_race.db"
TEST_DB.parent.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("DATABASE_URL", f"sqlite:///{TEST_DB.as_posix()}")
os.environ.setdefault("API_KEY_PEPPER", "a" * 64)
atexit.register(lambda: TEST_DB.unlink(missing_ok=True))

import database.auth_db as auth_db  # noqa: E402

USER = "race-user"


class VanishingCache(dict):
    """A cache that claims to hold a key and then does not.

    This is the race in one object: ``__contains__`` answers True, and by the
    time anything reads the entry it has gone. A TTL lapse or an LRU eviction
    landing between those two operations looks exactly like this from the
    caller's side.
    """

    def __contains__(self, key):  # noqa: D105
        return True

    def __getitem__(self, key):  # noqa: D105
        raise KeyError(key)


@pytest.fixture()
def fresh_db():
    auth_db.init_db()
    auth_db.Auth.query.delete()
    auth_db.db_session.commit()
    auth_db.auth_cache.clear()
    auth_db.feed_token_cache.clear()
    auth_db.broker_cache.clear()
    yield
    auth_db.Auth.query.delete()
    auth_db.db_session.commit()
    auth_db.auth_cache.clear()
    auth_db.feed_token_cache.clear()


@pytest.fixture()
def vanishing_auth_cache(monkeypatch):
    monkeypatch.setattr(auth_db, "auth_cache", VanishingCache())


@pytest.fixture()
def vanishing_feed_cache(monkeypatch):
    monkeypatch.setattr(auth_db, "feed_token_cache", VanishingCache())


# ---------------------------------------------------------------------------


def test_get_auth_token_survives_the_entry_going_between_check_and_read(
    fresh_db, vanishing_auth_cache
):
    auth_db.upsert_auth(USER, "tok-1", "zerodha")

    # Must fall through to the database rather than raising.
    assert auth_db.get_auth_token(USER) == "tok-1"


def test_get_feed_token_survives_the_same_race(fresh_db, vanishing_feed_cache):
    auth_db.upsert_auth(USER, "tok-1", "zerodha", feed_token="feed-1")

    assert auth_db.get_feed_token(USER) == "feed-1"


def test_the_bypass_path_does_not_raise_when_there_is_nothing_to_clear(
    fresh_db, vanishing_auth_cache
):
    # bypass_cache clears the entry first. Deleting one that has already gone
    # was a KeyError on the path taken specifically to recover from a 403.
    auth_db.upsert_auth(USER, "tok-1", "zerodha")

    assert auth_db.get_auth_token(USER, bypass_cache=True) == "tok-1"


def test_a_revoked_token_still_answers_none_rather_than_raising(fresh_db, vanishing_auth_cache):
    auth_db.upsert_auth(USER, "tok-1", "zerodha")
    auth_db.upsert_auth(USER, "tok-1", "zerodha", revoke=True)

    assert auth_db.get_auth_token(USER) is None


def test_get_auth_token_broker_survives_the_race_that_reached_the_user(
    fresh_db, vanishing_auth_cache, monkeypatch
):
    # The one that surfaced as "Broker Session Expired". The cache claims a
    # hit, the entry is gone, and the caller must still get its token.
    auth_db.upsert_auth(USER, "tok-1", "zerodha")
    monkeypatch.setattr(auth_db, "verify_api_key", lambda _key: USER)

    token, broker = auth_db.get_auth_token_broker("any-api-key")

    assert token == "tok-1"
    assert broker == "zerodha"


class UndeletableCache(dict):
    """Answers a cache hit, then refuses to be deleted from.

    The second half of the original bug. The recovery path in
    ``get_auth_token_broker`` deleted an entry that had already gone, raising a
    KeyError nothing caught, so the code that existed to recover from a failure
    was itself the failure.
    """

    def get(self, key, default=None):  # noqa: D102
        return "cached-value"

    def __contains__(self, key):  # noqa: D105
        return True

    def __delitem__(self, key):  # noqa: D105
        raise KeyError(key)


def test_the_recovery_path_does_not_raise_a_second_error_of_its_own(fresh_db, monkeypatch):
    # Force the revocation check to fail so the except handler runs, against a
    # cache that will not tolerate a bare del. With pop(key, None) this is
    # fine; with del it raised a second, uncaught KeyError.
    auth_db.upsert_auth(USER, "tok-1", "zerodha")
    monkeypatch.setattr(auth_db, "auth_cache", UndeletableCache())
    monkeypatch.setattr(auth_db, "verify_api_key", lambda _key: USER)

    class Boom:
        @staticmethod
        def filter_by(**_kwargs):
            raise RuntimeError("revocation check failed")

    monkeypatch.setattr(auth_db.Auth, "query", Boom)

    # The assertion is simply that nothing escapes: this used to raise
    # KeyError out of the function and into /quotes.
    result = auth_db.get_auth_token_broker("any-api-key")

    assert isinstance(result, tuple)


def test_a_normal_cached_read_still_works(fresh_db):
    # The fix must not have turned every read into a database round trip.
    auth_db.upsert_auth(USER, "tok-1", "zerodha")

    assert auth_db.get_auth_token(USER) == "tok-1"
    assert auth_db.get_auth_token(USER) == "tok-1"
    assert f"auth-{USER}" in auth_db.auth_cache
