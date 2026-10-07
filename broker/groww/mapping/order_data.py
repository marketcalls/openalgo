import datetime
import json
import os
import re
from typing import Any, Dict, List, Optional

import pandas as pd

from broker.dhan.mapping.transform_data import map_exchange
from database.token_db import get_symbol
from utils.logging import get_logger

logger = get_logger(__name__)


# Every order status in Groww's annexure "Order Status", plus OPEN (what
# /v1/order/create returns for a resting order), in OpenAlgo's vocabulary.
# A requested cancel or modify is still working until Groww confirms it.
GROWW_ORDER_STATUS_MAP = {
    "NEW": "open",
    "ACKED": "open",
    "OPEN": "open",
    "APPROVED": "open",
    "TRIGGER_PENDING": "trigger pending",
    "MODIFICATION_REQUESTED": "open",
    "CANCELLATION_REQUESTED": "open",
    "EXECUTED": "complete",
    "DELIVERY_AWAITED": "complete",
    "COMPLETED": "complete",
    "CANCELLED": "cancelled",
    "REJECTED": "rejected",
    "FAILED": "rejected",
}

# Groww order_type (annexure "Order Type") -> OpenAlgo pricetype
GROWW_PRICETYPE_MAP = {"MARKET": "MARKET", "LIMIT": "LIMIT", "SL": "SL", "SL_M": "SL-M"}


def map_order_status(status):
    """OpenAlgo order status for a Groww order_status. Unknown values are shown as sent."""
    status = str(status or "")
    mapped = GROWW_ORDER_STATUS_MAP.get(status.upper())
    if mapped is None:
        logger.warning(f"Unmapped Groww order status: {status!r}")
        return status.lower()
    return mapped


def _orders_from(order_data):
    """The order list from get_order_book's response, or a list passed through."""
    if isinstance(order_data, list):
        return order_data
    if isinstance(order_data, dict):
        return order_data.get("data") or order_data.get("order_list") or []
    return []


def map_order_data(order_data):
    """
    Map Groww's order list (04-orders "List orders") to OpenAlgo order fields.

    get_order_book has already resolved each order's OpenAlgo exchange
    (NSE/BSE/NFO/BFO) and symbol from the master contract.

    Returns:
        list: Orders with OpenAlgo field names (see docs/api/account-services/orderbook.md)
    """
    mapped_orders = []
    for order in _orders_from(order_data):
        order_type = order.get("order_type", "")
        mapped_orders.append(
            {
                "symbol": order.get("symbol") or order.get("trading_symbol", ""),
                "exchange": order.get("exchange", ""),
                "action": order.get("transaction_type", ""),
                "quantity": order.get("quantity", 0),
                "price": order.get("price", 0.0),
                "trigger_price": order.get("trigger_price", 0.0),
                "pricetype": GROWW_PRICETYPE_MAP.get(order_type, order_type),
                "product": order.get("product", ""),
                "orderid": order.get("groww_order_id", ""),
                "order_status": map_order_status(order.get("order_status")),
                "timestamp": order.get("created_at", ""),
            }
        )
    return mapped_orders


def calculate_order_statistics(order_data):
    """
    Count buy/sell, completed, open and rejected orders in mapped order data.

    Open includes orders waiting on their trigger, as other brokers count them.
    """
    stats = {
        "total_buy_orders": 0,
        "total_sell_orders": 0,
        "total_completed_orders": 0,
        "total_open_orders": 0,
        "total_rejected_orders": 0,
    }
    for order in _orders_from(order_data):
        if order.get("action") == "BUY":
            stats["total_buy_orders"] += 1
        elif order.get("action") == "SELL":
            stats["total_sell_orders"] += 1

        status = order.get("order_status")
        if status == "complete":
            stats["total_completed_orders"] += 1
        elif status in ("open", "trigger pending"):
            stats["total_open_orders"] += 1
        elif status == "rejected":
            stats["total_rejected_orders"] += 1
    return stats


def transform_order_data(orders):
    """
    Final OpenAlgo orderbook rows. map_order_data already produces the
    documented fields, so this only selects them in order.
    """
    fields = (
        "symbol",
        "exchange",
        "action",
        "quantity",
        "price",
        "trigger_price",
        "pricetype",
        "product",
        "orderid",
        "order_status",
        "timestamp",
    )
    return [{f: order.get(f, "") for f in fields} for order in _orders_from(orders)]


def map_trade_data(trade_data):
    """The trade list from get_trade_book's response, or a list passed through."""
    if isinstance(trade_data, tuple) and trade_data:
        trade_data = trade_data[0]
    if isinstance(trade_data, list):
        return trade_data
    if isinstance(trade_data, dict):
        return trade_data.get("data") or trade_data.get("tradebook") or []
    return []


def transform_tradebook_data(tradebook_data):
    """
    OpenAlgo tradebook rows (docs/api/account-services/tradebook.md).

    get_order_trades has already resolved each trade's OpenAlgo exchange and
    symbol from Groww's exchange + segment and the master contract; prices are
    rupees as Groww documents them.
    """
    transformed_data = []
    for trade in tradebook_data or []:
        quantity = float(trade.get("tradedQuantity", trade.get("quantity", 0)) or 0)
        price = float(trade.get("tradedPrice", trade.get("price", 0.0)) or 0)
        transformed_data.append(
            {
                "symbol": trade.get("tradingSymbol", trade.get("symbol", "")),
                "exchange": trade.get("exchangeSegment", trade.get("exchange", "")),
                "product": trade.get("productType", trade.get("product", "")),
                "action": trade.get("transactionType", trade.get("transaction_type", "")),
                "quantity": quantity,
                "average_price": price,
                "trade_price": price,
                "trade_value": quantity * price,
                "orderid": trade.get("orderId", trade.get("order_id", "")),
                "timestamp": trade.get("updateTime", trade.get("trade_date_time", "")),
                "tradeid": trade.get("tradeId", trade.get("trade_id", "")),
            }
        )
    return transformed_data


def map_position_data(position_data):
    logger.info(f"Map position data received type: {type(position_data)}")

    # If it's a tuple with status code (from direct API), extract the data
    if isinstance(position_data, tuple) and len(position_data) == 2:
        position_data = position_data[0]
        logger.info("Extracted position data from tuple")

    # Handle direct list of positions
    if isinstance(position_data, list):
        logger.info(f"Received direct list of {len(position_data)} positions")
        return position_data

    # Handle dictionary formats
    if isinstance(position_data, dict):
        # Log keys for debugging
        logger.info(f"Position data dict keys: {list(position_data.keys())}")

        # Check for data field
        if "data" in position_data and isinstance(position_data["data"], list):
            logger.info(f"Using 'data' field with {len(position_data['data'])} positions")
            return position_data["data"]

    # If all else fails, try the regular order mapping (fallback)
    logger.info("Falling back to regular order mapping")
    return map_order_data(position_data)


def transform_positions_data(positions_data):
    logger.info(
        f"Transform positions received type: {type(positions_data)}, length: {len(positions_data) if isinstance(positions_data, list) else 'not a list'}"
    )

    # Handle empty input
    if not positions_data:
        logger.warning("Positions data is empty")
        return []

    # Log first position for debugging
    if isinstance(positions_data, list) and positions_data:
        logger.info(
            f"Sample position to transform: {json.dumps(positions_data[0], indent=2)[:500]}"
        )

    transformed_data = []
    for position in positions_data:
        # Get tradingsymbol with fallbacks
        # Make sure we explicitly check for the trading_symbol field which is in the Groww API response
        trading_symbol = position.get("trading_symbol", "")
        broker_symbol = position.get("tradingsymbol", trading_symbol)
        if not broker_symbol:
            broker_symbol = position.get("symbol", "")

        # Ensure broker_symbol is a string, not None
        broker_symbol = str(broker_symbol) if broker_symbol is not None else ""
        exchange = position.get("exchange", "NSE")
        segment = position.get("segment", "")

        # For debugging
        logger.info(
            f"Processing position with trading_symbol: {trading_symbol}, broker_symbol: {broker_symbol}, segment: {segment}"
        )

        # Determine proper exchange based on segment and symbol pattern
        if segment == "FNO" or (
            broker_symbol and any(marker in broker_symbol for marker in ["CE", "PE", "FUT"])
        ):
            exchange = "NFO"
        else:
            exchange = "NSE"

        # Try to get token from position data if available
        token = position.get("token", position.get("instrument_token", None))

        # For cash segment, use the trading_symbol directly
        if segment == "CASH" or exchange == "NSE":
            symbol = broker_symbol
            # Ensure we have a trading symbol for cash segment
            if not symbol and "trading_symbol" in position:
                symbol = position["trading_symbol"]
        else:
            symbol = broker_symbol

        # Try to get OpenAlgo symbol from database
        try:
            from database.token_db import get_oa_symbol

            # Try to get the OpenAlgo symbol using the token if available
            if token:
                openalgo_symbol = get_oa_symbol(token, exchange)
                if openalgo_symbol:
                    symbol = openalgo_symbol
                    logger.info(f"Found OpenAlgo symbol by token: {broker_symbol} -> {symbol}")

            # If token lookup failed or token wasn't available, try by broker symbol
            elif broker_symbol:
                # For options/futures specifically, try database lookup
                if exchange == "NFO" and (
                    broker_symbol.endswith("CE")
                    or broker_symbol.endswith("PE")
                    or "FUT" in broker_symbol
                ):
                    # Query the database to find the OpenAlgo symbol for this broker symbol
                    from broker.groww.database.master_contract_db import SymToken, db_session

                    with db_session() as session:
                        record = (
                            session.query(SymToken)
                            .filter(
                                SymToken.brsymbol == broker_symbol, SymToken.exchange == exchange
                            )
                            .first()
                        )

                        if record and record.symbol:
                            symbol = record.symbol
                            logger.info(
                                f"Found OpenAlgo symbol in database: {broker_symbol} -> {symbol}"
                            )
        except Exception as e:
            logger.error(f"Error looking up OpenAlgo symbol from database: {e}")

        # Continue with the rest of your transformation
        quantity = float(position.get("quantity", 0))
        sell_qty = float(position.get("sellQty", 0))
        buy_qty = float(position.get("buyQty", 0))
        avg_price = float(position.get("avgPrice", 0))
        close_price = float(position.get("closePrice", 0))
        last_price = float(position.get("lastPrice", 0))
        pnl = float(position.get("pnl", 0))
        multiplier = float(position.get("multiplier", 1))
        unrealised = float(position.get("unrealised", 0))
        realised = float(position.get("realised", 0))

        transformed_position = {
            "symbol": symbol,
            "exchange": exchange,
            "product": position.get("product", "CNC"),
            "quantity": quantity,
            "average_price": avg_price,
            "close_price": close_price,
            "last_price": last_price,
            "pnl": pnl,
            "multiplier": multiplier,
            "unrealised": unrealised,
            "realised": realised,
            "buy_quantity": buy_qty,
            "sell_quantity": sell_qty,
            "instrument_token": position.get("instrument_token", position.get("symbol_isin", "")),
        }
        transformed_data.append(transformed_position)

    logger.info(f"Transformed {len(transformed_data)} positions successfully")
    return transformed_data


def transform_holdings_data(holdings_data):
    """
    Transform holdings data from Groww API

    Args:
        holdings_data: Can be a list of holdings or a tuple (holdings_list, metadata)

    Returns:
        List of transformed holdings
    """

    # Handle dictionary input with nested holdings
    if isinstance(holdings_data, dict) and "data" in holdings_data:
        holdings_data = holdings_data["data"].get("holdings", [])

    # Handle tuple input (holdings list, metadata)
    if isinstance(holdings_data, tuple):
        holdings_data = holdings_data[0]  # Take the first element (holdings list)

    # Validate input
    if not isinstance(holdings_data, list):
        logger.error(f"Invalid holdings data format: {type(holdings_data)}")
        return []

    transformed_data = []
    for holdings in holdings_data:
        # Extract symbol from trading symbol
        symbol = holdings.get("symbol", "")
        if not symbol and "trading_symbol" in holdings:
            # Try to extract symbol from trading symbol
            symbol = holdings["trading_symbol"].replace("NSE:", "").replace("BSE:", "")

        transformed_position = {
            "symbol": symbol,
            "exchange": holdings.get("exchange", "NSE"),  # Default to NSE
            "quantity": float(holdings.get("quantity", holdings.get("totalQty", 0))),
            "average_price": float(holdings.get("average_price", holdings.get("avgPrice", 0))),
            "product": holdings.get("product", "CNC"),
            "pnl": float(holdings.get("pnl", 0)),
            "pnlpercent": float(holdings.get("pnlpercent", 0)),
        }
        transformed_data.append(transformed_position)

    return transformed_data


def map_portfolio_data(portfolio_data):
    """
    Processes and modifies a list of Portfolio dictionaries based on specific conditions.

    Parameters:
    - portfolio_data: A list of dictionaries, where each dictionary represents an portfolio information.

    Returns:
    - The modified portfolio_data with  'product' fields.
    """
    # Check if 'portfolio_data' is empty
    if (
        portfolio_data is None
        or isinstance(portfolio_data, dict)
        and (
            portfolio_data.get("errorCode") == "DHOLDING_ERROR"
            or portfolio_data.get("internalErrorCode") == "DH-1111"
            or portfolio_data.get("internalErrorMessage") == "No holdings available"
        )
    ):
        # Handle the case where there is no data or specific error message about no holdings
        logger.info("No data or no holdings available.")
        portfolio_data = {}  # This resets portfolio_data to an empty dictionary if conditions are met

    return portfolio_data


def calculate_portfolio_statistics(holdings_data):
    """
    Calculate portfolio statistics from Groww API holdings data

    Parameters:
    - holdings_data: Holdings data from Groww API

    Returns:
    - Dictionary with portfolio statistics
    """
    # Logging for debugging
    logger.info(f"Input holdings data type: {type(holdings_data)}")
    logger.info(f"Input holdings data: {holdings_data}")

    # Check if holdings_data is empty or None
    if not holdings_data:
        return {
            "totalholdingvalue": 0,
            "totalinvvalue": 0,
            "totalpnlpercentage": 0,
            "totalprofitandloss": 0,
        }

    # Handle tuple input (holdings list, metadata) -- get_holdings() returns
    # (holdings, status) for this broker, and holdings_service passes that
    # through unchanged. transform_holdings_data() already unwraps it; without
    # the same handling here every statistic silently came back as zero.
    if isinstance(holdings_data, tuple):
        holdings_data = holdings_data[0]  # Take the first element (holdings list)

    if not holdings_data:
        return {
            "totalholdingvalue": 0,
            "totalinvvalue": 0,
            "totalpnlpercentage": 0,
            "totalprofitandloss": 0,
        }

    # Extract holdings from the API response structure
    if isinstance(holdings_data, dict):
        # Check if statistics are already provided
        if "data" in holdings_data and "statistics" in holdings_data["data"]:
            return holdings_data["data"]["statistics"]

        if "payload" in holdings_data:
            holdings_data = holdings_data["payload"].get("holdings", [])
        elif "data" in holdings_data and "holdings" in holdings_data["data"]:
            holdings_data = holdings_data["data"]["holdings"]

    # Validate holdings data
    if not isinstance(holdings_data, list):
        logger.error(f"Invalid holdings data format: {type(holdings_data)}")
        return {
            "totalholdingvalue": 0,
            "totalinvvalue": 0,
            "totalpnlpercentage": 0,
            "totalprofitandloss": 0,
        }

    # Calculate total holding value
    totalholdingvalue = 0
    totalinvvalue = 0
    totalprofitandloss = 0

    for holding in holdings_data:
        # Handle different possible key variations
        quantity = float(holding.get("quantity", holding.get("qty", 0)))
        avg_price = float(holding.get("average_price", holding.get("avgPrice", 0)))

        # Calculate holding value
        holding_value = quantity * avg_price
        totalholdingvalue += holding_value
        totalinvvalue += holding_value

        # Use provided PnL if available
        pnl = float(holding.get("pnl", 0))
        totalprofitandloss += pnl

    # Calculate PnL percentage
    totalpnlpercentage = (totalprofitandloss / totalinvvalue * 100) if totalinvvalue else 0

    # Prepare and return statistics
    return {
        "totalholdingvalue": round(totalholdingvalue, 2),
        "totalinvvalue": round(totalinvvalue, 2),
        "totalpnlpercentage": round(totalpnlpercentage, 2),
        "totalprofitandloss": round(totalprofitandloss, 2),
    }
