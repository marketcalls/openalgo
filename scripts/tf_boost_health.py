"""One-command readiness check for the Intraday Boost rank-movement stack.

Run it before the open and any time during the session:

    uv run python scripts/tf_boost_health.py

It answers the only questions that matter live: is the TradeFinder token alive,
is the recorder still beating, did we lose any minutes (a restart costs the
minutes it was down -- the engine's resolution comes straight off this), and is
the movement engine producing events right now.
"""

import os
import sys
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

# Runnable from anywhere, including scripts/ itself.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.tf_boost_db import get_connection
from services.tf_jwt_keepalive_service import get_tf_jwt_status
from services.tf_rank_movement_service import movement_snapshot

IST = ZoneInfo("Asia/Kolkata")
LISTS = ("intraday_boost", "breakout_beacon", "high_powered_stocks", "sector_index")
# A 1-minute recorder that has not written for this long is not beating.
STALE_AFTER_SECONDS = 150


def _fmt(t: datetime) -> str:
    return t.strftime("%H:%M")


def _unreadable(exc: Exception) -> None:
    """DuckDB gives the whole file to one process at a time, so this script
    cannot read while the app happens to be mid-write or mid-request. It is a
    collision, not damage: wait a moment and run it again."""
    print(
        f"[ATTENTION] snapshot database busy -- the app is using it. Try again in a few "
        f"seconds. ({exc.__class__.__name__})"
    )


def main() -> None:
    now = datetime.now(IST)
    today = date.today()
    print(f"TF Boost health -- {now:%Y-%m-%d %H:%M:%S} IST\n")

    jwt = get_tf_jwt_status()
    secs = jwt.get("expiresInSeconds") or 0
    state = "OK" if jwt.get("hasToken") and secs > 600 else "ATTENTION"
    print(
        f"[{state}] TradeFinder token: present={jwt.get('hasToken')} "
        f"expires in {secs // 60} min refreshing={jwt.get('refreshing')}"
    )

    try:
        _report_recorder(now, today)
    except Exception as exc:  # noqa: BLE001 -- any read failure reads the same to the user
        _unreadable(exc)
        return

    print()
    rows = movement_snapshot(list_type="intraday_boost")
    live = [r for r in rows if r.get("present", True)]
    hot = [r for r in live if r["event_priority"] >= 68]
    print(
        f"[{'OK' if rows else 'ATTENTION'}] movement engine: {len(rows)} symbols today, "
        f"{len(live)} on the list now, {len(hot)} at alert strength"
    )
    for r in sorted(hot, key=lambda r: -r["event_priority"])[:5]:
        print(f"    {r['symbol']:<14} {r['event']:<16} {r['first_seen_rank']}->{r['current_rank']}")


def _report_recorder(now: datetime, today: date) -> None:
    with get_connection() as conn:
        hb = conn.execute(
            "select max(snapshot_time), count(*) from tf_boost_heartbeat where snapshot_date = ?",
            [today],
        ).fetchone()
        last_beat, beats = hb[0], hb[1]
        if last_beat is None:
            print(
                "[ATTENTION] recorder: no heartbeat today -- is the app running "
                "with TF_BOOST_SNAPSHOT_ENABLED=true?"
            )
        else:
            age = (now.replace(tzinfo=None) - last_beat).total_seconds()
            # Outside 09:15-15:30 a silent recorder is the schedule, not a fault.
            in_session = now.time() >= time(9, 15) and now.time() <= time(15, 30)
            state = "OK" if age <= STALE_AFTER_SECONDS or not in_session else "ATTENTION"
            print(
                f"[{state}] recorder: {beats} beats today, last at {_fmt(last_beat)} "
                f"({int(age)}s ago)"
            )

        print()
        for list_type in LISTS:
            times = [
                r[0]
                for r in conn.execute(
                    "select distinct snapshot_time from tf_boost_snapshots "
                    "where snapshot_date = ? and list_type = ? order by 1",
                    [today, list_type],
                ).fetchall()
            ]
            if not times:
                print(f"[ATTENTION] {list_type}: no snapshots today")
                continue
            gaps = [
                (times[i - 1], times[i])
                for i in range(1, len(times))
                if times[i] - times[i - 1] > timedelta(seconds=90)
            ]
            lost = sum(int((b - a).total_seconds() // 60) - 1 for a, b in gaps)
            state = "OK" if not gaps else "GAPS"
            print(
                f"[{state}] {list_type}: {len(times)} ticks {_fmt(times[0])}-{_fmt(times[-1])}"
                + (
                    f", {len(gaps)} gaps, {lost} minutes lost: "
                    + ", ".join(f"{_fmt(a)}->{_fmt(b)}" for a, b in gaps[:4])
                    if gaps
                    else ""
                )
            )


if __name__ == "__main__":
    main()
