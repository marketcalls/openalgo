"""
Per-strategy realized / unrealized / total P&L.

The broker - and OpenAlgo's own position book - nets positions per
`(symbol, exchange, product)` and carries no strategy label, so a position
alone cannot answer "how is *this* strategy doing?". Two strategies trading
the same contract are indistinguishable downstream.

`database/strategy_book_db.py` keeps a parallel book keyed by strategy, fed
from the event bus. This module reads it:

* **realized** - taken from the book, which accumulates across sessions and
  survives restarts
* **unrealized** - computed here by marking open quantity to the position
  book's last traded price, because a stored value would be stale the instant
  it was written
* **total** - realized + unrealized (plus `today_realized` / `today_total`
  for intraday exits)

Accounting convention: weighted-average cost, where a position flipping
through zero realizes the closed leg and reopens the remainder at the fill
price.
"""

from typing import Any

from utils.logging import get_logger

logger = get_logger(__name__)


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def pnl_from_book(
    legs: list[dict[str, Any]],
    positions: list[dict[str, Any]] | None = None,
    strategy: str | None = None,
) -> dict[str, Any]:
    """Aggregate the persisted per-strategy legs into realized / unrealized /
    total, marking open quantity to the position book's last traded price.

    Realized comes from the book (it accumulates across sessions and survives
    restarts). Unrealized is computed here rather than stored, because it is a
    function of a price that changes continuously.
    """
    positions = positions or []
    # `ltp` is the standardized OpenAlgo position field (see
    # docs/api/account-services/positionbook.md); every broker mapper converts
    # its own raw field into it. `last_price` is accepted only as a fallback
    # for a mapper that passes the broker's name through unchanged.
    ltp_by_key = {
        (p.get("symbol"), p.get("exchange"), p.get("product")): _f(
            p.get("ltp") if p.get("ltp") is not None else p.get("last_price")
        )
        for p in positions
    }

    grouped: dict[str, dict[str, Any]] = {}
    for leg in legs:
        name = leg.get("strategy") or "untagged"
        if strategy and name != strategy:
            continue
        entry = grouped.setdefault(
            name,
            {
                "strategy": name,
                "realized": 0.0,
                "today_realized": 0.0,
                "unrealized": 0.0,
                "total": 0.0,
                "open_quantity": 0.0,
                "unpriced_legs": 0,
                "legs": [],
            },
        )

        qty = _f(leg.get("quantity"))
        avg = _f(leg.get("average_price"))
        realized = _f(leg.get("realized_pnl"))
        today_realized = _f(leg.get("today_realized_pnl"))

        key = (leg.get("symbol"), leg.get("exchange"), leg.get("product"))
        ltp = ltp_by_key.get(key)
        unrealized = 0.0
        if abs(qty) > 1e-9:
            if ltp is None:
                # Open per the book but absent from the position book, so it
                # cannot be marked to market. Surfaced rather than silently
                # counted as zero.
                entry["unpriced_legs"] += 1
            else:
                unrealized = qty * (ltp - avg)
            entry["open_quantity"] += qty

        entry["realized"] += realized
        entry["today_realized"] += today_realized
        entry["unrealized"] += unrealized
        entry["legs"].append(
            {
                "symbol": leg.get("symbol"),
                "exchange": leg.get("exchange"),
                "product": leg.get("product"),
                "quantity": round(qty, 4),
                "average_price": round(avg, 4),
                "ltp": ltp,
                "realized": round(realized, 4),
                "today_realized": round(today_realized, 4),
                "unrealized": round(unrealized, 4),
            }
        )

    for entry in grouped.values():
        entry["realized"] = round(entry["realized"], 4)
        entry["today_realized"] = round(entry["today_realized"], 4)
        entry["unrealized"] = round(entry["unrealized"], 4)
        entry["total"] = round(entry["realized"] + entry["unrealized"], 4)
        entry["today_total"] = round(entry["today_realized"] + entry["unrealized"], 4)
        entry["open_quantity"] = round(entry["open_quantity"], 4)

    if strategy:
        return grouped.get(
            strategy,
            {
                "strategy": strategy,
                "realized": 0.0,
                "today_realized": 0.0,
                "unrealized": 0.0,
                "total": 0.0,
                "today_total": 0.0,
                "open_quantity": 0.0,
                "unpriced_legs": 0,
                "legs": [],
            },
        )
    return grouped


def get_strategy_pnl(
    client, strategy: str | None = None, user_id: str | None = None
) -> dict[str, Any]:
    """Realized / unrealized / total P&L for one strategy, or all of them.

    Reads the persisted strategy book (authoritative for realized P&L and
    cost basis, and durable across restarts) and marks open quantity against
    a single position-book call for last traded prices.
    """
    from database.strategy_book_db import StrategyBookUnavailable, get_strategy_legs

    try:
        legs = get_strategy_legs(user_id=user_id, strategy=strategy)
    except StrategyBookUnavailable as exc:
        # An unreadable book is unknown, not empty. Reporting zero here would
        # look identical to a flat, healthy strategy to an exit trigger.
        logger.error(f"Strategy P&L unavailable: {exc}")
        return {"status": "error", "message": f"Strategy book unavailable: {exc}"}

    positions_resp = client.positionbook() or {}
    # Propagate rather than pricing against an empty book. A transient broker
    # failure would otherwise mark every open leg unpriced, report unrealized
    # as zero, and still return success - letting a workflow act on a total
    # that is materially wrong.
    if positions_resp.get("status") == "error":
        message = positions_resp.get("error") or positions_resp.get("message") or "unavailable"
        return {
            "status": "error",
            "message": f"Position book unavailable, cannot value open legs: {message}",
        }
    positions = positions_resp.get("data") or []
    if not isinstance(positions, list):
        positions = []

    result = pnl_from_book(legs, positions, strategy=strategy)
    if strategy:
        return {"status": "success", **result}
    return {"status": "success", "strategies": result, "count": len(result)}
