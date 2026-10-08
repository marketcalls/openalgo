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


def _num(value):
    """A finite float from a Groww numeric field, or 0."""
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    return number if math.isfinite(number) else 0.0


def _position_row(position, segment):
    """One Groww position (06-portfolio "Get User Positions") in OpenAlgo terms.

    Prices are rupees as documented. P&L starts as the documented realised_pnl;
    _attach_ltp adds the open quantity's move when a live price is available.
    """
    groww_symbol = position.get("trading_symbol", "")
    groww_exchange = position.get("exchange", "")
    groww_segment = position.get("segment") or segment
    exchange = openalgo_exchange(groww_exchange, groww_segment)
    buy_qty = _num(position.get("credit_quantity")) + _num(
        position.get("carry_forward_credit_quantity")
    )
    sell_qty = _num(position.get("debit_quantity")) + _num(
        position.get("carry_forward_debit_quantity")
    )
    net_qty = position.get("quantity", buy_qty - sell_qty)
    prices = groww_position_prices(position)
    realised = _num(position.get("realised_pnl"))
    symbol = get_oa_symbol(groww_symbol, exchange) or groww_symbol
    return {
        "symbol": symbol,
        "tradingsymbol": symbol,
        "trading_symbol": groww_symbol,
        "exchange": exchange,
        "brexchange": groww_exchange,
        "segment": groww_segment,
        "product": position.get("product", ""),
        "quantity": net_qty,
        "net_quantity": net_qty,
        "average_price": prices["average_price"],
        "buy_quantity": buy_qty,
        "sell_quantity": sell_qty,
        "buy_price": prices["buy_price"],
        "sell_price": prices["sell_price"],
        "symbol_isin": position.get("symbol_isin", ""),
        "ltp": 0,
        "realised": realised,
        "unrealised": 0,
        "pnl": realised,
    }


_LTP_BATCH_SIZE = 50  # 08-live-data "Get LTP": up to 50 instruments


def _attach_ltp(rows, auth):
    """Add a live price and the open quantity's P&L to each open position.

    Groww's positions carry no last price, so one /v1/live-data/ltp call per
    segment (50 symbols each) supplies it; the payload maps each
    EXCHANGE_SYMBOL to its LTP. A failed price read leaves the row with LTP 0
    and P&L as the realised amount - the position itself is still shown.
    """
    wanted = {}
    for row in rows:
        if _num(row["quantity"]) == 0 or not row["trading_symbol"]:
            continue
        key = f"{row['brexchange']}_{row['trading_symbol']}"
        wanted.setdefault(row["segment"], {}).setdefault(key, []).append(row)
    if not wanted:
        return

    client = get_httpx_client()
    headers = _groww_headers(auth)
    for segment, rows_by_key in wanted.items():
        keys = list(rows_by_key)
        for start in range(0, len(keys), _LTP_BATCH_SIZE):
            batch = keys[start : start + _LTP_BATCH_SIZE]
            try:
                resp = client.get(
                    f"{GROWW_BASE_URL}/v1/live-data/ltp",
                    params={"segment": segment, "exchange_symbols": ",".join(batch)},
                    headers=headers,
                    timeout=10,
                )
                body = resp.json()
            except Exception:
                logger.warning(f"Groww LTP for {segment} positions could not be read", exc_info=True)
                continue
            payload = body.get("payload") if isinstance(body, dict) else None
            if resp.status_code != 200 or body.get("status") != "SUCCESS" or not isinstance(payload, dict):
                reason = _groww_error_message(body, f"HTTP {resp.status_code}")
                logger.warning(f"Groww LTP for {segment} positions refused: {reason}")
                continue
            for key in batch:
                ltp = _num(payload.get(key))
                if ltp <= 0:
                    continue
                for row in rows_by_key[key]:
                    row["ltp"] = ltp
                    if row["average_price"] > 0:
                        row["unrealised"] = (ltp - row["average_price"]) * _num(row["quantity"])
                        row["pnl"] = row["realised"] + row["unrealised"]


def get_positions(auth, strict=False, include_ltp=None):
    """
    Read the day's positions from both segments (GET /v1/positions/user).

    Args:
        auth (str): Authentication token
        strict (bool): Report a CASH segment that could not be read as an
            error instead of an empty book, which is what the smart order needs.
            An FNO read that fails does not fail the whole read: it fails on
            accounts without F&O, and refusing every smart order there would be
            the wrong trade. The CASH rows come back with
            "failed_segments": ["FNO"], so a smart order in NFO or BFO is
            refused while one in NSE or BSE goes ahead.
        include_ltp (bool, optional): Attach live prices and P&L. Defaults to
            on for the position book and off for the strict smart-order read,
            which only needs quantities.

    Returns:
        tuple: (positions data, status code)
    """
    if include_ltp is None:
        include_ltp = not strict
    try:
        client = get_httpx_client()
        headers = _groww_headers(auth)
        positions_url = f"{GROWW_BASE_URL}/v1/positions/user"

        rows = []
        cash = client.get(
            positions_url, params={"segment": SEGMENT_CASH}, headers=headers, timeout=30
        )
        try:
            cash_body = cash.json()
        except ValueError:
            cash_body = None
        if (
            cash.status_code == 200
            and isinstance(cash_body, dict)
            and cash_body.get("status") == "SUCCESS"
        ):
            for position in (cash_body.get("payload") or {}).get("positions") or []:
                rows.append(_position_row(position, SEGMENT_CASH))
        elif not says_no_positions(cash_body):
            reason = _groww_error_message(cash_body, f"HTTP {cash.status_code}")
            if strict:
                logger.error(f"Groww position book incomplete: CASH segment: {reason}")
                return {"status": "error", "message": f"CASH segment: {reason}", "data": []}, 502
            logger.warning(f"Groww CASH positions could not be read: {reason}")

        fno_failure = None
        try:
            fno = client.get(
                positions_url, params={"segment": SEGMENT_FNO}, headers=headers, timeout=30
            )
            fno_failure = _fno_read_failure(fno)
            if fno_failure is None and fno.status_code == 200:
                fno_body = fno.json()
                if fno_body.get("status") == "SUCCESS":
                    for position in (fno_body.get("payload") or {}).get("positions") or []:
                        rows.append(_position_row(position, SEGMENT_FNO))
        except Exception as fno_error:
            logger.warning(f"Error fetching FNO positions: {fno_error}")
            fno_failure = f"FNO segment: {type(fno_error).__name__}: {fno_error}"

        if include_ltp:
            _attach_ltp(rows, auth)

        response = {
            "status": "success",
            "message": f"Retrieved {len(rows)} positions",
            "data": rows,
        }
        if strict and fno_failure:
            logger.warning(f"Groww FNO positions not read: {fno_failure}")
            response["failed_segments"] = ["FNO"]
        return response, 200

    except Exception as e:
        logger.exception("Error fetching Groww positions")
        return {
            "status": "error",
            "message": f"Could not reach Groww to read positions: {type(e).__name__}",
            "data": [],
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

    # get_positions returns (payload, status); its rows carry Groww's own
    # trading_symbol and the OpenAlgo exchange (NSE/BSE/NFO/BFO).
    positions_list = (payload.get("data") or []) if isinstance(payload, dict) else []
    for position in positions_list:
        if (
            position.get("trading_symbol") == tradingsymbol
            and position.get("exchange") == exchange
            and position.get("product") == product
        ):
            net_qty = str(position.get("net_quantity", position.get("quantity", "0")))
            break

    return net_qty


class _Status:
    """The HTTP status the order services read from a broker response (res.status)."""

    def __init__(self, status):
        self.status = status


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

        # An exchange Groww cannot trade is the reason to give, before any
        # symbol lookup (MCX contracts are in the master contract)
        map_exchange_type(original_exchange)

        # First, try to look up the broker symbol (brsymbol) directly from the database
        from broker.groww.database.master_contract_db import SymToken, db_session

        # Look up the symbol in the database
        with db_session() as session:
            db_record = (
                session.query(SymToken)
                .filter_by(symbol=original_symbol, exchange=original_exchange)
                .first()
            )

        if not (db_record and db_record.brsymbol):
            # Groww's trading_symbol comes from its instrument file; a guessed
            # symbol could name a different contract
            raise ValueError(
                f"{original_symbol} is not in the {original_exchange} master contract. "
                "Check the symbol, or download the master contract again."
            )
        trading_symbol = db_record.brsymbol

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
            "X-API-VERSION": "1.0",
        }

        client = get_httpx_client()
        resp = client.post(api_url, json=payload, headers=headers)
        logger.debug(f"Place order: HTTP {resp.status_code}, {resp.text}")
        try:
            body = resp.json()
        except ValueError:
            body = None

        # Success only when Groww says so (01-introduction, "Response structure")
        if resp.status_code == 200 and isinstance(body, dict) and body.get("status") == "SUCCESS":
            payload_data = body.get("payload") or {}
            orderid = payload_data.get("groww_order_id")
            formatted_response = {
                "groww_order_id": orderid,
                "order_status": payload_data.get("order_status"),
                "order_reference_id": payload_data.get("order_reference_id", order_reference_id),
                "remark": payload_data.get("remark", "Order placed successfully"),
                "trading_symbol": trading_symbol,
                "symbol": original_symbol,
            }
            return _Status(200), formatted_response, orderid

        message = _groww_error_message(body, f"Groww did not accept the order (HTTP {resp.status_code})")
        logger.error(f"Groww refused order for {original_symbol}: HTTP {resp.status_code}, {message}")
        status = resp.status_code if resp.status_code >= 400 else 400
        return _Status(status), {"status": "error", "message": message}, None

    except ValueError as e:
        # Refused before sending: unsupported exchange, product, price type,
        # validity or action, an unknown symbol, or an invalid number
        logger.warning(f"Order not sent to Groww: {e}")
        return _Status(400), {"status": "error", "message": str(e)}, None
    except Exception:
        logger.exception("Error placing Groww order")
        return (
            _Status(500),
            {
                "status": "error",
                "message": "Could not reach Groww to place the order. Check the order book before retrying.",
            },
            None,
        )


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
        positions_data, status_code = get_positions(auth, include_ltp=False)

        if status_code != 200:
            logger.error(f"Failed to fetch positions: {positions_data}")
            return {"status": "error", "message": "Failed to fetch positions"}, 500

        positions = positions_data.get("data") or []
        if not positions:
            return {"status": "success", "message": "No positions to close"}, 200

        success_count = 0
        failure_count = 0
        detailed_results = []

        for position in positions:
            try:
                net_qty = int(_num(position.get("net_quantity", position.get("quantity", 0))))
                if net_qty == 0:
                    continue

                # get_positions rows carry the OpenAlgo symbol, exchange and
                # product, which is what place_order_api takes
                trading_symbol = position.get("symbol")
                exchange = position.get("exchange")
                product = position.get("product")
                action = "SELL" if net_qty > 0 else "BUY"
                quantity = abs(net_qty)

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
                    "segment": position.get("segment", ""),
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
                        f"Successfully closed position {trading_symbol} on {exchange}"
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
                        f"Failed to close position {trading_symbol} on {exchange}: {api_response}"
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
