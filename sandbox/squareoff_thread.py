# sandbox/squareoff_thread.py
"""
Square-Off Manager Thread

Manages the square-off manager as a separate daemon thread using APScheduler that:
- Runs scheduled jobs at configured square-off times for each exchange
- Uses IST (Asia/Kolkata) timezone for all scheduling
- Cancels pending MIS orders at square-off time
- Closes open MIS positions at square-off time
- Reads all configuration from sandbox database config
"""

import threading
import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz
from utils.logging import get_logger
from database.sandbox_db import get_config

logger = get_logger(__name__)

# Reduce APScheduler logging verbosity
# APScheduler logs every job execution at INFO level which is too noisy
# Set it to WARNING to only see errors and warnings
logging.getLogger('apscheduler.scheduler').setLevel(logging.WARNING)
logging.getLogger('apscheduler.executors.default').setLevel(logging.WARNING)

# Global scheduler instance
_scheduler = None
_scheduler_lock = threading.Lock()

# IST timezone
IST = pytz.timezone('Asia/Kolkata')


def _schedule_square_off_jobs(scheduler):
    """Schedule square-off jobs for all exchanges based on config"""
    from sandbox.squareoff_manager import SquareOffManager

    som = SquareOffManager()

    # Get configured times from database
    square_off_configs = {
        'NSE_BSE': get_config('nse_bse_square_off_time', '15:15'),
        'CDS_BCD': get_config('cds_bcd_square_off_time', '16:45'),
        'MCX': get_config('mcx_square_off_time', '23:30'),
        'NCDEX': get_config('ncdex_square_off_time', '17:00'),
    }

    logger.info("Scheduling MIS square-off jobs (IST timezone):")

    for config_name, time_str in square_off_configs.items():
        try:
            hour, minute = map(int, time_str.split(':'))

            # Create cron trigger for the specific time in IST
            trigger = CronTrigger(
                hour=hour,
                minute=minute,
                timezone=IST
            )

            # Schedule the job
            job = scheduler.add_job(
                func=som.check_and_square_off,
                trigger=trigger,
                id=f'squareoff_{config_name}',
                name=f'MIS Square-off {config_name}',
                replace_existing=True,
                misfire_grace_time=300  # Allow 5 minutes grace time
            )

            logger.info(f"  {config_name}: {time_str} IST (Job ID: {job.id})")

        except Exception as e:
            logger.error(f"Failed to schedule square-off for {config_name}: {e}")

    # Add a backup job that runs every minute to catch any missed executions
    # This provides a safety net in case:
    # - System was restarted during square-off time
    # - Primary cron job failed to execute
    # - There were timing issues or delays
    # Note: The check_and_square_off() function is smart - it only squares off
    # positions if current time is past the configured square-off time
    backup_job = scheduler.add_job(
        func=som.check_and_square_off,
        trigger='interval',
        minutes=1,
        id='squareoff_backup',
        name='MIS Square-off Backup Check',
        replace_existing=True,
        timezone=IST
    )

    logger.info(f"  Backup check: Every 1 minute (Job ID: {backup_job.id})")
    logger.debug("  Note: APScheduler logs have been set to WARNING level to reduce verbosity")

    # Schedule T+1 settlement job at midnight (00:00 IST)
    # This moves CNC positions to holdings after market close
    try:
        from sandbox.holdings_manager import process_all_t1_settlements

        settlement_trigger = CronTrigger(
            hour=0,
            minute=0,
            timezone=IST
        )

        settlement_job = scheduler.add_job(
            func=process_all_t1_settlements,
            trigger=settlement_trigger,
            id='t1_settlement',
            name='T+1 Settlement (CNC to Holdings)',
            replace_existing=True,
            misfire_grace_time=300
        )

        logger.info(f"  T+1 Settlement: 00:00 IST (Job ID: {settlement_job.id})")

    except Exception as e:
        logger.error(f"Failed to schedule T+1 settlement: {e}")

    # Schedule auto-reset job based on configured reset day and time
    # This resets all user funds to starting capital on the configured day/time
    try:
        from sandbox.fund_manager import reset_all_user_funds

        reset_day = get_config('reset_day', 'Sunday')
        reset_time_str = get_config('reset_time', '00:00')
        reset_hour, reset_minute = map(int, reset_time_str.split(':'))

        # Map day names to APScheduler day_of_week values
        day_mapping = {
            'Monday': 0, 'Tuesday': 1, 'Wednesday': 2, 'Thursday': 3,
            'Friday': 4, 'Saturday': 5, 'Sunday': 6
        }

        reset_trigger = CronTrigger(
            day_of_week=day_mapping.get(reset_day, 6),  # Default to Sunday
            hour=reset_hour,
            minute=reset_minute,
            timezone=IST
        )

        reset_job = scheduler.add_job(
            func=reset_all_user_funds,
            trigger=reset_trigger,
            id='auto_reset',
            name=f'Auto-Reset Funds ({reset_day} {reset_time_str})',
            replace_existing=True,
            misfire_grace_time=300
        )

        logger.info(f"  Auto-Reset: {reset_day} {reset_time_str} IST (Job ID: {reset_job.id})")

    except Exception as e:
        logger.error(f"Failed to schedule auto-reset: {e}")


def start_squareoff_scheduler():
    """
    Start the square-off scheduler daemon thread
    Thread-safe - only one instance will run
    """
    global _scheduler

    with _scheduler_lock:
        if _scheduler is not None and _scheduler.running:
            logger.debug("Square-off scheduler already running")
            return True, "Square-off scheduler already running"

        try:
            # Create background scheduler with IST timezone
            _scheduler = BackgroundScheduler(
                timezone=IST,
                daemon=True,
                job_defaults={
                    'coalesce': True,  # Combine missed executions
                    'max_instances': 1,  # Only one instance of each job at a time
                }
            )

            # Schedule all square-off jobs
            _schedule_square_off_jobs(_scheduler)

            # Start the scheduler
            _scheduler.start()

            logger.info("Square-off scheduler started successfully")
            return True, "Square-off scheduler started"

        except Exception as e:
            logger.error(f"Failed to start square-off scheduler: {e}")
            return False, f"Failed to start square-off scheduler: {str(e)}"


def stop_squareoff_scheduler():
    """
    Stop the square-off scheduler gracefully
    """
    global _scheduler

    with _scheduler_lock:
        if _scheduler is None or not _scheduler.running:
            logger.debug("Square-off scheduler not running")
            return True, "Square-off scheduler not running"

        try:
            logger.info("Stopping square-off scheduler...")
            _scheduler.shutdown(wait=True)
            _scheduler = None
            logger.info("Square-off scheduler stopped successfully")
            return True, "Square-off scheduler stopped"

        except Exception as e:
            logger.error(f"Error stopping square-off scheduler: {e}")
            return False, f"Error stopping square-off scheduler: {str(e)}"


def is_squareoff_scheduler_running():
    """Check if square-off scheduler is running"""
    global _scheduler
    return _scheduler is not None and _scheduler.running


def get_squareoff_scheduler_status():
    """Get status information about the square-off scheduler"""
    global _scheduler

    if _scheduler is None or not _scheduler.running:
        return {
            'running': False,
            'jobs': []
        }

    jobs_info = []
    for job in _scheduler.get_jobs():
        next_run = job.next_run_time
        jobs_info.append({
            'id': job.id,
            'name': job.name,
            'next_run': next_run.strftime('%Y-%m-%d %H:%M:%S %Z') if next_run else 'N/A'
        })

    return {
        'running': True,
        'timezone': str(IST),
        'jobs': jobs_info
    }


def reload_squareoff_schedule():
    """
    Reload square-off schedule from config
    Useful when config is updated
    """
    global _scheduler

    if _scheduler is None or not _scheduler.running:
        logger.warning("Cannot reload schedule - scheduler not running")
        return False, "Scheduler not running"

    try:
        logger.info("Reloading square-off schedule from config...")

        # Remove all existing jobs
        _scheduler.remove_all_jobs()

        # Re-schedule jobs with new config
        _schedule_square_off_jobs(_scheduler)

        logger.info("Square-off schedule reloaded successfully")
        return True, "Schedule reloaded"

    except Exception as e:
        logger.error(f"Error reloading schedule: {e}")
        return False, f"Error reloading schedule: {str(e)}"
