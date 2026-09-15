"""TF Boost snapshot query service — returns the day's full boost universe.

Backs the ISI backtest so it can run on every stock that was in the Intraday
Boost list at ANY point during the trading day(s), not just whatever is in the
live list right now (which drops morning-only movers like TECHM).

Reads the isolated tf_boost_snapshots DuckDB (written every 5 min during market
hours by services/tf_boost_snapshot_service.py). Degrades to an empty list — the
caller then falls back to the live list — so a missing/empty table is never an
error the client has to handle.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from database.auth_db import get_auth_token_broker
from database.tf_boost_db import (
    get_boost_price_timeline,
    get_boost_rank_timeline,
    get_boost_symbols,
)
from utils.logging import get_logger

logger = get_logger(__name__)


def boost_universe_service(
    api_key: str,
    date: str,
    lookback_days: int = 1,
    list_type: str = "intraday_boost",
    rank_as_of: str = "",
    include_ranks: bool = False,
    include_prices: bool = False,
) -> tuple[bool, dict, int]:
    """Validate the API key and return the union of boost-list symbols for the
    [date - (lookback_days - 1), date] window. Returns (success, response, http)."""
    auth_token, _feed_token, _broker = get_auth_token_broker(api_key, include_feed_token=True)
    if auth_token is None:
        return False, {"status": "error", "message": "Invalid openalgo apikey"}, 403

    try:
        end = datetime.strptime(date, "%Y-%m-%d").date()
        start = end - timedelta(days=max(int(lookback_days), 1) - 1)
    except (ValueError, TypeError):
        return False, {"status": "error", "message": "date must be YYYY-MM-DD"}, 400

    start_str, end_str = start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")
    symbols = get_boost_symbols(start_str, end_str, list_type, rank_as_of or None)
    # Only sent when asked for: the full rank timeline is roughly (symbols x
    # snapshots) pairs — ~15k for one day, and it scales with lookbackDays.
    ranks = get_boost_rank_timeline(start_str, end_str, list_type) if include_ranks else None
    prices = get_boost_price_timeline(start_str, end_str, list_type) if include_prices else None
    return (
        True,
        {
            "status": "success",
            "date": end.strftime("%Y-%m-%d"),
            "start_date": start.strftime("%Y-%m-%d"),
            "list_type": list_type,
            "rank_as_of": rank_as_of or None,
            "count": len(symbols),
            "symbols": symbols,
            **({"ranks": ranks} if ranks is not None else {}),
            **({"prices": prices} if prices is not None else {}),
        },
        200,
    )
