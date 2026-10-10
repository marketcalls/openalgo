# Mapping OpenAlgo API Request https://openalgo.in/docs
# Mapping Groww Margin API

from broker.groww.mapping.transform_data import (
    map_exchange_type,
    map_order_type,
    map_product_type,
    map_segment_type,
    map_transaction_type,
)
from database.token_db import get_br_symbol
from utils.logging import get_logger

logger = get_logger(__name__)


def map_margin_exchange(exchange):
    """
    Maps the OpenAlgo Exchange to Groww Exchange values for margin API.
    Groww only accepts NSE/BSE - segment (CASH/FNO) is passed separately.
    """
    return map_exchange_type(exchange)


def transform_margin_positions(positions):
    """
    Transform OpenAlgo margin positions to Groww order items, grouped by segment.

    Each item carries every field 07-margin marks required: trading_symbol,
    quantity, exchange, segment, product, order_type and transaction_type,
    plus price in rupees when given.

    Args:
        positions: List of positions in OpenAlgo format

    Returns:
        dict: {"CASH": [items], "FNO": [items]} for the segments present

    Raises:
        ValueError: When a position cannot be sent to Groww (unknown symbol,
            unsupported exchange, product, price type or action). Margin for
            part of a basket would understate what the trader needs, so the
            whole request is refused and the position named.
    """
    groups = {}
    for position in positions:
        symbol = position.get("symbol")
        exchange = position.get("exchange", "")
        try:
            segment = map_segment_type(exchange)
            broker_symbol = get_br_symbol(symbol, exchange)
            if not broker_symbol:
                raise ValueError(f"{symbol} is not in the {exchange} master contract")
            item = {
                "trading_symbol": broker_symbol,
                "quantity": int(position["quantity"]),
                "exchange": map_margin_exchange(exchange),
                "segment": segment,
                "product": map_product_type(position["product"]),
                "order_type": map_order_type(position["pricetype"]),
                "transaction_type": map_transaction_type(position["action"]),
            }
            if position.get("price") and float(position["price"]) > 0:
                item["price"] = float(position["price"])
        except (KeyError, TypeError, ValueError) as e:
            raise ValueError(f"Cannot calculate margin for {symbol} on {exchange}: {e}") from e
        groups.setdefault(segment, []).append(item)
    return groups


def parse_margin_response(response_data):
    """
    Read one Groww margin response (07-margin "Calculate Required Margin").

    Returns:
        dict: {"status": "success", "data": {total_margin_required,
        span_margin, exposure_margin}} or {"status": "error", "message"}.
    """
    if not isinstance(response_data, dict):
        return {"status": "error", "message": "Groww returned no margin data"}
    if response_data.get("status") != "SUCCESS":
        error = response_data.get("error")
        message = error.get("message") if isinstance(error, dict) else None
        return {"status": "error", "message": message or "Groww could not calculate the margin"}

    payload = response_data.get("payload") or {}
    return {
        "status": "success",
        "data": {
            "total_margin_required": float(payload.get("total_requirement") or 0),
            "span_margin": float(payload.get("span_required") or 0),
            "exposure_margin": float(payload.get("exposure_required") or 0),
        },
    }
