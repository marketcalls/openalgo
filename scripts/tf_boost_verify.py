"""Every badge the panel raised on a day, and what the stock did afterwards.

    uv run python scripts/tf_boost_verify.py              # today
    uv run python scripts/tf_boost_verify.py 2026-09-17

For each symbol that earned a RUN badge, this replays the day minute by minute,
finds the FIRST moment the badge would have appeared using only the data that
existed at that moment, and then reports what followed at the broker's own
prices: how long until +1%, the best it reached, and the worst it went against
you first.

Winners and losers both. A sheet that only shows the ones that worked cannot be
used to judge anything, which is the entire point of writing it down.
"""

from __future__ import annotations

import os
import statistics
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.auth_db import get_auth_token_broker, get_first_available_api_key  # noqa: E402
from database.tf_boost_db import (  # noqa: E402
    get_boost_change_timeline,
    get_boost_rank_timeline,
)
from services.history_service import get_history  # noqa: E402
from services.tf_rank_movement_service import compute_symbol_movement  # noqa: E402
from services.tf_symbol_alias import tradable_symbol  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")
TARGET_PCT = 1.0  # the move that pays on a stock option


def first_recorded_minute(day: str, list_type: str = "intraday_boost") -> int | None:
    """The first minute actually captured live, not reconstructed. A badge dated
    to it was already running when the recorder woke, so it is not an entry
    anyone could have taken -- see the same guard in tf_boost_option_audit."""
    from database.tf_boost_db import get_connection

    try:
        with get_connection() as conn:
            value = conn.execute(
                "SELECT min(hour(snapshot_time) * 60 + minute(snapshot_time)) "
                "FROM tf_boost_snapshots WHERE snapshot_date = ? AND list_type = ?",
                [day, list_type],
            ).fetchone()[0]
        return int(value) if value is not None else None
    except Exception:
        return None


def first_badge(symbol, changes, ranks):
    """The first minute the panel would show RUN, with no hindsight.

    Asks the engine instead of restating its rule. This function used to carry
    its own copy and fell two changes behind it: no requirement that the price
    direction agrees with the ranked list, and no allowance for a clean run
    being outranked by a JUMP label, so it reported badges the panel never
    showed. A rule that lives in two places is a rule that disagrees with
    itself.
    """
    for i in range(10, len(changes)):
        upto = changes[i][0]
        row = compute_symbol_movement(
            symbol, [p for p in ranks if p[0] <= upto], upto, changes[: i + 1]
        )
        if row and row["event"] in ("CLEAN_RUN_UP", "CLEAN_RUN_DOWN"):
            return upto, row
    return None, None


def outcome(bars, badge_min, direction):
    """What the stock did after the badge, at the broker's own prices."""
    before = [b for t, b in bars if t.hour * 60 + t.minute <= badge_min]
    after = [(t, b) for t, b in bars if t.hour * 60 + t.minute >= badge_min]
    if not before or len(after) < 2:
        return None
    entry = before[-1]["close"]
    up = direction == "up"
    best = worst = 0.0
    minutes_to_target = None
    for t, b in after:
        gain = ((b["high"] - entry) if up else (entry - b["low"])) / entry * 100
        loss = ((entry - b["low"]) if up else (b["high"] - entry)) / entry * 100
        best, worst = max(best, gain), max(worst, loss)
        if minutes_to_target is None and gain >= TARGET_PCT:
            minutes_to_target = t.hour * 60 + t.minute - badge_min
    close = after[-1][1]["close"]
    return {
        "entry": entry,
        "best": round(best, 2),
        "heat": round(worst, 2),
        "close_pct": round(((close - entry) if up else (entry - close)) / entry * 100, 2),
        "minutes_to_target": minutes_to_target,
    }


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    day = args[0] if args else datetime.now(IST).strftime("%Y-%m-%d")
    changes, ranks = get_boost_change_timeline(day), get_boost_rank_timeline(day)
    if not changes:
        print(f"No snapshots for {day}.")
        return

    already_running = 0
    recording_began = first_recorded_minute(day)
    api_key = get_first_available_api_key()
    auth_token, broker = get_auth_token_broker(api_key, include_feed_token=False)
    rows = []
    for symbol in sorted(changes):
        cps, rps = changes[symbol].get(day, []), ranks.get(symbol, {}).get(day, [])
        if len(cps) < 12 or not rps:
            continue
        badge_min, row = first_badge(symbol, cps, rps)
        if badge_min is None:
            continue
        if recording_began is not None and badge_min <= recording_began + 1:
            already_running += 1
            continue
        try:
            ok, res, _ = get_history(
                tradable_symbol(symbol),
                "NSE",
                "5m",
                day,
                day,
                auth_token=auth_token,
                broker=broker,
                source="api",
            )
            candles = (res.get("data") if isinstance(res, dict) else None) or []
            if not ok or not candles:
                continue
            bars = [(datetime.fromtimestamp(b["timestamp"], IST), b) for b in candles]
            result = outcome(bars, badge_min, row["run_direction"])
            if result:
                rows.append(
                    {
                        "symbol": symbol,
                        "min": badge_min,
                        "row": row,
                        "rank": row["current_rank"],
                        **result,
                    }
                )
        except Exception:
            continue

    rows.sort(key=lambda r: r["min"])
    paid = [r for r in rows if r["minutes_to_target"] is not None]
    clean = [r for r in paid if r["heat"] < 0.5]
    print(
        f"\n{day}: {len(rows)} badges. {len(paid)} reached +{TARGET_PCT}%, "
        f"{len(clean)} of those without {0.5}% against you first.\n"
    )

    header = (
        f"{'symbol':<12}{'badge':>7}{'rank':>5}{'price':>10}{'eff':>6}"
        f"{'+1% in':>8}{'best':>7}{'heat':>7}{'at close':>10}"
    )
    print(header)
    lines = []
    for r in rows:
        t = f"{r['min'] // 60:02d}:{r['min'] % 60:02d}"
        target = f"{r['minutes_to_target']}m" if r["minutes_to_target"] is not None else "-"
        line = (
            f"{r['symbol']:<12}{t:>7}{r['rank']:>5}{r['entry']:>10.2f}"
            f"{r['row']['run_efficiency']:>6.1f}{target:>8}{r['best']:>+7.2f}{r['heat']:>7.2f}"
            f"{r['close_pct']:>+10.2f}"
        )
        print(line)
        lines.append(line)

    if paid:
        print(
            f"\nmedian time to +{TARGET_PCT}%: "
            f"{int(statistics.median([r['minutes_to_target'] for r in paid]))} minutes"
        )
        print(
            f"median heat on the ones that paid: "
            f"{statistics.median([r['heat'] for r in paid]):.2f}%"
        )

    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "log")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"tf_boost_verify_{day}.txt")
    with open(path, "w") as fh:
        fh.write(f"{day}: {len(rows)} badges, {len(paid)} reached +{TARGET_PCT}%\n\n")
        fh.write(header + "\n")
        fh.write("\n".join(lines) + "\n")
    print(f"\nsaved to {path}")


if __name__ == "__main__":
    main()
