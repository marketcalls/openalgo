"""
deltaexchange_demo_adapter.py
Alias module so broker_factory.py can find the Delta Exchange Demo adapter under
the expected name: broker.deltaexchange_demo.streaming.deltaexchange_demo_adapter

The factory uses `{broker_name.capitalize()}WebSocketAdapter` as the class name,
which resolves to `Deltaexchange_demoWebSocketAdapter`.
"""

from broker.deltaexchange_demo.streaming.delta_adapter import DeltaWebSocketAdapter

# Alias to the name that broker_factory.py expects
Deltaexchange_demoWebSocketAdapter = DeltaWebSocketAdapter

__all__ = ["Deltaexchange_demoWebSocketAdapter"]
