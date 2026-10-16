# utils/symbol_utils.py
"""
Shared symbol classification helpers used across the sandbox and other modules.
"""

from decimal import Decimal

from utils.constants import CRYPTO_EXCHANGES, FNO_EXCHANGES
from database.token_db_enhanced import fno_search_symbols
from utils.constants import INSTRUMENT_PERPFUT


def normalize_contract_value(raw) -> Decimal:
    """Validate a raw ``contract_value`` into a positive, finite ``Decimal`` multiplier.

    ``contract_value`` scales notional and P&L for instruments where one contract is a
    fraction of the underlying (e.g. 0.001 BTC or 0.01 ETH per crypto contract). Both the
    sandbox margin path (``fund_manager``) and the P&L path (``position_manager``) use this
    single normalizer so their ledgers cannot diverge. Returns ``Decimal('1.0')`` when the
    value is missing, non-finite, or non-positive, so a bad multiplier can never turn
    margin or P&L negative or zero.
    """
    try:
        if raw is not None:
            candidate = Decimal(str(raw))
            if candidate.is_finite() and candidate > 0:
                return candidate
    except (ArithmeticError, TypeError, ValueError):
        pass
    return Decimal("1.0")


def get_underlying_quote_symbol(base_symbol: str, exchange: str) -> str:
    """Return the quote symbol for an underlying, appending the crypto quote currency if needed.

    For crypto exchanges: canonical perpetual (e.g. BTCUSD.P)
    For all other exchanges: base_symbol unchanged
    """
    if exchange.upper() in CRYPTO_EXCHANGES:
        _perp = fno_search_symbols(
            underlying=base_symbol.upper(),
            exchange=exchange,
            instrumenttype=INSTRUMENT_PERPFUT,
            limit=1,
        )
        if _perp:
            return _perp[0]["symbol"]
        return f"{base_symbol.upper()}USD.P"
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
