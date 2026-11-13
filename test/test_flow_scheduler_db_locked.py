"""A locked database must not kill the Flow scheduler thread (issue #2355).

APScheduler 3.x writes each job's next run time back to the job store from its
scheduler loop (``BaseScheduler._process_jobs``) with no exception handling
around ``update_job()`` or ``remove_job()``. One ``sqlite3.OperationalError:
database is locked`` from openalgo.db therefore ended the ``APScheduler``
thread: the process kept running, jobs could still be added, and no scheduled
flow fired again until the container was restarted.

These tests inject the lock at the ``SQLAlchemyJobStore`` write that
production hits, run a real ``BackgroundScheduler`` on a temporary SQLite file,
and assert on what a trader sees: the thread is alive, the job keeps firing,
and a job that already ran is not run a second time because its write was
deferred.
"""

import os
import sqlite3
import sys
import threading
import time
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from apscheduler.events import EVENT_JOB_EXECUTED
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy.exc import OperationalError

from database.apscheduler_jobstore_db import FLOW_JOBSTORE_TABLE, LockTolerantJobStore
from database.engine_factory import create_db_engine


def _locked():
    return OperationalError(
        "UPDATE flow_apscheduler_jobs SET next_run_time=?, job_state=? WHERE id = ?",
        {},
        sqlite3.OperationalError("database is locked"),
    )


def _fail_first(monkeypatch, method, times=1, error=_locked):
    """Make ``SQLAlchemyJobStore.<method>`` raise ``error()`` ``times`` times."""
    original = getattr(SQLAlchemyJobStore, method)
    state = {"left": times}

    def wrapper(self, *args, **kwargs):
        if state["left"] > 0:
            state["left"] -= 1
            raise error()
        return original(self, *args, **kwargs)

    monkeypatch.setattr(SQLAlchemyJobStore, method, wrapper)
    return state


@pytest.fixture
def flow_scheduler(tmp_path, monkeypatch):
    """The real FlowScheduler, initialised on a throwaway SQLite file."""
    from services import flow_scheduler_service as svc

    for name, value in (("_instance", None), ("_scheduler", None), ("_initialized", False)):
        monkeypatch.setattr(svc.FlowScheduler, name, value)

    fs = svc.FlowScheduler()
    fs.init(db_url=f"sqlite:///{(tmp_path / 'jobs.db').as_posix()}")
    executed = []
    fs.scheduler.add_listener(lambda event: executed.append(event.job_id), EVENT_JOB_EXECUTED)
    try:
        yield fs, executed
    finally:
        fs.scheduler.shutdown(wait=False)


def _wait_until(predicate, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


def test_flow_scheduler_uses_the_lock_tolerant_store(flow_scheduler):
    fs, _ = flow_scheduler
    assert isinstance(fs.scheduler._lookup_jobstore("default"), LockTolerantJobStore)


def test_locked_update_does_not_kill_the_scheduler_thread(flow_scheduler, monkeypatch):
    """The production failure: a lock on the next-run-time write after a run."""
    fs, executed = flow_scheduler
    _fail_first(monkeypatch, "update_job")

    fs.scheduler.add_job(
        time.time,
        IntervalTrigger(seconds=1, start_date=datetime.now() + timedelta(seconds=0.3)),
        id="flow_workflow_1",
    )

    assert _wait_until(lambda: len(executed) >= 3, timeout=8), (
        f"job ran {len(executed)} time(s) after a locked update; the scheduler stopped"
    )
    assert fs.scheduler._thread.is_alive()


def test_deferred_update_does_not_run_the_job_twice(flow_scheduler, monkeypatch):
    """The stale row must not be read back as due once the job has run."""
    fs, executed = flow_scheduler
    calls = _fail_first(monkeypatch, "update_job")

    fs.scheduler.add_job(
        time.time,
        IntervalTrigger(minutes=1, start_date=datetime.now() + timedelta(seconds=0.3)),
        id="flow_workflow_2",
    )

    assert _wait_until(lambda: executed and calls["left"] == 0, timeout=5)
    time.sleep(1.5)
    assert executed == ["flow_workflow_2"]
    assert fs.scheduler._thread.is_alive()

    # The deferred write reached the database: next run is a minute out.
    job = fs.scheduler.get_job("flow_workflow_2")
    assert job.next_run_time.timestamp() > time.time() + 50


def test_locked_remove_of_a_finished_job_is_applied_later(flow_scheduler, monkeypatch):
    """A one-shot job is removed, not updated, after it runs."""
    fs, executed = flow_scheduler
    _fail_first(monkeypatch, "remove_job")

    fs.scheduler.add_job(
        time.time,
        DateTrigger(run_date=datetime.now() + timedelta(seconds=0.3)),
        id="flow_workflow_3",
    )

    assert _wait_until(lambda: executed, timeout=5)
    time.sleep(1.0)
    assert executed == ["flow_workflow_3"]
    assert fs.scheduler._thread.is_alive()
    assert fs.scheduler.get_job("flow_workflow_3") is None


def test_locked_next_run_time_read_does_not_kill_the_thread(flow_scheduler, monkeypatch):
    fs, executed = flow_scheduler
    _fail_first(monkeypatch, "get_next_run_time")

    fs.scheduler.add_job(
        time.time,
        IntervalTrigger(seconds=1, start_date=datetime.now() + timedelta(seconds=0.3)),
        id="flow_workflow_4",
    )
    # The first tick hits the lock and waits out jobstore_retry_interval (10s),
    # so shorten it rather than the test sleeping that long.
    fs.scheduler.jobstore_retry_interval = 0.5

    assert _wait_until(lambda: len(executed) >= 2, timeout=8)
    assert fs.scheduler._thread.is_alive()


@pytest.fixture
def store(tmp_path):
    from database.apscheduler_jobstore_db import ensure_jobstore_table

    url = f"sqlite:///{(tmp_path / 'jobs.db').as_posix()}"
    ensure_jobstore_table(FLOW_JOBSTORE_TABLE, database_url=url)
    s = LockTolerantJobStore(engine=create_db_engine(url), tablename=FLOW_JOBSTORE_TABLE)
    yield s
    s.shutdown()


def test_writes_outside_the_scheduler_loop_still_raise(store, monkeypatch):
    """Deactivating a workflow must not be told a locked removal succeeded."""
    _fail_first(monkeypatch, "remove_job")
    with pytest.raises(OperationalError):
        store.remove_job("flow_workflow_5")
    assert store._pending == {}


def test_errors_that_are_not_a_lock_are_not_deferred(store, monkeypatch):
    store.get_due_jobs(datetime.now().astimezone())  # enter the loop window
    _fail_first(
        monkeypatch,
        "remove_job",
        error=lambda: OperationalError("DELETE", {}, sqlite3.OperationalError("disk I/O error")),
    )
    with pytest.raises(OperationalError):
        store.remove_job("flow_workflow_6")
    assert store._pending == {}


def test_deferral_is_limited_to_the_thread_in_the_loop(store, monkeypatch):
    store.get_due_jobs(datetime.now().astimezone())
    _fail_first(monkeypatch, "remove_job")
    raised = []

    def other():
        try:
            store.remove_job("flow_workflow_7")
        except OperationalError as exc:
            raised.append(exc)

    worker = threading.Thread(target=other)
    worker.start()
    worker.join(timeout=10)
    assert raised and store._pending == {}
