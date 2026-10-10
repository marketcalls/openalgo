"""A smart order must never size itself against a position it could not read.

A smart order asks the broker for the open position, compares it with the
target the caller sent, and places the difference. Most broker plugins used to
turn a position read that failed (a network error, an HTTP error, an error
envelope in the body, a body that would not parse) into a net quantity of 0,
because 0 is also what an empty book reads as. The smart order then sized
against a flat position the account did not have: an exit read as "nothing to
close", and an entry or a flip placed the full quantity on top of the position
that was really there, doubling or reversing it.

This module is the one place that tells the two apart:

- ``read_position_book`` runs a broker's position-book fetch and raises
  ``PositionReadError`` unless the broker's own success check passes, or the
  broker is one that answers an empty book with an error envelope and the
  message field of this response says the book is empty.
- ``refuse_smart_order_on_read_failure`` wraps a broker's
  ``place_smartorder_api`` so that the error becomes a refusal: no order, and a
  sentence a trader can act on.

A successful read is returned exactly as the broker sent it, so everything the
plugin does with it afterwards is unchanged. A read the broker pacer refused
under the gthread worker (``BrokerBusyError``) passes through as it is, so it
keeps its busy answer and its own sentence. Nothing here blocks, sleeps or
takes a lock, so it behaves the same under eventlet, gthread and the
development server.
"""

import functools
import json
from collections.abc import Callable
from typing import Any

from utils.broker_backpressure import BrokerBusyError
from utils.logging import get_logger

logger = get_logger(__name__)

# The names traders see for each plugin, matching the broker picker on the
# login page (frontend/src/pages/BrokerSelect.tsx).
BROKER_DISPLAY_NAMES = {
    "aliceblue": "Alice Blue",
    "angel": "Angel One",
    "arrow": "Arrow",
    "compositedge": "CompositEdge",
    "definedge": "Definedge",
    "deltaexchange": "Delta Exchange",
    "dhan": "Dhan",
    "dhan_sandbox": "Dhan (Sandbox)",
    "firstock": "Firstock",
    "fivepaisa": "5 Paisa",
    "fivepaisaxts": "5 Paisa (XTS)",
    "flattrade": "Flattrade",
    "fyers": "Fyers",
    "groww": "Groww",
    "hdfcsecurities": "HDFC Securities",
    "hdfcsky": "HDFC Sky",
    "ibulls": "Ibulls",
    "iifl": "IIFL",
    "iiflcapital": "IIFL Capital",
    "indmoney": "IndMoney",
    "jainamxts": "JainamXts",
    "kotak": "Kotak Securities",
    "motilal": "Motilal Oswal",
    "mstock": "mStock by Mirae Asset",
    "nubra": "Nubra",
    "paytm": "Paytm Money",
    "pocketful": "Pocketful",
    "rmoney": "RMoney",
    "samco": "Samco",
    "shoonya": "Shoonya",
    "tradejini": "Tradejini",
    "tradesmart": "TradeSmart",
    "upstox": "Upstox",
    "wisdom": "Wisdom Capital",
    "zebu": "Zebu",
    "zerodha": "Zerodha",
}

# Phrases brokers use in the message of an answer that means "no positions".
_EMPTY_BOOK_MARKERS = (
    "no data",
    "nodata",
    "no_data",
    "no-data",
    "no position",
    "no open position",
    "no record",
    "have any position",
    "have any open position",
    "data not found",
    "record not found",
    "positions not found",
)

# A one-line "no data" message is short. Anything longer is not treated as one,
# so a large error page that happens to contain the words cannot pass.
_EMPTY_BOOK_MAX_CHARS = 2000

# The fields that carry a broker's message, as dotted paths into the response.
# Only these are read for an empty-book phrase; the rest of the body never is,
# so an error whose other fields happen to contain "no data" cannot pass.
MESSAGE_FIELDS = (
    "emsg",
    "message",
    "msg",
    "errorMessage",
    "statusMessage",
    "errMsg",
    "description",
    "s",
    "error",
    "error.message",
    "error.msg",
)

# The brokers whose empty position book can come back as their error envelope
# with a message, rather than as a success with an empty list, and the fields
# that carry that message. A broker listed here keeps its empty book flat, as
# before. A broker not listed has an empty book that its own success check
# already accepts (a bare [] for Dhan, a success envelope for Zerodha, Upstox,
# Angel, Fyers and the XTS family), so for it an error envelope is always a
# failed read, whatever its message says. Dhan's DH-907 ("unable to fetch data
# due to incorrect parameters or no data present") is one of those: its empty
# position book is [], and a flat account's Positions page could not render
# the error envelope if it were not.
#
# The Noren family (Flattrade, Shoonya, Zebu, TradeSmart) answers an empty book
# with {"stat": "Not_Ok", "emsg": "no data"}. The others are listed because
# nothing yet shows which shape their empty book takes, and refusing every
# entry from a flat account on a guess would be the wrong trade. Remove one
# only once its empty book has been seen on a real account.
EMPTY_BOOK_MESSAGE_FIELDS: dict[str, tuple[str, ...]] = {
    "flattrade": ("emsg",),
    "shoonya": ("emsg",),
    "zebu": ("emsg",),
    "tradesmart": ("emsg",),
    "arrow": ("message",),
    "definedge": ("message", "emsg"),
    "firstock": ("error.message", "message"),
    "fivepaisa": ("head.statusDescription", "body.Message"),
    "hdfcsecurities": ("message", "error"),
    "hdfcsky": ("message", "error"),
    "iiflcapital": ("message",),
    "kotak": ("emsg", "errMsg", "message"),
    "motilal": ("message",),
    "mstock": ("message",),
    "nubra": ("message", "error"),
    "paytm": ("message",),
    "samco": ("statusMessage",),
}

_PREVIEW_CHARS = 300


class PositionReadError(Exception):
    """The broker's position book could not be read, so the position is unknown.

    ``str()`` of the error is the sentence shown to the trader. ``detail`` keeps
    the technical reason for the log.
    """

    def __init__(self, broker: str, detail: str = ""):
        self.broker = broker
        self.detail = detail
        super().__init__(position_read_failed_message(broker))


def broker_display_name(broker: str) -> str:
    """Return the name a trader knows the broker by."""
    return BROKER_DISPLAY_NAMES.get(broker, broker)


def position_read_failed_message(broker: str) -> str:
    """Return the sentence a trader reads when a smart order is refused."""
    return (
        f"OpenAlgo could not read your open position from {broker_display_name(broker)}, "
        "so no order was sent. Check your positions and try again."
    )


def _as_text(response: Any) -> str:
    if isinstance(response, str):
        return response
    try:
        return json.dumps(response, default=str)
    except (TypeError, ValueError):
        return str(response)


def _preview(response: Any) -> str:
    text = _as_text(response)
    return text if len(text) <= _PREVIEW_CHARS else f"{text[:_PREVIEW_CHARS]}..."


def _field(response: Any, path: str) -> Any:
    value = response
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def says_no_positions(response: Any, fields: tuple[str, ...] = MESSAGE_FIELDS) -> bool:
    """True when the message of a response that is not a success means "no positions".

    Args:
        response: The position-book response, in whatever shape the broker
            plugin returns it.
        fields: The dotted paths of the fields that carry the broker's
            message. Only these are read, never the rest of the body.

    Returns:
        bool: True when one of those fields is a short string carrying one of
        the phrases brokers use for an empty book.
    """
    if not isinstance(response, dict):
        return False
    for path in fields:
        value = _field(response, path)
        if not isinstance(value, str) or len(value) > _EMPTY_BOOK_MAX_CHARS:
            continue
        text = value.lower()
        if any(marker in text for marker in _EMPTY_BOOK_MARKERS):
            return True
    return False


def _empty_book_check(broker: str) -> Callable[[Any], bool] | None:
    fields = EMPTY_BOOK_MESSAGE_FIELDS.get(broker)
    if fields is None:
        return None
    return lambda response: says_no_positions(response, fields)


def read_position_book(
    broker: str,
    fetch: Callable[[], Any],
    is_ok: Callable[[Any], bool],
    is_empty: Callable[[Any], bool] | None = None,
) -> Any:
    """Fetch a broker's position book for a smart order, or raise.

    Args:
        broker: The plugin name, for example ``"zerodha"``.
        fetch: Takes no arguments and returns the position book as the plugin
            reads it. Anything it raises is a failed read.
        is_ok: The broker's own test for a successful response.
        is_empty: The broker's test for an error envelope that means the book
            is empty. Defaults to the message check registered for the broker
            in ``EMPTY_BOOK_MESSAGE_FIELDS``. A broker with none has no such
            answer, so a response its ``is_ok`` rejects is always a failure.

    Returns:
        The response from ``fetch``, unchanged, when it is a successful read or
        the broker's way of saying the book is empty.

    Raises:
        PositionReadError: When the read failed, so the position is unknown.
    """
    name = broker_display_name(broker)
    try:
        response = fetch()
    except (PositionReadError, BrokerBusyError):
        # A read the broker pacer refused under the gthread worker was never
        # sent. It keeps its own sentence and its busy answer, which the
        # plugin or the smart order service turns into a refusal; folding it
        # into a failed read would lose both. Never raised under eventlet.
        raise
    except Exception as exc:
        logger.exception(f"{name} position book could not be read for a smart order")
        raise PositionReadError(broker, f"{type(exc).__name__}: {exc}") from exc

    try:
        ok = bool(is_ok(response))
    except Exception:
        logger.exception(f"{name} position book response could not be checked")
        ok = False

    if ok:
        return response

    if is_empty is None:
        is_empty = _empty_book_check(broker)
    if is_empty is not None:
        try:
            empty = bool(is_empty(response))
        except Exception:
            logger.exception(f"{name} position book response could not be checked")
            empty = False
        if empty:
            logger.debug(f"{name} reported an empty position book: {_preview(response)}")
            return response

    detail = _preview(response)
    logger.error(f"{name} position book read failed, smart order refused. Response: {detail}")
    raise PositionReadError(broker, detail)


def refuse_smart_order_on_read_failure(func: Callable) -> Callable:
    """Turn a PositionReadError inside a broker's place_smartorder_api into a refusal.

    The wrapped function keeps its ``(response, response_data, order_id)``
    return shape. A refusal is ``(None, {"status": "error", "message": ...},
    None)``, which the smart order service and the close-position route both
    already report as a failed order carrying that message.
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except PositionReadError as exc:
            logger.warning(f"Smart order not sent: {exc} Reason: {exc.detail}")
            return None, {"status": "error", "message": str(exc)}, None

    return wrapper
