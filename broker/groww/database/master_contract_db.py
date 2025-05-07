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
    print("Initializing Master Contract DB")
    Base.metadata.create_all(bind=engine)

def delete_symtoken_table():
    print("Deleting Symtoken Table")
    SymToken.query.delete()
    db_session.commit()

def copy_from_dataframe(df):
    print("Performing Bulk Insert")
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
                        print(f"Schema validation failed for record: {record}")
                        print(f"Symbol is missing, empty, or null")
                    else:
                        valid_records.append(record)
            
            if valid_records:
                db_session.bulk_insert_mappings(SymToken, valid_records)
                db_session.commit()
                print(f"Bulk insert completed successfully with {len(valid_records)} new records.")
                
            if invalid_records:
                print(f"Warning: {len(invalid_records)} records failed schema validation and were skipped.")
        else:
            print("No new records to insert.")
    except Exception as e:
        print(f"Error during bulk insert: {e}")
        if hasattr(e, '__cause__'):
            print(f"Caused by: {e.__cause__}")
        db_session.rollback()




def download_groww_instrument_data(output_path):
    """
    Downloads Groww instrument data CSV, replaces headers with expected ones,
    and saves it to the specified output directory.
    """
    print("Downloading Groww Instrument Data...")

    # Ensure the output directory exists
    os.makedirs(output_path, exist_ok=True)

    # File path for the saved CSV
    file_path = os.path.join(output_path, "master.csv")
    csv_url = "https://growwapi-assets.groww.in/instruments/instrument.csv"

    # Expected headers
    headers_csv = "exchange,exchange_token,trading_symbol,groww_symbol,name,instrument_type,segment,series,isin,underlying_symbol,underlying_exchange_token,expiry_date,lot_size,strike_price,tick_size,freeze_quantity,is_reserved,buy_allowed,sell_allowed,feed_key"
    expected_headers = headers_csv.split(",")

    try:
        with httpx.Client() as client:
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
                print(f"Successfully saved instruments CSV to: {file_path}")
                return [file_path]
            else:
                raise ValueError("Downloaded content does not appear to be a valid CSV.")
    except Exception as e:
        print(f"Failed to download or process Groww instrument data: {e}")
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
            return f"{symbol}{day}{month.upper()}{year}{strike_price}{instrument_type}"
    
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
    print("Processing Groww Instrument Data")
    
    # Check for both possible file names
    master_file = os.path.join(path, "master.csv")
    instruments_file = os.path.join(path, "instruments.csv")
    
    # Use master.csv if it exists, otherwise try instruments.csv
    if os.path.exists(master_file):
        file_path = master_file
    elif os.path.exists(instruments_file):
        file_path = instruments_file
    else:
        print(f"No instrument files found in {path}")
        return pd.DataFrame()
    
    print(f"Using instrument file: {file_path}")
        
    try:
        # Load the CSV file - from the documentation, we know the CSV format
        # CSV columns: exchange,exchange_token,trading_symbol,groww_symbol,name,instrument_type,segment,series,isin,underlying_symbol,underlying_exchange_token,lot_size,expiry_date,strike_price,tick_size,freeze_quantity,is_reserved,buy_allowed,sell_allowed,feed_key
        print(f"Loading CSV file from {file_path}")
        df = pd.read_csv(file_path, low_memory=False)
        
        print(f"Loaded {len(df)} instruments from CSV file")
        print(f"CSV columns: {', '.join(df.columns)}")
        
        # Create a mapping from Groww CSV columns to our database columns
        column_mapping = {
            'exchange': 'brexchange',            # Broker exchange (NSE, BSE, etc.)
            'exchange_token': 'token',          # Token ID
            'trading_symbol': 'brsymbol',        # Broker-specific symbol
            'groww_symbol': 'groww_symbol',      # Groww-specific symbol (keep for reference)
            'name': 'name',                     # Instrument name
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
        df_mapped['temp_strike'] = pd.to_numeric(df_mapped['lotsize'], errors='coerce').fillna(0)
        df_mapped['lotsize'] = pd.to_numeric(df_mapped['strike'], errors='coerce').fillna(1).astype(int)
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
                    elif row['instrumenttype'] == 'OPT':
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
                    print(f"Error formatting F&O symbol: {e}")
                    
            # Return original symbol if formatting fails
            return row['symbol']
        
        # Apply F&O symbol formatting
        df_mapped['symbol'] = df_mapped.apply(format_fo_symbol, axis=1)
        
        print(f"Processed {len(df_mapped)} instruments")
        return df_mapped
        
    except Exception as e:
        print(f"Error processing Groww instrument data: {str(e)}")
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
    
    print(f"Processed {len(token_df)} Groww instruments")
    return token_df

def delete_groww_temp_data(output_path):
    """Delete temporary files created during instrument data download"""
    try:
        # Check each file in the directory
        for filename in os.listdir(output_path):
            # Construct the full file path
            file_path = os.path.join(output_path, filename)
            # Check if it is a file (not a directory)
            if os.path.isfile(file_path):
                os.remove(file_path)
                print(f"Deleted temporary file: {file_path}")
        
        # Check if the directory is now empty
        if not os.listdir(output_path):
            os.rmdir(output_path)
            print(f"Deleted empty directory: {output_path}")
    except Exception as e:
        print(f"Error deleting temporary files: {str(e)}")

def master_contract_download():
    print("Downloading Master Contract")
    

    output_path = 'tmp'
    try:
        download_groww_instrument_data(output_path)
        delete_symtoken_table()
        token_df = process_groww_data(output_path)
        copy_from_dataframe(token_df)
        delete_groww_temp_data(output_path)
        #token_df['token'] = pd.to_numeric(token_df['token'], errors='coerce').fillna(-1).astype(int)
        
        #token_df = token_df.drop_duplicates(subset='symbol', keep='first')
        
        return socketio.emit('master_contract_download', {'status': 'success', 'message': 'Successfully Downloaded'})

    
    except Exception as e:
        print(str(e))
        return socketio.emit('master_contract_download', {'status': 'error', 'message': str(e)})



def search_symbols(symbol, exchange):
    return SymToken.query.filter(SymToken.symbol.like(f'%{symbol}%'), SymToken.exchange == exchange).all()
