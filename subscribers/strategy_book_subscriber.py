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
    return _request_field(event, "user_id")


def _request_field(event, key: str) -> str:
    data = getattr(event, "request_data", None) or {}
    return str(data.get(key) or "") if isinstance(data, dict) else ""


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


def on_batch_completed(event) -> None:
    """Tag the child orders of a batch node.

    optionsMultiOrder, basketOrder, splitOrder and optionsOrder place their
    legs with emit_event=False, so no per-leg order.placed is published and
    the legs would otherwise never be tagged. Each batch instead publishes one
    completion event carrying the strategy and a results list of child orders.
    """
    strategy = (getattr(event, "strategy", "") or "").strip()
    results = getattr(event, "results", None) or []
    if not strategy or not isinstance(results, list):
        return

    user_id = _user_id(event)
    # A split or options batch is one contract, so the event carries the leg
    # identity. A basket spans several, so each result supplies its own and the
    # event has none - hence per-leg values win and the event is the fallback.
    default_symbol = getattr(event, "symbol", "") or ""
    default_exchange = getattr(event, "exchange", "") or ""
    default_product = getattr(event, "product", "") or _request_field(event, "product")
    for leg in results:
        if not isinstance(leg, dict):
            continue

        # A leg placed with splitsize reports its children under split_results
        # and carries no orderid of its own, so the children were never tagged
        # and their fills went unattributed. They inherit the leg's identity.
        children = leg.get("split_results")
        if isinstance(children, list) and children:
            for child in children:
                if not isinstance(child, dict):
                    continue
                child_orderid = child.get("orderid") or child.get("order_id") or ""
                if not child_orderid:
                    continue
                record_order_tag(
                    orderid=str(child_orderid),
                    user_id=user_id,
                    strategy=strategy,
                    symbol=leg.get("symbol") or default_symbol,
                    exchange=leg.get("exchange") or default_exchange,
                    product=leg.get("product") or default_product,
                )
            continue

        orderid = leg.get("orderid") or leg.get("order_id") or ""
        if not orderid:
            continue  # a rejected leg has no id
        symbol = leg.get("symbol") or default_symbol
        exchange = leg.get("exchange") or default_exchange
        product = leg.get("product") or default_product
        if not (symbol and exchange and product):
            # Without all three the leg cannot be matched against the broker
            # position book, so its unrealized P&L would silently read zero.
            logger.warning(
                f"Strategy book: skipping batch leg {orderid} for {strategy} - "
                f"incomplete identity (symbol={symbol!r} exchange={exchange!r} "
                f"product={product!r})"
            )
            continue
        record_order_tag(
            orderid=str(orderid),
            user_id=user_id,
            strategy=strategy,
            symbol=symbol,
            exchange=exchange,
            product=product,
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
    # Batch nodes suppress per-leg order.placed, so their legs are tagged from
    # the single completion event each publishes.
    for topic in (
        "multiorder.completed",
        "basket.completed",
        "split.completed",
        "options.completed",
    ):
        bus.subscribe(topic, on_batch_completed, name="StrategyBookBatchTagger")
    logger.debug("Strategy book subscriber registered")
