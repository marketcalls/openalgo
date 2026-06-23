"""TradeSmart (Noren v2) master contract download & processing.

TradeSmart runs on the Noren platform and serves its own scrip-master files
from the v2 API host (``https://v2api.tradesmartonline.in/<EXCH>_symbols.txt.zip``)
in the standard Noren ``*_symbols.txt.zip`` layout. See ``tradesmart_urls`` below.

Symbol conventions enforced here (verified against the live zerodha symtoken):
  * instrumenttype is one of EQ / FUT / CE / PE / INDEX
  * indices live on NSE_INDEX / BSE_INDEX
  * expiry formatted as DD-MMM-YY uppercase, empty for EQ/index
  * special equity symbols keep their hyphen/ampersand (BAJAJ-AUTO, M&M) after
    the broker ``-EQ``/``-BE`` suffix is stripped
"""

import io
import os
import zipfile
from datetime import datetime

import pandas as pd
import requests
from sqlalchemy import Column, Float, Index, Integer, Sequence, String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker

from database.engine_factory import create_db_engine
from utils.logging import get_logger

logger = get_logger(__name__)

try:
    from extensions import socketio
except ImportError:
    socketio = None


# Database setup
DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_db_engine(DATABASE_URL)
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
    # Declared (left NULL) so a fresh-install create_all() matches the shared table
    contract_value = Column(Float)

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

    existing_token_exchange = {
        (result.token, result.exchange)
        for result in db_session.query(SymToken.token, SymToken.exchange).all()
    }
    filtered_data_dict = [
        row for row in data_dict if (row["token"], row["exchange"]) not in existing_token_exchange
    ]

    try:
        if filtered_data_dict:
            db_session.bulk_insert_mappings(SymToken, filtered_data_dict)
            db_session.commit()
            logger.info(f"Bulk insert completed with {len(filtered_data_dict)} new records.")
        else:
            logger.info("No new records to insert.")
    except Exception as e:
        logger.error(f"Error during bulk insert: {e}")
        db_session.rollback()


# TradeSmart's own Noren scrip masters, served from the v2 API host (verified
# live: each returns application/zip). Same Noren CSV layout as shoonya — header
# Exchange,Token,LotSize,Symbol,TradingSymbol,Instrument,TickSize.
tradesmart_urls = {
    "NSE": "https://v2api.tradesmartonline.in/NSE_symbols.txt.zip",
    "NFO": "https://v2api.tradesmartonline.in/NFO_symbols.txt.zip",
    "CDS": "https://v2api.tradesmartonline.in/CDS_symbols.txt.zip",
    "MCX": "https://v2api.tradesmartonline.in/MCX_symbols.txt.zip",
    "BSE": "https://v2api.tradesmartonline.in/BSE_symbols.txt.zip",
    "BFO": "https://v2api.tradesmartonline.in/BFO_symbols.txt.zip",
}


def download_and_unzip_tradesmart_data(output_path):
    """Download and unzip the Noren scrip-master text files into ``output_path``."""
    logger.info("Downloading and Unzipping TradeSmart (Noren) Data")
    if not os.path.exists(output_path):
        os.makedirs(output_path)

    downloaded_files = []
    for key, url in tradesmart_urls.items():
        try:
            response = requests.get(url, timeout=30)
            if response.status_code == 200:
                logger.info(f"Successfully downloaded {key} from {url}")
                z = zipfile.ZipFile(io.BytesIO(response.content))
                z.extractall(output_path)
                downloaded_files.append(f"{key}.txt")
            else:
                logger.error(f"Failed to download {key}: status {response.status_code}")
        except Exception as e:
            logger.error(f"Error downloading {key} from {url}: {e}")

    return downloaded_files


def process_tradesmart_nse_data(output_path):
    """Process NSE_symbols.txt → EQ + NSE_INDEX rows."""
    logger.info("Processing TradeSmart NSE Data")
    file_path = f"{output_path}/NSE_symbols.txt"

    df = pd.read_csv(
        file_path,
        usecols=["Exchange", "Token", "LotSize", "Symbol", "TradingSymbol", "Instrument", "TickSize"],
    )
    df.columns = ["exchange", "token", "lotsize", "name", "brsymbol", "instrumenttype", "tick_size"]
    df["symbol"] = df["brsymbol"]

    def get_openalgo_symbol(broker_symbol):
        # Strip only the broker series suffix; keep hyphens/ampersands in the base
        # (BAJAJ-AUTO-EQ -> BAJAJ-AUTO, M&M-EQ -> M&M)
        if "-EQ" in broker_symbol:
            return broker_symbol.replace("-EQ", "")
        elif "-BE" in broker_symbol:
            return broker_symbol.replace("-BE", "")
        return broker_symbol

    df["symbol"] = df["brsymbol"].apply(get_openalgo_symbol)
    df["exchange"] = df.apply(
        lambda row: "NSE_INDEX" if row["instrumenttype"] == "INDEX" else "NSE", axis=1
    )
    df["brexchange"] = df["exchange"]
    df["expiry"] = ""
    df["strike"] = -1
    df["instrumenttype"] = df["instrumenttype"].apply(lambda x: "EQ" if x in ["EQ", "BE"] else x)
    df["lotsize"] = pd.to_numeric(df["lotsize"], errors="coerce").fillna(0).astype(int)
    df["tick_size"] = pd.to_numeric(df["tick_size"], errors="coerce") / 100  # paise -> rupees

    columns_to_keep = [
        "symbol", "brsymbol", "name", "exchange", "brexchange", "token",
        "expiry", "strike", "lotsize", "instrumenttype", "tick_size",
    ]
    df_filtered = df[columns_to_keep]

    nse_idx_mask = df_filtered["exchange"] == "NSE_INDEX"
    df_filtered.loc[nse_idx_mask, "symbol"] = (
        df_filtered.loc[nse_idx_mask, "symbol"]
        .str.upper()
        .str.replace(" ", "", regex=False)
        .str.replace("-", "", regex=False)
    )
    df_filtered.loc[nse_idx_mask, "symbol"] = df_filtered.loc[nse_idx_mask, "symbol"].replace({
        "NIFTY50": "NIFTY",
        "NIFTYINDEX": "NIFTY",
        "NIFTYBANK": "BANKNIFTY",
        "NIFTYFIN": "FINNIFTY",
        "NIFTYFINSERVICE": "FINNIFTY",
        "NIFTYFINANCIALSERVICES": "FINNIFTY",
        "NIFTYNEXT50": "NIFTYNXT50",
        "NIFTYMIDSELECT": "MIDCPNIFTY",
        "NIFTYMIDCAPSELECT": "MIDCPNIFTY",
    })

    return df_filtered


def _format_expiry_date(date_str):
    """Format a Noren expiry (DD-MMM-YYYY) as DD-MMM-YY uppercase."""
    try:
        return datetime.strptime(date_str, "%d-%b-%Y").strftime("%d-%b-%y").upper()
    except ValueError:
        logger.info(f"Invalid expiry date format: {date_str}")
        return None


def _handle_strike_price(strike):
    try:
        if float(strike).is_integer():
            return int(float(strike))
        return float(strike)
    except (ValueError, TypeError):
        return -1


def _format_derivative_symbol(row):
    expiry_date = row["expiry"]
    compact_expiry = expiry_date.replace("-", "") if isinstance(expiry_date, str) else ""
    if row["instrumenttype"] == "FUT":
        return f"{row['name']}{compact_expiry}FUT"
    strike = row["strike"]
    if isinstance(strike, (int, float)) and float(strike).is_integer():
        strike = int(float(strike))
    return f"{row['name']}{compact_expiry}{strike}{row['instrumenttype']}"


def process_tradesmart_nfo_data(output_path):
    """Process NFO_symbols.txt → FUT/CE/PE rows."""
    logger.info("Processing TradeSmart NFO Data")
    file_path = f"{output_path}/NFO_symbols.txt"

    df = pd.read_csv(
        file_path,
        usecols=[
            "Exchange", "Token", "LotSize", "Symbol", "TradingSymbol", "Expiry",
            "Instrument", "OptionType", "StrikePrice", "TickSize",
        ],
    )
    df.columns = [
        "exchange", "token", "lotsize", "name", "brsymbol", "expiry",
        "instrumenttype", "optiontype", "strike", "tick_size",
    ]
    df["expiry"] = df["expiry"].fillna("")
    df["strike"] = df["strike"].fillna("-1")
    df["expiry"] = df["expiry"].apply(_format_expiry_date)
    df["instrumenttype"] = df.apply(
        lambda row: "FUT" if row["optiontype"] == "XX" else row["optiontype"], axis=1
    )
    df["strike"] = df["strike"].apply(_handle_strike_price)
    df["symbol"] = df.apply(_format_derivative_symbol, axis=1)
    df["exchange"] = "NFO"
    df["brexchange"] = df["exchange"]

    columns_to_keep = [
        "symbol", "brsymbol", "name", "exchange", "brexchange", "token",
        "expiry", "strike", "lotsize", "instrumenttype", "tick_size",
    ]
    return df[columns_to_keep]


def process_tradesmart_cds_data(output_path):
    """Process CDS_symbols.txt → currency FUT/CE/PE rows."""
    logger.info("Processing TradeSmart CDS Data")
    file_path = f"{output_path}/CDS_symbols.txt"

    df = pd.read_csv(
        file_path,
        usecols=[
            "Exchange", "Token", "LotSize", "Precision", "Multiplier", "Symbol",
            "TradingSymbol", "Expiry", "Instrument", "OptionType", "StrikePrice", "TickSize",
        ],
    )
    df.columns = [
        "exchange", "token", "lotsize", "precision", "multiplier", "name", "brsymbol",
        "expiry", "instrumenttype", "optiontype", "strike", "tick_size",
    ]
    df = df[df["token"] > 100]  # drop dummy/index rows
    df["expiry"] = df["expiry"].fillna("")
    df["strike"] = df["strike"].fillna("-1")
    df["expiry"] = df["expiry"].apply(_format_expiry_date)
    df["instrumenttype"] = df.apply(
        lambda row: "FUT" if row["optiontype"] == "XX" else row["instrumenttype"], axis=1
    )
    df["instrumenttype"] = df.apply(
        lambda row: row["optiontype"] if row["instrumenttype"] == "OPTCUR" else row["instrumenttype"],
        axis=1,
    )
    df["strike"] = df["strike"].apply(_handle_strike_price)
    df["symbol"] = df.apply(_format_derivative_symbol, axis=1)
    df["exchange"] = "CDS"
    df["brexchange"] = df["exchange"]

    columns_to_keep = [
        "symbol", "brsymbol", "name", "exchange", "brexchange", "token",
        "expiry", "strike", "lotsize", "instrumenttype", "tick_size",
    ]
    return df[columns_to_keep]


def process_tradesmart_mcx_data(output_path):
    """Process MCX_symbols.txt → commodity FUT/CE/PE rows."""
    logger.info("Processing TradeSmart MCX Data")
    file_path = f"{output_path}/MCX_symbols.txt"

    df = pd.read_csv(
        file_path,
        usecols=[
            "Exchange", "Token", "LotSize", "GNGD", "Symbol", "TradingSymbol",
            "Expiry", "Instrument", "OptionType", "StrikePrice", "TickSize",
        ],
    )
    df.columns = [
        "exchange", "token", "lotsize", "gngd", "name", "brsymbol", "expiry",
        "instrumenttype", "optiontype", "strike", "tick_size",
    ]
    df["expiry"] = df["expiry"].fillna("")
    df["strike"] = df["strike"].fillna("-1")
    df["expiry"] = df["expiry"].apply(_format_expiry_date)
    df["instrumenttype"] = df.apply(
        lambda row: "FUT" if row["optiontype"] == "XX" else row["instrumenttype"], axis=1
    )
    df["instrumenttype"] = df.apply(
        lambda row: row["optiontype"] if row["instrumenttype"] == "OPTFUT" else row["instrumenttype"],
        axis=1,
    )
    df["strike"] = df["strike"].apply(_handle_strike_price)
    df["symbol"] = df.apply(_format_derivative_symbol, axis=1)
    df["exchange"] = "MCX"
    df["brexchange"] = df["exchange"]

    columns_to_keep = [
        "symbol", "brsymbol", "name", "exchange", "brexchange", "token",
        "expiry", "strike", "lotsize", "instrumenttype", "tick_size",
    ]
    return df[columns_to_keep]


def process_tradesmart_bse_data(output_path):
    """Process BSE_symbols.txt → EQ rows + manual BSE indices (SENSEX, BANKEX)."""
    logger.info("Processing TradeSmart BSE Data")
    file_path = f"{output_path}/BSE_symbols.txt"

    df = pd.read_csv(
        file_path,
        usecols=["Exchange", "Token", "LotSize", "Symbol", "TradingSymbol", "Instrument", "TickSize"],
    )
    df.columns = ["exchange", "token", "lotsize", "name", "brsymbol", "instrumenttype", "tick_size"]
    df["symbol"] = df["brsymbol"]
    df["exchange"] = "BSE"
    df["brexchange"] = df["exchange"]
    df["expiry"] = ""
    df["strike"] = -1
    df["instrumenttype"] = "EQ"
    df["lotsize"] = pd.to_numeric(df["lotsize"], errors="coerce").fillna(0).astype(int)
    df["tick_size"] = pd.to_numeric(df["tick_size"], errors="coerce") / 100

    columns_to_keep = [
        "symbol", "brsymbol", "name", "exchange", "brexchange", "token",
        "expiry", "strike", "lotsize", "instrumenttype", "tick_size",
    ]
    df_filtered = df[columns_to_keep]

    bse_index_data = [
        {
            "symbol": "SENSEX", "brsymbol": "SENSEX", "name": "SENSEX",
            "exchange": "BSE_INDEX", "brexchange": "BSE_INDEX", "token": "1",
            "expiry": "", "strike": -1, "lotsize": 1, "instrumenttype": "INDEX", "tick_size": 0.05,
        },
        {
            "symbol": "BANKEX", "brsymbol": "BANKEX", "name": "BANKEX",
            "exchange": "BSE_INDEX", "brexchange": "BSE_INDEX", "token": "12",
            "expiry": "", "strike": -1, "lotsize": 1, "instrumenttype": "INDEX", "tick_size": 0.05,
        },
    ]
    bse_index_df = pd.DataFrame(bse_index_data)
    return pd.concat([df_filtered, bse_index_df], ignore_index=True)


def process_tradesmart_bfo_data(output_path):
    """Process BFO_symbols.txt → FUT/CE/PE rows (name extracted from symbol)."""
    logger.info("Processing TradeSmart BFO Data")
    file_path = f"{output_path}/BFO_symbols.txt"

    # NOTE: TradeSmart's BFO file names the strike column "Strike" (NFO/CDS/MCX
    # use "StrikePrice") and carries a trailing comma (an extra unnamed column).
    try:
        df = pd.read_csv(
            file_path,
            usecols=[
                "Exchange", "Token", "LotSize", "Symbol", "TradingSymbol", "Expiry",
                "Instrument", "OptionType", "Strike", "TickSize",
            ],
        )
    except Exception as e:
        logger.warning(f"Error reading BFO with specified columns: {e}")
        # Fallback: read everything, drop the trailing unnamed column(s)
        df = pd.read_csv(file_path).iloc[:, :10]

    df.columns = [
        "exchange", "token", "lotsize", "name", "brsymbol", "expiry",
        "instrumenttype", "optiontype", "strike", "tick_size",
    ]
    df["expiry"] = df["expiry"].fillna("")
    df["strike"] = df["strike"].fillna("-1")
    df["expiry"] = df["expiry"].apply(_format_expiry_date)

    import re

    def extract_name(tradingsymbol):
        match = re.match(r"([A-Za-z]+)", str(tradingsymbol))
        return match.group(1) if match else tradingsymbol

    def extract_instrument_type(tradingsymbol):
        ts = str(tradingsymbol)
        if ts.endswith("FUT"):
            return "FUT"
        elif ts.endswith("CE"):
            return "CE"
        elif ts.endswith("PE"):
            return "PE"
        return "UNKNOWN"

    df["name"] = df["brsymbol"].apply(extract_name)
    df["instrumenttype"] = df["brsymbol"].apply(extract_instrument_type)
    df["strike"] = df["strike"].apply(_handle_strike_price)

    def format_symbol(row):
        expiry_date = row["expiry"]
        compact_expiry = expiry_date.replace("-", "") if isinstance(expiry_date, str) else ""
        if row["instrumenttype"] == "FUT":
            return f"{row['name']}{compact_expiry}FUT"
        formatted_strike = (
            f"{int(row['strike'])}"
            if isinstance(row["strike"], int)
            else f"{row['strike']:.2f}".rstrip("0").rstrip(".")
        )
        return f"{row['name']}{compact_expiry}{formatted_strike}{row['instrumenttype']}"

    df["symbol"] = df.apply(format_symbol, axis=1)
    df["exchange"] = "BFO"
    df["brexchange"] = df["exchange"]

    columns_to_keep = [
        "symbol", "brsymbol", "name", "exchange", "brexchange", "token",
        "expiry", "strike", "lotsize", "instrumenttype", "tick_size",
    ]
    return df[columns_to_keep]


def delete_tradesmart_temp_data(output_path):
    """Delete the downloaded Noren symbol files after processing."""
    for filename in os.listdir(output_path):
        file_path = os.path.join(output_path, filename)
        if filename.endswith(".txt") and os.path.isfile(file_path):
            os.remove(file_path)
            logger.info(f"Deleted {file_path}")


def master_contract_download():
    """Download, process, and persist the TradeSmart master contract."""
    logger.info("Downloading TradeSmart Master Contract")
    output_path = "tmp"
    try:
        download_and_unzip_tradesmart_data(output_path)
        delete_symtoken_table()

        copy_from_dataframe(process_tradesmart_nse_data(output_path))
        copy_from_dataframe(process_tradesmart_bse_data(output_path))
        copy_from_dataframe(process_tradesmart_nfo_data(output_path))
        copy_from_dataframe(process_tradesmart_cds_data(output_path))
        copy_from_dataframe(process_tradesmart_mcx_data(output_path))
        copy_from_dataframe(process_tradesmart_bfo_data(output_path))

        delete_tradesmart_temp_data(output_path)

        if socketio:
            return socketio.emit(
                "master_contract_download",
                {"status": "success", "message": "Successfully Downloaded"},
            )
        logger.info("Successfully downloaded and processed all contracts")
    except Exception as e:
        error_msg = f"Error in master contract download: {e}"
        logger.error(error_msg)
        if socketio:
            return socketio.emit(
                "master_contract_download", {"status": "error", "message": error_msg}
            )
        raise
    finally:
        db_session.remove()
