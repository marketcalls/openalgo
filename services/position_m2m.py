# services/position_m2m.py
"""Today's mark-to-market (M2M) per position, from fills and yesterday's close.

Pure and I/O-free, like services/risk/: every
input is an argument, every decision is a return value.

M2M is today's move only. A position opened today is measured from its fills;
a position carried overnight is measured from the previous close:

    m2m = (sell value - buy value, today's fills)
          + end quantity * LTP
          - overnight quantity * previous close

Checked against real rows from two brokers, all exact to the paisa: Zerodha's
`m2m` field, and Kotak's `pnl`, which for a carried leg is already the day's M2M.
It is computed here, not read from the broker, so it works for every broker that
gives today's fills and a previous close, and needs no change to any broker
mapping.

The result is split in two so a page can keep it live between polls:
`m2m_fixed` does not depend on LTP, and `m2m = m2m_fixed + end_qty * ltp`.

Limit: only exchanges whose price multiplier is 1 (equity and index F&O) are
computed. Commodity and currency rows come back unavailable rather than wrong.
"""

from typing import Any

SUPPORTED_EXCHANGES = {"NSE", "BSE", "NFO", "BFO"}

_EPS = 1e-9


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _key(row: dict[str, Any]) -> tuple:
    return (row.get("symbol"), row.get("exchange"), row.get("product"))


def compute_m2m(
    positions: list[dict[str, Any]],
    trades: list[dict[str, Any]],
    prev_closes: dict[tuple, float | None],
) -> dict[tuple, dict[str, Any]]:
    """M2M for every position row, keyed by (symbol, exchange, product).

    `prev_closes` is keyed by (symbol, exchange). Each result holds:
    `available`, `reason` (when not), `m2m_fixed`, `m2m`, `overnight_quantity`,
    `prev_close`.
    """
    buys: dict[tuple, float] = {}
    sells: dict[tuple, float] = {}
    buy_qty: dict[tuple, float] = {}
    sell_qty: dict[tuple, float] = {}
    for trade in trades or []:
        key = _key(trade)
        qty = _f(trade.get("quantity"))
        value = qty * _f(trade.get("average_price"))
        action = str(trade.get("action") or "").upper()
        if action == "BUY":
            buys[key] = buys.get(key, 0.0) + value
            buy_qty[key] = buy_qty.get(key, 0.0) + qty
        elif action == "SELL":
            sells[key] = sells.get(key, 0.0) + value
            sell_qty[key] = sell_qty.get(key, 0.0) + qty

    results: dict[tuple, dict[str, Any]] = {}
    for position in positions or []:
        key = _key(position)
        end_qty = _f(position.get("quantity"))
        ltp = _f(position.get("ltp"))
        # Whatever the end quantity is beyond today's net fills was carried in.
        overnight = end_qty - (buy_qty.get(key, 0.0) - sell_qty.get(key, 0.0))
        prev_close = prev_closes.get((position.get("symbol"), position.get("exchange")))

        result: dict[str, Any] = {
            "available": False,
            "reason": None,
            "m2m_fixed": None,
            "m2m": None,
            "overnight_quantity": overnight,
            "prev_close": prev_close,
        }
        if position.get("exchange") not in SUPPORTED_EXCHANGES:
            result["reason"] = "exchange not supported for M2M"
        elif abs(overnight) > _EPS and not (prev_close and prev_close > 0):
            result["reason"] = "previous close unavailable for a carried position"
        elif abs(end_qty) > _EPS and ltp <= 0:
            result["reason"] = "no live price to mark the open quantity"
        else:
            fixed = sells.get(key, 0.0) - buys.get(key, 0.0)
            if abs(overnight) > _EPS:
                fixed -= overnight * prev_close
            result.update(
                available=True,
                m2m_fixed=round(fixed, 4),
                m2m=round(fixed + end_qty * ltp, 2),
            )
        results[key] = result
    return results
