# utils/symbol_utils.py
"""
Shared symbol classification helpers used across the sandbox and other modules.
"""

from utils.constants import CRYPTO_EXCHANGES, CRYPTO_QUOTE_CURRENCY, FNO_EXCHANGES


def get_underlying_quote_symbol(base_symbol: str, exchange: str) -> str:
    """Return the quote symbol for an underlying, appending the crypto quote currency if needed.

    For crypto exchanges: BTCUSDT (base_symbol + CRYPTO_QUOTE_CURRENCY)
    For all other exchanges: base_symbol unchanged
    """
    if exchange.upper() in CRYPTO_EXCHANGES:
        return base_symbol + CRYPTO_QUOTE_CURRENCY
    return base_symbol


def is_option(symbol: str, exchange: str) -> bool:
    """Check if symbol is an option based on exchange and canonical symbol suffix."""
    # All exchanges (including CRYPTO) use canonical CE/PE suffix convention.
    # CRYPTO canonical format: BTC28FEB2580000CE / BTC28FEB2580000PE (no dashes)
    if exchange in FNO_EXCHANGES:
        return symbol.endswith("CE") or symbol.endswith("PE")
    return False


def is_future(symbol: str, exchange: str) -> bool:
    """Check if symbol is a future (or perpetual) based on exchange and canonical symbol suffix."""
    # For CRYPTO: dated futures end with FUT; perpetuals (e.g. BTCUSDT) are also futures.
    # Both are non-options so: is_future ≡ not is_option for the CRYPTO exchange.
    if exchange in CRYPTO_EXCHANGES:
        return not (symbol.endswith("CE") or symbol.endswith("PE"))
    if exchange in FNO_EXCHANGES - CRYPTO_EXCHANGES:
        return symbol.endswith("FUT")
    return False
