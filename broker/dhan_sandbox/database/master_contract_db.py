# database/master_contract_db.py

import gzip
import http.client
import io
import json
import os
import shutil

import numpy as np
import pandas as pd
import requests
from sqlalchemy import Column, Float, Index, Integer, Sequence, String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker

from database.auth_db import get_auth_token
from database.engine_factory import create_db_engine
from extensions import socketio  # Import SocketIO
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
        logger.exception(f"Error during bulk insert: {e}")
        db_session.rollback()


def download_csv_dhan_data(output_path):
    logger.info("Downloading Master Contract CSV Files")
    # URLs of the CSV files to be downloaded
    csv_urls = {"master": "https://images.dhan.co/api-data/api-scrip-master.csv"}

    # Create a list to hold the paths of the downloaded files
    downloaded_files = []

    # Iterate through the URLs and download the CSV files
    for key, url in csv_urls.items():
        # Send GET request
        response = requests.get(url, timeout=10)
        # Check if the request was successful
        if response.status_code == 200:
            # Construct the full output path for the file
            file_path = f"{output_path}/{key}.csv"
            # Write the content to the file
            with open(file_path, "wb") as file:
                file.write(response.content)
            downloaded_files.append(file_path)
        else:
            logger.error(
                f"Failed to download {key} from {url}. Status code: {response.status_code}"
            )


def format_strike(strike):
    """Render a strike in OpenAlgo format: exact value, no trailing zeros.

    SEM_CUSTOM_SYMBOL renders strikes at two decimals, which both misformats
    (87.5 shown as "87.50") and, in currency, loses precision outright - EURUSD
    1.010 and 1.015 both display as "1.01". Building the strike from the
    authoritative SEM_STRIKE_PRICE avoids both. See #1930.
    """
    if pd.isna(strike):
        return ""
    # Format with decimals first so rstrip cannot eat significant zeros: "100"
    # would strip to "1", whereas "100.000000" stops at the decimal point.
    return f"{float(strike):.6f}".rstrip("0").rstrip(".") or "0"


def qualify_equity_symbol(trading_symbol, series):
    """Suffix a non-EQ NSE series onto the symbol, matching Zerodha's convention.

    Several NSE securities share a SEM_TRADING_SYMBOL across series - ELECTCAST
    is both the equity (EQ) and its warrant (W1), and IMC1 is three different
    bond tranches (N1/N2/N3). Without the series in the symbol, get_token()
    takes the first match and an order can reach the warrant. See #1930.
    """
    if pd.isna(series):
        return trading_symbol
    series = str(series).strip()
    if not series or series == "EQ":
        return trading_symbol
    return f"{trading_symbol}-{series}"


def reformat_symbol(row):
    symbol = row["SEM_CUSTOM_SYMBOL"]
    instrument_type = row["instrumenttype"]
    equity = row["SEM_INSTRUMENT_NAME"]
    expiry = row["expiry"].replace("-", "")

    if equity == "EQUITY":
        # NSE qualifies by series; BSE ships one row per symbol and has none.
        if row["SEM_EXM_EXCH_ID"] == "NSE":
            symbol = qualify_equity_symbol(row["SEM_TRADING_SYMBOL"], row["SEM_SERIES"])
        else:
            symbol = row["SEM_TRADING_SYMBOL"]
    elif equity == "INDEX":
        symbol = row["SEM_TRADING_SYMBOL"]

    elif instrument_type == "FUT":
        # For FUT, remove the spaces and append 'FUT' at the end
        parts = symbol.split(" ")
        if len(parts) == 3:  # Make sure the symbol has the correct format
            symbol = f"{parts[0]}{expiry}{instrument_type}"
        if len(parts) == 4:  # Make sure the symbol has the correct format
            symbol = f"{parts[0]}{expiry}{instrument_type}"
    elif instrument_type in ["CE", "PE"]:
        # For CE/PE take the underlying from the display string but the strike
        # from SEM_STRIKE_PRICE, which is exact.
        parts = symbol.split(" ")
        if len(parts) in (4, 5):
            symbol = f"{parts[0]}{expiry}{format_strike(row['SEM_STRIKE_PRICE'])}{instrument_type}"

    else:
        symbol = symbol  # No change for other instrument types

    return symbol


# Dhan segment codes. A Dhan security id is unique per SEM_SEGMENT, not per
# SEM_EXM_EXCH_ID, so the segment is the only safe key to map on.
SEGMENT_EQUITY = "E"
SEGMENT_INDEX = "I"
SEGMENT_EQUITY_DERIVATIVE = "D"
SEGMENT_CURRENCY = "C"
SEGMENT_COMMODITY = "M"

# Instrument names valid within each segment.
EQUITY_FNO_INSTRUMENTS = {"FUTIDX", "FUTSTK", "OPTIDX", "OPTSTK", "OPTFUT"}
CURRENCY_INSTRUMENTS = {"FUTCUR", "OPTCUR"}
COMMODITY_INSTRUMENTS = {"FUTCOM", "FUTIDX", "OPTFUT", "OPTIDX"}


# Define the function to apply conditions
def assign_values(row):
    """Map a Dhan scrip master row onto an OpenAlgo (exchange, brexchange, instrumenttype).

    Gating on SEM_SEGMENT is mandatory, not defensive. Dhan scopes
    SEM_SMST_SECURITY_ID per segment, and NSE carries two derivative segments
    under the same SEM_EXM_EXCH_ID of "NSE": segment D (equity F&O) and segment
    M (NSE's own commodity book, all OPTFUT). Matching on SEM_INSTRUMENT_NAME
    alone put both under NFO, so 8,642 security ids resolved to two different
    contracts - a TCS option and a SILVERM option shared token 153964. The
    reverse lookup in get_symbol() takes the first match, so a live equity
    option position could be reported under a commodity symbol, the position
    book lookup would miss it, and a strategy would skip the exit. See #1929.
    """
    exchange_id = row["SEM_EXM_EXCH_ID"]
    segment = row["SEM_SEGMENT"]
    instrument = str(row["SEM_INSTRUMENT_NAME"])

    # CE / PE for options, FUT for futures.
    derivative_type = row["SEM_OPTION_TYPE"] if "OPT" in instrument else "FUT"

    if segment == SEGMENT_EQUITY and instrument == "EQUITY":
        if exchange_id == "NSE":
            return "NSE", "NSE_EQ", "EQ"
        if exchange_id == "BSE":
            return "BSE", "BSE_EQ", "EQ"

    elif segment == SEGMENT_INDEX and instrument == "INDEX":
        if exchange_id == "NSE":
            return "NSE_INDEX", "IDX_I", "INDEX"
        if exchange_id == "BSE":
            return "BSE_INDEX", "IDX_I", "INDEX"

    elif segment == SEGMENT_EQUITY_DERIVATIVE and instrument in EQUITY_FNO_INSTRUMENTS:
        if exchange_id == "NSE":
            return "NFO", "NSE_FNO", derivative_type
        if exchange_id == "BSE":
            return "BFO", "BSE_FNO", derivative_type

    elif segment == SEGMENT_CURRENCY and instrument in CURRENCY_INSTRUMENTS:
        if exchange_id == "NSE":
            return "CDS", "NSE_CURRENCY", derivative_type
        if exchange_id == "BSE":
            return "BCD", "BSE_CURRENCY", derivative_type

    elif segment == SEGMENT_COMMODITY and instrument in COMMODITY_INSTRUMENTS:
        if exchange_id == "MCX":
            return "MCX", "MCX_COMM", derivative_type
        # NSE segment M is NSE's commodity derivatives book - OpenAlgo's NCO
        # exchange, which Dhan addresses as NSE_COMM. That segment string is
        # absent from Dhan's published annexure but is accepted by the API:
        # /v2/margincalculator returns a real margin and the live account
        # balance for NSE_COMM + securityId 153964, while NSE_COMMODITY and
        # NSE_FNO are both rejected with DH-905. It must never be folded into
        # NFO - its id space (121601-171512) overlaps NSE segment D, which is
        # the #1929 collision.
        if exchange_id == "NSE":
            return "NCO", "NSE_COMM", derivative_type

    return "Unknown", "Unknown", "Unknown"


def process_dhan_csv(path):
    """
    Processes the Dhan CSV file to fit the existing database schema and performs exchange name mapping.
    """
    logger.info("Processing Dhan Scrip Master CSV Data")
    file_path = f"{path}/master.csv"

    df = pd.read_csv(file_path, low_memory=False)
    df.columns = df.columns.str.strip()

    # Attempt to convert all date entries to datetime objects, errors are coerced to NaT
    df["SEM_EXPIRY_DATE"] = pd.to_datetime(df["SEM_EXPIRY_DATE"], errors="coerce")

    # Now, format all non-NaT datetime objects to the desired format "DD-MMM-YY"
    # NaT values will remain as NaT and can be handled separately if needed
    df["SEM_EXPIRY_DATE"] = df["SEM_EXPIRY_DATE"].dt.strftime("%d-%b-%y")

    # Optionally, handle NaT values by replacing them with a placeholder or removing them
    # For example, replacing NaT with 'Unknown Date':
    df["SEM_EXPIRY_DATE"] = df["SEM_EXPIRY_DATE"].fillna("-1")

    # Assigning headers to the DataFrame

    df["token"] = df["SEM_SMST_SECURITY_ID"]
    df["name"] = df["SM_SYMBOL_NAME"]
    df["expiry"] = df["SEM_EXPIRY_DATE"].str.upper()
    df["strike"] = df["SEM_STRIKE_PRICE"]
    df["lotsize"] = df["SEM_LOT_UNITS"]
    df["tick_size"] = df["SEM_TICK_SIZE"]
    df["brsymbol"] = df["SEM_TRADING_SYMBOL"]

    # Apply the function
    df[["exchange", "brexchange", "instrumenttype"]] = df.apply(
        assign_values, axis=1, result_type="expand"
    )

    # Drop rows no OpenAlgo exchange covers. Today that is NSE segment M, whose
    # security ids Dhan does not serve on any exchangeSegment (see
    # assign_values). A row kept here would keep its raw SEM_CUSTOM_SYMBOL
    # (reformat_symbol only normalizes known instrument types) and still
    # surface in symbol search, which filters by exchange only when the caller
    # passes one - so it would look tradable and then fail at the quote step.
    # Log the breakdown so a segment Dhan adds later is visible, not silent.
    unmapped = df["exchange"] == "Unknown"
    if unmapped.any():
        breakdown = (
            df.loc[unmapped]
            .groupby(["SEM_EXM_EXCH_ID", "SEM_SEGMENT", "SEM_INSTRUMENT_NAME"])
            .size()
            .to_dict()
        )
        logger.info(
            f"Dhan master contract: dropping {int(unmapped.sum())} rows with no "
            f"OpenAlgo exchange (exchange/segment/instrument: {breakdown})"
        )
        df = df[~unmapped].copy()

    df["symbol"] = df.apply(reformat_symbol, axis=1)

    # Normalize NSE_INDEX symbols: uppercase, remove spaces, only for symbols in OpenAlgo docs
    nse_idx_mask = df["exchange"] == "NSE_INDEX"
    valid_nse_symbols = {
        "NIFTY", "NIFTYNXT50", "FINNIFTY", "BANKNIFTY", "MIDCPNIFTY", "INDIAVIX",
        "HANGSENGBEESNAV", "NIFTY100", "NIFTY200", "NIFTY500", "NIFTYALPHA50",
        "NIFTYAUTO", "NIFTYCOMMODITIES", "NIFTYCONSUMPTION", "NIFTYCPSE",
        "NIFTYDIVOPPS50", "NIFTYENERGY", "NIFTYFMCG", "NIFTYGROWSECT15",
        "NIFTYGS10YR", "NIFTYGS10YRCLN", "NIFTYGS1115YR", "NIFTYGS15YRPLUS",
        "NIFTYGS48YR", "NIFTYGS813YR", "NIFTYGSCOMPSITE", "NIFTYINFRA", "NIFTYIT",
        "NIFTYMEDIA", "NIFTYMETAL", "NIFTYMIDLIQ15", "NIFTYMIDCAP100",
        "NIFTYMIDCAP150", "NIFTYMIDCAP50", "NIFTYMIDSML400", "NIFTYMNC",
        "NIFTYPHARMA", "NIFTYPSE", "NIFTYPSUBANK", "NIFTYPVTBANK", "NIFTYREALTY",
        "NIFTYSERVSECTOR", "NIFTYSMLCAP100", "NIFTYSMLCAP250", "NIFTYSMLCAP50",
        "NIFTY100EQLWGT", "NIFTY100LIQ15", "NIFTY100LOWVOL30", "NIFTY100QUALTY30",
        "NIFTY200QUALTY30", "NIFTY50DIVPOINT", "NIFTY50EQLWGT", "NIFTY50PR1XINV",
        "NIFTY50PR2XLEV", "NIFTY50TR1XINV", "NIFTY50TR2XLEV", "NIFTY50VALUE20",
    }
    original_nse = df.loc[nse_idx_mask, "symbol"].copy()
    df.loc[nse_idx_mask, "symbol"] = (
        df.loc[nse_idx_mask, "symbol"]
        .str.upper()
        .str.replace(" ", "", regex=False)
        .str.replace("-", "", regex=False)
    )
    df.loc[nse_idx_mask, "symbol"] = df.loc[nse_idx_mask, "symbol"].replace(
        {
            "NIFTYNEXT50": "NIFTYNXT50",
            "NIFTYMCAP50": "NIFTYMIDCAP50",
            "NIFTYMIDSMALLCAP400": "NIFTYMIDSML400",
            "NIFTYSMALLCAP100": "NIFTYSMLCAP100",
            "NIFTYSMALLCAP250": "NIFTYSMLCAP250",
            "NIFTYSMALLCAP50": "NIFTYSMLCAP50",
            "NIFTY100EQUALWEIGHT": "NIFTY100EQLWGT",
            "NIFTY100LOWVOLATILITY30": "NIFTY100LOWVOL30",
            "NIFTYMID100FREE": "NIFTYMIDCAP100",
        }
    )
    # Revert symbols not in the OpenAlgo standard set
    not_valid = ~df.loc[nse_idx_mask, "symbol"].isin(valid_nse_symbols)
    revert_idx = not_valid[not_valid].index
    df.loc[revert_idx, "symbol"] = original_nse.loc[revert_idx]

    # Normalize BSE_INDEX symbols to OpenAlgo standard format
    bse_idx_mask = df["exchange"] == "BSE_INDEX"
    bse_index_map = {
        "SENSEX": "SENSEX",
        "BANKEX": "BANKEX",
        "SNSX50": "SENSEX50",
        "SNXT50": "BSESENSEXNEXT50",
        "BSE100": "BSE100",
        "BSE200": "BSE200",
        "BSE500": "BSE500",
        "MID150": "BSE150MIDCAPINDEX",
        "LMI250": "BSE250LARGEMIDCAPINDEX",
        "MSL400": "BSE400MIDSMALLCAPINDEX",
        "AUTO": "BSEAUTO",
        "BSE CG": "BSECAPITALGOODS",
        "BSE CD": "BSECONSUMERDURABLES",
        "BSE HC": "BSEHEALTHCARE",
        "BSE IT": "BSEINFORMATIONTECHNOLOGY",
        "CARBON": "BSECARBONEX",
        "CPSE": "BSECPSE",
        "DOL100": "BSEDOLLEX100",
        "DOL200": "BSEDOLLEX200",
        "DOL30": "BSEDOLLEX30",
        "ENERGY": "BSEENERGY",
        "BSEFMC": "BSEFASTMOVINGCONSUMERGOODS",
        "FINSER": "BSEFINANCIALSERVICES",
        "GREENX": "BSEGREENEX",
        "INFRA": "BSEINDIAINFRASTRUCTUREINDEX",
        "INDSTR": "BSEINDUSTRIALS",
        "BSEIPO": "BSEIPO",
        "LRGCAP": "BSELARGECAP",
        "METAL": "BSEMETAL",
        "MIDCAP": "BSEMIDCAP",
        "MIDSEL": "BSEMIDCAPSELECTINDEX",
        "OILGAS": "BSEOIL&GAS",
        "POWER": "BSEPOWER",
        "BSEPSU": "BSEPSU",
        "REALTY": "BSEREALTY",
        "SMLCAP": "BSESMALLCAP",
        "SMLSEL": "BSESMALLCAPSELECTINDEX",
        "SMEIPO": "BSESMEIPO",
        "TECK": "BSETECK",
        "TELCOM": "BSETELECOM",
    }
    df.loc[bse_idx_mask, "symbol"] = df.loc[bse_idx_mask, "symbol"].replace(bse_index_map)

    # A (exchange, token) pair is what get_symbol() reverse-looks-up a live
    # position with, so it has to be unique. Two rows sharing one pair means a
    # position can resolve to the wrong contract silently (#1929). Log loudly
    # rather than raise - a broken master contract is worse than a duplicated
    # one, and the operator needs the detail to report it.
    collisions = df[df.duplicated(subset=["exchange", "token"], keep=False)]
    if not collisions.empty:
        samples = [
            f"{r.exchange}/{r.token}: {r.brsymbol}"
            for r in collisions.sort_values(["exchange", "token"]).head(6).itertuples()
        ]
        logger.error(
            f"Dhan master contract: {len(collisions)} rows share a duplicate "
            f"(exchange, token) across "
            f"{collisions.groupby(['exchange', 'token']).ngroups} pairs "
            f"(by exchange: {collisions['exchange'].value_counts().to_dict()}). "
            f"Position reverse-lookup is ambiguous for these. Samples: {samples}"
        )

    # The mirror of the check above: (symbol, exchange) is what get_token()
    # forward-looks-up before placing an order, so it has to be unique too. Two
    # rows sharing one pair means an order can reach the wrong instrument -
    # historically a warrant instead of the equity, or a neighbouring strike
    # (#1930). Logged, not raised, for the same reason as above.
    sym_collisions = df[df.duplicated(subset=["symbol", "exchange"], keep=False)]
    if not sym_collisions.empty:
        samples = [
            f"{r.exchange}/{r.symbol} -> {r.brsymbol} (token {r.token})"
            for r in sym_collisions.sort_values(["exchange", "symbol"]).head(6).itertuples()
        ]
        logger.error(
            f"Dhan master contract: {len(sym_collisions)} rows share a duplicate "
            f"(symbol, exchange) across "
            f"{sym_collisions.groupby(['symbol', 'exchange']).ngroups} pairs "
            f"(by exchange: {sym_collisions['exchange'].value_counts().to_dict()}). "
            f"Order forward-lookup is ambiguous for these. Samples: {samples}"
        )

    # List of columns to remove
    columns_to_remove = [
        "SEM_EXM_EXCH_ID",
        "SEM_SEGMENT",
        "SEM_SMST_SECURITY_ID",
        "SEM_INSTRUMENT_NAME",
        "SEM_EXPIRY_CODE",
        "SEM_TRADING_SYMBOL",
        "SEM_LOT_UNITS",
        "SEM_CUSTOM_SYMBOL",
        "SEM_EXPIRY_DATE",
        "SEM_STRIKE_PRICE",
        "SEM_OPTION_TYPE",
        "SEM_TICK_SIZE",
        "SEM_EXPIRY_FLAG",
        "SEM_EXCH_INSTRUMENT_TYPE",
        "SEM_SERIES",
        "SM_SYMBOL_NAME",
    ]

    # Removing the specified columns. errors="ignore" so a column Dhan drops
    # from a future master file does not break the whole download.
    token_df = df.drop(columns=columns_to_remove, errors="ignore")

    return token_df


def delete_dhan_temp_data(output_path):
    # Check each file in the directory
    for filename in os.listdir(output_path):
        # Construct the full file path
        file_path = os.path.join(output_path, filename)
        # If the file is a CSV, delete it
        if filename.endswith(".csv") and os.path.isfile(file_path):
            os.remove(file_path)
            logger.info(f"Deleted {file_path}")


def master_contract_download():
    logger.info("Downloading Master Contract")

    output_path = "tmp"
    try:
        download_csv_dhan_data(output_path)
        delete_symtoken_table()
        token_df = process_dhan_csv(output_path)
        copy_from_dataframe(token_df)
        delete_dhan_temp_data(output_path)
        # token_df['token'] = pd.to_numeric(token_df['token'], errors='coerce').fillna(-1).astype(int)

        # token_df = token_df.drop_duplicates(subset='symbol', keep='first')

        return socketio.emit(
            "master_contract_download", {"status": "success", "message": "Successfully Downloaded"}
        )

    except Exception as e:
        logger.exception(f"Error during master contract download: {e}")
        return socketio.emit("master_contract_download", {"status": "error", "message": str(e)})


def search_symbols(symbol, exchange):
    return SymToken.query.filter(
        SymToken.symbol.like(f"%{symbol}%"), SymToken.exchange == exchange
    ).all()
