# database/master_contract_db.py

import gzip
import os
import shutil
from datetime import datetime

# Import httpx and shared client
import httpx
import pandas as pd
from sqlalchemy import Column, Float, Index, Integer, Sequence, String, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker

from extensions import socketio  # Import SocketIO
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


DATABASE_URL = os.getenv("DATABASE_URL")  # Replace with your database path

engine = create_engine(DATABASE_URL)
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


def download_csv_5paisa_data(url, output_path):
    """
    Downloads a CSV file from the specified URL and saves it to the specified path using shared httpx client.
    Implements retry logic with increased timeout for reliability.

    Args:
        url (str): URL to download the CSV from
        output_path (str): Path where the downloaded file should be saved
    """
    max_retries = 3
    current_retry = 0
    chunk_size = 16384  # Increased chunk size for better performance

    # Create directory if it doesn't exist
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    while current_retry < max_retries:
        try:
            logger.info(f"Downloading CSV data (attempt {current_retry + 1}/{max_retries})")

            # Use a custom timeout for this specific request
            client = get_httpx_client()

            # Custom timeout for master contract download (2 minutes)
            timeout = httpx.Timeout(120.0)

            with client.stream("GET", url, timeout=timeout) as response:
                response.raise_for_status()

                total_size = int(response.headers.get("content-length", 0))
                bytes_downloaded = 0
                last_progress_report = 0

                with open(output_path, "wb") as f:
                    for chunk in response.iter_bytes(chunk_size=chunk_size):
                        if chunk:  # Filter out keep-alive chunks
                            f.write(chunk)
                            bytes_downloaded += len(chunk)

                            # Report progress every 10%
                            if total_size > 0:
                                progress = int((bytes_downloaded / total_size) * 100)
                                if progress >= last_progress_report + 10:
                                    logger.info(
                                        f"Download progress: {progress}% ({bytes_downloaded} / {total_size} bytes)"
                                    )
                                    last_progress_report = progress

            logger.info("Download complete")
            return  # Successfully downloaded, exit the function

        except httpx.TimeoutException as e:
            current_retry += 1
            logger.info(
                f"Timeout downloading master contract (attempt {current_retry}/{max_retries}): {e}"
            )
            if current_retry >= max_retries:
                logger.info("Maximum retries reached for master contract download.")
                raise Exception(
                    f"Failed to download master contract after {max_retries} attempts: {str(e)}"
                )
        except Exception as e:
            logger.error(f"Failed to download data: {e}")
            if "time" in str(e).lower() and current_retry < max_retries:
                # If it's a timeout-related error, retry
                current_retry += 1
                logger.info(f"Retrying download (attempt {current_retry}/{max_retries})")
            else:
                # For other errors, raise immediately
                raise


def process_5paisa_csv(path):
    """
    Processes the 5Paisa CSV file to fit the existing database schema.
    Args:
    path (str): The file path of the downloaded JSON data.

    Returns:
    DataFrame: The processed DataFrame ready to be inserted into the database.
    """
    # Read JSON data into a DataFrame
    df = pd.read_csv(path)
    exchange_mapping = {
        ("N", "C"): "NSE",
        ("B", "C"): "BSE",
        ("N", "D"): "NFO",
        ("B", "D"): "BFO",
        ("N", "U"): "CDS",
        ("B", "U"): "BCD",
        ("M", "D"): "MCX",
        # Add other mappings as needed
    }

    # Function to map Exch and ExchType to exchange names with additional conditions
    def map_exchange(row):
        if row["Exch"] == "N" and row["ExchType"] == "C":
            return "NSE_INDEX" if row["ScripCode"] > 999900 else "NSE"
        elif row["Exch"] == "B" and row["ExchType"] == "C":
            return "BSE_INDEX" if row["ScripCode"] > 999900 else "BSE"
        else:
            return exchange_mapping.get((row["Exch"], row["ExchType"]), "Unknown")

    # Apply the function to create the exchange column
    df["exchange"] = df.apply(map_exchange, axis=1)

    # Filter the DataFrame for Series 'EQ', 'BE', 'XX'
    filtered_df = df[df["Series"].isin(["EQ", "BE", "XX", "  "])].copy()

    filtered_df.loc[filtered_df["Series"].isin(["XX", "  "]), "Series"] = df["ScripType"]

    # filtered_df.loc[filtered_df['Series'] == 'XX', 'Series'] = 'FUT'

    # Convert 'Expiry' to datetime format
    filtered_df["Expiry"] = pd.to_datetime(filtered_df["Expiry"])

    # Format 'Expiry' to 'DD-MMM-YY'
    filtered_df["Expiry"] = filtered_df["Expiry"].dt.strftime("%d-%b-%y").str.upper()

    # Function to format StrikeRate
    def format_strike(strike):
        # Convert strike to string first
        strike_str = str(strike)
        # Check if the string ends with '.0' and remove it
        if strike_str.endswith(".0"):
            # Remove the last two characters '.0'
            return strike_str[:-2]
        elif strike_str.endswith(".00"):
            # Remove the last three characters '.00'
            return strike_str[:-3]
        # Return the original string if it does not end with '.0'
        return strike_str

    # Apply the function to the StrikeRate column
    filtered_df["StrikeRate"] = filtered_df["StrikeRate"].apply(format_strike)

    # Convert the Expiry column to strings and strip '-'
    filtered_df["Expiry1"] = filtered_df["Expiry"].astype(str).str.replace("-", "")

    # Apply the conditions
    def create_trading_symbol(row):
        if row["Series"] in ["BE", "EQ"]:
            return row["SymbolRoot"]
        elif row["Series"] == "XX":
            return row["SymbolRoot"] + row["Expiry1"] + "FUT"
        elif row["Series"] == "CE":
            return row["SymbolRoot"] + row["Expiry1"] + str(row["StrikeRate"]) + "CE"
        elif row["Series"] == "PE":
            return row["SymbolRoot"] + row["Expiry1"] + str(row["StrikeRate"]) + "PE"
        return row["SymbolRoot"]

    filtered_df["TradingSymbol"] = filtered_df.apply(create_trading_symbol, axis=1)

    # Create a new DataFrame in OpenAlgo format
    new_df = pd.DataFrame()
    new_df["symbol"] = filtered_df["TradingSymbol"]
    new_df["brsymbol"] = filtered_df["Name"].str.upper().str.rstrip()
    new_df["name"] = filtered_df["FullName"]
    new_df["exchange"] = filtered_df["exchange"]
    new_df["brexchange"] = filtered_df["exchange"]
    new_df["token"] = filtered_df["ScripCode"]
    new_df["expiry"] = filtered_df["Expiry"]
    new_df["strike"] = filtered_df["StrikeRate"]
    new_df["lotsize"] = filtered_df["LotSize"]
    new_df["instrumenttype"] = filtered_df["Series"]
    new_df["tick_size"] = filtered_df["TickSize"]
    # Common Index Symbol Normalization

    # Step 1: Normalize NSE_INDEX symbols - uppercase and remove spaces/hyphens
    nse_idx_mask = new_df["exchange"] == "NSE_INDEX"
    new_df.loc[nse_idx_mask, "symbol"] = (
        new_df.loc[nse_idx_mask, "symbol"]
        .str.upper()
        .str.replace(" ", "", regex=False)
        .str.replace("-", "", regex=False)
    )

    # Step 2: Normalize BSE_INDEX symbols - uppercase and remove spaces/hyphens
    bse_idx_mask = new_df["exchange"] == "BSE_INDEX"
    new_df.loc[bse_idx_mask, "symbol"] = (
        new_df.loc[bse_idx_mask, "symbol"]
        .str.upper()
        .str.replace(" ", "", regex=False)
        .str.replace("-", "", regex=False)
    )

    # Step 3: Explicit rename map for symbols whose cleaned form differs from OpenAlgo standard
    # Only apply to index exchanges to avoid renaming non-index symbols (e.g., ENERGY, FIN on NSE/BSE)
    idx_rename_mask = new_df["exchange"].isin(["NSE_INDEX", "BSE_INDEX"])
    new_df.loc[idx_rename_mask, "symbol"] = new_df.loc[idx_rename_mask, "symbol"].replace(
        {
            # NSE Index symbols (post-cleanup: uppercase, no spaces/hyphens)
            "NIFTY50": "NIFTY",
            "NIFTYNEXT50": "NIFTYNXT50",
            "NIFTYFINSERVICE": "FINNIFTY",
            "NIFTYFINANCIALSERVICES": "FINNIFTY",
            "NIFTYFIN": "FINNIFTY",
            "NIFTYBANK": "BANKNIFTY",
            "NIFTYMIDSELECT": "MIDCPNIFTY",
            "NIFTYMIDCAPSELECT": "MIDCPNIFTY",
            "NIFTYMCAP50": "NIFTYMIDCAP50",
            "NIFTYMIDSMALLCAP400": "NIFTYMIDSML400",
            "NIFTYSMALLCAP100": "NIFTYSMLCAP100",
            "NIFTYSMALLCAP250": "NIFTYSMLCAP250",
            "NIFTYSMALLCAP50": "NIFTYSMLCAP50",
            "NIFTY100EQUALWEIGHT": "NIFTY100EQLWGT",
            "NIFTY100LOWVOLATILITY30": "NIFTY100LOWVOL30",
            "NIFTYMID100FREE": "NIFTYMIDCAP100",
            # BSE Index symbols - short forms (raw SymbolRoot without BSE prefix)
            "SNSX50": "SENSEX50",
            "SNXT50": "BSESENSEXNEXT50",
            "MID150": "BSE150MIDCAPINDEX",
            "LMI250": "BSE250LARGEMIDCAPINDEX",
            "MSL400": "BSE400MIDSMALLCAPINDEX",
            "ENERGY": "BSEENERGY",
            "FIN": "BSEFINANCIALSERVICES",
            "FINSER": "BSEFINANCIALSERVICES",
            "INDSTR": "BSEINDUSTRIALS",
            "LRGCAP": "BSELARGECAP",
            "MIDSEL": "BSEMIDCAPSELECTINDEX",
            "SMLSEL": "BSESMALLCAPSELECTINDEX",
            "TELCOM": "BSETELECOM",
            # BSE Index symbols - BSE-prefixed forms (after cleanup of "BSE XXX" SymbolRoots)
            "BSESENSEX50": "SENSEX50",
            "BSEBANKEX": "BANKEX",
            "BSEAUTO": "BSEAUTO",
            "BSECAPGOOD": "BSECAPITALGOODS",
            "BSECG": "BSECAPITALGOODS",
            "BSECARBON": "BSECARBONEX",
            "BSECONSDUR": "BSECONSUMERDURABLES",
            "BSECD": "BSECONSUMERDURABLES",
            "BSECPSE": "BSECPSE",
            "BSEDOL100": "BSEDOLLEX100",
            "BSEDOL200": "BSEDOLLEX200",
            "BSEDOL30": "BSEDOLLEX30",
            "BSEFMCG": "BSEFASTMOVINGCONSUMERGOODS",
            "BSEFMC": "BSEFASTMOVINGCONSUMERGOODS",
            "BSEGREENX": "BSEGREENEX",
            "BSEHEALTHC": "BSEHEALTHCARE",
            "BSEHC": "BSEHEALTHCARE",
            "BSEINDIA150": "BSE150MIDCAPINDEX",
            "BSEINFRA": "BSEINDIAINFRASTRUCTUREINDEX",
            "BSEIT": "BSEINFORMATIONTECHNOLOGY",
            "BSEIPO": "BSEIPO",
            "BSEMETAL": "BSEMETAL",
            "BSEMIDCAP": "BSEMIDCAP",
            "BSEOIL&GAS": "BSEOIL&GAS",
            "BSEPOWER": "BSEPOWER",
            "BSEPSU": "BSEPSU",
            "BSEPBI": "BSEPSU",
            "BSEREALTY": "BSEREALTY",
            "BSESMLCAP": "BSESMALLCAP",
            "BSESMEIPO": "BSESMEIPO",
            "BSETECK": "BSETECK",
            "BSEPSUBANK": "BSEPSU",
        }
    )

    # Step 4: Remove duplicate index symbols (keep first occurrence)
    idx_mask = new_df["exchange"].isin(["NSE_INDEX", "BSE_INDEX"])
    idx_df = new_df[idx_mask]
    non_idx_df = new_df[~idx_mask]
    idx_df = idx_df.drop_duplicates(subset=["symbol", "exchange"], keep="first")
    new_df = pd.concat([non_idx_df, idx_df], ignore_index=True)

    return new_df


def delete_5paisa_temp_data(output_path):
    try:
        # Check if the file exists
        if os.path.exists(output_path):
            # Delete the file
            os.remove(output_path)
            logger.info(f"The temporary file {output_path} has been deleted.")
        else:
            logger.info(f"The temporary file {output_path} does not exist.")
    except Exception as e:
        logger.error(f"An error occurred while deleting the file: {e}")


def master_contract_download():
    logger.info("Starting Master Contract Download Process")
    url = "https://openapi.5paisa.com/VendorsAPI/Service1.svc/ScripMaster/segment/all"
    output_path = "tmp/5paisa.csv"

    # Ensure tmp directory exists
    os.makedirs("tmp", exist_ok=True)

    try:
        logger.info(f"Initiating download from {url}")
        download_csv_5paisa_data(url, output_path)

        logger.info("CSV downloaded, processing data...")
        token_df = process_5paisa_csv(output_path)
        logger.info(f"Processed {len(token_df)} symbols")

        # Clean up temporary files
        delete_5paisa_temp_data(output_path)

        # Clear existing data and insert new data
        logger.info("Updating database with new symbols...")
        delete_symtoken_table()  # Clear existing table
        copy_from_dataframe(token_df)

        logger.info("Master contract download completed successfully")
        # Notify UI through Socket.IO
        return socketio.emit(
            "master_contract_download",
            {"status": "success", "message": "Successfully Downloaded Master Contract"},
        )

    except Exception as e:
        error_message = str(e)
        logger.error(f"Error during master contract download: {error_message}")

        # Check if it's a timeout error and provide more helpful message
        if "timeout" in error_message.lower() or "timed out" in error_message.lower():
            error_message = f"Download timed out. The FivePaisa server is not responding within the allowed time. Error details: {error_message}"

        # Notify UI through Socket.IO
        return socketio.emit(
            "master_contract_download", {"status": "error", "message": error_message}
        )


def search_symbols(symbol, exchange):
    return SymToken.query.filter(
        SymToken.symbol.like(f"%{symbol}%"), SymToken.exchange == exchange
    ).all()
