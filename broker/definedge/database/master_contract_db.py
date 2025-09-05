#database/master_contract_db.py

import os
import pandas as pd
import numpy as np
import gzip
import shutil
import json
import io
from datetime import datetime
from utils.httpx_client import get_httpx_client

from sqlalchemy import create_engine, Column, Integer, String, Float, Sequence, Index
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from database.auth_db import get_auth_token
from database.user_db import find_user_by_username
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

def init_db():
    Base.metadata.create_all(bind=engine)

def delete_symtoken_table():
    """Delete all records from symtoken table"""
    try:
        db_session.query(SymToken).delete()
        db_session.commit()
        logger.info("All records deleted from symtoken table")
    except Exception as e:
        logger.error(f"Error deleting symtoken table: {e}")
        db_session.rollback()

def copy_from_dataframe(df):
    """Copy dataframe to database"""
    try:
        df.to_sql('symtoken', con=engine, if_exists='append', index=False)
        logger.info(f"Inserted {len(df)} records into symtoken table")
    except Exception as e:
        logger.error(f"Error copying dataframe to database: {e}")

def download_definedge_master_files(auth_token, output_path):
    """Download master contract files from DefinedGe Securities using shared connection pooling"""
    try:
        # DefinedGe provides all master contracts in a single ZIP file
        # No authentication required for public master file
        master_url = "https://app.definedgesecurities.com/public/allmaster.zip"
        
        # Get the shared httpx client with connection pooling
        client = get_httpx_client()
        
        # Download the ZIP file
        logger.info("Downloading DefinedGe master contract ZIP file")
        response = client.get(master_url, timeout=30)
        response.raise_for_status()  # Raise exception for error status codes
        
        zip_filepath = os.path.join(output_path, "allmaster.zip")
        
        # Save the ZIP file
        with open(zip_filepath, 'wb') as f:
            f.write(response.content)
        
        logger.info("Downloaded DefinedGe master contract ZIP file")
        
        # Extract the ZIP file
        import zipfile
        with zipfile.ZipFile(zip_filepath, 'r') as zip_ref:
            zip_ref.extractall(output_path)
        
        logger.info("Extracted DefinedGe master contract files")
        
        # Remove the ZIP file
        os.remove(zip_filepath)
        
        return True

    except Exception as e:
        logger.error(f"Error downloading DefinedGe master files: {e}")
        return False

def process_definedge_nse_csv(path):
    """Process DefinedGe NSE master file"""
    try:
        df = pd.read_csv(path)

        # Map DefinedGe NSE columns to OpenAlgo schema
        # Assuming DefinedGe uses standard format: Symbol, Token, Name, etc.
        processed_df = pd.DataFrame()

        if 'Symbol' in df.columns:
            processed_df['symbol'] = df['Symbol'] + '-EQ'  # OpenAlgo format
            processed_df['brsymbol'] = df['Symbol']  # DefinedGe format

        if 'Token' in df.columns:
            processed_df['token'] = df['Token'].astype(str)

        if 'Name' in df.columns:
            processed_df['name'] = df['Name']

        processed_df['exchange'] = 'NSE'
        processed_df['brexchange'] = 'NSE'
        processed_df['expiry'] = ''
        processed_df['strike'] = 0.0
        processed_df['lotsize'] = df.get('LotSize', 1)
        processed_df['instrumenttype'] = 'EQ'
        processed_df['tick_size'] = df.get('TickSize', 0.05)

        return processed_df

    except Exception as e:
        logger.error(f"Error processing NSE CSV: {e}")
        return pd.DataFrame()

def process_definedge_bse_csv(path):
    """Process DefinedGe BSE master file"""
    try:
        df = pd.read_csv(path)

        processed_df = pd.DataFrame()

        if 'Symbol' in df.columns:
            processed_df['symbol'] = df['Symbol']  # BSE doesn't need -EQ suffix
            processed_df['brsymbol'] = df['Symbol']

        if 'Token' in df.columns:
            processed_df['token'] = df['Token'].astype(str)

        if 'Name' in df.columns:
            processed_df['name'] = df['Name']

        processed_df['exchange'] = 'BSE'
        processed_df['brexchange'] = 'BSE'
        processed_df['expiry'] = ''
        processed_df['strike'] = 0.0
        processed_df['lotsize'] = df.get('LotSize', 1)
        processed_df['instrumenttype'] = 'EQ'
        processed_df['tick_size'] = df.get('TickSize', 0.05)

        return processed_df

    except Exception as e:
        logger.error(f"Error processing BSE CSV: {e}")
        return pd.DataFrame()

def process_definedge_nfo_csv(path):
    """Process DefinedGe NFO (derivatives) master file"""
    try:
        df = pd.read_csv(path)

        processed_df = pd.DataFrame()

        if 'TradingSymbol' in df.columns:
            processed_df['symbol'] = df['TradingSymbol']
            processed_df['brsymbol'] = df['TradingSymbol']

        if 'Token' in df.columns:
            processed_df['token'] = df['Token'].astype(str)

        if 'Name' in df.columns:
            processed_df['name'] = df['Name']

        processed_df['exchange'] = 'NFO'
        processed_df['brexchange'] = 'NFO'
        processed_df['expiry'] = df.get('Expiry', '')
        processed_df['strike'] = df.get('StrikePrice', 0.0)
        processed_df['lotsize'] = df.get('LotSize', 1)
        processed_df['instrumenttype'] = df.get('InstrumentType', 'FUT')
        processed_df['tick_size'] = df.get('TickSize', 0.05)

        return processed_df

    except Exception as e:
        logger.error(f"Error processing NFO CSV: {e}")
        return pd.DataFrame()

def process_definedge_cds_csv(path):
    """Process DefinedGe CDS master file"""
    try:
        df = pd.read_csv(path)

        processed_df = pd.DataFrame()

        if 'TradingSymbol' in df.columns:
            processed_df['symbol'] = df['TradingSymbol']
            processed_df['brsymbol'] = df['TradingSymbol']

        if 'Token' in df.columns:
            processed_df['token'] = df['Token'].astype(str)

        processed_df['exchange'] = 'CDS'
        processed_df['brexchange'] = 'CDS'
        processed_df['expiry'] = df.get('Expiry', '')
        processed_df['strike'] = 0.0
        processed_df['lotsize'] = df.get('LotSize', 1)
        processed_df['instrumenttype'] = 'CUR'
        processed_df['tick_size'] = df.get('TickSize', 0.0025)

        return processed_df

    except Exception as e:
        logger.error(f"Error processing CDS CSV: {e}")
        return pd.DataFrame()

def process_definedge_mcx_csv(path):
    """Process DefinedGe MCX master file"""
    try:
        df = pd.read_csv(path)

        processed_df = pd.DataFrame()

        if 'TradingSymbol' in df.columns:
            processed_df['symbol'] = df['TradingSymbol']
            processed_df['brsymbol'] = df['TradingSymbol']

        if 'Token' in df.columns:
            processed_df['token'] = df['Token'].astype(str)

        processed_df['exchange'] = 'MCX'
        processed_df['brexchange'] = 'MCX'
        processed_df['expiry'] = df.get('Expiry', '')
        processed_df['strike'] = 0.0
        processed_df['lotsize'] = df.get('LotSize', 1)
        processed_df['instrumenttype'] = 'COM'
        processed_df['tick_size'] = df.get('TickSize', 1.0)

        return processed_df

    except Exception as e:
        logger.error(f"Error processing MCX CSV: {e}")
        return pd.DataFrame()

def process_definedge_bfo_csv(path):
    """Process DefinedGe BFO master file"""
    try:
        df = pd.read_csv(path)

        processed_df = pd.DataFrame()

        if 'TradingSymbol' in df.columns:
            processed_df['symbol'] = df['TradingSymbol']
            processed_df['brsymbol'] = df['TradingSymbol']

        if 'Token' in df.columns:
            processed_df['token'] = df['Token'].astype(str)

        processed_df['exchange'] = 'BFO'
        processed_df['brexchange'] = 'BFO'
        processed_df['expiry'] = df.get('Expiry', '')
        processed_df['strike'] = df.get('StrikePrice', 0.0)
        processed_df['lotsize'] = df.get('LotSize', 1)
        processed_df['instrumenttype'] = df.get('InstrumentType', 'FUT')
        processed_df['tick_size'] = df.get('TickSize', 0.05)

        return processed_df

    except Exception as e:
        logger.error(f"Error processing BFO CSV: {e}")
        return pd.DataFrame()

def process_definedge_allmaster_csv(path):
    """Process DefinedGe allmaster.csv file containing all symbols"""
    try:
        # Read CSV without headers since the file doesn't have proper column names
        df = pd.read_csv(path, header=None)
        
        if df.empty:
            logger.warning("allmaster.csv is empty")
            return pd.DataFrame()
        
        logger.info(f"Processing allmaster.csv with {len(df)} rows")
        logger.info(f"First row sample: {df.iloc[0].tolist()[:5]}")
        
        # Define column names based on DefinedGe format
        # Based on the sample: ['NFO', '144537', 'ZYDUSLIFE', 'ZYDUSLIFE30SEP25P1360', 'OPTSTK', '30092025', '5', '900', 'PE', '136000', '2', '1', 'Unnamed: 12', '1.000000', 'Unnamed: 14']
        # Format appears to be: Exchange, Token, Name, TradingSymbol, InstrumentType, Expiry, LotSize, TickSize, OptionType, StrikePrice, ...
        column_names = [
            'Exchange', 'Token', 'Name', 'TradingSymbol', 'InstrumentType', 
            'Expiry', 'LotSize', 'TickSize', 'OptionType', 'StrikePrice',
            'Col10', 'Col11', 'Col12', 'PriceFactor', 'Col14'
        ]
        
        # Assign column names (only up to the number of columns we have)
        df.columns = column_names[:len(df.columns)]
        
        processed_df = pd.DataFrame()
        
        # Store broker symbol as is
        processed_df['brsymbol'] = df['TradingSymbol']
        processed_df['token'] = df['Token'].astype(str)
        processed_df['name'] = df['Name'].fillna('')
        processed_df['brexchange'] = df['Exchange']
        
        # Handle expiry formatting
        processed_df['expiry'] = df['Expiry'].fillna('')
        processed_df['strike'] = pd.to_numeric(df['StrikePrice'], errors='coerce').fillna(0.0) / 100  # Convert paise to rupees
        processed_df['lotsize'] = pd.to_numeric(df['LotSize'], errors='coerce').fillna(1)
        processed_df['tick_size'] = pd.to_numeric(df['TickSize'], errors='coerce').fillna(0.05)
        
        # Map instrument types based on exchange and instrument type
        processed_df['instrumenttype'] = df['InstrumentType'].fillna('EQ')
        processed_df['option_type'] = df['OptionType'].fillna('')
        
        # Format symbols according to OpenAlgo standard
        processed_df['symbol'] = processed_df['brsymbol'].copy()
        processed_df['exchange'] = processed_df['brexchange'].copy()
        
        # Filter NSE to keep only EQ, BE, and IDX (INDEX) instrument types
        # BSE is NOT filtered (following AliceBlue pattern)
        nse_allowed_types = ['EQ', 'BE', 'INDEX', 'IDX']  # Include IDX as it might be used for indices
        nse_filter_mask = (processed_df['brexchange'] == 'NSE') & (~processed_df['instrumenttype'].isin(nse_allowed_types))
        
        # Log the filtering statistics
        filtered_count = nse_filter_mask.sum()
        if filtered_count > 0:
            logger.info(f"Filtering out {filtered_count} non-equity/index instruments from NSE (keeping only EQ, BE, IDX, and INDEX types)")
        
        # Log what types we're keeping
        nse_types = processed_df[processed_df['brexchange'] == 'NSE']['instrumenttype'].value_counts().to_dict()
        bse_types = processed_df[processed_df['brexchange'] == 'BSE']['instrumenttype'].value_counts().to_dict()
        if nse_types:
            logger.info(f"NSE instrument types before filtering: {nse_types}")
        if bse_types:
            logger.info(f"BSE instrument types (no filtering): {bse_types}")
        
        # Apply filtering only to NSE, not BSE
        processed_df = processed_df[~nse_filter_mask]
        
        # Remove empty symbols from BSE (similar to AliceBlue)
        bse_empty_mask = (processed_df['brexchange'] == 'BSE') & (processed_df['brsymbol'].isna() | (processed_df['brsymbol'] == ''))
        processed_df = processed_df[~bse_empty_mask]
        
        # NSE Equity formatting - remove suffixes like -EQ, -BE, -MF, -SG
        nse_eq_mask = (processed_df['brexchange'] == 'NSE') & (processed_df['instrumenttype'].isin(['EQ', 'BE']))
        processed_df.loc[nse_eq_mask, 'symbol'] = processed_df.loc[nse_eq_mask, 'brsymbol'].str.replace(r'-(EQ|BE|MF|SG)$', '', regex=True)
        processed_df.loc[nse_eq_mask, 'instrumenttype'] = 'EQ'
        # Set expiry and strike for NSE equities (following AliceBlue pattern)
        processed_df.loc[nse_eq_mask, 'expiry'] = ''
        processed_df.loc[nse_eq_mask, 'strike'] = 1.0
        
        # BSE Equity formatting - keep as is for BSE
        bse_eq_mask = (processed_df['brexchange'] == 'BSE') & (processed_df['instrumenttype'].isin(['EQ', 'BE']))
        processed_df.loc[bse_eq_mask, 'instrumenttype'] = 'EQ'
        # Set expiry and strike for BSE equities (following AliceBlue pattern)
        processed_df.loc[bse_eq_mask, 'expiry'] = ''
        processed_df.loc[bse_eq_mask, 'strike'] = 1.0
        
        # Index formatting - handle both INDEX and IDX instrument types
        index_mask = processed_df['instrumenttype'].isin(['INDEX', 'IDX'])
        
        # Map NSE indices to NSE_INDEX
        nse_index_mask = index_mask & (processed_df['brexchange'] == 'NSE')
        processed_df.loc[nse_index_mask, 'exchange'] = 'NSE_INDEX'
        processed_df.loc[nse_index_mask, 'instrumenttype'] = 'IDX'  # Keep as IDX for indices
        processed_df.loc[nse_index_mask, 'expiry'] = ''
        processed_df.loc[nse_index_mask, 'strike'] = 1.0
        
        # Map BSE indices to BSE_INDEX
        bse_index_mask = index_mask & (processed_df['brexchange'] == 'BSE')
        processed_df.loc[bse_index_mask, 'exchange'] = 'BSE_INDEX'
        processed_df.loc[bse_index_mask, 'instrumenttype'] = 'IDX'  # Keep as IDX for indices
        processed_df.loc[bse_index_mask, 'expiry'] = ''
        processed_df.loc[bse_index_mask, 'strike'] = 1.0
        
        # Map MCX indices to MCX_INDEX
        mcx_index_mask = index_mask & (processed_df['brexchange'] == 'MCX')
        processed_df.loc[mcx_index_mask, 'exchange'] = 'MCX_INDEX'
        processed_df.loc[mcx_index_mask, 'instrumenttype'] = 'IDX'  # Keep as IDX for indices
        processed_df.loc[mcx_index_mask, 'expiry'] = ''
        processed_df.loc[mcx_index_mask, 'strike'] = 1.0
        
        # Common index symbol mapping
        index_mapping = {
            'Nifty 50': 'NIFTY',
            'NIFTY50': 'NIFTY',
            'Nifty Next 50': 'NIFTYNXT50',
            'Nifty Fin Service': 'FINNIFTY',
            'FINNIFTY': 'FINNIFTY',
            'Nifty Bank': 'BANKNIFTY',
            'BANKNIFTY': 'BANKNIFTY',
            'NIFTY MID SELECT': 'MIDCPNIFTY',
            'MIDCPNIFTY': 'MIDCPNIFTY',
            'India VIX': 'INDIAVIX',
            'INDIAVIX': 'INDIAVIX',
            'SENSEX': 'SENSEX',
            'SENSEX50': 'SENSEX50',
            'SNSX50': 'SENSEX50'  # BSE index mapping
        }
        
        for old_name, new_name in index_mapping.items():
            processed_df.loc[processed_df['symbol'] == old_name, 'symbol'] = new_name
        
        # NFO (Futures and Options) formatting
        # Convert expiry date format from DDMMYYYY to DD-MMM-YY (AliceBlue format)
        def format_expiry_date(expiry_str):
            try:
                if pd.isna(expiry_str) or expiry_str == '':
                    return ''
                # Convert from DDMMYYYY to DD-MMM-YY
                from datetime import datetime
                expiry_date = datetime.strptime(str(expiry_str), '%d%m%Y')
                return expiry_date.strftime('%d-%b-%y').upper()
            except:
                return str(expiry_str)
        
        # Apply expiry formatting for derivatives
        derivatives_mask = processed_df['brexchange'].isin(['NFO', 'BFO', 'CDS', 'MCX'])
        processed_df.loc[derivatives_mask, 'expiry'] = processed_df.loc[derivatives_mask, 'expiry'].apply(format_expiry_date)
        
        # Format Futures symbols: [Base Symbol][Expiration Date]FUT
        futures_mask = (processed_df['brexchange'] == 'NFO') & (processed_df['instrumenttype'].isin(['FUTIDX', 'FUTSTK']))
        # For symbol, remove dashes from expiry date
        processed_df.loc[futures_mask, 'symbol'] = processed_df.loc[futures_mask, 'name'] + processed_df.loc[futures_mask, 'expiry'].str.replace('-', '') + 'FUT'
        processed_df.loc[futures_mask, 'instrumenttype'] = 'FUT'
        
        # Format Options symbols: [Base Symbol][Expiration Date][Strike Price][Option Type]
        options_mask = (processed_df['brexchange'] == 'NFO') & (processed_df['instrumenttype'].isin(['OPTIDX', 'OPTSTK']))
        # Remove decimal points from strike price for options
        strike_str = processed_df.loc[options_mask, 'strike'].apply(lambda x: str(int(x)) if x == int(x) else str(x).replace('.', ''))
        # For symbol, remove dashes from expiry date
        processed_df.loc[options_mask, 'symbol'] = (processed_df.loc[options_mask, 'name'] + 
                                                     processed_df.loc[options_mask, 'expiry'].str.replace('-', '') + 
                                                     strike_str + 
                                                     processed_df.loc[options_mask, 'option_type'])
        processed_df.loc[options_mask, 'instrumenttype'] = processed_df.loc[options_mask, 'option_type']
        
        # CDS Futures formatting
        cds_fut_mask = (processed_df['brexchange'] == 'CDS') & (processed_df['instrumenttype'].isin(['FUTCUR', 'FUTIRC']))
        # For symbol, remove dashes from expiry date
        processed_df.loc[cds_fut_mask, 'symbol'] = processed_df.loc[cds_fut_mask, 'name'] + processed_df.loc[cds_fut_mask, 'expiry'].str.replace('-', '') + 'FUT'
        processed_df.loc[cds_fut_mask, 'instrumenttype'] = 'FUT'
        
        # CDS Options formatting
        cds_opt_mask = (processed_df['brexchange'] == 'CDS') & (processed_df['instrumenttype'].isin(['OPTCUR', 'OPTIRC']))
        strike_str = processed_df.loc[cds_opt_mask, 'strike'].apply(lambda x: str(int(x)) if x == int(x) else str(x).replace('.', ''))
        # For symbol, remove dashes from expiry date
        processed_df.loc[cds_opt_mask, 'symbol'] = (processed_df.loc[cds_opt_mask, 'name'] + 
                                                    processed_df.loc[cds_opt_mask, 'expiry'].str.replace('-', '') + 
                                                    strike_str + 
                                                    processed_df.loc[cds_opt_mask, 'option_type'])
        processed_df.loc[cds_opt_mask, 'instrumenttype'] = processed_df.loc[cds_opt_mask, 'option_type']
        
        # MCX Futures formatting
        mcx_fut_mask = (processed_df['brexchange'] == 'MCX') & (processed_df['instrumenttype'] == 'FUTCOM')
        # For symbol, remove dashes from expiry date
        processed_df.loc[mcx_fut_mask, 'symbol'] = processed_df.loc[mcx_fut_mask, 'name'] + processed_df.loc[mcx_fut_mask, 'expiry'].str.replace('-', '') + 'FUT'
        processed_df.loc[mcx_fut_mask, 'instrumenttype'] = 'FUT'
        
        # MCX Options formatting
        mcx_opt_mask = (processed_df['brexchange'] == 'MCX') & (processed_df['instrumenttype'] == 'OPTFUT')
        strike_str = processed_df.loc[mcx_opt_mask, 'strike'].apply(lambda x: str(int(x)) if x == int(x) else str(x).replace('.', ''))
        # For symbol, remove dashes from expiry date
        processed_df.loc[mcx_opt_mask, 'symbol'] = (processed_df.loc[mcx_opt_mask, 'name'] + 
                                                    processed_df.loc[mcx_opt_mask, 'expiry'].str.replace('-', '') + 
                                                    strike_str + 
                                                    processed_df.loc[mcx_opt_mask, 'option_type'])
        processed_df.loc[mcx_opt_mask, 'instrumenttype'] = processed_df.loc[mcx_opt_mask, 'option_type']
        
        # BFO (BSE F&O) Futures formatting
        bfo_fut_mask = (processed_df['brexchange'] == 'BFO') & (processed_df['instrumenttype'].isin(['FUTIDX', 'FUTSTK']))
        # For symbol, remove dashes from expiry date
        processed_df.loc[bfo_fut_mask, 'symbol'] = processed_df.loc[bfo_fut_mask, 'name'] + processed_df.loc[bfo_fut_mask, 'expiry'].str.replace('-', '') + 'FUT'
        processed_df.loc[bfo_fut_mask, 'instrumenttype'] = 'FUT'
        
        # BFO Options formatting
        bfo_opt_mask = (processed_df['brexchange'] == 'BFO') & (processed_df['instrumenttype'].isin(['OPTIDX', 'OPTSTK']))
        strike_str = processed_df.loc[bfo_opt_mask, 'strike'].apply(lambda x: str(int(x)) if x == int(x) else str(x).replace('.', ''))
        # For symbol, remove dashes from expiry date
        processed_df.loc[bfo_opt_mask, 'symbol'] = (processed_df.loc[bfo_opt_mask, 'name'] + 
                                                    processed_df.loc[bfo_opt_mask, 'expiry'].str.replace('-', '') + 
                                                    strike_str + 
                                                    processed_df.loc[bfo_opt_mask, 'option_type'])
        processed_df.loc[bfo_opt_mask, 'instrumenttype'] = processed_df.loc[bfo_opt_mask, 'option_type']
        
        # Remove temporary option_type column
        processed_df = processed_df.drop(columns=['option_type'], errors='ignore')
        
        # Clean up data
        processed_df = processed_df.dropna(subset=['symbol', 'token', 'exchange'])
        processed_df = processed_df[processed_df['symbol'].str.len() > 0]  # Remove empty symbols
        
        logger.info(f"Processed {len(processed_df)} valid symbols from allmaster.csv")
        
        # Log sample of different exchanges for verification
        for exc in ['NSE', 'BSE', 'NSE_INDEX', 'BSE_INDEX', 'NFO', 'BFO', 'CDS', 'MCX']:
            exc_symbols = processed_df[processed_df['exchange'] == exc]
            if not exc_symbols.empty:
                logger.info(f"Found {len(exc_symbols)} {exc} symbols")
                # Show different samples based on exchange type
                if exc in ['NSE', 'BSE']:
                    # For equities, show instrument types
                    inst_types = exc_symbols['instrumenttype'].value_counts().to_dict()
                    logger.info(f"{exc} instrument types: {inst_types}")
                logger.info(f"Sample {exc} symbols: {exc_symbols['symbol'].head(3).tolist()}")
        
        return processed_df
        
    except Exception as e:
        logger.error(f"Error processing allmaster.csv: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return pd.DataFrame()

def delete_temp_files(output_path):
    """Delete temporary downloaded files"""
    try:
        # Clean up temporary files
        temp_files = ['allmaster.zip', 'allmaster.csv']
        for filename in temp_files:
            filepath = os.path.join(output_path, filename)
            if os.path.exists(filepath):
                os.remove(filepath)
                logger.info(f"Deleted temporary file: {filename}")
    except Exception as e:
        logger.error(f"Error deleting temporary files: {e}")

def master_contract_download():
    """Download and process DefinedGe master contracts"""
    try:
        # Import here to avoid circular imports
        from database.master_contract_status_db import update_status
        from database.token_db import get_symbol_count
        from extensions import socketio
        
        # Update status to downloading
        update_status('definedge', 'downloading', 'Master contract download in progress')
        
        # Create temp directory
        output_path = "tmp"
        os.makedirs(output_path, exist_ok=True)

        # Download master files (no auth token needed for public master file)
        if not download_definedge_master_files(None, output_path):
            logger.error("Failed to download DefinedGe master files")
            update_status('definedge', 'error', 'Failed to download master files')
            return socketio.emit('master_contract_download', {'status': 'error', 'message': 'Failed to download master files'})

        # Delete existing data
        delete_symtoken_table()

        # Process the single allmaster.csv file
        allmaster_filepath = os.path.join(output_path, "allmaster.csv")
        if os.path.exists(allmaster_filepath):
            try:
                df = process_definedge_allmaster_csv(allmaster_filepath)
                if not df.empty:
                    copy_from_dataframe(df)
                    logger.info(f"Processed all symbols: {len(df)} records")
                    
                    # Get final symbol count and update status
                    total_symbols = get_symbol_count()
                    update_status('definedge', 'success', 'Master contract download completed successfully', total_symbols)
                    
                else:
                    logger.warning("No data processed from allmaster.csv")
                    update_status('definedge', 'error', 'No data processed from master file')
                    return socketio.emit('master_contract_download', {'status': 'error', 'message': 'No data processed'})
            except Exception as e:
                logger.error(f"Error processing allmaster.csv file: {e}")
                update_status('definedge', 'error', f'Error processing master file: {str(e)}')
                return socketio.emit('master_contract_download', {'status': 'error', 'message': str(e)})
        else:
            logger.error(f"allmaster.csv file not found: {allmaster_filepath}")
            update_status('definedge', 'error', 'Master file not found after download')
            return socketio.emit('master_contract_download', {'status': 'error', 'message': 'Master file not found'})

        # Clean up temporary files
        delete_temp_files(output_path)

        logger.info("DefinedGe master contract download completed successfully")
        
        # Emit socketio event if available
        try:
            return socketio.emit('master_contract_download', {'status': 'success', 'message': 'Successfully Downloaded'})
        except:
            return True

    except Exception as e:
        logger.error(f"Error in DefinedGe master contract download: {e}")
        try:
            from database.master_contract_status_db import update_status
            from extensions import socketio
            update_status('definedge', 'error', f'Download failed: {str(e)}')
            try:
                return socketio.emit('master_contract_download', {'status': 'error', 'message': str(e)})
            except:
                return False
        except:
            return False

def search_symbols(symbol, exchange):
    """Search for symbols in the database"""
    try:
        results = db_session.query(SymToken).filter(
            SymToken.symbol.ilike(f"%{symbol}%"),
            SymToken.exchange == exchange
        ).limit(10).all()

        return [{'symbol': r.symbol, 'token': r.token, 'name': r.name} for r in results]

    except Exception as e:
        logger.error(f"Error searching symbols: {e}")
        return []
