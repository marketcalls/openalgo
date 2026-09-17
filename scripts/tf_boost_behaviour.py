"""Post-mortem of how every stock on a day's Intraday Boost list actually moved.

    uv run python scripts/tf_boost_behaviour.py                 # today
    uv run python scripts/tf_boost_behaviour.py 2026-09-17      # a stored day
    uv run python scripts/tf_boost_behaviour.py --report        # print, do not write

For each symbol it pairs the ranked-list record with the day's 5-minute candles
and answers the questions that decide whether a move was catchable:

  where it turned        the run anchor, matched to the bar it happened on
  what it broke          previous-day high/low, the opening 15-minute range,
                         previous close, or VWAP -- whichever gave way at the turn
  how hard it broke      that bar's volume against the day's median bar
  how fast the money came minutes from the turn to +1% and to +2%
  what it cost to hold   the worst move against you after the turn (heat), and
                         whether +1% arrived before -0.5% did

Rows land in tf_boost_behaviour (one per symbol per day, re-runnable), so the
record accumulates night after night and the same questions can be asked of a
month instead of an afternoon.
"""

from __future__ import annotations

import os
import statistics
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# Runnable from anywhere, including scripts/ itself.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.auth_db import get_auth_token_broker, get_first_available_api_key  # noqa: E402
from database.tf_boost_db import (  # noqa: E402
    get_connection,
    init_behaviour_table,
    upsert_behaviour,
)
from services.history_service import get_history  # noqa: E402
from services.tf_rank_movement_service import movement_snapshot  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")
LIST_TYPE = "intraday_boost"
OPENING_RANGE_BARS = 3  # 15 minutes on a 5-minute chart
LEVEL_TOLERANCE_PCT = 0.15  # how close counts as "at" a level
TRIGGER_WINDOW_BARS = 2  # bars either side of the turn to look for the break
CAPTURE_TARGETS = (1.0, 2.0)  # the move the user is actually trying to take
HEAT_LIMIT_PCT = 0.5  # adverse move that spoils a clean capture

# TradeFinder keeps trading under the old name after a corporate action while
# the broker's symbol master moves to the new one, so the ranked list can carry
# a symbol no history call will answer for. On 17-Sep-2026 that silently dropped
# TATAMOTORS -- the day's number one -- because the master now lists it as TMPV
# under the same ISIN. Anything skipped is printed, so a new rename shows up as
# a name rather than as a stock that quietly stopped being studied.
SYMBOL_ALIASES = {"TATAMOTORS": "TMPV"}

# Nobody trades stock options into the opening auction's volatility -- the book
# settles after about ten o'clock, and an entry before that is a different (and
# worse) trade than the one this study is meant to describe. So the default
# study starts at 10:00 and asks what was available from there, not from 09:15.
# Not a hard rule -- a 09:45 entry is fine if it is the right one and the stock
# does not turn back on you from there. That is what the heat columns measure:
# an entry that reverses is the failure mode, not a late clock.
DEFAULT_ENTRY_AFTER = "09:45"


def option_underlyings() -> set[str]:
    """Symbols with listed options, from the broker's own F&O master.

    A stock-options trader can only act on these, so everything else in the
    ranked list is noise for this purpose however well it moved.
    """
    import re

    from database.symbol import SymToken, db_session

    try:
        rows = (
            db_session.query(SymToken.symbol)
            .filter(SymToken.exchange == "NFO", SymToken.symbol.like("%CE"))
            .all()
        )
        bases = set()
        for (sym,) in rows:
            match = re.match(r"^([A-Z&-]+?)\d{2}[A-Z]{3}\d{2}", sym)
            if match:
                bases.add(match.group(1))
        return bases
    finally:
        db_session.remove()


def _bars_by_day(candles: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for bar in candles:
        stamp = datetime.fromtimestamp(bar["timestamp"], IST)
        out.setdefault(stamp.strftime("%Y-%m-%d"), []).append({**bar, "dt": stamp})
    return out


def _minute_of_day(bar: dict) -> int:
    return bar["dt"].hour * 60 + bar["dt"].minute


def _vwap_series(bars: list[dict]) -> list[float]:
    vwaps, pv, vol = [], 0.0, 0.0
    for b in bars:
        typical = (b["high"] + b["low"] + b["close"]) / 3
        pv += typical * b["volume"]
        vol += b["volume"]
        vwaps.append(pv / vol if vol else b["close"])
    return vwaps


def _level_broken(bars, idx, direction, prev_high, prev_low, prev_close, vwaps):
    """Which level gave way around the turn, and at what price.

    Checked in the order a trader would read them: the previous day's extreme is
    the one everyone watches, then the opening range, then the previous close,
    then VWAP. Returns (name, price) or (None, None).
    """
    lo = max(0, idx - TRIGGER_WINDOW_BARS)
    hi = min(len(bars), idx + TRIGGER_WINDOW_BARS + 1)
    window = bars[lo:hi]
    if not window:
        return None, None
    before = bars[:lo] or bars[:1]
    up = direction == "up"

    opening = bars[:OPENING_RANGE_BARS]
    or_high = max(b["high"] for b in opening) if opening else None
    or_low = min(b["low"] for b in opening) if opening else None

    candidates = (
        [
            ("previous day high", prev_high),
            ("opening range high", or_high),
            ("previous close", prev_close),
            ("VWAP", vwaps[idx] if idx < len(vwaps) else None),
        ]
        if up
        else [
            ("previous day low", prev_low),
            ("opening range low", or_low),
            ("previous close", prev_close),
            ("VWAP", vwaps[idx] if idx < len(vwaps) else None),
        ]
    )

    for name, level in candidates:
        if level is None:
            continue
        crossed_after = (
            max(b["close"] for b in window) > level
            if up
            else min(b["close"] for b in window) < level
        )
        was_below = (
            min(b["close"] for b in before) <= level * (1 + LEVEL_TOLERANCE_PCT / 100)
            if up
            else max(b["close"] for b in before) >= level * (1 - LEVEL_TOLERANCE_PCT / 100)
        )
        if crossed_after and was_below:
            return name, round(level, 2)
    return None, None


def _first_signal_after(bars, start_min, direction, levels, vwaps):
    """The first thing worth acting on at or after the entry window opens.

    Read the way a trader reads a chart mid-morning: has it taken out yesterday's
    high, the opening range, or the high of the day so far, or reclaimed VWAP?
    The first of those to happen is the entry, and everything after it is what
    the trade would have done. Returns (index, trigger) or (None, None).
    """
    up = direction == "up"
    prev_high, prev_low, or_high, or_low = levels
    start_idx = next((i for i, b in enumerate(bars) if _minute_of_day(b) >= start_min), None)
    if start_idx is None or start_idx == 0:
        return None, None

    for i in range(start_idx, len(bars)):
        bar, prior = bars[i], bars[i - 1]
        running = bars[:i]
        day_extreme = max(b["high"] for b in running) if up else min(b["low"] for b in running)
        checks = (
            [
                ("previous day high", prev_high),
                ("opening range high", or_high),
                ("day high", day_extreme),
                ("VWAP reclaim", vwaps[i]),
            ]
            if up
            else [
                ("previous day low", prev_low),
                ("opening range low", or_low),
                ("day low", day_extreme),
                ("VWAP loss", vwaps[i]),
            ]
        )
        for name, level in checks:
            if level is None:
                continue
            crossed = (
                bar["close"] > level and prior["close"] <= level
                if up
                else bar["close"] < level and prior["close"] >= level
            )
            if crossed:
                return i, name
    return None, None


def _capture(bars, idx, direction) -> dict:
    """How the move paid after the turn: time to each target, heat, cleanliness."""
    entry = bars[idx]["close"]
    up = direction == "up"
    after = bars[idx:]
    out = {
        "mins_to_1pct": None,
        "mins_to_2pct": None,
        "mfe_pct": 0.0,
        "mae_pct": 0.0,
        "clean_1pct": False,
    }
    heat_first = None
    for b in after:
        move = (b["high"] - entry) / entry * 100 if up else (entry - b["low"]) / entry * 100
        adverse = (entry - b["low"]) / entry * 100 if up else (b["high"] - entry) / entry * 100
        out["mfe_pct"] = max(out["mfe_pct"], round(move, 2))
        out["mae_pct"] = max(out["mae_pct"], round(adverse, 2))
        mins = _minute_of_day(b) - _minute_of_day(bars[idx])
        for target, key in zip(CAPTURE_TARGETS, ("mins_to_1pct", "mins_to_2pct"), strict=False):
            if out[key] is None and move >= target:
                out[key] = mins
        if heat_first is None and adverse >= HEAT_LIMIT_PCT:
            heat_first = mins
    if out["mins_to_1pct"] is not None:
        out["clean_1pct"] = heat_first is None or out["mins_to_1pct"] <= heat_first
    return out


def analyse(day: str, entry_after_min: int) -> list[dict]:
    init_behaviour_table()
    movement = {r["symbol"]: r for r in movement_snapshot(date=day, list_type=LIST_TYPE)}
    if not movement:
        print(f"No snapshots for {day} -- nothing to analyse.")
        return []

    with get_connection() as conn:
        enrich = {
            r[0]: (r[1], r[2])
            for r in conn.execute(
                """
                SELECT symbol, any_value(cpr_bias), any_value(first_candle_range_pct)
                FROM tf_boost_snapshots
                WHERE snapshot_date = ? AND list_type = ? AND cpr_bias IS NOT NULL
                GROUP BY symbol
                """,
                [day, LIST_TYPE],
            ).fetchall()
        }

    optionable = option_underlyings()
    api_key = get_first_available_api_key()
    auth_token, broker = get_auth_token_broker(api_key, include_feed_token=False)
    start = (datetime.strptime(day, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")

    rows, skipped = [], []
    for n, (symbol, mv) in enumerate(sorted(movement.items()), start=1):
        try:
            tradable = SYMBOL_ALIASES.get(symbol, symbol)
            ok, res, _ = get_history(
                tradable,
                "NSE",
                "5m",
                start,
                day,
                auth_token=auth_token,
                broker=broker,
                source="api",
            )
            candles = (res.get("data") if isinstance(res, dict) else None) or []
            if not ok or not candles:
                skipped.append(symbol)
                continue
            by_day = _bars_by_day(candles)
            bars = by_day.get(day) or []
            if len(bars) < OPENING_RANGE_BARS + 2:
                skipped.append(symbol)
                continue
            prior = [d for d in sorted(by_day) if d < day]
            prev_bars = by_day[prior[-1]] if prior else []
            prev_high = max(b["high"] for b in prev_bars) if prev_bars else None
            prev_low = min(b["low"] for b in prev_bars) if prev_bars else None
            prev_close = prev_bars[-1]["close"] if prev_bars else None

            direction = mv.get("run_direction") or "up"
            opening = bars[:OPENING_RANGE_BARS]
            or_high = max(b["high"] for b in opening) if opening else None
            or_low = min(b["low"] for b in opening) if opening else None
            vwaps = _vwap_series(bars)
            levels = (prev_high, prev_low, or_high, or_low)

            idx, trigger = _first_signal_after(bars, entry_after_min, direction, levels, vwaps)
            if idx is None:
                skipped.append(f"{symbol}(no signal)")
                continue

            level, level_price = _level_broken(
                bars, idx, direction, prev_high, prev_low, prev_close, vwaps
            )
            # A turn in the first bars has almost no day to average against, so
            # the baseline comes from the previous session instead -- otherwise
            # every early trigger reports a volume ratio of 1.0 and says nothing.
            baseline_bars = bars[:idx] if idx >= OPENING_RANGE_BARS else prev_bars or bars
            median_vol = statistics.median([b["volume"] for b in baseline_bars] or [1]) or 1
            cap = _capture(bars, idx, direction)
            cpr_bias, first_candle = enrich.get(symbol, (None, None))
            opening_price = bars[0]["open"]

            rows.append(
                {
                    "day": day,
                    "symbol": symbol,
                    "list_type": LIST_TYPE,
                    "entry_after_min": entry_after_min,
                    "has_options": symbol in optionable,
                    "entry_trigger": trigger,
                    "first_seen_rank": mv["first_seen_rank"],
                    "best_rank": mv["best_rank"],
                    "final_rank": mv["current_rank"],
                    "rank_at_trigger": None,
                    "gap_pct": round((opening_price - prev_close) / prev_close * 100, 2)
                    if prev_close
                    else None,
                    "run_direction": direction,
                    "trigger_min": _minute_of_day(bars[idx]),
                    "trigger_price": round(bars[idx]["close"], 2),
                    "level_broken": level,
                    "level_price": level_price,
                    "vol_ratio": round(bars[idx]["volume"] / median_vol, 2),
                    "above_vwap": bool(bars[idx]["close"] >= vwaps[idx]),
                    "cpr_bias": cpr_bias,
                    "first_candle_range_pct": first_candle,
                    "mins_to_1pct": cap["mins_to_1pct"],
                    "mins_to_2pct": cap["mins_to_2pct"],
                    "mfe_pct": cap["mfe_pct"],
                    "mae_pct": cap["mae_pct"],
                    "clean_1pct": cap["clean_1pct"],
                    "day_move_pct": round(
                        (bars[-1]["close"] - opening_price) / opening_price * 100, 2
                    ),
                    "run_move_pct": mv.get("run_move_pct"),
                    "run_adverse_pct": mv.get("run_adverse_pct"),
                    "run_efficiency": mv.get("run_efficiency"),
                    "notes": None,
                }
            )
        except Exception as exc:  # noqa: BLE001 -- one bad symbol must not stop the study
            skipped.append(f"{symbol}({exc.__class__.__name__})")
        if n % 25 == 0:
            print(f"  ... {n}/{len(movement)}")

    if skipped:
        print(
            f"skipped {len(skipped)}: {', '.join(skipped[:8])}{' ...' if len(skipped) > 8 else ''}"
        )
    return rows


def report(rows: list[dict]) -> None:
    if not rows:
        return
    catchable = [r for r in rows if r["mins_to_1pct"] is not None]
    clean = [r for r in rows if r["clean_1pct"]]
    print(
        f"\n{len(rows)} signals. {len(catchable)} reached +1%, {len(clean)} of those without "
        f"first turning back {HEAT_LIMIT_PCT}% -- {len(clean) / max(1, len(rows)) * 100:.0f}% "
        "of every signal held and paid.\n"
    )

    triggers: dict[str, list[dict]] = {}
    for r in rows:
        triggers.setdefault(r["entry_trigger"] or "-", []).append(r)
    print("by what triggered the entry:")
    for trigger, group in sorted(triggers.items(), key=lambda kv: -len(kv[1])):
        held = [g for g in group if g["clean_1pct"]]
        hit = [g for g in group if g["mins_to_1pct"] is not None]
        med = statistics.median([g["mins_to_1pct"] for g in hit]) if hit else None
        rate = len(held) / len(group) * 100
        print(
            f"  {trigger:<22}{len(group):>4} signals, {len(held):>3} held and paid ({rate:>3.0f}%)"
            + (f", median {int(med)} min" if med is not None else "")
        )

    by_level: dict[str, list[dict]] = {}
    for r in rows:
        by_level.setdefault(r["level_broken"] or "no level broken", []).append(r)
    print("\nlevel already broken when the signal fired:")
    for level, group in sorted(by_level.items(), key=lambda kv: -len(kv[1])):
        hit = [g for g in group if g["mins_to_1pct"] is not None]
        med = statistics.median([g["mins_to_1pct"] for g in hit]) if hit else None
        print(
            f"  {level:<22}{len(group):>4} symbols, {len(hit):>3} reached +1%"
            + (f", median {int(med)} min" if med is not None else "")
        )

    print(
        f"\n{'symbol':<13}{'turn':>6}{'level':>21}{'vol':>6}{'+1%':>6}{'+2%':>6}"
        f"{'heat':>6}{'day%':>7}"
    )
    ranked = sorted(catchable, key=lambda r: (r["mins_to_1pct"], r["mae_pct"]))
    for r in ranked[:25]:
        t = r["trigger_min"]
        print(
            f"{r['symbol']:<13}{t // 60:>3}:{t % 60:02d}{(r['level_broken'] or '-'):>21}"
            f"{r['vol_ratio']:>6.1f}{r['mins_to_1pct']:>6}"
            f"{(r['mins_to_2pct'] if r['mins_to_2pct'] is not None else '-'):>6}"
            f"{r['mae_pct']:>6.2f}{r['day_move_pct']:>+7.2f}"
        )


def write_markdown(day: str, rows: list[dict], path: str) -> None:
    """The same study as a file, so a day can be read without the database."""
    catchable = [r for r in rows if r["mins_to_1pct"] is not None]
    clean = [r for r in rows if r["clean_1pct"]]
    by_level: dict[str, list[dict]] = {}
    for r in rows:
        by_level.setdefault(r["level_broken"] or "no level broken", []).append(r)

    lines = [
        f"# Intraday Boost behaviour -- {day}",
        "",
        f"{len(rows)} symbols studied. {len(catchable)} reached +1% after their turn; "
        f"{len(clean)} got there without first giving back {HEAT_LIMIT_PCT}%.",
        "",
        "## What gave way at the turn",
        "",
        "| level | symbols | reached +1% | median minutes |",
        "| --- | ---: | ---: | ---: |",
    ]
    for level, group in sorted(by_level.items(), key=lambda kv: -len(kv[1])):
        hit = [g for g in group if g["mins_to_1pct"] is not None]
        med = statistics.median([g["mins_to_1pct"] for g in hit]) if hit else None
        lines.append(
            f"| {level} | {len(group)} | {len(hit)} | {int(med) if med is not None else '-'} |"
        )

    lines += [
        "",
        "## Every symbol",
        "",
        "| symbol | turn | level broken | vol x | +1% | +2% | heat % | run % | gave back % | day % |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for r in sorted(rows, key=lambda r: (r["mins_to_1pct"] is None, r["mins_to_1pct"] or 0)):
        t = r["trigger_min"]
        lines.append(
            f"| {r['symbol']} | {t // 60:02d}:{t % 60:02d} | {r['level_broken'] or '-'} | "
            f"{r['vol_ratio']} | {r['mins_to_1pct'] if r['mins_to_1pct'] is not None else '-'} | "
            f"{r['mins_to_2pct'] if r['mins_to_2pct'] is not None else '-'} | {r['mae_pct']} | "
            f"{r['run_move_pct']} | {r['run_adverse_pct']} | {r['day_move_pct']} |"
        )
    with open(path, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"wrote {path}")


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    day = args[0] if args else datetime.now(IST).strftime("%Y-%m-%d")
    after = DEFAULT_ENTRY_AFTER
    for i, a in enumerate(sys.argv):
        if a == "--after" and i + 1 < len(sys.argv):
            after = sys.argv[i + 1]
    hour, minute = (int(x) for x in after.split(":"))
    entry_after_min = hour * 60 + minute
    options_only = "--all" not in sys.argv

    print(
        f"Intraday Boost behaviour study -- {day}, entries from {after}"
        f"{' (option underlyings only)' if options_only else ''}\n"
    )
    rows = analyse(day, entry_after_min)
    if options_only:
        rows = [r for r in rows if r["has_options"]]
    report(rows)
    if "--report" not in sys.argv and rows:
        written = upsert_behaviour(rows)
        print(
            f"\nstored {written} rows in tf_boost_behaviour (day={day}, from {after}); "
            "re-running replaces them"
        )
        out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "log")
        os.makedirs(out_dir, exist_ok=True)
        write_markdown(
            day,
            rows,
            os.path.join(out_dir, f"tf_boost_behaviour_{day}_{after.replace(':', '')}.md"),
        )


if __name__ == "__main__":
    main()
