"""
Normalizes broker-agnostic order/trade/position dicts into the payload
shape delivered on the order_update, trade_update and position_update
WebSocket channels.

Input dicts are already broker-normalized by each broker's
mapping/order_data.py (symbol/exchange/action/quantity/... in OpenAlgo's
common format) - this module only reshapes them into the wire event and
carries the generation/sequence bookkeeping used for reconnect handling
and canonical ordering.
"""

from typing import Any

ORDER_UPDATE = "order_update"
TRADE_UPDATE = "trade_update"
POSITION_UPDATE = "position_update"


def build_trade_id(trade: dict[str, Any]) -> str:
    """Synthesize a stable per-fill id.

    The common tradebook format has no broker-native trade id (only
    orderid, which is shared across partial fills on the same order), so
    identity is derived from orderid + quantity + average_price +
    timestamp - unique per fill, stable across repeated polls of the same
    fill.
    """
    orderid = trade.get("orderid", "")
    quantity = trade.get("quantity", 0)
    average_price = trade.get("average_price", 0.0)
    timestamp = trade.get("timestamp", "")
    return f"{orderid}:{quantity}:{average_price}:{timestamp}"


def normalize_order_event(order: dict[str, Any], generation: int, sequence: int) -> dict[str, Any]:
    return {
        "event_type": ORDER_UPDATE,
        "generation": generation,
        "sequence": sequence,
        "orderid": order.get("orderid", ""),
        "symbol": order.get("symbol", ""),
        "exchange": order.get("exchange", ""),
        "action": order.get("action", ""),
        "product": order.get("product", ""),
        "pricetype": order.get("pricetype", ""),
        "quantity": order.get("quantity", 0),
        "price": order.get("price", 0.0),
        "trigger_price": order.get("trigger_price", 0.0),
        "status": order.get("order_status", ""),
        "rejection_reason": order.get("rejection_reason", ""),
        "timestamp": order.get("timestamp", ""),
    }


def normalize_trade_event(trade: dict[str, Any], generation: int, sequence: int) -> dict[str, Any]:
    return {
        "event_type": TRADE_UPDATE,
        "generation": generation,
        "sequence": sequence,
        "orderid": trade.get("orderid", ""),
        "tradeid": build_trade_id(trade),
        "symbol": trade.get("symbol", ""),
        "exchange": trade.get("exchange", ""),
        "product": trade.get("product", ""),
        "action": trade.get("action", ""),
        "fill_quantity": trade.get("quantity", 0),
        "fill_price": trade.get("average_price", 0.0),
        "trade_value": trade.get("trade_value", 0.0),
        "timestamp": trade.get("timestamp", ""),
    }


def normalize_position_event(
    position: dict[str, Any], generation: int, sequence: int
) -> dict[str, Any]:
    return {
        "event_type": POSITION_UPDATE,
        "generation": generation,
        "sequence": sequence,
        "symbol": position.get("symbol", ""),
        "exchange": position.get("exchange", ""),
        "product": position.get("product", ""),
        "net_quantity": position.get("quantity", 0),
        "average_price": position.get("average_price", 0.0),
        "ltp": position.get("ltp", 0.0),
        "pnl": position.get("pnl", 0.0),
        "timestamp": position.get("timestamp", ""),
    }
