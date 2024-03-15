# database/tv_search.py

from database.master_contract_db import SymToken
#from database.db import db_session

def search_symbols(symbol,exchange):
    return SymToken.query.filter(SymToken.symbol == symbol,SymToken.exch_seg == exchange).all()
