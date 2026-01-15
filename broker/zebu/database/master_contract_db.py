import os
import httpx
import zipfile
import io
import pandas as pd
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, Float, Sequence, Index
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from extensions import socketio  # Import SocketIO
from utils.httpx_client import get_httpx_client
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

# Define the Zebu URLs for downloading the symbol files
zebu_urls = {
    "NSE": "https://go.mynt.in/NSE_symbols.txt.zip",
    "NFO": "https://go.mynt.in/NFO_symbols.txt.zip",
    "CDS": "https://go.mynt.in/CDS_symbols.txt.zip",
    "MCX": "https://go.mynt.in/MCX_symbols.txt.zip",
    "BSE": "https://go.mynt.in/BSE_symbols.txt.zip",
    "BFO": "https://go.mynt.in/BFO_symbols.txt.zip"
}

def download_and_unzip_zebu_data(output_path):
    """
    Downloads and unzips the Zebu text files to the tmp folder using httpx with connection pooling.
    """
    logger.info("Downloading and Unzipping Zebu Data")

    # Create the tmp directory if it doesn't exist
    if not os.path.exists(output_path):
        os.makedirs(output_path)

    downloaded_files = []

    # Get the shared httpx client
    client = get_httpx_client()

    # Iterate through the Zebu URLs and download/unzip files
    for key, url in zebu_urls.items():
        try:
            # Send GET request to download the zip file using httpx client
            response = client.get(url, timeout=10.0)

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

def process_zebu_nse_data(output_path):
    """
    Processes the Zebu NSE data (NSE_symbols.txt) to generate OpenAlgo symbols.
    Separates EQ, BE symbols, and Index symbols.
    """
    logger.info("Processing Zebu NSE Data")
    file_path = f'{output_path}/NSE_symbols.txt'

    # Read the NSE symbols file, specifying the exact columns to use and ignoring extra columns
    df = pd.read_csv(file_path, usecols=['Exchange', 'Token', 'LotSize', 'Symbol', 'TradingSymbol', 'Instrument', 'TickSize'])

    # Rename columns to match your schema
    df.columns = ['exchange', 'token', 'lotsize', 'name', 'brsymbol', 'instrumenttype', 'tick_size']

    # Convert token to string to ensure compatibility with Zebu API
    df['token'] = df['token'].astype(str)

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
    # Broker exchange should always be NSE for Zebu API calls
    df['brexchange'] = 'NSE'

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

    # Map common NSE index symbols to OpenAlgo format
    nse_index_mapping = {
        'NIFTY INDEX': 'NIFTY',
        'NIFTY BANK': 'BANKNIFTY',
        'NIFTY FIN SERVICE': 'FINNIFTY',
        'NIFTY MIDCAP SELECT': 'MIDCPNIFTY',
        'NIFTY NEXT 50': 'NIFTYNXT50',
        'INDIA VIX': 'INDIAVIX'
    }

    # Apply the mapping only to NSE_INDEX symbols
    df_filtered.loc[df_filtered['exchange'] == 'NSE_INDEX', 'symbol'] = \
        df_filtered.loc[df_filtered['exchange'] == 'NSE_INDEX', 'symbol'].replace(nse_index_mapping)

    # Return the processed DataFrame
    return df_filtered



def process_zebu_nfo_data(output_path):
    """
    Processes the Zebu NFO data (NFO_symbols.txt) to generate OpenAlgo symbols.
    Handles both futures and options formatting.
    """
    logger.info("Processing Zebu NFO Data")
    file_path = f'{output_path}/NFO_symbols.txt'

    # Read the NFO symbols file, specifying the exact columns to use
    df = pd.read_csv(file_path, usecols=['Exchange', 'Token', 'LotSize', 'Symbol', 'TradingSymbol', 'Expiry', 'Instrument', 'OptionType', 'StrikePrice', 'TickSize'])

    # Rename columns to match your schema
    df.columns = ['exchange', 'token', 'lotsize', 'name', 'brsymbol', 'expiry', 'instrumenttype', 'optiontype', 'strike', 'tick_size']

    # Convert token to string to ensure compatibility with Zebu API
    df['token'] = df['token'].astype(str)

    # Add missing columns to ensure DataFrame matches the database structure
    df['expiry'] = df['expiry'].fillna('')  # Fill expiry with empty strings if missing
    df['strike'] = df['strike'].fillna('-1')  # Fill strike with -1 if missing

    # Define a function to format the expiry date as DDMMMYY
    def format_expiry_date(date_str):
        try:
            return datetime.strptime(date_str, '%d-%b-%Y').strftime('%d%b%y').upper()
        except ValueError:
            logger.info(f"Invalid expiry date format: {date_str}")
            return None

    # Apply the expiry date format
    df['expiry'] = df['expiry'].apply(format_expiry_date)

    # Replace the 'XX' option type with 'FUT' for futures
    df['instrumenttype'] = df.apply(lambda row: 'FUT' if row['optiontype'] == 'XX' else row['optiontype'], axis=1)

    # Format the symbol column based on the instrument type
    def format_symbol(row):
        if row['instrumenttype'] == 'FUT':
            return f"{row['name']}{row['expiry']}FUT"
        else:
            # Ensure strike prices are either integers or floats
            formatted_strike = int(row['strike']) if float(row['strike']).is_integer() else row['strike']
            return f"{row['name']}{row['expiry']}{formatted_strike}{row['instrumenttype']}"

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

def process_zebu_cds_data(output_path):
    """
    Processes the Zebu CDS data (CDS_symbols.txt) to generate OpenAlgo symbols.
    Handles both futures and options formatting.
    """
    logger.info("Processing Zebu CDS Data")
    file_path = f'{output_path}/CDS_symbols.txt'

    # Read the CDS symbols file, specifying the exact columns to use
    df = pd.read_csv(file_path, usecols=['Exchange', 'Token', 'LotSize', 'Precision', 'Multiplier', 'Symbol', 'TradingSymbol', 'Expiry', 'Instrument', 'OptionType', 'StrikePrice', 'TickSize'])

    # Rename columns to match your schema
    df.columns = ['exchange', 'token', 'lotsize', 'precision', 'multiplier', 'name', 'brsymbol', 'expiry', 'instrumenttype', 'optiontype', 'strike', 'tick_size']

    # Convert token to string to ensure compatibility with Zebu API
    df['token'] = df['token'].astype(str)

    # Add missing columns to ensure DataFrame matches the database structure
    df['expiry'] = df['expiry'].fillna('')  # Fill expiry with empty strings if missing
    df['strike'] = df['strike'].fillna('-1')  # Fill strike with -1 if missing

    # Define a function to format the expiry date as DDMMMYY
    def format_expiry_date(date_str):
        try:
            return datetime.strptime(date_str, '%d-%b-%Y').strftime('%d%b%y').upper()
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
        if row['instrumenttype'] == 'FUT':
            return f"{row['name']}{row['expiry']}FUT"
        else:
            return f"{row['name']}{row['expiry']}{row['strike']}{row['instrumenttype']}"

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

def process_zebu_mcx_data(output_path):
    """
    Processes the Zebu MCX data (MCX_symbols.txt) to generate OpenAlgo symbols.
    Handles both futures and options formatting.
    """
    logger.info("Processing Zebu MCX Data")
    file_path = f'{output_path}/MCX_symbols.txt'

    # Read the MCX symbols file, specifying the exact columns to use
    df = pd.read_csv(file_path, usecols=['Exchange', 'Token', 'LotSize', 'GNGD', 'Symbol', 'TradingSymbol', 'Expiry', 'Instrument', 'OptionType', 'StrikePrice', 'TickSize'])

    # Rename columns to match your schema
    df.columns = ['exchange', 'token', 'lotsize', 'gngd', 'name', 'brsymbol', 'expiry', 'instrumenttype', 'optiontype', 'strike', 'tick_size']

    # Convert token to string to ensure compatibility with Zebu API
    df['token'] = df['token'].astype(str)

    # Add missing columns to ensure DataFrame matches the database structure
    df['expiry'] = df['expiry'].fillna('')  # Fill expiry with empty strings if missing
    df['strike'] = df['strike'].fillna('-1')  # Fill strike with -1 if missing

    # Define a function to format the expiry date as DDMMMYY
    def format_expiry_date(date_str):
        try:
            return datetime.strptime(date_str, '%d-%b-%Y').strftime('%d%b%y').upper()
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
        if row['instrumenttype'] == 'FUT':
            return f"{row['name']}{row['expiry']}FUT"
        else:
            return f"{row['name']}{row['expiry']}{row['strike']}{row['instrumenttype']}"

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

def process_zebu_bse_data(output_path):
    """
    Processes the Zebu BSE data (BSE_symbols.txt) to generate OpenAlgo symbols.
    Ensures that the instrument type is always 'EQ' (no BSE index symbols available from Zebu).
    """
    logger.info("Processing Zebu BSE Data")
    file_path = f'{output_path}/BSE_symbols.txt'

    # Read the BSE symbols file
    df = pd.read_csv(file_path)

    # Read the BSE symbols file, specifying the exact columns to use and ignoring extra columns
    df = pd.read_csv(file_path, usecols=['Exchange', 'Token', 'LotSize', 'Symbol', 'TradingSymbol', 'Instrument', 'TickSize'])

    # Rename columns to match your schema
    df.columns = ['exchange', 'token', 'lotsize', 'name', 'brsymbol', 'instrumenttype', 'tick_size']

    # Convert token to string to ensure compatibility with Zebu API
    df['token'] = df['token'].astype(str)


    # Add missing columns to ensure DataFrame matches the database structure
    df['symbol'] = df['brsymbol']  # Initialize 'symbol' with 'brsymbol'

    # Apply transformation for OpenAlgo symbols (no special logic needed here)
    def get_openalgo_symbol(broker_symbol):
        return broker_symbol

    # Update the 'symbol' column
    df['symbol'] = df['brsymbol'].apply(get_openalgo_symbol)

    # Set Exchange: 'BSE' for all rows (no BSE index symbols from Zebu)
    df['exchange'] = 'BSE'
    df['brexchange'] = df['exchange']  # Broker exchange is the same as exchange

    # Set expiry and strike, fill -1 for missing strike prices
    df['expiry'] = ''  # No expiry for these instruments
    df['strike'] = -1  # Default to -1 for strike price

    # Ensure the instrument type is always 'EQ' since no BSE indices are provided
    df['instrumenttype'] = 'EQ'

    # Handle missing or invalid numeric values in 'lotsize' and 'tick_size'
    df['lotsize'] = pd.to_numeric(df['lotsize'], errors='coerce').fillna(0).astype(int)  # Convert to int, default to 0
    df['tick_size'] = pd.to_numeric(df['tick_size'], errors='coerce').fillna(0).astype(float)  # Convert to float, default to 0.0

    # Reorder the columns to match the database structure
    columns_to_keep = ['symbol', 'brsymbol', 'name', 'exchange', 'brexchange', 'token', 'expiry', 'strike', 'lotsize', 'instrumenttype', 'tick_size']
    df_filtered = df[columns_to_keep]

    # Return the processed DataFrame
    return df_filtered

def process_zebu_bfo_data(output_path):
    """
    Processes the Zebu BFO data (BFO_symbols.txt) to generate OpenAlgo symbols and correctly extract the name column.
    Handles both futures and options formatting, ensuring strike prices are handled as either float or integer.
    """
    logger.info("Processing Zebu BFO Data")
    file_path = f'{output_path}/BFO_symbols.txt'

    # Read the BFO symbols file, specifying the exact columns to use
    df = pd.read_csv(file_path, usecols=['Exchange', 'Token', 'LotSize', 'Symbol', 'TradingSymbol', 'Expiry', 'Instrument', 'Strike', 'TickSize'])

    # Rename columns to match your schema
    df.columns = ['exchange', 'token', 'lotsize', 'name', 'brsymbol', 'expiry', 'instrumenttype', 'strike', 'tick_size']

    # Convert token to string to ensure compatibility with Zebu API
    df['token'] = df['token'].astype(str)

    # Add missing columns to ensure DataFrame matches the database structure
    df['expiry'] = df['expiry'].fillna('')  # Fill expiry with empty strings if missing
    df['strike'] = df['strike'].fillna('-1')  # Fill strike with -1 if missing

    # Define a function to format the expiry date as DDMMMYY
    def format_expiry_date(date_str):
        try:
            return datetime.strptime(date_str, '%d-%b-%Y').strftime('%d%b%y').upper()
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
        if row['instrumenttype'] == 'FUT':
            return f"{row['name']}{row['expiry']}FUT"
        else:
            # Correctly format the strike price based on whether it's an integer or a float
            formatted_strike = f"{int(row['strike'])}" if isinstance(row['strike'], int) else f"{row['strike']:.2f}".rstrip('0').rstrip('.')
            return f"{row['name']}{row['expiry']}{formatted_strike}{row['instrumenttype']}"

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

def delete_zebu_temp_data(output_path):
    """
    Deletes the Zebu symbol files from the tmp folder after processing.
    """
    for filename in os.listdir(output_path):
        file_path = os.path.join(output_path, filename)
        if filename.endswith(".txt") and os.path.isfile(file_path):
            os.remove(file_path)
            logger.info(f"Deleted {file_path}")

def master_contract_download():
    """
    Downloads, processes, and deletes Zebu data.
    """
    logger.info("Downloading Zebu Master Contract")

    output_path = 'tmp'
    try:
        download_and_unzip_zebu_data(output_path)
        delete_symtoken_table()
        
        # Placeholders for processing different exchanges
        token_df = process_zebu_nse_data(output_path)
        copy_from_dataframe(token_df)
        token_df = process_zebu_bse_data(output_path)
        copy_from_dataframe(token_df)
        token_df = process_zebu_nfo_data(output_path)
        copy_from_dataframe(token_df)
        token_df = process_zebu_cds_data(output_path)
        copy_from_dataframe(token_df)
        token_df = process_zebu_mcx_data(output_path)
        copy_from_dataframe(token_df)
        token_df = process_zebu_bfo_data(output_path)
        copy_from_dataframe(token_df)
        
        delete_zebu_temp_data(output_path)
        
        return socketio.emit('master_contract_download', {'status': 'success', 'message': 'Successfully Downloaded'})
    except Exception as e:
        logger.info(f"{e}")
        return socketio.emit('master_contract_download', {'status': 'error', 'message': str(e)})