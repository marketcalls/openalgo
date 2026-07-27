from broker.iiflcapital.mapping.transform_data import (
    reverse_map_order_type,
    reverse_map_product_type,
)
from database.token_db import get_symbol


# Fields that indicate a dict is an actual order/trade/position/holding row,
# not a status/metadata wrapper. Used to avoid fabricating phantom UI rows
# when IIFL returns an empty book wrapped as `{"result": {...wrapper...}}`.
# Covers the canonical field names plus the variants the per-section
# transforms accept as fallbacks (orderId, formattedInstrumentName,
# tradedPrice, etc.) so a record with any of those still passes.
_ROW_FIELDS = (
    # Order / trade identifiers
    "brokerOrderId",
    "exchangeOrderId",
    "orderId",
    # Instrument identifiers
    "instrumentId",
    "token",
    "exchangeInstrumentID",
    "tradingSymbol",
    "symbol",
    "formattedInstrumentName",
    "nseTradingSymbol",
    "bseTradingSymbol",
    # Quantity-bearing fields (any of these implies a real record)
    "netQuantity",
    "filledQuantity",
    "pendingQuantity",
    "cancelledQuantity",
    "dpQuantity",
    "totalQuantity",
    # Action / price fields specific to real records
    "transactionType",
    "tradedPrice",
    "averageTradedPrice",
)


def _looks_like_row(item) -> bool:
    """True if a dict carries at least one identifying field of a real row."""
    if not isinstance(item, dict):
        return False
    for field in _ROW_FIELDS:
        value = item.get(field)
        # `value not in (None, "")` rather than truthy so legitimate `0` /
        # `"0"` quantity / netQuantity values on closed positions still
        # qualify the row.
        if value not in (None, ""):
            return True
    return False


def _extract_rows(payload):
    if isinstance(payload, list):
        # Some IIFL endpoints emit a single status-wrapper element when the
        # book is empty (e.g. `[{"status": "ok"}]`); strip those so the
        # downstream transforms don't render them as phantom rows.
        return [item for item in payload if _looks_like_row(item)]

    if not isinstance(payload, dict):
        return []

    result = payload.get("result")
    if isinstance(result, list):
        return [item for item in result if _looks_like_row(item)]
    if isinstance(result, dict):
        for key in ("orders", "trades", "positions", "holdings", "data", "positionList"):
            value = result.get(key)
            if isinstance(value, list):
                return [item for item in value if _looks_like_row(item)]
        # Only treat a result-dict as a single row when it actually looks
        # like one. Empty/metadata-only `result` wrappers were previously
        # rendered as phantom blank rows in the orderbook UI.
        if _looks_like_row(result):
            return [result]
        return []

    for key in ("data", "orders", "trades", "positions", "holdings"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if _looks_like_row(item)]

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
    if normalized == "TRIGGER_PENDING":
        return "trigger pending"
    if normalized in {"OPEN", "PENDING", "PARTIALLY_FILLED", "NEW", "PUT ORDER REQ RECEIVED"}:
        return "open"
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


def _first_present(row: dict, *keys: str):
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def _resolve_order_quantity(row: dict) -> int:
    quantity = _first_present(row, "quantity", "orderQuantity")
    if quantity not in (None, ""):
        return int(float(quantity or 0))

    filled_qty = _to_float(row.get("filledQuantity"))
    pending_qty = _to_float(row.get("pendingQuantity"))
    cancelled_qty = _to_float(row.get("cancelledQuantity"))
    return int(filled_qty + pending_qty + cancelled_qty)


def _resolve_holding_quantity(row: dict) -> float:
    """
    Resolve holding quantity preferring settled DP balance.

    Per IIFL spec: totalQuantity = dpQuantity + collateralQuantity + t1Quantity
    + authorizedQuantity. dpQuantity is what the broker UI shows as "settled".
    """
    for key in ("dpQuantity", "dpQty", "availableQuantity"):
        dp_qty = _to_float(row.get(key))
        if dp_qty > 0:
            return dp_qty

    for key in ("totalQuantity", "totalQty", "quantity", "holdingQuantity"):
        qty = _to_float(row.get(key))
        if qty > 0:
            return qty

    return _to_float(row.get("t1Quantity"))


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
                "quantity": _resolve_order_quantity(row),
                "price": _to_float(row.get("price")),
                "trigger_price": _to_float(_first_present(row, "slTriggerPrice", "triggerPrice")),
                "pricetype": reverse_map_order_type(str(row.get("orderType", "MARKET"))),
                "product": reverse_map_product_type(str(row.get("product", "INTRADAY"))),
                "orderid": str(_first_present(row, "brokerOrderId", "exchangeOrderId", "orderId") or ""),
                "order_status": _map_status(str(row.get("orderStatus", ""))),
                "rejection_reason": str(row.get("rejectionReason", "") or ""),
                "timestamp": _first_present(
                    row,
                    "exchangeTimestamp",
                    "exchangeUpdateTime",
                    "brokerUpdateTime",
                )
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

        qty = int(float(_first_present(row, "filledQuantity", "quantity", "filledQty") or 0))
        avg_price = _to_float(_first_present(row, "tradedPrice", "averageTradedPrice", "price"))

        transformed.append(
            {
                "symbol": _resolve_symbol(row, exchange),
                "exchange": exchange,
                "product": reverse_map_product_type(str(row.get("product", "INTRADAY"))),
                "action": (row.get("transactionType") or "").upper(),
                "quantity": qty,
                "average_price": avg_price,
                "trade_value": qty * avg_price,
                "orderid": str(_first_present(row, "brokerOrderId", "exchangeOrderId", "orderId") or ""),
                "timestamp": _first_present(
                    row,
                    "fillTimestamp",
                    "exchangeTimestamp",
                    "exchangeUpdateTime",
                    "brokerUpdateTime",
                )
                or "",
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
        average_price = _to_float(row.get("netAveragePrice", row.get("averagePrice", 0)))

        # IIFL position spec exposes only `previousDayClose`; fall back to it when
        # an upstream LTP isn't injected into the payload.
        ltp = _to_float(_first_present(row, "ltp", "lastPrice", "previousDayClose"))

        # Spec exposes `realizedPnl` only. Compute MTM unrealized from netQuantity
        # and netAveragePrice so OpenAlgo's `pnl` field reflects total P&L —
        # but only when LTP is genuinely populated. A missing LTP defaulting
        # to 0 would otherwise fabricate a (-average_price * quantity) loss.
        realized_pnl = _to_float(row.get("realizedPnl"))
        if quantity and ltp > 0:
            unrealized_pnl = (ltp - average_price) * quantity
        else:
            unrealized_pnl = 0.0
        pnl = realized_pnl + unrealized_pnl

        transformed.append(
            {
                "symbol": _resolve_symbol(row, exchange),
                "exchange": exchange,
                "product": reverse_map_product_type(row.get("product", "NORMAL")),
                "quantity": quantity,
                "average_price": f"{average_price:.2f}",
                "ltp": round(ltp, 2),
                "pnl": round(pnl, 2),
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
        quantity = int(_resolve_holding_quantity(row))

        # IIFL holdings expose nse* and bse* pairs. Pick the populated side so
        # BSE-only scrips aren't mislabeled as NSE with an empty symbol.
        nse_symbol = row.get("nseTradingSymbol")
        bse_symbol = row.get("bseTradingSymbol")
        if nse_symbol:
            symbol, exchange = nse_symbol, "NSE"
        elif bse_symbol:
            symbol, exchange = bse_symbol, "BSE"
        else:
            symbol = row.get("tradingSymbol") or row.get("formattedInstrumentName") or row.get("symbol") or ""
            exchange = "NSE"

        # Skip empty placeholder rows IIFL returns when the account has no
        # settled holdings (avg=0, qty=0, no trading symbol).
        if quantity <= 0:
            continue
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
