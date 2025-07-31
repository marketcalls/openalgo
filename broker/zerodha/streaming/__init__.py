"""
Zerodha WebSocket streaming module for OpenAlgo.

This module provides WebSocket integration with Zerodha's market data streaming API,
following the OpenAlgo WebSocket proxy architecture.
"""

from .zerodha_adapter import ZerodhaWebSocketAdapter

__all__ = ['ZerodhaWebSocketAdapter']
