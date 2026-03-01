# database/tv_search.py

from database.symbol import SymToken


def search_symbols(symbol, exchange):
    """Search for symbols matching an exact symbol-exchange pair.

    Used by TradingView integration to resolve symbol identifiers.

    Args:
        symbol: The OpenAlgo-format symbol string to search for.
        exchange: The exchange code (e.g. ``'NSE'``, ``'NFO'``).

    Returns:
        A list of ``SymToken`` ORM instances matching the query.
    """
    return SymToken.query.filter(SymToken.symbol == symbol, SymToken.exchange == exchange).all()
