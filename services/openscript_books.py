"""One OpenScript strategy's orders, fills and positions, for tracking it.

A trader running several strategies asks one question constantly: which of them
did this. This answers it, per strategy, in the shape the global books already
come in.

**The attribution is already on the order, and that is the whole design.** Every
order a run places carries its run's name in the platform's own ``strategy``
field, because the child passes ``strategy=`` on every call it makes. So an
OpenScript strategy's book is a filter on a field that is already there.

That is why this does not go through ``services/strategy_module``. That module
keeps its own ``sm_strategy_order`` rows and matches the broker's rows against
them, and it has to: a webhook strategy's orders reach the broker carrying no
strategy of their own, so without those rows nothing could say whose they were.
Ours arrive tagged. Writing a second copy of that bookkeeping, with a synthetic
leg for orders that have no legs and a synthetic webhook token for a strategy
that has no webhook, would be paying that module's cost for a problem we do not
have.

**What is borrowed from it is the approach, which is right.** Read the
platform's own global book and narrow it, rather than deriving a book from
records of what was asked for. The stored record says what a run tried to do;
the broker knows what happened, and for money that difference is the point. The
envelope comes back untouched, same keys and same formatting, so the page that
renders the global orderbook renders this with the same table.

**The book a run is read from is the run's own, never the platform toggle.** A
run sends through the order path, so where its orders went was decided by the
mode at the moment each was sent. Reading the sandbox book for a strategy whose
orders went live would answer an empty book, and reading the live one for a
sandbox strategy would answer somebody else's. The mode comes from the run.

**Nothing here raises.** One failing tab must not take down the page a trader is
using to decide whether to stop something.
"""

from __future__ import annotations

from typing import Any

from services.openscript_deployment import is_deployment_id
from utils.logging import get_logger

logger = get_logger(__name__)

#: What a run's orders are tagged with, which is the run id the service mints.
#: A strategy's book is every order carrying its own, and no other.
PREFIX = "openscript_"


def tag_for(name: str) -> str:
    """The `strategy` value this deployment's run tags its orders with.

    A deployment's id **is** that value, so this is a check rather than a
    lookup: nothing here reads a file, and a book can be taken of a deployment
    whose settings have since been removed.

    **A name that is not a deployment answers nothing, and nothing means no
    book.** The tag used to be minted from the script alone, so two deployments
    of one file shared it and each one's book listed the other's orders: a run
    on a commodity future showed the stock orders the same file had placed that
    morning. A caller that holds only a file name resolves it first, where the
    settings are, rather than here.
    """
    return name if is_deployment_id(name) else ""


# ---------------------------------------------------------------------------
# The three books
# ---------------------------------------------------------------------------


def orderbook(script: str, api_key: str, mode: str) -> dict[str, Any]:
    """This strategy's orders, in the global orderbook's envelope."""
    try:
        ok, response = _fetch("orderbook", mode, api_key)
        if not ok:
            return _as_error(response, "Could not read the orderbook")

        payload = _envelope(response)
        data = _data_of(response)
        found, under = _rows_and_shape(data, "orders")
        orders = _mine(found, script)
        _narrowed(payload, data, orders, under)
        if isinstance(payload.get("data"), dict) and "statistics" in payload["data"]:
            # A global statistic over a filtered list is simply wrong, so what
            # cannot be recounted here is dropped rather than shown as this
            # strategy's. The rows are the answer; a total that counts somebody
            # else's orders is not.
            payload["data"]["statistics"] = _statistics(orders)
        return payload
    except Exception:
        logger.exception("Could not build the orderbook for %s", script)
        return _error("Could not read the orderbook")


def tradebook(script: str, api_key: str, mode: str) -> dict[str, Any]:
    """This strategy's fills, in the global tradebook's envelope.

    Filtered on the same tag rather than on the order ids this strategy placed.
    A fill carries the tag for the same reason an order does, and matching by id
    would answer nothing for a fill whose order row had not been read back yet.
    """
    try:
        ok, response = _fetch("tradebook", mode, api_key)
        if not ok:
            return _as_error(response, "Could not read the tradebook")

        payload = _envelope(response)
        data = _data_of(response)
        found, under = _rows_and_shape(data, "trades")
        _narrowed(payload, data, _mine(found, script), under)
        return payload
    except Exception:
        logger.exception("Could not build the tradebook for %s", script)
        return _error("Could not read the tradebook")


def positions(name: str, api_key: str, mode: str) -> dict[str, Any]:
    """The contracts this strategy traded, in the global positionbook's envelope.

    **Weaker than the other two, and it says so.** A position row is per
    contract and carries no strategy: the broker holds one position in an
    instrument however many strategies traded it. So this narrows to the
    contracts this strategy actually traded, taken from its own orders, and a
    row it returns may hold size somebody else opened.

    **The profit beside the rows is this deployment's, not the account's.** It
    is read from the platform's own per strategy book, which keeps a leg per
    order tag with realised profit accumulated across sessions, and marked
    against the prices in the answer that has just been read. Passed through as
    it arrives, every deployment on the server reported the account's profit as
    its own. See `_own_totals`.
    """
    try:
        ok, orders = _fetch("orderbook", mode, api_key)
        if not ok:
            return _as_error(orders, "Could not read the positions")
        placed, _ = _rows_and_shape(_data_of(orders), "orders")
        traded = {
            (_text(row.get("symbol")), _text(row.get("exchange")))
            for row in _mine(placed, name)
        }

        ok, response = _fetch("positions", mode, api_key)
        if not ok:
            return _as_error(response, "Could not read the positions")

        payload = _envelope(response)
        data = _data_of(response)
        found, under = _rows_and_shape(data, "positions")
        kept = [
            row
            for row in found
            if (_text(row.get("symbol")), _text(row.get("exchange"))) in traded
        ]
        _narrowed(payload, data, kept, under)
        _own_totals(payload, name, api_key, found)
        return payload
    except Exception:
        logger.exception("Could not build the positions for %s", name)
        return _error("Could not read the positions")


# ---------------------------------------------------------------------------
# Reading the platform's own books
# ---------------------------------------------------------------------------


def _fetch(book: str, mode: str, api_key: str) -> tuple[bool, Any]:
    """One of the platform's global books, from the side this run traded on."""
    if mode == "sandbox":
        from services import sandbox_service

        call = {
            "orderbook": sandbox_service.sandbox_get_orderbook,
            "tradebook": sandbox_service.sandbox_get_tradebook,
            "positions": sandbox_service.sandbox_get_positions,
        }[book]
        ok, response, _status = call(api_key, {"apikey": api_key})
        return ok, response

    from services.strategy_module.order_dispatch import resolve_live_auth

    auth_token, broker, error = resolve_live_auth(api_key)
    if error:
        return False, {"status": "error", "message": error}

    if book == "orderbook":
        from services.orderbook_service import get_orderbook_with_auth as get
    elif book == "tradebook":
        from services.tradebook_service import get_tradebook_with_auth as get
    else:
        from services.positionbook_service import get_positionbook_with_auth as get

    # original_data=None is the internal-call form: the live broker, whatever
    # the platform-wide toggle currently says. Letting the toggle decide would
    # hand a live strategy an empty sandbox book the moment somebody switched.
    ok, response, _status = get(auth_token, broker, None)
    return ok, response


# ---------------------------------------------------------------------------
# Small shared readers
# ---------------------------------------------------------------------------


#: The figures a positions answer states beside its rows, which are the whole
#: account's and never one deployment's.
#:
#: A page reads these in preference to adding up the rows, and it is right to:
#: a strategy's realised profit is on trades whose rows the book no longer holds,
#: so a sum of what came back is the unrealised half only. Left as they arrive,
#: though, every deployment on the server reports the account's profit as its
#: own, which is the one number a trader is actually watching.
ACCOUNT_TOTALS = (
    "total_pnl",
    "total_pnl_today",
    "total_unrealized_pnl",
    "total_today_realized_pnl",
    "total_realized_pnl",
)


def _own_totals(
    payload: dict[str, Any], name: str, api_key: str, positions: list[dict[str, Any]]
) -> None:
    """Replace the account's totals with this deployment's, or remove them.

    **The platform already keeps this per strategy.** Every order carries its
    deployment's tag, and `strategy_book_db` keeps a leg per tag with the
    realised profit accumulated across sessions. `pnl_from_book` marks the open
    part of those legs against the position book that has just been read, which
    is the same prices the rows in this answer carry.

    **What cannot be worked out is removed rather than passed through.** An
    account total on a filtered list is not this strategy's profit, it is
    somebody else's added to it, and a trader reading it has no way to tell.
    Removing it leaves the page adding up the rows, which understates by the
    realised part and is at least this deployment's own number.

    Nothing raises. A total that could not be worked out is one this answer does
    not carry; a book that could not be read must not take the rows down with
    it.
    """
    tag = tag_for(name)
    if not tag:
        for key in ACCOUNT_TOTALS:
            payload.pop(key, None)
        return

    try:
        from database.auth_db import verify_api_key
        from database.strategy_book_db import get_strategy_legs
        from services.strategy_pnl_service import pnl_from_book

        user_id = verify_api_key(api_key)
        legs = get_strategy_legs(user_id=user_id, strategy=tag)
        figures = pnl_from_book(legs, positions, strategy=tag)
    except Exception:
        logger.exception("Could not read the per strategy profit for %s", tag)
        for key in ACCOUNT_TOTALS:
            payload.pop(key, None)
        return

    payload["total_pnl"] = figures.get("total", 0.0)
    payload["total_pnl_today"] = figures.get("today_total", 0.0)
    payload["total_unrealized_pnl"] = figures.get("unrealized", 0.0)
    payload["total_today_realized_pnl"] = figures.get("today_realized", 0.0)
    payload["total_realized_pnl"] = figures.get("realized", 0.0)


def _mine(rows: Any, name: str) -> list[dict[str, Any]]:
    """The rows this deployment's run placed, and no others.

    No tag means no rows, and never every untagged row. A comparison against an
    empty tag matches exactly the orders that carry no strategy at all, which is
    every order the trader placed by hand: a deployment that could not be
    identified would show a book of somebody else's trades.
    """
    wanted = tag_for(name)
    if not wanted:
        return []
    return [row for row in _rows(rows) if _text(row.get("strategy")) == wanted]


def _rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [row for row in value if isinstance(row, dict)]


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _data_of(response: Any) -> Any:
    """Whatever the service put under ``data``, whatever shape that is."""
    return response.get("data") if isinstance(response, dict) else None


#: Where a book's rows sit inside its ``data``, tried in order.
#:
#: **The three services do not agree, and this is the whole reason this exists.**
#: The orderbook answers ``data`` as an object with the rows under ``orders``
#: beside a ``statistics`` block. The tradebook and the positionbook answer
#: ``data`` as the list of rows itself. Reading every one of them as an object
#: is how two of these three books returned nothing at all while reporting
#: success, which reads on screen as a strategy that has not traded.
_ROW_KEYS = ("orders", "trades", "positions", "positionbook", "data")


def _rows_and_shape(data: Any, key: str) -> tuple[list[dict[str, Any]], str | None]:
    """The rows a book answered, and the key they were under, or ``None`` for a bare list.

    The second half is what lets the filtered rows be written back the way they
    arrived. A book whose rows were a bare list has to answer a bare list: the
    page that renders the global positionbook reads it that way, and handing it
    an object instead would be this narrowing quietly changing the shape of a
    book as well as its contents.
    """
    if isinstance(data, list):
        return _rows(data), None
    if isinstance(data, dict):
        # The book's own key first, so a response that carries more than one
        # list is read for the one that was asked for.
        for name in (key, *_ROW_KEYS):
            if isinstance(data.get(name), list):
                return _rows(data[name]), name
    return [], None


def _envelope(response: Any) -> dict[str, Any]:
    """The service's own envelope, copied before anything is written into it.

    Copied because the service's dict is not ours: a book service may hold or
    cache what it returned, and narrowing it in place would narrow the global
    orderbook for whoever reads it next.

    A status is always present. Every reader of these answers branches on it
    first, and an envelope without one is read as neither a success nor a
    failure: the page shows no rows and no reason for there being none.
    """
    payload = dict(response) if isinstance(response, dict) else {}
    payload.setdefault("status", "success")
    return payload


def _narrowed(payload: dict[str, Any], data: Any, rows: list[dict[str, Any]], under: str | None) -> None:
    """Write the kept rows back into the envelope in the shape they arrived in."""
    if under is None:
        payload["data"] = rows
        return
    copied = dict(data) if isinstance(data, dict) else {}
    copied[under] = rows
    payload["data"] = copied


def _statistics(orders: list[dict[str, Any]]) -> dict[str, int]:
    """Counted over what survived the filter, never carried over from the global."""
    counted = {"total_orders": len(orders), "open_orders": 0, "completed_orders": 0, "rejected_orders": 0}
    for order in orders:
        status = _text(order.get("order_status") or order.get("status")).lower()
        if status in ("complete", "completed", "filled"):
            counted["completed_orders"] += 1
        elif status in ("rejected", "cancelled", "canceled"):
            counted["rejected_orders"] += 1
        else:
            counted["open_orders"] += 1
    return counted


def _error(message: str) -> dict[str, Any]:
    return {"status": "error", "message": message}


def _as_error(response: Any, fallback: str) -> dict[str, Any]:
    """A service's own refusal, passed through rather than replaced."""
    if isinstance(response, dict) and response.get("message"):
        return {"status": "error", "message": str(response["message"])}
    return _error(fallback)
