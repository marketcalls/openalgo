import json

from broker.tradejini.mapping.transform_data import (
    reverse_map_order_type,
    reverse_map_product_type,
)
from database.token_db import get_oa_symbol, get_symbol
from utils.logging import get_logger

logger = get_logger(__name__)


# --- Symbol object readers -------------------------------------------------
# The symbol object returned with symDetails=true is documented with the field
# names 'id', 'symbol', 'tradSymbol' and 'exchange', while some responses use
# the short forms 'sym', 'trdSym' and 'exch'. Read both so a rename on either
# side cannot blank out the order book, trade book, positions or holdings.


def _first(source, names, default=""):
    """Return the first present, non-empty value among `names`."""
    if not isinstance(source, dict):
        return default
    for name in names:
        value = source.get(name)
        if value not in (None, ""):
            return value
    return default


def sym_id(sym):
    """Symbol identifier, e.g. 'EQT_RELIANCE_EQ_NSE'."""
    return _first(sym, ("id", "symId"))


def sym_exchange(sym):
    """Exchange of the instrument, e.g. 'NSE'."""
    return _first(sym, ("exchange", "exch"))


def sym_base_symbol(sym):
    """Base symbol, e.g. 'RELIANCE'."""
    return _first(sym, ("symbol", "sym"))


def sym_trading_symbol(sym):
    """Exchange trading symbol, e.g. 'RELIANCE-EQ'."""
    return _first(sym, ("tradSymbol", "trdSym", "dispSymbol", "dispSym"))


def map_order_data(order_data):
    """
    Processes and modifies a list of order dictionaries based on specific conditions.

    Parameters:
    - order_data: Tradejini API response containing order information

    Returns:
    - The modified order_data with updated fields
    """
    logger.debug(f"map_order_data - Input order_data: {order_data}")

    # Check if response status is ok
    if order_data.get("stat") != "Ok":
        logger.debug("map_order_data - Error in API response")
        return []

    # Get orders from response - they are nested under 'data' field
    orders_data = order_data.get("data", [])
    # print(f"[DEBUG] map_order_data - Found {len(orders_data)} orders in response")
    # print(f"[DEBUG] map_order_data - Orders data: {orders_data}")

    # Process each order
    if orders_data:
        for order in orders_data:
            # Get the actual order data from the nested structure
            order_info = order.get("data", {})
            # logger.info(f"[DEBUG] map_order_data - Processing order info: {order_info}")

            # Update fields in place
            order["action"] = "BUY" if order_info.get("side") == "buy" else "SELL"
            order["exchange"] = order_info.get("exchange", "")
            # Map Tradejini status to OpenAlgo status
            raw_status = order_info.get("status", "").lower()
            status_map = {
                "completed": "complete",
                "traded": "complete",
                "filled": "complete",
                "complete": "complete",
                "open": "open",
                "pending": "open",
                "trigger pending": "trigger pending",
                "rejected": "rejected",
                "cancelled": "cancelled",
                "canceled": "cancelled",
            }
            order["order_status"] = status_map.get(raw_status, raw_status)
            order["orderid"] = str(order_info.get("order_id", ""))
            order["price"] = float(order_info.get("limit_price", 0) or 0)
            # Tradejini price types are limit/market/stoplimit/stopmarket - map
            # them to the OpenAlgo MARKET/LIMIT/SL/SL-M set.
            order["pricetype"] = reverse_map_order_type(order_info.get("type", ""))

            # Map product type using reverse mapping function
            product = order_info.get("product", "").lower()
            order["product"] = reverse_map_product_type(product) or "MIS"

            order["quantity"] = int(order_info.get("quantity", 0) or 0)
            order["symbol"] = order_info.get("tradingsymbol", "")
            order["timestamp"] = order_info.get("order_time", "")
            order["trigger_price"] = float(order_info.get("trigger_price", 0) or 0)

            # print(f"[DEBUG] map_order_data - Updated order: {order}")

    return orders_data


def calculate_order_statistics(order_data):
    """
    Calculates statistics from order data, including totals for buy orders, sell orders,
    completed orders, open orders, and rejected orders.

    Parameters:
    - order_data: List of orders with modified fields

    Returns:
    - Dictionary containing counts of different types of orders
    """
    # print(f"[DEBUG] calculate_order_statistics - Input order_data: {order_data}")

    # Initialize counters
    total_buy_orders = total_sell_orders = 0
    total_completed_orders = total_open_orders = total_rejected_orders = 0

    if order_data:
        for order in order_data:
            # Count buy and sell orders
            if order.get("action") == "BUY":
                total_buy_orders += 1
            elif order.get("action") == "SELL":
                total_sell_orders += 1

            # Count orders based on their status
            status = order.get("order_status", "").lower()
            if status == "complete":
                total_completed_orders += 1
            elif status == "rejected":
                total_rejected_orders += 1
            elif status == "open":
                total_open_orders += 1

    # Compile and return the statistics
    return {
        "total_buy_orders": total_buy_orders,
        "total_sell_orders": total_sell_orders,
        "total_completed_orders": total_completed_orders,
        "total_open_orders": total_open_orders,
        "total_rejected_orders": total_rejected_orders,
    }


def transform_order_data(orders):
    """
    Processes and modifies a list of order dictionaries into the final OpenAlgo format.

    Parameters:
    - orders: List of orders with modified fields

    Returns:
    - Dictionary with orders in OpenAlgo format
    """
    # print(f"[DEBUG] transform_order_data - Input orders: {orders}")

    # Directly handling a dictionary assuming it's the structure we expect
    if isinstance(orders, dict):
        # Convert the single dictionary into a list of one dictionary
        orders = [orders]

    transformed_orders = []

    for order in orders:
        # Convert to OpenAlgo format if needed
        transformed_order = {
            "action": order.get("action", ""),
            "exchange": order.get("exchange", ""),
            "order_status": order.get("order_status", ""),
            "orderid": str(order.get("orderid", "")),
            "price": float(order.get("price", 0)),
            "pricetype": order.get("pricetype", "").upper(),
            "product": order.get("product", "").upper(),
            "quantity": int(order.get("quantity", 0)),
            "symbol": order.get("symbol", ""),
            "timestamp": order.get("timestamp", ""),
            "trigger_price": float(order.get("trigger_price", 0)),
        }
        transformed_orders.append(transformed_order)
        # print(f"[DEBUG] transform_order_data - Transformed order: {transformed_order}")

    return transformed_orders


def map_trade_data(trade_data):
    """
    Processes and modifies a list of trade dictionaries based on specific conditions.

    Args:
        trade_data: Tradejini API response containing trade information

    Returns:
        The modified trade_data with updated fields
    """
    logger.debug(f"map_trade_data - Input trade_data type: {type(trade_data)}")

    # Handle already transformed data that might be in different formats

    # Handle direct array of trades (from get_trade_book)
    if isinstance(trade_data, list):
        # If it's already a list of trades, just return it
        return trade_data

    # Handle OpenAlgo format with status and data fields
    if (
        isinstance(trade_data, dict)
        and "status" in trade_data
        and trade_data.get("status") == "success"
    ):
        if "data" in trade_data and isinstance(trade_data["data"], list):
            return trade_data["data"]
        return []

    # Check if it's a TradeJini API response
    if not isinstance(trade_data, dict) or "s" not in trade_data or trade_data.get("s") != "ok":
        # Not a TradeJini API response - log at debug level instead of warning to avoid unnecessary warnings
        logger.debug("map_trade_data - Not a TradeJini API response format")
        return []

    # Get trades from response - they are in the 'd' array
    trades_data = trade_data.get("d", [])
    logger.debug(f"map_trade_data - Found {len(trades_data)} trades in response")

    # Process each trade
    mapped_trades = []
    if trades_data:
        for trade in trades_data:
            # Get symbol details from the sym object
            symbol = trade.get("sym", {}) or {}

            # Map product types (delivery/intraday/normal/cover/bracket)
            product = reverse_map_product_type(trade.get("product", "")) or "NRML"

            # Map side to action
            side = trade.get("side", "").lower()
            action = "BUY" if side == "buy" else "SELL"

            # Get exchange from sym object
            exchange = str(sym_exchange(symbol)).upper()

            # Create mapped trade
            mapped_trade = {
                "symbol": sym_trading_symbol(symbol),
                "exchange": exchange,
                "product": product,
                "action": action,
                "quantity": trade.get("fillQty", 0),
                "average_price": trade.get("fillPrice", 0.0),
                "trade_value": trade.get("fillValue", 0.0),
                "orderid": trade.get("orderId", ""),
                "timestamp": trade.get("time", ""),
                "sym_id": sym_id(symbol) or trade.get("symId", ""),  # For OpenAlgo lookup
            }

            # Add optional fields if present
            if trade.get("exchOrderId"):
                mapped_trade["exchange_order_id"] = trade.get("exchOrderId", "")

            if trade.get("remarks"):
                mapped_trade["remarks"] = trade.get("remarks", "")

            mapped_trades.append(mapped_trade)

    return mapped_trades


def transform_tradebook_data(trades):
    """
    Transforms mapped trade data to OpenAlgo format.

    Args:
        trades: List of mapped trade dictionaries or raw API response

    Returns:
        dict: Trade book data in OpenAlgo format with {'data': [...], 'status': 'success'}
    """
    logger.debug(f"transform_tradebook_data - Input trades type: {type(trades)}")

    # Check if already in OpenAlgo format
    if isinstance(trades, dict) and "status" in trades and "data" in trades:
        logger.debug("transform_tradebook_data - Already in OpenAlgo format")
        # Extract just the data array without the wrapper
        return trades["data"]

    # Handle empty list case
    if not trades:
        logger.debug("transform_tradebook_data - Empty trades list")
        # Return just the array without any wrapper
        return []

    # Check if raw TradeJini API response
    if isinstance(trades, dict) and "s" in trades and trades.get("s") == "ok" and "d" in trades:
        logger.debug("transform_tradebook_data - Processing raw TradeJini API response")
        trades = trades.get("d", [])

    # Directly handling a dictionary assuming it's a single trade
    if isinstance(trades, dict) and "action" not in trades and "orderid" not in trades:
        # Convert the single dictionary into a list of one dictionary
        logger.debug("transform_tradebook_data - Converting single dict to list")
        trades = [trades]

    if not isinstance(trades, list):
        logger.error(f"Invalid input data type: Expected list or dict, got {type(trades)}")
        return {
            "status": "error",
            "data": [],
            "message": f"Invalid input data type: Expected list or dict, got {type(trades)}",
        }

    transformed_trades = []

    for trade in trades:
        if not isinstance(trade, dict):
            logger.warning(f"Skipping invalid trade data: {type(trade)}")
            continue

        # Check if this is already transformed
        if all(key in trade for key in ["action", "average_price", "exchange", "orderid"]):
            transformed_trades.append(trade)
            continue

        # Get Symbol details if it exists
        symbol = trade.get("sym", {})

        if isinstance(symbol, dict) and symbol:
            symbol_id = sym_id(symbol)
            exchange = sym_exchange(symbol)
            trading_symbol = sym_trading_symbol(symbol)
        else:
            # Use data from trade directly if sym object doesn't exist
            symbol_id = trade.get("sym_id", "")
            exchange = trade.get("exchange", "")
            trading_symbol = trade.get("symbol", "")

        # Get OpenAlgo symbol if possible
        try:
            # get_oa_symbol(brsymbol, exchange) - pass positionally, the first
            # parameter is the broker symbol id, not an OpenAlgo symbol.
            openalgo_symbol = get_oa_symbol(symbol_id, exchange)
        except Exception as e:
            logger.warning(f"Symbol lookup failed: {str(e)}")
            openalgo_symbol = None

        # Map product type if needed
        if "product" in trade:
            product = reverse_map_product_type(trade["product"]) or str(trade["product"]).upper()
        else:
            product = "MIS"  # Default

        # Map side to action if needed
        if "action" in trade:
            action = trade["action"]
        elif "side" in trade:
            side = trade.get("side", "").lower()
            action = "BUY" if side == "buy" else "SELL"
        else:
            action = ""  # Can't determine

        # Create transformed trade - match OpenAlgo format exactly
        transformed_trade = {
            "action": action,
            "average_price": float(trade.get("fillPrice", trade.get("average_price", 0.0))),
            "exchange": exchange.upper() if exchange else "",
            "orderid": str(trade.get("orderId", trade.get("orderid", ""))),
            "product": product,
            "quantity": int(trade.get("fillQty", trade.get("quantity", 0))),
            "symbol": openalgo_symbol or trading_symbol,
            "timestamp": trade.get("time", trade.get("timestamp", "")),
            "trade_value": float(trade.get("fillValue", trade.get("trade_value", 0.0))),
        }

        # Removed tradingsymbol and exchange_order_id fields as per requirements

        if "remarks" in trade:
            transformed_trade["remarks"] = trade.get("remarks", "")

        transformed_trades.append(transformed_trade)

    logger.debug(f"transform_tradebook_data - Transformed {len(transformed_trades)} trades")

    return transformed_trades


# Position mapping functions have been moved to get_positions function in order_api.py
# These compatibility functions are kept for backward compatibility


def map_position_data(position_data):
    """
    Map TradeJini position data to a standardized format.
    DEPRECATED: This function is kept for backward compatibility only.
    Position mapping is now done directly in get_positions function.
    """
    logger.warning(
        "map_position_data is deprecated - position mapping is now done directly in get_positions"
    )

    # Check for different response formats
    if isinstance(position_data, dict):
        # Handle the case where the entire API response is passed
        if position_data.get("s") == "ok" and "d" in position_data:
            position_data = position_data.get("d", [])
        # Handle already processed data with status and data fields
        elif position_data.get("status") == "success" and "data" in position_data:
            # Data already mapped - return as is
            return position_data.get("data", [])

    if not position_data or not isinstance(position_data, list):
        logger.warning("No valid position data available or invalid format")
        return []

    mapped_positions = []

    for position in position_data:
        try:
            # Skip zero positions
            net_qty = position.get("netQty", 0)
            if net_qty == 0:
                continue

            # Map product type (delivery/intraday/normal/cover/bracket)
            product = reverse_map_product_type(position.get("product", "")) or "MIS"

            sym = position.get("sym", {}) or {}
            exchange_symbol = sym_base_symbol(sym)
            tradingsymbol = sym_trading_symbol(sym)
            exchange = sym_exchange(sym)

            # Get symbol ID from the position data
            symbol_id = position.get("symId", "")

            # Log position data for debugging
            logger.info(
                f"Position data: symId={symbol_id}, tradingsymbol={tradingsymbol}, exchange={exchange}"
            )

            # Get OpenAlgo symbol - follow same approach as the main implementation
            openalgo_symbol = None
            try:
                # First try with the symbol ID from sym object
                symid_from_object = sym_id(sym)
                if symid_from_object:
                    openalgo_symbol = get_oa_symbol(symid_from_object, exchange)
                    logger.info(
                        f"Symbol lookup with sym.id: {symid_from_object} -> {openalgo_symbol}"
                    )

                # If not found and we have the position symId, try that
                if not openalgo_symbol and symbol_id:
                    openalgo_symbol = get_oa_symbol(symbol_id, "")
                    logger.info(
                        f"Symbol lookup with position.symId: {symbol_id} -> {openalgo_symbol}"
                    )

                # If still not found, try with exchange symbol
                if not openalgo_symbol:
                    openalgo_symbol = get_oa_symbol(exchange_symbol, exchange)
                    logger.info(
                        f"Symbol lookup with exchange symbol: {exchange_symbol} -> {openalgo_symbol}"
                    )

            except Exception as e:
                logger.warning(f"Symbol lookup failed: {str(e)}")
                openalgo_symbol = None

            # Determine the final symbol to use
            final_symbol = ""
            if openalgo_symbol:
                final_symbol = openalgo_symbol
                logger.info(f"Using OpenAlgo symbol: {final_symbol}")
            else:
                # Fallback to exchange symbol if OpenAlgo symbol isn't available
                final_symbol = exchange_symbol
                logger.info(f"Fallback to exchange symbol: {final_symbol}")

            # Create mapped position - without tradingsymbol field as requested
            mapped_position = {
                "symbol": final_symbol,  # Use final symbol (OpenAlgo or fallback)
                "exchange": exchange,
                "product": product,
                "quantity": int(position.get("netQty", 0)),
                "average_price": str(round(float(position.get("netAvgPrice", 0.0)), 2)),
                "pnl": position.get("realizedPnl", 0.0),
                "day_quantity": position.get("dayPos", {}).get("dayQty", 0),
                "day_average": position.get("dayPos", {}).get("dayAvg", 0.0),
                "day_pnl": position.get("dayPos", {}).get("dayRealizedPnl", 0.0),
            }

            mapped_positions.append(mapped_position)

        except Exception as e:
            logger.error(f"Error mapping position: {e}", exc_info=True)

    return mapped_positions


def transform_positions_data(positions_data):
    """
    Transform mapped position data to OpenAlgo format.
    DEPRECATED: This function is kept for backward compatibility only.
    Position transformation is now done directly in get_positions function.
    """
    logger.warning(
        "transform_positions_data is deprecated - transformation is now done directly in get_positions"
    )

    # Handle already processed data with status and data fields
    if isinstance(positions_data, dict):
        if positions_data.get("status") == "success" and "data" in positions_data:
            return positions_data.get("data", [])

    # Check if this is an empty or invalid list
    if not positions_data or not isinstance(positions_data, list):
        logger.warning("No valid positions data to transform")
        return []

    transformed_data = []

    for position in positions_data:
        try:
            # Check if position data is already in expected format
            if all(
                k in position
                for k in ("symbol", "exchange", "product", "quantity", "average_price")
            ):
                # Already transformed, just add to list
                transformed_data.append(position)
                continue

            # Convert quantity to int and skip zero positions
            quantity = int(position.get("quantity", 0))
            if quantity == 0:
                continue

            # Create transformed position with required fields
            transformed_position = {
                "symbol": position.get("symbol", ""),
                "exchange": position.get("exchange", "NSE"),
                "product": position.get("product", "MIS"),
                "quantity": quantity,
                "average_price": str(round(float(position.get("average_price", 0.0)), 2)),
            }

            transformed_data.append(transformed_position)

        except Exception as e:
            logger.error(f"Error transforming position: {e}", exc_info=True)

    return transformed_data


def _holding_values(holding):
    """
    Derive (quantity, avg_price, ltp, realized_pnl) from one Tradejini holding.

    The holdings response has no last-traded price, so the average buy price is
    used as the valuation price unless the symbol object happens to carry one.
    """
    sym = holding.get("sym", {}) or {}
    quantity = float(holding.get("qty", holding.get("saleableQty", 0)) or 0)
    avg_price = float(holding.get("avgPrice", 0) or 0)
    ltp = float(_first(sym, ("lastPrice", "ltp"), avg_price) or avg_price)
    realized_pnl = float(holding.get("realizedPnl", 0) or 0)
    return quantity, avg_price, ltp, realized_pnl


def map_portfolio_data(portfolio_data):
    """
    Normalises the holdings list returned by GET /api/oms/holdings.

    get_holdings() already unwraps the envelope and returns the 'd.holdings'
    array, so this only has to drop anything that is not a usable record.
    """
    if not isinstance(portfolio_data, list):
        logger.warning("Portfolio data is not a list.")
        return []

    # Handle empty list gracefully - it's not an error
    if len(portfolio_data) == 0:
        logger.debug("No portfolio data available (empty list)")
        return []

    return [holding for holding in portfolio_data if isinstance(holding, dict)]


def calculate_portfolio_statistics(holdings_data):
    """
    Aggregate holdings into the totals OpenAlgo shows above the holdings table.
    """
    totalholdingvalue = 0.0
    totalinvvalue = 0.0
    totalprofitandloss = 0.0
    totalpnlpercentage = 0.0

    if not isinstance(holdings_data, list) or not holdings_data:
        if not isinstance(holdings_data, list):
            logger.error("Error: Holdings data is not a list.")
        else:
            logger.debug("No holdings to calculate statistics for (empty list)")
        return {
            "totalholdingvalue": totalholdingvalue,
            "totalinvvalue": totalinvvalue,
            "totalprofitandloss": totalprofitandloss,
            "totalpnlpercentage": totalpnlpercentage,
        }

    for holding in holdings_data:
        if not isinstance(holding, dict):
            continue

        try:
            quantity, avg_price, ltp, realized_pnl = _holding_values(holding)
        except (TypeError, ValueError) as e:
            logger.warning(f"Skipping holding with unparseable values: {e}")
            continue

        inv_value = quantity * avg_price
        holding_value = quantity * ltp

        totalinvvalue += inv_value
        totalholdingvalue += holding_value
        totalprofitandloss += (holding_value - inv_value) + realized_pnl

    if totalinvvalue != 0:
        totalpnlpercentage = (totalprofitandloss / totalinvvalue) * 100

    return {
        "totalholdingvalue": round(totalholdingvalue, 2),
        "totalinvvalue": round(totalinvvalue, 2),
        "totalprofitandloss": round(totalprofitandloss, 2),
        "totalpnlpercentage": round(totalpnlpercentage, 2),
    }


def transform_holdings_data(holdings_data):
    """
    Transforms Tradejini holdings data to OpenAlgo format.

    Args:
        holdings_data (list): List of holdings dictionaries from TradeJini API

    Returns:
        dict: Holdings data in OpenAlgo format
        {
            "data": {
                "holdings": [
                    {
                        "exchange": "NSE",
                        "pnl": 3.27,
                        "pnlpercent": 13.04,
                        "product": "CNC",
                        "quantity": 1,
                        "symbol": "BSLNIFTY"
                    }
                ],
                "statistics": {
                    "totalholdingvalue": 36.46,
                    "totalinvvalue": 32.17,
                    "totalpnlpercentage": 13.34,
                    "totalprofitandloss": 4.29
                }
            },
            "status": "success"
        }
    """
    try:
        # Handle empty list case gracefully - it's not an error
        if isinstance(holdings_data, list) and len(holdings_data) == 0:
            logger.debug("No holdings to transform (empty list)")
            # Return empty list for service layer
            return []

        logger.debug(
            f"Transforming {len(holdings_data) if isinstance(holdings_data, list) else 0} holdings records"
        )

        # Initialize statistics
        statistics = {
            "totalholdingvalue": 0.0,
            "totalinvvalue": 0.0,
            "totalprofitandloss": 0.0,
            "totalpnlpercentage": 0.0,
        }

        # Transform individual holdings
        transformed_holdings = []

        if not isinstance(holdings_data, list):
            logger.error("Holdings data is not a list")
            # Return empty list for consistency
            return []

        for holding in holdings_data:
            try:
                if not isinstance(holding, dict):
                    logger.warning("Non-dict item in holdings list")
                    continue

                # Get symbol details from the sym object
                sym = holding.get("sym", {}) or {}

                # Skip if we don't have basic required data
                trade_symbol = sym_trading_symbol(sym) or sym_base_symbol(sym)
                exchange = sym_exchange(sym)
                if not sym or not trade_symbol:
                    logger.warning(f"Missing symbol data in holding: {holding}")
                    continue

                # Resolve to the OpenAlgo symbol so holdings line up with the
                # rest of the platform; fall back to the broker symbol.
                try:
                    openalgo_symbol = get_oa_symbol(
                        sym_id(sym) or holding.get("symId", ""), exchange
                    )
                except Exception as e:
                    logger.warning(f"Holdings symbol lookup failed: {str(e)}")
                    openalgo_symbol = None

                # 'qty' is the holding quantity ('saleableQty' excludes T1 stock);
                # the response carries no LTP, so avgPrice is the fallback price.
                quantity, avg_price, ltp, realized_pnl = _holding_values(holding)
                pnl_percent = 0.0

                # Calculate investment value and current value
                investment_value = quantity * avg_price
                current_value = quantity * ltp if ltp > 0 else investment_value

                # Keep this in step with calculate_portfolio_statistics()
                pnl = (current_value - investment_value) + realized_pnl

                # Calculate P&L percentage
                if investment_value > 0:
                    pnl_percent = (pnl / investment_value) * 100

                # Map product type (CNC for delivery, MIS for intraday)
                product = "CNC"  # Default to CNC (delivery)
                if holding.get("product", "").upper() in ["MIS", "INTRADAY"]:
                    product = "MIS"

                # Create the transformed holding
                transformed_holding = {
                    "exchange": exchange or "NSE",  # Default to NSE if not specified
                    "pnl": round(pnl, 2),
                    "pnlpercent": round(pnl_percent, 2),
                    "product": product,
                    "quantity": int(quantity),
                    "symbol": (openalgo_symbol or trade_symbol).strip(),
                    # Additional fields that might be useful
                    "avgprice": round(avg_price, 2),
                    "ltp": round(ltp, 2),
                    "investment": round(investment_value, 2),
                    "current_value": round(current_value, 2),
                }

                # Update statistics
                statistics["totalholdingvalue"] += current_value
                statistics["totalinvvalue"] += investment_value
                statistics["totalprofitandloss"] += current_value - investment_value

                transformed_holdings.append(transformed_holding)

            except Exception as e:
                logger.error(
                    f"Error transforming holding: {str(e)}\nHolding data: {holding}", exc_info=True
                )
                continue

        # Calculate final statistics
        if statistics["totalinvvalue"] > 0:
            statistics["totalpnlpercentage"] = (
                statistics["totalprofitandloss"] / statistics["totalinvvalue"]
            ) * 100

        # Round all statistics to 2 decimal places
        for key in statistics:
            statistics[key] = round(statistics[key], 2)

        # Return just the holdings list - service layer handles statistics separately
        return transformed_holdings

    except Exception as e:
        logger.error(f"Error in transform_holdings_data: {str(e)}", exc_info=True)
        # Return empty list on error for consistency
        return []
