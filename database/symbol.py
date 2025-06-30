import os
from sqlalchemy import create_engine, Column, Integer, String, Float, Sequence, Index, or_, and_
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from typing import List
from utils.logging import get_logger

logger = get_logger(__name__)

DATABASE_URL = os.getenv('DATABASE_URL')
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
        
        # Execute query with a reasonable limit
        results = final_query.limit(50).all()
        return results
        
    except Exception as e:
        logger.error(f"Error in enhanced search: {str(e)}")
        return []

def init_db():
    """Initialize the database"""
    logger.info("Initializing Master Contract DB")
    Base.metadata.create_all(bind=engine)