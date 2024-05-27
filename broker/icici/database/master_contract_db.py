#database/master_contract_db.py

import os
import glob
import pandas as pd
import requests
import zipfile
from io import BytesIO

from sqlalchemy import create_engine, Column, Integer, String, Float , Sequence, Index
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from dotenv import load_dotenv
from extensions import socketio  # Import SocketIO

load_dotenv()

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


def download_and_extract_icici_zip(url, extract_to='tmp'):
    # Make a request to fetch the data from the URL
    response = requests.get(url,timeout=10)
    
    # Raise an exception if the download fails
    response.raise_for_status()
    
    # Open the ZIP file contained in the response's content
    with zipfile.ZipFile(BytesIO(response.content)) as the_zip:
        # Get the list of file names contained in the zip
        zip_files = the_zip.namelist()
        
        # Extract the contents into the specified directory
        the_zip.extractall(path=extract_to)


# Function to transform the strike value
def transform_strike(strike):
    if strike.endswith('.0'):
        return strike[:-2]  # Remove the '.0' from the string
    return strike  # Return the original value if no '.0'

def reformat_symbol(row):
    symbol1 = str(row['symbol1'])
    expiry = str(row['expiry']).replace('-', '')  # Remove dashes right here
    row['strike'] = str(row['strike'])
    row['strike'] = transform_strike(row['strike'])  # Directly call the transform function
    strike = row['strike']

    instrument_type = row['instrumenttype']

    if row['instrumenttype'] == 'FUT':
        symbol = symbol1 + expiry + instrument_type
    elif row['instrumenttype'] in ['CE', 'PE']:
        symbol = symbol1 + expiry + strike + instrument_type
    else:
        symbol = symbol1  # Default return in case other instrument types are encountered

    return symbol

def process_icici_nse_csv(path):
    # Define the path to the file
    file_path = 'tmp/NSEScripMaster.txt'

    # Check if the file exists
    if os.path.exists(file_path):
        try:
            df = pd.read_csv(file_path, sep=",")
        except Exception as e:
            # If there's an error, output it
            print(f"An error occurred: {e}")
    else:
        print("File does not exist at the specified path.")

    newdata = pd.DataFrame()

    # Replace double quotes and strip spaces from column names
    df.columns = df.columns.str.replace('"', '').str.strip()
    df.columns = df.columns.str.upper()
    
    df.loc[df['SERIES'] != '0', 'EXCHANGE'] = 'NSE'
    df.loc[df['SERIES'] == '0', 'EXCHANGE'] = 'NSE_INDEX'
    df.loc[df['SERIES'] != '0', 'INSTRUMENTTYPE'] = 'EQ'
    df.loc[df['SERIES'] == '0', 'INSTRUMENTTYPE'] = 'INDEX'

    newdata['symbol'] = df['EXCHANGECODE']
    newdata['brsymbol'] = df['SHORTNAME']
    newdata['name'] = df['COMPANYNAME']
    newdata['exchange'] = df['EXCHANGE']
    newdata['brexchange'] = df['EXCHANGE']
    newdata['token'] = df['TOKEN']
    newdata['expiry'] = None
    newdata['strike'] = None
    newdata['lotsize'] = df['LOTSIZE']
    newdata['instrumenttype'] = df['INSTRUMENTTYPE']
    newdata['tick size'] = df['TICKSIZE']

    return newdata


def process_icici_bse_csv(path):
    # Define the path to the file
    file_path = 'tmp/BSEScripMaster.txt'

    # Check if the file exists
    if os.path.exists(file_path):
        try:
            df = pd.read_csv(file_path, sep=",")
        except Exception as e:
            # If there's an error, output it
            print(f"An error occurred: {e}")
    else:
        print("File does not exist at the specified path.")

    newdata = pd.DataFrame()

    # Replace double quotes and strip spaces from column names
    df.columns = df.columns.str.replace('"', '').str.strip()
    df.columns = df.columns.str.upper()   
  
    newdata['symbol'] = df['EXCHANGECODE']
    newdata['symbol'] = newdata['symbol'].where(newdata['symbol'].notna(), '')
    newdata['brsymbol'] = df['SHORTNAME']
    newdata['name'] = df['COMPANYNAME']
    newdata['exchange'] = 'BSE'
    newdata['brexchange'] = 'BSE'
    newdata['token'] = df['TOKEN']
    newdata['expiry'] = None
    newdata['strike'] = None
    newdata['lotsize'] = df['LOTSIZE']
    newdata['instrumenttype'] = 'EQ'
    newdata['tick size'] = df['TICKSIZE']

    return newdata

def process_icici_nfo_csv(path):
    # Define the path to the file
    file_path = 'tmp/FONSEScripMaster.txt'

    # Check if the file exists
    if os.path.exists(file_path):
        try:
            df = pd.read_csv(file_path, sep=",")
        except Exception as e:
            # If there's an error, output it
            print(f"An error occurred: {e}")
    else:
        print("File does not exist at the specified path.")

    newdata = pd.DataFrame()

    # Replace double quotes and strip spaces from column names
    df.columns = df.columns.str.replace('"', '').str.strip()
    df.columns = df.columns.str.upper()   
    
    
    newdata['name'] = df['COMPANYNAME']
    newdata['exchange'] = 'NFO'
    newdata['brexchange'] = 'NFO'
    newdata['token'] = df['TOKEN']

    newdata['EXPIRYDATE1'] = df['EXPIRYDATE'].copy()
    df['EXPIRYDATE'] = pd.to_datetime(df['EXPIRYDATE'], format='%d-%b-%Y')
    #df['EXPIRYDATE'] = df['EXPIRYDATE']
    newdata['expiry'] = df['EXPIRYDATE'].dt.strftime('%d-%b-%y')  # '25-APR-24' format    newdata['expiry'] = newdata['expiry'].str.upper()
    newdata['strike'] = df['STRIKEPRICE']
    newdata['lotsize'] = df['LOTSIZE']
    
    newdata['instrumenttype'] = df['OPTIONTYPE'].map({
    'XX': 'FUT',
    'CE': 'CE',
    'PE': 'PE'
    })

    

    newdata['tick size'] = df['TICKSIZE']
   
    mapping = {
    'NIFTY 50': 'NIFTY',
    'NIFTY BANK': 'BANKNIFTY',
    'NIFTY MIDCAP': 'MIDCPNIFTY',
    'NIFTY FINANCIAL': 'FINNIFTY',
    'NIFTY NEXT 50': 'NIFTYNXT50'
    }

    # Map the values
    df['EXCHANGECODE'] = df['EXCHANGECODE'].map(mapping)

    newdata['symbol1'] = df['EXCHANGECODE']
    # Apply the function across the DataFrame rows
    newdata['symbol'] = newdata.apply(lambda x: reformat_symbol(x).upper(), axis=1)

    newdata['SHORTNAME'] = df['SHORTNAME']
    
    def format_strike(strike):
        # Convert strike to string first
        strike_str = str(strike)
        # Check if the string ends with '.0' and remove it
        if strike_str.endswith('.0'):
            # Remove the last two characters '.0'
            return strike_str[:-2]
        # Return the original string if it does not end with '.0'
        return strike_str


    def calculate_brsymbol(row):
        if row['instrumenttype'] == 'FUT':
            return row['SHORTNAME'] + ':::' +  row['EXPIRYDATE1'].upper() + ':::' +  'FUT'
        elif row['instrumenttype'] == 'CE':
            return row['SHORTNAME'] + ':::' +  row['EXPIRYDATE1'].upper()  + ':::' +  format_strike(row['strike']) + ':::' +  'Call'
        elif row['instrumenttype'] == 'PE':
            return row['SHORTNAME'] + ':::' +  row['EXPIRYDATE1'].upper()  + ':::' +  format_strike(row['strike']) + ':::' +  'Put'
        else:
            return row['SHORTNAME']



    # Apply the function to each row to calculate brsymbol
    newdata['brsymbol'] = newdata.apply(lambda x: calculate_brsymbol(x).upper(), axis=1)
    # Remove the 'SHORTNAME' column from the DataFrame
    newdata = newdata.drop('SHORTNAME', axis=1)
    newdata = newdata.drop('EXPIRYDATE1', axis=1)

    return newdata


def process_icici_cds_csv(path):
    # Define the path to the file
    file_path = 'tmp/CDNSEScripMaster.txt'

    # Check if the file exists
    if os.path.exists(file_path):
        try:
            df = pd.read_csv(file_path, sep=",")
        except Exception as e:
            # If there's an error, output it
            print(f"An error occurred: {e}")
    else:
        print("File does not exist at the specified path.")

    newdata = pd.DataFrame()

    # Replace double quotes and strip spaces from column names
    df.columns = df.columns.str.replace('"', '').str.strip()
    df.columns = df.columns.str.upper()   
    
    
    newdata['name'] = df['COMPANYNAME']
    newdata['exchange'] = 'CDS'
    newdata['brexchange'] = 'CDS'
    newdata['token'] = df['TOKEN']

    newdata['EXPIRYDATE1'] = df['EXPIRYDATE'].copy()
    df['EXPIRYDATE'] = pd.to_datetime(df['EXPIRYDATE'], format='%d-%b-%Y')
    #df['EXPIRYDATE'] = df['EXPIRYDATE']
    newdata['expiry'] = df['EXPIRYDATE'].dt.strftime('%d-%b-%y')  # '25-APR-24' format    newdata['expiry'] = newdata['expiry'].str.upper()
    newdata['strike'] = df['STRIKEPRICE']
    newdata['lotsize'] = df['LOTSIZE']
    
    newdata['instrumenttype'] = df['OPTIONTYPE'].map({
    'XX': 'FUT',
    'CE': 'CE',
    'PE': 'PE'
    })

    

    newdata['tick size'] = df['TICKSIZE']
   

    newdata['symbol1'] = df['EXCHANGECODE']
    # Apply the function across the DataFrame rows
    newdata['symbol'] = newdata.apply(lambda x: reformat_symbol(x).upper(), axis=1)

    newdata['SHORTNAME'] = df['SHORTNAME']
    
    def format_strike(strike):
        # Convert strike to string first
        strike_str = str(strike)
        # Check if the string ends with '.0' and remove it
        if strike_str.endswith('.0'):
            # Remove the last two characters '.0'
            return strike_str[:-2]
        # Return the original string if it does not end with '.0'
        return strike_str


    def calculate_brsymbol(row):
        if row['instrumenttype'] == 'FUT':
            return row['SHORTNAME'] + ':::' +  row['EXPIRYDATE1'].upper() + ':::' +  'FUT'
        elif row['instrumenttype'] == 'CE':
            return row['SHORTNAME'] + ':::' +  row['EXPIRYDATE1'].upper()  + ':::' +  format_strike(row['strike']) + ':::' +  'Call'
        elif row['instrumenttype'] == 'PE':
            return row['SHORTNAME'] + ':::' +  row['EXPIRYDATE1'].upper()  + ':::' +  format_strike(row['strike']) + ':::' +  'Put'
        else:
            return row['SHORTNAME']



    # Apply the function to each row to calculate brsymbol
    newdata['brsymbol'] = newdata.apply(lambda x: calculate_brsymbol(x).upper(), axis=1)
    # Remove the 'SHORTNAME' column from the DataFrame
    newdata = newdata.drop('SHORTNAME', axis=1)
    newdata = newdata.drop('EXPIRYDATE1', axis=1)

    return newdata


def delete_icici_temp_data(input_path):
    try:
        # Construct the full path for txt files in the directory
        txt_files_path = os.path.join(input_path, '*.txt')
        # Find all txt files in the directory
        txt_files = glob.glob(txt_files_path)
        if txt_files:
            for file in txt_files:
                os.remove(file)
                print(f"Deleted {file}")
        else:
            print("No .txt files found to delete.")
    except Exception as e:
        print(f"An error occurred: {e}")



def master_contract_download():
    
    url = 'https://directlink.icicidirect.com/NewSecurityMaster/SecurityMaster.zip'
    input_path = 'tmp'
 
    try:
        print("Downloading Master Contract")
        download_and_extract_icici_zip(url, input_path)
        delete_symtoken_table()  # Consider the implications of this action
        print("Processing NSE CM Master Contract")
        token_df = process_icici_nse_csv(input_path)
        copy_from_dataframe(token_df)
        print("Processing BSE CM Master Contract")
        token_df = process_icici_bse_csv(input_path)
        copy_from_dataframe(token_df)
        print("Processing NSE FO Master Contract")
        token_df = process_icici_nfo_csv(input_path)
        copy_from_dataframe(token_df)

        print("Processing NSE CD Master Contract")
        token_df = process_icici_cds_csv(input_path)
        copy_from_dataframe(token_df)


        delete_icici_temp_data(input_path)
        #token_df['token'] = pd.to_numeric(token_df['token'], errors='coerce').fillna(-1).astype(int)
        
        #token_df = token_df.drop_duplicates(subset='symbol', keep='first')

        
                
        return socketio.emit('master_contract_download', {'status': 'success', 'message': 'Successfully Downloaded'})

    
    except Exception as e:
        print(str(e))
        return socketio.emit('master_contract_download', {'status': 'error', 'message': str(e)})



def search_symbols(symbol, exchange):
    return SymToken.query.filter(SymToken.symbol.like(f'%{symbol}%'), SymToken.exchange == exchange).all()

