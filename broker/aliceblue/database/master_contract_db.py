# database/master_contract_db.py

import gzip
import io
import json
import os
import shutil
import zipfile

import numpy as np
import pandas as pd
from sqlalchemy import Column, Float, Index, Integer, Sequence, String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker

from database.auth_db import get_auth_token
from database.engine_factory import create_db_engine
from extensions import socketio  # Import SocketIO
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


# Define the headers as provided
headers = [
    "Fytoken",
    "Symbol Details",
    "Exchange Instrument type",
    "Minimum lot size",
    "Tick size",
    "ISIN",
    "Trading Session",
    "Last update date",
    "Expiry date",
    "Symbol ticker",
    "Exchange",
    "Segment",
    "Scrip code",
    "Underlying symbol",
    "Underlying scrip code",
    "Strike price",
    "Option type",
    "Underlying FyToken",
    "Reserved column1",
    "Reserved column2",
    "Reserved column3",
]

# Data types for each header
data_types = {
    "Fytoken": str,
    "Symbol Details": str,
    "Exchange Instrument type": int,
    "Minimum lot size": int,
    "Tick size": float,
    "ISIN": str,
    "Trading Session": str,
    "Last update date": str,
    "Expiry date": str,
    "Symbol ticker": str,
    "Exchange": int,
    "Segment": int,
    "Scrip code": int,
    "Underlying symbol": str,
    "Underlying scrip code": pd.Int64Dtype(),
    "Strike price": float,
    "Option type": str,
    "Underlying FyToken": str,
    "Reserved column1": str,
    "Reserved column2": str,
    "Reserved column3": str,
}

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


def download_csv_aliceblue_data(output_path):
    """Download AliceBlue master contract CSV files using shared connection pooling."""

    logger.info("Downloading Master Contract CSV Files")
    # URLs of the CSV files to be downloaded
    csv_urls = {
        "CDS": "https://v2api.aliceblueonline.com/restpy/static/contract_master/V2/CDS.csv",
        "NFO": "https://v2api.aliceblueonline.com/restpy/static/contract_master/V2/NFO.csv",
        "NSE": "https://v2api.aliceblueonline.com/restpy/static/contract_master/V2/NSE.csv",
        "BSE": "https://v2api.aliceblueonline.com/restpy/static/contract_master/V2/BSE.csv",
        "BFO": "https://v2api.aliceblueonline.com/restpy/static/contract_master/V2/BFO.csv",
        "BCD": "https://v2api.aliceblueonline.com/restpy/static/contract_master/V2/BCD.csv",
        "MCX": "https://v2api.aliceblueonline.com/restpy/static/contract_master/V2/MCX.csv",
        "INDICES": "https://v2api.aliceblueonline.com/restpy/static/contract_master/V2/INDICES.csv",
    }

    # Get the shared httpx client with connection pooling
    client = get_httpx_client()

    # Create a list to hold the paths of the downloaded files
    downloaded_files = []

    # Iterate through the URLs and download the CSV files
    for key, url in csv_urls.items():
        file_path = f"{output_path}/{key}.csv"
        try:
            # Prefer the zipped contract master. Measured against the live
            # endpoints, the whole set is 19.4MB as CSV and 2.8MB zipped - an
            # 85% saving, and NFO alone drops from 9.5MB to 1.2MB. Same V2 data,
            # just compressed (12-contract-master.md lists both).
            if _download_zipped_master(client, key, file_path):
                downloaded_files.append(file_path)
                continue

            # Fall back to the plain CSV. The zip is an optimisation, not a
            # dependency: if AliceBlue stops publishing one, or a single
            # exchange's archive is malformed, the download must still work.
            response = client.get(url, timeout=60)
            response.raise_for_status()  # Raise exception for error status codes

            # Write the content to the file with a larger chunk size for better performance
            with open(file_path, "wb") as file:
                file.write(response.content)

            downloaded_files.append(file_path)
            logger.info(f"Successfully downloaded {key} master contract (csv)")

        except Exception as e:
            logger.error(f"Failed to download {key} from {url}. Error: {e}")


ZIP_BASE_URL = "https://v2api.aliceblueonline.com/restpy/static/contract_master/V2/"


def _download_zipped_master(client, key, file_path) -> bool:
    """Fetch <key>_contract.zip and write the CSV inside it to file_path.

    Returns False on any problem so the caller can fall back to the plain CSV -
    a smaller download is not worth a failed master-contract refresh, which
    would leave every symbol lookup broken.

    Everything is streamed through BytesIO and closed via context managers: this
    runs inside the long-lived worker, so a leaked archive handle would sit
    there until restart.
    """
    url = f"{ZIP_BASE_URL}{key}_contract.zip"
    try:
        response = client.get(url, timeout=60)
        if response.status_code != 200:
            logger.debug(f"No zipped master for {key} (HTTP {response.status_code})")
            return False

        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            members = archive.namelist()
            if not members:
                logger.warning(f"Zipped master for {key} is empty")
                return False

            member_name = members[0]
            if member_name.lower().endswith(".csv"):
                with archive.open(member_name) as member, open(file_path, "wb") as out:
                    shutil.copyfileobj(member, out)
            elif member_name.lower().endswith(".json"):
                # The archives hold JSON, not CSV - e.g. NSE_contract.zip carries
                # NSE_contract_060826.json - despite sitting beside the .csv
                # endpoints. Same data and the same field names, just serialized
                # as {"NSE": [ {...}, ... ]}, so it converts to the CSV the
                # parsers below already expect. Verified field-for-field against
                # NSE.csv: Exch, Exchange Segment, Group Name, Symbol, Token,
                # Instrument Type, Instrument Name, Formatted Ins Name,
                # Trading Symbol, Lot Size, Tick Size.
                with archive.open(member_name) as member:
                    payload = json.load(member)
                records = payload if isinstance(payload, list) else next(
                    (v for v in payload.values() if isinstance(v, list)), None
                )
                if not records:
                    logger.warning(f"Zipped master for {key} has no records in {member_name}")
                    return False
                pd.DataFrame(records).to_csv(file_path, index=False)
            else:
                logger.warning(f"Zipped master for {key} has an unexpected member: {member_name}")
                return False

        logger.info(
            f"Successfully downloaded {key} master contract "
            f"(zip, {len(response.content) / 1e6:.1f}MB compressed)"
        )
        return True

    except zipfile.BadZipFile:
        logger.warning(f"Zipped master for {key} is not a valid archive; falling back to CSV")
        return False
    except Exception as exc:
        logger.warning(f"Zipped master for {key} failed ({exc}); falling back to CSV")
        return False


def _clean_tokens(series):
    """Coerce a Token column to plain integer strings.

    pd.read_csv infers Token as float64 whenever the column carries a NaN, so
    the values arrive as 2885.0 and land in the VARCHAR token column as the
    string "2885.0". That affected 165,576 of 165,690 rows - every tradable
    exchange; only the index feeds, which load through a different path, were
    clean.

    Nothing crashed because three call sites defend with
    str(int(float(token))) - transform_data for order placement, the streaming
    adapter, and _normalize_token in api/data.py. Those stay as belt and braces,
    but they are now redundant, and any new code path that used the token
    without that dance would have sent AliceBlue "2885.0".

    Rows whose token will not parse become an empty string rather than -1: a
    sentinel integer would look like a real instrument to downstream lookups.
    """
    numeric = pd.to_numeric(series, errors="coerce")
    return numeric.map(lambda v: "" if pd.isna(v) else str(int(v)))


def reformat_symbol_detail(s):
    parts = s.split()  # Split the string into parts
    # Reorder and format the parts to match the desired output
    # Assuming the format is consistent and always "Name DD Mon YY FUT"
    return f"{parts[0]}{parts[3]}{parts[2].upper()}{parts[1]}{parts[4]}"


def process_aliceblue_nse_csv(path):
    """
    Processes the aliceblue CSV file to fit the existing database schema and performs exchange name mapping.
    """
    logger.info("Processing aliceblue NSE CSV Data")
    file_path = f"{path}/NSE.csv"

    df = pd.read_csv(file_path)

    filter_df = df[df["Group Name"].isin(["EQ", "BE"])]

    token_df = pd.DataFrame()

    token_df["symbol"] = filter_df["Symbol"]
    token_df["brsymbol"] = filter_df["Trading Symbol"]
    token_df["name"] = filter_df["Instrument Name"]
    token_df["exchange"] = filter_df["Exch"]
    token_df["brexchange"] = filter_df["Exch"]
    token_df["token"] = _clean_tokens(filter_df["Token"])
    token_df["expiry"] = ""
    token_df["strike"] = 1.0
    token_df["lotsize"] = filter_df["Lot Size"]
    token_df["instrumenttype"] = "EQ"
    token_df["tick_size"] = filter_df["Tick Size"]

    # Filter out rows with NaN symbol values (which would violate DB NOT NULL constraints)
    token_df = token_df.dropna(subset=["symbol"])

    return token_df


def process_aliceblue_bse_csv(path):
    """
    Processes the aliceblue CSV file to fit the existing database schema and performs exchange name mapping.
    """
    logger.info("Processing aliceblue BSE CSV Data")
    file_path = f"{path}/BSE.csv"

    df = pd.read_csv(file_path)

    filtered_df = df[df["Trading Symbol"].notna() & (df["Trading Symbol"] != "")]

    token_df = pd.DataFrame()

    token_df["symbol"] = filtered_df["Symbol"]
    token_df["brsymbol"] = filtered_df["Trading Symbol"]
    token_df["name"] = filtered_df["Instrument Name"]
    token_df["exchange"] = filtered_df["Exch"]
    token_df["brexchange"] = filtered_df["Exch"]
    token_df["token"] = _clean_tokens(filtered_df["Token"])
    token_df["expiry"] = ""
    token_df["strike"] = 1.0
    token_df["lotsize"] = filtered_df["Lot Size"]
    token_df["instrumenttype"] = "EQ"
    token_df["tick_size"] = filtered_df["Tick Size"]

    # Filter out rows with NaN symbol values (which would violate DB NOT NULL constraints)
    token_df = token_df.dropna(subset=["symbol"])

    return token_df


def process_aliceblue_nfo_csv(path):
    """
    Processes the AliceBlue NFO CSV file to fit the existing database schema and performs exchange name mapping.
    """
    logger.info("Processing AliceBlue NFO CSV Data")
    file_path = f"{path}/NFO.csv"

    df = pd.read_csv(file_path)

    # Convert 'Expiry Date' column to datetime format with error handling
    df["Expiry Date"] = pd.to_datetime(
        df["Expiry Date"], errors="coerce"
    )  # 'coerce' will set invalid dates to NaT

    # Define the function to reformat symbol details
    def reformat_symbol_detail(row):
        if row["Strike Price"].is_integer():
            Strike_price = int(row["Strike Price"])
        else:
            Strike_price = float(row["Strike Price"])

        # Check if the date is NaT (Not a Time) before formatting
        if pd.notna(row["Expiry Date"]):
            date_str = row["Expiry Date"].strftime("%d%b%y").upper()
        else:
            date_str = "NOEXP"  # Use a placeholder for missing dates

        return f"{row['Symbol']}{date_str}{Strike_price}"

    # Futures rows in the NFO master carry Instrument Type 'FUTSTK'/'FUTIDX'
    # with a NaN Option Type. Map them to 'XX' so the futures symbol logic
    # below picks them up (mirrors the BFO/MCX processors).
    df.loc[df["Instrument Type"] == "FUTSTK", "Option Type"] = "XX"
    df.loc[df["Instrument Type"] == "FUTIDX", "Option Type"] = "XX"

    # Apply the function to rows where 'Option Type' is 'XX'
    df.loc[df["Option Type"] == "XX", "symbol"] = df["Trading Symbol"] + "UT"

    # Apply the function to rows where 'Option Type' is 'CE'
    df.loc[df["Option Type"] == "CE", "symbol"] = df.apply(
        lambda row: reformat_symbol_detail(row) + "CE", axis=1
    )

    # Apply the function to rows where 'Option Type' is 'PE'
    df.loc[df["Option Type"] == "PE", "symbol"] = df.apply(
        lambda row: reformat_symbol_detail(row) + "PE", axis=1
    )

    # Create token_df with the relevant columns
    token_df = df[["symbol"]].copy()

    token_df["brsymbol"] = df["Trading Symbol"].values
    token_df["name"] = df["Instrument Name"].values
    token_df["exchange"] = df["Exch"].values
    token_df["brexchange"] = df["Exch"].values
    token_df["token"] = _clean_tokens(df["Token"])

    # Convert 'Expiry Date' to desired format with NaT handling
    token_df["expiry"] = df["Expiry Date"].apply(
        lambda x: x.strftime("%d-%b-%y").upper() if pd.notna(x) else None
    )
    token_df["strike"] = df["Strike Price"].values
    token_df["lotsize"] = df["Lot Size"].values
    token_df["instrumenttype"] = df["Option Type"].map({"XX": "FUT", "CE": "CE", "PE": "PE"})
    token_df["tick_size"] = df["Tick Size"].values

    # Filter out rows with NaN symbol values (which would violate DB NOT NULL constraints)
    token_df = token_df.dropna(subset=["symbol"])

    return token_df


def process_aliceblue_cds_csv(path):
    """
    Processes the AliceBlue CSV file to fit the existing database schema and performs exchange name mapping.
    """
    logger.info("Processing Aliceblue CDS CSV Data")
    file_path = f"{path}/CDS.csv"

    df = pd.read_csv(file_path)

    # Convert 'Expiry Date' column to datetime format
    df["Expiry Date"] = pd.to_datetime(df["Expiry Date"])

    # Define the function to reformat symbol details
    def reformat_symbol_detail(row):
        if row["Strike Price"].is_integer():
            Strike_price = int(row["Strike Price"])
        else:
            Strike_price = float(row["Strike Price"])

        # Check if the date is NaT (Not a Time) before formatting
        if pd.notna(row["Expiry Date"]):
            date_str = row["Expiry Date"].strftime("%d%b%y").upper()
        else:
            date_str = "NOEXP"  # Use a placeholder for missing dates

        return f"{row['Symbol']}{date_str}{Strike_price}"

    # Currency futures carry Instrument Type 'FUTCUR' with a NaN Option Type.
    # Map them to 'XX' so the futures symbol logic below picks them up.
    df.loc[df["Instrument Type"] == "FUTCUR", "Option Type"] = "XX"

    # Apply the function to rows where 'Option Type' is 'XX'
    df.loc[df["Option Type"] == "XX", "symbol"] = df["Trading Symbol"] + "UT"

    # Apply the function to rows where 'Option Type' is 'CE'
    df.loc[df["Option Type"] == "CE", "symbol"] = df.apply(
        lambda row: reformat_symbol_detail(row) + "CE", axis=1
    )

    # Apply the function to rows where 'Option Type' is 'PE'
    df.loc[df["Option Type"] == "PE", "symbol"] = df.apply(
        lambda row: reformat_symbol_detail(row) + "PE", axis=1
    )

    # Create token_df with the relevant columns
    token_df = df[["symbol"]].copy()

    token_df["brsymbol"] = df["Trading Symbol"].values
    token_df["name"] = df["Instrument Name"].values
    token_df["exchange"] = df["Exch"].values
    token_df["brexchange"] = df["Exch"].values
    token_df["token"] = _clean_tokens(df["Token"])

    # Convert 'Expiry Date' to desired format with NaT handling
    token_df["expiry"] = df["Expiry Date"].apply(
        lambda x: x.strftime("%d-%b-%y").upper() if pd.notna(x) else None
    )
    token_df["strike"] = df["Strike Price"].values
    token_df["lotsize"] = df["Lot Size"].values
    token_df["instrumenttype"] = df["Option Type"].map({"XX": "FUT", "CE": "CE", "PE": "PE"})
    token_df["tick_size"] = df["Tick Size"].values

    # Filter out rows with NaN symbol values (which would violate DB NOT NULL constraints)
    token_df = token_df.dropna(subset=["symbol"])

    return token_df


def process_aliceblue_bfo_csv(path):
    """
    Processes the Aliceblue CSV file to fit the existing database schema and performs exchange name mapping.
    """
    logger.info("Processing Aliceblue BFO CSV Data")
    file_path = f"{path}/BFO.csv"

    df = pd.read_csv(file_path)

    # Convert 'Expiry Date' column to datetime format
    df["Expiry Date"] = pd.to_datetime(df["Expiry Date"])

    df.loc[df["Instrument Type"] == "SF", "Option Type"] = "XX"
    df.loc[df["Instrument Type"] == "IF", "Option Type"] = "XX"

    # Apply the function to rows where 'Option Type' is 'XX'
    df.loc[df["Option Type"] == "XX", "symbol"] = df["Formatted Ins Name"].str.replace(" ", "")

    # Apply the function to rows where 'Option Type' is 'CE'
    df.loc[df["Option Type"] == "CE", "symbol"] = df["Formatted Ins Name"].str.replace(" ", "")

    # Apply the function to rows where 'Option Type' is 'PE'
    df.loc[df["Option Type"] == "PE", "symbol"] = df["Formatted Ins Name"].str.replace(" ", "")

    # Create token_df with the relevant columns
    token_df = df[["symbol"]].copy()

    token_df["brsymbol"] = df["Trading Symbol"].values
    token_df["name"] = df["Instrument Name"].values
    token_df["exchange"] = df["Exch"].values
    token_df["brexchange"] = df["Exch"].values
    token_df["token"] = _clean_tokens(df["Token"])

    # Convert 'Expiry Date' to desired format with NaT handling
    token_df["expiry"] = df["Expiry Date"].apply(
        lambda x: x.strftime("%d-%b-%y").upper() if pd.notna(x) else None
    )
    token_df["strike"] = df["Strike Price"].values
    token_df["lotsize"] = df["Lot Size"].values
    token_df["instrumenttype"] = df["Option Type"].map({"XX": "FUT", "CE": "CE", "PE": "PE"})
    token_df["tick_size"] = df["Tick Size"].values

    # Drop rows where 'symbol' is NaN
    token_df_cleaned = token_df.dropna(subset=["symbol"])

    # Filter out rows with NaN symbol values (which would violate DB NOT NULL constraints)
    token_df = token_df.dropna(subset=["symbol"])

    return token_df_cleaned


def process_aliceblue_mcx_csv(path):
    """
    Processes the Aliceblue CSV file to fit the existing database schema and performs exchange name mapping.
    """
    logger.info("Processing Aliceblue MCX CSV Data")
    file_path = f"{path}/MCX.csv"

    df = pd.read_csv(file_path)

    # Drop rows where the 'Exch Seg' column has the value 'mcx_idx'
    df = df[df["Exchange Segment"] != "mcx_idx"]

    df["Expiry Date"] = pd.to_datetime(df["Expiry Date"])

    # Define the function to reformat symbol details
    def reformat_symbol_detail(row):
        if row["Strike Price"].is_integer():
            Strike_price = int(row["Strike Price"])
        else:
            Strike_price = float(row["Strike Price"])

        # Check if the date is NaT (Not a Time) before formatting
        if pd.notna(row["Expiry Date"]):
            date_str = row["Expiry Date"].strftime("%d%b%y").upper()
        else:
            date_str = "NOEXP"  # Use a placeholder for missing dates

        return f"{row['Symbol']}{date_str}{Strike_price}"

    df.loc[df["Instrument Type"] == "FUTCOM", "Option Type"] = "XX"
    df.loc[df["Instrument Type"] == "FUTIDX", "Option Type"] = "XX"

    # Apply the function to rows where 'Option Type' is 'XX'
    df.loc[df["Option Type"] == "XX", "symbol"] = df["Trading Symbol"] + "FUT"

    # Apply the function to rows where 'Option Type' is 'CE'
    df.loc[df["Option Type"] == "CE", "symbol"] = df.apply(
        lambda row: reformat_symbol_detail(row) + "CE", axis=1
    )

    # Apply the function to rows where 'Option Type' is 'PE'
    df.loc[df["Option Type"] == "PE", "symbol"] = df.apply(
        lambda row: reformat_symbol_detail(row) + "PE", axis=1
    )

    # Create token_df with the relevant columns
    token_df = df[["symbol"]].copy()

    token_df["brsymbol"] = df["Trading Symbol"].values
    token_df["name"] = df["Instrument Name"].values
    token_df["exchange"] = df["Exch"].values
    token_df["brexchange"] = df["Exch"].values
    token_df["token"] = _clean_tokens(df["Token"])

    # Convert 'Expiry Date' to desired format with NaT handling
    token_df["expiry"] = df["Expiry Date"].apply(
        lambda x: x.strftime("%d-%b-%y").upper() if pd.notna(x) else None
    )
    token_df["strike"] = df["Strike Price"].values
    token_df["lotsize"] = df["Lot Size"].values
    token_df["instrumenttype"] = df["Option Type"].map({"XX": "FUT", "CE": "CE", "PE": "PE"})
    token_df["tick_size"] = df["Tick Size"].values

    # Drop rows where 'symbol' is NaN
    # token_df_cleaned = token_df.dropna(subset=['symbol'])

    # Filter out rows with NaN symbol values (which would violate DB NOT NULL constraints)
    token_df = token_df.dropna(subset=["symbol"])

    return token_df


def process_aliceblue_bcd_csv(path):
    """
    Processes the Aliceblue CSV file to fit the existing database schema and performs exchange name mapping.
    """
    logger.info("Processing Aliceblue BCD CSV Data")
    file_path = f"{path}/BCD.csv"

    df = pd.read_csv(file_path)

    # Convert 'Expiry Date' column to datetime format
    df["Expiry Date"] = pd.to_datetime(df["Expiry Date"])

    # Define the function to reformat symbol details
    def reformat_symbol_detail(row):
        if row["Strike Price"].is_integer():
            Strike_price = int(row["Strike Price"])
        else:
            Strike_price = float(row["Strike Price"])

        # Check if the date is NaT (Not a Time) before formatting
        if pd.notna(row["Expiry Date"]):
            date_str = row["Expiry Date"].strftime("%d%b%y").upper()
        else:
            date_str = "NOEXP"  # Use a placeholder for missing dates

        return f"{row['Symbol']}{date_str}{Strike_price}"

    df.loc[df["Instrument Type"] == "FUTCUR", "Option Type"] = "XX"
    df.loc[df["Instrument Type"] == "FUTCUR", "Strike Price"] = 1

    # Apply the function to rows where 'Option Type' is 'XX'
    df.loc[df["Option Type"] == "XX", "symbol"] = df["Trading Symbol"] + "UT"

    # Apply the function to rows where 'Option Type' is 'CE'
    df.loc[df["Option Type"] == "CE", "symbol"] = df.apply(
        lambda row: reformat_symbol_detail(row) + "CE", axis=1
    )

    # Apply the function to rows where 'Option Type' is 'PE'
    df.loc[df["Option Type"] == "PE", "symbol"] = df.apply(
        lambda row: reformat_symbol_detail(row) + "PE", axis=1
    )

    # Create token_df with the relevant columns
    token_df = df[["symbol"]].copy()

    token_df["brsymbol"] = df["Trading Symbol"].values
    token_df["name"] = df["Instrument Name"].values
    token_df["exchange"] = df["Exch"].values
    token_df["brexchange"] = df["Exch"].values
    token_df["token"] = _clean_tokens(df["Token"])

    # Convert 'Expiry Date' to desired format with NaT handling
    token_df["expiry"] = df["Expiry Date"].apply(
        lambda x: x.strftime("%d-%b-%y").upper() if pd.notna(x) else None
    )
    token_df["strike"] = df["Strike Price"].values
    token_df["lotsize"] = df["Lot Size"].values
    token_df["instrumenttype"] = df["Option Type"].map({"XX": "FUT", "CE": "CE", "PE": "PE"})
    token_df["tick_size"] = df["Tick Size"].values

    # Drop rows where 'symbol' is NaN
    # token_df_cleaned = token_df.dropna(subset=['symbol'])

    # Filter out rows with NaN symbol values (which would violate DB NOT NULL constraints)
    token_df = token_df.dropna(subset=["symbol"])

    return token_df


def process_aliceblue_indices_csv(path):
    """
    Processes the Aliceblue CSV file to fit the existing database schema and performs exchange name mapping.
    """
    logger.info("Processing Aliceblue INDICES CSV Data")
    file_path = f"{path}/INDICES.csv"

    df = pd.read_csv(file_path)

    # Create token_df with the relevant columns
    token_df = df[["symbol"]].copy()

    token_df["brsymbol"] = df["symbol"].values
    token_df["name"] = df["symbol"].values
    token_df["exchange"] = df["exch"].values
    token_df["brexchange"] = df["exch"].values
    token_df["token"] = _clean_tokens(df["token"])

    # Convert 'Expiry Date' to desired format
    token_df["expiry"] = ""
    token_df["strike"] = 1.0
    token_df["lotsize"] = 1
    token_df["instrumenttype"] = df["exch"].map(
        {"NSE": "NSE_INDEX", "BSE": "BSE_INDEX", "MCX": "MCX_INDEX"}
    )
    token_df["exchange"] = df["exch"].map(
        {"NSE": "NSE_INDEX", "BSE": "BSE_INDEX", "MCX": "MCX_INDEX"}
    )
    token_df["tick_size"] = 0.01
    # Step 1: Remove all spaces from symbol names (handles most NSE index mappings automatically)
    token_df["symbol"] = token_df["symbol"].str.replace(" ", "", regex=False)

    # Step 2: Apply only the special mappings that involve actual renaming (not just space removal)
    token_df["symbol"] = token_df["symbol"].replace(
        {
            # NSE Index Symbols requiring renaming (not just space removal)
            "NIFTY50": "NIFTY",
            "NIFTYNEXT50": "NIFTYNXT50",
            "NIFTYFINSERVICE": "FINNIFTY",
            "NIFTYBANK": "BANKNIFTY",
            "NIFTYMIDCAPSELECT": "MIDCPNIFTY",
            # BSE Index Symbols (AliceBlue -> OpenAlgo)
            "SNSX50": "SENSEX50",
            "SNXT50": "BSESENSEXNEXT50",
            "MID150": "BSE150MIDCAPINDEX",
            "LMI250": "BSE250LARGEMIDCAPINDEX",
            "MSL400": "BSE400MIDSMALLCAPINDEX",
            "AUTO": "BSEAUTO",
            "BSE CG": "BSECAPITALGOODS",
            "CARBON": "BSECARBONEX",
            "BSE CD": "BSECONSUMERDURABLES",
            "CPSE": "BSECPSE",
            "ENERGY": "BSEENERGY",
            "BSEFMC": "BSEFASTMOVINGCONSUMERGOODS",
            "FIN": "BSEFINANCIALSERVICES",
            "GREENX": "BSEGREENEX",
            "BSE HC": "BSEHEALTHCARE",
            "INFRA": "BSEINDIAINFRASTRUCTUREINDEX",
            "INDSTR": "BSEINDUSTRIALS",
            "BSE IT": "BSEINFORMATIONTECHNOLOGY",
            "LRGCAP": "BSELARGECAP",
            "METAL": "BSEMETAL",
            "MIDCAP": "BSEMIDCAP",
            "MIDSEL": "BSEMIDCAPSELECTINDEX",
            "OILGAS": "BSEOIL&GAS",
            "POWER": "BSEPOWER",
            "REALTY": "BSEREALTY",
            "SMLCAP": "BSESMALLCAP",
            "SMLSEL": "BSESMALLCAPSELECTINDEX",
            "SMEIPO": "BSESMEIPO",
            "TECK": "BSETECK",
            "TELCOM": "BSETELECOM",
        }
    )

    # Filter out rows with NaN symbol values (which would violate DB NOT NULL constraints)
    token_df = token_df.dropna(subset=["symbol"])

    return token_df


def delete_aliceblue_temp_data(output_path):
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
        download_csv_aliceblue_data(output_path)
        delete_symtoken_table()
        token_df = process_aliceblue_nse_csv(output_path)
        copy_from_dataframe(token_df)
        token_df = process_aliceblue_bse_csv(output_path)
        copy_from_dataframe(token_df)
        token_df = process_aliceblue_nfo_csv(output_path)
        copy_from_dataframe(token_df)
        token_df = process_aliceblue_cds_csv(output_path)
        copy_from_dataframe(token_df)
        token_df = process_aliceblue_mcx_csv(output_path)
        copy_from_dataframe(token_df)
        token_df = process_aliceblue_bfo_csv(output_path)
        copy_from_dataframe(token_df)
        token_df = process_aliceblue_bcd_csv(output_path)
        copy_from_dataframe(token_df)
        token_df = process_aliceblue_indices_csv(output_path)
        copy_from_dataframe(token_df)
        delete_aliceblue_temp_data(output_path)

        return socketio.emit(
            "master_contract_download", {"status": "success", "message": "Successfully Downloaded"}
        )

    except Exception as e:
        logger.info(f"{e}")
        return socketio.emit("master_contract_download", {"status": "error", "message": str(e)})


def search_symbols(symbol, exchange):
    return SymToken.query.filter(
        SymToken.symbol.like(f"%{symbol}%"), SymToken.exchange == exchange
    ).all()
