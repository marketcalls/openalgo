# sandbox/__init__.py
"""
Sandbox Mode - API Analyzer Environment

This package implements OpenAlgo's Sandbox Mode (API Analyzer) which provides
a realistic simulated trading environment for testing trading strategies without
executing real trades through a broker.

Key Features:
- ₹10,000,000 (1 Crore) starting sandbox capital
- Auto reset every Sunday at midnight IST (configurable)
- Real market data integration
- Realistic order execution simulation
- Position and holdings management
- Leverage-based margin calculations
- Auto square-off for MIS positions
- T+1 settlement for CNC holdings
"""

__version__ = '1.0.0'
