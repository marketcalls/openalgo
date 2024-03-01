# database/tv_search.py

from database.master_contract_db import SymToken
#from database.db import db_session

def search_symbols(symbol):
    # The "%" is a wildcard for the LIKE SQL operator
    return SymToken.query.filter(SymToken.symbol == symbol).all()
