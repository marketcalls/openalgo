import copy
from typing import Any, Dict, Optional, Tuple

from database.bracket_order_db import (
    create_bracket_order,
    get_active_bo_for_symbol,
    get_bracket_order_by_bo_id,
    update_bracket_order,
)
from events.order_events import (
    BracketOrderCancelledEvent,
    BracketOrderPlacedEvent,
)
from services.cancel_order_service import cancel_order_with_auth
from utils.event_bus import EventBus
from utils.logging import get_logger

logger = get_logger(__name__)
bus = EventBus()

def calculate_exit_prices(
    entry_price: float,
    action: str,
    target_type: str,
    target_value: float,
    sl_type: str,
    sl_value: float,
) -> tuple[float, float]:
    """
    Calculate target and stop-loss prices based on entry price and strategy parameters.
    """
    if action.upper() == "BUY":
        if target_type == "points":
            target_price = entry_price + target_value
        elif target_type == "percentage":
            target_price = entry_price * (1 + target_value / 100)
        else:  # absolute
            target_price = target_value

        if sl_type == "points":
            sl_price = entry_price - sl_value
        elif sl_type == "percentage":
            sl_price = entry_price * (1 - sl_value / 100)
        else:  # absolute
            sl_price = sl_value

    else:  # SELL
        if target_type == "points":
            target_price = entry_price - target_value
        elif target_type == "percentage":
            target_price = entry_price * (1 - target_value / 100)
        else:  # absolute
            target_price = target_value

        if sl_type == "points":
            sl_price = entry_price + sl_value
        elif sl_type == "percentage":
            sl_price = entry_price * (1 + sl_value / 100)
        else:  # absolute
            sl_price = sl_value

    # Round to 2 decimal places to be safe for Indian markets
    return round(target_price, 2), round(sl_price, 2)


def place_bracket_order(order_data: dict[str, Any], api_key: str) -> tuple[bool, dict[str, Any], int]:
    """
    Place a new bracket order.
    """
    try:
        strategy = order_data.get("strategy")
        symbol = order_data.get("symbol")
        exchange = order_data.get("exchange")
        action = order_data.get("action", "").upper()
        product = order_data.get("product", "MIS")
        quantity = int(order_data.get("quantity", 0))
        price_type = order_data.get("price_type", "MARKET").upper()
        price = float(order_data.get("price", 0.0))
        
        target_type = order_data.get("target_type")
        target_value = float(order_data.get("target_value", 0.0))
        sl_type = order_data.get("sl_type")
        sl_value = float(order_data.get("sl_value", 0.0))

        # Check for duplicates
        existing_bo = get_active_bo_for_symbol(api_key, symbol, exchange, action)
        if existing_bo:
            return False, {
                "status": "error",
                "message": f"Active bracket order already exists for {symbol} ({action})"
            }, 400

        # Create DB record
        bo_id = create_bracket_order(
            api_key=api_key,
            strategy=strategy,
            symbol=symbol,
            exchange=exchange,
            action=action,
            product=product,
            quantity=quantity,
            price_type=price_type,
            price=price,
            target_type=target_type,
            target_value=target_value,
            sl_type=sl_type,
            sl_value=sl_value,
        )

        if not bo_id:
            return False, {"status": "error", "message": "Failed to initialize bracket order"}, 500

        # Place the entry order using standard place_order logic (handles routing and analyze mode)
        entry_payload = {
            "apikey": api_key,
            "strategy": strategy,
            "symbol": symbol,
            "exchange": exchange,
            "action": action,
            "quantity": str(quantity),
            "pricetype": price_type,
            "product": product,
        }
        
        if price_type == "LIMIT":
            entry_payload["price"] = str(price)

        from services.place_order_service import place_order
        success, resp, status_code = place_order(entry_payload, api_key=api_key)

        if success and resp.get("status") == "success":
            entry_order_id = resp.get("orderid", "")
            
            update_bracket_order(bo_id, {
                "status": "ENTRY_PENDING",
                "entry_order_id": entry_order_id
            })
            
            bus.publish(BracketOrderPlacedEvent(
                bo_id=bo_id,
                symbol=symbol,
                exchange=exchange,
                action=action,
                entry_order_id=entry_order_id
            ))
            
            return True, {
                "status": "success",
                "message": "Bracket order placed successfully",
                "bo_id": bo_id,
                "entry_order_id": entry_order_id
            }, 200
        else:
            error_message = resp.get("message", "Broker rejected entry order")
            update_bracket_order(bo_id, {
                "status": "FAILED",
                "error_message": error_message
            })
            return False, resp, status_code

    except Exception as e:
        logger.error(f"Error placing bracket order: {e}")
        return False, {"status": "error", "message": str(e)}, 500


def get_bracket_order_status(bo_id: str, api_key: str) -> tuple[bool, dict[str, Any], int]:
    """
    Get the status of a bracket order.
    """
    bo = get_bracket_order_by_bo_id(bo_id, api_key)
    if not bo:
        return False, {"status": "error", "message": "Bracket order not found or invalid API key"}, 404

    return True, {
        "status": "success",
        "data": {
            "bo_id": bo["bo_id"],
            "bo_status": bo["status"],
            "strategy": bo["strategy"],
            "symbol": bo["symbol"],
            "exchange": bo["exchange"],
            "action": bo["action"],
            "product": bo["product"],
            "quantity": bo["quantity"],
            "target_type": bo["target_type"],
            "target_value": bo["target_value"],
            "sl_type": bo["sl_type"],
            "sl_value": bo["sl_value"],
            "entry_order_id": bo["entry_order_id"],
            "target_order_id": bo["target_order_id"],
            "sl_order_id": bo["sl_order_id"],
            "entry_price": bo["entry_price"],
            "target_price": bo["target_price"],
            "sl_price": bo["sl_price"],
            "exit_price": bo["exit_price"],
            "exit_type": bo["exit_type"],
            "error_message": bo["error_message"],
            "created_at": bo["created_at"],
            "updated_at": bo["updated_at"]
        }
    }, 200


def cancel_bracket_order(
    bo_id: str, api_key: str, auth_token: str, broker: str, square_off: bool = False
) -> tuple[bool, dict[str, Any], int]:
    """
    Cancel an active bracket order. 
    Requires auth_token and broker resolved from the api_key.
    """
    bo = get_bracket_order_by_bo_id(bo_id, api_key)
    if not bo:
        return False, {"status": "error", "message": "Bracket order not found or invalid API key"}, 404

    status = bo["status"]
    
    if status in ["COMPLETED", "FAILED", "CANCELLED"]:
        return False, {"status": "error", "message": f"Bracket order is already terminal ({status})"}, 400

    try:
        messages = []
        if status == "ENTRY_PENDING" and bo["entry_order_id"]:
            # Cancel entry
            status_data = {"orderid": bo["entry_order_id"], "strategy": bo["strategy"]}
            ok, resp, _ = cancel_order_with_auth(status_data, auth_token, broker, status_data)
            if ok:
                messages.append("Entry order cancelled")
            
        elif status == "ACTIVE":
            # Cancel target
            if bo["target_order_id"]:
                status_data = {"orderid": bo["target_order_id"], "strategy": bo["strategy"]}
                ok, resp, _ = cancel_order_with_auth(status_data, auth_token, broker, status_data)
                if ok:
                    messages.append("Target order cancelled")
            
            # Cancel SL
            if bo["sl_order_id"]:
                status_data = {"orderid": bo["sl_order_id"], "strategy": bo["strategy"]}
                ok, resp, _ = cancel_order_with_auth(status_data, auth_token, broker, status_data)
                if ok:
                    messages.append("SL order cancelled")
            
            # Square off via market order if requested
            if square_off:
                close_action = "SELL" if bo["action"] == "BUY" else "BUY"
                sq_payload = {
                    "apikey": api_key,
                    "strategy": bo["strategy"],
                    "symbol": bo["symbol"],
                    "exchange": bo["exchange"],
                    "action": close_action,
                    "quantity": str(bo["quantity"]),
                    "pricetype": "MARKET",
                    "product": bo["product"]
                }
                from services.place_order_service import place_order
                sq_ok, sq_resp, _ = place_order(sq_payload, api_key=api_key)
                if sq_ok:
                    messages.append("Position squared off")
                else:
                    messages.append("Failed to square off position")

        update_bracket_order(bo_id, {"status": "CANCELLED"})
        bus.publish(BracketOrderCancelledEvent(bo_id=bo_id))
        
        return True, {
            "status": "success",
            "message": "Bracket order cancelled",
            "details": messages
        }, 200

    except Exception as e:
        logger.error(f"Error cancelling BO {bo_id}: {e}")
        return False, {"status": "error", "message": f"Error during cancellation: {str(e)}"}, 500
