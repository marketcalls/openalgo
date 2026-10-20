"""The single place a strategy run turns a decision into an order.

Every order the module places - entries, rule-driven exits, manual closes,
square-offs - goes through :func:`dispatch_order`. One decision point means the
live and sandbox paths cannot drift apart, and the engine never has to know
which one it is on.

Three deliberate departures from how the rest of the product places orders:

**Mode is per run, not global.** OpenAlgo's analyzer setting is a single
platform-wide switch. A strategy chooses live or sandbox when the run starts,
and two runs may disagree, so this module branches explicitly on the run's own
mode and calls each pipe directly.

A live order passes ``force_live=True``, which is load bearing rather than
decorative: ``place_order_with_auth`` consults the global toggle before it
looks at the broker arguments, so without the flag an operator turning the
analyzer on to try something elsewhere would divert a live run's exits into the
sandbox. Those report success, so the engine would close the leg and finalise
the run while the real broker position stayed open with nothing managing it.
Nothing here changes the toggle.

**Action Center is bypassed.** ``place_order`` routes API-key orders into the
semi-automatic approval queue when that is enabled. That is right for a signal
arriving from outside and wrong here: a stop-loss exit that sits in a queue
waiting for a human is not a stop loss. The module calls
``place_order_with_auth``, which is the same code path minus the queue.

**Broker authorisation is resolved fresh, per order, and never cached in run
state.** Indian broker tokens expire daily around 3 AM IST, and a run may be
open across that boundary. If authorisation cannot be resolved, an automated
exit is refused and reported rather than attempted: leaving the position open
and telling the operator is recoverable, and pretending to have exited is not.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from utils.logging import get_logger

logger = get_logger(__name__)

# Exits are always MARKET. A limit exit that does not fill is not an exit, and
# every exit this module places is a risk decision that has already fired.
EXIT_PRICETYPE = "MARKET"


@dataclass(frozen=True, slots=True)
class DispatchResult:
    """What one placement attempt produced.

    ``ok`` is whether the order reached the broker or the sandbox, not whether
    it filled. Fills arrive later, over the order-update event.
    """

    ok: bool
    broker_order_id: str | None = None
    response: dict[str, Any] | None = None
    error: str | None = None

    @property
    def rejected(self) -> bool:
        return not self.ok


@dataclass(frozen=True, slots=True)
class OrderStatusResult:
    """One broker orderbook fact, or why it could not be read."""

    ok: bool
    order: dict[str, Any] | None = None
    error: str | None = None


# Which venues list derivatives, for the purpose of naming the product.
# /scalping already carries this rule (blueprints/scalping.py), and every
# broker enforces it: CNC is a delivery product for cash, NRML a carry-forward
# product for derivatives, and neither is accepted on the other's venue.
#
# There is deliberately no set of "products a derivative accepts" beside this
# one. Two such sets used to sit here and were referenced by nothing, which
# read as a validation rule that ran somewhere and did not: the product is
# translated per venue below rather than refused, so a legal value for the
# venue is produced instead of being demanded from the caller.
DERIVATIVE_EXCHANGES_FOR_PRODUCT = frozenset({"NFO", "BFO", "MCX", "CDS", "BCD", "NCDEX", "NCO"})


def product_for_exchange(product: str, exchange: str) -> str:
    """The venue's spelling of the product the strategy asked for.

    A strategy carries one product for every leg, so a basket holding a cash
    leg and an option leg could not be given a product both would accept, and
    the default NRML reached NSE and BSE while CNC reached NFO, BFO, MCX and
    CDS. Nothing downstream catches it: the schemas and the sandbox only check
    the value is one of the three, so it went to the broker as configured.

    The product is read as the intent rather than as a literal. MIS is
    intraday everywhere and passes through. Anything else means carry the
    position, which is NRML on a derivatives venue and CNC on cash, so a mixed
    basket works and no leg is ever sent a product its venue refuses.
    """
    wanted = (product or "").upper()
    if wanted == "MIS":
        return "MIS"
    if (exchange or "").upper() in DERIVATIVE_EXCHANGES_FOR_PRODUCT:
        return "NRML"
    return "CNC"


def build_order(
    *,
    symbol: str,
    exchange: str,
    action: str,
    quantity: int,
    product: str,
    strategy_name: str,
    pricetype: str = "MARKET",
    price: float = 0,
    trigger_price: float = 0,
) -> dict[str, Any]:
    """The order payload, in the shape the placement services expect.

    Quantity is a string because that is what the rest of the order path uses;
    passing an int works today but diverges from every other caller.
    """
    return {
        "symbol": symbol,
        "exchange": exchange,
        "action": action.upper(),
        "quantity": str(int(quantity)),
        # Translated to what this venue accepts. Every order the module places
        # passes through here, so this is the one place it has to be right.
        "product": product_for_exchange(product, exchange),
        "pricetype": pricetype,
        "price": str(price or 0),
        "trigger_price": str(trigger_price or 0),
        # Tags the order so it is attributable in the orderbook and in logs.
        "strategy": strategy_name,
    }


def exit_action(position: str) -> str:
    """The action that closes a leg.

    Derived from the leg's own recorded side, never from its configuration. The
    original reads the configured side, which defaults to "B" for every leg
    including short ones, so a rule-driven exit on a short leg placed another
    SELL and doubled the position instead of covering it.
    """
    normalised = (position or "").upper()
    if normalised == "B":
        return "SELL"
    if normalised == "S":
        return "BUY"
    raise ValueError(f"Cannot derive an exit action from position {position!r}")


def resolve_live_auth(api_key: str) -> tuple[str | None, str | None, str | None]:
    """Broker authorisation for a live order, as ``(auth_token, broker, error)``.

    Resolved on every call rather than held for the life of the run. A token
    refreshed during the trading day is picked up transparently, and a session
    that has expired or been revoked is reported instead of being used.
    """
    try:
        from database.auth_db import get_auth_token_broker

        auth_token, broker = get_auth_token_broker(api_key)
        if not auth_token or not broker:
            return None, None, "Broker session is not available or has expired"
        return auth_token, broker, None
    except Exception:
        logger.exception("Could not resolve broker authorisation for a live order")
        return None, None, "Could not resolve broker authorisation"


def dispatch_order(
    *,
    mode: str,
    api_key: str,
    order: dict[str, Any],
) -> DispatchResult:
    """Place one order, live or sandbox, and normalise the answer.

    Both pipes return ``(success, response, status_code)``, so the caller gets
    one shape whichever ran.
    """
    if mode == "sandbox":
        return _dispatch_sandbox(api_key, order)
    if mode == "live":
        return _dispatch_live(api_key, order)
    return DispatchResult(ok=False, error=f"Unknown run mode: {mode!r}")


def cancel_order(
    *,
    mode: str,
    api_key: str,
    broker_order_id: str,
) -> DispatchResult:
    """Cancel a strategy order through the run's own execution pipe.

    Used both for an entry whose run is stopping and for an exit retry made too
    large by a late cumulative correction. Like placement, this bypasses the
    platform analyzer toggle because ``mode`` was fixed durably at run start.
    """
    if not broker_order_id:
        return DispatchResult(ok=False, error="Broker order id is unavailable")
    if mode == "sandbox":
        from services.sandbox_service import sandbox_cancel_order

        request = {"orderid": broker_order_id}
        original = {**request, "apikey": api_key}
        try:
            ok, response, _status = sandbox_cancel_order(request, api_key, original)
        except Exception:
            logger.exception("Sandbox strategy cancellation raised for %s", broker_order_id)
            return DispatchResult(
                ok=False,
                broker_order_id=broker_order_id,
                error="Sandbox strategy cancellation failed",
            )
        result = _normalise(ok, response)
        return DispatchResult(
            ok=result.ok,
            broker_order_id=result.broker_order_id or broker_order_id,
            response=result.response,
            error=result.error,
        )
    if mode != "live":
        return DispatchResult(ok=False, error=f"Unknown run mode: {mode!r}")

    auth_token, broker, error = resolve_live_auth(api_key)
    if error:
        return DispatchResult(ok=False, broker_order_id=broker_order_id, error=error)

    from services.cancel_order_service import import_broker_module

    broker_module = import_broker_module(broker)
    if broker_module is None:
        return DispatchResult(
            ok=False,
            broker_order_id=broker_order_id,
            error="Broker-specific cancellation module is unavailable",
        )
    try:
        response, status_code = broker_module.cancel_order(broker_order_id, auth_token)
    except Exception:
        logger.exception("Live strategy cancellation raised for %s", broker_order_id)
        return DispatchResult(
            ok=False,
            broker_order_id=broker_order_id,
            error="Live strategy cancellation failed",
        )
    payload = response if isinstance(response, dict) else {}
    if status_code == 200:
        return DispatchResult(ok=True, broker_order_id=broker_order_id, response=payload)
    return DispatchResult(
        ok=False,
        broker_order_id=broker_order_id,
        response=payload,
        error=payload.get("message") or "Broker refused strategy cancellation",
    )


def cancel_exit_order(
    *,
    mode: str,
    api_key: str,
    broker_order_id: str,
) -> DispatchResult:
    """Backward-compatible name for correction-retry cancellation."""
    return cancel_order(
        mode=mode,
        api_key=api_key,
        broker_order_id=broker_order_id,
    )


def fetch_order_status(
    *,
    mode: str,
    api_key: str,
    broker_order_id: str,
) -> OrderStatusResult:
    """Read one order through the run's sandbox or live order-status path."""
    if not broker_order_id:
        return OrderStatusResult(ok=False, error="Broker order id is unavailable")

    request = {"orderid": broker_order_id}
    if mode == "sandbox":
        from services.sandbox_service import sandbox_get_order_status

        original = {**request, "apikey": api_key}
        try:
            ok, response, _status = sandbox_get_order_status(request, api_key, original)
        except Exception:
            logger.exception("Sandbox strategy status lookup raised for %s", broker_order_id)
            return OrderStatusResult(ok=False, error="Sandbox order status lookup failed")
    elif mode == "live":
        auth_token, broker, error = resolve_live_auth(api_key)
        if error:
            return OrderStatusResult(ok=False, error=error)

        from services.orderstatus_service import get_order_status

        try:
            ok, response, _status = get_order_status(
                dict(request),
                auth_token=auth_token,
                broker=broker,
            )
        except Exception:
            logger.exception("Live strategy status lookup raised for %s", broker_order_id)
            return OrderStatusResult(ok=False, error="Live order status lookup failed")
    else:
        return OrderStatusResult(ok=False, error=f"Unknown run mode: {mode!r}")

    payload = response if isinstance(response, dict) else {}
    order = payload.get("data")
    if ok and isinstance(order, dict):
        return OrderStatusResult(ok=True, order=order)
    return OrderStatusResult(
        ok=False,
        error=payload.get("message") or "Broker order status is unavailable",
    )


def _dispatch_sandbox(api_key: str, order: dict[str, Any]) -> DispatchResult:
    from services.sandbox_service import sandbox_place_order

    original = dict(order)
    original["apikey"] = api_key
    try:
        ok, response, _status = sandbox_place_order(dict(order), api_key, original)
    except Exception:
        logger.exception("Sandbox order placement raised for %s", order.get("symbol"))
        return DispatchResult(ok=False, error="Sandbox order placement failed")

    return _normalise(ok, response)


def _dispatch_live(api_key: str, order: dict[str, Any]) -> DispatchResult:
    auth_token, broker, error = resolve_live_auth(api_key)
    if error:
        # Deliberately not attempted. See the module docstring: refusing and
        # saying so leaves a recoverable situation, and a silent failure does
        # not.
        return DispatchResult(ok=False, error=error)

    from services.place_order_service import place_order_with_auth

    original = dict(order)
    original["apikey"] = api_key
    try:
        ok, response, _status = place_order_with_auth(
            dict(order),
            auth_token,
            broker,
            original,
            # The run already decided this is live. Without force_live the
            # platform-wide analyzer toggle would divert it to the sandbox,
            # which reports success and leaves a real position orphaned.
            force_live=True,
        )
    except Exception:
        logger.exception("Live order placement raised for %s", order.get("symbol"))
        return DispatchResult(ok=False, error="Live order placement failed")

    return _normalise(ok, response)


def _normalise(ok: bool, response: Any) -> DispatchResult:
    """One shape out of either pipe."""
    payload = response if isinstance(response, dict) else {}
    if ok:
        return DispatchResult(
            ok=True,
            broker_order_id=payload.get("orderid"),
            response=payload,
        )
    return DispatchResult(
        ok=False,
        # A rejected order can still carry a broker reference, and the audit row
        # is more useful with it than without.
        broker_order_id=payload.get("orderid"),
        response=payload,
        error=payload.get("message") or "Order rejected",
    )
