import os
import pandas as pd
import requests
from io import StringIO
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, Float, Sequence, Index
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.ext.declarative import declarative_base

from extensions import socketio
from utils.logging import get_logger
from database.auth_db import get_auth_token

logger = get_logger(__name__)

# -------------------------------------------------------------------
# DATABASE SETUP
# -------------------------------------------------------------------
DATABASE_URL = os.getenv('DATABASE_URL')
engine = create_engine(DATABASE_URL)
db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()


# -------------------------------------------------------------------
# TABLE DEFINITION
# -------------------------------------------------------------------
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


# -------------------------------------------------------------------
# INIT / UTILS
# -------------------------------------------------------------------
def init_db():
    logger.info("Initializing MStock Master Contract DB")
    Base.metadata.create_all(bind=engine)


def delete_symtoken_table():
    logger.info("Deleting SymToken Table (MStock)")
    SymToken.query.delete()
    db_session.commit()


def copy_from_dataframe(df):
    """Bulk insert DataFrame records into the symtoken table."""
    logger.info("Performing Bulk Insert into SymToken Table")

    data_dict = df.to_dict(orient='records')
    existing_tokens = {result.token for result in db_session.query(SymToken.token).all()}

    filtered_data_dict = [
        row for row in data_dict if row.get('token') and str(row['token']) not in existing_tokens
    ]

    try:
        if filtered_data_dict:
            db_session.bulk_insert_mappings(SymToken, filtered_data_dict)
            db_session.commit()
            logger.info(f"Inserted {len(filtered_data_dict)} new records successfully.")
        else:
            logger.info("No new MStock records to insert.")
    except Exception as e:
        logger.error(f"Error during MStock bulk insert: {e}")
        db_session.rollback()


# -------------------------------------------------------------------
# MStock Master Contract Fetch
# -------------------------------------------------------------------
def download_mstock_csv(auth_token):
    """
    Download the MStock master contract CSV from the API.
    """
    api_key = os.getenv('BROKER_API_KEY')
    url = 'https://api.mstock.trade/openapi/typea/instruments/scriptmaster'

    headers = {
        'X-Mirae-Version': '1',
        'Authorization': f'token {api_key}:{auth_token}',
    }

    logger.info(f"Fetching MStock master contract from {url}")

    try:
        response = requests.get(url, headers=headers, timeout=60)
        logger.info(f"MStock master contract download status: {response.status_code}")

        if response.status_code != 200:
            logger.error(f"Failed to download MStock master contract: {response.status_code}")
            return None

        return response.text

    except Exception as e:
        logger.error(f"Error fetching MStock master contract: {e}")
        return None


# -------------------------------------------------------------------
# PROCESS CSV
# -------------------------------------------------------------------
def process_mstock_csv(csv_text):
    """
    Convert raw CSV text from MStock API to DataFrame in OpenAlgo schema.
    """
    try:
        df = pd.read_csv(StringIO(csv_text))
    except Exception as e:
        logger.error(f"Error reading MStock CSV: {e}")
        return pd.DataFrame()

    # Normalize column names
    df.columns = [col.strip().lower() for col in df.columns]

    expected_cols = {'instrument_token','exchange_token','tradingsymbol','name','last_price','expiry','strike','tick_size','lot_size','instrument_type','segment','exchange'    }

    if not expected_cols.issubset(df.columns):
        logger.error(f"Unexpected MStock CSV columns: {list(df.columns)}")
        return pd.DataFrame()

    # Map to OpenAlgo schema
    df['symbol'] = df['tradingsymbol'].astype(str)
    df['brsymbol'] = df['symbol']
    df['name'] = df['name'].astype(str)
    df['exchange'] = df['exchange'].astype(str)
    df['brexchange'] = df['exchange']
    df['token'] = df['instrument_token'].astype(str)
    df['expiry'] = df['expiry'].fillna('')
    df['strike'] = pd.to_numeric(df['strike'], errors='coerce').fillna(0)
    df['lotsize'] = pd.to_numeric(df['lot_size'], errors='coerce').fillna(1).astype(int)
    df['instrumenttype'] = df['instrument_type']
    df['tick_size'] = pd.to_numeric(df['tick_size'], errors='coerce').fillna(0.05)

    # Remove duplicates
    df = df.drop_duplicates(subset=['symbol', 'exchange'])

    # Keep only relevant columns
    final_cols = [
        'symbol', 'brsymbol', 'name', 'exchange', 'brexchange',
        'token', 'expiry', 'strike', 'lotsize', 'instrumenttype', 'tick_size'
    ]
    df = df[final_cols]

    logger.info(f"MStock Master Contract Processed: {len(df)} records ready")
    return df


# -------------------------------------------------------------------
# MASTER CONTRACT PIPELINE
# -------------------------------------------------------------------
def master_contract_download():
    """
    Main async download pipeline for MStock master contract.
    """
    try:
        login_username = os.getenv('LOGIN_USERNAME')
        auth_token = get_auth_token(login_username)

        safe_token = f"{auth_token[:6]}..." if auth_token else "None"
        logger.info(f"Downloading MStock Master Contract (token={safe_token})")

        csv_data = download_mstock_csv(auth_token)
        if not csv_data:
            logger.error("No data received from MStock API.")
            socketio.emit('master_contract_download', {
                'status': 'error',
                'message': 'Failed to download MStock Master Contract'
            })
            return

        token_df = process_mstock_csv(csv_data)

        if token_df is None or token_df.empty:
            socketio.emit('master_contract_download', {
                'status': 'error',
                'message': 'Empty or invalid master contract data'
            })
            return

        delete_symtoken_table()
        copy_from_dataframe(token_df)

        socketio.emit('master_contract_download', {
            'status': 'success',
            'message': 'MStock Master Contract downloaded and stored successfully'
        })

    except Exception as e:
        logger.error(f"Error during MStock master contract pipeline: {str(e)}")
        socketio.emit('master_contract_download', {
            'status': 'error',
            'message': str(e)
        })


# -------------------------------------------------------------------
# SEARCH SYMBOL
# -------------------------------------------------------------------
def search_symbols(symbol, exchange):
    """
    Search symbols in MStock Master Contract DB.
    """
    return SymToken.query.filter(
        SymToken.symbol.like(f"%{symbol}%"),
        SymToken.exchange == exchange
    ).all()
