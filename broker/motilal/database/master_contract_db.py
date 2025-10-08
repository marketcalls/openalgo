#database/master_contract_db.py

import os
import pandas as pd
import io
from datetime import datetime
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
            db_session.bulk_insert_mappings(SymToken, filtered_data_dict)
            db_session.commit()
            logger.info(f"Bulk insert completed successfully with {len(filtered_data_dict)} new records.")
        else:
            logger.info("No new records to insert.")
    except Exception as e:
        logger.error(f"Error during bulk insert: {e}")
        db_session.rollback()

def download_csv_motilal_data(exchange_name):
    """
    Downloads the CSV file from Motilal Oswal for a specific exchange.

    Args:
        exchange_name (str): Exchange name (e.g., 'NSE', 'BSE', 'NSEFO', 'NSECD', 'MCX', etc.)

    Returns:
        pd.DataFrame: DataFrame containing the downloaded instrument data
    """
    try:
        # Get the shared httpx client
        client = get_httpx_client()

        # Motilal Oswal CSV download URL
        url = f'https://openapi.motilaloswal.com/getscripmastercsv?name={exchange_name}'

        logger.info(f"Downloading Motilal scrip master for {exchange_name} from {url}")

        # Make the GET request using the shared client
        response = client.get(url, timeout=30)
        response.raise_for_status()  # Raises an exception for 4XX/5XX responses

        # Process the response directly as CSV
        csv_string = response.text
        df = pd.read_csv(io.StringIO(csv_string))

        logger.info(f"Downloaded {len(df)} records for {exchange_name}")
        return df

    except Exception as e:
        error_message = str(e)
        logger.error(f"Error downloading Motilal instruments for {exchange_name}: {error_message}")
        raise


def extract_expiry_from_scripname(scripname):
    """
    Extract expiry date from scripname and convert to DD-MMM-YY format.
    Args:
        scripname: Script name like "TGBL 30-OCT-2025 CE 1180"
    Returns:
        str: Formatted date string (DD-MMM-YY) or empty string
    """
    try:
        if pd.isna(scripname) or scripname == '':
            return ''

        # Split the scripname by spaces
        parts = str(scripname).split()

        # Look for date pattern DD-MMM-YYYY
        import re
        for part in parts:
            # Match pattern like 30-OCT-2025 or 30-Oct-2025
            if re.match(r'\d{1,2}-[A-Za-z]{3}-\d{4}', part):
                # Parse and reformat to DD-MMM-YY
                date_obj = datetime.strptime(part, '%d-%b-%Y')
                return date_obj.strftime('%d-%b-%y').upper()

        return ''
    except (ValueError, AttributeError):
        return ''


def process_motilal_csv(df, exchange_name):
    """
    Processes the Motilal CSV file to fit the OpenAlgo database schema.

    Args:
        df (pd.DataFrame): Raw DataFrame from Motilal API
        exchange_name (str): Exchange name for processing

    Returns:
        pd.DataFrame: Processed DataFrame ready for database insertion
    """
    logger.info(f"Processing Motilal CSV Data for {exchange_name}")

    # Rename columns based on Motilal API format to OpenAlgo schema
    df = df.rename(columns={
        'scripcode': 'token',
        'scripname': 'symbol',
        'scripshortname': 'name',
        'marketlot': 'lotsize',
        'instrumentname': 'instrumenttype',
        'expirydate': 'expiry',
        'strikeprice': 'strike',
        'ticksize': 'tick_size',
        'exchangename': 'brexchange'
    })

    # Add broker symbol and exchange (keep original)
    df['brsymbol'] = df['symbol']

    # Map Motilal exchange names to OpenAlgo exchange names
    exchange_map = {
        'NSE': 'NSE',
        'BSE': 'BSE',
        'NSEFO': 'NFO',
        'NSECD': 'CDS',
        'MCX': 'MCX',
        'BSEFO': 'BFO',
        'BSECD': 'BCD',
        'NCDEX': 'NCDEX',
        'NSECO': 'CDS',
        'BSECO': 'BCD'
    }

    df['exchange'] = df['brexchange'].map(exchange_map).fillna(df['brexchange'])

    # Extract expiry date from scripname (brsymbol) instead of timestamp
    df['expiry'] = df['brsymbol'].apply(extract_expiry_from_scripname)

    # Convert strike price (Motilal sends it in correct format, no conversion needed)
    df['strike'] = pd.to_numeric(df['strike'], errors='coerce').fillna(0)

    # Convert lotsize to int
    df['lotsize'] = pd.to_numeric(df['lotsize'], errors='coerce').fillna(1).astype(int)

    # Convert tick_size (Motilal sends in paisa, divide by 100)
    df['tick_size'] = pd.to_numeric(df['tick_size'], errors='coerce').fillna(0.05) / 100

    # Convert token to string
    df['token'] = df['token'].astype(str)

    # Process option type column
    if 'optiontype' in df.columns:
        df['optiontype'] = df['optiontype'].fillna('XX')
    else:
        df['optiontype'] = 'XX'

    # Update instrumenttype to match Angel format (FUT, CE, PE, etc.)
    # For Futures - set to 'FUT'
    df.loc[df['instrumenttype'].str.contains('FUT', na=False), 'instrumenttype'] = 'FUT'

    # For Options - set to 'CE' or 'PE' based on optiontype
    df.loc[(df['instrumenttype'].str.contains('OPT', na=False)) & (df['optiontype'] == 'CE'), 'instrumenttype'] = 'CE'
    df.loc[(df['instrumenttype'].str.contains('OPT', na=False)) & (df['optiontype'] == 'PE'), 'instrumenttype'] = 'PE'

    # Format symbols according to OpenAlgo standards

    # For Index instruments, update exchange
    df.loc[(df['instrumenttype'].str.contains('IDX', na=False)) & (df['exchange'] == 'NSE'), 'exchange'] = 'NSE_INDEX'
    df.loc[(df['instrumenttype'].str.contains('IDX', na=False)) & (df['exchange'] == 'BSE'), 'exchange'] = 'BSE_INDEX'
    df.loc[(df['instrumenttype'].str.contains('IDX', na=False)) & (df['exchange'] == 'MCX'), 'exchange'] = 'MCX_INDEX'

    # Helper function to format strike price
    def format_strike(strike):
        try:
            strike_float = float(strike)
            # If strike has decimal part, keep it; otherwise show as integer
            if strike_float % 1 == 0:
                return str(int(strike_float))
            else:
                # Remove trailing zeros after decimal point
                return str(strike_float).rstrip('0').rstrip('.')
        except:
            return str(strike)

    # Format Futures symbols: NAME + EXPIRY(no dashes) + FUT
    # For MCX and CDS, use brsymbol if expiry exists, otherwise use name
    df.loc[(df['instrumenttype'] == 'FUT') & (df['exchange'].isin(['MCX', 'CDS'])) & (df['expiry'] != ''), 'symbol'] = (
        df['name'] + df['expiry'].str.replace('-', '', regex=False) + 'FUT'
    )
    # For other exchanges with FUT
    df.loc[(df['instrumenttype'] == 'FUT') & (~df['exchange'].isin(['MCX', 'CDS'])), 'symbol'] = (
        df['name'] + df['expiry'].str.replace('-', '', regex=False) + 'FUT'
    )

    # Format Options symbols: NAME + EXPIRY(no dashes) + STRIKE + CE/PE
    # For MCX and CDS options
    df.loc[(df['instrumenttype'] == 'CE') & (df['exchange'].isin(['MCX', 'CDS'])) & (df['expiry'] != ''), 'symbol'] = (
        df['name'] + df['expiry'].str.replace('-', '', regex=False) + df['strike'].apply(format_strike) + 'CE'
    )
    df.loc[(df['instrumenttype'] == 'PE') & (df['exchange'].isin(['MCX', 'CDS'])) & (df['expiry'] != ''), 'symbol'] = (
        df['name'] + df['expiry'].str.replace('-', '', regex=False) + df['strike'].apply(format_strike) + 'PE'
    )
    # For other exchanges with options
    df.loc[(df['instrumenttype'] == 'CE') & (~df['exchange'].isin(['MCX', 'CDS'])), 'symbol'] = (
        df['name'] + df['expiry'].str.replace('-', '', regex=False) + df['strike'].apply(format_strike) + 'CE'
    )
    df.loc[(df['instrumenttype'] == 'PE') & (~df['exchange'].isin(['MCX', 'CDS'])), 'symbol'] = (
        df['name'] + df['expiry'].str.replace('-', '', regex=False) + df['strike'].apply(format_strike) + 'PE'
    )

    # Clean up equity symbols (remove EQ suffix if present)
    df.loc[df['instrumenttype'].str.contains('EQ|CASH', na=False, case=False), 'symbol'] = (
        df['symbol'].str.replace(' EQ', '', regex=False).str.strip()
    )

    # Standardize index names
    df['symbol'] = df['symbol'].replace({
        'Nifty 50': 'NIFTY',
        'NIFTY 50': 'NIFTY',
        'Nifty Next 50': 'NIFTYNXT50',
        'NIFTY NEXT 50': 'NIFTYNXT50',
        'Nifty Fin Service': 'FINNIFTY',
        'NIFTY FIN SERVICE': 'FINNIFTY',
        'Nifty Bank': 'BANKNIFTY',
        'NIFTY BANK': 'BANKNIFTY',
        'NIFTY MID SELECT': 'MIDCPNIFTY',
        'India VIX': 'INDIAVIX',
        'INDIA VIX': 'INDIAVIX',
        'SENSEX': 'SENSEX',
        'SNSX50': 'SENSEX50'
    })

    # Select only the columns needed for the database
    required_columns = ['token', 'symbol', 'brsymbol', 'name', 'exchange', 'brexchange',
                       'expiry', 'strike', 'lotsize', 'instrumenttype', 'tick_size']

    df = df[required_columns]

    # Fill NaN values
    df['expiry'] = df['expiry'].fillna('')
    df['name'] = df['name'].fillna('')
    df['symbol'] = df['symbol'].fillna('')
    df['brsymbol'] = df['brsymbol'].fillna('')

    logger.info(f"Processed {len(df)} records for {exchange_name}")
    return df


def master_contract_download():
    """
    Downloads master contracts from Motilal Oswal for all supported exchanges.
    """
    logger.info("Downloading Master Contract from Motilal Oswal")

    # List of exchanges to download
    exchanges = ['NSE', 'BSE', 'NSEFO', 'NSECD', 'MCX', 'BSEFO']

    try:
        all_data = []

        for exchange in exchanges:
            try:
                logger.info(f"Downloading {exchange} data...")
                df = download_csv_motilal_data(exchange)
                processed_df = process_motilal_csv(df, exchange)
                all_data.append(processed_df)
                logger.info(f"Successfully processed {exchange}")
            except Exception as e:
                logger.error(f"Error processing {exchange}: {str(e)}")
                # Continue with other exchanges even if one fails
                continue

        if not all_data:
            raise Exception("Failed to download data from any exchange")

        # Combine all exchange data
        token_df = pd.concat(all_data, ignore_index=True)

        # Remove duplicates based on token
        token_df = token_df.drop_duplicates(subset='token', keep='first')

        logger.info(f"Total records to insert: {len(token_df)}")

        # Delete existing data and insert new data
        delete_symtoken_table()
        copy_from_dataframe(token_df)

        return socketio.emit('master_contract_download', {
            'status': 'success',
            'message': f'Successfully Downloaded {len(token_df)} instruments'
        })

    except Exception as e:
        logger.error(f"Error in master_contract_download: {str(e)}")
        return socketio.emit('master_contract_download', {
            'status': 'error',
            'message': str(e)
        })


def search_symbols(symbol, exchange):
    return SymToken.query.filter(SymToken.symbol.like(f'%{symbol}%'), SymToken.exchange == exchange).all()
