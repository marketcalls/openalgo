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
                # Check if it's our emulated SL-M (Limit price == Trigger price)
                # Need to read prices first to compare
                op_paise = order.get("order_price", 0)
                tp_paise = order.get("trigger_price", 0)
                if not tp_paise:
                    ap = order.get("algo_params") or {}
                    tp_paise = ap.get("trigger_price", 0)
                
                if op_paise > 0 and op_paise == tp_paise:
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
        # Fallback: Nubra returns trigger_price inside algo_params for stoploss orders
        if not trigger_price_paise:
            algo_params = order.get("algo_params") or {}
            trigger_price_paise = algo_params.get("trigger_price", 0)
        
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
    Map Nubra's orders response to tradebook format.
    
    Nubra doesn't have a separate tradebook API. This function takes the
    orders response (from /orders/v2) and filters for filled orders,
    mapping them to the normalized tradebook format.
    
    Nubra returns orders as a direct list (not wrapped in {"data": [...]}).
    Prices are in paise (÷100 for rupees).
    """
    # Handle Nubra's response format — direct list or dict with various shapes
    if isinstance(trade_data, dict):
        if "data" in trade_data and trade_data.get("data") is not None:
            orders = trade_data["data"]
        elif trade_data.get("status") == False or trade_data.get("error"):
            logger.info(f"No trade data available or error: {trade_data}")
            return []
        else:
            logger.info("No trade data available.")
            return []
    elif isinstance(trade_data, list):
        orders = trade_data
    else:
        logger.info("Unexpected trade_data format.")
        return []

    if not orders:
        return []

    # Filter for filled/completed orders only (these are the "trades")
    filled_orders = [
        order for order in orders
        if order.get("order_status") in ["ORDER_STATUS_FILLED", "ORDER_STATUS_PARTIALLY_FILLED"]
    ]

    normalized_trades = []
    for order in filled_orders:
        ref_data = order.get("ref_data", {})
        exchange = ref_data.get("exchange", "")
        symboltoken = str(ref_data.get("token", order.get("ref_id", "")))

        # Get OpenAlgo symbol
        symbol_from_db = get_symbol(symboltoken, exchange)
        tradingsymbol = symbol_from_db if symbol_from_db else order.get("display_name", ref_data.get("stock_name", ""))

        # Map transaction type
        order_side = order.get("order_side", "")
        if order_side == "ORDER_SIDE_BUY":
            transaction_type = "BUY"
        elif order_side == "ORDER_SIDE_SELL":
            transaction_type = "SELL"
        else:
            transaction_type = order_side.replace("ORDER_SIDE_", "") if order_side else ""

        # Map product type
        delivery_type = order.get("order_delivery_type", "")
        product_map = {
            "ORDER_DELIVERY_TYPE_CNC": "CNC",
            "ORDER_DELIVERY_TYPE_IDAY": "MIS",
            "ORDER_DELIVERY_TYPE_INTRADAY": "MIS",
            "ORDER_DELIVERY_TYPE_MARGIN": "NRML",
            "ORDER_DELIVERY_TYPE_NRML": "NRML",
        }
        producttype = product_map.get(delivery_type, delivery_type.replace("ORDER_DELIVERY_TYPE_", "") if delivery_type else "")

        # Convert prices from paise to rupees
        avg_filled_price = (order.get("avg_filled_price", 0) or 0) / 100
        filled_qty = order.get("filled_qty", 0) or 0
        trade_value = round(avg_filled_price * filled_qty, 2)

        # Get fill time from order_time (nanosecond timestamp)
        filltime = ""
        order_time = order.get("order_time")
        if order_time:
            try:
                from datetime import datetime
                ts_seconds = order_time / 1_000_000_000
                dt = datetime.fromtimestamp(ts_seconds)
                filltime = dt.strftime("%Y-%m-%d %H:%M:%S")
            except (ValueError, OSError):
                filltime = str(order_time)

        normalized_trade = {
            "tradingsymbol": tradingsymbol,
            "exchange": exchange,
            "producttype": producttype,
            "transactiontype": transaction_type,
            "quantity": filled_qty,
            "fillprice": round(avg_filled_price, 2),
            "tradevalue": trade_value,
            "orderid": str(order.get("order_id", "")),
            "filltime": filltime,
        }
        normalized_trades.append(normalized_trade)

    return normalized_trades


def transform_tradebook_data(tradebook_data):
    """
    Transform normalized trade data to final OpenAlgo UI format.
    """
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
    """
    Transform mapped Nubra holdings data to final OpenAlgo UI format.

    Expects the output of map_portfolio_data():
        {"holdings": [...mapped...], "holding_stats": {...}}

    Returns a list of dicts with: symbol, exchange, quantity, product, pnl, pnlpercent.
    """
    transformed_data = []

    holdings_list = holdings_data.get("holdings", []) if isinstance(holdings_data, dict) else []

    for holding in holdings_list:
        transformed_position = {
            "symbol": holding.get("tradingsymbol", ""),
            "exchange": holding.get("exchange", ""),
            "quantity": holding.get("quantity", 0),
            "product": holding.get("product", ""),
            "average_price": holding.get("average_price", 0.0),
            "ltp": holding.get("ltp", 0.0),
            "pnl": holding.get("pnl", 0.0),
            "pnlpercent": holding.get("pnlpercent", 0.0),
            "invested_value": holding.get("invested_value", 0.0),
            "current_value": holding.get("current_value", 0.0),
            "day_pnl": holding.get("day_pnl", 0.0),
            "day_pnl_chg": holding.get("day_pnl_chg", 0.0),
            "ltp_chg": holding.get("ltp_chg", 0.0),
            "ref_id": holding.get("ref_id", ""),
        }
        transformed_data.append(transformed_position)
    return transformed_data


def map_portfolio_data(portfolio_data):
    """
    Map Nubra's holdings response to a normalized internal format.

    Nubra API returns:
        {
            "message": "holdings",
            "portfolio": {
                "client_code": "...",
                "holding_stats": { invested_amount, current_value, total_pnl, ... },
                "holdings": [ { ref_id, symbol, exchange, qty, avg_price, ltp, net_pnl, ... } ]
            }
        }

    Prices are in paise — this function converts them to rupees (÷100).
    Symbols are mapped to OpenAlgo format via get_oa_symbol().

    Returns:
        {"holdings": [...normalized...], "holding_stats": {...converted...}}
    """
    # Extract 'portfolio' from the Nubra response
    portfolio = None
    if isinstance(portfolio_data, dict):
        portfolio = portfolio_data.get("portfolio")

    if not portfolio or "holdings" not in portfolio:
        logger.info("Nubra Holdings - No portfolio data available.")
        return {"holdings": [], "holding_stats": {}}

    raw_holdings = portfolio.get("holdings") or []
    raw_stats = portfolio.get("holding_stats") or {}

    logger.info(f"Nubra holdings: {len(raw_holdings)} items, stats keys: {list(raw_stats.keys())}")
    logger.info(f"Nubra Raw Holdings Data: {raw_holdings}")

    mapped_holdings = []
    for h in raw_holdings:
        exchange = h.get("exchange", "NSE")
        broker_symbol = h.get("symbol", h.get("displayName", ""))
        ref_id = str(h.get("ref_id", ""))

        # Look up OpenAlgo symbol from database using ref_id or broker symbol
        oa_symbol = get_oa_symbol(broker_symbol, exchange)
        tradingsymbol = oa_symbol if oa_symbol else broker_symbol

        # Convert paise → rupees for price fields
        avg_price = (h.get("avg_price", 0) or 0) / 100
        ltp = (h.get("ltp", 0) or 0) / 100
        prev_close = (h.get("prev_close", 0) or 0) / 100
        invested_value = (h.get("invested_value", 0) or 0) / 100
        current_value = (h.get("current_value", 0) or 0) / 100
        net_pnl = (h.get("net_pnl", 0) or 0) / 100
        day_pnl = (h.get("day_pnl", 0) or 0) / 100

        mapped_holdings.append({
            "tradingsymbol": tradingsymbol,
            "exchange": exchange,
            "quantity": h.get("qty", 0),
            "product": "CNC",  # Holdings are always delivery
            "average_price": round(avg_price, 2),
            "ltp": round(ltp, 2),
            "prev_close": round(prev_close, 2),
            "invested_value": round(invested_value, 2),
            "current_value": round(current_value, 2),
            "pnl": round(net_pnl, 2),
            "pnlpercent": round(h.get("net_pnl_chg", 0) or 0, 2),
            "day_pnl": round(day_pnl, 2),
            "day_pnl_chg": round(h.get("day_pnl", 0) or 0, 2),  # percentage from API? No, use ltp_chg
            "ltp_chg": round(h.get("ltp_chg", 0) or 0, 2),
            "ref_id": ref_id,
        })

    # Convert holding_stats paise → rupees
    mapped_stats = {
        "invested_amount": round((raw_stats.get("invested_amount", 0) or 0) / 100, 2),
        "current_value": round((raw_stats.get("current_value", 0) or 0) / 100, 2),
        "total_pnl": round((raw_stats.get("total_pnl", 0) or 0) / 100, 2),
        "total_pnl_chg": round(raw_stats.get("total_pnl_chg", 0) or 0, 2),
        "day_pnl": round((raw_stats.get("day_pnl", 0) or 0) / 100, 2),
        "day_pnl_chg": round(raw_stats.get("day_pnl_chg", 0) or 0, 2),
    }

    return {"holdings": mapped_holdings, "holding_stats": mapped_stats}


def calculate_portfolio_statistics(holdings_data):
    """
    Calculate portfolio statistics from Nubra's mapped holdings data.

    Reads from the 'holding_stats' key (already converted to rupees by map_portfolio_data).

    Returns dict with: totalholdingvalue, totalinvvalue, totalprofitandloss, totalpnlpercentage.
    """
    stats = holdings_data.get("holding_stats") if isinstance(holdings_data, dict) else None

    if not stats:
        return {
            "totalholdingvalue": 0,
            "totalinvvalue": 0,
            "totalprofitandloss": 0,
            "totalpnlpercentage": 0,
        }

    return {
        "totalholdingvalue": stats.get("current_value", 0),
        "totalinvvalue": stats.get("invested_amount", 0),
        "totalprofitandloss": stats.get("total_pnl", 0),
        "totalpnlpercentage": stats.get("total_pnl_chg", 0),
    }
