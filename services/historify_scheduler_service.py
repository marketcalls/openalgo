# services/historify_scheduler_service.py
"""
Historify Scheduler Service
Handles scheduled historical data downloads using APScheduler (Flask/sync version)
"""

import os
import threading
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from utils.logging import get_logger

logger = get_logger(__name__)


class HistorifyScheduler:
    """Singleton scheduler for Historify data downloads"""

    _instance: Optional["HistorifyScheduler"] = None
    _scheduler: BackgroundScheduler | None = None
    _lock = threading.Lock()
    _initialized = False
    _api_key: str | None = None
    _socketio = None

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def init(self, db_url: str = None, api_key: str = None, socketio=None):
        """Initialize the scheduler with database URL for job persistence"""
        if self._initialized:
            return

        with self._lock:
            if self._initialized:
                return

            if db_url is None:
                db_url = os.getenv("DATABASE_URL", "sqlite:///db/openalgo.db")

            self._api_key = api_key
            self._socketio = socketio

            try:
                jobstores = {
                    "default": SQLAlchemyJobStore(
                        url=db_url, tablename="historify_apscheduler_jobs"
                    )
                }
                self._scheduler = BackgroundScheduler(
                    jobstores=jobstores,
                    job_defaults={
                        "coalesce": True,
                        "max_instances": 1,
                        "misfire_grace_time": 300,  # 5 minutes grace for missed jobs
                    },
                )
                self._scheduler.start()
                self._initialized = True
                logger.debug("Historify Scheduler initialized and started")

                # Restore schedules from database on startup
                self._restore_schedules()

            except Exception as e:
                logger.exception(f"Failed to initialize Historify Scheduler: {e}")
                raise

    def set_api_key(self, api_key: str):
        """Set API key for data downloads"""
        self._api_key = api_key

    def set_socketio(self, socketio):
        """Set Socket.IO instance for real-time updates"""
        self._socketio = socketio

    @property
    def scheduler(self) -> BackgroundScheduler:
        """Get the scheduler instance"""
        if self._scheduler is None:
            raise RuntimeError("Scheduler not initialized. Call init() first.")
        return self._scheduler

    @property
    def api_key(self) -> str | None:
        """Get the API key for data downloads"""
        return self._api_key

    @property
    def socketio(self):
        """Get the Socket.IO instance"""
        return self._socketio

    def _restore_schedules(self):
        """Restore active schedules from database on startup"""
        try:
            from database.historify_db import get_active_schedules

            active_schedules = get_active_schedules()
            restored_count = 0

            for schedule in active_schedules:
                try:
                    # Check if job already exists in APScheduler
                    job_id = f"historify_schedule_{schedule['id']}"
                    existing_job = self.scheduler.get_job(job_id)

                    if existing_job is None:
                        # Re-add the job to APScheduler
                        self._add_schedule_job(schedule)
                        restored_count += 1
                        logger.debug(f"Restored schedule: {schedule['name']}")

                except Exception as e:
                    logger.warning(f"Failed to restore schedule {schedule['id']}: {e}")

            if restored_count > 0:
                logger.info(f"Restored {restored_count} Historify schedules")

        except Exception as e:
            logger.exception(f"Error restoring schedules: {e}")

    def _add_schedule_job(self, schedule: dict[str, Any]) -> str | None:
        """Add a schedule to APScheduler based on its configuration"""
        job_id = f"historify_schedule_{schedule['id']}"

        try:
            # Remove existing job if any
            self.remove_job(job_id)

            trigger = None
            schedule_type = schedule.get("schedule_type")

            if schedule_type == "interval":
                value = schedule.get("interval_value", 1)
                unit = schedule.get("interval_unit", "minutes")

                if unit == "hours":
                    trigger = IntervalTrigger(hours=value)
                else:  # minutes
                    trigger = IntervalTrigger(minutes=value)

                logger.debug(f"Creating interval trigger: every {value} {unit}")

            elif schedule_type == "daily":
                time_str = schedule.get("time_of_day", "09:15")
                try:
                    hour, minute = map(int, time_str.split(":"))
                    # Use IST timezone explicitly for Indian markets
                    trigger = CronTrigger(hour=hour, minute=minute, timezone="Asia/Kolkata")
                    logger.debug(f"Creating daily trigger at {time_str} IST")
                except ValueError as e:
                    logger.error(f"Invalid time format: {time_str} - {e}")
                    return None

            else:
                logger.error(f"Invalid schedule type: {schedule_type}")
                return None

            # Add job to scheduler
            # Note: API key is retrieved dynamically at execution time
            self.scheduler.add_job(
                execute_schedule,
                trigger=trigger,
                id=job_id,
                args=[schedule["id"]],
                replace_existing=True,
                name=f"Historify: {schedule['name']}",
            )

            # Update next_run_at in database
            job = self.scheduler.get_job(job_id)
            if job and job.next_run_time:
                from database.historify_db import update_schedule

                update_schedule(
                    schedule["id"], next_run_at=job.next_run_time, apscheduler_job_id=job_id
                )

            logger.info(f"Added schedule job: {job_id}")
            return job_id

        except Exception as e:
            logger.exception(f"Error adding schedule job: {e}")
            return None

    def add_schedule(
        self,
        schedule_id: str,
        name: str,
        schedule_type: str,
        data_interval: str,
        interval_value: int | None = None,
        interval_unit: str | None = None,
        time_of_day: str | None = None,
        lookback_days: int = 1,
        description: str | None = None,
    ) -> tuple[bool, str]:
        """
        Create a new schedule and add it to APScheduler.

        Args:
            schedule_id: Unique identifier for the schedule
            name: Human-readable schedule name
            schedule_type: 'interval' or 'daily'
            data_interval: Data timeframe to download ('1m' or 'D')
            interval_value: Numeric value for interval schedules
            interval_unit: Unit for interval schedules ('minutes' or 'hours')
            time_of_day: Time for daily schedules ('HH:MM')
            lookback_days: Number of days to look back
            description: Optional description

        Returns:
            Tuple of (success, message)
        """
        from database.historify_db import create_schedule, get_schedule

        try:
            # Create in database (always uses watchlist as download source)
            success, msg = create_schedule(
                schedule_id=schedule_id,
                name=name,
                schedule_type=schedule_type,
                data_interval=data_interval,
                interval_value=interval_value,
                interval_unit=interval_unit,
                time_of_day=time_of_day,
                download_source="watchlist",
                lookback_days=lookback_days,
                description=description,
            )

            if not success:
                return False, msg

            # Get the full schedule record
            schedule = get_schedule(schedule_id)
            if not schedule:
                return False, "Failed to retrieve created schedule"

            # Add to APScheduler
            job_id = self._add_schedule_job(schedule)
            if not job_id:
                return False, "Failed to add schedule to scheduler"

            # Emit Socket.IO event
            self._emit_schedule_event("historify_schedule_created", schedule_id)

            return True, f"Schedule '{name}' created successfully"

        except Exception as e:
            logger.exception(f"Error adding schedule: {e}")
            return False, str(e)

    def update_schedule(self, schedule_id: str, **kwargs) -> tuple[bool, str]:
        """Update a schedule and refresh APScheduler job if needed"""
        from database.historify_db import get_schedule
        from database.historify_db import update_schedule as db_update_schedule

        try:
            # Update in database
            success, msg = db_update_schedule(schedule_id, **kwargs)
            if not success:
                return False, msg

            # Get updated schedule
            schedule = get_schedule(schedule_id)
            if not schedule:
                return False, "Schedule not found"

            # Re-add to APScheduler if schedule config changed
            config_fields = {"schedule_type", "interval_value", "interval_unit", "time_of_day"}
            if any(k in kwargs for k in config_fields):
                job_id = self._add_schedule_job(schedule)
                if not job_id:
                    return False, "Failed to update scheduler job"

            # Emit Socket.IO event
            self._emit_schedule_event("historify_schedule_updated", schedule_id)

            return True, "Schedule updated successfully"

        except Exception as e:
            logger.exception(f"Error updating schedule: {e}")
            return False, str(e)

    def delete_schedule(self, schedule_id: str) -> tuple[bool, str]:
        """Delete a schedule and remove from APScheduler"""
        from database.historify_db import delete_schedule as db_delete_schedule

        try:
            job_id = f"historify_schedule_{schedule_id}"

            # Remove from APScheduler
            self.remove_job(job_id)

            # Delete from database
            success, msg = db_delete_schedule(schedule_id)
            if not success:
                return False, msg

            # Emit Socket.IO event
            self._emit_schedule_event("historify_schedule_deleted", schedule_id)

            return True, "Schedule deleted successfully"

        except Exception as e:
            logger.exception(f"Error deleting schedule: {e}")
            return False, str(e)

    def enable_schedule(self, schedule_id: str) -> tuple[bool, str]:
        """Enable a schedule"""
        from database.historify_db import get_schedule
        from database.historify_db import update_schedule as db_update_schedule

        try:
            success, msg = db_update_schedule(schedule_id, is_enabled=True)
            if not success:
                return False, msg

            # Get schedule and add to APScheduler
            schedule = get_schedule(schedule_id)
            if schedule and not schedule.get("is_paused", False):
                self._add_schedule_job(schedule)

            self._emit_schedule_event("historify_schedule_updated", schedule_id)
            return True, "Schedule enabled"

        except Exception as e:
            logger.exception(f"Error enabling schedule: {e}")
            return False, str(e)

    def disable_schedule(self, schedule_id: str) -> tuple[bool, str]:
        """Disable a schedule"""
        from database.historify_db import update_schedule as db_update_schedule

        try:
            job_id = f"historify_schedule_{schedule_id}"
            self.remove_job(job_id)

            success, msg = db_update_schedule(schedule_id, is_enabled=False)
            if not success:
                return False, msg

            self._emit_schedule_event("historify_schedule_updated", schedule_id)
            return True, "Schedule disabled"

        except Exception as e:
            logger.exception(f"Error disabling schedule: {e}")
            return False, str(e)

    def pause_schedule(self, schedule_id: str) -> tuple[bool, str]:
        """Pause a schedule"""
        from database.historify_db import update_schedule as db_update_schedule

        try:
            job_id = f"historify_schedule_{schedule_id}"
            self.pause_job(job_id)

            success, msg = db_update_schedule(schedule_id, is_paused=True)
            if not success:
                return False, msg

            self._emit_schedule_event("historify_schedule_updated", schedule_id)
            return True, "Schedule paused"

        except Exception as e:
            logger.exception(f"Error pausing schedule: {e}")
            return False, str(e)

    def resume_schedule(self, schedule_id: str) -> tuple[bool, str]:
        """Resume a paused schedule"""
        from database.historify_db import get_schedule
        from database.historify_db import update_schedule as db_update_schedule

        try:
            job_id = f"historify_schedule_{schedule_id}"

            # Check if job exists
            job = self.scheduler.get_job(job_id)
            if job:
                self.resume_job(job_id)
            else:
                # Re-add the job
                schedule = get_schedule(schedule_id)
                if schedule:
                    self._add_schedule_job(schedule)

            success, msg = db_update_schedule(schedule_id, is_paused=False)
            if not success:
                return False, msg

            self._emit_schedule_event("historify_schedule_updated", schedule_id)
            return True, "Schedule resumed"

        except Exception as e:
            logger.exception(f"Error resuming schedule: {e}")
            return False, str(e)

    def trigger_schedule(self, schedule_id: str) -> tuple[bool, str]:
        """Manually trigger a schedule execution"""
        try:
            from database.historify_db import get_schedule

            schedule = get_schedule(schedule_id)
            if not schedule:
                return False, "Schedule not found"

            # Execute immediately in background thread
            # API key is retrieved dynamically at execution time
            import threading

            thread = threading.Thread(target=execute_schedule, args=(schedule_id,), daemon=True)
            thread.start()

            return True, "Schedule triggered"

        except Exception as e:
            logger.exception(f"Error triggering schedule: {e}")
            return False, str(e)

    def remove_job(self, job_id: str) -> bool:
        """Remove a job from the scheduler"""
        try:
            self.scheduler.remove_job(job_id)
            logger.debug(f"Removed job {job_id}")
            return True
        except Exception:
            return False

    def get_job(self, job_id: str):
        """Get a job by ID"""
        return self.scheduler.get_job(job_id)

    def get_next_run_time(self, schedule_id: str) -> datetime | None:
        """Get the next run time for a schedule"""
        job_id = f"historify_schedule_{schedule_id}"
        job = self.get_job(job_id)
        if job:
            return job.next_run_time
        return None

    def pause_job(self, job_id: str) -> bool:
        """Pause a job"""
        try:
            self.scheduler.pause_job(job_id)
            logger.debug(f"Paused job {job_id}")
            return True
        except Exception:
            return False

    def resume_job(self, job_id: str) -> bool:
        """Resume a paused job"""
        try:
            self.scheduler.resume_job(job_id)
            logger.debug(f"Resumed job {job_id}")
            return True
        except Exception:
            return False

    def _emit_schedule_event(self, event: str, schedule_id: str, data: dict = None):
        """Emit a Socket.IO event for schedule updates"""
        if self._socketio:
            try:
                payload = {"schedule_id": schedule_id}
                if data:
                    payload.update(data)
                self._socketio.emit(event, payload)
            except Exception as e:
                logger.warning(f"Failed to emit {event}: {e}")

    def shutdown(self):
        """Shutdown the scheduler"""
        if self._scheduler:
            self._scheduler.shutdown(wait=False)
            self._initialized = False
            logger.info("Historify Scheduler shutdown")


def execute_schedule(schedule_id: str, api_key: str = None):
    """Execute a scheduled download (called by APScheduler)"""
    from datetime import datetime

    from database.auth_db import get_first_available_api_key
    from database.historify_db import (
        create_schedule_execution,
        get_schedule,
        get_watchlist,
        increment_schedule_run_counts,
        update_schedule,
        update_schedule_execution,
    )
    from services.historify_service import create_and_start_job

    logger.info(f"Executing scheduled download: {schedule_id}")

    execution_id = None

    try:
        # Get schedule configuration
        schedule = get_schedule(schedule_id)
        if not schedule:
            logger.error(f"Schedule not found: {schedule_id}")
            return

        if not schedule.get("is_enabled", False) or schedule.get("is_paused", False):
            logger.info(f"Schedule {schedule_id} is disabled or paused, skipping")
            return

        # Update status to running
        update_schedule(schedule_id, status="running")

        # Get API key - prefer from parameter, then scheduler instance, then database
        effective_api_key = api_key
        if not effective_api_key:
            scheduler = get_historify_scheduler()
            effective_api_key = scheduler.api_key

        # If still no API key, get from database (for background service)
        if not effective_api_key:
            effective_api_key = get_first_available_api_key()

        if not effective_api_key:
            logger.error(
                f"No API key available for schedule {schedule_id}. Please generate an API key first."
            )
            update_schedule(schedule_id, status="idle", last_run_status="no_api_key")
            return

        # Get symbols from watchlist (scheduler only supports watchlist)
        watchlist = get_watchlist()
        symbols = [{"symbol": item["symbol"], "exchange": item["exchange"]} for item in watchlist]

        if not symbols:
            logger.warning(f"No symbols found for schedule {schedule_id}")
            update_schedule(schedule_id, status="idle", last_run_status="no_symbols")
            return

        # Calculate date range
        lookback_days = schedule.get("lookback_days", 1)
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

        # Create execution record
        execution_id = create_schedule_execution(schedule_id)

        # Create and start the download job (always incremental for scheduled downloads)
        success, response, status_code = create_and_start_job(
            job_type="scheduled",
            symbols=symbols,
            interval=schedule.get("data_interval", "D"),
            start_date=start_date,
            end_date=end_date,
            api_key=effective_api_key,
            config={"schedule_id": schedule_id},
            incremental=True,
        )

        if success:
            job_id = response.get("job_id")
            if execution_id:
                update_schedule_execution(
                    execution_id, download_job_id=job_id, symbols_processed=len(symbols)
                )
            update_schedule(schedule_id, status="idle", last_run_status="success")
            increment_schedule_run_counts(schedule_id, is_success=True)
            logger.info(f"Scheduled download started: {job_id} ({len(symbols)} symbols)")

            # Emit Socket.IO event
            scheduler = get_historify_scheduler()
            if scheduler.socketio:
                scheduler.socketio.emit(
                    "historify_schedule_execution_started",
                    {"schedule_id": schedule_id, "execution_id": execution_id, "job_id": job_id},
                )

        else:
            error_msg = response.get("message", "Unknown error")
            if execution_id:
                update_schedule_execution(
                    execution_id,
                    status="failed",
                    completed_at=datetime.now(),
                    error_message=error_msg,
                )
            update_schedule(schedule_id, status="idle", last_run_status="failed")
            increment_schedule_run_counts(schedule_id, is_success=False)
            logger.error(f"Scheduled download failed: {error_msg}")

    except Exception as e:
        logger.exception(f"Error executing schedule {schedule_id}: {e}")
        if execution_id:
            update_schedule_execution(
                execution_id, status="failed", completed_at=datetime.now(), error_message=str(e)
            )
        update_schedule(schedule_id, status="idle", last_run_status="error")
        increment_schedule_run_counts(schedule_id, is_success=False)


# Global scheduler instance
historify_scheduler = HistorifyScheduler()


def get_historify_scheduler() -> HistorifyScheduler:
    """Get the global historify scheduler instance"""
    return historify_scheduler


def init_historify_scheduler(db_url: str = None, api_key: str = None, socketio=None):
    """Initialize the historify scheduler"""
    historify_scheduler.init(db_url=db_url, api_key=api_key, socketio=socketio)
    return historify_scheduler
