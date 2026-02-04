import json

from database.token_db import get_oa_symbol, get_symbol
from utils.logging import get_logger

logger = get_logger(__name__)


def map_order_data(order_data):
    """
    Processes and modifies a list of order dictionaries from Nubra API.
    
    Nubra API returns orders as a direct list with fields like:
    - order_id, order_side, order_status, order_type, order_price, order_qty
    - ref_data containing: token, stock_name, exchange, etc.
    
    Parameters:
    - order_data: Response from Nubra API (list of orders or dict with status).

    Returns:
    - The modified order_data normalized to OpenAlgo format.
    """
    # Nubra API returns a direct list of orders, not wrapped in {status: bool, data: [...]}
    # Handle both cases for compatibility
    if isinstance(order_data, dict):
        if "data" in order_data and order_data.get("data") is not None:
            orders = order_data["data"]
        elif order_data.get("status") == False or order_data.get("error"):
            logger.info(f"No data available or error in response: {order_data}")
            return []
        else:
            # Might be an empty dict or unexpected format
            logger.info("No data available.")
            return []
    elif isinstance(order_data, list):
        orders = order_data
    else:
        logger.info("Unexpected order_data format.")
        return []

    if not orders:
        return []

    normalized_orders = []
    for order in orders:
        # Get ref_data for symbol information
        ref_data = order.get("ref_data", {})
        
        # Map Nubra fields to OpenAlgo/Angel-like format
        # Nubra: order_side -> transactiontype (BUY/SELL)
        order_side = order.get("order_side", "")
        if order_side == "ORDER_SIDE_BUY":
            transaction_type = "BUY"
        elif order_side == "ORDER_SIDE_SELL":
            transaction_type = "SELL"
        else:
            transaction_type = order_side.replace("ORDER_SIDE_", "") if order_side else ""

        # Nubra: order_status -> status (complete/open/rejected)
        order_status = order.get("order_status", "")
        status_map = {
            "ORDER_STATUS_FILLED": "complete",
            "ORDER_STATUS_OPEN": "open",
            "ORDER_STATUS_PENDING": "open",
            "ORDER_STATUS_REJECTED": "rejected",
            "ORDER_STATUS_CANCELLED": "cancelled",
            "ORDER_STATUS_PARTIALLY_FILLED": "open",
        }
        status = status_map.get(order_status, order_status.replace("ORDER_STATUS_", "").lower() if order_status else "")

        # Nubra uses both order_type and price_type:
        # - order_type: ORDER_TYPE_REGULAR, ORDER_TYPE_STOPLOSS, ORDER_TYPE_ICEBERG
        # - price_type: MARKET, LIMIT
        # For OpenAlgo we need: MARKET, LIMIT, SL, SL-M (uppercase like Angel)
        order_type = order.get("order_type", "")
        price_type = order.get("price_type", "")
        
        # Determine the ordertype based on Nubra's fields
        if order_type == "ORDER_TYPE_STOPLOSS":
            # Stoploss order - check price_type for SL vs SL-M
            if price_type == "MARKET":
                ordertype = "SL-M"
            else:
                ordertype = "SL"
        elif price_type == "MARKET":
            ordertype = "MARKET"
        elif price_type == "LIMIT":
            ordertype = "LIMIT"
        else:
            # Fallback: try to derive from price_type or default to MARKET
            ordertype = price_type.upper() if price_type else "MARKET"

        # Nubra: order_delivery_type -> producttype (CNC/MIS/NRML)
        delivery_type = order.get("order_delivery_type", "")
        product_map = {
            "ORDER_DELIVERY_TYPE_CNC": "CNC",
            "ORDER_DELIVERY_TYPE_IDAY": "MIS",
            "ORDER_DELIVERY_TYPE_INTRADAY": "MIS",
            "ORDER_DELIVERY_TYPE_MARGIN": "NRML",
            "ORDER_DELIVERY_TYPE_NRML": "NRML",
        }
        producttype = product_map.get(delivery_type, delivery_type.replace("ORDER_DELIVERY_TYPE_", "") if delivery_type else "")

        # Exchange from ref_data
        exchange = ref_data.get("exchange", "")
        
        # Symbol token from ref_data
        symboltoken = str(ref_data.get("token", order.get("ref_id", "")))
        
        # Get symbol from database using token
        symbol_from_db = get_symbol(symboltoken, exchange)
        tradingsymbol = symbol_from_db if symbol_from_db else order.get("display_name", ref_data.get("stock_name", ""))

        # Build normalized order object
        # Note: Nubra prices are in paise, convert to rupees (divide by 100)
        order_price_paise = order.get("order_price", 0)
        avg_price_paise = order.get("avg_filled_price", 0)
        trigger_price_paise = order.get("trigger_price", 0)
        
        normalized_order = {
            "orderid": str(order.get("order_id", "")),
            "exchange_order_id": str(order.get("exchange_order_id", "")),
            "tradingsymbol": tradingsymbol,
            "symboltoken": symboltoken,
            "exchange": exchange,
            "transactiontype": transaction_type,
            "producttype": producttype,
            "ordertype": ordertype,
            "quantity": order.get("order_qty", 0),
            "filledshares": order.get("filled_qty", 0),
            "averageprice": avg_price_paise / 100 if avg_price_paise else 0.0,
            "price": order_price_paise / 100 if order_price_paise else 0.0,
            "triggerprice": trigger_price_paise / 100 if trigger_price_paise else 0.0,
            "status": status,
            "ordertag": order.get("tag", ""),
            "updatetime": "",  # Nubra doesn't provide formatted time directly
        }
        
        # Convert timestamps if available
        order_time = order.get("order_time")
        if order_time:
            try:
                # Nubra timestamp is in nanoseconds, convert to readable format
                from datetime import datetime
                ts_seconds = order_time / 1_000_000_000
                dt = datetime.fromtimestamp(ts_seconds)
                normalized_order["updatetime"] = dt.strftime("%Y-%m-%d %H:%M:%S")
            except (ValueError, OSError):
                normalized_order["updatetime"] = str(order_time)

        normalized_orders.append(normalized_order)

    return normalized_orders


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
            if order["transactiontype"] == "BUY":
                total_buy_orders += 1
            elif order["transactiontype"] == "SELL":
                total_sell_orders += 1

            # Count orders based on their status
            if order["status"] == "complete":
                total_completed_orders += 1
            elif order["status"] == "open":
                total_open_orders += 1
            elif order["status"] == "rejected":
                total_rejected_orders += 1

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

        ordertype = order.get("ordertype", "")
        if ordertype == "STOPLOSS_LIMIT":
            ordertype = "SL"
        if ordertype == "STOPLOSS_MARKET":
            ordertype = "SL-M"

        transformed_order = {
            "symbol": order.get("tradingsymbol", ""),
            "exchange": order.get("exchange", ""),
            "action": order.get("transactiontype", ""),
            "quantity": order.get("quantity", 0),
            "price": order.get("price", 0.0),
            "trigger_price": order.get("triggerprice", 0.0),
            "pricetype": ordertype,
            "product": order.get("producttype", ""),
            "orderid": order.get("orderid", ""),
            "order_status": order.get("status", ""),
            "timestamp": order.get("updatetime", ""),
        }

        transformed_orders.append(transformed_order)

    return transformed_orders


def map_trade_data(trade_data):
    """
    Processes and modifies a list of order dictionaries based on specific conditions.

    Parameters:
    - order_data: A list of dictionaries, where each dictionary represents an order.

    Returns:
    - The modified order_data with updated 'tradingsymbol' and 'product' fields.
    """
    # Check if 'data' is None
    if trade_data["data"] is None:
        # Handle the case where there is no data
        # For example, you might want to display a message to the user
        # or pass an empty list or dictionary to the template.
        logger.info("No data available.")
        trade_data = {}  # or set it to an empty list if it's supposed to be a list
    else:
        trade_data = trade_data["data"]

    if trade_data:
        for order in trade_data:
            # Extract the instrument_token and exchange for the current order
            symbol = order["tradingsymbol"]
            exchange = order["exchange"]

            # Use the get_symbol function to fetch the symbol from the database
            symbol_from_db = get_oa_symbol(symbol, exchange)

            # Check if a symbol was found; if so, update the trading_symbol in the current order
            if symbol_from_db:
                order["tradingsymbol"] = symbol_from_db
                if (order["exchange"] == "NSE" or order["exchange"] == "BSE") and order[
                    "producttype"
                ] == "DELIVERY":
                    order["producttype"] = "CNC"

                elif order["producttype"] == "INTRADAY":
                    order["producttype"] = "MIS"

                elif (
                    order["exchange"] in ["NFO", "MCX", "BFO", "CDS"]
                    and order["producttype"] == "CARRYFORWARD"
                ):
                    order["producttype"] = "NRML"
            else:
                logger.info(
                    f"Unable to find the symbol {symbol} and exchange {exchange}. Keeping original trading symbol."
                )

    return trade_data


def transform_tradebook_data(tradebook_data):
    transformed_data = []
    for trade in tradebook_data:
        transformed_trade = {
            "symbol": trade.get("tradingsymbol", ""),
            "exchange": trade.get("exchange", ""),
            "product": trade.get("producttype", ""),
            "action": trade.get("transactiontype", ""),
            "quantity": trade.get("quantity", 0),
            "average_price": trade.get("fillprice", 0.0),
            "trade_value": trade.get("tradevalue", 0),
            "orderid": trade.get("orderid", ""),
            "timestamp": trade.get("filltime", ""),
        }
        transformed_data.append(transformed_trade)
    return transformed_data


def map_position_data(position_data):
    """
    Map Nubra's positions response to OpenAlgo normalized format.
    
    Nubra returns positions in portfolio.stock_positions, portfolio.fut_positions, 
    portfolio.opt_positions arrays. Prices are in paise (divide by 100).
    
    Args:
        position_data: Raw response from Nubra's /portfolio/positions API
        
    Returns:
        List of normalized position dictionaries
    """
    logger.info(f"Nubra map_position_data input: {position_data}")
    
    # Handle error responses
    if isinstance(position_data, dict) and position_data.get("error"):
        logger.warning(f"Nubra positions error: {position_data}")
        return []
    
    # Handle empty response
    if not position_data:
        logger.info("No position data available.")
        return []
    
    positions = []
    
    # If position_data is a dict with 'portfolio' key (Nubra format)
    if isinstance(position_data, dict):
        portfolio = position_data.get("portfolio", position_data)
        
        # Collect positions from all position types
        stock_positions = portfolio.get("stock_positions") or []
        fut_positions = portfolio.get("fut_positions") or []
        opt_positions = portfolio.get("opt_positions") or []
        close_positions = portfolio.get("close_positions") or []
        
        # Build a dictionary to merge positions by unique key (symbol+exchange+product)
        # Open positions take priority over closed positions
        merged_positions = {}
        
        # First, add closed positions (they will be overwritten by open positions if exists)
        for pos in close_positions:
            symbol = pos.get("symbol", pos.get("display_name", ""))
            exchange = pos.get("exchange", "NSE")
            product = pos.get("product", "")
            key = f"{symbol}_{exchange}_{product}"
            
            # Mark as closed (qty=0)
            pos_copy = pos.copy()
            pos_copy["_is_closed"] = True
            merged_positions[key] = pos_copy
        
        # Then, add open positions (will overwrite closed if same symbol)
        for pos in stock_positions + fut_positions + opt_positions:
            symbol = pos.get("symbol", pos.get("display_name", ""))
            exchange = pos.get("exchange", "NSE")
            product = pos.get("product", "")
            key = f"{symbol}_{exchange}_{product}"
            
            pos_copy = pos.copy()
            pos_copy["_is_closed"] = False
            merged_positions[key] = pos_copy
        
        logger.info(f"Nubra merged_positions keys: {list(merged_positions.keys())}")
        logger.info(f"Nubra merged_positions count: {len(merged_positions)}")
        
        # Process merged positions
        for pos in merged_positions.values():
            # Nubra prices are in paise, convert to rupees
            # Note: PnL values are already in rupees, no conversion needed
            avg_price_paise = pos.get("avg_price", 0) or 0
            ltp_paise = pos.get("ltp", 0) or 0
            pnl_rupees = pos.get("pnl", 0) or 0  # Already in rupees
            
            # Map product type from Nubra format to OpenAlgo format
            product = pos.get("product", "")
            if product == "ORDER_DELIVERY_TYPE_CNC":
                producttype = "CNC"
            elif product == "ORDER_DELIVERY_TYPE_IDAY":
                producttype = "MIS"
            elif product == "ORDER_DELIVERY_TYPE_NRML":
                producttype = "NRML"
            else:
                producttype = product
            
            # Determine net quantity
            qty = pos.get("qty", 0) or 0
            order_side = pos.get("order_side", "BUY")
            is_closed = pos.get("_is_closed", False)
            
            # If position is closed only (not in open positions), show qty=0
            if is_closed or order_side == "C":
                netqty = 0
            elif order_side == "SELL":
                netqty = -qty
            else:  # BUY
                netqty = qty
            
            normalized_position = {
                "tradingsymbol": pos.get("symbol", pos.get("display_name", "")),
                "symboltoken": str(pos.get("ref_id", "")),
                "exchange": pos.get("exchange", "NSE"),
                "producttype": producttype,
                "netqty": netqty,
                "quantity": qty if not is_closed else 0,
                "avgnetprice": avg_price_paise / 100 if avg_price_paise else 0.0,
                "avgbuyprice": (pos.get("avg_buy_price", 0) or 0) / 100,
                "avgsellprice": (pos.get("avg_sell_price", 0) or 0) / 100,
                "ltp": ltp_paise / 100 if ltp_paise else 0.0,
                "pnl": pnl_rupees,  # Already in rupees
                "pnlpercentage": pos.get("pnl_chg", 0) or 0,
            }
            positions.append(normalized_position)
    
    elif isinstance(position_data, list):
        # If already a list, normalize each position
        for pos in position_data:
            avg_price_paise = pos.get("avg_price", pos.get("avgnetprice", 0)) or 0
            ltp_paise = pos.get("ltp", 0) or 0
            pnl_paise = pos.get("pnl", 0) or 0
            
            # Check if already in rupees (small value) or paise (large value)
            # If avg_price > 10000, likely paise
            if avg_price_paise > 10000:
                avg_price = avg_price_paise / 100
                ltp = ltp_paise / 100
                pnl = pnl_paise / 100
            else:
                avg_price = avg_price_paise
                ltp = ltp_paise
                pnl = pnl_paise
            
            normalized_position = {
                "tradingsymbol": pos.get("symbol", pos.get("tradingsymbol", "")),
                "symboltoken": str(pos.get("ref_id", pos.get("symboltoken", ""))),
                "exchange": pos.get("exchange", "NSE"),
                "producttype": pos.get("producttype", "MIS"),
                "netqty": pos.get("netqty", pos.get("qty", 0)),
                "quantity": pos.get("quantity", pos.get("qty", 0)),
                "avgnetprice": avg_price,
                "ltp": ltp,
                "pnl": pnl,
            }
            positions.append(normalized_position)
    
    logger.info(f"Nubra mapped positions: {len(positions)} positions")
    return positions


def transform_positions_data(positions_data):
    """
    Transform normalized position data to final UI format.
    
    Args:
        positions_data: List of normalized position dictionaries from map_position_data
        
    Returns:
        List of transformed position dictionaries for UI display
    """
    transformed_data = []
    for position in positions_data:
        transformed_position = {
            "symbol": position.get("tradingsymbol", ""),
            "exchange": position.get("exchange", ""),
            "product": position.get("producttype", ""),
            "quantity": position.get("netqty", 0),
            "average_price": position.get("avgnetprice", 0.0),
            "ltp": position.get("ltp", 0.0),
            "pnl": position.get("pnl", 0.0),
        }
        transformed_data.append(transformed_position)
    return transformed_data


def transform_holdings_data(holdings_data):
    transformed_data = []
    for holdings in holdings_data["holdings"]:
        transformed_position = {
            "symbol": holdings.get("tradingsymbol", ""),
            "exchange": holdings.get("exchange", ""),
            "quantity": holdings.get("quantity", 0),
            "product": holdings.get("product", ""),
            "pnl": holdings.get("profitandloss", 0.0),
            "pnlpercent": holdings.get("pnlpercentage", 0.0),
        }
        transformed_data.append(transformed_position)
    return transformed_data


def map_portfolio_data(portfolio_data):
    """
    Processes and modifies a list of Portfolio dictionaries based on specific conditions and
    ensures both holdings and totalholding parts are transmitted in a single response.

    Parameters:
    - portfolio_data: A dictionary, where keys are 'holdings' and 'totalholding',
                      and values are lists/dictionaries representing the portfolio information.

    Returns:
    - The modified portfolio_data with 'product' fields changed for 'holdings' and 'totalholding' included.
    """
    # Check if 'data' is None or doesn't contain 'holdings'
    if portfolio_data.get("data") is None or "holdings" not in portfolio_data["data"]:
        logger.info("No data available.")
        # Return an empty structure or handle this scenario as needed
        return {}

    # Directly work with 'data' for clarity and simplicity
    data = portfolio_data["data"]

    # Modify 'product' field for each holding if applicable
    if data.get("holdings"):
        for portfolio in data["holdings"]:
            symbol = portfolio["tradingsymbol"]
            exchange = portfolio["exchange"]
            symbol_from_db = get_oa_symbol(symbol, exchange)

            # Check if a symbol was found; if so, update the trading_symbol in the current order
            if symbol_from_db:
                portfolio["tradingsymbol"] = symbol_from_db
            if portfolio["product"] == "DELIVERY":
                portfolio["product"] = "CNC"  # Modify 'product' field
            else:
                logger.info("AngelOne Portfolio - Product Value for Delivery Not Found or Changed.")

    # The function already works with 'data', which includes 'holdings' and 'totalholding',
    # so we can return 'data' directly without additional modifications.
    return data


def calculate_portfolio_statistics(holdings_data):
    if holdings_data["totalholding"] is None:
        totalholdingvalue = 0
        totalinvvalue = 0
        totalprofitandloss = 0
        totalpnlpercentage = 0
    else:
        totalholdingvalue = holdings_data["totalholding"]["totalholdingvalue"]
        totalinvvalue = holdings_data["totalholding"]["totalinvvalue"]
        totalprofitandloss = holdings_data["totalholding"]["totalprofitandloss"]

        # To avoid division by zero in the case when total_investment_value is 0
        totalpnlpercentage = holdings_data["totalholding"]["totalpnlpercentage"]

    return {
        "totalholdingvalue": totalholdingvalue,
        "totalinvvalue": totalinvvalue,
        "totalprofitandloss": totalprofitandloss,
        "totalpnlpercentage": totalpnlpercentage,
    }
