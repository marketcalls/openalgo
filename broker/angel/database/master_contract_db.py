#database/master_contract_db.py

import os
import pandas as pd
import requests
import gzip
import shutil
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

def download_json_angel_data(url, output_path):
    """
    Downloads a JSON file from the specified URL and saves it to the specified path.
    """
    logger.info("Downloading JSON data")
    response = requests.get(url, timeout=10)  # timeout after 10 seconds
    if response.status_code == 200:  # Successful download
        with open(output_path, 'wb') as f:
            f.write(response.content)
        logger.info("Download complete")
    else:
        logger.error(f"Failed to download data. Status code: {response.status_code}")


def reformat_symbol(row):
    symbol = row['symbol']
    instrument_type = row['instrumenttype']
    
    if instrument_type == 'FUT':
        # For FUT, remove the spaces and append 'FUT' at the end
        parts = symbol.split(' ')
        if len(parts) == 5:  # Make sure the symbol has the correct format
            symbol = parts[0] + parts[2] + parts[3] + parts[4] + parts[1]
    elif instrument_type in ['CE', 'PE']:
        # For CE/PE, rearrange the parts and remove spaces
        parts = symbol.split(' ')
        if len(parts) == 6:  # Make sure the symbol has the correct format
            symbol = parts[0] + parts[3] + parts[4] + parts[5] + parts[1] + parts[2]
    else:
        symbol = symbol  # No change for other instrument types

    return symbol


def convert_date(date_str):
    # Convert from '19MAR2024' to '19-MAR-24'
    try:
        return datetime.strptime(date_str, '%d%b%Y').strftime('%d-%b-%y')
    except ValueError:
        # Return the original date if it doesn't match the format
        return date_str

def process_angel_json(path):
    """
    Processes the Angel JSON file to fit the existing database schema.
    Args:
    path (str): The file path of the downloaded JSON data.

    Returns:
    DataFrame: The processed DataFrame ready to be inserted into the database.
    """
    # Read JSON data into a DataFrame
    df = pd.read_json(path)
    
    # Rename the columns based on the database schema
    # Assuming that the JSON structure matches the sample response provided
    df = df.rename(columns={
        'exch_seg': 'exchange',
        'instrumenttype': 'instrumenttype',
        'lotsize': 'lotsize',
        'strike': 'strike',
        'symbol': 'symbol',
        'token': 'token',
        'name': 'name',
        'tick_size': 'tick_size'
    })
    
    # Reformat 'symbol' column if needed (based on the given reformat_symbol function)
    #df['symbol'] = df.apply(lambda row: reformat_symbol(row), axis=1)
    
    
    # Assuming 'brsymbol' and 'brexchange' are not present in the JSON and are the same as 'symbol' and 'exchange'
    df['brsymbol'] = df['symbol']
    df['brexchange'] = df['exchange']

     # Update exchange names based on the instrument type
    df.loc[(df['instrumenttype'] == 'AMXIDX') & (df['exchange'] == 'NSE'), 'exchange'] = 'NSE_INDEX'
    df.loc[(df['instrumenttype'] == 'AMXIDX') & (df['exchange'] == 'BSE'), 'exchange'] = 'BSE_INDEX'
    df.loc[(df['instrumenttype'] == 'AMXIDX') & (df['exchange'] == 'MCX'), 'exchange'] = 'MCX_INDEX'
    
    # Reformat 'symbol' based on 'brsymbol'
    df['symbol'] = df['symbol'].str.replace('-EQ|-BE|-MF|-SG', '', regex=True)
    
    
    # Assuming the 'expiry' field in the JSON is in the format '19MAR2024'
    df['expiry'] = df['expiry'].apply(lambda x: convert_date(x) if pd.notnull(x) else x)
    df['expiry'] = df['expiry'].str.upper()

    


    # Convert 'strike' to float, 'lotsize' to int, and 'tick_size' to float as per the database schema
    df['strike'] = df['strike'].astype(float) / 100
    df.loc[(df['instrumenttype'] == 'OPTCUR') & (df['exchange'] == 'CDS'), 'strike'] = df['strike'].astype(float) / 100000
    df.loc[(df['instrumenttype'] == 'OPTIRC') & (df['exchange'] == 'CDS'), 'strike'] = df['strike'].astype(float) / 100000
    

    df['lotsize'] = df['lotsize'].astype(int)
    df['tick_size'] = df['tick_size'].astype(float) / 100  # Divide tick_size by 100

    # Futures Symbol Update in CDS and MCX Exchanges
    df.loc[(df['instrumenttype'] == 'FUTCUR') & (df['exchange'] == 'CDS'), 'symbol'] = df['name'] + df['expiry'].str.replace('-', '', regex=False) + 'FUT'
    df.loc[(df['instrumenttype'] == 'FUTIRC') & (df['exchange'] == 'CDS'), 'symbol'] = df['name'] + df['expiry'].str.replace('-', '', regex=False) + 'FUT' 
    df.loc[(df['instrumenttype'] == 'FUTCOM') & (df['exchange'] == 'MCX'), 'symbol'] = df['name'] + df['expiry'].str.replace('-', '', regex=False) + 'FUT'
    # Options Symbol Update in CDS and MCX Exchanges
    df.loc[(df['instrumenttype'] == 'OPTCUR') & (df['exchange'] == 'CDS'), 'symbol'] = df['name'] + df['expiry'].str.replace('-', '', regex=False) + df['strike'].astype(str).str.replace(r'\.0', '', regex=True) + df['symbol'].str[-2:]
    df.loc[(df['instrumenttype'] == 'OPTIRC') & (df['exchange'] == 'CDS'), 'symbol'] = df['name'] + df['expiry'].str.replace('-', '', regex=False) + df['strike'].astype(str).str.replace(r'\.0', '', regex=True) + df['symbol'].str[-2:]
    df.loc[(df['instrumenttype'] == 'OPTFUT') & (df['exchange'] == 'MCX'), 'symbol'] = df['name'] + df['expiry'].str.replace('-', '', regex=False) + df['strike'].astype(str).str.replace(r'\.0', '', regex=True) + df['symbol'].str[-2:]  
    # Common Index Symbol Formats

    df['symbol'] = df['symbol'].replace({
    'Nifty 50': 'NIFTY',
    'Nifty Next 50': 'NIFTYNXT50',
    'Nifty Fin Service': 'FINNIFTY',
    'Nifty Bank': 'BANKNIFTY',
    'NIFTY MID SELECT': 'MIDCPNIFTY',
    'India VIX': 'INDIAVIX',
    'SNSX50': 'SENSEX50'
    })

 
    # Return the processed DataFrame
    return df

def delete_angel_temp_data(output_path):
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
    logger.info("Downloading Master Contract")
    url = 'https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json'
    output_path = 'tmp/angel.json'
    try:
        download_json_angel_data(url,output_path)
        token_df = process_angel_json(output_path)
        delete_angel_temp_data(output_path)
        #token_df['token'] = pd.to_numeric(token_df['token'], errors='coerce').fillna(-1).astype(int)
        
        #token_df = token_df.drop_duplicates(subset='symbol', keep='first')

        delete_symtoken_table()  # Consider the implications of this action
        copy_from_dataframe(token_df)
                
        return socketio.emit('master_contract_download', {'status': 'success', 'message': 'Successfully Downloaded'})

    
    except Exception as e:
        logger.info(f"{str(e)}")
        return socketio.emit('master_contract_download', {'status': 'error', 'message': str(e)})



def search_symbols(symbol, exchange):
    return SymToken.query.filter(SymToken.symbol.like(f'%{symbol}%'), SymToken.exchange == exchange).all()
