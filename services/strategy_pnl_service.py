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

`pnl_from_book` is the primary path. `compute_strategy_pnl` is the
independent trade-replay implementation: it derives the same figures from
tagged tradebook rows without consulting the book, which makes it useful for
reconciling the book against the broker's own record of the session. Both
share one accounting convention - weighted-average cost, where a position
flipping through zero realizes the closed leg and reopens the remainder at
the fill price.
"""

from typing import Any

from utils.logging import get_logger

logger = get_logger(__name__)


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class _Book:
    """Weighted-average position accounting for one instrument."""

    __slots__ = ("qty", "avg", "realized")

    def __init__(self) -> None:
        self.qty = 0.0  # signed: positive long, negative short
        self.avg = 0.0  # average cost of the open quantity
        self.realized = 0.0

    def apply(self, signed_qty: float, price: float) -> None:
        if signed_qty == 0:
            return

        # Opening, or adding to an existing position in the same direction.
        if self.qty == 0 or (self.qty > 0) == (signed_qty > 0):
            total = abs(self.qty) + abs(signed_qty)
            self.avg = ((self.avg * abs(self.qty)) + (price * abs(signed_qty))) / total
            self.qty += signed_qty
            return

        # Reducing, closing, or flipping.
        closing = min(abs(signed_qty), abs(self.qty))
        direction = 1.0 if self.qty > 0 else -1.0
        self.realized += closing * (price - self.avg) * direction
        remaining = abs(signed_qty) - closing
        self.qty += signed_qty

        if abs(self.qty) < 1e-9:
            self.qty = 0.0
            self.avg = 0.0
        elif remaining > 0:
            # Flipped through zero: the leftover opens a fresh position.
            self.avg = price


def compute_strategy_pnl(
    trades: list[dict[str, Any]],
    positions: list[dict[str, Any]] | None = None,
    strategy: str | None = None,
) -> dict[str, Any]:
    """Aggregate realized / unrealized / total P&L per strategy.

    Args:
        trades: tradebook rows (need `strategy`, `symbol`, `exchange`,
            `product`, `action`, `quantity`, and `average_price` or `price`).
        positions: position-book rows, used only for last traded price and to
            detect positions carried over from a previous session.
        strategy: when given, only this strategy is returned.

    Returns a dict keyed by strategy name; each value carries `realized`,
    `unrealized`, `total`, `open_quantity`, `trade_count`, `carried_over` and
    a per-instrument `legs` breakdown.
    """
    positions = positions or []

    ltp_by_key: dict[tuple, float] = {}
    pos_by_key: dict[tuple, dict[str, Any]] = {}
    for row in positions:
        key = (row.get("symbol"), row.get("exchange"), row.get("product"))
        ltp_by_key[key] = _f(row.get("ltp"))
        pos_by_key[key] = row

    books: dict[str, dict[tuple, _Book]] = {}
    counts: dict[str, int] = {}

    for trade in trades:
        name = (trade.get("strategy") or "").strip() or "untagged"
        if strategy and name != strategy:
            continue
        key = (trade.get("symbol"), trade.get("exchange"), trade.get("product"))
        qty = abs(_f(trade.get("quantity")))
        if qty == 0:
            continue
        price = _f(trade.get("average_price")) or _f(trade.get("price"))
        signed = qty if str(trade.get("action", "")).upper() == "BUY" else -qty
        books.setdefault(name, {}).setdefault(key, _Book()).apply(signed, price)
        counts[name] = counts.get(name, 0) + 1

    out: dict[str, Any] = {}
    for name, per_key in books.items():
        realized = unrealized = 0.0
        open_qty = 0.0
        carried_over = False
        legs = []

        for key, book in per_key.items():
            realized += book.realized
            leg_unrealized = 0.0
            if abs(book.qty) > 1e-9:
                ltp = ltp_by_key.get(key)
                if ltp is None:
                    # Open per this strategy's trades but absent from the
                    # position book - cannot mark to market.
                    carried_over = True
                else:
                    leg_unrealized = book.qty * (ltp - book.avg)
                unrealized += leg_unrealized
                open_qty += book.qty
            legs.append(
                {
                    "symbol": key[0],
                    "exchange": key[1],
                    "product": key[2],
                    "quantity": round(book.qty, 4),
                    "average_price": round(book.avg, 4),
                    "ltp": ltp_by_key.get(key),
                    "realized": round(book.realized, 4),
                    "unrealized": round(leg_unrealized, 4),
                }
            )

        out[name] = {
            "strategy": name,
            "realized": round(realized, 4),
            "unrealized": round(unrealized, 4),
            "total": round(realized + unrealized, 4),
            "open_quantity": round(open_qty, 4),
            "trade_count": counts.get(name, 0),
            "carried_over": carried_over,
            "legs": legs,
        }

    if strategy:
        return out.get(
            strategy,
            {
                "strategy": strategy,
                "realized": 0.0,
                "unrealized": 0.0,
                "total": 0.0,
                "open_quantity": 0.0,
                "trade_count": 0,
                "carried_over": False,
                "legs": [],
            },
        )
    return out


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
    ltp_by_key = {
        (p.get("symbol"), p.get("exchange"), p.get("product")): _f(p.get("ltp")) for p in positions
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
    from database.strategy_book_db import get_strategy_legs

    legs = get_strategy_legs(user_id=user_id, strategy=strategy)
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
