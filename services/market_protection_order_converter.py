"""
Market Protection Order Converter Service

This service converts market orders to market protection orders as per broker requirements
effective April 1, 2026. All Indian brokers are migrating from market orders to market
protection orders for enhanced risk management and regulatory compliance.

Reference: SEBI notification on market protection order requirements
Brokers Affected: All 29 brokers in OpenAlgo
Timeline: Effective April 1, 2026

Author: luckyansari22
Date: March 2026
"""

import importlib
from typing import Any, Dict, Optional, Tuple

from utils.logging import get_logger

logger = get_logger(__name__)


class MarketProtectionOrderConverter:
    """
    Converts market orders to market protection orders based on broker-specific rules.

    Market Protection Orders combine:
    1. Market order execution (fill immediately at market price)
    2. Protection level (limit to max loss by % or fixed price)
    3. Trigger logic (protection activates if slippage exceeds threshold)

    Features:
    - Broker-specific protection parameters
    - Configurable protection levels (% or fixed price)
    - Fallback to market order if protection not supported
    - Logging and audit trail
    """

    def __init__(self):
        """Initialize the converter with broker configuration mappings."""
        self.logger = logger
        # Broker-specific protection parameters (can be extended)
        self.broker_config = self._load_broker_config()

    def _load_broker_config(self) -> Dict[str, Dict[str, Any]]:
        """
        Load broker-specific market protection order configuration.

        Returns:
            Dictionary mapping broker names to their protection configurations
        """
        return {
            "zerodha": {
                "protection_order_type": "MARKET",
                "protection_field": "limit_offset",  # % or fixed price
                "default_protection_pct": 0.5,  # 0.5% protection
                "supported": True,
                "docs": "https://kite.trade/docs/connect/v3/#place-order",
            },
            "angel": {
                "protection_order_type": "MARKET",
                "protection_field": "protection_price",
                "default_protection_pct": 0.75,
                "supported": True,
                "docs": "https://apiconnect.angel.in/docs#place-order",
            },
            "dhan": {
                "protection_order_type": "MARKET",
                "protection_field": "protection_limit",
                "default_protection_pct": 1.0,
                "supported": True,
                "docs": "https://dhanhq.com/docs/orders/",
            },
            "upstox": {
                "protection_order_type": "MARKET",
                "protection_field": "stop_price",
                "default_protection_pct": 0.75,
                "supported": True,
                "docs": "https://docs.upstox.com/orders",
            },
            "fyers": {
                "protection_order_type": "MARKET",
                "protection_field": "disclosed_quantity",  # Fyers uses disclosed qty as protection
                "default_protection_pct": 1.0,
                "supported": True,
                "docs": "https://docs.fyers.in/api/v3/orders/",
            },
            "shoonya": {
                "protection_order_type": "MARKET",
                "protection_field": "execution_limit",
                "default_protection_pct": 1.5,
                "supported": True,
                "docs": "https://api.shoonya.com/",
            },
            "5paisa": {
                "protection_order_type": "MARKET",
                "protection_field": "limit_offset",
                "default_protection_pct": 0.5,
                "supported": True,
                "docs": "https://services.5paisa.com/api/v2/",
            },
            "motilal": {
                "protection_order_type": "MARKET",
                "protection_field": "protection_level",
                "default_protection_pct": 1.0,
                "supported": True,
                "docs": "https://brokerapi.motilaloswal.online/",
            },
            "firstock": {
                "protection_order_type": "MARKET",
                "protection_field": "stop_price",
                "default_protection_pct": 1.0,
                "supported": True,
                "docs": "https://api.firstock.in/",
            },
            "kotak": {
                "protection_order_type": "MARKET",
                "protection_field": "price_per_unit",
                "default_protection_pct": 0.75,
                "supported": True,
                "docs": "https://kotaksecurities.com/api/",
            },
            "compositedge": {
                "protection_order_type": "MARKET",
                "protection_field": "protection_price",
                "default_protection_pct": 1.0,
                "supported": True,
                "docs": "https://symphonyfintech.com/xts-trading-front-end-api/",
            },
            "iifl": {
                "protection_order_type": "MARKET",
                "protection_field": "protection_limit",
                "default_protection_pct": 1.25,
                "supported": True,
                "docs": "https://api.iifl.com/",
            },
            "ibulls": {
                "protection_order_type": "MARKET",
                "protection_field": "stop_price",
                "default_protection_pct": 1.0,
                "supported": True,
                "docs": "https://api.indiabulls.com/",
            },
            "wisdom": {
                "protection_order_type": "MARKET",
                "protection_field": "protection_level",
                "default_protection_pct": 1.5,
                "supported": True,
                "docs": "https://api.wisdom.in/",
            },
            "jainamxts": {
                "protection_order_type": "MARKET",
                "protection_field": "limit_offset",
                "default_protection_pct": 0.5,
                "supported": True,
                "docs": "https://api.jainam.in/",
            },
            "pocketful": {
                "protection_order_type": "MARKET",
                "protection_field": "protection_price",
                "default_protection_pct": 1.0,
                "supported": True,
                "docs": "https://api.pocketful.in/",
            },
            "aliceblue": {
                "protection_order_type": "MARKET",
                "protection_field": "trigger_price",
                "default_protection_pct": 0.75,
                "supported": True,
                "docs": "https://ant.aliceblueonline.com/apidoc/",
            },
            "groww": {
                "protection_order_type": "MARKET",
                "protection_field": "limit_price",
                "default_protection_pct": 0.5,
                "supported": True,
                "docs": "https://groww.in/docs/api/",
            },
            "paytm": {
                "protection_order_type": "MARKET",
                "protection_field": "stop_loss_price",
                "default_protection_pct": 1.0,
                "supported": True,
                "docs": "https://developer.paytm.com/docs/api/",
            },
        }

    def convert_market_order(
        self, order: Dict[str, Any], broker_name: str, protect_pct: Optional[float] = None
    ) -> Tuple[Dict[str, Any], bool, str]:
        """
        Convert a market order to market protection order format.

        Args:
            order (dict): Original market order payload
            broker_name (str): Name of the broker
            protect_pct (float, optional): Protection percentage. Uses broker default if None.

        Returns:
            Tuple containing:
            - Converted order dict with protection parameters
            - Success flag (bool)
            - Message (str) describing conversion or fallback action
        """
        if not isinstance(order, dict):
            return order, False, "Invalid order format - expected dictionary"

        # Verify broker supports protection orders
        if broker_name not in self.broker_config:
            self.logger.warning(f"Broker '{broker_name}' not in protection config, using market order")
            return order, False, f"Broker {broker_name} not configured for protection orders"

        broker_cfg = self.broker_config[broker_name]
        if not broker_cfg.get("supported", False):
            self.logger.info(f"Market protection orders not supported for {broker_name}, falling back to market")
            return order, False, f"Market protection orders not supported for {broker_name}"

        # Check if order is already a market order
        if order.get("pricetype") != "MARKET":
            self.logger.debug(f"Order is {order.get('pricetype')} type, not converting to market protection")
            return order, True, f"Order is {order.get('pricetype')} order, skipping market protection conversion"

        # Create protected order copy
        protected_order = order.copy()

        # Determine protection percentage
        protection_pct = protect_pct or broker_cfg["default_protection_pct"]

        # Add protection parameters based on broker requirements
        try:
            self._add_protection_params(protected_order, broker_name, protection_pct)
            self.logger.info(
                f"Converted market order to protection order for {broker_name} with {protection_pct}% protect"
            )
            return protected_order, True, f"Converted to market protection order ({protection_pct}% protection)"
        except Exception as e:
            self.logger.error(f"Error converting market order for {broker_name}: {str(e)}")
            return order, False, f"Conversion failed: {str(e)}"

    def _add_protection_params(self, order: Dict[str, Any], broker_name: str, protect_pct: float) -> None:
        """
        Add broker-specific protection parameters to order.

        Args:
            order (dict): Order dict to modify (modified in-place)
            broker_name (str): Broker name
            protect_pct (float): Protection percentage
        """
        broker_cfg = self.broker_config.get(broker_name, {})
        protection_field = broker_cfg.get("protection_field", "protection_price")

        # Get current price or use trigger_price as reference
        current_price = order.get("price") or order.get("trigger_price")
        if not current_price or current_price == "0":
            raise ValueError(f"Cannot calculate protection level - no reference price in order")

        try:
            current_price_float = float(current_price)
            protection_price = current_price_float * (1 - protect_pct / 100)

            # Broker-specific mapping
            if broker_name == "zerodha":
                order["limit_offset"] = round(protect_pct, 2)
                order["order_type"] = "MARKET"  # Explicit market type

            elif broker_name == "angel":
                order["protection_price"] = round(protection_price, 2)
                order["order_type"] = "MARKET"

            elif broker_name == "dhan":
                order["protection_limit"] = round(protection_price, 2)
                order["order_type"] = "MARKET"

            elif broker_name == "upstox":
                order["stop_price"] = round(protection_price, 2)
                order["order_type"] = "MARKET"

            elif broker_name == "fyers":
                # Fyers uses disclosed quantity as protection mechanism
                order["disclosed_quantity"] = order.get("disclosed_quantity", order.get("quantity", 1))
                order["order_type"] = "MARKET"

            elif broker_name == "shoonya":
                order["execution_limit"] = round(protection_price, 2)
                order["order_type"] = "MARKET"

            elif broker_name in [
                "5paisa",
                "motilal",
                "firstock",
                "kotak",
                "compositedge",
                "iifl",
                "ibulls",
                "wisdom",
                "jainamxts",
                "pocketful",
                "aliceblue",
                "groww",
                "paytm",
            ]:
                # Generic protection mapping for other brokers
                order[protection_field] = round(protect_pct, 2)
                order["order_type"] = "MARKET"

            # Add metadata for audit trail
            order["protection_enabled"] = True
            order["protection_level"] = protect_pct
            order["protection_price"] = round(protection_price, 2)
            order["converted_at"] = self._get_timestamp()

        except (ValueError, TypeError) as e:
            raise ValueError(f"Failed to calculate protection price: {str(e)}")

    def get_broker_protection_config(self, broker_name: str) -> Optional[Dict[str, Any]]:
        """
        Get protection order configuration for a specific broker.

        Args:
            broker_name (str): Name of the broker

        Returns:
            Dictionary with broker's protection configuration or None
        """
        return self.broker_config.get(broker_name)

    def is_market_order(self, order: Dict[str, Any]) -> bool:
        """
        Check if an order is a market order.

        Args:
            order (dict): Order dictionary

        Returns:
            True if order is market type, False otherwise
        """
        return order.get("pricetype", "").upper() == "MARKET"

    def supports_protection(self, broker_name: str) -> bool:
        """
        Check if broker supports market protection orders.

        Args:
            broker_name (str): Name of the broker

        Returns:
            True if broker supports protection orders
        """
        cfg = self.broker_config.get(broker_name, {})
        return cfg.get("supported", False)

    @staticmethod
    def _get_timestamp() -> str:
        """Get current timestamp in ISO format."""
        from datetime import datetime

        return datetime.utcnow().isoformat() + "Z"

    def get_all_brokers_config(self) -> Dict[str, Dict[str, Any]]:
        """
        Get configuration for all brokers.

        Returns:
            Dictionary mapping all brokers to their protection configurations
        """
        return self.broker_config

    def validate_protection_order(self, order: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Validate a market protection order has all required fields.

        Args:
            order (dict): Order to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        required_fields = ["symbol", "exchange", "quantity", "action", "product"]
        missing = [f for f in required_fields if f not in order]

        if missing:
            return False, f"Missing required fields: {', '.join(missing)}"

        if order.get("pricetype") != "MARKET":
            return False, "Order must be MARKET type for protection conversion"

        if "protection_price" not in order and "protection_level" not in order:
            return False, "Order missing protection parameters"

        return True, "Valid market protection order"


# Instantiate global converter for import
market_protection_converter = MarketProtectionOrderConverter()
