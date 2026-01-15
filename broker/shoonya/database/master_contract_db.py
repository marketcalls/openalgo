import os
import requests
import zipfile
import io
import pandas as pd
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, Float, Sequence, Index
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from extensions import socketio  # Import SocketIO
from utils.logging import get_logger

logger = get_logger(__name__)




# Database setup
DATABASE_URL = os.getenv('DATABASE_URL')  # Replace with your database path
engine = create_engine(DATABASE_URL)
db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()

# Define SymToken table
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

    # Retrieve existing token-exchange combinations to filter them out from the insert
    existing_token_exchange = {(result.token, result.exchange) for result in db_session.query(SymToken.token, SymToken.exchange).all()}

    # Filter out data_dict entries with token-exchange combinations that already exist
    filtered_data_dict = [row for row in data_dict if (row['token'], row['exchange']) not in existing_token_exchange]

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

# Define the shoonya URLs for downloading the symbol files
shoonya_urls = {
    "NSE": "https://api.shoonya.com/NSE_symbols.txt.zip",
    "NFO": "https://api.shoonya.com/NFO_symbols.txt.zip",
    "CDS": "https://api.shoonya.com/CDS_symbols.txt.zip",
    "MCX": "https://api.shoonya.com/MCX_symbols.txt.zip",
    "BSE": "https://api.shoonya.com/BSE_symbols.txt.zip",
    "BFO": "https://api.shoonya.com/BFO_symbols.txt.zip"
}

def download_and_unzip_shoonya_data(output_path):
    """
    Downloads and unzips the shoonya text files to the tmp folder.
    """
    logger.info("Downloading and Unzipping shoonya Data")

    # Create the tmp directory if it doesn't exist
    if not os.path.exists(output_path):
        os.makedirs(output_path)

    downloaded_files = []

    # Iterate through the shoonya URLs and download/unzip files
    for key, url in shoonya_urls.items():
        try:
            # Send GET request to download the zip file
            response = requests.get(url, timeout=10)
            
            if response.status_code == 200:
                logger.info(f"Successfully downloaded {key} from {url}")
                
                # Use in-memory file to handle the downloaded zip file
                z = zipfile.ZipFile(io.BytesIO(response.content))
                z.extractall(output_path)
                downloaded_files.append(f"{key}.txt")
            else:
                logger.error(f"Failed to download {key} from {url}. Status code: {response.status_code}")
        except Exception as e:
            logger.error(f"Error downloading {key} from {url}: {e}")

    return downloaded_files

# Placeholder functions for processing data

def process_shoonya_nse_data(output_path):
    """
    Processes the shoonya NSE data (NSE_symbols.txt) to generate OpenAlgo symbols.
    Separates EQ, BE symbols, and Index symbols.
    """
    logger.info("Processing shoonya NSE Data")
    file_path = f'{output_path}/NSE_symbols.txt'

    # Read the NSE symbols file, specifying the exact columns to use and ignoring extra columns
    df = pd.read_csv(file_path, usecols=['Exchange', 'Token', 'LotSize', 'Symbol', 'TradingSymbol', 'Instrument', 'TickSize'])

    # Rename columns to match your schema
    df.columns = ['exchange', 'token', 'lotsize', 'name', 'brsymbol', 'instrumenttype', 'tick_size']

    # Add missing columns to ensure DataFrame matches the database structure
    df['symbol'] = df['brsymbol']  # Initialize 'symbol' with 'brsymbol'

    # Apply transformation for OpenAlgo symbols
    def get_openalgo_symbol(broker_symbol):
        # Separate by hyphen and apply logic for EQ and BE
        if '-EQ' in broker_symbol:
            return broker_symbol.replace('-EQ', '')
        elif '-BE' in broker_symbol:
            return broker_symbol.replace('-BE', '')
        else:
            # For other symbols (including index), OpenAlgo symbol remains the same as broker symbol
            return broker_symbol

    # Update the 'symbol' column
    df['symbol'] = df['brsymbol'].apply(get_openalgo_symbol)

    # Define Exchange: 'NSE' for EQ and BE, 'NSE_INDEX' for indexes
    df['exchange'] = df.apply(lambda row: 'NSE_INDEX' if row['instrumenttype'] == 'INDEX' else 'NSE', axis=1)
    df['brexchange'] = df['exchange']  # Broker exchange is the same as exchange

    # Set empty columns for 'expiry' and fill -1 for 'strike' where the data is missing
    df['expiry'] = ''  # No expiry for these instruments
    df['strike'] = -1  # Set default value -1 for strike price where missing

    # Ensure the instrument type is consistent
    df['instrumenttype'] = df['instrumenttype'].apply(lambda x: 'EQ' if x in ['EQ', 'BE'] else x)

    # Handle missing or invalid numeric values in 'lotsize' and 'tick_size'
    df['lotsize'] = pd.to_numeric(df['lotsize'], errors='coerce').fillna(0).astype(int)  # Convert to int, default to 0
    df['tick_size'] = pd.to_numeric(df['tick_size'], errors='coerce').fillna(0).astype(float)  # Convert to float, default to 0.0

    # Reorder the columns to match the database structure
    columns_to_keep = ['symbol', 'brsymbol', 'name', 'exchange', 'brexchange', 'token', 'expiry', 'strike', 'lotsize', 'instrumenttype', 'tick_size']
    df_filtered = df[columns_to_keep]

    df_filtered['symbol'] = df_filtered['symbol'].replace({
        'NIFTY INDEX': 'NIFTY',
        'NIFTY BANK': 'BANKNIFTY',
        'MIDCPNIFTY': 'MIDCPNIFTY',
        'INDIA VIX': 'INDIAVIX'
        })

    # Return the processed DataFrame
    return df_filtered



def process_shoonya_nfo_data(output_path):
    """
    Processes the shoonya NFO data (NFO_symbols.txt) to generate OpenAlgo symbols.
    Handles both futures and options formatting.
    """
    logger.info("Processing shoonya NFO Data")
    file_path = f'{output_path}/NFO_symbols.txt'

    # Read the NFO symbols file, specifying the exact columns to use
    df = pd.read_csv(file_path, usecols=['Exchange', 'Token', 'LotSize', 'Symbol', 'TradingSymbol', 'Expiry', 'Instrument', 'OptionType', 'StrikePrice', 'TickSize'])

    # Rename columns to match your schema
    df.columns = ['exchange', 'token', 'lotsize', 'name', 'brsymbol', 'expiry', 'instrumenttype', 'optiontype', 'strike', 'tick_size']

    # Add missing columns to ensure DataFrame matches the database structure
    df['expiry'] = df['expiry'].fillna('')  # Fill expiry with empty strings if missing
    df['strike'] = df['strike'].fillna('-1')  # Fill strike with -1 if missing

    # Define a function to format the expiry date as DD-MMM-YY
    def format_expiry_date(date_str):
        try:
            # Parse the input date and format it as DD-MMM-YY
            date_obj = datetime.strptime(date_str, '%d-%b-%Y')
            return date_obj.strftime('%d-%b-%y').upper()
        except ValueError:
            logger.info(f"Invalid expiry date format: {date_str}")
            return None

    # Apply the expiry date format
    df['expiry'] = df['expiry'].apply(format_expiry_date)

    # Replace the 'XX' option type with 'FUT' for futures
    df['instrumenttype'] = df.apply(lambda row: 'FUT' if row['optiontype'] == 'XX' else row['optiontype'], axis=1)

    # Format the symbol column based on the instrument type
    def format_symbol(row):
        # Convert hyphenated date to compact format for symbol
        expiry_date = row['expiry']
        if expiry_date and isinstance(expiry_date, str):
            compact_expiry = expiry_date.replace('-', '')
        else:
            compact_expiry = ''
            
        if row['instrumenttype'] == 'FUT':
            return f"{row['name']}{compact_expiry}FUT"
        else:
            # Ensure strike prices are either integers or floats
            formatted_strike = int(row['strike']) if float(row['strike']).is_integer() else row['strike']
            return f"{row['name']}{compact_expiry}{formatted_strike}{row['instrumenttype']}"

    df['symbol'] = df.apply(format_symbol, axis=1)

    # Define Exchange
    df['exchange'] = 'NFO'
    df['brexchange'] = df['exchange']

    # Ensure strike prices are handled as either float or int
    def handle_strike_price(strike):
        try:
            if float(strike).is_integer():
                return int(float(strike))  # Return as integer if no decimal
            else:
                return float(strike)  # Return as float if decimal exists
        except (ValueError, TypeError):
            return -1  # If there's an error or it's empty, return -1

    # Apply the function to strike column
    df['strike'] = df['strike'].apply(handle_strike_price)

    # Reorder the columns to match the database structure
    columns_to_keep = ['symbol', 'brsymbol', 'name', 'exchange', 'brexchange', 'token', 'expiry', 'strike', 'lotsize', 'instrumenttype', 'tick_size']
    df_filtered = df[columns_to_keep]

    # Return the processed DataFrame
    return df_filtered

def process_shoonya_cds_data(output_path):
    """
    Processes the shoonya CDS data (CDS_symbols.txt) to generate OpenAlgo symbols.
    Handles both futures and options formatting.
    """
    logger.info("Processing shoonya CDS Data")
    file_path = f'{output_path}/CDS_symbols.txt'

    # Read the CDS symbols file, specifying the exact columns to use
    df = pd.read_csv(file_path, usecols=['Exchange', 'Token', 'LotSize', 'Precision', 'Multiplier', 'Symbol', 'TradingSymbol', 'Expiry', 'Instrument', 'OptionType', 'StrikePrice', 'TickSize'])

    # Rename columns to match your schema
    df.columns = ['exchange', 'token', 'lotsize', 'precision', 'multiplier', 'name', 'brsymbol', 'expiry', 'instrumenttype', 'optiontype', 'strike', 'tick_size']

    df = df[df['token'] > 100] # Filter out CDS tokens with less than 100 digits to avioid dummy entries or index values that are not actual CDS tokens

    # Add missing columns to ensure DataFrame matches the database structure
    df['expiry'] = df['expiry'].fillna('')  # Fill expiry with empty strings if missing
    df['strike'] = df['strike'].fillna('-1')  # Fill strike with -1 if missing

    # Define a function to format the expiry date as DD-MMM-YY
    def format_expiry_date(date_str):
        try:
            return datetime.strptime(date_str, '%d-%b-%Y').strftime('%d-%b-%y').upper()
        except ValueError:
            logger.info(f"Invalid expiry date format: {date_str}")
            return None

    # Apply the expiry date format
    df['expiry'] = df['expiry'].apply(format_expiry_date)

    # Replace the 'XX' option type with 'FUT' for futures
    df['instrumenttype'] = df.apply(lambda row: 'FUT' if row['optiontype'] == 'XX' else row['instrumenttype'], axis=1)

    # Update instrumenttype to 'CE' or 'PE' based on the option type
    df['instrumenttype'] = df.apply(lambda row: row['optiontype'] if row['instrumenttype'] == 'OPTCUR' else row['instrumenttype'], axis=1)

    # Format the symbol column based on the instrument type
    def format_symbol(row):
        # Convert hyphenated date to compact format for symbol
        expiry_date = row['expiry']
        if expiry_date and isinstance(expiry_date, str):
            compact_expiry = expiry_date.replace('-', '')
        else:
            compact_expiry = ''
            
        if row['instrumenttype'] == 'FUT':
            return f"{row['name']}{compact_expiry}FUT"
        else:
            # Format strike price: remove .0 if it's a whole number
            strike = row['strike']
            if isinstance(strike, (int, float)):
                if float(strike).is_integer():
                    strike = int(float(strike))
            return f"{row['name']}{compact_expiry}{strike}{row['instrumenttype']}"

    df['symbol'] = df.apply(format_symbol, axis=1)

    # Define Exchange
    df['exchange'] = 'CDS'
    df['brexchange'] = df['exchange']

    # Ensure strike prices are handled as either float or int
    def handle_strike_price(strike):
        try:
            if float(strike).is_integer():
                return int(float(strike))  # Return as integer if no decimal
            else:
                return float(strike)  # Return as float if decimal exists
        except (ValueError, TypeError):
            return -1  # If there's an error or it's empty, return -1

    # Apply the function to strike column
    df['strike'] = df['strike'].apply(handle_strike_price)

    # Reorder the columns to match the database structure
    columns_to_keep = ['symbol', 'brsymbol', 'name', 'exchange', 'brexchange', 'token', 'expiry', 'strike', 'lotsize', 'instrumenttype', 'tick_size']
    df_filtered = df[columns_to_keep]

    # Return the processed DataFrame
    return df_filtered

def process_shoonya_mcx_data(output_path):
    """
    Processes the shoonya MCX data (MCX_symbols.txt) to generate OpenAlgo symbols.
    Handles both futures and options formatting.
    """
    logger.info("Processing shoonya MCX Data")
    file_path = f'{output_path}/MCX_symbols.txt'

    # Read the MCX symbols file, specifying the exact columns to use
    df = pd.read_csv(file_path, usecols=['Exchange', 'Token', 'LotSize', 'GNGD', 'Symbol', 'TradingSymbol', 'Expiry', 'Instrument', 'OptionType', 'StrikePrice', 'TickSize'])

    # Rename columns to match your schema
    df.columns = ['exchange', 'token', 'lotsize', 'gngd', 'name', 'brsymbol', 'expiry', 'instrumenttype', 'optiontype', 'strike', 'tick_size']

    # Add missing columns to ensure DataFrame matches the database structure
    df['expiry'] = df['expiry'].fillna('')  # Fill expiry with empty strings if missing
    df['strike'] = df['strike'].fillna('-1')  # Fill strike with -1 if missing

    # Define a function to format the expiry date as DD-MMM-YY
    def format_expiry_date(date_str):
        try:
            return datetime.strptime(date_str, '%d-%b-%Y').strftime('%d-%b-%y').upper()
        except ValueError:
            logger.info(f"Invalid expiry date format: {date_str}")
            return None

    # Apply the expiry date format
    df['expiry'] = df['expiry'].apply(format_expiry_date)

    # Replace the 'XX' option type with 'FUT' for futures
    df['instrumenttype'] = df.apply(lambda row: 'FUT' if row['optiontype'] == 'XX' else row['instrumenttype'], axis=1)

    # Update instrumenttype to 'CE' or 'PE' based on the option type
    df['instrumenttype'] = df.apply(lambda row: row['optiontype'] if row['instrumenttype'] == 'OPTFUT' else row['instrumenttype'], axis=1)

    # Format the symbol column based on the instrument type
    def format_symbol(row):
        # Convert hyphenated date to compact format for symbol
        expiry_date = row['expiry']
        if expiry_date and isinstance(expiry_date, str):
            compact_expiry = expiry_date.replace('-', '')
        else:
            compact_expiry = ''
            
        if row['instrumenttype'] == 'FUT':
            return f"{row['name']}{compact_expiry}FUT"
        else:
            # Format strike price: remove .0 if it's a whole number
            strike = row['strike']
            if isinstance(strike, (int, float)):
                if float(strike).is_integer():
                    strike = int(float(strike))
            return f"{row['name']}{compact_expiry}{strike}{row['instrumenttype']}"

    df['symbol'] = df.apply(format_symbol, axis=1)

    # Define Exchange
    df['exchange'] = 'MCX'
    df['brexchange'] = df['exchange']

    # Ensure strike prices are handled as either float or int
    def handle_strike_price(strike):
        try:
            if float(strike).is_integer():
                return int(float(strike))  # Return as integer if no decimal
            else:
                return float(strike)  # Return as float if decimal exists
        except (ValueError, TypeError):
            return -1  # If there's an error or it's empty, return -1

    # Apply the function to strike column
    df['strike'] = df['strike'].apply(handle_strike_price)

    # Reorder the columns to match the database structure
    columns_to_keep = ['symbol', 'brsymbol', 'name', 'exchange', 'brexchange', 'token', 'expiry', 'strike', 'lotsize', 'instrumenttype', 'tick_size']
    df_filtered = df[columns_to_keep]

    # Return the processed DataFrame
    return df_filtered

def process_shoonya_bse_data(output_path):
    """
    Processes the shoonya BSE data (BSE_symbols.txt) to generate OpenAlgo symbols.
    Maps all instrument types to 'EQ' and manually adds missing BSE index symbols.
    """
    logger.info("Processing shoonya BSE Data")
    file_path = f'{output_path}/BSE_symbols.txt'

    # Read the BSE symbols file, specifying the exact columns to use and ignoring extra columns
    df = pd.read_csv(file_path, usecols=['Exchange', 'Token', 'LotSize', 'Symbol', 'TradingSymbol', 'Instrument', 'TickSize'])

    # Rename columns to match your schema
    df.columns = ['exchange', 'token', 'lotsize', 'name', 'brsymbol', 'instrumenttype', 'tick_size']

    # Add missing columns to ensure DataFrame matches the database structure
    df['symbol'] = df['brsymbol']  # Initialize 'symbol' with 'brsymbol'

    # Apply transformation for OpenAlgo symbols (no special logic needed here)
    def get_openalgo_symbol(broker_symbol):
        return broker_symbol

    # Update the 'symbol' column
    df['symbol'] = df['brsymbol'].apply(get_openalgo_symbol)

    # Set Exchange: 'BSE' for all rows initially
    df['exchange'] = 'BSE'
    df['brexchange'] = df['exchange']  # Broker exchange is the same as exchange

    # Set expiry and strike, fill -1 for missing strike prices
    df['expiry'] = ''  # No expiry for these instruments
    df['strike'] = -1  # Default to -1 for strike price

    # Map all instrument types to 'EQ' for consistency
    # Original instrument types in BSE include: F, B, A, E, G, T, Z, X, XT, M, MT, TS, W, etc.
    df['instrumenttype'] = 'EQ'
    
    logger.info(f"Mapped all BSE instrument types to 'EQ'. Original types found: {df['instrumenttype'].unique()}")

    # Handle missing or invalid numeric values in 'lotsize' and 'tick_size'
    df['lotsize'] = pd.to_numeric(df['lotsize'], errors='coerce').fillna(0).astype(int)  # Convert to int, default to 0
    df['tick_size'] = pd.to_numeric(df['tick_size'], errors='coerce').fillna(0).astype(float)  # Convert to float, default to 0.0

    # Reorder the columns to match the database structure
    columns_to_keep = ['symbol', 'brsymbol', 'name', 'exchange', 'brexchange', 'token', 'expiry', 'strike', 'lotsize', 'instrumenttype', 'tick_size']
    df_filtered = df[columns_to_keep]

    # Manually add missing BSE index symbols
    bse_index_data = [
        {
            'symbol': 'SENSEX',
            'brsymbol': 'SENSEX',
            'name': 'SENSEX',
            'exchange': 'BSE_INDEX',
            'brexchange': 'BSE_INDEX',
            'token': '1',
            'expiry': '',
            'strike': -1,
            'lotsize': 1,
            'instrumenttype': 'INDEX',
            'tick_size': 0.05
        },
        {
            'symbol': 'BANKEX',
            'brsymbol': 'BANKEX',
            'name': 'BANKEX',
            'exchange': 'BSE_INDEX',
            'brexchange': 'BSE_INDEX',
            'token': '12',
            'expiry': '',
            'strike': -1,
            'lotsize': 1,
            'instrumenttype': 'INDEX',
            'tick_size': 0.05
        }
    ]

    # Create DataFrame from the manual index data
    bse_index_df = pd.DataFrame(bse_index_data)

    # Concatenate the regular BSE data with the manual index data
    df_combined = pd.concat([df_filtered, bse_index_df], ignore_index=True)

    logger.info(f"Processed {len(df_filtered)} BSE equity symbols and added {len(bse_index_data)} BSE index symbols manually")

    # Return the combined DataFrame
    return df_combined

def process_shoonya_bfo_data(output_path):
    """
    Processes the shoonya BFO data (BFO_symbols.txt) to generate OpenAlgo symbols and correctly extract the name column.
    Handles both futures and options formatting, ensuring strike prices are handled as either float or integer.
    """
    logger.info("Processing shoonya BFO Data")
    file_path = f'{output_path}/BFO_symbols.txt'
    
    try:
        # Read the BFO symbols file
        df = pd.read_csv(file_path, usecols=['Exchange', 'Token', 'LotSize', 'Symbol', 'TradingSymbol', 'Expiry', 'Instrument', 'OptionType', 'StrikePrice', 'TickSize'])
    except Exception as e:
        logger.warning(f"Error reading BFO file with specified columns: {e}")
        # Read without specifying columns in case structure is different
        df = pd.read_csv(file_path)
    # Rename columns to match your schema
    df.columns = ['exchange', 'token', 'lotsize', 'name', 'brsymbol', 'expiry', 'instrumenttype', 'optiontype', 'strike', 'tick_size']

    # Add missing columns to ensure DataFrame matches the database structure
    df['expiry'] = df['expiry'].fillna('')  # Fill expiry with empty strings if missing
    df['strike'] = df['strike'].fillna('-1')  # Fill strike with -1 if missing

    # Define a function to format the expiry date as DD-MMM-YY
    def format_expiry_date(date_str):
        try:
            return datetime.strptime(date_str, '%d-%b-%Y').strftime('%d-%b-%y').upper()
        except ValueError:
            logger.info(f"Invalid expiry date format: {date_str}")
            return None

    # Apply the expiry date format
    df['expiry'] = df['expiry'].apply(format_expiry_date)

    # Extract the 'name' from the 'TradingSymbol'
    def extract_name(tradingsymbol):
        import re
        match = re.match(r'([A-Za-z]+)', tradingsymbol)
        return match.group(1) if match else tradingsymbol

    # Apply name extraction
    df['name'] = df['brsymbol'].apply(extract_name)

    # Extract the instrument type (CE, PE, FUT) from TradingSymbol
    def extract_instrument_type(tradingsymbol):
        if tradingsymbol.endswith('FUT'):
            return 'FUT'
        elif tradingsymbol.endswith('CE'):
            return 'CE'
        elif tradingsymbol.endswith('PE'):
            return 'PE'
        else:
            return 'UNKNOWN'  # Handle cases where the suffix is not FUT, CE, or PE

    # Apply instrument type extraction
    df['instrumenttype'] = df['brsymbol'].apply(extract_instrument_type)

    # Ensure strike prices are handled as either float or int
    def handle_strike_price(strike):
        try:
            if float(strike).is_integer():
                return int(float(strike))  # Return as integer if no decimal
            else:
                return float(strike)  # Return as float if decimal exists
        except (ValueError, TypeError):
            return -1  # If there's an error or it's empty, return -1

    df['strike'] = df['strike'].apply(handle_strike_price)

    # Format the symbol column based on the instrument type and correctly handle the strike price
    def format_symbol(row):
        # Convert hyphenated date to compact format for symbol
        expiry_date = row['expiry']
        if expiry_date and isinstance(expiry_date, str):
            compact_expiry = expiry_date.replace('-', '')
        else:
            compact_expiry = ''
            
        if row['instrumenttype'] == 'FUT':
            return f"{row['name']}{compact_expiry}FUT"
        else:
            # Correctly format the strike price based on whether it's an integer or a float
            formatted_strike = f"{int(row['strike'])}" if isinstance(row['strike'], int) else f"{row['strike']:.2f}".rstrip('0').rstrip('.')
            return f"{row['name']}{compact_expiry}{formatted_strike}{row['instrumenttype']}"

    # Apply the symbol format
    df['symbol'] = df.apply(format_symbol, axis=1)

    # Define Exchange and Broker Exchange
    df['exchange'] = 'BFO'
    df['brexchange'] = df['exchange']

    # Reorder the columns to match the database structure
    columns_to_keep = ['symbol', 'brsymbol', 'name', 'exchange', 'brexchange', 'token', 'expiry', 'strike', 'lotsize', 'instrumenttype', 'tick_size']
    df_filtered = df[columns_to_keep]

    # Return the processed DataFrame
    return df_filtered

def delete_shoonya_temp_data(output_path):
    """
    Deletes the shoonya symbol files from the tmp folder after processing.
    """
    for filename in os.listdir(output_path):
        file_path = os.path.join(output_path, filename)
        if filename.endswith(".txt") and os.path.isfile(file_path):
            os.remove(file_path)
            logger.info(f"Deleted {file_path}")

def master_contract_download():
    """
    Downloads, processes, and deletes shoonya data.
    """
    logger.info("Downloading shoonya Master Contract")

    output_path = 'tmp'
    try:
        download_and_unzip_shoonya_data(output_path)
        delete_symtoken_table()
        
        # Process exchange data
        token_df = process_shoonya_nse_data(output_path)
        copy_from_dataframe(token_df)
        token_df = process_shoonya_bse_data(output_path)
        copy_from_dataframe(token_df)
        token_df = process_shoonya_nfo_data(output_path)
        copy_from_dataframe(token_df)
        token_df = process_shoonya_cds_data(output_path)
        copy_from_dataframe(token_df)
        token_df = process_shoonya_mcx_data(output_path)
        copy_from_dataframe(token_df)
        token_df = process_shoonya_bfo_data(output_path)
        copy_from_dataframe(token_df)
        
        delete_shoonya_temp_data(output_path)
        
        return socketio.emit('master_contract_download', {'status': 'success', 'message': 'Successfully Downloaded'})
    except Exception as e:
        logger.info(f"{str(e)}")
        return socketio.emit('master_contract_download', {'status': 'error', 'message': str(e)})
