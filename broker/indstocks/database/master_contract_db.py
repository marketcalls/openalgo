#database/master_contract_db.py

import os
import pandas as pd
import numpy as np
import requests
import gzip
import shutil
import http.client
import json
import pandas as pd
import gzip
import io


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
        logger.exception(f"Error during bulk insert: {e}")
        db_session.rollback()




def download_csv_indstocks_data(output_path):
    logger.info("Downloading Master Contract CSV Files from IndStocks")
    
    # Get the access token from auth_db using login username
    login_username = os.getenv('LOGIN_USERNAME')
    auth_token = get_auth_token(login_username)
    if not auth_token:
        logger.error("No authentication token available")
        return
    
    # IndStocks API endpoints for different segments
    segments = ['equity', 'fno', 'index']
    
    headers = {
        'Authorization': auth_token
    }
    
    # Download CSV files for each segment
    for segment in segments:
        url = f"https://api.indstocks.com/market/instruments?source={segment}"
        
        try:
            # Send GET request with authorization header
            response = requests.get(url, headers=headers, timeout=30)
            
            # Check if the request was successful
            if response.status_code == 200:
                # Construct the full output path for the file
                file_path = f"{output_path}/{segment}.csv"
                # Write the content to the file
                with open(file_path, 'wb') as file:
                    file.write(response.content)
                logger.info(f"Successfully downloaded {segment} instruments")
            else:
                logger.error(f"Failed to download {segment} from {url}. Status code: {response.status_code}")
        except Exception as e:
            logger.error(f"Error downloading {segment} instruments: {e}")
    

def reformat_symbol(row):
    symbol = row['CUSTOM_SYMBOL']
    instrument_type = row['instrumenttype']
    instrument_name = row['INSTRUMENT_NAME']
    expiry = row['expiry'].replace('-', '')
    
    if instrument_name == 'EQUITY':
        symbol = row['TRADING_SYMBOL']
    elif instrument_name == 'INDEX':
        symbol = row['TRADING_SYMBOL']
    elif instrument_type == 'FUT':
        # For FUT, format according to OpenAlgo standards
        base_symbol = row['SYMBOL_NAME']
        symbol = f"{base_symbol}{expiry}FUT"
    elif instrument_type in ['CE', 'PE']:
        # For options, format with strike price
        base_symbol = row['SYMBOL_NAME']
        strike = str(int(row['STRIKE_PRICE'])) if pd.notna(row['STRIKE_PRICE']) else ''
        symbol = f"{base_symbol}{expiry}{strike}{instrument_type}"
    
    return symbol

# Define the function to apply conditions for IndStocks
def assign_values(row):
    exch = row['EXCH']
    segment = row['SEGMENT']
    instrument_name = row['INSTRUMENT_NAME']
    option_type = row.get('OPTION_TYPE', '')
    
    if exch == 'NSE' and segment == 'E':
        return 'NSE', 'NSE_EQ', 'EQ'
    elif exch == 'BSE' and segment == 'E':
        return 'BSE', 'BSE_EQ', 'EQ'
    elif exch == 'NSE' and instrument_name == 'INDEX':
        return 'NSE_INDEX', 'IDX_I', 'INDEX'
    elif exch == 'BSE' and instrument_name == 'INDEX':
        return 'BSE_INDEX', 'IDX_I', 'INDEX'
    elif exch == 'NSE' and segment == 'FNO':
        if instrument_name in ['FUTCUR', 'OPTCUR']:
            return 'CDS', 'NSE_CURRENCY', option_type if option_type else 'FUT'
        else:
            return 'NFO', 'NSE_FNO', option_type if option_type else 'FUT'
    elif exch == 'BSE' and segment == 'FNO':
        if instrument_name in ['FUTCUR', 'OPTCUR']:
            return 'BCD', 'BSE_CURRENCY', option_type if option_type else 'FUT'
        else:
            return 'BFO', 'BSE_FNO', option_type if option_type else 'FUT'
    elif exch == 'MCX':
        return 'MCX', 'MCX_COMM', option_type if option_type else 'FUT'
    else:
        return 'Unknown', 'Unknown', 'Unknown'

def process_indstocks_csv(path):
    """
    Processes the IndStocks CSV files to fit the existing database schema and performs exchange name mapping.
    """
    logger.info("Processing IndStocks Instrument Master CSV Data")
    
    # List to hold all dataframes
    all_dfs = []
    
    # Process each segment CSV file
    for segment in ['equity', 'fno', 'index']:
        file_path = f'{path}/{segment}.csv'
        
        if not os.path.exists(file_path):
            logger.warning(f"File {file_path} not found, skipping...")
            continue
            
        df = pd.read_csv(file_path, low_memory=False)
        df.columns = df.columns.str.strip()
        
        # Convert expiry date
        if 'EXPIRY_DATE' in df.columns:
            df['EXPIRY_DATE'] = pd.to_datetime(df['EXPIRY_DATE'], errors='coerce')
            df['EXPIRY_DATE'] = df['EXPIRY_DATE'].dt.strftime('%d-%b-%y')
            df['EXPIRY_DATE'] = df['EXPIRY_DATE'].fillna('-1')
        else:
            df['EXPIRY_DATE'] = '-1'
        
        # Map IndStocks columns to our schema
        df['token'] = df['SECURITY_ID'].astype(str)
        df['name'] = df.get('SYMBOL_NAME', df.get('TRADING_SYMBOL', ''))
        df['expiry'] = df['EXPIRY_DATE'].str.upper()
        df['strike'] = df.get('STRIKE_PRICE', 0)
        df['lotsize'] = df.get('LOT_UNITS', 1)
        df['tick_size'] = df.get('TICK_SIZE', 0.05)
        df['brsymbol'] = df['TRADING_SYMBOL']
        
        # Apply exchange mapping
        df[['exchange', 'brexchange', 'instrumenttype']] = df.apply(assign_values, 
                                                                    axis=1, result_type='expand')
        
        # Generate OpenAlgo formatted symbol
        df['symbol'] = df.apply(reformat_symbol, axis=1)
        df['symbol'] = df['symbol'].replace('INDIA VIX', 'INDIAVIX')
        
        # Keep only required columns
        required_columns = ['symbol', 'brsymbol', 'name', 'exchange', 'brexchange', 
                           'token', 'expiry', 'strike', 'lotsize', 'instrumenttype', 'tick_size']
        
        # Filter to keep only required columns that exist
        existing_columns = [col for col in required_columns if col in df.columns]
        token_df = df[existing_columns]
        
        all_dfs.append(token_df)
    
    # Combine all dataframes
    if all_dfs:
        combined_df = pd.concat(all_dfs, ignore_index=True)
        return combined_df
    else:
        logger.error("No data files were processed successfully")
        return pd.DataFrame()


    

def delete_indstocks_temp_data(output_path):
    # Check each file in the directory
    for filename in os.listdir(output_path):
        # Construct the full file path
        file_path = os.path.join(output_path, filename)
        # If the file is a CSV, delete it
        if filename.endswith(".csv") and os.path.isfile(file_path):
            os.remove(file_path)
            logger.info(f"Deleted {file_path}")
    

def master_contract_download():
    logger.info("Downloading Master Contract from IndStocks")
    
    output_path = 'tmp'
    
    # Create output directory if it doesn't exist
    if not os.path.exists(output_path):
        os.makedirs(output_path)
        
    try:
        download_csv_indstocks_data(output_path)
        delete_symtoken_table()
        token_df = process_indstocks_csv(output_path)
        
        if not token_df.empty:
            copy_from_dataframe(token_df)
            delete_indstocks_temp_data(output_path)
            return socketio.emit('master_contract_download', {'status': 'success', 'message': 'Successfully Downloaded IndStocks Instruments'})
        else:
            return socketio.emit('master_contract_download', {'status': 'error', 'message': 'No data downloaded from IndStocks'})
    
    except Exception as e:
        logger.exception(f"Error during master contract download: {e}")
        return socketio.emit('master_contract_download', {'status': 'error', 'message': str(e)})



def search_symbols(symbol, exchange):
    return SymToken.query.filter(SymToken.symbol.like(f'%{symbol}%'), SymToken.exchange == exchange).all()
