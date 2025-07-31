import os
import requests
import pandas as pd
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, Float, Sequence, Index
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from utils.logging import get_logger

logger = get_logger(__name__)

try:
    from extensions import socketio  # Import SocketIO
except ImportError:
    socketio = None



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
    """Initialize the database and create tables"""
    logger.info("Initializing Master Contract DB")
    
    # Create database directory if it doesn't exist
    db_path = os.path.dirname(DATABASE_URL.replace('sqlite:///', ''))
    if db_path and not os.path.exists(db_path):
        os.makedirs(db_path)
    
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
            logger.info(f"No new records to insert.")
    except Exception as e:
        logger.error(f"Error during bulk insert: {e}")
        db_session.rollback()

# Define the Flattrade URLs for downloading the symbol files
flattrade_urls = {
    "NSE": "https://flattrade.s3.ap-south-1.amazonaws.com/scripmaster/NSE_Equity.csv",
    "NFO_EQ": "https://flattrade.s3.ap-south-1.amazonaws.com/scripmaster/Nfo_Equity_Derivatives.csv",
    "NFO_IDX": "https://flattrade.s3.ap-south-1.amazonaws.com/scripmaster/Nfo_Index_Derivatives.csv",
    "CDS": "https://flattrade.s3.ap-south-1.amazonaws.com/scripmaster/Currency_Derivatives.csv",
    "MCX": "https://flattrade.s3.ap-south-1.amazonaws.com/scripmaster/Commodity.csv",
    "BSE": "https://flattrade.s3.ap-south-1.amazonaws.com/scripmaster/BSE_Equity.csv",
    "BFO_IDX": "https://flattrade.s3.ap-south-1.amazonaws.com/scripmaster/Bfo_Index_Derivatives.csv",
    "BFO_EQ": "https://flattrade.s3.ap-south-1.amazonaws.com/scripmaster/Bfo_Equity_Derivatives.csv"
}

def download_csv_data(output_path):
    """
    Downloads CSV files directly to the tmp folder.
    """
    logger.info("Downloading CSV Data")

    if not os.path.exists(output_path):
        os.makedirs(output_path)

    downloaded_files = []

    for key, url in flattrade_urls.items():
        try:
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                logger.info(f"Successfully downloaded {key} from {url}")
                output_file = os.path.join(output_path, f"{key}.csv")
                with open(output_file, 'wb') as f:
                    f.write(response.content)
                downloaded_files.append(f"{key}.csv")
            else:
                logger.error(f"Failed to download {key} from {url}. Status code: {response.status_code}")
        except Exception as e:
            logger.error(f"Error downloading {key} from {url}: {e}")

    # Combine NFO and BFO files
    combine_nfo_files(output_path)
    combine_bfo_files(output_path)

    return downloaded_files

# Placeholder functions for processing data

def process_flattrade_nse_data(output_path):
    """
    Processes the Flattrade NSE data (NSE_Equity.csv) to generate OpenAlgo symbols.
    Separates EQ, BE symbols, and Index symbols.
    """
    logger.info("Processing Flattrade NSE Data")
    file_path = f'{output_path}/NSE.csv'

    try:
        # Read the CSV file once
        df = pd.read_csv(file_path)
        
        if df.empty:
            logger.warning("Warning: NSE CSV file is empty")
            return pd.DataFrame()  # Return empty DataFrame if file is empty
            
        logger.info(f"Available columns in NSE CSV: {df.columns.tolist()}")

        # Validate required columns
        required_columns = ['Token', 'Lotsize', 'Symbol', 'Tradingsymbol', 'Instrument']
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            raise ValueError(f"Missing required columns in NSE CSV: {missing_columns}")

        # Rename columns to match your schema
        column_mapping = {
            'Token': 'token',
            'Lotsize': 'lotsize',
            'Symbol': 'name',
            'Tradingsymbol': 'brsymbol',
            'Instrument': 'instrumenttype',
            'Expiry': 'expiry',
            'Strike': 'strike',
            'Optiontype': 'optiontype'
        }
        
        df = df.rename(columns=column_mapping)

        # Fill NaN values in required fields
        df['name'] = df['name'].fillna('')
        df['brsymbol'] = df['brsymbol'].fillna('')
        df['token'] = df['token'].fillna('').astype(str)
        
        # Remove rows where brsymbol is empty (required field)
        df = df[df['brsymbol'] != '']
        
        # Add missing columns
        df['symbol'] = df['brsymbol'].copy()  # Initialize 'symbol' with 'brsymbol'
        df['tick_size'] = 0.05  # Default tick size for NSE

        # Apply transformation for OpenAlgo symbols
        def get_openalgo_symbol(broker_symbol):
            if pd.isna(broker_symbol) or not broker_symbol:  # Handle NaN and empty values
                return broker_symbol  # Return as is, will be filtered out later
            broker_symbol = str(broker_symbol)  # Convert to string to ensure string operations work
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
        df['instrumenttype'] = df['instrumenttype'].fillna('EQ')  # Fill NaN values with 'EQ'
        df['exchange'] = df.apply(lambda row: 'NSE_INDEX' if row['instrumenttype'] == 'INDEX' else 'NSE', axis=1)
        df['brexchange'] = df['exchange']  # Broker exchange is the same as exchange

        # Set empty columns for 'expiry' and fill -1 for 'strike' where the data is missing
        df['expiry'] = df.get('expiry', '').fillna('')
        df['strike'] = pd.to_numeric(df.get('strike', pd.Series([-1] * len(df))), errors='coerce').fillna(-1)

        # Ensure the instrument type is consistent
        df['instrumenttype'] = df['instrumenttype'].apply(lambda x: 'EQ' if x in ['EQ', 'BE'] else x)

        # Handle missing or invalid numeric values in 'lotsize'
        df['lotsize'] = pd.to_numeric(df['lotsize'], errors='coerce').fillna(1).astype(int)  # Default lotsize to 1

        # Reorder the columns to match the database structure
        columns_to_keep = ['symbol', 'brsymbol', 'name', 'exchange', 'brexchange', 'token', 'expiry', 'strike', 'lotsize', 'instrumenttype', 'tick_size']
        df_filtered = df[columns_to_keep]

        # Final validation - remove any rows with empty required fields
        df_filtered = df_filtered[
            (df_filtered['symbol'].notna()) & 
            (df_filtered['brsymbol'].notna()) & 
            (df_filtered['token'].notna()) & 
            (df_filtered['symbol'] != '') & 
            (df_filtered['brsymbol'] != '') & 
            (df_filtered['token'] != '')
        ]

        df_filtered['symbol'] = df_filtered['symbol'].replace({
            'Nifty 50': 'NIFTY',
            'Nifty Bank': 'BANKNIFTY',
            'Nifty Fin': 'FINNIFTY',
            'Nifty Next 50': 'NIFTYNXT50',
            'NIFTY MID SELECT': 'MIDCPNIFTY',
            'INDIAVIX': 'INDIAVIX'
        })

      
        logger.info(f"Successfully processed {len(df_filtered)} NSE records")
        return df_filtered
        
    except Exception as e:
        logger.error(f"Error processing NSE data: {e}")
        raise  # Re-raise the exception after logging

def process_flattrade_nfo_data(output_path):
    """
    Processes the Flattrade NFO data (NFO.csv) to generate OpenAlgo symbols.
    Handles both futures and options formatting.
    """
    logger.info("Processing Flattrade NFO Data")
    file_path = f'{output_path}/NFO.csv'

    # First read the CSV to check columns
    df = pd.read_csv(file_path)
    logger.info(f"Available columns in NFO CSV: {df.columns.tolist()}")

    # Rename columns to match your schema
    column_mapping = {
        'Token': 'token',
        'Lotsize': 'lotsize',
        'Symbol': 'name',
        'Tradingsymbol': 'brsymbol',
        'Instrument': 'instrumenttype',
        'Expiry': 'expiry',
        'Strike': 'strike',
        'Optiontype': 'optiontype'
    }
    
    df = df.rename(columns=column_mapping)

    # Add missing columns
    df['tick_size'] = 0.05  # Default tick size for NFO

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
            formatted_strike = int(float(row['strike'])) if float(row['strike']).is_integer() else float(row['strike'])
            return f"{row['name']}{row['expiry']}{formatted_strike}{row['instrumenttype']}"

    df['symbol'] = df.apply(format_symbol, axis=1)

    # Convert expiry format to hyphenated format for database storage (28AUG25 -> 28-AUG-25)
    def add_hyphens_to_expiry(expiry_str):
        if expiry_str and len(expiry_str) == 7:  # Format: 28AUG25
            return f"{expiry_str[:2]}-{expiry_str[2:5]}-{expiry_str[5:]}"
        return expiry_str
    
    df['expiry'] = df['expiry'].apply(add_hyphens_to_expiry)

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

    # Handle missing or invalid numeric values in 'lotsize'
    df['lotsize'] = pd.to_numeric(df['lotsize'], errors='coerce').fillna(0).astype(int)  # Convert to int, default to 0

    # Reorder the columns to match the database structure
    columns_to_keep = ['symbol', 'brsymbol', 'name', 'exchange', 'brexchange', 'token', 'expiry', 'strike', 'lotsize', 'instrumenttype', 'tick_size']
    df_filtered = df[columns_to_keep]

    # Return the processed DataFrame
    return df_filtered

def process_flattrade_cds_data(output_path):
    """
    Processes the Flattrade CDS data (Currency_Derivatives.csv) to generate OpenAlgo symbols.
    Handles both futures and options formatting.
    """
    logger.info("Processing Flattrade CDS Data")
    file_path = f'{output_path}/CDS.csv'

    # First read the CSV to check columns
    df = pd.read_csv(file_path)
    logger.info(f"Available columns in CDS CSV: {df.columns.tolist()}")

    # Rename columns to match your schema
    column_mapping = {
        'Token': 'token',
        'Lotsize': 'lotsize',
        'Symbol': 'name',
        'Tradingsymbol': 'brsymbol',
        'Instrument': 'instrumenttype',
        'Expiry': 'expiry',
        'Strike': 'strike',
        'Optiontype': 'optiontype'
    }
    
    df = df.rename(columns=column_mapping)

    # Add missing columns
    df['tick_size'] = 0.0025  # Default tick size for CDS

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
            formatted_strike = int(float(row['strike'])) if float(row['strike']).is_integer() else float(row['strike'])
            return f"{row['name']}{row['expiry']}{formatted_strike}{row['instrumenttype']}"

    df['symbol'] = df.apply(format_symbol, axis=1)

    # Convert expiry format to hyphenated format for database storage (28AUG25 -> 28-AUG-25)
    def add_hyphens_to_expiry(expiry_str):
        if expiry_str and len(expiry_str) == 7:  # Format: 28AUG25
            return f"{expiry_str[:2]}-{expiry_str[2:5]}-{expiry_str[5:]}"
        return expiry_str
    
    df['expiry'] = df['expiry'].apply(add_hyphens_to_expiry)

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

    # Handle missing or invalid numeric values in 'lotsize'
    df['lotsize'] = pd.to_numeric(df['lotsize'], errors='coerce').fillna(0).astype(int)  # Convert to int, default to 0

    # Reorder the columns to match the database structure
    columns_to_keep = ['symbol', 'brsymbol', 'name', 'exchange', 'brexchange', 'token', 'expiry', 'strike', 'lotsize', 'instrumenttype', 'tick_size']
    df_filtered = df[columns_to_keep]

    # Return the processed DataFrame
    return df_filtered

def process_flattrade_mcx_data(output_path):
    """
    Processes the Flattrade MCX data (Commodity.csv) to generate OpenAlgo symbols.
    Handles both futures and options formatting.
    """
    logger.info("Processing Flattrade MCX Data")
    file_path = f'{output_path}/MCX.csv'

    # First read the CSV to check columns
    df = pd.read_csv(file_path)
    logger.info(f"Available columns in MCX CSV: {df.columns.tolist()}")

    # Rename columns to match your schema
    column_mapping = {
        'Token': 'token',
        'Lotsize': 'lotsize',
        'Symbol': 'name',
        'Tradingsymbol': 'brsymbol',
        'Instrument': 'instrumenttype',
        'Expiry': 'expiry',
        'Strike': 'strike',
        'Optiontype': 'optiontype'
    }
    
    df = df.rename(columns=column_mapping)

    # Add missing columns
    df['tick_size'] = 0.05  # Default tick size for MCX

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
            formatted_strike = int(float(row['strike'])) if float(row['strike']).is_integer() else float(row['strike'])
            return f"{row['name']}{row['expiry']}{formatted_strike}{row['instrumenttype']}"

    df['symbol'] = df.apply(format_symbol, axis=1)

    # Convert expiry format to hyphenated format for database storage (28AUG25 -> 28-AUG-25)
    def add_hyphens_to_expiry(expiry_str):
        if expiry_str and len(expiry_str) == 7:  # Format: 28AUG25
            return f"{expiry_str[:2]}-{expiry_str[2:5]}-{expiry_str[5:]}"
        return expiry_str
    
    df['expiry'] = df['expiry'].apply(add_hyphens_to_expiry)

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

    # Handle missing or invalid numeric values in 'lotsize'
    df['lotsize'] = pd.to_numeric(df['lotsize'], errors='coerce').fillna(0).astype(int)  # Convert to int, default to 0

    # Reorder the columns to match the database structure
    columns_to_keep = ['symbol', 'brsymbol', 'name', 'exchange', 'brexchange', 'token', 'expiry', 'strike', 'lotsize', 'instrumenttype', 'tick_size']
    df_filtered = df[columns_to_keep]

    # Return the processed DataFrame
    return df_filtered

def process_flattrade_bse_data(output_path):
    """
    Processes the Flattrade BSE data (BSE_Equity.csv) to generate OpenAlgo symbols.
    Ensures that the instrument type is always 'EQ'.
    """
    logger.info("Processing Flattrade BSE Data")
    file_path = f'{output_path}/BSE.csv'

    # First read the CSV to check columns
    df = pd.read_csv(file_path)
    logger.info(f"Available columns in BSE CSV: {df.columns.tolist()}")

    # Rename columns to match your schema
    column_mapping = {
        'Token': 'token',
        'Lotsize': 'lotsize',
        'Symbol': 'name',
        'Tradingsymbol': 'brsymbol',
        'Instrument': 'instrumenttype',
        'Expiry': 'expiry',
        'Strike': 'strike',
        'Optiontype': 'optiontype'
    }
    
    df = df.rename(columns=column_mapping)

    # Add missing columns
    df['symbol'] = df['brsymbol']  # Initialize 'symbol' with 'brsymbol'
    df['tick_size'] = 0.05  # Default tick size for BSE

    # Apply transformation for OpenAlgo symbols (no special logic needed here)
    def get_openalgo_symbol(broker_symbol):
        return broker_symbol

    # Update the 'symbol' column
    df['symbol'] = df['brsymbol'].apply(get_openalgo_symbol)

    # Set Exchange based on Instrument type: BSE_INDEX for UNDIND, BSE for others
    df['exchange'] = df['instrumenttype'].apply(lambda x: 'BSE_INDEX' if x == 'UNDIND' else 'BSE')
    df['brexchange'] = 'BSE'  # Broker exchange is always BSE

    # Handle expiry and strike like NSE data
    df['expiry'] = df.get('expiry', '').fillna('')  # Fill expiry with empty strings if missing
    df['strike'] = pd.to_numeric(df.get('strike', pd.Series([-1] * len(df))), errors='coerce').fillna(-1)  # Fill strike with -1 if missing

    # Set instrument type: keep UNDIND for index instruments, set EQ for others
    df['instrumenttype'] = df['instrumenttype'].apply(lambda x: 'INDEX' if x == 'UNDIND' else 'EQ')

    # Handle missing or invalid numeric values in 'lotsize'
    df['lotsize'] = pd.to_numeric(df['lotsize'], errors='coerce').fillna(1).astype(int)  # Convert to int, default to 1 like NSE

    # Reorder the columns to match the database structure
    columns_to_keep = ['symbol', 'brsymbol', 'name', 'exchange', 'brexchange', 'token', 'expiry', 'strike', 'lotsize', 'instrumenttype', 'tick_size']
    df_filtered = df[columns_to_keep]

    # Final validation - remove any rows with empty required fields
    df_filtered = df_filtered[
        (df_filtered['symbol'].notna()) & 
        (df_filtered['brsymbol'].notna()) & 
        (df_filtered['token'].notna()) & 
        (df_filtered['symbol'] != '') & 
        (df_filtered['brsymbol'] != '') & 
        (df_filtered['token'] != '')
    ]

    logger.info(f"Successfully processed {len(df_filtered)} BSE records")
    # Return the processed DataFrame
    return df_filtered

def process_flattrade_bfo_data(output_path):
    """
    Processes the Flattrade BFO data (BFO.csv) to generate OpenAlgo symbols.
    Handles both futures and options formatting.
    """
    logger.info("Processing Flattrade BFO Data")
    file_path = f'{output_path}/BFO.csv'

    # First read the CSV to check columns
    df = pd.read_csv(file_path)
    logger.info(f"Available columns in BFO CSV: {df.columns.tolist()}")

    # Rename columns to match your schema
    column_mapping = {
        'Token': 'token',
        'Lotsize': 'lotsize',
        'Symbol': 'name',
        'Tradingsymbol': 'brsymbol',
        'Instrument': 'instrumenttype',
        'Expiry': 'expiry',
        'Strike': 'strike',
        'Optiontype': 'optiontype'
    }
    
    df = df.rename(columns=column_mapping)

    # Add missing columns
    df['tick_size'] = 0.05  # Default tick size for BFO

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
            formatted_strike = int(float(row['strike'])) if float(row['strike']).is_integer() else float(row['strike'])
            return f"{row['name']}{row['expiry']}{formatted_strike}{row['instrumenttype']}"

    df['symbol'] = df.apply(format_symbol, axis=1)

    # Convert expiry format to hyphenated format for database storage (28AUG25 -> 28-AUG-25)
    def add_hyphens_to_expiry(expiry_str):
        if expiry_str and len(expiry_str) == 7:  # Format: 28AUG25
            return f"{expiry_str[:2]}-{expiry_str[2:5]}-{expiry_str[5:]}"
        return expiry_str
    
    df['expiry'] = df['expiry'].apply(add_hyphens_to_expiry)

    # Define Exchange
    df['exchange'] = 'BFO'
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

    # Handle missing or invalid numeric values in 'lotsize'
    df['lotsize'] = pd.to_numeric(df['lotsize'], errors='coerce').fillna(0).astype(int)  # Convert to int, default to 0

    # Reorder the columns to match the database structure
    columns_to_keep = ['symbol', 'brsymbol', 'name', 'exchange', 'brexchange', 'token', 'expiry', 'strike', 'lotsize', 'instrumenttype', 'tick_size']
    df_filtered = df[columns_to_keep]

    # Return the processed DataFrame
    return df_filtered

def combine_nfo_files(output_path):
    """Combines NFO equity and index files into one"""
    logger.info("Combining NFO files")
    nfo_eq = pd.read_csv(f"{output_path}/NFO_EQ.csv")
    nfo_idx = pd.read_csv(f"{output_path}/NFO_IDX.csv")
    combined = pd.concat([nfo_eq, nfo_idx], ignore_index=True)
    combined.to_csv(f"{output_path}/NFO.csv", index=False)

def combine_bfo_files(output_path):
    """Combines BFO equity and index files into one"""
    logger.info("Combining BFO files")
    bfo_eq = pd.read_csv(f"{output_path}/BFO_EQ.csv")
    bfo_idx = pd.read_csv(f"{output_path}/BFO_IDX.csv")
    combined = pd.concat([bfo_eq, bfo_idx], ignore_index=True)
    combined.to_csv(f"{output_path}/BFO.csv", index=False)

def delete_flattrade_temp_data(output_path):
    """
    Deletes the Flattrade symbol files from the tmp folder after processing.
    """
    for filename in os.listdir(output_path):
        file_path = os.path.join(output_path, filename)
        if filename.endswith(".csv") and os.path.isfile(file_path):
            os.remove(file_path)
            logger.info(f"Deleted {file_path}")

def master_contract_download():
    """
    Downloads, processes, and deletes Flattrade data.
    """
    logger.info("Downloading Flattrade Master Contract")

    output_path = 'tmp'
    try:
        download_csv_data(output_path)
        delete_symtoken_table()
        
        # Placeholders for processing different exchanges
        token_df = process_flattrade_nse_data(output_path)
        copy_from_dataframe(token_df)
        token_df = process_flattrade_bse_data(output_path)
        copy_from_dataframe(token_df)
        token_df = process_flattrade_nfo_data(output_path)
        copy_from_dataframe(token_df)
        token_df = process_flattrade_cds_data(output_path)
        copy_from_dataframe(token_df)
        token_df = process_flattrade_mcx_data(output_path)
        copy_from_dataframe(token_df)
        token_df = process_flattrade_bfo_data(output_path)
        copy_from_dataframe(token_df)
        
        delete_flattrade_temp_data(output_path)
        
        if socketio:
            return socketio.emit('master_contract_download', {'status': 'success', 'message': 'Successfully Downloaded'})
        else:
            logger.info("Successfully downloaded and processed all contracts")
    except Exception as e:
        error_msg = f"Error in master contract download: {e}"
        logger.error(f"{error_msg}")
        if socketio:
            return socketio.emit('master_contract_download', {'status': 'error', 'message': error_msg})
        raise e