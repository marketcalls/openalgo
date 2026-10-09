# services/strategy_attribution.py
"""Split broker positions / holdings into per-strategy slices.

The broker nets positions per symbol and
carries no strategy label; the strategy book (database/strategy_book_db.py)
keeps a parallel per-strategy book. This module joins the two.

Pure and I/O-free, in the style of services/risk/: every input is an argument,
every decision is a return value. Every consumer (the React Positions and
Holdings pages, AlgoMirror later) reads this one answer rather than
re-deriving it.

Rules:
* The broker row is the truth for how much is held; legs only say who owns it.
* A leg is matched on (symbol, exchange, product) for positions and on
  (symbol, exchange) with product CNC for holdings. A flat position leg that
  realized P&L today becomes a zero-quantity slice carrying that figure.
* Slices never sum to more than the broker quantity. Whatever the legs do not
  explain becomes an `Unattributed` slice (manual trades, pre-OpenAlgo
  holdings, a book that drifted).
* Legs that cannot be reconciled with the broker row (opposite sign, or larger
  than the broker quantity) are not netted silently: the row is flagged
  `mismatch` with a reason.
"""

from typing import Any

UNATTRIBUTED = "Unattributed"

KIND_POSITIONS = "positions"
KIND_HOLDINGS = "holdings"

_EPS = 1e-9


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def holding_total_quantity(row: dict[str, Any]) -> float:
    """Total shares held: free + T1 (unsettled) + pledged, matching the
    Holdings page's own totalQty(). Brokers that do not report T1 or pledged
    quantity simply contribute zero for them."""
    return _f(row.get("quantity")) + _f(row.get("t1_quantity")) + _f(row.get("pledged_quantity"))


def _row_key(row: dict[str, Any], kind: str) -> tuple:
    if kind == KIND_HOLDINGS:
        return (row.get("symbol"), row.get("exchange"))
    return (row.get("symbol"), row.get("exchange"), row.get("product"))


def _index_legs(legs: list[dict[str, Any]], kind: str) -> dict[tuple, list[dict[str, Any]]]:
    """Legs worth attributing, grouped by match key: open legs, plus (positions
    only) flat legs that realized P&L today - a strategy that exited intraday
    still owns that day's result even though it holds nothing now."""
    index: dict[tuple, list[dict[str, Any]]] = {}
    for leg in legs or []:
        is_open = abs(_f(leg.get("quantity"))) > _EPS
        realized_today = abs(_f(leg.get("today_realized_pnl"))) > _EPS
        if kind == KIND_HOLDINGS:
            if not is_open or leg.get("product") != "CNC":
                continue
            key = (leg.get("symbol"), leg.get("exchange"))
        else:
            if not (is_open or realized_today):
                continue
            key = (leg.get("symbol"), leg.get("exchange"), leg.get("product"))
        index.setdefault(key, []).append(leg)
    return index


def _slice(leg: dict[str, Any], quantity: float, average_price: float) -> dict[str, Any]:
    return {
        "strategy": leg.get("strategy") or UNATTRIBUTED,
        "quantity": quantity,
        "average_price": average_price,
        "today_realized_pnl": _f(leg.get("today_realized_pnl")),
        "attributed": bool(leg.get("strategy")),
    }


def attribute_row(
    row: dict[str, Any], legs_for_key: list[dict[str, Any]], kind: str
) -> dict[str, Any]:
    """Slices for one broker row. `legs_for_key` are the legs that match it
    (see _index_legs)."""
    broker_qty = holding_total_quantity(row) if kind == KIND_HOLDINGS else _f(row.get("quantity"))
    broker_avg = _f(row.get("average_price"))

    result = {
        "symbol": row.get("symbol"),
        "exchange": row.get("exchange"),
        "product": row.get("product"),
        "quantity": broker_qty,
        "average_price": broker_avg,
        "slices": [],
        "mismatch": False,
        "mismatch_reason": None,
        # Set only for a row that is flat at the broker: the one strategy with
        # activity on it (still shown holding it, or realized P&L today), the
        # owner of whatever realized P&L the slices do not explain.
        "leftover_owner": None,
    }

    def by_strategy(item: dict[str, Any]) -> str:
        return str(item.get("strategy") or "")

    # Flat legs that realized P&L today: zero-quantity slices, so the day's
    # result is shown under the strategy that earned it.
    flat_today = [leg for leg in legs_for_key if abs(_f(leg.get("quantity"))) <= _EPS]
    open_legs = [leg for leg in legs_for_key if abs(_f(leg.get("quantity"))) > _EPS]

    if abs(broker_qty) <= _EPS:
        # Flat at the broker: any open leg is a stale book entry and owns no
        # quantity. If exactly one strategy has activity on this contract (a
        # stale open leg, or realized P&L today) it is named as the owner of
        # whatever realized P&L the slices do not explain, e.g. the broker
        # valuing a carried position at a different cost than the real fills.
        # Two or more strategies is ambiguous and stays Unattributed.
        for leg in sorted(flat_today, key=by_strategy):
            result["slices"].append(_slice(leg, 0.0, 0.0))
        owners = {leg.get("strategy") for leg in open_legs + flat_today if leg.get("strategy")}
        if len(owners) == 1:
            result["leftover_owner"] = next(iter(owners))
        if open_legs:
            # The book thinks something is still open that the broker has closed.
            result["mismatch"] = True
            result["mismatch_reason"] = (
                "the strategy book still shows an open leg on a position the broker has closed"
            )
        return result

    direction = 1.0 if broker_qty > 0 else -1.0

    # Strategies hedging each other on one contract (A long 100, B short 40,
    # broker net +60). The broker only shows the net, so the legs are taken as
    # they are, gross, when they reconcile with it: their signed sum lies on
    # the broker's side and does not exceed it. Anything left is Unattributed.
    # A book that disagrees with the broker (net on the other side, or larger)
    # falls through to the capping below and is flagged.
    net = sum(_f(leg.get("quantity")) for leg in open_legs)
    has_opposite = any(_f(leg.get("quantity")) * direction < 0 for leg in open_legs)
    if has_opposite and net * direction >= 0 and abs(net) <= abs(broker_qty) + _EPS:
        legs_notional = 0.0
        for leg in sorted(open_legs, key=by_strategy):
            leg_qty = _f(leg.get("quantity"))
            leg_avg = _f(leg.get("average_price"))
            result["slices"].append(_slice(leg, leg_qty, leg_avg))
            legs_notional += leg_qty * leg_avg
        remainder = broker_qty - net
        if abs(remainder) > _EPS:
            rem_avg = (broker_avg * broker_qty - legs_notional) / remainder
            if rem_avg <= 0:
                rem_avg = broker_avg
            result["slices"].append(
                {
                    "strategy": UNATTRIBUTED,
                    "quantity": remainder,
                    "average_price": rem_avg,
                    "today_realized_pnl": 0.0,
                    "attributed": False,
                }
            )
        for leg in sorted(flat_today, key=by_strategy):
            result["slices"].append(_slice(leg, 0.0, 0.0))
        return result

    remaining = broker_qty
    attributed_notional = 0.0
    reasons: list[str] = []

    same_side = [leg for leg in open_legs if _f(leg.get("quantity")) * direction > 0]
    if len(same_side) != len(open_legs):
        reasons.append("a strategy leg holds the opposite side of the broker position")

    # Deterministic order so a book that over-claims always trims the same leg.
    for leg in sorted(same_side, key=by_strategy):
        if abs(remaining) <= _EPS:
            reasons.append("strategy legs exceed the broker quantity")
            break
        leg_qty = abs(_f(leg.get("quantity")))
        take = min(leg_qty, abs(remaining))
        if leg_qty - take > _EPS:
            reasons.append("strategy legs exceed the broker quantity")
        leg_avg = _f(leg.get("average_price"))
        result["slices"].append(_slice(leg, direction * take, leg_avg))
        attributed_notional += take * leg_avg
        remaining -= direction * take

    if abs(remaining) > _EPS:
        # Back out the remainder's cost so the slices' notional adds up to the
        # broker's own. Falls back to the broker average if that goes negative
        # (a book whose average price disagrees with the broker's).
        rem_abs = abs(remaining)
        rem_avg = (broker_avg * abs(broker_qty) - attributed_notional) / rem_abs
        if rem_avg <= 0:
            rem_avg = broker_avg
        result["slices"].append(
            {
                "strategy": UNATTRIBUTED,
                "quantity": remaining,
                "average_price": rem_avg,
                "today_realized_pnl": 0.0,
                "attributed": False,
            }
        )

    for leg in sorted(flat_today, key=by_strategy):
        result["slices"].append(_slice(leg, 0.0, 0.0))

    if reasons:
        result["mismatch"] = True
        result["mismatch_reason"] = "; ".join(dict.fromkeys(reasons))
    return result


def attribute(rows: list[dict[str, Any]], legs: list[dict[str, Any]], kind: str) -> dict[str, Any]:
    """Attribute every broker row. Returns the rows plus the sorted list of
    strategy names that own part of any of them (for filter dropdowns)."""
    if kind not in (KIND_POSITIONS, KIND_HOLDINGS):
        raise ValueError(f"kind must be '{KIND_POSITIONS}' or '{KIND_HOLDINGS}'")

    index = _index_legs(legs, kind)
    out_rows = [attribute_row(row, index.get(_row_key(row, kind), []), kind) for row in rows or []]
    # By the `attributed` flag, not the label: a real strategy that happens to be
    # named like the synthetic remainder is still a strategy.
    strategies = sorted({s["strategy"] for r in out_rows for s in r["slices"] if s["attributed"]})

    return {"kind": kind, "rows": out_rows, "strategies": strategies}
