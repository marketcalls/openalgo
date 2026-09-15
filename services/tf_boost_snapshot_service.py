# services/tf_boost_snapshot_service.py
"""
TF Boost Snapshot Scheduler — fully isolated APScheduler instance, in-memory
jobstore only. Does not touch flow_scheduler / historify_scheduler infra or
openalgo.db. Opt-in only (see TF_BOOST_SNAPSHOT_ENABLED gate in app.py).

Every 5 minutes during 09:15-15:30 IST on weekdays, snapshots TradeFinder's
three market_pulse ranked lists, plus the sector rfactor index (as list_type
"sector_index", same table), into db/tf_boost_snapshots.duckdb for later
backtest replay.
"""

from __future__ import annotations
import threading
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from database.tf_boost_db import get_connection, init_tf_boost_database
from services.tradefinder_service import fetch_market_pulse, fetch_sector_scope
from utils.logging import get_logger

logger = get_logger(__name__)

IST = ZoneInfo("Asia/Kolkata")
TF_SNAPSHOT_JOB_ID = "tf_boost_snapshot_tick"

_scheduler: Optional[BackgroundScheduler] = None
_lock = threading.Lock()


def _within_market_window(now_ist: datetime) -> bool:
    start = now_ist.replace(hour=9, minute=15, second=0, microsecond=0)
    end = now_ist.replace(hour=15, minute=30, second=0, microsecond=0)
    return start <= now_ist <= end


def _run_snapshot_tick():
    """APScheduler job callable — must never raise, or crash the scheduler
    thread. The CronTrigger already narrows to hours 9-15 (mon-fri); this
    in-job guard enforces the exact 09:15-15:30 IST boundary."""
    now_ist = datetime.now(IST)
    if not _within_market_window(now_ist):
        logger.debug(f"tf_boost_snapshot: {now_ist.time()} outside 09:15-15:30 IST, skipping")
        return

    # Align to the 5-min tick, naive IST (matches isi_v56_live_strategy.py's
    # own naive-IST convention), so replay joins line up predictably.
    aligned_minute = (now_ist.minute // 5) * 5
    snapshot_time = now_ist.replace(minute=aligned_minute, second=0, microsecond=0, tzinfo=None)
    snapshot_date = snapshot_time.date()

    try:
        result = fetch_market_pulse()
    except Exception as e:
        logger.warning(f"tf_boost_snapshot: unexpected fetch error: {e}")
        result = None

    if result is None:
        logger.warning("tf_boost_snapshot: market_pulse fetch failed / JWT expired, skipping boost lists")
    else:
        total_inserted = 0
        try:
            with get_connection() as conn:
                for list_type, items in result.items():
                    if not items:
                        # Was permanently empty for breakout_beacon due to a parsing
                        # bug (tradefinder_service._map_items dropped every item
                        # whose param_2 wasn't numeric — fixed 2026-07-29). Genuinely
                        # possible for any list to be empty on a given tick though,
                        # so this stays a plain skip-and-log rather than a warning.
                        logger.debug(f"tf_boost_snapshot: {list_type} empty @ {snapshot_time}, skipping")
                        continue
                    for rank, item in enumerate(items, start=1):
                        conn.execute(
                            """
                            INSERT INTO tf_boost_snapshots
                                (snapshot_date, snapshot_time, list_type, rank, symbol,
                                 ltp, prev_close, change_pct, score)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                            ON CONFLICT (snapshot_time, list_type, symbol) DO NOTHING
                            """,
                            [snapshot_date, snapshot_time, list_type, rank, item["symbol"],
                             item["ltp"], item["prev_close"], item["change_pct"], item["score"]],
                        )
                        total_inserted += 1
            logger.info(f"tf_boost_snapshot: stored @ {snapshot_time} ({total_inserted} rows across 3 lists)")
        except Exception as e:
            logger.warning(f"tf_boost_snapshot: DB write failed for boost lists: {e}")

    # Sector index gets the same treatment, stored as list_type "sector_index"
    # in the same table -- TF hands back only a score (param_3/rfactor), not an
    # explicit rank, so it's assigned here the same way _map_items ranks the
    # boost lists: sorted by score, descending. Independent try/except from the
    # block above so one feed failing never blocks the other.
    try:
        sector_result = fetch_sector_scope()
    except Exception as e:
        logger.warning(f"tf_boost_snapshot: unexpected sector fetch error: {e}")
        sector_result = None

    if sector_result is None:
        logger.warning("tf_boost_snapshot: sector_scope fetch failed / JWT expired, skipping sector index")
        return

    index_items = [
        {"symbol": it.get("Symbol"), "score": it.get("param_3")}
        for it in (sector_result.get("index") or [])
        if it.get("Symbol") is not None
    ]
    if not index_items:
        logger.debug(f"tf_boost_snapshot: sector index empty @ {snapshot_time}, skipping")
        return
    index_items.sort(key=lambda x: (x["score"] is None, x["score"]), reverse=True)

    try:
        with get_connection() as conn:
            for rank, item in enumerate(index_items, start=1):
                conn.execute(
                    """
                    INSERT INTO tf_boost_snapshots
                        (snapshot_date, snapshot_time, list_type, rank, symbol,
                         ltp, prev_close, change_pct, score)
                    VALUES (?, ?, 'sector_index', ?, ?, NULL, NULL, NULL, ?)
                    ON CONFLICT (snapshot_time, list_type, symbol) DO NOTHING
                    """,
                    [snapshot_date, snapshot_time, rank, item["symbol"], item["score"]],
                )
        logger.info(f"tf_boost_snapshot: stored sector index @ {snapshot_time} ({len(index_items)} sectors)")
    except Exception as e:
        logger.warning(f"tf_boost_snapshot: DB write failed for sector index: {e}")


def init_tf_boost_snapshot():
    """Idempotent init: creates the isolated DB, starts a dedicated in-memory
    BackgroundScheduler. Safe to call once at app startup; opt-in only."""
    global _scheduler
    with _lock:
        if _scheduler is not None:
            logger.debug("tf_boost_snapshot: already initialized, skipping")
            return

        init_tf_boost_database()

        _scheduler = BackgroundScheduler(timezone=IST)
        _scheduler.add_job(
            _run_snapshot_tick,
            trigger=CronTrigger(day_of_week="mon-fri", hour="9-15", minute="*/5", timezone=IST),
            id=TF_SNAPSHOT_JOB_ID,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=60,
        )
        _scheduler.start()
        logger.info("TF Boost snapshot scheduler started (isolated, in-memory jobstore, "
                    "*/5 9-15 mon-fri Asia/Kolkata, 09:15-15:30 in-job guard)")
