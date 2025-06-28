import os
import pandas as pd
from sqlalchemy import create_engine, Column, Integer, String, Float, Sequence, Index
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from breeze_connect import BreezeConnect
from extensions import socketio
from utils.logging import get_logger

logger = get_logger(__name__)

DATABASE_URL = os.getenv('DATABASE_URL')
engine = create_engine(DATABASE_URL)
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
    __table_args__ = (Index('idx_symbol_exchange', 'symbol', 'exchange'),)

def init_db():
    logger.info("Initializing Master Contract DB")
    Base.metadata.create_all(bind=engine)

def delete_symtoken_table():
    logger.info("Deleting Symtoken Table")
    SymToken.query.delete()
    db_session.commit()

def copy_from_dataframe(df):
    logger.info("Performing Bulk Insert to symtoken")
    existing_tokens = {result.token for result in db_session.query(SymToken.token).all()}
    filtered_data = [row for row in df.to_dict(orient='records') if row['token'] not in existing_tokens]

    if filtered_data:
        db_session.bulk_insert_mappings(SymToken, filtered_data)
        db_session.commit()
        logger.info(f"Inserted {len(filtered_data)} new records.")
    else:
        logger.info("No new records to insert.")

def fetch_breeze_master_contract(api_key, api_secret, exchange="NSE") -> pd.DataFrame:
    logger.info(f"Fetching ICICI Breeze master contract for {exchange}")
    breeze = BreezeConnect(api_key=api_key)
    breeze.generate_session(api_secret=api_secret)
    df = breeze.get_master_contract(exchange)
    logger.info(f"Master contract fetched with {len(df)} rows")
    return df

def process_breeze_contract(df: pd.DataFrame) -> pd.DataFrame:
    logger.info("Processing Breeze contract data")
    df.columns = df.columns.str.strip()

    df['symbol'] = df['stock_code'].str.upper()
    df['brsymbol'] = df['stock_code']
    df['name'] = df['company_name']
    df['exchange'] = df['exchange_code']
    df['brexchange'] = df['exchange_code']
    df['token'] = df['stock_token']
    df['expiry'] = df.get('expiry_date', '').astype(str).fillna('')
    df['strike'] = pd.to_numeric(df.get('strike_price', 0), errors='coerce').fillna(0)
    df['lotsize'] = pd.to_numeric(df.get('lot_size', 1), errors='coerce').fillna(1)
    df['tick_size'] = 0.05
    df['instrumenttype'] = df['instrument_type']

    return df[[
        'symbol', 'brsymbol', 'name', 'exchange', 'brexchange',
        'token', 'expiry', 'strike', 'lotsize', 'tick_size', 'instrumenttype'
    ]]

def master_contract_download():
    logger.info("Starting Breeze master contract download")
    try:
        api_key = os.getenv('BROKER_API_KEY')
        api_secret = os.getenv('BROKER_API_SECRET')
        raw_df = fetch_breeze_master_contract(api_key, api_secret)
        delete_symtoken_table()
        token_df = process_breeze_contract(raw_df)
        copy_from_dataframe(token_df)

        return socketio.emit('master_contract_download', {
            'status': 'success',
            'message': 'ICICI Master Contract Synced'
        })

    except Exception as e:
        logger.exception(f"Error during Breeze contract load: {e}")
        return socketio.emit('master_contract_download', {
            'status': 'error',
            'message': str(e)
        })

def search_symbols(symbol, exchange):
    return SymToken.query.filter(SymToken.symbol.like(f'%{symbol}%'),
                                 SymToken.exchange == exchange).all()
