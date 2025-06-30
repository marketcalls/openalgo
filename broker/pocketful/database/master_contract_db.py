#database/master_contract_db.py

import os
import pandas as pd
import numpy as np
import gzip
import shutil
import json
import gzip
import io
import zipfile
# Use httpx client for connection pooling
import httpx
from utils.httpx_client import get_httpx_client

from sqlalchemy import create_engine, Column, Integer, String, Float , Sequence, Index
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from database.auth_db import get_auth_token
from extensions import socketio  # Import SocketIO
from utils.logging import get_logger

logger = get_logger(__name__)




# Define the headers as provided
headers = [
    "Fytoken", "Symbol Details", "Exchange Instrument type", "Minimum lot size",
    "Tick size", "ISIN", "Trading Session", "Last update date", "Expiry date",
    "Symbol ticker", "Exchange", "Segment", "Scrip code", "Underlying symbol",
    "Underlying scrip code", "Strike price", "Option type", "Underlying FyToken",
    "Reserved column1", "Reserved column2", "Reserved column3"
]

# Data types for each header
data_types = {
    "Fytoken": str,
    "Symbol Details": str,
    "Exchange Instrument type": int,
    "Minimum lot size": int,
    "Tick size": float,
    "ISIN": str,
    "Trading Session": str,
    "Last update date": str,
    "Expiry date": str,
    "Symbol ticker": str,
    "Exchange": int,
    "Segment": int,
    "Scrip code": int,
    "Underlying symbol": str,
    "Underlying scrip code": pd.Int64Dtype(),
    "Strike price": float,
    "Option type": str,
    "Underlying FyToken": str,
    "Reserved column1": str,  
    "Reserved column2": str, 
    "Reserved column3": str, 
}

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




def download_csv_pocketful_data(output_path):
    """
    Downloads contract files from Pocketful API using httpx client with connection pooling
    and extracts the contents to the specified output path.
    """
    # Get the shared httpx client
    client = get_httpx_client()
    
    # API endpoint for contract download
    zip_url = "https://trade.pocketful.in/api/v1/contract/Compact?info=download&exchanges=NSE,NFO,BSE,BFO,MCX"
    downloaded_files = []

    try: 
        # Use the httpx client to make the request
        response = client.get(zip_url)
        response.raise_for_status()
        
        # Extract the ZIP file contents
        with zipfile.ZipFile(io.BytesIO(response.content)) as zip_file:
            zip_file.extractall(output_path)
            extracted_files = zip_file.namelist()
            downloaded_files.extend([os.path.join(output_path, name) for name in extracted_files])
            logger.info("Extraction successful!")
    except httpx.HTTPError as e:
        logger.error(f"Failed to download ZIP archive. HTTP Error: {e}")
    except zipfile.BadZipFile as e:
        logger.error(f"Failed to extract ZIP archive. Error: {e}")
    except Exception as e:
        logger.error(f"Unexpected error during contract download: {e}")

    return downloaded_files
    
def reformat_symbol_detail(s):
    parts = s.split()  # Split the string into parts
    # Reorder and format the parts to match the desired output
    # Assuming the format is consistent and always "Name DD Mon YY FUT"
    return f"{parts[0]}{parts[3]}{parts[2].upper()}{parts[1]}{parts[4]}"

def process_pocketful_nse_csv(path):
    """
    Processes the pocketful CSV file to fit the existing database schema and performs exchange name mapping.
    """
    logger.info("Processing pocketful NSE CSV Data")
    file_path = f'{path}/NSECompactScrip.csv'

    df = pd.read_csv(file_path)

    # Normalize column names to avoid key errors
    df.columns = df.columns.str.strip().str.lower()

    # Check expected column exists
    required_cols = ['instrument_name', 'trading_symbol', 'company_name', 'exchange',
                     'exchange_token', 'lot_size', 'tick_size']
    for col in required_cols:
        if col not in df.columns:
            raise KeyError(f"Missing expected column: {col}")

    filter_df = df[df['instrument_name'].isin(['EQ'])]

    token_df = pd.DataFrame()
    token_df['symbol'] = filter_df['trading_symbol'].str.replace('-EQ', '', regex=True)
    token_df['brsymbol'] = filter_df['trading_symbol']
    token_df['name'] = filter_df['company_name']
    token_df['exchange'] = filter_df['exchange']
    token_df['brexchange'] = filter_df['exchange']
    token_df['token'] = filter_df['exchange_token']
    token_df['expiry'] = ''
    token_df['strike'] = 0.0
    token_df['lotsize'] = filter_df['lot_size']
    token_df['instrumenttype'] = 'EQ'
    token_df['tick_size'] = filter_df['tick_size']
    
    return token_df


def process_pocketful_bse_csv(path):
    """
    Processes the pocketful CSV file to fit the existing database schema and performs exchange name mapping.
    """
    logger.info("Processing pocketful BSE CSV Data")
    file_path = f'{path}/BSECompactScrip.csv'

    df = pd.read_csv(file_path)

    # # Map 'IDX' segment to 'BSE_INDEX' exchange
    # df['mapped_exchange'] = df.apply(
    #     lambda row: 'BSE_INDEX' if row['segment'] == 'IDX' else row['exchange'],
    #     axis=1
    # )

    token_df = pd.DataFrame()
    token_df['symbol'] = df['trading_symbol'].str.replace(r'-.*$', '', regex=True)
    token_df['brsymbol'] = df['trading_symbol']
    token_df['name'] = df['company_name']
    token_df['exchange'] = df['exchange']
    token_df['brexchange'] = df['exchange']
    token_df['token'] = df['exchange_token']
    token_df['expiry'] = ''
    token_df['strike'] = 0.0
    token_df['lotsize'] = df['lot_size']
    token_df['instrumenttype'] = df['instrument_name']
    token_df['tick_size'] = df['tick_size']
    
    token_df['exchange'] = df['segment'].map({
        'IDX': 'BSE_INDEX'
    }).fillna(df['exchange'])

    token_df['symbol'] = token_df['symbol'].replace({'SNSX50': 'SENSEX50'})

    return token_df

def process_pocketful_nfo_csv(path):
    """
    Processes the pocketful CSV file to fit the existing database schema and formats the symbol properly
    using the actual expiry date instead of what's embedded in the trading_symbol.
    """
    logger.info("Processing pocketful NFO CSV Data")
    file_path = f'{path}/NFOCompactScrip.csv'

    df = pd.read_csv(file_path)

    # Convert 'expiry' column to datetime format
    df['Expiry Date'] = pd.to_datetime(df['expiry'], errors='coerce')

    # Helper to format expiry as DDMMMYY (e.g., 26JUN25)
    def format_expiry(expiry):
        return expiry.strftime('%d%b%y').upper() if pd.notnull(expiry) else ''

    def build_symbol(row):
        try:
            expiry_str = format_expiry(row['Expiry Date'])
            if row['option_type'] == 'XX':
                return f"{row['company_name']}{expiry_str}FUT"
            elif row['option_type'] in ['CE', 'PE']:
                strike = float(row['strike'])
                strike_str = str(int(strike)) if strike.is_integer() else str(strike)
                return f"{row['company_name']}{expiry_str}{strike_str}{row['option_type']}"
            else:
                return row['trading_symbol']
        except Exception as e:
            logger.error(f"Error building symbol: {row}, Error: {e}")
            return row['trading_symbol']

    # Build the symbol column
    df['symbol'] = df.apply(build_symbol, axis=1)

    # Create token_df with relevant columns
    token_df = df[['symbol']].copy()
    token_df['brsymbol'] = df['trading_symbol'].values
    token_df['name'] = df['company_name'].values
    token_df['exchange'] = df['exchange'].values
    token_df['brexchange'] = df['exchange'].values
    token_df['token'] = df['exchange_token'].values
    token_df['expiry'] = df['Expiry Date'].dt.strftime('%d-%b-%y').str.upper()
    token_df['strike'] = df['strike'].values
    token_df['lotsize'] = df['lot_size'].values
    token_df['instrumenttype'] = df['option_type'].map({
        'XX': 'FUT',
        'CE': 'CE',
        'PE': 'PE'
    })
    token_df['tick_size'] = df['tick_size'].values

    return token_df

def process_pocketful_bfo_csv(path):
    """
    Processes the Pocketful BFO CSV file to fit the existing database schema and performs exchange name mapping.
    """
    logger.info("Processing pocketful BFO CSV Data")
    file_path = f'{path}/BFOCompactScrip.csv'

    df = pd.read_csv(file_path)

    # Convert 'expiry' column to datetime format
    df['Expiry Date'] = pd.to_datetime(df['expiry'], errors='coerce')

    # Normalize Instrument Type to Option Type
    df.loc[df['instrument_name'].isin(['SF', 'IF']), 'option_type'] = 'XX'

    # Helper to format expiry as DDMMMYY (e.g., 26JUN25)
    def format_expiry(expiry):
        return expiry.strftime('%d%b%y').upper() if pd.notnull(expiry) else ''

    # Function to build symbol using known fields
    def build_symbol(row):
        try:
            expiry_str = format_expiry(row['Expiry Date'])
            company = row['company_name']
            strike = str(row['strike']).replace('.', '')
            option_type = row['option_type']

            if option_type == 'XX':
                return f"{company}{expiry_str}FUT"
            elif option_type in ['CE', 'PE']:
                strike_str = str(int(float(strike))) if float(strike).is_integer() else strike
                return f"{company}{expiry_str}{strike_str}{option_type}"
            else:
                return row['trading_symbol']
        except Exception as e:
            logger.error(f"Error processing row: {row}, Error: {e}")
            return row['trading_symbol']

    # Apply symbol formatting to all types
    df['symbol'] = df.apply(lambda row: build_symbol(row), axis=1)

    # Create token_df with required columns
    token_df = df[['symbol']].copy()
    token_df['brsymbol'] = df['trading_symbol'].values
    token_df['name'] = df['company_name'].values
    token_df['exchange'] = df['exchange'].values
    token_df['brexchange'] = df['exchange'].values
    token_df['token'] = df['exchange_token'].values
    token_df['expiry'] = df['Expiry Date'].dt.strftime('%d-%b-%y').str.upper()
    token_df['strike'] = df['strike'].values
    token_df['lotsize'] = df['lot_size'].values
    token_df['instrumenttype'] = df['option_type'].map({
        'XX': 'FUT',
        'CE': 'CE',
        'PE': 'PE'
    })
    token_df['tick_size'] = df['tick_size'].values

    # Drop rows where 'symbol' is NaN
    token_df_cleaned = token_df.dropna(subset=['symbol'])

    return token_df_cleaned



def process_pocketful_mcx_csv(path):
    """
    Processes the pocketful MCX CSV file to fit the existing database schema and performs exchange name mapping.
    """
    logger.info("Processing pocketful MCX CSV Data")
    file_path = f'{path}/MCXCompactScrip.csv'

    df = pd.read_csv(file_path)

    # Remove unwanted instruments
    df = df[df['instrument_name'] != 'COM']

    # Convert 'expiry' column to datetime and store as 'Expiry Date'
    df['Expiry Date'] = pd.to_datetime(df['expiry'], errors='coerce')

    # Normalize Instrument Type to Option Type
    df.loc[df['instrument_name'].isin(['FUTCOM', 'FUTIDX']), 'option_type'] = 'XX'

    # Helper to format expiry as DDMMMYY (e.g., 26JUN25)
    def format_expiry(expiry):
        return expiry.strftime('%d%b%y').upper() if pd.notnull(expiry) else ''

    # Define the function to reformat symbol details
    def reformat_symbol_detail(row):
        try:
            expiry_str = format_expiry(row['Expiry Date'])
            strike = float(row['strike'])
            strike_str = str(int(strike)) if strike.is_integer() else str(strike)
            if row['option_type'] == 'XX':
                return f"{row['trading_symbol']}{expiry_str}FUT"
            elif row['option_type'] in ['CE', 'PE']:
                return f"{row['trading_symbol']}{expiry_str}{strike_str}{row['option_type']}"
            else:
                return row['trading_symbol']
        except Exception as e:
            logger.error(f"Error processing row: {row}, Error: {e}")
            return row['trading_symbol']  # fallback to just the symbol

    # Apply the symbol formatting for all rows based on option_type
    df['symbol'] = df.apply(reformat_symbol_detail, axis=1)

    # Create token_df with required columns
    token_df = df[['symbol']].copy()
    token_df['brsymbol'] = df['trading_symbol'].values
    token_df['name'] = df['trading_symbol'].values
    token_df['exchange'] = df['exchange'].values
    token_df['brexchange'] = df['exchange'].values
    token_df['token'] = df['exchange_token'].values
    token_df['expiry'] = df['Expiry Date'].dt.strftime('%d-%b-%y').str.upper()
    token_df['strike'] = df['strike'].values
    token_df['lotsize'] = df['lot_size'].values
    token_df['instrumenttype'] = df['option_type'].map({
        'XX': 'FUT',
        'CE': 'CE',
        'PE': 'PE'
    })
    token_df['tick_size'] = df['tick_size'].values

    return token_df


def process_pocketful_indices_csv(path):
    """
    Processes the pocketful CSV file to fit the existing database schema and performs exchange name mapping.
    """
    logger.info("Processing pocketful INDICES CSV Data")
    file_path = f'{path}/NSECompactScrip.csv'

    df = pd.read_csv(file_path)

    # Create an explicit copy to avoid SettingWithCopyWarning
    filter_df = df[df['segment'].isin(['INDICES'])].copy()

    # Use standard assignment instead of .loc to improve readability
    filter_df['symbol'] = filter_df['trading_symbol'].map({
        'Nifty 50': 'NIFTY',
        'Nifty Bank': 'BANKNIFTY',
        'India VIX': 'INDIAVIX',
        'Nifty Fin Service': 'FINNIFTY',
        'NIFTY MID SELECT': 'MIDCPNIFTY',
        'Nifty Next 50': 'NIFTYNXT50'
    }).fillna(filter_df['trading_symbol'])

    # Create token_df with the relevant columns
    token_df = filter_df[['symbol']].copy()
    token_df['brsymbol'] = filter_df['trading_symbol'].values
    token_df['name'] = filter_df['trading_symbol'].values
    token_df['exchange'] = filter_df['segment'].map({
        'INDICES': 'NSE_INDEX',
        'IDX': 'BSE_INDEX'
    }).fillna(filter_df['exchange'])
    token_df['brexchange'] = filter_df['exchange'].values
    token_df['token'] = filter_df['exchange_token'].values
    token_df['expiry'] = ''
    token_df['strike'] = 0.0
    token_df['lotsize'] = filter_df['lot_size'].values
    token_df['instrumenttype'] = filter_df['instrument_name'].map({
        'FUT': 'FUT',
        'CE': 'CE',
        'PE': 'PE'
    }).fillna(filter_df['instrument_name'])
    token_df['tick_size'] = filter_df['tick_size'].values
    return token_df
    token_df['brsymbol'] = filter_df['trading_symbol'].values
    token_df['name'] = filter_df['trading_symbol'].values
    token_df['exchange'] = filter_df['segment'].map({
        'INDICES': 'NSE_INDEX',
        'IDX': 'BSE_INDEX'
    }).fillna(filter_df['exchange'])
    token_df['brexchange'] = filter_df['exchange'].values
    token_df['token'] = filter_df['exchange_token'].values

    # Convert 'Expiry Date' to desired format
    token_df['expiry'] = ''
    token_df['strike'] = 0.0
    token_df['lotsize'] = filter_df['lot_size'].values
    token_df['instrumenttype'] = filter_df['segment'].map({
        'INDICES': 'NSE_INDEX',
        'IDX': 'BSE_INDEX'
    }).fillna(filter_df['exchange'])
    token_df['tick_size'] = 0.01

    # logger.info("Unique trading_symbols before replacement:")
    # logger.info(f"{filter_df['trading_symbol'].unique()}")

    # logger.info("Symbols after replacement:")
    # logger.info(f"{filter_df['symbol'].unique()}")

    return token_df

    


def delete_pocketful_temp_data(output_path):
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
        download_csv_pocketful_data(output_path)
        delete_symtoken_table()
        token_df = process_pocketful_nse_csv(output_path)
        copy_from_dataframe(token_df)
        token_df = process_pocketful_bse_csv(output_path)
        copy_from_dataframe(token_df)
        token_df = process_pocketful_nfo_csv(output_path)
        copy_from_dataframe(token_df)
        
        token_df = process_pocketful_mcx_csv(output_path)
        copy_from_dataframe(token_df)
        token_df = process_pocketful_bfo_csv(output_path)
        copy_from_dataframe(token_df)
        
        token_df = process_pocketful_indices_csv(output_path)
        copy_from_dataframe(token_df)
        delete_pocketful_temp_data(output_path)
        
        return socketio.emit('master_contract_download', {'status': 'success', 'message': 'Successfully Downloaded'})

    
    except Exception as e:
        logger.info(f"{e}")
        return socketio.emit('master_contract_download', {'status': 'error', 'message': str(e)})
        logger.info(f"{e}")
        return socketio.emit('master_contract_download', {'status': 'error', 'message': str(e)})



def search_symbols(symbol, exchange):
    return SymToken.query.filter(SymToken.symbol.like(f'%{symbol}%'), SymToken.exchange == exchange).all()
