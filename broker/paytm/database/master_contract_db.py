#database/master_contract_db.py

import os
import pandas as pd
import numpy as np
from utils.httpx_client import get_httpx_client

from sqlalchemy import create_engine, Column, Integer, String, Float , Sequence, Index
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.ext.declarative import declarative_base
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
    logger.debug("Initializing Master Contract DB")
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
            # Pre-validate records before insertion
            invalid_records = []
            valid_records = []
            
            for record in filtered_data_dict:
                # Allow indices ("I") even if symbol is missing
                if record.get('instrumenttype') == 'I':
                    valid_records.append(record)
                else:
                    # Check if symbol exists and is not empty/null
                    symbol = record.get('symbol')
                    if not symbol or pd.isna(symbol) or str(symbol).strip() == '':
                        invalid_records.append(record)
                        logger.error(f"Schema validation failed for record: {record}")
                        logger.debug("Symbol is missing, empty, or null")
                    else:
                        valid_records.append(record)
            
            if valid_records:
                db_session.bulk_insert_mappings(SymToken, valid_records)
                db_session.commit()
                logger.info(f"Bulk insert completed successfully with {len(valid_records)} new records.")
                
            if invalid_records:
                logger.warning(f"{len(invalid_records)} records failed schema validation and were skipped.")
        else:
            logger.info("No new records to insert.")
    except Exception as e:
        logger.exception(f"Error during bulk insert: {e}")
        if hasattr(e, '__cause__'):
            logger.error(f"Caused by: {e.__cause__}")
        db_session.rollback()




def download_csv_paytm_data(output_path):

    logger.info("Downloading Master Contract CSV Files")
    # Create output directory if it doesn't exist
    if not os.path.exists(output_path):
        os.makedirs(output_path)
        logger.debug(f"Created directory: {output_path}")

    # URLs of the CSV files to be downloaded
    csv_urls = {
        "master": "https://developer.paytmmoney.com/data/v1/scrips/security_master.csv"
    }
    
    # Create a list to hold the paths of the downloaded files
    downloaded_files = []

    # Iterate through the URLs and download the CSV files
    for key, url in csv_urls.items():
        try:
            # Send GET request using httpx client
            client = get_httpx_client()
            response = client.get(url)
            response.raise_for_status() # Raise an exception for bad status codes
            # Construct the full output path for the file
            file_path = os.path.join(output_path, f"{key}.csv")
            # Write the content to the file
            with open(file_path, 'wb') as file:
                file.write(response.content)
            downloaded_files.append(file_path)
            logger.info(f"Successfully downloaded {key} from {url}")
        except Exception as e:
            logger.exception(f"Failed to download {key} from {url}. Error: {e}")
    

def reformat_symbol(row):
    # Use trading symbol as base instead of name
    symbol = row['symbol']
    instrument_type = row['instrument_type']
    expiry = row['expiry_date'].replace('-', '').upper()
    
    # For equity instruments, use the symbol as is
    if instrument_type in ['ES']:
        return symbol

    # For index instruments, use name without spaces and set it as both symbol and brsymbol
    elif instrument_type in ['I']:
        symbol = "".join(row['name'].split())
        row['symbol'] = symbol  # Set the symbol in the row
        return symbol
    
    # For futures
    elif instrument_type in ['FUTSTK', 'FUTIDX']:
        # Remove any spaces and standardize format
        parts = row['name'].split(' ')
        base_symbol = parts[0].strip()
        return f"{base_symbol}{expiry}FUT"
    
    # For options
    elif instrument_type in ['OPTIDX', 'OPTSTK']:
        parts = row['name'].split(' ')
        base_symbol = parts[0].strip()
        
        # Get strike price from the row directly instead of parsing from symbol
        strike = str(int(float(row['strike_price'])))
        
        # Determine option type (CE/PE)
        option_type = 'CE' if 'CALL' in row['name'].upper() else 'PE' if 'PUT' in row['name'].upper() else parts[-1]
        
        return f"{base_symbol}{expiry}{strike}{option_type}"
    
    # For any other instrument type, return symbol as is
    else:
        return symbol

# Define the function to apply conditions
def assign_values(row):
    #Paytm Exchange Mappings are simply NSE and BSE. No other complications
    # Handle equity segment
    if row['exchange'] == 'NSE' and (row['instrument_type'] == 'ETF' or row['instrument_type'] == 'ES'):
        return 'NSE', 'NSE', 'EQ'
    elif row['exchange'] == 'BSE' and (row['instrument_type'] == 'ETF' or row['instrument_type'] == 'ES'):
        return 'BSE', 'BSE', 'EQ'
    
    # Handle indices
    elif row['exchange'] == 'NSE' and row['instrument_type'] == 'I':
        return 'NSE_INDEX', 'NSE', 'INDEX'
    elif row['exchange'] == 'BSE' and row['instrument_type'] == 'I':
        return 'BSE_INDEX', 'BSE', 'INDEX'
    
    # Handle futures
    elif row['exchange'] == 'NSE' and row['instrument_type'] in ['FUTIDX', 'FUTSTK']:
        return 'NFO', 'NSE', 'FUT'
    elif row['exchange'] == 'BSE' and row['instrument_type'] in ['FUTIDX', 'FUTSTK']:
        return 'BFO', 'BSE', 'FUT'
    
    # Handle options
    elif row['exchange'] == 'NSE' and row['instrument_type'] in ['OPTIDX', 'OPTSTK']:
        return 'NFO', 'NSE', 'OPT'
    elif row['exchange'] == 'BSE' and row['instrument_type'] in ['OPTIDX', 'OPTSTK']:
        return 'BFO', 'BSE', 'OPT'
    
    # Handle unknown cases
    else:
        return 'Unknown', 'Unknown', 'Unknown'

def process_paytm_csv(path):
    """Processes the Paytm CSV file to fit the existing database schema and performs exchange name mapping."""
    logger.info("Processing Paytm Scrip Master CSV Data")
    file_path = os.path.join(path, "master.csv")

    df = pd.read_csv(file_path, low_memory=False)
    df.columns = df.columns.str.strip()

    # Attempt to convert all date entries to datetime objects, errors are coerced to NaT
    df['expiry_date'] = pd.to_datetime(df['expiry_date'], errors='coerce')

    # Format all non-NaT datetime objects to the desired format "DD-MMM-YY"
    df['expiry_date'] = df['expiry_date'].dt.strftime('%d-%b-%y')

    # Handle NaT values by replacing them with '-1'
    df['expiry_date'] = df['expiry_date'].fillna('-1')

    # Assigning headers to the DataFrame
    df['token'] = df['security_id']
    df['name'] = df['name']
    df['expiry'] = df['expiry_date'].str.upper()
    df['strike'] = df['strike_price']
    df['lotsize'] = df['lot_size']
    df['tick_size'] = df['tick_size']
    df['brsymbol'] = df['symbol']
    
    # For indices, set brsymbol to be the same as the formatted symbol
    indices_mask = df['instrument_type'] == 'I'
    df.loc[indices_mask, 'brsymbol'] = df.loc[indices_mask, 'name'].apply(lambda x: "".join(x.split()))

    # Apply the function to get exchange mappings
    df[['exchange', 'brexchange', 'instrumenttype']] = df.apply(assign_values, axis=1, result_type='expand')

    # Generate symbol field and ensure it's not null
    df['symbol'] = df.apply(reformat_symbol, axis=1)
    df['symbol'] = df['symbol'].fillna(df['brsymbol'])  # Use brsymbol as fallback if reformat_symbol returns None

    # Remove rows where symbol is still null
    df = df.dropna(subset=['symbol'])

    # List of columns to remove
    columns_to_remove = [
        "security_id", "series", "lot_size",
        "segment", "upper_limit", "lower_limit", 
        "expiry_date", "strike_price", "freeze_quantity"
    ]

    # Removing the specified columns
    token_df = df.drop(columns=columns_to_remove)

    # Common Index Symbol Formats

    token_df['symbol'] = token_df['symbol'].replace({
    'NIFTYNEXT50': 'NIFTYNXT50',
    'NIFTYMIDCAP150': 'MIDCPNIFTY',
    'SNSX50': 'SENSEX50'
    })

    return token_df
    
def delete_paytm_temp_data(output_path):
    # Check each file in the directory
    for filename in os.listdir(output_path):
        # Construct the full file path
        file_path = os.path.join(output_path, filename)
        # If the file is a CSV, delete it
        if filename.endswith(".csv") and os.path.isfile(file_path):
            os.remove(file_path)
            logger.info(f"Deleted {file_path}")
    

def master_contract_download():
    logger.info("Downloading Master Contract")
    

    output_path = 'tmp'
    try:
        download_csv_paytm_data(output_path)
        delete_symtoken_table()
        token_df = process_paytm_csv(output_path)
        copy_from_dataframe(token_df)
        delete_paytm_temp_data(output_path)
        #token_df['token'] = pd.to_numeric(token_df['token'], errors='coerce').fillna(-1).astype(int)
        
        #token_df = token_df.drop_duplicates(subset='symbol', keep='first')
        
        return socketio.emit('master_contract_download', {'status': 'success', 'message': 'Successfully Downloaded'})

    
    except Exception as e:
        logger.exception(f"An error occurred during master contract download: {e}")
        return socketio.emit('master_contract_download', {'status': 'error', 'message': str(e)})



def search_symbols(symbol, exchange):
    return SymToken.query.filter(SymToken.symbol.like(f'%{symbol}%'), SymToken.exchange == exchange).all()
