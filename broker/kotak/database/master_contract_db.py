# database/master_contract_db.py

import gzip
import io
import json
import os
import shutil

import httpx
import numpy as np
import pandas as pd
from sqlalchemy import Column, Float, Index, Integer, Sequence, String, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker

from database.auth_db import get_auth_token
from database.user_db import find_user_by_username
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


def download_csv_kotak_data(output_path):
    logger.info("Downloading Master Contract CSV Files")

    # URLs of the CSV files to be downloaded
    csv_urls = get_kotak_master_filepaths()
    logger.info(f"Master contract URLs: {csv_urls}")

    if not csv_urls:
        logger.error("No master contract URLs found - scripmaster API failed")
        raise Exception("Scripmaster API failed - unable to get master contract URLs")

    # Get the shared httpx client with connection pooling
    client = get_httpx_client()

    # Create a list to hold the paths of the downloaded files
    downloaded_files = []

    # Iterate through the URLs and download the CSV files
    for key, url in csv_urls.items():
        try:
            logger.info(f"Downloading {key} from {url}")
            # Send GET request using httpx
            response = client.get(url, timeout=30)
            # Check if the request was successful
            if response.status_code == 200:
                # Construct the full output path for the file
                file_path = f"{output_path}/{key}.csv"
                # Write the content to the file
                with open(file_path, "wb") as file:
                    file.write(response.content)
                downloaded_files.append(file_path)
                logger.info(f"Successfully downloaded {key} ({len(response.content)} bytes)")
            else:
                logger.error(
                    f"Failed to download {key} from {url}. Status code: {response.status_code}"
                )
        except httpx.HTTPError as e:
            logger.error(f"HTTP error downloading {key}: {e}")
        except Exception as e:
            logger.error(f"Error downloading {key}: {e}")

    if not downloaded_files:
        raise Exception("No master contract files were downloaded successfully")

    logger.info(f"Downloaded {len(downloaded_files)} files successfully")
    return downloaded_files


def process_kotak_nse_csv(path):
    """
    Processes the kotak CSV file to fit the existing database schema and performs exchange name mapping.
    """
    logger.info("Processing kotak NSE CSV Data")
    file_path = f"{path}/NSE_CM.csv"

    df = pd.read_csv(file_path)

    filtereddataframe = pd.DataFrame()

    filtereddataframe["token"] = df["pSymbol"]
    filtereddataframe["name"] = df["pDesc"]
    filtereddataframe["expiry"] = df["pExpiryDate"]
    filtereddataframe["strike"] = df["dStrikePrice;"]
    filtereddataframe["lotsize"] = df["lLotSize"]
    filtereddataframe["tick_size"] = df["dTickSize "]
    filtereddataframe["brsymbol"] = df["pTrdSymbol"]
    filtereddataframe["symbol"] = df["pSymbolName"]

    # Filtering the DataFrame based on 'Exchange Instrument type' and assigning values to 'exchange'

    df.loc[df["pGroup"].isin(["EQ", "BE"]), "instrumenttype"] = "EQ"
    df.loc[df["pISIN"].isna(), "exchange"] = "NSE_INDEX"
    df.loc[df["pGroup"].isin(["EQ", "BE"]), "exchange"] = "NSE"
    df.loc[df["pISIN"].isna(), "instrumenttype"] = "INDEX"
    df.loc[df["pISIN"].isna(), "pGroup"] = ""

    filtereddataframe["instrumenttype"] = df["instrumenttype"]
    filtereddataframe["exchange"] = df["exchange"]
    filtereddataframe["pGroup"] = df["pGroup"]

    # Keeping only rows where 'exchange' column has been filled ('NSE' or 'NSE_INDEX')
    df_filtered = filtereddataframe[filtereddataframe["pGroup"].isin(["EQ", "BE", ""])].copy()

    df_filtered["brexchange"] = "NSE"

    # List of columns to remove
    columns_to_remove = ["pGroup"]

    # Removing the specified columns
    token_df = df_filtered.drop(columns=columns_to_remove)

    return token_df


def process_kotak_bse_csv(path):
    """
    Processes the kotak CSV file to fit the existing database schema and performs exchange name mapping.
    """
    logger.info("Processing kotak BSE CSV Data")
    file_path = f"{path}/BSE_CM.csv"

    df = pd.read_csv(file_path)
    df.columns = df.columns.str.replace(" ", "")
    df.columns = df.columns.str.replace(";", "")
    df.dropna(subset=["pSymbolName"], inplace=True)

    filtereddataframe = pd.DataFrame()

    filtereddataframe["token"] = df["pSymbol"]
    filtereddataframe["name"] = df["pDesc"]
    filtereddataframe["expiry"] = df["pExpiryDate"]
    filtereddataframe["strike"] = df["dStrikePrice"]
    filtereddataframe["lotsize"] = df["lLotSize"]
    filtereddataframe["tick_size"] = df["dTickSize"]
    filtereddataframe["brsymbol"] = df["pTrdSymbol"]
    filtereddataframe["symbol"] = df["pSymbolName"]

    # Filtering the DataFrame based on 'Exchange Instrument type' and assigning values to 'exchange'

    df["instrumenttype"] = "EQ"

    df["exchange"] = "BSE"
    df.loc[df["pISIN"].isna(), "exchange"] = "BSE_INDEX"
    df.loc[df["pISIN"].isna(), "instrumenttype"] = "INDEX"
    df.loc[df["pISIN"].isna(), "pGroup"] = ""

    filtereddataframe["instrumenttype"] = df["instrumenttype"]
    filtereddataframe["exchange"] = df["exchange"]
    filtereddataframe["pGroup"] = df["pGroup"]

    # Keeping only rows where 'exchange' column has been filled ('NSE' or 'NSE_INDEX')
    df_filtered = filtereddataframe.copy()

    df_filtered["brexchange"] = "BSE"

    # List of columns to remove
    columns_to_remove = ["pGroup"]

    # Removing the specified columns
    token_df = df_filtered.drop(columns=columns_to_remove)

    return token_df


def combine_details(row):
    base = f"{row['name']}{row['expiry'].replace('-', '')}"
    if row["instrumenttype"] == "FUT":
        return f"{base}FUT"
    elif row["instrumenttype"] in ["CE", "PE"]:
        row["strike"] = int(row["strike"]) if row["strike"].is_integer() else row["strike"]
        return f"{base}{row['strike']}{row['instrumenttype']}"
    else:
        return base


def process_kotak_nfo_csv(path):
    """
    Processes the kotak CSV file to fit the existing database schema and performs exchange name mapping.
    """
    logger.info("Processing kotak NFO CSV Data")
    file_path = f"{path}/NSE_FO.csv"

    df = pd.read_csv(file_path, dtype={"pOptionType": "str"})
    df.columns = df.columns.str.replace(" ", "")
    df.columns = df.columns.str.replace(";", "")
    tokensymbols = pd.DataFrame()
    tokensymbols["token"] = df["pSymbol"]
    tokensymbols["name"] = df["pSymbolName"]
    df["lExpiryDate"] = df["lExpiryDate"] + 315513000

    # Convert 'Expiry date' from Unix timestamp to datetime
    tokensymbols["expiry"] = pd.to_datetime(df["lExpiryDate"], unit="s")

    # Format the datetime object to the desired format '15-APR-24'
    tokensymbols["expiry"] = tokensymbols["expiry"].dt.strftime("%d-%b-%y").str.upper()

    tokensymbols["strike"] = df["dStrikePrice"] / 100
    tokensymbols["strike"] = tokensymbols["strike"].apply(lambda x: int(x) if x.is_integer() else x)

    tokensymbols["lotsize"] = df["lLotSize"]
    tokensymbols["tick_size"] = df["dTickSize"]
    tokensymbols["brsymbol"] = df["pTrdSymbol"]
    tokensymbols["brexchange"] = df["pExchSeg"]
    tokensymbols["exchange"] = "NFO"

    # df1['instrumenttype'] = df['pOptionType'].apply(lambda x: x.replace('XX', 'FUT'))
    tokensymbols["instrumenttype"] = df["pOptionType"].str.replace("XX", "FUT")

    # pSymbolName  df['expiry']
    tokensymbols["symbol"] = tokensymbols.apply(combine_details, axis=1)
    return tokensymbols


def get_kotak_master_filepaths():
    """
    Get master contract file paths using Neo API v2
    Based on PowerShell test: scripmaster API works with access token and correct baseUrl
    """
    login_username = find_user_by_username().username
    auth_token = get_auth_token(login_username)

    # Updated for Neo API v2: trading_token:::trading_sid:::base_url:::access_token
    trading_token, trading_sid, base_url, access_token = auth_token.split(":::")

    # Use the baseUrl from auth token first, then try alternatives
    # Sometimes scripmaster API is on different servers
    base_urls_to_try = [
        base_url,  # From MPIN validation response
        "https://cis.kotaksecurities.com",  # Alternative server
        "https://neo-gw.kotaksecurities.com",  # Another alternative
    ]

    # Get the shared httpx client with connection pooling
    client = get_httpx_client()

    for base_url_attempt in base_urls_to_try:
        try:
            logger.info(f"Trying scripmaster API with baseUrl: {base_url_attempt}")

            endpoint = "/script-details/1.0/masterscrip/file-paths"

            # According to Neo API v2 docs and PowerShell test: use only Authorization header
            headers = {"Authorization": access_token, "Content-Type": "application/json"}

            # Construct full URL
            url = f"{base_url_attempt}{endpoint}"

            logger.info(f"SCRIPMASTER API - Using access_token: {access_token[:10]}...")
            logger.info(f"Making request to: {url}")

            response = client.get(url, headers=headers, timeout=30)

            logger.info(f"Response status: {response.status_code} from {base_url_attempt}")

            if response.status_code != 200:
                logger.warning(
                    f"HTTP {response.status_code} from {base_url_attempt}: {response.text}"
                )

            if response.status_code == 200:
                try:
                    data_dict = json.loads(response.text)
                    logger.debug(f"Response data: {data_dict}")

                    # Check for the expected response structure
                    if "data" in data_dict and "filesPaths" in data_dict["data"]:
                        filepaths_list = data_dict["data"]["filesPaths"]
                        file_dict = {}

                        # Process each file path
                        for url in filepaths_list:
                            # Extract file name and create mapping
                            filename = url.split("/")[-1]

                            # Map to our expected format
                            if "nse_cm" in filename.lower():
                                file_dict["NSE_CM"] = url
                            elif "bse_cm" in filename.lower():
                                file_dict["BSE_CM"] = url
                            elif "nse_fo" in filename.lower():
                                file_dict["NSE_FO"] = url
                            elif "bse_fo" in filename.lower():
                                file_dict["BSE_FO"] = url
                            elif "cde_fo" in filename.lower():
                                file_dict["CDE_FO"] = url
                            elif "mcx_fo" in filename.lower():
                                file_dict["MCX_FO"] = url
                            elif "nse_com" in filename.lower():
                                file_dict["NSE_COM"] = url

                        logger.info(
                            f"✅ Successfully retrieved {len(file_dict)} master contract files from {base_url_attempt}"
                        )
                        logger.info(f"Available files: {list(file_dict.keys())}")
                        return file_dict
                    else:
                        logger.warning(
                            f"Unexpected response structure from {base_url_attempt}: {data_dict}"
                        )

                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse JSON from {base_url_attempt}: {e}")
                    logger.debug(f"Raw response: {response.text}")

        except httpx.HTTPError as e:
            logger.error(f"HTTP error with {base_url_attempt}: {e}")
            continue
        except Exception as e:
            logger.error(f"Error with {base_url_attempt}: {e}")
            continue

    logger.error("All baseUrl attempts failed for scripmaster API")

    # Fallback: Use direct URLs from PowerShell test results
    logger.warning("API failed, using direct URLs from PowerShell test")
    from datetime import datetime

    today = datetime.now().strftime("%Y-%m-%d")

    fallback_urls = {
        "CDE_FO": f"https://lapi.kotaksecurities.com/wso2-scripmaster/v1/prod/{today}/transformed/cde_fo.csv",
        "MCX_FO": f"https://lapi.kotaksecurities.com/wso2-scripmaster/v1/prod/{today}/transformed/mcx_fo.csv",
        "NSE_FO": f"https://lapi.kotaksecurities.com/wso2-scripmaster/v1/prod/{today}/transformed/nse_fo.csv",
        "BSE_FO": f"https://lapi.kotaksecurities.com/wso2-scripmaster/v1/prod/{today}/transformed/bse_fo.csv",
        "NSE_COM": f"https://lapi.kotaksecurities.com/wso2-scripmaster/v1/prod/{today}/transformed/nse_com.csv",
        "BSE_CM": f"https://lapi.kotaksecurities.com/wso2-scripmaster/v1/prod/{today}/transformed-v1/bse_cm-v1.csv",
        "NSE_CM": f"https://lapi.kotaksecurities.com/wso2-scripmaster/v1/prod/{today}/transformed-v1/nse_cm-v1.csv",
    }

    # Test accessibility of fallback URLs using httpx
    accessible_urls = {}
    for key, url in fallback_urls.items():
        try:
            logger.info(f"Testing direct URL: {url}")
            response = client.head(url, timeout=10, follow_redirects=True)
            if response.status_code == 200:
                accessible_urls[key] = url
                logger.info(f"✅ Direct URL accessible: {key}")
            else:
                logger.warning(f"❌ Direct URL returned {response.status_code}: {key}")
        except httpx.HTTPError as e:
            logger.warning(f"❌ Direct URL HTTP error: {key} - {e}")
        except Exception as e:
            logger.warning(f"❌ Direct URL failed: {key} - {e}")

    if accessible_urls:
        logger.info(f"Using {len(accessible_urls)} direct URLs")
        return accessible_urls

    logger.error("All scripmaster sources failed")
    return {}


def process_kotak_cds_csv(path):
    """
    Processes the kotak CSV file to fit the existing database schema and performs exchange name mapping.
    """
    logger.info("Processing kotak CDS CSV Data")
    file_path = f"{path}/CDE_FO.csv"

    df = pd.read_csv(file_path, dtype={"pOptionType": "str"})
    df.columns = df.columns.str.replace(" ", "")
    df.columns = df.columns.str.replace(";", "")
    tokensymbols = pd.DataFrame()
    tokensymbols["token"] = df["pSymbol"]
    tokensymbols["name"] = df["pSymbolName"]
    df["lExpiryDate"] = df["lExpiryDate"] + 315513000

    # Convert 'Expiry date' from Unix timestamp to datetime
    tokensymbols["expiry"] = pd.to_datetime(df["lExpiryDate"], unit="s")

    # Format the datetime object to the desired format '15-APR-24'
    tokensymbols["expiry"] = tokensymbols["expiry"].dt.strftime("%d-%b-%y").str.upper()

    tokensymbols["strike"] = df["dStrikePrice"] / 100
    tokensymbols["strike"] = tokensymbols["strike"].apply(lambda x: int(x) if x.is_integer() else x)

    tokensymbols["lotsize"] = df["lLotSize"]
    tokensymbols["tick_size"] = df["dTickSize"]
    tokensymbols["brsymbol"] = df["pTrdSymbol"]
    tokensymbols["brexchange"] = df["pExchSeg"]
    tokensymbols["exchange"] = "CDS"

    # df1['instrumenttype'] = df['pOptionType'].apply(lambda x: x.replace('XX', 'FUT'))
    tokensymbols["instrumenttype"] = df["pOptionType"].str.replace("XX", "FUT")

    # pSymbolName  df['expiry']
    tokensymbols["symbol"] = tokensymbols.apply(combine_details, axis=1)
    return tokensymbols


def process_kotak_mcx_csv(path):
    """
    Processes the kotak CSV file to fit the existing database schema and performs exchange name mapping.
    """
    logger.info("Processing kotak MCX CSV Data")
    file_path = f"{path}/MCX_FO.csv"

    df = pd.read_csv(file_path, dtype={"pOptionType": "str"})
    df.columns = df.columns.str.replace(" ", "")
    df.columns = df.columns.str.replace(";", "")
    df.dropna(subset=["pOptionType"], inplace=True)
    tokensymbols = pd.DataFrame()
    tokensymbols["token"] = df["pSymbol"]
    tokensymbols["name"] = df["pSymbolName"]
    df["lExpiryDate"] = df["lExpiryDate"]

    # Convert 'Expiry date' from Unix timestamp to datetime
    tokensymbols["expiry"] = pd.to_datetime(df["lExpiryDate"], unit="s")

    # Format the datetime object to the desired format '15-APR-24'
    tokensymbols["expiry"] = tokensymbols["expiry"].dt.strftime("%d-%b-%y").str.upper()

    tokensymbols["strike"] = df["dStrikePrice"] / 100
    tokensymbols["strike"] = tokensymbols["strike"].apply(lambda x: int(x) if x.is_integer() else x)

    tokensymbols["lotsize"] = df["lLotSize"]
    tokensymbols["tick_size"] = df["dTickSize"]
    tokensymbols["brsymbol"] = df["pTrdSymbol"]
    tokensymbols["brexchange"] = df["pExchSeg"]
    tokensymbols["exchange"] = "MCX"

    # df1['instrumenttype'] = df['pOptionType'].apply(lambda x: x.replace('XX', 'FUT'))
    tokensymbols["instrumenttype"] = df["pOptionType"].str.replace("XX", "FUT")

    # pSymbolName  df['expiry']
    tokensymbols["symbol"] = tokensymbols.apply(combine_details, axis=1)
    return tokensymbols


def process_kotak_bfo_csv(path):
    """
    Processes the kotak CSV file to fit the existing database schema and performs exchange name mapping.
    """
    logger.info("Processing kotak BFO CSV Data")
    file_path = f"{path}/BSE_FO.csv"

    df = pd.read_csv(file_path, dtype={"pOptionType": "str"})
    df.columns = df.columns.str.replace(" ", "")
    df.columns = df.columns.str.replace(";", "")
    df.dropna(subset=["pOptionType"], inplace=True)
    tokensymbols = pd.DataFrame()
    tokensymbols["token"] = df["pSymbol"]
    tokensymbols["name"] = df["pSymbolName"]
    df["lExpiryDate"] = df["lExpiryDate"]

    # Convert 'Expiry date' from Unix timestamp to datetime
    tokensymbols["expiry"] = pd.to_datetime(df["lExpiryDate"], unit="s")

    # Format the datetime object to the desired format '15-APR-24'
    tokensymbols["expiry"] = tokensymbols["expiry"].dt.strftime("%d-%b-%y").str.upper()

    tokensymbols["strike"] = df["dStrikePrice"] / 100
    tokensymbols["strike"] = tokensymbols["strike"].apply(lambda x: int(x) if x.is_integer() else x)

    tokensymbols["lotsize"] = df["lLotSize"]
    tokensymbols["tick_size"] = df["dTickSize"]
    tokensymbols["brsymbol"] = df["pTrdSymbol"]
    tokensymbols["brexchange"] = df["pExchSeg"]
    tokensymbols["exchange"] = "BFO"

    # df1['instrumenttype'] = df['pOptionType'].apply(lambda x: x.replace('XX', 'FUT'))
    tokensymbols["instrumenttype"] = df["pOptionType"].str.replace("XX", "FUT")

    # pSymbolName  df['expiry']
    tokensymbols["symbol"] = tokensymbols.apply(combine_details, axis=1)
    return tokensymbols


def delete_kotak_temp_data(output_path):
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
        # Download CSV files
        downloaded_files = download_csv_kotak_data(output_path)

        if not downloaded_files:
            raise Exception("No CSV files were downloaded successfully")

        # Clear existing data
        delete_symtoken_table()

        # Process each exchange if the file exists
        processors = [
            ("NSE_CM.csv", process_kotak_nse_csv, "NSE Cash"),
            ("NSE_FO.csv", process_kotak_nfo_csv, "NSE F&O"),
            ("BSE_CM.csv", process_kotak_bse_csv, "BSE Cash"),
            ("CDE_FO.csv", process_kotak_cds_csv, "CDS"),
            ("MCX_FO.csv", process_kotak_mcx_csv, "MCX"),
            ("BSE_FO.csv", process_kotak_bfo_csv, "BSE F&O"),
        ]

        total_records = 0
        for filename, processor_func, exchange_name in processors:
            file_path = f"{output_path}/{filename}"
            if os.path.exists(file_path):
                try:
                    logger.info(f"Processing {exchange_name} data...")
                    token_df = processor_func(output_path)
                    if not token_df.empty:
                        copy_from_dataframe(token_df)
                        total_records += len(token_df)
                        logger.info(f"Processed {len(token_df)} records for {exchange_name}")
                    else:
                        logger.warning(f"No data found in {exchange_name} file")
                except Exception as e:
                    logger.error(f"Error processing {exchange_name}: {e}")
            else:
                logger.warning(f"File not found: {filename}")

        # Clean up temporary files
        delete_kotak_temp_data(output_path)

        logger.info(f"Master contract download completed. Total records: {total_records}")

        if total_records > 0:
            return socketio.emit(
                "master_contract_download",
                {
                    "status": "success",
                    "message": f"Successfully Downloaded {total_records} records",
                },
            )
        else:
            raise Exception("No records were processed successfully")

    except Exception as e:
        logger.error(f"Master contract download failed: {str(e)}")
        return socketio.emit("master_contract_download", {"status": "error", "message": str(e)})


def search_symbols(symbol, exchange):
    return SymToken.query.filter(
        SymToken.symbol.like(f"%{symbol}%"), SymToken.exchange == exchange
    ).all()
