"""
deltaexchange_adapter.py
Alias module so broker_factory.py can find the Delta Exchange adapter under
the expected name: broker.deltaexchange.streaming.deltaexchange_adapter

The factory uses `{broker_name.capitalize()}WebSocketAdapter` as the class name,
which resolves to `DeltaexchangeWebSocketAdapter`.
"""

from broker.deltaexchange.streaming.delta_adapter import DeltaWebSocketAdapter

# Alias to the name that broker_factory.py expects
DeltaexchangeWebSocketAdapter = DeltaWebSocketAdapter

__all__ = ["DeltaexchangeWebSocketAdapter"]
