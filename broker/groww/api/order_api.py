import datetime
import json
import math
import os
import re
import uuid
from datetime import datetime
import threading
import time

from broker.groww.database.master_contract_db import (
    format_groww_to_openalgo_symbol,
    format_openalgo_to_groww_symbol,
)
from broker.groww.mapping.transform_data import (
    EXCHANGE_BSE,
    EXCHANGE_NSE,
    ORDER_STATUS_ACKED,
    ORDER_STATUS_APPROVED,
    ORDER_STATUS_CANCELLED,
    ORDER_STATUS_NEW,
    ORDER_TYPE_LIMIT,
    ORDER_TYPE_MARKET,
    ORDER_TYPE_SL,
    ORDER_TYPE_SLM,
    PRODUCT_CNC,
    PRODUCT_MIS,
    PRODUCT_NRML,
    SEGMENT_CASH,
    SEGMENT_FNO,
    openalgo_exchange,
    TRANSACTION_TYPE_BUY,
    TRANSACTION_TYPE_SELL,
    # Constants
    VALIDITY_DAY,
    VALIDITY_IOC,
    map_exchange,
    map_exchange_type,
    map_order_type,
    map_product_type,
    map_segment_type,
    map_transaction_type,
    map_validity,
    reverse_map_product_type,
    # Functions
    transform_data,
    transform_modify_order_data,
)
from database.auth_db import get_auth_token
from database.token_db import get_br_symbol, get_oa_symbol, get_symbol, get_token
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger
from utils.position_read import (
    PositionReadError,
    read_position_book,
    refuse_smart_order_on_read_failure,
    says_no_positions,
)
from utils.smart_order_guard import PositionBookCache, SymbolLocks

logger = get_logger(__name__)

# API Endpoints
GROWW_BASE_URL = "https://api.groww.in"
GROWW_ORDER_LIST_URL = f"{GROWW_BASE_URL}/v1/order/list"
GROWW_PLACE_ORDER_URL = f"{GROWW_BASE_URL}/v1/order/create"
GROWW_MODIFY_ORDER_URL = f"{GROWW_BASE_URL}/v1/order/modify"
GROWW_CANCEL_ORDER_URL = f"{GROWW_BASE_URL}/v1/order/cancel"
GROWW_ORDER_TRADES_URL = f"{GROWW_BASE_URL}/v1/order/trades"


# Groww's documented page size limits (04-orders)
_ORDER_LIST_PAGE_SIZE = 100
_TRADES_PAGE_SIZE = 50


def _groww_headers(auth):
    """Headers Groww requires on every request (01-introduction)."""
    return {
        "Authorization": f"Bearer {auth}",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-API-VERSION": "1.0",
    }


def _get_paged(client, url, headers, params, list_key, page_size):
    """Read every page of a Groww list endpoint.

    Returns:
        tuple: (items, None) on success, or (items read so far, reason) when a
        page failed. A short page ends the list.
    """
    items, page = [], 0
    while True:
        resp = client.get(url, headers=headers, params={**params, "page": page, "page_size": page_size})
        try:
            body = resp.json()
        except ValueError:
            body = None
        if resp.status_code != 200 or not isinstance(body, dict) or body.get("status") != "SUCCESS":
            return items, _groww_error_message(body, f"HTTP {resp.status_code}")
        batch = (body.get("payload") or {}).get(list_key) or []
        items.extend(batch)
        if len(batch) < page_size:
            return items, None
        page += 1


def direct_get_order_book(auth):
    """
    Read the day's orders from both segments (GET /v1/order/list).

    Each order keeps Groww's documented fields and gains OpenAlgo's exchange
    (NSE/BSE/NFO/BFO) and symbol.

    Returns:
        dict: {"data": orders, ...}, or {"status": "error", "message": ...}
        when the CASH book cannot be read. An FNO read that fails is logged
        and skipped, as for positions: it fails on accounts without F&O.
    """
    try:
        client = get_httpx_client()
        headers = _groww_headers(auth)
        all_orders = []
        for segment in (SEGMENT_CASH, SEGMENT_FNO):
            orders, failure = _get_paged(
                client,
                GROWW_ORDER_LIST_URL,
                headers,
                {"segment": segment},
                "order_list",
                _ORDER_LIST_PAGE_SIZE,
            )
            if failure and not says_no_positions({"message": failure}):
                if segment == SEGMENT_CASH:
                    logger.error(f"Groww order list (CASH) could not be read: {failure}")
                    return {
                        "status": "error",
                        "message": f"Could not read the Groww order book: {failure}",
                    }
                logger.warning(f"Groww order list (FNO) could not be read, skipped: {failure}")
            all_orders.extend(orders)

        # Map each order to OpenAlgo's exchange and symbol. Groww reports exchange
        # NSE/BSE plus segment CASH/FNO (04-orders "List orders"); OpenAlgo puts
        # F&O on NFO/BFO. The OpenAlgo symbol comes from the master contract.
        for order in all_orders:
            if "trading_symbol" not in order:
                continue
            groww_symbol = order["trading_symbol"]
            groww_exchange = order.get("exchange", "")
            order["brsymbol"] = groww_symbol
            order["brexchange"] = groww_exchange
            exchange = openalgo_exchange(groww_exchange, order.get("segment", ""))
            order["exchange"] = exchange
            order["symbol"] = get_oa_symbol(groww_symbol, exchange) or groww_symbol

        logger.debug(f"Groww order book: {len(all_orders)} orders")
        return {"data": all_orders, "order_list": all_orders}

    except Exception:
        logger.exception("Error fetching the Groww order book")
        return {
            "status": "error",
            "message": "Could not reach Groww to read the order book. Try again shortly.",
        }


def get_order_book(auth):
    """
    Get list of orders for the user from both CASH and FNO segments
    Using direct API implementation only (no SDK fallback)

    Args:
        auth (str): Authentication token

    Returns:
        dict: Order book data with combined orders from all segments
    """
    logger.debug("Using direct API implementation for get_order_book")
    return direct_get_order_book(auth)


def groww_position_prices(position):
    """
    The three prices OpenAlgo reports for a Groww position, in rupees.

    Groww documents every price on a position in rupees: `net_price` as "Net
    average price in rupees of instruments", `credit_price` and `debit_price`
    as the average price in rupees of credited and debited instruments. They
    are carried through unchanged.

    Two conversions used to stand here. `credit_price` and `debit_price` were
    divided by 100 unconditionally, so a Rs 433.00 entry was reported as
    Rs 4.33 on every position. `net_price` was divided only above 1000, which
    left the scale discontinuous: Rs 1,000 came back as Rs 1,000 and Rs 1,001
    as Rs 10.01. The same value-based conversion was removed from the
    tradebook in #1995; holdings in this file never had one.

    Args:
        position (dict): One entry from Groww's positions payload.

    Returns:
        dict: average_price, buy_price and sell_price in rupees.
    """

    def rupees(key):
        try:
            value = float(position.get(key) or 0)
        except (TypeError, ValueError):
            return 0
        # float() accepts NaN and infinities, but these are not valid prices
        # and can produce invalid JSON in the positions response.
        return value if math.isfinite(value) else 0

    sell_price = rupees("debit_price")
    return {
        "average_price": rupees("net_price"),
        "buy_price": rupees("credit_price"),
        # A position with nothing sold reports 0 rather than a price.
        "sell_price": sell_price if sell_price > 0 else 0,
    }


def transform_groww_trade(trade):
    """
    Transform one normalised Groww trade into the shape map_trade_data and
    transform_tradebook_data expect.

    Groww reports the trade `price` in rupees, so it is carried through as-is.
    An earlier value-based "paise to rupees" conversion divided any price above
    100 by 100, which turned a genuine Rs 433.00 fill into Rs 4.33 and left the
    scale discontinuous at Rs 100. Synthetic trades built from the order book
    take their price from the same rupee-denominated source, so they were
    corrupted the same way.

    Args:
        trade (dict): Trade as returned by get_order_trades(), or a synthetic
            trade assembled from an executed order.

    Returns:
        dict: Trade in OpenAlgo's tradebook format.
    """
    price = trade.get("price", 0)

    return {
        # Fields expected by OpenAlgo's UI
        "tradingSymbol": trade.get("symbol", ""),  # Capitalized for exact matching
        "exchangeSegment": trade.get("exchange", ""),
        "productType": trade.get("product", ""),
        "transactionType": trade.get("transaction_type", ""),
        "tradedQuantity": trade.get("quantity", 0),
        "tradedPrice": price,
        "orderId": trade.get("order_id", ""),
        "updateTime": trade.get("trade_date_time", ""),
        "tradeId": trade.get("trade_id", ""),
        # Include additional fields that might be needed
        "trade_id": trade.get("trade_id", ""),
        "order_id": trade.get("order_id", ""),
        "exchange": trade.get("exchange", ""),
        "segment": trade.get("segment", ""),
        "symbol": trade.get("symbol", ""),
        "quantity": trade.get("quantity", 0),
        "price": price,
        "transaction_type": trade.get("transaction_type", ""),
        "trade_date_time": trade.get("trade_date_time", ""),
        "created_at": trade.get("created_at", ""),
        "status": trade.get("trade_status", "EXECUTED"),
    }


def get_trade_book(auth):
    """
    Every fill of the day, read from Groww's trades endpoint per filled order.

    Groww has no account-wide trade list, so the order book names the orders
    that filled (filled_quantity > 0, 04-orders "List orders") and
    get_order_trades reads each one's fills. Nothing is synthesised: if Groww
    cannot return an order's trades, the tradebook reports an error rather
    than inventing a fill.

    Returns:
        dict: {"status": "success", "data": trades} with each trade already
        transformed by transform_groww_trade, or {"status": "error", "message"}.
    """
    book = get_order_book(auth)
    if book.get("status") == "error":
        return book

    trades, failed = [], []
    for order in book.get("data", []):
        try:
            filled = float(order.get("filled_quantity") or 0)
        except (TypeError, ValueError):
            filled = 0
        orderid = order.get("groww_order_id")
        if filled <= 0 or not orderid:
            continue
        result, status_code = get_order_trades(orderid, auth, order.get("segment"))
        if status_code != 200:
            failed.append(orderid)
            logger.error(f"Groww trades for order {orderid} could not be read: {result.get('message')}")
            continue
        trades.extend(result["trades"])

    if failed:
        return {
            "status": "error",
            "message": f"Groww did not return the trades for {len(failed)} filled order(s). "
            "Try again shortly; the order book shows their fills.",
        }
    return {"status": "success", "data": [transform_groww_trade(t) for t in trades]}


def _fno_read_failure(response):
    """Say why the FNO position read failed, or return None when it worked.

    A SUCCESS answer is a read, whatever it holds, as it is for CASH, and so is
    an answer whose message says the book is empty. Anything else is a failure.
    """
    try:
        body = response.json()
    except Exception:
        body = None
    if response.status_code == 200 and isinstance(body, dict) and body.get("status") == "SUCCESS":
        return None
    if says_no_positions(body, ("error.message", "message")):
        return None
    shown = body if body is not None else response.text
    return f"FNO segment: HTTP {response.status_code}, {str(shown)[:200]}"


# The query segment that holds each exchange's positions.
_SEGMENT_BY_EXCHANGE = {"NSE": "CASH", "BSE": "CASH", "NFO": "FNO", "BFO": "FNO"}


def get_positions(auth, strict=False):
    """
    Get current positions for the user using direct API calls to Groww API
    Uses the /v1/positions/user endpoint as documented

    Args:
        auth (str): Authentication token
        strict (bool): Report a CASH segment that could not be read as an
            error instead of an empty book, which is what the smart order needs.
            An FNO read that fails does not fail the whole read: this code has
            always expected it to fail on some accounts, and refusing every
            smart order on an account without F&O would be the wrong trade.
            The CASH rows come back with "failed_segments": ["FNO"], so a smart
            order in NFO or BFO is refused while one in NSE or BSE goes ahead.

    Returns:
        tuple: (positions data, status code)
    """
    try:
        logger.debug("Using direct API implementation for get_positions")

        # Prepare the API client and headers
        client = get_httpx_client()
        headers = {
            "Authorization": f"Bearer {auth}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        # Groww API endpoint for positions - using documented endpoint
        positions_url = f"{GROWW_BASE_URL}/v1/positions/user"

        # Get both CASH and FNO segments
        params = {
            "segment": "CASH"  # Default to CASH segment
        }

        # Log the request details (with redacted auth token)
        logger.debug("-------- GET POSITIONS REQUEST --------")
        logger.debug(f"API URL: {positions_url}")
        logger.debug(f"Request parameters: {params}")
        logger.debug(
            'Request headers: {\n  "Authorization": "Bearer ***REDACTED***",\n  "Accept": "application/json",\n  "Content-Type": "application/json"\n}'
        )

        # Make the API call for CASH segment
        response_obj = client.get(positions_url, params=params, headers=headers, timeout=30)

        # Log the response status
        logger.debug("-------- GET POSITIONS RESPONSE --------")
        logger.debug(f"Response status code: {response_obj.status_code}")

        # Parse the response
        all_positions = []
        failures = []

        try:
            # Parse CASH segment response
            response_data = response_obj.json()
            logger.debug(
                f"Raw CASH positions response: {json.dumps(response_data, indent=2)[:1000]}..."
            )

            # Process the response to extract position information
            if response_obj.status_code == 200 and response_data.get("status") == "SUCCESS":
                # Extract positions from the payload based on the documented format
                if "payload" in response_data and "positions" in response_data["payload"]:
                    raw_positions = response_data["payload"]["positions"]
                    logger.debug(f"Found {len(raw_positions)} positions in CASH segment")

                    # Transform positions to match OpenAlgo's expected format
                    for position in raw_positions:
                        # Calculate net quantities
                        buy_qty = position.get("credit_quantity", 0) + position.get(
                            "carry_forward_credit_quantity", 0
                        )
                        sell_qty = position.get("debit_quantity", 0) + position.get(
                            "carry_forward_debit_quantity", 0
                        )
                        net_qty = position.get("quantity", buy_qty - sell_qty)

                        prices = groww_position_prices(position)
                        avg_price = prices["average_price"]

                        # Get the trading symbol
                        groww_symbol = position.get("trading_symbol", "")
                        openalgo_symbol = groww_symbol
                        symbol_converted = False

                        # Handle symbol conversion for consistency with orderbook
                        # This is primarily for FNO instruments, but we'll check all symbols
                        try:
                            # Import get_oa_symbol from token_db with fallback paths
                            try:
                                from database.token_db import get_oa_symbol
                            except ImportError:
                                from openalgo.database.token_db import get_oa_symbol

                            # First try database lookup for any symbol
                            db_symbol = get_oa_symbol(groww_symbol, "NFO")
                            if db_symbol:
                                openalgo_symbol = db_symbol
                                logger.debug(
                                    f"Database: Converted Groww symbol: {groww_symbol} -> {openalgo_symbol}"
                                )
                                symbol_converted = True
                            else:
                                # Pattern matching fallbacks if database lookup fails
                                # 1. Try option pattern
                                option_pattern = re.compile(
                                    r"([A-Z]+)(\d{2})(\d{2})(\d{2})(\d+)([CP]E)"
                                )
                                option_match = option_pattern.match(groww_symbol)

                                if option_match:
                                    # Extract components
                                    symbol_name, year, month_num, day, strike, option_type = (
                                        option_match.groups()
                                    )

                                    # Convert numeric month to alphabetic
                                    months = [
                                        "JAN",
                                        "FEB",
                                        "MAR",
                                        "APR",
                                        "MAY",
                                        "JUN",
                                        "JUL",
                                        "AUG",
                                        "SEP",
                                        "OCT",
                                        "NOV",
                                        "DEC",
                                    ]
                                    month_name = (
                                        months[int(month_num) - 1]
                                        if 1 <= int(month_num) <= 12
                                        else f"M{month_num}"
                                    )

                                    # Format as OpenAlgo expects: NIFTY15MAY2526650CE
                                    openalgo_symbol = (
                                        f"{symbol_name}{day}{month_name}{year}{strike}{option_type}"
                                    )
                                    logger.debug(
                                        f"Pattern: Converted Groww option symbol: {groww_symbol} -> {openalgo_symbol}"
                                    )
                                    symbol_converted = True
                                else:
                                    # 2. Try futures pattern
                                    future_pattern = re.compile(
                                        r"([A-Z]+)(\d{2})(\d{2})(\d{2})(?:FUT)?"
                                    )
                                    future_match = future_pattern.match(groww_symbol)

                                    if future_match:
                                        # Extract components
                                        symbol_name, year, month_num, day = future_match.groups()

                                        # Convert numeric month to alphabetic
                                        months = [
                                            "JAN",
                                            "FEB",
                                            "MAR",
                                            "APR",
                                            "MAY",
                                            "JUN",
                                            "JUL",
                                            "AUG",
                                            "SEP",
                                            "OCT",
                                            "NOV",
                                            "DEC",
                                        ]
                                        month_name = (
                                            months[int(month_num) - 1]
                                            if 1 <= int(month_num) <= 12
                                            else f"M{month_num}"
                                        )

                                        # Format as OpenAlgo expects: NIFTY29MAY25FUT
                                        openalgo_symbol = f"{symbol_name}{day}{month_name}{year}FUT"
                                        logger.debug(
                                            f"Pattern: Converted Groww futures symbol: {groww_symbol} -> {openalgo_symbol}"
                                        )
                                        symbol_converted = True

                        except Exception as e:
                            logger.error(f"Error converting position symbol: {e}")
                            # Fall back to original symbol if conversion fails

                        # Map exchange to OpenAlgo format
                        exchange = position.get("exchange", "")
                        if exchange == "NSE":
                            openalgo_exchange = "NSE_EQ"
                        elif exchange == "BSE":
                            openalgo_exchange = "BSE_EQ"
                        elif exchange == "NFO":
                            openalgo_exchange = "NSE_FO"
                        else:
                            openalgo_exchange = exchange

                        # Create position object in OpenAlgo format
                        # For CASH segment, use the original trading_symbol as the symbol
                        if position.get("segment") == "CASH":
                            position_symbol = position.get(
                                "trading_symbol", groww_symbol
                            )  # Use trading_symbol for cash segment
                        else:
                            position_symbol = (
                                openalgo_symbol  # Use converted symbol for other segments
                            )

                        transformed_position = {
                            # Standard OpenAlgo fields
                            "symbol": position_symbol,
                            "tradingsymbol": position_symbol,
                            "exchange": openalgo_exchange,
                            "product": position.get("product", ""),
                            "quantity": net_qty,
                            "net_quantity": net_qty,
                            "average_price": avg_price,
                            "buy_quantity": buy_qty,
                            "sell_quantity": sell_qty,
                            "segment": "EQ",  # OpenAlgo format for CASH segment
                            # Specific Groww fields (renamed to match OpenAlgo expectations)
                            "buy_price": prices["buy_price"],
                            "sell_price": prices["sell_price"],
                            "symbol_isin": position.get("symbol_isin", ""),
                            # Fields expected by OpenAlgo's UI
                            "pnl": 0,  # Not provided in response, calculate if needed
                            "last_price": 0,  # Not provided in response
                            "close_price": 0,  # Not provided in response
                            "instrument_token": position.get(
                                "symbol_isin", ""
                            ),  # Use ISIN as token
                            "unrealised": 0,  # Not provided in response
                            "realised": 0,  # Not provided in response
                        }
                        all_positions.append(transformed_position)
            elif not says_no_positions(response_data):
                failures.append(
                    f"CASH segment: HTTP {response_obj.status_code}, {str(response_data)[:200]}"
                )

            # Now try to get FNO segment positions
            fno_failure = None
            try:
                params["segment"] = "FNO"
                logger.debug(f"Fetching FNO positions with params: {params}")

                fno_response = client.get(positions_url, params=params, headers=headers, timeout=30)
                fno_failure = _fno_read_failure(fno_response)

                if fno_response.status_code == 200:
                    fno_data = fno_response.json()
                    logger.debug(f"FNO response status: {fno_data.get('status')}")

                    if (
                        fno_data.get("status") == "SUCCESS"
                        and "payload" in fno_data
                        and "positions" in fno_data["payload"]
                    ):
                        fno_positions = fno_data["payload"]["positions"]
                        logger.debug(f"Found {len(fno_positions)} positions in FNO segment")

                        # Process FNO positions the same way
                        for position in fno_positions:
                            # Calculate net quantities
                            buy_qty = position.get("credit_quantity", 0) + position.get(
                                "carry_forward_credit_quantity", 0
                            )
                            sell_qty = position.get("debit_quantity", 0) + position.get(
                                "carry_forward_debit_quantity", 0
                            )
                            net_qty = position.get("quantity", buy_qty - sell_qty)

                            prices = groww_position_prices(position)
                            avg_price = prices["average_price"]

                            # Get the trading symbol
                            groww_symbol = position.get("trading_symbol", "")
                            openalgo_symbol = groww_symbol
                            symbol_converted = False

                            # Handle FNO symbol conversion
                            if (
                                position.get("segment") == "FNO"
                                or position.get("exchange") == "NFO"
                            ):
                                try:
                                    # Import get_oa_symbol with fallback paths
                                    try:
                                        from database.token_db import get_oa_symbol
                                    except ImportError:
                                        from openalgo.database.token_db import get_oa_symbol

                                    # First try database lookup for this FNO symbol
                                    db_symbol = get_oa_symbol(groww_symbol, "NFO")
                                    if db_symbol:
                                        openalgo_symbol = db_symbol
                                        logger.debug(
                                            f"Database: Converted Groww FNO symbol: {groww_symbol} -> {openalgo_symbol}"
                                        )
                                        symbol_converted = True
                                    else:
                                        # Fallback to pattern matching if database lookup fails
                                        # For Options: Convert from Groww format to OpenAlgo format
                                        # Groww format: "NIFTY25051334000CE" or "BANKNIFTY25051332500PE"
                                        # OpenAlgo format: "NIFTY13MAY2534000CE" or "BANKNIFTY13MAY2532500PE"
                                        groww_pattern = re.compile(
                                            r"([A-Z]+)(\d{2})(\d{2})(\d{2})(\d+)([CP]E)"
                                        )
                                        match = groww_pattern.match(groww_symbol)

                                    if match:
                                        # Extract components
                                        symbol_name, year, month_num, day, strike, option_type = (
                                            match.groups()
                                        )

                                        # Convert numeric month to alphabetic
                                        months = [
                                            "JAN",
                                            "FEB",
                                            "MAR",
                                            "APR",
                                            "MAY",
                                            "JUN",
                                            "JUL",
                                            "AUG",
                                            "SEP",
                                            "OCT",
                                            "NOV",
                                            "DEC",
                                        ]
                                        month_name = (
                                            months[int(month_num) - 1]
                                            if 1 <= int(month_num) <= 12
                                            else f"M{month_num}"
                                        )

                                        # Format as OpenAlgo expects: NIFTY15MAY2526650CE
                                        openalgo_symbol = f"{symbol_name}{day}{month_name}{year}{strike}{option_type}"
                                        logger.debug(
                                            f"Pattern: Converted Groww option position symbol: {groww_symbol} -> {openalgo_symbol}"
                                        )
                                        symbol_converted = True

                                    # For Futures: Convert from "NIFTY2551FUT" to "NIFTY29MAY25FUT"
                                    else:
                                        future_pattern = re.compile(
                                            r"([A-Z]+)(\d{2})(\d{2})(\d{2})(?:FUT)?"
                                        )
                                        match = future_pattern.match(groww_symbol)

                                        if match:
                                            # Extract components
                                            symbol_name, year, month_num, day = match.groups()

                                            # Convert numeric month to alphabetic
                                            months = [
                                                "JAN",
                                                "FEB",
                                                "MAR",
                                                "APR",
                                                "MAY",
                                                "JUN",
                                                "JUL",
                                                "AUG",
                                                "SEP",
                                                "OCT",
                                                "NOV",
                                                "DEC",
                                            ]
                                            month_name = (
                                                months[int(month_num) - 1]
                                                if 1 <= int(month_num) <= 12
                                                else f"M{month_num}"
                                            )

                                            # Format as OpenAlgo expects: NIFTY29MAY25FUT
                                            openalgo_symbol = (
                                                f"{symbol_name}{day}{month_name}{year}FUT"
                                            )
                                            logger.debug(
                                                f"Pattern: Converted Groww futures position symbol: {groww_symbol} -> {openalgo_symbol}"
                                            )
                                            symbol_converted = True
                                except Exception as e:
                                    logger.error(f"Error converting position symbol: {e}")
                                    # Fall back to original symbol if conversion fails

                            # Map exchange to OpenAlgo format
                            exchange = position.get("exchange", "")
                            if exchange == "NSE":
                                openalgo_exchange = "NSE"
                            elif exchange == "BSE":
                                openalgo_exchange = "BSE"
                            elif exchange == "NFO":
                                openalgo_exchange = "NSE_FO"
                            else:
                                openalgo_exchange = exchange

                            # Create position object with segment set to FNO
                            transformed_position = {
                                "symbol": openalgo_symbol,
                                "tradingsymbol": openalgo_symbol,
                                "exchange": openalgo_exchange,
                                "product": position.get("product", ""),
                                "quantity": net_qty,
                                "net_quantity": net_qty,
                                "average_price": avg_price,
                                "buy_quantity": buy_qty,
                                "sell_quantity": sell_qty,
                                "segment": "FO",  # OpenAlgo format for FNO segment
                                "buy_price": prices["buy_price"],
                                "sell_price": prices["sell_price"],
                                "symbol_isin": position.get("symbol_isin", ""),
                                "pnl": 0,
                                "last_price": 0,
                                "close_price": 0,
                                "instrument_token": position.get("symbol_isin", ""),
                                "unrealised": 0,
                                "realised": 0,
                            }
                            all_positions.append(transformed_position)
            except Exception as fno_error:
                # Don't fail if FNO segment request fails
                logger.warning(f"Error fetching FNO positions: {fno_error}")
                fno_failure = f"FNO segment: {type(fno_error).__name__}: {fno_error}"

            if strict and failures:
                logger.error(f"Groww position book incomplete: {'; '.join(failures)}")
                return {"status": "error", "message": "; ".join(failures), "data": []}, 502

            # Create formatted response
            formatted_response = {
                "status": "success",
                "message": f"Retrieved {len(all_positions)} positions",
                "data": all_positions,
                "raw_response": response_data,  # Include the CASH segment response
            }
            if strict and fno_failure:
                logger.warning(f"Groww FNO positions not read: {fno_failure}")
                formatted_response["failed_segments"] = ["FNO"]

            logger.debug(f"Successfully processed {len(all_positions)} total positions")
            return formatted_response, 200

        except json.JSONDecodeError as e:
            logger.error(f"Error parsing positions response: {e}")
            logger.error(f"Response content: {response_obj.content[:1000]}")
            return {
                "status": "error",
                "message": f"Error parsing positions response: {str(e)}",
                "data": [],
                "raw_content": response_obj.content.decode("utf-8", errors="replace")[:1000],
            }, response_obj.status_code

    except Exception as e:
        logger.error(f"Error fetching positions: {e}")
        logger.exception("Full stack trace:")
        return {
            "status": "error",
            "message": f"Error fetching positions: {str(e)}",
            "data": [],
            "raw_response": {},
        }, 500


def get_holdings(auth):
    """
    Get holdings for the user using direct API calls

    Args:
        auth (str): Authentication token

    Returns:
        tuple: (holdings data, status code)
    """
    try:
        logger.debug("Using direct API implementation for get_holdings")

        # Prepare the API client and headers
        client = get_httpx_client()
        headers = {
            "Authorization": f"Bearer {auth}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        # Groww API endpoint for holdings
        holdings_url = f"{GROWW_BASE_URL}/v1/portfolio/holdings"

        # Log the request details
        logger.debug("-------- GET HOLDINGS REQUEST --------")
        logger.debug(f"API URL: {holdings_url}")

        # Make the API call
        response_obj = client.get(holdings_url, headers=headers, timeout=30)

        # Log the response status
        logger.debug("-------- GET HOLDINGS RESPONSE --------")
        logger.debug(f"Response status code: {response_obj.status_code}")

        # Parse the response
        try:
            response_data = response_obj.json()
            logger.debug(
                f"Raw holdings response received with status code: {response_obj.status_code}"
            )

            # Process the response to extract holdings information
            if response_obj.status_code == 200 and "payload" in response_data:
                holdings = []

                # Extract holdings from the payload
                if "holdings" in response_data["payload"]:
                    raw_holdings = response_data["payload"]["holdings"]
                    logger.debug(f"Found {len(raw_holdings)} holdings")

                    # Transform holdings to a more consistent format
                    for holding in raw_holdings:
                        transformed_holding = {
                            "symbol": holding.get("trading_symbol", ""),
                            "exchange": holding.get("exchange", ""),
                            "isin": holding.get("isin", ""),
                            "quantity": holding.get("quantity", 0),
                            "average_price": holding.get("average_price", 0),
                            "last_price": holding.get("last_price", 0),
                            "close_price": holding.get("close_price", 0),
                            "pnl": holding.get("pnl", 0),
                            "day_change": holding.get("day_change", 0),
                            "day_change_percentage": holding.get("day_change_percentage", 0),
                            "value": holding.get("value", 0),
                            "company_name": holding.get("company_name", ""),
                            # Using the key names OpenAlgo expects
                            "tradingsymbol": holding.get("trading_symbol", ""),
                            "instrument_token": holding.get("token", ""),
                            "t1_quantity": holding.get("t1_quantity", 0),
                            "realised": holding.get("realised_pnl", 0),
                            "unrealised": holding.get("unrealised_pnl", 0),
                        }
                        holdings.append(transformed_holding)

                # Create response object
                formatted_response = {
                    "status": "success",
                    "message": f"Retrieved {len(holdings)} holdings",
                    "data": holdings,
                    "raw_response": response_data,
                }

                logger.debug(f"Successfully processed {len(holdings)} holdings")
                return formatted_response, 200
            else:
                # Handle error responses
                error_message = response_data.get("message", "Error retrieving holdings")
                error_details = response_data.get("error", {})

                logger.warning(f"Error getting holdings: {error_message}")
                if error_details:
                    logger.warning(f"Error details: {json.dumps(error_details, indent=2)}")

                return {
                    "status": "error",
                    "message": f"Failed to retrieve holdings: {error_message}",
                    "data": [],
                    "raw_response": response_data,
                }, response_obj.status_code

        except Exception as e:
            logger.error(f"Error parsing holdings response: {e}")
            return {
                "status": "error",
                "message": f"Error parsing holdings response: {str(e)}",
                "data": [],
                "tradebook": [],
                "raw_data": response_obj.content.decode("utf-8", errors="replace"),
            }, response_obj.status_code

    except Exception as e:
        logger.error(f"Error while fetching trades using direct API: {e}")
        logger.exception("Full stack trace:")
        # Even in error case, maintain consistent structure with empty data
        # This ensures map_trade_data can still process it
        return {
            "status": "error",
            "message": f"Error fetching trades: {str(e)}",
            "data": [],  # Empty list but with the expected structure
            "tradebook": [],
            "raw_data": [],
        }, 500


# --- Per-Symbol Smart Order Lock ---
# Ensures only one smart order per symbol executes at a time.
# Others queue and execute sequentially, each getting a fresh position book.
# The registry only holds the symbols in use right now, and under the gthread
# worker a smart order gives up after SMART_ORDER_LOCK_WAIT_SECONDS rather
# than hold a request thread behind a slow broker. Under eventlet and the dev
# server it waits as long as it takes, as before.
_symbol_locks = SymbolLocks(name="groww smart orders")

# --- Position Book Cache ---
# Caches get_positions() for 1 second. Invalidated after each smart order placement.
# A fetch still in flight when an order invalidates the book is returned to
# its own caller but never cached, so the next order cannot size itself
# against the position from before that fill.
_position_cache = PositionBookCache()


def _get_symbol_lock(symbol, exchange, product):
    """Hold the per-symbol smart-order lock for the body of a ``with`` block.

    Yields True while held, or False when the bounded wait under the gthread
    worker ran out; the caller then returns ``SymbolLocks.busy(symbol)`` and
    places nothing.
    """
    return _symbol_locks.hold(symbol, exchange, product)


def _position_book_ok(positions_data):
    """get_positions returns (payload, http status); with strict=True the payload
    says "success" only when the CASH segment was read."""
    payload = positions_data
    if isinstance(positions_data, tuple) and positions_data:
        payload = positions_data[0]
    return isinstance(payload, dict) and payload.get("status") == "success"


def _get_cached_positions(auth):
    """Get positions from cache if fresh, otherwise fetch from broker API."""
    return _position_cache.get(
        auth,
        lambda: read_position_book(
            "groww",
            lambda: get_positions(auth, strict=True),
            _position_book_ok,
        ),
    )


def _invalidate_position_cache(auth):
    """Invalidate the position cache so the next queued order fetches fresh data."""
    _position_cache.invalidate(auth)


def get_open_position(tradingsymbol, exchange, product, auth):
    """
    Get open position for a specific symbol

    Args:
        tradingsymbol (str): Trading symbol
        exchange (str): Exchange
        product (str): Product type
        auth (str): Authentication token

    Returns:
        str: Net quantity
    """
    # Convert Trading Symbol from OpenAlgo Format to Broker Format Before Search
    tradingsymbol = get_br_symbol(tradingsymbol, exchange)
    positions_data = _get_cached_positions(auth)
    net_qty = "0"

    # A strict read that could not read FNO still holds the whole CASH book. A
    # symbol in FNO, or in a segment this read does not cover, has no answer.
    payload = positions_data
    if isinstance(positions_data, tuple) and positions_data:
        payload = positions_data[0]
    failed_segments = payload.get("failed_segments") if isinstance(payload, dict) else None
    if failed_segments:
        segment = _SEGMENT_BY_EXCHANGE.get(str(exchange).upper())
        if segment is None or segment in failed_segments:
            raise PositionReadError("groww", f"the {failed_segments} position read failed")

    # Check if we received positions data in expected format
    # Handle both direct list format and dictionary with data field
    if positions_data:
        # If it's a dictionary with status and data fields (like Angel's format)
        if (
            isinstance(positions_data, dict)
            and positions_data.get("status") == "success"
            and positions_data.get("data")
        ):
            positions_list = positions_data.get("data", [])
        # If it's already a list
        elif isinstance(positions_data, list):
            positions_list = positions_data
        else:
            positions_list = []

        # Accept both OpenAlgo-standard exchange codes and the segment-suffixed
        # variants stored by get_positions() (NSE_EQ/BSE_EQ for CASH, NSE_FO/BSE_FO for FNO).
        exchange_variants = {
            "NSE": {"NSE", "NSE_EQ"},
            "BSE": {"BSE", "BSE_EQ"},
            "NFO": {"NFO", "NSE_FO", "NSE"},
            "BFO": {"BFO", "BSE_FO", "BSE"},
        }
        expected_exchanges = exchange_variants.get(exchange, {map_exchange_type(exchange), exchange})

        for position in positions_list:
            # Check for matching position - compare with both tradingsymbol and symbol fields
            symbol_match = (
                position.get("tradingsymbol") == tradingsymbol
                or position.get("symbol") == tradingsymbol
                or position.get("trading_symbol") == tradingsymbol
            )
            exchange_match = position.get("exchange") in expected_exchanges
            product_match = position.get("product") == product

            if symbol_match and exchange_match and product_match:
                # Try different field names for net quantity
                net_qty = str(
                    position.get(
                        "net_quantity", position.get("netqty", position.get("quantity", "0"))
                    )
                )
                break  # Found the position

    return net_qty


def direct_place_order_api(data, auth):
    """
    Place an order with Groww using direct API (no SDK)

    Args:
        data (dict): Order data in OpenAlgo format
        auth (str): Authentication token

    Returns:
        tuple: (response object, response data, order id)
    """
    try:
        # Import the shared httpx client
        from utils.httpx_client import get_httpx_client

        # API endpoint for placing orders
        api_url = "https://api.groww.in/v1/order/create"

        # Get original parameters
        original_symbol = data.get("symbol")
        original_exchange = data.get("exchange", "NSE")
        quantity = int(data.get("quantity"))

        # First, try to look up the broker symbol (brsymbol) directly from the database
        from broker.groww.database.master_contract_db import SymToken, db_session

        # Look up the symbol in the database
        with db_session() as session:
            db_record = (
                session.query(SymToken)
                .filter_by(symbol=original_symbol, exchange=original_exchange)
                .first()
            )

        if db_record and db_record.brsymbol:
            # Use the broker symbol from the database if found
            trading_symbol = db_record.brsymbol
            logger.debug(f"Using brsymbol from database: {original_symbol} -> {trading_symbol}")
        else:
            # If not found in database, try format conversion as fallback
            trading_symbol = format_openalgo_to_groww_symbol(original_symbol, original_exchange)
            logger.debug(
                f"Symbol not found in database, using conversion: {original_symbol} -> {trading_symbol}"
            )

        # Map the rest of the parameters to Groww API format
        product = map_product_type(data.get("product", "CNC"))
        exchange = map_exchange_type(original_exchange)
        segment = map_segment_type(original_exchange)
        order_type = map_order_type(data.get("pricetype", "MARKET"))
        transaction_type = map_transaction_type(data.get("action", "BUY"))
        validity = map_validity(data.get("validity", "DAY"))

        # Optional parameters
        # SL is a stop-limit order: Groww needs both price and trigger_price
        price = (
            float(data.get("price", 0))
            if data.get("pricetype", "").upper() in ["LIMIT", "SL"]
            else None
        )
        trigger_price = (
            float(data.get("trigger_price", 0))
            if data.get("pricetype", "").upper() in ["SL", "SL-M"]
            else None
        )

        # Generate a valid Groww order reference ID (8-20 alphanumeric with at most two hyphens)
        raw_id = data.get("order_reference_id", "")
        if not raw_id:
            # Create a reference ID based on timestamp and a partial UUID
            timestamp = datetime.now().strftime("%Y%m%d")
            uuid_part = str(uuid.uuid4()).replace("-", "")[:8]
            raw_id = f"{timestamp}-{uuid_part}"

        # Ensure the ID meets Groww's requirements
        # 1. Must be 8-20 characters
        # 2. Must be alphanumeric with at most two hyphens
        raw_id = re.sub(r"[^a-zA-Z0-9-]", "", raw_id)  # Remove non-alphanumeric/non-hyphen chars
        hyphen_count = raw_id.count("-")
        if hyphen_count > 2:
            # Remove excess hyphens, keeping the first two
            positions = [pos for pos, char in enumerate(raw_id) if char == "-"]
            for pos in positions[2:]:
                raw_id = raw_id[:pos] + "X" + raw_id[pos + 1 :]  # Replace excess hyphens with 'X'
            raw_id = raw_id.replace("X", "")  # Remove the placeholder

        # Ensure length is between 8-20 characters
        if len(raw_id) < 8:
            raw_id = raw_id.ljust(8, "0")  # Pad with zeros if too short
        if len(raw_id) > 20:
            raw_id = raw_id[:20]  # Truncate if too long

        order_reference_id = raw_id

        # Prepare the request payload according to Groww API documentation
        payload = {
            "trading_symbol": trading_symbol,
            "quantity": quantity,
            "validity": validity,
            "exchange": exchange,
            "segment": segment,
            "product": product,
            "order_type": order_type,
            "transaction_type": transaction_type,
            "order_reference_id": order_reference_id,
        }

        # Add price for LIMIT and SL (stop-limit) orders with detailed logging
        if price is not None and order_type in [ORDER_TYPE_LIMIT, ORDER_TYPE_SL]:
            # Ensure price is a proper numeric value
            try:
                price_value = float(price)
                payload["price"] = price_value
                logger.debug(f"Using price: {price_value} (original: {price}, type: {type(price)})")
            except (ValueError, TypeError) as e:
                logger.error(f"Invalid price value ({price}, type: {type(price)}): {str(e)}")
                raise ValueError(f"Invalid price format: {price}. Must be a valid number.")

        # Add trigger price for SL and SL-M orders with detailed logging
        if trigger_price is not None and order_type in [ORDER_TYPE_SL, ORDER_TYPE_SLM]:
            # Ensure trigger_price is a proper numeric value
            try:
                trigger_price_value = float(trigger_price)
                payload["trigger_price"] = trigger_price_value
                logger.debug(
                    f"Using trigger_price: {trigger_price_value} (original: {trigger_price}, type: {type(trigger_price)})"
                )
            except (ValueError, TypeError) as e:
                logger.error(
                    f"Invalid trigger_price value ({trigger_price}, type: {type(trigger_price)}): {str(e)}"
                )
                raise ValueError(
                    f"Invalid trigger_price format: {trigger_price}. Must be a valid number."
                )

        # Validate quantity with detailed logging
        try:
            quantity_value = int(quantity)
            if quantity_value <= 0:
                raise ValueError("Quantity must be greater than zero")
            logger.debug(
                f"Using quantity: {quantity_value} (original: {quantity}, type: {type(quantity)})"
            )
        except (ValueError, TypeError) as e:
            logger.error(f"Invalid quantity value ({quantity}, type: {type(quantity)}): {str(e)}")
            raise ValueError(f"Invalid quantity format: {quantity}. Must be a positive integer.")

        logger.debug(f"Placing {transaction_type} order for {quantity} of {trading_symbol}")
        logger.debug(f"API Parameters: {payload}")

        # Set up headers with authorization token
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {auth}",
        }

        # Make the API request using httpx client with connection pooling
        client = get_httpx_client()
        logger.debug(f"Sending API request to {api_url} with payload: {json.dumps(payload)}")
        logger.debug(f"Request headers: {headers}")

        try:
            resp = client.post(api_url, json=payload, headers=headers)
            logger.debug(f"API response status code: {resp.status_code}")

            # Log raw response for debugging
            raw_response = resp.text
            logger.debug(f"Raw API response: {raw_response}")
        except Exception as e:
            logger.error(f"Exception during API request: {str(e)}")
            raise

        # Create a response object to maintain compatibility with existing code
        class ResponseObject:
            def __init__(self, status_code):
                self.status = status_code

        # Handle the response
        if resp.status_code == 200:
            # Try to parse the response JSON
            try:
                response_data = resp.json()
                logger.debug(f"Groww order response: {json.dumps(response_data)}")
            except json.JSONDecodeError as e:
                logger.error(f"Error parsing response JSON: {e}")
                response_data = {
                    "status": "error",
                    "message": f"Invalid JSON response: {raw_response}",
                }
                res = ResponseObject(400)
                return res, response_data, None

            if response_data.get("status") == "SUCCESS":
                # Extract values from the response payload
                payload_data = response_data.get("payload", {})
                orderid = payload_data.get("groww_order_id")
                order_status = payload_data.get("order_status")

                logger.debug(f"Order ID: {orderid}, Status: {order_status}")

                # Format response to match the expected structure
                formatted_response = {
                    "groww_order_id": orderid,
                    "order_status": order_status,
                    "order_reference_id": payload_data.get(
                        "order_reference_id", order_reference_id
                    ),
                    "remark": payload_data.get("remark", "Order placed successfully"),
                    "trading_symbol": trading_symbol,
                    "symbol": original_symbol,  # Add original OpenAlgo symbol to response
                }

                res = ResponseObject(200)
                return res, formatted_response, orderid
            else:
                # API call succeeded but order placement failed
                error_message = response_data.get("message", "Unknown error")
                error_mode = response_data.get("mode", "")
                error_details = response_data.get("details", {})

                logger.error(f"Order placement failed: {error_message}, Mode: {error_mode}")
                logger.error(
                    f"Error details: {json.dumps(error_details) if error_details else 'None provided'}"
                )

                # Special handling for numeric validation errors
                if "Invalid numeric value" in error_message:
                    logger.error("NUMERIC VALUE ERROR DETECTED - Debugging payload values:")
                    for field in ["price", "trigger_price", "quantity", "disclosed_quantity"]:
                        if field in payload:
                            logger.error(
                                f"Field: {field}, Value: {payload[field]}, Type: {type(payload[field])}"
                            )

                    # Additional debugging info about the request
                    logger.error(f"Original data received: {json.dumps(data)}")

                res = ResponseObject(400)
                response_data = {"status": "error", "message": error_message, "mode": error_mode}
                return res, response_data, None
        else:
            # API call failed
            try:
                error_data = resp.json()
                error_message = error_data.get("message", f"API error: {resp.status_code}")
                error_mode = error_data.get("mode", "")
                error_details = error_data.get("details", {})

                logger.error(
                    f"API error response: Status: {resp.status_code}, Message: {error_message}, Mode: {error_mode}"
                )
                logger.error(
                    f"Error details: {json.dumps(error_details) if error_details else 'None provided'}"
                )

                # Special handling for numeric validation errors
                if "Invalid numeric value" in error_message:
                    logger.error("NUMERIC VALUE ERROR DETECTED - Debugging payload values:")
                    for field in ["price", "trigger_price", "quantity", "disclosed_quantity"]:
                        if field in payload:
                            logger.error(
                                f"Field: {field}, Value: {payload[field]}, Type: {type(payload[field])}"
                            )

                    # Additional debugging info about the request
                    logger.error(f"Original data received: {json.dumps(data)}")
            except Exception as parse_error:
                error_message = f"API error: {resp.status_code}. Raw response: {raw_response}"
                logger.error(f"Failed to parse error response: {parse_error}")

            logger.error(f"Error placing order: {error_message}")
            res = ResponseObject(resp.status_code)
            response_data = {"status": "error", "message": error_message}
            return res, response_data, None

    except Exception as e:
        logger.exception(f"Error placing order: {e}")

        class ResponseObject:
            def __init__(self, status_code):
                self.status = status_code

        res = ResponseObject(500)
        response_data = {"status": "error", "message": str(e)}
        return res, response_data, None


def place_order_api(data, auth):
    """
    Place an order with Groww using direct API only (no SDK fallback)

    Args:
        data (dict): Order data in OpenAlgo format
        auth (str): Authentication token

    Returns:
        tuple: (response object, response data, order id)
    """
    logger.debug("Using direct API implementation for order placement")
    return direct_place_order_api(data, auth)


def direct_place_order(
    auth_token,
    symbol,
    quantity,
    price=None,
    order_type="MARKET",
    transaction_type="BUY",
    product="CNC",
    order_reference_id=None,
):
    """
    Directly place an order with Groww SDK (for testing)

    Args:
        auth_token (str): Authentication token
        symbol (str): Trading symbol
        quantity (int): Quantity to trade
        price (float, optional): Price for limit orders. Defaults to None.
        order_type (str, optional): Order type. Defaults to "MARKET".
        transaction_type (str, optional): BUY or SELL. Defaults to "BUY".
        product (str, optional): Product type. Defaults to "CNC".
        order_reference_id (str, optional): Custom reference ID. If None, a valid ID will be generated.

    Returns:
        dict: Order response
    """
    try:
        # Initialize Groww API client
        groww = init_groww_client(auth_token)

        # Default exchange and segment
        exchange = EXCHANGE_NSE
        segment = SEGMENT_CASH
        validity = VALIDITY_DAY

        # Generate a valid Groww order reference ID if not provided
        if not order_reference_id:
            timestamp = datetime.now().strftime("%Y%m%d")
            uuid_part = str(uuid.uuid4()).replace("-", "")[:8]
            order_reference_id = f"{timestamp}-{uuid_part}"

            # Ensure it meets Groww's requirements
            order_reference_id = re.sub(r"[^a-zA-Z0-9-]", "", order_reference_id)[:20]
            if len(order_reference_id) < 8:
                order_reference_id = order_reference_id.ljust(8, "0")

        logger.debug(
            f"Placing {transaction_type} order for {quantity} of {symbol} at {price if price else 'MARKET'}"
        )
        logger.debug(
            f"SDK Parameters: exchange={{exchange}}, segment={{segment}}, product={{product}}, order_type={order_type}"
        )
        logger.debug(f"Using order reference ID: {order_reference_id}")

        # Place order using SDK
        response = groww.place_order(
            trading_symbol=symbol,
            quantity=quantity,
            price=price,
            validity=validity,
            exchange=exchange,
            segment=segment,
            product=product,
            order_type=order_type,
            transaction_type=transaction_type,
            order_reference_id=order_reference_id,
        )
        logger.debug(f"Direct order response: {response}")
        return response

    except Exception as e:
        logger.exception(f"Direct order error: {e}")
        return {"status": "error", "message": str(e)}


@refuse_smart_order_on_read_failure
def place_smartorder_api(data, auth):
    """
    Place a smart order with position management using direct API implementation

    Args:
        data (dict): Order data in OpenAlgo format
        auth (str): Authentication token

    Returns:
        tuple: (response object, response data, order id)
    """
    try:
        # Extensive logging for debugging
        logger.debug(
            "===== PLACE SMART ORDER START =====\n"
            + f"Full Input Data: {json.dumps(data, indent=2)}"
        )

        AUTH_TOKEN = auth
        # If no API call is made in this function then res will return None
        res = None

        # Extract necessary info from data
        symbol = data.get("symbol")
        exchange = data.get("exchange")
        product = data.get("product")

        # Parse position_size with detailed logging
        raw_position_size = data.get("position_size", "0")
        logger.debug(
            f"Raw position_size from request: '{raw_position_size}' (type: {type(raw_position_size)})"
        )
        # Per-symbol lock: serialize smart orders per symbol
        symbol_lock = _get_symbol_lock(symbol, exchange, product)

        with symbol_lock as acquired:
            if not acquired:
                return SymbolLocks.busy(symbol)
            position_size = int(raw_position_size)

            # Validate input data
            if not symbol or not exchange or not product:
                error_msg = "Invalid input: Missing symbol, exchange, or product"
                logger.error(error_msg)
                return None, {"status": "error", "message": error_msg}, None

            logger.debug(
                "Smart order details:\n"
                + f"Symbol: {symbol}\n"
                + f"Exchange: {exchange}\n"
                + f"Product: {product}\n"
                + f"Target Position Size: {position_size}"
            )

            # Try to look up broker symbol from database
            try:
                from database.token_db import get_br_symbol
            except ImportError:
                from openalgo.database.token_db import get_br_symbol

            # Get current open position for the symbol
            position_str = get_open_position(symbol, exchange, map_product_type(product), AUTH_TOKEN)
            logger.debug(
                f"Raw position from get_open_position: '{position_str}' (type: {type(position_str)})"
            )

            # Ensure proper conversion to integer
            try:
                current_position = (
                    int(float(position_str)) if position_str and position_str != "0" else 0
                )
            except (ValueError, TypeError) as e:
                logger.error(f"Error converting position to int: {e}, using 0")
                current_position = 0

            logger.debug(f"Current Position (converted to int): {current_position}")
            logger.debug(f"Target Position Size: {position_size} (type: {type(position_size)})")

            # Determine action based on position_size and current_position
            # This logic matches Angel's implementation exactly
            action = None
            quantity = 0

            logger.debug(
                f"Smart Order Decision: Current Position={current_position}, Target Position={position_size}"
            )

            # If both position_size and current_position are 0, check if user wants to place a fresh order
            if position_size == 0 and current_position == 0 and int(data.get("quantity", 0)) != 0:
                action = data["action"]
                quantity = data["quantity"]
                logger.debug(f"No position exists, placing fresh order: {action} {quantity}")
                res, response, orderid = place_order_api(data, AUTH_TOKEN)
                _invalidate_position_cache(AUTH_TOKEN)
                return res, response, orderid

            elif position_size == current_position:
                if int(data.get("quantity", 0)) == 0:
                    response = {
                        "status": "success",
                        "message": "No OpenPosition Found. Not placing Exit order.",
                    }
                else:
                    response = {
                        "status": "success",
                        "message": "No action needed. Position size matches current position",
                    }
                orderid = None
                logger.debug("Positions already matched. No order will be placed.")
                return res, response, orderid  # res remains None as no API call was made

            # Close long position
            if position_size == 0 and current_position > 0:
                action = "SELL"
                quantity = abs(current_position)
                logger.debug(f"Closing long position: SELL {quantity} shares")
            # Close short position
            elif position_size == 0 and current_position < 0:
                action = "BUY"
                quantity = abs(current_position)
                logger.debug(f"Closing short position: BUY {quantity} shares")
            # Open new position when no current position exists
            elif current_position == 0:
                action = "BUY" if position_size > 0 else "SELL"
                quantity = abs(position_size)
                logger.debug(f"Opening new position: {action} {quantity} shares")
            # Adjust existing position
            else:
                if position_size > current_position:
                    action = "BUY"
                    quantity = position_size - current_position
                    logger.debug(
                        f"Increasing position: BUY {quantity} shares (from {current_position} to {position_size})"
                    )
                elif position_size < current_position:
                    action = "SELL"
                    quantity = current_position - position_size
                    logger.debug(
                        f"Reducing position: SELL {quantity} shares (from {current_position} to {position_size})"
                    )

            if action:
                # Double-check the calculation
                logger.debug("=== FINAL SMART ORDER DECISION ===")
                logger.debug(f"Current Position: {current_position}")
                logger.debug(f"Target Position: {position_size}")
                logger.debug(f"Action to take: {action}")
                logger.debug(f"Quantity to {action}: {quantity}")
                logger.debug(f"This will move position from {current_position} to {position_size}")

                # Prepare data for placing the order
                order_data = data.copy()
                order_data["action"] = action
                order_data["quantity"] = str(quantity)

                # Place the order using direct API
                logger.debug(f"Final Order Data: {json.dumps(order_data, indent=2)}")
                logger.debug(f"Placing smart order: {action} {quantity} shares of {symbol}")

                # Validate order data before placing
                if (
                    not order_data.get("symbol")
                    or not order_data.get("action")
                    or not order_data.get("quantity")
                ):
                    error_msg = "Invalid order data: Missing critical fields"
                    logger.error(error_msg)
                    return None, {"status": "error", "message": error_msg}, None

                res, response, orderid = place_order_api(order_data, AUTH_TOKEN)
                _invalidate_position_cache(AUTH_TOKEN)

                # Create response in the format expected by the API endpoint
                # Using SimpleNamespace to create an object with status attribute
                # Handle different response types
                is_success = False
                if isinstance(res, dict):
                    is_success = res.get("status") == "success"
                elif hasattr(res, "status"):
                    is_success = res.status == 200 or res.status == "SUCCESS"

                if is_success:
                    logger.debug(f"Smart order placed successfully. Order ID: {orderid}")
                    from types import SimpleNamespace

                    response_obj = SimpleNamespace()
                    response_obj.status = 200
                    return response_obj, response, orderid
                else:
                    logger.error("Smart order placement failed")
                    logger.error(f"Response: {response}")
                    logger.error(f"Response Type: {type(response)}")
                    logger.error(f"Res Object: {res}")
                    return res, response, orderid

            # Default return if no action was taken
            response = {
                "status": "success",
                "message": "No order action needed. Position size matches current position",
            }
            return None, response, None

    except PositionReadError:
        raise
    except Exception as e:
        logger.exception(f"Error in smart order placement: {e}")
        response = {"status": "error", "message": f"Smart order error: {str(e)}"}
        return None, response, None


def get_holdings(auth):
    """
    Fetch user's current stock holdings from Groww API

    Args:
        auth (str): Authentication token

    Returns:
        tuple: (holdings data, response status)
    """
    try:
        # Logging for debugging
        logger.debug("===== FETCH HOLDINGS START =====")

        # Prepare headers for the API request
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {auth}",
            "X-API-VERSION": "1.0",
        }

        # Make the API request
        import httpx

        with httpx.Client() as client:
            response = client.get(
                "https://api.groww.in/v1/holdings/user",
                headers=headers,
                timeout=10.0,  # 10-second timeout
            )

        # Log the raw response
        logger.debug(f"Holdings API Response Status: {response.status_code}")
        logger.debug(f"Holdings API Response: {response.text}")

        # Check response status
        if response.status_code != 200:
            error_msg = f"Holdings API Error: {response.status_code} - {response.text}"
            logger.error(error_msg)
            return None, {"status": "error", "message": error_msg}

        # Parse the response
        response_data = response.json()

        # Validate response structure
        if not response_data or response_data.get("status") != "SUCCESS":
            error_msg = f"Invalid holdings response: {response_data}"
            logger.error(error_msg)
            return None, {"status": "error", "message": error_msg}

        # Transform holdings to OpenAlgo format
        holdings = response_data.get("payload", {}).get("holdings", [])
        formatted_holdings = []

        for holding in holdings:
            formatted_holding = {
                "symbol": holding.get("trading_symbol"),
                "isin": holding.get("isin"),
                "quantity": holding.get("quantity", 0),
                "average_price": holding.get("average_price", 0),
                "free_quantity": holding.get("demat_free_quantity", 0),
                "locked_quantity": (
                    holding.get("demat_locked_quantity", 0)
                    + holding.get("groww_locked_quantity", 0)
                ),
                "pledged_quantity": holding.get("pledge_quantity", 0),
                "t1_quantity": holding.get("t1_quantity", 0),
            }
            formatted_holdings.append(formatted_holding)

        logger.debug(f"Processed {len(formatted_holdings)} holdings")

        return formatted_holdings, {"status": "success"}

    except Exception as e:
        error_msg = f"Error fetching holdings: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return None, {"status": "error", "message": error_msg}


def close_all_positions(token=None, auth=None):
    logger.debug("Starting close_all_positions")
    logger.debug(f"Current timestamp: {datetime.now().isoformat()}")

    # Validate input
    if not auth:
        logger.error("No authentication token provided")
        return {"status": "error", "message": "Authentication token is required"}, 400

    try:
        from database.token_db import get_br_symbol
    except ImportError:
        from openalgo.database.token_db import get_br_symbol
    """
    Close all open positions for the authenticated user
    """
    try:
        logger.debug("Starting close_all_positions function")
        positions_data, status_code = get_positions(auth)

        if status_code != 200:
            logger.error(f"Failed to fetch positions: {positions_data}")
            return {"status": "error", "message": "Failed to fetch positions"}, 500

        if not positions_data or "data" not in positions_data:
            logger.debug("No positions to close")
            return {"status": "success", "message": "No positions to close"}, 200

        # Ensure we're using the data from the positions_data
        positions = positions_data.get("data", [])

        success_count = 0
        failure_count = 0
        detailed_results = []

        logger.debug(f"Total positions to process: {len(positions)}")

        for position in positions:
            try:
                # Extensive logging of position details
                logger.debug(f"Processing position: {json.dumps(position, indent=2)}")

                # Get quantity and validate
                net_qty = position.get("net_quantity", position.get("quantity", 0))
                logger.debug(f"Net Quantity: {net_qty}")

                if int(net_qty) == 0:
                    logger.debug("Skipping position with zero net quantity")
                    continue

                # Get trading details
                trading_symbol = position.get(
                    "tradingsymbol", position.get("trading_symbol", position.get("symbol"))
                )
                exchange = position.get("exchange", "NSE").replace("_EQ", "").replace("_FO", "")
                product = position.get("product", "MIS")
                segment = position.get("segment", "")

                # Retrieve broker symbol from database
                br_symbol = get_br_symbol(trading_symbol, exchange)
                if br_symbol:
                    trading_symbol = br_symbol
                    logger.debug(f"Retrieved broker symbol: {br_symbol}")
                else:
                    logger.warning(f"No broker symbol found for {trading_symbol} in {exchange}")

                # Extensive logging of trading details
                logger.debug(f"Trading Symbol: {trading_symbol}")
                logger.debug(f"Exchange: {exchange}")
                logger.debug(f"Product: {product}")
                logger.debug(f"Segment: {segment}")

                # Determine order action
                action = "SELL" if int(net_qty) > 0 else "BUY"
                quantity = abs(int(net_qty))

                # Special handling for FNO segment with more logging
                if (
                    segment.upper() == "FO"
                    or "FNO" in exchange.upper()
                    or "NFO" in exchange.upper()
                ):
                    logger.debug(f"Detected FNO/Derivative segment for {trading_symbol}")
                    exchange = "NFO"
                    product = "MIS"  # Ensure MIS for derivatives
                    logger.debug(f"Updated Exchange to {exchange}, Product to {product}")

                # Prepare order payload
                place_order_payload = {
                    "apikey": token,
                    "strategy": "Squareoff",
                    "symbol": trading_symbol,
                    "action": action,
                    "exchange": exchange,
                    "pricetype": "MARKET",
                    "product": product,
                    "quantity": str(quantity),
                }

                logger.debug(
                    f"Prepared square-off order payload: {json.dumps(place_order_payload, indent=2)}"
                )

                # Place the order
                res, api_response, order_id = place_order_api(place_order_payload, auth)
                logger.debug(f"Square-off response: {api_response}, order_id: {order_id}")

                # Enhanced logging for detailed tracking
                result_entry = {
                    "symbol": trading_symbol,
                    "segment": segment,
                    "quantity": quantity,
                    "action": action,
                    "order_id": order_id,
                    "response": api_response,
                    "exchange": exchange,
                    "product": product,
                }

                # Handle 400 Bad Request more gracefully
                if api_response and api_response.get("status") == "success":
                    success_count += 1
                    result_entry["status"] = "success"
                    logger.debug(
                        f"Successfully closed position {trading_symbol} in {segment} segment"
                    )
                elif api_response and api_response.get("message", "").startswith("API error: 400"):
                    # Specific handling for 400 Bad Request
                    logger.error(
                        f"400 Bad Request for {trading_symbol}. Possible symbol mismatch or invalid order parameters."
                    )
                    failure_count += 1
                    result_entry["status"] = "error"
                    result_entry["error_details"] = "Invalid order parameters"
                else:
                    failure_count += 1
                    result_entry["status"] = "failed"
                    logger.error(
                        f"Failed to close position {trading_symbol} in {segment} segment: {api_response}"
                    )

                detailed_results.append(result_entry)

            except Exception as e:
                logger.exception(f"Error processing position {position}: {str(e)}")
                failure_count += 1
                detailed_results.append(
                    {"symbol": trading_symbol, "status": "error", "error_message": str(e)}
                )

        msg = f"Squared off {success_count} positions. Failed: {failure_count}"
        logger.debug(msg)
        return {"status": "success", "message": msg, "detailed_results": detailed_results}, 200

    except Exception as e:
        error_msg = f"Error in close_all_positions: {str(e)}"
        logger.exception(error_msg)

        # Log additional context
        logger.error(f"Exception type: {type(e).__name__}")
        logger.error(f"Auth token length: {len(auth) if auth else 'None'}")

        return {
            "status": "error",
            "message": error_msg,
            "error_type": type(e).__name__,
            "error_details": str(e),
        }, 500


def _groww_error_message(body, fallback):
    """The reason Groww gave for a failed request.

    Groww documents failures as ``{"status": "FAILURE", "error": {"code", "message"}}``
    (01-introduction, "Response structure").
    """
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict) and err.get("message"):
            return str(err["message"])
        if body.get("message"):
            return str(body["message"])
    return fallback


def _cancel_segments(orderid, auth):
    """Segments to try when cancelling ``orderid``.

    Groww's cancel needs the order's own segment. Read it from the order book;
    if the order is not there, try CASH then FNO - a cancel sent to the wrong
    segment is refused by Groww, so the second attempt is harmless.
    """
    try:
        for order in get_order_book(auth).get("data", []):
            if order.get("groww_order_id") == orderid:
                seg = order.get("segment")
                if seg in (SEGMENT_CASH, SEGMENT_FNO):
                    return [seg]
                break
    except Exception:
        logger.exception(f"Could not read the order book to find the segment of {orderid}")
    return [SEGMENT_CASH, SEGMENT_FNO]


def cancel_order(orderid, auth, segment=None, symbol=None, exchange=None):
    """
    Cancel an order (POST /v1/order/cancel).

    Args:
        orderid (str): Groww order ID to cancel
        auth (str): Authentication token
        segment (str, optional): CASH or FNO. Looked up from the order book when omitted.
        symbol (str, optional): OpenAlgo symbol, echoed back in the response
        exchange (str, optional): Unused, kept for call compatibility

    Returns:
        tuple: (response data, status code). 200 only when Groww reports SUCCESS.
    """
    try:
        client = get_httpx_client()
        headers = {
            "Authorization": f"Bearer {auth}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-API-VERSION": "1.0",
        }
        segments = [segment] if segment else _cancel_segments(orderid, auth)

        message, status_code = f"Groww could not cancel order {orderid}", 400
        for seg in segments:
            payload = {"segment": seg, "groww_order_id": orderid}
            logger.debug(f"Cancelling order {orderid} in segment {seg}")
            resp = client.post(GROWW_CANCEL_ORDER_URL, headers=headers, json=payload, timeout=30)
            try:
                body = resp.json()
            except ValueError:
                body = {}

            if resp.status_code == 200 and body.get("status") == "SUCCESS":
                order_status = (body.get("payload") or {}).get("order_status", "")
                response = {
                    "status": "success",
                    "orderid": orderid,
                    "order_status": order_status,
                    "message": "Order cancellation requested"
                    if order_status == "CANCELLATION_REQUESTED"
                    else "Order cancelled",
                }
                if symbol:
                    response["symbol"] = symbol
                return response, 200

            message = _groww_error_message(body, message)
            status_code = resp.status_code if resp.status_code >= 400 else 400
            logger.warning(
                f"Groww refused cancel of {orderid} in segment {seg}: "
                f"HTTP {resp.status_code}, {message}"
            )

        return {"status": "error", "orderid": orderid, "message": message}, status_code
    except Exception:
        logger.exception(f"Error cancelling order {orderid}")
        return {
            "status": "error",
            "orderid": orderid,
            "message": "Could not reach Groww to cancel the order. Check the order book before retrying.",
        }, 500


def direct_modify_order(data, auth):
    """
    Modify an order with Groww using direct API (no SDK)

    Args:
        data (dict): Order data with modification parameters
        auth (str): Authentication token

    Returns:
        tuple: (response data dict, status code). 200 only when Groww reports SUCCESS.
    """
    try:
        # Import the shared httpx client
        from utils.httpx_client import get_httpx_client

        # API endpoint for modifying orders
        api_url = "https://api.groww.in/v1/order/modify"

        logger.debug(f"Starting direct modify order process for order: {data.get('orderid')}")

        # Get order ID from request data
        groww_order_id = data.get("orderid")
        if not groww_order_id:
            raise ValueError("Order ID (orderid) is required for order modification")

        # Get order type from request data
        order_type = None
        if "pricetype" in data:
            order_type = map_order_type(data["pricetype"])
        else:
            # Try to determine from order book if not provided
            try:
                # Get order book to find the order and determine its type
                order_book_response = get_order_book(auth)

                if (
                    order_book_response
                    and "data" in order_book_response
                    and order_book_response["data"]
                ):
                    for order in order_book_response["data"]:
                        if order.get("groww_order_id") == groww_order_id:
                            # Get the order type from the order book
                            if "order_type" in order:
                                order_type = order["order_type"]
                                logger.debug(f"Retrieved order type from order book: {order_type}")
                                break
            except Exception as e:
                logger.error(f"Error retrieving order type from order book: {e}")

        # If still not determined, use MARKET as default
        if not order_type:
            order_type = ORDER_TYPE_MARKET
            logger.warning(
                f"Could not determine order type for {groww_order_id}, defaulting to MARKET"
            )

        # Get the exchange and derive segment
        exchange = data.get("exchange", EXCHANGE_NSE)
        segment = map_segment_type(exchange)  # Map to CASH, FNO, etc.

        # Prepare the payload for the API request
        payload = {"groww_order_id": groww_order_id, "order_type": order_type, "segment": segment}

        # Add optional parameters if provided with detailed validation logging
        # Process quantity with detailed logging
        if "quantity" in data:
            try:
                quantity_value = int(data["quantity"])
                if quantity_value <= 0:
                    logger.warning(f"Invalid quantity value: {quantity_value}. Must be positive.")
                    raise ValueError(f"Invalid quantity: {quantity_value}. Must be positive.")
                payload["quantity"] = quantity_value
                logger.debug(
                    f"Using quantity: {quantity_value} (original: {data['quantity']}, type: {type(data['quantity'])})"
                )
            except (ValueError, TypeError) as e:
                logger.error(
                    f"Invalid quantity value ({data['quantity']}, type: {type(data['quantity'])}): {str(e)}"
                )
                raise ValueError(
                    f"Invalid quantity format: {data['quantity']}. Must be a positive integer."
                )

        # Process price with detailed logging
        if "price" in data and data["price"] and order_type in [ORDER_TYPE_LIMIT, ORDER_TYPE_SL]:
            try:
                price_value = float(data["price"])
                if price_value <= 0:
                    logger.warning(f"Price should be positive: {price_value}")
                payload["price"] = price_value
                logger.debug(
                    f"Using price: {price_value} (original: {data['price']}, type: {type(data['price'])})"
                )
            except (ValueError, TypeError) as e:
                logger.error(
                    f"Invalid price value ({data['price']}, type: {type(data['price'])}): {str(e)}"
                )
                raise ValueError(f"Invalid price format: {data['price']}. Must be a valid number.")

        # Process trigger_price with detailed logging
        if (
            "trigger_price" in data
            and data["trigger_price"]
            and order_type in [ORDER_TYPE_SL, ORDER_TYPE_SLM]
        ):
            try:
                trigger_price_value = float(data["trigger_price"])
                if trigger_price_value <= 0:
                    logger.warning(f"Trigger price should be positive: {trigger_price_value}")
                payload["trigger_price"] = trigger_price_value
                logger.debug(
                    f"Using trigger_price: {trigger_price_value} (original: {data['trigger_price']}, type: {type(data['trigger_price'])})"
                )
            except (ValueError, TypeError) as e:
                logger.error(
                    f"Invalid trigger_price value ({data['trigger_price']}, type: {type(data['trigger_price'])}): {str(e)}"
                )
                raise ValueError(
                    f"Invalid trigger_price format: {data['trigger_price']}. Must be a valid number."
                )

        logger.debug(f"Modifying order {groww_order_id} with parameters: {json.dumps(payload)}")

        # Set up headers with authorization token
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {auth}",
            "X-API-VERSION": "1.0",
        }

        client = get_httpx_client()
        resp = client.post(api_url, json=payload, headers=headers)
        logger.debug(f"Modify order {groww_order_id}: HTTP {resp.status_code}, {resp.text}")
        try:
            body = resp.json()
        except ValueError:
            body = {}

        # Success only when Groww says so (01-introduction, "Response structure")
        if resp.status_code == 200 and body.get("status") == "SUCCESS":
            response = {
                "status": "success",
                "orderid": groww_order_id,
                "order_status": (body.get("payload") or {}).get("order_status", ""),
                "message": "Order modification requested",
            }
            if data.get("symbol"):
                response["symbol"] = data["symbol"]
            return response, 200

        message = _groww_error_message(body, f"Groww could not modify order {groww_order_id}")
        logger.warning(f"Groww refused modify of {groww_order_id}: HTTP {resp.status_code}, {message}")
        status_code = resp.status_code if resp.status_code >= 400 else 400
        return {"status": "error", "orderid": groww_order_id, "message": message}, status_code

    except ValueError as e:
        # Raised above for missing order ID or invalid quantity/price values
        logger.warning(f"Modify order rejected before sending: {e}")
        return {"status": "error", "orderid": data.get("orderid", ""), "message": str(e)}, 400
    except Exception:
        logger.exception("Error in direct_modify_order")
        return {
            "status": "error",
            "orderid": data.get("orderid", ""),
            "message": "Could not reach Groww to modify the order. Check the order book before retrying.",
        }, 500


def modify_order(data, auth):
    """
    Modify an existing order (POST /v1/order/modify).

    Args:
        data (dict): Order data with modification parameters
        auth (str): Authentication token

    Returns:
        tuple: (response data dict, status code). 200 only when Groww reports SUCCESS.
    """
    return direct_modify_order(data, auth)


# Groww order statuses that can still be cancelled (annexure "Order Status";
# OPEN is what /v1/order/create returns for a resting order)
_CANCELLABLE_STATUSES = {
    "NEW",
    "ACKED",
    "TRIGGER_PENDING",
    "APPROVED",
    "OPEN",
    "MODIFICATION_REQUESTED",
}


def cancel_all_orders_api(data, auth):
    """
    Cancel every open Groww order.

    Args:
        data (dict): Request data
        auth (str): Authentication token

    Returns:
        tuple: (canceled_orders, failed_cancellations) in OpenAlgo format - a
        list of order IDs, and a list of {"orderid", "reason"}.
    """
    book = get_order_book(auth)
    if book.get("status") == "error":
        # An unreadable order book is not "nothing to cancel"
        raise RuntimeError(book.get("message", "Could not read the Groww order book"))

    canceled_orders, failed_cancellations = [], []
    for order in book.get("data", []):
        if str(order.get("order_status", "")).upper() not in _CANCELLABLE_STATUSES:
            continue
        orderid = order.get("groww_order_id")
        if not orderid:
            continue
        segment = order.get("segment")
        if segment not in (SEGMENT_CASH, SEGMENT_FNO):
            segment = None  # cancel_order looks the order up itself

        response, status_code = cancel_order(orderid, auth, segment)
        if status_code == 200:
            canceled_orders.append(orderid)
        else:
            failed_cancellations.append(
                {"orderid": orderid, "reason": response.get("message", "Failed to cancel")}
            )

    logger.info(
        f"Groww cancel all: {len(canceled_orders)} cancelled, {len(failed_cancellations)} failed"
    )
    return canceled_orders, failed_cancellations


def get_order_trades(orderid, auth, segment=None):
    """
    All fills of one order (GET /v1/order/trades/{groww_order_id}).

    Groww requires the order's segment and caps page_size at 50, and an order
    can have more fills than that, so every page is read.

    Args:
        orderid (str): Groww order ID
        auth (str): Authentication token
        segment (str, optional): CASH or FNO. Looked up from the order book when omitted.

    Returns:
        tuple: ({"status": "success", "trades": [...]}, 200), or
        ({"status": "error", "message": ...}, status code)
    """
    try:
        segments = [segment] if segment in (SEGMENT_CASH, SEGMENT_FNO) else _cancel_segments(orderid, auth)
        client = get_httpx_client()
        headers = _groww_headers(auth)
        message = f"Groww returned no trades for order {orderid}"
        for seg in segments:
            trade_list, failure = _get_paged(
                client,
                f"{GROWW_ORDER_TRADES_URL}/{orderid}",
                headers,
                {"segment": seg},
                "trade_list",
                _TRADES_PAGE_SIZE,
            )
            if failure:
                message = failure
                continue

            trades = []
            for trade in trade_list:
                exchange = openalgo_exchange(trade.get("exchange", ""), trade.get("segment", seg))
                groww_symbol = trade.get("trading_symbol", "")
                trades.append(
                    {
                        "trade_id": trade.get("groww_trade_id", ""),
                        "order_id": trade.get("groww_order_id", orderid),
                        "exchange_trade_id": trade.get("exchange_trade_id", ""),
                        "exchange_order_id": trade.get("exchange_order_id", ""),
                        "symbol": get_oa_symbol(groww_symbol, exchange) or groww_symbol,
                        "quantity": trade.get("quantity", 0),
                        "price": trade.get("price", 0),
                        "trade_status": trade.get("trade_status", ""),
                        "exchange": exchange,
                        "segment": trade.get("segment", seg),
                        "product": trade.get("product", ""),
                        "transaction_type": trade.get("transaction_type", ""),
                        "created_at": trade.get("created_at", ""),
                        "trade_date_time": trade.get("trade_date_time", ""),
                        "settlement_number": trade.get("settlement_number", ""),
                        "remarks": trade.get("remark"),
                    }
                )
            return {"status": "success", "trades": trades}, 200

        return {"status": "error", "message": message, "trades": []}, 400
    except Exception:
        logger.exception(f"Error reading Groww trades for order {orderid}")
        return {
            "status": "error",
            "message": "Could not reach Groww to read the order's trades.",
            "trades": [],
        }, 500
