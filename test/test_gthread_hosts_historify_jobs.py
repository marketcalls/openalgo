"""Historify download jobs: cancel must not deadlock, and a retry runs once.

hosts-11. ``cancel_job`` held ``_job_state_lock`` and called ``_cleanup_job``,
which takes the same lock again. The lock is not reentrant, so the cancel
blocked forever holding it, and every later user of the lock queued behind it:
the download workers, pause, resume, retry and every new job, scheduled ones
included. That is a defect on every runtime; under gthread each of those
callers also pins a web server thread for good.

hosts-12. ``retry_failed_items`` checked the job's stored status with no lock
held and then started a processor. Two retries arriving together both passed
the check and both started one, so every symbol was fetched twice against the
broker's rate limit. The claim is now taken in the hold that checks it.

The first test asserts the deadlock itself: on the old code the cancelling
thread is still alive after the join and the lock is still held.
"""

import threading

import pytest

import database.historify_db as historify_db
from services import historify_service as hs


@pytest.fixture(autouse=True)
def clean_job_state():
    """Leave the module's job registries as they were found."""
    running = dict(hs._running_jobs)
    paused = dict(hs._paused_jobs)
    yield
    hs._running_jobs.clear()
    hs._running_jobs.update(running)
    hs._paused_jobs.clear()
    hs._paused_jobs.update(paused)


def test_cancel_returns_and_leaves_the_lock_free(monkeypatch):
    """Cancelling a running job answers, and the state lock is free afterwards."""
    statuses = []
    monkeypatch.setattr(historify_db, "get_download_job", lambda job_id: {"status": "running"})
    monkeypatch.setattr(
        historify_db, "update_job_status", lambda job_id, status, *a, **k: statuses.append(status)
    )
    monkeypatch.setattr(hs, "_emit_job_cancelled", lambda job_id: None)

    event = threading.Event()
    event.set()
    hs._running_jobs["J1"] = True
    hs._paused_jobs["J1"] = event

    result = {}

    def cancel():
        result["value"] = hs.cancel_job("J1")

    worker = threading.Thread(target=cancel, daemon=True)
    worker.start()
    worker.join(2)

    assert not worker.is_alive(), "cancel_job deadlocked on its own state lock"
    assert result["value"][0] is True
    assert result["value"][2] == 200
    assert statuses == ["cancelled"]
    assert "J1" not in hs._running_jobs
    assert "J1" not in hs._paused_jobs
    assert not hs._job_state_lock.locked(), "the state lock was left held"


def test_a_new_job_can_start_after_a_cancel(monkeypatch):
    """The lock the cancel used to strand is the one every new job needs."""
    monkeypatch.setattr(historify_db, "get_download_job", lambda job_id: {"status": "paused"})
    monkeypatch.setattr(historify_db, "update_job_status", lambda *a, **k: None)
    monkeypatch.setattr(historify_db, "create_download_job", lambda **k: (True, "ok"))
    monkeypatch.setattr(hs, "_emit_job_cancelled", lambda job_id: None)
    submitted = []
    monkeypatch.setattr(hs._job_executor, "submit", lambda *a, **k: submitted.append(a))

    paused = threading.Event()  # cleared: the job is paused
    hs._running_jobs["J2"] = True
    hs._paused_jobs["J2"] = paused

    ok, _, code = hs.cancel_job("J2")
    assert ok and code == 200
    # Resumed so a processor parked on it can leave through its cancel check.
    assert paused.is_set()

    started = {}

    def create():
        started["value"] = hs.create_and_start_job(
            "custom", [{"symbol": "SBIN", "exchange": "NSE"}], "D", "2026-01-01", "2026-01-02", "k"
        )

    worker = threading.Thread(target=create, daemon=True)
    worker.start()
    worker.join(2)

    assert not worker.is_alive(), "a new job could not take the state lock"
    assert started["value"][0] is True
    assert len(submitted) == 1


def test_retry_is_single_flight(monkeypatch):
    """Four retries of one failed job together start exactly one processor."""
    monkeypatch.setattr(historify_db, "get_download_job", lambda job_id: {"status": "failed"})
    monkeypatch.setattr(
        historify_db, "get_job_items", lambda job_id, status=None: [{"id": 1}, {"id": 2}]
    )
    monkeypatch.setattr(historify_db, "update_job_item_status", lambda *a, **k: None)
    monkeypatch.setattr(historify_db, "update_job_status", lambda *a, **k: None)

    submitted = []
    submit_lock = threading.Lock()

    def fake_submit(fn, *args):
        with submit_lock:
            submitted.append(args)

    monkeypatch.setattr(hs._job_executor, "submit", fake_submit)

    barrier = threading.Barrier(4)
    results = []
    results_lock = threading.Lock()

    def retry():
        barrier.wait()
        outcome = hs.retry_failed_items("J3", "key")
        with results_lock:
            results.append(outcome)

    workers = [threading.Thread(target=retry, daemon=True) for _ in range(4)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(5)

    assert len(results) == 4
    codes = sorted(code for _, _, code in results)
    assert codes == [200, 409, 409, 409], codes
    assert len(submitted) == 1
    refused = [body for ok, body, code in results if code == 409]
    assert all(body["message"] == hs.RETRY_BUSY_MESSAGE for body in refused)


def test_a_retry_that_cannot_start_releases_its_claim(monkeypatch):
    """A retry that fails after claiming must not leave the job unretryable."""
    monkeypatch.setattr(historify_db, "get_download_job", lambda job_id: {"status": "failed"})
    monkeypatch.setattr(historify_db, "get_job_items", lambda job_id, status=None: [{"id": 1}])

    def broken(*a, **k):
        raise RuntimeError("disk full")

    monkeypatch.setattr(historify_db, "update_job_item_status", broken)

    ok, _, code = hs.retry_failed_items("J4", "key")
    assert not ok and code == 500
    assert "J4" not in hs._running_jobs
    assert "J4" not in hs._paused_jobs
