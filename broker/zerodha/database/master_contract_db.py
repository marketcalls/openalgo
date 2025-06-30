#database/master_contract_db.py

import os
import pandas as pd
import numpy as np
import gzip
import shutil
import json
import io
from utils.httpx_client import get_httpx_client


from sqlalchemy import create_engine, Column, Integer, String, Float , Sequence, Index
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from database.auth_db import get_auth_token
from extensions import socketio  # Import SocketIO
from utils.logging import get_logger

logger = get_logger(__name__)




DATABASE_URL = os.getenv('DATABASE_URL')  # Replace with your database path

engine = create_engine(DATABASE_URL)
db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()

class SymToken(Base):
    __tablename__ = 'symtoken'
    id = Column(Integer, Sequence('symtoken_id_seq'), primary_key=True)
    symbol = Column(String, nullable=False, index=True)  # Single column index
    brsymbol = Column(String, nullable=False, index=True)  # Single column index
    name = Column(String)
    exchange = Column(String, index=True)  # Include this column in a composite index
    brexchange = Column(String, index=True)  
    token = Column(String, index=True)  # Indexed for performance
    expiry = Column(String)
    strike = Column(Float)
    lotsize = Column(Integer)
    instrumenttype = Column(String)
    tick_size = Column(Float)

    # Define a composite index on symbol and exchange columns
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
    # Convert DataFrame to a list of dictionaries
    data_dict = df.to_dict(orient='records')

    # Retrieve existing tokens to filter them out from the insert
    existing_tokens = {result.token for result in db_session.query(SymToken.token).all()}

    # Filter out data_dict entries with tokens that already exist
    filtered_data_dict = [row for row in data_dict if row['token'] not in existing_tokens]

    # Insert in bulk the filtered records
    try:
        if filtered_data_dict:  # Proceed only if there's anything to insert
            db_session.bulk_insert_mappings(SymToken, filtered_data_dict)
            db_session.commit()
            logger.info(f"Bulk insert completed successfully with {len(filtered_data_dict)} new records.")
        else:
            logger.info("No new records to insert.")
    except Exception as e:
        logger.error(f"Error during bulk insert: {e}")
        db_session.rollback()


def download_csv_zerodha_data(output_path):
    """
    Downloads the CSV file from Zerodha using Auth Credentials, saves it to the specified path and convert.
    to pandas dataframe using shared httpx client with connection pooling.
    
    Args:
        output_path (str): Path where the CSV file will be saved
        
    Returns:
        pd.DataFrame: DataFrame containing the downloaded instrument data
    """
    try:
        login_username = os.getenv('LOGIN_USERNAME')
        AUTH_TOKEN = get_auth_token(login_username)
        
        # Get the shared httpx client with connection pooling
        client = get_httpx_client()
        
        headers = {
            'X-Kite-Version': '3',
            'Authorization': f'token {AUTH_TOKEN}'
        }
        
        # Make the GET request using the shared client
        response = client.get(
            'https://api.kite.trade/instruments',
            headers=headers  # Increased timeout for potentially large file
        )
        response.raise_for_status()  # Raises an exception for 4XX/5XX responses
        
        # Process the response directly as CSV
        csv_string = response.text
        df = pd.read_csv(io.StringIO(csv_string))
        
        # Save to output path if needed
        if output_path:
            df.to_csv(output_path, index=False)
            
        return df
        
    except Exception as e:
        error_message = str(e)
        try:
            if hasattr(e, 'response') and e.response is not None:
                error_detail = e.response.json()
                error_message = error_detail.get('message', str(e))
        except:
            pass
            
        logger.error(f"Error downloading Zerodha instruments: {error_message}")
        raise


def reformat_symbol(row):
    symbol = row['symbol']
    instrument_type = row['instrumenttype']
    
    if instrument_type == 'FUT':
        # For FUT, remove the spaces and append 'FUT' at the end
        parts = symbol.split(' ')
        if len(parts) == 5:  # Make sure the symbol has the correct format
            symbol = parts[0] + parts[2] + parts[3] + parts[4] + parts[1]
    elif instrument_type in ['CE', 'PE']:
        # For CE/PE, rearrange the parts and remove spaces
        parts = symbol.split(' ')
        if len(parts) == 6:  # Make sure the symbol has the correct format
            symbol = parts[0] + parts[3] + parts[4] + parts[5] + parts[1] + parts[2]
    else:
        symbol = symbol  # No change for other instrument types

    return symbol



def process_zerodha_csv(path):
    """
    Processes the Zerodha CSV file to fit the existing database schema and performs exchange name mapping.
    """
    logger.info("Processing Zerodha CSV Data")
    df = pd.read_csv(path)

    # Map exchange names
    exchange_map = {
        "NSE": "NSE",
        "NFO": "NFO",
        "CDS": "CDS",
        "NSE_INDEX": "NSE_INDEX",
        "BSE_INDEX": "BSE_INDEX",
        "BSE": "BSE",
        "BFO": "BFO",
        "BCD": "BCD",
        "MCX": "MCX"

    }
    
    df['exchange'] = df['exchange'].map(exchange_map)

    # Update exchange names based on the instrument type
    df.loc[(df['segment'] == 'INDICES') & (df['exchange'] == 'NSE'), 'exchange'] = 'NSE_INDEX'
    df.loc[(df['segment'] == 'INDICES') & (df['exchange'] == 'BSE'), 'exchange'] = 'BSE_INDEX'
    df.loc[(df['segment'] == 'INDICES') & (df['exchange'] == 'MCX'), 'exchange'] = 'MCX_INDEX'
    df.loc[(df['segment'] == 'INDICES') & (df['exchange'] == 'CDS'), 'exchange'] = 'CDS_INDEX'

    # Format expiry date
    df['expiry'] = pd.to_datetime(df['expiry']).dt.strftime('%d-%b-%y').str.upper()

    # Combine instrument_token and exchange_token
    df['token'] = df['instrument_token'].astype(str) + '::::' + df['exchange_token'].astype(str)

    # Select and rename columns
    df = df[['token', 'tradingsymbol', 'name', 'expiry', 
             'strike', 'lot_size', 'instrument_type', 'exchange', 
             'tick_size']].rename(columns={
        'tradingsymbol': 'symbol',
        'name': 'name',
        'expiry': 'expiry',
        'strike': 'strike',
        'lot_size': 'lotsize',
        'instrument_type': 'instrumenttype',
        'exchange': 'exchange',
        'tick_size': 'tick_size'
    })

    df['brsymbol'] = df['symbol']
    df['symbol'] = df.apply(reformat_symbol, axis=1)
    df['brexchange'] = df['exchange']

    # Fill NaN values in the 'expiry' column with an empty string
    df['expiry'] = df['expiry'].fillna('')
    
    # Futures Symbol Update 
    df.loc[(df['instrumenttype'] == 'FUT'), 'symbol'] = df['name'] + df['expiry'].str.replace('-', '', regex=False) + 'FUT'
    
    # Options Symbol Update 

    def format_strike(strike):
        # Convert the string to a float, then to an integer, and finally back to a string.
        return str(int(float(strike)))


    df.loc[(df['instrumenttype'] == 'CE'), 'symbol'] = df['name'] + df['expiry'].str.replace('-', '', regex=False) + df['strike'].apply(format_strike) + df['instrumenttype']
    df.loc[(df['instrumenttype'] == 'PE'), 'symbol'] = df['name'] + df['expiry'].str.replace('-', '', regex=False) + df['strike'].apply(format_strike) + df['instrumenttype']

    df['symbol'] = df['symbol'].replace({
    'NIFTY 50': 'NIFTY',
    'NIFTY NEXT 50': 'NIFTYNXT50',
    'NIFTY FIN SERVICE': 'FINNIFTY',
    'NIFTY BANK': 'BANKNIFTY',
    'NIFTY MID SELECT': 'MIDCPNIFTY',
    'INDIA VIX': 'INDIAVIX',
    'SNSX50': 'SENSEX50'
    })

    return df
    

def delete_zerodha_temp_data(output_path):
    try:
        # Check if the file exists
        if os.path.exists(output_path):
            # Delete the file
            os.remove(output_path)
            logger.info(f"The temporary file {output_path} has been deleted.")
        else:
            logger.info(f"The temporary file {output_path} does not exist.")
    except Exception as e:
        logger.error(f"An error occurred while deleting the file: {e}")


def master_contract_download():
    logger.info("Downloading Master Contract")
    

    output_path = 'tmp/zerodha.csv'
    try:
        download_csv_zerodha_data(output_path)
        token_df = process_zerodha_csv(output_path)
        delete_zerodha_temp_data(output_path)
        #token_df['token'] = pd.to_numeric(token_df['token'], errors='coerce').fillna(-1).astype(int)
        
        #token_df = token_df.drop_duplicates(subset='symbol', keep='first')

        delete_symtoken_table()  # Consider the implications of this action
        copy_from_dataframe(token_df)
                
        return socketio.emit('master_contract_download', {'status': 'success', 'message': 'Successfully Downloaded'})

    
    except Exception as e:
        logger.info(f"{str(e)}")
        return socketio.emit('master_contract_download', {'status': 'error', 'message': str(e)})


def search_symbols(symbol, exchange):
    return SymToken.query.filter(SymToken.symbol.like(f'%{symbol}%'), SymToken.exchange == exchange).all()
