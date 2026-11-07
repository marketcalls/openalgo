# services/pnl_curve.py
"""Daily realized and unrealized P&L per strategy, for the P&L Analysis page.

Pure and I/O-free, like services/risk/: every input is an argument, every result is a return
value. services/pnl_history_service.py reads the fills and the daily closes and
calls this.

Two series per strategy, on every trading day of the range:

    realized[d]    P&L booked on day d by lots closed on d (a daily amount).
    unrealized[d]  Open lots at the close of d, each valued at
                   side * qty * (close[d] - cost) (a level, not a flow).

Combined is realized (cumulative) plus the unrealized level. Its daily change
is the day's true mark-to-market.

Basis decides each lot's `cost`:

    "actual_cost"   the fill price. Same as the broker's own P&L report: a lot
                    bought before the range books its whole gain on the day it
                    is sold, including the part earned before the range.
    "range_start"   a lot opened before the range is valued from the close of
                    the last trading day before the range, so the window holds
                    only what was earned inside it, and adjacent ranges add up.

Equity only. Corporate actions are not adjusted for: the caller is expected to
have exited before one (flagged as a known gap, not handled here).
"""

from collections import deque
from datetime import date, datetime, timedelta

from utils.pnl_fifo import collapse_same_day

BASIS_ACTUAL_COST = "actual_cost"
BASIS_RANGE_START = "range_start"
VALID_BASES = (BASIS_ACTUAL_COST, BASIS_RANGE_START)

UNTAGGED = "Untagged"

_EPS = 1e-9


def _day(value) -> date:
    return value.date() if isinstance(value, datetime) else value


def _name(strategy) -> str:
    return strategy or UNTAGGED


def _exchanges_by_symbol(fills: list[dict]) -> dict[str, str]:
    """One price exchange per symbol: NSE when the symbol ever traded there.

    NSE and BSE are one security for cash equity, so a position is one queue,
    valued once at one exchange's close.
    """
    chosen: dict[str, str] = {}
    for fill in fills:
        symbol, exchange = fill["symbol"], fill["exchange"]
        if symbol not in chosen or exchange == "NSE":
            chosen[symbol] = exchange
    return chosen


def _price_exchange(by_symbol: dict[str, str], fill: dict) -> str:
    return by_symbol.get(fill["symbol"], fill["exchange"])


def symbols_needing_closes(fills: list[dict], base_date: date, end: date) -> set[tuple]:
    """(symbol, exchange) pairs that are held at the close of at least one day
    in [base_date, end]. Only these need a daily close from the broker.

    `fills` must be in time order. A fill is signed by action; a position that
    is flat at every close inside the range is never priced.
    """
    per_key: dict[tuple, list[tuple[date, float]]] = {}
    exchange_of = _exchanges_by_symbol(fills)
    for fill in fills:
        sign = 1.0 if (fill.get("action") or "").upper() == "BUY" else -1.0
        per_key.setdefault((fill["symbol"], exchange_of[fill["symbol"]]), []).append(
            (_day(fill["timestamp"]), sign * float(fill.get("quantity") or 0))
        )

    needed = set()
    for key, items in per_key.items():
        net = 0.0
        i = 0
        while i < len(items):
            day = items[i][0]
            while i < len(items) and items[i][0] == day:
                net += items[i][1]
                i += 1
            if abs(net) <= _EPS or day > end:
                continue
            following = items[i][0] if i < len(items) else None
            lo = max(day, base_date)
            hi = end if following is None else min(end, following - timedelta(days=1))
            if lo <= hi:
                needed.add(key)
                break
    return needed


def _close_on(closes: dict[date, float], day: date, history: list[date]) -> float | None:
    """The close on `day`, else the last known close before it, else None."""
    if day in closes:
        return closes[day]
    prior = [d for d in history if d <= day]
    return closes[prior[-1]] if prior else None


def _series(store: dict, name: str, n: int) -> list[float]:
    if name not in store:
        store[name] = [0.0] * n
    return store[name]


def _drop_stale_shorts(shorts, before: date, key, notes) -> None:
    """Remove shorts opened before `before`.

    Cash equity cannot be carried short overnight, so a short that is still
    open the day after it was opened is a sell whose buy is older than the
    ledger. It is reported and dropped; keeping it would invent a position.
    A sell that is covered by a buy the same day (an intraday short) is closed
    by FIFO before this runs and is never touched.
    """
    kept = [lot for lot in shorts if lot["opened"] >= before]
    if len(kept) == len(shorts):
        return
    for lot in shorts:
        if lot["opened"] < before:
            notes["orphan_sells"].append({"symbol": key[0], "date": lot["opened"].isoformat()})
    shorts.clear()
    shorts.extend(kept)


def _apply_fill(fill, key, day_index, longs, shorts, realized, n, notes):
    action = (fill.get("action") or "").upper()
    qty = float(fill.get("quantity") or 0)
    price = float(fill.get("average_price") or 0)
    if qty <= 0 or action not in ("BUY", "SELL"):
        return
    _drop_stale_shorts(shorts, _day(fill["timestamp"]), key, notes)
    name = _name(fill.get("strategy"))
    is_buy = action == "BUY"
    opposing = shorts if is_buy else longs
    remaining = qty
    while remaining > _EPS and opposing:
        lot = opposing[0]
        matched = min(remaining, lot["qty"])
        pnl = lot["side"] * (price - lot["cost"]) * matched
        if day_index is not None:
            _series(realized, lot["strategy"], n)[day_index] += pnl
        lot["qty"] -= matched
        remaining -= matched
        if lot["qty"] <= _EPS:
            opposing.popleft()
    if remaining <= _EPS:
        return
    (longs if is_buy else shorts).append(
        {
            "qty": remaining,
            "price": price,
            "cost": price,
            "side": 1.0 if is_buy else -1.0,
            "strategy": name,
            "opened": _day(fill["timestamp"]),
        }
    )


def build_curve(
    fills: list[dict],
    closes: dict[tuple, dict[date, float]],
    trading_dates: list[date],
    base_date: date | None,
    basis: str = BASIS_RANGE_START,
) -> dict:
    """The per-strategy realized and unrealized series.

    fills          time-ordered dicts: symbol, exchange, action, quantity,
                   average_price, timestamp, product, strategy. Must include
                   every fill from before the range (the lots being carried).
    closes         {(symbol, exchange): {date: close}}; needs `base_date` and
                   every day a position is held.
    trading_dates  the days of the range, ascending.
    base_date      the last trading day before the range (for "range_start").

    Returns {"dates", "by_strategy": {name: {"realized", "unrealized"}},
    "notes": {...}}.
    """
    if basis not in VALID_BASES:
        raise ValueError(f"basis must be one of {VALID_BASES}")
    if not trading_dates:
        return {"dates": [], "by_strategy": {}, "notes": _notes()}

    first_day = trading_dates[0]
    notes = _notes()
    fills_by_symbol = _exchanges_by_symbol(fills)

    # Group fills per instrument, in order.
    per_key: dict[tuple, list[dict]] = {}
    for fill in fills:
        per_key.setdefault((fill["symbol"], _price_exchange(fills_by_symbol, fill)), []).append(
            fill
        )

    n = len(trading_dates)
    realized: dict[str, list[float]] = {}
    unrealized: dict[str, list[float]] = {}

    for key, key_fills in per_key.items():
        key_closes = closes.get(key, {})
        history = sorted(key_closes)

        # Same-day round trips are settled first, as Console does; only the
        # leftover reaches the carried-lot queues.
        intraday, key_fills = collapse_same_day(key_fills, "timestamp")
        for item in intraday:
            booked_on = _day(item["exit_timestamp"])
            day_index = next((i for i, d in enumerate(trading_dates) if d >= booked_on), None)
            if booked_on >= first_day and day_index is not None:
                _series(realized, _name(item["strategy"]), n)[day_index] += item["realized_pnl"]
        longs: deque[dict] = deque()
        shorts: deque[dict] = deque()
        idx = 0

        # Everything before the range builds the carried lots; none of it is booked.
        while idx < len(key_fills) and _day(key_fills[idx]["timestamp"]) < first_day:
            _apply_fill(key_fills[idx], key, None, longs, shorts, realized, n, notes)
            idx += 1

        _drop_stale_shorts(shorts, first_day, key, notes)

        # Re-base the lots carried into the range.
        if basis == BASIS_RANGE_START:
            base_close = None
            if base_date is not None:
                base_close = _close_on(key_closes, base_date, history)
            for lot in [*longs, *shorts]:
                if base_close is not None:
                    lot["cost"] = base_close
                else:
                    notes["missing_base"].append(key[0])

        for day_index, day in enumerate(trading_dates):
            while idx < len(key_fills) and _day(key_fills[idx]["timestamp"]) <= day:
                _apply_fill(key_fills[idx], key, day_index, longs, shorts, realized, n, notes)
                idx += 1
            _drop_stale_shorts(shorts, day + timedelta(days=1), key, notes)
            open_lots = [*longs, *shorts]
            if not open_lots:
                continue
            close = _close_on(key_closes, day, history)
            if close is None:
                notes["missing_close"].append(key[0])
                continue
            for lot in open_lots:
                _series(unrealized, lot["strategy"], n)[day_index] += (
                    lot["side"] * lot["qty"] * (close - lot["cost"])
                )

    names = sorted(set(realized) | set(unrealized))
    by_strategy = {
        name: {
            "realized": [round(v, 2) for v in realized.get(name, [0.0] * n)],
            "unrealized": [round(v, 2) for v in unrealized.get(name, [0.0] * n)],
        }
        for name in names
    }
    notes["orphan_sells"] = notes["orphan_sells"][:50]
    notes["missing_close"] = sorted(set(notes["missing_close"]))
    notes["missing_base"] = sorted(set(notes["missing_base"]))
    return {
        "dates": [d.isoformat() for d in trading_dates],
        "by_strategy": by_strategy,
        "notes": notes,
    }


def _notes() -> dict:
    return {"orphan_sells": [], "missing_close": [], "missing_base": []}
