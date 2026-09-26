"""The abuse counters count every hit, and a new ban is not cached away.

The 404 and invalid-API-key trackers read a counter, add one and write it
back. Under the gthread worker a scanner's parallel requests each read the
same count, so increments were lost and two first hits each inserted a row;
auto-bans then arrived late. The ban cache had the stale-fill shape: a check
that read "not banned" just before a ban committed stored that verdict after
the ban invalidated it, and the banned address kept being served for a minute.
"""

from __future__ import annotations

import threading
import uuid

import pytest

import database.settings_db as settings_db
import database.traffic_db as traffic_db

THREADS = 20


@pytest.fixture
def ip():
    settings_db.init_db()
    traffic_db.init_logs_db()
    address = f"10.{uuid.uuid4().int % 250}.{uuid.uuid4().int % 250}.{uuid.uuid4().int % 250}"
    yield address
    session = traffic_db.logs_session
    try:
        traffic_db.Error404Tracker.query.filter_by(ip_address=address).delete()
        traffic_db.InvalidAPIKeyTracker.query.filter_by(ip_address=address).delete()
        traffic_db.IPBan.query.filter_by(ip_address=address).delete()
        session.commit()
    finally:
        session.remove()
        traffic_db._ip_ban_cache.invalidate()


def _hammer(target):
    barrier = threading.Barrier(THREADS)
    errors = []

    def runner(index):
        try:
            barrier.wait()
            target(index)
        except BaseException as exc:  # noqa: BLE001 - reported below
            errors.append(exc)
        finally:
            traffic_db.logs_session.remove()
            settings_db.db_session.remove()

    threads = [threading.Thread(target=runner, args=(i,)) for i in range(THREADS)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(60)
        assert not thread.is_alive()
    assert errors == [], errors[:3]


def test_parallel_404s_from_one_address_are_each_counted(ip):
    _hammer(lambda index: traffic_db.Error404Tracker.track_404(ip, f"/probe/{index}"))

    rows = traffic_db.Error404Tracker.query.filter_by(ip_address=ip).all()
    traffic_db.logs_session.remove()
    # Before the fix: lost increments, and sometimes two rows from two first hits.
    assert len(rows) == 1
    assert rows[0].error_count == THREADS


def test_parallel_invalid_keys_from_one_address_are_each_counted(ip):
    _hammer(lambda index: traffic_db.InvalidAPIKeyTracker.track_invalid_api_key(ip, f"h{index}"))

    rows = traffic_db.InvalidAPIKeyTracker.query.filter_by(ip_address=ip).all()
    traffic_db.logs_session.remove()
    assert len(rows) == 1
    assert rows[0].attempt_count == THREADS


def test_a_single_404_is_tracked_as_before(ip):
    assert traffic_db.Error404Tracker.track_404(ip, "/one") is True
    row = traffic_db.Error404Tracker.query.filter_by(ip_address=ip).first()
    assert row.error_count == 1
    traffic_db.logs_session.remove()


class StagedBanQuery:
    """The ban check's query answers "no ban" and waits; other threads are real."""

    def __init__(self):
        self.reader = None
        self.read_done = threading.Event()
        self.release = threading.Event()

    def filter_by(self, **kwargs):
        if threading.get_ident() == self.reader:
            return self
        return traffic_db.logs_session.query(traffic_db.IPBan).filter_by(**kwargs)

    def filter(self, *args):
        return traffic_db.logs_session.query(traffic_db.IPBan).filter(*args)

    def first(self):
        self.read_done.set()
        assert self.release.wait(10), "the test never released the reader"
        return None


def test_a_ban_committed_during_a_ban_check_is_not_cached_away(ip, monkeypatch):
    staged = StagedBanQuery()
    monkeypatch.setattr(traffic_db.IPBan, "query", staged)
    result = {}

    def check():
        staged.reader = threading.get_ident()
        try:
            result["banned"] = traffic_db.IPBan.is_ip_banned(ip)
        finally:
            traffic_db.logs_session.remove()

    thread = threading.Thread(target=check)
    thread.start()
    assert staged.read_done.wait(10)

    assert traffic_db.IPBan.ban_ip(ip, "test ban", duration_hours=1) is True
    staged.release.set()
    thread.join(10)
    monkeypatch.undo()

    assert result["banned"] is False  # what the in-flight check saw
    # Before the fix "not banned" was stored after the ban's invalidation.
    assert traffic_db.IPBan.is_ip_banned(ip) is True
    traffic_db.logs_session.remove()
