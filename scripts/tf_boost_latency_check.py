"""Measure how long a snapshot takes to reach a client, against the 40s budget.

    uv run python scripts/tf_boost_latency_check.py           # watch 5 ticks
    uv run python scripts/tf_boost_latency_check.py 10        # watch 10

Run it during market hours. It connects the same way the chart does, waits for
the recorder's `boost_snapshot` events, and times each one from the minute it
belongs to -- which is the number that matters, because that is when the move it
describes happened.

The budget is forty seconds, set by the person trading on it. The parts:

    sampling interval   30s   the floor -- a move at 10:20:05 is not
                              captured until the 10:20:30 tick
    write               ~1s   measured p90 2.0s on 18-Sep-2026
    push                ~1s   Socket.IO, once the row exists

so about 32s worst case. This proves it end to end rather than adding the parts
up, because a push that never arrives looks exactly like a fast one until it is
measured.
"""

from __future__ import annotations

import os
import statistics
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

IST = ZoneInfo("Asia/Kolkata")
BUDGET_SECONDS = 40
DEFAULT_TICKS = 5


def main() -> None:
    import socketio

    wanted = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else DEFAULT_TICKS
    url = os.getenv("OPENALGO_URL", "http://127.0.0.1:5000")
    seen: list[float] = []

    client = socketio.Client()

    @client.on("boost_snapshot")
    def _on_snapshot(data):  # noqa: ANN001 - socketio hands through whatever was emitted
        received = datetime.now(IST)
        stamp = str((data or {}).get("snapshot_time") or "")
        try:
            taken = datetime.fromisoformat(stamp).replace(tzinfo=IST)
        except ValueError:
            print(f"  ? event with an unreadable time: {stamp!r}")
            return
        delay = (received - taken).total_seconds()
        seen.append(delay)
        verdict = "OK" if delay <= BUDGET_SECONDS else "OVER BUDGET"
        print(
            f"  [{verdict}] snapshot {taken:%H:%M:%S} reached this client at "
            f"{received:%H:%M:%S} -- {delay:.1f}s ({(data or {}).get('rows')} rows)"
        )

    print(f"Watching {url} for {wanted} snapshots. Budget is {BUDGET_SECONDS}s.\n")
    client.connect(url, wait_timeout=10)
    if not client.connected:
        print("Could not connect. Is the app running?")
        return

    # A tick every 30s during the session, so this is the longest a healthy
    # recorder can keep us waiting plus a margin.
    deadline = time.time() + wanted * 45 + 60
    while len(seen) < wanted and time.time() < deadline:
        time.sleep(1)
    client.disconnect()

    print()
    if not seen:
        print(
            "No snapshots arrived. Either the market is closed (the recorder runs "
            "09:15-15:30 on weekdays), or the recorder is not ticking -- check "
            "scripts/tf_boost_health.py."
        )
        return
    worst = max(seen)
    print(f"{len(seen)} snapshots: median {statistics.median(seen):.1f}s, worst {worst:.1f}s")
    print(
        f"{'WITHIN' if worst <= BUDGET_SECONDS else 'OVER'} the {BUDGET_SECONDS}s budget"
        + ("" if worst <= BUDGET_SECONDS else " -- the sampling interval is the thing to shorten")
    )


if __name__ == "__main__":
    main()
