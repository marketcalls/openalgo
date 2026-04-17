"""Pluggable market-data vendors.

Vendors provide quote/ltp/depth/history APIs as an alternative to the connected
broker's data feed. A single vendor is active per deployment, selected via the
DATA_VENDOR environment variable. See utils/data_router.py for dispatch.
"""
