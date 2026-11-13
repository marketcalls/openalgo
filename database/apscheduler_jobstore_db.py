"""APScheduler job store tables in openalgo.db.

APScheduler's ``SQLAlchemyJobStore`` issues its own ``CREATE TABLE`` from
``start()``. At boot that DDL lands in the middle of the startup write burst
and has to take the SQLite write lock. On a slow or memory-starved machine the
burst outlasts the 15s ``busy_timeout`` set in ``database/__init__.py`` and the
DDL fails with "database is locked". Scheduler init runs once with no retry, so
the scheduler then stays dead for the life of the process and scheduled Flow
workflows / Historify downloads silently never run. See issue #1750.

Creating the tables here, from the serialized database-init phase in ``app.py``,
means ``SQLAlchemyJobStore.start()`` finds them already present and its
``checkfirst=True`` create is a read-only no-op that never takes the write lock.
That phase runs single-threaded (``max_workers=1``) alongside the other twenty
``init_db`` functions, so the DDL is issued while nothing else is writing.

The scheduler services call ``ensure_jobstore_table`` again from their own
``init()`` as a safety net -- for a caller that starts a scheduler outside app
boot, and for the case where the init-phase attempt itself failed.

Upgrading installs get the same tables from ``upgrade/migrate_flow.py`` and
``upgrade/migrate_historify_scheduler.py``; this is the fresh-install path,
which runs no migrations.
"""

import os
import threading
import time
from datetime import UTC, datetime, timedelta

from apscheduler.jobstores.base import JobLookupError
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from sqlalchemy import inspect
from sqlalchemy.exc import OperationalError

from database.db_init_helper import _ensure_sqlite_dir
from database.engine_factory import create_db_engine
from utils.logging import get_logger

logger = get_logger(__name__)

#: Table names are owned here rather than by the scheduler services so the
#: init-phase creation and the runtime job store cannot drift apart.
FLOW_JOBSTORE_TABLE = "flow_apscheduler_jobs"
HISTORIFY_JOBSTORE_TABLE = "historify_apscheduler_jobs"

#: A lost write-lock race is transient, so it is retried rather than surfaced.
#: Each attempt already waits out the 15s busy_timeout, making the total worst
#: case ~45s -- well inside the gunicorn 300s worker timeout, and only ever
#: reached on the one boot that creates the tables.
_MAX_ATTEMPTS = 3


def get_database_url():
    """Return the openalgo.db URL the job stores live in.

    Matches the default used by the scheduler services so both resolve to the
    same file when DATABASE_URL is unset.
    """
    return os.getenv("DATABASE_URL", "sqlite:///db/openalgo.db")


def _create_table(engine, tablename):
    """Create one job store table and its index, if either is missing."""
    # Built from APScheduler's own table metadata rather than hand-written SQL,
    # so the schema cannot drift from what APScheduler expects. Constructing
    # the store touches no connection -- it only builds the Table object.
    # engine= rather than url= so this reuses our engine instead of opening a
    # second one that would then have to be disposed.
    jobs_t = SQLAlchemyJobStore(engine=engine, tablename=tablename).jobs_t

    jobs_t.create(engine, checkfirst=True)

    # Table.create(checkfirst=True) tests only for the table, so a job store
    # table that predates the index would never acquire one and every due-job
    # poll would scan it. Checked separately for that reason.
    existing = {idx["name"] for idx in inspect(engine).get_indexes(tablename)}
    for index in jobs_t.indexes:
        if index.name not in existing:
            index.create(engine)


def ensure_jobstore_table(tablename, database_url=None):
    """Create an APScheduler job store table, retrying a locked database.

    Safe to call repeatedly: an existing table and index make this a pair of
    read-only catalog queries that never take the write lock.

    Args:
        tablename: Job store table to create.
        database_url: SQLAlchemy URL. Defaults to the openalgo.db URL.

    Raises:
        OperationalError: If the database stayed locked across every attempt.
    """
    engine = create_db_engine(database_url or get_database_url())
    try:
        _ensure_sqlite_dir(engine)
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                _create_table(engine, tablename)
                return
            except OperationalError:
                if attempt == _MAX_ATTEMPTS:
                    raise
                logger.warning(
                    f"{tablename}: database locked creating job store table "
                    f"(attempt {attempt} of {_MAX_ATTEMPTS}), retrying"
                )
                time.sleep(attempt)
    finally:
        # One-shot init: dispose rather than leave an engine holding a pool for
        # the life of the process.
        engine.dispose()


def ensure_jobstore_tables_exist():
    """Create every APScheduler job store table.

    Registered in the ``app.py`` database-init phase. One table failing must not
    stop the other from being created, so each is attempted independently and a
    failure is logged rather than raised -- the owning scheduler retries on its
    own init and reports the real error there.
    """
    for tablename in (FLOW_JOBSTORE_TABLE, HISTORIFY_JOBSTORE_TABLE):
        try:
            ensure_jobstore_table(tablename)
        except Exception:
            logger.exception(f"Failed to create job store table {tablename}")


def _is_lock_error(exc):
    """True when a SQLAlchemy OperationalError is SQLite's transient write lock."""
    message = str(getattr(exc, "orig", exc)).lower()
    return "database is locked" in message or "database is busy" in message


#: Marks a deferred remove_job in ``LockTolerantJobStore._pending``.
_REMOVED = object()


class LockTolerantJobStore(SQLAlchemyJobStore):
    """A job store whose writes cannot kill the scheduler thread (issue #2355).

    APScheduler 3.x calls ``update_job()`` and ``remove_job()`` from its
    scheduler loop (``BaseScheduler._process_jobs``) with no exception handling,
    so a single "database is locked" from openalgo.db ends the ``APScheduler``
    thread. The process keeps running, jobs can still be added, and nothing
    ever fires again until a restart. Only ``get_due_jobs()`` is guarded there:
    an error from it is logged and retried after ``jobstore_retry_interval``.

    A lock that outlives the cooperative retry budget in ``database/__init__.py``
    (or a WAL snapshot conflict, which fails at once) is therefore deferred
    instead of raised, but only for writes the scheduler loop makes itself. The
    write is kept in memory and replayed before anything else touches the store,
    and above all at the start of the next ``get_due_jobs()``. Until the replay
    succeeds the stale row is never read back as due, so a job that already ran
    is not run a second time; a replay that is still locked raises from
    ``get_due_jobs()``, where APScheduler logs it and retries.

    Writes from any other thread (activating, deactivating or editing a
    workflow) still raise exactly as before, because their callers act on the
    outcome: deactivation must not report success while the row is still live.
    Errors that are not a lock are never deferred.

    APScheduler serializes every job store call under its ``_jobstores_lock``,
    so ``_pending`` and ``_loop_ident`` need no lock of their own.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        #: job id -> Job to write, or _REMOVED, in the order they were deferred.
        self._pending = {}
        #: Thread ident of the scheduler loop between get_due_jobs() and
        #: get_next_run_time(), the window in which _process_jobs writes.
        self._loop_ident = None

    def _flush_pending(self):
        """Replay deferred writes, raising if the database is still locked."""
        for job_id, item in list(self._pending.items()):
            try:
                if item is _REMOVED:
                    super().remove_job(job_id)
                else:
                    super().update_job(item)
            except JobLookupError:
                # Removed by someone else meanwhile: the desired end state for a
                # removal, and nothing left to update for an update.
                pass
            del self._pending[job_id]
            logger.info(f"Job store {self.jobs_t.name}: applied deferred write for {job_id}")

    def _defer(self, job_id, item, exc):
        """Keep a scheduler-loop write for later if it hit the lock, else raise."""
        if not _is_lock_error(exc) or self._loop_ident != threading.get_ident():
            return False
        self._pending[job_id] = item
        logger.warning(
            f"Job store {self.jobs_t.name}: database locked writing {job_id}, "
            f"deferring the write to the next scheduler tick: {exc}"
        )
        return True

    def get_due_jobs(self, now):
        self._loop_ident = None
        self._flush_pending()
        jobs = super().get_due_jobs(now)
        self._loop_ident = threading.get_ident()
        return jobs

    def get_next_run_time(self):
        self._loop_ident = None
        try:
            return super().get_next_run_time()
        except OperationalError as exc:
            if not _is_lock_error(exc):
                raise
            # Unguarded in _process_jobs too. Wake again after the same interval
            # APScheduler uses for a failed get_due_jobs().
            retry = getattr(self._scheduler, "jobstore_retry_interval", 10)
            logger.warning(
                f"Job store {self.jobs_t.name}: database locked reading the next "
                f"run time, retrying in {retry}s: {exc}"
            )
            return datetime.now(UTC) + timedelta(seconds=retry)

    def update_job(self, job):
        try:
            self._flush_pending()
            super().update_job(job)
        except OperationalError as exc:
            if not self._defer(job.id, job, exc):
                raise

    def remove_job(self, job_id):
        try:
            self._flush_pending()
            super().remove_job(job_id)
        except OperationalError as exc:
            if not self._defer(job_id, _REMOVED, exc):
                raise

    def add_job(self, job):
        self._flush_pending()
        super().add_job(job)

    def lookup_job(self, job_id):
        self._flush_pending()
        return super().lookup_job(job_id)

    def get_all_jobs(self):
        self._flush_pending()
        return super().get_all_jobs()

    def remove_all_jobs(self):
        super().remove_all_jobs()
        self._pending.clear()
