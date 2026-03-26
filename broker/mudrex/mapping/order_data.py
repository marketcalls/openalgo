"""
Normalize Mudrex order / position / trade / holding data to OpenAlgo format.

Used by orderbook_service, tradebook_service, positionbook_service,
and holdings_service to present a consistent UI across all brokers.
"""

from database.token_db import get_oa_symbol, get_symbol, get_symbol_info
from utils.logging import get_logger

logger = get_logger(__name__)

_EXCHANGE = "CRYPTO_FUT"

_ORDER_STATUS_MAP = {
    "CREATED": "open",
    "PARTIALLY_FILLED": "open",
    "PENDING": "open",
    "FILLED": "complete",
    "CANCELLED": "cancelled",
    "REJECTED": "rejected",
    "EXPIRED": "cancelled",
}


def _safe_float(val, default: float = 0.0) -> float:
    try:
        return float(val) if val is not None else default
    except (ValueError, TypeError):
        return default


# ---------------------------------------------------------------------------
# Order book
# ---------------------------------------------------------------------------

def map_order_data(order_data):
    """Normalize Mudrex order dicts to OpenAlgo orderbook format."""
    try:
        if order_data is None:
            return []
        if isinstance(order_data, dict) and not order_data.get("success", True):
            logger.error(f"Error in order data: {order_data}")
            return []
        if isinstance(order_data, str):
            logger.error(f"Received string instead of order list: {order_data[:200]}")
            return []
        if not isinstance(order_data, list):
            logger.warning(f"Expected list, got {type(order_data)}")
            return []

        for order in order_data:
            if not isinstance(order, dict):
                continue

            order_id = order.get("id", "")
            symbol_raw = order.get("symbol", "")
            asset_uuid = order.get("asset_uuid", "")

            order["orderId"] = str(order_id)

            sym_from_db = get_symbol(asset_uuid, _EXCHANGE) if asset_uuid else None
            order["tradingSymbol"] = sym_from_db or symbol_raw

            order["exchangeSegment"] = _EXCHANGE
            order["productType"] = "NRML"

            ot = order.get("order_type", "").upper()
            order["transactionType"] = "BUY" if ot == "LONG" else "SELL"

            tt = order.get("trigger_type", "").upper()
            order["orderType"] = "LIMIT" if tt == "LIMIT" else "MARKET"

            status_raw = order.get("status", "").upper()
            order["orderStatus"] = _ORDER_STATUS_MAP.get(status_raw, status_raw.lower())

            order["quantity"] = _safe_float(order.get("quantity"))
            order["price"] = _safe_float(order.get("price"))
            # Some responses expose conditional trigger/risk prices under different keys.
            order["triggerPrice"] = _safe_float(
                order.get("trigger_price", order.get("stoploss_price", order.get("stop_price")))
            )
            order["updateTime"] = order.get("updated_at", order.get("created_at", ""))
            order["reduceOnly"] = bool(order.get("reduce_only", False))
            order["postOnly"] = bool(order.get("post_only", False))
            order["clientOrderId"] = order.get("client_order_id", "")
            order["trailAmount"] = _safe_float(order.get("trail_amount"))
            order["stopTriggerMethod"] = order.get("stop_trigger_method", "")
            order["bracketStopLossPrice"] = order.get("stoploss_price", "")
            order["bracketTakeProfitPrice"] = order.get("takeprofit_price", "")

        return order_data

    except Exception as exc:
        logger.exception(f"[Mudrex] map_order_data error: {exc}")
        return []


def calculate_order_statistics(order_data):
    """Calculate totals for buy/sell/complete/open/rejected orders."""
    try:
        if not order_data or not isinstance(order_data, list):
            return {
                "total_buy_orders": 0,
                "total_sell_orders": 0,
                "total_completed_orders": 0,
                "total_open_orders": 0,
                "total_rejected_orders": 0,
            }

        total_buy = total_sell = total_complete = total_open = total_rejected = 0

        for order in order_data:
            if not isinstance(order, dict):
                continue
            if order.get("transactionType") == "BUY":
                total_buy += 1
            elif order.get("transactionType") == "SELL":
                total_sell += 1

            status = order.get("orderStatus", "").lower()
            if status in ("complete", "filled"):
                total_complete += 1
                order["orderStatus"] = "complete"
            elif status in ("open", "pending"):
                total_open += 1
                order["orderStatus"] = "open"
            elif status == "rejected":
                total_rejected += 1
            elif status == "cancelled":
                pass

        return {
            "total_buy_orders": total_buy,
            "total_sell_orders": total_sell,
            "total_completed_orders": total_complete,
            "total_open_orders": total_open,
            "total_rejected_orders": total_rejected,
        }
    except Exception as exc:
        logger.exception(f"[Mudrex] calculate_order_statistics error: {exc}")
        return {
            "total_buy_orders": 0,
            "total_sell_orders": 0,
            "total_completed_orders": 0,
            "total_open_orders": 0,
            "total_rejected_orders": 0,
        }


def transform_order_data(orders):
    """Transform orders to OpenAlgo standard format for the UI."""
    try:
        if orders is None:
            return []
        if isinstance(orders, dict):
            orders = [orders]
        if not isinstance(orders, list):
            return []

        transformed = []
        for order in orders:
            if not isinstance(order, dict):
                continue

            transformed.append({
                "symbol": order.get("tradingSymbol", ""),
                "exchange": order.get("exchangeSegment", ""),
                "action": order.get("transactionType", ""),
                "quantity": order.get("quantity", 0),
                "price": order.get("price", 0.0),
                "trigger_price": order.get("triggerPrice", 0.0),
                "pricetype": order.get("orderType", ""),
                "product": order.get("productType", ""),
                "orderid": order.get("orderId", ""),
                "order_status": order.get("orderStatus", ""),
                "timestamp": order.get("updateTime", ""),
            })

        return transformed
    except Exception as exc:
        logger.exception(f"[Mudrex] transform_order_data error: {exc}")
        return []


# ---------------------------------------------------------------------------
# Trade book
# ---------------------------------------------------------------------------

def map_trade_data(trade_data):
    """Normalize filled Mudrex orders to trade format."""
    try:
        if trade_data is None:
            return []
        if isinstance(trade_data, dict) and "status" in trade_data:
            if trade_data.get("status") in ("error", "failure"):
                return []
        if isinstance(trade_data, str):
            return []
        if not isinstance(trade_data, list):
            return []

        for trade in trade_data:
            if not isinstance(trade, dict):
                continue

            symbol_raw = trade.get("symbol", "")
            asset_uuid = trade.get("asset_uuid", "")
            sym_from_db = get_symbol(asset_uuid, _EXCHANGE) if asset_uuid else None

            trade["tradingSymbol"] = sym_from_db or symbol_raw
            trade["exchangeSegment"] = _EXCHANGE
            trade["productType"] = "NRML"

            ot = trade.get("order_type", "").upper()
            trade["transactionType"] = "BUY" if ot == "LONG" else "SELL"

            trade["orderId"] = str(trade.get("id", ""))
            trade["tradedQuantity"] = _safe_float(trade.get("filled_quantity"))
            trade["tradedPrice"] = _safe_float(trade.get("filled_price"))
            trade["updateTime"] = trade.get("updated_at", trade.get("created_at", ""))

        return trade_data
    except Exception as exc:
        logger.exception(f"[Mudrex] map_trade_data error: {exc}")
        return []


def transform_tradebook_data(tradebook_data):
    """Transform trade data to OpenAlgo standard format."""
    try:
        if not tradebook_data or not isinstance(tradebook_data, list):
            return []

        transformed = []
        for trade in tradebook_data:
            if not isinstance(trade, dict):
                continue

            quantity = _safe_float(trade.get("tradedQuantity"))
            price = _safe_float(trade.get("tradedPrice"))

            transformed.append({
                "symbol": trade.get("tradingSymbol", ""),
                "exchange": trade.get("exchangeSegment", ""),
                "product": trade.get("productType", ""),
                "action": trade.get("transactionType", ""),
                "quantity": quantity,
                "average_price": price,
                "trade_value": quantity * price,
                "orderid": trade.get("orderId", ""),
                "timestamp": trade.get("updateTime", ""),
            })

        return transformed
    except Exception as exc:
        logger.exception(f"[Mudrex] transform_tradebook_data error: {exc}")
        return []


# ---------------------------------------------------------------------------
# Positions
# ---------------------------------------------------------------------------

def map_position_data(position_data):
    """Normalize Mudrex position dicts to OpenAlgo position format."""
    try:
        if position_data is None:
            return []
        if isinstance(position_data, dict) and "status" in position_data:
            if position_data.get("status") in ("error", "failure"):
                return []
        if isinstance(position_data, str):
            return []
        if not isinstance(position_data, list):
            return []

        processed = []
        for pos in position_data:
            if not isinstance(pos, dict):
                continue

            symbol_raw = pos.get("symbol", "")
            asset_uuid = pos.get("asset_uuid", "")
            sym_from_db = get_symbol(asset_uuid, _EXCHANGE) if asset_uuid else None
            pos["tradingSymbol"] = sym_from_db or symbol_raw

            pos["exchangeSegment"] = _EXCHANGE
            pos["productType"] = "NRML"

            ot = pos.get("order_type", "").upper()
            qty = _safe_float(pos.get("quantity"))
            net_qty = qty if ot == "LONG" else -qty

            pos["netQty"] = net_qty
            pos["avgCostPrice"] = _safe_float(pos.get("entry_price"))
            pos["lastTradedPrice"] = _safe_float(
                pos.get("mark_price", pos.get("last_price", pos.get("price")))
            )
            pos["marketValue"] = _safe_float(pos.get("notional_value"))
            # Keep parity with Delta: total pnl = realised + unrealised when present.
            realised = _safe_float(pos.get("realized_pnl", pos.get("realised_pnl")))
            unrealised = _safe_float(pos.get("unrealized_pnl", pos.get("unrealised_pnl", pos.get("pnl"))))
            pos["pnlAbsolute"] = realised + unrealised

            lot_size = 1.0
            if sym_from_db:
                sym_info = get_symbol_info(sym_from_db, _EXCHANGE)
                if sym_info and getattr(sym_info, "contract_value", None) is not None:
                    lot_size = float(sym_info.contract_value)
            pos["lot_size"] = lot_size
            pos["multiplier"] = 1
            pos["positionType"] = "open" if net_qty != 0 else "closed"

            processed.append(pos)

        return processed
    except Exception as exc:
        logger.exception(f"[Mudrex] map_position_data error: {exc}")
        return []


def transform_positions_data(positions_data):
    """Transform positions to OpenAlgo standard format."""
    try:
        if not positions_data or not isinstance(positions_data, list):
            return []

        transformed = []
        for pos in positions_data:
            if not isinstance(pos, dict):
                continue
            transformed.append({
                "symbol": pos.get("tradingSymbol", ""),
                "exchange": pos.get("exchangeSegment", ""),
                "product": pos.get("productType", ""),
                "quantity": pos.get("netQty", 0),
                "average_price": float(pos.get("avgCostPrice", 0.0)),
                "ltp": float(pos.get("lastTradedPrice", 0.0)),
                "pnl": float(pos.get("pnlAbsolute", 0.0)),
                "lot_size": float(pos.get("lot_size", 1.0)),
            })
        return transformed
    except Exception as exc:
        logger.exception(f"[Mudrex] transform_positions_data error: {exc}")
        return []


# ---------------------------------------------------------------------------
# Holdings (not applicable for futures-only broker)
# ---------------------------------------------------------------------------

def map_holdings_data(holdings_data):
    """Mudrex is futures-only; return empty."""
    return []


def transform_holdings_data(holdings_data):
    """Transform holdings data — always empty for Mudrex."""
    return []


# ---------------------------------------------------------------------------
# Portfolio
# ---------------------------------------------------------------------------

def map_portfolio_data(portfolio_data):
    """Process portfolio (holdings) data. No-op for futures-only broker."""
    if portfolio_data is None or not isinstance(portfolio_data, list):
        return []
    return portfolio_data


def calculate_portfolio_statistics(holdings_data):
    """Calculate portfolio statistics — always zero for Mudrex."""
    return {
        "totalholdingvalue": 0.0,
        "totalinvvalue": 0.0,
        "totalprofitandloss": 0.0,
        "totalpnlpercentage": 0.0,
    }
