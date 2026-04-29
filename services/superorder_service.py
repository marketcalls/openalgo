import copy
from typing import Any, Optional

from database.auth_db import get_auth_token_broker, verify_api_key
from database.superorder_db import SuperOrder, db_session
from utils.logging import get_logger

# Initialize logger
logger = get_logger(__name__)


def place_superorder(
    order_data: dict[str, Any], api_key: str | None = None
) -> tuple[bool, dict[str, Any], int]:
    """
    Place a Super Order.
    """
    if not api_key:
        return False, {"status": "error", "message": "API key is required"}, 401

    user_id = verify_api_key(api_key)
    if not user_id:
        return False, {"status": "error", "message": "Invalid API key"}, 401

    AUTH_TOKEN, broker_name = get_auth_token_broker(api_key)
    if not AUTH_TOKEN:
        return (
            False,
            {
                "status": "error",
                "message": "Invalid openalgo apikey or broker configuration missing",
            },
            403,
        )

    try:
        import datetime

        # Calculate expiration time
        expires_at = None
        if order_data["product"].upper() in ["INTRADAY", "MIS"]:
            # Auto-cancel at end of day
            today = datetime.datetime.now().replace(
                hour=15, minute=30, second=0, microsecond=0
            )
            expires_at = today
        else:
            # Valid for up to 365 days
            expires_at = datetime.datetime.now() + datetime.timedelta(days=365)

        # Create SuperOrder in database
        super_order = SuperOrder(
            user_id=user_id,
            symbol=order_data["symbol"],
            exchange=order_data["exchange"],
            product_type=order_data["product"],
            transaction_type=order_data["action"],
            quantity=order_data["quantity"],
            entry_price=order_data["price"],
            target_price=order_data["target_price"],
            stoploss_price=order_data["stoploss_price"],
            trail_jump=order_data.get("trail_jump"),
            order_tag=order_data.get("order_tag"),
            status="PENDING",
            expires_at=expires_at,
        )

        # Determine pricetype for Main Leg
        if order_data["price"] > 0:
            pricetype = "LIMIT"
        else:
            pricetype = "MARKET"

        # Place the main leg order using existing place_order service
        main_leg_data = {
            "apikey": api_key,
            "strategy": order_data.get("strategy", "SuperOrder"),
            "symbol": order_data["symbol"],
            "exchange": order_data["exchange"],
            "action": order_data["action"],
            "quantity": order_data["quantity"],
            "pricetype": pricetype,
            "product": order_data["product"],
            "price": order_data["price"],
        }

        from services.place_order_service import place_order
        success, response_data, status_code = place_order(
            order_data=main_leg_data,
            api_key=api_key,
        )

        if success:
            super_order.main_order_id = str(response_data.get("orderid"))
            db_session.add(super_order)
            db_session.commit()
            return (
                True,
                {
                    "status": "success",
                    "message": "Super Order placed successfully",
                    "super_order_id": super_order.id,
                    "main_order_id": super_order.main_order_id,
                },
                200,
            )
        else:
            # If main order fails, save SuperOrder as FAILED
            super_order.status = "FAILED"
            db_session.add(super_order)
            db_session.commit()
            return False, response_data, status_code

    except Exception as e:
        logger.exception(f"Error in place_superorder: {str(e)}")
        db_session.rollback()
        return False, {"status": "error", "message": "Failed to place Super Order"}, 500


def get_superorders(api_key: str | None = None) -> tuple[bool, dict[str, Any], int]:
    """
    Get all Super Orders for a user.
    """
    user_id = verify_api_key(api_key)
    if not user_id:
        return False, {"status": "error", "message": "Invalid API key"}, 401

    try:
        orders = (
            SuperOrder.query.filter_by(user_id=user_id)
            .order_by(SuperOrder.created_at.desc())
            .all()
        )
        result = []
        for order in orders:
            result.append(
                {
                    "id": order.id,
                    "symbol": order.symbol,
                    "exchange": order.exchange,
                    "product_type": order.product_type,
                    "transaction_type": order.transaction_type,
                    "quantity": order.quantity,
                    "entry_price": float(order.entry_price),
                    "target_price": float(order.target_price),
                    "stoploss_price": float(order.stoploss_price),
                    "trail_jump": float(order.trail_jump) if order.trail_jump else None,
                    "main_order_id": order.main_order_id,
                    "target_order_id": order.target_order_id,
                    "stoploss_order_id": order.stoploss_order_id,
                    "status": order.status,
                    "order_tag": order.order_tag,
                    "created_at": (
                        order.created_at.isoformat() if order.created_at else None
                    ),
                    "updated_at": (
                        order.updated_at.isoformat() if order.updated_at else None
                    ),
                }
            )
        return True, {"status": "success", "data": result}, 200
    except Exception as e:
        logger.exception(f"Error in get_superorders: {str(e)}")
        return (
            False,
            {"status": "error", "message": "Failed to fetch Super Orders"},
            500,
        )


def get_superorder(
    order_id: int, api_key: str | None = None
) -> tuple[bool, dict[str, Any], int]:
    """
    Get details of a specific Super Order.
    """
    user_id = verify_api_key(api_key)
    if not user_id:
        return False, {"status": "error", "message": "Invalid API key"}, 401

    try:
        order = SuperOrder.query.filter_by(id=order_id, user_id=user_id).first()
        if not order:
            return False, {"status": "error", "message": "Super Order not found"}, 404

        result = {
            "id": order.id,
            "symbol": order.symbol,
            "exchange": order.exchange,
            "product_type": order.product_type,
            "transaction_type": order.transaction_type,
            "quantity": order.quantity,
            "entry_price": float(order.entry_price),
            "target_price": float(order.target_price),
            "stoploss_price": float(order.stoploss_price),
            "trail_jump": float(order.trail_jump) if order.trail_jump else None,
            "main_order_id": order.main_order_id,
            "target_order_id": order.target_order_id,
            "stoploss_order_id": order.stoploss_order_id,
            "status": order.status,
            "order_tag": order.order_tag,
            "created_at": order.created_at.isoformat() if order.created_at else None,
            "updated_at": order.updated_at.isoformat() if order.updated_at else None,
        }
        return True, {"status": "success", "data": result}, 200
    except Exception as e:
        logger.exception(f"Error in get_superorder: {str(e)}")
        return False, {"status": "error", "message": "Failed to fetch Super Order"}, 500


def modify_superorder(
    order_data: dict[str, Any], api_key: str | None = None
) -> tuple[bool, dict[str, Any], int]:
    """
    Modify a Super Order.
    In PENDING state: all legs (price + quantity) can be modified.
    In ACTIVE state: only Target and SL price can be modified (NOT quantity).
    """
    user_id = verify_api_key(api_key)
    if not user_id:
        return False, {"status": "error", "message": "Invalid API key"}, 401

    AUTH_TOKEN, broker_name = get_auth_token_broker(api_key)
    if not AUTH_TOKEN:
        return (
            False,
            {
                "status": "error",
                "message": "Invalid openalgo apikey or broker configuration missing",
            },
            403,
        )

    try:
        order = SuperOrder.query.filter_by(
            id=order_data["order_id"], user_id=user_id
        ).first()
        if not order:
            return False, {"status": "error", "message": "Super Order not found"}, 404

        if order.status not in ["PENDING", "ACTIVE"]:
            return (
                False,
                {
                    "status": "error",
                    "message": f"Cannot modify Super Order in {order.status} state",
                },
                400,
            )

        # Update fields
        if order_data.get("target_price") is not None:
            order.target_price = order_data["target_price"]
        if order_data.get("stoploss_price") is not None:
            order.stoploss_price = order_data["stoploss_price"]
        if order_data.get("trail_jump") is not None:
            order.trail_jump = order_data["trail_jump"]

        if order.status == "PENDING":
            mod_main_leg = False
            main_leg_mod_data = {
                "orderid": order.main_order_id,
                "symbol": order.symbol,
                "exchange": order.exchange,
                "action": order.transaction_type,
                "product": order.product_type,
                "pricetype": "LIMIT" if order.entry_price > 0 else "MARKET",
            }
            if (
                order_data.get("quantity") is not None
                and order_data["quantity"] != order.quantity
            ):
                order.quantity = order_data["quantity"]
                main_leg_mod_data["quantity"] = order.quantity
                mod_main_leg = True

            if (
                order_data.get("price") is not None
                and order_data["price"] != order.entry_price
            ):
                order.entry_price = order_data["price"]
                main_leg_mod_data["price"] = order.entry_price
                main_leg_mod_data["pricetype"] = (
                    "LIMIT" if order.entry_price > 0 else "MARKET"
                )
                mod_main_leg = True

            if mod_main_leg:
                from services.modify_order_service import modify_order
                success, resp, code = modify_order(
                    order_data=main_leg_mod_data, api_key=api_key
                )
                if not success:
                    db_session.rollback()
                    return False, resp, code
        else:
            # Active state
            if (
                order_data.get("quantity") is not None
                or order_data.get("price") is not None
            ):
                return (
                    False,
                    {
                        "status": "error",
                        "message": "Can only modify target and SL prices in ACTIVE state",
                    },
                    400,
                )

        db_session.commit()
        return (
            True,
            {"status": "success", "message": "Super Order modified successfully"},
            200,
        )

    except Exception as e:
        logger.exception(f"Error in modify_superorder: {str(e)}")
        db_session.rollback()
        return (
            False,
            {"status": "error", "message": "Failed to modify Super Order"},
            500,
        )


def cancel_superorder(
    order_id: int, api_key: str | None = None
) -> tuple[bool, dict[str, Any], int]:
    """
    Cancel a Super Order.
    """
    user_id = verify_api_key(api_key)
    if not user_id:
        return False, {"status": "error", "message": "Invalid API key"}, 401

    try:
        order = SuperOrder.query.filter_by(id=order_id, user_id=user_id).first()
        if not order:
            return False, {"status": "error", "message": "Super Order not found"}, 404

        from services.cancel_order_service import cancel_order

        if order.status == "PENDING":
            if order.main_order_id:
                success, resp, code = cancel_order(
                    orderid=order.main_order_id, api_key=api_key
                )
                if success:
                    order.status = "CANCELLED"
                    db_session.commit()
                    return (
                        True,
                        {
                            "status": "success",
                            "message": "Super Order cancelled successfully",
                        },
                        200,
                    )
                else:
                    return False, resp, code
        elif order.status == "ACTIVE":
            order.status = "CANCELLED"
            # Cancel any active target or SL orders on the exchange
            if order.target_order_id:
                cancel_order(orderid=order.target_order_id, api_key=api_key)
            if order.stoploss_order_id:
                cancel_order(orderid=order.stoploss_order_id, api_key=api_key)

            db_session.commit()
            return (
                True,
                {
                    "status": "success",
                    "message": "Super Order target and SL cancelled successfully",
                },
                200,
            )
        else:
            return (
                False,
                {
                    "status": "error",
                    "message": f"Cannot cancel Super Order in {order.status} state",
                },
                400,
            )

    except Exception as e:
        logger.exception(f"Error in cancel_superorder: {str(e)}")
        db_session.rollback()
        return (
            False,
            {"status": "error", "message": "Failed to cancel Super Order"},
            500,
        )
