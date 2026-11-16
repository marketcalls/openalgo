"""What an order alert says, before any channel decides how it looks.

``build_message`` turns an order event's request and response into a title, a
mode banner and a list of plain ``Label: value`` lines. Each channel then
renders that one structure in its own markup: WhatsApp and Slack bold with
``*``, Discord with ``**``, and the webhook channels escape the values first.
Writing the field selection once is the point: a new order type, or a new
field on an existing one, reaches every channel that uses this module.

This is the formatter WhatsApp alerts used, moved here unchanged except for
GTT orders, which it used to describe as a bare "Order Update" with no
fields. WhatsApp's other messages are pinned byte for byte by
``test/test_alerts_formatting.py``.
Telegram keeps its own formatter for now: it marks symbols as code and draws a
different separator, and converging the two would change messages Telegram
users already receive.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from utils.logging import get_logger

logger = get_logger(__name__)

#: The title for each order type. An order type missing here gets
#: ``DEFAULT_TITLE``.
TITLES: dict[str, str] = {
    "placeorder": "Order Placed",
    "placesmartorder": "Smart Order Placed",
    "basketorder": "Basket Order Executed",
    "splitorder": "Split Order Executed",
    "optionsorder": "Options Order Executed",
    "optionsmultiorder": "Options Multi-Order Executed",
    "modifyorder": "Order Modified",
    "cancelorder": "Order Cancelled",
    "cancelallorder": "All Orders Cancelled",
    "closeposition": "Position Closed",
    "placegttorder": "GTT Order Placed",
    "modifygttorder": "GTT Order Modified",
    "cancelgttorder": "GTT Order Cancelled",
    "gtttriggered": "GTT Triggered",
    "gttexpired": "GTT Expired",
}

#: The GTT operations, whose fields come from ``_gtt_lines``.
GTT_TYPES = frozenset(
    {"placegttorder", "modifygttorder", "cancelgttorder", "gtttriggered", "gttexpired"}
)
DEFAULT_TITLE = "Order Update"

LIVE_BANNER = "LIVE MODE - Real Order"
ANALYZE_BANNER = "ANALYZE MODE - No Real Order"

#: Drawn under the banner. Plain hyphens so it reads the same on every
#: channel and in every font.
SEPARATOR = "---------------------"

#: How many legs or child orders a batch alert lists before summarising the
#: rest. A basket of forty orders is one message, not a scroll.
BASKET_LISTED = 3
OPTIONS_LISTED = 5


@dataclass(frozen=True)
class AlertMessage:
    """One alert, channel-neutral.

    Attributes:
        title: The headline, such as "Order Placed".
        lines: The body, one ``Label: value`` line each, ending with the time.
        banner: Live or analyze mode. None for the short message sent when the
            event could not be read.
        strategy: The strategy that sent the order, shown above the banner.
    """

    title: str
    lines: tuple[str, ...]
    banner: str | None = None
    strategy: str | None = None


def build_message(
    api_type: str,
    request: dict[str, Any],
    response: dict[str, Any],
    now: datetime | None = None,
) -> AlertMessage:
    """Describe one order event as an alert.

    Never raises: an event that cannot be read becomes a short message naming
    the order type and status, so a malformed response costs the detail and
    never the alert.

    Args:
        api_type: The order operation, such as "placeorder".
        request: The order as it was sent.
        response: What the broker or the sandbox answered.
        now: When the alert is raised. Defaults to the server's local time.

    Returns:
        The alert, ready for a channel to render.
    """
    title = TITLES.get(api_type, DEFAULT_TITLE)
    try:
        return AlertMessage(
            title=title,
            lines=tuple(_detail_lines(api_type, request, response))
            + (f"Time: {(now or datetime.now()).strftime('%H:%M:%S')}",),
            banner=ANALYZE_BANNER if response.get("mode", "live") == "analyze" else LIVE_BANNER,
            strategy=request.get("strategy") or None,
        )
    except Exception:
        logger.exception("Could not read an order event for its alert")
        return AlertMessage(
            title=title,
            lines=(f"Order Type: {api_type}", f"Status: {response.get('status', 'unknown')}"),
        )


def _detail_lines(api_type: str, request: dict[str, Any], response: dict[str, Any]) -> list[str]:
    """The lines between the banner and the time, for one order type."""
    succeeded = response.get("status") == "success"

    if api_type == "placeorder":
        lines = [
            f"Symbol: {request.get('symbol', 'N/A')}",
            f"Action: {request.get('action', 'N/A')}",
            f"Quantity: {request.get('quantity', 'N/A')}",
            f"Price Type: {request.get('pricetype', 'N/A')}",
            f"Exchange: {request.get('exchange', 'N/A')}",
            f"Product: {request.get('product', 'N/A')}",
        ]
        if succeeded:
            lines.append(f"Order ID: {response.get('orderid', 'N/A')}")
        else:
            lines.append(f"Error: {response.get('message', 'Failed')}")
        return lines

    if api_type == "placesmartorder":
        lines = [
            f"Symbol: {request.get('symbol', 'N/A')}",
            f"Action: {request.get('action', 'N/A')}",
            f"Quantity: {request.get('quantity', 'N/A')}",
            f"Position Size: {request.get('position_size', 'N/A')}",
            f"Exchange: {request.get('exchange', 'N/A')}",
        ]
        if succeeded:
            lines.append(f"Order ID: {response.get('orderid', 'N/A')}")
        return lines

    if api_type == "basketorder":
        if not succeeded:
            return []
        results = response.get("results", [])
        lines = _tally("Total Orders", results)
        for result in results[:BASKET_LISTED]:
            lines.append(
                f"[{_mark(result)}] {result.get('symbol', 'N/A')}: "
                f"{result.get('orderid', result.get('message', 'N/A'))}"
            )
        if len(results) > BASKET_LISTED:
            lines.append(f"... and {len(results) - BASKET_LISTED} more")
        return lines

    if api_type == "splitorder":
        results = response.get("results", [])
        success_count = _successes(results)
        failed_count = len(results) - success_count
        lines = [
            f"Symbol: {request.get('symbol', 'N/A')}",
            f"Total Quantity: {response.get('total_quantity', 'N/A')}",
            f"Split Size: {response.get('split_size', 'N/A')}",
            *_tally("Total Orders", results),
        ]
        if failed_count > 0 and success_count == 0:
            lines.append("All orders rejected")
        elif failed_count > 0:
            lines.append("Partial fill")
            first_fail = next((r for r in results if r.get("status") != "success"), None)
            if first_fail and first_fail.get("message"):
                lines.append(f"Reason: {first_fail['message']}")
        return lines

    if api_type == "modifyorder":
        return [
            f"Order ID: {request.get('orderid', 'N/A')}",
            f"Symbol: {request.get('symbol', 'N/A')}",
            f"New Quantity: {request.get('quantity', 'N/A')}",
            f"New Price: {request.get('price', 'N/A')}",
            _outcome(response, "Modification Successful"),
        ]

    if api_type == "cancelorder":
        return [
            f"Order ID: {request.get('orderid', 'N/A')}",
            _outcome(response, "Cancellation Successful"),
        ]

    if api_type == "cancelallorder":
        if not succeeded:
            return []
        cancelled = response.get("canceled_orders", [])
        failed = response.get("failed_cancellations", [])
        lines = [f"Cancelled: {len(cancelled)} orders", f"Failed: {len(failed)} orders"]
        if cancelled and len(cancelled) <= 5:
            lines.append(f"Order IDs: {', '.join(cancelled[:5])}")
        return lines

    if api_type == "closeposition":
        return _close_position_lines(request, response)

    if api_type in ("optionsorder", "optionsmultiorder"):
        return _options_lines(request, response)

    if api_type in GTT_TYPES:
        return _gtt_lines(api_type, request, response)

    return []


def _gtt_lines(api_type: str, request: dict[str, Any], response: dict[str, Any]) -> list[str]:
    """A GTT placed, modified or cancelled by the trader, or fired or lapsed on its own."""
    if api_type == "cancelgttorder":
        return [
            f"Trigger ID: {request.get('trigger_id', 'N/A')}",
            _outcome(response, "Cancellation Successful"),
        ]

    if api_type in ("gtttriggered", "gttexpired"):
        lines = [
            f"Symbol: {request.get('symbol', 'N/A')}",
            f"Exchange: {request.get('exchange', 'N/A')}",
            f"Trigger ID: {request.get('trigger_id', 'N/A')}",
        ]
        if api_type == "gtttriggered":
            prices = ", ".join(str(price) for price in request.get("trigger_prices") or [])
            lines.append(f"Trigger Prices: {prices or 'N/A'}")
            lines.append(f"Order ID: {response.get('orderid') or 'N/A'}")
        elif response.get("message"):
            lines.append(str(response["message"]))
        return lines

    # placegttorder and modifygttorder: the order the GTT will send.
    lines = []
    if api_type == "modifygttorder":
        lines.append(f"Trigger ID: {request.get('trigger_id', 'N/A')}")
    lines.extend(
        [
            f"Symbol: {request.get('symbol', 'N/A')}",
            f"Action: {request.get('action', 'N/A')}",
            f"Quantity: {request.get('quantity', 'N/A')}",
            f"Exchange: {request.get('exchange', 'N/A')}",
            f"Trigger Type: {request.get('trigger_type', 'N/A')}",
        ]
    )
    # A SINGLE GTT sets one of the two; an OCO sets both.
    if request.get("triggerprice_sl"):
        lines.append(f"Stop Loss Trigger: {request['triggerprice_sl']}")
    if request.get("triggerprice_tg"):
        lines.append(f"Target Trigger: {request['triggerprice_tg']}")
    if api_type == "modifygttorder":
        lines.append(_outcome(response, "Modification Successful"))
    elif response.get("status") == "success":
        lines.append(f"Trigger ID: {response.get('trigger_id', 'N/A')}")
    else:
        lines.append(f"Error: {response.get('message', 'Failed')}")
    return lines


def _close_position_lines(request: dict[str, Any], response: dict[str, Any]) -> list[str]:
    """One position closed, or a count of every position closed."""
    if response.get("status") != "success":
        return [f"Error: {response.get('message', 'Failed')}"]
    if request.get("symbol"):
        return [
            f"Symbol: {request.get('symbol', 'N/A')}",
            f"Exchange: {request.get('exchange', 'N/A')}",
            f"Product: {request.get('product', 'N/A')}",
            f"Order ID: {response.get('orderid', 'N/A')}",
        ]
    closed = response.get("closed_positions", 0)
    failed = response.get("failed_closures", 0)
    if closed or failed:
        return [f"Closed: {closed} positions", f"Failed: {failed} positions"]
    return ["All positions closed successfully"]


def _options_lines(request: dict[str, Any], response: dict[str, Any]) -> list[str]:
    """The underlying, each leg's outcome, and the underlying's price."""
    lines = [f"Underlying: {request.get('underlying', 'N/A')}"]
    if response.get("status") != "success":
        lines.append(f"Error: {response.get('message', 'Failed')}")
        return lines
    results = response.get("results", [])
    if results:
        lines.extend(_tally("Total Legs", results))
        for result in results[:OPTIONS_LISTED]:
            symbol = result.get("symbol", "N/A")
            action = result.get("action", "")
            order_id = result.get("orderid", result.get("message", "N/A"))
            lines.append(f"[{_mark(result)}] {symbol} {action} -> {order_id}")
    if response.get("underlying_ltp"):
        lines.append(f"Underlying LTP: {response.get('underlying_ltp')}")
    return lines


def _successes(results: list[dict[str, Any]]) -> int:
    return sum(1 for result in results if result.get("status") == "success")


def _tally(total_label: str, results: list[dict[str, Any]]) -> list[str]:
    """How many child orders there were, and how many went through."""
    success_count = _successes(results)
    return [
        f"{total_label}: {len(results)}",
        f"Successful: {success_count}",
        f"Failed: {len(results) - success_count}",
    ]


def _mark(result: dict[str, Any]) -> str:
    return "OK" if result.get("status") == "success" else "X"


def _outcome(response: dict[str, Any], success_text: str) -> str:
    if response.get("status") == "success":
        return success_text
    return f"Error: {response.get('message', 'Failed')}"
