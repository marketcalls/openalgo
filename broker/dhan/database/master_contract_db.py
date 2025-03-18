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


from sqlalchemy import create_engine, Column, Integer, String, Float , Sequence, Index
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from database.auth_db import get_auth_token
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
            db_session.bulk_insert_mappings(SymToken, filtered_data_dict)
            db_session.commit()
            print(f"Bulk insert completed successfully with {len(filtered_data_dict)} new records.")
        else:
            print("No new records to insert.")
    except Exception as e:
        print(f"Error during bulk insert: {e}")
        db_session.rollback()




def download_csv_dhan_data(output_path):

    print("Downloading Master Contract CSV Files")
    # URLs of the CSV files to be downloaded
    csv_urls = {
        "master": "https://images.dhan.co/api-data/api-scrip-master.csv"
    }
    
    # Create a list to hold the paths of the downloaded files
    downloaded_files = []

    # Iterate through the URLs and download the CSV files
    for key, url in csv_urls.items():
        # Send GET request
        response = requests.get(url,timeout=10)
        # Check if the request was successful
        if response.status_code == 200:
            # Construct the full output path for the file
            file_path = f"{output_path}/{key}.csv"
            # Write the content to the file
            with open(file_path, 'wb') as file:
                file.write(response.content)
            downloaded_files.append(file_path)
        else:
            print(f"Failed to download {key} from {url}. Status code: {response.status_code}")
    

def reformat_symbol(row):
    symbol = row['SEM_CUSTOM_SYMBOL']
    instrument_type = row['instrumenttype']
    equity = row['SEM_INSTRUMENT_NAME']
    expiry = row['expiry'].replace('-', '')
    

    if equity == 'EQUITY':
        symbol = row['SEM_TRADING_SYMBOL']
    elif equity == 'INDEX':
        symbol = row['SEM_TRADING_SYMBOL']

    elif instrument_type == 'FUT':
        # For FUT, remove the spaces and append 'FUT' at the end
        parts = symbol.split(' ')
        if len(parts) == 3:  # Make sure the symbol has the correct format
            symbol = f"{parts[0]}{expiry}{instrument_type}"
        if len(parts) == 4:  # Make sure the symbol has the correct format
            symbol = f"{parts[0]}{expiry}{instrument_type}"
    elif instrument_type in ['CE', 'PE']:
        # For CE/PE, rearrange the parts and remove spaces
        parts = symbol.split(' ')
        if len(parts) == 4:  # Make sure the symbol has the correct format
            symbol = f"{parts[0]}{expiry}{parts[2]}{instrument_type}"
        if len(parts) == 5:  # Make sure the symbol has the correct format
            symbol = f"{parts[0]}{expiry}{parts[3]}{instrument_type}"
    
    else:
        symbol = symbol  # No change for other instrument types

    return symbol

# Define the function to apply conditions
def assign_values(row):
    if row['SEM_EXM_EXCH_ID'] == 'NSE' and row['SEM_INSTRUMENT_NAME'] == 'EQUITY':
        return 'NSE', 'NSE_EQ', 'EQ'
    elif row['SEM_EXM_EXCH_ID'] == 'BSE' and row['SEM_INSTRUMENT_NAME'] == 'EQUITY':
        return 'BSE', 'BSE_EQ', 'EQ'
    elif row['SEM_EXM_EXCH_ID'] == 'NSE' and row['SEM_INSTRUMENT_NAME'] == 'INDEX':
        return 'NSE_INDEX', 'IDX_I', 'INDEX'
    elif row['SEM_EXM_EXCH_ID'] == 'BSE' and row['SEM_INSTRUMENT_NAME'] == 'INDEX':
        return 'BSE_INDEX', 'IDX_I', 'INDEX'
    elif row['SEM_EXM_EXCH_ID'] == 'MCX' and row['SEM_INSTRUMENT_NAME'] in ['FUTIDX','FUTCOM','OPTFUT']:
        return 'MCX', 'MCX_COMM', row['SEM_OPTION_TYPE'] if 'OPT' in row['SEM_INSTRUMENT_NAME'] else 'FUT'
    
    elif row['SEM_EXM_EXCH_ID'] == 'NSE' and row['SEM_INSTRUMENT_NAME'] in ['FUTIDX', 'FUTSTK', 'OPTIDX', 'OPTSTK','OPTFUT']:
        return 'NFO', 'NSE_FNO', row['SEM_OPTION_TYPE'] if 'OPT' in row['SEM_INSTRUMENT_NAME'] else 'FUT'
    elif row['SEM_EXM_EXCH_ID'] == 'NSE' and row['SEM_INSTRUMENT_NAME'] in ['FUTCUR', 'OPTCUR']:
        return 'CDS', 'NSE_CURRENCY', row['SEM_OPTION_TYPE'] if 'OPT' in row['SEM_INSTRUMENT_NAME'] else 'FUT'
    
    elif row['SEM_EXM_EXCH_ID'] == 'BSE' and row['SEM_INSTRUMENT_NAME'] in ['FUTIDX', 'FUTSTK','OPTIDX', 'OPTSTK']:
        return 'BFO', 'BSE_FNO', row['SEM_OPTION_TYPE'] if 'OPT' in row['SEM_INSTRUMENT_NAME'] else 'FUT'
    elif row['SEM_EXM_EXCH_ID'] == 'BSE' and row['SEM_INSTRUMENT_NAME'] in ['FUTCUR', 'OPTCUR']:
        return 'BCD', 'BSE_CURRENCY', row['SEM_OPTION_TYPE'] if 'OPT' in row['SEM_INSTRUMENT_NAME'] else 'FUT'
  
    else:
        return 'Unknown', 'Unknown', 'Unknown'

def process_dhan_csv(path):
    """
    Processes the Dhan CSV file to fit the existing database schema and performs exchange name mapping.
    """
    print("Processing Dhan Scrip Master CSV Data")
    file_path = f'{path}/master.csv'

    df = pd.read_csv(file_path, low_memory=False)
    df.columns = df.columns.str.strip()

    # Attempt to convert all date entries to datetime objects, errors are coerced to NaT
    df['SEM_EXPIRY_DATE'] = pd.to_datetime(df['SEM_EXPIRY_DATE'], errors='coerce')

    # Now, format all non-NaT datetime objects to the desired format "DD-MMM-YY"
    # NaT values will remain as NaT and can be handled separately if needed
    df['SEM_EXPIRY_DATE'] = df['SEM_EXPIRY_DATE'].dt.strftime('%d-%b-%y')

    # Optionally, handle NaT values by replacing them with a placeholder or removing them
    # For example, replacing NaT with 'Unknown Date':
    df['SEM_EXPIRY_DATE'] = df['SEM_EXPIRY_DATE'].fillna('-1')


    # Assigning headers to the DataFrame
    
    df['token'] = df['SEM_SMST_SECURITY_ID']
    df['name'] = df['SM_SYMBOL_NAME']
    df['expiry'] = df['SEM_EXPIRY_DATE'].str.upper()
    df['strike'] = df['SEM_STRIKE_PRICE']
    df['lotsize'] = df['SEM_LOT_UNITS']
    df['tick_size'] = df['SEM_TICK_SIZE']
    df['brsymbol'] = df['SEM_TRADING_SYMBOL']


    # Apply the function
    df[['exchange', 'brexchange', 'instrumenttype']] = df.apply(assign_values, 
                                                                axis=1, result_type='expand')

      
        
    df['symbol'] = df.apply(reformat_symbol, axis=1)
    df['symbol'] = df['symbol'].replace('INDIA VIX', 'INDIAVIX')

    # List of columns to remove
    columns_to_remove = [
    "SEM_EXM_EXCH_ID", "SEM_SEGMENT", "SEM_SMST_SECURITY_ID", "SEM_INSTRUMENT_NAME",
    "SEM_EXPIRY_CODE", "SEM_TRADING_SYMBOL", "SEM_LOT_UNITS", "SEM_CUSTOM_SYMBOL",
    "SEM_EXPIRY_DATE", "SEM_STRIKE_PRICE", "SEM_OPTION_TYPE", "SEM_TICK_SIZE",
    "SEM_EXPIRY_FLAG", "SEM_EXCH_INSTRUMENT_TYPE", "SEM_SERIES", "SM_SYMBOL_NAME"
    ]


    # Removing the specified columns
    token_df = df.drop(columns=columns_to_remove)


    
    return token_df


    

def delete_dhan_temp_data(output_path):
    # Check each file in the directory
    for filename in os.listdir(output_path):
        # Construct the full file path
        file_path = os.path.join(output_path, filename)
        # If the file is a CSV, delete it
        if filename.endswith(".csv") and os.path.isfile(file_path):
            os.remove(file_path)
            print(f"Deleted {file_path}")
    

def master_contract_download():
    print("Downloading Master Contract")
    

    output_path = 'tmp'
    try:
        download_csv_dhan_data(output_path)
        delete_symtoken_table()
        token_df = process_dhan_csv(output_path)
        copy_from_dataframe(token_df)
        delete_dhan_temp_data(output_path)
        #token_df['token'] = pd.to_numeric(token_df['token'], errors='coerce').fillna(-1).astype(int)
        
        #token_df = token_df.drop_duplicates(subset='symbol', keep='first')
        
        return socketio.emit('master_contract_download', {'status': 'success', 'message': 'Successfully Downloaded'})

    
    except Exception as e:
        print(str(e))
        return socketio.emit('master_contract_download', {'status': 'error', 'message': str(e)})



def search_symbols(symbol, exchange):
    return SymToken.query.filter(SymToken.symbol.like(f'%{symbol}%'), SymToken.exchange == exchange).all()
