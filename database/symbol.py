import os
from sqlalchemy import create_engine, Column, Integer, String, Float, Sequence, Index, or_, and_
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.pool import NullPool
from typing import List
from utils.logging import get_logger

logger = get_logger(__name__)

DATABASE_URL = os.getenv('DATABASE_URL')
# Conditionally create engine based on DB type
if DATABASE_URL and 'sqlite' in DATABASE_URL:
    # SQLite: Use NullPool to prevent connection pool exhaustion
    engine = create_engine(
        DATABASE_URL,
        poolclass=NullPool,
        connect_args={'check_same_thread': False}
    )
else:
    # For other databases like PostgreSQL, use connection pooling
    engine = create_engine(
        DATABASE_URL,
        pool_size=50,
        max_overflow=100,
        pool_timeout=10
    )
db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()

class SymToken(Base):
    __tablename__ = 'symtoken'
    id = Column(Integer, Sequence('symtoken_id_seq'), primary_key=True)
    symbol = Column(String, nullable=False, index=True)
    brsymbol = Column(String, nullable=False, index=True)
    name = Column(String)
    exchange = Column(String, index=True)
    brexchange = Column(String, index=True)
    token = Column(String, index=True)
    expiry = Column(String)
    strike = Column(Float)
    lotsize = Column(Integer)
    instrumenttype = Column(String)
    tick_size = Column(Float)

    # Composite indices for improved search performance
    __table_args__ = (
        Index('idx_symbol_exchange', 'symbol', 'exchange'),
        Index('idx_symbol_name', 'symbol', 'name'),
        Index('idx_brsymbol_exchange', 'brsymbol', 'exchange'),
    )

def enhanced_search_symbols(query: str, exchange: str = None) -> List[SymToken]:
    """
    Enhanced search function that searches across multiple fields
    and supports partial matching with multiple terms
    
    Args:
        query (str): Search query string
        exchange (str, optional): Exchange to filter by
        
    Returns:
        List[SymToken]: List of matching SymToken objects
    """
    try:
        # Split the query into terms and clean them
        terms = [term.strip().upper() for term in query.split() if term.strip()]
        
        # Base query
        base_query = SymToken.query
        
        # If exchange is specified, filter by it
        if exchange:
            base_query = base_query.filter(SymToken.exchange == exchange)
        
        # Create conditions for each term
        all_conditions = []
        for term in terms:
            # Number detection for more accurate strike price and token searches
            try:
                num_term = float(term)
                term_conditions = or_(
                    SymToken.symbol.ilike(f'%{term}%'),
                    SymToken.brsymbol.ilike(f'%{term}%'),
                    SymToken.name.ilike(f'%{term}%'),
                    SymToken.token.ilike(f'%{term}%'),
                    SymToken.strike == num_term
                )
            except ValueError:
                term_conditions = or_(
                    SymToken.symbol.ilike(f'%{term}%'),
                    SymToken.brsymbol.ilike(f'%{term}%'),
                    SymToken.name.ilike(f'%{term}%'),
                    SymToken.token.ilike(f'%{term}%')
                )
            all_conditions.append(term_conditions)
        
        # Combine all conditions with AND
        if all_conditions:
            final_query = base_query.filter(and_(*all_conditions))
        else:
            final_query = base_query

        # Execute query - no limit to show all matching results
        results = final_query.all()
        return results
        
    except Exception as e:
        logger.error(f"Error in enhanced search: {str(e)}")
        return []

def fno_search_symbols_db(
    query: str = None,
    exchange: str = None,
    expiry: str = None,
    instrumenttype: str = None,  # "FUT", "CE", or "PE"
    strike_min: float = None,
    strike_max: float = None,
    underlying: str = None,
    limit: int = 500
) -> List[dict]:
    """
    FNO-specific search function using direct database queries.
    This is the fallback when cache is not available.

    Can search with just filters (no query required) - useful for:
    - "Show all NIFTY futures" (underlying=NIFTY, instrumenttype=FUT)
    - "Show all weekly expiry options" (expiry=26-DEC-24)

    Args:
        query (str, optional): Search query string (optional if filters are provided)
        exchange (str, optional): Exchange to filter by (NFO, BFO, MCX, CDS)
        expiry (str, optional): Expiry date filter (e.g., "26-DEC-24")
        instrumenttype (str, optional): "FUT" for futures, "CE" for calls, "PE" for puts
        strike_min (float, optional): Minimum strike price
        strike_max (float, optional): Maximum strike price
        underlying (str, optional): Underlying symbol name (e.g., "NIFTY")
        limit (int, optional): Maximum results to return (default 500)

    Returns:
        List[dict]: List of matching symbol dictionaries
    """
    try:
        # Base query
        base_query = SymToken.query

        # Filter by exchange
        if exchange:
            base_query = base_query.filter(SymToken.exchange == exchange)

        # Filter by underlying name
        if underlying:
            base_query = base_query.filter(SymToken.name.ilike(underlying.strip().upper()))

        # Filter by expiry date
        if expiry:
            base_query = base_query.filter(SymToken.expiry == expiry.strip())

        # Filter by instrument type (FUT, CE, PE) - based on symbol suffix
        if instrumenttype:
            inst_type = instrumenttype.strip().upper()
            if inst_type == "FUT":
                # Symbol ends with FUT (e.g., NIFTY26DEC24FUT)
                base_query = base_query.filter(SymToken.symbol.ilike('%FUT'))
            elif inst_type == "CE":
                # Symbol ends with CE (e.g., NIFTY26DEC2424000CE)
                base_query = base_query.filter(SymToken.symbol.ilike('%CE'))
            elif inst_type == "PE":
                # Symbol ends with PE (e.g., NIFTY26DEC2424000PE)
                base_query = base_query.filter(SymToken.symbol.ilike('%PE'))

        # Filter by strike price range (for options)
        if strike_min is not None:
            base_query = base_query.filter(SymToken.strike >= strike_min)
        if strike_max is not None:
            base_query = base_query.filter(SymToken.strike <= strike_max)

        # Create conditions for each search term (if query provided)
        if query:
            terms = [term.strip().upper() for term in query.split() if term.strip()]
            all_conditions = []
            for term in terms:
                try:
                    num_term = float(term)
                    term_conditions = or_(
                        SymToken.symbol.ilike(f'%{term}%'),
                        SymToken.brsymbol.ilike(f'%{term}%'),
                        SymToken.name.ilike(f'%{term}%'),
                        SymToken.token.ilike(f'%{term}%'),
                        SymToken.strike == num_term
                    )
                except ValueError:
                    term_conditions = or_(
                        SymToken.symbol.ilike(f'%{term}%'),
                        SymToken.brsymbol.ilike(f'%{term}%'),
                        SymToken.name.ilike(f'%{term}%'),
                        SymToken.token.ilike(f'%{term}%')
                    )
                all_conditions.append(term_conditions)

            # Combine all conditions with AND
            if all_conditions:
                base_query = base_query.filter(and_(*all_conditions))

        # Execute query (fetch more for sorting, then limit)
        results = base_query.all()

        # Import freeze qty function
        from database.qty_freeze_db import get_freeze_qty_for_option

        # Convert to dictionaries
        results_dicts = [{
            'symbol': r.symbol,
            'brsymbol': r.brsymbol,
            'name': r.name,
            'exchange': r.exchange,
            'brexchange': r.brexchange,
            'token': r.token,
            'expiry': r.expiry,
            'strike': r.strike,
            'lotsize': r.lotsize,
            'instrumenttype': r.instrumenttype,
            'tick_size': r.tick_size,
            'freeze_qty': get_freeze_qty_for_option(r.symbol, r.exchange)
        } for r in results]

        # Smart sorting: prioritize exact underlying matches, then alphabetical
        primary_term = None
        if query:
            terms = [t.strip().upper() for t in query.split() if t.strip()]
            primary_term = terms[0] if terms else None

        def sort_key(r):
            name = r['name'] or ''
            symbol = r['symbol'] or ''
            # Priority 1: Exact match on name/underlying
            name_exact = 0 if (primary_term and name.upper() == primary_term) else 1
            # Priority 2: Name starts with search term
            name_starts = 0 if (primary_term and name.upper().startswith(primary_term)) else 1
            # Priority 3: Symbol starts with search term
            symbol_starts = 0 if (primary_term and symbol.upper().startswith(primary_term)) else 1
            # Priority 4: Alphabetical by symbol
            return (name_exact, name_starts, symbol_starts, symbol)

        results_dicts.sort(key=sort_key)
        return results_dicts[:limit] if limit else results_dicts

    except Exception as e:
        logger.error(f"Error in FNO search: {str(e)}")
        return []


def get_distinct_expiries(exchange: str = None, underlying: str = None) -> List[str]:
    """
    Get distinct expiry dates for FNO symbols.

    Args:
        exchange (str, optional): Exchange to filter by (NFO, BFO, MCX, CDS)
        underlying (str, optional): Underlying symbol name (e.g., "NIFTY")

    Returns:
        List[str]: List of distinct expiry dates sorted chronologically
    """
    try:
        from sqlalchemy import distinct
        from datetime import datetime

        query = db_session.query(distinct(SymToken.expiry))

        if exchange:
            query = query.filter(SymToken.exchange == exchange)

        if underlying:
            query = query.filter(SymToken.name.ilike(underlying.strip().upper()))

        # Only get non-null expiries
        query = query.filter(SymToken.expiry.isnot(None))
        query = query.filter(SymToken.expiry != '')

        results = query.all()
        expiries = [r[0] for r in results if r[0]]

        # Sort expiries chronologically
        def parse_expiry(exp_str):
            try:
                return datetime.strptime(exp_str, "%d-%b-%y")
            except ValueError:
                try:
                    return datetime.strptime(exp_str, "%d-%b-%Y")
                except ValueError:
                    return datetime.max

        expiries.sort(key=parse_expiry)
        return expiries

    except Exception as e:
        logger.error(f"Error fetching distinct expiries: {str(e)}")
        return []


def get_distinct_underlyings(exchange: str = None) -> List[str]:
    """
    Get distinct underlying names for FNO symbols.

    Args:
        exchange (str, optional): Exchange to filter by (NFO, BFO, MCX, CDS)

    Returns:
        List[str]: List of distinct underlying names sorted alphabetically
    """
    try:
        from sqlalchemy import distinct

        query = db_session.query(distinct(SymToken.name))

        if exchange:
            query = query.filter(SymToken.exchange == exchange)

        # Only get non-null names
        query = query.filter(SymToken.name.isnot(None))
        query = query.filter(SymToken.name != '')

        results = query.all()
        underlyings = sorted([r[0] for r in results if r[0]])
        return underlyings

    except Exception as e:
        logger.error(f"Error fetching distinct underlyings: {str(e)}")
        return []


def init_db():
    """Initialize the database"""
    from database.db_init_helper import init_db_with_logging
    init_db_with_logging(Base, engine, "Master Contract DB", logger)