"""
Event-bus subscriber that maintains the per-strategy position book.

Two topics carry everything needed, so the order execution path itself is
never modified:

* ``order.placed`` is the only moment the strategy tag is known - it is
  supplied by the caller and never round-trips through the broker. The
  orderid -> strategy mapping is recorded here.
* ``order.update`` reports fills. The mapping is looked up and the unseen
  portion of the fill is booked against that strategy's position.

Both live and analyze (sandbox) orders publish these events, so the book
covers either mode, and orders placed through ``/api/v1`` are tracked exactly
like Flow-placed ones as long as they carry a ``strategy``.
"""

from database.strategy_book_db import apply_fill, record_order_tag
from utils.logging import get_logger

logger = get_logger(__name__)

# Statuses that can carry filled quantity worth booking. "open" and
# "trigger pending" are skipped - nothing has traded yet.
_FILLABLE = {"complete", "filled", "partially filled", "partial"}


def _user_id(event) -> str:
    data = getattr(event, "request_data", None) or {}
    return str(data.get("user_id") or "")


def on_order_placed(event) -> None:
    """Record which strategy an order belongs to."""
    strategy = (getattr(event, "strategy", "") or "").strip()
    orderid = getattr(event, "orderid", "") or ""
    if not orderid or not strategy:
        return
    record_order_tag(
        orderid=orderid,
        user_id=_user_id(event),
        strategy=strategy,
        symbol=getattr(event, "symbol", "") or "",
        exchange=getattr(event, "exchange", "") or "",
        product=getattr(event, "product", "") or "",
    )


def on_order_update(event) -> None:
    """Book a fill against its strategy's position."""
    status = str(getattr(event, "order_status", "") or "").strip().lower().replace("_", " ")
    if status not in _FILLABLE:
        return

    filled = getattr(event, "filled_quantity", 0) or 0
    if not filled:
        # Some adapters report a completed order without restating quantity.
        filled = getattr(event, "quantity", 0) or 0
    if not filled:
        return

    price = getattr(event, "average_price", 0) or getattr(event, "price", 0) or 0
    result = apply_fill(
        orderid=getattr(event, "orderid", "") or "",
        filled_quantity=filled,
        average_price=price,
        action=getattr(event, "action", "") or "",
    )
    if result:
        logger.info(
            f"Strategy book: {result['strategy']} {result['symbol']} "
            f"qty={result['quantity']} avg={result['average_price']} "
            f"realizedToday={result['today_realized_pnl']}"
        )


def register(bus) -> None:
    """Attach both handlers. Called once during app startup."""
    bus.subscribe("order.placed", on_order_placed, name="StrategyBookTagger")
    bus.subscribe("order.update", on_order_update, name="StrategyBookFills")
    logger.info("Strategy book subscriber registered")
