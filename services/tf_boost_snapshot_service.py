# services/tf_boost_snapshot_service.py
"""
TF Boost Snapshot Scheduler — fully isolated APScheduler instance, in-memory
jobstore only. Does not touch flow_scheduler / historify_scheduler infra or
openalgo.db. Opt-in only (see TF_BOOST_SNAPSHOT_ENABLED gate in app.py).

Every minute during 09:15-15:30 IST on weekdays, snapshots TradeFinder's
three market_pulse ranked lists, plus the sector rfactor index (as list_type
"sector_index", same table), into db/tf_boost_snapshots.duckdb for later
backtest replay.

Why every minute rather than every five: the interesting thing a ranked list
does is the transition, and five minutes is wide enough to hide one whole.
Measured on 16-Sep-2026, PATANJALI was rank 62 at 09:15 and rank 1 at 10:15
with nothing in between, so the hour in which it became the day's strongest
stock is simply not in the record. A study cannot find an entry inside a gap.

The intraday_boost rows also carry the enrichments the live /tfmarketpulse
endpoint computes and discards - Kaufman steadiness, CPR width and bias, the
first candle's range. They cost nothing extra here (the caches are shared with
the live endpoint and self-throttle) and without them there is no way to ask
whether a straight-line climber behaves differently from a chopper.
"""

from __future__ import annotations

import threading
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from database.tf_boost_db import get_connection, init_tf_boost_database, record_heartbeat
from services.tradefinder_service import fetch_market_pulse, fetch_sector_scope
from utils.logging import get_logger

logger = get_logger(__name__)

IST = ZoneInfo("Asia/Kolkata")
TF_SNAPSHOT_JOB_ID = "tf_boost_snapshot_tick"

_scheduler: BackgroundScheduler | None = None
_lock = threading.Lock()


def _within_market_window(now_ist: datetime) -> bool:
    """09:15 to 15:30 IST inclusive, judged on the MINUTE.

    The cron fires at 15:30:00 but APScheduler dispatches a fraction later, so
    an end of exactly 15:30:00.000000 rejected the tick every single day: the
    closing minute -- the day's final ranked list -- was never recorded. Both
    days in the store ended at 15:29 before this.
    """
    start = now_ist.replace(hour=9, minute=15, second=0, microsecond=0)
    end = now_ist.replace(hour=15, minute=30, second=59, microsecond=999999)
    return start <= now_ist <= end


def _enrich_boost_items(items: list[dict]) -> None:
    """Attach the locally-computed fields to intraday_boost rows, in place.

    Same three services the /tfmarketpulse endpoint uses, so a row stored here
    carries exactly what the panel displayed at that minute. Each `ensure_`
    call is non-blocking and self-throttling - CPR and the first candle are
    once per symbol per day, steadiness once per symbol per five minutes - so
    calling them on a one-minute beat costs a dictionary lookup on most ticks.

    Never raises: enrichment is a bonus on top of the rank and the price, and a
    broker that will not answer must not cost the tick its snapshot.
    """
    if not items:
        return
    try:
        from database.auth_db import get_auth_token_broker, get_first_available_api_key
        from services.tf_cpr_service import attach_cpr, ensure_cpr_cache
        from services.tf_directional_score_service import (
            attach_directional_score,
            ensure_directional_score_cache,
        )
        from services.tf_first_candle_service import attach_first_candle, ensure_first_candle_cache

        symbols = [it["symbol"] for it in items if it.get("symbol")]
        api_key = get_first_available_api_key()
        if api_key:
            auth_token, broker = get_auth_token_broker(api_key, include_feed_token=False)
            if auth_token and broker:
                ensure_cpr_cache(symbols, auth_token, broker)
                ensure_first_candle_cache(symbols, auth_token, broker)
                ensure_directional_score_cache(symbols, auth_token, broker)
        # Attached regardless of whether the caches could be topped up: whatever
        # the live endpoint has already computed this session is still worth
        # storing, and a symbol with nothing cached gets None rather than a zero.
        attach_cpr(items)
        attach_first_candle(items)
        attach_directional_score(items)
    except Exception as e:
        logger.warning(f"tf_boost_snapshot: enrichment skipped: {e}")


def _run_snapshot_tick():
    """APScheduler job callable — must never raise, or crash the scheduler
    thread. The CronTrigger already narrows to hours 9-15 (mon-fri); this
    in-job guard enforces the exact 09:15-15:30 IST boundary."""
    now_ist = datetime.now(IST)
    if not _within_market_window(now_ist):
        logger.debug(f"tf_boost_snapshot: {now_ist.time()} outside 09:15-15:30 IST, skipping")
        return

    # Aligned to the minute, naive IST (matches isi_v56_live_strategy.py's own
    # naive-IST convention), so replay joins line up predictably. Rows written
    # before this was a one-minute beat land on :00/:05/:10 and still read as
    # the same series - the finer grid is a superset of the old one.
    snapshot_time = now_ist.replace(second=0, microsecond=0, tzinfo=None)
    snapshot_date = snapshot_time.date()
    total_inserted = 0
    sector_ok = False

    try:
        result = fetch_market_pulse()
    except Exception as e:
        logger.warning(f"tf_boost_snapshot: unexpected fetch error: {e}")
        result = None

    if result is None:
        logger.warning(
            "tf_boost_snapshot: market_pulse fetch failed / JWT expired, skipping boost lists"
        )
    else:
        _enrich_boost_items(result.get("intraday_boost") or [])
        try:
            with get_connection() as conn:
                for list_type, items in result.items():
                    if not items:
                        # Was permanently empty for breakout_beacon due to a parsing
                        # bug (tradefinder_service._map_items dropped every item
                        # whose param_2 wasn't numeric — fixed 2026-07-29). Genuinely
                        # possible for any list to be empty on a given tick though,
                        # so this stays a plain skip-and-log rather than a warning.
                        logger.debug(
                            f"tf_boost_snapshot: {list_type} empty @ {snapshot_time}, skipping"
                        )
                        continue
                    for rank, item in enumerate(items, start=1):
                        conn.execute(
                            """
                            INSERT INTO tf_boost_snapshots
                                (snapshot_date, snapshot_time, list_type, rank, symbol,
                                 ltp, prev_close, change_pct, score,
                                 directional_score, directional_direction, directional_reversals,
                                 cpr_width_pct, cpr_bias, first_candle_range_pct)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            ON CONFLICT (snapshot_time, list_type, symbol) DO NOTHING
                            """,
                            [
                                snapshot_date,
                                snapshot_time,
                                list_type,
                                rank,
                                item["symbol"],
                                item["ltp"],
                                item["prev_close"],
                                item["change_pct"],
                                item["score"],
                                item.get("directional_score"),
                                item.get("directional_direction"),
                                item.get("directional_reversals"),
                                item.get("cpr_width_pct"),
                                item.get("cpr_bias"),
                                item.get("first_candle_range_pct"),
                            ],
                        )
                        total_inserted += 1
            logger.debug(
                f"tf_boost_snapshot: stored @ {snapshot_time} ({total_inserted} rows across 3 lists)"
            )
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

    index_items = []
    if sector_result is None:
        logger.warning(
            "tf_boost_snapshot: sector_scope fetch failed / JWT expired, skipping sector index"
        )
    else:
        index_items = [
            {"symbol": it.get("Symbol"), "score": it.get("param_3")}
            for it in (sector_result.get("index") or [])
            if it.get("Symbol") is not None
        ]
        if not index_items:
            logger.debug(f"tf_boost_snapshot: sector index empty @ {snapshot_time}, skipping")

    if index_items:
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
            total_inserted += len(index_items)
            sector_ok = True
            logger.debug(
                f"tf_boost_snapshot: stored sector index @ {snapshot_time} ({len(index_items)} sectors)"
            )
        except Exception as e:
            logger.warning(f"tf_boost_snapshot: DB write failed for sector index: {e}")

    # Last, and unconditionally: a tick that fetched nothing is exactly the tick
    # a later study most needs to know about. The early returns this block
    # replaced are why 13 of 38 captured days cannot be told apart from quiet
    # ones.
    record_heartbeat(
        snapshot_time,
        pulse_ok=result is not None,
        sector_ok=sector_ok,
        rows_written=total_inserted,
        note=None if result is not None else "market_pulse fetch failed",
    )


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
            trigger=CronTrigger(day_of_week="mon-fri", hour="9-15", minute="*", timezone=IST),
            id=TF_SNAPSHOT_JOB_ID,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=60,
        )
        _scheduler.start()
        logger.info(
            "TF Boost snapshot scheduler started (isolated, in-memory jobstore, "
            "every minute 9-15 mon-fri Asia/Kolkata, 09:15-15:30 in-job guard)"
        )
