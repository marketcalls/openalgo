"""
Nubra WebSocket streaming module for OpenAlgo.

This module provides WebSocket integration with Nubra's market data streaming API,
following the OpenAlgo WebSocket proxy architecture.
"""

from .nubra_adapter import NubraWebSocketAdapter

__all__ = ["NubraWebSocketAdapter"]
