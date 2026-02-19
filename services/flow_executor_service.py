# services/flow_executor_service.py
"""
Flow Workflow Executor Service
Executes workflow nodes using internal OpenAlgo services (synchronous Flask version)
"""

import json
import logging
import re
import threading
import time as time_module
from datetime import datetime, time
from typing import Any, Dict, List, Optional, Tuple

from database.flow_db import (
    add_execution_log,
    create_execution,
    get_execution,
    get_workflow,
    update_execution_status,
)
from services.flow_openalgo_client import FlowOpenAlgoClient, get_flow_client

logger = logging.getLogger(__name__)

# Execution limits
MAX_NODE_DEPTH = 100
MAX_NODE_VISITS = 500

# Execution locks to prevent concurrent execution
_workflow_locks: dict[int, threading.Lock] = {}
_locks_mutex = threading.Lock()


def get_workflow_lock(workflow_id: int) -> threading.Lock:
    """Get or create a lock for a workflow"""
    with _locks_mutex:
        if workflow_id not in _workflow_locks:
            _workflow_locks[workflow_id] = threading.Lock()
        return _workflow_locks[workflow_id]


def parse_time_string(
    time_str: str, default_hour: int = 9, default_minute: int = 15
) -> tuple[int, int, int]:
    """Parse a time string in HH:MM or HH:MM:SS format"""
    if not time_str or not isinstance(time_str, str):
        return (default_hour, default_minute, 0)

    try:
        parts = time_str.strip().split(":")
        if not parts:
            return (default_hour, default_minute, 0)

        hour = int(parts[0]) if parts[0].isdigit() else default_hour
        minute = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else default_minute
        second = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0

        hour = max(0, min(23, hour))
        minute = max(0, min(59, minute))
        second = max(0, min(59, second))

        return (hour, minute, second)
    except (ValueError, AttributeError, IndexError):
        return (default_hour, default_minute, 0)


class WorkflowContext:
    """Context for storing variables during workflow execution"""

    def __init__(self):
        self.variables: dict[str, Any] = {}
        self.condition_results: dict[str, bool] = {}

    def set_variable(self, name: str, value: Any):
        """Store a variable"""
        self.variables[name] = value

    def get_variable(self, name: str, default: Any = None) -> Any:
        """Get a variable value"""
        return self.variables.get(name, default)

    def set_condition_result(self, node_id: str, result: bool):
        """Store a condition result for a node"""
        self.condition_results[node_id] = result

    def get_condition_result(self, node_id: str) -> bool | None:
        """Get the condition result for a node"""
        return self.condition_results.get(node_id)

    def _get_builtin_variable(self, name: str) -> str | None:
        """Get built-in system variables"""
        now = datetime.now()
        builtins = {
            "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
            "date": now.strftime("%Y-%m-%d"),
            "time": now.strftime("%H:%M:%S"),
            "year": now.strftime("%Y"),
            "month": now.strftime("%m"),
            "day": now.strftime("%d"),
            "hour": now.strftime("%H"),
            "minute": now.strftime("%M"),
            "second": now.strftime("%S"),
            "weekday": now.strftime("%A"),
            "iso_timestamp": now.isoformat(),
        }
        return builtins.get(name)

    def interpolate(self, text: str) -> str:
        """Replace {{variable}} patterns with actual values"""
        if not isinstance(text, str):
            return text

        def replacer(match):
            var_path = match.group(1).strip()

            # Check built-in variables first
            builtin_value = self._get_builtin_variable(var_path)
            if builtin_value is not None:
                return builtin_value

            # Then check user variables
            parts = var_path.split(".")
            value = self.variables

            for part in parts:
                if isinstance(value, dict):
                    value = value.get(part)
                else:
                    return match.group(0)

                if value is None:
                    return match.group(0)

            return str(value) if value is not None else match.group(0)

        return re.sub(r"\{\{([^}]+)\}\}", replacer, text)


class NodeExecutor:
    """Executes individual workflow nodes"""

    def __init__(self, client: FlowOpenAlgoClient, context: WorkflowContext, logs: list):
        self.client = client
        self.context = context
        self.logs = logs

    def log(self, message: str, level: str = "info"):
        """Add log entry"""
        self.logs.append(
            {"time": datetime.now().isoformat(), "message": message, "level": level}
        )
        if level == "error":
            logger.error(message)
        else:
            logger.info(message)

    def store_output(self, node_data: dict, result: Any):
        """Store result in output variable if configured"""
        output_var = node_data.get("outputVariable")
        if output_var and output_var.strip():
            self.context.set_variable(output_var.strip(), result)
            self.log(f"Stored result in variable: {output_var}")

    def get_str(self, node_data: dict, key: str, default: str = "") -> str:
        """Get interpolated string value from node data"""
        value = node_data.get(key, default)
        return self.context.interpolate(str(value)) if value else default

    def get_int(self, node_data: dict, key: str, default: int = 0) -> int:
        """Get interpolated integer value from node data"""
        value = node_data.get(key, default)
        if isinstance(value, str):
            interpolated = self.context.interpolate(value)
            try:
                return int(float(interpolated))
            except (ValueError, TypeError):
                return default
        return int(value) if value else default

    def get_float(self, node_data: dict, key: str, default: float = 0.0) -> float:
        """Get interpolated float value from node data"""
        value = node_data.get(key, default)
        if isinstance(value, str):
            interpolated = self.context.interpolate(value)
            try:
                return float(interpolated)
            except (ValueError, TypeError):
                return default
        return float(value) if value else default

    # === Order Nodes ===

    def execute_place_order(self, node_data: dict) -> dict:
        """Execute Place Order node"""
        symbol = self.get_str(node_data, "symbol", "")
        exchange = self.get_str(node_data, "exchange", "NSE")
        action = self.get_str(node_data, "action", "BUY")
        quantity = self.get_int(node_data, "quantity", 1)
        price_type = self.get_str(node_data, "priceType", "MARKET")
        product = self.get_str(node_data, "product", "MIS")
        price = self.get_float(node_data, "price", 0)
        trigger_price = self.get_float(node_data, "triggerPrice", 0)

        self.log(f"Placing order: {symbol} {action} qty={quantity}")
        result = self.client.place_order(
            symbol=symbol,
            exchange=exchange,
            action=action,
            quantity=quantity,
            price_type=price_type,
            product_type=product,
            price=price,
            trigger_price=trigger_price,
        )
        self.log(
            f"Order result: {result}", "info" if result.get("status") == "success" else "error"
        )
        self.store_output(node_data, result)
        return result

    def execute_smart_order(self, node_data: dict) -> dict:
        """Execute Smart Order node"""
        symbol = self.get_str(node_data, "symbol", "")
        exchange = self.get_str(node_data, "exchange", "NSE")
        action = self.get_str(node_data, "action", "BUY")
        quantity = self.get_int(node_data, "quantity", 1)
        position_size = self.get_int(node_data, "positionSize", 0)
        price_type = self.get_str(node_data, "priceType", "MARKET")
        product = self.get_str(node_data, "product", "MIS")

        self.log(f"Placing smart order: {symbol} {action}")
        result = self.client.place_smart_order(
            symbol=symbol,
            exchange=exchange,
            action=action,
            quantity=quantity,
            position_size=position_size,
            price_type=price_type,
            product_type=product,
        )
        self.log(
            f"Smart order result: {result}",
            "info" if result.get("status") == "success" else "error",
        )
        self.store_output(node_data, result)
        return result

    def execute_options_order(self, node_data: dict) -> dict:
        """Execute Options Order node"""
        underlying = self.get_str(node_data, "underlying", "NIFTY")
        expiry_type = self.get_str(node_data, "expiryType", "current_week")
        quantity = self.get_int(node_data, "quantity", 1)
        offset = self.get_str(node_data, "offset", "ATM")
        option_type = self.get_str(node_data, "optionType", "CE")
        action = self.get_str(node_data, "action", "BUY")
        price_type = self.get_str(node_data, "priceType", "MARKET")
        product = self.get_str(node_data, "product", "NRML")
        split_size = self.get_int(node_data, "splitSize", 0)

        self.log(f"Placing options order: {underlying} {option_type} {offset}")

        # Get the underlying exchange for index
        if underlying in ["SENSEX", "BANKEX", "SENSEX50"]:
            underlying_exchange = "BSE_INDEX"
            fo_exchange = "BFO"
        else:
            underlying_exchange = "NSE_INDEX"
            fo_exchange = "NFO"

        # Get lot size (updated Jan 2026)
        lot_sizes = {
            "NIFTY": 65,
            "BANKNIFTY": 30,
            "FINNIFTY": 65,
            "MIDCPNIFTY": 120,
            "NIFTYNXT50": 25,
            "SENSEX": 20,
            "BANKEX": 30,
            "SENSEX50": 25,
        }
        lot_size = lot_sizes.get(underlying, 75)
        total_quantity = quantity * lot_size

        # Resolve expiry date from expiry type
        expiry_date = self._resolve_expiry_date(underlying, fo_exchange, expiry_type)
        if not expiry_date:
            error_result = {
                "status": "error",
                "message": f"Could not resolve expiry for {expiry_type}",
            }
            self.log(f"Options order failed: {error_result['message']}", "error")
            return error_result

        self.log(f"Resolved expiry: {expiry_type} -> {expiry_date}")

        result = self.client.options_order(
            underlying=underlying,
            exchange=underlying_exchange,
            action=action,
            quantity=total_quantity,
            expiry_date=expiry_date,
            offset=offset,
            option_type=option_type,
            price_type=price_type,
            product=product,
            splitsize=split_size,
        )
        self.log(
            f"Options order result: {result}",
            "info" if result.get("status") == "success" else "error",
        )
        self.store_output(node_data, result)
        return result

    def execute_options_multi_order(self, node_data: dict) -> dict:
        """Execute Options Multi-Order node (multi-leg strategy)"""
        # Debug: log node_data keys to understand structure
        self.log(f"Options multi-order node_data keys: {list(node_data.keys())}")

        underlying = self.get_str(node_data, "underlying", "NIFTY")
        expiry_type = self.get_str(node_data, "expiryType", "current_week")
        # Frontend uses "strategy" field, not "strategyType"
        strategy_type = self.get_str(node_data, "strategy", "") or self.get_str(
            node_data, "strategyType", "custom"
        )
        action = self.get_str(node_data, "action", "SELL")  # BUY or SELL for the strategy direction
        quantity_lots = self.get_int(node_data, "quantity", 1)  # Number of lots per leg
        product = self.get_str(node_data, "product", "MIS")
        strangle_width = self.get_str(node_data, "strangleWidth", "OTM2")  # For strangle strategy

        # Check for custom legs data
        legs_data = node_data.get("legs", []) or node_data.get("orderLegs", [])

        self.log(
            f"Strategy: {strategy_type}, Action: {action}, Quantity: {quantity_lots} lots, Product: {product}"
        )

        # Get the underlying exchange for index
        if underlying in ["SENSEX", "BANKEX", "SENSEX50"]:
            underlying_exchange = "BSE_INDEX"
            fo_exchange = "BFO"
        else:
            underlying_exchange = "NSE_INDEX"
            fo_exchange = "NFO"

        # Get lot size for quantity calculation
        lot_sizes = {
            "NIFTY": 65,
            "BANKNIFTY": 30,
            "FINNIFTY": 65,
            "MIDCPNIFTY": 120,
            "NIFTYNXT50": 25,
            "SENSEX": 20,
            "BANKEX": 30,
            "SENSEX50": 25,
        }
        lot_size = lot_sizes.get(underlying, 65)
        total_quantity = quantity_lots * lot_size

        # Resolve expiry date
        expiry_date = self._resolve_expiry_date(underlying, fo_exchange, expiry_type)
        if not expiry_date:
            error_result = {
                "status": "error",
                "message": f"Could not resolve expiry for {expiry_type}",
            }
            self.log(f"Options multi-order failed: {error_result['message']}", "error")
            return error_result

        self.log(f"Resolved expiry: {expiry_type} -> {expiry_date}")

        # Generate legs based on strategy type if no custom legs provided
        legs = []
        if legs_data:
            # Use custom legs from node data
            for leg in legs_data:
                leg_qty = self.get_int(leg, "quantity", 1)
                leg_entry = {
                    "offset": self.get_str(leg, "offset", "ATM"),
                    "option_type": self.get_str(leg, "optionType", "CE"),
                    "action": self.get_str(leg, "action", "BUY"),
                    "quantity": leg_qty * lot_size,
                    "pricetype": self.get_str(leg, "priceType", "MARKET"),
                    "product": self.get_str(leg, "product", product),
                    "price": self.get_float(leg, "price", 0),
                    "splitsize": self.get_int(leg, "splitSize", 0),
                }
                legs.append(leg_entry)
        else:
            # Generate legs from predefined strategy type
            legs = self._generate_strategy_legs(
                strategy_type, action, total_quantity, product, strangle_width
            )

        if not legs:
            error_result = {
                "status": "error",
                "message": f"No legs generated for strategy: {strategy_type}",
            }
            self.log(f"Options multi-order failed: {error_result['message']}", "error")
            return error_result

        self.log(f"Placing options multi-order: {underlying} {strategy_type} with {len(legs)} legs")
        for i, leg in enumerate(legs):
            self.log(
                f"  Leg {i + 1}: {leg['offset']} {leg['option_type']} {leg['action']} qty={leg['quantity']}"
            )

        result = self.client.options_multi_order(
            underlying=underlying,
            exchange=underlying_exchange,
            expiry_date=expiry_date,
            legs=legs,
        )
        self.log(
            f"Options multi-order result: {result}",
            "info" if result.get("status") == "success" else "error",
        )
        self.store_output(node_data, result)
        return result

    def _generate_strategy_legs(
        self,
        strategy_type: str,
        action: str,
        quantity: int,
        product: str,
        strangle_width: str = "OTM2",
    ) -> list[dict]:
        """Generate legs for predefined option strategies"""
        legs = []

        # Common leg template
        def make_leg(offset: str, option_type: str, leg_action: str) -> dict:
            return {
                "offset": offset,
                "option_type": option_type,
                "action": leg_action,
                "quantity": quantity,
                "pricetype": "MARKET",
                "product": product,
                "price": 0,
                "splitsize": 0,
            }

        if strategy_type == "straddle":
            # Straddle: ATM CE + ATM PE (same action for both)
            legs.append(make_leg("ATM", "CE", action))
            legs.append(make_leg("ATM", "PE", action))

        elif strategy_type == "strangle":
            # Strangle: OTM CE + OTM PE (same action for both)
            # Use configurable width, default OTM2
            legs.append(make_leg(strangle_width, "CE", action))
            legs.append(make_leg(strangle_width, "PE", action))

        elif strategy_type == "iron_condor":
            # Iron Condor: 4 legs - sell near strikes, buy far strikes
            # Sell OTM2 CE, Buy OTM4 CE, Sell OTM2 PE, Buy OTM4 PE
            legs.append(make_leg("OTM2", "CE", "SELL"))
            legs.append(make_leg("OTM4", "CE", "BUY"))
            legs.append(make_leg("OTM2", "PE", "SELL"))
            legs.append(make_leg("OTM4", "PE", "BUY"))

        elif strategy_type == "bull_call_spread":
            # Bull Call Spread: Buy lower strike CE, Sell higher strike CE
            legs.append(make_leg("ATM", "CE", "BUY"))
            legs.append(make_leg("OTM2", "CE", "SELL"))

        elif strategy_type == "bear_put_spread":
            # Bear Put Spread: Buy higher strike PE, Sell lower strike PE
            legs.append(make_leg("ATM", "PE", "BUY"))
            legs.append(make_leg("OTM2", "PE", "SELL"))

        elif strategy_type == "custom":
            # Custom strategy requires legs to be provided
            self.log("Custom strategy selected but no legs provided", "warning")

        else:
            self.log(f"Unknown strategy type: {strategy_type}", "warning")

        return legs

    def _resolve_expiry_date(self, symbol: str, exchange: str, expiry_type: str) -> str | None:
        """Resolve expiry type to actual expiry date"""
        try:
            response = self.client.get_expiry(
                symbol=symbol, exchange=exchange, instrumenttype="options"
            )
            if response.get("status") != "success":
                self.log(f"Failed to fetch expiry: {response}", "error")
                return None

            expiry_list = response.get("data", [])
            if not expiry_list:
                self.log(f"No expiry dates found for {symbol} on {exchange}", "error")
                return None

            # Parse and sort expiry dates
            def parse_expiry(exp_str: str) -> datetime | None:
                """Parse expiry date string"""
                if not exp_str or not isinstance(exp_str, str):
                    return None
                for fmt in ["%d-%b-%y", "%d%b%y", "%d-%B-%Y", "%d%B%Y"]:
                    try:
                        return datetime.strptime(exp_str.upper(), fmt)
                    except ValueError:
                        continue
                return None

            # Filter and sort expiries
            valid_expiries = []
            for exp_str in expiry_list:
                parsed = parse_expiry(exp_str)
                if parsed is not None:
                    valid_expiries.append((exp_str, parsed))

            if not valid_expiries:
                self.log(f"No valid expiry dates found for {symbol}", "error")
                return None

            # Sort by parsed date
            valid_expiries.sort(key=lambda x: x[1])
            sorted_expiries = [exp[0] for exp in valid_expiries]
            now = datetime.now()
            current_month = now.month
            current_year = now.year

            # Calculate next month
            if current_month == 12:
                next_month, next_year = 1, current_year + 1
            else:
                next_month, next_year = current_month + 1, current_year

            if expiry_type == "current_week":
                if sorted_expiries:
                    return self._format_expiry_for_api(sorted_expiries[0])
                return None
            elif expiry_type == "next_week":
                if len(sorted_expiries) > 1:
                    return self._format_expiry_for_api(sorted_expiries[1])
                return None
            elif expiry_type == "current_month":
                result = None
                for exp_str, exp_date in valid_expiries:
                    if exp_date.month == current_month and exp_date.year == current_year:
                        result = exp_str
                if result:
                    return self._format_expiry_for_api(result)
                return None
            elif expiry_type == "next_month":
                result = None
                for exp_str, exp_date in valid_expiries:
                    if exp_date.month == next_month and exp_date.year == next_year:
                        result = exp_str
                if result:
                    return self._format_expiry_for_api(result)
                return None

            self.log(f"Unknown expiry type: {expiry_type}", "error")
            return None
        except Exception as e:
            self.log(f"Error resolving expiry: {e}", "error")
            return None

    def _format_expiry_for_api(self, expiry_str: str) -> str:
        """Format expiry date for API (e.g., '10-JUL-25' -> '10JUL25')"""
        if not expiry_str:
            return ""
        return expiry_str.replace("-", "").upper()

    def execute_modify_order(self, node_data: dict) -> dict:
        """Execute Modify Order node"""
        order_id = self.get_str(node_data, "orderId", "")
        symbol = self.get_str(node_data, "symbol", "")
        exchange = self.get_str(node_data, "exchange", "NSE")
        action = self.get_str(node_data, "action", "BUY")
        # Support both newQuantity (frontend) and quantity (legacy) field names
        quantity = self.get_int(node_data, "newQuantity", 0) or self.get_int(
            node_data, "quantity", 1
        )
        price_type = self.get_str(node_data, "priceType", "LIMIT")
        product = self.get_str(node_data, "product", "MIS")
        # Support both newPrice (frontend) and price (legacy) field names
        price = self.get_float(node_data, "newPrice", 0) or self.get_float(node_data, "price", 0)
        # Support both newTriggerPrice (frontend) and triggerPrice (legacy) field names
        trigger_price = self.get_float(node_data, "newTriggerPrice", 0) or self.get_float(
            node_data, "triggerPrice", 0
        )

        self.log(
            f"Modifying order: {order_id} - {symbol} {action} qty={quantity} price={price} trigger={trigger_price}"
        )
        result = self.client.modify_order(
            order_id=order_id,
            symbol=symbol,
            exchange=exchange,
            action=action,
            quantity=quantity,
            price_type=price_type,
            product_type=product,
            price=price,
            trigger_price=trigger_price,
        )
        self.log(
            f"Modify order result: {result}",
            "info" if result.get("status") == "success" else "error",
        )
        self.store_output(node_data, result)
        return result

    def execute_cancel_order(self, node_data: dict) -> dict:
        """Execute Cancel Order node"""
        order_id = self.context.interpolate(str(node_data.get("orderId", "")))
        self.log(f"Cancelling order: {order_id}")
        result = self.client.cancel_order(order_id=order_id)
        self.log(
            f"Cancel result: {result}", "info" if result.get("status") == "success" else "error"
        )
        return result

    def execute_cancel_all_orders(self, node_data: dict) -> dict:
        """Execute Cancel All Orders node"""
        self.log("Cancelling all orders")
        result = self.client.cancel_all_orders()
        self.log(
            f"Cancel all result: {result}", "info" if result.get("status") == "success" else "error"
        )
        return result

    def execute_close_positions(self, node_data: dict) -> dict:
        """Execute Close All Positions node - squares off all open positions"""
        self.log("Closing all positions")
        result = self.client.close_all_positions()
        self.log(
            f"Close all positions result: {result}",
            "info" if result.get("status") == "success" else "error",
        )
        return result

    def execute_basket_order(self, node_data: dict) -> dict:
        """Execute Basket Order node - places multiple orders in batch"""
        orders_raw = node_data.get("orders", "")
        product = self.get_str(node_data, "product", "MIS")
        price_type = self.get_str(node_data, "priceType", "MARKET")
        basket_name = self.get_str(node_data, "basketName", "flow_basket")

        orders = []
        if isinstance(orders_raw, str):
            # Parse orders from CSV-like format: SYMBOL,EXCHANGE,ACTION,QTY per line
            for line in orders_raw.strip().split("\n"):
                line = line.strip()
                if not line:
                    continue
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 4:
                    try:
                        order = {
                            "symbol": self.context.interpolate(parts[0]),
                            "exchange": self.context.interpolate(parts[1]),
                            "action": self.context.interpolate(parts[2]).upper(),
                            "quantity": int(self.context.interpolate(parts[3])),
                            "pricetype": price_type,
                            "product": product,
                        }
                        orders.append(order)
                    except (ValueError, IndexError) as e:
                        self.log(f"Skipping invalid order line '{line}': {e}", "warning")
                else:
                    self.log(
                        f"Skipping invalid order line '{line}': expected SYMBOL,EXCHANGE,ACTION,QTY",
                        "warning",
                    )
        elif isinstance(orders_raw, list):
            # Already a list of order dicts
            orders = orders_raw

        if not orders:
            error_result = {"status": "error", "message": "No valid orders to place"}
            self.log("Basket order failed: No valid orders", "error")
            return error_result

        self.log(f"Placing basket order '{basket_name}' with {len(orders)} orders")
        for i, order in enumerate(orders):
            self.log(
                f"  Order {i + 1}: {order['symbol']} {order['exchange']} {order['action']} qty={order['quantity']}"
            )

        result = self.client.basket_order(orders=orders, strategy=basket_name)
        self.log(
            f"Basket order result: {result}",
            "info" if result.get("status") == "success" else "error",
        )
        self.store_output(node_data, result)
        return result

    def execute_split_order(self, node_data: dict) -> dict:
        """Execute Split Order node"""
        symbol = self.get_str(node_data, "symbol", "")
        exchange = self.get_str(node_data, "exchange", "NSE")
        action = self.get_str(node_data, "action", "BUY")
        quantity = self.get_int(node_data, "quantity", 1)
        split_size = self.get_int(node_data, "splitSize", 10)
        price_type = self.get_str(node_data, "priceType", "MARKET")
        product = self.get_str(node_data, "product", "MIS")

        self.log(f"Placing split order: {symbol} qty={quantity} split={split_size}")
        result = self.client.split_order(
            symbol=symbol,
            exchange=exchange,
            action=action,
            quantity=quantity,
            split_size=split_size,
            price_type=price_type,
            product_type=product,
        )
        self.log(
            f"Split order result: {result}",
            "info" if result.get("status") == "success" else "error",
        )
        self.store_output(node_data, result)
        return result

    # === Data Nodes ===

    def execute_get_quote(self, node_data: dict) -> dict:
        """Execute Get Quote node"""
        symbol = self.get_str(node_data, "symbol", "")
        exchange = self.get_str(node_data, "exchange", "NSE")
        self.log(f"Getting quote for: {symbol}")
        result = self.client.get_quotes(symbol=symbol, exchange=exchange)
        self.log(f"Quote result: {result}")
        self.store_output(node_data, result)
        return result

    def execute_get_depth(self, node_data: dict) -> dict:
        """Execute Get Depth node"""
        symbol = self.get_str(node_data, "symbol", "")
        exchange = self.get_str(node_data, "exchange", "NSE")
        self.log(f"Getting depth for: {symbol}")
        result = self.client.get_depth(symbol=symbol, exchange=exchange)
        self.log(f"Depth result received")
        self.store_output(node_data, result)
        return result

    def execute_get_order_status(self, node_data: dict) -> dict:
        """Execute Get Order Status node"""
        order_id = self.get_str(node_data, "orderId", "")
        self.log(f"Getting order status for: {order_id}")
        result = self.client.get_order_status(order_id=order_id)
        self.log(f"Order status result: {result}")
        self.store_output(node_data, result)
        return result

    def execute_open_position(self, node_data: dict) -> dict:
        """Execute Open Position node"""
        symbol = self.get_str(node_data, "symbol", "")
        exchange = self.get_str(node_data, "exchange", "NSE")
        product = self.get_str(node_data, "product", "MIS")
        self.log(f"Getting open position for: {symbol}")
        result = self.client.get_open_position(
            symbol=symbol, exchange=exchange, product_type=product
        )
        self.log(f"Open position result: {result}")
        self.store_output(node_data, result)
        return result

    def execute_history(self, node_data: dict) -> dict:
        """Execute History node"""
        symbol = self.get_str(node_data, "symbol", "")
        exchange = self.get_str(node_data, "exchange", "NSE")
        interval = self.get_str(node_data, "interval", "5m")
        start_date = self.get_str(node_data, "startDate", "")
        end_date = self.get_str(node_data, "endDate", "")
        self.log(f"Getting history for: {symbol} ({interval})")
        result = self.client.get_history(
            symbol=symbol,
            exchange=exchange,
            interval=interval,
            start_date=start_date,
            end_date=end_date,
        )
        self.log(f"History data received")
        self.store_output(node_data, result)
        return result

    def execute_order_book(self, node_data: dict) -> dict:
        """Execute OrderBook node"""
        self.log("Fetching order book")
        result = self.client.orderbook()
        self.log(f"Order book received")
        self.store_output(node_data, result)
        return result

    def execute_trade_book(self, node_data: dict) -> dict:
        """Execute TradeBook node"""
        self.log("Fetching trade book")
        result = self.client.tradebook()
        self.log(f"Trade book received")
        self.store_output(node_data, result)
        return result

    def execute_position_book(self, node_data: dict) -> dict:
        """Execute PositionBook node"""
        self.log("Fetching position book")
        result = self.client.positionbook()
        self.log(f"Position book received")
        self.store_output(node_data, result)
        return result

    def execute_holdings(self, node_data: dict) -> dict:
        """Execute Holdings node"""
        self.log("Fetching holdings")
        result = self.client.holdings()
        self.log(f"Holdings received")
        self.store_output(node_data, result)
        return result

    def execute_funds(self, node_data: dict) -> dict:
        """Execute Funds node"""
        self.log("Fetching funds")
        result = self.client.funds()
        self.log(f"Funds received")
        self.store_output(node_data, result)
        return result

    # === Additional Data Nodes ===

    def execute_symbol(self, node_data: dict) -> dict:
        """Execute Symbol node - get symbol info (lotsize, tick_size, etc.)"""
        symbol = self.get_str(node_data, "symbol", "")
        exchange = self.get_str(node_data, "exchange", "NSE")
        self.log(f"Getting symbol info for: {symbol} ({exchange})")
        result = self.client.symbol(symbol=symbol, exchange=exchange)
        self.log(f"Symbol result: {result}")
        self.store_output(node_data, result)
        return result

    def execute_option_symbol(self, node_data: dict) -> dict:
        """Execute OptionSymbol node - resolve option symbol from underlying"""
        underlying = self.get_str(node_data, "underlying", "NIFTY")
        exchange = self.get_str(node_data, "exchange", "NSE_INDEX")
        expiry_date = self.get_str(node_data, "expiryDate", "")
        offset = self.get_str(node_data, "offset", "ATM")
        option_type = self.get_str(node_data, "optionType", "CE")
        self.log(f"Resolving option symbol: {underlying} {option_type} {offset}")
        result = self.client.optionsymbol(
            underlying=underlying,
            exchange=exchange,
            expiry_date=expiry_date,
            offset=offset,
            option_type=option_type,
        )
        self.log(f"Option symbol result: {result}")
        self.store_output(node_data, result)
        return result

    def execute_expiry(self, node_data: dict) -> dict:
        """Execute Expiry node - get expiry dates for F&O"""
        symbol = self.get_str(node_data, "symbol", "NIFTY")
        exchange = self.get_str(node_data, "exchange", "NFO")
        self.log(f"Getting expiry dates for: {symbol}")
        result = self.client.get_expiry(symbol=symbol, exchange=exchange)
        self.log(f"Expiry result: {result}")
        self.store_output(node_data, result)
        return result

    def execute_intervals(self, node_data: dict) -> dict:
        """Execute Intervals node - get available intervals for historical data"""
        self.log("Getting available intervals")
        result = self.client.get_intervals()
        self.log(f"Intervals result: {result}")
        self.store_output(node_data, result)
        return result

    def execute_multi_quotes(self, node_data: dict) -> dict:
        """Execute Multi Quotes node - get quotes for multiple symbols"""
        raw_symbols = node_data.get("symbols", "")
        exchange = self.get_str(node_data, "exchange", "NSE")
        # Convert comma-separated string to list of dicts expected by service
        if isinstance(raw_symbols, str):
            symbol_list = [s.strip() for s in raw_symbols.split(",") if s.strip()]
        else:
            symbol_list = raw_symbols
        symbols = [{"symbol": s, "exchange": exchange} for s in symbol_list]
        self.log(f"Getting quotes for {len(symbols)} symbols")
        result = self.client.get_multi_quotes(symbols=symbols)
        self.log(f"Multi quotes result: {result}")
        self.store_output(node_data, result)
        return result

    def execute_option_chain(self, node_data: dict) -> dict:
        """Execute OptionChain node - get option chain data"""
        underlying = self.get_str(node_data, "underlying", "NIFTY")
        exchange = self.get_str(node_data, "exchange", "NSE_INDEX")
        expiry_date = self.get_str(node_data, "expiryDate", "")
        strike_count = self.get_int(node_data, "strikeCount", 10)
        self.log(f"Fetching option chain for: {underlying} expiry={expiry_date}")
        result = self.client.optionchain(
            underlying=underlying,
            exchange=exchange,
            expiry_date=expiry_date,
            strike_count=strike_count,
        )
        self.log(f"Option chain result received")
        self.store_output(node_data, result)
        return result

    def execute_synthetic_future(self, node_data: dict) -> dict:
        """Execute SyntheticFuture node - calculate synthetic future price"""
        underlying = self.get_str(node_data, "underlying", "NIFTY")
        exchange = self.get_str(node_data, "exchange", "NSE_INDEX")
        expiry_date = self.get_str(node_data, "expiryDate", "")
        self.log(f"Calculating synthetic future for: {underlying}")
        result = self.client.syntheticfuture(
            underlying=underlying,
            exchange=exchange,
            expiry_date=expiry_date,
        )
        self.log(f"Synthetic future result: {result}")
        self.store_output(node_data, result)
        return result

    def execute_holidays(self, node_data: dict) -> dict:
        """Execute Holidays node - get market holidays"""
        exchange = self.get_str(node_data, "exchange", "NSE")
        self.log(f"Fetching holidays for exchange: {exchange}")
        result = self.client.holidays(exchange=exchange)
        self.log(f"Holidays result received")
        self.store_output(node_data, result)
        return result

    def execute_timings(self, node_data: dict) -> dict:
        """Execute Timings node - get market timings"""
        exchange = self.get_str(node_data, "exchange", "NSE")
        self.log(f"Fetching market timings for exchange: {exchange}")
        result = self.client.timings(exchange=exchange)
        self.log(f"Timings result: {result}")
        self.store_output(node_data, result)
        return result

    def execute_margin(self, node_data: dict) -> dict:
        """Execute Margin node - calculate margin requirements"""
        symbol = self.get_str(node_data, "symbol", "")
        exchange = self.get_str(node_data, "exchange", "NSE")
        quantity = self.get_int(node_data, "quantity", 1)
        price = self.get_float(node_data, "price", 0)
        product_type = self.get_str(node_data, "product", "MIS")
        action = self.get_str(node_data, "action", "BUY")
        price_type = self.get_str(node_data, "priceType", "MARKET")
        self.log(f"Calculating margin for: {symbol} ({exchange})")
        result = self.client.margin(
            symbol=symbol,
            exchange=exchange,
            quantity=quantity,
            price=price,
            product_type=product_type,
            action=action,
            price_type=price_type,
        )
        self.log(f"Margin result: {result}")
        self.store_output(node_data, result)
        return result

    def execute_math_expression(self, node_data: dict) -> dict:
        """Execute Math Expression node - evaluate mathematical expressions

        Supports:
        - Basic operators: +, -, *, /, %, ** (power)
        - Parentheses for grouping
        - Variable interpolation: {{variableName}}
        - Numbers (integers and decimals)

        Example: ({{ltp}} * {{lotSize}}) + {{brokerage}}
        """
        expression = node_data.get("expression", "")
        output_var = node_data.get("outputVariable", "result")

        if not expression:
            self.log("No expression provided", "error")
            return {"status": "error", "message": "No expression provided"}

        self.log(f"Evaluating: {expression}")

        try:
            # Step 1: Interpolate variables
            interpolated = self.context.interpolate(expression)
            self.log(f"Interpolated: {interpolated}")

            # Step 2: Safely evaluate the expression
            result = self._safe_eval_math(interpolated)

            # Step 3: Store result in output variable
            self.context.set_variable(output_var, result)
            self.log(f"Result: {output_var} = {result}")

            return {
                "status": "success",
                "expression": expression,
                "interpolated": interpolated,
                "result": result,
                "outputVariable": output_var,
            }

        except Exception as e:
            self.log(f"Math expression failed: {e}", "error")
            return {"status": "error", "message": str(e)}

    def _safe_eval_math(self, expression: str) -> float:
        """Safely evaluate a mathematical expression

        Uses Python's ast module to parse and evaluate only safe math operations.
        Prevents arbitrary code execution.
        """
        import ast
        import operator as op

        # Supported operators
        operators = {
            ast.Add: op.add,
            ast.Sub: op.sub,
            ast.Mult: op.mul,
            ast.Div: op.truediv,
            ast.Mod: op.mod,
            ast.Pow: op.pow,
            ast.USub: op.neg,
            ast.UAdd: op.pos,
        }

        def _eval(node):
            if isinstance(node, ast.Constant):
                if isinstance(node.value, (int, float)):
                    return node.value
                raise ValueError(f"Unsupported constant: {node.value}")
            elif isinstance(node, ast.BinOp):
                left = _eval(node.left)
                right = _eval(node.right)
                op_type = type(node.op)
                if op_type not in operators:
                    raise ValueError(f"Unsupported operator: {op_type.__name__}")
                if op_type is ast.Pow:
                    if abs(right) > 100:
                        raise ValueError(f"Exponent too large: {right} (max 100)")
                return operators[op_type](left, right)
            elif isinstance(node, ast.UnaryOp):
                operand = _eval(node.operand)
                op_type = type(node.op)
                if op_type not in operators:
                    raise ValueError(f"Unsupported unary operator: {op_type.__name__}")
                return operators[op_type](operand)
            elif isinstance(node, ast.Expression):
                return _eval(node.body)
            else:
                raise ValueError(f"Unsupported expression type: {type(node).__name__}")

        cleaned = expression.strip()
        if not cleaned:
            raise ValueError("Empty expression")

        try:
            tree = ast.parse(cleaned, mode="eval")
            return float(_eval(tree))
        except SyntaxError as e:
            raise ValueError(f"Invalid expression syntax: {e}")

    # === Utility Nodes ===

    def execute_delay(self, node_data: dict) -> dict:
        """Execute Delay node"""
        delay_value = node_data.get("delayValue")
        delay_unit = node_data.get("delayUnit", "seconds")

        if delay_value is not None:
            delay_value = int(delay_value)
            if delay_unit == "minutes":
                delay_seconds = delay_value * 60
            elif delay_unit == "hours":
                delay_seconds = delay_value * 3600
            else:
                delay_seconds = delay_value
        else:
            delay_ms = int(node_data.get("delayMs", 1000))
            delay_seconds = delay_ms / 1000

        self.log(f"Waiting for {delay_seconds} seconds")
        time_module.sleep(delay_seconds)
        return {"status": "success", "message": f"Waited {delay_seconds}s"}

    def execute_wait_until(self, node_data: dict) -> dict:
        """Execute Wait Until node"""
        target_time_str = node_data.get("targetTime", "09:30")
        target_hour, target_minute, target_second = parse_time_string(target_time_str, 9, 30)
        target_time = time(target_hour, target_minute, target_second)

        now = datetime.now().time()
        now_seconds = now.hour * 3600 + now.minute * 60 + now.second
        target_seconds = target_time.hour * 3600 + target_time.minute * 60 + target_time.second

        if now_seconds >= target_seconds:
            self.log(f"Target time {target_time_str} already passed")
            return {"status": "success", "waited": False}

        wait_seconds = target_seconds - now_seconds
        self.log(f"Waiting until {target_time_str} (~{wait_seconds}s)")
        time_module.sleep(wait_seconds)
        return {"status": "success", "waited": True}

    def execute_log(self, node_data: dict) -> dict:
        """Execute Log node"""
        message = self.context.interpolate(node_data.get("message", ""))
        log_level = node_data.get("level", "info")
        self.log(f"[LOG] {message}", log_level)
        return {"status": "success", "message": message}

    def execute_variable(self, node_data: dict) -> dict:
        """Execute Variable node"""
        var_name = node_data.get("variableName") or node_data.get("name", "")
        operation = node_data.get("operation", "set")
        var_value = node_data.get("value", "")

        if isinstance(var_value, str):
            var_value = self.context.interpolate(var_value)

        if operation == "set":
            if isinstance(var_value, str):
                if var_value.startswith("{") or var_value.startswith("["):
                    try:
                        var_value = json.loads(var_value)
                    except json.JSONDecodeError:
                        pass
            self.context.set_variable(var_name, var_value)
            self.log(f"Set variable {var_name} = {var_value}")
        elif operation == "add":
            current = float(self.context.get_variable(var_name, 0) or 0)
            result = current + float(var_value or 0)
            self.context.set_variable(var_name, result)
            var_value = result
        elif operation == "increment":
            current = float(self.context.get_variable(var_name, 0) or 0)
            result = current + 1
            self.context.set_variable(var_name, result)
            var_value = result
        elif operation == "decrement":
            current = float(self.context.get_variable(var_name, 0) or 0)
            result = current - 1
            self.context.set_variable(var_name, result)
            var_value = result

        return {"status": "success", "variable": var_name, "value": var_value}

    def execute_telegram_alert(self, node_data: dict) -> dict:
        """Execute Telegram Alert node"""
        message = self.context.interpolate(node_data.get("message", ""))
        self.log(f"Sending Telegram alert: {message}")
        result = self.client.telegram(message=message)
        self.log(
            f"Telegram result: {result}", "info" if result.get("status") == "success" else "error"
        )
        return result

    def execute_http_request(self, node_data: dict) -> dict:
        """Execute HTTP Request node"""
        import requests

        method = self.get_str(node_data, "method", "GET").upper()
        url = self.get_str(node_data, "url", "")
        headers_raw = node_data.get("headers", {})
        body = node_data.get("body", "")
        timeout = self.get_int(node_data, "timeout", 30)

        if not url:
            return {"status": "error", "message": "No URL specified"}

        headers = {}
        if isinstance(headers_raw, dict):
            for key, value in headers_raw.items():
                headers[key] = self.context.interpolate(str(value))

        url = self.context.interpolate(url)
        if isinstance(body, str) and body:
            body = self.context.interpolate(body)

        self.log(f"HTTP {method} {url}")

        try:
            if method == "GET":
                response = requests.get(url, headers=headers, timeout=timeout)
            elif method == "POST":
                try:
                    body_json = json.loads(body) if body else {}
                    response = requests.post(url, json=body_json, headers=headers, timeout=timeout)
                except json.JSONDecodeError:
                    response = requests.post(url, data=body, headers=headers, timeout=timeout)
            elif method == "PUT":
                try:
                    body_json = json.loads(body) if body else {}
                    response = requests.put(url, json=body_json, headers=headers, timeout=timeout)
                except json.JSONDecodeError:
                    response = requests.put(url, data=body, headers=headers, timeout=timeout)
            elif method == "DELETE":
                response = requests.delete(url, headers=headers, timeout=timeout)
            else:
                return {"status": "error", "message": f"Unsupported method: {method}"}

            try:
                response_data = response.json()
            except:
                response_data = response.text

            result = {
                "status": "success" if response.ok else "error",
                "statusCode": response.status_code,
                "data": response_data,
            }
            self.store_output(node_data, result)
            return result

        except requests.exceptions.RequestException as e:
            return {"status": "error", "message": str(e)}

    # === Condition Nodes ===

    def _evaluate_condition(self, value: float, operator: str, threshold: float) -> bool:
        """Evaluate a condition"""
        operators = {
            "gt": value > threshold,
            "gte": value >= threshold,
            "lt": value < threshold,
            "lte": value <= threshold,
            "eq": value == threshold,
            "neq": value != threshold,
        }
        return operators.get(operator, False)

    def execute_position_check(self, node_data: dict) -> dict:
        """Execute Position Check node"""
        symbol = self.get_str(node_data, "symbol", "")
        exchange = self.get_str(node_data, "exchange", "NSE")
        product = self.get_str(node_data, "product", "MIS")
        operator = self.get_str(node_data, "operator", "gt")
        threshold = self.get_int(node_data, "threshold", 0)

        self.log(f"Checking position for: {symbol}")
        result = self.client.get_open_position(
            symbol=symbol, exchange=exchange, product_type=product
        )
        quantity = int(result.get("quantity", 0))
        condition_met = self._evaluate_condition(quantity, operator, threshold)
        self.log(f"Position check: qty={quantity} {operator} {threshold} = {condition_met}")
        return {"status": "success", "condition": condition_met, "quantity": quantity}

    def execute_fund_check(self, node_data: dict) -> dict:
        """Execute Fund Check node"""
        operator = self.get_str(node_data, "operator", "gt")
        threshold = self.get_float(node_data, "threshold", 0)

        self.log("Checking funds")
        result = self.client.funds()
        data = result.get("data", {})
        available = float(data.get("availablecash", 0) if data else 0)
        condition_met = self._evaluate_condition(available, operator, threshold)
        self.log(f"Fund check: available={available} {operator} {threshold} = {condition_met}")
        return {"status": "success", "condition": condition_met, "available": available}

    def execute_price_condition(self, node_data: dict) -> dict:
        """Execute Price Condition node"""
        symbol = self.get_str(node_data, "symbol", "")
        exchange = self.get_str(node_data, "exchange", "NSE")
        operator = self.get_str(node_data, "operator", "gt")
        threshold = self.get_float(node_data, "threshold", 0)

        self.log(f"Checking price for: {symbol}")
        result = self.client.get_quotes(symbol=symbol, exchange=exchange)
        data = result.get("data", {})
        ltp = float(data.get("ltp", 0) if data else 0)
        condition_met = self._evaluate_condition(ltp, operator, threshold)
        self.log(f"Price check: ltp={ltp} {operator} {threshold} = {condition_met}")
        return {"status": "success", "condition": condition_met, "ltp": ltp}

    def execute_time_window(self, node_data: dict) -> dict:
        """Execute Time Window node"""
        start_time_str = node_data.get("startTime", "09:15")
        end_time_str = node_data.get("endTime", "15:30")

        now = datetime.now().time()
        start_h, start_m, _ = parse_time_string(start_time_str, 9, 15)
        end_h, end_m, _ = parse_time_string(end_time_str, 15, 30)
        start_time = time(start_h, start_m)
        end_time = time(end_h, end_m)

        condition_met = start_time <= now <= end_time
        self.log(f"Time window: {start_time_str}-{end_time_str}, in_window={condition_met}")
        return {"status": "success", "condition": condition_met}

    def execute_time_condition(self, node_data: dict) -> dict:
        """Execute Time Condition node"""
        target_time_str = node_data.get("targetTime", "09:30")
        operator = node_data.get("operator", ">=")

        now = datetime.now().time()
        target_hour, target_minute, _ = parse_time_string(target_time_str, 9, 30)
        target_time = time(target_hour, target_minute)

        now_seconds = now.hour * 3600 + now.minute * 60 + now.second
        target_seconds = target_time.hour * 3600 + target_time.minute * 60 + target_time.second

        if operator == ">=":
            condition_met = now_seconds >= target_seconds
        elif operator == "<=":
            condition_met = now_seconds <= target_seconds
        elif operator == ">":
            condition_met = now_seconds > target_seconds
        elif operator == "<":
            condition_met = now_seconds < target_seconds
        elif operator == "==":
            condition_met = now.hour == target_time.hour and now.minute == target_time.minute
        else:
            condition_met = False

        self.log(
            f"Time condition: {now.strftime('%H:%M')} {operator} {target_time_str} = {condition_met}"
        )
        return {"status": "success", "condition": condition_met}

    def execute_price_alert(self, node_data: dict) -> dict:
        """Execute Price Alert trigger node"""
        symbol = self.get_str(node_data, "symbol", "")
        exchange = self.get_str(node_data, "exchange", "NSE")
        condition_type = self.get_str(node_data, "condition", "greater_than")
        price = self.get_float(node_data, "price", 0)
        price_lower = self.get_float(node_data, "priceLower", 0)
        price_upper = self.get_float(node_data, "priceUpper", 0)

        if not symbol:
            return {"status": "error", "condition": False}

        result = self.client.get_quotes(symbol=symbol, exchange=exchange)
        if result.get("status") != "success":
            return {"status": "error", "condition": False}

        data = result.get("data", {})
        ltp = float(data.get("ltp", 0) if data else 0)

        condition_met = False
        if condition_type == "greater_than":
            condition_met = ltp > price
        elif condition_type == "less_than":
            condition_met = ltp < price
        elif condition_type == "crossing":
            tolerance = price * 0.001
            condition_met = abs(ltp - price) <= tolerance
        elif condition_type in ["entering_channel", "inside_channel"]:
            condition_met = price_lower <= ltp <= price_upper
        elif condition_type in ["exiting_channel", "outside_channel"]:
            condition_met = ltp < price_lower or ltp > price_upper

        self.log(f"Price alert: {symbol} LTP={ltp} {condition_type} {price} = {condition_met}")
        self.store_output(node_data, {"ltp": ltp, "condition_met": condition_met})
        return {"status": "success", "condition": condition_met, "ltp": ltp}

    # === Streaming Nodes (WebSocket with REST API fallback) ===

    def _get_websocket_data(
        self, symbol: str, exchange: str, mode: str, timeout: float = 5.0
    ) -> dict | None:
        """
        Get market data via WebSocket subscription using callback approach.

        Uses a callback to capture data with the correct mode, bypassing the
        shared cache which may contain data from other modes (e.g., LTP overwriting Depth).

        Args:
            symbol: Symbol to subscribe to
            exchange: Exchange code
            mode: Subscription mode ("LTP", "Quote", or "Depth")
            timeout: Maximum time to wait for data in seconds

        Returns:
            Market data dict or None if failed
        """
        import threading

        try:
            from database.auth_db import get_broker_name, verify_api_key
            from services.websocket_service import get_websocket_connection, subscribe_to_symbols

            # Get username from API key
            username = verify_api_key(self.client.api_key)
            if not username:
                self.log("WebSocket: Invalid API key", "warning")
                return None

            # Get broker name
            broker = get_broker_name(self.client.api_key) or "unknown"

            # Try to get WebSocket connection
            success, ws_client, error = get_websocket_connection(username)
            if not success:
                self.log(f"WebSocket connection failed: {error}", "warning")
                return None

            # Map mode string to numeric for comparison
            mode_to_num = {"LTP": 1, "Quote": 2, "Depth": 3}
            expected_mode_num = mode_to_num.get(mode, 2)

            # Thread-safe container for captured data
            captured_data = {"data": None}
            data_event = threading.Event()

            def on_market_data(data):
                """Callback to capture data with matching mode and symbol"""
                if captured_data["data"] is not None:
                    return  # Already captured

                data_symbol = data.get("symbol", "")
                data_exchange = data.get("exchange", "")
                data_mode = data.get("mode")

                # Check if this is the data we're looking for
                if (
                    data_symbol == symbol
                    and data_exchange == exchange
                    and data_mode == expected_mode_num
                ):
                    # For Depth mode, verify we have actual depth data (not just empty init message)
                    if mode == "Depth":
                        nested = data.get("data", {}) if isinstance(data.get("data"), dict) else {}
                        # Check multiple possible structures:
                        # 1. Standard: bids/asks arrays
                        # 2. Fyers: depth.buy/depth.sell arrays
                        bids = data.get("bids") or nested.get("bids") or []
                        asks = data.get("asks") or nested.get("asks") or []
                        # Fyers format: depth: {buy: [], sell: []}
                        depth_obj = data.get("depth", {}) or nested.get("depth", {})
                        if isinstance(depth_obj, dict):
                            bids = bids or depth_obj.get("buy", [])
                            asks = asks or depth_obj.get("sell", [])
                        if not bids and not asks:
                            return  # Skip empty depth messages, wait for actual data

                    captured_data["data"] = data
                    data_event.set()

            # Register callback before subscribing
            ws_client.register_callback("market_data", on_market_data)

            try:
                # Subscribe to symbol
                symbols = [{"symbol": symbol, "exchange": exchange}]
                sub_success, sub_result, _ = subscribe_to_symbols(username, broker, symbols, mode)

                if not sub_success:
                    self.log(f"WebSocket subscribe failed: {sub_result.get('message')}", "warning")
                    return None

                # Wait for data with the correct mode (using event instead of polling)
                if data_event.wait(timeout=timeout):
                    return captured_data["data"]
                else:
                    return None  # Timeout

            finally:
                # Always unregister callback
                ws_client.unregister_callback("market_data", on_market_data)

        except Exception as e:
            self.log(f"WebSocket error: {str(e)}", "warning")
            return None

    def execute_subscribe_ltp(self, node_data: dict) -> dict:
        """Execute Subscribe LTP node - get real-time LTP via WebSocket

        Connects to OpenAlgo WebSocket server and subscribes to LTP updates.
        Falls back to REST API if WebSocket fails or times out.
        """
        symbol = self.get_str(node_data, "symbol", "")
        exchange = self.get_str(node_data, "exchange", "NSE")
        output_var = node_data.get("outputVariable", "ltp")

        if not symbol:
            self.log("Subscribe LTP: No symbol specified", "error")
            return {"status": "error", "message": "No symbol specified"}

        self.log(f"Subscribing to LTP stream: {symbol} ({exchange})")

        # Try WebSocket first
        ws_data = self._get_websocket_data(symbol, exchange, "LTP", timeout=5.0)

        if ws_data:
            # LTP may be nested under 'data' or at top level
            nested_data = ws_data.get("data", {}) if isinstance(ws_data.get("data"), dict) else {}
            ltp = (
                nested_data.get("ltp")
                if nested_data.get("ltp") is not None
                else ws_data.get("ltp", 0)
            )

            streaming_result = {
                "status": "success",
                "type": "ltp",
                "symbol": symbol,
                "exchange": exchange,
                "ltp": ltp,
                "source": "websocket",
            }
            self.log(f"LTP for {symbol}: {ltp} (via WebSocket)")

            # Store in context variable
            self.context.set_variable(output_var, ltp)
            self.store_output(node_data, streaming_result)
            return streaming_result

        # Fallback to REST API
        self.log(f"WebSocket timeout/failed, falling back to REST API for {symbol}")

        try:
            result = self.client.get_quotes(symbol=symbol, exchange=exchange)

            if result.get("status") == "success":
                data = result.get("data", {})
                ltp = data.get("ltp", 0) if data else 0

                streaming_result = {
                    "status": "success",
                    "type": "ltp",
                    "symbol": symbol,
                    "exchange": exchange,
                    "ltp": ltp,
                    "source": "rest_api",
                }
                self.log(f"LTP for {symbol}: {ltp} (via REST API)")

                # Store in context variable
                self.context.set_variable(output_var, ltp)
                self.store_output(node_data, streaming_result)
                return streaming_result
            else:
                error_msg = result.get("error", "Failed to get LTP")
                self.log(f"Subscribe LTP error: {error_msg}", "error")
                return {
                    "status": "error",
                    "type": "ltp",
                    "symbol": symbol,
                    "exchange": exchange,
                    "error": error_msg,
                }

        except Exception as e:
            self.log(f"Subscribe LTP exception: {str(e)}", "error")
            return {
                "status": "error",
                "type": "ltp",
                "symbol": symbol,
                "exchange": exchange,
                "error": str(e),
            }

    def execute_subscribe_quote(self, node_data: dict) -> dict:
        """Execute Subscribe Quote node - get real-time quote via WebSocket

        Connects to OpenAlgo WebSocket and subscribes to quote updates (OHLC + volume).
        Falls back to REST API if WebSocket fails or times out.
        """
        symbol = self.get_str(node_data, "symbol", "")
        exchange = self.get_str(node_data, "exchange", "NSE")
        output_var = node_data.get("outputVariable", "quote")

        if not symbol:
            self.log("Subscribe Quote: No symbol specified", "error")
            return {"status": "error", "message": "No symbol specified"}

        self.log(f"Subscribing to Quote stream: {symbol} ({exchange})")

        # Try WebSocket first
        ws_data = self._get_websocket_data(symbol, exchange, "Quote", timeout=5.0)

        if ws_data:
            # Quote data may be nested under 'data' or at top level
            nested_data = ws_data.get("data", {}) if isinstance(ws_data.get("data"), dict) else {}

            # Extract from nested level first, fallback to top level
            quote_data = {
                "ltp": nested_data.get("ltp")
                if nested_data.get("ltp") is not None
                else ws_data.get("ltp", 0),
                "open": nested_data.get("open") or ws_data.get("open", 0),
                "high": nested_data.get("high") or ws_data.get("high", 0),
                "low": nested_data.get("low") or ws_data.get("low", 0),
                "close": nested_data.get("close")
                or nested_data.get("prev_close")
                or ws_data.get("close", ws_data.get("prev_close", 0)),
                "volume": nested_data.get("volume") or ws_data.get("volume", 0),
                "prev_close": nested_data.get("prev_close") or ws_data.get("prev_close", 0),
            }

            streaming_result = {
                "status": "success",
                "type": "quote",
                "symbol": symbol,
                "exchange": exchange,
                "data": quote_data,
                "source": "websocket",
            }
            self.log(f"Quote for {symbol}: LTP={quote_data.get('ltp')} (via WebSocket)")

            # Store in context variable
            self.context.set_variable(output_var, quote_data)
            self.store_output(node_data, streaming_result)
            return streaming_result

        # Fallback to REST API
        self.log(f"WebSocket timeout/failed, falling back to REST API for {symbol}")

        try:
            result = self.client.get_quotes(symbol=symbol, exchange=exchange)

            if result.get("status") == "success":
                data = result.get("data", {})

                quote_data = (
                    {
                        "ltp": data.get("ltp", 0),
                        "open": data.get("open", 0),
                        "high": data.get("high", 0),
                        "low": data.get("low", 0),
                        "close": data.get("close", data.get("prev_close", 0)),
                        "volume": data.get("volume", 0),
                        "prev_close": data.get("prev_close", 0),
                    }
                    if data
                    else {}
                )

                streaming_result = {
                    "status": "success",
                    "type": "quote",
                    "symbol": symbol,
                    "exchange": exchange,
                    "data": quote_data,
                    "source": "rest_api",
                }
                self.log(f"Quote for {symbol}: LTP={quote_data.get('ltp')} (via REST API)")

                # Store in context variable
                self.context.set_variable(output_var, quote_data)
                self.store_output(node_data, streaming_result)
                return streaming_result
            else:
                error_msg = result.get("error", "Failed to get quote")
                self.log(f"Subscribe Quote error: {error_msg}", "error")
                return {
                    "status": "error",
                    "type": "quote",
                    "symbol": symbol,
                    "exchange": exchange,
                    "error": error_msg,
                }

        except Exception as e:
            self.log(f"Subscribe Quote exception: {str(e)}", "error")
            return {
                "status": "error",
                "type": "quote",
                "symbol": symbol,
                "exchange": exchange,
                "error": str(e),
            }

    def execute_subscribe_depth(self, node_data: dict) -> dict:
        """Execute Subscribe Depth node - get market depth via WebSocket

        Connects to OpenAlgo WebSocket and subscribes to depth updates (order book).
        Falls back to REST API if WebSocket fails or times out.
        """
        symbol = self.get_str(node_data, "symbol", "")
        exchange = self.get_str(node_data, "exchange", "NSE")
        output_var = node_data.get("outputVariable", "depth")

        if not symbol:
            self.log("Subscribe Depth: No symbol specified", "error")
            return {"status": "error", "message": "No symbol specified"}

        self.log(f"Subscribing to Depth stream: {symbol} ({exchange})")

        # Try WebSocket first (shorter timeout for depth as it may not stream outside market hours)
        ws_data = self._get_websocket_data(symbol, exchange, "Depth", timeout=3.0)

        if ws_data:
            # Depth data may be nested under 'data' or at top level
            # Handle multiple nesting levels: ws_data -> data -> (actual depth fields)
            nested_data = ws_data.get("data", {}) if isinstance(ws_data.get("data"), dict) else {}

            # Check for Fyers format: depth: {buy: [], sell: []}
            depth_obj = ws_data.get("depth", {}) or nested_data.get("depth", {})
            if isinstance(depth_obj, dict) and (depth_obj.get("buy") or depth_obj.get("sell")):
                # Fyers format - convert to standard bids/asks
                bids = depth_obj.get("buy", [])
                asks = depth_obj.get("sell", [])
                # Convert Fyers format (price/quantity) if needed
                if bids and isinstance(bids[0], dict) and "price" in bids[0]:
                    bids = [
                        {
                            "price": b.get("price", 0),
                            "quantity": b.get("quantity", b.get("volume", 0)),
                        }
                        for b in bids
                    ]
                if asks and isinstance(asks[0], dict) and "price" in asks[0]:
                    asks = [
                        {
                            "price": a.get("price", 0),
                            "quantity": a.get("quantity", a.get("volume", 0)),
                        }
                        for a in asks
                    ]
            else:
                # Standard format
                bids = nested_data.get("bids") or ws_data.get("bids", [])
                asks = nested_data.get("asks") or ws_data.get("asks", [])

            # Extract depth fields
            depth_data = {
                "bids": bids,
                "asks": asks,
                "totalbuyqty": nested_data.get("totalbuyqty") or ws_data.get("totalbuyqty", 0),
                "totalsellqty": nested_data.get("totalsellqty") or ws_data.get("totalsellqty", 0),
                "ltp": nested_data.get("ltp")
                if nested_data.get("ltp") is not None
                else ws_data.get("ltp", 0),
            }

            streaming_result = {
                "status": "success",
                "type": "depth",
                "symbol": symbol,
                "exchange": exchange,
                "data": depth_data,
                "source": "websocket",
            }
            # Log depth summary with top bid/ask prices
            bids_list = depth_data.get("bids", [])
            asks_list = depth_data.get("asks", [])
            top_bid = bids_list[0].get("price", 0) if bids_list else 0
            top_ask = asks_list[0].get("price", 0) if asks_list else 0
            self.log(
                f"Depth for {symbol}: Bid={top_bid}, Ask={top_ask} ({len(bids_list)} bids, {len(asks_list)} asks) via WebSocket"
            )

            # Store in context variable
            self.context.set_variable(output_var, depth_data)
            self.store_output(node_data, streaming_result)
            return streaming_result

        # Fallback to REST API
        self.log(f"WebSocket timeout/failed, falling back to REST API for {symbol}")

        try:
            result = self.client.get_depth(symbol=symbol, exchange=exchange)

            if result.get("status") == "success":
                data = result.get("data", {})

                depth_data = (
                    {
                        "bids": data.get("bids", []),
                        "asks": data.get("asks", []),
                        "totalbuyqty": data.get("totalbuyqty", 0),
                        "totalsellqty": data.get("totalsellqty", 0),
                        "ltp": data.get("ltp", 0),
                    }
                    if data
                    else {"bids": [], "asks": []}
                )

                streaming_result = {
                    "status": "success",
                    "type": "depth",
                    "symbol": symbol,
                    "exchange": exchange,
                    "data": depth_data,
                    "source": "rest_api",
                }
                # Log depth summary with top bid/ask prices
                bids_list = depth_data.get("bids", [])
                asks_list = depth_data.get("asks", [])
                top_bid = bids_list[0].get("price", 0) if bids_list else 0
                top_ask = asks_list[0].get("price", 0) if asks_list else 0
                self.log(
                    f"Depth for {symbol}: Bid={top_bid}, Ask={top_ask} ({len(bids_list)} bids, {len(asks_list)} asks) via REST API"
                )

                # Store in context variable
                self.context.set_variable(output_var, depth_data)
                self.store_output(node_data, streaming_result)
                return streaming_result
            else:
                error_msg = result.get("error", "Failed to get depth")
                self.log(f"Subscribe Depth error: {error_msg}", "error")
                return {
                    "status": "error",
                    "type": "depth",
                    "symbol": symbol,
                    "exchange": exchange,
                    "error": error_msg,
                }

        except Exception as e:
            self.log(f"Subscribe Depth exception: {str(e)}", "error")
            return {
                "status": "error",
                "type": "depth",
                "symbol": symbol,
                "exchange": exchange,
                "error": str(e),
            }

    def execute_unsubscribe(self, node_data: dict) -> dict:
        """Execute Unsubscribe node - unsubscribe from WebSocket streams

        Unsubscribes from specified stream type (ltp/quote/depth/all).
        """
        symbol = self.get_str(node_data, "symbol", "")
        exchange = self.get_str(node_data, "exchange", "NSE")
        stream_type = self.get_str(node_data, "streamType", "all")

        self.log(f"Unsubscribing from {stream_type} stream: {symbol or 'all'} ({exchange})")

        try:
            from database.auth_db import get_broker_name, verify_api_key
            from services.websocket_service import (
                get_websocket_connection,
                unsubscribe_all,
                unsubscribe_from_symbols,
            )

            # Get username from API key
            username = verify_api_key(self.client.api_key)
            if not username:
                self.log("Unsubscribe: Invalid API key", "warning")
                return {
                    "status": "success",
                    "type": "unsubscribe",
                    "message": "No active WebSocket connection",
                }

            # Get broker name
            broker = get_broker_name(self.client.api_key) or "unknown"

            # Check WebSocket connection
            success, ws_client, error = get_websocket_connection(username)
            if not success:
                return {
                    "status": "success",
                    "type": "unsubscribe",
                    "message": "No active WebSocket connection",
                }

            # Map stream_type to mode
            mode_map = {"ltp": "LTP", "quote": "Quote", "depth": "Depth"}

            if stream_type.lower() == "all" or not symbol:
                # Unsubscribe from all
                unsub_success, unsub_result, _ = unsubscribe_all(username, broker)
                self.log("Unsubscribed from all streams")
            else:
                # Unsubscribe from specific symbol/mode
                mode = mode_map.get(stream_type.lower(), "Quote")
                symbols = [{"symbol": symbol, "exchange": exchange}]
                unsub_success, unsub_result, _ = unsubscribe_from_symbols(
                    username, broker, symbols, mode
                )
                self.log(f"Unsubscribed from {stream_type} for {symbol}")

            return {
                "status": "success",
                "type": "unsubscribe",
                "symbol": symbol,
                "exchange": exchange,
                "stream_type": stream_type,
                "message": f"Unsubscribed from {stream_type} stream",
            }

        except Exception as e:
            self.log(f"Unsubscribe error: {str(e)}", "warning")
            return {
                "status": "success",
                "type": "unsubscribe",
                "symbol": symbol,
                "exchange": exchange,
                "stream_type": stream_type,
                "message": "Unsubscribe completed (with warnings)",
            }

    # === Logic Gates ===

    def execute_and_gate(self, node_data: dict, input_results: list[bool]) -> dict:
        """Execute AND Gate"""
        if not input_results:
            return {"status": "success", "condition": False}
        condition_met = all(input_results)
        self.log(f"AND Gate: {input_results} -> {condition_met}")
        return {"status": "success", "condition": condition_met}

    def execute_or_gate(self, node_data: dict, input_results: list[bool]) -> dict:
        """Execute OR Gate"""
        if not input_results:
            return {"status": "success", "condition": False}
        condition_met = any(input_results)
        self.log(f"OR Gate: {input_results} -> {condition_met}")
        return {"status": "success", "condition": condition_met}

    def execute_not_gate(self, node_data: dict, input_results: list[bool]) -> dict:
        """Execute NOT Gate"""
        input_value = input_results[0] if input_results else False
        condition_met = not input_value
        self.log(f"NOT Gate: {input_value} -> {condition_met}")
        return {"status": "success", "condition": condition_met}


def execute_node_chain(
    node_id: str,
    nodes: list,
    edge_map: dict[str, list[dict]],
    incoming_edge_map: dict[str, list[dict]],
    executor: NodeExecutor,
    context: WorkflowContext,
    visited_count: dict[str, int],
    depth: int = 0,
):
    """Execute a chain of nodes"""
    if depth > MAX_NODE_DEPTH:
        raise Exception(f"Maximum node depth ({MAX_NODE_DEPTH}) exceeded")

    total_visits = sum(visited_count.values())
    if total_visits >= MAX_NODE_VISITS:
        raise Exception(f"Maximum node visits ({MAX_NODE_VISITS}) exceeded")

    visited_count[node_id] = visited_count.get(node_id, 0) + 1

    node = next((n for n in nodes if n["id"] == node_id), None)
    if not node:
        return

    node_type = node.get("type")
    node_data = node.get("data", {})
    result = None

    # Execute node based on type
    if node_type == "start":
        executor.log("Workflow started")
    elif node_type == "placeOrder":
        result = executor.execute_place_order(node_data)
    elif node_type == "smartOrder":
        result = executor.execute_smart_order(node_data)
    elif node_type == "optionsOrder":
        result = executor.execute_options_order(node_data)
    elif node_type == "modifyOrder":
        result = executor.execute_modify_order(node_data)
    elif node_type == "optionsMultiOrder":
        result = executor.execute_options_multi_order(node_data)
    elif node_type == "cancelOrder":
        result = executor.execute_cancel_order(node_data)
    elif node_type == "cancelAllOrders":
        result = executor.execute_cancel_all_orders(node_data)
    elif node_type == "closePositions":
        result = executor.execute_close_positions(node_data)
    elif node_type == "basketOrder":
        result = executor.execute_basket_order(node_data)
    elif node_type == "splitOrder":
        result = executor.execute_split_order(node_data)
    elif node_type == "getQuote":
        result = executor.execute_get_quote(node_data)
    elif node_type == "getDepth":
        result = executor.execute_get_depth(node_data)
    elif node_type == "getOrderStatus":
        result = executor.execute_get_order_status(node_data)
    elif node_type == "openPosition":
        result = executor.execute_open_position(node_data)
    elif node_type == "history":
        result = executor.execute_history(node_data)
    elif node_type == "symbol":
        result = executor.execute_symbol(node_data)
    elif node_type == "optionSymbol":
        result = executor.execute_option_symbol(node_data)
    elif node_type == "expiry":
        result = executor.execute_expiry(node_data)
    elif node_type == "intervals":
        result = executor.execute_intervals(node_data)
    elif node_type == "multiQuotes":
        result = executor.execute_multi_quotes(node_data)
    elif node_type == "optionChain":
        result = executor.execute_option_chain(node_data)
    elif node_type == "syntheticFuture":
        result = executor.execute_synthetic_future(node_data)
    elif node_type == "holidays":
        result = executor.execute_holidays(node_data)
    elif node_type == "timings":
        result = executor.execute_timings(node_data)
    elif node_type == "orderBook":
        result = executor.execute_order_book(node_data)
    elif node_type == "tradeBook":
        result = executor.execute_trade_book(node_data)
    elif node_type == "positionBook":
        result = executor.execute_position_book(node_data)
    elif node_type == "holdings":
        result = executor.execute_holdings(node_data)
    elif node_type == "funds":
        result = executor.execute_funds(node_data)
    elif node_type == "margin":
        result = executor.execute_margin(node_data)
    elif node_type == "delay":
        result = executor.execute_delay(node_data)
    elif node_type == "waitUntil":
        result = executor.execute_wait_until(node_data)
    elif node_type == "log":
        result = executor.execute_log(node_data)
    elif node_type == "variable":
        result = executor.execute_variable(node_data)
    elif node_type == "mathExpression":
        result = executor.execute_math_expression(node_data)
    elif node_type == "group":
        # Group is just a container, pass through
        pass
    elif node_type == "telegramAlert":
        result = executor.execute_telegram_alert(node_data)
    elif node_type == "httpRequest":
        result = executor.execute_http_request(node_data)
    elif node_type == "positionCheck":
        result = executor.execute_position_check(node_data)
    elif node_type == "fundCheck":
        result = executor.execute_fund_check(node_data)
    elif node_type == "priceCondition":
        result = executor.execute_price_condition(node_data)
    elif node_type == "timeWindow":
        result = executor.execute_time_window(node_data)
    elif node_type == "timeCondition":
        result = executor.execute_time_condition(node_data)
    elif node_type == "priceAlert":
        result = executor.execute_price_alert(node_data)
    elif node_type == "webhookTrigger":
        executor.log("Webhook trigger activated")
    # Streaming Nodes
    elif node_type == "subscribeLtp":
        result = executor.execute_subscribe_ltp(node_data)
    elif node_type == "subscribeQuote":
        result = executor.execute_subscribe_quote(node_data)
    elif node_type == "subscribeDepth":
        result = executor.execute_subscribe_depth(node_data)
    elif node_type == "unsubscribe":
        result = executor.execute_unsubscribe(node_data)
    elif node_type == "andGate":
        incoming_edges = incoming_edge_map.get(node_id, [])
        input_results = []
        for edge in incoming_edges:
            source_result = context.get_condition_result(edge.get("source"))
            if source_result is not None:
                input_results.append(source_result)
        result = executor.execute_and_gate(node_data, input_results)
    elif node_type == "orGate":
        incoming_edges = incoming_edge_map.get(node_id, [])
        input_results = []
        for edge in incoming_edges:
            source_result = context.get_condition_result(edge.get("source"))
            if source_result is not None:
                input_results.append(source_result)
        result = executor.execute_or_gate(node_data, input_results)
    elif node_type == "notGate":
        incoming_edges = incoming_edge_map.get(node_id, [])
        input_results = []
        for edge in incoming_edges:
            source_result = context.get_condition_result(edge.get("source"))
            if source_result is not None:
                input_results.append(source_result)
        result = executor.execute_not_gate(node_data, input_results)
    else:
        executor.log(f"Unknown node type: {node_type}", "warning")

    # Determine which edges to follow
    edges_to_follow = edge_map.get(node_id, [])

    # For condition nodes, filter edges based on Yes/No
    if result and "condition" in result:
        condition_met = result.get("condition", False)
        context.set_condition_result(node_id, condition_met)
        filtered_edges = []
        for edge in edges_to_follow:
            source_handle = edge.get("sourceHandle", "")
            if condition_met and source_handle == "yes":
                filtered_edges.append(edge)
            elif not condition_met and source_handle == "no":
                filtered_edges.append(edge)
            elif source_handle not in ["yes", "no"]:
                filtered_edges.append(edge)
        edges_to_follow = filtered_edges

    # Execute connected nodes
    for edge in edges_to_follow:
        target_id = edge.get("target")
        if target_id:
            execute_node_chain(
                target_id,
                nodes,
                edge_map,
                incoming_edge_map,
                executor,
                context,
                visited_count,
                depth + 1,
            )


def execute_workflow(
    workflow_id: int, webhook_data: dict[str, Any] | None = None, api_key: str = None
) -> dict:
    """Execute a workflow synchronously"""
    lock = get_workflow_lock(workflow_id)

    if lock.locked():
        logger.warning(f"Workflow {workflow_id} is already running")
        return {
            "status": "error",
            "message": "Workflow is already running",
            "already_running": True,
        }

    with lock:
        workflow = get_workflow(workflow_id)
        if not workflow:
            return {"status": "error", "message": "Workflow not found"}

        execution = create_execution(workflow_id, status="running")
        if not execution:
            return {"status": "error", "message": "Failed to create execution record"}

        logs = []
        context = WorkflowContext()

        if webhook_data:
            context.set_variable("webhook", webhook_data)
            logger.info(f"Webhook data injected: {webhook_data}")

        try:
            if not api_key:
                raise Exception("API key required for workflow execution")

            client = get_flow_client(api_key)
            executor = NodeExecutor(client, context, logs)
            logger.info(f"Starting workflow: {workflow.name}")
            executor.log(f"Starting workflow: {workflow.name}")

            nodes = workflow.nodes or []
            edges = workflow.edges or []

            # Find trigger node
            trigger_types = ["start", "webhookTrigger", "priceAlert"]
            start_node = next((n for n in nodes if n.get("type") in trigger_types), None)
            if not start_node:
                raise Exception("No trigger node found")

            # Build edge maps
            edge_map: dict[str, list[dict]] = {}
            incoming_edge_map: dict[str, list[dict]] = {}
            for edge in edges:
                source = edge["source"]
                target = edge["target"]
                if source not in edge_map:
                    edge_map[source] = []
                edge_map[source].append(edge)
                if target not in incoming_edge_map:
                    incoming_edge_map[target] = []
                incoming_edge_map[target].append(edge)

            visited_count: dict[str, int] = {}

            execute_node_chain(
                start_node["id"],
                nodes,
                edge_map,
                incoming_edge_map,
                executor,
                context,
                visited_count,
                depth=0,
            )

            update_execution_status(execution.id, "completed")
            return {
                "status": "success",
                "message": "Workflow executed successfully",
                "execution_id": execution.id,
                "logs": logs,
            }

        except Exception as e:
            logger.exception(f"Workflow execution failed: {e}")
            logs.append(
                {
                    "time": datetime.now().isoformat(),
                    "message": f"Error: {str(e)}",
                    "level": "error",
                }
            )
            update_execution_status(execution.id, "failed", error=str(e))
            return {
                "status": "error",
                "message": str(e),
                "execution_id": execution.id,
                "logs": logs,
            }
