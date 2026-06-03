import json

from broker.dhan.mapping.transform_data import map_exchange
from database.token_db import get_symbol
from utils.logging import get_logger

logger = get_logger(__name__)


def map_order_data(order_data):
    """
    Processes and modifies a list of order dictionaries based on specific conditions.

    Parameters:
    - order_data: A list of dictionaries, where each dictionary represents an order.

    Returns:
    - The modified order_data with updated 'tradingsymbol' and 'product' fields.
    """
    # Check if 'data' is None
    if order_data is None:
        # Handle the case where there is no data
        # For example, you might want to display a message to the user
        # or pass an empty list or dictionary to the template.
        logger.info("No data available.")
        order_data = {}  # or set it to an empty list if it's supposed to be a list
    else:
        order_data = order_data

    if order_data:
        for order in order_data:
            # Extract the instrument_token and exchange for the current order
            instrument_token = order["securityId"]
            exchange = map_exchange(order["exchangeSegment"])
            order["exchangeSegment"] = exchange

            # Use the get_symbol function to fetch the symbol from the database
            symbol_from_db = get_symbol(instrument_token, exchange)

            # Check if a symbol was found; if so, update the trading_symbol in the current order
            if symbol_from_db:
                order["tradingSymbol"] = symbol_from_db
                if (
                    order["exchangeSegment"] == "NSE" or order["exchangeSegment"] == "BSE"
                ) and order["productType"] == "CNC":
                    order["productType"] = "CNC"

                elif order["productType"] == "INTRADAY":
                    order["productType"] = "MIS"

                elif (
                    order["exchangeSegment"] in ["NFO", "MCX", "BFO", "CDS"]
                    and order["productType"] == "MARGIN"
                ):
                    order["productType"] = "NRML"
            else:
                # Symbol resolution failed (e.g. stale/partial master contract).
                # Never leave a null tradingSymbol — fall back to the raw broker
                # symbol or securityId so the row stays usable instead of
                # crashing the positions UI with null.toUpperCase(). See #1463.
                order["tradingSymbol"] = (
                    order.get("tradingSymbol") or str(order.get("securityId") or "")
                )
                logger.warning(
                    f"Symbol not found for token {instrument_token} and exchange {exchange}. "
                    f"Falling back to raw symbol '{order['tradingSymbol']}'."
                )

    return order_data


def calculate_order_statistics(order_data):
    """
    Calculates statistics from order data, including totals for buy orders, sell orders,
    completed orders, open orders, and rejected orders.

    Parameters:
    - order_data: A list of dictionaries, where each dictionary represents an order.

    Returns:
    - A dictionary containing counts of different types of orders.
    """
    # Initialize counters
    total_buy_orders = total_sell_orders = 0
    total_completed_orders = total_open_orders = total_rejected_orders = 0

    if order_data:
        for order in order_data:
            # Count buy and sell orders
            if order["transactionType"] == "BUY":
                total_buy_orders += 1
            elif order["transactionType"] == "SELL":
                total_sell_orders += 1

            # Count orders based on their status
            if order["orderStatus"] == "TRADED":
                total_completed_orders += 1
                order["orderStatus"] = "complete"
            elif order["orderStatus"] == "PENDING":
                total_open_orders += 1
                order["orderStatus"] = "open"
            elif order["orderStatus"] == "REJECTED":
                total_rejected_orders += 1
                order["orderStatus"] = "rejected"
            elif order["orderStatus"] == "CANCELLED":
                order["orderStatus"] = "cancelled"

    # Compile and return the statistics
    return {
        "total_buy_orders": total_buy_orders,
        "total_sell_orders": total_sell_orders,
        "total_completed_orders": total_completed_orders,
        "total_open_orders": total_open_orders,
        "total_rejected_orders": total_rejected_orders,
    }


def transform_order_data(orders):
    # Directly handling a dictionary assuming it's the structure we expect
    if isinstance(orders, dict):
        # Convert the single dictionary into a list of one dictionary
        orders = [orders]

    transformed_orders = []

    for order in orders:
        # Make sure each item is indeed a dictionary
        if not isinstance(order, dict):
            logger.warning(
                f"Warning: Expected a dict, but found a {type(order)}. Skipping this item."
            )
            continue

        if order["orderType"] == "MARKET":
            order["orderType"] = "MARKET"
        if order["orderType"] == "LIMIT":
            order["orderType"] = "LIMIT"
        if order["orderType"] == "STOP_LOSS":
            order["orderType"] = "SL"
        if order["orderType"] == "STOP_LOSS_MARKET":
            order["orderType"] = "SL-M"

        transformed_order = {
            "symbol": order.get("tradingSymbol", ""),
            "exchange": order.get("exchangeSegment", ""),
            "action": order.get("transactionType", ""),
            "quantity": order.get("quantity", 0),
            "price": order.get("price", 0.0),
            "trigger_price": order.get("triggerPrice", 0.0),
            "pricetype": order.get("orderType", ""),
            "product": order.get("productType", ""),
            "orderid": order.get("orderId", ""),
            "order_status": order.get("orderStatus", ""),
            "timestamp": order.get("updateTime", ""),
        }

        transformed_orders.append(transformed_order)

    return transformed_orders


def map_trade_data(trade_data):
    return map_order_data(trade_data)


def transform_tradebook_data(tradebook_data):
    transformed_data = []
    for trade in tradebook_data:
        transformed_trade = {
            "symbol": trade.get("tradingSymbol", ""),
            "exchange": trade.get("exchangeSegment", ""),
            "product": trade.get("productType", ""),
            "action": trade.get("transactionType", ""),
            "quantity": trade.get("tradedQuantity", 0),
            "average_price": trade.get("tradedPrice", 0.0),
            "trade_value": trade.get("tradedQuantity", 0) * trade.get("tradedPrice", 0.0),
            "orderid": trade.get("orderId", ""),
            "timestamp": trade.get("updateTime", ""),
        }
        transformed_data.append(transformed_trade)
    return transformed_data


def map_position_data(position_data):
    return map_order_data(position_data)


def transform_positions_data(positions_data):
    # Dhan's /v2/positions doesn't include LTP unlike other brokers
    # Fetch LTP via multiquotes service (same pattern as sandbox mode)
    ltp_map = {}
    if positions_data:
        try:
            from database.auth_db import ApiKeys, decrypt_token
            from services.quotes_service import get_multiquotes

            api_key_obj = ApiKeys.query.first()
            if api_key_obj:
                api_key = decrypt_token(api_key_obj.api_key_encrypted)
                symbols_payload = [
                    {
                        "symbol": pos.get("tradingSymbol") or "",
                        "exchange": pos.get("exchangeSegment") or "",
                    }
                    for pos in positions_data
                    if pos.get("tradingSymbol") and pos.get("exchangeSegment")
                ]
                if symbols_payload:
                    success, response, _ = get_multiquotes(symbols=symbols_payload, api_key=api_key)
                    if success and "results" in response:
                        for result in response["results"]:
                            if "data" in result and result["data"]:
                                key = f"{result['exchange']}:{result['symbol']}"
                                ltp_map[key] = float(result["data"].get("ltp", 0))
        except Exception as e:
            logger.warning(f"Failed to fetch LTP via multiquotes: {e}")

    transformed_data = []
    for position in positions_data:
        realized_pnl = float(position.get("realizedProfit", 0))
        unrealized_pnl = float(position.get("unrealizedProfit", 0))
        # Coerce nulls: dict.get(k, "") returns None (not "") when the key is
        # present with a null value, so a null symbol/exchange/product would
        # otherwise reach the frontend and crash null.toUpperCase(). See #1463.
        symbol = position.get("tradingSymbol") or ""
        exchange = position.get("exchangeSegment") or ""
        ltp = ltp_map.get(f"{exchange}:{symbol}", 0.0)

        transformed_position = {
            "symbol": symbol,
            "exchange": exchange,
            "product": position.get("productType") or "",
            "quantity": position.get("netQty", 0),
            "average_price": position.get("costPrice", 0.0),
            "ltp": round(ltp, 2),
            "pnl": round(realized_pnl + unrealized_pnl, 2),
        }
        transformed_data.append(transformed_position)
    return transformed_data


def map_portfolio_data(portfolio_data):
    """Validate the Dhan /holdings response and enrich each row with LTP +
    real exchange so the downstream stats and transform stages can render
    a meaningful row on first paint.

    Dhan returns ``exchange="ALL"`` for every holding (demat is exchange-
    agnostic) and the /holdings endpoint does NOT include LTP. We resolve
    the actual listing exchange via the SymToken cache (probing NSE then
    BSE using the broker-returned ``securityId``) and batch-fetch LTPs
    via the multiquote service — same pattern transform_positions_data
    uses for the same reason.

    Enrichment writes three private fields into each holding dict that
    calculate_portfolio_statistics and transform_holdings_data both
    consume:

    - ``_oa_symbol``: OpenAlgo symbol resolved from securityId+exchange
    - ``_exchange``: real exchange ("NSE" or "BSE"), never "ALL"
    - ``_ltp``: last-traded price (0.0 if multiquote failed/missing — the
      frontend's useLivePrice hook fills it in via WebSocket within seconds)
    """
    if portfolio_data is None or (
        isinstance(portfolio_data, dict)
        and (
            portfolio_data.get("errorCode") == "DHOLDING_ERROR"
            or portfolio_data.get("internalErrorCode") == "DH-1111"
            or portfolio_data.get("internalErrorMessage") == "No holdings available"
        )
    ):
        logger.info("No data or no holdings available.")
        return {}
    if not isinstance(portfolio_data, list):
        return {}

    # Resolve exchange per holding via SymToken cache. securityId is the
    # Dhan broker token and is exchange-scoped, so a single hit uniquely
    # identifies the listing. Probe NSE first (most equity), then BSE.
    for h in portfolio_data:
        security_id = str(h.get("securityId", "") or "")
        trading_sym = h.get("tradingSymbol", "")
        resolved_exchange = None
        resolved_symbol = trading_sym
        if security_id:
            for candidate in ("NSE", "BSE"):
                sym = get_symbol(security_id, candidate)
                if sym:
                    resolved_exchange = candidate
                    resolved_symbol = sym
                    break
        h["_oa_symbol"] = resolved_symbol
        h["_exchange"] = resolved_exchange or "NSE"
        h["_ltp"] = 0.0

    # Batch-fetch LTPs via multiquote.
    try:
        from database.auth_db import ApiKeys, decrypt_token
        from services.quotes_service import get_multiquotes

        api_key_obj = ApiKeys.query.first()
        if api_key_obj:
            api_key = decrypt_token(api_key_obj.api_key_encrypted)
            symbols_payload = [
                {"symbol": h["_oa_symbol"], "exchange": h["_exchange"]}
                for h in portfolio_data
                if h.get("_oa_symbol") and h.get("_exchange")
            ]
            if symbols_payload:
                success, response, _ = get_multiquotes(
                    symbols=symbols_payload, api_key=api_key
                )
                if success and isinstance(response, dict) and "results" in response:
                    ltp_map = {}
                    for result in response["results"]:
                        if isinstance(result, dict) and result.get("data"):
                            key = f"{result.get('exchange')}:{result.get('symbol')}"
                            ltp_map[key] = float(result["data"].get("ltp", 0) or 0)
                    for h in portfolio_data:
                        key = f"{h['_exchange']}:{h['_oa_symbol']}"
                        if key in ltp_map:
                            h["_ltp"] = ltp_map[key]
    except Exception as e:
        logger.warning(f"Failed to fetch LTP via multiquotes for holdings: {e}")

    return portfolio_data


def calculate_portfolio_statistics(holdings_data):
    if not holdings_data:
        return {
            "totalholdingvalue": 0,
            "totalinvvalue": 0,
            "totalprofitandloss": 0,
            "totalpnlpercentage": 0,
        }
    totalinvvalue = sum(
        float(item.get("avgCostPrice", 0) or 0) * int(item.get("totalQty", 0) or 0)
        for item in holdings_data
    )
    # Prefer the enriched _ltp when present; fall back to avg cost so the
    # value is at least equal to investment (i.e. zero P&L) instead of zero
    # holding value before the frontend's useLivePrice fills in live LTP.
    totalholdingvalue = sum(
        (float(item.get("_ltp", 0) or 0) or float(item.get("avgCostPrice", 0) or 0))
        * int(item.get("totalQty", 0) or 0)
        for item in holdings_data
    )
    totalprofitandloss = totalholdingvalue - totalinvvalue
    totalpnlpercentage = (totalprofitandloss / totalinvvalue * 100) if totalinvvalue else 0
    return {
        "totalholdingvalue": totalholdingvalue,
        "totalinvvalue": totalinvvalue,
        "totalprofitandloss": totalprofitandloss,
        "totalpnlpercentage": totalpnlpercentage,
    }


def transform_holdings_data(holdings_data):
    transformed_data = []
    if not holdings_data:
        return transformed_data
    for h in holdings_data:
        qty = int(h.get("totalQty", 0) or 0)
        avg = float(h.get("avgCostPrice", 0) or 0)
        ltp = float(h.get("_ltp", 0) or 0)
        if ltp > 0 and avg > 0:
            pnl = round((ltp - avg) * qty, 2)
            pnlpercent = round((ltp - avg) / avg * 100, 2)
        else:
            pnl = 0.0
            pnlpercent = 0.0
        transformed_data.append({
            "symbol": h.get("_oa_symbol") or h.get("tradingSymbol", ""),
            "exchange": h.get("_exchange") or "NSE",
            "quantity": qty,
            "product": "CNC",
            "average_price": round(avg, 2),
            "ltp": round(ltp, 2),
            "pnl": pnl,
            "pnlpercent": pnlpercent,
        })
    return transformed_data
