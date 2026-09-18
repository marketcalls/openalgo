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

import os
import subprocess
import sys
import threading
from datetime import datetime, timedelta
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

    # Aligned to the half minute, naive IST (matches isi_v56_live_strategy.py's
    # own naive-IST convention), so replay joins line up predictably. Rows from
    # the older one-minute beat land on :00 and still read as the same series --
    # the finer grid is a superset of the old one.
    #
    # Half a minute rather than a whole one because the sampling interval is the
    # floor on how late a badge can be. Measured 18-Sep-2026: a write lands 1.0s
    # after its tick (p90 2.0s) and the socket push adds about a second, so a
    # 60s beat gave a 65s worst case and a 30s beat gives 33s.
    stamp_second = 0 if now_ist.second < 30 else 30
    snapshot_time = now_ist.replace(second=stamp_second, microsecond=0, tzinfo=None)
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

    # Tell the panels the moment the row exists, rather than leaving them to
    # find it on their own timer. The recorder writes 0.8s after the minute
    # (median, measured 17-Sep-2026) but a 60s blind poll then sat on it for
    # another 31s on average and up to a minute -- so a badge that the data
    # supported at 10:04 could reach the screen at 10:05. One event closes that.
    if total_inserted:
        try:
            from extensions import socketio

            socketio.emit(
                "boost_snapshot",
                {"snapshot_time": snapshot_time.isoformat(), "rows": total_inserted},
            )
        except Exception as e:
            # A panel that misses the nudge still refreshes on its own timer, so
            # this must never cost the tick its snapshot.
            logger.debug(f"tf_boost_snapshot: socket notify skipped: {e}")

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
            trigger=CronTrigger(
                day_of_week="mon-fri", hour="9-15", minute="*", second="0,30", timezone=IST
            ),
            id=TF_SNAPSHOT_JOB_ID,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=60,
        )
        _scheduler.start()
        logger.info(
            "TF Boost snapshot scheduler started (isolated, in-memory jobstore, "
            "every 30s 9-15 mon-fri Asia/Kolkata, 09:15-15:30 in-job guard)"
        )


def _daily_log_path(now_ist: datetime) -> str:
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    log_dir = os.path.join(base, "log", "tf_boost_daily")
    os.makedirs(log_dir, exist_ok=True)
    return os.path.join(log_dir, f"{now_ist:%Y-%m-%d}.log")


def _append(now_ist: datetime, line: str) -> None:
    """One day, one file, one line per event. A morning that failed has to leave
    evidence -- the upstream only serves the live list, so a day not recorded is
    a day that cannot be recovered or even described after the fact."""
    try:
        with open(_daily_log_path(now_ist), "a") as fh:
            fh.write(f"[{now_ist:%H:%M:%S}] {line}\n")
    except Exception as e:
        logger.warning(f"tf_boost daily log write failed: {e}")


def _run_morning_check():
    """09:25 IST: is the day actually being recorded? Written down, not guessed."""
    now_ist = datetime.now(IST)
    try:
        from database.tf_boost_db import get_connection as boost_conn
        from services.tf_jwt_keepalive_service import get_tf_jwt_status

        jwt = get_tf_jwt_status()
        with boost_conn() as conn:
            beats, last = conn.execute(
                "SELECT count(*), max(snapshot_time) FROM tf_boost_heartbeat "
                "WHERE snapshot_date = ?",
                [now_ist.date()],
            ).fetchone()
            symbols = conn.execute(
                "SELECT count(DISTINCT symbol) FROM tf_boost_snapshots "
                "WHERE snapshot_date = ? AND list_type = 'intraday_boost'",
                [now_ist.date()],
            ).fetchone()[0]

        healthy = bool(beats) and bool(symbols) and jwt.get("hasToken")
        _append(
            now_ist,
            f"{'OK' if healthy else 'ATTENTION'} morning check -- {beats} beats "
            f"(last {last}), {symbols} symbols recorded, token "
            f"{'present' if jwt.get('hasToken') else 'MISSING'}, "
            f"expires in {(jwt.get('expiresInSeconds') or 0) // 60} min",
        )
        if not healthy:
            logger.error(
                "TF Boost morning check failed: the day is not being recorded "
                f"(beats={beats}, symbols={symbols}, token={jwt.get('hasToken')})"
            )
    except Exception as e:
        logger.exception(f"tf_boost morning check failed: {e}")
        _append(now_ist, f"ATTENTION morning check could not run: {e}")


def _run_daily_study():
    """15:45 IST: the post-close behaviour study, for both entry windows.

    Run as a child process rather than in this thread: it makes a few hundred
    broker history calls and takes minutes, and none of that belongs inside the
    scheduler that has to fire on the next minute. Output goes to the day's log
    file (never a pipe) and each child is waited on, so no descriptor is left
    behind.
    """
    now_ist = datetime.now(IST)
    day = now_ist.strftime("%Y-%m-%d")
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    script = os.path.join(base, "scripts", "tf_boost_behaviour.py")
    _append(now_ist, "evening study starting")

    # Every study the day needs, in the order a person would run them: what each
    # stock did, what each badge did, and what the option on the badge's own
    # side did. All three or the record is partial, and a partial record is what
    # a week of evidence cannot be rebuilt from.
    runs = [
        ("behaviour 09:45", [sys.executable, script, day, "--after", "09:45"]),
        ("behaviour 10:00", [sys.executable, script, day, "--after", "10:00"]),
        (
            "verify sheet",
            [sys.executable, os.path.join(base, "scripts", "tf_boost_verify.py"), day],
        ),
        (
            "option audit",
            [sys.executable, os.path.join(base, "scripts", "tf_boost_option_audit.py"), day],
        ),
    ]
    for label, argv in runs:
        try:
            with open(_daily_log_path(now_ist), "a") as out:
                proc = subprocess.Popen(argv, cwd=base, stdout=out, stderr=subprocess.STDOUT)
                code = proc.wait(timeout=1800)
            _append(
                datetime.now(IST),
                f"{'OK' if code == 0 else 'ATTENTION'} {label} finished (exit {code})",
            )
        except Exception as e:
            logger.exception(f"tf_boost evening study ({label}) failed: {e}")
            _append(datetime.now(IST), f"ATTENTION {label} failed: {e}")


def init_tf_boost_daily_jobs():
    """Attach the morning check and the post-close study to the snapshot
    scheduler. Same opt-in as the recorder: if the day is being captured, it
    should also be checked and studied, without anyone remembering to."""
    if _scheduler is None:
        logger.warning("tf_boost daily jobs skipped: snapshot scheduler is not running")
        return
    _scheduler.add_job(
        _run_morning_check,
        trigger=CronTrigger(day_of_week="mon-fri", hour=9, minute=25, timezone=IST),
        id="tf_boost_morning_check",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
        replace_existing=True,
    )
    _scheduler.add_job(
        _run_daily_study,
        trigger=CronTrigger(day_of_week="mon-fri", hour=15, minute=45, timezone=IST),
        id="tf_boost_daily_study",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=1800,
        replace_existing=True,
    )
    # A one-off a few seconds after boot: off the startup path (which must not
    # wait on the broker) but early enough that a late start still records.
    _scheduler.add_job(
        _startup_catchup,
        trigger="date",
        run_date=datetime.now(IST) + timedelta(seconds=20),
        id="tf_boost_startup_catchup",
        max_instances=1,
        replace_existing=True,
    )
    logger.info(
        "TF Boost daily jobs scheduled (morning check 09:25, behaviour study 15:45 IST, "
        "catch-up on start)"
    )


def _study_already_done(day) -> bool:
    try:
        from database.tf_boost_db import get_connection as boost_conn

        with boost_conn() as conn:
            done = conn.execute(
                "SELECT count(*) FROM tf_boost_behaviour WHERE day = ?", [day]
            ).fetchone()[0]
        return bool(done)
    except Exception:
        # No table yet, or the file is busy: treat as not done and let the study
        # decide. Re-running a day replaces it, so a duplicate attempt is cheap.
        return False


def _startup_catchup():
    """Make starting the app enough, whenever in the day it happens.

    The jobs below only fire if the app happens to be running at 09:25 and
    15:45. Someone who starts it at 09:40, or only in the evening, would
    otherwise get a day with no morning line and no study -- and the study is
    the research record. So every start writes down when recording began, and
    picks up whatever the day has already missed.
    """
    now_ist = datetime.now(IST)
    _append(now_ist, f"app started -- recording from {now_ist:%H:%M}")

    if now_ist.weekday() >= 5:
        return
    try:
        # A morning that started late leaves the run engine measuring a move
        # from the wrong end. Fill it from the broker's candles before anything
        # reads it; the call returns quietly when there is no hole.
        try:
            from services.tf_boost_backfill_service import backfill_day

            filled = backfill_day(now_ist.strftime("%Y-%m-%d"))
            if filled.get("rows"):
                _append(
                    now_ist,
                    f"reconstructed {filled['rows']} missed minutes across "
                    f"{filled['symbols']} symbols ({filled['gap_minutes']} minute gap)",
                )
        except Exception as e:
            logger.exception(f"tf_boost startup backfill failed: {e}")

        # Past the close with snapshots captured but no study: run it now.
        if now_ist.hour * 60 + now_ist.minute >= 15 * 60 + 45:
            from database.tf_boost_db import get_connection as boost_conn

            with boost_conn() as conn:
                captured = conn.execute(
                    "SELECT count(*) FROM tf_boost_snapshots WHERE snapshot_date = ?",
                    [now_ist.date()],
                ).fetchone()[0]
            if captured and not _study_already_done(now_ist.date()):
                _append(now_ist, "study for today had not run yet -- catching up")
                _run_daily_study()
            return

        # Started after the morning check but inside the session: still leave the
        # health line, so a late start is visible as a late start.
        if 9 * 60 + 25 < now_ist.hour * 60 + now_ist.minute <= 15 * 60 + 30:
            _run_morning_check()
    except Exception as e:
        logger.exception(f"tf_boost startup catch-up failed: {e}")
        _append(now_ist, f"ATTENTION startup catch-up failed: {e}")


# --- watchdog ----------------------------------------------------------------
# A laptop that sleeps through the open takes the scheduler with it. On
# 18-Sep-2026 the process was suspended overnight, woke at 10:01 with APScheduler
# logging runs "missed by 0:00:59" for other jobs, and this scheduler never fired
# again: zero heartbeats at 10:03, forty-nine minutes of the session gone and
# unrecoverable, because the upstream only ever serves the live list. A restart
# fixed it instantly, which is the whole point -- nobody was watching to do it.
#
# The watchdog cannot live on the scheduler it guards, so it runs on a real OS
# thread of its own. It only reads the heartbeat table and restarts the
# scheduler; it touches no green primitive, which is what makes that safe under
# eventlet as well as on the dev server.
WATCHDOG_POLL_SECONDS = 60
# Three missed minutes is past any normal tick (median 0.8s, worst 43s observed)
# and still catches the failure inside the same five minutes it began.
WATCHDOG_STALE_SECONDS = 180

_watchdog: object | None = None
_watchdog_stop = None


def _heartbeat_age_seconds(now_ist: datetime) -> float | None:
    """Seconds since the last heartbeat today, or None if there is none yet."""
    try:
        from database.tf_boost_db import get_connection as boost_conn

        with boost_conn() as conn:
            last = conn.execute(
                "SELECT max(snapshot_time) FROM tf_boost_heartbeat WHERE snapshot_date = ?",
                [now_ist.date()],
            ).fetchone()[0]
        if last is None:
            return None
        return (now_ist.replace(tzinfo=None) - last).total_seconds()
    except Exception as e:
        logger.debug(f"tf_boost watchdog: could not read the heartbeat: {e}")
        return None


def _restart_scheduler() -> None:
    """Tear the scheduler down and stand it back up, jobs and all."""
    global _scheduler
    with _lock:
        old = _scheduler
        _scheduler = None
    if old is not None:
        try:
            old.shutdown(wait=False)
        except Exception as e:
            logger.debug(f"tf_boost watchdog: old scheduler would not shut down: {e}")
    init_tf_boost_snapshot()
    init_tf_boost_daily_jobs()


def _watchdog_loop(stop_event) -> None:
    from utils.real_threading import wait_for

    while not wait_for(stop_event, WATCHDOG_POLL_SECONDS):
        try:
            now_ist = datetime.now(IST)
            if not _within_market_window(now_ist) or now_ist.weekday() >= 5:
                continue
            age = _heartbeat_age_seconds(now_ist)
            # No heartbeat at all yet is only alarming once the session has been
            # running long enough for one to exist.
            opened_minutes_ago = (now_ist.hour * 60 + now_ist.minute) - (9 * 60 + 15)
            stale = age is not None and age > WATCHDOG_STALE_SECONDS
            never = age is None and opened_minutes_ago > WATCHDOG_STALE_SECONDS / 60
            if stale or never:
                logger.error(
                    "TF Boost recorder has written nothing for "
                    f"{int(age) if age is not None else 'the whole session'} seconds -- "
                    "restarting its scheduler"
                )
                _append(now_ist, "ATTENTION recorder stalled -- watchdog restarted it")
                _restart_scheduler()
        except Exception as e:
            logger.exception(f"tf_boost watchdog: {e}")


def init_tf_boost_watchdog() -> None:
    """Start the watchdog once. Safe to call again; it will not double-start."""
    global _watchdog, _watchdog_stop
    if _watchdog is not None:
        return
    from utils.real_threading import Event, Thread

    _watchdog_stop = Event()
    _watchdog = Thread(
        target=_watchdog_loop,
        args=(_watchdog_stop,),
        name="tf-boost-watchdog",
        daemon=True,
    )
    _watchdog.start()
    logger.info(
        "TF Boost watchdog started (checks every "
        f"{WATCHDOG_POLL_SECONDS}s, restarts the recorder after "
        f"{WATCHDOG_STALE_SECONDS}s without a heartbeat)"
    )
