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
import time


from sqlalchemy import create_engine, Column, Integer, String, Float , Sequence, Index, text
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from database.auth_db import get_auth_token
from extensions import socketio  # Import SocketIO
from utils.logging import get_logger

logger = get_logger(__name__)

DATABASE_URL = os.getenv('DATABASE_URL')  # Replace with your database path

# Create engine with optimized settings for SQLite concurrency
engine = create_engine(
    DATABASE_URL,
    pool_size=20,
    max_overflow=50,
    pool_timeout=30,
    pool_recycle=3600,
    connect_args={
        'timeout': 30,
        'check_same_thread': False
    }
)

# Enable WAL mode for better concurrent access
try:
    with engine.connect() as conn:
        conn.execute(text("PRAGMA journal_mode=WAL"))
        conn.execute(text("PRAGMA synchronous=NORMAL"))
        conn.execute(text("PRAGMA temp_store=memory"))
        conn.execute(text("PRAGMA mmap_size=268435456"))  # 256MB
        conn.commit()
except Exception as e:
    logger.warning(f"Could not set SQLite pragmas for master_contract_db: {e}")

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

    # Insert in smaller chunks to minimize database lock time
    chunk_size = 500  # Reduced chunk size for shorter lock duration
    total_inserted = 0
    
    try:
        if filtered_data_dict:  # Proceed only if there's anything to insert
            logger.info(f"Starting bulk insert of {len(filtered_data_dict)} records in chunks of {chunk_size}")
            
            # Process data in chunks
            for i in range(0, len(filtered_data_dict), chunk_size):
                chunk = filtered_data_dict[i:i + chunk_size]
                
                # Use a separate transaction for each chunk with retry logic
                try:
                    # Insert chunk
                    db_session.bulk_insert_mappings(SymToken, chunk)
                    db_session.commit()  # Commit each chunk immediately
                    
                    total_inserted += len(chunk)
                    
                    # Log progress every 20 chunks (10,000 records)
                    if (i // chunk_size + 1) % 20 == 0:
                        logger.info(f"Processed {total_inserted} records so far...")
                    
                except Exception as chunk_error:
                    logger.warning(f"Error inserting chunk {i//chunk_size + 1}, retrying: {chunk_error}")
                    db_session.rollback()
                    
                    # Retry once for this chunk
                    try:
                        time.sleep(0.1)  # Brief pause before retry
                        db_session.bulk_insert_mappings(SymToken, chunk)
                        db_session.commit()
                        total_inserted += len(chunk)
                    except Exception as retry_error:
                        logger.error(f"Failed to insert chunk {i//chunk_size + 1} after retry: {retry_error}")
                        db_session.rollback()
                        # Continue with next chunk instead of failing completely
                        continue
                
                # Small delay to allow other operations
                time.sleep(0.005)  # 5ms delay between chunks (reduced from 10ms)
            
            logger.info(f"Bulk insert completed successfully with {total_inserted} new records.")
        else:
            logger.info("No new records to insert.")
    except Exception as e:
        logger.exception(f"Error during bulk insert: {e}")
        db_session.rollback()

def download_csv_indmoney_data(output_path):
    logger.info("Downloading Master Contract CSV Files from Indmoney")
    
    # Get the access token for Indmoney broker from the database
    # Since Indmoney might have multiple users, we need to get the first valid one
    try:
        from database.auth_db import Auth, db_session
        auth_obj = Auth.query.filter_by(broker='indmoney', is_revoked=False).first()
        if auth_obj:
            from database.auth_db import decrypt_token
            auth_token = decrypt_token(auth_obj.auth)
        else:
            auth_token = None
    except Exception as e:
        logger.error(f"Error getting auth token from database: {e}")
        auth_token = None
    
    if not auth_token:
        logger.error("No authentication token available for Indmoney broker")
        return
    
    # Indmoney API endpoints for different segments
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

def reformat_symbol(row, file_segment=None):
    """
    Reformat symbols according to OpenAlgo standards based on Indmoney data structure
    """
    instrument_name = row['INSTRUMENT_NAME']
    option_type = row.get('OPTION_TYPE', '')
    symbol_name = row.get('SYMBOL_NAME', '')
    trading_symbol = row.get('TRADING_SYMBOL', '')
    expiry_date = row.get('EXPIRY_DATE', '')
    strike_price = row.get('STRIKE_PRICE', 0)
    
    # Format expiry date for OpenAlgo format (DDMMMYY)
    if expiry_date and expiry_date != '-1':
        expiry_formatted = expiry_date.replace('-', '').upper()
    else:
        expiry_formatted = ''
    
    # Format symbol based on instrument type
    if instrument_name == 'EQUITY':
        return trading_symbol
    elif instrument_name == 'INDEX' or file_segment == 'index':
        # For index symbols, use the SEGMENT column value directly
        if file_segment == 'index':
            segment_value = row.get('SEGMENT', '')
            if segment_value:
                return segment_value
        
        # Fallback to available fields
        if symbol_name:
            return symbol_name
        elif trading_symbol:
            return trading_symbol
        else:
            return row.get('name', '')
    elif instrument_name in ['FUTSTK', 'FUTIDX'] or (instrument_name.startswith('FUT') and not option_type):
        # Futures - Format: [Base Symbol][Expiration Date]FUT
        # Examples: POONAWALLA28AUG25FUT, MANAPPURAM31JUL25FUT
        # Extract base symbol from trading_symbol (everything before first hyphen)
        base_symbol = trading_symbol.split('-')[0] if '-' in trading_symbol else trading_symbol
        return f"{base_symbol}{expiry_formatted}FUT"
    elif instrument_name in ['OPTSTK', 'OPTIDX'] or option_type in ['CE', 'PE']:
        # Options - Format: [Base Symbol][Expiration Date][Strike Price][Option Type]
        # Examples: NIFTY28MAR2420800CE, VEDL25APR24292.5CE, USDINR19APR2482CE
        # Extract base symbol from trading_symbol (everything before first hyphen)
        base_symbol = trading_symbol.split('-')[0] if '-' in trading_symbol else trading_symbol
        
        # Format strike price properly - preserve decimals if needed
        if pd.notna(strike_price) and strike_price > 0:
            # If strike price is a whole number, format as integer
            if strike_price == int(strike_price):
                strike = str(int(strike_price))
            else:
                # Preserve decimal places, remove trailing zeros
                strike = f"{strike_price:g}"
        else:
            strike = ''
            
        opt_type = option_type if option_type else ''
        return f"{base_symbol}{expiry_formatted}{strike}{opt_type}"
    else:
        # Default to trading symbol
        return trading_symbol

def assign_values(row, file_segment=None):
    """
    Assign exchange and instrument type values based on Indmoney data structure
    """
    exch = row['EXCH']
    segment = row['SEGMENT']
    instrument_name = row['INSTRUMENT_NAME']
    option_type = row.get('OPTION_TYPE', '')
    
    # If instrument name starts with 'FUT', set option type to 'FUT'
    if instrument_name.startswith('FUT'):
        option_type = 'FUT'
    
    # Handle Indices first (prioritize over segment-based identification)
    # Check for INDEX instrument name or if processing index.csv file
    if exch == 'NSE' and (instrument_name == 'INDEX' or file_segment == 'index'):
        return 'NSE_INDEX', 'NSE', 'INDEX'
    
    elif exch == 'BSE' and (instrument_name == 'INDEX' or file_segment == 'index'):
        return 'BSE_INDEX', 'BSE', 'INDEX'
    
    # Handle NSE Equity
    elif exch == 'NSE' and segment == 'E':
        return 'NSE', 'NSE', 'EQ'
    
    # Handle BSE Equity
    elif exch == 'BSE' and segment == 'E':
        return 'BSE', 'BSE', 'EQ'
    
    # Handle NSE D segment (Derivatives)
    elif exch == 'NSE' and segment == 'D':
        return 'NFO', 'NSE', option_type if option_type else 'FUT'
    
    # Handle BSE D segment (Derivatives)
    elif exch == 'BSE' and segment == 'D':
        return 'BFO', 'BSE', option_type if option_type else 'FUT'
    
    # Handle NSE F&O segment
    elif exch == 'NSE' and segment == 'FNO':
        return 'NFO', 'NSE', option_type if option_type else 'FUT'
    
    # Handle BSE F&O segment
    elif exch == 'BSE' and segment == 'FNO':
        return 'BFO', 'BSE', option_type if option_type else 'FUT'
    
    # Default case
    else:
        return 'Unknown', 'Unknown', 'Unknown'

def process_indmoney_csv(path):
    """
    Processes the Indmoney CSV files to fit the existing database schema.
    Based on the official Indmoney API documentation CSV structure.
    """
    logger.info("Processing Indmoney Instrument Master CSV Data")
    
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
        
        # Handle missing columns with defaults
        required_columns = ['EXCH', 'SEGMENT', 'SECURITY_ID', 'INSTRUMENT_NAME', 'EXPIRY_CODE', 
                           'TRADING_SYMBOL', 'LOT_UNITS', 'CUSTOM_SYMBOL', 'EXPIRY_DATE', 
                           'STRIKE_PRICE', 'OPTION_TYPE', 'TICK_SIZE', 'EXPIRY_FLAG', 
                           'SEM_EXCH_INSTRUMENT_TYPE', 'SERIES', 'SYMBOL_NAME']
        
        # Add missing columns with default values
        for col in required_columns:
            if col not in df.columns:
                if col == 'OPTION_TYPE':
                    df[col] = ''
                elif col in ['STRIKE_PRICE', 'TICK_SIZE']:
                    df[col] = 0.0
                elif col in ['LOT_UNITS', 'EXPIRY_CODE']:
                    df[col] = 1
                else:
                    df[col] = ''
        
        # Convert expiry date to standard format
        if 'EXPIRY_DATE' in df.columns:
            df['EXPIRY_DATE'] = pd.to_datetime(df['EXPIRY_DATE'], errors='coerce')
            df['EXPIRY_DATE'] = df['EXPIRY_DATE'].dt.strftime('%d-%b-%y')
            df['EXPIRY_DATE'] = df['EXPIRY_DATE'].fillna('-1')
        else:
            df['EXPIRY_DATE'] = '-1'
        
        # Map Indmoney columns to our database schema
        df['token'] = df['SECURITY_ID'].astype(str)
        df['name'] = df['SYMBOL_NAME'].fillna(df['TRADING_SYMBOL'])
        df['expiry'] = df['EXPIRY_DATE'].str.upper()
        df['strike'] = pd.to_numeric(df['STRIKE_PRICE'], errors='coerce').fillna(0.0)
        df['lotsize'] = pd.to_numeric(df['LOT_UNITS'], errors='coerce').fillna(1).astype(int)
        df['tick_size'] = pd.to_numeric(df['TICK_SIZE'], errors='coerce').fillna(0.05)
        # Set brsymbol - use SEGMENT for index records, TRADING_SYMBOL for others
        if segment == 'index':
            df['brsymbol'] = df['SEGMENT']
        else:
            df['brsymbol'] = df['TRADING_SYMBOL']
        
        # Apply exchange and instrument type mapping
        df[['exchange', 'brexchange', 'instrumenttype']] = df.apply(lambda row: assign_values(row, segment), 
                                                                    axis=1, result_type='expand')
        
        # Generate OpenAlgo formatted symbol
        df['symbol'] = df.apply(lambda row: reformat_symbol(row, segment), axis=1)
        
        # Handle special cases
        df['symbol'] = df['symbol'].replace({
        'NIFTY 50': 'NIFTY',
        'Nifty Next 50': 'NIFTYNXT50',
        'Nifty Financial': 'FINNIFTY',
        'BANK NIFTY': 'BANKNIFTY',
        'Nifty Midcap Sel': 'MIDCPNIFTY',
        'India VIX': 'INDIAVIX',
        'S&P BSE SENSEX 50': 'SENSEX50'
        })

        # Keep only required columns for the database
        db_columns = ['symbol', 'brsymbol', 'name', 'exchange', 'brexchange', 
                     'token', 'expiry', 'strike', 'lotsize', 'instrumenttype', 'tick_size']
        
        # Filter to keep only required columns that exist
        existing_columns = [col for col in db_columns if col in df.columns]
        token_df = df[existing_columns]
        
        # Remove rows with empty or invalid tokens
        token_df = token_df[token_df['token'].notna() & (token_df['token'] != '')]
        
        all_dfs.append(token_df)
    
    # Combine all dataframes
    if all_dfs:
        combined_df = pd.concat(all_dfs, ignore_index=True)
        # Remove duplicates based on token
        combined_df = combined_df.drop_duplicates(subset=['token'], keep='first')
        return combined_df
    else:
        logger.error("No data files were processed successfully")
        return pd.DataFrame()

def delete_indmoney_temp_data(output_path):
    """
    Delete temporary CSV files after processing
    """
    # Check each file in the directory
    for filename in os.listdir(output_path):
        # Construct the full file path
        file_path = os.path.join(output_path, filename)
        # If the file is a CSV, delete it
        if filename.endswith(".csv") and os.path.isfile(file_path):
            os.remove(file_path)
            logger.info(f"Deleted {file_path}")

def master_contract_download():
    """
    Main function to download and process Indmoney master contract data
    """
    logger.info("Downloading Master Contract from Indmoney")
    
    output_path = 'tmp'
    
    # Create output directory if it doesn't exist
    if not os.path.exists(output_path):
        os.makedirs(output_path)
        
    try:
        download_csv_indmoney_data(output_path)
        delete_symtoken_table()
        token_df = process_indmoney_csv(output_path)
        
        if not token_df.empty:
            copy_from_dataframe(token_df)
            delete_indmoney_temp_data(output_path)
            return socketio.emit('master_contract_download', {'status': 'success', 'message': 'Successfully Downloaded Indmoney Instruments'})
        else:
            return socketio.emit('master_contract_download', {'status': 'error', 'message': 'No data downloaded from Indmoney'})
    
    except Exception as e:
        logger.exception(f"Error during master contract download: {e}")
        return socketio.emit('master_contract_download', {'status': 'error', 'message': str(e)})

def search_symbols(symbol, exchange):
    """
    Search for symbols in the database
    """
    return SymToken.query.filter(SymToken.symbol.like(f'%{symbol}%'), SymToken.exchange == exchange).all()
