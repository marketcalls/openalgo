"""Map SMIFS God Quant responses to OpenAlgo's display shapes."""
from broker.smifs.mapping.transform_data import map_exchange, reverse_map_product_type
from database.token_db import get_symbol

_STATUS = {"TRANSIT": "open", "PENDING": "open", "PARTIALLY_FILLED": "open",
           "FILLED": "complete", "CANCELLED": "cancelled", "REJECTED": "rejected",
           "EXPIRED": "cancelled"}


def _symbol(row):
    exch = map_exchange(row.get("exchangeSegment"))
    return get_symbol(row.get("securityId"), exch) or row.get("securityId"), exch


def map_order_data(order_data):
    return order_data or []


def calculate_order_statistics(order_data):
    buys = sum(1 for o in (order_data or []) if o.get("transactionType") == "BUY")
    sells = sum(1 for o in (order_data or []) if o.get("transactionType") == "SELL")
    return {"total_buy_orders": buys, "total_sell_orders": sells,
            "total_orders": len(order_data or [])}


def transform_order_data(orders):
    out = []
    for o in (orders or []):
        sym, exch = _symbol(o)
        out.append({
            "symbol": sym, "exchange": exch,
            "action": o.get("transactionType"),
            "quantity": o.get("quantity"),
            "price": o.get("price"),
            "trigger_price": o.get("triggerPrice"),
            "pricetype": o.get("orderType"),
            "product": reverse_map_product_type(o.get("productType")),
            "orderid": o.get("orderId"),
            "order_status": _STATUS.get(o.get("orderStatus"), "open"),
            "timestamp": o.get("createdAt", ""),
        })
    return out


def map_trade_data(trade_data):
    return trade_data or []


def transform_tradebook_data(tradebook_data):
    out = []
    for t in (tradebook_data or []):
        sym, exch = _symbol(t)
        out.append({
            "symbol": sym, "exchange": exch,
            "product": reverse_map_product_type(t.get("productType")),
            "action": t.get("transactionType"),
            "quantity": t.get("tradedQuantity"),
            "average_price": t.get("tradedPrice"),
            "trade_value": float(t.get("tradedPrice", 0)) * int(t.get("tradedQuantity", 0)),
            "orderid": t.get("orderId"),
            "timestamp": t.get("tradedAt", ""),
        })
    return out


def map_position_data(position_data):
    return position_data or []


def transform_positions_data(positions_data):
    out = []
    for p in (positions_data or []):
        sym, exch = _symbol(p)
        out.append({
            "symbol": sym, "exchange": exch,
            "product": reverse_map_product_type(p.get("productType")),
            "quantity": p.get("netQty"),
            "average_price": p.get("buyAvg") if int(p.get("netQty", 0)) >= 0 else p.get("sellAvg"),
            "ltp": 0,
            "pnl": float(p.get("realizedProfit", 0)) + float(p.get("unrealizedProfit", 0)),
        })
    return out


def map_portfolio_data(portfolio_data):
    return portfolio_data or []


def calculate_portfolio_statistics(holdings_data):
    inv = sum(float(h.get("avgCostPrice", 0)) * int(h.get("totalQty", 0)) for h in (holdings_data or []))
    return {"totalholdingvalue": inv, "totalinvvalue": inv,
            "totalprofitandloss": 0, "totalpnlpercentage": 0}


def transform_holdings_data(holdings_data):
    out = []
    for h in (holdings_data or []):
        out.append({
            "symbol": h.get("tradingSymbol"),
            "exchange": h.get("exchange", "NSE"),
            "quantity": h.get("totalQty"),
            "product": "CNC",
            "average_price": h.get("avgCostPrice"),
            "ltp": 0, "pnl": 0, "pnlpercent": 0,
        })
    return out
