import os
import requests
import pandas as pd
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, Float, Sequence, Index
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from extensions import socketio  # Import SocketIO



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
    print("Downloading CSV Data")

    if not os.path.exists(output_path):
        os.makedirs(output_path)

    downloaded_files = []

    for key, url in flattrade_urls.items():
        try:
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                print(f"Successfully downloaded {key} from {url}")
                output_file = os.path.join(output_path, f"{key}.csv")
                with open(output_file, 'wb') as f:
                    f.write(response.content)
                downloaded_files.append(f"{key}.csv")
            else:
                print(f"Failed to download {key} from {url}. Status code: {response.status_code}")
        except Exception as e:
            print(f"Error downloading {key} from {url}: {e}")

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
    print("Processing Flattrade NSE Data")
    file_path = f'{output_path}/NSE.csv'

    # Read the NSE symbols file, specifying the exact columns to use and ignoring extra columns
    df = pd.read_csv(file_path, usecols=['SYMBOL', 'NAME', 'EXCHANGE', 'TOKEN', 'LOT_SIZE', 'INSTRUMENT_TYPE', 'TICK_SIZE'])

    # Rename columns to match your schema
    df.columns = ['symbol', 'name', 'exchange', 'token', 'lotsize', 'instrumenttype', 'tick_size']

    # Add missing columns to ensure DataFrame matches the database structure
    df['brsymbol'] = df['symbol']  # Initialize 'brsymbol' with 'symbol'

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
    df['symbol'] = df['symbol'].apply(get_openalgo_symbol)

    # Define Exchange: 'NSE' for EQ and BE, 'NSE_INDEX' for indexes
    df['exchange'] = df.apply(lambda row: 'NSE_INDEX' if row['instrumenttype'] == 'INDEX' else 'NSE', axis=1)
    df['brexchange'] = df['exchange']  # Broker exchange is the same as exchange

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

    # Return the processed DataFrame
    return df_filtered



def process_flattrade_nfo_data(output_path):
    """
    Processes the Flattrade NFO data (Nfo_Equity_Derivatives.csv) to generate OpenAlgo symbols.
    Handles both futures and options formatting.
    """
    print("Processing Flattrade NFO Data")
    file_path = f'{output_path}/NFO.csv'

    # Read the NFO symbols file, specifying the exact columns to use
    df = pd.read_csv(file_path, usecols=['SYMBOL', 'NAME', 'EXCHANGE', 'TOKEN', 'EXPIRY_DT', 'STRIKE_PR', 'LOT_SIZE', 'INSTRUMENT_TYPE', 'TICK_SIZE'])

    # Rename columns to match your schema
    df.columns = ['symbol', 'name', 'exchange', 'token', 'expiry', 'strike', 'lotsize', 'instrumenttype', 'tick_size']

    # Add missing columns to ensure DataFrame matches the database structure
    df['brsymbol'] = df['symbol']  # Initialize 'brsymbol' with 'symbol'

    # Define a function to format the expiry date as DDMMMYY
    def format_expiry_date(date_str):
        try:
            return datetime.strptime(date_str, '%d-%b-%Y').strftime('%d%b%y').upper()
        except ValueError:
            print(f"Invalid expiry date format: {date_str}")
            return None

    # Apply the expiry date format
    df['expiry'] = df['expiry'].apply(format_expiry_date)

    # Replace the 'XX' option type with 'FUT' for futures
    df['instrumenttype'] = df.apply(lambda row: 'FUT' if row['instrumenttype'] == 'FUT' else row['instrumenttype'], axis=1)

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

def process_flattrade_cds_data(output_path):
    """
    Processes the Flattrade CDS data (Currency_Derivatives.csv) to generate OpenAlgo symbols.
    Handles both futures and options formatting.
    """
    print("Processing Flattrade CDS Data")
    file_path = f'{output_path}/CDS.csv'

    # Read the CDS symbols file, specifying the exact columns to use
    df = pd.read_csv(file_path, usecols=['SYMBOL', 'NAME', 'EXCHANGE', 'TOKEN', 'EXPIRY_DT', 'STRIKE_PR', 'LOT_SIZE', 'INSTRUMENT_TYPE', 'TICK_SIZE'])

    # Rename columns to match your schema
    df.columns = ['symbol', 'name', 'exchange', 'token', 'expiry', 'strike', 'lotsize', 'instrumenttype', 'tick_size']

    # Add missing columns to ensure DataFrame matches the database structure
    df['brsymbol'] = df['symbol']  # Initialize 'brsymbol' with 'symbol'

    # Define a function to format the expiry date as DDMMMYY
    def format_expiry_date(date_str):
        try:
            return datetime.strptime(date_str, '%d-%b-%Y').strftime('%d%b%y').upper()
        except ValueError:
            print(f"Invalid expiry date format: {date_str}")
            return None

    # Apply the expiry date format
    df['expiry'] = df['expiry'].apply(format_expiry_date)

    # Replace the 'XX' option type with 'FUT' for futures
    df['instrumenttype'] = df.apply(lambda row: 'FUT' if row['instrumenttype'] == 'FUT' else row['instrumenttype'], axis=1)

    # Update instrumenttype to 'CE' or 'PE' based on the option type
    df['instrumenttype'] = df.apply(lambda row: row['instrumenttype'] if row['instrumenttype'] in ['CE', 'PE'] else row['instrumenttype'], axis=1)

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

def process_flattrade_mcx_data(output_path):
    """
    Processes the Flattrade MCX data (Commodity.csv) to generate OpenAlgo symbols.
    Handles both futures and options formatting.
    """
    print("Processing Flattrade MCX Data")
    file_path = f'{output_path}/MCX.csv'

    # Read the MCX symbols file, specifying the exact columns to use
    df = pd.read_csv(file_path, usecols=['SYMBOL', 'NAME', 'EXCHANGE', 'TOKEN', 'EXPIRY_DT', 'STRIKE_PR', 'LOT_SIZE', 'INSTRUMENT_TYPE', 'TICK_SIZE'])

    # Rename columns to match your schema
    df.columns = ['symbol', 'name', 'exchange', 'token', 'expiry', 'strike', 'lotsize', 'instrumenttype', 'tick_size']

    # Add missing columns to ensure DataFrame matches the database structure
    df['brsymbol'] = df['symbol']  # Initialize 'brsymbol' with 'symbol'

    # Define a function to format the expiry date as DDMMMYY
    def format_expiry_date(date_str):
        try:
            return datetime.strptime(date_str, '%d-%b-%Y').strftime('%d%b%y').upper()
        except ValueError:
            print(f"Invalid expiry date format: {date_str}")
            return None

    # Apply the expiry date format
    df['expiry'] = df['expiry'].apply(format_expiry_date)

    # Replace the 'XX' option type with 'FUT' for futures
    df['instrumenttype'] = df.apply(lambda row: 'FUT' if row['instrumenttype'] == 'FUT' else row['instrumenttype'], axis=1)

    # Update instrumenttype to 'CE' or 'PE' based on the option type
    df['instrumenttype'] = df.apply(lambda row: row['instrumenttype'] if row['instrumenttype'] in ['CE', 'PE'] else row['instrumenttype'], axis=1)

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

def process_flattrade_bse_data(output_path):
    """
    Processes the Flattrade BSE data (BSE_Equity.csv) to generate OpenAlgo symbols.
    Ensures that the instrument type is always 'EQ'.
    """
    print("Processing Flattrade BSE Data")
    file_path = f'{output_path}/BSE.csv'

    # Read the BSE symbols file
    df = pd.read_csv(file_path)

    # Read the BSE symbols file, specifying the exact columns to use and ignoring extra columns
    df = pd.read_csv(file_path, usecols=['SYMBOL', 'NAME', 'EXCHANGE', 'TOKEN', 'LOT_SIZE', 'INSTRUMENT_TYPE', 'TICK_SIZE'])

    # Rename columns to match your schema
    df.columns = ['symbol', 'name', 'exchange', 'token', 'lotsize', 'instrumenttype', 'tick_size']


    # Add missing columns to ensure DataFrame matches the database structure
    df['brsymbol'] = df['symbol']  # Initialize 'brsymbol' with 'symbol'

    # Apply transformation for OpenAlgo symbols (no special logic needed here)
    def get_openalgo_symbol(broker_symbol):
        return broker_symbol

    # Update the 'symbol' column
    df['symbol'] = df['symbol'].apply(get_openalgo_symbol)

    # Set Exchange: 'BSE' for all rows
    df['exchange'] = 'BSE'
    df['brexchange'] = df['exchange']  # Broker exchange is the same as exchange

    # Set expiry and strike, fill -1 for missing strike prices
    df['expiry'] = ''  # No expiry for these instruments
    df['strike'] = -1  # Default to -1 for strike price

    # Ensure the instrument type is always 'EQ'
    df['instrumenttype'] = 'EQ'

    # Handle missing or invalid numeric values in 'lotsize' and 'tick_size'
    df['lotsize'] = pd.to_numeric(df['lotsize'], errors='coerce').fillna(0).astype(int)  # Convert to int, default to 0
    df['tick_size'] = pd.to_numeric(df['tick_size'], errors='coerce').fillna(0).astype(float)  # Convert to float, default to 0.0

    # Reorder the columns to match the database structure
    columns_to_keep = ['symbol', 'brsymbol', 'name', 'exchange', 'brexchange', 'token', 'expiry', 'strike', 'lotsize', 'instrumenttype', 'tick_size']
    df_filtered = df[columns_to_keep]

    # Return the processed DataFrame
    return df_filtered

def process_flattrade_bfo_data(output_path):
    """
    Processes the Flattrade BFO data (Bfo_Equity_Derivatives.csv) to generate OpenAlgo symbols and correctly extract the name column.
    Handles both futures and options formatting, ensuring strike prices are handled as either float or integer.
    """
    print("Processing Flattrade BFO Data")
    file_path = f'{output_path}/BFO.csv'

    # Read the BFO symbols file, specifying the exact columns to use
    df = pd.read_csv(file_path, usecols=['SYMBOL', 'NAME', 'EXCHANGE', 'TOKEN', 'EXPIRY_DT', 'STRIKE_PR', 'LOT_SIZE', 'INSTRUMENT_TYPE', 'TICK_SIZE'])

    # Rename columns to match your schema
    df.columns = ['symbol', 'name', 'exchange', 'token', 'expiry', 'strike', 'lotsize', 'instrumenttype', 'tick_size']

    # Add missing columns to ensure DataFrame matches the database structure
    df['brsymbol'] = df['symbol']  # Initialize 'brsymbol' with 'symbol'

    # Define a function to format the expiry date as DDMMMYY
    def format_expiry_date(date_str):
        try:
            return datetime.strptime(date_str, '%d-%b-%Y').strftime('%d%b%y').upper()
        except ValueError:
            print(f"Invalid expiry date format: {date_str}")
            return None

    # Apply the expiry date format
    df['expiry'] = df['expiry'].apply(format_expiry_date)

    # Replace the 'XX' option type with 'FUT' for futures
    df['instrumenttype'] = df.apply(lambda row: 'FUT' if row['instrumenttype'] == 'FUT' else row['instrumenttype'], axis=1)

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

    df['strike'] = df['strike'].apply(handle_strike_price)

    # Reorder the columns to match the database structure
    columns_to_keep = ['symbol', 'brsymbol', 'name', 'exchange', 'brexchange', 'token', 'expiry', 'strike', 'lotsize', 'instrumenttype', 'tick_size']
    df_filtered = df[columns_to_keep]

    # Return the processed DataFrame
    return df_filtered

def combine_nfo_files(output_path):
    """Combines NFO equity and index files into one"""
    print("Combining NFO files")
    nfo_eq = pd.read_csv(f"{output_path}/NFO_EQ.csv")
    nfo_idx = pd.read_csv(f"{output_path}/NFO_IDX.csv")
    combined = pd.concat([nfo_eq, nfo_idx], ignore_index=True)
    combined.to_csv(f"{output_path}/NFO.csv", index=False)

def combine_bfo_files(output_path):
    """Combines BFO equity and index files into one"""
    print("Combining BFO files")
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
            print(f"Deleted {file_path}")

def master_contract_download():
    """
    Downloads, processes, and deletes Flattrade data.
    """
    print("Downloading Flattrade Master Contract")

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
        
        return socketio.emit('master_contract_download', {'status': 'success', 'message': 'Successfully Downloaded'})
    except Exception as e:
        print(str(e))
        return socketio.emit('master_contract_download', {'status': 'error', 'message': str(e)})