"""Squareoff scheduler — auto-flatten intraday strategies at the configured
exit time on weekdays.

One APScheduler cron job per active intraday strategy at
strategy.squareoff_time IST (Mon-Fri). When the job fires:
  1. Look up the active run for the strategy (state ∈ ACTIVE_RUN_STATES)
  2. If found and IN_TRADE, call exit_service.exit_strategy(reason='squareoff')
  3. Otherwise no-op (engine handled it via leg-level rules already, or
     strategy was disabled before exit time)

Lifecycle:
  - schedule_strategy(strategy_id) — called when a strategy is enabled
                                       (POST /toggle, or on app startup for
                                       already-active strategies)
  - unschedule_strategy(strategy_id) — called when a strategy is disabled
                                         or deleted
  - rehydrate_all() — at app startup, walks strategies_v2 WHERE is_active=1
                       AND is_intraday=1 AND squareoff_time IS NOT NULL,
                       and re-creates the cron jobs.

Singleton scheduler — uses BackgroundScheduler (NOT AsyncIOScheduler) to
match the eventlet+gunicorn production model. Jobs run in the scheduler's
own thread pool.
"""

from __future__ import annotations

import threading
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from utils.logging import get_logger

logger = get_logger(__name__)


_IST_TZ = "Asia/Kolkata"
_JOB_PREFIX = "strategy_v2_squareoff_"


class _SquareoffScheduler:
    """Module-level singleton — see module docstring."""

    _scheduler: Optional[BackgroundScheduler] = None
    _lock = threading.Lock()
    _started = False

    def start(self) -> None:
        """Lazy-create the BackgroundScheduler. Called automatically on first
        schedule_strategy / rehydrate_all use."""
        with self._lock:
            if self._started:
                return
            self._scheduler = BackgroundScheduler(timezone=_IST_TZ)
            self._scheduler.start()
            self._started = True
            logger.info("squareoff_scheduler: started (tz=%s)", _IST_TZ)

    def shutdown(self) -> None:
        """For test teardown / clean shutdown."""
        with self._lock:
            if not self._started or self._scheduler is None:
                return
            self._scheduler.shutdown(wait=False)
            self._scheduler = None
            self._started = False

    def _job_id(self, strategy_id: int) -> str:
        return f"{_JOB_PREFIX}{strategy_id}"

    def schedule_strategy(self, strategy_id: int) -> bool:
        """Schedule (or reschedule) the squareoff job for a strategy.

        Reads strategies_v2 for the current squareoff_time and is_intraday +
        is_active flags. If the strategy isn't eligible (positional / no
        squareoff_time / disabled), removes any existing job and returns False.
        """
        # Lazy import — avoids circular load via subscribers.
        from database.strategy_v2_db import StrategyV2, db_session

        self.start()

        try:
            strategy = (
                db_session.query(StrategyV2)
                .filter(StrategyV2.id == strategy_id)
                .first()
            )
            if strategy is None:
                self.unschedule_strategy(strategy_id)
                return False
            if not strategy.is_active or not strategy.is_intraday or not strategy.squareoff_time:
                self.unschedule_strategy(strategy_id)
                return False

            squareoff_time = strategy.squareoff_time.strip()
            if ":" not in squareoff_time:
                logger.warning(
                    "squareoff_scheduler: bad squareoff_time %r on strategy_id=%s",
                    squareoff_time, strategy_id,
                )
                return False

            try:
                hh, mm = squareoff_time.split(":")
                hour = int(hh)
                minute = int(mm)
            except ValueError:
                logger.warning(
                    "squareoff_scheduler: cannot parse squareoff_time %r",
                    squareoff_time,
                )
                return False

            trigger = CronTrigger(
                day_of_week="mon-fri",
                hour=hour,
                minute=minute,
                timezone=_IST_TZ,
            )

            assert self._scheduler is not None
            self._scheduler.add_job(
                func=_run_squareoff,
                trigger=trigger,
                id=self._job_id(strategy_id),
                args=[strategy_id],
                replace_existing=True,
                misfire_grace_time=60,  # tolerate up to 60s of clock drift
            )
            logger.info(
                "squareoff_scheduler: scheduled strategy_id=%s @ %02d:%02d IST Mon-Fri",
                strategy_id, hour, minute,
            )
            return True
        finally:
            db_session.remove()

    def unschedule_strategy(self, strategy_id: int) -> None:
        """Remove the cron job for a strategy. Idempotent — if no job
        exists, no-op."""
        if not self._started or self._scheduler is None:
            return
        try:
            self._scheduler.remove_job(self._job_id(strategy_id))
            logger.info(
                "squareoff_scheduler: unscheduled strategy_id=%s", strategy_id,
            )
        except Exception:
            # Job didn't exist — fine.
            pass

    def rehydrate_all(self) -> int:
        """Rebuild jobs for every eligible strategy. Called at app startup.
        Returns the count of jobs scheduled."""
        from database.strategy_v2_db import StrategyV2, db_session

        self.start()

        try:
            strategies = (
                db_session.query(StrategyV2)
                .filter(
                    StrategyV2.is_active == True,  # noqa: E712
                    StrategyV2.is_intraday == True,  # noqa: E712
                    StrategyV2.squareoff_time.isnot(None),
                )
                .all()
            )
            count = 0
            for s in strategies:
                if self.schedule_strategy(s.id):
                    count += 1
            logger.info("squareoff_scheduler: rehydrated %s job(s)", count)
            return count
        finally:
            db_session.remove()


# Module-level singleton.
_scheduler = _SquareoffScheduler()


# ---------------------------------------------------------------------------
# Job body — what fires at squareoff_time IST
# ---------------------------------------------------------------------------


def _run_squareoff(strategy_id: int) -> None:
    """Fire-and-forget job body. Looks up the active run for the strategy
    and calls exit_service.exit_strategy."""
    # Lazy imports — avoid eager circular load on app boot before scheduler
    # ever fires.
    from database.strategy_v2_db import StrategyRun, db_session
    from services.strategy.exit_service import exit_strategy
    from services.strategy.state_machine import ACTIVE_RUN_STATES

    try:
        run = (
            db_session.query(StrategyRun)
            .filter(
                StrategyRun.strategy_id == strategy_id,
                StrategyRun.state.in_(ACTIVE_RUN_STATES),
            )
            .order_by(StrategyRun.id.desc())
            .first()
        )
        if run is None:
            logger.info(
                "squareoff_scheduler: no active run for strategy_id=%s — skipping",
                strategy_id,
            )
            return
        if run.state != "IN_TRADE":
            logger.info(
                "squareoff_scheduler: run %s in state %s, not IN_TRADE — skipping",
                run.id, run.state,
            )
            return
        exit_strategy(run_id=run.id, reason="squareoff")
    except Exception:
        logger.exception(
            "squareoff_scheduler: squareoff job failed for strategy_id=%s",
            strategy_id,
        )
    finally:
        db_session.remove()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def schedule_strategy(strategy_id: int) -> bool:
    return _scheduler.schedule_strategy(strategy_id)


def unschedule_strategy(strategy_id: int) -> None:
    _scheduler.unschedule_strategy(strategy_id)


def rehydrate_all() -> int:
    return _scheduler.rehydrate_all()


def shutdown() -> None:
    _scheduler.shutdown()


def get_scheduler() -> _SquareoffScheduler:
    """Test helper — exposes the singleton."""
    return _scheduler
