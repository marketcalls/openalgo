# services/flow_scheduler_service.py
"""
Flow Workflow Scheduler Service
Handles scheduled workflow execution using APScheduler (Flask/sync version)
"""

import logging
import os
import threading
from collections.abc import Callable
from datetime import datetime
from typing import Optional

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)


class FlowScheduler:
    """Singleton scheduler for Flow workflows"""

    _instance: Optional["FlowScheduler"] = None
    _scheduler: BackgroundScheduler | None = None
    _lock = threading.Lock()
    _initialized = False
    _api_key: str | None = None

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def init(self, db_url: str = None, api_key: str = None):
        """Initialize the scheduler with database URL for job persistence"""
        if self._initialized:
            return

        with self._lock:
            if self._initialized:
                return

            if db_url is None:
                db_url = os.getenv("DATABASE_URL", "sqlite:///db/openalgo.db")

            self._api_key = api_key

            try:
                jobstores = {
                    "default": SQLAlchemyJobStore(url=db_url, tablename="flow_apscheduler_jobs")
                }
                self._scheduler = BackgroundScheduler(
                    jobstores=jobstores,
                    job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 60},
                )
                self._scheduler.start()
                self._initialized = True
                logger.debug("Flow Scheduler initialized and started")
            except Exception as e:
                logger.exception(f"Failed to initialize Flow Scheduler: {e}")
                raise

    def set_api_key(self, api_key: str):
        """Set API key for workflow execution"""
        self._api_key = api_key

    @property
    def scheduler(self) -> BackgroundScheduler:
        """Get the scheduler instance"""
        if self._scheduler is None:
            raise RuntimeError("Scheduler not initialized. Call init() first.")
        return self._scheduler

    @property
    def api_key(self) -> str | None:
        """Get the API key for workflow execution"""
        return self._api_key

    def add_workflow_job(
        self,
        workflow_id: int,
        schedule_type: str,
        time_str: str = "09:15",
        days: list | None = None,
        execute_at: str | None = None,
        interval_value: int | None = None,
        interval_unit: str | None = None,
        func: Callable = None,
        market_hours_only: bool = False,
    ) -> str:
        """Add a workflow job to the scheduler

        Args:
            workflow_id: ID of the workflow
            schedule_type: 'once', 'daily', 'weekly', or 'interval'
            time_str: Time string in HH:MM format (for daily/weekly/once)
            days: List of days for weekly schedule (0=Mon, 6=Sun)
            execute_at: ISO datetime string for one-time execution
            interval_value: Interval value (e.g., 1, 5, 10)
            interval_unit: Interval unit ('seconds', 'minutes', 'hours')
            func: Function to execute (defaults to execute_workflow_scheduled)
        """
        job_id = f"flow_workflow_{workflow_id}"

        # Clear any previous job for this workflow. A brand-new workflow has
        # none, which remove_job treats as a normal no-op.
        self.remove_job(job_id)

        # Use default function if not provided
        if func is None:
            func = execute_workflow_scheduled

        trigger = None

        if schedule_type == "interval":
            value = interval_value or 1
            unit = interval_unit or "minutes"

            if unit == "seconds":
                trigger = IntervalTrigger(seconds=value)
            elif unit == "hours":
                trigger = IntervalTrigger(hours=value)
            else:
                trigger = IntervalTrigger(minutes=value)

            logger.info(f"Creating interval trigger: every {value} {unit}")

        elif schedule_type == "once" and execute_at:
            try:
                execute_datetime = datetime.fromisoformat(execute_at.replace("Z", "+00:00"))
                trigger = DateTrigger(run_date=execute_datetime)
                logger.info(f"Creating one-time trigger: {execute_datetime}")
            except ValueError as e:
                logger.error(f"Invalid execute_at datetime: {execute_at} - {e}")
                raise ValueError(f"Invalid datetime format: {execute_at}")

        elif schedule_type == "daily":
            try:
                hour, minute = map(int, time_str.split(":"))
                trigger = CronTrigger(hour=hour, minute=minute)
                logger.info(f"Creating daily trigger: {time_str}")
            except ValueError as e:
                logger.error(f"Invalid time format: {time_str} - {e}")
                raise ValueError(f"Invalid time format: {time_str}")

        elif schedule_type == "weekly" and days:
            try:
                hour, minute = map(int, time_str.split(":"))
                day_names = {0: "mon", 1: "tue", 2: "wed", 3: "thu", 4: "fri", 5: "sat", 6: "sun"}
                day_of_week = ",".join(day_names[d] for d in days if d in day_names)
                trigger = CronTrigger(day_of_week=day_of_week, hour=hour, minute=minute)
                logger.info(f"Creating weekly trigger: {day_of_week} at {time_str}")
            except (ValueError, KeyError) as e:
                logger.error(f"Invalid weekly schedule config: {e}")
                raise ValueError("Invalid weekly schedule configuration")

        else:
            raise ValueError(f"Invalid schedule configuration: type={schedule_type}")

        self.scheduler.add_job(
            func,
            trigger=trigger,
            id=job_id,
            # Only the default executor takes the market-hours flag. A custom
            # callback still receives the documented (workflow_id, api_key)
            # pair, which passing a third positional argument would break.
            args=(
                [workflow_id, self._api_key, market_hours_only]
                if func is execute_workflow_scheduled
                else [workflow_id, self._api_key]
            ),
            replace_existing=True,
            name=f"Workflow {workflow_id}",
        )

        logger.info(f"Added job {job_id}")
        return job_id

    def remove_job(self, job_id: str) -> bool:
        """Remove a job from the scheduler. Returns False if there was none.

        A job that does not exist is not an error for any caller: activating a
        workflow clears any prior job first (a new workflow has none), and
        deactivating may find it already gone after a restart. Logging that as
        an ERROR with a traceback made a perfectly normal activation look
        broken. A real jobstore failure is still logged with its traceback.
        """
        from apscheduler.jobstores.base import JobLookupError

        try:
            self.scheduler.remove_job(job_id)
            logger.info(f"Removed job {job_id}")
            return True
        except JobLookupError:
            logger.debug(f"No scheduler job {job_id} to remove")
            return False
        except Exception:
            logger.exception(f"Failed to remove job {job_id}")
            return False

    def remove_workflow_job(self, workflow_id: int) -> bool:
        """Remove a workflow job. A job that is already gone is not a failure."""
        job_id = f"flow_workflow_{workflow_id}"
        return self.remove_job(job_id)

    def get_job(self, job_id: str):
        """Get a job by ID"""
        return self.scheduler.get_job(job_id)

    def get_workflow_job(self, workflow_id: int):
        """Get a workflow job"""
        job_id = f"flow_workflow_{workflow_id}"
        return self.get_job(job_id)

    def get_next_run_time(self, job_id: str) -> datetime | None:
        """Get the next run time for a job"""
        job = self.get_job(job_id)
        if job:
            return job.next_run_time
        return None

    def get_all_jobs(self) -> list:
        """Get all scheduled jobs"""
        return self.scheduler.get_jobs()

    def pause_job(self, job_id: str) -> bool:
        """Pause a job"""
        try:
            self.scheduler.pause_job(job_id)
            logger.info(f"Paused job {job_id}")
            return True
        except Exception as e:
            logger.exception(f"Failed to pause job {job_id}: {e}")
            return False

    def resume_job(self, job_id: str) -> bool:
        """Resume a paused job"""
        try:
            self.scheduler.resume_job(job_id)
            logger.info(f"Resumed job {job_id}")
            return True
        except Exception as e:
            logger.exception(f"Failed to resume job {job_id}: {e}")
            return False

    def shutdown(self):
        """Shutdown the scheduler"""
        if self._scheduler:
            self._scheduler.shutdown(wait=False)
            self._initialized = False
            logger.info("Flow Scheduler shutdown")


#: Exchange whose calendar is consulted when the trigger node names none. This
#: selects a calendar, not a time - the hours themselves always come from the
#: market-calendar tables.
DEFAULT_MARKET_HOURS_EXCHANGE = "NSE"


def _parse_hhmm(value) -> int | None:
    """"HH:MM" as minutes past midnight, or None if it is not a valid time.

    Returning None rather than a fallback time matters: the caller then falls
    through to the exchange calendar instead of silently trading to a time
    nobody configured.
    """
    if value is None:
        return None
    try:
        hours, minutes = (int(part) for part in str(value).strip().split(":", 1))
    except (ValueError, TypeError):
        return None
    if not (0 <= hours <= 23 and 0 <= minutes <= 59):
        return None
    return hours * 60 + minutes


def is_within_market_hours(
    now: datetime | None = None,
    *,
    start: str | None = None,
    end: str | None = None,
    exchange: str | None = None,
) -> bool:
    """Whether ``now`` falls inside the workflow's trading window (IST).

    The editor offers a "market hours only" switch on the schedule trigger and
    defaults it on, but nothing read it, so an interval schedule kept firing
    overnight and at weekends.

    No trading time is hardcoded here. The day is resolved through
    ``get_effective_session_window``, the same calendar the rest of the
    platform uses, so weekends, trading holidays, muhurat and other special
    sessions, and per-exchange hours are all inherited rather than restated.
    That calendar knows MCX runs to 23:55 and CRYPTO never closes, which a
    fixed 09:15-15:30 window got wrong for every non-equity workflow.

    Args:
        now: IST-aware instant to test. Defaults to the current time.
        start: Optional "HH:MM" override from the workflow's trigger node.
        end: Optional "HH:MM" override from the workflow's trigger node.
        exchange: Calendar to consult. Defaults to NSE.

    Returns:
        False whenever the exchange is shut that day, regardless of any
        override - an override narrows or extends the clock, it does not
        reopen a holiday.
    """
    import pytz

    from database.market_calendar_db import get_effective_session_window

    ist = pytz.timezone("Asia/Kolkata")
    now = now or datetime.now(ist)

    exch = (exchange or DEFAULT_MARKET_HOURS_EXCHANGE).upper()
    window = get_effective_session_window(now.date(), exch)
    if window is None:
        # Shut that day: weekend, or a trading holiday for this exchange.
        return False

    start_minutes = _parse_hhmm(start)
    end_minutes = _parse_hhmm(end)

    if start_minutes is None or end_minutes is None:
        session_start = datetime.fromtimestamp(window["start_ms"] / 1000, ist)
        session_end = datetime.fromtimestamp(window["end_ms"] / 1000, ist)
        if start_minutes is None:
            start_minutes = session_start.hour * 60 + session_start.minute
        if end_minutes is None:
            end_minutes = session_end.hour * 60 + session_end.minute

    minutes = now.hour * 60 + now.minute
    return start_minutes <= minutes <= end_minutes


def get_market_hours_config(workflow) -> dict:
    """Market-hours settings from a workflow's trigger node.

    Read from the graph on every run rather than baked into the scheduler job,
    so editing the times in the flow JSON takes effect on the next run - the
    same way node edits already do - instead of needing a deactivate and
    reactivate cycle.
    """
    for node in getattr(workflow, "nodes", None) or []:
        if node.get("type") == "start":
            data = node.get("data") or {}
            return {
                "enabled": bool(data.get("marketHoursOnly", False)),
                "start": data.get("marketHoursStart") or None,
                "end": data.get("marketHoursEnd") or None,
                "exchange": data.get("marketHoursExchange") or None,
            }
    return {"enabled": False, "start": None, "end": None, "exchange": None}


def execute_workflow_scheduled(
    workflow_id: int, api_key: str = None, market_hours_only: bool = False
):
    """Execute a workflow from scheduler (synchronous)"""
    from services.flow_executor_service import execute_workflow

    logger.info(f"Scheduled execution of workflow {workflow_id}")

    if not api_key:
        logger.error(f"No API key available for workflow {workflow_id}")
        return

    # The window is read from the workflow's trigger node on every run, so
    # changing the times in the flow JSON applies from the next run. The
    # market_hours_only argument is what older jobs stored in the jobstore and
    # is honoured when the graph does not set the switch itself.
    config = {"enabled": market_hours_only, "start": None, "end": None, "exchange": None}
    try:
        from database.flow_db import get_workflow

        workflow = get_workflow(workflow_id)
        if workflow is not None:
            from_graph = get_market_hours_config(workflow)
            if from_graph["enabled"] or any(
                from_graph[k] for k in ("start", "end", "exchange")
            ):
                config = from_graph
    except Exception:
        # A lookup failure must not silently drop the gate and let a workflow
        # trade at 3am, so the stored flag stands.
        logger.exception(
            f"Could not read market-hours config for workflow {workflow_id}; "
            "using the schedule's stored setting"
        )

    if config["enabled"] and not is_within_market_hours(
        start=config["start"], end=config["end"], exchange=config["exchange"]
    ):
        logger.debug(
            f"Skipping scheduled workflow {workflow_id}: outside market hours"
        )
        return

    try:
        result = execute_workflow(workflow_id, api_key=api_key)
        logger.info(
            f"Scheduled execution result for workflow {workflow_id}: {result.get('status')}"
        )
    except Exception as e:
        logger.exception(f"Scheduled execution failed for workflow {workflow_id}: {e}")
    finally:
        # APScheduler runs this on its own worker thread with no Flask app
        # context, so teardown_appcontext never fires and the sessions this run
        # touched would stay bound to that thread.
        from utils.db_sessions import remove_all_scoped_sessions

        remove_all_scoped_sessions()


# Global scheduler instance
flow_scheduler = FlowScheduler()


def get_flow_scheduler() -> FlowScheduler:
    """Get the global flow scheduler instance"""
    return flow_scheduler


def init_flow_scheduler(db_url: str = None, api_key: str = None):
    """Initialize the flow scheduler"""
    flow_scheduler.init(db_url=db_url, api_key=api_key)
    return flow_scheduler
