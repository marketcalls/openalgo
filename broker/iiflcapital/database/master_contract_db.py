# database/master_contract_db.py

import os

import pandas as pd
from sqlalchemy import Column, Float, Index, Integer, Sequence, String, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker

from broker.iiflcapital.baseurl import BASE_URL
from extensions import socketio
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL)
db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()


class SymToken(Base):
    __tablename__ = "symtoken"
    id = Column(Integer, Sequence("symtoken_id_seq"), primary_key=True)
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

    __table_args__ = (Index("idx_symbol_exchange", "symbol", "exchange"),)


# ---------------------------------------------------------------------------
# CSV column names from IIFL Capital contract files
# ---------------------------------------------------------------------------
COL_EXCHANGE = "Exchange"
COL_UNDERLYING = "Underlying Instrument Symbol"
COL_TOKEN = "Instrument ID"
COL_INSTRUMENT_TYPE = "Instrument Type"
COL_OPTION_TYPE = "Option Type"
COL_STRIKE = "Strike Price"
COL_NAME = "Underlying Instrument Name"
COL_TRADING_SYMBOL = "Trading Symbol"
COL_EXPIRY = "Expiry"
COL_LOTSIZE = "Lot Size"
COL_TICKSIZE = "Tick Size"

# ---------------------------------------------------------------------------
# Segment configuration
# ---------------------------------------------------------------------------
SEGMENT_URLS = {
    "NSEEQ": f"{BASE_URL}/contractfiles/NSEEQ.csv",
    "BSEEQ": f"{BASE_URL}/contractfiles/BSEEQ.csv",
    "NSEFO": f"{BASE_URL}/contractfiles/NSEFO.csv",
    "BSEFO": f"{BASE_URL}/contractfiles/BSEFO.csv",
    "NSECURR": f"{BASE_URL}/contractfiles/NSECURR.csv",
    "BSECURR": f"{BASE_URL}/contractfiles/BSECURR.csv",
    "NSECOMM": f"{BASE_URL}/contractfiles/NSECOMM.csv",
    "MCXCOMM": f"{BASE_URL}/contractfiles/MCXCOMM.csv",
    "NCDEXCOMM": f"{BASE_URL}/contractfiles/NCDEXCOMM.csv",
    "INDICES": f"{BASE_URL}/contractfiles/INDICES.csv",
}

SEGMENT_EXCHANGE_MAP = {
    "NSEEQ": "NSE",
    "BSEEQ": "BSE",
    "NSEFO": "NFO",
    "BSEFO": "BFO",
    "NSECURR": "CDS",
    "BSECURR": "BCD",
    "NSECOMM": "MCX",
    "MCXCOMM": "MCX",
    "NCDEXCOMM": "MCX",
}

EQUITY_SEGMENTS = ["NSEEQ", "BSEEQ"]
DERIVATIVE_SEGMENTS = ["NSEFO", "BSEFO", "NSECURR", "BSECURR", "NSECOMM", "MCXCOMM", "NCDEXCOMM"]

# ---------------------------------------------------------------------------
# Index symbol normalization mappings
# ---------------------------------------------------------------------------
NSE_INDEX_MAP = {
    "NIFTY50": "NIFTY",
    "NIFTYBANK": "BANKNIFTY",
    "NIFTYFINSERVICE": "FINNIFTY",
    "NIFTYNEXT50": "NIFTYNXT50",
    "NIFTYMIDCAPSELECT": "MIDCPNIFTY",
}

BSE_INDEX_MAP = {
    "AUTO": "BSEAUTO",
    "BSECG": "BSECAPITALGOODS",
    "BSECD": "BSECONSUMERDURABLES",
    "TECK": "BSETECK",
    "METAL": "BSEMETAL",
    "OILGAS": "BSEOIL&GAS",
    "REALTY": "BSEREALTY",
    "POWER": "BSEPOWER",
    "GREENX": "BSEGREENEX",
    "CARBON": "BSECARBONEX",
    "SMEIPO": "BSESMEIPO",
    "INFRA": "BSEINDIAINFRASTRUCTUREINDEX",
    "CPSE": "BSECPSE",
    "MIDCAP": "BSEMIDCAP",
    "SMLCAP": "BSESMALLCAP",
    "BSEFMC": "BSEFASTMOVINGCONSUMERGOODS",
    "BSEHC": "BSEHEALTHCARE",
    "BSEIT": "BSEINFORMATIONTECHNOLOGY",
    "ENERGY": "BSEENERGY",
    "FIN": "BSEFINANCIALSERVICES",
    "INDSTR": "BSEINDUSTRIALS",
    "MIDSEL": "BSEMIDCAPSELECTINDEX",
    "SMLSEL": "BSESMALLCAPSELECTINDEX",
    "TELCOM": "BSETELECOM",
    "SNSX50": "SENSEX50",
    "SNXT50": "BSESENSEXNEXT50",
}


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------
def init_db():
    logger.info("Initializing Master Contract DB")
    Base.metadata.create_all(bind=engine)


def delete_symtoken_table():
    logger.info("Deleting Symtoken Table")
    SymToken.query.delete()
    db_session.commit()


def copy_from_dataframe(df):
    logger.info("Performing Bulk Insert")
    data_dict = df.to_dict(orient="records")

    existing_tokens = {result.token for result in db_session.query(SymToken.token).all()}
    filtered_data_dict = [row for row in data_dict if row["token"] not in existing_tokens]

    try:
        if filtered_data_dict:
            db_session.bulk_insert_mappings(SymToken, filtered_data_dict)
            db_session.commit()
            logger.info(
                f"Bulk insert completed successfully with {len(filtered_data_dict)} new records."
            )
        else:
            logger.info("No new records to insert.")
    except Exception as e:
        logger.error(f"Error during bulk insert: {e}")
        db_session.rollback()


# ---------------------------------------------------------------------------
# Download helpers
# ---------------------------------------------------------------------------
def download_csv_iiflcapital_data(output_path):
    """Download all IIFL Capital master contract CSV files to output_path."""
    logger.info("Downloading IIFL Capital Master Contract CSV Files")
    client = get_httpx_client()

    for segment, url in SEGMENT_URLS.items():
        try:
            response = client.get(url, timeout=30)
            response.raise_for_status()

            file_path = f"{output_path}/{segment}.csv"
            with open(file_path, "wb") as f:
                f.write(response.content)

            logger.info(f"Successfully downloaded {segment} master contract")
        except Exception as e:
            logger.warning(f"Failed to download {segment} from {url}. Error: {e}")


def delete_iiflcapital_temp_data(output_path):
    """Delete downloaded CSV files from the temp directory."""
    for segment in SEGMENT_URLS:
        file_path = os.path.join(output_path, f"{segment}.csv")
        if os.path.isfile(file_path):
            os.remove(file_path)
            logger.info(f"Deleted {file_path}")


# ---------------------------------------------------------------------------
# Expiry / strike formatting
# ---------------------------------------------------------------------------
def format_expiry(expiry_str):
    """Convert '30-Apr-2026' or '24-Apr-2026 23:59' to 'DD-MMM-YY' (e.g. '30-APR-26')."""
    if pd.isna(expiry_str) or not str(expiry_str).strip():
        return ""
    try:
        dt = pd.to_datetime(str(expiry_str).strip(), errors="coerce")
        if pd.isna(dt):
            return ""
        return dt.strftime("%d-%b-%y").upper()
    except Exception:
        return ""


def format_strike(strike_val):
    """Format strike price for OpenAlgo symbol. Integer if whole number, else decimal."""
    try:
        strike = float(strike_val)
    except (TypeError, ValueError):
        return ""
    if strike <= 0:
        return ""
    if strike == int(strike):
        return str(int(strike))
    return str(strike)


# ---------------------------------------------------------------------------
# Per-segment processing functions
# ---------------------------------------------------------------------------
def process_iiflcapital_nse_csv(path):
    """Process NSEEQ CSV for NSE equity."""
    return _process_equity_csv(path, "NSEEQ", "NSE")


def process_iiflcapital_bse_csv(path):
    """Process BSEEQ CSV for BSE equity."""
    return _process_equity_csv(path, "BSEEQ", "BSE")


def _process_equity_csv(path, segment, exchange):
    """Shared processor for equity segments (NSEEQ / BSEEQ)."""
    logger.info(f"Processing IIFL Capital {exchange} Equity CSV Data")
    file_path = f"{path}/{segment}.csv"

    df = pd.read_csv(file_path, dtype=str)

    # Filter out INDEX rows (handled separately by INDICES segment)
    df = df[df[COL_INSTRUMENT_TYPE].str.strip() != "INDEX"]

    # Filter rows with valid token and symbol
    df = df[df[COL_TOKEN].notna() & df[COL_UNDERLYING].notna()]
    df = df[df[COL_TOKEN].str.strip() != ""]
    df = df[df[COL_UNDERLYING].str.strip() != ""]

    token_df = pd.DataFrame()
    token_df["symbol"] = df[COL_UNDERLYING].str.strip()
    token_df["brsymbol"] = df[COL_TRADING_SYMBOL].str.strip()
    token_df["name"] = df[COL_NAME].str.strip()
    token_df["exchange"] = exchange
    token_df["brexchange"] = segment
    token_df["token"] = df[COL_TOKEN].str.strip()
    token_df["expiry"] = ""
    token_df["strike"] = 0.0
    token_df["lotsize"] = pd.to_numeric(df[COL_LOTSIZE], errors="coerce").fillna(1).astype(int)
    token_df["instrumenttype"] = "EQ"
    token_df["tick_size"] = pd.to_numeric(df[COL_TICKSIZE], errors="coerce").fillna(0.01)

    token_df = token_df.dropna(subset=["symbol"])
    return token_df


def process_iiflcapital_nfo_csv(path):
    """Process NSEFO CSV for NFO derivatives."""
    return _process_derivatives_csv(path, "NSEFO", "NFO")


def process_iiflcapital_bfo_csv(path):
    """Process BSEFO CSV for BFO derivatives."""
    return _process_derivatives_csv(path, "BSEFO", "BFO")


def process_iiflcapital_cds_csv(path):
    """Process NSECURR CSV for CDS currency derivatives."""
    return _process_derivatives_csv(path, "NSECURR", "CDS")


def process_iiflcapital_bcd_csv(path):
    """Process BSECURR CSV for BCD currency derivatives."""
    return _process_derivatives_csv(path, "BSECURR", "BCD")


def process_iiflcapital_nsecomm_csv(path):
    """Process NSECOMM CSV for NSE commodity derivatives."""
    return _process_derivatives_csv(path, "NSECOMM", "MCX")


def process_iiflcapital_mcxcomm_csv(path):
    """Process MCXCOMM CSV for MCX commodity derivatives."""
    return _process_derivatives_csv(path, "MCXCOMM", "MCX")


def process_iiflcapital_ncdexcomm_csv(path):
    """Process NCDEXCOMM CSV for NCDEX commodity derivatives."""
    return _process_derivatives_csv(path, "NCDEXCOMM", "MCX")


def _process_derivatives_csv(path, segment, exchange):
    """Shared processor for derivative segments (NFO/BFO/CDS/BCD/MCX)."""
    logger.info(f"Processing IIFL Capital {exchange} ({segment}) Derivatives CSV Data")
    file_path = f"{path}/{segment}.csv"

    if not os.path.isfile(file_path):
        logger.warning(f"File not found: {file_path}")
        return pd.DataFrame()

    df = pd.read_csv(file_path, dtype=str)

    if df.empty:
        logger.warning(f"Empty CSV for segment {segment}")
        return pd.DataFrame()

    # Filter rows with valid token and symbol
    df = df[df[COL_TOKEN].notna() & df[COL_UNDERLYING].notna()]
    df = df[df[COL_TOKEN].str.strip() != ""]

    # Parse expiry to standard format (DD-MMM-YY)
    df["_expiry"] = df[COL_EXPIRY].apply(format_expiry)

    # Compact expiry for symbol construction (DDMMMYY)
    df["_compact_expiry"] = df["_expiry"].str.replace("-", "", regex=False)

    # Parse strike
    df["_strike"] = pd.to_numeric(df[COL_STRIKE], errors="coerce").fillna(0.0)

    # Determine OpenAlgo instrument type from Option Type column
    # XX = FUT, CE = CE, PE = PE
    option_type = df[COL_OPTION_TYPE].str.strip().str.upper()
    df["_instrumenttype"] = option_type.map({"XX": "FUT", "CE": "CE", "PE": "PE"})

    # Build OpenAlgo symbols
    underlying = df[COL_UNDERLYING].str.strip()

    # Futures: {underlying}{DDMMMYY}FUT
    fut_mask = df["_instrumenttype"] == "FUT"
    df.loc[fut_mask, "_symbol"] = underlying + df["_compact_expiry"] + "FUT"

    # Options CE: {underlying}{DDMMMYY}{strike}{CE}
    ce_mask = df["_instrumenttype"] == "CE"
    df.loc[ce_mask, "_symbol"] = (
        underlying
        + df["_compact_expiry"]
        + df.loc[ce_mask, "_strike"].apply(format_strike)
        + "CE"
    )

    # Options PE: {underlying}{DDMMMYY}{strike}{PE}
    pe_mask = df["_instrumenttype"] == "PE"
    df.loc[pe_mask, "_symbol"] = (
        underlying
        + df["_compact_expiry"]
        + df.loc[pe_mask, "_strike"].apply(format_strike)
        + "PE"
    )

    token_df = pd.DataFrame()
    token_df["symbol"] = df["_symbol"]
    token_df["brsymbol"] = df[COL_TRADING_SYMBOL].str.strip()
    token_df["name"] = df[COL_NAME].str.strip()
    token_df["exchange"] = exchange
    token_df["brexchange"] = segment
    token_df["token"] = df[COL_TOKEN].str.strip()
    token_df["expiry"] = df["_expiry"]
    token_df["strike"] = df["_strike"]
    token_df["lotsize"] = pd.to_numeric(df[COL_LOTSIZE], errors="coerce").fillna(1).astype(int)
    token_df["instrumenttype"] = df["_instrumenttype"]
    token_df["tick_size"] = pd.to_numeric(df[COL_TICKSIZE], errors="coerce").fillna(0.01)

    token_df = token_df.dropna(subset=["symbol"])
    return token_df


def process_iiflcapital_indices_csv(path):
    """Process INDICES CSV for NSE_INDEX and BSE_INDEX."""
    logger.info("Processing IIFL Capital INDICES CSV Data")
    file_path = f"{path}/INDICES.csv"

    if not os.path.isfile(file_path):
        logger.warning(f"File not found: {file_path}")
        return pd.DataFrame()

    df = pd.read_csv(file_path, dtype=str)

    if df.empty:
        logger.warning("Empty CSV for INDICES segment")
        return pd.DataFrame()

    # Determine OpenAlgo exchange from CSV Exchange column
    # NSEEQ entries → NSE_INDEX, BSEEQ entries → BSE_INDEX
    csv_exchange = df[COL_EXCHANGE].str.strip().str.upper()
    df["_exchange"] = csv_exchange.map({"NSEEQ": "NSE_INDEX", "BSEEQ": "BSE_INDEX"})

    # Normalize symbol: uppercase, remove spaces
    df["_symbol"] = (
        df[COL_NAME]
        .str.strip()
        .str.upper()
        .str.replace(" ", "", regex=False)
    )

    # Apply NSE index name mappings
    nse_mask = df["_exchange"] == "NSE_INDEX"
    df.loc[nse_mask, "_symbol"] = df.loc[nse_mask, "_symbol"].replace(NSE_INDEX_MAP)

    # Apply BSE index name mappings
    bse_mask = df["_exchange"] == "BSE_INDEX"
    df.loc[bse_mask, "_symbol"] = df.loc[bse_mask, "_symbol"].replace(BSE_INDEX_MAP)

    token_df = pd.DataFrame()
    token_df["symbol"] = df["_symbol"]
    token_df["brsymbol"] = df[COL_TRADING_SYMBOL].str.strip()
    token_df["name"] = df["_symbol"]
    token_df["exchange"] = df["_exchange"]
    token_df["brexchange"] = df[COL_EXCHANGE].str.strip()
    token_df["token"] = df[COL_TOKEN].str.strip()
    token_df["expiry"] = ""
    token_df["strike"] = 0.0
    token_df["lotsize"] = 1
    token_df["instrumenttype"] = "INDEX"
    token_df["tick_size"] = 0.01

    token_df = token_df.dropna(subset=["symbol"])
    return token_df


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
def master_contract_download():
    logger.info("Downloading IIFL Capital Master Contract")

    output_path = "tmp"
    try:
        download_csv_iiflcapital_data(output_path)
        delete_symtoken_table()

        # Process equity segments
        token_df = process_iiflcapital_nse_csv(output_path)
        copy_from_dataframe(token_df)
        token_df = process_iiflcapital_bse_csv(output_path)
        copy_from_dataframe(token_df)

        # Process derivative segments
        token_df = process_iiflcapital_nfo_csv(output_path)
        copy_from_dataframe(token_df)
        token_df = process_iiflcapital_bfo_csv(output_path)
        copy_from_dataframe(token_df)
        token_df = process_iiflcapital_cds_csv(output_path)
        copy_from_dataframe(token_df)
        token_df = process_iiflcapital_bcd_csv(output_path)
        copy_from_dataframe(token_df)
        token_df = process_iiflcapital_nsecomm_csv(output_path)
        copy_from_dataframe(token_df)
        token_df = process_iiflcapital_mcxcomm_csv(output_path)
        copy_from_dataframe(token_df)
        token_df = process_iiflcapital_ncdexcomm_csv(output_path)
        copy_from_dataframe(token_df)

        # Process indices
        token_df = process_iiflcapital_indices_csv(output_path)
        copy_from_dataframe(token_df)

        delete_iiflcapital_temp_data(output_path)

        return socketio.emit(
            "master_contract_download",
            {"status": "success", "message": "Successfully Downloaded"},
        )

    except Exception as e:
        logger.error(f"Error in master contract download: {e}")
        return socketio.emit(
            "master_contract_download", {"status": "error", "message": str(e)}
        )


def search_symbols(symbol, exchange):
    return SymToken.query.filter(
        SymToken.symbol.like(f"%{symbol}%"), SymToken.exchange == exchange
    ).all()
