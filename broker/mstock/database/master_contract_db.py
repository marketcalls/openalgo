import os
import pandas as pd
import requests
import re
from io import StringIO
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, Float, Sequence, Index
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.ext.declarative import declarative_base

from extensions import socketio
from utils.logging import get_logger
from database.auth_db import get_auth_token

logger = get_logger(__name__)

# -------------------------------------------------------------------
# DATABASE SETUP
# -------------------------------------------------------------------
DATABASE_URL = os.getenv('DATABASE_URL')
engine = create_engine(DATABASE_URL)
db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()


# -------------------------------------------------------------------
# TABLE DEFINITION
# -------------------------------------------------------------------
class SymToken(Base):
    __tablename__ = 'symtoken'

    id = Column(Integer, Sequence('symtoken_id_seq'), primary_key=True)
    symbol = Column(String, nullable=False, index=True)
    brsymbol = Column(String, nullable=False, index=True)
    name = Column(String)
    exchange = Column(String, index=True)
    brexchange = Column(String, index=True)
    token = Column(String, index=True)
    expiry = Column(String)
    strike = Column(Float)
    lotsize = Column(Integer)
    instrumenttype = Column(String)
    tick_size = Column(Float)

    __table_args__ = (Index('idx_symbol_exchange', 'symbol', 'exchange'),)


# -------------------------------------------------------------------
# INIT / UTILS
# -------------------------------------------------------------------
def init_db():
    logger.info("Initializing MStock Master Contract DB")
    Base.metadata.create_all(bind=engine)


def delete_symtoken_table():
    logger.info("Deleting SymToken Table (MStock)")
    SymToken.query.delete()
    db_session.commit()


def copy_from_dataframe(df):
    """Bulk insert DataFrame records into the symtoken table."""
    logger.info("Performing Bulk Insert into SymToken Table")

    data_dict = df.to_dict(orient='records')
    existing_tokens = {result.token for result in db_session.query(SymToken.token).all()}

    filtered_data_dict = [
        row for row in data_dict if row.get('token') and str(row['token']) not in existing_tokens
    ]

    try:
        if filtered_data_dict:
            db_session.bulk_insert_mappings(SymToken, filtered_data_dict)
            db_session.commit()
            logger.info(f"Inserted {len(filtered_data_dict)} new records successfully.")
        else:
            logger.info("No new MStock records to insert.")
    except Exception as e:
        logger.error(f"Error during MStock bulk insert: {e}")
        db_session.rollback()


# -------------------------------------------------------------------
# MStock Master Contract Fetch
# -------------------------------------------------------------------
def download_mstock_csv(auth_token):
    """
    Download the MStock master contract CSV from the API using Type B authentication.
    """
    api_key = os.getenv('BROKER_API_SECRET')
    url = 'https://api.mstock.trade/openapi/typeb/instruments/OpenAPIScripMaster'

    headers = {
        'X-Mirae-Version': '1',
        'Authorization': f'Bearer {auth_token}',
        'X-PrivateKey': api_key,
    }

    logger.info(f"Fetching MStock master contract from {url}")

    try:
        response = requests.get(url, headers=headers, timeout=60)
        logger.info(f"MStock master contract download status: {response.status_code}")

        if response.status_code != 200:
            logger.error(f"Failed to download MStock master contract: {response.status_code}")
            logger.error(f"Response: {response.text}")
            return None

        # Type B API returns JSON array, not CSV
        return response.json()

    except Exception as e:
        logger.error(f"Error fetching MStock master contract: {e}")
        return None


# -------------------------------------------------------------------
# DATE CONVERSION HELPER
# -------------------------------------------------------------------
def convert_date(date_str):
    """
    Convert date format to OpenAlgo expiry column format: DD-MMM-YY (with hyphens).
    Example: '19MAR2024' -> '19-MAR-24' or '2024-03-19' -> '19-MAR-24'

    OpenAlgo Expiry Column Format: DD-MMM-YY (e.g., 28-MAR-24, 25-APR-24)
    Note: This is for the expiry column. Symbols use DDMMMYY without hyphens.
    """
    if pd.isna(date_str) or date_str == '' or str(date_str).strip() == '':
        return ''

    try:
        date_str = str(date_str).strip()

        # If already in correct format DD-MMM-YY, return as is
        if len(date_str) == 9 and date_str[2] == '-' and date_str[6] == '-':
            return date_str.upper()

        # Try format: 19MAR2024 or 19-MAR-2024 (with 4-digit year)
        if len(date_str) >= 9:
            try:
                parsed_date = datetime.strptime(date_str.replace('-', ''), '%d%b%Y')
                return parsed_date.strftime('%d-%b-%y').upper()  # DD-MMM-YY with hyphens
            except ValueError:
                pass

        # Try ISO format: 2024-03-19
        try:
            parsed_date = datetime.strptime(date_str, '%Y-%m-%d')
            return parsed_date.strftime('%d-%b-%y').upper()  # DD-MMM-YY with hyphens
        except ValueError:
            pass

        # Try format with hyphens: 19-MAR-24 (2-digit year)
        try:
            parsed_date = datetime.strptime(date_str, '%d-%b-%y')
            return parsed_date.strftime('%d-%b-%y').upper()  # DD-MMM-YY with hyphens
        except ValueError:
            pass

        # Try format: 19MAR24 (without hyphens, 2-digit year)
        if len(date_str) == 7:
            try:
                parsed_date = datetime.strptime(date_str, '%d%b%y')
                return parsed_date.strftime('%d-%b-%y').upper()  # DD-MMM-YY with hyphens
            except ValueError:
                pass

        # Try format without year: 19-MAR or 19MAR (add current year)
        if len(date_str) in [6, 7] and date_str.replace('-', '').isalnum():
            try:
                # Add current year
                current_year = datetime.now().year
                date_with_year = f"{date_str}{current_year}"
                parsed_date = datetime.strptime(date_with_year.replace('-', ''), '%d%b%Y')
                return parsed_date.strftime('%d-%b-%y').upper()
            except ValueError:
                pass

        # Log warning for unparseable date
        logger.warning(f"Could not parse date format: '{date_str}' (length: {len(date_str)})")

        # Return original if no format matched (with hyphens added if missing)
        if '-' not in date_str and len(date_str) >= 7:
            # Try to add hyphens: 25DEC24 -> 25-DEC-24
            return f"{date_str[:2]}-{date_str[2:5]}-{date_str[5:]}".upper()

        return date_str.upper()

    except Exception as e:
        logger.error(f"Error parsing date '{date_str}': {e}")
        return str(date_str)


def fetch_and_process_mstock_indices():
    """
    Fetch NSE index data from mstock documentation and process it.
    Note: BSE indices are already in the master contract API and are mapped there.
    Only NSE indices need to be fetched separately as they're not in the API.

    Similar to aliceblue's process_aliceblue_indices_csv() function.
    Returns a DataFrame ready to be inserted into the database.

    Reference: https://tradingapi.mstock.com/docs/v1/Annexure/#index-tokens
    """
    try:
        url = 'https://tradingapi.mstock.com/docs/v1/Annexure/'
        logger.info(f"Fetching NSE index data from {url}")

        response = requests.get(url, timeout=30)
        response.raise_for_status()
        html_content = response.text

        # Regex to extract NSE index rows only
        row_pattern = r'<tr>\s*<td[^>]*>([^<]+)</td>\s*<td[^>]*>(\d+)</td>\s*<td[^>]*>([^<]+)</td>\s*<td[^>]*>NSE</td>\s*</tr>'
        matches = re.findall(row_pattern, html_content, re.IGNORECASE)

        if not matches:
            logger.warning("No NSE index data found in web page")
            return pd.DataFrame()

        # Create DataFrame from matches
        df = pd.DataFrame(matches, columns=['script', 'token', 'name'])

        # Create token_df similar to aliceblue format
        token_df = pd.DataFrame()
        token_df['symbol'] = df['script'].str.strip()
        token_df['brsymbol'] = df['name'].str.strip()
        token_df['name'] = df['script'].str.strip()
        token_df['token'] = df['token'].str.strip()
        token_df['brexchange'] = 'NSE'
        token_df['exchange'] = 'NSE_INDEX'

        # Set index-specific fields
        token_df['expiry'] = ''
        token_df['strike'] = 0.0
        token_df['lotsize'] = 1
        token_df['instrumenttype'] = 'INDEX'
        token_df['tick_size'] = 0.05

        # Standardize common symbol names (similar to aliceblue)
        token_df['symbol'] = token_df['symbol'].replace({
            'NIFTY50': 'NIFTY',
            'NIFTYNEXT50': 'NIFTYNXT50',
            'NIFTYFINSERVICE': 'FINNIFTY',
            'NIFTYBANK': 'BANKNIFTY',
            'NIFTYMIDSELECT': 'MIDCPNIFTY',
            'INDIAVIX': 'INDIAVIX'
        })

        # Filter out rows with NaN symbol values
        token_df = token_df.dropna(subset=['symbol'])

        logger.info(f"Processed {len(token_df)} NSE index symbols from web")

        return token_df

    except Exception as e:
        logger.error(f"Error fetching and processing NSE indices: {e}")
        return pd.DataFrame()


# -------------------------------------------------------------------
# PROCESS JSON
# -------------------------------------------------------------------
def process_mstock_json(json_data):
    """
    Processes the MStock JSON data to fit the OpenAlgo database schema.

    Args:
        json_data: JSON array from MStock Type B API

    Returns:
        DataFrame: The processed DataFrame ready to be inserted into the database.
    """
    # Convert JSON array to DataFrame
    df = pd.DataFrame(json_data)

    # Map columns to database schema
    # API 'name' field (e.g., "SENSEX25O2382700CE", "RVNL-EQ") → brsymbol (broker's full symbol)
    # API 'symbol' field (e.g., "SENSEX", "RVNL") → name (base symbol name)
    df = df.rename(columns={
        'token': 'token',
        'symbol': 'name',           # API symbol → name (base symbol)
        'name': 'brsymbol',         # API name → brsymbol (broker's full symbol)
        'lotsize': 'lotsize',
        'instrumenttype': 'instrumenttype',
        'exch_seg': 'exchange',
        'expiry': 'expiry',
        'strike': 'strike',
        'tick_size': 'tick_size'
    })

    # Create symbol column (will be cleaned version of brsymbol)
    df['symbol'] = df['brsymbol']

    # Keep original broker exchange
    df['brexchange'] = df['exchange']

    # -------------------------------------------------------------------
    # Map Currency Derivatives Exchange
    # MStock API returns NSE/BSE for currency, but OpenAlgo uses CDS/BCD
    # -------------------------------------------------------------------
    # NSE Currency Derivatives → CDS (brexchange stays NSE)
    mask_nse_currency = (df['instrumenttype'].isin(['OPTCUR', 'FUTCUR', 'OPTIRC', 'FUTIRC'])) & (df['exchange'] == 'NSE')
    df.loc[mask_nse_currency, 'exchange'] = 'CDS'

    # BSE Currency Derivatives → BCD (brexchange stays BSE)
    mask_bse_currency = (df['instrumenttype'].isin(['OPTCUR', 'FUTCUR', 'OPTIRC', 'FUTIRC'])) & (df['exchange'] == 'BSE')
    df.loc[mask_bse_currency, 'exchange'] = 'BCD'

    # Clean up equity symbols (remove -EQ, -BE suffixes)
    df['symbol'] = df['symbol'].str.replace(r'-EQ$|-BZ$', '', regex=True)

    # Convert expiry dates to OpenAlgo format (DD-MMM-YY)
    df['expiry'] = df['expiry'].apply(lambda x: convert_date(x) if pd.notnull(x) and str(x).strip() != '' else '')
    df['expiry'] = df['expiry'].str.upper()

    # Convert numeric fields, handling empty strings
    # Replace empty strings with NaN, then convert to numeric, then fill with defaults
    df['strike'] = pd.to_numeric(df['strike'].replace('', None), errors='coerce').fillna(0).astype(float)
    df['lotsize'] = pd.to_numeric(df['lotsize'].replace('', None), errors='coerce').fillna(1).astype(int)
    df['tick_size'] = pd.to_numeric(df['tick_size'].replace('', None), errors='coerce').fillna(0.05).astype(float)

    # -------------------------------------------------------------------
    # Map BSE Indices (BSE indices ARE in master contract API)
    # NSE indices are NOT in the API - they're fetched separately
    # -------------------------------------------------------------------
    df['token'] = df['token'].astype(str)

    # Fetch BSE index tokens from documentation to map them
    try:
        url = 'https://tradingapi.mstock.com/docs/v1/Annexure/'
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        html_content = response.text

        # Extract BSE index tokens only
        row_pattern = r'<tr>\s*<td[^>]*>([^<]+)</td>\s*<td[^>]*>(\d+)</td>\s*<td[^>]*>([^<]+)</td>\s*<td[^>]*>BSE</td>\s*</tr>'
        matches = re.findall(row_pattern, html_content, re.IGNORECASE)

        bse_index_tokens = {match[1].strip() for match in matches}

        if bse_index_tokens:
            # Map BSE indices in master contract to BSE_INDEX exchange
            mask_bse_index = (
                (df['exchange'] == 'BSE') &
                (df['token'].isin(bse_index_tokens))
            )
            df.loc[mask_bse_index, 'exchange'] = 'BSE_INDEX'
            logger.info(f"Mapped {mask_bse_index.sum()} BSE index tokens to BSE_INDEX from master contract")
    except Exception as e:
        logger.warning(f"Could not fetch BSE index tokens for mapping: {e}")

    # -------------------------------------------------------------------
    # Format F&O Symbols (OpenAlgo Standard)
    # Format: [Base][DDMMMYY]FUT/CE/PE
    # -------------------------------------------------------------------

    # NSE Index Futures: BANKNIFTY28MAR24FUT
    mask = (df['instrumenttype'] == 'FUTIDX') & (df['exchange'] == 'NFO') & (df['expiry'].str.len() > 0)
    df.loc[mask, 'symbol'] = df.loc[mask, 'name'] + df.loc[mask, 'expiry'].str.replace('-', '', regex=False) + 'FUT'

    # NSE Stock Futures: ADANIGREEN25DEC25FUT
    mask = (df['instrumenttype'] == 'FUTSTK') & (df['exchange'] == 'NFO') & (df['expiry'].str.len() > 0)
    df.loc[mask, 'symbol'] = df.loc[mask, 'name'] + df.loc[mask, 'expiry'].str.replace('-', '', regex=False) + 'FUT'

    # BSE Index Futures: SENSEX28MAR24FUT
    mask = (df['instrumenttype'] == 'FUTIDX') & (df['exchange'] == 'BFO') & (df['expiry'].str.len() > 0)
    df.loc[mask, 'symbol'] = df.loc[mask, 'name'] + df.loc[mask, 'expiry'].str.replace('-', '', regex=False) + 'FUT'

    # BSE Stock Futures: RELIANCE30OCT25FUT
    mask = (df['instrumenttype'] == 'FUTSTK') & (df['exchange'] == 'BFO') & (df['expiry'].str.len() > 0)
    df.loc[mask, 'symbol'] = df.loc[mask, 'name'] + df.loc[mask, 'expiry'].str.replace('-', '', regex=False) + 'FUT'

    # NSE Index Options: NIFTY28MAR2420800CE
    mask_ce = (df['instrumenttype'] == 'OPTIDX') & (df['exchange'] == 'NFO') & (df['brsymbol'].str.endswith('CE', na=False))
    mask_pe = (df['instrumenttype'] == 'OPTIDX') & (df['exchange'] == 'NFO') & (df['brsymbol'].str.endswith('PE', na=False))

    df.loc[mask_ce, 'symbol'] = (
        df.loc[mask_ce, 'name'] +
        df.loc[mask_ce, 'expiry'].str.replace('-', '', regex=False) +
        df.loc[mask_ce, 'strike'].astype(str).str.replace(r'\.0$', '', regex=True) +
        'CE'
    )
    df.loc[mask_pe, 'symbol'] = (
        df.loc[mask_pe, 'name'] +
        df.loc[mask_pe, 'expiry'].str.replace('-', '', regex=False) +
        df.loc[mask_pe, 'strike'].astype(str).str.replace(r'\.0$', '', regex=True) +
        'PE'
    )

    # NSE Stock Options: ADANIGREEN25DEC251380CE
    mask_ce = (df['instrumenttype'] == 'OPTSTK') & (df['exchange'] == 'NFO') & (df['brsymbol'].str.endswith('CE', na=False))
    mask_pe = (df['instrumenttype'] == 'OPTSTK') & (df['exchange'] == 'NFO') & (df['brsymbol'].str.endswith('PE', na=False))

    df.loc[mask_ce, 'symbol'] = (
        df.loc[mask_ce, 'name'] +
        df.loc[mask_ce, 'expiry'].str.replace('-', '', regex=False) +
        df.loc[mask_ce, 'strike'].astype(str).str.replace(r'\.0$', '', regex=True) +
        'CE'
    )
    df.loc[mask_pe, 'symbol'] = (
        df.loc[mask_pe, 'name'] +
        df.loc[mask_pe, 'expiry'].str.replace('-', '', regex=False) +
        df.loc[mask_pe, 'strike'].astype(str).str.replace(r'\.0$', '', regex=True) +
        'PE'
    )

    # BSE Index Options: SENSEX28MAR2475000CE
    mask_ce = (df['instrumenttype'] == 'OPTIDX') & (df['exchange'] == 'BFO') & (df['brsymbol'].str.endswith('CE', na=False))
    mask_pe = (df['instrumenttype'] == 'OPTIDX') & (df['exchange'] == 'BFO') & (df['brsymbol'].str.endswith('PE', na=False))

    df.loc[mask_ce, 'symbol'] = (
        df.loc[mask_ce, 'name'] +
        df.loc[mask_ce, 'expiry'].str.replace('-', '', regex=False) +
        df.loc[mask_ce, 'strike'].astype(str).str.replace(r'\.0$', '', regex=True) +
        'CE'
    )
    df.loc[mask_pe, 'symbol'] = (
        df.loc[mask_pe, 'name'] +
        df.loc[mask_pe, 'expiry'].str.replace('-', '', regex=False) +
        df.loc[mask_pe, 'strike'].astype(str).str.replace(r'\.0$', '', regex=True) +
        'PE'
    )

    # BSE Stock Options: RELIANCE30OCT251330PE
    mask_ce = (df['instrumenttype'] == 'OPTSTK') & (df['exchange'] == 'BFO') & (df['brsymbol'].str.endswith('CE', na=False))
    mask_pe = (df['instrumenttype'] == 'OPTSTK') & (df['exchange'] == 'BFO') & (df['brsymbol'].str.endswith('PE', na=False))

    df.loc[mask_ce, 'symbol'] = (
        df.loc[mask_ce, 'name'] +
        df.loc[mask_ce, 'expiry'].str.replace('-', '', regex=False) +
        df.loc[mask_ce, 'strike'].astype(str).str.replace(r'\.0$', '', regex=True) +
        'CE'
    )
    df.loc[mask_pe, 'symbol'] = (
        df.loc[mask_pe, 'name'] +
        df.loc[mask_pe, 'expiry'].str.replace('-', '', regex=False) +
        df.loc[mask_pe, 'strike'].astype(str).str.replace(r'\.0$', '', regex=True) +
        'PE'
    )

    # Currency Futures (CDS - NSE): USDINR10MAY24FUT
    mask = (df['instrumenttype'].isin(['FUTCUR', 'FUTIRC'])) & (df['exchange'] == 'CDS') & (df['expiry'].str.len() > 0)
    df.loc[mask, 'symbol'] = df.loc[mask, 'name'] + df.loc[mask, 'expiry'].str.replace('-', '', regex=False) + 'FUT'

    # Currency Options (CDS - NSE): USDINR19APR2482CE
    mask_ce = (df['instrumenttype'].isin(['OPTCUR', 'OPTIRC'])) & (df['exchange'] == 'CDS') & (df['brsymbol'].str.endswith('CE', na=False))
    mask_pe = (df['instrumenttype'].isin(['OPTCUR', 'OPTIRC'])) & (df['exchange'] == 'CDS') & (df['brsymbol'].str.endswith('PE', na=False))

    df.loc[mask_ce, 'symbol'] = (
        df.loc[mask_ce, 'name'] +
        df.loc[mask_ce, 'expiry'].str.replace('-', '', regex=False) +
        df.loc[mask_ce, 'strike'].astype(str).str.replace(r'\.0$', '', regex=True) +
        'CE'
    )
    df.loc[mask_pe, 'symbol'] = (
        df.loc[mask_pe, 'name'] +
        df.loc[mask_pe, 'expiry'].str.replace('-', '', regex=False) +
        df.loc[mask_pe, 'strike'].astype(str).str.replace(r'\.0$', '', regex=True) +
        'PE'
    )

    # Currency Futures (BCD - BSE): USDINR10MAY24FUT
    mask = (df['instrumenttype'].isin(['FUTCUR', 'FUTIRC'])) & (df['exchange'] == 'BCD') & (df['expiry'].str.len() > 0)
    df.loc[mask, 'symbol'] = df.loc[mask, 'name'] + df.loc[mask, 'expiry'].str.replace('-', '', regex=False) + 'FUT'

    # Currency Options (BCD - BSE): USDINR19APR2482CE
    mask_ce = (df['instrumenttype'].isin(['OPTCUR', 'OPTIRC'])) & (df['exchange'] == 'BCD') & (df['brsymbol'].str.endswith('CE', na=False))
    mask_pe = (df['instrumenttype'].isin(['OPTCUR', 'OPTIRC'])) & (df['exchange'] == 'BCD') & (df['brsymbol'].str.endswith('PE', na=False))

    df.loc[mask_ce, 'symbol'] = (
        df.loc[mask_ce, 'name'] +
        df.loc[mask_ce, 'expiry'].str.replace('-', '', regex=False) +
        df.loc[mask_ce, 'strike'].astype(str).str.replace(r'\.0$', '', regex=True) +
        'CE'
    )
    df.loc[mask_pe, 'symbol'] = (
        df.loc[mask_pe, 'name'] +
        df.loc[mask_pe, 'expiry'].str.replace('-', '', regex=False) +
        df.loc[mask_pe, 'strike'].astype(str).str.replace(r'\.0$', '', regex=True) +
        'PE'
    )

    # MCX Futures: CRUDEOILM20MAY24FUT
    mask = (df['instrumenttype'] == 'FUTCOM') & (df['exchange'] == 'MCX') & (df['expiry'].str.len() > 0)
    df.loc[mask, 'symbol'] = df.loc[mask, 'name'] + df.loc[mask, 'expiry'].str.replace('-', '', regex=False) + 'FUT'

    # MCX Options: CRUDEOIL17APR246750CE
    mask_ce = (df['instrumenttype'] == 'OPTFUT') & (df['exchange'] == 'MCX') & (df['brsymbol'].str.endswith('CE', na=False))
    mask_pe = (df['instrumenttype'] == 'OPTFUT') & (df['exchange'] == 'MCX') & (df['brsymbol'].str.endswith('PE', na=False))

    df.loc[mask_ce, 'symbol'] = (
        df.loc[mask_ce, 'name'] +
        df.loc[mask_ce, 'expiry'].str.replace('-', '', regex=False) +
        df.loc[mask_ce, 'strike'].astype(str).str.replace(r'\.0$', '', regex=True) +
        'CE'
    )
    df.loc[mask_pe, 'symbol'] = (
        df.loc[mask_pe, 'name'] +
        df.loc[mask_pe, 'expiry'].str.replace('-', '', regex=False) +
        df.loc[mask_pe, 'strike'].astype(str).str.replace(r'\.0$', '', regex=True) +
        'PE'
    )

    # Return the processed DataFrame
    # Note: Index symbol formatting is handled in fetch_and_process_mstock_indices()
    return df


# -------------------------------------------------------------------
# MASTER CONTRACT PIPELINE
# -------------------------------------------------------------------
def master_contract_download():
    """
    Main async download pipeline for MStock master contract.
    """
    try:
        login_username = os.getenv('LOGIN_USERNAME')
        auth_token = get_auth_token(login_username)

        safe_token = f"{auth_token[:6]}..." if auth_token else "None"
        logger.info(f"Downloading MStock Master Contract (token={safe_token})")

        json_data = download_mstock_csv(auth_token)
        if not json_data:
            logger.error("No data received from MStock API.")
            socketio.emit('master_contract_download', {
                'status': 'error',
                'message': 'Failed to download MStock Master Contract'
            })
            return

        token_df = process_mstock_json(json_data)

        if token_df is None or token_df.empty:
            socketio.emit('master_contract_download', {
                'status': 'error',
                'message': 'Empty or invalid master contract data'
            })
            return

        delete_symtoken_table()
        copy_from_dataframe(token_df)

        # Fetch and insert NSE index data separately (BSE indices are in master contract)
        logger.info("Fetching and processing NSE index data from mstock documentation")
        indices_df = fetch_and_process_mstock_indices()
        if not indices_df.empty:
            copy_from_dataframe(indices_df)
            logger.info(f"Successfully added {len(indices_df)} NSE index symbols to database")
        else:
            logger.warning("No NSE index data fetched from web")

        socketio.emit('master_contract_download', {
            'status': 'success',
            'message': 'MStock Master Contract downloaded and stored successfully'
        })

    except Exception as e:
        logger.error(f"Error during MStock master contract pipeline: {str(e)}")
        socketio.emit('master_contract_download', {
            'status': 'error',
            'message': str(e)
        })


# -------------------------------------------------------------------
# SEARCH SYMBOL
# -------------------------------------------------------------------
def search_symbols(symbol, exchange):
    """
    Search symbols in MStock Master Contract DB.
    """
    return SymToken.query.filter(
        SymToken.symbol.like(f"%{symbol}%"),
        SymToken.exchange == exchange
    ).all()
