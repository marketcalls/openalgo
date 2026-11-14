"""A busy database must not stop scheduled Flow workflows.

Two defects made one outage (issues #2355 and #2326):

1. Recording a run trimmed that workflow's old executions, and the trim issued
   its DELETE on every run. When it removed nothing it never committed, so the
   run kept the database write lock until it finished. A run that took longer
   than the 15 second lock budget, or a workflow running every few seconds,
   left every other writer on openalgo.db waiting until it gave up.

2. One of those writers was the scheduler, saving a job's next run time. That
   failure escaped APScheduler's loop and ended its thread. The scheduler still
   said it was running and still accepted jobs, but nothing fired again until
   the application was restarted.

The cases below hold the database against a real second connection wherever the
lock itself is the subject, and fail the job store's own write where the
subject is what the scheduler does next.
"""

import sqlite3
import threading
import time
from datetime import datetime, timedelta

import pytest
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import event
from sqlalchemy.exc import OperationalError

import database
import utils.resilient_scheduler as resilient
from utils.resilient_scheduler import LockTolerantJobStore, ResilientBackgroundScheduler

TABLE = "resilience_test_jobs"

#: (tag, monotonic time) for every run a job makes. Module level because the job
#: store keeps a job's function by its import path.
RUNS = []


def _record(tag):
    RUNS.append((tag, time.monotonic()))


def _record_workflow(workflow_id, api_key=None):
    RUNS.append((workflow_id, time.monotonic()))


def _wait_for(condition, timeout=8.0, step=0.02):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(step)
    return bool(condition())


def _locked():
    """The error SQLite raises through SQLAlchemy when a write is refused."""
    return OperationalError("UPDATE jobs", {}, sqlite3.OperationalError("database is locked"))


def _plain_connection(path, **kwargs):
    """A second connection that gives up at once instead of waiting 15 seconds.

    ``factory`` is passed so this is a plain connection: the cooperative one
    that ``database/__init__.py`` installs would retry for its whole budget.
    """
    return sqlite3.connect(
        str(path), timeout=0.2, factory=sqlite3.Connection, isolation_level=None, **kwargs
    )


def _can_write(path) -> bool:
    other = _plain_connection(path)
    try:
        other.execute("BEGIN IMMEDIATE")
    except sqlite3.OperationalError as exc:
        assert "locked" in str(exc).lower()
        return False
    else:
        other.execute("ROLLBACK")
        return True
    finally:
        other.close()


# --- the run that kept the write lock ---------------------------------------


@pytest.fixture
def flow_database():
    """The test database with the Flow tables, cleaned of what a test adds."""
    import database.flow_db as flow_db

    flow_db.init_db()
    pre_existing = {workflow.id for workflow in flow_db.get_all_workflows()}

    yield flow_db

    flow_db.db_session.remove()
    for workflow in flow_db.get_all_workflows():
        if workflow.id not in pre_existing:
            flow_db.delete_workflow(workflow.id)
    flow_db.db_session.remove()


def test_recording_a_run_leaves_the_database_free_for_other_writers(flow_database):
    """create_execution() trims history; with nothing to trim it must hold nothing."""
    workflow = flow_database.create_workflow("lock test", nodes=[], edges=[])

    execution = flow_database.create_execution(workflow.id, status="running")

    assert execution is not None
    assert _can_write(flow_database.engine.url.database), (
        "the run still holds the database write lock"
    )


def test_trimming_with_nothing_to_trim_leaves_the_database_free(flow_database):
    workflow = flow_database.create_workflow("lock test", nodes=[], edges=[])
    flow_database.create_execution(workflow.id, status="running")

    deleted = flow_database.prune_workflow_executions(workflow.id, max_count=500, max_age_days=30)

    assert deleted == 0
    assert _can_write(flow_database.engine.url.database)


def test_trimming_that_removes_rows_still_removes_them_and_lets_go(flow_database):
    workflow = flow_database.create_workflow("lock test", nodes=[], edges=[])
    for _ in range(6):
        flow_database.create_execution(workflow.id, status="running")

    deleted = flow_database.prune_workflow_executions(workflow.id, max_count=2, max_age_days=0)

    assert deleted == 4
    assert len(flow_database.get_workflow_executions(workflow.id, limit=200)) == 2
    assert _can_write(flow_database.engine.url.database)


# --- the scheduler that a refused write used to stop -------------------------


def _stored_next_run(path, job_id):
    conn = _plain_connection(path)
    try:
        row = conn.execute(f"SELECT next_run_time FROM {TABLE} WHERE id = ?", (job_id,)).fetchone()
    finally:
        conn.close()
    return row[0] if row else None


def _every(seconds, first_in=0.3):
    return IntervalTrigger(
        seconds=seconds, start_date=datetime.now().astimezone() + timedelta(seconds=first_in)
    )


def _ticks_due(trigger) -> int:
    """How many fire times of an interval trigger have passed by now."""
    elapsed = (datetime.now().astimezone() - trigger.start_date).total_seconds()
    return int(elapsed // trigger.interval.total_seconds()) + 1 if elapsed >= 0 else 0


@pytest.fixture
def scheduler(tmp_path):
    """A running scheduler on its own database file, built as Flow builds its own."""
    from database.apscheduler_jobstore_db import ensure_jobstore_table
    from database.engine_factory import create_db_engine

    path = tmp_path / "jobs.db"
    url = f"sqlite:///{path}"
    ensure_jobstore_table(TABLE, database_url=url)
    engine = create_db_engine(url)

    @event.listens_for(engine, "connect")
    def _wait_for_the_lock_as_the_application_does(dbapi_connection, _record):
        # A test that imports a migration script loads upgrade/_pragmas.py, whose
        # process-wide listener sets SQLite's own lock wait to 15 seconds on
        # every connection made afterwards in this process. The application
        # never loads it. Without this, a case here that holds the lock passes
        # alone and fails after test_migrate_*.py, waiting inside SQLite for
        # longer than the case allows. This puts the application's value back
        # for this engine, so the wait happens in Python as it does in
        # production.
        dbapi_connection.execute(f"PRAGMA busy_timeout={database.BUSY_TIMEOUT_MS}")

    store = LockTolerantJobStore(engine=engine, tablename=TABLE)
    sched = ResilientBackgroundScheduler(
        jobstores={"default": store},
        job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 60},
    )
    del RUNS[:]
    sched.start()

    yield sched, store, path

    if sched.running:
        sched.shutdown(wait=True)
    engine.dispose()
    del RUNS[:]


def test_a_database_locked_at_the_save_does_not_stop_the_scheduler(scheduler, monkeypatch):
    """The outage of #2355, staged where it happened: the write after a dispatch.

    A second connection takes the write lock just before the scheduler saves the
    next run time and keeps it past the lock budget. The scheduler's thread used
    to end there. Now the runs go on every second while the database is still
    locked, each tick is run once, and the row is written once the lock goes.
    """
    sched, store, path = scheduler
    monkeypatch.setattr(database, "LOCK_RETRY_BUDGET_S", 0.3)
    holder = {}
    save = SQLAlchemyJobStore.update_job

    def lock_the_database_then_save(self, job):
        if "conn" not in holder:
            conn = _plain_connection(path, check_same_thread=False)
            conn.execute("BEGIN IMMEDIATE")
            holder["conn"] = conn
        return save(self, job)

    monkeypatch.setattr(SQLAlchemyJobStore, "update_job", lock_the_database_then_save)
    every_second = _every(1)
    sched.add_job(_record, every_second, id="tick", args=["tick"])

    try:
        assert _wait_for(lambda: "tick" in store._held), (
            f"the refused save was not kept: {len(RUNS)} run(s), lock taken: {'conn' in holder}, "
            f"loop alive: {sched.loop_alive()}"
        )
        assert _stored_next_run(path, "tick") < time.time(), "the row should still be the old one"

        # Still locked, and the workflow keeps its times.
        assert _wait_for(lambda: len(RUNS) >= 3), f"runs stopped after {len(RUNS)}"
        assert sched.loop_alive()
        assert "tick" in store._held
    finally:
        holder["conn"].execute("ROLLBACK")
        holder["conn"].close()

    assert _wait_for(lambda: not store._held), "the schedule was never saved after the lock went"
    assert _stored_next_run(path, "tick") > time.time() - 1.5
    before = len(RUNS)
    assert _wait_for(lambda: len(RUNS) >= before + 2), "runs stopped after the lock went"

    due = _ticks_due(every_second)
    assert len(RUNS) <= due, f"{len(RUNS)} runs for {due} ticks: a tick was run twice"


def test_a_run_is_dispatched_once_when_its_save_is_refused(scheduler, monkeypatch):
    """Catching the error and going round again would run the same tick twice.

    The run is handed to the executor before the next run time is written. With
    the row left as it was the job is due again on the next pass, a fraction of
    a second later, long before its one-minute interval.
    """
    sched, store, path = scheduler
    monkeypatch.setattr(resilient, "SAVE_RETRY_SECONDS", 0.2)
    sched.jobstore_retry_interval = 0.2
    refused = []
    save = SQLAlchemyJobStore.update_job

    def refuse_three_times(self, job):
        if len(refused) < 3:
            refused.append(job.id)
            raise _locked()
        return save(self, job)

    monkeypatch.setattr(SQLAlchemyJobStore, "update_job", refuse_three_times)
    started = time.time()
    sched.add_job(_record, _every(60), id="minute", args=["minute"])

    assert _wait_for(lambda: len(refused) == 3 and not store._held), "the save was never retried"
    time.sleep(0.5)

    assert len(RUNS) == 1, f"the tick was dispatched {len(RUNS)} times"
    assert sched.loop_alive()
    assert _stored_next_run(path, "minute") > started + 55


def test_a_pass_that_fails_does_not_end_the_loop(scheduler, monkeypatch):
    """Anything else going wrong in a pass is logged and the loop comes back."""
    sched, store, path = scheduler
    sched.jobstore_retry_interval = 0.2
    failed = []
    next_time = LockTolerantJobStore.get_next_run_time

    def fail_once(self):
        if not failed:
            failed.append(True)
            raise RuntimeError("the job store could not be read")
        return next_time(self)

    monkeypatch.setattr(LockTolerantJobStore, "get_next_run_time", fail_once)
    sched.add_job(_record, _every(1), id="tick", args=["tick"])

    assert _wait_for(lambda: len(RUNS) >= 2), "nothing ran after the failed pass"
    assert failed
    assert sched.loop_alive()


def _end_the_loop_once(monkeypatch):
    """Make the next pass end the scheduler's thread, as a refused save used to."""
    process = ResilientBackgroundScheduler._process_jobs
    ended = []

    def end_the_thread_once(self):
        if not ended:
            ended.append(True)
            raise SystemExit  # not an Exception: nothing in the loop catches it
        return process(self)

    monkeypatch.setattr(ResilientBackgroundScheduler, "_process_jobs", end_the_thread_once)
    return ended


def test_a_loop_that_has_ended_is_started_again_and_only_once(scheduler, monkeypatch):
    """What #2326 looked like: jobs are accepted, and nothing fires them."""
    sched, store, path = scheduler
    ended = _end_the_loop_once(monkeypatch)
    sched.add_job(_record, _every(1), id="tick", args=["tick"])
    assert _wait_for(lambda: ended and not sched.loop_alive()), "the loop did not end"
    time.sleep(1.5)
    assert RUNS == [], "a job ran with no loop to fire it"

    assert sched.revive() is True
    assert sched.revive() is False, "a second loop would run every tick twice"

    assert _wait_for(lambda: len(RUNS) >= 2), "the job did not fire after the loop came back"
    loops = [t for t in threading.enumerate() if t is sched._thread]
    assert len(loops) == 1 and loops[0].is_alive()


def test_a_running_loop_is_left_alone(scheduler):
    sched, store, path = scheduler
    loop = sched._thread

    assert sched.revive() is False
    assert sched._thread is loop


# --- the job store on its own ------------------------------------------------


@pytest.fixture
def paused(scheduler):
    """The scheduler with its loop idle, and one job due every minute."""
    sched, store, path = scheduler
    sched.pause()
    sched.add_job(_record, _every(60, first_in=30), id="job", args=["job"])
    return sched, store, path


def _as_the_loop(sched):
    """Mark this thread as the scheduler's own pass, as _process_jobs does."""
    sched._pass.active = True


def test_a_held_schedule_is_what_every_reader_gets(paused, monkeypatch):
    sched, store, path = paused
    job = store.lookup_job("job")
    first = job.next_run_time
    second = first + timedelta(seconds=60)
    refuse = [True]
    save = SQLAlchemyJobStore.update_job

    def maybe_refuse(self, held_job):
        if refuse[0]:
            raise _locked()
        return save(self, held_job)

    monkeypatch.setattr(SQLAlchemyJobStore, "update_job", maybe_refuse)
    _as_the_loop(sched)
    job._modify(next_run_time=second)

    store.update_job(job)  # the scheduler's own write: kept, not raised

    assert store.lookup_job("job").next_run_time == second
    assert [j.next_run_time for j in store.get_all_jobs()] == [second]
    # The row still says `first`, which is due a second later. It must not be.
    assert store.get_due_jobs(first + timedelta(seconds=1)) == []
    assert [j.id for j in store.get_due_jobs(second)] == ["job"]
    soon = datetime.now().astimezone() + timedelta(seconds=resilient.SAVE_RETRY_SECONDS + 1)
    assert store.get_next_run_time() <= soon, "nothing brings the scheduler back to save it"
    assert _stored_next_run(path, "job") == pytest.approx(first.timestamp())

    # A pass: what is due first, and the save at its end.
    refuse[0] = False
    assert store.get_due_jobs(first + timedelta(seconds=1)) == []
    assert store.get_next_run_time() == second

    assert not store._held
    assert _stored_next_run(path, "job") == pytest.approx(second.timestamp())


def test_a_write_made_for_a_caller_still_fails(paused, monkeypatch):
    """Deactivation relies on this: a job that could not be removed is reported."""
    sched, store, path = paused
    job = store.lookup_job("job")

    def refuse(self, *_args):
        raise _locked()

    monkeypatch.setattr(SQLAlchemyJobStore, "update_job", refuse)
    monkeypatch.setattr(SQLAlchemyJobStore, "remove_job", refuse)

    with pytest.raises(OperationalError):
        store.update_job(job)
    with pytest.raises(OperationalError):
        store.remove_job("job")
    with pytest.raises(OperationalError):
        sched.remove_job("job")

    assert not store._held


def test_a_finished_job_whose_row_could_not_be_deleted_does_not_run_again(paused, monkeypatch):
    sched, store, path = paused
    refuse = [True]
    delete = SQLAlchemyJobStore.remove_job

    def maybe_refuse(self, job_id):
        if refuse[0]:
            raise _locked()
        return delete(self, job_id)

    monkeypatch.setattr(SQLAlchemyJobStore, "remove_job", maybe_refuse)
    _as_the_loop(sched)
    far_ahead = datetime.now().astimezone() + timedelta(days=1)

    store.remove_job("job")  # the scheduler's own delete of a one-off job that has run

    assert store.lookup_job("job") is None
    assert store.get_all_jobs() == []
    assert store.get_due_jobs(far_ahead) == []
    assert _stored_next_run(path, "job") is not None, "the row is still there until it can go"

    refuse[0] = False
    assert store.get_due_jobs(far_ahead) == []
    assert store.get_next_run_time() is None

    assert not store._held
    assert _stored_next_run(path, "job") is None


def _hold_the_next_run(sched, store, monkeypatch):
    """Leave the job's next run time held, and return (that time, the refusal switch)."""
    job = store.lookup_job("job")
    second = job.next_run_time + timedelta(seconds=60)
    refuse = [True]
    save = SQLAlchemyJobStore.update_job

    def maybe_refuse(self, held_job):
        if refuse[0]:
            raise _locked()
        return save(self, held_job)

    monkeypatch.setattr(SQLAlchemyJobStore, "update_job", maybe_refuse)
    _as_the_loop(sched)
    job._modify(next_run_time=second)
    store.update_job(job)
    assert "job" in store._held
    sched._pass.active = False
    return second, refuse


def test_what_is_held_is_saved_when_the_scheduler_stops(paused, monkeypatch):
    """The next start reads the row, so stopping is the last chance to write it.

    Nothing in this project does the writing: APScheduler's loop makes one more
    pass as it stops, and a pass ends by saving what is held. This pins that,
    so an upgrade that drops the last pass is noticed here.
    """
    sched, store, path = paused
    second, refuse = _hold_the_next_run(sched, store, monkeypatch)
    refuse[0] = False

    sched.shutdown(wait=True)

    assert not store._held
    assert _stored_next_run(path, "job") == pytest.approx(second.timestamp())


def test_stopping_with_a_schedule_still_refused_says_so(paused, monkeypatch, caplog):
    sched, store, path = paused
    first = store.lookup_job("job").next_run_time
    _hold_the_next_run(sched, store, monkeypatch)

    with caplog.at_level("WARNING", logger="utils.resilient_scheduler"):
        sched.shutdown(wait=True)

    assert store.unsaved() == ["_record (job)"]
    assert _stored_next_run(path, "job") == pytest.approx(first.timestamp())
    warnings = [r.getMessage() for r in caplog.records if "stopped before" in r.getMessage()]
    assert len(warnings) == 1 and "_record (job)" in warnings[0], warnings


# --- Flow and Historify are built on it --------------------------------------


def _fresh(cls):
    """An instance that is not the process-wide singleton."""
    return object.__new__(cls)


def test_the_flow_scheduler_is_built_on_these_classes(tmp_path):
    from services.flow_scheduler_service import FlowScheduler

    flow = _fresh(FlowScheduler)
    flow.init(db_url=f"sqlite:///{tmp_path / 'flow.db'}")
    try:
        assert isinstance(flow.scheduler, ResilientBackgroundScheduler)
        assert isinstance(flow.scheduler._jobstores["default"], LockTolerantJobStore)
        assert flow.ensure_running() is False
    finally:
        flow.shutdown()


def test_the_flow_scheduler_brings_a_stopped_loop_back_when_a_job_is_added(tmp_path, monkeypatch):
    from services.flow_scheduler_service import FlowScheduler

    flow = _fresh(FlowScheduler)
    flow.init(db_url=f"sqlite:///{tmp_path / 'flow.db'}")
    ended = _end_the_loop_once(monkeypatch)
    del RUNS[:]
    try:
        flow.scheduler.wakeup()
        assert _wait_for(lambda: ended and not flow.scheduler.loop_alive())

        flow.add_workflow_job(
            workflow_id=9911,
            schedule_type="interval",
            interval_value=1,
            interval_unit="seconds",
            func=_record_workflow,
        )

        assert flow.scheduler.loop_alive()
        assert _wait_for(lambda: len(RUNS) >= 1), "the job was accepted and never fired"
    finally:
        flow.shutdown()
        del RUNS[:]


def test_the_historify_scheduler_is_built_on_these_classes(tmp_path, monkeypatch):
    from services.historify_scheduler_service import HistorifyScheduler

    monkeypatch.setattr(HistorifyScheduler, "_restore_schedules", lambda self: None)
    historify = _fresh(HistorifyScheduler)
    historify.init(db_url=f"sqlite:///{tmp_path / 'historify.db'}")
    try:
        assert isinstance(historify.scheduler, ResilientBackgroundScheduler)
        assert isinstance(historify.scheduler._jobstores["default"], LockTolerantJobStore)
    finally:
        historify.shutdown()
