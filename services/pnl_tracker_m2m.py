# services/pnl_tracker_m2m.py
"""Intraday M2M curve for the P&L Tracker, on the same basis as the Positions page.

blueprints/pnltracker.py calls `build_m2m_tracker_response` first and falls back
to its own code when this returns None.

Two bases, as on the Positions page (the switch there and on the tracker page):

* "m2m": today's move only, carried positions measured from the previous close.
* "pnl": the broker's own P&L. A carried position's cost is taken from the
  broker's figure (its carried cost, which on Zerodha can differ from the real
  fill), so the curve ends on the Positions page's P&L. Still per symbol and
  product, so the grouping bug is gone in this view too.

Why it exists: the tracker keys positions and trades by symbol only, so one
contract traded in two products on the same day (an MIS round trip and an NRML
position carried from the previous day) is mixed together, and the exit of a
carried position is valued as a brand-new short. For a carried position closed
today it also took the broker's own P&L, and a broker can carry a different cost
for such a position than the real fill.

This module builds the curve per (symbol, exchange, product) from the formula in
services/position_m2m.py:

    m2m(t) = (sell value - buy value, fills up to t)
             + (overnight qty + net fills up to t) x price(t)
             - overnight qty x previous close

summed over rows. The last point is replaced by the figure the Positions page
shows for the same basis, so the tracker and the page agree.

`build_m2m_frame` and `summarize` are pure; `build_m2m_tracker_response` does the
I/O (quotes for previous closes, one 1-minute history call per symbol).
"""

from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd
import pytz

from services.position_m2m import SUPPORTED_EXCHANGES, compute_m2m
from utils.logging import get_logger

logger = get_logger(__name__)

IST = pytz.timezone("Asia/Kolkata")
MARKET_OPEN = (9, 15)
MARKET_CLOSE = (15, 30)


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def build_m2m_frame(index: pd.DatetimeIndex, rows: list[dict[str, Any]]) -> pd.DataFrame:
    """One M2M column per row over `index`.

    Each row: `key` (column name), `overnight` (quantity carried in),
    `prev_close`, `prices` (a Series of minute closes, any index), `fallback_price`
    (used where no candle exists), and `trades` as (time, action, qty, price).
    `overnight_cost`, when present, is the carried quantity's value to subtract
    (default: overnight x previous close, i.e. the M2M basis).
    """
    frame: dict[str, np.ndarray] = {}
    index_ns = index.asi8
    for row in rows:
        fills = sorted(row["trades"], key=lambda t: t[0])
        times = np.array([t[0].value for t in fills], dtype="int64")
        signed_qty = np.array(
            [qty if action == "BUY" else -qty for _, action, qty, _ in fills], dtype=float
        )
        signed_value = np.array(
            [-qty * price if action == "BUY" else qty * price for _, action, qty, price in fills],
            dtype=float,
        )
        # Number of fills at or before each minute, then the running totals there.
        count = np.searchsorted(times, index_ns, side="right")
        cum_qty = np.concatenate([[0.0], np.cumsum(signed_qty)])[count]
        cum_value = np.concatenate([[0.0], np.cumsum(signed_value)])[count]

        prices = row["prices"].reindex(index.union(row["prices"].index)).ffill().bfill()
        prices = prices.reindex(index).to_numpy(dtype=float)
        prices = np.where(np.isnan(prices), _f(row.get("fallback_price")), prices)

        qty_now = row["overnight"] + cum_qty
        marked = np.where(np.abs(qty_now) > 1e-9, qty_now * prices, 0.0)
        overnight_cost = row.get("overnight_cost")
        if overnight_cost is None:
            overnight_cost = row["overnight"] * _f(row.get("prev_close"))
        frame[row["key"]] = cum_value + marked - overnight_cost
    return pd.DataFrame(frame, index=index)


def summarize(frame: pd.DataFrame) -> dict[str, Any]:
    """The response shape blueprints/pnltracker.py returns: current, max, min,
    max drawdown and the two series."""
    if frame.empty:
        return {
            "current_mtm": 0,
            "max_mtm": 0,
            "max_mtm_time": None,
            "min_mtm": 0,
            "min_mtm_time": None,
            "max_drawdown": 0,
            "pnl_series": [],
            "drawdown_series": [],
        }
    total = frame.sum(axis=1)
    drawdown = total - total.cummax()

    def _ms(ts: pd.Timestamp) -> int:
        return int(ts.tz_convert("UTC").timestamp() * 1000)

    return {
        "current_mtm": round(float(total.iloc[-1]), 2),
        "max_mtm": round(float(total.max()), 2),
        "max_mtm_time": total.idxmax().strftime("%H:%M"),
        "min_mtm": round(float(total.min()), 2),
        "min_mtm_time": total.idxmin().strftime("%H:%M"),
        "max_drawdown": round(float(drawdown.min()), 2),
        "pnl_series": [{"time": _ms(ts), "value": round(float(v), 2)} for ts, v in total.items()],
        "drawdown_series": [
            {"time": _ms(ts), "value": round(float(v), 2)} for ts, v in drawdown.items()
        ],
    }


def build_m2m_tracker_response(
    *,
    api_key: str,
    positions: list[dict[str, Any]],
    trades: list[dict[str, Any]],
    parse_time,
    to_ist,
    rate_limiter,
    get_history_fn,
    get_multiquotes_fn,
    basis: str = "m2m",
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """The tracker's response on the chosen basis, or None to let the tracker's own
    code run (anything this cannot do exactly: an unsupported exchange, an
    unparseable fill time, a missing previous close or candle history)."""
    now = now or datetime.now(IST)
    if basis not in ("m2m", "pnl"):
        return None

    if any(p.get("exchange") not in SUPPORTED_EXCHANGES for p in positions):
        return None
    if any(t.get("exchange") not in SUPPORTED_EXCHANGES for t in trades):
        return None

    parsed_trades = []
    for trade in trades:
        stamp = trade.get("timestamp") or trade.get("fill_timestamp") or trade.get("fill_time")
        when = parse_time(stamp) if stamp else None
        action = str(trade.get("action") or "").upper()
        qty = _f(trade.get("quantity"))
        if when is None or action not in ("BUY", "SELL") or qty <= 0:
            logger.info("M2M tracker: a trade cannot be placed in time, using the built-in curve")
            return None
        parsed_trades.append(
            {
                "symbol": trade.get("symbol"),
                "exchange": trade.get("exchange"),
                "product": trade.get("product"),
                "action": action,
                "quantity": qty,
                "average_price": _f(trade.get("average_price")),
                "time": pd.Timestamp(when),
            }
        )

    if not positions and not parsed_trades:
        return summarize(pd.DataFrame())

    # Previous closes for every contract involved.
    contracts = sorted(
        {(p.get("symbol"), p.get("exchange")) for p in positions}
        | {(t["symbol"], t["exchange"]) for t in parsed_trades}
    )
    ok, quotes, _ = get_multiquotes_fn(
        [{"symbol": s, "exchange": e} for s, e in contracts], api_key=api_key
    )
    if not ok:
        return None
    prev_closes = {
        (q.get("symbol"), q.get("exchange")): (q.get("data") or {}).get("prev_close")
        for q in quotes.get("results") or []
    }

    final = compute_m2m(positions, parsed_trades, prev_closes)
    if not final or any(not result["available"] for result in final.values()):
        return None

    # Minute candles for each contract, today only.
    today = now.astimezone(IST).date()
    closes: dict[tuple, pd.Series] = {}
    for symbol, exchange in contracts:
        rate_limiter.wait()
        ok, history, _ = get_history_fn(
            symbol=symbol,
            exchange=exchange,
            interval="1m",
            start_date=today.strftime("%Y-%m-%d"),
            end_date=today.strftime("%Y-%m-%d"),
            api_key=api_key,
        )
        if not ok or "data" not in history:
            return None
        df = pd.DataFrame(history["data"])
        if df.empty:
            closes[(symbol, exchange)] = pd.Series(dtype=float)
            continue
        df = to_ist(df, symbol)
        if df is None:
            return None
        closes[(symbol, exchange)] = df["close"].astype(float)

    open_at = IST.localize(datetime.combine(today, datetime.min.time())).replace(
        hour=MARKET_OPEN[0], minute=MARKET_OPEN[1]
    )
    close_at = open_at.replace(hour=MARKET_CLOSE[0], minute=MARKET_CLOSE[1])
    end = min(pd.Timestamp(now), pd.Timestamp(close_at)).floor("min")
    if end < pd.Timestamp(open_at):
        return summarize(pd.DataFrame())
    index = pd.date_range(start=open_at, end=end, freq="1min", tz=IST)

    rows = []
    last_value: dict[tuple, float] = {}
    for position in positions:
        key = (position.get("symbol"), position.get("exchange"), position.get("product"))
        result = final[key]
        ltp = _f(position.get("ltp"))
        overnight_cost = None
        if basis == "pnl":
            try:
                broker_pnl = float(position.get("pnl"))
            except (TypeError, ValueError):
                return None
            last_value[key] = broker_pnl
            if abs(result["overnight_quantity"]) > 1e-9:
                # Pick the carried cost that makes this row end on the broker's own
                # P&L: today's fills and the live mark are known, the rest is the
                # broker's carried cost.
                fills_value = result["m2m_fixed"] + result["overnight_quantity"] * _f(
                    result["prev_close"]
                )
                overnight_cost = fills_value + _f(position.get("quantity")) * ltp - broker_pnl
            else:
                overnight_cost = 0.0
        else:
            last_value[key] = result["m2m"]
        rows.append(
            {
                "key": "|".join(str(part) for part in key),
                "overnight": result["overnight_quantity"],
                "overnight_cost": overnight_cost,
                "prev_close": result["prev_close"],
                "prices": closes[(key[0], key[1])],
                "fallback_price": ltp or _f(result["prev_close"]),
                "trades": [
                    (t["time"], t["action"], t["quantity"], t["average_price"])
                    for t in parsed_trades
                    if (t["symbol"], t["exchange"], t["product"]) == key
                ],
            }
        )
    frame = build_m2m_frame(index, rows)

    # The last point is the Positions page's own figure for the same basis, so the
    # two always agree.
    for key, value in last_value.items():
        frame.iloc[-1, frame.columns.get_loc("|".join(str(part) for part in key))] = value
    return summarize(frame)
