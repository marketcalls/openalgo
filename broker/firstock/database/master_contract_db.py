import os
import pandas as pd
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, Float, Sequence, Index
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from extensions import socketio
from utils.logging import get_logger
from utils.httpx_client import get_httpx_client

logger = get_logger(__name__)

# Database setup
DATABASE_URL = os.getenv('DATABASE_URL')
engine = create_engine(DATABASE_URL)
db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()

# Define SymToken table
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
    data_dict = df.to_dict(orient='records')
    existing_tokens = {result.token for result in db_session.query(SymToken.token).all()}
    filtered_data_dict = [row for row in data_dict if row['token'] not in existing_tokens]

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

# Firstock URLs for downloading symbol files
firstock_urls = {
    "NSE": "https://openapi.thefirstock.com/NSESymbolDownload?ref=wikiconnect.thefirstock.com",
    "BSE": "https://openapi.thefirstock.com/BSESymbolDownload?ref=wikiconnect.thefirstock.com",
    "NFO": "https://openapi.thefirstock.com/NFOSymbolDownload?ref=wikiconnect.thefirstock.com",
    "BFO": "https://openapi.thefirstock.com/BFOSymbolDownload?ref=wikiconnect.thefirstock.com"
}

def download_firstock_data(output_path):
    """
    Downloads CSV files from Firstock's API endpoints using shared httpx client with connection pooling.
    
    CSV Columns:
    NSE/BSE: Exchange, Token, LotSize, TradingSymbol, CompanyName, ISIN, TickSize, FreezeQty
    NFO/BFO: Exchange, Token, LotSize, Symbol, TradingSymbol, CompanyName, Expiry, 
             Instrument, OptionType, StrikePrice, TickSize, FreezeQty
    """
    logger.info("Downloading Firstock Data")
    
    if not os.path.exists(output_path):
        os.makedirs(output_path)
    
    downloaded_files = []
    
    try:
        # Get the shared httpx client with connection pooling
        client = get_httpx_client()
        
        for exchange, url in firstock_urls.items():
            try:
                logger.info(f"Downloading {exchange} data from {url}")
                
                # Make request using shared httpx client
                response = client.get(url, timeout=30)
                
                # Add status attribute for compatibility
                response.status = response.status_code
                
                if response.status_code == 200:
                    file_path = f'{output_path}/{exchange}_symbols.csv'
                    with open(file_path, 'w') as f:
                        f.write(response.text)
                    downloaded_files.append(f"{exchange}_symbols.csv")
                    logger.info(f"Successfully downloaded {exchange} data")
                else:
                    logger.error(f"Failed to download {exchange} data. Status code: {response.status_code}")
                    
            except Exception as e:
                if "timeout" in str(e).lower():
                    logger.error(f"Timeout while downloading {exchange} data - please try again")
                elif "connection" in str(e).lower():
                    logger.error(f"Connection error while downloading {exchange} data - please check your internet connection")
                else:
                    logger.error(f"Error downloading {exchange} data: {str(e)}")
                    
    except Exception as e:
        logger.error(f"Error initializing HTTP client: {str(e)}")
    
    return downloaded_files

def process_firstock_nse_data(output_path):
    """
    Processes the Firstock NSE data (NSE_symbols.csv) to generate OpenAlgo symbols.
    Separates EQ, BE symbols, and Index symbols.
    
    Index symbols are identified by having 0 values in ISIN, TickSize, and FreezeQty columns.
    """
    logger.info("Processing Firstock NSE Data")
    file_path = f'{output_path}/NSE_symbols.csv'

    # Read the NSE symbols file with all columns
    df = pd.read_csv(file_path)

    # Identify index symbols based on zero values in specific columns
    df['is_index'] = (df['ISIN'].isna() | df['ISIN'].eq('')) & df['TickSize'].eq(0.0) & df['FreezeQty'].eq(0.0)

    # Rename columns to match schema
    column_mapping = {
        'Exchange': 'exchange',
        'Token': 'token',
        'LotSize': 'lotsize',
        'TradingSymbol': 'brsymbol',
        'CompanyName': 'name',
        'TickSize': 'tick_size'
    }
    df = df.rename(columns=column_mapping)

    # Initialize symbol with brsymbol
    df['symbol'] = df['brsymbol']

    # Apply transformation for OpenAlgo symbols
    def get_openalgo_symbol(broker_symbol):
        if '-EQ' in broker_symbol:
            return broker_symbol.replace('-EQ', '')
        elif '-BE' in broker_symbol:
            return broker_symbol.replace('-BE', '')
        else:
            return broker_symbol

    # Update the symbol column
    df['symbol'] = df['brsymbol'].apply(get_openalgo_symbol)
    
    # Map index symbols to OpenAlgo standard format
    index_symbol_mapping = {
        'Nifty 50': 'NIFTY',
        'Nifty Fin Service': 'FINNIFTY',
        'Nifty Bank': 'BANKNIFTY',
        'NIFTY MID SELECT': 'MIDCPNIFTY',
        'INDIAVIX': 'INDIAVIX'
    }
    
    # Apply index symbol mapping
    df['symbol'] = df['symbol'].replace(index_symbol_mapping)

    # Set instrument type based on is_index flag and trading symbol
    def get_instrument_type(row):
        if row['is_index']:
            return 'INDEX'
        elif '-BE' in row['brsymbol']:
            return 'BE'
        else:
            return 'EQ'

    # Set instrument type
    df['instrumenttype'] = df.apply(get_instrument_type, axis=1)

    # Define Exchange: 'NSE' for EQ and BE, 'NSE_INDEX' for indexes
    df['exchange'] = df.apply(lambda row: 'NSE_INDEX' if row['instrumenttype'] == 'INDEX' else 'NSE', axis=1)
    # brexchange should always be 'NSE' for Firstock (including indices)
    df['brexchange'] = 'NSE'

    # Set empty columns for expiry and strike
    df['expiry'] = ''
    df['strike'] = -1

    # Handle missing or invalid numeric values
    df['lotsize'] = pd.to_numeric(df['lotsize'], errors='coerce').fillna(0).astype(int)
    df['tick_size'] = pd.to_numeric(df['tick_size'], errors='coerce').fillna(0).astype(float)

    # Reorder the columns to match the database structure
    columns_to_keep = ['symbol', 'brsymbol', 'name', 'exchange', 'brexchange', 'token', 'expiry', 'strike', 'lotsize', 'instrumenttype', 'tick_size']
    df_filtered = df[columns_to_keep]

    # Return the processed DataFrame
    return df_filtered

def process_firstock_nfo_data(output_path):
    """
    Processes the Firstock NFO data (NFO_symbols.csv) to generate OpenAlgo symbols.
    Handles both futures and options formatting.
    """
    logger.info("Processing Firstock NFO Data")
    file_path = f'{output_path}/NFO_symbols.csv'

    # Read the NFO symbols file
    df = pd.read_csv(file_path)

    # Rename columns to match schema
    column_mapping = {
        'Exchange': 'exchange',
        'Token': 'token',
        'LotSize': 'lotsize',
        'Symbol': 'name',
        'TradingSymbol': 'brsymbol',
        'Expiry': 'expiry',
        'Instrument': 'instrumenttype',
        'OptionType': 'optiontype',
        'StrikePrice': 'strike',
        'TickSize': 'tick_size'
    }
    df = df.rename(columns=column_mapping)

    # Fill missing values
    df['expiry'] = df['expiry'].fillna('')
    df['strike'] = df['strike'].fillna(-1)

    # Format expiry date as DDMMMYY
    def format_expiry_date(date_str):
        try:
            return datetime.strptime(date_str, '%d-%b-%Y').strftime('%d%b%y').upper()
        except ValueError:
            logger.info(f"Invalid expiry date format: {date_str}")
            return None

    # Apply the expiry date format
    df['expiry'] = df['expiry'].apply(format_expiry_date)

    # Set instrument type based on option type
    df['instrumenttype'] = df.apply(lambda row: 'FUT' if row['optiontype'] == 'XX' else row['optiontype'], axis=1)

    # Format symbol based on instrument type
    def format_symbol(row):
        if row['instrumenttype'] == 'FUT':
            return f"{row['name']}{row['expiry']}FUT"
        else:
            # Ensure strike prices are either integers or floats
            formatted_strike = int(row['strike']) if float(row['strike']).is_integer() else row['strike']
            return f"{row['name']}{row['expiry']}{formatted_strike}{row['instrumenttype']}"

    df['symbol'] = df.apply(format_symbol, axis=1)

    # Set exchange
    df['exchange'] = 'NFO'
    df['brexchange'] = df['exchange']

    # Handle strike prices
    def handle_strike_price(strike):
        try:
            if float(strike).is_integer():
                return int(float(strike))
            else:
                return float(strike)
        except (ValueError, TypeError):
            return -1

    df['strike'] = df['strike'].apply(handle_strike_price)

    # Handle numeric values
    df['lotsize'] = pd.to_numeric(df['lotsize'], errors='coerce').fillna(0).astype(int)
    df['tick_size'] = pd.to_numeric(df['tick_size'], errors='coerce').fillna(0).astype(float)

    # Reorder columns
    columns_to_keep = ['symbol', 'brsymbol', 'name', 'exchange', 'brexchange', 'token', 'expiry', 'strike', 'lotsize', 'instrumenttype', 'tick_size']
    df_filtered = df[columns_to_keep]

    return df_filtered

def process_firstock_bse_data(output_path):
    """
    Processes the Firstock BSE data (BSE_symbols.csv) to generate OpenAlgo symbols.
    Ensures that the instrument type is always 'EQ'.
    """
    logger.info("Processing Firstock BSE Data")
    file_path = f'{output_path}/BSE_symbols.csv'

    # Read the BSE symbols file
    df = pd.read_csv(file_path)

    # Rename columns to match schema
    column_mapping = {
        'Exchange': 'exchange',
        'Token': 'token',
        'LotSize': 'lotsize',
        'TradingSymbol': 'brsymbol',
        'CompanyName': 'name',
        'TickSize': 'tick_size'
    }
    df = df.rename(columns=column_mapping)

    # Initialize symbol with brsymbol
    df['symbol'] = df['brsymbol']

    # Apply transformation for OpenAlgo symbols (no special logic needed for BSE)
    def get_openalgo_symbol(broker_symbol):
        return broker_symbol

    # Update the symbol column
    df['symbol'] = df['brsymbol'].apply(get_openalgo_symbol)

    # Set Exchange: 'BSE' for all rows
    df['exchange'] = 'BSE'
    df['brexchange'] = df['exchange']

    # Set empty columns for expiry and strike
    df['expiry'] = ''
    df['strike'] = -1

    # Set instrument type to 'EQ' for all rows
    df['instrumenttype'] = 'EQ'

    # Handle missing or invalid numeric values
    df['lotsize'] = pd.to_numeric(df['lotsize'], errors='coerce').fillna(0).astype(int)
    df['tick_size'] = pd.to_numeric(df['tick_size'], errors='coerce').fillna(0).astype(float)

    # Reorder the columns to match the database structure
    columns_to_keep = ['symbol', 'brsymbol', 'name', 'exchange', 'brexchange', 'token', 'expiry', 'strike', 'lotsize', 'instrumenttype', 'tick_size']
    df_filtered = df[columns_to_keep]

    # Return the processed DataFrame
    return df_filtered

def process_firstock_bfo_data(output_path):
    """
    Processes the Firstock BFO data (BFO_symbols.csv) to generate OpenAlgo symbols.
    Similar to NFO but for BSE derivatives.
    """
    logger.info("Processing Firstock BFO Data")
    file_path = f'{output_path}/BFO_symbols.csv'

    # Read the BFO symbols file
    df = pd.read_csv(file_path)

    # Rename columns to match schema
    column_mapping = {
        'Exchange': 'exchange',
        'Token': 'token',
        'LotSize': 'lotsize',
        'Symbol': 'name',
        'TradingSymbol': 'brsymbol',
        'Expiry': 'expiry',
        'Instrument': 'instrumenttype',
        'OptionType': 'optiontype',
        'StrikePrice': 'strike',
        'TickSize': 'tick_size'
    }
    df = df.rename(columns=column_mapping)

    # Fill missing values
    df['expiry'] = df['expiry'].fillna('')
    df['strike'] = df['strike'].fillna(-1)

    # Format expiry date as DDMMMYY
    def format_expiry_date(date_str):
        try:
            return datetime.strptime(date_str, '%d-%b-%Y').strftime('%d%b%y').upper()
        except ValueError:
            logger.info(f"Invalid expiry date format: {date_str}")
            return None

    # Apply the expiry date format
    df['expiry'] = df['expiry'].apply(format_expiry_date)

    # Set instrument type based on option type
    df['instrumenttype'] = df.apply(lambda row: 'FUT' if row['optiontype'] == 'XX' else row['optiontype'], axis=1)

    # Format symbol based on instrument type
    def format_symbol(row):
        if row['instrumenttype'] == 'FUT':
            return f"{row['name']}{row['expiry']}FUT"
        else:
            # Ensure strike prices are either integers or floats
            formatted_strike = int(row['strike']) if float(row['strike']).is_integer() else row['strike']
            return f"{row['name']}{row['expiry']}{formatted_strike}{row['instrumenttype']}"

    df['symbol'] = df.apply(format_symbol, axis=1)

    # Set exchange
    df['exchange'] = 'BFO'
    df['brexchange'] = df['exchange']

    # Handle strike prices
    def handle_strike_price(strike):
        try:
            if float(strike).is_integer():
                return int(float(strike))
            else:
                return float(strike)
        except (ValueError, TypeError):
            return -1

    df['strike'] = df['strike'].apply(handle_strike_price)

    # Handle numeric values
    df['lotsize'] = pd.to_numeric(df['lotsize'], errors='coerce').fillna(0).astype(int)
    df['tick_size'] = pd.to_numeric(df['tick_size'], errors='coerce').fillna(0).astype(float)

    # Reorder columns
    columns_to_keep = ['symbol', 'brsymbol', 'name', 'exchange', 'brexchange', 'token', 'expiry', 'strike', 'lotsize', 'instrumenttype', 'tick_size']
    df_filtered = df[columns_to_keep]

    return df_filtered

def delete_firstock_temp_data(output_path):
    """Deletes the temporary CSV files after processing."""
    for filename in os.listdir(output_path):
        if filename.endswith("_symbols.csv"):
            file_path = os.path.join(output_path, filename)
            os.remove(file_path)
            logger.info(f"Deleted {file_path}")

def master_contract_download():
    """Downloads and processes Firstock contract data."""
    logger.info("Starting master contract download")
    output_path = 'tmp'
    
    try:
        socketio.emit('download_progress', 'Starting download...')
        
        # Initialize database
        init_db()
        delete_symtoken_table()
        
        # Download data
        downloaded_files = download_firstock_data(output_path)
        
        if downloaded_files:
            # Process each exchange
            if 'NSE_symbols.csv' in downloaded_files:
                token_df = process_firstock_nse_data(output_path)
                copy_from_dataframe(token_df)
            
            if 'BSE_symbols.csv' in downloaded_files:
                token_df = process_firstock_bse_data(output_path)
                copy_from_dataframe(token_df)
            
            if 'NFO_symbols.csv' in downloaded_files:
                token_df = process_firstock_nfo_data(output_path)
                copy_from_dataframe(token_df)
            
            if 'BFO_symbols.csv' in downloaded_files:
                token_df = process_firstock_bfo_data(output_path)
                copy_from_dataframe(token_df)
            
            # Clean up temporary files
            delete_firstock_temp_data(output_path)
            
            logger.info("Master contract download completed successfully")
            socketio.emit('download_progress', 'Download completed')
        else:
            logger.info("No files were downloaded")
            socketio.emit('download_progress', 'Download failed')
            
    except Exception as e:
        logger.error(f"Error in master contract download: {e}")
        socketio.emit('download_progress', f'Error: {str(e)}')