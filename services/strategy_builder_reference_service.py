"""Resolve the canonical underlying reference used by Strategy Builder charts."""

from database.token_db_enhanced import fno_search_symbols
from services.option_symbol_service import NO_SPOT_EXCHANGES, resolve_underlying_quote
from utils.constants import CRYPTO_EXCHANGES, INSTRUMENT_PERPFUT

NSE_INDEX_SYMBOLS = {
    "NIFTY",
    "BANKNIFTY",
    "FINNIFTY",
    "MIDCPNIFTY",
    "NIFTYNXT50",
    "NIFTYIT",
    "NIFTYPHARMA",
    "NIFTYBANK",
}

BSE_INDEX_SYMBOLS = {"SENSEX", "BANKEX", "SENSEX50"}


def get_quote_exchange(base_symbol: str, underlying_exchange: str) -> str:
    """Resolve the exchange used for an underlying quote or history request."""
    upper = (underlying_exchange or "").upper()
    if base_symbol in NSE_INDEX_SYMBOLS:
        return "NSE_INDEX"
    if base_symbol in BSE_INDEX_SYMBOLS:
        return "BSE_INDEX"
    if upper == "NFO":
        return "NSE"
    if upper == "BFO":
        return "BSE"
    if upper in ("NSE_INDEX", "BSE_INDEX"):
        return upper
    return upper


def resolve_strategy_builder_reference(
    base_symbol: str,
    exchange: str,
    underlying_symbol: str | None = None,
    underlying_exchange: str | None = None,
) -> tuple[str, str] | None:
    """Return one symbol/exchange pair for both chart history and latest quote.

    A canonical pair supplied by the option-chain response takes precedence.
    Venues without a tradable spot fall back to their near-month future.
    """
    base = (base_symbol or "").strip().upper()
    venue = (exchange or "").strip().upper()
    if underlying_symbol and underlying_exchange:
        return underlying_symbol.strip().upper(), underlying_exchange.strip().upper()
    if venue in CRYPTO_EXCHANGES:
        perpetuals = fno_search_symbols(
            query=f"{base}USDFUT",
            exchange=venue,
            instrumenttype=INSTRUMENT_PERPFUT,
            limit=1,
        )
        if not perpetuals:
            return None
        perpetual = perpetuals[0]
        return perpetual["symbol"].strip().upper(), (
            perpetual.get("exchange") or venue
        ).strip().upper()
    if venue in NO_SPOT_EXCHANGES:
        return resolve_underlying_quote(base, venue)
    return base, get_quote_exchange(base, venue)
