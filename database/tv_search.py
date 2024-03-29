# database/tv_search.py

from database.master_contract_db import SymToken


def search_symbols(symbol,exchange):
    return SymToken.query.filter(SymToken.symbol == symbol,SymToken.exchange == exchange).all()
