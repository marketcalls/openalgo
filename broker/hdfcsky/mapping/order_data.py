# broker/hdfcsky/mapping/order_data.py
#
# Converts raw HDFC Sky account JSON into the documented OpenAlgo common
# format (docs/api/account-services/*).
#
# HDFC Sky response envelopes (from the docs):
#   order book : {"data": {"orders": [...]},   "status": "success"}
#   trade book : {"data": {"trades": [...]},   "status": "success"}
#   positions  : {"data": [...],               "status": "success"}   <- flat list
#   holdings   : {"data": {"holdings": [...]}, "status": "success"}

from broker.hdfcsky.mapping.exchange import to_oa_exchange
from broker.hdfcsky.mapping.transform_data import (
    reverse_map_order_type,
    reverse_map_product_type,
)
from database.token_db import get_oa_symbol
from utils.logging import get_logger

logger = get_logger(__name__)

# HDFC Sky order status -> OpenAlgo lowercase status.
#
# The status vocabulary comes from the GenericDTO proto's `Status` enum, which
# is the same set the REST order book returns. Anything that is still working
# at the exchange normalizes to "open".
_STATUS_MAP = {
    "COMPLETE": "complete",
    "REJECTED": "rejected",
    "MODIFY_REJECTED": "rejected",
    "CANCEL_REJECTED": "rejected",
    "BRACKET_ORDER_REJECTED": "rejected",
    "CANCELLED": "cancelled",
    "CANCEL_CONFIRMED": "cancelled",
    "BATCH_CANCEL_CONFIRMED": "cancelled",
    "AMO_CANCEL_CONFIRMED": "cancelled",
    "BRACKET_ORDER_CANCELLED": "cancelled",
    "SL_TRIGGER_CONFIRMED": "trigger pending",
    "TRIGGER_PENDING": "trigger pending",
    "ACCEPTED": "open",
    "CONFIRMED": "open",
    "PENDING": "open",
    "MODIFY_ACCEPTED": "open",
    "MODIFY_CONFIRMED": "open",
    "MODIFY_PENDING": "open",
    "CANCEL_ACCEPTED": "open",
    "CANCEL_PENDING": "open",
    "PARTIAL_TRADE": "open",
    "AMO_REQ_RECEIVED": "open",
    "AMO_REQ_CONFIRMED": "open",
    "AMO_REQ_MODIFIED": "open",
    "AMO_NEW_CONFIRMED": "open",
    "AMO_MODIFY_CONFIRMED": "open",
    "UNACCEPTED": "open",
    "EXCHANGE_RESPONSE_PENDING": "open",
    "RRM_PENDING_AT_EXCHANGE": "open",
    "RMS_VALIDATION_COMPLETED": "open",
}

# Statuses that can still be cancelled (used by cancel_all_orders_api).
CANCELLABLE_STATUSES = {
    status for status, mapped in _STATUS_MAP.items() if mapped in ("open", "trigger pending")
}


def map_order_status(status):
    return _STATUS_MAP.get(str(status).upper(), str(status).lower())


def _unwrap(payload, key):
    """Pull a list out of the HDFC Sky {status, message, data} envelope.

    `data` is a dict keyed by `key` for orders/trades/holdings and a bare list
    for positions, so both shapes are accepted.
    """
    if not payload:
        return []
    if isinstance(payload, list):
        return payload
    data = payload.get("data")
    if data is None:
        logger.info("No data available in HDFC Sky response.")
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        rows = data.get(key)
        return rows if isinstance(rows, list) else []
    return []


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


def _oa_symbol(brsymbol, exchange):
    """Broker trading symbol -> OpenAlgo symbol, falling back to the raw value
    so a symbol missing from the master contract never blanks out a row."""
    if not brsymbol:
        return ""
    try:
        return get_oa_symbol(brsymbol=brsymbol, exchange=exchange) or brsymbol
    except Exception as e:
        logger.debug(f"Could not map HDFC Sky symbol {exchange}:{brsymbol}: {e}")
        return brsymbol


# --- order book ---------------------------------------------------------


def map_order_data(order_data):
    """Normalize broker symbols/codes in the order book in place."""
    orders = _unwrap(order_data, "orders")
    for order in orders:
        exchange = to_oa_exchange(order.get("exchange"))
        order["exchange"] = exchange
        order["symbol"] = _oa_symbol(order.get("trading_symbol"), exchange)
        order["product"] = reverse_map_product_type(exchange, order.get("product")) or order.get(
            "product"
        )
        order["order_type"] = reverse_map_order_type(order.get("order_type"))
    return orders


def calculate_order_statistics(order_data):
    total_buy_orders = total_sell_orders = 0
    total_completed_orders = total_open_orders = total_rejected_orders = 0

    for order in order_data or []:
        if str(order.get("order_side", "")).upper() == "BUY":
            total_buy_orders += 1
        elif str(order.get("order_side", "")).upper() == "SELL":
            total_sell_orders += 1

        # Accept raw broker statuses and already-transformed lowercase ones so
        # the counts hold whichever stage the caller passes in.
        status = order.get("order_status", "")
        status = map_order_status(status) if str(status).isupper() else str(status).lower()
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
        orders = [orders]

    transformed = []
    for order in orders or []:
        if not isinstance(order, dict):
            logger.warning(f"Expected a dict, found {type(order)}. Skipping.")
            continue
        transformed.append(
            {
                "symbol": order.get("symbol", ""),
                "exchange": order.get("exchange", ""),
                "action": str(order.get("order_side", "")).upper(),
                "quantity": _int(order.get("quantity")),
                "price": _float(order.get("price")),
                "trigger_price": _float(order.get("trigger_price")),
                "pricetype": order.get("order_type", ""),
                "product": order.get("product", ""),
                "orderid": str(order.get("oms_order_id", "")),
                "order_status": map_order_status(order.get("order_status", "")),
                "timestamp": order.get("order_entry_time") or order.get("exchange_time", ""),
            }
        )
    return transformed


# --- trade book ---------------------------------------------------------


def map_trade_data(trade_data):
    trades = _unwrap(trade_data, "trades")
    for trade in trades:
        exchange = to_oa_exchange(trade.get("exchange"))
        trade["exchange"] = exchange
        trade["symbol"] = _oa_symbol(trade.get("trading_symbol"), exchange)
        trade["product"] = reverse_map_product_type(exchange, trade.get("product")) or trade.get(
            "product"
        )
    return trades


def transform_tradebook_data(tradebook_data):
    transformed = []
    for trade in tradebook_data or []:
        quantity = _int(trade.get("trade_quantity", trade.get("filled_quantity")))
        average_price = _float(trade.get("trade_price", trade.get("order_price")))
        transformed.append(
            {
                "symbol": trade.get("symbol", ""),
                "exchange": trade.get("exchange", ""),
                "product": trade.get("product", ""),
                "action": str(trade.get("order_side", "")).upper(),
                "quantity": quantity,
                "average_price": average_price,
                "trade_value": round(quantity * average_price, 2),
                "orderid": str(trade.get("oms_order_id", "")),
                "timestamp": trade.get("trade_time") or trade.get("exchange_time", ""),
            }
        )
    return transformed


# --- positions ----------------------------------------------------------


def map_position_data(position_data):
    positions = _unwrap(position_data, "positions")
    for position in positions:
        exchange = to_oa_exchange(position.get("exchange"))
        position["exchange"] = exchange
        position["symbol"] = _oa_symbol(position.get("trading_symbol"), exchange)
        position["product"] = reverse_map_product_type(
            exchange, position.get("product")
        ) or position.get("product")
    return positions


def transform_positions_data(positions_data):
    transformed = []
    for position in positions_data or []:
        net_quantity = _int(position.get("net_quantity"))
        multiplier = _float(position.get("multiplier"), 1.0) or 1.0
        ltp = _float(position.get("ltp"))
        buy_amount = _float(position.get("buy_amount"))
        sell_amount = _float(position.get("sell_amount"))

        # Standard MTM: realized leg (sell - buy value) plus the open leg
        # marked to the last traded price.
        pnl = (sell_amount - buy_amount) + (net_quantity * ltp * multiplier)

        # The average price of the OPEN leg: a long carries the buy average,
        # a short the sell average.
        if net_quantity > 0:
            average_price = _float(position.get("average_buy_price"))
        elif net_quantity < 0:
            average_price = _float(position.get("average_sell_price"))
        else:
            average_price = _float(position.get("average_price"))

        transformed.append(
            {
                "symbol": position.get("symbol", ""),
                "exchange": position.get("exchange", ""),
                "product": position.get("product", ""),
                "quantity": net_quantity,
                "pnl": round(pnl, 2),
                "average_price": f"{average_price:.2f}",
                "ltp": round(ltp, 2),
            }
        )
    return transformed


# --- holdings -----------------------------------------------------------


def map_portfolio_data(portfolio_data):
    """Normalize demat holdings.

    The row's own `trading_symbol` is already series-free ("SBIN"), while
    `instrument_details.trading_symbol` carries the broker format ("SBIN-EQ")
    that the master contract stores as brsymbol -- so resolve from the latter
    and fall back to the former.
    """
    holdings = _unwrap(portfolio_data, "holdings")
    for holding in holdings:
        exchange = to_oa_exchange(holding.get("exchange"))
        holding["exchange"] = exchange
        details = holding.get("instrument_details") or {}
        brsymbol = details.get("trading_symbol") or holding.get("trading_symbol")
        holding["symbol"] = _oa_symbol(brsymbol, exchange)
        # Demat holdings are delivery by definition.
        holding["product"] = "CNC"
    return holdings


def transform_holdings_data(holdings_data):
    transformed = []
    for holding in holdings_data or []:
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
                "pnl": round(pnl, 2),
                "pnlpercent": round(pnlpercent, 2),
            }
        )
    return transformed


def calculate_portfolio_statistics(holdings_data):
    totalholdingvalue = sum(
        _float(h.get("ltp")) * _int(h.get("quantity")) for h in holdings_data or []
    )
    totalinvvalue = sum(
        _float(h.get("buy_avg")) * _int(h.get("quantity")) for h in holdings_data or []
    )
    totalprofitandloss = totalholdingvalue - totalinvvalue
    totalpnlpercentage = (totalprofitandloss / totalinvvalue * 100) if totalinvvalue else 0.0

    return {
        "totalholdingvalue": round(totalholdingvalue, 2),
        "totalinvvalue": round(totalinvvalue, 2),
        "totalprofitandloss": round(totalprofitandloss, 2),
        "totalpnlpercentage": round(totalpnlpercentage, 2),
    }
