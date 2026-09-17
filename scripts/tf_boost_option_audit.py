"""Per-stock audit: what the badge said, what the stock did, what the option did.

    uv run python scripts/tf_boost_option_audit.py            # today
    uv run python scripts/tf_boost_option_audit.py 2026-09-17

For every symbol that earned a RUN badge, this reports:

  direction   what the badge called, from data available at that minute only
  stock       how far it went the badge's way, and how far it went the OTHER way
  option      the September ATM contract ON THE SIDE THE BADGE CALLED -- a call
              for an up badge, a put for a down one -- with its liquidity

Four checks are built in because each one is a mistake already made on this
data and caught by the person relying on it:

  1. the option side must match the badge direction (a call was once tested
     against a down badge, which "profited" precisely because the badge was wrong)
  2. travel from the turn is never reported as the stock's day move
  3. every snapshot price is checked against the broker's own traded range
  4. liquidity is reported, never assumed: volume, and bars that did not trade
"""

from __future__ import annotations

import os
import re
import statistics
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.auth_db import get_auth_token_broker, get_first_available_api_key  # noqa: E402
from database.symbol import SymToken, db_session  # noqa: E402
from database.tf_boost_db import (  # noqa: E402
    get_boost_change_timeline,
    get_boost_rank_timeline,
)
from services.history_service import get_history  # noqa: E402
from services.tf_rank_movement_service import compute_symbol_movement  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")
EXPIRY = os.getenv("TF_AUDIT_EXPIRY", "29SEP26")
ALIASES = {"TATAMOTORS": "TMPV"}
MIN_OPTION_VOLUME = 10_000  # below this the fill is not something to rely on
# Only stocks that were ON the ranked list in the morning. The day's cumulative
# universe is much wider -- a name that first appears at 14:00 was never on the
# list when the session's decisions were being made, and including it describes
# a list nobody was looking at.
MORNING_CUTOFF_MIN = 10 * 60


def first_badge(symbol, changes, ranks):
    """The first minute the panel would actually show RUN, using only data up
    to that minute.

    Asks the engine rather than reimplementing its rule. An earlier version of
    this script duplicated the logic and drifted: it counted 12 symbols as RUN
    badges that the engine labels LARGE_JUMP or EXTREME_JUMP, because those
    outrank a clean run and take the label. The panel never showed RUN for them,
    so auditing them as RUN badges described a screen nobody saw.
    """
    for i in range(10, len(changes)):
        upto = changes[i][0]
        row = compute_symbol_movement(
            symbol,
            [p for p in ranks if p[0] <= upto],
            upto,
            changes[: i + 1],
        )
        if row and row["event"] in ("CLEAN_RUN_UP", "CLEAN_RUN_DOWN"):
            return upto, row, changes[i][1]
    return None, None, None


def atm_contract(symbol, price, side):
    """Nearest strike on the given side for the configured expiry, or None."""
    rows = (
        db_session.query(SymToken.symbol)
        .filter(SymToken.exchange == "NFO", SymToken.symbol.like(f"{symbol}{EXPIRY}%{side}"))
        .all()
    )
    best = None
    for (name,) in rows:
        match = re.match(rf"^{re.escape(symbol)}{EXPIRY}([\d.]+){side}$", name)
        if match:
            strike = float(match.group(1))
            if best is None or abs(strike - price) < abs(best[1] - price):
                best = (name, strike)
    return best


def fetch_bars(symbol, exchange, day, auth_token, broker):
    ok, res, _ = get_history(
        symbol, exchange, "5m", day, day, auth_token=auth_token, broker=broker, source="api"
    )
    candles = (res.get("data") if isinstance(res, dict) else None) or []
    if not ok or not candles:
        return []
    return [(datetime.fromtimestamp(b["timestamp"], IST), b) for b in candles]


def outcome(bars, badge_min, direction):
    """Move the badge's way, and move the OTHER way, at traded prices."""
    before = [b for t, b in bars if t.hour * 60 + t.minute <= badge_min]
    after = [(t, b) for t, b in bars if t.hour * 60 + t.minute >= badge_min]
    if not before or len(after) < 2:
        return None
    entry = before[-1]["close"]
    up = direction == "up"
    with_it = against = 0.0
    minutes_to_1pct = None
    for t, b in after:
        gain = ((b["high"] - entry) if up else (entry - b["low"])) / entry * 100
        loss = ((entry - b["low"]) if up else (b["high"] - entry)) / entry * 100
        with_it, against = max(with_it, gain), max(against, loss)
        if minutes_to_1pct is None and gain >= 1.0:
            minutes_to_1pct = t.hour * 60 + t.minute - badge_min
    close = after[-1][1]["close"]
    close_pct = ((close - entry) if up else (entry - close)) / entry * 100
    return {
        "entry": round(entry, 2),
        "with_pct": round(with_it, 2),
        "against_pct": round(against, 2),
        "close_pct": round(close_pct, 2),
        "minutes_to_1pct": minutes_to_1pct,
        # The stock ran the opposite way if it never gave half a percent the
        # badge's way while giving at least that much against it.
        "ran_opposite": with_it < 0.5 <= against,
    }


def option_outcome(bars, badge_min):
    """Premium path for a long position opened at the badge, plus liquidity."""
    before = [b for t, b in bars if t.hour * 60 + t.minute <= badge_min]
    after = [b for t, b in bars if t.hour * 60 + t.minute >= badge_min]
    if not before or len(after) < 2:
        return None
    entry = before[-1]["close"]
    if entry <= 0:
        return None
    best = max(b["high"] for b in after)
    worst = min(b["low"] for b in after)
    volumes = [b["volume"] for b in after]
    # Nobody holds an option to the bell. Walk the bars in order and see which
    # came first, the target or the stop -- within a bar the stop is assumed to
    # hit first, which is the pessimistic reading and the honest one.
    paths = {}
    for target, stop in ((25, 25), (50, 25), (15, 15)):
        hit = None
        for b in after:
            if b["low"] <= entry * (1 - stop / 100):
                hit = "stopped"
                break
            if b["high"] >= entry * (1 + target / 100):
                hit = "target"
                break
        paths[f"t{target}s{stop}"] = hit or "neither"
    return {
        **paths,
        "premium": round(entry, 2),
        "best_pct": round((best - entry) / entry * 100),
        "worst_pct": round((worst - entry) / entry * 100),
        "close_pct": round((after[-1]["close"] - entry) / entry * 100),
        "volume": sum(volumes),
        "dead_bars": sum(1 for v in volumes if v == 0),
        "liquid": sum(volumes) >= MIN_OPTION_VOLUME and sum(1 for v in volumes if v == 0) <= 3,
    }


def price_integrity(snapshot_rows, bars, badge_min):
    """Check A: does the snapshot price sit inside the bar the stock traded in?"""
    ranges = {}
    for t, b in bars:
        ranges[(t.hour * 60 + t.minute)] = (b["low"], b["high"])
    checked = outside = 0
    for minute, ltp in snapshot_rows:
        if minute < badge_min:
            continue
        bucket = (minute // 5) * 5
        if bucket not in ranges:
            continue
        low, high = ranges[bucket]
        checked += 1
        if ltp < low * 0.999 or ltp > high * 1.001:
            outside += 1
    return checked, outside


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    day = args[0] if args else datetime.now(IST).strftime("%Y-%m-%d")
    changes, ranks = get_boost_change_timeline(day), get_boost_rank_timeline(day)
    if not changes:
        print(f"No snapshots for {day}.")
        return

    from database.tf_boost_db import get_connection

    with get_connection() as conn:
        ltp_rows = conn.execute(
            "SELECT symbol, hour(snapshot_time) * 60 + minute(snapshot_time), ltp "
            "FROM tf_boost_snapshots WHERE snapshot_date = ? AND list_type = 'intraday_boost' "
            "ORDER BY symbol, snapshot_time",
            [day],
        ).fetchall()
    ltps: dict[str, list] = {}
    for sym, minute, ltp in ltp_rows:
        ltps.setdefault(sym, []).append((minute, ltp))

    api_key = get_first_available_api_key()
    auth_token, broker = get_auth_token_broker(api_key, include_feed_token=False)

    results, problems = [], []
    # The whole intraday_boost list for the day. --morning narrows it to names
    # that were already on the list early, which on 17-Sep-2026 was 193 of 200
    # and therefore almost the same set.
    symbols = sorted(changes)
    if "--morning" in sys.argv:
        early = {
            sym
            for sym, days in ranks.items()
            if any(minute <= MORNING_CUTOFF_MIN for minute, _ in days.get(day, []))
        }
        symbols = [s for s in symbols if s in early]
    print(f"{len(symbols)} symbols on the intraday boost list for {day}\n")
    for n, symbol in enumerate(symbols, start=1):
        cps, rps = changes[symbol].get(day, []), ranks.get(symbol, {}).get(day, [])
        if len(cps) < 12 or not rps:
            continue
        badge_min, row, day_change = first_badge(symbol, cps, rps)
        if badge_min is None:
            continue

        stock_bars = fetch_bars(ALIASES.get(symbol, symbol), "NSE", day, auth_token, broker)
        if not stock_bars:
            problems.append(f"{symbol}: no stock candles")
            continue
        stock = outcome(stock_bars, badge_min, row["run_direction"])
        if not stock:
            problems.append(f"{symbol}: no stock bar at the badge minute")
            continue

        # CHECK 1: the option side must match the badge direction.
        side = "CE" if row["run_direction"] == "up" else "PE"
        contract = atm_contract(ALIASES.get(symbol, symbol), stock["entry"], side)
        option = None
        if contract is None:
            problems.append(f"{symbol}: no {EXPIRY} {side} contract")
        else:
            opt_bars = fetch_bars(contract[0], "NFO", day, auth_token, broker)
            if not opt_bars:
                problems.append(f"{symbol}: no candles for {contract[0]}")
            else:
                option = option_outcome(opt_bars, badge_min)
                if option:
                    option["name"] = contract[0]

        checked, outside = price_integrity(ltps.get(symbol, []), stock_bars, badge_min)
        results.append(
            {
                "symbol": symbol,
                "badge_min": badge_min,
                "direction": row["run_direction"],
                "side": side,
                "rank": row["current_rank"],
                "eff": row["run_efficiency"],
                "travel": row["run_move_pct"],
                "day_change": round(day_change, 2),
                "stock": stock,
                "option": option,
                "price_checked": checked,
                "price_outside": outside,
            }
        )
        if n % 40 == 0:
            print(f"  ... {n}/{len(symbols)}")

    db_session.remove()
    report(day, results, problems)


def report(day, results, problems):
    results.sort(key=lambda r: r["badge_min"])
    opposite = [r for r in results if r["stock"]["ran_opposite"]]
    with_opt = [r for r in results if r["option"]]
    liquid = [r for r in with_opt if r["option"]["liquid"]]

    print(
        f"\n{'=' * 104}\n{day} -- every RUN badge, the stock, and the September "
        f"option on the side the badge called\n{'=' * 104}\n"
    )
    header = (
        f"{'symbol':<12}{'badge':>6}{'dir':>5}{'rk':>4}{'day%':>7}{'travel':>7}"
        f"{'went its way':>13}{'went against':>13}{'opt':>5}{'premium':>9}"
        f"{'best':>7}{'worst':>7}{'close':>7}{'volume':>11}{'liq':>5}"
    )
    print(header)
    lines = []
    for r in results:
        s, o = r["stock"], r["option"]
        t = f"{r['badge_min'] // 60:02d}:{r['badge_min'] % 60:02d}"
        line = (
            f"{r['symbol']:<12}{t:>6}{r['direction']:>5}{r['rank']:>4}"
            f"{r['day_change']:>+7.2f}{r['travel']:>+7.2f}"
            f"{s['with_pct']:>+13.2f}{s['against_pct']:>+13.2f}{r['side']:>5}"
            + (
                f"{o['premium']:>9.2f}{o['best_pct']:>+6}%{o['worst_pct']:>+6}%"
                f"{o['close_pct']:>+6}%{o['volume']:>11,}{'yes' if o['liquid'] else 'NO':>5}"
                if o
                else f"{'-':>9}{'-':>7}{'-':>7}{'-':>7}{'-':>11}{'-':>5}"
            )
        )
        print(line)
        lines.append(line)

    print(f"\n{'-' * 104}")
    print(f"badges                         {len(results)}")
    print(
        f"ran the OPPOSITE way           {len(opposite)} "
        f"({len(opposite) / max(1, len(results)) * 100:.0f}%)  -- never gave 0.5% the badge's "
        f"way while giving 0.5% against"
    )
    print(f"September option found         {len(with_opt)}")
    print(
        f"of those, liquid               {len(liquid)} "
        f"(>= {MIN_OPTION_VOLUME:,} contracts, <= 3 bars without a trade)"
    )
    if liquid:
        closes = [r["option"]["close_pct"] for r in liquid]
        winners = [c for c in closes if c > 0]
        print(
            f"option held to the close: {len(winners)} of {len(liquid)} in profit, "
            f"median {statistics.median(closes):+.0f}%, best {max(closes):+.0f}%, "
            f"worst {min(closes):+.0f}%"
        )
        print("\noption traded with a target and a stop (liquid contracts only):")
        for key, target, stop in (("t15s15", 15, 15), ("t25s25", 25, 25), ("t50s25", 50, 25)):
            won = sum(1 for r in liquid if r["option"][key] == "target")
            lost = sum(1 for r in liquid if r["option"][key] == "stopped")
            flat = sum(1 for r in liquid if r["option"][key] == "neither")
            net = won * target - lost * stop
            print(
                f"   +{target}% target / {stop}% stop:  {won:>3} hit target, "
                f"{lost:>3} stopped, {flat:>3} neither   net {net:+d}% across "
                f"{len(liquid)} trades ({net / max(1, len(liquid)):+.1f}% each)"
            )
    checked = sum(r["price_checked"] for r in results)
    outside = sum(r["price_outside"] for r in results)
    print(
        f"price integrity                {checked:,} snapshot prices checked against the "
        f"broker's traded range, {outside} outside ({outside / max(1, checked) * 100:.2f}%)"
    )
    if problems:
        print(
            f"\nexcluded ({len(problems)}): "
            + "; ".join(problems[:10])
            + (" ..." if len(problems) > 10 else "")
        )

    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "log")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"tf_boost_option_audit_{day}.txt")
    with open(path, "w") as fh:
        fh.write(f"{day} -- RUN badges with the September option on the badge's own side\n\n")
        fh.write(header + "\n" + "\n".join(lines) + "\n")
    print(f"\nsaved to {path}")


if __name__ == "__main__":
    main()
