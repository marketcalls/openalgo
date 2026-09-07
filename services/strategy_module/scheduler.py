"""Cron scheduling for the /strategy module: automatic start, automatic square-off.

A strategy carries a ``scheduler`` JSON config
(``{enabled, days, start_time, auto_stop_time, default_mode}``) and this module
turns it into at most two APScheduler jobs:

    strategy:{id}:start   start a run at ``start_time`` on the configured days
    strategy:{id}:stop    square the run off at ``auto_stop_time``

Everything here is deliberately different from the four schedulers that came
before it, because each of them carries a defect that is invisible until it is
live:

**The timezone is explicit, on the scheduler and on every trigger.**
``flow_scheduler_service`` and ``historify_scheduler_service`` build a
``CronTrigger`` with neither, so their jobs fire in server-local time. A VPS in
UTC runs a 09:20 IST entry at 14:50 IST. Trading times in this product are
always IST, so ``Asia/Kolkata`` is passed in both places.

**Job defaults are set.** APScheduler's default ``misfire_grace_time`` is one
second. Production is a single Gunicorn worker, so a 09:20 job whose worker is
mid-request at 09:20:01 is dropped without a trace, which is how an entry
silently never happens. Sixty seconds is long enough to survive a busy worker
and short enough that a job which missed its slot by minutes does not fire into
a market that has moved.

**Job functions are module-level callables with plain arguments.**
``blueprints/python_strategy.py`` schedules ``lambda: f(id)``, which no job
store can serialize. This one uses an in-memory store, so it would work
anyway - it is written this way so it stays true if that ever changes.

**Every job releases its scoped sessions.** A scheduler worker runs outside any
Flask app context, so ``teardown_appcontext`` never fires and the sessions the
job touched stay bound to that thread for the life of the process (issue
#1738). Both job functions end in ``finally: remove_all_scoped_sessions()``.

**Nothing starts at import.** ``blueprints/chartink.py`` and
``blueprints/python_strategy.py`` call ``scheduler.start()`` at module scope, so
merely importing the app - a test, a migration, a CLI tool - spins up a live
scheduler. Here the caller calls :func:`start` explicitly.

The job store is in memory. Jobs are derived from the database on every boot
(:func:`sync_all_jobs`) and re-derived whenever a strategy changes
(:func:`sync_strategy_jobs`), so there is no persisted schedule that can go
stale against the config it came from, and nothing to reconcile at startup.
"""

from __future__ import annotations

import re
import threading
from datetime import time as dt_time
from typing import Any

import pytz
from apscheduler.jobstores.base import JobLookupError
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from database import strategy_module_db as store
from utils.logging import get_logger

logger = get_logger(__name__)

#: Every trading time in this product is IST. Passed to the scheduler *and* to
#: each trigger: a trigger built without one inherits the machine's local zone,
#: not the scheduler's, on some APScheduler paths.
IST = pytz.timezone("Asia/Kolkata")

#: Applied to every job. See the module docstring on misfire_grace_time.
JOB_DEFAULTS: dict[str, Any] = {
    "coalesce": True,
    "max_instances": 1,
    "misfire_grace_time": 60,
}

#: Job ids are ``strategy:{id}:start`` / ``strategy:{id}:stop``. The prefix is
#: what lets :func:`sync_all_jobs` recognise its own jobs and drop orphans.
JOB_PREFIX = "strategy:"

# One shared safety job, independent of per-strategy schedules. A broker push
# frame can be dropped after a cancellation; polling every pending durable stop
# lets that run self-heal without creating one timer or thread per run.
PENDING_STOP_RECONCILE_JOB_ID = "strategy-pending-stop-reconcile"
PENDING_STOP_RECONCILE_SECONDS = 5

_DAY_TO_CRON = {
    "MON": "mon",
    "TUE": "tue",
    "WED": "wed",
    "THU": "thu",
    "FRI": "fri",
    "SAT": "sat",
    "SUN": "sun",
}
_CRON_WEEK_ORDER = tuple(_DAY_TO_CRON.values())

_HHMM = re.compile(r"^(\d{1,2}):(\d{2})$")

# The scheduler singleton and the lock that guards creating and tearing it down.
#
# A plain threading.Lock is correct here: under eventlet every caller is a
# greenlet (a request handler, boot, or an APScheduler worker, all of which are
# green once the stdlib is patched), so no real thread ever touches it and the
# cross-world hazard in CLAUDE.md does not apply. The critical section is
# in-memory bookkeeping only.
_scheduler: BackgroundScheduler | None = None
_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


def start(paused: bool = False) -> BackgroundScheduler:
    """Create and start the shared scheduler. Idempotent.

    Args:
        paused: Start the scheduler paused, so jobs are installed and their
            next fire times computed but nothing ever fires. Tests use this to
            assert on the schedule without waiting on the wall clock.

    Returns:
        The running scheduler.
    """
    global _scheduler
    with _lock:
        if _scheduler is not None and _scheduler.running:
            return _scheduler

        # No jobstores argument: the default MemoryJobStore is the point. The
        # schedule is a projection of the database, rebuilt on every boot.
        _scheduler = BackgroundScheduler(timezone=IST, job_defaults=JOB_DEFAULTS)
        _scheduler.add_job(
            func=reconcile_pending_stops,
            trigger=IntervalTrigger(
                seconds=PENDING_STOP_RECONCILE_SECONDS,
                timezone=IST,
            ),
            id=PENDING_STOP_RECONCILE_JOB_ID,
            name="Strategy pending-stop reconciliation",
            replace_existing=True,
        )
        _scheduler.start(paused=paused)
        logger.info("Strategy module scheduler started (timezone %s, paused=%s)", IST, paused)
        return _scheduler


def shutdown() -> None:
    """Stop the shared scheduler and drop it. Idempotent."""
    global _scheduler
    with _lock:
        if _scheduler is None:
            return
        try:
            if _scheduler.running:
                _scheduler.shutdown(wait=False)
            logger.info("Strategy module scheduler shut down")
        except Exception:
            logger.exception("Could not shut the strategy module scheduler down cleanly")
        finally:
            _scheduler = None


def get_scheduler() -> BackgroundScheduler | None:
    """The shared scheduler, or None when :func:`start` has not been called."""
    return _scheduler


def _require_scheduler() -> BackgroundScheduler | None:
    """The scheduler, or None with a warning.

    Syncing before the scheduler exists is not an error worth raising over: a
    deployment that never calls :func:`start` simply has no automation, and a
    create or update on such an install must still succeed.
    """
    scheduler = _scheduler
    if scheduler is None:
        logger.warning(
            "Strategy module scheduler is not started; no jobs were installed or removed"
        )
    return scheduler


# ---------------------------------------------------------------------------
# Job ids
# ---------------------------------------------------------------------------


def start_job_id(strategy_id: int) -> str:
    return f"{JOB_PREFIX}{strategy_id}:start"


def stop_job_id(strategy_id: int) -> str:
    return f"{JOB_PREFIX}{strategy_id}:stop"


def _strategy_id_from_job_id(job_id: str) -> int | None:
    """The strategy id encoded in one of our job ids, or None."""
    parts = str(job_id).split(":")
    if len(parts) != 3 or parts[0] != JOB_PREFIX.rstrip(":"):
        return None
    try:
        return int(parts[1])
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Config parsing
# ---------------------------------------------------------------------------


def _parse_hhmm(value: Any, label: str) -> tuple[int, int] | None:
    """``HH:MM`` (or a ``datetime.time``) as ``(hour, minute)``, else None.

    Strict on purpose. A trigger built from a half-parsed time fires at the
    wrong moment forever and looks scheduled while doing it, so anything that
    is not a valid 24-hour clock time is refused here and the job is skipped
    with a log line the operator can act on.
    """
    if value is None:
        return None
    if isinstance(value, dt_time):
        return value.hour, value.minute
    if not isinstance(value, str):
        logger.warning("%s is not a HH:MM time: %r", label, value)
        return None

    match = _HHMM.match(value.strip())
    if not match:
        logger.warning("%s is not a HH:MM time: %r", label, value)
        return None

    hour, minute = int(match.group(1)), int(match.group(2))
    if hour > 23 or minute > 59:
        logger.warning("%s is not a valid time of day: %r", label, value)
        return None
    return hour, minute


def _cron_days(raw: Any, label: str) -> str | None:
    """``["MON", "WED"]`` as APScheduler's ``day_of_week`` string, else None.

    An unrecognised day rejects the whole list rather than being dropped from
    it. Silently trading four days out of a five-day schedule is worse than not
    trading at all, because nothing reports it.
    """
    if not isinstance(raw, (list, tuple)) or not raw:
        logger.warning("%s has no days configured; no job was installed", label)
        return None

    days: list[str] = []
    for day in raw:
        cron = _DAY_TO_CRON.get(str(day).strip().upper())
        if cron is None:
            logger.warning("%s lists an unknown day %r; no job was installed", label, day)
            return None
        if cron not in days:
            days.append(cron)

    return ",".join(sorted(days, key=_CRON_WEEK_ORDER.index))


# Monday to Friday, in APScheduler's cron vocabulary.
_WEEKDAYS = "mon,tue,wed,thu,fri"


def _planned_jobs(row: store.SmStrategy) -> list[dict[str, Any]]:
    """What should be installed for one strategy, as ``{job_id, func, ...}``.

    Returns an empty list when the strategy schedules nothing, which is also
    the answer for a config too broken to build a trigger from.
    """
    config = row.scheduler if isinstance(row.scheduler, dict) else None
    label = f"strategy {row.id} scheduler"
    scheduled = bool(config and config.get("enabled"))

    day_of_week = _cron_days(config.get("days"), f"{label}.days") if scheduled else None

    planned: list[dict[str, Any]] = []

    # The square-off from exit_time has to survive both of the early returns
    # this function used to take. An intraday strategy that sets exit_time and
    # leaves the scheduler switched off is the default configuration, and it
    # got no stop job at all: nothing squared the position off and it stayed
    # open past the exit the user configured, until a manual stop or the EOD
    # path caught it. exit_time is the strategy's own statement of when it must
    # be flat, so it is honoured whether or not anything else is scheduled.
    if not scheduled or not day_of_week:
        if row.exit_time is None:
            return []
        exit_at = _parse_hhmm(row.exit_time, f"strategy {row.id} exit_time")
        if exit_at is None:
            return []
        return [
            {
                "job_id": stop_job_id(row.id),
                "name": f"Strategy {row.id} scheduled square-off (exit_time)",
                "func": run_scheduled_stop,
                # No scheduler config to take days from, so every trading day.
                # A holiday costs one no-op on a strategy that is not running.
                "day_of_week": _WEEKDAYS,
                "hour": exit_at[0],
                "minute": exit_at[1],
            }
        ]

    start_at = _parse_hhmm(config.get("start_time"), f"{label}.start_time")
    if start_at is None:
        logger.warning("%s has no usable start_time; no start job was installed", label)
    else:
        planned.append(
            {
                "job_id": start_job_id(row.id),
                "name": f"Strategy {row.id} scheduled start",
                "func": run_scheduled_start,
                "day_of_week": day_of_week,
                "hour": start_at[0],
                "minute": start_at[1],
            }
        )

    stop_at = _parse_hhmm(config.get("auto_stop_time"), f"{label}.auto_stop_time")
    stop_source = "scheduler.auto_stop_time"

    # The auto-stop job is installed only from scheduler.auto_stop_time in the
    # module this is ported from, so an intraday strategy that sets exit_time
    # and leaves auto_stop_time blank got no square-off. exit_time fills in
    # whenever the scheduler config does not give one; see the block above for
    # the case where the scheduler is off entirely.
    if stop_at is None and row.exit_time is not None:
        stop_at = _parse_hhmm(row.exit_time, f"strategy {row.id} exit_time")
        stop_source = "exit_time"

    if stop_at is None:
        logger.debug("%s has no auto stop time and no exit_time; no stop job installed", label)
    else:
        planned.append(
            {
                "job_id": stop_job_id(row.id),
                "name": f"Strategy {row.id} scheduled square-off ({stop_source})",
                "func": run_scheduled_stop,
                "day_of_week": day_of_week,
                "hour": stop_at[0],
                "minute": stop_at[1],
            }
        )

    return planned


# ---------------------------------------------------------------------------
# Sync
# ---------------------------------------------------------------------------


def _remove_job(scheduler: BackgroundScheduler, job_id: str) -> bool:
    """Remove a job. A job that is not there is the desired end state, not an error."""
    try:
        scheduler.remove_job(job_id)
        logger.info("Removed scheduler job %s", job_id)
        return True
    except JobLookupError:
        return False
    except Exception:
        logger.exception("Could not remove scheduler job %s", job_id)
        return False


def sync_strategy_jobs(strategy_id: int) -> list[str]:
    """Rebuild one strategy's jobs from its stored config.

    Call after a strategy is created, updated or deleted. Removing what is no
    longer wanted happens first, so a strategy whose scheduler was switched off
    stops firing even though nothing new is installed.

    Returns the job ids now installed for this strategy.
    """
    scheduler = _require_scheduler()
    if scheduler is None:
        return []

    row = store.get_strategy_unscoped(strategy_id)
    planned = _planned_jobs(row) if row is not None else []
    wanted = {job["job_id"] for job in planned}

    for job_id in (start_job_id(strategy_id), stop_job_id(strategy_id)):
        if job_id not in wanted:
            _remove_job(scheduler, job_id)

    installed: list[str] = []
    for job in planned:
        try:
            scheduler.add_job(
                func=job["func"],
                trigger=CronTrigger(
                    day_of_week=job["day_of_week"],
                    hour=job["hour"],
                    minute=job["minute"],
                    # Explicit, every time. See the module docstring.
                    timezone=IST,
                ),
                # A module-level callable and plain arguments, never a closure.
                args=[strategy_id],
                id=job["job_id"],
                name=job["name"],
                replace_existing=True,
            )
            installed.append(job["job_id"])
            logger.info(
                "Scheduled %s on %s at %02d:%02d IST",
                job["job_id"],
                job["day_of_week"],
                job["hour"],
                job["minute"],
            )
        except Exception:
            logger.exception("Could not install scheduler job %s", job["job_id"])

    return installed


def sync_all_jobs() -> dict[str, int]:
    """Rebuild every job from the database. Call once at startup.

    Also drops jobs whose strategy no longer exists, so a delete that never
    reached :func:`sync_strategy_jobs` cannot leave something firing against a
    strategy that is gone.

    Returns ``{"strategies": n, "installed": n, "orphans_removed": n}``.
    """
    scheduler = _require_scheduler()
    if scheduler is None:
        return {"strategies": 0, "installed": 0, "orphans_removed": 0}

    installed: list[str] = []
    seen: set[int] = set()
    try:
        rows = store.db_session.query(store.SmStrategy).all()
        for row in rows:
            seen.add(row.id)
            installed.extend(sync_strategy_jobs(row.id))
    except Exception:
        logger.exception("Could not rebuild the strategy module schedule")
    finally:
        # This runs at boot, on a thread with no Flask app context, so
        # teardown_appcontext never fires and the session would stay bound to
        # that thread for the life of the process. Only this module's session is
        # released: a caller running inside a request keeps everything else.
        store.db_session.remove()

    orphans = 0
    for job in scheduler.get_jobs():
        owner = _strategy_id_from_job_id(job.id)
        if owner is not None and owner not in seen:
            logger.warning("Removing orphaned scheduler job %s: the strategy is gone", job.id)
            if _remove_job(scheduler, job.id):
                orphans += 1

    logger.info(
        "Strategy module schedule rebuilt: %d strategies, %d jobs, %d orphans removed",
        len(seen),
        len(installed),
        orphans,
    )
    return {"strategies": len(seen), "installed": len(installed), "orphans_removed": orphans}


def remove_strategy_jobs(strategy_id: int) -> int:
    """Remove both jobs for one strategy. Returns how many were actually there."""
    scheduler = _require_scheduler()
    if scheduler is None:
        return 0

    removed = 0
    for job_id in (start_job_id(strategy_id), stop_job_id(strategy_id)):
        if _remove_job(scheduler, job_id):
            removed += 1
    return removed


def list_jobs() -> list[dict[str, Any]]:
    """Every installed job, for diagnostics.

    ``next_run_time`` is what an operator actually needs: a job can be present
    and correct and still never fire, and this is the only place that shows it.
    """
    scheduler = _scheduler
    if scheduler is None:
        return []

    jobs: list[dict[str, Any]] = []
    for job in scheduler.get_jobs():
        if not str(job.id).startswith(JOB_PREFIX):
            continue
        next_run = getattr(job, "next_run_time", None)
        jobs.append(
            {
                "id": job.id,
                "name": job.name,
                "strategy_id": _strategy_id_from_job_id(job.id),
                "trigger": str(job.trigger),
                "next_run_time": next_run.isoformat() if next_run else None,
            }
        )
    return sorted(jobs, key=lambda item: item["id"])


# ---------------------------------------------------------------------------
# Job functions
#
# Module-level and picklable, and each one ends by releasing its scoped
# sessions: there is no app context on a scheduler worker.
# ---------------------------------------------------------------------------


def run_scheduled_start(strategy_id: int) -> None:
    """Start a strategy on its schedule."""
    try:
        row = store.get_strategy_unscoped(strategy_id)
        if row is None:
            logger.warning("Scheduled start skipped: strategy %s no longer exists", strategy_id)
            return

        config = row.scheduler if isinstance(row.scheduler, dict) else {}
        if not config.get("enabled"):
            # Fail closed. A job can outlive the sync that should have removed
            # it, and this is the last check before real orders.
            logger.warning(
                "Scheduled start skipped: the scheduler is disabled on strategy %s", strategy_id
            )
            return

        # Idempotent by design. The UI, an inbound webhook and this job can all
        # target the same strategy, and a webhook that already started it is the
        # normal case, not a conflict.
        if row.status == "running":
            logger.info("Scheduled start skipped: strategy %s is already running", strategy_id)
            return

        mode = config.get("default_mode") or "sandbox"
        if mode not in store.RUN_MODES:
            logger.error(
                "Scheduled start skipped: strategy %s has an unknown default_mode %r",
                strategy_id,
                mode,
            )
            return

        if mode == "live" and not row.live_enabled:
            # Recorded, not just logged. The operator's view of why an entry did
            # not happen is the event trail, and a schedule that quietly does
            # nothing every morning is the failure this is here to make visible.
            message = "Scheduled live start refused: live trading is not enabled for this strategy"
            logger.warning("%s (strategy %s)", message, strategy_id)
            store.record_event(
                strategy_id,
                row.user_id,
                "live_disabled",
                message,
                severity="warn",
                payload={"trigger_source": "scheduler", "mode": mode},
            )
            return

        from services.strategy_module import engine

        result = engine.start_run(strategy_id, row.user_id, mode, trigger_source="scheduler")
        if getattr(result, "ok", False):
            logger.info(
                "Scheduled start of strategy %s opened run %s in %s mode",
                strategy_id,
                getattr(result, "run_id", None),
                mode,
            )
        else:
            logger.error(
                "Scheduled start of strategy %s failed: %s",
                strategy_id,
                getattr(result, "error", "unknown error"),
            )
    except Exception:
        logger.exception("Scheduled start failed for strategy %s", strategy_id)
    finally:
        from utils.db_sessions import remove_all_scoped_sessions

        remove_all_scoped_sessions()


def run_scheduled_stop(strategy_id: int) -> None:
    """Square a strategy off on its schedule.

    Deliberately not gated on ``scheduler.enabled``: this is the safety half of
    the pair, and a run that is open must be closed whatever the config now
    says.
    """
    try:
        row = store.get_strategy_unscoped(strategy_id)
        if row is None:
            logger.warning("Scheduled stop skipped: strategy %s no longer exists", strategy_id)
            return

        if row.status != "running" or not row.current_run_id:
            logger.info("Scheduled stop skipped: strategy %s is not running", strategy_id)
            return
        run_id = int(row.current_run_id)
        user_id = str(row.user_id)

        from services.strategy_module import engine

        result = engine.stop_run(run_id, user_id, reason="scheduler")
        accepted = isinstance(result, dict) and bool(result.get("ok"))
        pending = isinstance(result, dict) and bool(result.get("stop_pending"))
        if accepted and pending:
            logger.info(
                "Scheduled square-off accepted for run %s of strategy %s; exit fills pending",
                run_id,
                strategy_id,
            )
        elif accepted:
            logger.info(
                "Scheduled square-off closed run %s of strategy %s",
                run_id,
                strategy_id,
            )
        elif pending:
            error = result.get("error") if isinstance(result, dict) else result
            logger.error(
                "Scheduled square-off refused for strategy %s; stop remains pending and "
                "retryable: %s",
                strategy_id,
                error,
            )
        else:
            error = result.get("error") if isinstance(result, dict) else result
            logger.error("Scheduled square-off of strategy %s failed: %s", strategy_id, error)
    except Exception:
        logger.exception("Scheduled stop failed for strategy %s", strategy_id)
    finally:
        from utils.db_sessions import remove_all_scoped_sessions

        remove_all_scoped_sessions()


def reconcile_pending_stops() -> dict[str, int]:
    """Repair open-run acknowledgements, then retry every durable stop."""
    result_counts = {"examined": 0, "pending": 0, "finalised": 0, "failed": 0}
    try:
        try:
            from services.strategy_module import ack_reconciliation

            # The same bounded job covers ordinary active runs. This keeps a
            # lost acknowledgement/fill managed without adding a per-run
            # timer, thread, sleep, or broker I/O under the scheduler lock.
            ack_reconciliation.reconcile_open_runs()
        except Exception:
            logger.exception("Periodic open-run acknowledgement repair failed")

        pending_runs = [
            run.id
            for run in store.list_open_runs()
            if run.stop_requested_reason is not None
        ]
        from services.strategy_module import engine

        for run_id in pending_runs:
            result_counts["examined"] += 1
            try:
                outcome = engine.reconcile_pending_stop(run_id)
            except Exception:
                logger.exception("Pending-stop reconciliation failed for run %s", run_id)
                result_counts["failed"] += 1
                continue

            if not isinstance(outcome, dict):
                result_counts["failed"] += 1
            elif outcome.get("stop_pending"):
                result_counts["pending"] += 1
                if not outcome.get("ok"):
                    result_counts["failed"] += 1
            elif outcome.get("ok"):
                result_counts["finalised"] += 1
            else:
                result_counts["failed"] += 1
        return result_counts
    finally:
        from utils.db_sessions import remove_all_scoped_sessions

        remove_all_scoped_sessions()
