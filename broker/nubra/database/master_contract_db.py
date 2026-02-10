#database/master_contract_db.py

import os
import pandas as pd
import requests
from datetime import datetime

from sqlalchemy import create_engine, Column, Integer, String, Float, Sequence, Index
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.ext.declarative import declarative_base

from database.auth_db import get_auth_token, Auth
from extensions import socketio
from utils.logging import get_logger

logger = get_logger(__name__)


DATABASE_URL = os.getenv('DATABASE_URL')

engine = create_engine(DATABASE_URL)
db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()

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
        if filtered_data_dict:
            db_session.bulk_insert_mappings(SymToken, filtered_data_dict)
            db_session.commit()
            logger.info(f"Bulk insert completed successfully with {len(filtered_data_dict)} new records.")
        else:
            logger.info("No new records to insert.")
    except Exception as e:
        logger.error(f"Error during bulk insert: {e}")
        db_session.rollback()


def download_nubra_instruments(output_path):
    """
    Downloads instrument data from Nubra API for NSE and BSE exchanges.
    """
    date = datetime.now().strftime('%Y-%m-%d')

    # Get the logged-in username for nubra broker from database
    auth_obj = Auth.query.filter_by(broker='nubra', is_revoked=False).first()
    if not auth_obj:
        raise Exception("No active Nubra session found. Please login first.")

    login_username = auth_obj.name
    auth_token = get_auth_token(login_username)

    if not auth_token:
        raise Exception(f"No valid auth token found for user '{login_username}'. Please login first.")

    headers = {
        'Authorization': f'Bearer {auth_token}',
        'x-device-id': 'OPENALGO'
    }

    all_data = []

    for exchange in ['NSE', 'BSE']:
        url = f'https://api.nubra.io/refdata/refdata/{date}?exchange={exchange}'
        logger.info(f"Downloading Nubra instruments for {exchange}")

        response = requests.get(url, headers=headers, timeout=15)

        if response.status_code != 200:
            logger.error(f"{exchange} failed: {response.text}")
            continue

        payload = response.json()
        if 'refdata' in payload:
            all_data.extend(payload['refdata'])

    if not all_data:
        raise Exception("No Nubra instruments downloaded")

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    pd.DataFrame(all_data).to_json(output_path, orient='records')
    logger.info(f"Download complete with {len(all_data)} instruments")


def process_nubra_json(path):
    """
    Processes the Nubra JSON file to fit the existing database schema
    and converts it into OpenAlgo master contract format.

    Rules:
    - NSE + non-STOCK  -> exchange = NFO, brexchange = NSE
    - BSE + non-STOCK  -> exchange = BFO, brexchange = BSE
    - STOCK instruments keep their original exchange
    - Expiry column remains in DB as DD-MMM-YY
    - Symbol format follows OpenAlgo F&O spec:
        FUT : [BASE][DDMMMYY]FUT
        OPT : [BASE][DDMMMYY][STRIKE][CE/PE]
    """

    df = pd.read_json(path)

    # Basic field mappings
    # IMPORTANT: Use ref_id as token because Nubra's order API uses ref_id, not exchange token
    df['token'] = df['ref_id'].astype(str)  # ref_id is what Nubra order API needs
    df['lotsize'] = df['lot_size']
    df['tick_size'] = df['tick_size'].astype(float)
    df['name'] = df['asset']
    df['brsymbol'] = df['stock_name']

    # Preserve broker exchange
    df['brexchange'] = df['exchange']

    # OpenAlgo exchange mapping
    df['exchange'] = df.apply(
        lambda r: (
            'NFO' if (r['exchange'] == 'NSE' and r['derivative_type'] != 'STOCK')
            else 'BFO' if (r['exchange'] == 'BSE' and r['derivative_type'] != 'STOCK')
            else r['exchange']
        ),
        axis=1
    )

    # Instrument type mapping
    df['instrumenttype'] = None
    df.loc[df['derivative_type'] == 'FUT', 'instrumenttype'] = 'FUT'
    df.loc[df['option_type'] == 'CE', 'instrumenttype'] = 'CE'
    df.loc[df['option_type'] == 'PE', 'instrumenttype'] = 'PE'
    df.loc[df['derivative_type'] == 'STOCK', 'instrumenttype'] = 'EQ'

    # Default symbol = broker symbol (cash)
    df['symbol'] = df['brsymbol']

    # ---- Expiry Handling (keep DB format as DD-MMM-YY) ----
    expiry_series = df.get('expiry')

    expiry_dt = pd.to_datetime(
        expiry_series.fillna(0).astype('Int64').astype(str),
        format='%Y%m%d',
        errors='coerce'
    )

    # Apply expiry only for derivatives (FUT / CE / PE)
    df['expiry'] = None
    fo_mask = df['instrumenttype'].isin(['FUT', 'CE', 'PE'])
    df.loc[fo_mask, 'expiry'] = (
        expiry_dt[fo_mask]
        .dt.strftime('%d-%b-%y')   # keep DB format
        .str.upper()
    )

    # Strike price (options)
    df['strike'] = df.get('strike_price', 0).fillna(0).astype(float) / 100

    # ---------------- Symbol Construction (OpenAlgo format) ----------------

    valid_expiry = df['expiry'].notna()

    # Convert expiry for symbol: DD-MMM-YY -> DDMMMYY
    sym_expiry = df['expiry'].str.replace('-', '', regex=False)

    # Futures: BASE + DDMMMYY + FUT
    fut_mask = (df['instrumenttype'] == 'FUT') & valid_expiry
    df.loc[fut_mask, 'symbol'] = (
        df.loc[fut_mask, 'asset']
        + sym_expiry[fut_mask]
        + 'FUT'
    )

    # Options: BASE + DDMMMYY + STRIKE + CE/PE
    opt_mask = df['instrumenttype'].isin(['CE', 'PE']) & valid_expiry
    df.loc[opt_mask, 'symbol'] = (
        df.loc[opt_mask, 'asset']
        + sym_expiry[opt_mask]
        + df.loc[opt_mask, 'strike'].astype(str).str.replace(r'\.0$', '', regex=True)
        + df.loc[opt_mask, 'instrumenttype']
    )

    return df[[
        'symbol',
        'brsymbol',
        'name',
        'exchange',
        'brexchange',
        'token',
        'expiry',
        'strike',
        'lotsize',
        'instrumenttype',
        'tick_size',
    ]]


def download_nubra_indexes(output_path):
    """
    Downloads index data from Nubra public API (no authentication required).
    URL: https://api.nubra.io/public/indexes?format=csv
    """
    url = 'https://api.nubra.io/public/indexes?format=csv'
    logger.info("Downloading Nubra index data")
    
    response = requests.get(url, timeout=15)
    
    if response.status_code != 200:
        logger.error(f"Failed to download index data: {response.text}")
        raise Exception(f"Index data download failed with status {response.status_code}")
    
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'wb') as f:
        f.write(response.content)
    
    logger.info("Index data download complete")


def process_nubra_indexes(path):
    """
    Processes the Nubra index CSV file to fit the OpenAlgo database schema.
    
    CSV Structure from Nubra API:
    - EXCHANGE: NSE or BSE
    - INDEX_SYMBOL: Index symbol from Nubra (e.g., NIFTY, Nifty 50, etc.)
    - ZANSKAR_INDEX_SYMBOL: Zanskar's internal symbol (preserved as brsymbol)
    - INDEX_NAME: Full index name (e.g., "Nifty 50", "Nifty Bank")
    
    Output format follows OpenAlgo convention:
    - exchange = NSE_INDEX or BSE_INDEX
    - brexchange = NSE or BSE (original exchange)
    - instrumenttype = 'INDEX'
    - symbol = Standardized OpenAlgo format (NIFTY, BANKNIFTY, SENSEX, etc.)
    - brsymbol = ZANSKAR_INDEX_SYMBOL (original broker symbol)
    - token = ZANSKAR_INDEX_SYMBOL
    
    Common NSE Index Symbols: NIFTY, NIFTYNXT50, FINNIFTY, BANKNIFTY, MIDCPNIFTY, INDIAVIX
    Common BSE Index Symbols: SENSEX, BANKEX, SENSEX50
    """
    df = pd.read_csv(path)
    
    # Map CSV columns to OpenAlgo database schema
    df = df.rename(columns={
        'EXCHANGE': 'brexchange',
        'INDEX_SYMBOL': 'symbol',
        'ZANSKAR_INDEX_SYMBOL': 'brsymbol',
        'INDEX_NAME': 'name'
    })
    
    # Use broker symbol as token
    df['token'] = df['brsymbol'].astype(str)
    
    # Map to OpenAlgo index exchange format
    # NSE indexes → NSE_INDEX, BSE indexes → BSE_INDEX
    df['exchange'] = df['brexchange'].apply(
        lambda x: (
            'NSE_INDEX' if x == 'NSE'
            else 'BSE_INDEX' if x == 'BSE'
            else x + '_INDEX'
        )
    )
    
    # Common Index Symbol Formats - map Nubra INDEX_SYMBOL to OpenAlgo standard
    # Reference: OpenAlgo symbols.md
    nubra_to_openalgo_index = {
        # ---- NSE Indexes ----
        'INDIA_VIX': 'INDIAVIX',
        'NIFTYALPHA': 'NIFTYALPHA50',
        'NIFTYCDTY': 'NIFTYCOMMODITIES',
        'NIFTYCONSUMP': 'NIFTYCONSUMPTION',
        'NIFTYDIVOPPT': 'NIFTYDIVOPPS50',
        'NIFTYGSCOMP': 'NIFTYGSCOMPSITE',
        'NIFTYINFRAST': 'NIFTYINFRA',
        'LIX15MIDCAP': 'NIFTYMIDLIQ15',
        'NIFTYMIDCAP': 'NIFTYMIDCAP100',
        'NIFTYSMALL': 'NIFTYSMLCAP100',
        'NIFTYSMALLCAP250': 'NIFTYSMLCAP250',
        'NIFTYSMALLCAP50': 'NIFTYSMLCAP50',
        'NIFTYMIDSMALL400': 'NIFTYMIDSML400',
        'NIFTYEQWGT': 'NIFTY50EQLWGT',
        'NIFTY100WEIGHT': 'NIFTY100EQLWGT',
        'LIQ15': 'NIFTY100LIQ15',
        'NIFTYLOWVOL': 'NIFTY100LOWVOL30',
        'NSEQ30': 'NIFTY100QUALTY30',
        'NIFTY200QLTY30': 'NIFTY200QUALTY30',
        'NIFTYPR1X': 'NIFTY50PR1XINV',
        'NIFTYPR2X': 'NIFTY50PR2XLEV',
        'NIFTYTR1X': 'NIFTY50TR1XINV',
        'NIFTYTR2X': 'NIFTY50TR2XLEV',
        'NIFTYV20': 'NIFTY50VALUE20',
        'NIFTY10YRBMGSEC': 'NIFTYGS10YR',
        'NIFTY10YRBMSECCP': 'NIFTYGS10YRCLN',
        'NIFTY11-15YRGSEC': 'NIFTYGS1115YR',
        'NIFTY15YRABOVEGSEC': 'NIFTYGS15YRPLUS',
        'NIFTY4-8YRGESC': 'NIFTYGS48YR',
        'NIFTY8-13YRGSEC': 'NIFTYGS813YR',
        'NIFTYSERVICE': 'NIFTYSERVSECTOR',
        'NIFTYPTBNK': 'NIFTYPVTBANK',
        'NIFTY50DIVPOINT': 'NIFTY50DIVPOINT',
        # ---- BSE Indexes ----
        'SNXT50': 'BSESENSEXNEXT50',
        'MID150': 'BSE150MIDCAPINDEX',
        'LMI250': 'BSE250LARGEMIDCAPINDEX',
        'MSL400': 'BSE400MIDSMALLCAPINDEX',
        'AUTO': 'BSEAUTO',
        'BSECG': 'BSECAPITALGOODS',
        'BSECD': 'BSECONSUMERDURABLES',
        'CPSE': 'BSECPSE',
        'DOL100': 'BSEDOLLEX100',
        'DOL200': 'BSEDOLLEX200',
        'DOL30': 'BSEDOLLEX30',
        'ENERGY': 'BSEENERGY',
        'BSEFMC': 'BSEFASTMOVINGCONSUMERGOODS',
        'FINSER': 'BSEFINANCIALSERVICES',
        'BSEHC': 'BSEHEALTHCARE',
        'INDSTR': 'BSEINDUSTRIALS',
        'BSEIT': 'BSEINFORMATIONTECHNOLOGY',
        'BSEIPO': 'BSEIPO',
        'LRGCAP': 'BSELARGECAP',
        'METAL': 'BSEMETAL',
        'MIDCAP': 'BSEMIDCAP',
        'MIDSEL': 'BSEMIDCAPSELECTINDEX',
        'OILGAS': 'BSEOIL&GAS',
        'POWER': 'BSEPOWER',
        'BSEPSU': 'BSEPSU',
        'REALTY': 'BSEREALTY',
        'SMLCAP': 'BSESMALLCAP',
        'SMLSEL': 'BSESMALLCAPSELECTINDEX',
        'SMEIPO': 'BSESMEIPO',
        'TECK': 'BSETECK',
        'TELCOM': 'BSETELECOM',
    }
    df['symbol'] = df['symbol'].replace(nubra_to_openalgo_index)
    
    # Index-specific fields
    df['instrumenttype'] = 'INDEX'
    df['expiry'] = None
    df['strike'] = 0.0
    df['lotsize'] = 0
    df['tick_size'] = 0.05  # Default tick size for indexes
    
    return df[[
        'symbol',
        'brsymbol',
        'name',
        'exchange',
        'brexchange',
        'token',
        'expiry',
        'strike',
        'lotsize',
        'instrumenttype',
        'tick_size',
    ]]


def delete_nubra_temp_data(output_path):
    try:
        if os.path.exists(output_path):
            os.remove(output_path)
            logger.info(f"The temporary file {output_path} has been deleted.")
        else:
            logger.info(f"The temporary file {output_path} does not exist.")
    except Exception as e:
        logger.error(f"An error occurred while deleting the file: {e}")


def master_contract_download():
    logger.info("Downloading Master Contract")
    instruments_path = 'tmp/nubra_instruments.json'
    indexes_path = 'tmp/nubra_indexes.csv'
    
    try:
        # Download and process instrument data
        download_nubra_instruments(instruments_path)
        instruments_df = process_nubra_json(instruments_path)
        delete_nubra_temp_data(instruments_path)
        
        # Download and process index data
        download_nubra_indexes(indexes_path)
        indexes_df = process_nubra_indexes(indexes_path)
        delete_nubra_temp_data(indexes_path)
        
        # Combine both dataframes
        combined_df = pd.concat([instruments_df, indexes_df], ignore_index=True)
        
        # Clear existing data and insert combined data
        delete_symtoken_table()
        copy_from_dataframe(combined_df)

        return socketio.emit('master_contract_download', {'status': 'success', 'message': 'Successfully Downloaded'})

    except Exception as e:
        logger.error(f"{str(e)}")
        return socketio.emit('master_contract_download', {'status': 'error', 'message': str(e)})


def search_symbols(symbol, exchange):
    return SymToken.query.filter(SymToken.symbol.like(f'%{symbol}%'), SymToken.exchange == exchange).all()