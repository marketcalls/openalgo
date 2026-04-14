# services/action_center_service.py

import json
from typing import Any, Dict, List, Tuple

from database.action_center_db import get_pending_orders
from utils.logging import get_logger

# Initialize logger
logger = get_logger(__name__)


def parse_pending_order(pending_order) -> dict[str, Any]:
    """
    Parse a pending order object into a dictionary for display
    Handles different order types: placeorder, smartorder, basketorder, splitorder, optionsorder

    Args:
        pending_order: PendingOrder database object

    Returns:
        dict: Parsed order data
    """
    try:
        # Parse JSON order data
        order_data = json.loads(pending_order.order_data)
        api_type = pending_order.api_type

        # Common fields for all order types
        order_dict = {
            "id": pending_order.id,
            "user_id": pending_order.user_id,
            "api_type": api_type,
            "status": pending_order.status,
            # Timestamps
            "created_at_ist": pending_order.created_at_ist,
            "approved_at_ist": pending_order.approved_at_ist,
            "approved_by": pending_order.approved_by,
            "rejected_at_ist": pending_order.rejected_at_ist,
            "rejected_by": pending_order.rejected_by,
            "rejected_reason": pending_order.rejected_reason,
            # Broker status
            "broker_order_id": pending_order.broker_order_id,
            "broker_status": pending_order.broker_status,
            # Strategy (common to all)
            "strategy": order_data.get("strategy", "N/A"),
            # Raw order data for details view (exclude sensitive data)
            "raw_order_data": {
                k: v for k, v in order_data.items() if k not in ["apikey", "api_key"]
            },
        }

        # Parse based on API type
        if api_type == "optionsorder":
            # Options order format
            order_dict.update(
                {
                    "symbol": f"{order_data.get('underlying', '')} {order_data.get('offset', '')} {order_data.get('option_type', '')}",
                    "exchange": order_data.get("exchange", ""),
                    "action": order_data.get("action", ""),
                    "quantity": order_data.get("quantity", ""),
                    "price": order_data.get("price", "0"),
                    "trigger_price": order_data.get("trigger_price", "0"),
                    "price_type": order_data.get("pricetype", "MARKET"),
                    "product_type": order_data.get("product", ""),
                }
            )

        elif api_type == "basketorder":
            # Basket order format - show summary
            orders = order_data.get("orders", [])
            order_dict.update(
                {
                    "symbol": f"Basket ({len(orders)} orders)",
                    "exchange": "Multiple"
                    if len(orders) > 1
                    else orders[0].get("exchange", "")
                    if orders
                    else "",
                    "action": "Multiple"
                    if len(orders) > 1
                    else orders[0].get("action", "")
                    if orders
                    else "",
                    "quantity": str(sum(int(o.get("quantity", 0)) for o in orders)),
                    "price": "Multiple",
                    "trigger_price": "0",
                    "price_type": "Multiple",
                    "product_type": "Multiple",
                }
            )

        elif api_type == "smartorder":
            # Smart order format
            order_dict.update(
                {
                    "symbol": order_data.get("symbol", ""),
                    "exchange": order_data.get("exchange", ""),
                    "action": order_data.get("action", ""),
                    "quantity": order_data.get("quantity", ""),
                    "price": order_data.get("price", "0"),
                    "trigger_price": order_data.get("trigger_price", "0"),
                    "price_type": order_data.get(
                        "pricetype", order_data.get("price_type", "MARKET")
                    ),
                    "product_type": order_data.get("product", order_data.get("product_type", "")),
                }
            )

        elif api_type == "splitorder":
            # Split order format
            order_dict.update(
                {
                    "symbol": order_data.get("symbol", ""),
                    "exchange": order_data.get("exchange", ""),
                    "action": order_data.get("action", ""),
                    "quantity": f"{order_data.get('quantity', '')} (split: {order_data.get('splitsize', '')})",
                    "price": order_data.get("price", "0"),
                    "trigger_price": order_data.get("trigger_price", "0"),
                    "price_type": order_data.get(
                        "pricetype", order_data.get("price_type", "MARKET")
                    ),
                    "product_type": order_data.get("product", order_data.get("product_type", "")),
                }
            )

        else:  # placeorder (default)
            # Regular order format
            order_dict.update(
                {
                    "symbol": order_data.get("symbol", ""),
                    "exchange": order_data.get("exchange", ""),
                    "action": order_data.get("action", ""),
                    "quantity": order_data.get("quantity", ""),
                    "price": order_data.get("price", "0"),
                    "trigger_price": order_data.get("trigger_price", "0"),
                    "price_type": order_data.get(
                        "price_type", order_data.get("pricetype", "MARKET")
                    ),
                    "product_type": order_data.get("product_type", order_data.get("product", "")),
                }
            )

        return order_dict

    except Exception as e:
        logger.exception(f"Error parsing pending order (api_type={pending_order.api_type}): {e}")
        return {
            "id": pending_order.id if hasattr(pending_order, "id") else None,
            "api_type": pending_order.api_type if hasattr(pending_order, "api_type") else "unknown",
            "strategy": "Error",
            "symbol": "Error parsing order",
            "exchange": "-",
            "action": "-",
            "quantity": "-",
            "price": "-",
            "price_type": "-",
            "product_type": "-",
            "error": str(e),
        }


def calculate_action_center_stats(orders_list: list[dict[str, Any]]) -> dict[str, int]:
    """
    Calculate statistics for action center dashboard

    Args:
        orders_list: List of parsed order dictionaries

    Returns:
        dict: Statistics dictionary
    """
    stats = {
        "total_pending": 0,
        "total_approved": 0,
        "total_rejected": 0,
        "total_buy_orders": 0,
        "total_sell_orders": 0,
        "total_placeorder": 0,
        "total_smartorder": 0,
        "total_basketorder": 0,
        "total_splitorder": 0,
    }

    for order in orders_list:
        # Count by status
        if order.get("status") == "pending":
            stats["total_pending"] += 1
        elif order.get("status") == "approved":
            stats["total_approved"] += 1
        elif order.get("status") == "rejected":
            stats["total_rejected"] += 1

        # Count by action
        action = order.get("action", "").upper()
        if action == "BUY":
            stats["total_buy_orders"] += 1
        elif action == "SELL":
            stats["total_sell_orders"] += 1

        # Count by API type
        api_type = order.get("api_type", "")
        if api_type == "placeorder":
            stats["total_placeorder"] += 1
        elif api_type == "smartorder":
            stats["total_smartorder"] += 1
        elif api_type == "basketorder":
            stats["total_basketorder"] += 1
        elif api_type == "splitorder":
            stats["total_splitorder"] += 1

    return stats


def get_action_center_data(
    user_id: str, status_filter: str = None
) -> tuple[bool, dict[str, Any], int]:
    """
    Get pending orders for action center display

    Args:
        user_id: User identifier
        status_filter: Optional status filter ('pending', 'approved', 'rejected', or None for all)

    Returns:
        Tuple containing:
        - Success status (bool)
        - Response data (dict)
        - HTTP status code (int)
    """
    try:
        # Get ALL orders for statistics calculation (always show correct counts in tabs)
        all_orders = get_pending_orders(user_id, status=None)
        all_orders_list = []
        for order in all_orders:
            order_dict = parse_pending_order(order)
            all_orders_list.append(order_dict)

        # Calculate statistics from ALL orders
        stats = calculate_action_center_stats(all_orders_list)

        # Get filtered orders for display
        if status_filter:
            filtered_orders = get_pending_orders(user_id, status=status_filter)
            orders_list = []
            for order in filtered_orders:
                order_dict = parse_pending_order(order)
                orders_list.append(order_dict)
        else:
            # If no filter, use all orders
            orders_list = all_orders_list

        response_data = {"status": "success", "data": {"orders": orders_list, "statistics": stats}}

        logger.info(
            f"Retrieved {len(orders_list)} orders for user {user_id} (filter: {status_filter})"
        )
        return True, response_data, 200

    except Exception as e:
        logger.exception(f"Error getting action center data: {e}")
        return (
            False,
            {"status": "error", "message": f"Failed to retrieve action center data: {str(e)}"},
            500,
        )
