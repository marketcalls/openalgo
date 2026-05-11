import os
import copy
import threading
import time
from datetime import datetime, timezone
from database.auth_db import get_auth_token_broker
from database.bracket_order_db import (
    get_orders_by_status,
    update_bracket_order,
)
from events.order_events import BracketOrderCompletedEvent, BracketOrderFilledEvent
from services.bracket_order_service import calculate_exit_prices
from services.cancel_order_service import cancel_order_with_auth
from services.orderstatus_service import get_order_status
from services.place_order_service import place_order
from utils.event_bus import EventBus
from utils.logging import get_logger

logger = get_logger(__name__)
bus = EventBus()

# Manager state
_running = False
_thread = None

# Polling interval (default 3s)
POLL_INTERVAL = int(os.getenv("BO_POLL_INTERVAL_SECONDS", "3"))
ENTRY_TIMEOUT = int(os.getenv("BO_ENTRY_TIMEOUT_SECONDS", "7200"))

def _get_time_elapsed(dt_obj):
    if not dt_obj:
        return 0
    now = datetime.now(timezone.utc)
    # Ensure dt_obj is timezone aware for comparison
    if dt_obj.tzinfo is None:
        dt_obj = dt_obj.replace(tzinfo=timezone.utc)
    return (now - dt_obj).total_seconds()


def _process_pending_entries():
    """Phase A: Monitor entry orders"""
    try:
        bos = get_orders_by_status(["ENTRY_PENDING"])
        for bo in bos:
            bo_id = bo["bo_id"]
            entry_order_id = bo["entry_order_id"]
            
            if not entry_order_id:
                logger.warning(f"BO {bo_id} is ENTRY_PENDING but has no entry_order_id")
                continue

            # Check status
            status_data = {"orderid": entry_order_id, "strategy": bo["strategy"]}
            ok, resp, _ = get_order_status(status_data, api_key=bo["api_key"])
            
            if not ok or resp.get("status") != "success":
                continue
                
            data = resp.get("data", {})
            order_status = data.get("order_status", "").lower()

            if order_status == "complete":
                # Entry Filled!
                fill_price = float(data.get("price", bo["price"]))
                if fill_price <= 0:
                    fill_price = float(data.get("average_price", 0))

                logger.info(f"BO {bo_id} entry filled at {fill_price}")
                
                # Calculate exit prices
                target_price, sl_price = calculate_exit_prices(
                    entry_price=fill_price,
                    action=bo["action"],
                    target_type=bo["target_type"],
                    target_value=bo["target_value"],
                    sl_type=bo["sl_type"],
                    sl_value=bo["sl_value"]
                )

                # Determine exit actions
                exit_action = "SELL" if bo["action"] == "BUY" else "BUY"

                update_bracket_order(bo_id, {
                    "status": "EXIT_PLACING",
                    "entry_price": fill_price,
                    "target_price": target_price,
                    "sl_price": sl_price,
                    "filled_at": datetime.now(timezone.utc)
                })
                
                bus.publish(BracketOrderFilledEvent(
                    bo_id=bo_id, symbol=bo["symbol"], entry_price=fill_price
                ))

                # Place Target
                target_payload = {
                    "apikey": bo["api_key"],
                    "strategy": bo["strategy"],
                    "symbol": bo["symbol"],
                    "exchange": bo["exchange"],
                    "action": exit_action,
                    "quantity": str(bo["quantity"]),
                    "pricetype": "LIMIT",
                    "price": str(target_price),
                    "product": bo["product"]
                }
                t_ok, t_resp, _ = place_order(target_payload, bo["api_key"])

                # Place SL
                sl_payload = copy.deepcopy(target_payload)
                sl_payload["pricetype"] = "SL-M"
                del sl_payload["price"]
                sl_payload["trigger_price"] = str(sl_price)
                
                s_ok, s_resp, _ = place_order(sl_payload, bo["api_key"])

                if t_ok and s_ok and t_resp.get("status") == "success" and s_resp.get("status") == "success":
                    update_bracket_order(bo_id, {
                        "status": "ACTIVE",
                        "target_order_id": t_resp.get("orderid"),
                        "sl_order_id": s_resp.get("orderid")
                    })
                    logger.info(f"BO {bo_id} exit legs placed successfully. Now ACTIVE.")
                else:
                    # One or both failed. Clean up.
                    logger.error(f"BO {bo_id} exit leg placement failed. Target: {t_resp}, SL: {s_resp}")
                    
                    auth_token, broker = get_auth_token_broker(bo["api_key"])
                    
                    # Cancel whichever succeeded
                    if t_ok and t_resp.get("orderid"):
                        sd = {"orderid": t_resp.get("orderid"), "strategy": bo["strategy"], "apikey": bo["api_key"]}
                        cancel_order_with_auth(t_resp.get("orderid"), auth_token, broker, sd)
                    if s_ok and s_resp.get("orderid"):
                        sd = {"orderid": s_resp.get("orderid"), "strategy": bo["strategy"], "apikey": bo["api_key"]}
                        cancel_order_with_auth(s_resp.get("orderid"), auth_token, broker, sd)
                        
                    update_bracket_order(bo_id, {
                        "status": "FAILED",
                        "error_message": "Failed to place exit legs"
                    })

            elif order_status in ["rejected", "cancelled"]:
                logger.info(f"BO {bo_id} entry order was {order_status}")
                update_bracket_order(bo_id, {
                    "status": "FAILED" if order_status == "rejected" else "CANCELLED",
                    "error_message": data.get("text", f"Entry {order_status}")
                })

            else:
                # Still open/pending
                # Check timeout
                created_at = datetime.fromisoformat(bo["created_at"]) if bo.get("created_at") else None
                if _get_time_elapsed(created_at) > ENTRY_TIMEOUT:
                    logger.warning(f"BO {bo_id} entry timed out. Cancelling.")
                    auth_token, broker = get_auth_token_broker(bo["api_key"])
                    sd = copy.deepcopy(status_data)
                    sd["apikey"] = bo["api_key"]
                    cancel_order_with_auth(entry_order_id, auth_token, broker, sd)
                    update_bracket_order(bo_id, {"status": "CANCELLED"})

    except Exception as e:
        logger.error(f"Error in _process_pending_entries: {e}")


def _process_active_orders():
    """Phase B: Monitor OCO legs"""
    try:
        bos = get_orders_by_status(["ACTIVE"])
        for bo in bos:
            bo_id = bo["bo_id"]
            
            t_id = bo["target_order_id"]
            s_id = bo["sl_order_id"]
            
            if not t_id or not s_id:
                continue

            auth_token, broker = get_auth_token_broker(bo["api_key"])
            if not auth_token:
                continue

            # Check target
            t_data = {"orderid": t_id, "strategy": bo["strategy"]}
            t_ok, t_resp, _ = get_order_status(t_data, api_key=bo["api_key"])
            t_status = t_resp.get("data", {}).get("order_status", "").lower() if t_ok else ""

            # Check SL
            s_data = {"orderid": s_id, "strategy": bo["strategy"]}
            s_ok, s_resp, _ = get_order_status(s_data, api_key=bo["api_key"])
            s_status = s_resp.get("data", {}).get("order_status", "").lower() if s_ok else ""

            if t_status == "complete":
                # Target hit! Cancel SL.
                sd = copy.deepcopy(s_data)
                sd["apikey"] = bo["api_key"]
                cancel_order_with_auth(s_id, auth_token, broker, sd)
                
                fill_price = float(t_resp.get("data", {}).get("price", bo["target_price"]))
                if fill_price <= 0:
                    fill_price = float(t_resp.get("data", {}).get("average_price", bo["target_price"]))
                
                update_bracket_order(bo_id, {
                    "status": "COMPLETED",
                    "exit_type": "TARGET",
                    "exit_price": fill_price,
                    "completed_at": datetime.now(timezone.utc)
                })
                bus.publish(BracketOrderCompletedEvent(bo_id=bo_id, exit_type="TARGET", exit_price=fill_price))
                logger.info(f"BO {bo_id} TARGET HIT at {fill_price}")

            elif s_status == "complete":
                # SL hit! Cancel target.
                sd = copy.deepcopy(t_data)
                sd["apikey"] = bo["api_key"]
                cancel_order_with_auth(t_id, auth_token, broker, sd)
                
                fill_price = float(s_resp.get("data", {}).get("price", bo["sl_price"]))
                if fill_price <= 0:
                    fill_price = float(s_resp.get("data", {}).get("average_price", bo["sl_price"]))
                    
                update_bracket_order(bo_id, {
                    "status": "COMPLETED",
                    "exit_type": "STOPLOSS",
                    "exit_price": fill_price,
                    "completed_at": datetime.now(timezone.utc)
                })
                bus.publish(BracketOrderCompletedEvent(bo_id=bo_id, exit_type="STOPLOSS", exit_price=fill_price))
                logger.info(f"BO {bo_id} STOPLOSS HIT at {fill_price}")
                
            elif t_status in ["rejected", "cancelled"] and s_status in ["rejected", "cancelled"]:
                update_bracket_order(bo_id, {"status": "FAILED", "error_message": "Both exit legs failed"})

    except Exception as e:
        logger.error(f"Error in _process_active_orders: {e}")


def _poll_loop():
    logger.info(f"Bracket Order Manager started (interval={POLL_INTERVAL}s, timeout={ENTRY_TIMEOUT}s)")
    while _running:
        try:
            _process_pending_entries()
            _process_active_orders()
        except Exception as e:
            logger.error(f"Error in BO polling loop: {e}")
        
        time.sleep(POLL_INTERVAL)


def start_bo_manager():
    """Start the background daemon thread for bracket orders"""
    global _running, _thread
    
    if _running:
        logger.warning("Bracket Order Manager is already running")
        return
        
    _running = True
    _thread = threading.Thread(target=_poll_loop, name="BracketOrderManagerThread", daemon=True)
    _thread.start()


def stop_bo_manager():
    """Stop the background daemon thread"""
    global _running
    _running = False
    if _thread:
        _thread.join(timeout=2.0)
