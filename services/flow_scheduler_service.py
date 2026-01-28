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

        # Remove existing job if any
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
            args=[workflow_id, self._api_key],
            replace_existing=True,
            name=f"Workflow {workflow_id}",
        )

        logger.info(f"Added job {job_id}")
        return job_id

    def remove_job(self, job_id: str) -> bool:
        """Remove a job from the scheduler"""
        try:
            self.scheduler.remove_job(job_id)
            logger.info(f"Removed job {job_id}")
            return True
        except Exception:
            return False

    def remove_workflow_job(self, workflow_id: int) -> bool:
        """Remove a workflow job"""
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
        except Exception:
            return False

    def resume_job(self, job_id: str) -> bool:
        """Resume a paused job"""
        try:
            self.scheduler.resume_job(job_id)
            logger.info(f"Resumed job {job_id}")
            return True
        except Exception:
            return False

    def shutdown(self):
        """Shutdown the scheduler"""
        if self._scheduler:
            self._scheduler.shutdown(wait=False)
            self._initialized = False
            logger.info("Flow Scheduler shutdown")


def execute_workflow_scheduled(workflow_id: int, api_key: str = None):
    """Execute a workflow from scheduler (synchronous)"""
    from services.flow_executor_service import execute_workflow

    logger.info(f"Scheduled execution of workflow {workflow_id}")

    if not api_key:
        logger.error(f"No API key available for workflow {workflow_id}")
        return

    try:
        result = execute_workflow(workflow_id, api_key=api_key)
        logger.info(
            f"Scheduled execution result for workflow {workflow_id}: {result.get('status')}"
        )
    except Exception as e:
        logger.exception(f"Scheduled execution failed for workflow {workflow_id}: {e}")


# Global scheduler instance
flow_scheduler = FlowScheduler()


def get_flow_scheduler() -> FlowScheduler:
    """Get the global flow scheduler instance"""
    return flow_scheduler


def init_flow_scheduler(db_url: str = None, api_key: str = None):
    """Initialize the flow scheduler"""
    flow_scheduler.init(db_url=db_url, api_key=api_key)
    return flow_scheduler
