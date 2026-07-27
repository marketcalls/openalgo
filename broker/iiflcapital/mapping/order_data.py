from database.token_db import get_symbol

from broker.iiflcapital.mapping.transform_data import reverse_map_order_type, reverse_map_product_type


def _extract_rows(payload):
    if isinstance(payload, list):
        return payload

    if not isinstance(payload, dict):
        return []

    result = payload.get("result")
    if isinstance(result, list):
        return result
    if isinstance(result, dict):
        for key in ("orders", "trades", "positions", "holdings", "data", "positionList"):
            value = result.get(key)
            if isinstance(value, list):
                return value
        return [result]

    for key in ("data", "orders", "trades", "positions", "holdings"):
        value = payload.get(key)
        if isinstance(value, list):
            return value

    return []


def _map_exchange(exchange: str) -> str:
    mapping = {
        "NSEEQ": "NSE",
        "BSEEQ": "BSE",
        "NSEFO": "NFO",
        "BSEFO": "BFO",
        "NSECURR": "CDS",
        "BSECURR": "BCD",
        "MCXCOMM": "MCX",
        "NSECOMM": "MCX",
        "NCDEXCOMM": "MCX",
    }
    return mapping.get((exchange or "").upper(), (exchange or "").upper())


def _map_status(status: str) -> str:
    normalized = (status or "").upper()
    if normalized in {"COMPLETE", "COMPLETED", "FILLED", "SUCCESS", "EXECUTED"}:
        return "complete"
    if normalized in {"REJECTED", "FAIL", "FAILED"}:
        return "rejected"
    if normalized in {"CANCELLED", "CANCELED"}:
        return "cancelled"
    if normalized in {"TRIGGER_PENDING"}:
        return "trigger pending"
    return "open"


def _resolve_symbol(row: dict, exchange: str) -> str:
    symbol = row.get("tradingSymbol") or row.get("symbol") or row.get("formattedInstrumentName", "")

    token = row.get("instrumentId") or row.get("token") or row.get("exchangeInstrumentID")
    if token and exchange:
        db_symbol = get_symbol(str(token), exchange)
        if db_symbol:
            return db_symbol

    return symbol


def _to_float(value, default=0.0):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return default


def _resolve_holding_quantity(row: dict) -> float:
    """
    Resolve holding quantity without inflating totals.

    IIFL holdings payload can include aggregate fields like `totalQuantity` alongside
    component quantities (`quantity`, `dpQuantity`, `t1Quantity`). In some accounts,
    using only `totalQuantity` can overstate effective holdings. Prefer explicit
    quantity fields first, then fall back to totalQuantity.
    """
    # Prefer settled DP quantity first (matches broker holdings page more closely)
    # before generic quantity fields that may include aggregate values.
    for key in ("dpQuantity", "dpQty", "availableQuantity", "dpquantity", "dp_qty"):
        dp_qty = _to_float(row.get(key))
        if dp_qty > 0:
            return dp_qty

    qty = 0.0
    for key in ("quantity", "holdingQuantity", "qty"):
        qty = _to_float(row.get(key))
        if qty > 0:
            break

    total_qty = 0.0
    for key in ("totalQuantity", "totalQty", "holdingTotalQuantity"):
        total_qty = _to_float(row.get(key))
        if total_qty > 0:
            break

    t1_qty = 0.0
    for key in ("t1Quantity", "t1Qty", "t1_quantity", "unsettledQuantity"):
        t1_qty = _to_float(row.get(key))
        if t1_qty > 0:
            break

    # If aggregate quantity appears to include T1, value only settled quantity.
    if qty > 0 and t1_qty > 0 and qty >= t1_qty:
        settled = qty - t1_qty
        if settled >= 0:
            return settled

    if total_qty > 0 and t1_qty > 0 and total_qty >= t1_qty:
        settled = total_qty - t1_qty
        if settled >= 0:
            return settled

    if qty > 0:
        return qty

    if total_qty > 0:
        return total_qty

    if t1_qty > 0:
        return t1_qty

    return 0.0


def map_order_data(order_data):
    return _extract_rows(order_data)


def calculate_order_statistics(order_data):
    rows = order_data if isinstance(order_data, list) else _extract_rows(order_data)

    total_buy_orders = 0
    total_sell_orders = 0
    total_completed_orders = 0
    total_open_orders = 0
    total_rejected_orders = 0

    for row in rows:
        action = (row.get("transactionType") or row.get("action") or "").upper()
        status = _map_status(row.get("orderStatus") or row.get("status"))

        if action == "BUY":
            total_buy_orders += 1
        elif action == "SELL":
            total_sell_orders += 1

        if status == "complete":
            total_completed_orders += 1
        elif status == "rejected":
            total_rejected_orders += 1
        elif status in ("open", "trigger pending"):
            total_open_orders += 1

    return {
        "total_buy_orders": total_buy_orders,
        "total_sell_orders": total_sell_orders,
        "total_completed_orders": total_completed_orders,
        "total_open_orders": total_open_orders,
        "total_rejected_orders": total_rejected_orders,
    }


def transform_order_data(orders):
    rows = orders if isinstance(orders, list) else _extract_rows(orders)
    transformed = []

    for row in rows:
        broker_exchange = row.get("exchange", "")
        exchange = _map_exchange(broker_exchange)

        transformed.append(
            {
                "symbol": _resolve_symbol(row, exchange),
                "exchange": exchange,
                "action": (row.get("transactionType") or "").upper(),
                "quantity": int(float(row.get("quantity", 0) or 0)),
                "price": float(row.get("price", 0) or 0),
                "trigger_price": float(row.get("slTriggerPrice", 0) or 0),
                "pricetype": reverse_map_order_type(row.get("orderType", "MARKET")),
                "product": reverse_map_product_type(row.get("product", "INTRADAY")),
                "orderid": str(row.get("brokerOrderId", "")),
                "order_status": _map_status(row.get("orderStatus", "")),
                "timestamp": row.get("exchangeTimestamp")
                or row.get("exchangeUpdateTime")
                or row.get("brokerUpdateTime")
                or "",
            }
        )

    return transformed


def map_trade_data(trade_data):
    return _extract_rows(trade_data)


def transform_tradebook_data(tradebook_data):
    rows = tradebook_data if isinstance(tradebook_data, list) else _extract_rows(tradebook_data)
    transformed = []

    for row in rows:
        broker_exchange = row.get("exchange", "")
        exchange = _map_exchange(broker_exchange)

        qty = int(float(row.get("filledQuantity", row.get("quantity", 0)) or 0))
        avg_price = float(row.get("tradedPrice", row.get("averageTradedPrice", 0)) or 0)

        transformed.append(
            {
                "symbol": _resolve_symbol(row, exchange),
                "exchange": exchange,
                "product": reverse_map_product_type(row.get("product", "INTRADAY")),
                "action": (row.get("transactionType") or "").upper(),
                "quantity": qty,
                "average_price": avg_price,
                "trade_value": qty * avg_price,
                "orderid": str(row.get("brokerOrderId", "")),
                "timestamp": row.get("fillTimestamp") or row.get("exchangeTimestamp") or "",
            }
        )

    return transformed


def map_position_data(position_data):
    return _extract_rows(position_data)


def transform_positions_data(positions_data):
    rows = positions_data if isinstance(positions_data, list) else _extract_rows(positions_data)
    transformed = []

    for row in rows:
        broker_exchange = row.get("exchange", "")
        exchange = _map_exchange(broker_exchange)

        quantity = int(float(row.get("netQuantity", row.get("quantity", 0)) or 0))
        average_price = float(row.get("netAveragePrice", row.get("averagePrice", 0)) or 0)

        transformed.append(
            {
                "symbol": _resolve_symbol(row, exchange),
                "exchange": exchange,
                "product": reverse_map_product_type(row.get("product", "NORMAL")),
                "quantity": quantity,
                "average_price": f"{average_price:.2f}",
                "ltp": float(row.get("ltp", row.get("lastPrice", row.get("previousDayClose", 0))) or 0),
                "pnl": float(row.get("pnl", row.get("mtm", 0)) or 0),
            }
        )

    return transformed


def map_portfolio_data(portfolio_data):
    return _extract_rows(portfolio_data)


def calculate_portfolio_statistics(holdings_data):
    rows = holdings_data if isinstance(holdings_data, list) else _extract_rows(holdings_data)

    if not rows:
        return {
            "totalholdingvalue": 0.0,
            "totalinvvalue": 0.0,
            "totalprofitandloss": 0.0,
            "totalpnlpercentage": 0.0,
        }

    total_holding_value = 0.0
    total_investment_value = 0.0

    for row in rows:
        qty = _resolve_holding_quantity(row)
        avg_price = _to_float(row.get("averageTradedPrice", row.get("averagePrice", 0)))
        ltp = _to_float(row.get("ltp", row.get("previousDayClose", avg_price)), avg_price)

        total_holding_value += qty * ltp
        total_investment_value += qty * avg_price

    pnl = total_holding_value - total_investment_value
    pnl_pct = (pnl / total_investment_value * 100) if total_investment_value > 0 else 0.0

    return {
        "totalholdingvalue": round(total_holding_value, 2),
        "totalinvvalue": round(total_investment_value, 2),
        "totalprofitandloss": round(pnl, 2),
        "totalpnlpercentage": round(pnl_pct, 2),
    }


def transform_holdings_data(holdings_data):
    rows = holdings_data if isinstance(holdings_data, list) else _extract_rows(holdings_data)
    transformed = []

    for row in rows:
        # Prefer NSE instrument symbol if present
        symbol = row.get("nseTradingSymbol") or row.get("tradingSymbol") or row.get("symbol") or ""
        exchange = "NSE"

        quantity = int(_resolve_holding_quantity(row))
        avg_price = _to_float(row.get("averageTradedPrice", row.get("averagePrice", 0)))
        ltp = _to_float(row.get("ltp", row.get("previousDayClose", avg_price)), avg_price)

        pnl = quantity * (ltp - avg_price)
        pnl_pct = (pnl / (quantity * avg_price) * 100) if quantity > 0 and avg_price > 0 else 0.0

        transformed.append(
            {
                "symbol": symbol,
                "exchange": exchange,
                "product": reverse_map_product_type(row.get("product", "DELIVERY")),
                "quantity": quantity,
                "average_price": round(avg_price, 2),
                "ltp": round(ltp, 2),
                "pnl": round(pnl, 2),
                "pnlpercent": round(pnl_pct, 2),
            }
        )

    return transformed
