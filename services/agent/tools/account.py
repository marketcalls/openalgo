"""Account toolkit: funds, books, and single position or order lookups.

Seven read-only tools covering the question an operator asks most often, "what
do I have and what did I do". Every one of them calls the matching function in
``services/*`` directly. Nothing here makes an HTTP request back into this
process and nothing here uses the ``openalgo`` SDK.

What this toolkit deliberately does not do
------------------------------------------

* **It never mutates anything**, so no tool is named in
  ``requires_confirmation_tools`` and no risk guard runs. Reading a balance is
  not an act that needs approving, and pausing on one would train the operator
  to approve without reading.
* **It never takes a credential as an argument.** The API key comes from the
  :class:`~services.agent.tools.ToolContext` and is filled in by
  ``OpenAlgoToolkit.service_call``. There is no argument a model could set to
  name a different key, and no key ever appears in a tool schema, a tool result
  or an audit row.
* **It never reformats money.** Rupee figures are returned exactly as the
  service produced them, whether that is a float or a numeric string, because
  rounding a balance in a tool and then rounding it again in the answer is how a
  wrong number gets a confident presentation. The model decides how to show it.

Mode
----

Every figure reflects the platform's current mode. When analyzer mode is on,
the services below route to the sandbox and return sandbox values, which look
exactly like live ones. Each result therefore carries a ``mode`` field of
``live`` or ``analyze``, read at call time from the same
``database.settings_db.get_analyze_mode`` the services themselves consult, and
every docstring tells the model to say which it is reporting.

Empty is an answer
------------------

A book with no rows is the truth, not a failure. An operator holding nothing
must be told they hold nothing, so an empty book returns a normal result
carrying ``count: 0`` and a note saying so, and an order id absent from today's
book returns ``found: false``. Neither raises. The only things that raise are a
bad argument, which the model can fix, and a genuine upstream failure.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

from agno.exceptions import RetryAgentRun

from services.agent.prompts import ASSISTANT_NAME, wrap_tool_result
from services.agent.tools.base import OpenAlgoToolkit
from utils.constants import VALID_EXCHANGES, VALID_PRODUCT_TYPES
from utils.logging import get_logger

if TYPE_CHECKING:  # pragma: no cover - typing only
    from services.agent.tools import ToolContext

logger = get_logger(__name__)

#: Every money figure on this platform is rupees. Stated on each result so the
#: model never has to guess the unit or invent a conversion.
CURRENCY = "INR"

#: Hard ceiling on the rows one book tool will even attempt to serialise. The
#: character cap in ``to_json`` would discard the tail anyway; stopping here
#: keeps a thousand-row order book from being serialised repeatedly by the
#: fitting search below before most of it is thrown away.
MAX_BOOK_ROWS = 500

#: Written into the ``strategy`` field the openposition and orderstatus API logs
#: record, so a row raised by the agent is attributable in the API log rather
#: than appearing as an anonymous call.
STRATEGY_LABEL = ASSISTANT_NAME

_EXCHANGES = tuple(VALID_EXCHANGES)
_PRODUCTS = tuple(VALID_PRODUCT_TYPES)

_MODE_LIVE = "live"
_MODE_ANALYZE = "analyze"

_ANALYZE_NOTE = (
    "Analyzer mode is on, so these are sandbox figures and not the live broker account. "
    "Say so when you report them."
)

_UNEXPECTED_SHAPE_NOTE = (
    "The broker returned this book in a shape OpenAlgo does not recognise as a row list, so it "
    "is passed through unchanged. Read it as it is rather than assuming the book is empty."
)


def _is_truncation_envelope(text: str) -> bool:
    """Report whether ``to_json`` had to cut a payload instead of serialising it.

    ``OpenAlgoToolkit.to_json`` returns
    ``{"ok": true, "truncated": true, "dropped_chars": N, "partial": "..."}``
    when the full JSON would exceed the character cap. A book tool would rather
    drop whole rows than hand the model a payload that stops mid-value, so it
    needs to detect that envelope. No payload built in this module uses the key
    ``truncated``, which is what makes the test unambiguous.

    Args:
        text: The JSON string ``to_json`` returned.

    Returns:
        True when the string is the truncation envelope.
    """
    try:
        parsed = json.loads(text)
    except ValueError:
        return False
    return isinstance(parsed, dict) and parsed.get("truncated") is True and "partial" in parsed


def _split_book(
    payload: Any, rows_key: str | None = None
) -> tuple[list[Any], dict[str, Any], bool]:
    """Split a book service payload into its rows and whatever else it carried.

    Two shapes exist. ``positionbook`` and ``tradebook`` put the rows directly in
    ``data``; ``orderbook`` and ``holdings`` put them under a named key beside a
    ``statistics`` block.

    Args:
        payload: The service response, normally ``{"status": ..., "data": ...}``.
        rows_key: Key holding the rows when ``data`` is a mapping, such as
            ``orders`` or ``holdings``. None when ``data`` is the list itself.

    Returns:
        A ``(rows, extras, recognised)`` triple. ``extras`` carries the sibling
        fields, such as ``statistics``. ``recognised`` is False when the payload
        was neither shape, which is the one case where an empty row list must not
        be reported as an empty book.
    """
    data = payload.get("data") if isinstance(payload, Mapping) else payload

    if isinstance(data, list):
        return list(data), {}, True

    if isinstance(data, Mapping):
        if rows_key is not None and isinstance(data.get(rows_key), list):
            extras = {str(key): value for key, value in data.items() if key != rows_key}
            return list(data[rows_key]), extras, True
        return [], {str(key): value for key, value in data.items()}, False

    if data is None:
        return [], {}, True

    return [], {"data": data}, False


def looks_flat(quantity: Any) -> bool:
    """Report whether a position quantity means "no position".

    Brokers return the quantity as an integer, a float or a numeric string, so
    the comparison is made on a parsed copy. The value the tool returns is never
    the parsed one.

    Module level and public, because more than one toolkit has to decide whether
    a row in the position book is a position the operator actually holds, and a
    second copy of this would eventually disagree about the unparseable case.

    Args:
        quantity: The quantity exactly as the service returned it.

    Returns:
        True when it parses as zero. False when it is non-zero or unparseable,
        because claiming "no position" on a value nobody could read is the
        dangerous direction to be wrong in.
    """
    try:
        return float(str(quantity).strip()) == 0.0
    except (TypeError, ValueError):
        return False


def current_mode(fallback_analyzer: bool = False) -> str:
    """Report which account a figure just read came from.

    Read at call time from the same setting the services consult, so the label
    matches the routing that actually happened rather than the state the run
    started in.

    Module level for the same reason as :func:`looks_flat`: the instrument card
    reports the mode beside the operator's position exactly as this toolkit
    reports it beside a balance, and never presenting a sandbox number as real
    money is too important to hold two copies of.

    Args:
        fallback_analyzer: What the run believed the analyzer toggle was, used
            only when the setting cannot be read. A slightly stale label beats a
            missing one.

    Returns:
        ``analyze`` when the platform analyzer toggle is on, else ``live``.
    """
    try:
        from database.settings_db import get_analyze_mode

        return _MODE_ANALYZE if get_analyze_mode() else _MODE_LIVE
    except Exception:
        logger.exception("Could not read the analyzer mode for an agent tool result")
        return _MODE_ANALYZE if fallback_analyzer else _MODE_LIVE


class AccountToolkit(OpenAlgoToolkit):
    """Read-only account state: funds, positions, holdings, orders and trades."""

    def __init__(self, context: ToolContext) -> None:
        """Register the seven read-only account tools.

        No tool here mutates anything, so ``requires_confirmation_tools`` is
        deliberately empty. Adding a mutating tool to this toolkit would mean
        naming it there; the base class refuses a name that is not a registered
        tool, so a typo cannot quietly remove the gate.

        Args:
            context: The run's tool context, carrying the OpenAlgo API key every
                service call below is made with.
        """
        super().__init__(
            context,
            name="account",
            tools=[
                self.get_funds,
                self.get_positions,
                self.get_holdings,
                self.get_orderbook,
                self.get_tradebook,
                self.get_open_position,
                self.get_order_status,
            ],
        )

    # -- helpers -------------------------------------------------------------

    def _mode(self) -> str:
        """Report which account the figures in a result came from.

        Returns:
            ``analyze`` when the platform analyzer toggle is on, else ``live``.
            A lookup failure falls back to what the run context believed,
            because a missing label is worse than a slightly stale one.
        """
        return current_mode(self.analyzer_mode)

    def _envelope(self, **fields: Any) -> dict[str, Any]:
        """Build the common part of every result in this toolkit.

        Args:
            **fields: Result-specific fields, added after the common ones so a
                caller can override the currency on a result that carries none.

        Returns:
            A dictionary carrying ``ok``, ``mode``, ``currency`` and the fields.
        """
        payload: dict[str, Any] = {"ok": True, "mode": self._mode(), "currency": CURRENCY}
        payload.update(fields)
        if payload.get("currency") is None:
            payload.pop("currency")
        if payload["mode"] == _MODE_ANALYZE:
            payload["mode_note"] = _ANALYZE_NOTE
        return payload

    def _result(self, tool: str, payload: Mapping[str, Any], **labels: Any) -> str:
        """Serialise one result and label it as data before it re-enters context.

        Args:
            tool: The tool's registered name, written into the wrapper.
            payload: The result to serialise.
            **labels: Extra wrapper attributes, such as the symbol the result is
                about.

        Returns:
            A ``<tool_result>`` block holding the capped JSON.
        """
        return wrap_tool_result(tool, self.to_json(payload), **labels)

    def _book_result(
        self,
        tool: str,
        rows_key: str,
        rows: Sequence[Any],
        extras: Mapping[str, Any],
        recognised: bool,
        empty_note: str,
    ) -> str:
        """Serialise a book, dropping whole rows rather than characters if needed.

        The base class caps a result at 12000 characters and returns a
        truncation envelope when the full text will not fit. For a book that is
        the wrong trade: "here are 40 of your 300 orders" is readable, while JSON
        cut off inside the 41st is not. So the largest prefix of rows that still
        fits is found by measuring candidates, and the count of everything
        dropped is stated.

        Args:
            tool: The tool's registered name.
            rows_key: Key the rows are returned under, such as ``orders``.
            rows: The rows from the service, in the order it produced them.
            extras: Sibling fields such as the ``statistics`` block. Merged in
                without overwriting anything this method sets.
            recognised: False when the payload was not a shape with a row list,
                in which case an empty ``rows`` must not be read as an empty
                book.
            empty_note: What to tell the model when the book really is empty.

        Returns:
            A ``<tool_result>`` block holding the capped JSON.
        """
        total = len(rows)
        head = list(rows[:MAX_BOOK_ROWS])
        pre_dropped = total - len(head)

        def build(shown: list[Any], dropped: int) -> dict[str, Any]:
            payload = self._envelope(count=total, **{rows_key: shown})
            for key, value in extras.items():
                payload.setdefault(key, value)
            omitted = dropped + pre_dropped
            if omitted:
                payload["rows_omitted"] = omitted
                payload["note"] = (
                    f"Only the first {len(shown)} of {total} rows are shown; {omitted} were "
                    "dropped so the result would fit. Report the count honestly, and ask about a "
                    "specific symbol or order id if you need one of the rows that is missing."
                )
            elif not recognised:
                payload["note"] = _UNEXPECTED_SHAPE_NOTE
            elif not total:
                payload["note"] = empty_note
            return payload

        text = self.to_json(build(head, 0))
        if _is_truncation_envelope(text) and head:
            text = self.to_json(build([], len(head)))
            low, high = 0, len(head) - 1
            while low <= high:
                middle = (low + high) // 2
                candidate = self.to_json(build(head[:middle], len(head) - middle))
                if _is_truncation_envelope(candidate):
                    high = middle - 1
                else:
                    text = candidate
                    low = middle + 1

        return wrap_tool_result(tool, text)

    def _clean(self, field: str, value: Any, *, upper: bool = True) -> str:
        """Normalise a required text argument, or reject it with a fixable message.

        Args:
            field: The argument name exactly as the model sees it.
            value: The value the model supplied.
            upper: Whether to upper-case it. True for symbols, exchanges and
                products, which are upper case everywhere in OpenAlgo; False for
                an order id, which is the broker's own string.

        Returns:
            The stripped value.

        Raises:
            RetryAgentRun: When the value is empty or not text.
        """
        if not isinstance(value, str):
            self.invalid_argument(
                field,
                f"it must be text, not {type(value).__name__}.",
                "Pass it as a plain string.",
            )
        cleaned = value.strip()
        if not cleaned:
            self.invalid_argument(field, "it is empty.", "Supply a real value.")
        return cleaned.upper() if upper else cleaned

    # -- tools ---------------------------------------------------------------

    def get_funds(self) -> str:
        """Fetch the account's cash, collateral, used margin and P&L.

        Use this for any question about buying power, available balance, margin
        in use, or how much money is free.

        The result carries a ``funds`` object typically holding
        ``availablecash``, ``collateral``, ``m2munrealized`` (P&L on open
        positions), ``m2mrealized`` (P&L already booked) and ``utiliseddebits``
        (margin in use); a broker may add fields of its own. Every figure is in
        rupees and comes back exactly as the broker reported it, which may be a
        number or a numeric string. Present it as money without recalculating
        it.

        Figures reflect the platform's current mode. In analyzer mode these are
        sandbox balances rather than the live broker account, and the ``mode``
        field in the result says which. Never present a sandbox balance as the
        operator's real money.

        Returns:
            JSON carrying ``mode``, ``currency`` and the ``funds`` object.
        """
        from services.funds_service import get_funds

        payload = self.service_call(get_funds)
        data = payload.get("data") if isinstance(payload, Mapping) else payload
        funds = data if isinstance(data, Mapping) else {}

        result = self._envelope(funds=funds)
        if not funds:
            result["note"] = (
                "The broker returned no fund figures. That is an empty answer rather than an "
                "error; say the balance could not be read rather than reporting zero."
            )
        return self._result("get_funds", result)

    def get_positions(self) -> str:
        """Fetch every open intraday and carry position for the trading day.

        Use this for "what am I holding", "what is my P&L", "am I long or short
        in X", and before discussing any exit. Settled delivery stock is not
        here; that is ``get_holdings``, and a question about everything the
        operator owns needs both.

        The result carries ``count`` and a ``positions`` list whose rows
        typically hold ``symbol``, ``exchange``, ``product``, ``quantity``,
        ``average_price``, ``ltp`` and ``pnl``, money in rupees. A positive
        quantity is long, a negative one is short, and zero means the position
        was opened and closed again today. A ``count`` of zero means the
        operator is flat, which is a real answer and not a failure.

        Figures reflect the platform's current mode; in analyzer mode these are
        sandbox positions, and the ``mode`` field says so.

        Returns:
            JSON carrying ``mode``, ``count`` and the ``positions`` list.
        """
        from services.positionbook_service import get_positionbook

        payload = self.service_call(get_positionbook)
        rows, extras, recognised = _split_book(payload)
        return self._book_result(
            "get_positions",
            "positions",
            rows,
            extras,
            recognised,
            "There are no open positions. The position book is empty, so the operator is flat.",
        )

    def get_holdings(self) -> str:
        """Fetch the delivery portfolio: shares held beyond the trading day.

        Use this for "what is in my portfolio", long-term P&L, and any question
        about stock held in the demat account. Holdings are settled delivery
        stock, separate from the day's open positions, which are
        ``get_positions``. A question about everything the operator owns needs
        both.

        The result carries ``count``, a ``holdings`` list and a ``statistics``
        object holding ``totalholdingvalue``, ``totalinvvalue``,
        ``totalprofitandloss`` and ``totalpnlpercentage``. Each holding row
        typically holds ``symbol``, ``exchange``, ``product``, ``quantity``,
        ``pnl`` and ``pnlpercent``, money in rupees. A ``count`` of zero means
        the portfolio is empty, which is a real answer and not a failure.

        Figures reflect the platform's current mode; in analyzer mode these are
        sandbox holdings, and the ``mode`` field says so.

        Returns:
            JSON carrying ``mode``, ``count``, the ``holdings`` list and
            ``statistics``.
        """
        from services.holdings_service import get_holdings

        payload = self.service_call(get_holdings)
        rows, extras, recognised = _split_book(payload, "holdings")
        return self._book_result(
            "get_holdings",
            "holdings",
            rows,
            extras,
            recognised,
            "There are no holdings. The delivery portfolio is empty.",
        )

    def get_orderbook(self) -> str:
        """Fetch every order placed today, whatever state it ended in.

        Use this for "what orders did I place", "is my order filled", "what was
        rejected", and to find an order id before calling ``get_order_status``.
        It covers completed, open, cancelled and rejected orders alike, so an
        order missing from here was never accepted.

        The result carries ``count``, an ``orders`` list and a ``statistics``
        object counting buy, sell, completed, open and rejected orders. Each
        order row typically holds ``orderid``, ``symbol``, ``exchange``,
        ``action``, ``product``, ``quantity``, ``price``, ``trigger_price``,
        ``pricetype``, ``order_status`` and ``timestamp``, money in rupees. A
        ``count`` of zero means no orders were placed today, which is a real
        answer and not a failure. A long book comes back as its first rows plus
        a ``rows_omitted`` count; report the count honestly rather than implying
        you saw every row.

        Figures reflect the platform's current mode; in analyzer mode this is
        the sandbox order book, and the ``mode`` field says so.

        Returns:
            JSON carrying ``mode``, ``count``, the ``orders`` list and
            ``statistics``.
        """
        from services.orderbook_service import get_orderbook

        payload = self.service_call(get_orderbook)
        rows, extras, recognised = _split_book(payload, "orders")
        return self._book_result(
            "get_orderbook",
            "orders",
            rows,
            extras,
            recognised,
            "No orders were placed today. The order book is empty.",
        )

    def get_tradebook(self) -> str:
        """Fetch today's executed trades, the fills rather than the orders.

        Use this for "what actually got executed", average fill prices, and
        turnover. An order can exist without a trade, having been open,
        cancelled or rejected, and one order can produce several trades, so
        ``get_orderbook`` is the intent and this is what really happened.

        The result carries ``count`` and a ``trades`` list whose rows typically
        hold ``orderid``, ``symbol``, ``exchange``, ``action``, ``product``,
        ``quantity``, ``average_price``, ``trade_value`` and ``timestamp``,
        money in rupees. A ``count`` of zero means nothing was executed today,
        which is a real answer and not a failure. A long book comes back as its
        first rows plus a ``rows_omitted`` count.

        Figures reflect the platform's current mode; in analyzer mode these are
        simulated fills, and the ``mode`` field says so.

        Returns:
            JSON carrying ``mode``, ``count`` and the ``trades`` list.
        """
        from services.tradebook_service import get_tradebook

        payload = self.service_call(get_tradebook)
        rows, extras, recognised = _split_book(payload)
        return self._book_result(
            "get_tradebook",
            "trades",
            rows,
            extras,
            recognised,
            "No trades were executed today. The trade book is empty.",
        )

    def get_open_position(self, symbol: str, exchange: str, product: str) -> str:
        """Fetch the net quantity held in one exact contract.

        Use this when the question is about a single instrument, rather than
        pulling the whole position book and searching it. The match is exact on
        all three arguments together: the same symbol held as ``MIS`` and as
        ``NRML`` is two separate positions, and asking for the wrong product
        reports zero.

        The result carries the ``quantity`` for that contract. Positive is long,
        negative is short, and zero means there is no open position in it, which
        is a real answer and not a failure. Figures reflect the platform's
        current mode; in analyzer mode this is the sandbox position, and the
        ``mode`` field says so.

        Args:
            symbol: OpenAlgo symbol, exactly as the instrument is listed. Equity
                is the base symbol (``RELIANCE``, ``SBIN``). A future is
                ``[base][expiry]FUT`` (``BANKNIFTY24APR24FUT``). An option is
                ``[base][expiry][strike][CE or PE]`` (``NIFTY28MAR2420800CE``,
                ``VEDL25APR24292.5CE``). Resolve the exact symbol with the symbol
                search tool if you are not certain of it; a symbol that does not
                match reports zero rather than an error.
            exchange: Exchange code. One of NSE, BSE (equity), NFO, BFO (F&O),
                CDS, BCD (currency), MCX, NCDEX, NCO (commodity), NSE_INDEX,
                BSE_INDEX, MCX_INDEX, GLOBAL_INDEX (quote-only indices) or
                CRYPTO.
            product: Product type. CNC for delivery equity, NRML for carry
                futures and options, MIS for intraday.

        Returns:
            JSON carrying ``mode``, ``symbol``, ``exchange``, ``product`` and
            ``quantity``.
        """
        from services.openposition_service import get_open_position

        symbol = self._clean("symbol", symbol)
        exchange = self._clean("exchange", exchange)
        product = self._clean("product", product)

        if exchange not in _EXCHANGES:
            self.invalid_argument(
                "exchange",
                f"{exchange!r} is not an OpenAlgo exchange code.",
                f"Use one of: {', '.join(_EXCHANGES)}.",
            )
        if product not in _PRODUCTS:
            self.invalid_argument(
                "product",
                f"{product!r} is not an OpenAlgo product type.",
                f"Use one of: {', '.join(_PRODUCTS)}. CNC is delivery equity, NRML is carry "
                "futures and options, MIS is intraday.",
            )

        # The service mutates the dict it is given, so it gets its own.
        position_data = {
            "symbol": symbol,
            "exchange": exchange,
            "product": product,
            "strategy": STRATEGY_LABEL,
        }
        payload = self.service_call(get_open_position, position_data)

        quantity = payload.get("quantity") if isinstance(payload, Mapping) else payload
        result = self._envelope(
            currency=None,
            symbol=symbol,
            exchange=exchange,
            product=product,
            quantity=quantity,
        )
        if looks_flat(quantity):
            result["note"] = (
                f"There is no open {product} position in {symbol} on {exchange}. Zero is a real "
                "answer, not a failure; the operator is flat in this contract."
            )
        return self._result("get_open_position", result, symbol=symbol, exchange=exchange)

    def get_order_status(self, order_id: str) -> str:
        """Fetch the current state of one order placed today.

        Use this to answer "did my order go through", to check a fill price, or
        to find out why an order did not execute. The order is looked up in
        today's order book, so an id from an earlier session is not found. Use
        ``get_orderbook`` when you do not have the id.

        The result carries ``found`` and, when the order exists, an ``order``
        object holding ``orderid``, ``symbol``, ``exchange``, ``action``,
        ``product``, ``quantity``, ``price``, ``trigger_price``, ``pricetype``,
        ``order_status``, ``average_price`` (the real fill price, filled in for
        a completed order) and ``timestamp``, money in rupees. ``order_status``
        is one of complete, open, pending, cancelled or rejected. A ``found`` of
        false means no order with that id is in today's book, which is an answer
        rather than an error. Figures reflect the platform's current mode; in
        analyzer mode this is the sandbox order, and the ``mode`` field says so.

        Args:
            order_id: The broker's order id, exactly as it appeared in the order
                book or in the confirmation of a placed order, for example
                ``250408000989443``. It is an opaque string; pass it unchanged
                rather than reformatting or trimming it.

        Returns:
            JSON carrying ``mode``, ``order_id``, ``found`` and the ``order``
            object when one was found.
        """
        from services.orderstatus_service import get_order_status

        order_id = self._clean("order_id", order_id, upper=False)
        label = "orderstatus_service.get_order_status"

        # Called directly rather than through service_call because an id that is
        # not in today's book comes back as a 404, and that is a legitimate
        # answer here: raising on it would have the model report a failure when
        # the truth is simply that no such order exists.
        try:
            outcome = get_order_status(
                {"orderid": order_id, "strategy": STRATEGY_LABEL}, api_key=self.api_key
            )
        except Exception as exc:
            logger.exception("Agent tool get_order_status: %s raised", label)
            raise RetryAgentRun(
                f"{label} raised {type(exc).__name__}: {exc}. "
                "Check the order id you passed; if it is correct, this is a platform failure and "
                "you should report it to the user rather than calling the tool again."
            ) from exc

        if (
            isinstance(outcome, tuple)
            and len(outcome) == 3
            and outcome[0] is False
            and outcome[2] == 404
        ):
            return self._result(
                "get_order_status",
                self._envelope(
                    order_id=order_id,
                    found=False,
                    note=(
                        f"No order with id {order_id} is in today's order book. That is an "
                        "answer, not a failure: the id may belong to an earlier session, or the "
                        "order was never accepted. Call get_orderbook to see today's orders."
                    ),
                ),
                order_id=order_id,
            )

        payload = self.unwrap_service_result(outcome, label=label)
        data = payload.get("data") if isinstance(payload, Mapping) else payload
        order = data if isinstance(data, Mapping) else {}

        return self._result(
            "get_order_status",
            self._envelope(order_id=order_id, found=bool(order), order=order),
            order_id=order_id,
        )
