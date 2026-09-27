"""Per-strategy orderbook, tradebook and positions for the Detail page.

The Detail page shows what one strategy has done: the orders it placed, the
trades that came back, and the contracts it is holding. All three are read from
the platform's own global book services and then post-filtered down to this
strategy, rather than being derived from the ``sm_strategy_order`` rows the
engine writes.

**Why go back to the broker at all.** The order rows are the engine's record of
what it *asked for*. They are written before the broker answers and updated as
order updates arrive, so they lag, and a fill or a cancellation whose update
never reached us leaves them wrong. For money the broker is the authority. The
order rows are used here for exactly one thing: deciding which of the broker's
rows belong to this strategy.

**Why the envelope is passed through unchanged.** Filtering happens inside the
envelope the global service returned - same keys, same field names, same
formatting - so the Detail page renders these with the same table components as
the global /orderbook, /tradebook and /positions surfaces. The only values this
module recomputes are the aggregates, because a global statistic over a
filtered list is simply wrong.

**Mode is per run, not global.** As in ``order_dispatch``, a run chooses live or
sandbox when it starts and two runs may disagree, so the book is chosen from the
run's own ``mode``: a sandbox run reads the sandbox books, a live run reads the
broker's. The live path deliberately calls ``get_*_with_auth`` with
``original_data=None``, which is the internal-call form that never consults the
platform-wide analyzer toggle. Letting that toggle decide would hand a live run
an empty sandbox book the moment an operator switched analyzer mode on, and
would hand a sandbox run the real broker's book when it was off - which is how a
sandbox strategy ends up showing an empty book, or someone else's.

**What the position view cannot promise.** A broker's position book is keyed by
contract, not by order: a position row carries no order id to match against. The
filter therefore uses the set of ``(symbol, exchange)`` this strategy actually
traded, plus the strategy's product. That is a materially weaker guarantee than
the orderbook's. If the same contract is also held from another source - a
manual order, a second strategy, a TradingView webhook - the position row is
*shared*, and its quantity and its P&L belong to all of them; there is nothing
in the row that can divide it. So nothing returned by :func:`strategy_positions`
is the strategy's own P&L. The aggregate a strategy reports comes from its own
fills (the ``sm_strategy_order`` rows and the run checkpoint), never from a
position row it may not exclusively own. The recomputed totals here are sums
over the filtered position rows and carry the same caveat.

**Resources.** Nothing here opens one. Every function composes services that
already exist and reads through the shared ``database.strategy_module_db``
session: no engine, session, thread, executor, HTTP client, socket or
subprocess is created.
"""

from __future__ import annotations

import math
from typing import Any

from database import strategy_module_db as store
from services.strategy_module.order_dispatch import resolve_live_auth
from utils.logging import get_logger

logger = get_logger(__name__)

# Statistic keys every broker mapping produces. Used only when the service
# returned no statistics block of its own to take the key set from.
_DEFAULT_STATISTIC_KEYS = (
    "total_buy_orders",
    "total_sell_orders",
    "total_completed_orders",
    "total_open_orders",
    "total_rejected_orders",
)

# Order statuses are lower-cased by the broker mappings, but not spelled
# identically across them.
_TRIGGER_PENDING_STATUSES = frozenset({"trigger pending", "trigger_pending", "trigger-pending"})

# Position-book totals, and the per-row field each one sums. Only keys the
# service actually returned are recomputed; the rest of the envelope is left
# exactly as it came.
_POSITION_TOTALS = {
    "total_pnl": "pnl",
    "total_pnl_today": "pnl",
    "total_unrealized_pnl": "unrealized_pnl",
    "total_today_realized_pnl": "today_realized_pnl",
}

# ---------------------------------------------------------------------------
# Public views
# ---------------------------------------------------------------------------


def strategy_orderbook(strategy_id: int, api_key: str, run_id: int | None = None) -> dict[str, Any]:
    """This strategy's orders, in the global orderbook's envelope.

    Returns ``{"status": "success", "data": {"orders": [...], "statistics":
    {...}}}`` - the same shape, keys and formatting the global orderbook
    service returns, with ``orders`` narrowed to this strategy and
    ``statistics`` recounted over what survived. A sandbox book adds its own
    ``"mode": "analyze"``, because that is what the sandbox service returns.

    Failures come back as ``{"status": "error", "message": ...}``, again the
    global service's own error envelope. Nothing raises: one failing tab must
    not take out the Detail page.
    """
    try:
        mode, error = _resolve_mode(strategy_id, run_id)
        if error:
            return _error(error)
        if mode is None:
            # Never run, so there is nothing to attribute and no way to know
            # which book to read. The one envelope here that is synthesised
            # rather than taken from a service.
            return {
                "status": "success",
                "data": {"orders": [], "statistics": _statistics([], None)},
            }

        order_ids = _broker_order_ids(_order_rows(strategy_id, run_id))
        ok, response = _fetch_orderbook(mode, api_key)
        if not ok:
            return _as_error(response, "Could not read the orderbook")

        payload = dict(response)
        original = payload.get("data")
        # Copied before anything is written back: the service's own dict is
        # never mutated, and the copy still holds the untouched statistics.
        data = dict(original) if isinstance(original, dict) else {}
        orders = [
            order for order in _rows(data.get("orders")) if _text(order.get("orderid")) in order_ids
        ]
        data["statistics"] = _statistics(orders, data.get("statistics"))
        data["orders"] = orders
        payload["data"] = data
        return payload
    except Exception:
        logger.exception("Could not build the orderbook for strategy %s", strategy_id)
        return _error("Could not read the orderbook")


def strategy_tradebook(strategy_id: int, api_key: str, run_id: int | None = None) -> dict[str, Any]:
    """This strategy's fills, in the global tradebook's envelope.

    Returns ``{"status": "success", "data": [...]}`` - the global tradebook
    service's shape, a flat list with no statistics block - narrowed to trades
    whose ``orderid`` is one of this strategy's orders. A sandbox book adds its
    own ``"mode": "analyze"``.

    Failures come back as ``{"status": "error", "message": ...}``.
    """
    try:
        mode, error = _resolve_mode(strategy_id, run_id)
        if error:
            return _error(error)
        if mode is None:
            return {"status": "success", "data": []}

        order_ids = _broker_order_ids(_order_rows(strategy_id, run_id))
        ok, response = _fetch_tradebook(mode, api_key)
        if not ok:
            return _as_error(response, "Could not read the tradebook")

        payload = dict(response)
        payload["data"] = [
            trade
            for trade in _rows(payload.get("data"))
            if _text(trade.get("orderid")) in order_ids
        ]
        return payload
    except Exception:
        logger.exception("Could not build the tradebook for strategy %s", strategy_id)
        return _error("Could not read the tradebook")


def strategy_positions(strategy_id: int, api_key: str, run_id: int | None = None) -> dict[str, Any]:
    """The contracts this strategy traded, in the global positionbook's envelope.

    Returns ``{"status": "success", "data": [...]}`` - the global positionbook
    service's shape - narrowed to the ``(symbol, exchange)`` pairs this strategy
    traded at the strategy's product. The sandbox book also carries
    ``total_pnl``, ``total_unrealized_pnl``, ``total_today_realized_pnl``,
    ``total_pnl_today`` and ``mode``; the totals are re-summed over the filtered
    rows and the rest is passed through.

    Read the module docstring before using any of it as the strategy's P&L: a
    position row is per contract, so a contract also held from somewhere else
    is shared and cannot be attributed to this strategy alone.

    Failures come back as ``{"status": "error", "message": ...}``.
    """
    try:
        mode, error = _resolve_mode(strategy_id, run_id)
        if error:
            return _error(error)
        if mode is None:
            return {"status": "success", "data": []}

        product = _strategy_product(strategy_id)
        # The selected run owns the book mode, not the exposure boundary. A
        # prior run can still own a position after a newer run starts.
        local_owners = _unresolved_position_owners(
            _order_rows(strategy_id, None), product
        )

        ok, response = _fetch_positions(mode, api_key)
        if not ok:
            return _as_error(response, "Could not read the positions")

        payload = dict(response)
        positions = _overlay_broker_positions(
            _rows(payload.get("data")), local_owners, product
        )
        payload["data"] = positions
        for key, field in _POSITION_TOTALS.items():
            # Recomputed only where the service reported it, so the key set of
            # the envelope is unchanged either way.
            if key in payload:
                payload[key] = round(sum(_number(row.get(field)) for row in positions), 2)
        return payload
    except Exception:
        logger.exception("Could not build the positions for strategy %s", strategy_id)
        return _error("Could not read the positions")


# ---------------------------------------------------------------------------
# Which book, and whose rows
# ---------------------------------------------------------------------------


def _resolve_mode(strategy_id: int, run_id: int | None) -> tuple[str | None, str | None]:
    """``(mode, error)`` for the book this view should read.

    ``(None, None)`` is not a failure: it means the strategy has never run, so
    there is nothing to attribute and no run to take a mode from. A named run
    that does not exist, belongs to another strategy, or carries a mode this
    build does not know is an error - refused rather than defaulted, for the
    same reason ``order_dispatch`` refuses: defaulting to live would read a real
    broker book for a run the operator believed was on paper.
    """
    if run_id is not None:
        run = store.get_run(run_id)
        if run is None:
            return None, f"Run {run_id} was not found"
        if getattr(run, "strategy_id", None) != strategy_id:
            return None, f"Run {run_id} does not belong to strategy {strategy_id}"
        mode = _text(getattr(run, "mode", ""))
    else:
        runs = store.list_runs(strategy_id, limit=1) or []
        if not runs:
            return None, None
        # list_runs is newest first, so this is the run the page is looking at.
        mode = _text(runs[0].get("mode"))

    if mode not in store.RUN_MODES:
        return None, f"Unknown run mode: {mode!r}"
    return mode, None


def _order_rows(strategy_id: int, run_id: int | None) -> list[dict[str, Any]]:
    """This strategy's order rows, narrowed to one run when asked."""
    return store.list_orders_for_strategy(strategy_id, run_id) or []


def _broker_order_ids(rows: list[dict[str, Any]]) -> set[str]:
    """The broker references this strategy owns.

    An order with no reference was refused before the broker ever saw it and
    cannot match anything, so it is skipped rather than added. A falsy id left
    in this set would compare equal to a broker row whose own order id is blank
    or missing, and would pull in rows that are not ours.
    """
    ids = set()
    for row in rows:
        reference = _text(row.get("broker_order_id"))
        if reference:
            ids.add(reference)
    return ids


def _traded_contracts(rows: list[dict[str, Any]]) -> set[tuple[str, str]]:
    """The ``(symbol, exchange)`` pairs this strategy actually traded.

    A complete order counts for legacy rows that predate fill-quantity capture.
    For every other status only an explicit positive fill proves exposure: a
    working order may already be partially filled and a rejection/cancellation
    can apply only to its remainder.
    """
    contracts = set()
    for row in rows:
        status = _text(row.get("status")).lower()
        raw_fill = row.get("filled_qty")
        try:
            fill_qty = float(raw_fill)
            explicit_fill = math.isfinite(fill_qty) and fill_qty > 0
        except (TypeError, ValueError):
            explicit_fill = False
        if not explicit_fill:
            # A complete row with no fill quantity is a legacy record. Broker
            # acknowledgement plus a positive requested quantity is the only
            # safe fallback. Explicit zero/invalid fill evidence must win.
            legacy_complete = (
                raw_fill is None
                and status == "complete"
                and bool(_text(row.get("broker_order_id")))
                and _number(row.get("qty")) > 0
            )
            if not legacy_complete:
                continue
        symbol = _text(row.get("symbol")).upper()
        exchange = _text(row.get("exchange")).upper()
        if symbol and exchange:
            contracts.add((symbol, exchange))
    return contracts


def _filled_order_quantity(row: dict[str, Any]) -> int:
    status = _text(row.get("status")).lower()
    raw_fill = row.get("filled_qty")
    try:
        fill_qty = float(raw_fill)
        if math.isfinite(fill_qty) and fill_qty > 0:
            return int(fill_qty)
    except (TypeError, ValueError):
        pass
    legacy_complete = (
        raw_fill is None
        and status == "complete"
        and bool(_text(row.get("broker_order_id")))
        and _number(row.get("qty")) > 0
    )
    return int(_number(row.get("qty"))) if legacy_complete else 0


def _usable_price(value: Any) -> float | None:
    try:
        price = float(value)
    except (TypeError, ValueError):
        return None
    return price if math.isfinite(price) and price > 0 else None


def _position_contract_key(row: dict[str, Any], product: str) -> tuple[str, str, str]:
    return (
        _text(row.get("symbol")).upper(),
        _text(row.get("exchange")).upper(),
        _text(row.get("product")).upper() or product,
    )


def _unresolved_position_owners(
    rows: list[dict[str, Any]], product: str
) -> list[dict[str, Any]]:
    """Lifetime local residuals, kept separate by durable position owner."""
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for row in rows:
        quantity = _filled_order_quantity(row)
        action = _text(row.get("action")).upper()
        contract = _position_contract_key(row, product)
        if quantity <= 0 or action not in {"BUY", "SELL"} or not all(contract[:2]):
            continue
        position_ref = _text(row.get("position_ref")) or None
        owner_key = (
            row.get("run_id"),
            row.get("leg_id"),
            position_ref,
            *contract,
        )
        groups.setdefault(owner_key, []).append({**row, "_filled_quantity": quantity})

    residuals: list[dict[str, Any]] = []
    for owner_key, owner_rows in groups.items():
        lots: list[dict[str, Any]] = []
        ordered = sorted(
            owner_rows,
            key=lambda row: (
                _text(row.get("filled_at") or row.get("placed_at")),
                int(row.get("id") or 0),
            ),
        )
        for row in ordered:
            side = 1 if _text(row.get("action")).upper() == "BUY" else -1
            remaining = int(row["_filled_quantity"])
            while remaining > 0 and lots and lots[0]["side"] != side:
                matched = min(remaining, lots[0]["quantity"])
                lots[0]["quantity"] -= matched
                remaining -= matched
                if lots[0]["quantity"] <= 0:
                    lots.pop(0)
            if remaining > 0:
                lots.append(
                    {
                        "side": side,
                        "quantity": remaining,
                        "price": _usable_price(row.get("avg_fill_price")),
                    }
                )

        net_quantity = sum(lot["side"] * lot["quantity"] for lot in lots)
        if net_quantity == 0:
            continue
        gross_quantity = sum(lot["quantity"] for lot in lots)
        priced = all(lot["price"] is not None for lot in lots)
        average_price = (
            sum(lot["quantity"] * lot["price"] for lot in lots) / gross_quantity
            if priced and gross_quantity
            else None
        )
        run_id, leg_id, position_ref, symbol, exchange, owner_product = owner_key
        residuals.append(
            {
                "symbol": symbol,
                "exchange": exchange,
                "product": owner_product,
                "quantity": net_quantity,
                "average_price": average_price,
                "ltp": None,
                "pnl": None,
                "source": "local/unreconciled",
                "position_ref": position_ref,
                "run_id": run_id,
                "leg_id": leg_id,
            }
        )

    return sorted(
        residuals,
        key=lambda row: (
            row["symbol"],
            row["exchange"],
            row["product"],
            int(row.get("run_id") or 0),
            int(row.get("leg_id") or 0),
            _text(row.get("position_ref")),
        ),
    )


def _overlay_broker_positions(
    broker_rows: list[dict[str, Any]],
    local_owners: list[dict[str, Any]],
    product: str,
) -> list[dict[str, Any]]:
    """Overlay attributable broker truth without erasing unmatched owners."""
    owners_by_contract: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for owner in local_owners:
        owners_by_contract.setdefault(_position_contract_key(owner, product), []).append(owner)

    result: list[dict[str, Any]] = []
    matched_contracts: set[tuple[str, str, str]] = set()
    for broker_row in broker_rows:
        contract = _position_contract_key(broker_row, product)
        owners = owners_by_contract.get(contract, [])
        if not owners:
            continue
        row_product = _text(broker_row.get("product")).upper()
        if product and row_product and row_product != product:
            continue
        matched_contracts.add(contract)
        if len(owners) == 1:
            owner = owners[0]
            result.append(
                {
                    **broker_row,
                    "source": "broker",
                    "position_ref": owner.get("position_ref"),
                    "run_id": owner.get("run_id"),
                    "leg_id": owner.get("leg_id"),
                }
            )
        else:
            # One contract row cannot be divided across multiple durable owners.
            result.append({**broker_row, "source": "broker/shared"})

    for contract, owners in owners_by_contract.items():
        if contract not in matched_contracts or len(owners) > 1:
            result.extend(owners)
    return result


def _strategy_product(strategy_id: int) -> str:
    """The product this strategy trades, for the position filter.

    Read unscoped on purpose. The caller has already resolved this strategy for
    the session user, one field is read, and nothing from the row is returned:
    this narrows a filter, it does not serve strategy content. A blank falls
    back to matching on contract alone, which is wider but never wrong in the
    other direction.
    """
    try:
        row = store.get_strategy_unscoped(strategy_id)
    except Exception:
        logger.exception("Could not read the product for strategy %s", strategy_id)
        return ""
    return _text(getattr(row, "product", "")).upper() if row is not None else ""


def _matches_contract(
    position: dict[str, Any], contracts: set[tuple[str, str]], product: str
) -> bool:
    """Whether one position row is on a contract this strategy traded."""
    symbol = _text(position.get("symbol")).upper()
    exchange = _text(position.get("exchange")).upper()
    if not symbol or not exchange:
        return False
    if (symbol, exchange) not in contracts:
        return False
    row_product = _text(position.get("product")).upper()
    if product and row_product and row_product != product:
        return False
    return True


# ---------------------------------------------------------------------------
# The books themselves
# ---------------------------------------------------------------------------


def _fetch_orderbook(mode: str, api_key: str) -> tuple[bool, Any]:
    if mode == "sandbox":
        from services.sandbox_service import sandbox_get_orderbook

        ok, response, _status = sandbox_get_orderbook(api_key, {"apikey": api_key})
        return ok, response

    auth_token, broker, error = resolve_live_auth(api_key)
    if error:
        return False, {"status": "error", "message": error}

    from services.orderbook_service import get_orderbook_with_auth

    # original_data=None is the internal-call form: the live broker, whatever
    # the platform-wide analyzer toggle currently says.
    ok, response, _status = get_orderbook_with_auth(auth_token, broker, None)
    return ok, response


def _fetch_tradebook(mode: str, api_key: str) -> tuple[bool, Any]:
    if mode == "sandbox":
        from services.sandbox_service import sandbox_get_tradebook

        ok, response, _status = sandbox_get_tradebook(api_key, {"apikey": api_key})
        return ok, response

    auth_token, broker, error = resolve_live_auth(api_key)
    if error:
        return False, {"status": "error", "message": error}

    from services.tradebook_service import get_tradebook_with_auth

    ok, response, _status = get_tradebook_with_auth(auth_token, broker, None)
    return ok, response


def _fetch_positions(mode: str, api_key: str) -> tuple[bool, Any]:
    if mode == "sandbox":
        from services.sandbox_service import sandbox_get_positions

        ok, response, _status = sandbox_get_positions(api_key, {"apikey": api_key})
        return ok, response

    auth_token, broker, error = resolve_live_auth(api_key)
    if error:
        return False, {"status": "error", "message": error}

    from services.positionbook_service import get_positionbook_with_auth

    ok, response, _status = get_positionbook_with_auth(auth_token, broker, None)
    return ok, response


# ---------------------------------------------------------------------------
# Aggregates and shapes
# ---------------------------------------------------------------------------


def _statistics(orders: list[dict[str, Any]], template: Any) -> dict[str, Any]:
    """Order statistics counted over ``orders``, keyed like ``template``.

    The global count describes the whole account and says nothing about this
    strategy, so it is recounted rather than passed through. The key set is
    taken from what the service returned so the frontend sees the same fields;
    a key this module cannot derive is reported as 0 rather than carried over
    from the account-wide block, since a global number on a filtered list would
    be read as this strategy's.
    """
    buy = sell = 0
    by_status: dict[str, int] = {}
    for order in orders:
        action = _text(order.get("action")).upper()
        if action == "BUY":
            buy += 1
        elif action == "SELL":
            sell += 1
        status = _text(order.get("order_status") or order.get("orderstatus")).lower()
        if status in _TRIGGER_PENDING_STATUSES:
            status = "trigger pending"
        by_status[status] = by_status.get(status, 0) + 1

    counted = {
        "total_orders": len(orders),
        "total_buy_orders": buy,
        "total_sell_orders": sell,
        "total_completed_orders": by_status.get("complete", 0),
        "total_open_orders": by_status.get("open", 0),
        "total_rejected_orders": by_status.get("rejected", 0),
        "total_cancelled_orders": by_status.get("cancelled", 0),
        "total_trigger_pending_orders": by_status.get("trigger pending", 0),
    }

    keys = tuple(template) if isinstance(template, dict) and template else _DEFAULT_STATISTIC_KEYS
    statistics = {}
    for key in keys:
        if key not in counted:
            logger.debug("No per-strategy count for statistic %r; reporting 0", key)
        statistics[key] = counted.get(key, 0)
    return statistics


def _rows(value: Any) -> list[dict[str, Any]]:
    """The dict rows in a service payload, however oddly it answered."""
    if not isinstance(value, list):
        return []
    return [row for row in value if isinstance(row, dict)]


def _text(value: Any) -> str:
    """A comparable string. ``None`` and whitespace both become empty."""
    if value is None:
        return ""
    return str(value).strip()


def _number(value: Any) -> float:
    """A summable number. Position fields arrive as floats or as strings."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _error(message: str) -> dict[str, Any]:
    return {"status": "error", "message": message}


def _as_error(response: Any, fallback: str) -> dict[str, Any]:
    """The service's own failure envelope, or one in its shape.

    A sandbox failure carries ``"mode": "analyze"`` and is passed through with
    it, so the page can tell which book failed.
    """
    if isinstance(response, dict):
        if response.get("status") == "error":
            return dict(response)
        message = _text(response.get("message"))
        if message:
            return _error(message)
    return _error(fallback)
