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

**The broker is the run's, not the session's.** The token is fresh per order,
but which broker (and, when the session names one, which account) the order
belongs to was fixed when the run started, and is passed in as a
:class:`BrokerBinding`. OpenAlgo lets a trader log out of one broker and in to
another. Resolving the broker at send time sent a run's exits to whichever
broker was logged in by then: the cover for a short held at the first opened a
new position at the second and left the first with nothing managing it. A live
order, cancel or status read whose session is on another broker or account is
refused here, before anything is sent, and the run keeps its position and its
risk management until the trader logs back in to the right one.
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


#: What a live run's broker column holds before the run knows its broker. A
#: batch run records "" when no session could be read at start, and a signal
#: run opened while no broker was logged in records its mode, "live".
UNBOUND_BROKERS = frozenset({"", "live"})


@dataclass(frozen=True, slots=True)
class BrokerBinding:
    """The broker a live run's orders belong to, recorded when the run started.

    ``account`` is the broker account id the session carried at the time, when
    the broker's login gives one (``Auth.user_id``), and None otherwise. It is
    compared only when both it and the current session's are known, so a broker
    whose login names no account is bound by broker alone.

    ``user_id`` is the OpenAlgo user whose stored session is compared; it is how
    the current account is read, and nothing else.
    """

    broker: str
    account: str | None = None
    user_id: str | None = None

    @property
    def known(self) -> bool:
        """Whether the run has a broker to be held to."""
        return _broker_key(self.broker) not in UNBOUND_BROKERS


def _broker_key(broker: Any) -> str:
    return str(broker or "").strip().lower()


def _account_key(account: Any) -> str:
    # Client codes are typed by hand on some brokers' login forms, so the same
    # account can arrive as "ab1234" one day and "AB1234" the next. Treating
    # those as two accounts would refuse a stop loss on the account it belongs to.
    return str(account or "").strip().upper()


def _broker_name(broker: str) -> str:
    try:
        from utils.broker_keys import broker_title

        return broker_title(broker)
    except Exception:
        return (broker or "").capitalize()


def session_account(user_id: str | None) -> str | None:
    """The broker account id the user's stored session carries, or None.

    Only some brokers' logins record one. None is "not known", never "none":
    the binding is then held by broker alone.
    """
    if not user_id:
        return None
    try:
        from database.auth_db import get_user_id

        account = str(get_user_id(user_id) or "").strip()
        return account or None
    except Exception:
        logger.exception("Could not read the broker account of the stored session")
        return None


def binding_refusal(
    binding: BrokerBinding | None,
    broker: str | None,
    account: str | None,
) -> str | None:
    """Why a live call for ``binding`` may not go through this session, or None.

    ``broker`` and ``account`` describe the session OpenAlgo is logged in to
    now. The sentence is for a trader: it names both brokers and what to do.
    """
    if binding is None or not binding.known:
        return (
            "OpenAlgo could not confirm which broker this strategy's run trades on, so "
            "nothing was sent. Try again; if this repeats, check the run's positions at "
            "your broker."
        )
    bound = _broker_name(_broker_key(binding.broker))
    if _broker_key(binding.broker) != _broker_key(broker):
        current = _broker_name(_broker_key(broker))
        return (
            f"OpenAlgo is logged in to {current}, but this strategy's run trades on "
            f"{bound}, so nothing was sent to {current}. Log in to {bound} to manage it."
        )
    if binding.account and account and _account_key(binding.account) != _account_key(account):
        return (
            f"OpenAlgo is logged in to {bound} account {account}, but this strategy's run "
            f"trades on {bound} account {binding.account}, so nothing was sent. Log in to "
            f"{bound} with account {binding.account} to manage it."
        )
    return None


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


def resolve_bound_auth(
    api_key: str,
    binding: BrokerBinding | None,
) -> tuple[str | None, str | None, str | None]:
    """``(auth_token, broker, error)`` for a live call on behalf of a bound run.

    The session is resolved first, so a missing or expired one is reported as
    that rather than as a mismatch. The token is read before the account: both
    come from one stored row, so an account read after the token is never older
    than it, and a re-login landing between the two can only produce a refusal.
    """
    auth_token, broker, error = resolve_live_auth(api_key)
    if error:
        return None, None, error
    account = None
    if binding is not None and binding.account:
        # Read only when the run recorded one: there is nothing to compare
        # otherwise, and it costs a query on every order.
        account = session_account(binding.user_id)
    refusal = binding_refusal(binding, broker, account)
    if refusal:
        logger.warning(
            "Live strategy call refused: the run is bound to %s, the session is on %s",
            _broker_key(binding.broker if binding else ""),
            _broker_key(broker),
        )
        return None, None, refusal
    return auth_token, broker, None


def dispatch_order(
    *,
    mode: str,
    api_key: str,
    order: dict[str, Any],
    binding: BrokerBinding | None = None,
) -> DispatchResult:
    """Place one order, live or sandbox, and normalise the answer.

    Both pipes return ``(success, response, status_code)``, so the caller gets
    one shape whichever ran. ``binding`` is the run's broker; a live order
    without one, or whose session is on another broker or account, is refused
    without being sent. The sandbox pipe does not read it.
    """
    if mode == "sandbox":
        return _dispatch_sandbox(api_key, order)
    if mode == "live":
        return _dispatch_live(api_key, order, binding)
    return DispatchResult(ok=False, error=f"Unknown run mode: {mode!r}")


def cancel_order(
    *,
    mode: str,
    api_key: str,
    broker_order_id: str,
    binding: BrokerBinding | None = None,
) -> DispatchResult:
    """Cancel a strategy order through the run's own execution pipe.

    Used both for an entry whose run is stopping and for an exit retry made too
    large by a late cumulative correction. Like placement, this bypasses the
    platform analyzer toggle because ``mode`` was fixed durably at run start,
    and a live cancel goes only to the run's own broker: an order id from one
    broker sent to another names nothing, or names somebody else's order.
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

    auth_token, broker, error = resolve_bound_auth(api_key, binding)
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
    binding: BrokerBinding | None = None,
) -> DispatchResult:
    """Backward-compatible name for correction-retry cancellation."""
    return cancel_order(
        mode=mode,
        api_key=api_key,
        broker_order_id=broker_order_id,
        binding=binding,
    )


def fetch_order_status(
    *,
    mode: str,
    api_key: str,
    broker_order_id: str,
    binding: BrokerBinding | None = None,
) -> OrderStatusResult:
    """Read one order through the run's sandbox or live order-status path.

    A live read goes only to the run's own broker. Its answer is folded into
    run state as a fill or a cancellation, so a fact read from another broker
    about an order id that happens to exist there would be applied to a
    position it does not describe.
    """
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
        auth_token, broker, error = resolve_bound_auth(api_key, binding)
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


def _dispatch_live(
    api_key: str,
    order: dict[str, Any],
    binding: BrokerBinding | None,
) -> DispatchResult:
    auth_token, broker, error = resolve_bound_auth(api_key, binding)
    if error:
        # Deliberately not attempted. See the module docstring: refusing and
        # saying so leaves a recoverable situation, and a silent failure does
        # not. That holds for a session on another broker or account as much
        # as for a missing one: an exit sent there opens a position instead of
        # closing one.
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
