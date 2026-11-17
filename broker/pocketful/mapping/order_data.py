"""Pocketful books -> OpenAlgo's common shapes (docs/api/account-services/).

Sources: Pocketful's API documentation (offline copy of 2026-11-17):
fetch-pending-orders.md, fetch-completed-orders.md, order-book.md,
trade-book.md, fetch-position-netwise.md and fetch-demat-holdings.md.

Each ``get_*`` function in broker/pocketful/api/order_api.py returns
``{"status": "success", "data": [rows]}`` with Pocketful's rows as they came.
The ``map_*`` functions turn those rows into OpenAlgo's vocabulary in place
(symbol, product, pricetype, status) and can run twice on the same rows; the
``transform_*`` functions build the documented output.

Order statuses. Pocketful splits the order book into a pending list and a
completed list, and get_order_book tags every row with the list it came from
(BOOK_KEY). The docs name only some statuses (COMPLETE, REJECTED, CANCELLED,
PENDING, CONFIRMED, MODCONFIRMED, AMO_REQ_RECEIVED, AMO_MODIFY_CONFIRMED,
AMO_CANCEL_CONFIRMED), so the list decides what the words cannot:

- a row from the pending list is still working: "trigger pending" when its
  status mentions a trigger, otherwise "open";
- a row from the completed list is finished: "complete", "rejected" or
  "cancelled" from its status, or "complete" when it filled in full.
"""

from datetime import datetime, timedelta, timezone

from broker.pocketful.mapping.transform_data import (
    reverse_map_order_type,
    reverse_map_product_type,
)
from database.token_db import get_oa_symbol, get_symbol
from utils.logging import get_logger

logger = get_logger(__name__)

# The key get_order_book adds to each order row: "pending" or "completed".
BOOK_KEY = "_pocketful_book"
PENDING_BOOK = "pending"
COMPLETED_BOOK = "completed"

# India Standard Time has no daylight saving, so a fixed offset is exact.
_IST = timezone(timedelta(hours=5, minutes=30))


def _float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value, default=0):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _ist_text(epoch):
    """Pocketful's epoch seconds (order_entry_time, exchange_time) as IST
    "DD-MM-YYYY HH:MM:SS", a form the order book page parses; "" for none."""
    seconds = _float(epoch)
    if seconds <= 0:
        return ""
    try:
        return datetime.fromtimestamp(seconds, _IST).strftime("%d-%m-%Y %H:%M:%S")
    except (OverflowError, OSError, ValueError):
        return str(epoch)


def _rows(data):
    """The list of rows inside ``{"data": [...]}`` (what the get_* functions
    return), or a bare list; anything else is no rows."""
    if isinstance(data, dict):
        data = data.get("data")
    if not isinstance(data, list):
        return []
    return [row for row in data if isinstance(row, dict)]


def oa_symbol(brsymbol, token, exchange):
    """The OpenAlgo symbol for a Pocketful row: by its trading symbol, then by
    its instrument token, else the trading symbol as Pocketful sent it, so a
    row missing from the master contract never shows up blank."""
    for lookup, key in ((get_oa_symbol, brsymbol), (get_symbol, token)):
        if key in (None, ""):
            continue
        try:
            symbol = lookup(str(key), exchange)
        except Exception:
            logger.exception(f"Could not look up the OpenAlgo symbol of {exchange}:{key}")
            symbol = None
        if symbol:
            return symbol
    return str(brsymbol or "")


def _map_common(row):
    """Symbol, product and side of an order, trade or position row, in place."""
    exchange = str(row.get("exchange") or "")
    row["exchange"] = exchange
    row["symbol"] = oa_symbol(row.get("trading_symbol"), row.get("instrument_token"), exchange)
    product = row.get("product")
    row["product"] = reverse_map_product_type(exchange, product) or str(product or "")
    row["order_side"] = str(row.get("order_side") or "").upper()
    return row


# --- order book ---------------------------------------------------------


def order_status(order):
    """OpenAlgo's status for one order row (see the module docstring)."""
    status = str(order.get("order_status") or "").upper()
    book = order.get(BOOK_KEY)
    if book == PENDING_BOOK:
        return "trigger pending" if "TRIGGER" in status else "open"
    if "COMPLETE" in status:
        return "complete"
    if "REJECT" in status:
        return "rejected"
    if "CANCEL" in status:
        return "cancelled"
    if book == COMPLETED_BOOK:
        quantity = _int(order.get("quantity"))
        if quantity > 0 and _int(order.get("filled_quantity")) >= quantity:
            return "complete"
        # A finished order whose word the docs do not name: show Pocketful's.
        return status.lower()
    if "TRIGGER" in status:
        return "trigger pending"
    return "open"


def map_order_data(order_data):
    """Order rows in OpenAlgo's vocabulary, in place."""
    orders = _rows(order_data)
    for order in orders:
        _map_common(order)
        order["order_type"] = reverse_map_order_type(order.get("order_type"))
        order["order_status"] = order_status(order)
    return orders


def calculate_order_statistics(order_data):
    total_buy_orders = total_sell_orders = 0
    total_completed_orders = total_open_orders = total_rejected_orders = 0

    for order in order_data or []:
        side = str(order.get("order_side") or "").upper()
        if side == "BUY":
            total_buy_orders += 1
        elif side == "SELL":
            total_sell_orders += 1

        status = order_status(order)
        if status == "complete":
            total_completed_orders += 1
        elif status in ("open", "trigger pending"):
            total_open_orders += 1
        elif status == "rejected":
            total_rejected_orders += 1

    return {
        "total_buy_orders": total_buy_orders,
        "total_sell_orders": total_sell_orders,
        "total_completed_orders": total_completed_orders,
        "total_open_orders": total_open_orders,
        "total_rejected_orders": total_rejected_orders,
    }


def transform_order_data(orders):
    if isinstance(orders, dict):
        orders = _rows(orders)

    transformed = []
    for order in orders or []:
        if not isinstance(order, dict):
            logger.warning(f"Skipping an order row that is not an object: {type(order).__name__}")
            continue
        average_price = _float(order.get("average_trade_price")) or _float(
            order.get("average_price")
        )
        transformed.append(
            {
                "symbol": order.get("symbol", ""),
                "exchange": order.get("exchange", ""),
                "action": str(order.get("order_side") or "").upper(),
                "quantity": _int(order.get("quantity")),
                "price": _float(order.get("price")),
                "trigger_price": _float(order.get("trigger_price")),
                "pricetype": reverse_map_order_type(order.get("order_type")),
                "product": order.get("product", ""),
                "orderid": str(order.get("oms_order_id") or ""),
                "order_status": order_status(order),
                "timestamp": _ist_text(order.get("order_entry_time"))
                or _ist_text(order.get("exchange_time")),
                "filled_quantity": _int(order.get("filled_quantity")),
                "pending_quantity": _int(order.get("remaining_quantity")),
                "average_price": average_price,
            }
        )
    return transformed


# --- trade book ---------------------------------------------------------


def map_trade_data(trade_data):
    """Trade rows in OpenAlgo's vocabulary, in place."""
    trades = _rows(trade_data)
    for trade in trades:
        _map_common(trade)
    return trades


def _trade_quantity(trade):
    """The quantity a trade row filled: filled_quantity, else quantity.

    The trade-book page's only example is an order-shaped row with a
    filled_quantity of 0, so the order quantity stands in when no fill
    quantity is given.
    """
    return _int(trade.get("filled_quantity")) or _int(trade.get("quantity"))


def _trade_price(trade):
    """The price a trade row filled at: trade_price ("Price at which the trade
    was executed"), else the order's average trade price, else its average."""
    for key in ("trade_price", "average_trade_price", "average_price"):
        price = _float(trade.get(key))
        if price > 0:
            return price
    return 0.0


def transform_tradebook_data(tradebook_data):
    if isinstance(tradebook_data, dict):
        tradebook_data = _rows(tradebook_data)

    transformed = []
    for trade in tradebook_data or []:
        if not isinstance(trade, dict):
            continue
        quantity = _trade_quantity(trade)
        average_price = _trade_price(trade)
        transformed.append(
            {
                "symbol": trade.get("symbol", ""),
                "exchange": trade.get("exchange", ""),
                "product": trade.get("product", ""),
                "action": str(trade.get("order_side") or "").upper(),
                "quantity": quantity,
                "average_price": average_price,
                "trade_value": round(quantity * average_price, 2),
                "orderid": str(trade.get("oms_order_id") or ""),
                "timestamp": _ist_text(trade.get("exchange_time"))
                or _ist_text(trade.get("order_entry_time")),
            }
        )
    return transformed


# --- positions ----------------------------------------------------------


def map_position_data(position_data):
    """Position rows in OpenAlgo's vocabulary, in place."""
    positions = _rows(position_data)
    for position in positions:
        _map_common(position)
    return positions


def _position_pnl(position):
    """Realised and open P&L: the net amount of the buys and sells plus the
    open quantity at the LTP. ``net_amount`` is "Net amount considering buy and
    sell transactions"; without it, sell_amount less buy_amount."""
    net_quantity = _int(position.get("net_quantity"))
    multiplier = _float(position.get("multiplier"), 1.0) or 1.0
    if position.get("net_amount") is not None:
        net_amount = _float(position.get("net_amount"))
    else:
        net_amount = _float(position.get("sell_amount")) - _float(position.get("buy_amount"))
    return net_amount + net_quantity * _float(position.get("ltp")) * multiplier


def transform_positions_data(positions_data):
    if isinstance(positions_data, dict):
        positions_data = _rows(positions_data)

    transformed = []
    for position in positions_data or []:
        if not isinstance(position, dict):
            continue
        net_quantity = _int(position.get("net_quantity"))
        # The average of the open side: a long carries the buy average, a
        # short the sell average.
        if net_quantity > 0:
            average_price = _float(position.get("average_buy_price"))
        elif net_quantity < 0:
            average_price = _float(position.get("average_sell_price"))
        else:
            average_price = 0.0
        if not average_price:
            average_price = _float(position.get("average_price"))

        transformed.append(
            {
                "symbol": position.get("symbol", ""),
                "exchange": position.get("exchange", ""),
                "product": position.get("product", ""),
                "quantity": net_quantity,
                "average_price": f"{average_price:.2f}",
                "ltp": round(_float(position.get("ltp")), 2),
                "pnl": round(_position_pnl(position), 2),
            }
        )
    return transformed


# --- holdings -----------------------------------------------------------


def map_portfolio_data(portfolio_data):
    """Holding rows in OpenAlgo's vocabulary, in place.

    The row's own ``trading_symbol`` is the bare name ("SBIN"); the broker
    symbol the master contract stores ("SBIN-EQ") is in
    ``instrument_details.trading_symbol``.
    """
    holdings = _rows(portfolio_data)
    for holding in holdings:
        exchange = str(holding.get("exchange") or "")
        details = holding.get("instrument_details")
        details = details if isinstance(details, dict) else {}
        brsymbol = details.get("trading_symbol") or holding.get("trading_symbol")
        token = holding.get("token") or details.get("instrument_token")
        holding["exchange"] = exchange
        holding["symbol"] = oa_symbol(brsymbol, token, exchange)
        # Demat holdings are delivery holdings.
        holding["product"] = "CNC"
    return holdings


def calculate_portfolio_statistics(holdings_data):
    holdings = [h for h in holdings_data or [] if isinstance(h, dict)]
    totalholdingvalue = sum(_float(h.get("ltp")) * _int(h.get("quantity")) for h in holdings)
    totalinvvalue = sum(_float(h.get("buy_avg")) * _int(h.get("quantity")) for h in holdings)
    totalprofitandloss = totalholdingvalue - totalinvvalue
    totalpnlpercentage = (totalprofitandloss / totalinvvalue * 100) if totalinvvalue else 0.0
    return {
        "totalholdingvalue": round(totalholdingvalue, 2),
        "totalinvvalue": round(totalinvvalue, 2),
        "totalprofitandloss": round(totalprofitandloss, 2),
        "totalpnlpercentage": round(totalpnlpercentage, 2),
    }


def transform_holdings_data(holdings_data):
    transformed = []
    for holding in holdings_data or []:
        if not isinstance(holding, dict):
            continue
        quantity = _int(holding.get("quantity"))
        average_price = _float(holding.get("buy_avg"))
        ltp = _float(holding.get("ltp"))
        pnl = (ltp - average_price) * quantity
        pnlpercent = ((ltp - average_price) / average_price * 100) if average_price else 0.0
        transformed.append(
            {
                "symbol": holding.get("symbol", ""),
                "exchange": holding.get("exchange", ""),
                "quantity": quantity,
                "product": holding.get("product", "CNC"),
                "average_price": round(average_price, 2),
                "ltp": round(ltp, 2),
                "pnl": round(pnl, 2),
                "pnlpercent": round(pnlpercent, 2),
            }
        )
    return transformed
