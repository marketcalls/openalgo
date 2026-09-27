"""
Motilal Oswal WebSocket streaming module for OpenAlgo.

This module provides WebSocket streaming functionality for Motilal Oswal broker,
integrating with OpenAlgo's WebSocket proxy infrastructure.
"""

from .motilal_adapter import MotilalWebSocketAdapter
from .motilal_mapping import MotilalCapabilityRegistry, MotilalExchangeMapper

__all__ = ["MotilalWebSocketAdapter", "MotilalExchangeMapper", "MotilalCapabilityRegistry"]

# NOTE: motilal_order_adapter is deliberately NOT imported here. Order-update
# adapters are lazily imported by services/order_update_service.py, and
# importing it at package level would drag websocket_proxy into every
# `broker.motilal.streaming` import (the two packages import each other).
