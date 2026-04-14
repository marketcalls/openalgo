"""
Options Multi-Order Service

Places multiple option legs with common underlying, resolving symbols based on offset.
BUY legs are executed first, then SELL legs for margin efficiency.
Supports split orders per leg if splitsize is specified.
"""

import copy
import os
import time
from typing import Any, Dict, List, Optional, Tuple

from database.auth_db import get_auth_token_broker
from database.settings_db import get_analyze_mode
from events import AnalyzerErrorEvent, MultiOrderCompletedEvent
from services.option_symbol_service import get_option_symbol, parse_underlying_symbol
from services.place_order_service import place_order
from services.quotes_service import get_quotes
from utils.event_bus import bus
from utils.logging import get_logger

logger = get_logger(__name__)

# Maximum number of split orders per leg
MAX_SPLIT_ORDERS_PER_LEG = 100


# Get rate limit from environment (default: 10 per second)
def get_order_rate_limit():
    """Parse ORDER_RATE_LIMIT and return delay in seconds between orders"""
    rate_limit_str = os.getenv("ORDER_RATE_LIMIT", "10 per second")
    try:
        rate = int(rate_limit_str.split()[0])
        return 1.0 / rate if rate > 0 else 0.1
    except (ValueError, IndexError):
        return 0.1  # Default 100ms delay


def get_underlying_ltp(
    underlying: str, exchange: str, api_key: str
) -> tuple[bool, float | None, str]:
    """
    Fetch the LTP of the underlying symbol once.

    Args:
        underlying: Underlying symbol (e.g., "NIFTY", "NIFTY28OCT25FUT")
        exchange: Exchange (e.g., "NSE_INDEX", "NSE", "NFO")
        api_key: OpenAlgo API key

    Returns:
        Tuple of (success, ltp, error_message)
    """
    try:
        # Parse underlying to get base symbol
        base_symbol, embedded_expiry = parse_underlying_symbol(underlying)

        # Determine the quote exchange (where to fetch LTP from)
        quote_exchange = exchange
        if exchange.upper() in ["NFO", "BFO"]:
            # User passed options exchange, need to map back to index/equity
            if base_symbol in [
                "NIFTY",
                "BANKNIFTY",
                "FINNIFTY",
                "MIDCPNIFTY",
                "NIFTYNXT50",
                "INDIAVIX",
            ]:
                quote_exchange = "NSE_INDEX"
            elif base_symbol in ["SENSEX", "BANKEX", "SENSEX50"]:
                quote_exchange = "BSE_INDEX"
            else:
                # Assume it's an equity symbol
                quote_exchange = "NSE" if exchange.upper() == "NFO" else "BSE"

        # For MCX/CDS: no spot symbol exists, so use the full futures symbol for LTP
        # For NSE/BSE: use base symbol (spot/index symbol exists)
        if embedded_expiry:
            if exchange.upper() in ["MCX", "CDS"]:
                quote_symbol = underlying.upper()
            else:
                quote_symbol = base_symbol
        else:
            quote_symbol = underlying

        logger.info(f"Fetching LTP once for: {quote_symbol} on {quote_exchange}")

        success, quote_response, status_code = get_quotes(
            symbol=quote_symbol, exchange=quote_exchange, api_key=api_key
        )

        if not success:
            error_msg = quote_response.get("message", "Unknown error")
            logger.error(f"Failed to fetch LTP for {quote_symbol}: {error_msg}")
            return False, None, f"Failed to fetch LTP for {quote_symbol}. {error_msg}"

        # Extract LTP from quote response
        ltp = quote_response.get("data", {}).get("ltp")
        if ltp is None:
            logger.error(f"LTP not found in quote response for {quote_symbol}")
            return False, None, f"Could not determine LTP for {quote_symbol}"

        logger.info(f"Got LTP: {ltp} for {quote_symbol} (single fetch)")
        return True, ltp, ""

    except Exception as e:
        logger.exception(f"Error fetching underlying LTP: {e}")
        return False, None, str(e)


def emit_analyzer_error(request_data: dict[str, Any], error_message: str) -> dict[str, Any]:
    """Helper function to emit analyzer error events via the event bus."""
    error_response = {"mode": "analyze", "status": "error", "message": error_message}

    analyzer_request = request_data.copy()
    if "apikey" in analyzer_request:
        del analyzer_request["apikey"]
    analyzer_request["api_type"] = "optionsmultiorder"

    bus.publish(AnalyzerErrorEvent(
        mode="analyze",
        api_type="optionsmultiorder",
        request_data=analyzer_request,
        response_data=error_response,
        error_message=error_message,
        api_key=request_data.get("apikey", ""),
    ))

    return error_response


def place_single_split_order_for_leg(
    order_data: dict[str, Any],
    api_key: str,
    order_num: int,
    total_orders: int,
    auth_token: str | None = None,
    broker: str | None = None,
    prefetched_quote: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Place a single split order for a leg and return result.

    Args:
        order_data: Order data with symbol, exchange, action, quantity, etc.
        api_key: OpenAlgo API key
        order_num: Order number in the split sequence
        total_orders: Total number of split orders
        auth_token: Direct broker auth token (optional)
        broker: Broker name (optional)
        prefetched_quote: Pre-fetched quote for sandbox batch optimization (optional)

    Returns:
        Result dictionary with order status
    """
    try:
        # Pass emit_event=False to suppress per-order socket events
        # A summary event is emitted at the end of all legs
        success, order_response, status_code = place_order(
            order_data=order_data,
            api_key=api_key,
            auth_token=auth_token,
            broker=broker,
            emit_event=False,
            prefetched_quote=prefetched_quote,
        )

        if success:
            return {
                "order_num": order_num,
                "quantity": int(order_data["quantity"]),
                "status": "success",
                "orderid": order_response.get("orderid"),
            }
        else:
            return {
                "order_num": order_num,
                "quantity": int(order_data["quantity"]),
                "status": "error",
                "message": order_response.get("message", "Failed to place order"),
            }
    except Exception as e:
        logger.exception(f"Error placing split order {order_num} for leg: {e}")
        return {
            "order_num": order_num,
            "quantity": int(order_data["quantity"]),
            "status": "error",
            "message": "Failed to place order due to internal error",
        }


def resolve_and_place_leg(
    leg_data: dict[str, Any],
    common_data: dict[str, Any],
    api_key: str,
    leg_index: int,
    total_legs: int,
    auth_token: str | None = None,
    broker: str | None = None,
    underlying_ltp: float | None = None,
    leg_quote_cache: dict[tuple[str, str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Resolve option symbol and place order for a single leg.
    Supports split orders if splitsize is specified in leg_data.

    Args:
        leg_data: Leg-specific data (offset, option_type, action, quantity, splitsize, etc.)
        common_data: Common data (underlying, exchange, expiry_date, strike_int, strategy)
        api_key: OpenAlgo API key
        leg_index: Index of this leg
        total_legs: Total number of legs
        auth_token: Direct broker auth token (optional)
        broker: Broker name (optional)
        underlying_ltp: Pre-fetched underlying LTP to avoid redundant quote requests
        leg_quote_cache: Pre-fetched quotes keyed by (symbol, exchange) for sandbox batch optimization

    Returns:
        Result dictionary with leg details and order status
    """
    try:
        # Step 1: Resolve option symbol
        # Use leg-specific expiry_date if provided, otherwise fall back to common expiry_date
        leg_expiry = leg_data.get("expiry_date") or common_data.get("expiry_date")

        success, symbol_response, status_code = get_option_symbol(
            underlying=common_data.get("underlying"),
            exchange=common_data.get("exchange"),
            expiry_date=leg_expiry,
            strike_int=common_data.get("strike_int"),
            offset=leg_data.get("offset"),
            option_type=leg_data.get("option_type"),
            api_key=api_key,
            underlying_ltp=underlying_ltp,
        )

        if not success:
            return {
                "leg": leg_index + 1,
                "offset": leg_data.get("offset"),
                "option_type": leg_data.get("option_type", "").upper(),
                "action": leg_data.get("action", "").upper(),
                "status": "error",
                "message": symbol_response.get("message", "Failed to resolve option symbol"),
            }

        resolved_symbol = symbol_response.get("symbol")
        resolved_exchange = symbol_response.get("exchange")
        underlying_ltp = symbol_response.get("underlying_ltp")

        # Check if split order is requested for this leg
        splitsize = leg_data.get("splitsize", 0) or 0
        total_quantity = int(leg_data.get("quantity", 0))

        # Step 2: Handle split orders if splitsize > 0
        if splitsize > 0:
            # Validate split parameters
            num_full_orders = total_quantity // splitsize
            remaining_qty = total_quantity % splitsize
            total_split_orders = num_full_orders + (1 if remaining_qty > 0 else 0)

            if total_split_orders > MAX_SPLIT_ORDERS_PER_LEG:
                return {
                    "leg": leg_index + 1,
                    "symbol": resolved_symbol,
                    "exchange": resolved_exchange,
                    "offset": leg_data.get("offset"),
                    "option_type": leg_data.get("option_type", "").upper(),
                    "action": leg_data.get("action", "").upper(),
                    "status": "error",
                    "message": f"Split orders would exceed maximum limit of {MAX_SPLIT_ORDERS_PER_LEG} per leg",
                }

            logger.info(
                f"Split order for leg {leg_index + 1}: total_qty={total_quantity}, "
                f"splitsize={splitsize}, orders={total_split_orders}"
            )

            # Base order data template - include underlying_ltp for execution reference
            base_order_data = {
                "apikey": api_key,
                "strategy": common_data.get("strategy"),
                "exchange": resolved_exchange,
                "symbol": resolved_symbol,
                "action": leg_data.get("action"),
                "pricetype": leg_data.get("pricetype", "MARKET"),
                "product": leg_data.get("product", "MIS"),
                "price": leg_data.get("price", 0.0),
                "trigger_price": leg_data.get("trigger_price", 0.0),
                "disclosed_quantity": leg_data.get("disclosed_quantity", 0),
                "underlying_ltp": underlying_ltp,  # Pass LTP for execution reference
            }

            # Process split orders sequentially with rate limiting
            split_results = []
            order_delay = get_order_rate_limit()

            # Look up pre-fetched quote for this resolved option symbol
            prefetched = (leg_quote_cache or {}).get((resolved_symbol, resolved_exchange))

            # Place full-size orders
            for i in range(num_full_orders):
                if i > 0:
                    time.sleep(order_delay)  # Rate limit delay between orders
                order_data = copy.deepcopy(base_order_data)
                order_data["quantity"] = splitsize
                result = place_single_split_order_for_leg(
                    order_data, api_key, i + 1, total_split_orders, auth_token, broker,
                    prefetched_quote=prefetched,
                )
                split_results.append(result)

            # Place remaining quantity order if any
            if remaining_qty > 0:
                if num_full_orders > 0:
                    time.sleep(order_delay)  # Rate limit delay
                order_data = copy.deepcopy(base_order_data)
                order_data["quantity"] = remaining_qty
                result = place_single_split_order_for_leg(
                    order_data, api_key, total_split_orders, total_split_orders, auth_token, broker,
                    prefetched_quote=prefetched,
                )
                split_results.append(result)

            # Determine overall status
            successful_orders = sum(1 for r in split_results if r.get("status") == "success")
            overall_status = "success" if successful_orders > 0 else "error"

            return {
                "leg": leg_index + 1,
                "symbol": resolved_symbol,
                "exchange": resolved_exchange,
                "offset": leg_data.get("offset"),
                "option_type": leg_data.get("option_type", "").upper(),
                "action": leg_data.get("action", "").upper(),
                "status": overall_status,
                "total_quantity": total_quantity,
                "split_size": splitsize,
                "split_results": split_results,
                "mode": "analyze" if get_analyze_mode() else "live",
            }

        # Step 2 (non-split): Construct regular order data - include underlying_ltp for execution reference
        order_data = {
            "apikey": api_key,
            "strategy": common_data.get("strategy"),
            "exchange": resolved_exchange,
            "symbol": resolved_symbol,
            "action": leg_data.get("action"),
            "quantity": leg_data.get("quantity"),
            "pricetype": leg_data.get("pricetype", "MARKET"),
            "product": leg_data.get("product", "MIS"),
            "price": leg_data.get("price", 0.0),
            "trigger_price": leg_data.get("trigger_price", 0.0),
            "disclosed_quantity": leg_data.get("disclosed_quantity", 0),
            "underlying_ltp": underlying_ltp,  # Pass LTP for execution reference
        }

        # Step 3: Place the order
        # Pass emit_event=False to suppress per-leg socket events
        # A summary event is emitted at the end of all legs
        # Look up pre-fetched quote for this resolved option symbol
        prefetched = (leg_quote_cache or {}).get((resolved_symbol, resolved_exchange))
        success, order_response, status_code = place_order(
            order_data=order_data,
            api_key=api_key,
            auth_token=auth_token,
            broker=broker,
            emit_event=False,
            prefetched_quote=prefetched,
        )

        if success:
            result = {
                "leg": leg_index + 1,
                "symbol": resolved_symbol,
                "exchange": resolved_exchange,
                "offset": leg_data.get("offset"),
                "option_type": leg_data.get("option_type", "").upper(),
                "action": leg_data.get("action", "").upper(),
                "status": "success",
                "orderid": order_response.get("orderid"),
                "mode": order_response.get("mode", "live"),
            }

            # Note: Toast notification is emitted once at the end of multiorder processing
            # to avoid multiple toast messages for each leg

            return result
        else:
            return {
                "leg": leg_index + 1,
                "symbol": resolved_symbol,
                "exchange": resolved_exchange,
                "offset": leg_data.get("offset"),
                "option_type": leg_data.get("option_type", "").upper(),
                "action": leg_data.get("action", "").upper(),
                "status": "error",
                "message": order_response.get("message", "Order placement failed"),
            }

    except Exception as e:
        logger.exception(f"Error processing leg {leg_index + 1}: {e}")
        return {
            "leg": leg_index + 1,
            "offset": leg_data.get("offset", "Unknown"),
            "option_type": leg_data.get("option_type", "").upper(),
            "action": leg_data.get("action", "").upper(),
            "status": "error",
            "message": f"Internal error: {str(e)}",
        }


def process_multiorder_with_auth(
    multiorder_data: dict[str, Any],
    auth_token: str,
    broker: str,
    api_key: str,
    original_data: dict[str, Any],
) -> tuple[bool, dict[str, Any], int]:
    """
    Process options multi-order with provided authentication.
    BUY legs execute first, then SELL legs.
    """
    # Prepare common data
    common_data = {
        "underlying": multiorder_data.get("underlying"),
        "exchange": multiorder_data.get("exchange"),
        "expiry_date": multiorder_data.get("expiry_date"),
        "strike_int": multiorder_data.get("strike_int"),
        "strategy": multiorder_data.get("strategy"),
    }

    legs = multiorder_data.get("legs", [])
    total_legs = len(legs)

    # Separate BUY and SELL legs
    buy_legs = [(i, leg) for i, leg in enumerate(legs) if leg.get("action", "").upper() == "BUY"]
    sell_legs = [(i, leg) for i, leg in enumerate(legs) if leg.get("action", "").upper() == "SELL"]

    results = []
    underlying_ltp = None

    # Fetch underlying LTP once (single quote fetch for all legs)
    if legs:
        underlying = common_data.get("underlying")
        exchange = common_data.get("exchange")
        success, ltp, error_msg = get_underlying_ltp(underlying, exchange, api_key)
        if success:
            underlying_ltp = ltp
            logger.info(f"Using single LTP fetch for all legs: {underlying_ltp}")
        else:
            logger.warning(f"Failed to fetch underlying LTP: {error_msg}. Will retry per leg.")

    # Check if any leg has splitsize > 0 (requires delay between orders)
    has_split_orders = any(leg.get("splitsize", 0) > 0 for _, leg in buy_legs + sell_legs)
    order_delay = get_order_rate_limit() if has_split_orders else 0

    # Pre-fetch quotes for all legs in sandbox mode via single multiquotes call.
    # Each leg has a different option symbol — without this, each leg would make
    # its own REST API quote call (~300-500ms each).
    leg_quote_cache = {}
    if get_analyze_mode():
        try:
            # Resolve all option symbols first (DB lookups, fast)
            resolved_symbols = []
            for _, leg in buy_legs + sell_legs:
                leg_expiry = leg.get("expiry_date") or common_data.get("expiry_date")
                success_sym, sym_response, _ = get_option_symbol(
                    underlying=common_data.get("underlying"),
                    exchange=common_data.get("exchange"),
                    expiry_date=leg_expiry,
                    strike_int=common_data.get("strike_int"),
                    offset=leg.get("offset"),
                    option_type=leg.get("option_type"),
                    api_key=api_key,
                    underlying_ltp=underlying_ltp,
                )
                if success_sym:
                    sym = sym_response.get("symbol")
                    exch = sym_response.get("exchange")
                    if sym and exch:
                        resolved_symbols.append({"symbol": sym, "exchange": exch})

            # Batch-fetch all option quotes in one multiquotes call
            if resolved_symbols:
                from services.quotes_service import get_multiquotes
                success_mq, mq_response, _ = get_multiquotes(
                    symbols=resolved_symbols, api_key=api_key
                )
                if success_mq and "results" in mq_response:
                    for result in mq_response["results"]:
                        sym = result.get("symbol")
                        exch = result.get("exchange")
                        data = result.get("data")
                        if sym and exch and data:
                            leg_quote_cache[(sym, exch)] = data
                    logger.info(
                        f"Pre-fetched {len(leg_quote_cache)} option quotes for multiorder"
                    )
        except Exception as e:
            logger.debug(f"Multiquotes pre-fetch failed for multiorder, falling back to per-leg fetch: {e}")

    # Process all legs sequentially (avoids ThreadPoolExecutor + eventlet hang)
    # Process BUY legs first
    for i, (orig_idx, leg) in enumerate(buy_legs):
        if order_delay and i > 0:
            time.sleep(order_delay)
        result = resolve_and_place_leg(
            leg, common_data, api_key, orig_idx, total_legs, auth_token, broker, underlying_ltp,
            leg_quote_cache=leg_quote_cache,
        )
        if result:
            results.append(result)

    # Then process SELL legs
    for i, (orig_idx, leg) in enumerate(sell_legs):
        if order_delay and (i > 0 or buy_legs):
            time.sleep(order_delay)
        result = resolve_and_place_leg(
            leg, common_data, api_key, orig_idx, total_legs, auth_token, broker, underlying_ltp,
            leg_quote_cache=leg_quote_cache,
        )
        if result:
            results.append(result)

    # Sort results by leg number
    results.sort(key=lambda x: x.get("leg", 0))

    # Count successful and failed legs
    successful_legs = sum(1 for r in results if r.get("status") == "success")
    failed_legs = len(results) - successful_legs

    # Build response
    mode = "analyze" if get_analyze_mode() else "live"
    response_data = {
        "status": "success",
        "underlying": common_data.get("underlying"),
        "underlying_ltp": underlying_ltp,
        "results": results,
    }

    # Add mode if in analyze mode
    if get_analyze_mode():
        response_data["mode"] = "analyze"

    # Prepare request data for logging (without apikey)
    request_log = original_data.copy()
    if "apikey" in request_log:
        del request_log["apikey"]
    request_log["api_type"] = "optionsmultiorder"

    bus.publish(MultiOrderCompletedEvent(
        mode=mode,
        api_type="optionsmultiorder",
        strategy=common_data.get("strategy", ""),
        underlying=common_data.get("underlying", ""),
        exchange=common_data.get("exchange", ""),
        results=results,
        successful_legs=successful_legs,
        failed_legs=failed_legs,
        total=len(results),
        request_data=request_log,
        response_data=response_data,
        api_key=api_key or "",
    ))

    return True, response_data, 200


def place_options_multiorder(
    multiorder_data: dict[str, Any],
    api_key: str | None = None,
    auth_token: str | None = None,
    broker: str | None = None,
) -> tuple[bool, dict[str, Any], int]:
    """
    Place multiple option legs with common underlying.
    BUY legs are executed first for margin efficiency.

    Args:
        multiorder_data: Multi-order data containing underlying, exchange, legs, etc.
        api_key: OpenAlgo API key (for API-based calls)
        auth_token: Direct broker auth token (for internal calls)
        broker: Broker name (for internal calls)

    Returns:
        Tuple containing:
        - Success status (bool)
        - Response data (dict)
        - HTTP status code (int)
    """
    original_data = copy.deepcopy(multiorder_data)
    if api_key:
        original_data["apikey"] = api_key
        multiorder_data["apikey"] = api_key

    # Validate legs exist
    legs = multiorder_data.get("legs", [])
    if not legs:
        error_msg = "No legs provided in the request"
        if get_analyze_mode():
            return False, emit_analyzer_error(original_data, error_msg), 400
        return False, {"status": "error", "message": error_msg}, 400

    # Case 1: API-based authentication
    if api_key and not (auth_token and broker):
        # Check if order should be routed to Action Center
        from services.order_router_service import queue_order, should_route_to_pending

        if should_route_to_pending(api_key, "optionsmultiorder"):
            return queue_order(api_key, original_data, "optionsmultiorder")

        AUTH_TOKEN, broker_name = get_auth_token_broker(api_key)
        if AUTH_TOKEN is None:
            error_response = {"status": "error", "message": "Invalid openalgo apikey"}
            return False, error_response, 403

        return process_multiorder_with_auth(
            multiorder_data, AUTH_TOKEN, broker_name, api_key, original_data
        )

    # Case 2: Direct internal call
    elif auth_token and broker:
        return process_multiorder_with_auth(
            multiorder_data, auth_token, broker, api_key or "", original_data
        )

    # Case 3: Invalid parameters
    else:
        error_response = {
            "status": "error",
            "message": "Either api_key or both auth_token and broker must be provided",
        }
        return False, error_response, 400
