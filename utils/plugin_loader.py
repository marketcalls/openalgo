# utils/plugin_loader.py

import os
import importlib
from flask import current_app
from utils.logging import get_logger

logger = get_logger(__name__)

def load_broker_auth_functions(broker_directory='broker'):
    auth_functions = {}
    broker_path = os.path.join(current_app.root_path, broker_directory)
    # List all items in broker directory and filter out __pycache__ and non-directories
    broker_names = [d for d in os.listdir(broker_path)
                    if os.path.isdir(os.path.join(broker_path, d)) and d != '__pycache__']

    for broker_name in broker_names:
        try:
            # Construct module name and import the module
            module_name = f"{broker_directory}.{broker_name}.api.auth_api"
            auth_module = importlib.import_module(module_name)
            # Retrieve the authenticate_broker function
            auth_function = getattr(auth_module, 'authenticate_broker', None)
            if auth_function:
                auth_functions[f"{broker_name}_auth"] = auth_function
        except ImportError as e:
            logger.error(f"Failed to import broker plugin {broker_name}: {e}")
        except AttributeError as e:
            logger.error(f"Authentication function not found in broker plugin {broker_name}: {e}")

    return auth_functions
