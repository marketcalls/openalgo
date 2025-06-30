#database/master_contract_db.py

import os
import pandas as pd
import gzip
import shutil
from datetime import datetime

# Import httpx and shared client
import httpx
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


def download_csv_5paisa_data(url, output_path):
    """
    Downloads a CSV file from the specified URL and saves it to the specified path using shared httpx client.
    Implements retry logic with increased timeout for reliability.
    
    Args:
        url (str): URL to download the CSV from
        output_path (str): Path where the downloaded file should be saved
    """
    max_retries = 3
    current_retry = 0
    chunk_size = 16384  # Increased chunk size for better performance
    
    # Create directory if it doesn't exist
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    while current_retry < max_retries:
        try:
            logger.info(f"Downloading CSV data (attempt {current_retry + 1}/{max_retries})")
            
            # Use a custom timeout for this specific request
            client = get_httpx_client()
            
            # Custom timeout for master contract download (2 minutes)
            timeout = httpx.Timeout(120.0)
            
            with client.stream('GET', url, timeout=timeout) as response:
                response.raise_for_status()
                
                total_size = int(response.headers.get('content-length', 0))
                bytes_downloaded = 0
                last_progress_report = 0
                
                with open(output_path, 'wb') as f:
                    for chunk in response.iter_bytes(chunk_size=chunk_size):
                        if chunk:  # Filter out keep-alive chunks
                            f.write(chunk)
                            bytes_downloaded += len(chunk)
                            
                            # Report progress every 10%
                            if total_size > 0:
                                progress = int((bytes_downloaded / total_size) * 100)
                                if progress >= last_progress_report + 10:
                                    logger.info(f"Download progress: {progress}% ({bytes_downloaded} / {total_size} bytes)")
                                    last_progress_report = progress
                    
            logger.info("Download complete")
            return  # Successfully downloaded, exit the function
            
        except httpx.TimeoutException as e:
            current_retry += 1
            logger.info(f"Timeout downloading master contract (attempt {current_retry}/{max_retries}): {e}")
            if current_retry >= max_retries:
                logger.info("Maximum retries reached for master contract download.")
                raise Exception(f"Failed to download master contract after {max_retries} attempts: {str(e)}")
        except Exception as e:
            logger.error(f"Failed to download data: {e}")
            if 'time' in str(e).lower() and current_retry < max_retries:
                # If it's a timeout-related error, retry
                current_retry += 1
                logger.info(f"Retrying download (attempt {current_retry}/{max_retries})")
            else:
                # For other errors, raise immediately
                raise


def process_5paisa_csv(path):
    """
    Processes the 5Paisa CSV file to fit the existing database schema.
    Args:
    path (str): The file path of the downloaded JSON data.

    Returns:
    DataFrame: The processed DataFrame ready to be inserted into the database.
    """
    # Read JSON data into a DataFrame
    df = pd.read_csv(path)
    exchange_mapping = {
    ('N', 'C'): 'NSE',
    ('B', 'C'): 'BSE',
    ('N', 'D'): 'NFO',
    ('B', 'D'): 'BFO',
    ('N', 'U'): 'CDS',
    ('B', 'U'): 'BCD',
    ('M', 'D'): 'MCX'
    # Add other mappings as needed
    }



    # Function to map Exch and ExchType to exchange names with additional conditions
    def map_exchange(row):
        if row['Exch'] == 'N' and row['ExchType'] == 'C':
            return 'NSE_INDEX' if row['ScripCode'] > 999900 else 'NSE'
        elif row['Exch'] == 'B' and row['ExchType'] == 'C':
            return 'BSE_INDEX' if row['ScripCode'] > 999900 else 'BSE'
        else:
            return exchange_mapping.get((row['Exch'], row['ExchType']), 'Unknown')

    # Apply the function to create the exchange column
    df['exchange'] = df.apply(map_exchange, axis=1)

    # Filter the DataFrame for Series 'EQ', 'BE', 'XX'
    filtered_df = df[df['Series'].isin(['EQ', 'BE', 'XX', '  '])].copy()

    filtered_df.loc[filtered_df['Series'].isin(['XX', '  ']), 'Series'] = df['ScripType']

    #filtered_df.loc[filtered_df['Series'] == 'XX', 'Series'] = 'FUT'

    # Convert 'Expiry' to datetime format
    filtered_df['Expiry'] = pd.to_datetime(filtered_df['Expiry'])

    # Format 'Expiry' to 'DD-MMM-YY'
    filtered_df['Expiry'] = filtered_df['Expiry'].dt.strftime('%d-%b-%y').str.upper()

    # Function to format StrikeRate
    def format_strike(strike):
        # Convert strike to string first
        strike_str = str(strike)
        # Check if the string ends with '.0' and remove it
        if strike_str.endswith('.0'):
            # Remove the last two characters '.0'
            return strike_str[:-2]
        elif strike_str.endswith('.00'):
            # Remove the last three characters '.00'
            return strike_str[:-3]
        # Return the original string if it does not end with '.0'
        return strike_str

    # Apply the function to the StrikeRate column
    filtered_df['StrikeRate'] = filtered_df['StrikeRate'].apply(format_strike)



    # Convert the Expiry column to strings and strip '-'
    filtered_df['Expiry1'] = filtered_df['Expiry'].astype(str).str.replace('-', '')

    # Apply the conditions
    def create_trading_symbol(row):
        if row['Series'] in ['BE', 'EQ']:
            return row['SymbolRoot']
        elif row['Series'] == 'XX':
            return row['SymbolRoot'] + row['Expiry1'] + 'FUT'
        elif row['Series'] == 'CE':
            return row['SymbolRoot'] + row['Expiry1'] + str(row['StrikeRate']) + 'CE'
        elif row['Series'] == 'PE':
            return row['SymbolRoot'] + row['Expiry1'] + str(row['StrikeRate']) + 'PE'
        return row['SymbolRoot'] 

    filtered_df['TradingSymbol'] = filtered_df.apply(create_trading_symbol, axis=1)

    # Create a new DataFrame in OpenAlgo format
    new_df = pd.DataFrame()
    new_df['symbol'] = filtered_df['TradingSymbol'] 
    new_df['brsymbol'] = filtered_df['Name'].str.upper().str.rstrip()
    new_df['name'] = filtered_df['FullName'] 
    new_df['exchange'] = filtered_df['exchange'] 
    new_df['brexchange'] = filtered_df['exchange'] 
    new_df['token'] = filtered_df['ScripCode'] 
    new_df['expiry'] = filtered_df['Expiry'] 
    new_df['strike'] = filtered_df['StrikeRate'] 
    new_df['lotsize'] = filtered_df['LotSize'] 
    new_df['instrumenttype'] = filtered_df['Series'] 
    new_df['tick_size'] = filtered_df['TickSize'] 
    # Common Index Symbol Formats

    new_df['symbol'] = new_df['symbol'].replace({
    'Nifty Next 50': 'NIFTYNXT50',
    'MIDCPNifty': 'MIDCPNIFTY',
    'India VIX' : 'INDIAVIX',
    'BSE BANKEX' : 'BANKEX',
    'BSE SENSEX 50': 'SENSEX50'
    })
    # Return the processed DataFrame

    return new_df

def delete_5paisa_temp_data(output_path):
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
    logger.info("Starting Master Contract Download Process")
    url = 'https://openapi.5paisa.com/VendorsAPI/Service1.svc/ScripMaster/segment/all'
    output_path = 'tmp/5paisa.csv'
    
    # Ensure tmp directory exists
    os.makedirs('tmp', exist_ok=True)
    
    try:
        logger.info(f"Initiating download from {url}")
        download_csv_5paisa_data(url, output_path)
        
        logger.info("CSV downloaded, processing data...")
        token_df = process_5paisa_csv(output_path)
        logger.info(f"Processed {len(token_df)} symbols")
        
        # Clean up temporary files
        delete_5paisa_temp_data(output_path)
        
        # Clear existing data and insert new data
        logger.info("Updating database with new symbols...")
        delete_symtoken_table()  # Clear existing table
        copy_from_dataframe(token_df)
        
        logger.info("Master contract download completed successfully")
        # Notify UI through Socket.IO
        return socketio.emit('master_contract_download', {'status': 'success', 'message': 'Successfully Downloaded Master Contract'})
    
    except Exception as e:
        error_message = str(e)
        logger.error(f"Error during master contract download: {error_message}")
        
        # Check if it's a timeout error and provide more helpful message
        if 'timeout' in error_message.lower() or 'timed out' in error_message.lower():
            error_message = f"Download timed out. The FivePaisa server is not responding within the allowed time. Error details: {error_message}"
        
        # Notify UI through Socket.IO
        return socketio.emit('master_contract_download', {
            'status': 'error', 
            'message': error_message
        })



def search_symbols(symbol, exchange):
    return SymToken.query.filter(SymToken.symbol.like(f'%{symbol}%'), SymToken.exchange == exchange).all()
