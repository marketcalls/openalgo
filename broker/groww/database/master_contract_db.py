#database/master_contract_db.py

import os
import pandas as pd
import numpy as np
import httpx
from io import StringIO
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
            logger.info(f"Inserting {len(filtered_data_dict)} new records into the database")
            # Create a list of SymToken objects from the filtered data
            symtoken_objects = []
            for item in filtered_data_dict:
                symtoken = SymToken(
                    symbol=item.get('symbol', ''),
                    brsymbol=item.get('brsymbol', ''),
                    name=item.get('name', ''),
                    exchange=item.get('exchange', ''),
                    brexchange=item.get('brexchange', ''),
                    token=item.get('token', ''),
                    expiry=item.get('expiry', ''),
                    strike=float(item.get('strike', 0)) if item.get('strike') else 0,
                    lotsize=int(item.get('lotsize', 0)) if item.get('lotsize') else 0,
                    instrumenttype=item.get('instrumenttype', ''),
                    tick_size=float(item.get('tick_size', 0)) if item.get('tick_size') else 0
                )
                symtoken_objects.append(symtoken)
            
            # Add all objects and commit in one transaction
            db_session.add_all(symtoken_objects)
            db_session.commit()
            logger.info(f"Successfully inserted {len(symtoken_objects)} records into the database")
        else:
            logger.info("No new records to insert")
    except Exception as e:
        db_session.rollback()
        logger.error(f"Error during bulk insert: {e}")
        raise


# Functions for symbol format conversion between OpenAlgo and Groww formats
def format_openalgo_to_groww_symbol(symbol, exchange):
    """
    Convert OpenAlgo symbol format to Groww symbol format
    
    Args:
        symbol (str): Symbol in OpenAlgo format (e.g., AARTIIND29MAY25630CE)
        exchange (str): Exchange code (NSE, BSE, NFO, etc.)
    
    Returns:
        str: Symbol in Groww format (e.g., "AARTIIND 29MAY25 630 CE")
    """
    logger.info(f"Converting symbol from OpenAlgo to Groww format: {{symbol}}, {exchange}")
    
    # If it's already in the right format or invalid, return as is
    if not symbol or len(symbol) < 6:
        return symbol
    
    # For NFO options specifically handle CE and PE options
    if exchange == 'NFO' and (symbol.endswith('CE') or symbol.endswith('PE')):
        import re
        # Extract the option type (CE or PE)
        option_type = symbol[-2:]
        
        # Try to identify the base symbol by checking common indices
        common_indices = ['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY', 'SENSEX', 'AARTIIND']
        base_symbol = None
        for index in common_indices:
            if symbol.startswith(index):
                base_symbol = index
                break
                
        # If we couldn't identify from common list, try to extract the alphabetic prefix
        if not base_symbol:
            # Match any alphabetic characters at the beginning (base symbol)
            base_match = re.match(r'^[A-Za-z]+', symbol)
            if base_match:
                base_symbol = base_match.group(0)
            else:
                # Fallback - unlikely to happen
                base_symbol = symbol[:6]
        
        # The remaining part contains expiration date and strike price
        # Format: [BaseSymbol][ExpirationDate][StrikePrice][OptionType]
        remaining = symbol[len(base_symbol):-2]
        
        # Pattern for DDMMMYY date format (like 29MAY25)
        date_pattern = r'(\d{2})([A-Za-z]{3})(\d{2})'
        date_match = re.search(date_pattern, remaining)
        
        if date_match:
            # Use named groups to extract parts
            day = date_match.group(1)
            month = date_match.group(2)
            year = date_match.group(3)
            date_str = f"{day}{month}{year}"
            
            # The strike price is everything between the date and the option type
            date_end_pos = remaining.find(date_str) + len(date_str)
            strike_str = remaining[date_end_pos:]
            
            # Format with spaces for Groww
            groww_symbol = f"{base_symbol} {date_str} {strike_str} {option_type}"
            logger.info(f"Converted to Groww format: {groww_symbol}")
            return groww_symbol
        else:
            # If we couldn't find a standard date pattern, try to parse it differently
            # Check for known month abbreviations and extract around them
            months = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC']
            
            for month in months:
                if month in remaining:
                    # Find month position
                    month_pos = remaining.find(month)
                    
                    # Try to extract day (1-2 digits before month)
                    day_match = re.search(r'(\d{1,2})' + month, remaining)
                    if day_match:
                        day = day_match.group(1).zfill(2)  # Pad to 2 digits if needed
                        
                        # Try to find year after month (2 digits)
                        year_match = re.search(month + r'(\d{2})', remaining)
                        year = year_match.group(1) if year_match else '25'  # Default to current year
                        
                        # Reconstruct date string
                        date_str = f"{day}{month}{year}"
                        
                        # Extract strike - look for numbers after the date
                        date_end_pos = remaining.find(month) + len(month) + len(year)
                        strike_match = re.search(r'\d+', remaining[date_end_pos:])
                        if strike_match:
                            strike_str = strike_match.group(0)
                            
                            # Format with spaces for Groww
                            groww_symbol = f"{base_symbol} {date_str} {strike_str} {option_type}"
                            logger.info(f"Converted to Groww format (alternate method): {groww_symbol}")
                            return groww_symbol
                    break  # Exit month loop if we found a match
    
    # For futures or if we couldn't parse the option symbol
    if exchange == 'NFO' and symbol.endswith('FUT'):
        # Example: NIFTY25APRFUT
        base_match = re.search(r'^[A-Za-z]+', symbol)
        date_match = re.search(r'\d{2}[A-Za-z]{3}', symbol)
        
        if base_match and date_match:
            base_symbol = base_match.group(0)
            date_str = date_match.group(0)
            groww_symbol = f"{base_symbol} {date_str} FUT"
            return groww_symbol
    
    # If all parsing attempts fail, return the original symbol
    # Groww might accept this format directly or provide specific error
    return symbol


def format_groww_to_openalgo_symbol(groww_symbol, exchange):
    """
    Convert Groww symbol format to OpenAlgo symbol format
    
    Args:
        groww_symbol (str): Symbol in Groww format (e.g., "AARTIIND 29MAY25 630 CE")
        exchange (str): Exchange code (NSE, BSE, NFO, etc.)
    
    Returns:
        str: Symbol in OpenAlgo format (e.g., "AARTIIND29MAY25630CE")
    """
    logger.info(f"Converting symbol from Groww to OpenAlgo format: {{groww_symbol}}, {exchange}")
    
    if not groww_symbol:
        return groww_symbol
    
    # Handle special cases for NFO
    if exchange == 'NFO':
        # Remove any extra whitespace and convert to uppercase
        clean_symbol = groww_symbol.strip().upper()
        
        # If already in OpenAlgo format (no spaces), return as is
        if ' ' not in clean_symbol:
            return clean_symbol
        
        # Split the components by spaces
        parts = clean_symbol.split()
        
        # For options (CE/PE)
        if len(parts) >= 4 and parts[-1] in ('CE', 'PE'):
            # Groww Format: BASE DATE STRIKE OPTIONTYPE
            # Example: "AARTIIND 29MAY25 630 CE"
            base_symbol = parts[0]
            date_str = parts[1]      # Format: DDMMMYY (e.g., 29MAY25)
            strike_price = parts[2]  # Strike price as string
            option_type = parts[3]   # CE or PE
            
            # Combine into OpenAlgo format: [BaseSymbol][ExpirationDate][StrikePrice][OptionType]
            # Example: AARTIIND29MAY25630CE
            openalgo_symbol = f"{base_symbol}{date_str}{strike_price}{option_type}"
            logger.info(f"Converted to OpenAlgo format: {openalgo_symbol}")
            return openalgo_symbol
            
        # For futures
        elif len(parts) >= 3 and parts[-1] == 'FUT':
            # Groww Format: BASE DATE FUT (e.g., "NIFTY 29MAY25 FUT")
            base_symbol = parts[0]
            date_str = parts[1]   # Format: DDMMMYY (e.g., 29MAY25)
            
            # Combine into OpenAlgo format: [BaseSymbol][ExpirationDate]FUT
            # Example: NIFTY29MAY25FUT
            openalgo_symbol = f"{base_symbol}{date_str}FUT"
            logger.info(f"Converted to OpenAlgo format: {openalgo_symbol}")
            return openalgo_symbol
        
        # Handle case where option type might be missing
        elif len(parts) == 3:
            # Check if middle part looks like a date (contains a month abbreviation)
            months = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC']
            is_date = any(month in parts[1] for month in months)
            
            if is_date:
                try:
                    # Try to parse the third part as a number (strike)
                    float(parts[2])
                    # If successful, assume it's an options contract
                    base_symbol = parts[0]
                    date_str = parts[1]
                    strike_price = parts[2]
                    
                    # Determine if it's likely a CE or PE based on context
                    # Default to CE (can be adjusted based on specific requirements)
                    option_type = "CE"  
                    
                    # Combine into standard format
                    openalgo_symbol = f"{base_symbol}{date_str}{strike_price}{option_type}"
                    logger.info(f"Converted to OpenAlgo format (assumed {{option_type}}): {openalgo_symbol}")
                    return openalgo_symbol
                except ValueError:
                    # Third part is not a number, might not be an option
                    pass
    
    # If we can't parse or it's not a special case, return as is
    return clean_symbol.replace(' ', '')


def find_symbol_by_token(token, exchange):
    """
    Find symbol in DB by token and exchange
    
    Args:
        token (str): Token ID
        exchange (str): Exchange code
    
    Returns:
        str: Symbol in OpenAlgo format, or None if not found
    """
    result = db_session.query(SymToken).filter_by(token=token, exchange=exchange).first()
    if result:
        return result.symbol
    return None


def find_token_by_symbol(symbol, exchange):
    """
    Find token in DB by symbol and exchange
    
    Args:
        symbol (str): Symbol in either OpenAlgo or Groww format
        exchange (str): Exchange code
    
    Returns:
        str: Token ID, or None if not found
    """
    # First try with the symbol as provided
    result = db_session.query(SymToken).filter_by(symbol=symbol, exchange=exchange).first()
    if result:
        return result.token
    
    # If not found and it's an NFO symbol, try with formatted version
    if exchange == 'NFO':
        # Try with OpenAlgo format if it was in Groww format
        openalgo_symbol = format_groww_to_openalgo_symbol(symbol, exchange)
        if openalgo_symbol != symbol:
            result = db_session.query(SymToken).filter_by(symbol=openalgo_symbol, exchange=exchange).first()
            if result:
                return result.token
        
        # Try with Groww format if it was in OpenAlgo format
        groww_symbol = format_openalgo_to_groww_symbol(symbol, exchange)
        if groww_symbol != symbol:
            result = db_session.query(SymToken).filter_by(symbol=groww_symbol, exchange=exchange).first()
            if result:
                return result.token
    
    # Check the brsymbol field as a fallback
    result = db_session.query(SymToken).filter_by(brsymbol=symbol, exchange=exchange).first()
    if result:
        return result.token
        
    return None

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
                        logger.info("Symbol is missing, empty, or null")
                    else:
                        valid_records.append(record)
            
            if valid_records:
                db_session.bulk_insert_mappings(SymToken, valid_records)
                db_session.commit()
                logger.info(f"Bulk insert completed successfully with {len(valid_records)} new records.")
                
            if invalid_records:
                logger.error(f"Warning: {len(invalid_records)} records failed schema validation and were skipped.")
        else:
            logger.info("No new records to insert.")
    except Exception as e:
        logger.error(f"Error during bulk insert: {e}")
        if hasattr(e, '__cause__'):
            logger.info(f"Caused by: {e.__cause__}")
        db_session.rollback()




def download_groww_instrument_data(output_path):
    """
    Downloads Groww instrument data CSV, replaces headers with expected ones,
    and saves it to the specified output directory.
    Uses shared httpx client with connection pooling for efficient downloads.
    """
    logger.info("Downloading Groww Instrument Data...")

    # Ensure the output directory exists
    os.makedirs(output_path, exist_ok=True)

    # File path for the saved CSV
    file_path = os.path.join(output_path, "master.csv")
    csv_url = "https://growwapi-assets.groww.in/instruments/instrument.csv"

    # Expected headers - Updated to match actual CSV structure
    headers_csv = "exchange,exchange_token,trading_symbol,groww_symbol,name,instrument_type,segment,series,isin,underlying_symbol,underlying_exchange_token,expiry_date,strike_price,lot_size,tick_size,freeze_quantity,is_reserved,buy_allowed,sell_allowed,internal_trading_symbol,is_intraday"
    expected_headers = headers_csv.split(",")

    try:
        # Get the shared httpx client with connection pooling
        client = get_httpx_client()
        
        # Make the API request using the shared client
        response = client.get(csv_url)
        response.raise_for_status()

        content = response.text
        if ',' in content and len(content.splitlines()) > 1:
            # Read CSV using pandas
            df = pd.read_csv(StringIO(content))

            # Replace headers if column count matches
            if len(df.columns) == len(expected_headers):
                df.columns = expected_headers
            else:
                raise ValueError("Downloaded CSV column count does not match expected headers.")

            # Save with new headers
            df.to_csv(file_path, index=False)
            logger.info(f"Successfully saved instruments CSV to: {file_path}")
            return [file_path]
        else:
            raise ValueError("Downloaded content does not appear to be a valid CSV.")
    except Exception as e:
        logger.error(f"Failed to download or process Groww instrument data: {e}")
        raise
    

def reformat_symbol(row):
    # Use trading symbol as base instead of name
    symbol = row['trading_symbol']
    instrument_type = row['instrument_type']
    expiry = row['expiry_date'].replace('/', '').upper()
    
    # For equity and index instruments, use the symbol as is
    if instrument_type in ['EQ','IDX']:
        return symbol
  
    # For futures
    elif instrument_type in ['FUT']:
        # Use regex to extract symbol, day, month, year
        import re
        match = re.match(r"NSE-([A-Z0-9]+)-(\d{2})([A-Za-z]{3})(\d{2})-FUT", row['groww_symbol'])
        if match:
            symbol, day, month, year = match.groups()
            return f"{symbol}{day}{month.upper()}{year}FUT"
    
    # For options
    elif instrument_type in ['CE', 'PE']:
        import re
        # Match format like: NSE-AARTIIND-26Jun25-435-CE
        match = re.match(r"NSE-([A-Z0-9]+)-(\d{2})([A-Za-z]{3})(\d{2})-(\d+)-([CP]E)", row['groww_symbol'])
        if match:
            symbol, day, month, year, strike_price, opt_type = match.groups()
            return f"{symbol}{day}{month.upper()}{year}{strike_price}{opt_type}"
    
    # For any other instrument type, return symbol as is
    else:
        return symbol

# Define the function to apply conditions
def assign_values(row):
    #Paytm Exchange Mappings are simply NSE and BSE. No other complications
    # Handle futures
    if row['exchange'] == 'NSE' and row['segment'] == 'FNO':
        return 'NFO'
    elif row['exchange'] == 'BSE' and row['segment'] == 'FNO':
        return 'BFO'
    
    # Handle indices
    elif row['exchange'] == 'NSE' and row['segment'] == 'IDX':
        return 'NSE_INDEX'
    elif row['exchange'] == 'BSE' and row['segment'] == 'IDX':
        return 'BSE_INDEX'
    else:
        return row['exchange']

def process_groww_data(path):
    """Processes the Groww instruments CSV file to fit the existing database schema."""
    logger.info("Processing Groww Instrument Data")
    
    # Check for both possible file names
    master_file = os.path.join(path, "master.csv")
    instruments_file = os.path.join(path, "instruments.csv")
    
    # Use master.csv if it exists, otherwise try instruments.csv
    if os.path.exists(master_file):
        file_path = master_file
    elif os.path.exists(instruments_file):
        file_path = instruments_file
    else:
        logger.info(f"No instrument files found in {path}")
        return pd.DataFrame()
    
    logger.info(f"Using instrument file: {file_path}")
        
    try:
        # Load the CSV file - from the documentation, we know the CSV format
        # CSV columns: exchange,exchange_token,trading_symbol,groww_symbol,name,instrument_type,segment,series,isin,underlying_symbol,underlying_exchange_token,lot_size,expiry_date,strike_price,tick_size,freeze_quantity,is_reserved,buy_allowed,sell_allowed,feed_key
        logger.info(f"Loading CSV file from {file_path}")
        # Specify dtypes for columns with known types to avoid mixed type warnings
        dtype_dict = {
            'exchange': str,
            'exchange_token': str,  # Keep as string to preserve leading zeros
            'trading_symbol': str,
            'groww_symbol': str,
            'name': str,
            'instrument_type': str,
            'segment': str,
            'series': str,
            'isin': str,
            'underlying_symbol': str,
            'underlying_exchange_token': str,
            'lot_size': float,  # Convert to numeric later
            'expiry_date': str,
            'strike_price': float,  # Convert to numeric later
            'tick_size': float,  # Convert to numeric later
        }
        df = pd.read_csv(file_path, low_memory=False, dtype=dtype_dict)
        
        logger.info(f"Loaded {len(df)} instruments from CSV file")
        logger.info("CSV columns: {")
        
        # Create a mapping from Groww CSV columns to our database columns
        column_mapping = {
            'exchange': 'brexchange',            # Broker exchange (NSE, BSE, etc.)
            'exchange_token': 'token',          # Token ID
            'trading_symbol': 'brsymbol',        # Broker-specific symbol
            'groww_symbol': 'groww_symbol',      # Groww-specific symbol (keep for reference)
            'name': 'groww_symbol',                     # Instrument name
            'instrument_type': 'instrument_type', # Instrument type from Groww
            'segment': 'segment',               # Segment (CASH, FNO)
            'series': 'series',                 # Series (EQ, etc.)
            'isin': 'isin',                     # ISIN code
            'underlying_symbol': 'underlying',   # Underlying symbol for derivatives
            'lot_size': 'lotsize',              # Lot size
            'expiry_date': 'expiry',            # Expiry date
            'strike_price': 'strike',           # Strike price
            'tick_size': 'tick_size'            # Tick size
        }
        
        # Rename columns based on the mapping
        df_mapped = pd.DataFrame()
        for src, dest in column_mapping.items():
            if src in df.columns:
                df_mapped[dest] = df[src]
        
        # Add a symbol column based on trading_symbol
        df_mapped['symbol'] = df['trading_symbol']
        
        # Replace specific index symbols with standardized names
        symbol_replacements = {
            'NIFTYJR': 'NIFTYNXT50',
            'NIFTYMIDSELECT': 'MIDCPNIFTY'
        }
        
        # Apply replacements
        df_mapped['symbol'] = df_mapped['symbol'].replace(symbol_replacements)
        
        # Ensure all required columns exist
        required_cols = ['symbol', 'brsymbol', 'name', 'brexchange', 'token', 'lotsize', 'expiry', 'strike', 'tick_size']
        for col in required_cols:
            if col not in df_mapped.columns:
                df_mapped[col] = ''
        
        # Swap lot_size and strike as they're reversed in the input data
        # Store the correctly mapped values using a temporary column
        df_mapped['temp_strike'] = pd.to_numeric(df_mapped['strike'], errors='coerce').fillna(0)
        df_mapped['lotsize'] = pd.to_numeric(df_mapped['lotsize'], errors='coerce').fillna(1).astype(int)
        df_mapped['strike'] = df_mapped['temp_strike']
        df_mapped.drop('temp_strike', axis=1, inplace=True)
        df_mapped['tick_size'] = pd.to_numeric(df_mapped['tick_size'], errors='coerce').fillna(0.05)
        
        # Map instrument types directly from Groww's data
        # We want CE, PE, FUT values to be preserved as is
        instrument_type_map = {
            'EQ': 'EQ',       # Equity
            'IDX': 'INDEX',   # Index
            'FUT': 'FUT',     # Futures
            'CE': 'CE',       # Call Options (keep original value)
            'PE': 'PE',       # Put Options (keep original value)
            'ETF': 'EQ',      # ETF
            'CURR': 'CUR',    # Currency
            'COM': 'COM'      # Commodity
        }
        
        # Map instrument types based on Groww's instrument_type field
        df_mapped['instrumenttype'] = df['instrument_type'].map(instrument_type_map)
        
        # For rows with missing instrumenttype, try to determine from segment and other fields
        missing_type_mask = df_mapped['instrumenttype'].isna()
        
        # For CASH segment, assume equity
        cash_mask = missing_type_mask & (df['segment'] == 'CASH')
        df_mapped.loc[cash_mask, 'instrumenttype'] = 'EQ'
        
        # For FNO segment, determine by presence of strike_price
        fno_mask = missing_type_mask & (df['segment'] == 'FNO')
        df_mapped.loc[fno_mask & (df['strike_price'] > 0), 'instrumenttype'] = 'OPT'  # Has strike price = option
        df_mapped.loc[fno_mask & (df['strike_price'] == 0), 'instrumenttype'] = 'FUT'  # No strike price = future
        
        # Fill any remaining missing instrumenttype with 'EQ'
        df_mapped['instrumenttype'] = df_mapped['instrumenttype'].fillna('EQ')
        
        # First set the brexchange directly from the original exchange
        df_mapped['brexchange'] = df['exchange']
        
        # Map exchanges based on rules
        # 1. If exchange is NSE and segment is FNO, then exchange should be NFO
        # 2. If exchange is BSE and segment is FNO, then exchange should be BFO
        # 3. If exchange is NSE and segment is IDX, then exchange should be NSE_INDEX  
        # 4. If exchange is BSE and segment is IDX, then exchange should be BSE_INDEX
        
        # Initialize exchange with original exchange value
        df_mapped['exchange'] = df['exchange']
        
        # Apply mapping rules
        # FNO segments to NFO/BFO
        fno_nse_mask = (df['exchange'] == 'NSE') & (df['segment'] == 'FNO')
        fno_bse_mask = (df['exchange'] == 'BSE') & (df['segment'] == 'FNO')
        df_mapped.loc[fno_nse_mask, 'exchange'] = 'NFO'
        df_mapped.loc[fno_bse_mask, 'exchange'] = 'BFO'
        
        # IDX segments to NSE_INDEX/BSE_INDEX
        idx_nse_mask = (df['exchange'] == 'NSE') & ((df['segment'] == 'IDX') | (df['instrument_type'] == 'IDX'))
        idx_bse_mask = (df['exchange'] == 'BSE') & ((df['segment'] == 'IDX') | (df['instrument_type'] == 'IDX'))
        df_mapped.loc[idx_nse_mask, 'exchange'] = 'NSE_INDEX'
        df_mapped.loc[idx_bse_mask, 'exchange'] = 'BSE_INDEX'
        
        # Special handling for indices
        # Make sure indices have instrumenttype=INDEX
        index_mask = (df['instrument_type'] == 'IDX') | (df['segment'] == 'IDX')
        df_mapped.loc[index_mask, 'instrumenttype'] = 'INDEX'
        
        # Format the symbol for F&O (NFO) instruments to match OpenAlgo format
        def format_fo_symbol(row):
            # Skip non-FNO instruments or those with missing expiry
            if row['brexchange'] != 'NSE' or pd.isna(row['expiry']) or row['expiry'] == '':
                return row['symbol']
                
            # For segment='FNO', format according to OpenAlgo standard
            if 'segment' in df.columns and df.loc[row.name, 'segment'] == 'FNO':
                try:
                    # Format expiry date (assuming yyyy-mm-dd format in input)
                    expiry_date = pd.to_datetime(row['expiry'])
                    expiry_str = expiry_date.strftime('%d%b%y').upper()
                    
                    # Get underlying symbol
                    symbol = row['underlying'] if 'underlying' in row and not pd.isna(row['underlying']) else row['symbol'].split('-')[0] if '-' in row['symbol'] else row['symbol']
                    
                    # For futures
                    if row['instrumenttype'] == 'FUT':
                        return f"{symbol}{expiry_str}FUT"
                    
                    # For options
                    elif row['instrumenttype'] == 'PE' or 'CE':
                        # Determine strike price
                        strike = str(int(row['strike'])) if not pd.isna(row['strike']) else '0'
                        
                        # Determine option type (CE/PE)
                        option_type = ''
                        if 'instrument_type' in df.columns:
                            instrument_type = df.loc[row.name, 'instrument_type']
                            option_type = 'CE' if instrument_type == 'CE' else 'PE' if instrument_type == 'PE' else ''
                        
                        if option_type:
                            return f"{symbol}{expiry_str}{strike}{option_type}"
                except Exception as e:
                    logger.error(f"Error formatting F&O symbol: {e}")
                    
            # Return original symbol if formatting fails
            return row['symbol']
        
        # Apply F&O symbol formatting
        df_mapped['symbol'] = df_mapped.apply(format_fo_symbol, axis=1)
        
        logger.info(f"Processed {len(df_mapped)} instruments")
        return df_mapped
        
    except Exception as e:
        logger.error(f"Error processing Groww instrument data: {e}")
        return pd.DataFrame()
    
    # Map instrument types to OpenAlgo standard types
    instrument_type_map = {
        'EQUITY': 'EQ',
        'INDEX': 'INDEX',
        'FUTURE': 'FUT',
        'CALL': 'OPT',
        'PUT': 'OPT',
        'ETF': 'EQ',
        'CURRENCY': 'CUR',
        'COMMODITY': 'COM'
    }
    
    # Apply instrument type mapping
    all_instruments['instrumenttype'] = all_instruments['instrument_type'].map(instrument_type_map).fillna('EQ')
    
    # Map exchanges to OpenAlgo standard exchanges
    exchange_map = {
        'NSE': 'NSE',
        'BSE': 'BSE',
        'NFO': 'NFO',
        'MCX': 'MCX',
        'CDS': 'CDS'
    }
    
    # Apply exchange mapping
    all_instruments['exchange'] = all_instruments['brexchange'].map(exchange_map).fillna(all_instruments['brexchange'])
    
    # Special handling for indices
    # Mark indices based on name patterns or specific flags in the data
    index_patterns = ['NIFTY', 'SENSEX', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY']
    
    for pattern in index_patterns:
        index_mask = all_instruments['symbol'].str.contains(pattern, case=False, na=False)
        all_instruments.loc[index_mask, 'instrumenttype'] = 'INDEX'
        all_instruments.loc[index_mask, 'exchange'] = 'NSE_INDEX'
    
    # Format specific fields
    all_instruments['expiry'] = all_instruments['expiry'].fillna('')
    all_instruments['strike'] = pd.to_numeric(all_instruments['strike'].fillna(0), errors='coerce')
    all_instruments['lotsize'] = pd.to_numeric(all_instruments['lotsize'].fillna(1), errors='coerce').astype(int)
    all_instruments['tick_size'] = pd.to_numeric(all_instruments['tick_size'].fillna(0.05), errors='coerce')
    
    # Ensure brsymbol is not empty - use symbol if needed
    all_instruments.loc[all_instruments['brsymbol'].isna() | (all_instruments['brsymbol'] == ''), 'brsymbol'] = \
        all_instruments.loc[all_instruments['brsymbol'].isna() | (all_instruments['brsymbol'] == ''), 'symbol']
    
    # For F&O instruments, format the symbol in OpenAlgo format
    fo_mask = all_instruments['exchange'] == 'NFO'
    if fo_mask.any():
        # Format F&O symbols according to OpenAlgo standard
        def format_fo_symbol(row):
            if pd.isna(row['expiry']) or row['expiry'] == '':
                return row['symbol']
                
            # Format expiry date to standard format (e.g., 25MAY23)
            try:
                from datetime import datetime
                expiry_date = pd.to_datetime(row['expiry'])
                expiry_str = expiry_date.strftime('%d%b%y').upper()
            except:
                expiry_str = row['expiry']
            
            # For futures
            if row['instrumenttype'] == 'FUT':
                return f"{row['symbol']}{expiry_str}FUT"
            
            # For options
            elif row['instrumenttype'] == 'OPT':
                strike = str(int(row['strike'])) if not pd.isna(row['strike']) else '0'
                option_type = 'CE' if 'option_type' in row and row['option_type'].upper() == 'CE' else 'PE'
                return f"{row['symbol']}{expiry_str}{strike}{option_type}"
            
            return row['symbol']
        
        all_instruments.loc[fo_mask, 'symbol'] = all_instruments[fo_mask].apply(format_fo_symbol, axis=1)
    
    # Create final DataFrame with required columns
    token_df = pd.DataFrame({
        'symbol': all_instruments['symbol'],
        'brsymbol': all_instruments['brsymbol'],
        'name': all_instruments['name'],
        'exchange': all_instruments['exchange'],
        'brexchange': all_instruments['brexchange'],
        'token': all_instruments['token'],
        'expiry': all_instruments['expiry'],
        'strike': all_instruments['strike'],
        'lotsize': all_instruments['lotsize'],
        'instrumenttype': all_instruments['instrumenttype'],
        'tick_size': all_instruments['tick_size']
    })
    
    # Remove duplicates
    token_df = token_df.drop_duplicates(subset=['symbol', 'exchange'], keep='first')
    
    logger.info(f"Processed {len(token_df)} Groww instruments")
    return token_df

def delete_groww_temp_data(output_path):
    """Delete only Groww-specific temporary files created during instrument data download"""
    try:
        # List of Groww-specific files to delete
        groww_files = ['master.csv', 'groww_instruments.csv', 'groww_master.csv']
        
        # Check each Groww-specific file
        for filename in groww_files:
            file_path = os.path.join(output_path, filename)
            # Check if the file exists and delete it
            if os.path.isfile(file_path):
                os.remove(file_path)
                logger.info(f"Deleted Groww temporary file: {file_path}")
        
        # Check if the directory is now empty
        if not os.listdir(output_path):
            os.rmdir(output_path)
            logger.info(f"Deleted empty directory: {output_path}")
    except Exception as e:
        logger.error(f"Error deleting temporary files: {e}")

def master_contract_download():
    logger.info("Downloading Master Contract")
    
    output_path = 'tmp'
    try:
        # Step 1: Download the instrument data
        download_groww_instrument_data(output_path)
        
        # Step 2: Clear existing data
        delete_symtoken_table()
        
        # Step 3: Process the downloaded data
        token_df = process_groww_data(output_path)
        
        # Step 4: Check if dataframe has required columns
        required_cols = ['symbol', 'brsymbol', 'exchange', 'brexchange', 'token', 'name', 'expiry', 'strike', 'lotsize', 'instrumenttype', 'tick_size']
        missing_cols = [col for col in required_cols if col not in token_df.columns]
        
        if missing_cols:
            logger.info(f"Missing required columns in processed data: {missing_cols}")
            # Add missing columns with default values
            for col in missing_cols:
                if col in ['strike', 'tick_size']:
                    token_df[col] = 0.0
                elif col in ['lotsize']:
                    token_df[col] = 1
                else:
                    token_df[col] = ''
        
        # Ensure numeric columns are properly converted
        token_df['strike'] = pd.to_numeric(token_df['strike'], errors='coerce').fillna(0)
        token_df['lotsize'] = pd.to_numeric(token_df['lotsize'], errors='coerce').fillna(1).astype(int)
        token_df['tick_size'] = pd.to_numeric(token_df['tick_size'], errors='coerce').fillna(0.05)
        
        # Step 5: Add OpenAlgo symbols where needed (converting Groww format to OpenAlgo format)
        # Identify rows that need conversion (NFO options and futures)
        nfo_options = token_df[
            (token_df['exchange'] == 'NFO') & 
            (token_df['instrumenttype'].isin(['CE', 'PE']))
        ]
        
        for idx, row in nfo_options.iterrows():
            # Convert the broker symbol to OpenAlgo format if spaces are detected
            if ' ' in row['brsymbol']:
                token_df.at[idx, 'symbol'] = format_groww_to_openalgo_symbol(row['brsymbol'], 'NFO')
        
        # Step 6: Insert into database
        logger.info(f"Inserting {len(token_df)} records into database")
        copy_from_dataframe(token_df)
        
        # Step 7: Cleanup
        delete_groww_temp_data(output_path)
        
        # Verify data was inserted
        count = db_session.query(SymToken).count()
        logger.info(f"Total records in database after insertion: {count}")
        
        return socketio.emit('master_contract_download', {'status': 'success', 'message': f'Successfully downloaded and inserted {count} symbols'})
    
    except Exception as e:
        import traceback
        logger.error(f"Error in master_contract_download: {e}")
        logger.info(f"{traceback.format_exc()}")
        return socketio.emit('master_contract_download', {'status': 'error', 'message': str(e)})



def search_symbols(symbol, exchange):
    return SymToken.query.filter(SymToken.symbol.like(f'%{symbol}%'), SymToken.exchange == exchange).all()