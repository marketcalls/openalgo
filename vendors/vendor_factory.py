import importlib
import os
import re
from typing import Any

from utils.logging import get_logger

from .base_vendor import BaseDataVendor

logger = get_logger(__name__)

_VENDOR_CLASS_CACHE: dict[str, type[BaseDataVendor]] = {}

BROKER_SENTINEL = "broker"

# Vendor names must be simple identifiers — prevents malformed DATA_VENDOR
# values from being fed into importlib. Defense in depth on top of the
# VALID_DATA_VENDORS whitelist enforced by env_check.
_VENDOR_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")


def _assert_valid_vendor_name(vendor_name: str) -> str:
    name = (vendor_name or "").strip().lower()
    if not _VENDOR_NAME_RE.match(name):
        raise ValueError(f"Invalid vendor name: '{vendor_name}'")
    if name == BROKER_SENTINEL:
        raise ValueError("'broker' is a sentinel, not a loadable vendor")
    if name not in get_valid_vendor_names():
        raise ValueError(
            f"Vendor '{name}' is not in VALID_DATA_VENDORS — refusing to load"
        )
    return name


def get_active_vendor_name() -> str:
    """Return the configured DATA_VENDOR (lowercased). Defaults to 'broker'."""
    name = (os.getenv("DATA_VENDOR", "") or "").strip().lower()
    return name or BROKER_SENTINEL


def get_valid_vendor_names() -> list[str]:
    raw = os.getenv("VALID_DATA_VENDORS", "") or ""
    return [v.strip().lower() for v in raw.split(",") if v.strip()]


def is_vendor_enabled() -> bool:
    """True when DATA_VENDOR selects a real vendor (anything other than 'broker')."""
    name = get_active_vendor_name()
    if name == BROKER_SENTINEL:
        return False
    if name not in get_valid_vendor_names():
        logger.warning(
            "DATA_VENDOR '%s' is set but not in VALID_DATA_VENDORS; falling back to broker data",
            name,
        )
        return False
    return True


def _load_vendor_class(vendor_name: str) -> type[BaseDataVendor]:
    safe_name = _assert_valid_vendor_name(vendor_name)
    if safe_name in _VENDOR_CLASS_CACHE:
        return _VENDOR_CLASS_CACHE[safe_name]

    module_path = f"vendors.{safe_name}.api.data"
    module = importlib.import_module(module_path)
    vendor_class = getattr(module, "VendorData", None)
    if vendor_class is None or not isinstance(vendor_class, type) or not issubclass(
        vendor_class, BaseDataVendor
    ):
        raise RuntimeError(
            f"vendors/{safe_name}/api/data.py must expose a VendorData class "
            f"that subclasses BaseDataVendor"
        )
    _VENDOR_CLASS_CACHE[safe_name] = vendor_class
    return vendor_class


def load_vendor_data_module(vendor_name: str) -> Any:
    """Import the vendor's api.data module (same shape as broker.<name>.api.data)."""
    safe_name = _assert_valid_vendor_name(vendor_name)
    return importlib.import_module(f"vendors.{safe_name}.api.data")


def create_vendor_data_handler(vendor_name: str) -> BaseDataVendor:
    """Instantiate the active vendor using credentials from environment variables."""
    vendor_class = _load_vendor_class(vendor_name)
    api_key = os.getenv("DATA_VENDOR_API_KEY", "") or ""
    api_secret = os.getenv("DATA_VENDOR_API_SECRET", "") or ""
    return vendor_class(api_key=api_key, api_secret=api_secret)
