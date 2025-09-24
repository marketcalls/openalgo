#database/master_contract_db.py

import os
import pandas as pd
import requests
import gzip
import shutil
import re
from datetime import datetime

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

def download_csv_motilal_data(exchange, output_path):
    """
    Downloads a CSV file from Motilal Oswal API for the specified exchange and saves it to the specified path.
    """
    logger.info(f"Downloading CSV data for exchange: {exchange}")
    
    # Use production or UAT URL based on environment
    is_testing = os.getenv('MOTILAL_USE_UAT', 'false').lower() == 'true'
    if is_testing:
        base_url = "https://openapi.motilaloswaluat.com/getscripmastercsv"
    else:
        base_url = "https://openapi.motilaloswal.com/getscripmastercsv"
    
    url = f"{base_url}?name={exchange}"
    
    try:
        response = requests.get(url, timeout=30)  # timeout after 30 seconds for CSV files
        if response.status_code == 200:  # Successful download
            with open(output_path, 'wb') as f:
                f.write(response.content)
            logger.info(f"Download complete for {exchange}")
            return True
        else:
            logger.error(f"Failed to download data for {exchange}. Status code: {response.status_code}")
            return False
    except Exception as e:
        logger.error(f"Error downloading CSV for {exchange}: {str(e)}")
        return False


def convert_date(date_str):
    # Convert from '19MAR2024' to '19-MAR-24'
    try:
        return datetime.strptime(date_str, '%d%b%Y').strftime('%d-%b-%y')
    except ValueError:
        # Return the original date if it doesn't match the format
        return date_str

def convert_date_for_symbol(date_str):
    # Convert from '19MAR2024' or '19-MAR-24' to '19MAR24' for OpenAlgo symbol format
    try:
        # Try parsing the full format first
        if len(date_str) == 9 and date_str[2].isalpha():  # '19MAR2024'
            return datetime.strptime(date_str, '%d%b%Y').strftime('%d%b%y').upper()
        elif '-' in date_str:  # '19-MAR-24'
            return datetime.strptime(date_str, '%d-%b-%y').strftime('%d%b%y').upper()
        else:
            # Return as is if format is unknown
            return date_str.upper().replace('-', '')
    except ValueError:
        # Return the original date if it doesn't match any format
        return date_str.upper().replace('-', '')

def process_motilal_csv(path, exchange_name):
    """
    Processes the Motilal Oswal CSV file to fit the existing database schema and OpenAlgo symbol format.
    Args:
    path (str): The file path of the downloaded CSV data.
    exchange_name (str): The exchange name for this CSV file.

    Returns:
    DataFrame: The processed DataFrame ready to be inserted into the database.
    """
    try:
        # Read CSV data into a DataFrame
        df = pd.read_csv(path)
        
        logger.info(f"Processing {len(df)} records from {exchange_name}")
        
        # Map Motilal Oswal CSV columns to database schema
        # Based on the CSV format: exchange, exchangename, scripcode, scripname, marketlot, scripshortname, issuspended, 
        # instrumentname, expirydate, strikeprice, optiontype, markettype, foexposurepercent, ticksize, 
        # scripisinno, indicesidentifier, isbanscrip, scripfullname, facevalue, calevel, maxqtyperorder
        column_mapping = {
            'exchange': 'broker_exchange_code', # Broker's internal exchange code
            'exchangename': 'brexchange',       # Exchange name (NSE, NSEFO, etc.) - this goes to brexchange
            'scripcode': 'token',               # Instrument token/code
            'scripname': 'brsymbol',           # Broker symbol name
            'scripfullname': 'name',           # Full name of the instrument
            'marketlot': 'lotsize',            # Market lot size
            'instrumentname': 'instrumenttype', # Instrument type (EQ, FUT, CE, PE, etc.)
            'expirydate': 'expiry',            # Expiry date
            'strikeprice': 'strike',           # Strike price
            'ticksize': 'tick_size'            # Tick size
        }
        
        # Store original columns before renaming
        if 'exchange' in df.columns:
            df['exchange_orig'] = df['exchange']
        if 'scripshortname' in df.columns:
            df['scripshortname_orig'] = df['scripshortname']
            
        # Rename columns
        df = df.rename(columns=column_mapping)
        
        # Map Motilal exchange codes to OpenAlgo standard exchange codes
        # Based on the exchange_name parameter and instrument types
        df['exchange'] = exchange_name
        
        # Map to OpenAlgo standard exchanges based on brexchange (which contains exchangename)
        if 'brexchange' in df.columns:
            exchange_mapping = {
                'NSE': 'NSE',      # NSE Cash
                'NSEFO': 'NFO',    # NSE F&O  
                'BSE': 'BSE',      # BSE Cash
                'BSEFO': 'BFO',    # BSE F&O
                'MCX': 'MCX'       # MCX Commodities
            }
            df['exchange'] = df['brexchange'].map(exchange_mapping).fillna(exchange_name)
        
        # Handle index instruments - map to NSE_INDEX or BSE_INDEX
        if 'instrumenttype' in df.columns:
            # Map index instruments to appropriate index exchanges
            df.loc[(df['instrumenttype'].isin(['INDEX', 'AMXIDX'])) & (df['exchange'] == 'NSE'), 'exchange'] = 'NSE_INDEX'
            df.loc[(df['instrumenttype'].isin(['INDEX', 'AMXIDX'])) & (df['exchange'] == 'BSE'), 'exchange'] = 'BSE_INDEX'
            df.loc[(df['instrumenttype'].isin(['INDEX', 'AMXIDX'])) & (df['exchange'] == 'MCX'), 'exchange'] = 'MCX_INDEX'
        
        # brexchange is now properly mapped from 'exchangename' column via column_mapping
        # No additional assignment needed since it's handled in the mapping
        
        # Create symbol field following OpenAlgo standard format
        # Start with scripshortname if available, otherwise use scripname
        if 'scripshortname_orig' in df.columns:
            df['base_symbol'] = df['scripshortname_orig'].fillna(df['brsymbol'])
        else:
            df['base_symbol'] = df['brsymbol']
        
        # Clean up base symbol - remove common suffixes for equities
        df['base_symbol'] = df['base_symbol'].str.replace('-EQ|-BE|-MF|-SG', '', regex=True)
        
        # Initialize symbol column with base symbol
        df['symbol'] = df['base_symbol']
        
        # Handle missing values and data types
        df['strike'] = pd.to_numeric(df['strike'], errors='coerce').fillna(0.0)
        df['lotsize'] = pd.to_numeric(df['lotsize'], errors='coerce').fillna(1).astype(int)
        df['tick_size'] = pd.to_numeric(df['tick_size'], errors='coerce').fillna(0.01)
        
        # Convert token to string to match database schema
        df['token'] = df['token'].astype(str)
        
        # Handle expiry dates - extract from scripname if not available in expiry column
        if 'expiry' in df.columns:
            df['expiry'] = df['expiry'].fillna('')
            df['expiry'] = df['expiry'].astype(str).str.upper()
            # Convert expiry date format if it's in DDMMMYYYY format (e.g., "19MAR2024")
            df['expiry'] = df['expiry'].apply(lambda x: convert_date(x) if x and x != '' else x)
        else:
            df['expiry'] = ''
            
        # Extract expiry dates from scripname for derivatives when expiry is empty
        # Pattern: "JSWSTEEL 30-Sep-2025 CE 1370" -> extract "30-SEP-2025"
        
        def extract_expiry_from_scripname(scripname):
            if pd.isna(scripname) or scripname == '':
                return ''
            
            # Pattern to match date formats like "30-Sep-2025", "31-Mar-2026", etc.
            date_pattern = r'(\d{1,2}-[A-Za-z]{3}-\d{4})'
            match = re.search(date_pattern, str(scripname))
            
            if match:
                date_str = match.group(1)
                # Convert to uppercase and proper format
                parts = date_str.split('-')
                if len(parts) == 3:
                    day, month, year = parts
                    return f"{day}-{month.upper()}-{year}"  # Convert to DD-MMM-YYYY format
            
            return ''
        
        def extract_strike_from_scripname(scripname):
            if pd.isna(scripname) or scripname == '':
                return 0.0
            
            # Pattern to extract strike price from option names
            # "JSWSTEEL 30-Sep-2025 CE 1370" -> extract 1370
            # Pattern: look for number at the end after CE/PE
            strike_pattern = r'[CP][EP]\s+(\d+(?:\.\d+)?)'
            match = re.search(strike_pattern, str(scripname))
            
            if match:
                try:
                    return float(match.group(1))
                except ValueError:
                    return 0.0
            
            return 0.0
        
        # Apply expiry extraction for derivatives where expiry is empty
        derivatives_mask = df['instrumenttype'].isin(['FUT', 'CE', 'PE', 'FUTCOM', 'FUTCUR', 'FUTIRC', 'OPTCUR', 'OPTIRC', 'OPTFUT'])
        empty_expiry_mask = (df['expiry'] == '') | df['expiry'].isna()
        
        mask_to_extract = derivatives_mask & empty_expiry_mask
        if mask_to_extract.any():
            df.loc[mask_to_extract, 'expiry'] = df.loc[mask_to_extract, 'brsymbol'].apply(extract_expiry_from_scripname)
            
        # Also extract from all derivatives regardless of current expiry value to ensure consistent format
        all_derivatives_mask = df['instrumenttype'].isin(['FUT', 'CE', 'PE', 'FUTCOM', 'FUTCUR', 'FUTIRC', 'OPTCUR', 'OPTIRC', 'OPTFUT'])
        if all_derivatives_mask.any():
            extracted_expiry = df.loc[all_derivatives_mask, 'brsymbol'].apply(extract_expiry_from_scripname)
            # Only update if we successfully extracted a non-empty expiry
            valid_extracted = extracted_expiry != ''
            df.loc[all_derivatives_mask & valid_extracted, 'expiry'] = extracted_expiry[valid_extracted]
            
        # Extract strike price for options where strike is 0 or empty
        options_mask = df['instrumenttype'].isin(['CE', 'PE', 'OPTCUR', 'OPTIRC', 'OPTFUT'])
        empty_strike_mask = (df['strike'] == 0.0) | df['strike'].isna()
        
        mask_to_extract_strike = options_mask & empty_strike_mask
        if mask_to_extract_strike.any():
            df.loc[mask_to_extract_strike, 'strike'] = df.loc[mask_to_extract_strike, 'brsymbol'].apply(extract_strike_from_scripname)
            
        # Handle instrument types
        if 'instrumenttype' not in df.columns or df['instrumenttype'].isna().all():
            df['instrumenttype'] = 'EQ'
        else:
            df['instrumenttype'] = df['instrumenttype'].fillna('EQ')
            
        # Handle option type for CE/PE instruments
        if 'optiontype' in df.columns:
            # If instrumenttype is not set but optiontype is available, use optiontype
            mask = (df['instrumenttype'].isna() | (df['instrumenttype'] == '')) & df['optiontype'].notna()
            df.loc[mask, 'instrumenttype'] = df.loc[mask, 'optiontype']
            
        # Convert symbols to OpenAlgo standard format
        # Following the OpenAlgo symbol format specification
        
        # 1. Handle Futures Symbol Format: [Base Symbol][Expiration Date]FUT
        future_mask = df['instrumenttype'].isin(['FUT', 'FUTCOM', 'FUTCUR', 'FUTIRC'])
        if future_mask.any():
            # For futures, create symbol as [name][expiry]FUT where expiry is in format like 28MAR24
            # Convert expiry dates to OpenAlgo symbol format (e.g., '19-MAR-24' -> '19MAR24')
            df.loc[future_mask, 'symbol'] = (
                df.loc[future_mask, 'base_symbol'] + 
                df.loc[future_mask, 'expiry'].apply(convert_date_for_symbol) + 
                'FUT'
            )
            
        # 2. Handle Options Symbol Format: [Base Symbol][Expiration Date][Strike Price][Option Type]
        option_mask = df['instrumenttype'].isin(['CE', 'PE', 'OPTCUR', 'OPTIRC', 'OPTFUT'])
        if option_mask.any():
            # For options, create symbol as [name][expiry][strike][CE/PE] (e.g., NIFTY28MAR2420800CE)
            # Convert expiry dates to OpenAlgo symbol format (e.g., '19-MAR-24' -> '19MAR24')
            df.loc[option_mask, 'symbol'] = (
                df.loc[option_mask, 'base_symbol'] + 
                df.loc[option_mask, 'expiry'].apply(convert_date_for_symbol) + 
                df.loc[option_mask, 'strike'].astype(str).str.replace(r'\.0$', '', regex=True) + 
                df.loc[option_mask, 'instrumenttype']
            )
            
        # 3. Handle Index Symbols - Map to OpenAlgo standard index names
        index_mask = df['instrumenttype'].isin(['INDEX', 'AMXIDX'])
        if index_mask.any():
            # Map common index names to OpenAlgo standard format
            index_mapping = {
                'NIFTY 50': 'NIFTY',
                'NIFTY': 'NIFTY',
                'NIFTY NEXT 50': 'NIFTYNXT50',
                'NIFTY FIN SERVICE': 'FINNIFTY',
                'NIFTY BANK': 'BANKNIFTY',
                'BANKNIFTY': 'BANKNIFTY',
                'NIFTY MID SELECT': 'MIDCPNIFTY',
                'INDIA VIX': 'INDIAVIX',
                'SENSEX': 'SENSEX',
                'BANKEX': 'BANKEX',
                'SENSEX 50': 'SENSEX50',
                'BSE SENSEX': 'SENSEX'
            }
            
            # Apply index name mapping
            for old_name, new_name in index_mapping.items():
                df.loc[index_mask & (df['base_symbol'].str.upper() == old_name.upper()), 'symbol'] = new_name
            
        # Ensure all required columns exist
        required_columns = ['symbol', 'brsymbol', 'name', 'exchange', 'brexchange', 
                          'token', 'expiry', 'strike', 'lotsize', 'instrumenttype', 'tick_size']
        
        for col in required_columns:
            if col not in df.columns:
                if col == 'name':
                    df[col] = df['brsymbol'] if 'brsymbol' in df.columns else ''
                elif col == 'brexchange':
                    # brexchange should already be mapped from 'exchangename', fallback to exchange_name if needed
                    df[col] = exchange_name
                elif col == 'symbol':
                    df[col] = df['brsymbol'] if 'brsymbol' in df.columns else ''
                elif col in ['strike', 'tick_size']:
                    df[col] = 0.0
                elif col == 'lotsize':
                    df[col] = 1
                else:
                    df[col] = ''
        
        # Filter out any rows with missing essential data
        df = df.dropna(subset=['token', 'symbol'])
        
        # Remove duplicates based on token
        df = df.drop_duplicates(subset=['token'], keep='first')
        
        # Clean up temporary columns
        temp_columns = ['exchange_orig', 'scripshortname_orig', 'base_symbol', 'broker_exchange_code']
        for col in temp_columns:
            if col in df.columns:
                df = df.drop(columns=[col])
        
        # Select only the columns we need for the database
        df = df[required_columns]
        
        logger.info(f"Processed {len(df)} valid records for {exchange_name}")
        return df
        
    except Exception as e:
        logger.error(f"Error processing CSV for {exchange_name}: {str(e)}")
        return pd.DataFrame()

def delete_motilal_temp_data(output_path):
    """Delete temporary CSV files after processing"""
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
    """Download master contract data from Motilal Oswal for all supported exchanges"""
    logger.info("Downloading Master Contract from Motilal Oswal")
    
    # Motilal Oswal supported exchanges
    exchanges = ['NSE', 'NSEFO', 'BSE', 'MCX', 'BSEFO']
    
    try:
        # Create tmp directory if it doesn't exist
        os.makedirs('tmp', exist_ok=True)
        
        # Clear existing data
        delete_symtoken_table()
        
        all_dataframes = []
        
        # Download and process each exchange
        for exchange in exchanges:
            output_path = f'tmp/motilal_{exchange.lower()}.csv'
            
            logger.info(f"Downloading {exchange} data...")
            
            if download_csv_motilal_data(exchange, output_path):
                # Process the CSV file
                token_df = process_motilal_csv(output_path, exchange)
                
                if not token_df.empty:
                    all_dataframes.append(token_df)
                    logger.info(f"Successfully processed {len(token_df)} records from {exchange}")
                else:
                    logger.warning(f"No valid data found for {exchange}")
                
                # Clean up the temporary file
                delete_motilal_temp_data(output_path)
            else:
                logger.error(f"Failed to download data for {exchange}")
        
        # Combine all dataframes
        if all_dataframes:
            combined_df = pd.concat(all_dataframes, ignore_index=True)
            logger.info(f"Total records to insert: {len(combined_df)}")
            
            # Insert into database
            copy_from_dataframe(combined_df)
            
            return socketio.emit('master_contract_download', {
                'status': 'success', 
                'message': f'Successfully Downloaded {len(combined_df)} records from {len(all_dataframes)} exchanges'
            })
        else:
            error_msg = "No data downloaded from any exchange"
            logger.error(error_msg)
            return socketio.emit('master_contract_download', {
                'status': 'error', 
                'message': error_msg
            })
    
    except Exception as e:
        error_msg = f"Error in master contract download: {str(e)}"
        logger.error(error_msg)
        return socketio.emit('master_contract_download', {
            'status': 'error', 
            'message': error_msg
        })



def search_symbols(symbol, exchange):
    return SymToken.query.filter(SymToken.symbol.like(f'%{symbol}%'), SymToken.exchange == exchange).all()
