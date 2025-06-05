import importlib
import logging
from typing import Dict, Type, Optional

from .base_adapter import BaseBrokerWebSocketAdapter

logger = logging.getLogger(__name__)

# Registry of all supported broker adapters
BROKER_ADAPTERS: Dict[str, Type[BaseBrokerWebSocketAdapter]] = {}

def register_adapter(broker_name: str, adapter_class: Type[BaseBrokerWebSocketAdapter]) -> None:
    """
    Register a broker adapter class for a specific broker
    
    Args:
        broker_name: Name of the broker
        adapter_class: Class that implements the BaseBrokerWebSocketAdapter interface
    """
    BROKER_ADAPTERS[broker_name.lower()] = adapter_class
    

def create_broker_adapter(broker_name: str) -> Optional[BaseBrokerWebSocketAdapter]:
    """
    Create an instance of the appropriate broker adapter
    
    Args:
        broker_name: Name of the broker (e.g., 'angel', 'zerodha')
        
    Returns:
        BaseBrokerWebSocketAdapter: An instance of the appropriate broker adapter
        
    Raises:
        ValueError: If the broker is not supported
    """
    broker_name = broker_name.lower()
    
    # Check if adapter is registered
    if broker_name in BROKER_ADAPTERS:
        logger.info(f"Creating adapter for broker: {broker_name}")
        return BROKER_ADAPTERS[broker_name]()
    
    # Try dynamic import if not registered
    try:
        # Try to import from broker-specific directory first
        module_name = f"broker.{broker_name}.streaming.{broker_name}_adapter"
        class_name = f"{broker_name.capitalize()}WebSocketAdapter"
        
        try:
            # Import the module
            module = importlib.import_module(module_name)
            
            # Get the adapter class
            adapter_class = getattr(module, class_name)
            
            # Register the adapter for future use
            register_adapter(broker_name, adapter_class)
            
            # Create and return an instance
            return adapter_class()
        except (ImportError, AttributeError) as e:
            logger.warning(f"Could not import from broker-specific path: {e}")
            
            # Try websocket_proxy directory as fallback
            module_name = f"websocket_proxy.{broker_name}_adapter"
            
            # Import the module
            module = importlib.import_module(module_name)
            
            # Get the adapter class
            adapter_class = getattr(module, class_name)
            
            # Register the adapter for future use
            register_adapter(broker_name, adapter_class)
            
            # Create and return an instance
            return adapter_class()
    
    except (ImportError, AttributeError) as e:
        logger.error(f"Failed to load adapter for broker {broker_name}: {e}")
        raise ValueError(f"Unsupported broker: {broker_name}. No adapter available.")
    
    return None
