import os
import pandas as pd
import requests
from io import StringIO
from sqlalchemy import create_engine, Column, Integer, String, Float, Sequence, Index
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from extensions import socketio
from utils.logging import get_logger
from database.auth_db import get_auth_token
from database.user_db import find_user_by_username

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
    logger.info("Performing Bulk Insert")
    data_dict = df.to_dict(orient='records')
    existing_tokens = {result.token for result in db_session.query(SymToken.token).all()}
    filtered_data_dict = [row for row in data_dict if row.get('token') and str(row['token']) not in existing_tokens]

    try:
        if filtered_data_dict:
            db_session.bulk_insert_mappings(SymToken, filtered_data_dict)
            db_session.commit()
            logger.info(f"Bulk insert completed successfully with {len(filtered_data_dict)} new records.")
        else:
            logger.info("No new records to insert.")
    except Exception as e:
        logger.error(f"Error during bulk insert: {e}")
        db_session.rollback()

def download_csv_mstock_data(auth_token):
    api_key = os.getenv('BROKER_API_KEY')
    url = 'https://api.mstock.trade/openapi/typea/instruments/scriptmaster'
    headers = {
        'X-Mirae-Version': '1',
        'Authorization': f'token {api_key}:{auth_token}',
    }
    response = requests.get(url, headers=headers, timeout=30)
    if response.status_code == 200:
        return response.text
    else:
        logger.error(f"Failed to download mstock master contract. Status code: {response.status_code}")
        return None

def process_mstock_csv(csv_data):
    df = pd.read_csv(StringIO(csv_data))
    df = df.rename(columns={
        'Exchange': 'exchange',
        'InstrumentType': 'instrumenttype',
        'LotSize': 'lotsize',
        'StrikePrice': 'strike',
        'Symbol': 'symbol',
        'Token': 'token',
        'InstrumentName': 'name',
        'TickSize': 'tick_size',
        'ExpiryDate': 'expiry'
    })
    df['brsymbol'] = df['symbol']
    df['brexchange'] = df['exchange']
    
    # Data type conversions and formatting
    df['strike'] = pd.to_numeric(df['strike'], errors='coerce').fillna(0)
    df['lotsize'] = pd.to_numeric(df['lotsize'], errors='coerce').fillna(0).astype(int)
    df['tick_size'] = pd.to_numeric(df['tick_size'], errors='coerce').fillna(0)
    
    return df

def master_contract_download():
    login_username = os.getenv('LOGIN_USERNAME')
    auth_token = get_auth_token(login_username)
    api_key = os.getenv('BROKER_API_KEY')
    logger.info("Downloading mstock Master Contract")
    try:
        csv_data = download_csv_mstock_data(api_key, auth_token)
        if csv_data:
            token_df = process_mstock_csv(csv_data)
            delete_symtoken_table()
            copy_from_dataframe(token_df)
            socketio.emit('master_contract_download', {'status': 'success', 'message': 'Successfully Downloaded'})
        else:
            socketio.emit('master_contract_download', {'status': 'error', 'message': 'Failed to download master contract'})
    except Exception as e:
        logger.error(f"Error in mstock master contract download: {str(e)}")
        socketio.emit('master_contract_download', {'status': 'error', 'message': str(e)})

def search_symbols(symbol, exchange):
    return SymToken.query.filter(SymToken.symbol.like(f'%{symbol}%'), SymToken.exchange == exchange).all()
