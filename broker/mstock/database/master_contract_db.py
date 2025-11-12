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
def process_mstock_csv(json_data):
    """
    Convert JSON array from MStock Type B API to DataFrame in OpenAlgo schema.
    Processes instrument data and applies necessary transformations.

    Input JSON format:
    [
        {
            "token": "877966",
            "symbol": "SENSEX",
            "name": "SENSEX25O2382700CE",
            "expiry": "23Oct2025",
            "strike": "82700",
            "lotsize": "20",
            "instrumenttype": "OPTIDX",
            "exch_seg": "BFO",
            "tick_size": "0.05"
        },
        ...
    ]
    """
    try:
        # Convert JSON array to DataFrame
        df = pd.DataFrame(json_data)
    except Exception as e:
        logger.error(f"Error reading MStock JSON: {e}")
        return pd.DataFrame()

    # Normalize column names
    df.columns = [col.strip().lower() for col in df.columns]

    expected_cols = {
        'instrument_token', 'exchange_token', 'tradingsymbol', 'name',
        'last_price', 'expiry', 'strike', 'tick_size', 'lot_size',
        'instrument_type', 'segment', 'exchange'
    }

    if not expected_cols.issubset(df.columns):
        logger.error(f"Unexpected MStock CSV columns. Expected: {expected_cols}, Got: {set(df.columns)}")
        return pd.DataFrame()

    # Map to OpenAlgo schema
    df['symbol'] = df['tradingsymbol'].astype(str)
    df['brsymbol'] = df['symbol']  # Keep original broker symbol
    df['name'] = df['name'].astype(str)

    # For F&O instruments where name might be empty/NaN, extract base from tradingsymbol
    def extract_base_symbol(row):
        """Extract base symbol from tradingsymbol for F&O instruments when name is missing."""
        import re
        name = str(row['name'])
        symbol = str(row['tradingsymbol'])
        instrument_type = str(row['instrument_type'])

        # If name is valid and not 'nan', use it
        if name and name.lower() not in ['nan', 'none', '']:
            return name

        # For F&O instruments, extract base from tradingsymbol
        if instrument_type in ['FUTIDX', 'OPTIDX', 'FUTSTK', 'OPTSTK', 'FUTCUR', 'OPTCUR', 'FUTIRC', 'OPTIRC', 'FUTCOM', 'OPTFUT']:
            # Common index patterns
            if symbol.startswith('NIFTY'):
                if 'BANK' in symbol[:12]:
                    return 'Nifty Bank'
                elif 'FIN' in symbol[:12] or 'FINNIFTY' in symbol[:12]:
                    return 'Nifty Fin Service'
                elif 'MIDCAP' in symbol[:15] or 'MIDCP' in symbol[:15]:
                    return 'NIFTY MID SELECT'
                elif 'NEXT' in symbol[:15] or 'NXT' in symbol[:15]:
                    return 'Nifty Next 50'
                else:
                    return 'Nifty 50'
            elif symbol.startswith('SENSEX'):
                return 'SENSEX'
            elif symbol.startswith('BANKEX'):
                return 'BANKEX'
            elif symbol.startswith('INDIA') and 'VIX' in symbol[:10]:
                return 'India VIX'
            elif symbol.startswith('USDINR') or symbol.startswith('EURINR') or symbol.startswith('GBPINR') or symbol.startswith('JPYINR'):
                # Currency - extract first 6 chars
                return symbol[:6]
            elif 'CRUDEOIL' in symbol[:10]:
                return 'CRUDEOILM'
            else:
                # For stock F&O, extract the base by removing date and option parts
                # Pattern: Remove DDMMMYY and numbers+CE/PE from end
                match = re.match(r'^([A-Z]+)', symbol)
                if match:
                    return match.group(1)

        return name

    df['name'] = df.apply(extract_base_symbol, axis=1)

    df['exchange'] = df['exchange'].astype(str)
    df['brexchange'] = df['exchange']  # Keep original broker exchange
    df['token'] = df['instrument_token'].astype(str)

    # Process expiry date with proper formatting
    # Log sample expiry dates before conversion for debugging
    if len(df) > 0:
        sample_expiry = df['expiry'].head(5).tolist()
        logger.info(f"Sample expiry dates from CSV (before conversion): {sample_expiry}")

    df['expiry'] = df['expiry'].apply(convert_date)

    # Log sample expiry dates after conversion
    if len(df) > 0:
        sample_expiry_after = df['expiry'].head(5).tolist()
        logger.info(f"Sample expiry dates after conversion: {sample_expiry_after}")

    # Process strike price (convert to float)
    df['strike'] = pd.to_numeric(df['strike'], errors='coerce').fillna(0)

    # Process lot size
    df['lotsize'] = pd.to_numeric(df['lot_size'], errors='coerce').fillna(1).astype(int)

    # Instrument type
    df['instrumenttype'] = df['instrument_type'].astype(str)

    # Process tick size
    df['tick_size'] = pd.to_numeric(df['tick_size'], errors='coerce').fillna(0.05)

    # Standardize common index names for consistency with OpenAlgo
    # Apply this mapping to ensure consistent naming
    df['name'] = df['name'].replace({
        'Nifty 50': 'NIFTY',
        'Nifty Next 50': 'NIFTYNXT50',
        'Nifty Fin Service': 'FINNIFTY',
        'Nifty Bank': 'BANKNIFTY',
        'NIFTY MID SELECT': 'MIDCPNIFTY',
        'India VIX': 'INDIAVIX',
        'SENSEX': 'SENSEX',
        'BANKEX': 'BANKEX',
        'Nifty Midcap Select': 'MIDCPNIFTY',
        'NIFTY MIDCAP SELECT': 'MIDCPNIFTY',
        'Nifty Financial Services': 'FINNIFTY',
        'NIFTY FINANCIAL SERVICES': 'FINNIFTY'
    })

    # Log sample name standardization
    if len(df) > 0:
        sample_names = df[df['instrumenttype'].isin(['FUTIDX', 'OPTIDX'])]['name'].unique()[:5]
        logger.info(f"Sample standardized index names: {sample_names.tolist()}")

    # Remove any suffix like -EQ from equity symbols for standardization
    df['symbol'] = df['symbol'].str.replace(r'-EQ$|-BE$|-BZ$', '', regex=True)

    # -------------------------------------------------------------------
    # F&O Symbol Construction (OpenAlgo Format)
    #
    # Expiry Column Format: DD-MMM-YY (with hyphens, e.g., 25-NOV-25)
    # Symbol Format: [Base][DDMMMYY]FUT/CE/PE (no hyphens, e.g., ABCAPITAL25NOV25FUT)
    #
    # Example:
    #   - Name: ABCAPITAL
    #   - Expiry Column: 25-NOV-25
    #   - Symbol: ABCAPITAL25NOV25FUT (ABCAPITAL + 25 + NOV + 25 + FUT)
    # -------------------------------------------------------------------

    # NSE Index Futures: BANKNIFTY28MAR24FUT (expiry: 28-MAR-24)
    mask = (df['instrumenttype'].isin(['FUTIDX'])) & (df['exchange'].isin(['NFO'])) & (df['expiry'].str.len() > 0)
    df.loc[mask, 'symbol'] = df.loc[mask, 'name'] + df.loc[mask, 'expiry'].str.replace('-', '', regex=False) + 'FUT'

    # NSE Stock Futures: ABCAPITAL25NOV25FUT (expiry: 25-NOV-25)
    mask = (df['instrumenttype'].isin(['FUTSTK'])) & (df['exchange'].isin(['NFO'])) & (df['expiry'].str.len() > 0)
    df.loc[mask, 'symbol'] = df.loc[mask, 'name'] + df.loc[mask, 'expiry'].str.replace('-', '', regex=False) + 'FUT'

    # Log sample NSE futures symbols to verify format
    nse_futures = df[(df['instrumenttype'].isin(['FUTIDX', 'FUTSTK'])) & (df['exchange'] == 'NFO')].head(3)
    if len(nse_futures) > 0:
        for _, row in nse_futures.iterrows():
            logger.info(f"NSE Future: name={row['name']}, expiry={row['expiry']}, symbol={row['symbol']}")

    # BSE Index Futures: SENSEX28MAR24FUT
    mask = (df['instrumenttype'].isin(['FUTIDX'])) & (df['exchange'].isin(['BFO']))
    df.loc[mask, 'symbol'] = df.loc[mask, 'name'] + df.loc[mask, 'expiry'].str.replace('-', '', regex=False) + 'FUT'

    # BSE Stock Futures: RELIANCE30OCT25FUT
    mask = (df['instrumenttype'].isin(['FUTSTK'])) & (df['exchange'].isin(['BFO']))
    df.loc[mask, 'symbol'] = df.loc[mask, 'name'] + df.loc[mask, 'expiry'].str.replace('-', '', regex=False) + 'FUT'

    # NSE Index Options: NIFTY28MAR2420800CE / NIFTY28MAR2420800PE
    mask_ce = (df['instrumenttype'] == 'OPTIDX') & (df['exchange'] == 'NFO') & (df['symbol'].str.endswith('CE', na=False))
    mask_pe = (df['instrumenttype'] == 'OPTIDX') & (df['exchange'] == 'NFO') & (df['symbol'].str.endswith('PE', na=False))

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

    # Log sample NSE index options symbols to verify format
    nse_index_options = df[(df['instrumenttype'] == 'OPTIDX') & (df['exchange'] == 'NFO')].head(3)
    if len(nse_index_options) > 0:
        for _, row in nse_index_options.iterrows():
            logger.info(f"NSE Index Option: name={row['name']}, expiry={row['expiry']}, strike={row['strike']}, symbol={row['symbol']}, brsymbol={row['brsymbol']}")

    # NSE Stock Options: VEDL25APR24292.5CE, ABCAPITAL25DEC24450CE
    mask_ce = (df['instrumenttype'] == 'OPTSTK') & (df['exchange'] == 'NFO') & (df['symbol'].str.endswith('CE', na=False))
    mask_pe = (df['instrumenttype'] == 'OPTSTK') & (df['exchange'] == 'NFO') & (df['symbol'].str.endswith('PE', na=False))

    df.loc[mask_ce, 'symbol'] = (
        df.loc[mask_ce, 'name'] +
        df.loc[mask_ce, 'expiry'].str.replace('-', '', regex=False) +
        df.loc[mask_ce, 'strike'].astype(str) +
        'CE'
    )
    df.loc[mask_pe, 'symbol'] = (
        df.loc[mask_pe, 'name'] +
        df.loc[mask_pe, 'expiry'].str.replace('-', '', regex=False) +
        df.loc[mask_pe, 'strike'].astype(str) +
        'PE'
    )

    # Log sample NSE stock options symbols to verify format
    nse_options = df[(df['instrumenttype'] == 'OPTSTK') & (df['exchange'] == 'NFO')].head(3)
    if len(nse_options) > 0:
        for _, row in nse_options.iterrows():
            logger.info(f"NSE Option: name={row['name']}, expiry={row['expiry']}, strike={row['strike']}, symbol={row['symbol']}")

    # BSE Index Options: SENSEX28MAR2475000CE
    mask_ce = (df['instrumenttype'] == 'OPTIDX') & (df['exchange'] == 'BFO') & (df['symbol'].str.endswith('CE', na=False))
    mask_pe = (df['instrumenttype'] == 'OPTIDX') & (df['exchange'] == 'BFO') & (df['symbol'].str.endswith('PE', na=False))

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

    # BSE Stock Options: RELIANCE30OCT251330CE/PE
    mask_ce = (df['instrumenttype'] == 'OPTSTK') & (df['exchange'] == 'BFO') & (df['symbol'].str.endswith('CE', na=False))
    mask_pe = (df['instrumenttype'] == 'OPTSTK') & (df['exchange'] == 'BFO') & (df['symbol'].str.endswith('PE', na=False))

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

    # Currency Futures (CDS): USDINR10MAY24FUT
    mask = (df['instrumenttype'].isin(['FUTCUR', 'FUTIRC'])) & (df['exchange'] == 'CDS')
    df.loc[mask, 'symbol'] = df.loc[mask, 'name'] + df.loc[mask, 'expiry'].str.replace('-', '', regex=False) + 'FUT'

    # Currency Options (CDS): USDINR19APR2482CE/PE
    mask_ce = (df['instrumenttype'].isin(['OPTCUR', 'OPTIRC'])) & (df['exchange'] == 'CDS') & (df['symbol'].str.endswith('CE', na=False))
    mask_pe = (df['instrumenttype'].isin(['OPTCUR', 'OPTIRC'])) & (df['exchange'] == 'CDS') & (df['symbol'].str.endswith('PE', na=False))

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

    # Commodity Futures (MCX): CRUDEOILM20MAY24FUT
    mask = (df['instrumenttype'].isin(['FUTCOM'])) & (df['exchange'] == 'MCX')
    df.loc[mask, 'symbol'] = df.loc[mask, 'name'] + df.loc[mask, 'expiry'].str.replace('-', '', regex=False) + 'FUT'

    # Commodity Options (MCX): CRUDEOILM20MAY245000CE/PE
    mask_ce = (df['instrumenttype'] == 'OPTFUT') & (df['exchange'] == 'MCX') & (df['symbol'].str.endswith('CE', na=False))
    mask_pe = (df['instrumenttype'] == 'OPTFUT') & (df['exchange'] == 'MCX') & (df['symbol'].str.endswith('PE', na=False))

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

    # Clean up any remaining symbol issues
    df['symbol'] = df['symbol'].str.replace(r'\s+', '', regex=True)  # Remove extra spaces
    df['symbol'] = df['symbol'].str.upper()  # Ensure uppercase

    # Remove duplicates based on symbol and exchange
    df = df.drop_duplicates(subset=['symbol', 'exchange'], keep='first')

    # Keep only relevant columns in correct order
    final_cols = [
        'symbol', 'brsymbol', 'name', 'exchange', 'brexchange',
        'token', 'expiry', 'strike', 'lotsize', 'instrumenttype', 'tick_size'
    ]
    df = df[final_cols]

    logger.info(f"MStock Master Contract Processed: {len(df)} records ready")
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

        csv_data = download_mstock_csv(auth_token)
        if not csv_data:
            logger.error("No data received from MStock API.")
            socketio.emit('master_contract_download', {
                'status': 'error',
                'message': 'Failed to download MStock Master Contract'
            })
            return

        token_df = process_mstock_csv(csv_data)

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
