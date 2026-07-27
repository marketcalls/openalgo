import json
import sys
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import FastMCP
from openalgo import api

# Get API key and host from command line arguments
if len(sys.argv) < 3:
    raise ValueError("API key and host must be provided as command line arguments")

api_key = sys.argv[1]
host = sys.argv[2]

# Initialize OpenAlgo client with provided arguments
client = api(api_key=api_key, host=host)

# Create MCP server
mcp = FastMCP("openalgo")

# ORDER MANAGEMENT TOOLS


@mcp.tool()
def place_order(
    symbol: str,
    quantity: int,
    action: str,
    exchange: str = "NSE",
    price_type: str = "MARKET",
    product: str = "MIS",
    strategy: str = "Python",
    price: float | None = None,
    trigger_price: float | None = None,
    disclosed_quantity: int | None = None,
) -> str:
    """
    Place a new order (market or limit).

    Args:
        symbol: Stock symbol (e.g., 'RELIANCE')
        quantity: Number of shares
        action: 'BUY' or 'SELL'
        exchange: 'NSE', 'NFO', 'CDS', 'BSE', 'BFO', 'BCD', 'MCX', 'NCDEX'
        price_type: 'MARKET', 'LIMIT', 'SL', 'SL-M'
        product: 'CNC', 'NRML', 'MIS'
        strategy: Strategy name
        price: Limit price (required for LIMIT orders)
        trigger_price: Trigger price (for stop loss orders)
        disclosed_quantity: Disclosed quantity
    """
    try:
        params = {
            "strategy": strategy,
            "symbol": symbol.upper(),
            "action": action.upper(),
            "exchange": exchange.upper(),
            "price_type": price_type.upper(),
            "product": product.upper(),
            "quantity": quantity,
        }

        if price is not None:
            params["price"] = price
        if trigger_price is not None:
            params["trigger_price"] = trigger_price
        if disclosed_quantity is not None:
            params["disclosed_quantity"] = disclosed_quantity

        response = client.placeorder(**params)
        return json.dumps(response, indent=2)
    except Exception as e:
        return f"Error placing order: {str(e)}"


@mcp.tool()
def place_smart_order(
    symbol: str,
    quantity: int,
    action: str,
    position_size: int,
    exchange: str = "NSE",
    price_type: str = "MARKET",
    product: str = "MIS",
    strategy: str = "Python",
    price: float | None = None,
) -> str:
    """
    Place a smart order considering current position size.

    Args:
        symbol: Stock symbol
        quantity: Number of shares
        action: 'BUY' or 'SELL'
        position_size: Current position size
        exchange: Exchange name
        price_type: Order type
        product: Product type
        strategy: Strategy name
        price: Limit price (optional)
    """
    try:
        params = {
            "strategy": strategy,
            "symbol": symbol.upper(),
            "action": action.upper(),
            "exchange": exchange.upper(),
            "price_type": price_type.upper(),
            "product": product.upper(),
            "quantity": quantity,
            "position_size": position_size,
        }

        if price is not None:
            params["price"] = price

        response = client.placesmartorder(**params)
        return json.dumps(response, indent=2)
    except Exception as e:
        return f"Error placing smart order: {str(e)}"


@mcp.tool()
def place_basket_order(orders: list[dict[str, Any]], strategy: str = "Python") -> str:
    """
    Place multiple orders in a basket.

    Args:
        orders: List of order dictionaries. Each order should contain:
            - symbol (str): Trading symbol. Required.
            - exchange (str): Exchange code. Required.
            - action (str): BUY or SELL. Required.
            - quantity (int/str): Quantity to trade. Required.
            - pricetype (str): MARKET, LIMIT, SL, SL-M. Optional, defaults to MARKET.
            - product (str): MIS, CNC, NRML. Optional, defaults to MIS.
            - price (str): Required for LIMIT orders.
            - trigger_price (str): Required for SL orders.
        strategy: Strategy name (default: Python)

        Example: [
            {"symbol": "BHEL", "exchange": "NSE", "action": "BUY", "quantity": 1, "pricetype": "MARKET", "product": "MIS"},
            {"symbol": "ZOMATO", "exchange": "NSE", "action": "SELL", "quantity": 1, "pricetype": "MARKET", "product": "MIS"}
        ]

    Returns:
        JSON with results for each order including orderid, status, and symbol
    """
    try:
        response = client.basketorder(strategy=strategy, orders=orders)
        return json.dumps(response, indent=2)
    except Exception as e:
        return f"Error placing basket order: {str(e)}"


@mcp.tool()
def place_split_order(
    symbol: str,
    quantity: int,
    split_size: int,
    action: str,
    exchange: str = "NSE",
    price_type: str = "MARKET",
    product: str = "MIS",
    strategy: str = "Python",
    price: float | None = None,
    trigger_price: float | None = None,
    disclosed_quantity: int | None = None,
) -> str:
    """
    Place a large order split into smaller chunks.

    Args:
        symbol: Stock symbol (e.g., 'YESBANK')
        quantity: Total quantity to trade
        split_size: Size of each split order
        action: 'BUY' or 'SELL'
        exchange: Exchange name (default: NSE)
        price_type: 'MARKET', 'LIMIT', 'SL', 'SL-M' (default: MARKET)
        product: 'MIS', 'CNC', 'NRML' (default: MIS)
        strategy: Strategy name (default: Python)
        price: Limit price (required for LIMIT orders)
        trigger_price: Trigger price (required for SL orders)
        disclosed_quantity: Disclosed quantity (optional)

    Returns:
        JSON with results array containing each split order's orderid, quantity, and status

    Example:
        # Split 105 shares into orders of 20 each (5 orders of 20 + 1 order of 5)
        place_split_order("YESBANK", 105, 20, "SELL", "NSE")
    """
    try:
        params = {
            "strategy": strategy,
            "symbol": symbol.upper(),
            "exchange": exchange.upper(),
            "action": action.upper(),
            "quantity": quantity,
            "splitsize": split_size,
            "price_type": price_type.upper(),
            "product": product.upper(),
        }

        if price is not None:
            params["price"] = price
        if trigger_price is not None:
            params["trigger_price"] = trigger_price
        if disclosed_quantity is not None:
            params["disclosed_quantity"] = disclosed_quantity

        response = client.splitorder(**params)
        return json.dumps(response, indent=2)
    except Exception as e:
        return f"Error placing split order: {str(e)}"


@mcp.tool()
def place_options_order(
    underlying: str,
    exchange: str,
    offset: str,
    option_type: str,
    action: str,
    quantity: int,
    expiry_date: str | None = None,
    strategy: str = "Python",
    price_type: str = "MARKET",
    product: str = "MIS",
    price: float | None = None,
    trigger_price: float | None = None,
    disclosed_quantity: int | None = None,
) -> str:
    """
    Place an options order with ATM/ITM/OTM offset.

    Args:
        underlying: Underlying symbol (e.g., 'NIFTY', 'BANKNIFTY', 'NIFTY28OCT25FUT')
        exchange: Exchange for underlying ('NSE_INDEX', 'BSE_INDEX', 'NFO')
        offset: Strike offset - 'ATM', 'ITM1'-'ITM50', 'OTM1'-'OTM50'
        option_type: 'CE' for Call or 'PE' for Put
        action: 'BUY' or 'SELL'
        quantity: Number of lots (must be multiple of lot size)
        expiry_date: Expiry date in format 'DDMMMYY' (e.g., '28OCT25'). Optional if underlying includes expiry.
        strategy: Strategy name (default: Python)
        price_type: 'MARKET', 'LIMIT', 'SL', 'SL-M' (default: MARKET)
        product: 'MIS', 'NRML' (default: MIS). Note: CNC not supported for options.
        price: Limit price (required for LIMIT orders)
        trigger_price: Trigger price (required for SL and SL-M orders)
        disclosed_quantity: Disclosed quantity (optional)

    Returns:
        JSON with orderid, symbol, underlying_ltp, offset, option_type, mode

    Example:
        # Basic ATM call order
        place_options_order("NIFTY", "NSE_INDEX", "ATM", "CE", "BUY", 75, "28NOV25")

        # Using future as underlying (expiry auto-detected)
        place_options_order("NIFTY28OCT25FUT", "NFO", "ITM2", "CE", "BUY", 75)
    """
    try:
        params = {
            "strategy": strategy,
            "underlying": underlying.upper(),
            "exchange": exchange.upper(),
            "offset": offset.upper(),
            "option_type": option_type.upper(),
            "action": action.upper(),
            "quantity": quantity,
            "price_type": price_type.upper(),
            "product": product.upper(),
        }

        if expiry_date is not None:
            params["expiry_date"] = expiry_date
        if price is not None:
            params["price"] = price
        if trigger_price is not None:
            params["trigger_price"] = trigger_price
        if disclosed_quantity is not None:
            params["disclosed_quantity"] = disclosed_quantity

        response = client.optionsorder(**params)
        return json.dumps(response, indent=2)
    except Exception as e:
        return f"Error placing options order: {str(e)}"


@mcp.tool()
def place_options_multi_order(
    strategy: str,
    underlying: str,
    exchange: str,
    legs: list[dict[str, Any]],
    expiry_date: str | None = None,
) -> str:
    """
    Place a multi-leg options order (spreads, iron condor, straddles, etc.).
    BUY legs are executed first for margin efficiency, then SELL legs.

    Args:
        strategy: Strategy name (required)
        underlying: Underlying symbol (e.g., 'NIFTY', 'BANKNIFTY', 'NIFTY28OCT25FUT')
        exchange: Exchange for underlying ('NSE_INDEX', 'BSE_INDEX', 'NFO')
        legs: List of leg dictionaries (1-20 legs). Each leg must contain:
            Required:
            - offset: Strike offset ('ATM', 'ITM1'-'ITM50', 'OTM1'-'OTM50')
            - option_type: 'CE' for Call or 'PE' for Put
            - action: 'BUY' or 'SELL'
            - quantity: Number of lots (must be multiple of lot size)
            Optional:
            - expiry_date: Per-leg expiry in DDMMMYY format for diagonal/calendar spreads
            - pricetype: 'MARKET', 'LIMIT', 'SL', 'SL-M' (default: MARKET)
            - product: 'MIS', 'NRML' (default: MIS)
            - price: Limit price for LIMIT orders
            - trigger_price: Trigger price for SL orders
            - disclosed_quantity: Disclosed quantity
        expiry_date: Default expiry date in format 'DDMMMYY' (e.g., '25NOV25') for all legs

    Returns:
        JSON with underlying, underlying_ltp, mode, and results array containing each leg's
        orderid, symbol, offset, option_type, action, and status

    Example - Iron Condor (same expiry):
        [
            {"offset": "OTM10", "option_type": "CE", "action": "BUY", "quantity": 75},
            {"offset": "OTM10", "option_type": "PE", "action": "BUY", "quantity": 75},
            {"offset": "OTM5", "option_type": "CE", "action": "SELL", "quantity": 75},
            {"offset": "OTM5", "option_type": "PE", "action": "SELL", "quantity": 75}
        ]

    Example - Bull Call Spread with NRML:
        [
            {"offset": "ATM", "option_type": "CE", "action": "BUY", "quantity": 75, "product": "NRML"},
            {"offset": "OTM1", "option_type": "CE", "action": "SELL", "quantity": 75, "product": "NRML"}
        ]

    Example - Diagonal Spread (different expiry):
        [
            {"offset": "ITM2", "option_type": "CE", "action": "BUY", "quantity": 75, "expiry_date": "30DEC25"},
            {"offset": "OTM2", "option_type": "CE", "action": "SELL", "quantity": 75, "expiry_date": "25NOV25"}
        ]

    Example - Long Straddle with LIMIT orders:
        [
            {"offset": "ATM", "option_type": "CE", "action": "BUY", "quantity": 30, "pricetype": "LIMIT", "price": 250.0},
            {"offset": "ATM", "option_type": "PE", "action": "BUY", "quantity": 30, "pricetype": "LIMIT", "price": 250.0}
        ]
    """
    try:
        params = {
            "strategy": strategy,
            "underlying": underlying.upper(),
            "exchange": exchange.upper(),
            "legs": legs,
        }

        if expiry_date is not None:
            params["expiry_date"] = expiry_date

        response = client.optionsmultiorder(**params)
        return json.dumps(response, indent=2)
    except Exception as e:
        return f"Error placing options multi order: {str(e)}"


@mcp.tool()
def modify_order(
    order_id: str,
    strategy: str,
    symbol: str,
    action: str,
    exchange: str,
    price_type: str,
    product: str,
    quantity: int,
    price: float | None = None,
) -> str:
    """
    Modify an existing order.

    Args:
        order_id: Order ID to modify
        strategy: Strategy name
        symbol: Stock symbol
        action: 'BUY' or 'SELL'
        exchange: Exchange name
        price_type: Order type
        product: Product type
        quantity: New quantity
        price: New price (optional)
    """
    try:
        params = {
            "order_id": order_id,
            "strategy": strategy,
            "symbol": symbol.upper(),
            "action": action.upper(),
            "exchange": exchange.upper(),
            "price_type": price_type.upper(),
            "product": product.upper(),
            "quantity": quantity,
        }

        if price is not None:
            params["price"] = price

        response = client.modifyorder(**params)
        return json.dumps(response, indent=2)
    except Exception as e:
        return f"Error modifying order: {str(e)}"


@mcp.tool()
def cancel_order(order_id: str, strategy: str) -> str:
    """
    Cancel a specific order.

    Args:
        order_id: Order ID to cancel
        strategy: Strategy name
    """
    try:
        response = client.cancelorder(order_id=order_id, strategy=strategy)
        return json.dumps(response, indent=2)
    except Exception as e:
        return f"Error canceling order: {str(e)}"


@mcp.tool()
def cancel_all_orders(strategy: str) -> str:
    """
    Cancel all open orders for a strategy.

    Args:
        strategy: Strategy name
    """
    try:
        response = client.cancelallorder(strategy=strategy)
        return json.dumps(response, indent=2)
    except Exception as e:
        return f"Error canceling all orders: {str(e)}"


# POSITION MANAGEMENT TOOLS


@mcp.tool()
def close_all_positions(strategy: str) -> str:
    """
    Close all open positions for a strategy.

    Args:
        strategy: Strategy name
    """
    try:
        response = client.closeposition(strategy=strategy)
        return json.dumps(response, indent=2)
    except Exception as e:
        return f"Error closing positions: {str(e)}"


@mcp.tool()
def get_open_position(strategy: str, symbol: str, exchange: str, product: str) -> str:
    """
    Get current open position for a specific instrument.

    Args:
        strategy: Strategy name
        symbol: Stock symbol
        exchange: Exchange name
        product: Product type
    """
    try:
        response = client.openposition(
            strategy=strategy,
            symbol=symbol.upper(),
            exchange=exchange.upper(),
            product=product.upper(),
        )
        return json.dumps(response, indent=2)
    except Exception as e:
        return f"Error getting open position: {str(e)}"


# ORDER STATUS AND TRACKING TOOLS


@mcp.tool()
def get_order_status(order_id: str, strategy: str) -> str:
    """
    Get status of a specific order.

    Args:
        order_id: Order ID
        strategy: Strategy name
    """
    try:
        response = client.orderstatus(order_id=order_id, strategy=strategy)
        return json.dumps(response, indent=2)
    except Exception as e:
        return f"Error getting order status: {str(e)}"


@mcp.tool()
def get_order_book() -> str:
    """Get all orders from the order book."""
    try:
        response = client.orderbook()
        return json.dumps(response, indent=2)
    except Exception as e:
        return f"Error getting order book: {str(e)}"


@mcp.tool()
def get_trade_book() -> str:
    """Get all executed trades."""
    try:
        response = client.tradebook()
        return json.dumps(response, indent=2)
    except Exception as e:
        return f"Error getting trade book: {str(e)}"


@mcp.tool()
def get_position_book() -> str:
    """Get all current positions."""
    try:
        response = client.positionbook()
        return json.dumps(response, indent=2)
    except Exception as e:
        return f"Error getting position book: {str(e)}"


@mcp.tool()
def get_holdings() -> str:
    """Get all holdings (long-term investments)."""
    try:
        response = client.holdings()
        return json.dumps(response, indent=2)
    except Exception as e:
        return f"Error getting holdings: {str(e)}"


@mcp.tool()
def get_funds() -> str:
    """Get account funds and margin information."""
    try:
        response = client.funds()
        return json.dumps(response, indent=2)
    except Exception as e:
        return f"Error getting funds: {str(e)}"


@mcp.tool()
def calculate_margin(positions: list[dict[str, Any]]) -> str:
    """
    Calculate margin requirements for positions.

    Args:
        positions: List of position dictionaries
        Example: [{"symbol": "NIFTY25NOV2525000CE", "exchange": "NFO", "action": "BUY", "product": "NRML", "pricetype": "MARKET", "quantity": "75"}]

        For Futures: [{"symbol": "NIFTY25NOV25FUT", "exchange": "NFO", "action": "BUY", "product": "NRML", "pricetype": "MARKET", "quantity": "25"}]
        For Options: [{"symbol": "NIFTY25NOV2525500CE", "exchange": "NFO", "action": "BUY", "product": "NRML", "pricetype": "MARKET", "quantity": "75"}]

    Returns:
        JSON with total_margin_required, span_margin, and exposure_margin
    """
    try:
        response = client.margin(positions=positions)
        return json.dumps(response, indent=2)
    except Exception as e:
        return f"Error calculating margin: {str(e)}"


# MARKET DATA TOOLS


@mcp.tool()
def get_quote(symbol: str, exchange: str = "NSE") -> str:
    """
    Get current quote for a symbol.

    Args:
        symbol: Stock symbol
        exchange: Exchange name
    """
    try:
        response = client.quotes(symbol=symbol.upper(), exchange=exchange.upper())
        return json.dumps(response, indent=2)
    except Exception as e:
        return f"Error getting quote: {str(e)}"


@mcp.tool()
def get_multi_quotes(symbols: list[dict[str, str]]) -> str:
    """
    Get real-time quotes for multiple symbols in a single request.

    Args:
        symbols: List of symbol-exchange pairs
        Example: [{"symbol": "RELIANCE", "exchange": "NSE"}, {"symbol": "INFY", "exchange": "NSE"}]

    Returns:
        JSON with quotes for all requested symbols including ltp, bid, ask, open, high, low, volume, oi
    """
    try:
        # Normalize symbols to uppercase
        normalized_symbols = [
            {"symbol": s["symbol"].upper(), "exchange": s["exchange"].upper()} for s in symbols
        ]
        response = client.multiquotes(symbols=normalized_symbols)
        return json.dumps(response, indent=2)
    except Exception as e:
        return f"Error getting multi quotes: {str(e)}"


@mcp.tool()
def get_option_chain(
    underlying: str, exchange: str, expiry_date: str, strike_count: int | None = None
) -> str:
    """
    Get option chain data with real-time quotes for all strikes.

    Args:
        underlying: Underlying symbol (e.g., 'NIFTY', 'BANKNIFTY', 'RELIANCE')
        exchange: Exchange for underlying ('NSE_INDEX', 'BSE_INDEX', 'NSE', 'BSE')
        expiry_date: Expiry date in DDMMMYY format (e.g., '30DEC25')
        strike_count: Number of strikes above and below ATM (1-100). If not provided, returns entire chain.

    Returns:
        JSON with:
        - underlying: Base symbol
        - underlying_ltp: Current price of underlying
        - expiry_date: Expiry date
        - atm_strike: At-The-Money strike price
        - chain: Array of strikes with CE and PE data including:
            - symbol, label (ATM/ITM1/OTM1 etc.), ltp, bid, ask, open, high, low, volume, oi, lotsize

    Note: CE and PE have different labels at the same strike:
        - Strikes below ATM: CE is ITM, PE is OTM
        - Strikes above ATM: CE is OTM, PE is ITM

    Example for 10 strikes around ATM:
        get_option_chain("NIFTY", "NSE_INDEX", "30DEC25", 10)

    Example for full chain:
        get_option_chain("NIFTY", "NSE_INDEX", "30DEC25")
    """
    try:
        params = {
            "underlying": underlying.upper(),
            "exchange": exchange.upper(),
            "expiry_date": expiry_date.upper(),
        }

        if strike_count is not None:
            params["strike_count"] = strike_count

        response = client.optionchain(**params)
        return json.dumps(response, indent=2)
    except Exception as e:
        return f"Error getting option chain: {str(e)}"


@mcp.tool()
def get_market_depth(symbol: str, exchange: str = "NSE") -> str:
    """
    Get market depth (order book) for a symbol.

    Args:
        symbol: Stock symbol
        exchange: Exchange name
    """
    try:
        response = client.depth(symbol=symbol.upper(), exchange=exchange.upper())
        return json.dumps(response, indent=2)
    except Exception as e:
        return f"Error getting market depth: {str(e)}"


@mcp.tool()
def get_historical_data(
    symbol: str, exchange: str, interval: str, start_date: str, end_date: str
) -> str:
    """
    Get historical price data.

    Args:
        symbol: Stock symbol
        exchange: Exchange name
        interval: Time interval ('1m', '3m', '5m', '10m', '15m', '30m', '1h', 'D')
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
    """
    try:
        response = client.history(
            symbol=symbol.upper(),
            exchange=exchange.upper(),
            interval=interval,
            start_date=start_date,
            end_date=end_date,
        )
        return str(response)  # DataFrame converted to string
    except Exception as e:
        return f"Error getting historical data: {str(e)}"


# INSTRUMENT SEARCH AND INFO TOOLS


@mcp.tool()
def search_instruments(query: str, exchange: str = "NSE", instrument_type: str = None) -> str:
    """
    Search for instruments by name or symbol.

    Args:
        query: Search query
        exchange: Exchange to search in (NSE, BSE, NSE_INDEX, BSE_INDEX, etc.)
        instrument_type: Optional - 'INDEX' to search in index exchanges
    """
    try:
        # Handle index searches
        if instrument_type and instrument_type.upper() == "INDEX":
            if exchange.upper() == "NSE":
                exchange = "NSE_INDEX"
            elif exchange.upper() == "BSE":
                exchange = "BSE_INDEX"

        response = client.search(query=query, exchange=exchange.upper())
        return json.dumps(response, indent=2)
    except Exception as e:
        return f"Error searching instruments: {str(e)}"


@mcp.tool()
def get_symbol_info(symbol: str, exchange: str = "NSE", instrument_type: str = None) -> str:
    """
    Get detailed information about a symbol.

    Args:
        symbol: Stock symbol
        exchange: Exchange name
        instrument_type: Optional - 'INDEX' for index symbols
    """
    try:
        # Handle index symbols
        if instrument_type and instrument_type.upper() == "INDEX":
            if exchange.upper() == "NSE":
                exchange = "NSE_INDEX"
            elif exchange.upper() == "BSE":
                exchange = "BSE_INDEX"

        # Or check if symbol is a known index
        nse_indices = ["NIFTY", "NIFTYNXT50", "FINNIFTY", "BANKNIFTY", "MIDCPNIFTY", "INDIAVIX"]
        bse_indices = ["SENSEX", "BANKEX", "SENSEX50"]

        if symbol.upper() in nse_indices and exchange.upper() == "NSE":
            exchange = "NSE_INDEX"
        elif symbol.upper() in bse_indices and exchange.upper() == "BSE":
            exchange = "BSE_INDEX"

        response = client.symbol(symbol=symbol.upper(), exchange=exchange.upper())
        return json.dumps(response, indent=2)
    except Exception as e:
        return f"Error getting symbol info: {str(e)}"


@mcp.tool()
def get_index_symbols(exchange: str = "NSE") -> str:
    """
    Get common index symbols for NSE or BSE.

    Args:
        exchange: NSE or BSE

    Returns:
        List of common index symbols for the specified exchange
    """
    indices = {
        "NSE": {
            "exchange_code": "NSE_INDEX",
            "symbols": ["NIFTY", "NIFTYNXT50", "FINNIFTY", "BANKNIFTY", "MIDCPNIFTY", "INDIAVIX"],
        },
        "BSE": {"exchange_code": "BSE_INDEX", "symbols": ["SENSEX", "BANKEX", "SENSEX50"]},
    }

    exchange_upper = exchange.upper()
    if exchange_upper in indices:
        return json.dumps(
            {
                "exchange": exchange_upper,
                "exchange_code": indices[exchange_upper]["exchange_code"],
                "indices": indices[exchange_upper]["symbols"],
            },
            indent=2,
        )
    else:
        return json.dumps({"error": f"Unknown exchange: {exchange}. Use NSE or BSE."}, indent=2)


@mcp.tool()
def get_expiry_dates(symbol: str, exchange: str = "NFO", instrument_type: str = "options") -> str:
    """
    Get expiry dates for derivatives.

    Args:
        symbol: Underlying symbol
        exchange: Exchange name (typically NFO for F&O)
        instrument_type: 'options' or 'futures'
    """
    try:
        response = client.expiry(
            symbol=symbol.upper(), exchange=exchange.upper(), instrumenttype=instrument_type.lower()
        )
        return json.dumps(response, indent=2)
    except Exception as e:
        return f"Error getting expiry dates: {str(e)}"


@mcp.tool()
def get_available_intervals() -> str:
    """Get all available time intervals for historical data."""
    try:
        response = client.intervals()
        return json.dumps(response, indent=2)
    except Exception as e:
        return f"Error getting intervals: {str(e)}"


@mcp.tool()
def get_option_symbol(
    underlying: str, exchange: str, expiry_date: str, offset: str, option_type: str
) -> str:
    """
    Get option symbol for specific strike and expiry.

    Args:
        underlying: Underlying symbol (e.g., 'NIFTY', 'BANKNIFTY')
        exchange: Exchange for underlying ('NSE_INDEX', 'BSE_INDEX')
        expiry_date: Expiry date in format 'DDMMMYY' (e.g., '28OCT25')
        offset: Strike offset - 'ATM', 'ITM1'-'ITM10', 'OTM1'-'OTM10'
        option_type: 'CE' for Call or 'PE' for Put

    Returns:
        JSON with symbol, exchange, lotsize, tick_size, underlying_ltp
    """
    try:
        response = client.optionsymbol(
            underlying=underlying.upper(),
            exchange=exchange.upper(),
            expiry_date=expiry_date,
            offset=offset.upper(),
            option_type=option_type.upper(),
        )
        return json.dumps(response, indent=2)
    except Exception as e:
        return f"Error getting option symbol: {str(e)}"


@mcp.tool()
def get_synthetic_future(underlying: str, exchange: str, expiry_date: str) -> str:
    """
    Calculate synthetic future price using put-call parity.

    Args:
        underlying: Underlying symbol (e.g., 'NIFTY', 'BANKNIFTY')
        exchange: Exchange for underlying ('NSE_INDEX', 'BSE_INDEX')
        expiry_date: Expiry date in format 'DDMMMYY' (e.g., '25NOV25')

    Returns:
        JSON with atm_strike, expiry, status, synthetic_future_price, underlying, underlying_ltp
    """
    try:
        response = client.syntheticfuture(
            underlying=underlying.upper(), exchange=exchange.upper(), expiry_date=expiry_date
        )
        return json.dumps(response, indent=2)
    except Exception as e:
        return f"Error calculating synthetic future: {str(e)}"


@mcp.tool()
def get_option_greeks(
    symbol: str,
    exchange: str,
    underlying_symbol: str,
    underlying_exchange: str,
    interest_rate: float = 0.0,
) -> str:
    """
    Calculate option Greeks (delta, gamma, theta, vega, rho).

    Args:
        symbol: Option symbol (e.g., 'NIFTY25NOV2526000CE')
        exchange: Exchange name (typically 'NFO')
        underlying_symbol: Underlying symbol (e.g., 'NIFTY')
        underlying_exchange: Underlying exchange ('NSE_INDEX')
        interest_rate: Risk-free interest rate (default: 0.0)

    Returns:
        JSON with Greeks, IV, spot price, strike, days to expiry
    """
    try:
        response = client.optiongreeks(
            symbol=symbol.upper(),
            exchange=exchange.upper(),
            interest_rate=interest_rate,
            underlying_symbol=underlying_symbol.upper(),
            underlying_exchange=underlying_exchange.upper(),
        )
        return json.dumps(response, indent=2)
    except Exception as e:
        return f"Error calculating option greeks: {str(e)}"


# UTILITY TOOLS


@mcp.tool()
def get_openalgo_version() -> str:
    """Get the OpenAlgo library version."""
    try:
        import openalgo

        return f"OpenAlgo version: {openalgo.__version__}"
    except Exception as e:
        return f"Error getting version: {str(e)}"


@mcp.tool()
def validate_order_constants() -> str:
    """Display all valid order constants for reference."""
    constants = {
        "exchanges": {
            "NSE": "NSE Equity",
            "NFO": "NSE Futures & Options",
            "CDS": "NSE Currency",
            "BSE": "BSE Equity",
            "BFO": "BSE Futures & Options",
            "BCD": "BSE Currency",
            "MCX": "MCX Commodity",
            "NCDEX": "NCDEX Commodity",
        },
        "product_types": {
            "CNC": "Cash & Carry for equity",
            "NRML": "Normal for futures and options",
            "MIS": "Intraday Square off",
        },
        "price_types": {
            "MARKET": "Market Order",
            "LIMIT": "Limit Order",
            "SL": "Stop Loss Limit Order",
            "SL-M": "Stop Loss Market Order",
        },
        "actions": {"BUY": "Buy", "SELL": "Sell"},
        "intervals": ["1m", "3m", "5m", "10m", "15m", "30m", "1h", "D"],
    }
    return json.dumps(constants, indent=2)


@mcp.tool()
def send_telegram_alert(username: str, message: str) -> str:
    """
    Send a Telegram alert notification.

    Args:
        username: OpenAlgo login ID/username
        message: Alert message to send

    Returns:
        JSON with status and message
    """
    try:
        response = client.telegram(username=username, message=message)
        return json.dumps(response, indent=2)
    except Exception as e:
        return f"Error sending telegram alert: {str(e)}"


@mcp.tool()
def get_holidays(year: int) -> str:
    """
    Get trading holidays for a specific year.

    Args:
        year: Year to get holidays for (e.g., 2025)

    Returns:
        JSON with list of trading holidays including:
        - date: Holiday date (YYYY-MM-DD)
        - description: Holiday name/reason
        - holiday_type: TRADING_HOLIDAY or SPECIAL_SESSION
        - closed_exchanges: List of closed exchanges
        - open_exchanges: List of exchanges with special timings

    Example:
        get_holidays(2025)
    """
    try:
        response = client.holidays(year=year)
        return json.dumps(response, indent=2)
    except Exception as e:
        return f"Error getting holidays: {str(e)}"


@mcp.tool()
def get_timings(date: str) -> str:
    """
    Get exchange trading timings for a specific date.

    Args:
        date: Date in YYYY-MM-DD format (e.g., '2025-12-23')

    Returns:
        JSON with exchange timings including:
        - exchange: Exchange name (NSE, BSE, NFO, BFO, MCX, CDS, BCD)
        - start_time: Market open time in epoch milliseconds
        - end_time: Market close time in epoch milliseconds

    Example:
        get_timings("2025-12-23")
    """
    try:
        response = client.timings(date=date)
        return json.dumps(response, indent=2)
    except Exception as e:
        return f"Error getting timings: {str(e)}"


@mcp.tool()
def get_instruments(exchange: str) -> str:
    """
    Download all instruments for an exchange.

    Args:
        exchange: Exchange name (NSE, BSE, NFO, BFO, MCX, CDS, BCD, NCDEX)

    Returns:
        JSON with list of all instruments including:
        - symbol: Trading symbol
        - name: Instrument name
        - exchange: Exchange
        - lotsize: Lot size
        - instrumenttype: Type of instrument
        - expiry: Expiry date (for derivatives)
        - strike: Strike price (for options)
        - token: Exchange token

    Note: This can return a large dataset. Use search_instruments for specific queries.

    Example:
        get_instruments("NSE")
    """
    try:
        response = client.instruments(exchange=exchange.upper())
        return json.dumps(response, indent=2)
    except Exception as e:
        return f"Error getting instruments: {str(e)}"


# Tool to get analyzer status
@mcp.tool()
def analyzer_status() -> dict:
    """
    Get the current analyzer status including mode and total logs.

    Returns:
        Dictionary containing analyzer status information:
        - analyze_mode: Boolean indicating if analyzer is active
        - mode: Current mode ('analyze' or 'live')
        - total_logs: Number of logs in analyzer

    Example Response:
        {
            'data': {
                'analyze_mode': True,
                'mode': 'analyze',
                'total_logs': 2
            },
            'status': 'success'
        }
    """
    try:
        response = client.analyzerstatus()
        return response
    except Exception as e:
        return {"status": "error", "error": str(e)}


# Tool to toggle analyzer mode
@mcp.tool()
def analyzer_toggle(mode: bool) -> dict:
    """
    Toggle the analyzer mode between analyze (simulated) and live trading.

    Args:
        mode: True for analyze mode (simulated), False for live mode

    Returns:
        Dictionary with updated analyzer status:
        - analyze_mode: Boolean indicating current state
        - message: Status message
        - mode: Current mode string
        - total_logs: Number of logs in analyzer

    Example:
        analyzer_toggle(True) - Switch to analyze mode (simulated responses)
        analyzer_toggle(False) - Switch to live trading mode
    """
    try:
        response = client.analyzertoggle(mode=mode)
        return response
    except Exception as e:
        return {"status": "error", "error": str(e)}


if __name__ == "__main__":
    mcp.run(transport="stdio")
