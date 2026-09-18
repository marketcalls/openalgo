"""Reconstruct the prices the recorder missed, from the broker's own candles.

The run engine measures a move from where it turned, so a series that begins
late measures the wrong thing. On 18-Sep-2026 the machine slept until 10:04 and
INDHOTEL -- the list's number one, up 1.94% on the day having given back 0.47 --
read as a DOWN move of 0.39, because the only data was a late pullback. Nothing
badged for the first twenty minutes and what would have badged was inverted.

This fills the hole from 1-minute candles, into its own table. It never writes
to tf_boost_snapshots: those rows are the record of what the ranked list showed
at a minute, and a candle cannot say whether a symbol was on the list or where
it stood. A reconstruction mixed in would corrupt the one thing they are for.

Rank is not reconstructed for the same reason, so a symbol's rank history still
begins when recording did. Only the price path is repaired, which is what the
run engine reads.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from database.auth_db import get_auth_token_broker, get_first_available_api_key
from database.tf_boost_db import get_connection, init_price_backfill_table, upsert_price_backfill
from services.history_service import get_history
from services.tf_symbol_alias import tradable_symbol
from utils.logging import get_logger

logger = get_logger(__name__)

IST = ZoneInfo("Asia/Kolkata")
SESSION_OPEN_MIN = 9 * 60 + 15
# Below this the hole is not worth a few hundred broker calls: the run engine
# needs ten observations and tolerates a gap by widening its own denominator.
MIN_GAP_MINUTES = 10


def _previous_close(symbol: str, day: str, auth_token: str, broker: str) -> float | None:
    """Yesterday's close, which is what a change percentage is measured against."""
    start = (datetime.strptime(day, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")
    ok, res, _ = get_history(
        symbol, "NSE", "D", start, day, auth_token=auth_token, broker=broker, source="api"
    )
    candles = (res.get("data") if isinstance(res, dict) else None) or []
    if not ok or len(candles) < 2:
        return None
    return float(candles[-2]["close"])


def backfill_day(day: str | None = None, list_type: str = "intraday_boost") -> dict:
    """Fill the pre-recording part of `day` for every symbol seen on the list.

    Returns a summary rather than raising: this runs at startup and must never
    be the reason the app does not come up.
    """
    day = day or datetime.now(IST).strftime("%Y-%m-%d")
    summary = {"day": day, "gap_minutes": 0, "symbols": 0, "rows": 0, "skipped": []}
    try:
        init_price_backfill_table()
        with get_connection() as conn:
            first = conn.execute(
                "SELECT min(hour(snapshot_time) * 60 + minute(snapshot_time)) "
                "FROM tf_boost_snapshots WHERE snapshot_date = ? AND list_type = ?",
                [day, list_type],
            ).fetchone()[0]
            if first is None:
                return summary
            symbols = [
                r[0]
                for r in conn.execute(
                    "SELECT DISTINCT symbol FROM tf_boost_snapshots "
                    "WHERE snapshot_date = ? AND list_type = ?",
                    [day, list_type],
                ).fetchall()
            ]
            already = {
                r[0]
                for r in conn.execute(
                    "SELECT DISTINCT symbol FROM tf_boost_price_backfill WHERE day = ?", [day]
                ).fetchall()
            }

        gap = int(first) - SESSION_OPEN_MIN
        summary["gap_minutes"] = max(0, gap)
        if gap < MIN_GAP_MINUTES:
            return summary

        todo = [s for s in symbols if s not in already]
        if not todo:
            return summary

        api_key = get_first_available_api_key()
        auth_token, broker = get_auth_token_broker(api_key, include_feed_token=False)
        logger.info(
            f"TF Boost backfill: {gap} minutes missing before {int(first) // 60:02d}:"
            f"{int(first) % 60:02d}, reconstructing {len(todo)} symbols from 1m candles"
        )

        for symbol in todo:
            tradable = tradable_symbol(symbol)
            try:
                prev_close = _previous_close(tradable, day, auth_token, broker)
                if not prev_close:
                    summary["skipped"].append(f"{symbol}(no previous close)")
                    continue
                ok, res, _ = get_history(
                    tradable,
                    "NSE",
                    "1m",
                    day,
                    day,
                    auth_token=auth_token,
                    broker=broker,
                    source="api",
                )
                candles = (res.get("data") if isinstance(res, dict) else None) or []
                if not ok or not candles:
                    summary["skipped"].append(f"{symbol}(no candles)")
                    continue
                rows = []
                for bar in candles:
                    stamp = datetime.fromtimestamp(bar["timestamp"], IST)
                    minute = stamp.hour * 60 + stamp.minute
                    # Only the hole: a recorded minute is the real thing and wins.
                    if minute < SESSION_OPEN_MIN or minute >= int(first):
                        continue
                    rows.append(
                        (day, symbol, minute, (float(bar["close"]) - prev_close) / prev_close * 100)
                    )
                summary["rows"] += upsert_price_backfill(rows)
                if rows:
                    summary["symbols"] += 1
            except Exception as e:  # noqa: BLE001 -- one symbol must not stop the repair
                summary["skipped"].append(f"{symbol}({e.__class__.__name__})")

        logger.info(
            f"TF Boost backfill: filled {summary['rows']} minutes across "
            f"{summary['symbols']} symbols"
            + (f", skipped {len(summary['skipped'])}" if summary["skipped"] else "")
        )
    except Exception as e:
        logger.exception(f"TF Boost backfill failed: {e}")
    return summary
