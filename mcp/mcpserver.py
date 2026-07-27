import json
import os
import sys
from datetime import date, timedelta
from typing import Any

import httpx
import pandas as pd
from mcp.server.fastmcp import FastMCP
from openalgo import api, ta

# Two boot paths share this module:
#
# 1. Stdio (legacy / local) — Claude Desktop, Cursor, Windsurf spawn this
#    file as `python -m mcp.mcpserver <api_key> <host>`. argv[1] and argv[2]
#    must be present. The original MCP integration lives here unchanged.
#
# 2. HTTP / SSE — blueprints/mcp_http.py imports this module to access the
#    `mcp` FastMCP instance (and every @mcp.tool decorated function), then
#    calls init_for_http(api_key, host) once per process to wire the SDK
#    client. The Flask app sets OPENALGO_MCP_HTTP_BOOT=1 *before* importing
#    so the argv check is bypassed.
#
# The branching is at module scope rather than inside a function so the
# FastMCP `mcp = FastMCP(...)` instance and every `@mcp.tool` decorator
# remain top-level (FastMCP relies on import-time registration).

if os.environ.get("OPENALGO_MCP_HTTP_BOOT") == "1":
    # HTTP transport — Flask sets the env var before import. The SDK
    # client is wired by init_for_http() right after import. Stdio
    # users never hit this branch.
    api_key: str | None = None
    host: str | None = None
    client = None
else:
    # === Original stdio behavior — preserved verbatim ===
    # Existing Claude Desktop / Cursor / Windsurf integrations launch
    # this file as `python -m mcp.mcpserver <api_key> <host>` and rely
    # on this exact error path on misconfiguration. Do NOT change the
    # check, the order, or the error message here.
    if len(sys.argv) < 3:
        raise ValueError("API key and host must be provided as command line arguments")

    api_key = sys.argv[1]
    host = sys.argv[2]

    # Initialize OpenAlgo client with provided arguments
    client = api(api_key=api_key, host=host)


def init_for_http(api_key_value: str, host_value: str) -> None:
    """Wire the SDK client when running under the HTTP transport.

    Called once from blueprints/mcp_http.py after the Flask app has
    determined the admin's API key and the local OpenAlgo loopback URL.
    Idempotent — safe to call repeatedly with the same values; later
    calls overwrite the global so a restarted broker session can rotate
    the underlying SDK client without restarting Gunicorn.
    """
    global api_key, host, client
    api_key = api_key_value
    host = host_value
    client = api(api_key=api_key_value, host=host_value)

# Default strategy name for all order-related calls originating from the MCP server.
# Surfaced in OpenAlgo logs and analyzer views so MCP-driven trades are identifiable.
MCP_STRATEGY = "python mcp"

# OpenAlgo standardized index symbols (NSE_INDEX / BSE_INDEX) — rolled out across all brokers.
# Source: https://docs.openalgo.in/symbol-format
NSE_INDEX_SYMBOLS = [
    "NIFTY", "NIFTYNXT50", "FINNIFTY", "BANKNIFTY", "MIDCPNIFTY", "INDIAVIX",
    "HANGSENGBEESNAV",
    "NIFTY100", "NIFTY200", "NIFTY500",
    "NIFTYALPHA50", "NIFTYAUTO", "NIFTYCOMMODITIES", "NIFTYCONSUMPTION",
    "NIFTYCPSE", "NIFTYDIVOPPS50", "NIFTYENERGY", "NIFTYFMCG",
    "NIFTYGROWSECT15",
    "NIFTYGS10YR", "NIFTYGS10YRCLN", "NIFTYGS1115YR", "NIFTYGS15YRPLUS",
    "NIFTYGS48YR", "NIFTYGS813YR", "NIFTYGSCOMPSITE",
    "NIFTYINFRA", "NIFTYIT", "NIFTYMEDIA", "NIFTYMETAL",
    "NIFTYMIDLIQ15", "NIFTYMIDCAP100", "NIFTYMIDCAP150", "NIFTYMIDCAP50",
    "NIFTYMIDSML400", "NIFTYMNC", "NIFTYPHARMA", "NIFTYPSE", "NIFTYPSUBANK",
    "NIFTYPVTBANK", "NIFTYREALTY", "NIFTYSERVSECTOR",
    "NIFTYSMLCAP100", "NIFTYSMLCAP250", "NIFTYSMLCAP50",
    "NIFTY100EQLWGT", "NIFTY100LIQ15", "NIFTY100LOWVOL30",
    "NIFTY100QUALTY30", "NIFTY200QUALTY30",
    "NIFTY50DIVPOINT", "NIFTY50EQLWGT",
    "NIFTY50PR1XINV", "NIFTY50PR2XLEV", "NIFTY50TR1XINV", "NIFTY50TR2XLEV",
    "NIFTY50VALUE20",
]
BSE_INDEX_SYMBOLS = [
    "SENSEX", "BANKEX", "SENSEX50",
    "BSE100", "BSE150MIDCAPINDEX", "BSE200", "BSE250LARGEMIDCAPINDEX",
    "BSE400MIDSMALLCAPINDEX", "BSE500",
    "BSEAUTO", "BSECAPITALGOODS", "BSECARBONEX", "BSECONSUMERDURABLES",
    "BSECPSE", "BSEDOLLEX100", "BSEDOLLEX200", "BSEDOLLEX30",
    "BSEENERGY", "BSEFASTMOVINGCONSUMERGOODS", "BSEFINANCIALSERVICES",
    "BSEGREENEX", "BSEHEALTHCARE", "BSEINDIAINFRASTRUCTUREINDEX",
    "BSEINDUSTRIALS", "BSEINFORMATIONTECHNOLOGY", "BSEIPO",
    "BSELARGECAP", "BSEMETAL", "BSEMIDCAP", "BSEMIDCAPSELECTINDEX",
    "BSEOIL&GAS", "BSEPOWER", "BSEPSU", "BSEREALTY", "BSESENSEXNEXT50",
    "BSESMALLCAP", "BSESMALLCAPSELECTINDEX", "BSESMEIPO",
    "BSETECK", "BSETELECOM",
]

# Create MCP server
mcp = FastMCP("openalgo")


def _to_json(payload: Any) -> str:
    """Serialize any SDK response (dict, list, or pandas DataFrame) to a JSON string."""
    if hasattr(payload, "to_dict") and hasattr(payload, "reset_index"):
        df = payload.reset_index()
        return json.dumps(
            {"count": len(df), "data": df.to_dict(orient="records")},
            indent=2,
            default=str,
        )
    return json.dumps(payload, indent=2, default=str)

# ORDER MANAGEMENT TOOLS


@mcp.tool()
def place_order(
    symbol: str,
    quantity: int,
    action: str,
    exchange: str = "NSE",
    price_type: str = "MARKET",
    product: str = "MIS",
    strategy: str = MCP_STRATEGY,
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
        strategy: Strategy name (defaults to 'python mcp')
        price: Limit price (required for LIMIT orders)
        trigger_price: Trigger price (required for SL and SL-M orders)
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
    strategy: str = MCP_STRATEGY,
    price: float | None = None,
    trigger_price: float | None = None,
    disclosed_quantity: int | None = None,
) -> str:
    """
    Place a smart order that considers the current position size (auto-calculates delta
    between requested and current size before sending to the broker).

    Args:
        symbol: Stock symbol
        quantity: Target quantity
        action: 'BUY' or 'SELL'
        position_size: Current position size
        exchange: Exchange name
        price_type: 'MARKET', 'LIMIT', 'SL', 'SL-M'
        product: 'CNC', 'NRML', 'MIS'
        strategy: Strategy name (defaults to 'python mcp')
        price: Limit price (required for LIMIT orders)
        trigger_price: Trigger price (required for SL / SL-M orders)
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
            "position_size": position_size,
        }

        if price is not None:
            params["price"] = price
        if trigger_price is not None:
            params["trigger_price"] = trigger_price
        if disclosed_quantity is not None:
            params["disclosed_quantity"] = disclosed_quantity

        response = client.placesmartorder(**params)
        return json.dumps(response, indent=2)
    except Exception as e:
        return f"Error placing smart order: {str(e)}"


@mcp.tool()
def place_basket_order(orders: list[dict[str, Any]], strategy: str = MCP_STRATEGY) -> str:
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
    strategy: str = MCP_STRATEGY,
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
    strategy: str = MCP_STRATEGY,
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
        quantity: Absolute quantity — must be a multiple of the contract lot size.
                  Do NOT hardcode lot size — call get_option_symbol() or get_option_chain()
                  first to read the current 'lotsize' from the broker master contract,
                  then pass quantity = lots * lotsize.
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
    underlying: str,
    exchange: str,
    legs: list[dict[str, Any]],
    expiry_date: str | None = None,
    strategy: str = MCP_STRATEGY,
) -> str:
    """
    Place a multi-leg options order (spreads, iron condor, straddles, etc.).
    BUY legs are executed first for margin efficiency, then SELL legs.

    Args:
        strategy: Strategy name (defaults to 'python mcp'). Give each multi-leg trade
                  a meaningful name (e.g., 'nifty iron condor') to make tracking easier.
        underlying: Underlying symbol (e.g., 'NIFTY', 'BANKNIFTY', 'NIFTY28OCT25FUT')
        exchange: Exchange for underlying ('NSE_INDEX', 'BSE_INDEX', 'NFO')
        legs: List of leg dictionaries (1-20 legs). Each leg must contain:
            Required:
            - offset: Strike offset ('ATM', 'ITM1'-'ITM50', 'OTM1'-'OTM50')
            - option_type: 'CE' for Call or 'PE' for Put
            - action: 'BUY' or 'SELL'
            - quantity: Absolute quantity — must be a multiple of the contract lot size.
                        Do NOT hardcode lot size. Look up the current 'lotsize' per leg
                        using get_option_symbol() or get_option_chain() first, then pass
                        quantity = lots * lotsize. Lot sizes can change (e.g., NIFTY has
                        changed multiple times) and differ by underlying.
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
    symbol: str,
    action: str,
    exchange: str,
    product: str,
    quantity: int,
    price: float,
    strategy: str = MCP_STRATEGY,
    price_type: str = "LIMIT",
    trigger_price: float = 0,
    disclosed_quantity: int = 0,
) -> str:
    """
    Modify an existing order.

    Args:
        order_id: Order ID to modify
        symbol: Stock symbol
        action: 'BUY' or 'SELL'
        exchange: Exchange name
        product: 'CNC', 'NRML', 'MIS'
        quantity: New quantity
        price: New price (required by the API — use current price if unchanged)
        strategy: Strategy name (defaults to 'python mcp')
        price_type: 'MARKET', 'LIMIT', 'SL', 'SL-M' (defaults to 'LIMIT')
        trigger_price: New trigger price for SL/SL-M orders (default 0)
        disclosed_quantity: New disclosed quantity (default 0)
    """
    try:
        response = client.modifyorder(
            order_id=order_id,
            strategy=strategy,
            symbol=symbol.upper(),
            action=action.upper(),
            exchange=exchange.upper(),
            price_type=price_type.upper(),
            product=product.upper(),
            quantity=quantity,
            price=price,
            trigger_price=trigger_price,
            disclosed_quantity=disclosed_quantity,
        )
        return json.dumps(response, indent=2)
    except Exception as e:
        return f"Error modifying order: {str(e)}"


@mcp.tool()
def cancel_order(order_id: str, strategy: str = MCP_STRATEGY) -> str:
    """
    Cancel a specific order.

    Args:
        order_id: Order ID to cancel
        strategy: Strategy name (defaults to 'python mcp')
    """
    try:
        response = client.cancelorder(order_id=order_id, strategy=strategy)
        return json.dumps(response, indent=2)
    except Exception as e:
        return f"Error canceling order: {str(e)}"


@mcp.tool()
def cancel_all_orders(strategy: str = MCP_STRATEGY) -> str:
    """
    Cancel all open orders for a strategy.

    Args:
        strategy: Strategy name (defaults to 'python mcp')
    """
    try:
        response = client.cancelallorder(strategy=strategy)
        return json.dumps(response, indent=2)
    except Exception as e:
        return f"Error canceling all orders: {str(e)}"


# POSITION MANAGEMENT TOOLS


@mcp.tool()
def close_all_positions(strategy: str = MCP_STRATEGY) -> str:
    """
    Close all open positions for a strategy.

    Args:
        strategy: Strategy name (defaults to 'python mcp')
    """
    try:
        response = client.closeposition(strategy=strategy)
        return json.dumps(response, indent=2)
    except Exception as e:
        return f"Error closing positions: {str(e)}"


@mcp.tool()
def get_open_position(
    symbol: str, exchange: str, product: str, strategy: str = MCP_STRATEGY
) -> str:
    """
    Get current open position for a specific instrument.

    Args:
        symbol: Stock symbol
        exchange: Exchange name
        product: Product type ('CNC', 'NRML', 'MIS')
        strategy: Strategy name (defaults to 'python mcp')
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
def get_order_status(order_id: str, strategy: str = MCP_STRATEGY) -> str:
    """
    Get status of a specific order.

    Args:
        order_id: Order ID
        strategy: Strategy name (defaults to 'python mcp')
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
    underlying: str,
    exchange: str,
    expiry_date: str | None = None,
    strike_count: int | None = None,
) -> str:
    """
    Get option chain data with real-time quotes for all strikes.

    Args:
        underlying: Underlying symbol (e.g., 'NIFTY', 'BANKNIFTY', 'RELIANCE',
                    or a future like 'NIFTY30DEC25FUT')
        exchange: Exchange for underlying ('NSE_INDEX', 'BSE_INDEX', 'NSE', 'BSE', 'NFO', 'BFO')
        expiry_date: Expiry date in DDMMMYY format (e.g., '30DEC25'). Optional when the
                     underlying already includes an expiry (e.g., 'NIFTY30DEC25FUT').
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
        params: dict[str, Any] = {
            "underlying": underlying.upper(),
            "exchange": exchange.upper(),
        }
        if expiry_date is not None:
            params["expiry_date"] = expiry_date.upper()
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
    symbol: str,
    exchange: str,
    interval: str,
    start_date: str | None = None,
    end_date: str | None = None,
    source: str = "api",
    bars: int = 20,
    lookback_days: int | None = None,
) -> str:
    """
    Get historical OHLCV data for a symbol.

    Args:
        symbol: Stock symbol
        exchange: Exchange name
        interval: Time interval. With source='api': '1m', '3m', '5m', '10m', '15m', '30m', '1h', 'D'.
                  With source='db': also supports custom intervals (2m, 4m, 6m, 7m, 2h, 3h, 4h) and
                  daily-based (W, M, Q, Y plus multiples like 2W, 3M).
        start_date: Start date (YYYY-MM-DD). Optional — when omitted, the last `bars`
                    (default 20) most-recent bars are returned (or `lookback_days` if given).
        end_date: End date (YYYY-MM-DD). Optional — defaults to today.
        source: 'api' (default) fetches from broker API. 'db' fetches from the local
                OpenAlgo Historify DuckDB store (1m/D stored, other intervals computed via SQL).
        bars: Number of most-recent bars to return (default 20). The window is fetched
              server-side; only the last `bars` rows are sent back to keep the payload small.
              Increase only if you explicitly need more rows.
        lookback_days: When dates are omitted, fetch the last N calendar days instead of a
                       bar-count window (e.g., 30 for "last 30 days").

    Returns:
        JSON with total count, returned count, a truncated flag, and data (list of
        {timestamp, open, high, low, close, volume}) — the last `bars` rows.
    """
    try:
        # Fetch enough to satisfy `bars` (min 252) unless an explicit range/lookback is given.
        response = _load_history(
            symbol, exchange, interval, start_date, end_date, max(252, bars), lookback_days, source
        )
        total = len(response)
        return json.dumps(
            {
                "count": total,
                "returned": min(bars, total),
                "truncated": total > bars,
                "bars": bars,
                "data": _df_records(response, bars),
            },
            indent=2,
            default=str,
        )
    except Exception as e:
        return f"Error getting historical data: {str(e)}"


# INSTRUMENT SEARCH AND INFO TOOLS


@mcp.tool()
def search_instruments(
    query: str, exchange: str | None = None, instrument_type: str | None = None
) -> str:
    """
    Search for instruments by name or symbol.

    Args:
        query: Search query (e.g., 'NIFTY 26000 DEC CE', 'RELIANCE')
        exchange: Exchange to restrict the search to (NSE, BSE, NFO, BFO, MCX, NSE_INDEX, etc.).
                  Optional — when omitted, searches across all exchanges.
        instrument_type: Optional convenience filter — pass 'INDEX' to auto-rewrite
                         exchange=NSE → NSE_INDEX and BSE → BSE_INDEX.
    """
    try:
        resolved_exchange = exchange
        if instrument_type and instrument_type.upper() == "INDEX" and exchange:
            if exchange.upper() == "NSE":
                resolved_exchange = "NSE_INDEX"
            elif exchange.upper() == "BSE":
                resolved_exchange = "BSE_INDEX"
        if resolved_exchange is not None:
            response = client.search(query=query, exchange=resolved_exchange.upper())
        else:
            response = client.search(query=query)
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

        # Or auto-route to the _INDEX exchange if the symbol is a known index.
        if symbol.upper() in NSE_INDEX_SYMBOLS and exchange.upper() == "NSE":
            exchange = "NSE_INDEX"
        elif symbol.upper() in BSE_INDEX_SYMBOLS and exchange.upper() == "BSE":
            exchange = "BSE_INDEX"

        response = client.symbol(symbol=symbol.upper(), exchange=exchange.upper())
        return json.dumps(response, indent=2)
    except Exception as e:
        return f"Error getting symbol info: {str(e)}"


@mcp.tool()
def get_index_symbols(exchange: str = "NSE") -> str:
    """
    Get the OpenAlgo-standardized index symbols for NSE or BSE.

    These are the common index names rolled out across all supported brokers via the
    OpenAlgo symbol standardization. Use exchange code 'NSE_INDEX' / 'BSE_INDEX' when
    placing orders or fetching quotes for these symbols.

    Args:
        exchange: NSE or BSE

    Returns:
        JSON with exchange, exchange_code, and the full list of standardized index
        symbols (57+ NSE, 40+ BSE).
    """
    indices = {
        "NSE": {"exchange_code": "NSE_INDEX", "symbols": NSE_INDEX_SYMBOLS},
        "BSE": {"exchange_code": "BSE_INDEX", "symbols": BSE_INDEX_SYMBOLS},
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
    underlying: str,
    exchange: str,
    offset: str,
    option_type: str,
    expiry_date: str | None = None,
) -> str:
    """
    Get option symbol for specific strike and expiry.

    Args:
        underlying: Underlying symbol (e.g., 'NIFTY', 'BANKNIFTY', 'NIFTY28OCT25FUT')
        exchange: Exchange for underlying ('NSE_INDEX', 'BSE_INDEX', 'NFO', 'BFO')
        offset: Strike offset - 'ATM', 'ITM1'-'ITM50', 'OTM1'-'OTM50'
        option_type: 'CE' for Call or 'PE' for Put
        expiry_date: Expiry date in 'DDMMMYY' format (e.g., '28OCT25'). Optional when
                     the underlying already includes an expiry.

    Returns:
        JSON with symbol, exchange, lotsize, tick_size, underlying_ltp
    """
    try:
        params: dict[str, Any] = {
            "underlying": underlying.upper(),
            "exchange": exchange.upper(),
            "offset": offset.upper(),
            "option_type": option_type.upper(),
        }
        if expiry_date is not None:
            params["expiry_date"] = expiry_date
        response = client.optionsymbol(**params)
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
    interest_rate: float | None = None,
    forward_price: float | None = None,
    underlying_symbol: str | None = None,
    underlying_exchange: str | None = None,
    expiry_time: str | None = None,
) -> str:
    """
    Calculate option Greeks (Delta, Gamma, Theta, Vega, Rho) and Implied Volatility using Black-76.

    Args:
        symbol: Option symbol (e.g., 'NIFTY25NOV2526000CE'). Required.
        exchange: Exchange code ('NFO', 'BFO', 'CDS', 'MCX'). Required.
        interest_rate: Risk-free interest rate in annualized % (e.g., 6.5 for RBI repo).
                       Optional — defaults to 0.
        forward_price: Custom forward / synthetic futures price. If provided, skips the
                       underlying price fetch. Useful for illiquid underlyings (FINNIFTY,
                       MIDCPNIFTY) or custom scenario analysis.
        underlying_symbol: Custom underlying symbol (e.g., 'NIFTY', 'NIFTY30DEC25FUT').
                           Optional — auto-detected from the option symbol when omitted.
        underlying_exchange: Custom underlying exchange ('NSE_INDEX', 'NFO', etc.).
                             Optional — auto-detected when omitted.
        expiry_time: Custom expiry time in HH:MM format (e.g., '19:00'). Required for
                     MCX contracts with non-standard expiry times. Exchange defaults:
                     NFO/BFO=15:30, CDS=12:30, MCX=23:30.

    Returns:
        JSON with greeks, implied_volatility, spot_price, strike, days_to_expiry.
    """
    try:
        params: dict[str, Any] = {
            "symbol": symbol.upper(),
            "exchange": exchange.upper(),
        }
        if interest_rate is not None:
            params["interest_rate"] = interest_rate
        if forward_price is not None:
            params["forward_price"] = forward_price
        if underlying_symbol is not None:
            params["underlying_symbol"] = underlying_symbol.upper()
        if underlying_exchange is not None:
            params["underlying_exchange"] = underlying_exchange.upper()
        if expiry_time is not None:
            params["expiry_time"] = expiry_time
        response = client.optiongreeks(**params)
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
def send_telegram_alert(username: str, message: str, priority: int = 5) -> str:
    """
    Send a Telegram alert notification.

    Args:
        username: OpenAlgo login ID/username
        message: Alert message to send
        priority: Notification priority (1-10, default 5). Higher values may be used
                  by the bot for emphasis/sorting depending on configuration.

    Returns:
        JSON with status and message
    """
    try:
        response = client.telegram(username=username, message=message, priority=priority)
        return json.dumps(response, indent=2)
    except Exception as e:
        return f"Error sending telegram alert: {str(e)}"


@mcp.tool()
def get_holidays(year: int | None = None) -> str:
    """
    Get trading holidays for a specific year.

    Args:
        year: Year to get holidays for (e.g., 2026). Optional — defaults to current year.

    Returns:
        JSON with list of trading holidays including:
        - date: Holiday date (YYYY-MM-DD)
        - description: Holiday name/reason
        - holiday_type: TRADING_HOLIDAY, SETTLEMENT_HOLIDAY, or SPECIAL_SESSION
        - closed_exchanges: List of closed exchanges
        - open_exchanges: List of exchanges with special timings

    Example:
        get_holidays(2026)
        get_holidays()          # current year
    """
    try:
        response = client.holidays(year=year) if year is not None else client.holidays()
        return json.dumps(response, indent=2, default=str)
    except Exception as e:
        return f"Error getting holidays: {str(e)}"


@mcp.tool()
def get_timings(date: str | None = None) -> str:
    """
    Get exchange trading timings for a specific date.

    Args:
        date: Date in YYYY-MM-DD format (e.g., '2026-04-23'). Optional — defaults to today.

    Returns:
        JSON with exchange timings including:
        - exchange: Exchange name (NSE, BSE, NFO, BFO, MCX, CDS, BCD)
        - start_time: Market open time in epoch milliseconds
        - end_time: Market close time in epoch milliseconds

    Example:
        get_timings("2026-04-23")
        get_timings()           # today
    """
    try:
        response = client.timings(date=date) if date is not None else client.timings()
        return json.dumps(response, indent=2, default=str)
    except Exception as e:
        return f"Error getting timings: {str(e)}"


@mcp.tool()
def check_holiday(date: str, exchange: str | None = None) -> str:
    """
    Check if a specific date is a market holiday for an exchange.

    This calls the /api/v1/checkholiday endpoint directly (not yet in the openalgo SDK).
    Use this for fast pre-trade "is the market open?" checks.

    Args:
        date: Date in YYYY-MM-DD format (between 2020-01-01 and 2050-12-31). Required.
        exchange: Exchange code (NSE, BSE, NFO, BFO, MCX, CDS, BCD). Optional.
                  When omitted, returns true if the date is a holiday for any major exchange.

    Returns:
        JSON with:
        - status: 'success' or 'error'
        - data.date, data.exchange (if specified), data.is_holiday (bool)

    Notes:
        - Weekends and national holidays both return is_holiday=true.
        - For a full calendar, use get_holidays(year).

    Examples:
        check_holiday("2026-01-26", "NSE")
        check_holiday("2026-01-27")
    """
    try:
        url = f"{host.rstrip('/')}/api/v1/checkholiday"
        payload: dict[str, Any] = {"apikey": api_key, "date": date}
        if exchange:
            payload["exchange"] = exchange.upper()
        with httpx.Client(timeout=30.0) as http:
            r = http.post(url, json=payload, headers={"Content-Type": "application/json"})
            return json.dumps(r.json(), indent=2, default=str)
    except Exception as e:
        return f"Error checking holiday: {str(e)}"


@mcp.tool()
def get_instruments(exchange: str | None = None, limit: int = 500) -> str:
    """
    Download the full instrument master.

    Args:
        exchange: Exchange name (NSE, BSE, NFO, BFO, MCX, CDS, BCD, NSE_INDEX, BSE_INDEX).
                  Optional — when omitted, downloads instruments for ALL exchanges.
        limit: Maximum number of rows to return in the response (default: 500).
               The full dataset can exceed 100k rows for derivatives exchanges, which
               overwhelms the MCP tool output. Use search_instruments for targeted lookups.

    Returns:
        JSON with count, returned, truncated flag, and data (list of instrument records).
        Each record includes: symbol, brsymbol, name, exchange, lotsize,
        instrumenttype, expiry, strike, token, tick_size.
    """
    try:
        response = (
            client.instruments(exchange=exchange.upper())
            if exchange is not None
            else client.instruments()
        )
        # SDK returns a DataFrame on success, dict on error
        if hasattr(response, "reset_index"):
            total = len(response)
            df_head = response.head(limit).reset_index(drop=True)
            return json.dumps(
                {
                    "exchange": exchange.upper() if exchange else "ALL",
                    "count": total,
                    "returned": len(df_head),
                    "truncated": total > limit,
                    "limit": limit,
                    "data": df_head.to_dict(orient="records"),
                },
                indent=2,
                default=str,
            )
        return json.dumps(response, indent=2, default=str)
    except Exception as e:
        return f"Error getting instruments: {str(e)}"


# Tool to get analyzer status
@mcp.tool()
def analyzer_status() -> str:
    """
    Get the current analyzer status including mode and total logs.

    Returns:
        JSON with analyzer status information:
        - data.analyze_mode: Boolean indicating if analyzer is active
        - data.mode: Current mode ('analyze' or 'live')
        - data.total_logs: Number of logs in analyzer
        - status: 'success' or 'error'
    """
    try:
        response = client.analyzerstatus()
        return json.dumps(response, indent=2, default=str)
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)}, indent=2)


# Tool to toggle analyzer mode
@mcp.tool()
def analyzer_toggle(mode: bool) -> str:
    """
    Toggle the analyzer mode between analyze (simulated) and live trading.

    Args:
        mode: True for analyze mode (simulated), False for live mode

    Returns:
        JSON with updated analyzer status:
        - data.analyze_mode, data.message, data.mode, data.total_logs
        - status: 'success' or 'error'

    Example:
        analyzer_toggle(True)  # Switch to analyze mode (simulated responses)
        analyzer_toggle(False) # Switch to live trading mode
    """
    try:
        response = client.analyzertoggle(mode=mode)
        return json.dumps(response, indent=2, default=str)
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)}, indent=2)


# ============================================================
# RESEARCH TOOLS — TECHNICAL INDICATORS (openalgo.ta)
# ============================================================
# These tools fetch OHLCV history via the SDK (client.history) and
# compute indicators with `from openalgo import ta`. They are SDK-only
# and work under BOTH the stdio and HTTP transports.

# Indicators whose first inputs are High/Low/Close (and optionally
# Volume) rather than a single Close series. Used to auto-pick inputs
# in calculate_indicator() when the caller does not pass `inputs`.
_HLC_INDICATORS = {
    "atr", "natr", "true_range", "adx", "adxr", "dmi", "dx", "supertrend",
    "stochastic", "stochf", "cci", "williams_r", "keltner", "donchian",
    "aroon", "aroon_oscillator", "psar", "ichimoku", "pivot_points",
    "ultimate_oscillator", "uo_oscillator", "chandelier_exit", "starc",
    "elderray", "ckstop", "fractals", "rwi", "alligator", "gator_oscillator",
    "bop", "rvi", "fisher", "avgprice", "medprice", "midprice", "typprice",
    "wclprice",
}
_HLCV_INDICATORS = {"mfi", "cmf", "adl", "emv", "klingervolumeoscillator"}


def _history_df(
    symbol: str,
    exchange: str,
    interval: str,
    start_date: str,
    end_date: str,
    source: str = "api",
):
    """Fetch OHLCV history as a timestamp-indexed DataFrame. Raises on failure.

    source: 'api' (default) fetches from the broker API; 'db' fetches from the local
    OpenAlgo Historify DuckDB store (1m/D stored, other intervals computed via SQL,
    enabling custom intervals like 2m/4m/W/M/Q for research).
    """
    df = client.history(
        symbol=symbol.upper(),
        exchange=exchange.upper(),
        interval=interval,
        start_date=start_date,
        end_date=end_date,
        source=source,
    )
    # SDK returns a DataFrame on success, a dict on error.
    if not hasattr(df, "reset_index"):
        raise ValueError(f"history error: {df}")
    if len(df) == 0:
        raise ValueError("no historical data returned for the given range")
    return df


# Approx bars per trading day per interval (NSE ~6h15m session). Used only to size
# the calendar window when fetching by bar-count, so it can be a rough estimate.
_BARS_PER_DAY = {
    "1m": 375, "3m": 125, "5m": 75, "10m": 38, "15m": 25, "30m": 13,
    "1h": 7, "60m": 7, "2h": 4, "3h": 3, "4h": 2,
    "d": 1, "day": 1, "w": 0.2, "week": 0.2, "m": 0.05, "month": 0.05,
}


def _load_history(
    symbol: str,
    exchange: str,
    interval: str,
    start_date: str | None = None,
    end_date: str | None = None,
    lookback_bars: int = 252,
    lookback_days: int | None = None,
    source: str = "api",
):
    """Fetch OHLCV history with a flexible lookback window.

    Resolution priority:
      1. Explicit start_date (with optional end_date) -> use that range verbatim.
      2. lookback_days given -> last N calendar days ending today (e.g., "last 30 days").
      3. else -> last `lookback_bars` bars (default 252 ≈ one trading year of daily data):
         fetch a wide-enough calendar window, then tail to exactly `lookback_bars` rows.
    """
    end = end_date or date.today().isoformat()
    if start_date:
        return _history_df(symbol, exchange, interval, start_date, end, source)
    if lookback_days:
        start = (date.fromisoformat(end) - timedelta(days=int(lookback_days))).isoformat()
        return _history_df(symbol, exchange, interval, start, end, source)
    bpd_per_day = _BARS_PER_DAY.get(interval.lower(), 75)
    cal_days = int((lookback_bars / bpd_per_day) * 1.6) + 5
    start = (date.fromisoformat(end) - timedelta(days=cal_days)).isoformat()
    df = _history_df(symbol, exchange, interval, start, end, source)
    return df.tail(int(lookback_bars))


def _idx_iso(df, pos: int) -> str:
    """ISO timestamp of the row at positional index `pos` (e.g., 0 first, -1 last)."""
    ts = df.index[pos]
    return ts.isoformat() if hasattr(ts, "isoformat") else str(ts)


def _last(series) -> float | None:
    """Last non-null value of a Series-like as a rounded float, or None."""
    try:
        s = series.dropna()
        return round(float(s.iloc[-1]), 4) if len(s) else None
    except Exception:
        return None


def _df_records(df, limit: int | None = None):
    """Convert a DataFrame to JSON-safe records with an ISO 'timestamp' column."""
    out = df.tail(limit) if limit else df
    out = out.reset_index()
    out = out.rename(columns={out.columns[0]: "timestamp"})
    return json.loads(out.to_json(orient="records", date_format="iso"))


def _resolve_inputs(df, name: str, inputs: list[str] | None):
    """Pick the ordered input Series for an indicator (caller override or heuristic)."""
    if inputs:
        cols = [c.lower() for c in inputs]
    elif name in _HLCV_INDICATORS:
        cols = ["high", "low", "close", "volume"]
    elif name in _HLC_INDICATORS:
        cols = ["high", "low", "close"]
    else:
        cols = ["close"]
    return cols, [df[c] for c in cols]


def _bundle(df, specs: list[tuple]):
    """Compute latest values for a set of indicators, capturing per-item errors.

    specs: list of (key, callable) where callable returns a Series or tuple of Series.
    Tuple results become a list of latest values (see each tool's 'legend').
    """
    result: dict[str, Any] = {}
    for key, fn in specs:
        try:
            val = fn()
            result[key] = [_last(s) for s in val] if isinstance(val, tuple) else _last(val)
        except Exception as e:
            result[key] = {"error": str(e)}
    return result


def _as_bool(x, index) -> pd.Series:
    """Coerce an indicator boolean result (Series or array) to a clean bool Series."""
    s = pd.Series(list(x), index=index)
    return s.fillna(False).astype(bool)


@mcp.tool()
def calculate_indicator(
    symbol: str,
    exchange: str,
    indicator: str,
    interval: str = "D",
    start_date: str | None = None,
    end_date: str | None = None,
    params: dict[str, Any] | None = None,
    inputs: list[str] | None = None,
    bars: int = 20,
    lookback_bars: int = 252,
    lookback_days: int | None = None,
    source: str = "api",
) -> str:
    """
    Run ANY of the 80+ openalgo.ta indicators over a symbol's historical OHLCV.

    History is fetched (db/api) and the indicator is computed entirely on the
    OpenAlgo server; only compact results are returned — never the raw OHLCV.

    Args:
        symbol: Stock symbol (e.g., 'RELIANCE', 'NIFTY')
        exchange: Exchange name (NSE, NFO, NSE_INDEX, etc.)
        indicator: ta function name, case-insensitive (e.g., 'rsi','macd','supertrend',
                   'atr','bbands','adx','ema','vwap').
        interval: '1m','3m','5m','10m','15m','30m','1h','D' (default 'D')
        start_date / end_date: YYYY-MM-DD. Optional — when omitted, a lookback window
                   ending today is used.
        params: Extra keyword args for the indicator (e.g., {"period": 14} for rsi;
                {"period": 10, "multiplier": 3} for supertrend;
                {"fast_period": 12, "slow_period": 26, "signal_period": 9} for macd).
        inputs: Ordered list of OHLCV columns to feed the indicator, e.g. ["close"] or
                ["high","low","close"]. Optional — auto-detected for common indicators;
                pass it explicitly if a result errors on inputs.
        bars: Number of most-recent computed rows to return (default 20). The indicator
              is ALWAYS computed server-side over the FULL fetched history; only the last
              `bars` rows (plus latest value and summary stats) are sent back, so the
              payload stays small. Increase only if you explicitly need more rows.
        lookback_bars: Bars of history to load/compute over when dates are omitted
                       (default 252 ≈ one trading year of daily data).
        lookback_days: Alternative calendar-day lookback (e.g., 30 for "last 30 days").
                       Overrides lookback_bars when set.
        source: 'api' (default, broker API) or 'db' (local Historify DuckDB store, which
                supports custom research intervals like 2m/4m/W/M/Q).

    Returns:
        JSON with the latest value(s), summary stats (last/min/max/mean), and a 'data'
        series of the last `bars` rows — all computed server-side. Multi-output indicators
        (macd, bbands, supertrend, stochastic, adx, ichimoku, keltner, donchian) report
        out0, out1, ...
    """
    try:
        df = _load_history(
            symbol, exchange, interval, start_date, end_date, lookback_bars, lookback_days, source
        )
        name = indicator.lower()
        fn = getattr(ta, name, None)
        if fn is None:
            return json.dumps(
                {"status": "error", "message": f"unknown indicator '{indicator}'"}, indent=2
            )
        cols, args = _resolve_inputs(df, name, inputs)
        result = fn(*args, **(params or {}))
        out = pd.DataFrame(index=df.index)
        if isinstance(result, tuple):
            for i, s in enumerate(result):
                out[f"out{i}"] = pd.Series(list(s), index=df.index)
        else:
            out["value"] = pd.Series(list(result), index=df.index)

        def _stats(s):
            s = s.dropna()
            if not len(s):
                return None
            return {
                "last": round(float(s.iloc[-1]), 4),
                "min": round(float(s.min()), 4),
                "max": round(float(s.max()), 4),
                "mean": round(float(s.mean()), 4),
            }

        cols_out = list(out.columns)
        ts = out.index[-1]
        payload: dict[str, Any] = {
            "symbol": symbol.upper(),
            "exchange": exchange.upper(),
            "indicator": name,
            "inputs": cols,
            "params": params or {},
            "interval": interval,
            "source": source,
            "bars": len(out),
            "last_close": _last(df["close"]),
            "latest_timestamp": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
            "latest": {c: _last(out[c]) for c in cols_out},
            "summary": {c: _stats(out[c]) for c in cols_out},
            "returned_bars": min(bars, len(out)),
            "data": _df_records(out, bars),
        }
        return json.dumps(payload, indent=2, default=str)
    except Exception as e:
        return f"Error calculating indicator: {str(e)}"


@mcp.tool()
def get_trend_snapshot(
    symbol: str,
    exchange: str,
    interval: str = "D",
    start_date: str | None = None,
    end_date: str | None = None,
    lookback_bars: int = 252,
    lookback_days: int | None = None,
    source: str = "api",
) -> str:
    """
    One-call trend read: SMA(20/50/200), EMA(20/50), Supertrend, ADX/DMI, Ichimoku.

    Args:
        symbol: Stock symbol
        exchange: Exchange name
        interval: Candle interval (default 'D')
        start_date / end_date: YYYY-MM-DD. Optional — default to a lookback window ending today.
        lookback_bars: Bars of history loaded when dates are omitted (default 252, enough for SMA200).
        lookback_days: Alternative calendar-day lookback (e.g., 30). Overrides lookback_bars.

    Returns:
        JSON with latest indicator values and a 'legend' explaining multi-value entries.
    """
    try:
        df = _load_history(
            symbol, exchange, interval, start_date, end_date, lookback_bars, lookback_days, source
        )
        snap = _bundle(
            df,
            [
                ("sma_20", lambda: ta.sma(df["close"], 20)),
                ("sma_50", lambda: ta.sma(df["close"], 50)),
                ("sma_200", lambda: ta.sma(df["close"], 200)),
                ("ema_20", lambda: ta.ema(df["close"], 20)),
                ("ema_50", lambda: ta.ema(df["close"], 50)),
                ("supertrend", lambda: ta.supertrend(df["high"], df["low"], df["close"])),
                ("adx_di", lambda: ta.adx(df["high"], df["low"], df["close"], period=14)),
                ("ichimoku", lambda: ta.ichimoku(df["high"], df["low"], df["close"])),
            ],
        )
        return json.dumps(
            {
                "symbol": symbol.upper(),
                "exchange": exchange.upper(),
                "interval": interval,
                "from": _idx_iso(df, 0),
                "to": _idx_iso(df, -1),
                "bars_loaded": len(df),
                "last_close": _last(df["close"]),
                "indicators": snap,
                "legend": {
                    "supertrend": "[supertrend_value, direction(+1 up / -1 down)]",
                    "adx_di": "[+DI, -DI, ADX]",
                    "ichimoku": "[tenkan, kijun, senkou_a, senkou_b, chikou]",
                },
            },
            indent=2,
            default=str,
        )
    except Exception as e:
        return f"Error getting trend snapshot: {str(e)}"


@mcp.tool()
def get_momentum_snapshot(
    symbol: str,
    exchange: str,
    interval: str = "D",
    start_date: str | None = None,
    end_date: str | None = None,
    lookback_bars: int = 252,
    lookback_days: int | None = None,
    source: str = "api",
) -> str:
    """
    One-call momentum read: RSI(14), MACD, Stochastic, CCI(20), Williams %R(14).

    Args:
        symbol: Stock symbol
        exchange: Exchange name
        interval: Candle interval (default 'D')
        start_date / end_date: YYYY-MM-DD. Optional — default to a lookback window ending today.
        lookback_bars: Bars of history loaded when dates are omitted (default 252).
        lookback_days: Alternative calendar-day lookback (e.g., 30). Overrides lookback_bars.

    Returns:
        JSON with latest values and a 'legend' for multi-value entries.
    """
    try:
        df = _load_history(
            symbol, exchange, interval, start_date, end_date, lookback_bars, lookback_days, source
        )
        snap = _bundle(
            df,
            [
                ("rsi_14", lambda: ta.rsi(df["close"], 14)),
                ("macd", lambda: ta.macd(df["close"])),
                ("stochastic", lambda: ta.stochastic(df["high"], df["low"], df["close"])),
                ("cci_20", lambda: ta.cci(df["high"], df["low"], df["close"], 20)),
                ("williams_r_14", lambda: ta.williams_r(df["high"], df["low"], df["close"], 14)),
            ],
        )
        return json.dumps(
            {
                "symbol": symbol.upper(),
                "exchange": exchange.upper(),
                "interval": interval,
                "from": _idx_iso(df, 0),
                "to": _idx_iso(df, -1),
                "bars_loaded": len(df),
                "last_close": _last(df["close"]),
                "indicators": snap,
                "legend": {
                    "macd": "[macd_line, signal_line, histogram]",
                    "stochastic": "[%K, %D]",
                },
            },
            indent=2,
            default=str,
        )
    except Exception as e:
        return f"Error getting momentum snapshot: {str(e)}"


@mcp.tool()
def get_volatility_snapshot(
    symbol: str,
    exchange: str,
    interval: str = "D",
    start_date: str | None = None,
    end_date: str | None = None,
    lookback_bars: int = 252,
    lookback_days: int | None = None,
    source: str = "api",
) -> str:
    """
    One-call volatility read: ATR, NATR, Bollinger Bands (+%B, width), Keltner,
    Donchian, Historical Volatility.

    Args:
        symbol: Stock symbol
        exchange: Exchange name
        interval: Candle interval (default 'D')
        start_date / end_date: YYYY-MM-DD. Optional — default to a lookback window ending today.
        lookback_bars: Bars of history loaded when dates are omitted (default 252).
        lookback_days: Alternative calendar-day lookback (e.g., 30). Overrides lookback_bars.

    Returns:
        JSON with latest values and a 'legend' for multi-value band entries.
    """
    try:
        df = _load_history(
            symbol, exchange, interval, start_date, end_date, lookback_bars, lookback_days, source
        )
        snap = _bundle(
            df,
            [
                ("atr_14", lambda: ta.atr(df["high"], df["low"], df["close"], period=14)),
                ("natr_14", lambda: ta.natr(df["high"], df["low"], df["close"], period=14)),
                ("bbands", lambda: ta.bbands(df["close"], period=20, std_dev=2.0)),
                ("bb_percent_b", lambda: ta.bbpercent(df["close"], period=20, std_dev=2.0)),
                ("bb_width", lambda: ta.bbwidth(df["close"], period=20, std_dev=2.0)),
                ("keltner", lambda: ta.keltner(df["high"], df["low"], df["close"])),
                ("donchian", lambda: ta.donchian(df["high"], df["low"], period=20)),
                ("historical_volatility", lambda: ta.hv(df["close"])),
            ],
        )
        return json.dumps(
            {
                "symbol": symbol.upper(),
                "exchange": exchange.upper(),
                "interval": interval,
                "from": _idx_iso(df, 0),
                "to": _idx_iso(df, -1),
                "bars_loaded": len(df),
                "last_close": _last(df["close"]),
                "indicators": snap,
                "legend": {
                    "bbands": "[upper, middle, lower]",
                    "keltner": "[upper, middle, lower]",
                    "donchian": "[upper, middle, lower]",
                },
            },
            indent=2,
            default=str,
        )
    except Exception as e:
        return f"Error getting volatility snapshot: {str(e)}"


@mcp.tool()
def get_support_resistance(
    symbol: str,
    exchange: str,
    interval: str = "D",
    start_date: str | None = None,
    end_date: str | None = None,
    lookback_bars: int = 252,
    lookback_days: int | None = None,
    period: int = 20,
    source: str = "api",
) -> str:
    """
    Support/resistance levels: Pivot Points, Donchian channel, and rolling
    highest-high / lowest-low over `period`.

    Args:
        symbol: Stock symbol
        exchange: Exchange name
        interval: Candle interval (default 'D')
        start_date / end_date: YYYY-MM-DD. Optional — default to a lookback window ending today.
        lookback_bars: Bars of history loaded when dates are omitted (default 252).
        lookback_days: Alternative calendar-day lookback (e.g., 30). Overrides lookback_bars.
        period: Lookback window for Donchian / highest / lowest (default 20).

    Returns:
        JSON with latest levels. 'pivot_points' is returned as ta.pivot_points emits it
        (typically [pivot, r1, s1, r2, s2, r3, s3]).
    """
    try:
        df = _load_history(
            symbol, exchange, interval, start_date, end_date, lookback_bars, lookback_days, source
        )
        snap = _bundle(
            df,
            [
                ("donchian", lambda: ta.donchian(df["high"], df["low"], period=period)),
                ("highest_high", lambda: ta.highest(df["high"], period)),
                ("lowest_low", lambda: ta.lowest(df["low"], period)),
                ("pivot_points", lambda: ta.pivot_points(df["high"], df["low"], df["close"])),
            ],
        )
        return json.dumps(
            {
                "symbol": symbol.upper(),
                "exchange": exchange.upper(),
                "interval": interval,
                "from": _idx_iso(df, 0),
                "to": _idx_iso(df, -1),
                "bars_loaded": len(df),
                "period": period,
                "last_close": _last(df["close"]),
                "levels": snap,
                "legend": {"donchian": "[upper, middle, lower]"},
            },
            indent=2,
            default=str,
        )
    except Exception as e:
        return f"Error getting support/resistance: {str(e)}"


@mcp.tool()
def detect_signals(
    symbol: str,
    exchange: str,
    interval: str = "D",
    start_date: str | None = None,
    end_date: str | None = None,
    signal_type: str = "ema_cross",
    fast: int = 20,
    slow: int = 50,
    period: int = 14,
    upper: float = 70.0,
    lower: float = 30.0,
    limit: int = 20,
    lookback_bars: int = 252,
    lookback_days: int | None = None,
    source: str = "api",
) -> str:
    """
    Detect technical signals over a symbol's history using ta crossover/threshold logic.

    Args:
        symbol: Stock symbol
        exchange: Exchange name
        interval: Candle interval (default 'D')
        start_date / end_date: YYYY-MM-DD. Optional — default to the lookback window.
        lookback_bars: Bars loaded when dates omitted (default 252).
        lookback_days: Alternative calendar-day lookback (e.g., 30). Overrides lookback_bars.
        signal_type: One of:
            'ema_cross'      - EMA(fast) crossing EMA(slow)
            'sma_cross'      - SMA(fast) crossing SMA(slow)
            'macd_cross'     - MACD line crossing its signal line
            'supertrend_flip'- Supertrend direction flip
            'rsi_threshold'  - RSI crossing out of oversold(lower) / overbought(upper)
        fast / slow: MA periods for ema_cross / sma_cross
        period: Lookback for rsi_threshold (default 14)
        upper / lower: RSI overbought / oversold levels (default 70 / 30)
        limit: Max number of most-recent signal events to return (default 20)

    Returns:
        JSON with recent events [{timestamp, signal: 'bullish'|'bearish'}] plus current values.
    """
    try:
        df = _load_history(
            symbol, exchange, interval, start_date, end_date, lookback_bars, lookback_days, source
        )
        close = df["close"]
        extra: dict[str, Any] = {}

        if signal_type in ("ema_cross", "sma_cross"):
            ma = ta.ema if signal_type == "ema_cross" else ta.sma
            f, s = ma(close, fast), ma(close, slow)
            bull = _as_bool(ta.crossover(f, s), df.index)
            bear = _as_bool(ta.crossunder(f, s), df.index)
            extra = {"fast": _last(f), "slow": _last(s)}
        elif signal_type == "macd_cross":
            line, sig, _hist = ta.macd(close)
            bull = _as_bool(ta.crossover(line, sig), df.index)
            bear = _as_bool(ta.crossunder(line, sig), df.index)
            extra = {"macd_line": _last(line), "signal_line": _last(sig)}
        elif signal_type == "supertrend_flip":
            st, d = ta.supertrend(df["high"], df["low"], close)
            d = pd.Series(list(d), index=df.index)
            bull = (d > 0) & (d.shift(1) <= 0)
            bear = (d < 0) & (d.shift(1) >= 0)
            bull, bear = bull.fillna(False), bear.fillna(False)
            extra = {"supertrend": _last(st), "direction": _last(d)}
        elif signal_type == "rsi_threshold":
            r = pd.Series(list(ta.rsi(close, period)), index=df.index)
            bull = (r > lower) & (r.shift(1) <= lower)
            bear = (r < upper) & (r.shift(1) >= upper)
            bull, bear = bull.fillna(False), bear.fillna(False)
            extra = {"rsi": _last(r)}
        else:
            return json.dumps(
                {"status": "error", "message": f"unknown signal_type '{signal_type}'"}, indent=2
            )

        def _stamp(ts):
            return ts.isoformat() if hasattr(ts, "isoformat") else str(ts)

        events = [{"timestamp": _stamp(ts), "signal": "bullish"} for ts, v in bull.items() if v]
        events += [{"timestamp": _stamp(ts), "signal": "bearish"} for ts, v in bear.items() if v]
        events.sort(key=lambda r: r["timestamp"])

        return json.dumps(
            {
                "symbol": symbol.upper(),
                "exchange": exchange.upper(),
                "interval": interval,
                "signal_type": signal_type,
                "last_close": _last(close),
                "current": extra,
                "event_count": len(events),
                "events": events[-limit:],
            },
            indent=2,
            default=str,
        )
    except Exception as e:
        return f"Error detecting signals: {str(e)}"


@mcp.tool()
def screen_instruments(
    symbols: list[dict[str, str]],
    interval: str = "D",
    start_date: str | None = None,
    end_date: str | None = None,
    condition: str = "rsi_below",
    value: float = 30.0,
    period: int = 14,
    lookback_bars: int = 252,
    lookback_days: int | None = None,
    source: str = "api",
) -> str:
    """
    Scan a watchlist of symbols for a technical condition.

    Note: this fetches history per symbol sequentially — keep the list modest (≤ ~25)
    or use a coarse interval to bound runtime and broker API calls.

    Args:
        symbols: List of {"symbol","exchange"} pairs.
            Example: [{"symbol":"RELIANCE","exchange":"NSE"},{"symbol":"INFY","exchange":"NSE"}]
        interval: Candle interval (default 'D')
        start_date / end_date: YYYY-MM-DD. Optional — default to the lookback window.
        lookback_bars: Bars loaded per symbol when dates omitted (default 252).
        lookback_days: Alternative calendar-day lookback (e.g., 30). Overrides lookback_bars.
        condition: One of:
            'rsi_below' / 'rsi_above'        - RSI(period) vs `value`
            'price_above_sma'/'price_below_sma' - last close vs SMA(period)
            'supertrend_bullish'/'supertrend_bearish' - current Supertrend direction
        value: Threshold for rsi conditions (default 30)
        period: Lookback for rsi / sma (default 14)

    Returns:
        JSON with per-symbol {passed, metric} and a count of matches.
    """
    try:
        results = []
        for item in symbols:
            sym, exch = item.get("symbol", ""), item.get("exchange", "")
            try:
                df = _load_history(
                    sym, exch, interval, start_date, end_date, lookback_bars, lookback_days, source
                )
                close = df["close"]
                metric: Any = None
                passed = False
                if condition in ("rsi_below", "rsi_above"):
                    metric = _last(ta.rsi(close, period))
                    if metric is not None:
                        passed = metric < value if condition == "rsi_below" else metric > value
                elif condition in ("price_above_sma", "price_below_sma"):
                    sma, c = _last(ta.sma(close, period)), _last(close)
                    metric = c
                    if sma is not None and c is not None:
                        passed = c > sma if condition == "price_above_sma" else c < sma
                elif condition in ("supertrend_bullish", "supertrend_bearish"):
                    _st, d = ta.supertrend(df["high"], df["low"], close)
                    metric = _last(pd.Series(list(d), index=df.index))
                    if metric is not None:
                        passed = metric > 0 if condition == "supertrend_bullish" else metric < 0
                else:
                    return json.dumps(
                        {"status": "error", "message": f"unknown condition '{condition}'"}, indent=2
                    )
                results.append(
                    {"symbol": sym.upper(), "exchange": exch.upper(), "passed": passed, "metric": metric}
                )
            except Exception as e:
                results.append({"symbol": sym, "exchange": exch, "error": str(e)})

        matched = [r for r in results if r.get("passed")]
        return json.dumps(
            {
                "condition": condition,
                "value": value,
                "period": period,
                "scanned": len(symbols),
                "matched": len(matched),
                "results": results,
            },
            indent=2,
            default=str,
        )
    except Exception as e:
        return f"Error screening instruments: {str(e)}"


@mcp.tool()
def multi_timeframe_analysis(
    symbol: str,
    exchange: str,
    start_date: str | None = None,
    end_date: str | None = None,
    intervals: list[str] | None = None,
    indicator: str = "rsi",
    params: dict[str, Any] | None = None,
    inputs: list[str] | None = None,
    lookback_bars: int = 252,
    lookback_days: int | None = None,
    source: str = "api",
) -> str:
    """
    Compute the same indicator across multiple timeframes for confluence analysis.

    Args:
        symbol: Stock symbol
        exchange: Exchange name
        start_date / end_date: YYYY-MM-DD. Optional — default to the lookback window per interval.
        intervals: List of intervals (default ['5m','15m','1h','D'])
        indicator: ta function name (default 'rsi')
        params: Extra keyword args for the indicator (e.g., {"period": 14})
        inputs: Ordered input columns; auto-detected if omitted.
        lookback_bars: Bars loaded per interval when dates omitted (default 252).
        lookback_days: Alternative calendar-day lookback (e.g., 30). Overrides lookback_bars.

    Returns:
        JSON with the latest indicator value (and last_close) per timeframe.
    """
    try:
        intervals = intervals or ["5m", "15m", "1h", "D"]
        name = indicator.lower()
        fn = getattr(ta, name, None)
        if fn is None:
            return json.dumps(
                {"status": "error", "message": f"unknown indicator '{indicator}'"}, indent=2
            )
        out: dict[str, Any] = {}
        for itv in intervals:
            try:
                df = _load_history(
                    symbol, exchange, itv, start_date, end_date, lookback_bars, lookback_days, source
                )
                _cols, args = _resolve_inputs(df, name, inputs)
                res = fn(*args, **(params or {}))
                value = [_last(s) for s in res] if isinstance(res, tuple) else _last(res)
                out[itv] = {"value": value, "last_close": _last(df["close"]), "bars": len(df)}
            except Exception as e:
                out[itv] = {"error": str(e)}
        return json.dumps(
            {
                "symbol": symbol.upper(),
                "exchange": exchange.upper(),
                "indicator": name,
                "params": params or {},
                "timeframes": out,
            },
            indent=2,
            default=str,
        )
    except Exception as e:
        return f"Error in multi-timeframe analysis: {str(e)}"


@mcp.tool()
def correlation_beta(
    symbol1: str,
    exchange1: str,
    symbol2: str,
    exchange2: str,
    interval: str = "D",
    start_date: str | None = None,
    end_date: str | None = None,
    period: int = 20,
    lookback_bars: int = 252,
    lookback_days: int | None = None,
    source: str = "api",
) -> str:
    """
    Correlation / Beta / Linear-regression slope between two symbols (pairs & hedge research).

    Both symbols' closes are aligned on common timestamps before computing.

    Args:
        symbol1 / exchange1: First instrument (the 'asset')
        symbol2 / exchange2: Second instrument (the 'market'/benchmark)
        interval: Candle interval (default 'D')
        start_date / end_date: YYYY-MM-DD. Optional — default to the lookback window.
        period: Rolling window for correlation/beta/slope (default 20)
        lookback_bars: Bars loaded per symbol when dates omitted (default 252).
        lookback_days: Alternative calendar-day lookback (e.g., 30). Overrides lookback_bars.

    Returns:
        JSON with rolling correlation, rolling beta, LR slope of symbol1, the full-sample
        Pearson correlation, and the number of overlapping bars.
    """
    try:
        df1 = _load_history(
            symbol1, exchange1, interval, start_date, end_date, lookback_bars, lookback_days, source
        )
        df2 = _load_history(
            symbol2, exchange2, interval, start_date, end_date, lookback_bars, lookback_days, source
        )
        j = pd.DataFrame({"a": df1["close"], "b": df2["close"]}).dropna()
        if len(j) < 2:
            return json.dumps(
                {"status": "error", "message": "insufficient overlapping bars between symbols"},
                indent=2,
            )
        p = min(period, len(j))
        metrics = _bundle(
            j,
            [
                ("correlation_rolling", lambda: ta.correlation(j["a"], j["b"], p)),
                ("beta_rolling", lambda: ta.beta(j["a"], j["b"], p)),
                ("lrslope_symbol1", lambda: ta.lrslope(j["a"], p)),
            ],
        )
        metrics["pearson_full_sample"] = round(float(j["a"].corr(j["b"])), 4)
        return json.dumps(
            {
                "symbol1": symbol1.upper(),
                "symbol2": symbol2.upper(),
                "interval": interval,
                "period": p,
                "overlapping_bars": len(j),
                "metrics": metrics,
            },
            indent=2,
            default=str,
        )
    except Exception as e:
        return f"Error calculating correlation/beta: {str(e)}"


if __name__ == "__main__":
    mcp.run(transport="stdio")
