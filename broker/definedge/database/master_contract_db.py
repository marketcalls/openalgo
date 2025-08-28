#database/master_contract_db.py

import os
import pandas as pd
import numpy as np
import requests
import gzip
import shutil
import http.client
import json
import pandas as pd
import gzip
import io

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
    """Download master contract files from DefinedGe Securities"""
    try:
        # DefinedGe provides all master contracts in a single ZIP file
        # No authentication required for public master file
        master_url = "https://app.definedgesecurities.com/public/allmaster.zip"
        
        # Download the ZIP file
        response = requests.get(master_url, timeout=30)
        
        if response.status_code == 200:
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
        else:
            logger.error(f"Failed to download master file: HTTP {response.status_code}")
            return False

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
        
        # Map columns based on DefinedGe format
        processed_df['symbol'] = df['TradingSymbol']
        processed_df['brsymbol'] = df['TradingSymbol']
        processed_df['token'] = df['Token'].astype(str)
        processed_df['name'] = df['Name'].fillna('')
        processed_df['exchange'] = df['Exchange']
        processed_df['brexchange'] = df['Exchange']
        
        # Handle other fields
        processed_df['expiry'] = df['Expiry'].fillna('')
        processed_df['strike'] = pd.to_numeric(df['StrikePrice'], errors='coerce').fillna(0.0) / 100  # Convert paise to rupees
        processed_df['lotsize'] = pd.to_numeric(df['LotSize'], errors='coerce').fillna(1)
        processed_df['instrumenttype'] = df['InstrumentType'].fillna('EQ')
        processed_df['tick_size'] = pd.to_numeric(df['TickSize'], errors='coerce').fillna(0.05)
        
        # Clean up data
        processed_df = processed_df.dropna(subset=['symbol', 'token', 'exchange'])
        processed_df = processed_df[processed_df['symbol'].str.len() > 0]  # Remove empty symbols
        
        logger.info(f"Processed {len(processed_df)} valid symbols from allmaster.csv")
        
        # Log sample of NFO symbols for verification
        nfo_symbols = processed_df[processed_df['exchange'] == 'NFO']
        if not nfo_symbols.empty:
            logger.info(f"Found {len(nfo_symbols)} NFO symbols")
            logger.info(f"Sample NFO symbols: {nfo_symbols['brsymbol'].head(3).tolist()}")
        
        return processed_df
        
    except Exception as e:
        logger.error(f"Error processing allmaster.csv: {e}")
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
