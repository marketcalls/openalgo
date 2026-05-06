"""
Buyer Edge — Shared Utilities

Common helpers used across all buyer_edge_* service modules.
Centralised here to eliminate duplicate definitions in each service file.
"""

from utils.constants import CRYPTO_EXCHANGES, NSE_INDEX_SYMBOLS, BSE_INDEX_SYMBOLS



def get_buyer_edge_quote_exchange(base_symbol: str, exchange: str) -> str:
    """
    Resolve the correct exchange to use when fetching underlying spot/history.

    Rules (in priority order):
    1. Known NSE index symbols  → NSE_INDEX
    2. Known BSE index symbols  → BSE_INDEX
    3. NFO / BFO derivative exchange → NSE / BSE (equity segment for spot)
    4. Crypto exchanges         → pass through as-is
    5. Everything else          → exchange unchanged
    """
    if base_symbol in NSE_INDEX_SYMBOLS:
        return "NSE_INDEX"
    if base_symbol in BSE_INDEX_SYMBOLS:
        return "BSE_INDEX"
    if exchange.upper() in ("NFO", "BFO"):
        return "NSE" if exchange.upper() == "NFO" else "BSE"
    if exchange.upper() in CRYPTO_EXCHANGES:
        return exchange.upper()
    return exchange.upper()
