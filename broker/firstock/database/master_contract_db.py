import os
from datetime import datetime

import pandas as pd
from sqlalchemy import Column, Float, Index, Integer, Sequence, String, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker

from extensions import socketio
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

# Database setup
DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL)
db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()


# Define SymToken table
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

    # Define a composite index on symbol and exchange columns
    __table_args__ = (Index("idx_symbol_exchange", "symbol", "exchange"),)


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


# Firstock V1 URLs for downloading symbol files
firstock_urls = {
    "NSE": "https://api.firstock.in/V1/symbols/NSE?ref=firstock.in",
    "BSE": "https://api.firstock.in/V1/symbols/BSE?ref=firstock.in",
    "NFO": "https://api.firstock.in/V1/symbols/NFO?ref=firstock.in",
    "BFO": "https://api.firstock.in/V1/symbols/BFO?ref=firstock.in",
}


def download_firstock_data(output_path):
    """
    Downloads CSV files from Firstock's API endpoints using shared httpx client with connection pooling.

    CSV Columns:
    NSE/BSE: Exchange, Token, LotSize, TradingSymbol, CompanyName, ISIN, TickSize, FreezeQty
    NFO/BFO: Exchange, Token, LotSize, Symbol, TradingSymbol, CompanyName, Expiry,
             Instrument, OptionType, StrikePrice, TickSize, FreezeQty
    """
    logger.info("Downloading Firstock Data")

    if not os.path.exists(output_path):
        os.makedirs(output_path)

    downloaded_files = []

    try:
        # Get the shared httpx client with connection pooling
        client = get_httpx_client()

        for exchange, url in firstock_urls.items():
            try:
                logger.info(f"Downloading {exchange} data from {url}")

                # Make request using shared httpx client
                response = client.get(url, timeout=30)

                # Add status attribute for compatibility
                response.status = response.status_code

                if response.status_code == 200:
                    file_path = f"{output_path}/{exchange}_symbols.csv"
                    with open(file_path, "w") as f:
                        f.write(response.text)
                    downloaded_files.append(f"{exchange}_symbols.csv")
                    logger.info(f"Successfully downloaded {exchange} data")
                else:
                    logger.error(
                        f"Failed to download {exchange} data. Status code: {response.status_code}"
                    )

            except Exception as e:
                if "timeout" in str(e).lower():
                    logger.error(f"Timeout while downloading {exchange} data - please try again")
                elif "connection" in str(e).lower():
                    logger.error(
                        f"Connection error while downloading {exchange} data - please check your internet connection"
                    )
                else:
                    logger.error(f"Error downloading {exchange} data: {str(e)}")

    except Exception as e:
        logger.error(f"Error initializing HTTP client: {str(e)}")

    return downloaded_files


def process_firstock_nse_data(output_path):
    """
    Processes the Firstock NSE data (NSE_symbols.csv) to generate OpenAlgo symbols.
    Separates EQ, BE symbols, and Index symbols.

    Index symbols are identified by having 0 values in ISIN, TickSize, and FreezeQty columns.
    """
    logger.info("Processing Firstock NSE Data")
    file_path = f"{output_path}/NSE_symbols.csv"

    # Read the NSE symbols file with all columns
    df = pd.read_csv(file_path)

    # Identify index symbols based on zero values in specific columns
    df["is_index"] = (
        (df["ISIN"].isna() | df["ISIN"].eq("")) & df["TickSize"].eq(0.0) & df["FreezeQty"].eq(0.0)
    )

    # Rename columns to match schema
    column_mapping = {
        "Exchange": "exchange",
        "Token": "token",
        "LotSize": "lotsize",
        "TradingSymbol": "brsymbol",
        "CompanyName": "name",
        "TickSize": "tick_size",
    }
    df = df.rename(columns=column_mapping)

    # Initialize symbol with brsymbol
    df["symbol"] = df["brsymbol"]

    # Apply transformation for OpenAlgo symbols
    def get_openalgo_symbol(broker_symbol):
        if "-EQ" in broker_symbol:
            return broker_symbol.replace("-EQ", "")
        elif "-BE" in broker_symbol:
            return broker_symbol.replace("-BE", "")
        else:
            return broker_symbol

    # Update the symbol column (non-index rows get -EQ/-BE stripped)
    df["symbol"] = df["brsymbol"].apply(get_openalgo_symbol)

    # For index rows, normalize to OpenAlgo-standard symbol using the
    # comprehensive mapping (symbol_Openalgo.md). Unlisted indices fall
    # through unchanged.
    index_mask = df["is_index"]
    if index_mask.any():
        df.loc[index_mask, "symbol"] = df.loc[index_mask].apply(
            lambda r: map_to_openalgo_index_symbol(
                r["brsymbol"], r.get("name", ""), "NSE"
            ),
            axis=1,
        )

    # Set instrument type based on is_index flag and trading symbol
    def get_instrument_type(row):
        if row["is_index"]:
            return "INDEX"
        elif "-BE" in row["brsymbol"]:
            return "BE"
        else:
            return "EQ"

    # Set instrument type
    df["instrumenttype"] = df.apply(get_instrument_type, axis=1)

    # Define Exchange: 'NSE' for EQ and BE, 'NSE_INDEX' for indexes
    df["exchange"] = df.apply(
        lambda row: "NSE_INDEX" if row["instrumenttype"] == "INDEX" else "NSE", axis=1
    )
    # brexchange should always be 'NSE' for Firstock (including indices)
    df["brexchange"] = "NSE"

    # Set empty columns for expiry and strike
    df["expiry"] = ""
    df["strike"] = -1

    # Handle missing or invalid numeric values
    df["lotsize"] = pd.to_numeric(df["lotsize"], errors="coerce").fillna(0).astype(int)
    df["tick_size"] = pd.to_numeric(df["tick_size"], errors="coerce")

    # Reorder the columns to match the database structure
    columns_to_keep = [
        "symbol",
        "brsymbol",
        "name",
        "exchange",
        "brexchange",
        "token",
        "expiry",
        "strike",
        "lotsize",
        "instrumenttype",
        "tick_size",
    ]
    df_filtered = df[columns_to_keep]

    # Return the processed DataFrame
    return df_filtered


def process_firstock_nfo_data(output_path):
    """
    Processes the Firstock NFO data (NFO_symbols.csv) to generate OpenAlgo symbols.
    Handles both futures and options formatting.
    """
    logger.info("Processing Firstock NFO Data")
    file_path = f"{output_path}/NFO_symbols.csv"

    # Read the NFO symbols file
    df = pd.read_csv(file_path)

    # Rename columns to match schema
    column_mapping = {
        "Exchange": "exchange",
        "Token": "token",
        "LotSize": "lotsize",
        "Symbol": "name",
        "TradingSymbol": "brsymbol",
        "Expiry": "expiry",
        "Instrument": "instrumenttype",
        "OptionType": "optiontype",
        "StrikePrice": "strike",
        "TickSize": "tick_size",
    }
    df = df.rename(columns=column_mapping)

    # Fill missing values
    df["expiry"] = df["expiry"].fillna("")
    df["strike"] = df["strike"].fillna(-1)

    # Format expiry date as DD-MMM-YY (with hyphens for option_symbol_service compatibility)
    def format_expiry_date(date_str):
        try:
            return datetime.strptime(date_str, "%d-%b-%Y").strftime("%d-%b-%y").upper()
        except ValueError:
            logger.info(f"Invalid expiry date format: {date_str}")
            return None

    # Apply the expiry date format
    df["expiry"] = df["expiry"].apply(format_expiry_date)

    # Set instrument type based on option type
    df["instrumenttype"] = df.apply(
        lambda row: "FUT" if row["optiontype"] == "XX" else row["optiontype"], axis=1
    )

    # Format symbol based on instrument type (expiry without hyphens in symbol)
    def format_symbol(row):
        # Remove hyphens from expiry for symbol construction
        expiry_no_hyphen = row["expiry"].replace("-", "") if row["expiry"] else ""
        if row["instrumenttype"] == "FUT":
            return f"{row['name']}{expiry_no_hyphen}FUT"
        else:
            # Ensure strike prices are either integers or floats
            formatted_strike = (
                int(row["strike"]) if float(row["strike"]).is_integer() else row["strike"]
            )
            return f"{row['name']}{expiry_no_hyphen}{formatted_strike}{row['instrumenttype']}"

    df["symbol"] = df.apply(format_symbol, axis=1)

    # Set exchange
    df["exchange"] = "NFO"
    df["brexchange"] = df["exchange"]

    # Handle strike prices
    def handle_strike_price(strike):
        try:
            if float(strike).is_integer():
                return int(float(strike))
            else:
                return float(strike)
        except (ValueError, TypeError):
            return -1

    df["strike"] = df["strike"].apply(handle_strike_price)

    # Handle numeric values
    df["lotsize"] = pd.to_numeric(df["lotsize"], errors="coerce").fillna(0).astype(int)
    df["tick_size"] = pd.to_numeric(df["tick_size"], errors="coerce")

    # Reorder columns
    columns_to_keep = [
        "symbol",
        "brsymbol",
        "name",
        "exchange",
        "brexchange",
        "token",
        "expiry",
        "strike",
        "lotsize",
        "instrumenttype",
        "tick_size",
    ]
    df_filtered = df[columns_to_keep]

    return df_filtered


def process_firstock_bse_data(output_path):
    """
    Processes the Firstock BSE data (BSE_symbols.csv) to generate OpenAlgo symbols.

    Indices (SENSEX, SENSEX50, etc.) are identified by empty ISIN + zero
    TickSize + zero FreezeQty (same heuristic as NSE) and routed to
    exchange='BSE_INDEX' with OpenAlgo-standard symbol normalization.
    All other BSE rows are treated as equity (instrumenttype='EQ').
    """
    logger.info("Processing Firstock BSE Data")
    file_path = f"{output_path}/BSE_symbols.csv"

    # Read the BSE symbols file
    df = pd.read_csv(file_path)

    # Identify index rows (BSE /V1/indexList does not return BSE indices,
    # so SENSEX/BANKEX/etc. must be picked out of the BSE CSV here).
    df["is_index"] = (
        (df["ISIN"].isna() | df["ISIN"].eq("")) & df["TickSize"].eq(0.0) & df["FreezeQty"].eq(0.0)
    )

    # Rename columns to match schema
    column_mapping = {
        "Exchange": "exchange",
        "Token": "token",
        "LotSize": "lotsize",
        "TradingSymbol": "brsymbol",
        "CompanyName": "name",
        "TickSize": "tick_size",
    }
    df = df.rename(columns=column_mapping)

    # Initialize symbol with brsymbol (BSE equity symbols need no
    # transformation — no -EQ/-BE suffix like NSE).
    df["symbol"] = df["brsymbol"]

    # For index rows, normalize to OpenAlgo-standard symbol (e.g. SENSEX,
    # SENSEX50, BANKEX). Unlisted indices fall through unchanged.
    index_mask = df["is_index"]
    if index_mask.any():
        df.loc[index_mask, "symbol"] = df.loc[index_mask].apply(
            lambda r: map_to_openalgo_index_symbol(
                r["brsymbol"], r.get("name", ""), "BSE"
            ),
            axis=1,
        )

    # Exchange + instrument type conditional on is_index.
    df["instrumenttype"] = df["is_index"].apply(lambda x: "INDEX" if x else "EQ")
    df["exchange"] = df["is_index"].apply(lambda x: "BSE_INDEX" if x else "BSE")
    df["brexchange"] = "BSE"

    # Set empty columns for expiry and strike
    df["expiry"] = ""
    df["strike"] = -1

    # Handle missing or invalid numeric values
    df["lotsize"] = pd.to_numeric(df["lotsize"], errors="coerce").fillna(0).astype(int)
    df["tick_size"] = pd.to_numeric(df["tick_size"], errors="coerce")

    # Reorder the columns to match the database structure
    columns_to_keep = [
        "symbol",
        "brsymbol",
        "name",
        "exchange",
        "brexchange",
        "token",
        "expiry",
        "strike",
        "lotsize",
        "instrumenttype",
        "tick_size",
    ]
    df_filtered = df[columns_to_keep]

    # Return the processed DataFrame
    return df_filtered


def process_firstock_bfo_data(output_path):
    """
    Processes the Firstock BFO data (BFO_symbols.csv) to generate OpenAlgo symbols.
    Similar to NFO but for BSE derivatives.
    """
    logger.info("Processing Firstock BFO Data")
    file_path = f"{output_path}/BFO_symbols.csv"

    # Read the BFO symbols file
    df = pd.read_csv(file_path)

    # Rename columns to match schema
    column_mapping = {
        "Exchange": "exchange",
        "Token": "token",
        "LotSize": "lotsize",
        "Symbol": "name",
        "TradingSymbol": "brsymbol",
        "Expiry": "expiry",
        "Instrument": "instrumenttype",
        "OptionType": "optiontype",
        "StrikePrice": "strike",
        "TickSize": "tick_size",
    }
    df = df.rename(columns=column_mapping)

    # Fill missing values
    df["expiry"] = df["expiry"].fillna("")
    df["strike"] = df["strike"].fillna(-1)

    # Format expiry date as DD-MMM-YY (with hyphens for option_symbol_service compatibility)
    def format_expiry_date(date_str):
        try:
            return datetime.strptime(date_str, "%d-%b-%Y").strftime("%d-%b-%y").upper()
        except ValueError:
            logger.info(f"Invalid expiry date format: {date_str}")
            return None

    # Apply the expiry date format
    df["expiry"] = df["expiry"].apply(format_expiry_date)

    # Set instrument type based on option type
    df["instrumenttype"] = df.apply(
        lambda row: "FUT" if row["optiontype"] == "XX" else row["optiontype"], axis=1
    )

    # Format symbol based on instrument type (expiry without hyphens in symbol)
    def format_symbol(row):
        # Remove hyphens from expiry for symbol construction
        expiry_no_hyphen = row["expiry"].replace("-", "") if row["expiry"] else ""
        if row["instrumenttype"] == "FUT":
            return f"{row['name']}{expiry_no_hyphen}FUT"
        else:
            # Ensure strike prices are either integers or floats
            formatted_strike = (
                int(row["strike"]) if float(row["strike"]).is_integer() else row["strike"]
            )
            return f"{row['name']}{expiry_no_hyphen}{formatted_strike}{row['instrumenttype']}"

    df["symbol"] = df.apply(format_symbol, axis=1)

    # Set exchange
    df["exchange"] = "BFO"
    df["brexchange"] = df["exchange"]

    # Handle strike prices
    def handle_strike_price(strike):
        try:
            if float(strike).is_integer():
                return int(float(strike))
            else:
                return float(strike)
        except (ValueError, TypeError):
            return -1

    df["strike"] = df["strike"].apply(handle_strike_price)

    # Handle numeric values
    df["lotsize"] = pd.to_numeric(df["lotsize"], errors="coerce").fillna(0).astype(int)
    df["tick_size"] = pd.to_numeric(df["tick_size"], errors="coerce")

    # Reorder columns
    columns_to_keep = [
        "symbol",
        "brsymbol",
        "name",
        "exchange",
        "brexchange",
        "token",
        "expiry",
        "strike",
        "lotsize",
        "instrumenttype",
        "tick_size",
    ]
    df_filtered = df[columns_to_keep]

    return df_filtered


# OpenAlgo standard index symbols per symbol_Openalgo.md.
# Matching any fetched idxname/tradingSymbol against these (case- and
# whitespace-insensitive) normalizes to the OpenAlgo format; unmatched
# indices pass through unchanged so new/custom indices still get stored.
OPENALGO_NSE_INDICES = {
    "NIFTY", "NIFTYNXT50", "FINNIFTY", "BANKNIFTY", "MIDCPNIFTY", "INDIAVIX",
    "HANGSENGBEESNAV",
    "NIFTY100", "NIFTY200", "NIFTY500",
    "NIFTYALPHA50", "NIFTYAUTO", "NIFTYCOMMODITIES", "NIFTYCONSUMPTION",
    "NIFTYCPSE", "NIFTYDIVOPPS50", "NIFTYENERGY", "NIFTYFMCG",
    "NIFTYGROWSECT15", "NIFTYGS10YR", "NIFTYGS10YRCLN", "NIFTYGS1115YR",
    "NIFTYGS15YRPLUS", "NIFTYGS48YR", "NIFTYGS813YR", "NIFTYGSCOMPSITE",
    "NIFTYINFRA", "NIFTYIT", "NIFTYMEDIA", "NIFTYMETAL",
    "NIFTYMIDLIQ15", "NIFTYMIDCAP100", "NIFTYMIDCAP150", "NIFTYMIDCAP50",
    "NIFTYMIDSML400", "NIFTYMNC", "NIFTYPHARMA", "NIFTYPSE",
    "NIFTYPSUBANK", "NIFTYPVTBANK", "NIFTYREALTY", "NIFTYSERVSECTOR",
    "NIFTYSMLCAP100", "NIFTYSMLCAP250", "NIFTYSMLCAP50",
    "NIFTY100EQLWGT", "NIFTY100LIQ15", "NIFTY100LOWVOL30", "NIFTY100QUALTY30",
    "NIFTY200QUALTY30", "NIFTY50DIVPOINT", "NIFTY50EQLWGT",
    "NIFTY50PR1XINV", "NIFTY50PR2XLEV", "NIFTY50TR1XINV", "NIFTY50TR2XLEV",
    "NIFTY50VALUE20",
}

OPENALGO_BSE_INDICES = {
    "SENSEX", "BANKEX", "SENSEX50",
    "BSE100", "BSE150MIDCAPINDEX", "BSE200", "BSE250LARGEMIDCAPINDEX",
    "BSE400MIDSMALLCAPINDEX", "BSE500",
    "BSEAUTO", "BSECAPITALGOODS", "BSECARBONEX", "BSECONSUMERDURABLES",
    "BSECPSE", "BSEDOLLEX100", "BSEDOLLEX200", "BSEDOLLEX30", "BSEENERGY",
    "BSEFASTMOVINGCONSUMERGOODS", "BSEFINANCIALSERVICES", "BSEGREENEX",
    "BSEHEALTHCARE", "BSEINDIAINFRASTRUCTUREINDEX", "BSEINDUSTRIALS",
    "BSEINFORMATIONTECHNOLOGY", "BSEIPO", "BSELARGECAP", "BSEMETAL",
    "BSEMIDCAP", "BSEMIDCAPSELECTINDEX", "BSEOIL&GAS", "BSEPOWER",
    "BSEPSU", "BSEREALTY", "BSESENSEXNEXT50", "BSESMALLCAP",
    "BSESMALLCAPSELECTINDEX", "BSESMEIPO", "BSETECK", "BSETELECOM",
}

# Explicit aliases for broker/exchange names that diverge from the OpenAlgo
# symbol even after whitespace/punctuation normalization (abbreviations,
# reordered words, etc.). Keys are normalized (see _normalize_index_key).
INDEX_NAME_ALIASES = {
    # NSE
    "NIFTY50": "NIFTY",
    "NIFTYNEXT50": "NIFTYNXT50",
    "NIFTYFINSERVICE": "FINNIFTY",
    "NIFTYFINSERV": "FINNIFTY",
    "NIFTYFINANCIALSERVICES": "FINNIFTY",
    "NIFTYMIDSELECT": "MIDCPNIFTY",
    # NSE - abbreviation expansions (broker uses long form, docs use short)
    "NIFTYSMALLCAP50": "NIFTYSMLCAP50",
    "NIFTYSMALLCAP100": "NIFTYSMLCAP100",
    "NIFTYSMALLCAP250": "NIFTYSMLCAP250",
    "NIFTYINFRASTRUCTURE": "NIFTYINFRA",
    # BSE - prefix variations
    "SPBSESENSEX": "SENSEX",
    "BSESENSEX": "SENSEX",
    "SPBSEBANKEX": "BANKEX",
    "SPBSESENSEX50": "SENSEX50",
    "BSESENSEX50": "SENSEX50",
    # BSE - abbreviation expansions (broker uses short form, docs use long)
    "BSEIT": "BSEINFORMATIONTECHNOLOGY",
    "BSEFMCG": "BSEFASTMOVINGCONSUMERGOODS",
    "BSECDGS": "BSECONSUMERDURABLES",
    "BSECG": "BSECAPITALGOODS",
}


def _normalize_index_key(value):
    """
    Normalize an index name/symbol for tolerant matching.

    Strips spaces, hyphens, underscores, ampersands, and the word "AND"
    so that "BSEOIL&GAS" and "BSEOILANDGAS" collapse to the same key.
    """
    if not value:
        return ""
    return (
        value.upper()
        .replace(" ", "")
        .replace("-", "")
        .replace("_", "")
        .replace("&", "")
        .replace("AND", "")
    )


# Pre-computed normalized lookup dicts: normalized_key -> canonical OpenAlgo symbol.
# Built once at module load so tolerant matching is a single dict lookup.
_NSE_INDEX_NORMALIZED_LOOKUP = {
    _normalize_index_key(s): s for s in OPENALGO_NSE_INDICES
}
_BSE_INDEX_NORMALIZED_LOOKUP = {
    _normalize_index_key(s): s for s in OPENALGO_BSE_INDICES
}


def _basic_index_cleanup(value):
    """
    Minimal format cleanup for unlisted indices: uppercase, strip spaces and
    hyphens. Preserves identity (no name/alias transformation) while ensuring
    the stored symbol is a valid OpenAlgo-format token.
    """
    if not value:
        return ""
    return value.upper().replace(" ", "").replace("-", "")


def map_to_openalgo_index_symbol(trading_symbol, idxname, br_exchange):
    """
    Resolve the OpenAlgo-standard index symbol for a fetched Firstock index.

    Match order:
      1. tradingSymbol is already an OpenAlgo canonical (NIFTY, SENSEX, ...)
      2. tradingSymbol/idxname normalizes to an explicit alias (e.g. BSEIT)
      3. tradingSymbol/idxname normalizes to a canonical OpenAlgo symbol

    Unlisted indices fall through with basic cleanup only (uppercase + strip
    spaces/hyphens) so identity is preserved but the stored symbol remains a
    valid OpenAlgo-format token.
    """
    if br_exchange == "NSE":
        normalized_lookup = _NSE_INDEX_NORMALIZED_LOOKUP
        openalgo_set = OPENALGO_NSE_INDICES
    elif br_exchange == "BSE":
        normalized_lookup = _BSE_INDEX_NORMALIZED_LOOKUP
        openalgo_set = OPENALGO_BSE_INDICES
    else:
        return _basic_index_cleanup(trading_symbol)

    # Direct tradingSymbol hit (e.g. "NIFTY", "BANKNIFTY", "SENSEX").
    if trading_symbol in openalgo_set:
        return trading_symbol

    ts_norm = _normalize_index_key(trading_symbol)
    idx_norm = _normalize_index_key(idxname)

    for key in (ts_norm, idx_norm):
        if not key:
            continue
        if key in INDEX_NAME_ALIASES:
            return INDEX_NAME_ALIASES[key]
        if key in normalized_lookup:
            return normalized_lookup[key]

    return _basic_index_cleanup(trading_symbol)


def fetch_firstock_indices():
    """
    Fetch NSE/BSE indices from Firstock V1 /indexList API.

    In V1, indices (NIFTY, BANKNIFTY, SENSEX, etc.) are no longer included
    in the symbol download CSVs — they must be fetched via authenticated
    POST /V1/indexList using the logged-in user's jKey (susertoken).

    Returns a DataFrame matching the SymToken schema, or empty DataFrame
    on failure.
    """
    logger.info("Fetching Firstock indices from /V1/indexList")

    from database.auth_db import Auth, decrypt_token

    try:
        auth_obj = Auth.query.filter_by(broker="firstock", is_revoked=False).first()
        if not auth_obj:
            logger.warning("No active Firstock auth session found; skipping index list fetch")
            return pd.DataFrame()

        jkey = decrypt_token(auth_obj.auth)

        # Firstock userId = BROKER_API_KEY (vendorCode) minus the "_API" suffix,
        # matching the convention in order_api.py and firstock_adapter.py.
        user_id = os.getenv("BROKER_API_KEY", "").replace("_API", "")
        if not user_id:
            logger.error("BROKER_API_KEY not set; cannot fetch Firstock indices")
            return pd.DataFrame()

        client = get_httpx_client()
        url = "https://api.firstock.in/V1/indexList"
        payload = {"userId": user_id, "jKey": jkey}
        headers = {"Content-Type": "application/json"}

        response = client.post(url, json=payload, headers=headers, timeout=30)
        response.status = response.status_code

        if response.status_code != 200:
            logger.error(
                f"Failed to fetch Firstock indices. Status code: {response.status_code}"
            )
            return pd.DataFrame()

        data = response.json()
        if data.get("status") != "success":
            logger.error(f"Firstock indexList returned error: {data.get('message')}")
            return pd.DataFrame()

        indices = data.get("data", []) or []
        if not indices:
            logger.warning("Firstock indexList returned empty data")
            return pd.DataFrame()

        rows = []
        for item in indices:
            br_exchange = item.get("exchange", "")
            trading_symbol = item.get("tradingSymbol", "")
            idxname = item.get("idxname", "")
            token = str(item.get("token", ""))

            if not token or not trading_symbol:
                continue

            openalgo_symbol = map_to_openalgo_index_symbol(
                trading_symbol, idxname, br_exchange
            )
            oa_exchange = (
                f"{br_exchange}_INDEX" if br_exchange in ("NSE", "BSE") else br_exchange
            )

            rows.append(
                {
                    "symbol": openalgo_symbol,
                    "brsymbol": trading_symbol,
                    "name": idxname,
                    "exchange": oa_exchange,
                    "brexchange": br_exchange,
                    "token": token,
                    "expiry": "",
                    "strike": -1,
                    "lotsize": 0,
                    "instrumenttype": "INDEX",
                    "tick_size": 0.0,
                }
            )

        logger.info(f"Fetched {len(rows)} Firstock indices from /V1/indexList")
        return pd.DataFrame(rows)

    except Exception as e:
        logger.exception(f"Error fetching Firstock indices: {e}")
        return pd.DataFrame()


def delete_firstock_temp_data(output_path):
    """Deletes the temporary CSV files after processing."""
    for filename in os.listdir(output_path):
        if filename.endswith("_symbols.csv"):
            file_path = os.path.join(output_path, filename)
            os.remove(file_path)
            logger.info(f"Deleted {file_path}")


def master_contract_download():
    """Downloads and processes Firstock contract data."""
    logger.info("Starting master contract download")
    output_path = "tmp"

    try:
        socketio.emit("download_progress", "Starting download...")

        # Initialize database
        init_db()
        delete_symtoken_table()

        # Download data
        downloaded_files = download_firstock_data(output_path)

        if downloaded_files:
            # Process each exchange
            if "NSE_symbols.csv" in downloaded_files:
                token_df = process_firstock_nse_data(output_path)
                copy_from_dataframe(token_df)

            if "BSE_symbols.csv" in downloaded_files:
                token_df = process_firstock_bse_data(output_path)
                copy_from_dataframe(token_df)

            if "NFO_symbols.csv" in downloaded_files:
                token_df = process_firstock_nfo_data(output_path)
                copy_from_dataframe(token_df)

            if "BFO_symbols.csv" in downloaded_files:
                token_df = process_firstock_bfo_data(output_path)
                copy_from_dataframe(token_df)

            # V1 API: indices are no longer in CSVs — fetch via authenticated endpoint
            index_df = fetch_firstock_indices()
            if not index_df.empty:
                copy_from_dataframe(index_df)

            # Clean up temporary files
            delete_firstock_temp_data(output_path)

            logger.info("Master contract download completed successfully")
            socketio.emit("download_progress", "Download completed")
        else:
            logger.info("No files were downloaded")
            socketio.emit("download_progress", "Download failed")

    except Exception as e:
        logger.error(f"Error in master contract download: {e}")
        socketio.emit("download_progress", f"Error: {str(e)}")
