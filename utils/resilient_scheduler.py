"""A persistent scheduler that a busy database cannot stop.

Flow and Historify keep their schedules in openalgo.db through APScheduler's
``SQLAlchemyJobStore``, so a restart brings the jobs back. APScheduler's loop
does three things for a job that is due: it hands the run to the executor,
works out the next run time, and writes that time to the job store. The write
is not guarded. If the database refuses it, the exception leaves the loop and
the scheduler's thread ends. The scheduler still reports that it is running and
still accepts new jobs, but nothing wakes to fire them: every schedule is dead
until the application is restarted, and nothing in the log says so apart from
one "Exception in thread APScheduler" on stderr (issues #2355 and #2326).

SQLite refuses a write with "database is locked" whenever another connection
has held the write lock for longer than the 15 second budget in
``database/__init__.py``. That is rare, but it only has to happen once.

Catching the exception and going round again is not enough, and for a scheduler
that places orders it is the wrong fix. The run has already been handed to the
executor when the write fails. If the stored next run time is left as it was,
the job is still due on the next pass and is handed over a second time: one
tick of a one-minute workflow, run twice a few seconds apart.

So the two classes here do it in this order:

``LockTolerantJobStore`` keeps what the database would not take. A job whose
new state could not be written is held in memory, and from then on the held
copy is the truth for that job: it is what is returned as due, as its next run
time and to anyone who looks the job up, and the stale row is left out. Every
pass ends by trying to write what is held, after the due runs have gone out, so
a database that is still refusing delays nothing. A run is dispatched once, the
schedule keeps its times, and the row catches up when the database allows.

``ResilientBackgroundScheduler`` is the net under that. Anything else that goes
wrong in a pass is logged with its traceback, through the application's logger
so it reaches ``log/errors.jsonl``, and the loop comes back a few seconds
later. ``revive()`` starts the loop again if its thread has ended all the same.

Only the scheduler's own writes are held. A write made for a caller (adding,
changing or removing a job from a request) still fails as it always did, so a
route that must not report success on a failed write keeps its answer.

Every job store method is called by the scheduler under its ``_jobstores_lock``,
which is the lock that guards the held states here. Nothing else may call the
store directly.
"""

import threading
from datetime import UTC, datetime, timedelta

from apscheduler.jobstores.base import JobLookupError
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers.base import STATE_STOPPED
from apscheduler.util import utc_timestamp_to_datetime
from sqlalchemy import null, select
from sqlalchemy.exc import SQLAlchemyError

from utils.logging import get_logger

logger = get_logger(__name__)

#: Held in place of a job that has finished and whose row is still to be deleted.
_GONE = object()

#: How soon the scheduler comes back to write what the database refused, when no
#: job is due sooner. Short, because until the row is written a restart would
#: read the old run time from it.
SAVE_RETRY_SECONDS = 5


def _label(job_id, state) -> str:
    name = getattr(state, "name", None)
    return f"{name} ({job_id})" if name else str(job_id)


class LockTolerantJobStore(SQLAlchemyJobStore):
    """A SQLAlchemy job store whose schedule survives a refused write."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # job id -> the Job as the scheduler last left it, or _GONE, for every
        # job whose row the database has not taken yet.
        self._held = {}
        # A refused write has already waited out the lock budget, 15 seconds
        # under a real lock. One such wait is enough for a pass.
        self._refused_in_pass = False

    # -- which writes are the scheduler's own --------------------------------

    def _in_scheduler_pass(self) -> bool:
        in_pass = getattr(self._scheduler, "in_pass", None)
        return bool(in_pass and in_pass())

    def _hold(self, job_id, state, exc) -> None:
        if job_id not in self._held:
            reason = str(getattr(exc, "orig", exc)).splitlines()[0]
            logger.warning(
                f"Scheduler: the database could not save the schedule of "
                f"{_label(job_id, state)} ({reason}). It is being kept in memory and "
                f"will be saved as soon as the database allows. Its runs continue on time."
            )
        self._held[job_id] = state
        self._refused_in_pass = True

    def _saved(self, job_id) -> None:
        state = self._held.pop(job_id, None)
        if state is not None:
            logger.info(f"Scheduler: the schedule of {_label(job_id, state)} has been saved.")

    def _save_held(self) -> None:
        """Write what the database refused earlier. Stops at the first refusal."""
        for job_id, state in list(self._held.items()):
            try:
                if state is _GONE:
                    SQLAlchemyJobStore.remove_job(self, job_id)
                else:
                    SQLAlchemyJobStore.update_job(self, state)
            except JobLookupError:
                # The row has gone in the meantime: nothing is left to write.
                self._held.pop(job_id, None)
                continue
            except SQLAlchemyError:
                # Still refusing. Each attempt can wait out the whole lock
                # budget, so one is enough for this pass.
                self._refused_in_pass = True
                return
            self._saved(job_id)

    # -- writes ---------------------------------------------------------------

    def add_job(self, job):
        super().add_job(job)
        self._held.pop(job.id, None)

    def update_job(self, job):
        try:
            super().update_job(job)
        except JobLookupError:
            self._held.pop(job.id, None)
            raise
        except SQLAlchemyError as exc:
            if not self._in_scheduler_pass():
                raise
            self._hold(job.id, job, exc)
            return
        self._saved(job.id)

    def remove_job(self, job_id):
        try:
            super().remove_job(job_id)
        except JobLookupError:
            self._held.pop(job_id, None)
            raise
        except SQLAlchemyError as exc:
            if not self._in_scheduler_pass():
                raise
            self._hold(job_id, _GONE, exc)
            return
        self._saved(job_id)

    def remove_all_jobs(self):
        super().remove_all_jobs()
        self._held.clear()

    def unsaved(self) -> list[str]:
        """The jobs whose schedule the database has not taken yet."""
        return [_label(job_id, state) for job_id, state in self._held.items()]

    # -- reads: a held state stands in for its stale row ----------------------

    def lookup_job(self, job_id):
        if job_id in self._held:
            state = self._held[job_id]
            return None if state is _GONE else state
        return super().lookup_job(job_id)

    def get_due_jobs(self, now):
        # The first call of a pass. What is held is not written here: the runs
        # that are due go out first, and get_next_run_time(), the last call of
        # the pass, does the writing.
        self._refused_in_pass = False
        jobs = super().get_due_jobs(now)
        if not self._held:
            return jobs
        jobs = [job for job in jobs if job.id not in self._held]
        jobs.extend(
            state
            for state in self._held.values()
            if state is not _GONE and state.next_run_time is not None and state.next_run_time <= now
        )
        jobs.sort(key=lambda job: job.next_run_time)
        return jobs

    def get_next_run_time(self):
        if self._held and not self._refused_in_pass:
            self._save_held()
        if not self._held:
            return super().get_next_run_time()
        selectable = (
            select(self.jobs_t.c.next_run_time)
            .where(
                self.jobs_t.c.next_run_time != null(),
                self.jobs_t.c.id.notin_(list(self._held)),
            )
            .order_by(self.jobs_t.c.next_run_time)
            .limit(1)
        )
        with self.engine.begin() as connection:
            stored = utc_timestamp_to_datetime(connection.execute(selectable).scalar())
        times = [
            state.next_run_time
            for state in self._held.values()
            if state is not _GONE and state.next_run_time is not None
        ]
        if stored is not None:
            times.append(stored)
        # Come back to write what is held even when no job is due before then.
        times.append(datetime.now(UTC) + timedelta(seconds=SAVE_RETRY_SECONDS))
        return min(times)

    def get_all_jobs(self):
        jobs = super().get_all_jobs()
        if not self._held:
            return jobs
        jobs = [job for job in jobs if job.id not in self._held]
        jobs.extend(state for state in self._held.values() if state is not _GONE)
        # Soonest first, paused jobs last, as the parent returns them.
        jobs.sort(
            key=lambda job: (
                job.next_run_time is None,
                job.next_run_time.timestamp() if job.next_run_time else 0.0,
            )
        )
        return jobs


class ResilientBackgroundScheduler(BackgroundScheduler):
    """A BackgroundScheduler whose loop outlives a pass that fails."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._pass = threading.local()
        self._revive_lock = threading.Lock()

    def in_pass(self) -> bool:
        """True on the scheduler's own thread while it is processing due jobs."""
        return getattr(self._pass, "active", False)

    def _process_jobs(self):
        self._pass.active = True
        try:
            return super()._process_jobs()
        except Exception:
            retry = self.jobstore_retry_interval
            logger.exception(
                f"Scheduler: a pass over the scheduled jobs failed. It will be tried "
                f"again in {retry:g} seconds. The scheduler is still running."
            )
            return retry
        finally:
            self._pass.active = False

    def shutdown(self, *args, **kwargs):
        stores = list(self._jobstores.values())
        super().shutdown(*args, **kwargs)
        # APScheduler's loop makes one more pass as it stops, and a pass ends
        # by writing what is held, so nothing extra is written here: a second
        # attempt would only wait out the lock budget twice. What is still held
        # now was refused to the end. The next start reads the row, and a row
        # that still carries a run time from the last minute has that run made
        # again, so it is said plainly.
        for store in stores:
            names = store.unsaved() if isinstance(store, LockTolerantJobStore) else []
            if names:
                logger.warning(
                    f"Scheduler: stopped before the database took the schedule of "
                    f"{', '.join(names)}. A run of theirs made in the last minute may be "
                    f"made again on the next start."
                )

    def loop_alive(self) -> bool:
        """Whether the thread that fires due jobs is running."""
        thread = self._thread
        return thread is not None and thread.is_alive()

    def revive(self) -> bool:
        """Start the loop again if its thread has ended while the scheduler is on.

        Returns True when a new loop was started. Serialised, and a loop is only
        ever started when the previous thread has ended: two loops would hand
        every due run to the executor twice.
        """
        with self._revive_lock:
            if self.state == STATE_STOPPED or self._thread is None or self._thread.is_alive():
                return False
            self._thread = threading.Thread(
                target=self._main_loop, name="APScheduler", daemon=self._daemon
            )
            self._thread.start()
        # The new loop starts by waiting. Wake it so anything overdue is seen now.
        self.wakeup()
        return True
