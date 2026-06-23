from broker.arrow.mapping.transform_data import reverse_map_product_type
from database.token_db import get_oa_symbol
from utils.logging import get_logger

logger = get_logger(__name__)

# Arrow code -> OpenAlgo vocabulary (for normalizing broker responses).
_SIDE_MAP = {"B": "BUY", "S": "SELL"}
_ORDER_TYPE_REVERSE = {
    "LMT": "LIMIT",
    "MKT": "MARKET",
    "SL-LMT": "SL",
    "SL-MKT": "SL-M",
}
# Arrow order status -> OpenAlgo lowercase status (matches the rest of the app).
_STATUS_MAP = {
    "COMPLETE": "complete",
    "OPEN": "open",
    "PENDING": "open",
    "TRIGGER_PENDING": "trigger pending",
    "CANCELLED": "cancelled",
    "REJECTED": "rejected",
}


def _unwrap(payload, key=None):
    """Pull the list out of an Arrow {status, data} envelope. Arrow returns a
    flat list under `data` (unlike Zerodha's nested data.net)."""
    if not payload:
        return []
    data = payload.get("data") if isinstance(payload, dict) else payload
    if data is None:
        logger.info("No data available.")
        return []
    return data


def map_order_data(order_data):
    """Normalize broker symbols/codes in the order book in place and return the
    list of orders."""
    orders = _unwrap(order_data)
    for order in orders:
        exchange = order.get("exchange")
        brsymbol = order.get("symbol")
        if brsymbol:
            order["symbol"] = get_oa_symbol(brsymbol=brsymbol, exchange=exchange)
        order["product"] = reverse_map_product_type(exchange, order.get("product")) or order.get(
            "product"
        )
        order["transactionType"] = _SIDE_MAP.get(
            order.get("transactionType"), order.get("transactionType")
        )
        order["order"] = _ORDER_TYPE_REVERSE.get(order.get("order"), order.get("order"))
    return orders


def calculate_order_statistics(order_data):
    total_buy_orders = total_sell_orders = 0
    total_completed_orders = total_open_orders = total_rejected_orders = 0

    for order in order_data or []:
        # Accept both raw Arrow codes (B/S) and mapped values (BUY/SELL), and
        # both raw (COMPLETE) and transformed (complete) statuses, so the
        # counts stay correct regardless of which transformation stage the
        # caller passes in.
        side = str(order.get("transactionType", "")).upper()
        if side in ("BUY", "B"):
            total_buy_orders += 1
        elif side in ("SELL", "S"):
            total_sell_orders += 1

        status = str(order.get("orderStatus", "")).upper().replace(" ", "_")
        if status == "COMPLETE":
            total_completed_orders += 1
        elif status in ("OPEN", "PENDING", "TRIGGER_PENDING"):
            total_open_orders += 1
        elif status == "REJECTED":
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

    transformed_orders = []
    for order in orders or []:
        if not isinstance(order, dict):
            logger.warning(f"Expected a dict, found {type(order)}. Skipping.")
            continue

        transformed_orders.append(
            {
                "symbol": order.get("symbol", ""),
                "exchange": order.get("exchange", ""),
                "action": order.get("transactionType", ""),
                "quantity": order.get("quantity", 0),
                "price": order.get("price", 0.0),
                # TODO(arrow): confirm the trigger-price field name in /user/orders.
                "trigger_price": order.get("triggerPrice", 0.0),
                "pricetype": order.get("order", ""),
                "product": order.get("product", ""),
                # TODO(arrow): place returns `orderNo`; order book id field may be `id`.
                "orderid": order.get("orderNo") or order.get("id", ""),
                "order_status": _STATUS_MAP.get(
                    order.get("orderStatus"), order.get("orderStatus", "")
                ),
                "timestamp": order.get("orderTime") or order.get("requestTime", ""),
            }
        )
    return transformed_orders


def map_trade_data(trade_data):
    return map_order_data(trade_data)


def transform_tradebook_data(tradebook_data):
    transformed = []
    for trade in tradebook_data or []:
        # TODO(arrow): confirm trade fill field names (docs mention fillPrice/
        # fillQuantity/fillTime; falling back to order-style fields).
        quantity = trade.get("fillQuantity", trade.get("quantity", 0)) or 0
        avg_price = trade.get("fillPrice", trade.get("averagePrice", 0.0)) or 0.0
        transformed.append(
            {
                "symbol": trade.get("symbol"),
                "exchange": trade.get("exchange", ""),
                "product": trade.get("product", ""),
                "action": trade.get("transactionType", ""),
                "quantity": quantity,
                "average_price": avg_price,
                "trade_value": float(quantity) * float(avg_price),
                "orderid": trade.get("orderNo") or trade.get("id", ""),
                "timestamp": trade.get("fillTime") or trade.get("orderTime", ""),
            }
        )
    return transformed


def map_position_data(position_data):
    """Normalize broker symbols/codes in the (flat) position list in place."""
    positions = _unwrap(position_data)
    for position in positions:
        exchange = position.get("exchange")
        brsymbol = position.get("symbol")
        if brsymbol:
            position["symbol"] = get_oa_symbol(brsymbol=brsymbol, exchange=exchange)
        position["product"] = reverse_map_product_type(
            exchange, position.get("product")
        ) or position.get("product")
    return positions


def transform_positions_data(positions_data):
    transformed = []
    for position in positions_data or []:
        # TODO(arrow): confirm whether avgPrice/ltp are scaled x100 like quotes
        # (positions doc does not state scaling). Assuming rupee values here.
        avg_price = float(position.get("avgPrice", 0.0) or 0.0)
        realised = float(position.get("realisedPnL", 0.0) or 0.0)
        unrealised = float(position.get("unrealisedMarkToMarket", 0.0) or 0.0)
        transformed.append(
            {
                "symbol": position.get("symbol", ""),
                "exchange": position.get("exchange", ""),
                "product": position.get("product", ""),
                "quantity": position.get("qty", "0"),
                "pnl": round(realised + unrealised, 2),
                "average_price": f"{avg_price:.2f}",
                "ltp": round(float(position.get("ltp", 0.0) or 0.0), 2),
            }
        )
    return transformed


def map_portfolio_data(portfolio_data):
    """Normalize holdings. Arrow consolidates each holding under a `symbols`
    array (one instrument can list multiple exchanges); we pick the first."""
    holdings = _unwrap(portfolio_data)
    for holding in holdings:
        symbols = holding.get("symbols") or []
        primary = symbols[0] if symbols else {}
        brsymbol = primary.get("tradingSymbol") or primary.get("symbol")
        exchange = primary.get("exchange")
        if brsymbol and exchange:
            holding["_oa_symbol"] = get_oa_symbol(brsymbol=brsymbol, exchange=exchange)
            holding["_exchange"] = exchange
        else:
            holding["_oa_symbol"] = brsymbol or ""
            holding["_exchange"] = exchange or ""
        # Holdings are delivery by definition.
        holding["_product"] = "CNC"
    return holdings


def transform_holdings_data(holdings_data):
    transformed = []
    for holding in holdings_data or []:
        average_price = float(holding.get("avgPrice") or 0.0)
        ltp = float(holding.get("ltp") or 0.0)
        if average_price == 0:
            pnlpercent = 0.0
        else:
            pnlpercent = round((ltp - average_price) / average_price * 100, 2)

        transformed.append(
            {
                "symbol": holding.get("_oa_symbol", ""),
                "exchange": holding.get("_exchange", ""),
                "quantity": holding.get("qty", 0),
                "product": holding.get("_product", "CNC"),
                "average_price": average_price,
                # TODO(arrow): confirm holdings PnL field name (`pnl`).
                "pnl": round(float(holding.get("pnl", 0.0) or 0.0), 2),
                "pnlpercent": pnlpercent,
            }
        )
    return transformed


def calculate_portfolio_statistics(holdings_data):
    totalholdingvalue = sum(
        float(item.get("ltp") or 0.0) * float(item.get("qty") or 0.0) for item in holdings_data
    )
    totalinvvalue = sum(
        float(item.get("avgPrice") or 0.0) * float(item.get("qty") or 0.0) for item in holdings_data
    )
    totalprofitandloss = sum(float(item.get("pnl") or 0.0) for item in holdings_data)
    totalpnlpercentage = (totalprofitandloss / totalinvvalue * 100) if totalinvvalue else 0

    return {
        "totalholdingvalue": totalholdingvalue,
        "totalinvvalue": totalinvvalue,
        "totalprofitandloss": totalprofitandloss,
        "totalpnlpercentage": totalpnlpercentage,
    }
