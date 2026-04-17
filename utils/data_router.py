"""Route market-data calls to either the connected broker or a configured vendor.

Selection is environment-driven via DATA_VENDOR:
    DATA_VENDOR = 'broker'    -> use broker.<name>.api.data (default)
    DATA_VENDOR = 'yfinance'  -> use vendors.yfinance.api.data

Order placement, funds, positions etc. always flow through the broker; only
quote/ltp/depth/history dispatches check this router.
"""

import importlib
from typing import Any

from utils.logging import get_logger
from vendors.base_vendor import BaseDataVendor, VendorCapabilityError, VendorSymbolError
from vendors.vendor_factory import (
    BROKER_SENTINEL,
    create_vendor_data_handler,
    get_active_vendor_name,
    is_vendor_enabled,
)

logger = get_logger(__name__)


def resolve_data_source(broker_name: str | None) -> tuple[str, str]:
    """Return (kind, name) where kind is 'vendor' or 'broker'."""
    if is_vendor_enabled():
        return "vendor", get_active_vendor_name()
    return "broker", (broker_name or "")


def build_data_handler(
    broker_name: str | None,
    auth_token: str | None,
    feed_token: str | None = None,
    user_id: str | None = None,
) -> tuple[Any, str, str]:
    """Build a data handler (vendor or broker) and return (handler, kind, name).

    The returned handler exposes the same methods as broker's BrokerData:
    get_quotes, get_multiquotes (optional), get_depth, get_history, timeframe_map.
    """
    kind, name = resolve_data_source(broker_name)
    if kind == "vendor":
        handler = create_vendor_data_handler(name)
        return handler, kind, name

    module_path = f"broker.{name}.api.data"
    try:
        broker_module = importlib.import_module(module_path)
    except ImportError as exc:
        logger.error("Failed to import broker data module '%s': %s", module_path, exc)
        raise

    broker_data_cls = broker_module.BrokerData
    param_count = broker_data_cls.__init__.__code__.co_argcount
    if param_count > 3:
        handler = broker_data_cls(auth_token, feed_token, user_id)
    elif param_count > 2:
        handler = broker_data_cls(auth_token, feed_token)
    else:
        handler = broker_data_cls(auth_token)
    return handler, kind, name


def vendor_exchange_supported(exchange: str) -> bool:
    if not is_vendor_enabled():
        return True
    try:
        handler = create_vendor_data_handler(get_active_vendor_name())
    except Exception:
        return False
    return (exchange or "").upper() in {e.upper() for e in handler.supported_exchanges}


def vendor_capability_enabled(capability: str) -> bool:
    if not is_vendor_enabled():
        return True
    try:
        handler = create_vendor_data_handler(get_active_vendor_name())
    except Exception:
        return False
    return bool(handler.capabilities.get(capability, False))


__all__ = [
    "BROKER_SENTINEL",
    "VendorCapabilityError",
    "VendorSymbolError",
    "BaseDataVendor",
    "build_data_handler",
    "is_vendor_enabled",
    "get_active_vendor_name",
    "resolve_data_source",
    "vendor_capability_enabled",
    "vendor_exchange_supported",
]
