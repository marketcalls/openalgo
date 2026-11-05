"""Sahi order, trade, position and holding rows to OpenAlgo's common format.

The service layer calls ``map_*`` on the raw book returned by ``api.order_api``
and then ``transform_*`` on the result. ``map_*`` resolves symbols, converts
paise to rupees and Sahi codes to OpenAlgo ones; ``transform_*`` picks the
documented output fields (docs/api/account-services).
"""

from datetime import datetime, timedelta, timezone

from broker.sahi.mapping.transform_data import (
    from_paise,
    reverse_map_action,
    reverse_map_order_type,
    reverse_map_product_type,
)
from database.token_db import get_oa_symbol, get_symbol
from utils.logging import get_logger

logger = get_logger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))

# Sahi order status -> OpenAlgo order_status. PartialFilled is terminal (the
# remainder was cancelled or an IOC expired), so it reads as cancelled, the way
# other brokers report a partly filled order that stopped working. A stop
# order waiting for its trigger is reported by Sahi as Open.
ORDER_STATUS_MAP = {
    "Open": "open",
    "OpenPartial": "open",
    "PartialFilled": "cancelled",
    "Completed": "complete",
    "Cancelled": "cancelled",
    "Rejected": "rejected",
}


def map_order_status(status):
    return ORDER_STATUS_MAP.get(status, str(status or "").lower() or "open")


def format_timestamp(epoch_ms):
    """Epoch milliseconds to an IST 'YYYY-MM-DD HH:MM:SS' string ('' if unset)."""
    if not epoch_ms:
        return ""
    try:
        return datetime.fromtimestamp(int(epoch_ms) / 1000, tz=IST).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OverflowError, OSError):
        return ""


def _oa_symbol(brsymbol, segment):
    """OpenAlgo symbol for a Sahi (symbol, exchange_segment), or the raw symbol."""
    if not brsymbol:
        return ""
    symbol = get_oa_symbol(brsymbol=brsymbol, exchange=segment)
    if not symbol:
        logger.info(f"{brsymbol} on {segment} not in the master contract; keeping Sahi's symbol")
        return brsymbol
    return symbol


def _rows(data, key):
    if not isinstance(data, dict):
        return data if isinstance(data, list) else []
    return data.get(key) or []


def map_order_data(order_data):
    """Normalize Sahi's order book rows (prices in rupees, OpenAlgo codes)."""
    orders = []
    for row in _rows(order_data, "orders"):
        segment = row.get("exchange_segment", "")
        orders.append(
            {
                "symbol": _oa_symbol(row.get("symbol"), segment),
                "exchange": segment,
                "action": reverse_map_action(row.get("txn_type")),
                "quantity": int(row.get("qty") or 0),
                "filled_quantity": int(row.get("filled_qty") or 0),
                "price": from_paise(row.get("price")),
                "trigger_price": from_paise(row.get("trigger_price")),
                "average_price": from_paise(row.get("avg_price")),
                "pricetype": reverse_map_order_type(row.get("order_type")),
                "product": reverse_map_product_type(row.get("product")),
                "orderid": str(row.get("order_id", "")),
                "order_status": map_order_status(row.get("status")),
                "rejection_reason": row.get("rejection_reason"),
                "timestamp": format_timestamp(row.get("created_at")),
            }
        )
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
        if order.get("action") == "BUY":
            stats["total_buy_orders"] += 1
        elif order.get("action") == "SELL":
            stats["total_sell_orders"] += 1
        status = order.get("order_status")
        if status == "complete":
            stats["total_completed_orders"] += 1
        elif status == "open":
            stats["total_open_orders"] += 1
        elif status == "rejected":
            stats["total_rejected_orders"] += 1
    return stats


def transform_order_data(orders):
    if isinstance(orders, dict):
        orders = [orders]
    return [
        {
            "symbol": order.get("symbol", ""),
            "exchange": order.get("exchange", ""),
            "action": order.get("action", ""),
            "quantity": order.get("quantity", 0),
            "price": order.get("price", 0.0),
            "trigger_price": order.get("trigger_price", 0.0),
            "pricetype": order.get("pricetype", ""),
            "product": order.get("product", ""),
            "orderid": order.get("orderid", ""),
            "order_status": order.get("order_status", ""),
            "timestamp": order.get("timestamp", ""),
        }
        for order in orders or []
        if isinstance(order, dict)
    ]


def map_trade_data(trade_data):
    trades = []
    for row in _rows(trade_data, "trades"):
        segment = row.get("exchange_segment", "")
        quantity = int(row.get("qty") or 0)
        price = from_paise(row.get("price"))
        trades.append(
            {
                "symbol": _oa_symbol(row.get("symbol"), segment),
                "exchange": segment,
                "product": reverse_map_product_type(row.get("product")),
                "action": reverse_map_action(row.get("txn_type")),
                "quantity": quantity,
                "average_price": price,
                "trade_value": round(quantity * price, 2),
                "orderid": str(row.get("order_id", "")),
                "tradeid": str(row.get("exchange_trade_id", "")),
                "timestamp": format_timestamp(row.get("traded_at")),
            }
        )
    return trades


def transform_tradebook_data(tradebook_data):
    return [
        {
            "symbol": trade.get("symbol", ""),
            "exchange": trade.get("exchange", ""),
            "product": trade.get("product", ""),
            "action": trade.get("action", ""),
            "quantity": trade.get("quantity", 0),
            "average_price": trade.get("average_price", 0.0),
            "trade_value": trade.get("trade_value", 0.0),
            "orderid": trade.get("orderid", ""),
            "tradeid": trade.get("tradeid", ""),
            "timestamp": trade.get("timestamp", ""),
        }
        for trade in tradebook_data or []
    ]


def map_position_data(position_data):
    """Normalize Sahi positions; P&L is realised plus the open position marked at LTP.

    Sahi reports ``realised_pnl`` but no unrealised figure, so the open part is
    (ltp - net_avg_price) * net_qty, using the LTP order_api added to each row.
    With no LTP the unrealised part is left out rather than guessed.
    """
    positions = []
    for row in _rows(position_data, "positions"):
        segment = row.get("exchange_segment", "")
        net_qty = int(row.get("net_qty") or 0)
        avg = from_paise(row.get("net_avg_price"))
        ltp = float(row.get("ltp") or 0.0)
        pnl = from_paise(row.get("realised_pnl"))
        if net_qty and ltp:
            pnl += (ltp - avg) * net_qty
        positions.append(
            {
                "symbol": _oa_symbol(row.get("symbol"), segment),
                "exchange": segment,
                "product": reverse_map_product_type(row.get("product")),
                "quantity": net_qty,
                "average_price": avg if net_qty else 0.0,
                "ltp": ltp,
                "pnl": round(pnl, 2),
                "buy_quantity": int(row.get("total_buy_qty") or 0),
                "sell_quantity": int(row.get("total_sell_qty") or 0),
            }
        )
    return positions


def transform_positions_data(positions_data):
    return [
        {
            "symbol": position.get("symbol", ""),
            "exchange": position.get("exchange", ""),
            "product": position.get("product", ""),
            "quantity": position.get("quantity", 0),
            "pnl": round(position.get("pnl", 0.0), 2),
            "average_price": "{:.2f}".format(float(position.get("average_price", 0.0))),
            "ltp": round(position.get("ltp", 0.0), 2),
        }
        for position in positions_data or []
    ]


def _holding_listing(instrument_ids):
    """(symbol, exchange, id) of a holding's listing, NSE first, else BSE."""
    for exchange in ("NSE", "BSE"):
        for instrument_id in instrument_ids or []:
            symbol = get_symbol(str(instrument_id), exchange)
            if symbol:
                return symbol, exchange, instrument_id
    return None, None, None


def map_portfolio_data(portfolio_data):
    """Normalize Sahi holdings (settled plus T1), valued at the listing's LTP.

    Shares bought for delivery today show up with no settled quantity; they are
    in the position book, so they are left out here.
    """
    holdings = []
    for row in _rows(portfolio_data, "holdings"):
        quantity = int(row.get("holding_qty") or 0)
        if quantity <= 0:
            continue
        symbol, exchange, instrument_id = _holding_listing(row.get("instrument_ids"))
        if not symbol:
            logger.info(f"Holding {row.get('isin')} not in the master contract; skipped")
            continue
        avg = from_paise(row.get("holding_avg_price"))
        ltp = float((row.get("ltp_by_id") or {}).get(instrument_id, 0.0))
        pnl = round((ltp - avg) * quantity, 2) if ltp else 0.0
        pnlpercent = round((ltp - avg) / avg * 100, 2) if ltp and avg else 0.0
        holdings.append(
            {
                "symbol": symbol,
                "exchange": exchange,
                "quantity": quantity,
                "product": "CNC",
                "average_price": avg,
                "ltp": ltp,
                "pnl": pnl,
                "pnlpercent": pnlpercent,
            }
        )
    return holdings


def calculate_portfolio_statistics(holdings_data):
    holdings_data = holdings_data or []
    totalholdingvalue = sum(h["ltp"] * h["quantity"] for h in holdings_data)
    totalinvvalue = sum(h["average_price"] * h["quantity"] for h in holdings_data)
    totalprofitandloss = sum(h["pnl"] for h in holdings_data)
    totalpnlpercentage = (totalprofitandloss / totalinvvalue * 100) if totalinvvalue else 0
    return {
        "totalholdingvalue": round(totalholdingvalue, 2),
        "totalinvvalue": round(totalinvvalue, 2),
        "totalprofitandloss": round(totalprofitandloss, 2),
        "totalpnlpercentage": round(totalpnlpercentage, 2),
    }


def transform_holdings_data(holdings_data):
    return [
        {
            "symbol": h.get("symbol", ""),
            "exchange": h.get("exchange", ""),
            "quantity": h.get("quantity", 0),
            "product": h.get("product", "CNC"),
            "average_price": h.get("average_price", 0.0),
            "ltp": h.get("ltp", 0.0),
            "pnl": h.get("pnl", 0.0),
            "pnlpercent": h.get("pnlpercent", 0.0),
        }
        for h in holdings_data or []
    ]
