import os
from sqlalchemy import create_engine, Column, Integer, String, Float
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from dotenv import load_dotenv

from cachetools import TTLCache
from functools import lru_cache

# Define a cache for the tokens with a max size and a 60-second TTL
token_cache = TTLCache(maxsize=1024, ttl=60)


load_dotenv()

DATABASE_URL = os.getenv('DATABASE_URL')  # Replace with your database path


engine = create_engine(
    DATABASE_URL,
    pool_size=50,  # Increase pool size
    max_overflow=100,  # Increase overflow
    pool_timeout=10  # Increase timeout to 10 seconds
)


db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()

# Assuming SymToken class definition is included here or imported
# For the sake of completeness, I'm defining it here based on previous context
class SymToken(Base):
    __tablename__ = 'symtoken'
    id = Column(Integer, primary_key=True)
    symbol = Column(String, nullable=False)
    exch_seg = Column(String, nullable=False)
    token = Column(Integer, nullable=False)
    # Add other fields as necessary

def get_token(symbol, exch_seg):
    cache_key = f"{symbol}-{exch_seg}"
    if cache_key in token_cache:
        print(f"Cache hit for {cache_key}.")
        return token_cache[cache_key]
    else:
        token = get_token_dbquery(symbol, exch_seg)
        if token is not None:
            token_cache[cache_key] = token
        return token

def get_token_dbquery(symbol, exch_seg):
    try:
        sym_token = db_session.query(SymToken).filter_by(symbol=symbol, exch_seg=exch_seg).first()
        if sym_token:
            print(f"The token for symbol '{symbol}' and exch_seg '{exch_seg}' is: {sym_token.token}")
            return sym_token.token
        else:
            print(f"No match found for symbol '{symbol}' and exch_seg '{exch_seg}'.")
            return None
    except Exception as e:
        print("Error while querying the database:", e)
        return None


def init_db():
    print("Initializing Token DB")
    Base.metadata.create_all(bind=engine)
