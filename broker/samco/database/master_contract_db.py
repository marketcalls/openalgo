#database/master_contract_db.py

import os
import pandas as pd
import requests
from datetime import datetime

from sqlalchemy import create_engine, Column, Integer, String, Float, Sequence, Index
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.ext.declarative import declarative_base
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
    data_dict = df.to_dict(orient='records')

    existing_tokens = {result.token for result in db_session.query(SymToken.token).all()}
    filtered_data_dict = [row for row in data_dict if row['token'] not in existing_tokens]

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


def master_contract_download():
    """
    Download and process Samco master contract data.
    Samco provides a consolidated ScripMaster.csv file.
    """
    logger.info("Downloading Samco Master Contract")

    try:
        # Samco consolidated scrip master file
        url = 'https://developers.stocknote.com/doc/ScripMaster.csv'
        output_path = 'tmp/samco_scripmaster.csv'

        # Ensure tmp directory exists
        os.makedirs('tmp', exist_ok=True)

        logger.info(f"Downloading ScripMaster from {url}")
        response = requests.get(url, timeout=60)

        if response.status_code == 200:
            with open(output_path, 'wb') as f:
                f.write(response.content)
            logger.info("Download complete")
        else:
            raise Exception(f"Failed to download data. Status code: {response.status_code}")

        # Read and process the CSV
        df = pd.read_csv(output_path)
        logger.info(f"Downloaded {len(df)} records")

        # Process the data
        token_df = process_samco_data(df)

        # Delete temp file
        if os.path.exists(output_path):
            os.remove(output_path)
            logger.info(f"Deleted temporary file {output_path}")

        delete_symtoken_table()
        copy_from_dataframe(token_df)

        return socketio.emit('master_contract_download', {'status': 'success', 'message': 'Successfully Downloaded'})

    except Exception as e:
        logger.error(f"Error downloading master contract: {str(e)}")
        return socketio.emit('master_contract_download', {'status': 'error', 'message': str(e)})


def convert_date_format(date_str):
    """Convert date from various formats to DD-MMM-YY format (e.g., 26-FEB-24)."""
    if pd.isnull(date_str) or date_str == '' or date_str is None:
        return None
    try:
        date_str = str(date_str).strip()
        # Try different date formats (order matters - try most specific first)
        date_formats = [
            '%Y-%m-%d',    # 2024-02-26
            '%d-%m-%Y',    # 26-02-2024
            '%d/%m/%Y',    # 26/02/2024
            '%d/%m/%y',    # 26/02/24
            '%y/%m/%d',    # 24/02/26 (YY/MM/DD)
            '%d%b%Y',      # 26FEB2024
            '%d%b%y',      # 26FEB24
            '%Y%m%d',      # 20240226
            '%d-%b-%Y',    # 26-FEB-2024
            '%d-%b-%y',    # 26-FEB-24
        ]
        for fmt in date_formats:
            try:
                return datetime.strptime(date_str, fmt).strftime('%d-%b-%y').upper()
            except ValueError:
                continue
        # If already in correct format, just uppercase it
        return date_str.upper()
    except Exception:
        return str(date_str).upper() if date_str else None


def process_samco_data(df):
    """
    Process Samco ScripMaster CSV data to fit the OpenAlgo database schema.
    """
    logger.info(f"Processing Samco data. Columns: {df.columns.tolist()}")

    # Rename columns to match database schema
    column_mapping = {
        'Exchange': 'exchange',
        'exchange': 'exchange',
        'Trading Symbol': 'brsymbol',
        'tradingSymbol': 'brsymbol',
        'Symbol Name': 'name',
        'symbolName': 'name',
        'Instrument': 'instrumenttype',
        'instrument': 'instrumenttype',
        'symbolCode': 'token',
        'Symbol Code': 'token',
        'Token': 'token',
        'token': 'token',
        'Lot Size': 'lotsize',
        'lotSize': 'lotsize',
        'Tick Size': 'tick_size',
        'tickSize': 'tick_size',
        'Expiry Date': 'expiry',
        'expiryDate': 'expiry',
        'Strike Price': 'strike',
        'strikePrice': 'strike'
    }

    # Only rename columns that exist
    existing_cols = {k: v for k, v in column_mapping.items() if k in df.columns}
    df = df.rename(columns=existing_cols)

    # Set brexchange same as exchange (broker's exchange naming)
    if 'exchange' in df.columns:
        df['brexchange'] = df['exchange']

    # Set brsymbol (broker's symbol) before any transformations
    if 'brsymbol' in df.columns:
        df['symbol'] = df['brsymbol']

    # Ensure required columns exist
    required_cols = ['symbol', 'brsymbol', 'name', 'exchange', 'brexchange', 'token',
                     'expiry', 'strike', 'lotsize', 'instrumenttype', 'tick_size']

    for col in required_cols:
        if col not in df.columns:
            df[col] = None

    # Convert data types
    df['token'] = df['token'].astype(str)
    df['lotsize'] = pd.to_numeric(df['lotsize'], errors='coerce').fillna(1).astype(int)
    df['strike'] = pd.to_numeric(df['strike'], errors='coerce').fillna(0.0)
    df['tick_size'] = pd.to_numeric(df['tick_size'], errors='coerce').fillna(0.05)

    # Convert expiry date to OpenAlgo format (DD-MMM-YY)
    if 'expiry' in df.columns:
        df['expiry'] = df['expiry'].apply(convert_date_format)

    # ============ Exchange Mapping ============
    # Map MFO (MCX Futures & Options) to MCX
    df.loc[df['exchange'] == 'MFO', 'exchange'] = 'MCX'

    # Map index instruments to OpenAlgo exchange format
    df.loc[(df['instrumenttype'] == 'INDEX') & (df['exchange'] == 'NSE'), 'exchange'] = 'NSE_INDEX'
    df.loc[(df['instrumenttype'] == 'INDEX') & (df['exchange'] == 'BSE'), 'exchange'] = 'BSE_INDEX'
    df.loc[(df['instrumenttype'] == 'INDEX') & (df['exchange'] == 'MCX'), 'exchange'] = 'MCX_INDEX'

    # ============ Symbol Formatting ============
    # Clean up equity symbols (remove -EQ, -BE, -MF, -SG suffixes)
    df.loc[df['instrumenttype'] == 'EQ', 'symbol'] = df['symbol'].str.replace('-EQ|-BE|-MF|-SG', '', regex=True)

    # Helper function to format strike price (keep decimals like 292.5, remove .0)
    def format_strike(strike_series):
        return strike_series.astype(str).str.replace(r'\.0$', '', regex=True)

    # Helper to get expiry without dashes for symbol construction
    expiry_for_symbol = df['expiry'].fillna('').str.replace('-', '', regex=False)

    # NFO Futures: NAME + EXPIRY + FUT (e.g., BANKNIFTY26FEB24FUT)
    nfo_fut_mask = (df['exchange'] == 'NFO') & (df['instrumenttype'].isin(['FUTIDX', 'FUTSTK', 'FUT']))
    if nfo_fut_mask.any():
        df.loc[nfo_fut_mask, 'symbol'] = (
            df['name'].fillna('') +
            expiry_for_symbol +
            'FUT'
        )

    # NFO Options: NAME + EXPIRY + STRIKE + CE/PE (e.g., NIFTY26FEB241480CE)
    nfo_opt_mask = (df['exchange'] == 'NFO') & (df['instrumenttype'].isin(['OPTIDX', 'OPTSTK', 'CE', 'PE']))
    if nfo_opt_mask.any():
        df.loc[nfo_opt_mask & df['brsymbol'].str.endswith('CE', na=False), 'symbol'] = (
            df['name'].fillna('') +
            expiry_for_symbol +
            format_strike(df['strike']) +
            'CE'
        )
        df.loc[nfo_opt_mask & df['brsymbol'].str.endswith('PE', na=False), 'symbol'] = (
            df['name'].fillna('') +
            expiry_for_symbol +
            format_strike(df['strike']) +
            'PE'
        )

    # MCX Futures: NAME + EXPIRY + FUT (e.g., CRUDEOILM20MAY24FUT)
    mcx_fut_mask = (df['exchange'] == 'MCX') & (df['instrumenttype'].isin(['FUTCOM', 'FUT']))
    if mcx_fut_mask.any():
        df.loc[mcx_fut_mask, 'symbol'] = (
            df['name'].fillna('') +
            expiry_for_symbol +
            'FUT'
        )

    # MCX Options: NAME + EXPIRY + STRIKE + CE/PE (e.g., CRUDEOIL17APR246750CE)
    mcx_opt_mask = (df['exchange'] == 'MCX') & (df['instrumenttype'].isin(['OPTFUT', 'CE', 'PE']))
    if mcx_opt_mask.any():
        df.loc[mcx_opt_mask & df['brsymbol'].str.endswith('CE', na=False), 'symbol'] = (
            df['name'].fillna('') +
            expiry_for_symbol +
            format_strike(df['strike']) +
            'CE'
        )
        df.loc[mcx_opt_mask & df['brsymbol'].str.endswith('PE', na=False), 'symbol'] = (
            df['name'].fillna('') +
            expiry_for_symbol +
            format_strike(df['strike']) +
            'PE'
        )

    # CDS Futures: NAME + EXPIRY + FUT (e.g., USDINR10MAY24FUT)
    cds_fut_mask = (df['exchange'] == 'CDS') & (df['instrumenttype'].isin(['FUTCUR', 'FUTIRC', 'FUT']))
    if cds_fut_mask.any():
        df.loc[cds_fut_mask, 'symbol'] = (
            df['name'].fillna('') +
            expiry_for_symbol +
            'FUT'
        )

    # CDS Options: NAME + EXPIRY + STRIKE + CE/PE (e.g., USDINR19APR2482CE)
    cds_opt_mask = (df['exchange'] == 'CDS') & (df['instrumenttype'].isin(['OPTCUR', 'OPTIRC', 'CE', 'PE']))
    if cds_opt_mask.any():
        df.loc[cds_opt_mask & df['brsymbol'].str.endswith('CE', na=False), 'symbol'] = (
            df['name'].fillna('') +
            expiry_for_symbol +
            format_strike(df['strike']) +
            'CE'
        )
        df.loc[cds_opt_mask & df['brsymbol'].str.endswith('PE', na=False), 'symbol'] = (
            df['name'].fillna('') +
            expiry_for_symbol +
            format_strike(df['strike']) +
            'PE'
        )

    # BFO - Detect options by CE/PE suffix in brsymbol, futures by FUT suffix or instrument type
    bfo_mask = (df['exchange'] == 'BFO')

    # BFO Options: NAME + EXPIRY + STRIKE + CE/PE (e.g., TATAMOTORS24DEC251210CE)
    bfo_ce_mask = bfo_mask & df['brsymbol'].str.endswith('CE', na=False)
    bfo_pe_mask = bfo_mask & df['brsymbol'].str.endswith('PE', na=False)

    if bfo_ce_mask.any():
        df.loc[bfo_ce_mask, 'symbol'] = (
            df['name'].fillna('') +
            expiry_for_symbol +
            format_strike(df['strike']) +
            'CE'
        )
    if bfo_pe_mask.any():
        df.loc[bfo_pe_mask, 'symbol'] = (
            df['name'].fillna('') +
            expiry_for_symbol +
            format_strike(df['strike']) +
            'PE'
        )

    # BFO Futures: NAME + EXPIRY + FUT (e.g., SENSEX26DEC24FUT)
    bfo_fut_mask = bfo_mask & (
        df['brsymbol'].str.endswith('FUT', na=False) |
        df['instrumenttype'].str.contains('FUT', case=False, na=False)
    )
    if bfo_fut_mask.any():
        df.loc[bfo_fut_mask, 'symbol'] = (
            df['name'].fillna('') +
            expiry_for_symbol +
            'FUT'
        )

    # ============ Common Index Symbol Mapping ============
    df['symbol'] = df['symbol'].replace({
        'Nifty 50': 'NIFTY',
        'NIFTY 50': 'NIFTY',
        'Nifty Next 50': 'NIFTYNXT50',
        'Nifty Fin Service': 'FINNIFTY',
        'NIFTY FIN SERVICE': 'FINNIFTY',
        'Nifty Bank': 'BANKNIFTY',
        'NIFTY BANK': 'BANKNIFTY',
        'NIFTY MID SELECT': 'MIDCPNIFTY',
        'India VIX': 'INDIAVIX',
        'INDIA VIX': 'INDIAVIX',
        'SENSEX': 'SENSEX',
        'BANKEX': 'BANKEX'
    })

    logger.info(f"Processed {len(df)} records")
    return df[required_cols]


def search_symbols(symbol, exchange):
    return SymToken.query.filter(SymToken.symbol.like(f'%{symbol}%'), SymToken.exchange == exchange).all()
