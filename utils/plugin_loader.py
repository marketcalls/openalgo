# utils/plugin_loader.py

import importlib
import json
import os

from flask import current_app

from utils.logging import get_logger

logger = get_logger(__name__)

# In-memory cache for broker capabilities (populated once at startup)
_broker_capabilities = {}


def load_broker_capabilities(broker_directory="broker"):
    """Read all broker/*/plugin.json files into memory at startup.

    Returns a dict keyed by broker name with capabilities from plugin.json.
    Only includes brokers that have a plugin.json with supported_exchanges.
    """
    global _broker_capabilities

    broker_path = os.path.join(current_app.root_path, broker_directory)
    capabilities = {}

    for broker_name in os.listdir(broker_path):
        broker_dir = os.path.join(broker_path, broker_name)
        if not os.path.isdir(broker_dir) or broker_name == "__pycache__":
            continue

        plugin_file = os.path.join(broker_dir, "plugin.json")
        if not os.path.exists(plugin_file):
            continue

        try:
            with open(plugin_file, "r") as f:
                plugin_data = json.load(f)

            # Only include brokers with the new capability fields
            if "supported_exchanges" in plugin_data:
                capabilities[broker_name] = {
                    "broker_name": broker_name,
                    "broker_type": plugin_data.get("broker_type", "IN_stock"),
                    "supported_exchanges": plugin_data.get("supported_exchanges", []),
                    "leverage_config": plugin_data.get("leverage_config", False),
                }
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Error reading plugin.json for {broker_name}: {e}")

    _broker_capabilities = capabilities
    logger.info(f"Loaded capabilities for {len(capabilities)} brokers")
    return capabilities


def get_broker_capabilities(broker_name):
    """Return cached capabilities for a specific broker.

    Returns None if broker not found or capabilities not loaded.
    """
    return _broker_capabilities.get(broker_name)


def load_broker_auth_functions(broker_directory="broker"):
    """Return a lazy dict that imports broker auth modules on first access.

    Instead of importing all 30 broker SDKs at startup (which takes ~3.5s),
    each broker's auth_api module is imported only when its auth function
    is actually requested (i.e. at login time).
    """
    broker_path = os.path.join(current_app.root_path, broker_directory)
    # Discover available broker names (directories only, skip __pycache__)
    broker_names = {
        d
        for d in os.listdir(broker_path)
        if os.path.isdir(os.path.join(broker_path, d)) and d != "__pycache__"
    }

    return _LazyBrokerAuthDict(broker_names, broker_directory)


class _LazyBrokerAuthDict(dict):
    """Dict-like object that lazily imports broker auth modules on access."""

    def __init__(self, broker_names, broker_directory):
        super().__init__()
        self._broker_names = broker_names
        self._broker_directory = broker_directory

    def get(self, key, default=None):
        if key not in self and key.endswith("_auth"):
            broker_name = key[: -len("_auth")]
            if broker_name in self._broker_names:
                self._load_broker(broker_name)
        return super().get(key, default)

    def __getitem__(self, key):
        if key not in self and key.endswith("_auth"):
            broker_name = key[: -len("_auth")]
            if broker_name in self._broker_names:
                self._load_broker(broker_name)
        return super().__getitem__(key)

    def __contains__(self, key):
        if not super().__contains__(key) and isinstance(key, str) and key.endswith("_auth"):
            broker_name = key[: -len("_auth")]
            if broker_name in self._broker_names:
                self._load_broker(broker_name)
        return super().__contains__(key)

    def _load_broker(self, broker_name):
        """Import a single broker's auth module on demand."""
        key = f"{broker_name}_auth"
        if super().__contains__(key):
            return
        try:
            module_name = f"{self._broker_directory}.{broker_name}.api.auth_api"
            auth_module = importlib.import_module(module_name)
            auth_function = getattr(auth_module, "authenticate_broker", None)
            if auth_function:
                self[key] = auth_function
            else:
                logger.error(f"authenticate_broker not found in {module_name}")
        except ImportError as e:
            logger.error(f"Failed to import broker plugin {broker_name}: {e}")
        except AttributeError as e:
            logger.error(f"Authentication function not found in broker plugin {broker_name}: {e}")
