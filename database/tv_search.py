# database/tv_search.py

from database.symbol import SymToken


def search_symbols(symbol, exchange):
    """Look up symbols by exact symbol-exchange match.

    Performs an exact-match query against the ``SymToken`` table
    and returns all rows where both ``symbol`` and ``exchange``
    match the provided values.

    Args:
        symbol: The symbol string to match exactly.
        exchange: The exchange code to match exactly (e.g. ``'NSE'``, ``'NFO'``).

    Returns:
        A list of ``SymToken`` ORM instances matching the query.
    """
    return SymToken.query.filter(SymToken.symbol == symbol, SymToken.exchange == exchange).all()
