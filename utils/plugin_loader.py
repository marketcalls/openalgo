# utils/plugin_loader.py

import importlib
import os

from flask import current_app

from utils.logging import get_logger

logger = get_logger(__name__)


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
