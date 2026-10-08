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
    """The position rows from get_positions' (payload, status), or a list passed through."""
    if isinstance(position_data, tuple) and position_data:
        position_data = position_data[0]
    if isinstance(position_data, list):
        return position_data
    if isinstance(position_data, dict):
        return position_data.get("data") or []
    return []


def transform_positions_data(positions_data):
    """
    OpenAlgo positionbook rows (docs/api/account-services/positionbook.md).

    get_positions has already resolved the OpenAlgo symbol and exchange, the
    rupee average price, the live price and P&L (realised_pnl plus the open
    quantity's move from the average).
    """
    return [
        {
            "symbol": position.get("symbol", ""),
            "exchange": position.get("exchange", ""),
            "product": position.get("product", ""),
            "quantity": position.get("quantity", 0),
            "average_price": position.get("average_price", 0.0),
            "ltp": position.get("ltp", 0.0),
            "pnl": position.get("pnl", 0.0),
        }
        for position in positions_data or []
    ]


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

        # get_holdings resolves the exchange from the master contract and the
        # P&L from the live LTP; a holding Groww could not price carries 0 P&L
        transformed_position = {
            "symbol": symbol,
            "exchange": holdings.get("exchange", ""),
            "quantity": float(holdings.get("quantity", holdings.get("totalQty", 0))),
            "average_price": float(holdings.get("average_price", holdings.get("avgPrice", 0))),
            "product": holdings.get("product", "CNC"),  # demat holdings are delivery
            "pnl": round(float(holdings.get("pnl", 0)), 2),
            "pnlpercent": round(float(holdings.get("pnlpercent", 0)), 2),
        }
        # Same extra fields as the reference broker (Zerodha), which the
        # Holdings page shows; no ltp when Groww could not price the holding
        if holdings.get("ltp"):
            transformed_position["ltp"] = round(float(holdings["ltp"]), 2)
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

        # Invested at the average price; held at the live price when Groww
        # priced the holding (get_holdings sets ltp), else at the average
        invested = quantity * avg_price
        ltp = float(holding.get("ltp") or 0)
        totalinvvalue += invested
        totalholdingvalue += quantity * ltp if ltp else invested

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
