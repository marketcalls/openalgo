"""The strategy module's caches: the banked session P&L and the webhook lookup.

The session total is read on every tick by the daily loss limit. A tick that
summed the runs just before a run finished used to store that total after the
finish invalidated it, so for up to a minute the limit was judged on a figure
that left the finished run out: a loss-limit breach, delayed.

The webhook lookup tested membership and then subscripted. An entry that went
in between (a clear on logout, a TTL lapse) raised a KeyError that the lookup
swallowed as "unknown token", and the TradingView alert, entry or exit, was
rejected for a strategy that exists.
"""

from __future__ import annotations

import sys
import threading
import time
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

import database.strategy_module_db as smdb
from utils.thread_safe_cache import LockedTTLCache


class FakeQuery:
    """Enough of a SQLAlchemy query for realized_pnl_since and the webhook lookup."""

    def __init__(self, session, model):
        self.session = session
        self.model = model
        self.kwargs = {}

    def filter(self, *_args):
        return self

    def filter_by(self, **kwargs):
        self.kwargs.update(kwargs)
        return self

    def all(self):
        return self.session.all_rows(self)

    def first(self):
        return self.session.first_row(self)


class FakeSession:
    def __init__(self):
        self.rows = [(100.0,)]
        self.reader = None
        self.read_done = threading.Event()
        self.release = threading.Event()
        self.strategy = SimpleNamespace(id=7, webhook_token_hash=None)

    def query(self, model):
        return FakeQuery(self, model)

    def all_rows(self, _query):
        rows = list(self.rows)
        if threading.get_ident() == self.reader:
            self.read_done.set()
            assert self.release.wait(10), "the test never released the reader"
        return rows

    def first_row(self, query):
        if "webhook_token_hash" in query.kwargs:
            if query.kwargs["webhook_token_hash"] == self.strategy.webhook_token_hash:
                return self.strategy
            return None
        if query.kwargs.get("id") == self.strategy.id:
            return self.strategy
        return None

    def remove(self):
        pass


@pytest.fixture
def fake_session(monkeypatch):
    session = FakeSession()
    monkeypatch.setattr(smdb, "db_session", session)
    smdb._forget_session_pnl(None)
    smdb.clear_strategy_module_cache()
    yield session
    smdb._forget_session_pnl(None)
    smdb.clear_strategy_module_cache()


SINCE = datetime(2026, 9, 23, 3, 45, tzinfo=UTC)


def test_a_run_finishing_during_a_tick_read_is_not_hidden_from_the_loss_limit(fake_session):
    result = {}

    def tick():
        fake_session.reader = threading.get_ident()
        result["total"] = smdb.realized_pnl_since(7, SINCE)

    thread = threading.Thread(target=tick)
    thread.start()
    assert fake_session.read_done.wait(10)

    # finish_run commits a -500 run and invalidates, while the tick is in flight.
    fake_session.rows.append((-500.0,))
    smdb._forget_session_pnl(7)
    fake_session.release.set()
    thread.join(10)

    assert result["total"] == 100.0  # what the tick saw
    # Before the fix the tick stored 100 after the invalidation, and the next
    # minute of ticks judged the daily limit without the -500 run.
    assert smdb.realized_pnl_since(7, SINCE) == -400.0


def test_the_session_total_is_still_cached_when_nothing_races(fake_session):
    assert smdb.realized_pnl_since(7, SINCE) == 100.0
    fake_session.rows.append((50.0,))
    # No invalidation: the cached figure stands, as before.
    assert smdb.realized_pnl_since(7, SINCE) == 100.0
    smdb._forget_session_pnl(7)
    assert smdb.realized_pnl_since(7, SINCE) == 150.0


def test_forgetting_one_strategy_keeps_the_others(fake_session):
    smdb._session_pnl_cache[(8, SINCE, None)] = 42.0
    assert smdb.realized_pnl_since(7, SINCE) == 100.0
    smdb._forget_session_pnl(7)
    assert (7, SINCE, None) not in smdb._session_pnl_cache
    assert smdb._session_pnl_cache.get((8, SINCE, None)) == 42.0


class VanishingEntryCache(LockedTTLCache):
    """Reports a key as present, then loses it before the subscript.

    Exactly what a concurrent clear or a TTL lapse between the two steps
    looks like to the membership-then-subscript shape.
    """

    def __contains__(self, key):
        return True

    def __getitem__(self, key):
        raise KeyError(key)

    def get(self, key, default=None):
        # One atomic read sees a consistent state: the entry has gone.
        return default


def test_a_valid_webhook_token_resolves_when_its_entry_vanishes(fake_session, monkeypatch):
    token = "oaws_valid"
    fake_session.strategy.webhook_token_hash = smdb.hash_webhook_token(token)
    monkeypatch.setattr(smdb, "_webhook_token_cache", VanishingEntryCache(maxsize=16, ttl=300))

    # Before the fix: 'in' said yes, the subscript raised, and the lookup
    # answered None, rejecting the alert as an unknown token.
    assert smdb.get_strategy_by_webhook_token(token) is fake_session.strategy


def test_webhook_lookups_racing_a_clear_never_miss_a_valid_token(fake_session):
    token = "oaws_valid"
    fake_session.strategy.webhook_token_hash = smdb.hash_webhook_token(token)
    stop = threading.Event()
    misses = []
    errors = []

    def resolver():
        try:
            while not stop.is_set():
                if smdb.get_strategy_by_webhook_token(token) is None:
                    misses.append(1)
        except BaseException as exc:  # noqa: BLE001 - reported below
            errors.append(exc)

    def clearer():
        while not stop.is_set():
            smdb.clear_strategy_module_cache()

    old_interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-5)
    try:
        threads = [threading.Thread(target=resolver) for _ in range(8)]
        threads.append(threading.Thread(target=clearer))
        for thread in threads:
            thread.start()
        time.sleep(1.0)
        stop.set()
        for thread in threads:
            thread.join(30)
    finally:
        sys.setswitchinterval(old_interval)

    assert errors == []
    assert misses == []


def test_an_unknown_token_is_still_cached_as_unknown(fake_session):
    fake_session.strategy.webhook_token_hash = smdb.hash_webhook_token("oaws_valid")
    assert smdb.get_strategy_by_webhook_token("oaws_guess") is None
    digest = smdb.hash_webhook_token("oaws_guess")
    assert smdb._webhook_token_cache.get(digest, "absent") is None
