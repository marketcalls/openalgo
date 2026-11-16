"""Nuvama order book, trade book, positions and holdings -> OpenAlgo's common format.

Every Nuvama book answers ``{"appID", "config", "msgID", "srvTm", "data": {...}}``
with the rows under ``data.ord`` (orders), ``data.trade`` (trades),
``data.pos`` (net positions) or ``data.rmsHdg`` (holdings). An empty book is
HTTP 222 with an ``error`` object (``ETRD0002``, ``ETRD0004``), which reads
here as no rows. Each row's ``sym`` is the streaming symbol, the token in the
master contract, so rows map back to OpenAlgo symbols through it.
"""

from broker.nuvama.mapping.exchange import to_oa_exchange
from broker.nuvama.mapping.transform_data import (
    reverse_map_order_type,
    reverse_map_product_type,
    reverse_map_side,
)
from database.token_db import get_oa_symbol, get_symbol
from utils.logging import get_logger

logger = get_logger(__name__)


def _rows(payload, key):
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if not isinstance(data, dict):
        return []
    rows = data.get(key)
    return rows if isinstance(rows, list) else []


def _f(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _i(value, default=0):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def oa_symbol_for(row):
    """OpenAlgo symbol for a book row: by streaming symbol, else by trading symbol."""
    exchange = to_oa_exchange(row.get("exc"))
    token = row.get("sym")
    if token:
        symbol = get_symbol(token, exchange)
        if symbol:
            return symbol
    trd_sym = row.get("trdSym")
    if trd_sym:
        symbol = get_oa_symbol(trd_sym, exchange)
        if symbol:
            return symbol
    return trd_sym or token or ""


def normalize_status(status):
    """Nuvama's order status text -> OpenAlgo's lowercase status."""
    text = (status or "").strip().lower()
    if not text:
        return ""
    # In-flight states Nuvama streams (seen live: "put order req received",
    # "validation pending", "open pending", "cancel pending") are still open:
    # a cancel that is pending has not cancelled anything yet.
    if text.endswith("pending") and "trigger" not in text:
        return "open"
    if "reject" in text:
        return "rejected"
    if "cancel" in text:
        return "cancelled"
    if "trigger" in text:
        return "trigger pending"
    if "partial" in text:
        return "open"
    if text in ("complete", "completed", "executed", "traded", "filled", "fully executed"):
        return "complete"
    if "complete" in text or "executed" in text:
        return "complete"
    return "open"


# --- orders ----------------------------------------------------------------


def map_order_data(order_data):
    """Rows of the order book with OpenAlgo symbols, sides, products and types."""
    orders = _rows(order_data, "ord")
    for order in orders:
        order["_symbol"] = oa_symbol_for(order)
        order["_exchange"] = to_oa_exchange(order.get("exc"))
        order["_action"] = reverse_map_side(order.get("trsTyp"))
        order["_product"] = reverse_map_product_type(order.get("prdCode"))
        order["_pricetype"] = reverse_map_order_type(order.get("ordTyp"))
        order["_status"] = normalize_status(order.get("sts"))
    return orders


def calculate_order_statistics(order_data):
    stats = {
        "total_buy_orders": 0,
        "total_sell_orders": 0,
        "total_completed_orders": 0,
        "total_open_orders": 0,
        "total_rejected_orders": 0,
    }
    for order in order_data or []:
        side = order.get("_action") or reverse_map_side(order.get("trsTyp"))
        if side == "BUY":
            stats["total_buy_orders"] += 1
        elif side == "SELL":
            stats["total_sell_orders"] += 1
        status = order.get("_status") or normalize_status(order.get("sts"))
        if status == "complete":
            stats["total_completed_orders"] += 1
        elif status in ("open", "trigger pending"):
            stats["total_open_orders"] += 1
        elif status == "rejected":
            stats["total_rejected_orders"] += 1
    return stats


def transform_order_data(orders):
    if isinstance(orders, dict):
        orders = [orders]
    out = []
    for order in orders or []:
        if not isinstance(order, dict):
            continue
        out.append(
            {
                "symbol": order.get("_symbol", ""),
                "exchange": order.get("_exchange", ""),
                "action": order.get("_action", ""),
                "quantity": _i(order.get("ntQty") or order.get("reqQty")),
                "price": _f(order.get("prc")),
                "trigger_price": _f(order.get("trgPrc")),
                "pricetype": order.get("_pricetype", ""),
                "product": order.get("_product", ""),
                "orderid": order.get("ordID", ""),
                "order_status": order.get("_status", ""),
                "timestamp": order.get("ordTim") or order.get("rcvTim") or "",
            }
        )
    return out


# --- trades ----------------------------------------------------------------


def map_trade_data(trade_data):
    trades = _rows(trade_data, "trade")
    for trade in trades:
        trade["_symbol"] = oa_symbol_for(trade)
        trade["_exchange"] = to_oa_exchange(trade.get("exc"))
        trade["_action"] = reverse_map_side(trade.get("trsTyp"))
        trade["_product"] = reverse_map_product_type(trade.get("prdCode"))
    return trades


def transform_tradebook_data(tradebook_data):
    out = []
    for trade in tradebook_data or []:
        quantity = _i(trade.get("flQty") or trade.get("fldQty"))
        price = _f(trade.get("flPrc"))
        timestamp = " ".join(p for p in (trade.get("flDt"), trade.get("flTim")) if p)
        out.append(
            {
                "symbol": trade.get("_symbol", ""),
                "exchange": trade.get("_exchange", ""),
                "product": trade.get("_product", ""),
                "action": trade.get("_action", ""),
                "quantity": quantity,
                "average_price": price,
                "trade_value": round(quantity * price, 2),
                "orderid": trade.get("ordID", ""),
                "timestamp": timestamp or trade.get("ordTim", ""),
            }
        )
    return out


# --- positions -------------------------------------------------------------


def map_position_data(position_data):
    positions = _rows(position_data, "pos")
    for position in positions:
        position["_symbol"] = oa_symbol_for(position)
        position["_exchange"] = to_oa_exchange(position.get("exc"))
        position["_product"] = reverse_map_product_type(position.get("prdCode"))
    return positions


def position_average_price(position):
    """Average of the side the open quantity is on."""
    net = _i(position.get("ntQty"))
    if net > 0:
        return _f(position.get("avgByPrc"))
    if net < 0:
        return _f(position.get("avgSlPrc"))
    return 0.0


def transform_positions_data(positions_data):
    out = []
    for position in positions_data or []:
        pnl = position.get("ntPL")
        if pnl in (None, ""):
            pnl = _f(position.get("rlzPL")) + _f(position.get("urlzPL"))
        out.append(
            {
                "symbol": position.get("_symbol", ""),
                "exchange": position.get("_exchange", ""),
                "product": position.get("_product", ""),
                "quantity": _i(position.get("ntQty")),
                "pnl": round(_f(pnl), 2),
                "average_price": f"{position_average_price(position):.2f}",
                "ltp": round(_f(position.get("ltp")), 2),
            }
        )
    return out


# --- holdings --------------------------------------------------------------


def map_portfolio_data(portfolio_data):
    holdings = _rows(portfolio_data, "rmsHdg")
    for holding in holdings:
        holding["_symbol"] = oa_symbol_for(holding)
        holding["_exchange"] = to_oa_exchange(holding.get("exc"))
        holding["_qty"] = _i(holding.get("totalQty"))
    return [h for h in holdings if h["_qty"]]


def transform_holdings_data(holdings_data):
    """Holdings rows. Nuvama's RMS holdings carry no buy average, so the
    average price and P&L stay 0 rather than being made up."""
    out = []
    for holding in holdings_data or []:
        out.append(
            {
                "symbol": holding.get("_symbol", ""),
                "exchange": holding.get("_exchange", ""),
                "quantity": holding.get("_qty", 0),
                "product": "CNC",
                "average_price": 0.0,
                "pnl": 0.0,
                "pnlpercent": 0.0,
            }
        )
    return out


def calculate_portfolio_statistics(holdings_data):
    total_value = 0.0
    for holding in holdings_data or []:
        value = holding.get("totalVal")
        if value in (None, ""):
            value = _f(holding.get("ltp")) * _i(holding.get("totalQty"))
        total_value += _f(value)
    return {
        "totalholdingvalue": round(total_value, 2),
        "totalinvvalue": 0.0,
        "totalprofitandloss": 0.0,
        "totalpnlpercentage": 0.0,
    }
