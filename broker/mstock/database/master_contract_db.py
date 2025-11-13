import os
import pandas as pd
import requests
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
    # Identify Index Instruments using official mStock Index Token list
    # Reference: https://tradingapi.mstock.com/docs/v1/Annexure/#index-tokens
    # -------------------------------------------------------------------
    df['token'] = df['token'].astype(str)

    # NSE Index tokens (98 indices from mStock official documentation)
    nse_index_tokens = {
        '100004438', '100003333', '100005568', '100005576', '100005605', '10000888',
        '100005572', '100004427', '100004437', '100004441', '100005582', '100005592',
        '100005604', '100004434', '100004428', '100004440', '100005569', '100005599',
        '100005571', '100005601', '100004436', '100005584', '100004435', '100004431',
        '100005591', '100004439', '100005566', '100004425', '100005600', '100005598',
        '100004443', '100004433', '100005607', '100005593', '100005606', '100005580',
        '100004426', '100005594', '100005603', '100005560', '100004444', '100005590',
        '100005562', '100005589', '100005561', '100004421', '100005570', '100004432',
        '100005602', '100004420', '100005595', '100005573', '100004424', '100004422',
        '100005587', '100005574', '100004423', '100005597', '100005563', '100005558',
        '100005588', '100005596', '100004442', '100005575', '100004430', '10000999',
        '100005583', '100005585', '100001111', '100004429', '100005586'
    }

    # BSE Index tokens (61 indices from mStock official documentation)
    bse_index_tokens = {
        '100005632', '100005626', '100005644', '100005651', '100005628', '100005614',
        '100005627', '100005611', '100005634', '100005654', '100005658', '100005640',
        '100005656', '100005645', '100005613', '100005637', '100005638', '100005620',
        '100005641', '100005630', '100005631', '100005636', '100002222', '100005653',
        '100005609', '100005652', '100005615', '100005621', '100005629', '100005655',
        '100005643', '100005623', '100005625', '100005642', '100005618', '100005617',
        '100005649', '100005635', '100005639', '100005619', '100005608', '100005624',
        '100005633', '100005622', '100005657', '100005647', '100005567', '100005557',
        '100005659', '100005646', '100005612', '100005650', '100005610'
    }

    # Map NSE indices to NSE_INDEX exchange
    mask_nse_index = (
        (df['exchange'] == 'NSE') &
        (df['token'].isin(nse_index_tokens))
    )
    df.loc[mask_nse_index, 'exchange'] = 'NSE_INDEX'
    logger.info(f"Mapped {mask_nse_index.sum()} NSE index tokens to NSE_INDEX")

    # Map BSE indices to BSE_INDEX exchange
    mask_bse_index = (
        (df['exchange'] == 'BSE') &
        (df['token'].isin(bse_index_tokens))
    )
    df.loc[mask_bse_index, 'exchange'] = 'BSE_INDEX'
    logger.info(f"Mapped {mask_bse_index.sum()} BSE index tokens to BSE_INDEX")

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

    # Currency Futures: USDINR10MAY24FUT
    mask = (df['instrumenttype'].isin(['FUTCUR', 'FUTIRC'])) & (df['exchange'] == 'CDS') & (df['expiry'].str.len() > 0)
    df.loc[mask, 'symbol'] = df.loc[mask, 'name'] + df.loc[mask, 'expiry'].str.replace('-', '', regex=False) + 'FUT'

    # Currency Options: USDINR19APR2482CE
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

    # -------------------------------------------------------------------
    # Common Index Symbol Formatting
    # Standardize index symbol names for NSE_INDEX and BSE_INDEX exchanges
    # -------------------------------------------------------------------
    df['symbol'] = df['symbol'].replace({
        'Nifty 50': 'NIFTY',
        'Nifty Next 50': 'NIFTYNXT50',
        'Nifty Fin Service': 'FINNIFTY',
        'Nifty Bank': 'BANKNIFTY',
        'NIFTY MID SELECT': 'MIDCPNIFTY',
        'India VIX': 'INDIAVIX',
        'SNSX50': 'SENSEX50',
        'S&P BSE SENSEX': 'SENSEX',
        'BSE BANKEX': 'BANKEX'
    })

    # Return the processed DataFrame
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
