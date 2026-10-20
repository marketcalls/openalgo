# database/master_contract_db.py

import io
import os
import re
from datetime import datetime

import pandas as pd
from sqlalchemy import Column, Float, Index, Integer, Sequence, String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker

from broker.motilal.api.baseurl import ENDPOINTS, get_base_url
from database.engine_factory import create_db_engine
from extensions import socketio  # Import SocketIO
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


DATABASE_URL = os.getenv("DATABASE_URL")  # Replace with your database path

engine = create_db_engine(DATABASE_URL)
db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()


class SymToken(Base):
    __tablename__ = "symtoken"
    id = Column(Integer, Sequence("symtoken_id_seq"), primary_key=True)
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
    # Convert DataFrame to a list of dictionaries
    data_dict = df.to_dict(orient="records")

    # Retrieve existing tokens to filter them out from the insert
    existing_tokens = {result.token for result in db_session.query(SymToken.token).all()}

    # Filter out data_dict entries with tokens that already exist
    filtered_data_dict = [row for row in data_dict if row["token"] not in existing_tokens]

    # Insert in bulk the filtered records
    try:
        if filtered_data_dict:  # Proceed only if there's anything to insert
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

        # Motilal Oswal CSV download URL (host honours BROKER_API_URL for UAT)
        url = f"{get_base_url()}{ENDPOINTS['getscripmastercsv']}?name={exchange_name}"

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


# --- Index symbol normalization (Motilal-specific) -----------------------
#
# Motilal ships index names in its own house-style ("Nifty 50", "BSE CAPGOOD",
# "SNXT50", ...) while OpenAlgo needs canonical symbols per symbol_Openalgo.md.
# The mapping is kept local to this broker loader so other brokers — which
# already feed clean strings — aren't affected.

# Broker-house-style NSE index name -> OpenAlgo canonical symbol. Keys are
# upper-cased and whitespace-stripped before lookup.
_NSE_INDEX_ALIASES: dict[str, str] = {
    "NIFTY50": "NIFTY",
    "NIFTYNEXT50": "NIFTYNXT50",
    "NIFTYFINSERVICE": "FINNIFTY",
    "NIFTYFINSERV": "FINNIFTY",
    "NIFTYBANK": "BANKNIFTY",
    "NIFTYMIDSELECT": "MIDCPNIFTY",
    "NIFTYMIDCAPSELECT": "MIDCPNIFTY",
    "INDIAVIX": "INDIAVIX",
}

# Broker-house-style BSE index name -> OpenAlgo canonical symbol. Keys are
# matched against the raw broker string after upper-casing + collapsing runs
# of whitespace to a single space (so "BSE  CAPGOOD" still hits "BSE CAPGOOD").
#
# The keys below are the strings the LIVE getindexdatacsv?name=BSE feed
# actually sends -- they are NOT the documented/expanded index names. Twenty
# keys here used to be spelled the documented way ("BSE DOLLEX 30",
# "BSE HEALTHCARE", "SNSX50", ...) and therefore never matched a single row,
# so those indices were stored under raw broker codes (BSEDOL30, BSEHEALTHC,
# ENERGY, LRGCAP, FIN, ...). Before changing a key, download
# https://openapi.motilaloswal.com/getindexdatacsv?name=BSE and copy the
# `indexname` column verbatim. Names with no live counterpart are kept as
# defensive entries in case the feed starts sending the longer form.
_BSE_INDEX_ALIASES_RAW: dict[str, str] = {
    # "SENSEX" is sent bare and falls through to "SENSEX" unchanged; the
    # "BSE SENSEX" key is defensive only.
    "BSE SENSEX": "SENSEX",
    "BSE BANKEX": "BANKEX",
    "BSE SENSEX 50": "SENSEX50",  # live name; was mis-keyed "SNSX50"
    "BSE 100": "BSE100",
    "BSE 150 MIDCAP": "BSE150MIDCAPINDEX",
    "BSE 200": "BSE200",
    "BSE 250 LARGEMIDCAP": "BSE250LARGEMIDCAPINDEX",
    "BSE 400 MIDSMALLCAP": "BSE400MIDSMALLCAPINDEX",
    "BSE 500": "BSE500",
    "BSE AUTO": "BSEAUTO",
    "BSE CAPGOOD": "BSECAPITALGOODS",
    "BSE CARBON": "BSECARBONEX",
    "BSE CONSDUR": "BSECONSUMERDURABLES",
    "BSE CPSE": "BSECPSE",
    "BSE DOL100": "BSEDOLLEX100",  # live name; was mis-keyed "BSE DOLLEX 100"
    "BSE DOL200": "BSEDOLLEX200",  # live name; was mis-keyed "BSE DOLLEX 200"
    "BSE DOL30": "BSEDOLLEX30",  # live name; was mis-keyed "BSE DOLLEX 30"
    "ENERGY": "BSEENERGY",  # live name; was mis-keyed "BSE ENERGY"
    "BSE FMCG": "BSEFASTMOVINGCONSUMERGOODS",
    "FIN": "BSEFINANCIALSERVICES",  # live name; was "BSE FINANCIAL SERVICES"
    "BSE GREENX": "BSEGREENEX",  # live name; was mis-keyed "BSE GREENEX"
    "BSE HEALTHC": "BSEHEALTHCARE",  # live name; was mis-keyed "BSE HEALTHCARE"
    "BSE INFRA": "BSEINDIAINFRASTRUCTUREINDEX",
    "INDSTR": "BSEINDUSTRIALS",  # live name; was mis-keyed "BSE INDUSTRIALS"
    "BSE IT": "BSEINFORMATIONTECHNOLOGY",
    "BSE IPO": "BSEIPO",
    "LRGCAP": "BSELARGECAP",  # live name; was mis-keyed "BSE LARGECAP"
    "BSE METAL": "BSEMETAL",
    "BSE MIDCAP": "BSEMIDCAP",
    "MIDSEL": "BSEMIDCAPSELECTINDEX",  # live name; was "BSE MIDCAP SELECT"
    "BSE OIL&GAS": "BSEOIL&GAS",
    "BSE POWER": "BSEPOWER",
    "BSE PSU": "BSEPSU",
    "BSE REALTY": "BSEREALTY",
    "SNXT50": "BSESENSEXNEXT50",
    "BSE SMLCAP": "BSESMALLCAP",  # live name; was mis-keyed "BSE SMALLCAP"
    "SMLSEL": "BSESMALLCAPSELECTINDEX",  # live name; was "BSE SMALLCAP SELECT"
    "BSE SMEIPO": "BSESMEIPO",  # live name; was mis-keyed "BSE SME IPO"
    "BSE TECK": "BSETECK",
    "TELCOM": "BSETELECOM",  # live name; was mis-keyed "BSE TELECOM"
}

_WHITESPACE_RE = re.compile(r"\s+")


def _collapse_ws(s: str) -> str:
    """Upper-case + collapse runs of whitespace to a single space + strip."""
    return _WHITESPACE_RE.sub(" ", s.upper()).strip()


_BSE_INDEX_ALIASES = {_collapse_ws(k): v for k, v in _BSE_INDEX_ALIASES_RAW.items()}


def _normalize_nse_index_symbol(broker_symbol):
    """NSE: upper + strip whitespace, then alias lookup; unlisted fall through."""
    if not broker_symbol:
        return broker_symbol
    cleaned = _WHITESPACE_RE.sub("", str(broker_symbol).upper())
    return _NSE_INDEX_ALIASES.get(cleaned, cleaned)


def _normalize_bse_index_symbol(broker_symbol):
    """
    BSE: alias lookup first (keys contain spaces / abbreviations that can't
    be auto-derived, e.g. "BSE CAPGOOD" -> "BSECAPITALGOODS"), then fall back
    to upper + strip whitespace so unlisted indices still come out canonical
    ("BSE 1000" -> "BSE1000").
    """
    if not broker_symbol:
        return broker_symbol
    raw = str(broker_symbol)
    aliased = _BSE_INDEX_ALIASES.get(_collapse_ws(raw))
    if aliased is not None:
        return aliased
    return _WHITESPACE_RE.sub("", raw.upper())


def standardize_index_symbols(df):
    """
    Standardize NSE_INDEX and BSE_INDEX symbol names to OpenAlgo canonical form
    using Motilal-specific alias maps. Symbols not in the maps pass through
    after basic cleanup (upper-case + whitespace removed). NaN rows are
    preserved — the old `.str` pipeline was NaN-safe and `.apply` is not.
    """
    nse_idx_mask = df["exchange"] == "NSE_INDEX"
    if nse_idx_mask.any():
        df.loc[nse_idx_mask, "symbol"] = df.loc[nse_idx_mask, "symbol"].apply(
            lambda s: _normalize_nse_index_symbol(s) if pd.notna(s) else s
        )

    bse_idx_mask = df["exchange"] == "BSE_INDEX"
    if bse_idx_mask.any():
        df.loc[bse_idx_mask, "symbol"] = df.loc[bse_idx_mask, "symbol"].apply(
            lambda s: _normalize_bse_index_symbol(s) if pd.notna(s) else s
        )

    return df


# --- BSE F&O underlying normalization ------------------------------------
#
# `scripshortname` -- which becomes `name` and is what the OpenAlgo symbol is
# built from -- carries Motilal/BSE *house contract codes* for BSE index
# derivatives, not the underlying index name. The BSEFO feed sends BSX / BKX /
# SX50 / BIT, which would produce "BSX03SEP2684200PE" instead of the canonical
# "SENSEX03SEP2684200PE".
#
# The mapping below is confirmed against the `ultoken` column of the live
# BSEFO scrip master, which points at the index code in getindexdatacsv?name=BSE:
#   BSX  -> ultoken 999901 -> "SENSEX"        -> SENSEX
#   BKX  -> ultoken 999912 -> "BSE BANKEX"    -> BANKEX
#   SX50 -> ultoken 999947 -> "BSE SENSEX 50" -> SENSEX50
#   BIT  -> ultoken 999975 -> "BSE Focused IT"-> *** deliberately unmapped ***
#
# BIT is left alone on purpose: its underlying is index 999975 "BSE Focused
# IT", which is NOT the documented BSEINFORMATIONTECHNOLOGY index (999934,
# "BSE IT"), and docs/prompt/symbol-format.md lists no canonical BFO name for
# it. Guessing "BSEIT" here would point at the wrong index, so the rows keep
# the broker code and a warning is logged instead (see _apply_bfo_underlying_aliases).
#
# NSEFO needs no equivalent map: its `scripshortname` is already canonical
# (NIFTY, BANKNIFTY, NIFTYNXT50, MIDCPNIFTY, FINNIFTY, NIFTYFPI) -- verified
# against the live NSEFO OPTIDX/FUTIDX rows.
_BFO_UNDERLYING_ALIASES: dict[str, str] = {
    "BSX": "SENSEX",
    "BKX": "BANKEX",
    "SX50": "SENSEX50",
}

# House codes seen on BSEFO index derivatives that have no confirmed canonical
# OpenAlgo underlying yet. Logged once per download rather than guessed.
_BFO_UNMAPPED_UNDERLYINGS = frozenset({"BIT"})


def _apply_bfo_underlying_aliases(df):
    """Rewrite BSE F&O house codes in `name` to canonical OpenAlgo underlyings.

    Must run BEFORE the FUT/CE/PE symbol strings are assembled, since those are
    built from `name`. Only touches rows whose exchange is BFO.
    """
    if "exchange" not in df.columns or "name" not in df.columns:
        return df

    bfo_mask = df["exchange"] == "BFO"
    if not bfo_mask.any():
        return df

    names = df.loc[bfo_mask, "name"]
    df.loc[bfo_mask, "name"] = names.replace(_BFO_UNDERLYING_ALIASES)

    unmapped = names[names.isin(_BFO_UNMAPPED_UNDERLYINGS)]
    if len(unmapped):
        logger.warning(
            f"Motilal BSEFO: {len(unmapped)} rows use house underlying code(s) "
            f"{sorted(set(unmapped))} with no confirmed canonical OpenAlgo name; "
            f"symbols keep the broker code. Add them to _BFO_UNDERLYING_ALIASES "
            f"once docs/prompt/symbol-format.md names them."
        )

    return df


# --- Expiry handling ------------------------------------------------------
#
# IMPORTANT: Motilal's `expirydate` column is NOT a Unix epoch. It is SECONDS
# SINCE 1980-01-01T00:00:00Z, i.e. unix_ts = expirydate + 315532800. Nothing
# else in OpenAlgo knows this, hence this note.
#
# We deliberately do NOT convert that field. Expiry is parsed out of
# `scripname` instead ("TGBL 30-OCT-2025 CE 1180" -> 30-OCT-25), for two
# reasons:
#
#   1. It is exact. Cross-checked against the converted epoch across all
#      ~146k derivative rows of the live feed: 0 mismatches on NSEFO/BSEFO/NSECD.
#   2. It dodges a real broker bug on MCX. Every one of the ~16k MCX rows
#      carries a 23:59:59-UTC stamp (e.g. 1475711999 -> 2026-10-05 23:59:59Z),
#      so converting and reading it in IST yields 2026-10-06 05:29:59 -- the
#      expiry date plus one day, for the entire exchange.
#
# So: keep parsing from scripname. If you ever switch to the epoch, add the
# 315532800 offset AND normalize MCX in UTC, not IST.


def extract_expiry_from_scripname(scripname):
    """
    Extract expiry date from scripname and convert to DD-MMM-YY format.
    Args:
        scripname: Script name like "TGBL 30-OCT-2025 CE 1180"
    Returns:
        str: Formatted date string (DD-MMM-YY) or empty string
    """
    try:
        if pd.isna(scripname) or scripname == "":
            return ""

        # Split the scripname by spaces
        parts = str(scripname).split()

        # Look for date pattern DD-MMM-YYYY
        import re

        for part in parts:
            # Match pattern like 30-OCT-2025 or 30-Oct-2025
            if re.match(r"\d{1,2}-[A-Za-z]{3}-\d{4}", part):
                # Parse and reformat to DD-MMM-YY
                date_obj = datetime.strptime(part, "%d-%b-%Y")
                return date_obj.strftime("%d-%b-%y").upper()

        return ""
    except (ValueError, AttributeError):
        return ""


def download_csv_index_data(exchange_name):
    """
    Downloads the index CSV file from Motilal Oswal for NSE/BSE indices.

    Args:
        exchange_name (str): Exchange name ('NSE' or 'BSE')

    Returns:
        pd.DataFrame: DataFrame containing the downloaded index data
    """
    try:
        # Get the shared httpx client
        client = get_httpx_client()

        # Motilal Oswal Index CSV download URL (host honours BROKER_API_URL for UAT)
        url = f"{get_base_url()}{ENDPOINTS['getindexdatacsv']}?name={exchange_name}"

        logger.info(f"Downloading Motilal index data for {exchange_name} from {url}")

        # Make the GET request using the shared client
        response = client.get(url, timeout=30)
        response.raise_for_status()

        # Process the response directly as CSV
        csv_string = response.text
        df = pd.read_csv(io.StringIO(csv_string))

        logger.info(f"Downloaded {len(df)} index records for {exchange_name}")
        return df

    except Exception as e:
        error_message = str(e)
        logger.error(f"Error downloading Motilal index data for {exchange_name}: {error_message}")
        raise


def process_motilal_index_csv(df, exchange_name):
    """
    Processes the Motilal Index CSV file to fit the OpenAlgo database schema.

    Args:
        df (pd.DataFrame): Raw DataFrame from Motilal Index API
        exchange_name (str): Exchange name ('NSE' or 'BSE')

    Returns:
        pd.DataFrame: Processed DataFrame ready for database insertion
    """
    logger.info(f"Processing Motilal Index CSV Data for {exchange_name}")

    # Rename columns based on Motilal Index API format
    df = df.rename(
        columns={"indexcode": "token", "indexname": "symbol", "exchangename": "brexchange"}
    )

    # Set the name same as symbol for indices
    df["name"] = df["symbol"]
    df["brsymbol"] = df["symbol"]

    # SymToken.token is a String column and process_motilal_csv() already emits
    # str tokens. The index feed's `indexcode` parses as int64, so without this
    # cast the same table would hold "26000" from one path and 26000 from the
    # other -- and token lookups on the index rows would silently miss.
    df["token"] = df["token"].astype(str)

    # Map exchange to OpenAlgo format with _INDEX suffix
    if exchange_name == "NSE":
        df["exchange"] = "NSE_INDEX"
    elif exchange_name == "BSE":
        df["exchange"] = "BSE_INDEX"
    else:
        df["exchange"] = exchange_name + "_INDEX"

    # Set instrumenttype for indices
    df["instrumenttype"] = "INDEX"

    # Set default values for fields not applicable to indices
    df["expiry"] = ""
    df["strike"] = 0.0
    df["lotsize"] = 1
    df["tick_size"] = 0.05

    # Standardize index symbols to OpenAlgo format
    df = standardize_index_symbols(df)

    # Select only the columns needed for the database
    required_columns = [
        "token",
        "symbol",
        "brsymbol",
        "name",
        "exchange",
        "brexchange",
        "expiry",
        "strike",
        "lotsize",
        "instrumenttype",
        "tick_size",
    ]

    df = df[required_columns]

    # Fill NaN values
    df["symbol"] = df["symbol"].fillna("")
    df["brsymbol"] = df["brsymbol"].fillna("")
    df["name"] = df["name"].fillna("")

    logger.info(f"Processed {len(df)} index records for {exchange_name}")
    return df


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
    df = df.rename(
        columns={
            "scripcode": "token",
            "scripname": "symbol",
            "scripshortname": "name",
            "marketlot": "lotsize",
            "instrumentname": "instrumenttype",
            "expirydate": "expiry",
            "strikeprice": "strike",
            "ticksize": "tick_size",
            "exchangename": "brexchange",
        }
    )

    # Add broker symbol and exchange (keep original)
    df["brsymbol"] = df["symbol"]

    # Map Motilal exchange names to OpenAlgo exchange names
    exchange_map = {
        "NSE": "NSE",
        "BSE": "BSE",
        "NSEFO": "NFO",
        "NSECD": "CDS",
        "MCX": "MCX",
        "BSEFO": "BFO",
        "BSECD": "BCD",
        "NCDEX": "NCDEX",
        "NSECO": "CDS",
        "BSECO": "BCD",
    }

    df["exchange"] = df["brexchange"].map(exchange_map).fillna(df["brexchange"])

    # Extract expiry date from scripname (brsymbol) instead of timestamp
    df["expiry"] = df["brsymbol"].apply(extract_expiry_from_scripname)

    # Convert strike price (Motilal sends it in correct format, no conversion needed)
    df["strike"] = pd.to_numeric(df["strike"], errors="coerce").fillna(0)

    # Convert lotsize to int
    df["lotsize"] = pd.to_numeric(df["lotsize"], errors="coerce").fillna(1).astype(int)

    # Motilal CSV already provides tick_size in rupees (e.g. 0.05), no conversion needed.
    # Coerce non-positive ticks (not just NaN) to the 0.05 default: the live NSECD
    # feed ships ticksize=0.000 on ~1.6k rows, and mapping/transform_data.py treats
    # tick_size as falsy at 0 when rounding to the market protection price.
    df["tick_size"] = pd.to_numeric(df["tick_size"], errors="coerce")
    df.loc[~(df["tick_size"] > 0), "tick_size"] = 0.05

    # Convert token to string
    df["token"] = df["token"].astype(str)

    # Process option type column
    if "optiontype" in df.columns:
        df["optiontype"] = df["optiontype"].fillna("XX")
    else:
        df["optiontype"] = "XX"

    # Motilal ships `instrumentname` space-padded, and BLANK for cash rows: every
    # NSE/BSE equity landed with instrumenttype "      " (six spaces) instead of
    # "EQ", and MCX underlyings with "COM   ". A padded value is not equal to any
    # constant it is compared against, and it is truthy, so UI badges rendered
    # blank and any instrumenttype filter silently matched nothing. Strip first,
    # then let the FUT/CE/PE rules below refine it.
    df["instrumenttype"] = (
        df["instrumenttype"].fillna("").astype(str).str.strip().str.upper()
    )

    # Update instrumenttype to match Angel format (FUT, CE, PE, etc.)
    # For Futures - set to 'FUT' (only when optiontype is XX, i.e., not an option)
    df.loc[
        (df["instrumenttype"].str.contains("FUT", na=False)) & (df["optiontype"] == "XX"),
        "instrumenttype",
    ] = "FUT"

    # For Options - set to 'CE' or 'PE' based on optiontype column directly
    df.loc[df["optiontype"] == "CE", "instrumenttype"] = "CE"
    df.loc[df["optiontype"] == "PE", "instrumenttype"] = "PE"

    # Format symbols according to OpenAlgo standards

    # For Index instruments, update exchange
    df.loc[
        (df["instrumenttype"].str.contains("IDX", na=False)) & (df["exchange"] == "NSE"), "exchange"
    ] = "NSE_INDEX"
    df.loc[
        (df["instrumenttype"].str.contains("IDX", na=False)) & (df["exchange"] == "BSE"), "exchange"
    ] = "BSE_INDEX"
    df.loc[
        (df["instrumenttype"].str.contains("IDX", na=False)) & (df["exchange"] == "MCX"), "exchange"
    ] = "MCX_INDEX"

    # Cash rows carry no instrumentname at all, so after the index rows above
    # have been routed to NSE_INDEX/BSE_INDEX everything still blank on a cash
    # exchange is an equity-style scrip. "EQ" is what every other OpenAlgo
    # broker stores there, and what the UI's type badge and instrumenttype
    # filters expect.
    df.loc[
        (df["exchange"].isin(["NSE", "BSE"])) & (df["instrumenttype"] == ""),
        "instrumenttype",
    ] = "EQ"

    # Normalize strike for everything that is not an option. Motilal ships
    # strikeprice=-1.000 on futures and on the CDS/MCX underlying rows (UNDCUR,
    # UNDIRC, COM); every other OpenAlgo broker stores 0.0 there, and -1.0 leaks
    # into strike-based filters and API responses.
    df.loc[~df["instrumenttype"].isin(["CE", "PE"]), "strike"] = 0.0

    # BSE F&O index derivatives ship house codes (BSX/BKX/SX50) in `name`.
    # Must happen before the symbol strings below are assembled from `name`.
    df = _apply_bfo_underlying_aliases(df)

    # Guard the symbol builders below: every FUT/CE/PE symbol is
    # NAME + EXPIRY + [STRIKE] + SUFFIX, so an empty expiry collapses every
    # contract on an underlying to the same string ("NIFTYFUT") and they all
    # collide on the (symbol, exchange) dedupe. The MCX/CDS branches already
    # tested for this; the other exchanges did not.
    _deriv_mask = df["instrumenttype"].isin(["FUT", "CE", "PE"])
    _has_expiry = df["expiry"].fillna("").astype(str) != ""
    _missing_expiry = _deriv_mask & ~_has_expiry
    if _missing_expiry.any():
        logger.warning(
            f"Motilal {exchange_name}: could not extract an expiry from scripname for "
            f"{int(_missing_expiry.sum())} derivative row(s); their symbols are left as "
            f"the raw broker scripname rather than being collapsed onto a shared "
            f"expiry-less symbol. Samples: "
            f"{df.loc[_missing_expiry, 'brsymbol'].head(5).tolist()}"
        )

    # Helper function to format strike price
    def format_strike(strike):
        try:
            strike_float = float(strike)
            # If strike has decimal part, keep it; otherwise show as integer
            if strike_float % 1 == 0:
                return str(int(strike_float))
            else:
                # Remove trailing zeros after decimal point
                return str(strike_float).rstrip("0").rstrip(".")
        except Exception:
            return str(strike)

    # Format Futures symbols: NAME + EXPIRY(no dashes) + FUT
    # For MCX and CDS, use brsymbol if expiry exists, otherwise use name
    df.loc[
        (df["instrumenttype"] == "FUT")
        & (df["exchange"].isin(["MCX", "CDS"]))
        & (df["expiry"] != ""),
        "symbol",
    ] = df["name"] + df["expiry"].str.replace("-", "", regex=False) + "FUT"
    # For other exchanges with FUT
    df.loc[
        (df["instrumenttype"] == "FUT") & (~df["exchange"].isin(["MCX", "CDS"])) & _has_expiry,
        "symbol",
    ] = df["name"] + df["expiry"].str.replace("-", "", regex=False) + "FUT"

    # Format Options symbols: NAME + EXPIRY(no dashes) + STRIKE + CE/PE
    # For MCX and CDS options
    df.loc[
        (df["instrumenttype"] == "CE")
        & (df["exchange"].isin(["MCX", "CDS"]))
        & (df["expiry"] != ""),
        "symbol",
    ] = (
        df["name"]
        + df["expiry"].str.replace("-", "", regex=False)
        + df["strike"].apply(format_strike)
        + "CE"
    )
    df.loc[
        (df["instrumenttype"] == "PE")
        & (df["exchange"].isin(["MCX", "CDS"]))
        & (df["expiry"] != ""),
        "symbol",
    ] = (
        df["name"]
        + df["expiry"].str.replace("-", "", regex=False)
        + df["strike"].apply(format_strike)
        + "PE"
    )
    # For other exchanges with options
    df.loc[
        (df["instrumenttype"] == "CE") & (~df["exchange"].isin(["MCX", "CDS"])) & _has_expiry,
        "symbol",
    ] = (
        df["name"]
        + df["expiry"].str.replace("-", "", regex=False)
        + df["strike"].apply(format_strike)
        + "CE"
    )
    df.loc[
        (df["instrumenttype"] == "PE") & (~df["exchange"].isin(["MCX", "CDS"])) & _has_expiry,
        "symbol",
    ] = (
        df["name"]
        + df["expiry"].str.replace("-", "", regex=False)
        + df["strike"].apply(format_strike)
        + "PE"
    )

    # Clean up cash symbols: strip the exchange SERIES suffix.
    #
    # On the NSE cash feed the series lives in the `optiontype` column and is
    # appended to `scripname`: "INFY EQ", "LOKESHMACH BE", "SFMP6DD MF",
    # "745AP33 SG". `instrumentname` is six blanks on every cash row, so the old
    # `EQ|CASH` instrumenttype test never fired, and the follow-up only removed
    # a literal " EQ" -- leaving 7,197 of 9,858 NSE symbols with a trailing
    # series token (SG 4301, N0 982, SM 442, BE 239, GS 132, ST 122, MF 115,
    # N1 107, TB 81, SF 50, GB 45, ...). No OpenAlgo symbol may contain a space.
    #
    # `scripshortname` (-> `name`) already holds the bare scrip and matches
    # `scripname` minus " <series>" on 9,839/9,858 NSE rows; the other 19 are
    # series "NA", which pandas reads as NaN so the suffix cannot be rebuilt --
    # `name` is right there too. So prefer `name`, and only fall back to
    # stripping the literal " <optiontype>" off the raw scripname.
    #
    # Scoped to non-derivative NSE/BSE rows so nothing built above is touched.
    # `brsymbol` intentionally keeps the RAW broker scripname ("INFY EQ").
    cash_mask = df["exchange"].isin(["NSE", "BSE"]) & ~_deriv_mask
    if cash_mask.any():
        raw = df.loc[cash_mask, "brsymbol"].fillna("").astype(str)
        series = df.loc[cash_mask, "optiontype"].fillna("").astype(str).str.strip()
        bare = df.loc[cash_mask, "name"].fillna("").astype(str).str.strip()

        stripped = pd.Series(
            [
                r[: -(len(s) + 1)].strip() if s and s != "XX" and r.endswith(" " + s) else r.strip()
                for r, s in zip(raw, series, strict=True)
            ],
            index=raw.index,
        )
        df.loc[cash_mask, "symbol"] = bare.where(bare != "", stripped)

        # Stripping the series makes parallel listings of the SAME scrip collapse
        # onto one bare symbol -- NSE runs temporary series alongside the main
        # line ("CHOLAFIN D1" + "CHOLAFIN EQ", "MOTHERSON D1" + "MOTHERSON EQ",
        # "ELECTCAST W1" + "ELECTCAST EQ"). OpenAlgo's namespace is
        # (symbol, exchange), so only one can survive the dedupe in
        # master_contract_download(); make it the EQ row, otherwise the canonical
        # symbol would resolve to the temporary series' token and orders on it
        # would hit the wrong instrument. Groups with no EQ row (e.g. the IMC1
        # N1/N2/N3 government-security series) keep their first row as before.
        eq_first = df.loc[cash_mask].assign(_eq_rank=(series != "EQ").astype(int))
        survivors = (
            eq_first.sort_values("_eq_rank", kind="stable")
            .drop_duplicates(subset=["symbol", "exchange"], keep="first")
            .index
        )
        shadowed = eq_first.index.difference(survivors)
        if len(shadowed):
            logger.info(
                f"Motilal {exchange_name}: dropping {len(shadowed)} non-primary cash "
                f"series row(s) that collapse onto an existing symbol: "
                f"{df.loc[shadowed, 'brsymbol'].head(10).tolist()}"
            )
            df = df.drop(index=shadowed)
            cash_mask = cash_mask.drop(index=shadowed)

        # The broker's own scripshortname carries a space on a handful of BSE
        # scrips ("PILANI INVE"); surface those rather than silently mangling
        # them, since the correct bare symbol cannot be derived from the feed.
        spaced = df.loc[cash_mask, "symbol"].astype(str).str.contains(" ")
        if spaced.any():
            logger.warning(
                f"Motilal {exchange_name}: {int(spaced.sum())} cash symbol(s) still "
                f"contain a space after series stripping (the broker's own "
                f"scripshortname is spaced): "
                f"{df.loc[cash_mask, 'symbol'][spaced].head(10).tolist()}"
            )

    # Standardize index symbols to OpenAlgo format
    df = standardize_index_symbols(df)

    # Select only the columns needed for the database
    required_columns = [
        "token",
        "symbol",
        "brsymbol",
        "name",
        "exchange",
        "brexchange",
        "expiry",
        "strike",
        "lotsize",
        "instrumenttype",
        "tick_size",
    ]

    df = df[required_columns]

    # Fill NaN values
    df["expiry"] = df["expiry"].fillna("")
    df["name"] = df["name"].fillna("")
    df["symbol"] = df["symbol"].fillna("")
    df["brsymbol"] = df["brsymbol"].fillna("")

    logger.info(f"Processed {len(df)} records for {exchange_name}")
    return df


def master_contract_download():
    """
    Downloads master contracts from Motilal Oswal for all supported exchanges including indices.
    """
    logger.info("Downloading Master Contract from Motilal Oswal")

    # List of exchanges to download scrip master data
    exchanges = ["NSE", "BSE", "NSEFO", "NSECD", "MCX", "BSEFO"]

    # List of exchanges to download index data
    index_exchanges = ["NSE", "BSE"]

    try:
        all_data = []

        # Download scrip master data for all exchanges
        for exchange in exchanges:
            try:
                logger.info(f"Downloading {exchange} scrip master data...")
                df = download_csv_motilal_data(exchange)
                processed_df = process_motilal_csv(df, exchange)
                all_data.append(processed_df)
                logger.info(f"Successfully processed {exchange} scrip master")
            except Exception as e:
                logger.error(f"Error processing {exchange}: {str(e)}")
                # Continue with other exchanges even if one fails
                continue

        # Download index data for NSE and BSE
        for exchange in index_exchanges:
            try:
                logger.info(f"Downloading {exchange} index data...")
                df = download_csv_index_data(exchange)
                processed_df = process_motilal_index_csv(df, exchange)
                all_data.append(processed_df)
                logger.info(f"Successfully processed {exchange} indices")
            except Exception as e:
                logger.error(f"Error processing {exchange} indices: {str(e)}")
                # Continue even if index download fails
                continue

        if not all_data:
            raise Exception("Failed to download data from any exchange")

        # Combine all exchange data (scrip master + indices)
        token_df = pd.concat(all_data, ignore_index=True)

        # Deduplicate on (symbol, exchange) -- the house convention, see
        # broker/hdfcsky, broker/fivepaisa and broker/definedge.
        #
        # NOT on token alone: a Motilal scripcode is unique only WITHIN an
        # exchange, never globally. Deduping on token dropped 2,452 real
        # instruments (169,486 -> 167,034), all of them CDS/MCX rows whose
        # scripcode happened to collide with an NSE/BSE cash token -- e.g. token
        # 5479 (USDINR23OCT26FUT) lost to an NSE scrip, token 10084
        # (GBPUSD27AUG261.4CE) lost to NSE "EMAMIPAP". That silently deleted
        # ~20% of the CDS segment, including 41 of its 178 futures.
        before = len(token_df)
        token_df = token_df.drop_duplicates(subset=["symbol", "exchange"], keep="first")
        if before != len(token_df):
            logger.info(
                f"Dropped {before - len(token_df)} duplicate (symbol, exchange) rows "
                f"({before} -> {len(token_df)})"
            )

        logger.info(f"Total records to insert: {len(token_df)}")

        # Delete existing data and insert new data
        delete_symtoken_table()
        copy_from_dataframe(token_df)

        return socketio.emit(
            "master_contract_download",
            {
                "status": "success",
                "message": f"Successfully Downloaded {len(token_df)} instruments",
            },
        )

    except Exception as e:
        logger.error(f"Error in master_contract_download: {str(e)}")
        return socketio.emit("master_contract_download", {"status": "error", "message": str(e)})


def search_symbols(symbol, exchange):
    return SymToken.query.filter(
        SymToken.symbol.like(f"%{symbol}%"), SymToken.exchange == exchange
    ).all()
