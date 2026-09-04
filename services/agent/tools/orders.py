"""The mutating toolkit: the only place the agent can change a real account.

Every tool in this file sends something to a broker. Nothing else in the agent
module does, which is why the whole safety apparatus is concentrated here.

The pipeline, in this exact order, for every tool
-------------------------------------------------

1. **Agno pauses for human approval.** Every method name is listed in
   :data:`MUTATING_TOOLS`, which is handed to the base class as
   ``requires_confirmation_tools``. Two independent checks make a typo there
   impossible to ship: the base class refuses to build a toolkit whose
   confirmation list names a tool it does not have, and :func:`_verify_toolkit`
   runs at import and refuses to load the module if a declared name is not a
   real method. A silently unconfirmed order tool is the failure this file
   exists to prevent, so neither check is advisory.
2. **An audit attempt row is written before anything else.** Before validation,
   before the guard, before any service is touched, through
   ``OpenAlgoToolkit.audit_attempt``. An attempt with no matching result row is
   how an operator sees a call that hung or a worker that died mid-order.
3. **The risk guard runs inside the tool body**, after approval and before the
   service call. ``services.agent.safety.risk`` reads no prompt, so no wording
   in a conversation, a symbol name or an earlier tool result can change its
   verdict. A refusal is **returned** as the tool result, never raised, so the
   model reads the reason instead of retrying a rejection as if it were a
   transient fault.
4. **The service is called**, through ``services.*`` directly. No tool here
   makes an HTTP request back into this process and none of them touches the
   ``openalgo`` SDK.
5. **An audit result row is written** with the outcome and the broker order ids.

Two things the guard cannot do for itself
-----------------------------------------

The guard performs no I/O by design, so the last traded price and the available
cash its notional and affordability checks need are fetched **here** and passed
in. Both reads fail open: they return None on any failure and the guard then
skips those two checks with a warning, because refusing a human-approved order
because a quote endpoint hiccuped is the worse failure. Everything else in the
guard fails closed.

Which failures are retryable
----------------------------

A **fixable input error** raises ``RetryAgentRun`` naming the argument: a LIMIT
with no price, an SL with no trigger, an unknown product. Those are caught
before anything is dispatched, so nothing has been sent when the model is asked
to correct itself.

An **upstream failure** returns a JSON error result instead. Once an order has
been handed to the service layer, an automatic retry is how one intention
becomes two orders, so a broker rejection, a refused dispatch and an unexpected
exception all come back as data the model reports rather than as a signal to try
again.

Credentials
-----------

No tool here takes an API key as an argument and no result carries one. The key
lives on the toolkit instance, is passed to the service layer as a keyword, and
every result is filtered through ``services.agent.safety.audit.redact`` before
it reaches the model, so a key that arrives inside a broker response is dropped
rather than serialised. Results are then wrapped by
``services.agent.prompts.wrap_tool_result`` so text a broker wrote re-enters the
context labelled as data.

Import placement
----------------

The order services are imported inside the functions that call them, not at the
top of this module. ``services.place_order_service`` reaches
``restx_api.schemas``, which runs ``restx_api/__init__.py``, which imports a
service that imports ``services.place_order_service`` again: a pre-existing
cycle that resolves only when something else has already imported ``restx_api``
first, as the running application does.

Deferring those imports is necessary but **not sufficient**, and that is worth
being precise about because the difference is a mutating tool failing at the
moment it is used. A local import does not break the cycle, it only moves when
the cycle is entered: whichever module reaches ``services.place_order_service``
first still triggers it, and if that is this toolkit then ``place_order`` fails
at call time with a partially-initialised module rather than at startup.
``app.py`` imports ``restx_api`` on line 141, so the running application never
sees it; a test, a script or any future process that builds a toolkit without
booting the app does. :func:`_ensure_order_services_importable` therefore warms
``restx_api`` once before the first dispatch, which makes the cycle resolve in
the order that works and costs nothing when the application has already done it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any

from agno.exceptions import RetryAgentRun

from services.agent import prompts
from services.agent.safety import audit as audit_trail
from services.agent.safety.risk import Verdict, get_guard
from services.agent.tools.base import OpenAlgoToolkit
from utils.constants import (
    PRICE_TYPE_LIMIT,
    PRICE_TYPE_MARKET,
    PRICE_TYPE_SL,
    PRICE_TYPE_SLM,
    VALID_ACTIONS,
    VALID_EXCHANGES,
    VALID_PRICE_TYPES,
    VALID_PRODUCT_TYPES,
)
from utils.logging import get_logger

if TYPE_CHECKING:  # pragma: no cover - typing only
    from services.agent.safety.risk import RiskGuard
    from services.agent.tools import ToolContext

logger = get_logger(__name__)

#: The strategy name every order this toolkit sends is tagged with. It appears
#: in the order book, the logs and the alerts, so an operator can tell an
#: agent-placed order from one they placed themselves. It is a constant rather
#: than an argument: the model does not get to choose how its own orders are
#: attributed.
AGENT_STRATEGY = "OpenAlgo Agent"

#: Every tool this toolkit exposes. All of them change the account, so all of
#: them require human approval and the two are the same list by construction.
#: The order is the order the model sees them in.
MUTATING_TOOLS: tuple[str, ...] = (
    "place_order",
    "place_smart_order",
    "modify_order",
    "cancel_order",
    "cancel_all_orders",
    "close_position",
    "close_all_positions",
)

#: Keys a broker quote may carry the last traded price under. Checked in order.
_LTP_KEYS: tuple[str, ...] = ("ltp", "last_price", "lastPrice", "last_traded_price")

#: Keys a broker margin payload may carry spendable cash under. Checked in
#: order, so a broker that reports both a cash figure and a wider limit is read
#: as the cash figure.
_FUNDS_KEYS: tuple[str, ...] = (
    "availablecash",
    "available_cash",
    "availablemargin",
    "available_margin",
    "cash",
)

#: Price types that must carry a limit price, and those that must carry a
#: trigger. Everything not listed must carry neither: sending a price an order
#: type does not use is an error rather than a harmless extra field.
_NEEDS_PRICE: frozenset[str] = frozenset({PRICE_TYPE_LIMIT, PRICE_TYPE_SL})
_NEEDS_TRIGGER: frozenset[str] = frozenset({PRICE_TYPE_SL, PRICE_TYPE_SLM})


#: Set once the ``restx_api`` cycle has been warmed, so the check is a boolean
#: test rather than a ``sys.modules`` lookup on every mutating call.
_order_services_warmed = False


def _ensure_order_services_importable() -> None:
    """Import ``restx_api`` once so the order services import cleanly after it.

    ``services.place_order_service`` cannot be the module that enters the
    ``restx_api`` cycle: it imports ``restx_api.schemas``, which runs
    ``restx_api/__init__.py``, which reaches
    ``services.options_multiorder_service``, which imports ``place_order`` back
    out of the module still executing. Entering from ``restx_api`` instead makes
    every step of that chain complete in order.

    The running application already imports ``restx_api`` at startup, so this is
    a no-op there. It matters for a test or a script that builds the toolkit
    without booting the app, where the cycle would otherwise surface as an
    ``ImportError`` inside a mutating tool call.

    A failure is logged and swallowed: the caller's own import raises next and
    the pipeline reports that, which is a better message than one about a
    warm-up the model cannot act on.
    """
    global _order_services_warmed
    if _order_services_warmed:
        return
    _order_services_warmed = True
    try:
        import restx_api  # noqa: F401
    except Exception:
        logger.exception(
            "Could not pre-import restx_api; an order service import may fail on the cycle"
        )


def _decimal(value: Any) -> Decimal | None:
    """Coerce a broker-supplied number to a finite Decimal, or None.

    Args:
        value: Anything a quote or margin payload put in a numeric field.

    Returns:
        The value as a Decimal when it is finite and not a bool, otherwise None.
        A bool is rejected rather than coerced, because True arriving where a
        price belongs is a bug and reading it as 1.0 hides it.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return value if value.is_finite() else None
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, TypeError, ValueError, AttributeError):
        return None
    return parsed if parsed.is_finite() else None


@dataclass(frozen=True, slots=True)
class _Plan:
    """Everything :meth:`OrdersToolkit._run_mutation` needs after the guard ran.

    Built by each tool between its audit attempt row and its dispatch, so the
    runner owns the audit pairing, the refusal path and the claim bookkeeping
    while each tool owns only what it means to do.

    Attributes:
        verdict: The guard's decision. A refusing verdict stops the runner.
        dispatch: Calls the service and returns its raw result, unexamined. It
            must not be called when the verdict refuses.
        label: Human-readable name of the service call, used in failure text.
        extra: Fields merged into the successful result for the model, such as
            the order that was sent.
    """

    verdict: Verdict
    dispatch: Callable[[], Any]
    label: str
    extra: Mapping[str, Any] | None = None


class OrdersToolkit(OpenAlgoToolkit):
    """Place, modify, cancel and close real orders and positions.

    Every tool here pauses for the operator's approval, then runs the risk guard
    inside its own body before touching the service layer. The toolkit is
    withheld entirely from a session that has not enabled trading, and from the
    chart surface, by the registry in ``services/agent/tools/__init__.py``, so a
    model that may not trade never sees these functions in its schema at all.
    """

    def __init__(self, context: ToolContext) -> None:
        """Build the toolkit and register every tool as requiring confirmation.

        Args:
            context: The run's tool context. Must carry an OpenAlgo API key.

        Raises:
            ValueError: If the context carries no API key, or if the tools
                handed to agno and :data:`MUTATING_TOOLS` do not name exactly
                the same set. The base class catches a confirmation name that is
                not a tool; this catches the dangerous direction, a tool that is
                not in the confirmation list and would therefore run without
                anybody approving it.
            RuntimeError: If the installed agno cannot enforce confirmations.
        """
        super().__init__(
            context,
            name="orders",
            tools=[
                self.place_order,
                self.place_smart_order,
                self.modify_order,
                self.cancel_order,
                self.cancel_all_orders,
                self.close_position,
                self.close_all_positions,
            ],
            requires_confirmation_tools=list(MUTATING_TOOLS),
        )

        declared = set(self.declared_tools)
        unconfirmed = sorted(declared - set(MUTATING_TOOLS))
        if unconfirmed:
            raise ValueError(
                f"OrdersToolkit registered {', '.join(unconfirmed)} without listing them in "
                "MUTATING_TOOLS, so they would change the account with no human approval. "
                "Every tool in this toolkit is mutating and belongs in that list."
            )

        self.strategy = AGENT_STRATEGY

    # -- tools ---------------------------------------------------------------

    def place_order(
        self,
        symbol: str,
        exchange: str,
        action: str,
        quantity: int,
        product: str,
        price_type: str = "MARKET",
        price: float = 0.0,
        trigger_price: float = 0.0,
    ) -> str:
        """Place a real order on the operator's live broker account.

        THIS PLACES A REAL ORDER WITH REAL MONEY and pauses for the operator's
        explicit approval before it runs. After they approve, a risk check runs
        inside this tool and can still refuse the order; a refusal is reported,
        not retried. If the platform is in analyzer mode the order goes to the
        sandbox instead, and the result says so.

        State the whole order in words before calling: action, quantity, symbol,
        exchange, product, price type and any price or trigger. The operator
        approves what you stated.

        Args:
            symbol: OpenAlgo symbol, exactly as the symbol search or option
                chain returned it. For example ``RELIANCE``,
                ``BANKNIFTY24APR24FUT`` or ``NIFTY28MAR2420800CE``. Never
                construct an expiry or a strike yourself.
            exchange: Exchange code the symbol trades on. One of NSE, BSE (cash
                equity), NFO, BFO (futures and options), CDS, BCD (currency),
                MCX, NCDEX, NCO (commodity), CRYPTO. The index codes NSE_INDEX,
                BSE_INDEX, MCX_INDEX and GLOBAL_INDEX are quote-only and an
                order on one is always wrong.
            action: ``BUY`` or ``SELL``.
            quantity: Whole number of units, not lots. For example ``10`` shares
                of RELIANCE, or ``75`` for one NIFTY option lot of 75. Look the
                lot size up rather than assuming it.
            product: ``CNC`` for delivery in a cash segment, ``NRML`` to carry a
                derivative overnight, ``MIS`` for intraday in either. CNC on a
                derivatives exchange is always wrong.
            price_type: ``MARKET`` (default, no price and no trigger), ``LIMIT``
                (needs price), ``SL`` (stop-loss limit, needs both price and
                trigger_price) or ``SL-M`` (stop-loss market, needs
                trigger_price only). Use MARKET unless the operator asked for
                something else.
            price: Limit price in rupees, for example ``1450.5``. Required for
                LIMIT and SL, and must be left at 0 for MARKET and SL-M. It must
                respect the instrument's tick size.
            trigger_price: Trigger price in rupees, for example ``1440.0``.
                Required for SL and SL-M, and must be left at 0 for MARKET and
                LIMIT.

        Returns:
            JSON carrying ``ok``, the broker ``order_ids``, the order as it was
            sent, the risk verdict, and the service response. On a refusal it
            carries ``status`` of ``blocked`` and the reason; on a failure,
            ``status`` of ``error`` and the broker's own message.
        """
        args = {
            "symbol": symbol,
            "exchange": exchange,
            "action": action,
            "quantity": quantity,
            "product": product,
            "price_type": price_type,
            "price": price,
            "trigger_price": trigger_price,
        }

        def plan() -> _Plan:
            from services.place_order_service import place_order as place_order_service

            order = self._build_order(
                symbol=symbol,
                exchange=exchange,
                action=action,
                quantity=quantity,
                product=product,
                price_type=price_type,
                price=price,
                trigger_price=trigger_price,
            )
            verdict = self._guard().check_order(
                symbol=order["symbol"],
                exchange=order["exchange"],
                action=order["action"],
                quantity=order["quantity"],
                product=order["product"],
                price_type=order["pricetype"],
                price=order["price"],
                trigger_price=order["trigger_price"],
                ltp=self._last_traded_price(order["symbol"], order["exchange"]),
                available_funds=self._available_funds(),
                analyzer_mode=self._analyzer_mode(),
            )
            return _Plan(
                verdict=verdict,
                dispatch=lambda: place_order_service(order_data=dict(order), api_key=self.api_key),
                label="place_order_service.place_order",
                extra={"order": order},
            )

        return self._run_mutation(
            "place_order", args, plan, symbol=str(symbol), exchange=str(exchange)
        )

    def place_smart_order(
        self,
        symbol: str,
        exchange: str,
        action: str,
        quantity: int,
        position_size: int,
        product: str,
        price_type: str = "MARKET",
        price: float = 0.0,
        trigger_price: float = 0.0,
    ) -> str:
        """Place a real order that moves a position to a target size.

        THIS PLACES A REAL ORDER WITH REAL MONEY and pauses for the operator's
        explicit approval before it runs. A risk check runs inside this tool
        after that approval and can still refuse it.

        A smart order compares ``position_size`` with the position the account
        actually holds in this symbol and product, then sends only the
        difference. Holding 100 and asking for 150 buys 50; holding 100 and
        asking for -100 sells 200; holding exactly the target sends nothing and
        reports that no action was needed. Use it when the operator describes a
        position they want to end up with rather than a trade they want to send.

        Because the order the broker finally sends is a difference this tool
        cannot know in advance, the risk check is sized on the larger of
        ``quantity`` and the absolute target position, which is the closest
        conservative figure available.

        Args:
            symbol: OpenAlgo symbol, exactly as a lookup returned it, for
                example ``INFY`` or ``NIFTY28MAR2420800CE``.
            exchange: Exchange code the symbol trades on, for example ``NSE`` or
                ``NFO``. Index codes are quote-only and cannot be traded.
            action: ``BUY`` or ``SELL``. It is used only when the account holds
                no position in this symbol and the target is zero; otherwise the
                direction is derived from the difference.
            quantity: Whole number of units to send when there is no position
                and no target, for example ``50``. Not lots.
            position_size: The position to end up holding, in units and signed:
                ``150`` for long 150, ``-75`` for short 75, ``0`` for flat. To
                flatten an existing position use the ``close_position`` tool
                instead, which is built for it.
            product: ``CNC``, ``NRML`` or ``MIS``. The position is matched
                within this product, so it must be the product the position is
                held under.
            price_type: ``MARKET`` (default), ``LIMIT``, ``SL`` or ``SL-M``.
            price: Limit price in rupees, for example ``1450.5``. Required for
                LIMIT and SL, left at 0 otherwise.
            trigger_price: Trigger price in rupees, for example ``1440.0``.
                Required for SL and SL-M, left at 0 otherwise.

        Returns:
            JSON carrying ``ok``, the broker ``order_ids``, the order as it was
            sent, the risk verdict and the service response. When the position
            already matches the target the response says so and no order was
            sent.
        """
        args = {
            "symbol": symbol,
            "exchange": exchange,
            "action": action,
            "quantity": quantity,
            "position_size": position_size,
            "product": product,
            "price_type": price_type,
            "price": price,
            "trigger_price": trigger_price,
        }

        def plan() -> _Plan:
            from services.place_smart_order_service import (
                place_smart_order as place_smart_order_service,
            )

            target = self._whole_number("position_size", position_size, minimum=None)
            order = self._build_order(
                symbol=symbol,
                exchange=exchange,
                action=action,
                quantity=quantity,
                product=product,
                price_type=price_type,
                price=price,
                trigger_price=trigger_price,
                allow_zero_quantity=True,
            )
            order["position_size"] = target

            exposure = max(abs(target), order["quantity"])
            if exposure <= 0:
                self.invalid_argument(
                    "position_size",
                    "a smart order with both quantity and position_size at zero flattens "
                    "whatever the account happens to be holding, which is not something to "
                    "ask for by accident.",
                    "Use the close_position tool to flatten a position, or give a non-zero "
                    "position_size for the position you want to end up with.",
                )

            verdict = self._guard().check_order(
                symbol=order["symbol"],
                exchange=order["exchange"],
                action=order["action"],
                quantity=exposure,
                product=order["product"],
                price_type=order["pricetype"],
                price=order["price"],
                trigger_price=order["trigger_price"],
                ltp=self._last_traded_price(order["symbol"], order["exchange"]),
                available_funds=self._available_funds(),
                analyzer_mode=self._analyzer_mode(),
            )
            return _Plan(
                verdict=verdict,
                dispatch=lambda: place_smart_order_service(
                    order_data=dict(order), api_key=self.api_key
                ),
                label="place_smart_order_service.place_smart_order",
                extra={"order": order, "risk_checked_quantity": exposure},
            )

        return self._run_mutation(
            "place_smart_order", args, plan, symbol=str(symbol), exchange=str(exchange)
        )

    def modify_order(
        self,
        order_id: str,
        symbol: str,
        exchange: str,
        action: str,
        quantity: int,
        product: str,
        price_type: str,
        price: float = 0.0,
        trigger_price: float = 0.0,
    ) -> str:
        """Modify a real pending order on the broker.

        THIS CHANGES A REAL ORDER and pauses for the operator's explicit
        approval before it runs. A risk check runs inside this tool after that
        approval and can still refuse it.

        The broker replaces the order wholesale, so every field below is sent
        whether or not it changed. Read the order book first and repeat the
        values you are not changing, or an unstated field is silently
        overwritten with whatever you passed here.

        Args:
            order_id: The broker's order id, exactly as the order book reported
                it, for example ``240307000616990``. Never invent one.
            symbol: OpenAlgo symbol of the existing order, for example ``INFY``.
            exchange: Exchange code of the existing order, for example ``NSE``.
            action: ``BUY`` or ``SELL``. This is the side of the existing order;
                a modify does not flip it.
            quantity: The order quantity after the change, in whole units.
            product: ``CNC``, ``NRML`` or ``MIS``, matching the existing order.
            price_type: ``MARKET``, ``LIMIT``, ``SL`` or ``SL-M`` after the
                change. There is no default: state what the order should become.
            price: Limit price in rupees after the change, for example
                ``1455.0``. Required for LIMIT and SL, left at 0 otherwise.
            trigger_price: Trigger price in rupees after the change. Required
                for SL and SL-M, left at 0 otherwise.

        Returns:
            JSON carrying ``ok``, the ``order_ids`` the broker confirmed, the
            payload that was sent, the risk verdict and the service response.
        """
        args = {
            "order_id": order_id,
            "symbol": symbol,
            "exchange": exchange,
            "action": action,
            "quantity": quantity,
            "product": product,
            "price_type": price_type,
            "price": price,
            "trigger_price": trigger_price,
        }

        def plan() -> _Plan:
            from services.modify_order_service import modify_order as modify_order_service

            identifier = self._order_id(order_id)
            order = self._build_order(
                symbol=symbol,
                exchange=exchange,
                action=action,
                quantity=quantity,
                product=product,
                price_type=price_type,
                price=price,
                trigger_price=trigger_price,
            )
            order["orderid"] = identifier
            verdict = self._guard().check_destructive(
                "modify_order",
                analyzer_mode=self._analyzer_mode(),
                orderid=identifier,
                symbol=order["symbol"],
                exchange=order["exchange"],
                quantity=order["quantity"],
            )
            return _Plan(
                verdict=verdict,
                dispatch=lambda: modify_order_service(order_data=dict(order), api_key=self.api_key),
                label="modify_order_service.modify_order",
                extra={"order": order},
            )

        return self._run_mutation(
            "modify_order",
            args,
            plan,
            symbol=str(symbol),
            exchange=str(exchange),
            order_id=str(order_id),
        )

    def cancel_order(self, order_id: str) -> str:
        """Cancel one real pending order on the broker.

        THIS CANCELS A REAL ORDER and pauses for the operator's explicit
        approval before it runs. A risk check runs inside this tool after that
        approval and can still refuse it.

        Only a working order can be cancelled. An order that is already
        complete, rejected or cancelled comes back as a failure from the broker,
        which is information rather than something to retry.

        Args:
            order_id: The broker's order id, exactly as the order book reported
                it, for example ``240307000616990``. Read it from the order book
                rather than reconstructing it.

        Returns:
            JSON carrying ``ok``, the cancelled ``order_ids``, the risk verdict
            and the service response.
        """
        args = {"order_id": order_id}

        def plan() -> _Plan:
            from services.cancel_order_service import cancel_order as cancel_order_service

            identifier = self._order_id(order_id)
            verdict = self._guard().check_destructive(
                "cancel_order",
                analyzer_mode=self._analyzer_mode(),
                orderid=identifier,
            )
            return _Plan(
                verdict=verdict,
                dispatch=lambda: cancel_order_service(orderid=identifier, api_key=self.api_key),
                label="cancel_order_service.cancel_order",
                extra={"order_id": identifier},
            )

        return self._run_mutation("cancel_order", args, plan, order_id=str(order_id))

    def cancel_all_orders(self) -> str:
        """Cancel every open order on the account.

        THIS CANCELS EVERY PENDING ORDER ON THE WHOLE ACCOUNT, including orders
        the operator placed by hand and orders belonging to other strategies. It
        pauses for the operator's explicit approval before it runs, and a risk
        check runs inside this tool after that approval.

        Account-wide operations are switched off by default and the risk check
        refuses this outright until an operator turns them on in the agent
        settings. That refusal is the intended answer, not a fault: report it
        and offer to cancel the specific orders instead.

        Returns:
            JSON carrying ``ok``, how many orders were cancelled and how many
            failed, the risk verdict and the service response.
        """

        def plan() -> _Plan:
            from services.cancel_all_order_service import (
                cancel_all_orders as cancel_all_orders_service,
            )

            verdict = self._guard().check_destructive(
                "cancel_all_orders", analyzer_mode=self._analyzer_mode()
            )
            return _Plan(
                verdict=verdict,
                dispatch=lambda: cancel_all_orders_service(
                    order_data={"strategy": self.strategy}, api_key=self.api_key
                ),
                label="cancel_all_order_service.cancel_all_orders",
            )

        return self._run_mutation("cancel_all_orders", {}, plan)

    def close_position(self, symbol: str, exchange: str, product: str) -> str:
        """Close one real open position by squaring it off at market.

        THIS SENDS A REAL ORDER WITH REAL MONEY and pauses for the operator's
        explicit approval before it runs. A risk check runs inside this tool
        after that approval and can still refuse it.

        The position held in this symbol and product is read first, and an
        offsetting market order for exactly that quantity is sent: a long is
        sold, a short is bought back. If the account holds nothing there,
        nothing is sent and the result says so.

        This closes one named position. To flatten the entire account use
        ``close_all_positions``, which is a different and much larger action.

        Args:
            symbol: OpenAlgo symbol of the position, exactly as the position
                book reported it, for example ``INFY`` or
                ``NIFTY28MAR2420800CE``.
            exchange: Exchange code of the position, for example ``NSE`` or
                ``NFO``.
            product: The product the position is held under: ``CNC``, ``NRML``
                or ``MIS``. A position is held per product, so the wrong product
                closes nothing. Read it from the position book.

        Returns:
            JSON carrying ``ok``, the broker ``order_ids``, the quantity that
            was held, the risk verdict and the service response.
        """
        args = {"symbol": symbol, "exchange": exchange, "product": product}

        def plan() -> _Plan:
            clean_symbol = self._required_text("symbol", symbol).upper()
            clean_exchange = self._exchange(exchange)
            clean_product = self._product(product)
            verdict = self._guard().check_destructive(
                "close_position",
                analyzer_mode=self._analyzer_mode(),
                symbol=clean_symbol,
                exchange=clean_exchange,
                product=clean_product,
            )
            return _Plan(
                verdict=verdict,
                dispatch=lambda: self._square_off(clean_symbol, clean_exchange, clean_product),
                label="place_smart_order_service.place_smart_order",
                extra={
                    "symbol": clean_symbol,
                    "exchange": clean_exchange,
                    "product": clean_product,
                },
            )

        return self._run_mutation(
            "close_position", args, plan, symbol=str(symbol), exchange=str(exchange)
        )

    def close_all_positions(self) -> str:
        """Square off every open position on the account.

        THIS CLOSES EVERY POSITION ON THE WHOLE ACCOUNT WITH REAL MONEY,
        including positions the operator opened by hand and positions belonging
        to other strategies. It pauses for the operator's explicit approval
        before it runs, and a risk check runs inside this tool after that
        approval.

        Account-wide operations are switched off by default and the risk check
        refuses this outright until an operator turns them on in the agent
        settings. That refusal is the intended answer, not a fault: report it
        and offer to close the named positions with ``close_position`` instead.

        Returns:
            JSON carrying ``ok``, the risk verdict and the service response
            describing what was squared off.
        """

        def plan() -> _Plan:
            from services.close_position_service import close_position as close_position_service

            verdict = self._guard().check_destructive(
                "close_all_positions", analyzer_mode=self._analyzer_mode()
            )
            return _Plan(
                verdict=verdict,
                dispatch=lambda: close_position_service(
                    position_data={"strategy": self.strategy}, api_key=self.api_key
                ),
                label="close_position_service.close_position",
            )

        return self._run_mutation("close_all_positions", {}, plan)

    # -- the pipeline --------------------------------------------------------

    def _run_mutation(
        self,
        tool: str,
        args: Mapping[str, Any],
        plan_factory: Callable[[], _Plan],
        **attributes: Any,
    ) -> str:
        """Run one mutating tool through the audit, guard and dispatch pipeline.

        The order of the five steps is fixed by the build contract and this
        method is the only place it is implemented, so no tool can accidentally
        run them in a different order or skip one.

        Args:
            tool: The tool's registered name, used on both audit rows.
            args: The arguments the model supplied, recorded on the attempt row
                after the base class redacts them.
            plan_factory: Validates the arguments, fetches whatever the guard
                needs, runs the guard and returns a :class:`_Plan`. It runs
                after the attempt row is written, so a call rejected during
                validation still leaves a trail.
            **attributes: Labels for the untrusted-content wrapper around the
                result, such as the symbol and exchange.

        Returns:
            The wrapped JSON result for the model.

        Raises:
            RetryAgentRun: When validation rejects an argument the model can
                correct. Nothing has been dispatched at that point.
        """
        attempt_id = self.audit_attempt(tool, args)

        try:
            # Every mutating tool reaches an order service through plan_factory
            # or through the dispatch it returns, so warming the restx_api cycle
            # here covers all seven of them from one place.
            _ensure_order_services_importable()
            plan = plan_factory()
        except RetryAgentRun as exc:
            self.audit_result(
                tool,
                ok=False,
                response={"status": "error", "stage": "validation", "message": str(exc)},
                order_ids=[],
                attempt_id=attempt_id,
            )
            raise
        except Exception as exc:
            logger.exception("Agent tool %s could not be prepared", tool)
            self.audit_result(
                tool,
                ok=False,
                response={
                    "status": "error",
                    "stage": "validation",
                    "message": f"{type(exc).__name__}: {exc}",
                },
                order_ids=[],
                attempt_id=attempt_id,
            )
            return self._emit(
                tool,
                {
                    "ok": False,
                    "tool": tool,
                    "status": "error",
                    "message": (
                        f"{tool} could not be prepared: {type(exc).__name__}: {exc}. Nothing "
                        "was sent to the broker. Report this to the operator rather than "
                        "calling the tool again."
                    ),
                    "retry": False,
                },
                **attributes,
            )

        verdict = plan.verdict
        if not verdict.allowed:
            # A refusal is returned, never raised. Raising would read to the
            # model as a transient fault and invite the identical order again.
            self.audit_result(
                tool,
                ok=False,
                response={"status": "blocked", "risk": verdict.as_dict()},
                order_ids=[],
                attempt_id=attempt_id,
                risk_verdict=str(verdict.code),
            )
            logger.warning("Agent risk guard refused %s: %s", tool, verdict.as_message())
            return self._emit(
                tool,
                {
                    "ok": False,
                    "tool": tool,
                    "status": "blocked",
                    "blocked_by": "risk_guard",
                    "code": str(verdict.code),
                    "message": verdict.as_message(),
                    "risk": verdict.as_dict(),
                    "retry": False,
                },
                **attributes,
            )

        guard = self._guard()
        try:
            raw = plan.dispatch()
        except Exception as exc:
            # The outcome is unknown: the order may have reached the broker
            # before this failed. The claim is deliberately NOT released, so the
            # duplicate window still refuses an identical immediate resend.
            logger.exception("Agent tool %s raised while dispatching", tool)
            self.audit_result(
                tool,
                ok=False,
                response={
                    "status": "unknown",
                    "message": f"{type(exc).__name__}: {exc}",
                    "risk": verdict.as_dict(),
                },
                order_ids=[],
                attempt_id=attempt_id,
                risk_verdict=str(verdict.code),
            )
            return self._emit(
                tool,
                {
                    "ok": False,
                    "tool": tool,
                    "status": "unknown",
                    "message": (
                        f"{plan.label} raised {type(exc).__name__}: {exc}. Whether the broker "
                        "received it is not known, so do NOT send it again. Tell the operator "
                        "to check the order book."
                    ),
                    "risk": verdict.as_dict(),
                    "retry": False,
                },
                **attributes,
            )

        try:
            payload = self.unwrap_service_result(raw, label=plan.label)
        except RetryAgentRun as exc:
            # A clean refusal from the service layer: nothing was placed, so the
            # claim goes back and the session keeps its budget.
            guard.release(verdict)
            self.audit_result(
                tool,
                ok=False,
                response={"status": "error", "message": str(exc), "risk": verdict.as_dict()},
                order_ids=[],
                attempt_id=attempt_id,
                risk_verdict=str(verdict.code),
            )
            return self._emit(
                tool,
                {
                    "ok": False,
                    "tool": tool,
                    "status": "error",
                    "message": str(exc),
                    "risk": verdict.as_dict(),
                    "retry": False,
                },
                **attributes,
            )

        guard.commit(verdict)
        order_ids = self.extract_order_ids(payload)
        self.audit_result(
            tool,
            ok=True,
            response=payload,
            order_ids=order_ids,
            attempt_id=attempt_id,
            risk_verdict=str(verdict.code),
        )

        result: dict[str, Any] = {
            "ok": True,
            "tool": tool,
            "status": "success",
            "order_ids": order_ids,
            "risk": verdict.as_dict(),
            "response": audit_trail.redact(payload),
        }
        if plan.extra:
            result.update(plan.extra)
        return self._emit(tool, result, **attributes)

    def _emit(self, tool: str, payload: Mapping[str, Any], **attributes: Any) -> str:
        """Serialise a result and wrap it as untrusted content.

        Every result carries text somebody else wrote, most obviously a broker
        rejection message, so it re-enters the model's context inside a labelled
        block rather than as prose.

        Args:
            tool: The tool's registered name.
            payload: The result structure.
            **attributes: Labels for the opening tag. Values are escaped.

        Returns:
            A ``<tool_result>`` block wrapping the capped JSON.
        """
        return prompts.wrap_tool_result(tool, self.to_json(payload), **attributes)

    def _guard(self) -> RiskGuard:
        """The risk guard for this agent session.

        One guard per session, so the session order cap and the duplicate-order
        window mean what they say across a whole conversation rather than
        resetting on every message.

        Returns:
            The shared guard for this run's session.
        """
        return get_guard(str(self.session_id or self.conversation_id or "default"))

    # -- validation ----------------------------------------------------------

    def _build_order(
        self,
        *,
        symbol: str,
        exchange: str,
        action: str,
        quantity: Any,
        product: str,
        price_type: str,
        price: Any,
        trigger_price: Any,
        allow_zero_quantity: bool = False,
    ) -> dict[str, Any]:
        """Validate the model's arguments and build the service payload.

        Everything here is a fixable input error, so each failure raises
        ``RetryAgentRun`` naming the argument. Nothing has been dispatched yet.
        The risk guard re-checks all of it afterwards and is the authority; this
        exists so the model gets a correctable message rather than a refusal.

        Args:
            symbol: OpenAlgo symbol.
            exchange: Exchange code.
            action: BUY or SELL.
            quantity: Whole number of units.
            product: CNC, NRML or MIS.
            price_type: MARKET, LIMIT, SL or SL-M.
            price: Limit price.
            trigger_price: Trigger price.
            allow_zero_quantity: True for the smart order, whose quantity is
                unused when a target position is given.

        Returns:
            The order payload in the service layer's own field names, carrying
            the agent's strategy tag and no credential of any kind.

        Raises:
            RetryAgentRun: When an argument is missing, malformed, or
                inconsistent with the price type.
        """
        kind = self._price_type(price_type)
        limit_price = self._money("price", price)
        trigger = self._money("trigger_price", trigger_price)

        if kind in _NEEDS_PRICE and limit_price <= 0:
            self.invalid_argument(
                "price",
                f"a {kind} order is priced by the operator, so it needs a limit price.",
                f"Pass the price in rupees, for example price=1450.5, or use "
                f"{PRICE_TYPE_MARKET} if you meant to trade at whatever is available.",
            )
        if kind in _NEEDS_TRIGGER and trigger <= 0:
            self.invalid_argument(
                "trigger_price",
                f"a {kind} order only becomes live once the market reaches its trigger, "
                "so it needs one.",
                "Pass the trigger in rupees, for example trigger_price=1440.0.",
            )
        if kind not in _NEEDS_PRICE and limit_price > 0:
            self.invalid_argument(
                "price",
                f"a {kind} order carries no limit price, and sending one is an error rather "
                "than a harmless extra field.",
                f"Leave price at 0, or use {PRICE_TYPE_LIMIT} if you meant to name a price.",
            )
        if kind not in _NEEDS_TRIGGER and trigger > 0:
            self.invalid_argument(
                "trigger_price",
                f"a {kind} order carries no trigger price.",
                f"Leave trigger_price at 0, or use {PRICE_TYPE_SL} or {PRICE_TYPE_SLM} if you "
                "meant a stop order.",
            )

        return {
            "strategy": self.strategy,
            "symbol": self._required_text("symbol", symbol).upper(),
            "exchange": self._exchange(exchange),
            "action": self._action(action),
            "quantity": self._whole_number(
                "quantity", quantity, minimum=0 if allow_zero_quantity else 1
            ),
            "product": self._product(product),
            "pricetype": kind,
            "price": limit_price,
            "trigger_price": trigger,
            "disclosed_quantity": 0,
        }

    def _required_text(self, field: str, value: Any) -> str:
        """Return a non-empty stripped string, or reject the argument.

        Args:
            field: Argument name as the model sees it.
            value: The value supplied.

        Returns:
            The value stripped of surrounding whitespace.

        Raises:
            RetryAgentRun: When the value is empty or not text.
        """
        text = "" if value is None else str(value).strip()
        if not text:
            self.invalid_argument(
                field,
                "it was empty.",
                "Pass the value the operator gave you, or look it up with the symbol search "
                "tool first.",
            )
        return text

    def _order_id(self, value: Any) -> str:
        """Validate a broker order id.

        Args:
            value: The order id the model supplied.

        Returns:
            The order id as a stripped string.

        Raises:
            RetryAgentRun: When it is empty.
        """
        text = "" if value is None else str(value).strip()
        if not text:
            self.invalid_argument(
                "order_id",
                "it was empty, and an order cannot be identified without it.",
                "Read the exact order id from the order book and pass it verbatim.",
            )
        return text

    def _exchange(self, value: Any) -> str:
        """Validate an exchange code.

        Args:
            value: The exchange the model supplied.

        Returns:
            The upper-cased exchange code.

        Raises:
            RetryAgentRun: When it is not an OpenAlgo exchange code.
        """
        text = self._required_text("exchange", value).upper()
        if text not in VALID_EXCHANGES:
            self.invalid_argument(
                "exchange",
                f"{text} is not an OpenAlgo exchange code.",
                f"Use one of: {', '.join(VALID_EXCHANGES)}.",
            )
        return text

    def _action(self, value: Any) -> str:
        """Validate a BUY or SELL action.

        Args:
            value: The action the model supplied.

        Returns:
            The upper-cased action.

        Raises:
            RetryAgentRun: When it is neither BUY nor SELL.
        """
        text = self._required_text("action", value).upper()
        if text not in VALID_ACTIONS:
            self.invalid_argument(
                "action", f"{text} is not a side.", f"Use one of: {', '.join(VALID_ACTIONS)}."
            )
        return text

    def _product(self, value: Any) -> str:
        """Validate a product type.

        Args:
            value: The product the model supplied.

        Returns:
            The upper-cased product type.

        Raises:
            RetryAgentRun: When it is not a product OpenAlgo accepts.
        """
        text = self._required_text("product", value).upper()
        if text not in VALID_PRODUCT_TYPES:
            self.invalid_argument(
                "product",
                f"{text} is not a product type.",
                f"Use one of: {', '.join(VALID_PRODUCT_TYPES)}. CNC is delivery in a cash "
                "segment, NRML carries a derivative overnight, MIS is intraday.",
            )
        return text

    def _price_type(self, value: Any) -> str:
        """Validate a price type, accepting SLM as a spelling of SL-M.

        Args:
            value: The price type the model supplied.

        Returns:
            The canonical price type.

        Raises:
            RetryAgentRun: When it is not a price type OpenAlgo accepts.
        """
        text = self._required_text("price_type", value).upper()
        if text == "SLM":
            text = PRICE_TYPE_SLM
        if text not in VALID_PRICE_TYPES:
            self.invalid_argument(
                "price_type",
                f"{text} is not a price type.",
                f"Use one of: {', '.join(VALID_PRICE_TYPES)}.",
            )
        return text

    def _whole_number(self, field: str, value: Any, *, minimum: int | None) -> int:
        """Coerce an argument to a whole number of units.

        Args:
            field: Argument name as the model sees it.
            value: The value supplied.
            minimum: Smallest permitted value, or None for a signed quantity
                such as a target position size.

        Returns:
            The value as an int.

        Raises:
            RetryAgentRun: When it is not a whole number, or is below the
                minimum.
        """
        parsed = _decimal(value)
        if parsed is None:
            self.invalid_argument(
                field,
                f"{value!r} is not a number.",
                "Pass a whole number of units, for example 10.",
            )
        if parsed != parsed.to_integral_value():
            self.invalid_argument(
                field,
                f"{parsed} is not a whole number, and quantities are in units rather than "
                "fractions.",
                "Round to a whole number of units. For a derivative it must also be a "
                "multiple of the contract's lot size, which you look up rather than assume.",
            )
        number = int(parsed)
        if minimum is not None and number < minimum:
            self.invalid_argument(
                field,
                f"{number} is below the smallest permitted value of {minimum}.",
                "Quantity is a positive whole number of units, never lots and never zero.",
            )
        return number

    def _money(self, field: str, value: Any) -> float:
        """Coerce a price argument to a non-negative float.

        Args:
            field: Argument name as the model sees it.
            value: The value supplied.

        Returns:
            The price as a float. Zero means the field is unused.

        Raises:
            RetryAgentRun: When it is not a number, or is negative.
        """
        if value is None or value == "":
            return 0.0
        parsed = _decimal(value)
        if parsed is None:
            self.invalid_argument(
                field,
                f"{value!r} is not a number.",
                "Pass a price in rupees, for example 1450.5, or 0 when the order type does "
                "not use it.",
            )
        if parsed < 0:
            self.invalid_argument(
                field,
                f"{parsed} is negative.",
                "A price is zero or positive. Use 0 when the order type does not use it.",
            )
        return float(parsed)

    # -- reads the guard needs, all of them fail open ------------------------

    def _last_traded_price(self, symbol: str, exchange: str) -> Decimal | None:
        """Fetch the last traded price for the guard's pricing checks.

        The guard does no I/O, so the number it compares against is fetched
        here. This read **fails open**: on any failure it returns None and the
        guard skips the notional and deviation checks with a warning, because
        refusing an order the operator already approved over a quote endpoint
        hiccup is the worse failure, and the broker still runs its own checks.

        Args:
            symbol: OpenAlgo symbol.
            exchange: Exchange code.

        Returns:
            The last traded price, or None when it could not be read.
        """
        try:
            from services.quotes_service import get_quotes

            success, response, status = get_quotes(
                symbol=symbol, exchange=exchange, api_key=self.api_key
            )
        except Exception:
            logger.exception(
                "Agent order tools could not read a quote for %s on %s; the guard's pricing "
                "checks will be skipped",
                symbol,
                exchange,
            )
            return None

        if not success or not isinstance(response, Mapping):
            logger.warning(
                "Agent order tools got no usable quote for %s on %s (HTTP %s); the guard's "
                "pricing checks will be skipped",
                symbol,
                exchange,
                status,
            )
            return None

        data = response.get("data")
        source = data if isinstance(data, Mapping) else response
        for key in _LTP_KEYS:
            price = _decimal(source.get(key))
            if price is not None and price > 0:
                return price

        logger.warning(
            "Agent order tools found no last traded price in the quote for %s on %s",
            symbol,
            exchange,
        )
        return None

    def _available_funds(self) -> Decimal | None:
        """Fetch spendable cash for the guard's affordability check.

        Fails open for the same reason as :meth:`_last_traded_price`.

        Returns:
            Available cash, or None when it could not be read.
        """
        try:
            from services.funds_service import get_funds

            success, response, status = get_funds(api_key=self.api_key)
        except Exception:
            logger.exception(
                "Agent order tools could not read account funds; the guard's affordability "
                "check will be skipped"
            )
            return None

        if not success or not isinstance(response, Mapping):
            logger.warning(
                "Agent order tools got no usable funds payload (HTTP %s); the guard's "
                "affordability check will be skipped",
                status,
            )
            return None

        data = response.get("data")
        source = data if isinstance(data, Mapping) else response
        for key in _FUNDS_KEYS:
            cash = _decimal(source.get(key))
            if cash is not None:
                return cash

        logger.warning("Agent order tools found no cash figure in the funds payload")
        return None

    def _analyzer_mode(self) -> bool | None:
        """Read the platform analyzer toggle for the guard.

        Read fresh rather than taken from the run context, because the toggle
        decides whether an approved order reaches the sandbox or the broker and
        the operator may have moved it since this run started.

        Returns:
            True in analyzer mode, False in live mode, or None when it could not
            be read. None is handed to the guard deliberately: when the operator
            has required analyzer mode, an unreadable toggle must refuse the
            order rather than assume the safe answer.
        """
        try:
            from database.settings_db import get_analyze_mode

            return bool(get_analyze_mode())
        except Exception:
            logger.exception("Agent order tools could not read the platform analyzer toggle")
            return None

    def _open_position_quantity(self, symbol: str, exchange: str, product: str) -> int | None:
        """Read the signed quantity held in one symbol and product.

        Args:
            symbol: OpenAlgo symbol.
            exchange: Exchange code.
            product: CNC, NRML or MIS.

        Returns:
            The signed quantity, positive for long and negative for short, or
            None when it could not be read. None means "carry on and let the
            broker decide", because the operator asked for the position to be
            closed and a failed lookup is not a reason to leave it open.
        """
        try:
            from services.openposition_service import get_open_position

            success, response, _status = get_open_position(
                position_data={
                    "strategy": self.strategy,
                    "symbol": symbol,
                    "exchange": exchange,
                    "product": product,
                },
                api_key=self.api_key,
            )
        except Exception:
            logger.exception(
                "Agent order tools could not read the open position in %s on %s", symbol, exchange
            )
            return None

        if not success or not isinstance(response, Mapping):
            return None

        held = _decimal(response.get("quantity"))
        return int(held) if held is not None else None

    def _square_off(self, symbol: str, exchange: str, product: str) -> Any:
        """Close one position by sending an offsetting order at market.

        A smart order with a target position of zero is the platform's own
        square-off primitive: the broker reads the position it actually holds
        and sends the exact offsetting quantity, so this tool never has to guess
        a quantity or a side.

        Args:
            symbol: OpenAlgo symbol.
            exchange: Exchange code.
            product: The product the position is held under.

        Returns:
            The raw service result, or a synthetic success when the account
            holds nothing to close, so an empty position reads as "nothing to
            do" rather than as a failed order.
        """
        from services.place_smart_order_service import (
            place_smart_order as place_smart_order_service,
        )

        held = self._open_position_quantity(symbol, exchange, product)
        if held == 0:
            return (
                True,
                {
                    "status": "success",
                    "message": (
                        f"No open {product} position in {symbol} on {exchange}, so no order "
                        "was sent."
                    ),
                    "quantity": 0,
                    "closed": False,
                },
                200,
            )

        order = {
            "strategy": self.strategy,
            "symbol": symbol,
            "exchange": exchange,
            # Ignored by the broker whenever a position exists, because the side
            # is derived from the position being closed.
            "action": "SELL" if (held or 0) > 0 else "BUY",
            "quantity": 0,
            "position_size": 0,
            "product": product,
            "pricetype": PRICE_TYPE_MARKET,
            "price": 0.0,
            "trigger_price": 0.0,
            "disclosed_quantity": 0,
        }
        return place_smart_order_service(order_data=order, api_key=self.api_key)


def _verify_toolkit() -> None:
    """Refuse to load the module if a confirmation name is not a real method.

    ``requires_confirmation_tools`` is matched by name, and a name that matches
    nothing does not fail loudly on its own: agno warns, and the tool it was
    meant to protect runs with no human approval. This check turns that warning
    into an import error, so a rename that leaves the list behind cannot ship.

    Raises:
        RuntimeError: If any name in :data:`MUTATING_TOOLS` is not a callable
            attribute of :class:`OrdersToolkit`.
    """
    missing = [name for name in MUTATING_TOOLS if not callable(getattr(OrdersToolkit, name, None))]
    if missing:
        raise RuntimeError(
            "OrdersToolkit.MUTATING_TOOLS names "
            f"{', '.join(missing)}, which are not methods of the class. Every name in that "
            "list becomes a requires_confirmation_tools entry, and one that matches no tool "
            "silently removes the human approval gate instead of failing."
        )


_verify_toolkit()
