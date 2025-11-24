"""
Motilal Oswal WebSocket streaming module for OpenAlgo.

This module provides WebSocket streaming functionality for Motilal Oswal broker,
integrating with OpenAlgo's WebSocket proxy infrastructure.
"""

from .motilal_adapter import MotilalWebSocketAdapter
from .motilal_mapping import MotilalExchangeMapper, MotilalCapabilityRegistry

__all__ = [
    'MotilalWebSocketAdapter',
    'MotilalExchangeMapper',
    'MotilalCapabilityRegistry'
]
