"""Map SMIFS God Quant responses to OpenAlgo's display shapes."""

from broker.smifs.mapping.transform_data import (
    map_exchange,
    reverse_map_order_type,
    reverse_map_product_type,
)
from database.token_db import get_symbol

_STATUS = {
    "TRANSIT": "open",
    "PENDING": "open",
    "PARTIALLY_FILLED": "open",
    "FILLED": "complete",
    "CANCELLED": "cancelled",
    "REJECTED": "rejected",
    "EXPIRED": "cancelled",
}


def _list(data):
    """SMIFS list endpoints return a list; anything else (an error) shows as empty."""
    return data if isinstance(data, list) else []


def _symbol(row):
    exch = map_exchange(row.get("exchangeSegment"))
    return get_symbol(row.get("securityId"), exch) or row.get("tradingSymbol") or row.get(
        "securityId"
    ), exch


def _order_status(o):
    status = _STATUS.get(o.get("orderStatus"), "open")
    if status == "open" and o.get("orderType") in ("STOP_LOSS", "STOP_LOSS_MARKET"):
        return "trigger pending"
    return status


def map_order_data(order_data):
    return _list(order_data)


def calculate_order_statistics(order_data):
    stats = {
        "total_buy_orders": 0,
        "total_sell_orders": 0,
        "total_completed_orders": 0,
        "total_open_orders": 0,
        "total_rejected_orders": 0,
    }
    for o in _list(order_data):
        if o.get("transactionType") == "BUY":
            stats["total_buy_orders"] += 1
        elif o.get("transactionType") == "SELL":
            stats["total_sell_orders"] += 1
        status = _STATUS.get(o.get("orderStatus"))
        if status == "complete":
            stats["total_completed_orders"] += 1
        elif status == "open":
            stats["total_open_orders"] += 1
        elif status == "rejected":
            stats["total_rejected_orders"] += 1
    return stats


def transform_order_data(orders):
    out = []
    for o in _list(orders):
        sym, exch = _symbol(o)
        out.append(
            {
                "symbol": sym,
                "exchange": exch,
                "action": o.get("transactionType"),
                "quantity": o.get("quantity"),
                "price": o.get("price"),
                "average_price": o.get("averagePrice", 0),
                "trigger_price": o.get("triggerPrice"),
                "pricetype": reverse_map_order_type(o.get("orderType")),
                "product": reverse_map_product_type(o.get("productType")),
                "orderid": o.get("orderId"),
                "order_status": _order_status(o),
                "timestamp": o.get("createdAt", ""),
            }
        )
    return out


def map_trade_data(trade_data):
    return _list(trade_data)


def transform_tradebook_data(tradebook_data):
    out = []
    for t in _list(tradebook_data):
        sym, exch = _symbol(t)
        qty = int(t.get("tradedQuantity", 0) or 0)
        price = float(t.get("tradedPrice", 0) or 0)
        out.append(
            {
                "symbol": sym,
                "exchange": exch,
                "product": reverse_map_product_type(t.get("productType")),
                "action": t.get("transactionType"),
                "quantity": qty,
                "average_price": price,
                "trade_value": round(price * qty, 2),
                "orderid": t.get("orderId"),
                "timestamp": t.get("tradedAt", ""),
            }
        )
    return out


def map_position_data(position_data):
    return _list(position_data)


def transform_positions_data(positions_data):
    out = []
    for p in _list(positions_data):
        sym, exch = _symbol(p)
        net = int(p.get("netQty", 0) or 0)
        out.append(
            {
                "symbol": sym,
                "exchange": exch,
                "product": reverse_map_product_type(p.get("productType")),
                "quantity": net,
                "average_price": p.get("buyAvg") if net >= 0 else p.get("sellAvg"),
                "ltp": 0,
                "pnl": round(
                    float(p.get("realizedProfit", 0) or 0)
                    + float(p.get("unrealizedProfit", 0) or 0),
                    2,
                ),
            }
        )
    return out


def map_portfolio_data(portfolio_data):
    return _list(portfolio_data)


def calculate_portfolio_statistics(holdings_data):
    """SMIFS holdings carry no live price, so value is shown at cost and P&L as zero."""
    inv = sum(
        float(h.get("avgCostPrice", 0) or 0) * int(h.get("totalQty", 0) or 0)
        for h in _list(holdings_data)
    )
    return {
        "totalholdingvalue": round(inv, 2),
        "totalinvvalue": round(inv, 2),
        "totalprofitandloss": 0,
        "totalpnlpercentage": 0,
    }


def transform_holdings_data(holdings_data):
    out = []
    for h in _list(holdings_data):
        # Holding.exchange is the SMIFS segment (NSE_EQ), not an OpenAlgo exchange code.
        exch = map_exchange(h.get("exchange"))
        sym = get_symbol(h.get("securityId"), exch) or h.get("tradingSymbol")
        out.append(
            {
                "symbol": sym,
                "exchange": exch,
                "quantity": h.get("totalQty"),
                "product": "CNC",
                "average_price": h.get("avgCostPrice"),
                "ltp": 0,
                "pnl": 0,
                "pnlpercent": 0,
            }
        )
    return out
