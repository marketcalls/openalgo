# services/order_router_service.py

from typing import Any, Dict, Optional, Tuple

from database.action_center_db import create_pending_order
from database.auth_db import get_order_mode, verify_api_key
from extensions import socketio
from utils.logging import get_logger

# Initialize logger
logger = get_logger(__name__)

# Operations that should NEVER be queued
# Note: closeposition, cancelorder, cancelallorder, modifyorder are blocked in semi-auto mode
# The remaining operations (status checks, data retrieval) always execute immediately
IMMEDIATE_EXECUTION_OPERATIONS = {
    "closeallpositions",
    "closeposition",
    "cancelorder",
    "cancelallorder",
    "modifyorder",
    "orderstatus",
    "orderbook",
    "tradebook",
    "positions",
    "holdings",
    "funds",
    "openposition",
}


def should_route_to_pending(api_key: str, api_type: str | None = None) -> bool:
    """
    Check if orders should be routed to Action Center (pending orders)

    Args:
        api_key: OpenAlgo API key
        api_type: Type of operation (e.g., 'placeorder', 'closeposition', etc.)

    Returns:
        bool: True if orders should be queued, False if they should execute immediately
    """
    try:
        # Operations that should always execute immediately (never queue)
        if api_type and api_type.lower() in IMMEDIATE_EXECUTION_OPERATIONS:
            logger.debug(
                f"Operation '{api_type}' will execute immediately (immediate execution operation)"
            )
            return False

        # Verify API key and get user ID
        user_id = verify_api_key(api_key)
        if not user_id:
            return False

        # Get order mode for user
        order_mode = get_order_mode(user_id)

        # Route to pending if semi_auto mode
        is_semi_auto = order_mode == "semi_auto"

        if is_semi_auto:
            logger.debug(
                f"Order will be routed to Action Center for user {user_id} (semi_auto mode)"
            )

        return is_semi_auto

    except Exception as e:
        logger.exception(f"Error checking order routing: {e}")
        # Default to auto mode on error (execute immediately)
        return False


def queue_order(
    api_key: str, order_data: dict[str, Any], api_type: str
) -> tuple[bool, dict[str, Any], int]:
    """
    Queue an order to the Action Center (pending_orders table)

    Args:
        api_key: OpenAlgo API key
        order_data: Order data dictionary
        api_type: Type of order ('placeorder', 'smartorder', 'basketorder', 'splitorder')

    Returns:
        Tuple containing:
        - Success status (bool)
        - Response data (dict)
        - HTTP status code (int)
    """
    try:
        # Verify API key and get user ID
        user_id = verify_api_key(api_key)
        if not user_id:
            logger.warning("Invalid API key for queuing order")
            return False, {"status": "error", "message": "Invalid API key"}, 403

        # Create a copy of order data without apikey for storage
        order_data_clean = order_data.copy()
        if "apikey" in order_data_clean:
            del order_data_clean["apikey"]

        # Create pending order
        pending_order_id = create_pending_order(user_id, api_type, order_data_clean)

        if pending_order_id:
            logger.info(
                f"Order queued successfully: pending_order_id={pending_order_id}, user={user_id}, type={api_type}"
            )

            # Emit socket event to notify about new pending order
            socketio.start_background_task(
                socketio.emit,
                "pending_order_created",
                {
                    "pending_order_id": pending_order_id,
                    "user_id": user_id,
                    "api_type": api_type,
                    "message": f"New {api_type} order queued for approval",
                },
            )

            return (
                True,
                {
                    "status": "success",
                    "message": "Order queued for approval in Action Center",
                    "mode": "semi_auto",
                    "pending_order_id": pending_order_id,
                },
                200,
            )
        else:
            logger.error("Failed to create pending order")
            return False, {"status": "error", "message": "Failed to queue order"}, 500

    except Exception as e:
        logger.exception(f"Error queuing order: {e}")
        return False, {"status": "error", "message": f"Failed to queue order: {str(e)}"}, 500
