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
        raise Exception(
            "Scripmaster API failed - unable to get master contract URLs. "
            "Please check: 1) Authentication token is valid, 2) Network connectivity, "
            "3) Kotak API service status"
        )

    # Get the shared httpx client with connection pooling
    client = get_httpx_client()

    # Create a list to hold the paths of the downloaded files
    downloaded_files = []
    failed_downloads = []

    # Iterate through the URLs and download the CSV files
    for key, url in csv_urls.items():
        retry_count = 0
        max_retries = 3
        success = False

        while retry_count < max_retries and not success:
            try:
                logger.info(f"Downloading {key} from {url} (attempt {retry_count + 1}/{max_retries})")
                # Send GET request using httpx
                response = client.get(url, timeout=30)
                # Check if the request was successful
                if response.status_code == 200:
                    # Validate response content
                    if len(response.content) == 0:
                        logger.warning(f"Empty response received for {key}")
                        failed_downloads.append(f"{key}: Empty file received")
                        break

                    # Construct the full output path for the file
                    file_path = f"{output_path}/{key}.csv"
                    # Write the content to the file
                    with open(file_path, "wb") as file:
                        file.write(response.content)
                    downloaded_files.append(file_path)
                    logger.info(f"Successfully downloaded {key} ({len(response.content)} bytes)")
                    success = True
                else:
                    error_msg = f"HTTP {response.status_code}"
                    try:
                        error_body = response.text[:200]
                        error_msg += f" - {error_body}"
                    except:
                        pass
                    logger.error(f"Failed to download {key}: {error_msg}")

                    if retry_count == max_retries - 1:
                        failed_downloads.append(f"{key}: {error_msg}")
                    else:
                        import time
                        time.sleep(2 ** retry_count)  # Exponential backoff
                        retry_count += 1

            except httpx.TimeoutException as e:
                logger.error(f"Timeout downloading {key}: {e}")
                if retry_count == max_retries - 1:
                    failed_downloads.append(f"{key}: Timeout after {max_retries} attempts")
                else:
                    import time
                    time.sleep(2 ** retry_count)
                    retry_count += 1

            except httpx.HTTPError as e:
                logger.error(f"HTTP error downloading {key}: {e}")
                if retry_count == max_retries - 1:
                    failed_downloads.append(f"{key}: HTTP error - {str(e)}")
                else:
                    import time
                    time.sleep(2 ** retry_count)
                    retry_count += 1

            except Exception as e:
                logger.error(f"Error downloading {key}: {e}")
                failed_downloads.append(f"{key}: {str(e)}")
                break

    # Provide detailed error message if no files downloaded
    if not downloaded_files:
        error_details = "\n".join(failed_downloads) if failed_downloads else "Unknown error"
        raise Exception(
            f"No master contract files were downloaded successfully.\n"
            f"Failed downloads:\n{error_details}\n\n"
            f"Troubleshooting:\n"
            f"1. Check network connectivity\n"
            f"2. Verify authentication token is valid\n"
            f"3. Check Kotak API service status\n"
            f"4. Review logs for detailed error messages"
        )

    # Log warnings for partial failures
    if failed_downloads:
        logger.warning(
            f"Downloaded {len(downloaded_files)} files successfully, "
            f"but {len(failed_downloads)} files failed:\n" + "\n".join(failed_downloads)
        )
    else:
        logger.info(f"Downloaded {len(downloaded_files)} files successfully")

    return downloaded_files


def process_kotak_nse_csv(path):
    """
    Processes the kotak CSV file to fit the existing database schema and performs exchange name mapping.
    """
    logger.info("Processing kotak NSE CSV Data")
    file_path = f"{path}/NSE_CM.csv"

    try:
        df = pd.read_csv(file_path)

        if df.empty:
            logger.warning("NSE CSV file is empty")
            return pd.DataFrame()

        # Validate required columns exist
        required_columns = ["pSymbol", "pDesc", "pExpiryDate", "dStrikePrice;", "lLotSize",
                          "dTickSize ", "pTrdSymbol", "pSymbolName", "pGroup", "pISIN"]
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            logger.error(f"Missing required columns in NSE CSV: {missing_columns}")
            raise KeyError(f"Missing columns: {', '.join(missing_columns)}")

        filtereddataframe = pd.DataFrame()

        filtereddataframe["token"] = df["pSymbol"]
        filtereddataframe["name"] = df["pDesc"]
        filtereddataframe["expiry"] = df["pExpiryDate"]
        filtereddataframe["strike"] = df["dStrikePrice;"]
        filtereddataframe["lotsize"] = df["lLotSize"]
        filtereddataframe["tick_size"] = pd.to_numeric(df["dTickSize "], errors="coerce") / 100
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

        logger.info(f"Successfully processed {len(token_df)} NSE records")
        return token_df

    except FileNotFoundError:
        logger.error(f"NSE CSV file not found: {file_path}")
        raise
    except pd.errors.EmptyDataError:
        logger.error("NSE CSV file is empty or corrupted")
        raise
    except Exception as e:
        logger.exception(f"Error processing NSE CSV: {e}")
        raise


def process_kotak_bse_csv(path):
    """
    Processes the kotak CSV file to fit the existing database schema and performs exchange name mapping.
    """
    logger.info("Processing kotak BSE CSV Data")
    file_path = f"{path}/BSE_CM.csv"

    try:
        df = pd.read_csv(file_path)

        if df.empty:
            logger.warning("BSE CSV file is empty")
            return pd.DataFrame()

        df.columns = df.columns.str.replace(" ", "")
        df.columns = df.columns.str.replace(";", "")
        df.dropna(subset=["pSymbolName"], inplace=True)

        # Validate required columns exist
        required_columns = ["pSymbol", "pDesc", "pExpiryDate", "dStrikePrice",
                          "lLotSize", "dTickSize", "pTrdSymbol", "pSymbolName", "pGroup", "pISIN"]
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            logger.error(f"Missing required columns in BSE CSV: {missing_columns}")
            raise KeyError(f"Missing columns: {', '.join(missing_columns)}")

        filtereddataframe = pd.DataFrame()

        filtereddataframe["token"] = df["pSymbol"]
        filtereddataframe["name"] = df["pDesc"]
        filtereddataframe["expiry"] = df["pExpiryDate"]
        filtereddataframe["strike"] = df["dStrikePrice"]
        filtereddataframe["lotsize"] = df["lLotSize"]
        filtereddataframe["tick_size"] = pd.to_numeric(df["dTickSize"], errors="coerce") / 100
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

        logger.info(f"Successfully processed {len(token_df)} BSE records")
        return token_df

    except FileNotFoundError:
        logger.error(f"BSE CSV file not found: {file_path}")
        raise
    except pd.errors.EmptyDataError:
        logger.error("BSE CSV file is empty or corrupted")
        raise
    except Exception as e:
        logger.exception(f"Error processing BSE CSV: {e}")
        raise


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

    try:
        df = pd.read_csv(file_path, dtype={"pOptionType": "str"})

        if df.empty:
            logger.warning("NFO CSV file is empty")
            return pd.DataFrame()

        df.columns = df.columns.str.replace(" ", "")
        df.columns = df.columns.str.replace(";", "")

        # Validate required columns exist
        required_columns = ["pSymbol", "pSymbolName", "lExpiryDate", "dStrikePrice",
                          "lLotSize", "dTickSize", "pTrdSymbol", "pExchSeg", "pOptionType"]
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            logger.error(f"Missing required columns in NFO CSV: {missing_columns}")
            raise KeyError(f"Missing columns: {', '.join(missing_columns)}")

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
        tokensymbols["tick_size"] = pd.to_numeric(df["dTickSize"], errors="coerce") / 100
        tokensymbols["brsymbol"] = df["pTrdSymbol"]
        tokensymbols["brexchange"] = df["pExchSeg"]
        tokensymbols["exchange"] = "NFO"

        # df1['instrumenttype'] = df['pOptionType'].apply(lambda x: x.replace('XX', 'FUT'))
        tokensymbols["instrumenttype"] = df["pOptionType"].str.replace("XX", "FUT")

        # pSymbolName  df['expiry']
        tokensymbols["symbol"] = tokensymbols.apply(combine_details, axis=1)

        logger.info(f"Successfully processed {len(tokensymbols)} NFO records")
        return tokensymbols

    except FileNotFoundError:
        logger.error(f"NFO CSV file not found: {file_path}")
        raise
    except pd.errors.EmptyDataError:
        logger.error("NFO CSV file is empty or corrupted")
        raise
    except Exception as e:
        logger.exception(f"Error processing NFO CSV: {e}")
        raise


def get_kotak_master_filepaths():
    """
    Get master contract file paths using Neo API v2
    Based on PowerShell test: scripmaster API works with access token and correct baseUrl
    """
    try:
        login_username = find_user_by_username().username
        auth_token = get_auth_token(login_username)

        if not auth_token:
            logger.error("No authentication token found for user")
            raise Exception(
                "Authentication token not found. Please log in again to refresh your session."
            )

        # Updated for Neo API v2: trading_token:::trading_sid:::base_url:::access_token
        try:
            trading_token, trading_sid, base_url, access_token = auth_token.split(":::")
        except ValueError as e:
            logger.error(f"Invalid auth token format: {e}")
            raise Exception(
                "Invalid authentication token format. Please log out and log in again."
            )

        if not access_token:
            logger.error("Access token is empty")
            raise Exception("Access token is missing. Please re-authenticate.")

        # Use the baseUrl from auth token first, then try alternatives
        # Sometimes scripmaster API is on different servers
        base_urls_to_try = [
            base_url,  # From MPIN validation response
            "https://cis.kotaksecurities.com",  # Alternative server
            "https://neo-gw.kotaksecurities.com",  # Another alternative
        ]

        # Get the shared httpx client with connection pooling
        client = get_httpx_client()

        api_errors = []

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

                if response.status_code == 401:
                    error_msg = f"Authentication failed (401) - Token may be expired"
                    logger.error(error_msg)
                    api_errors.append(f"{base_url_attempt}: {error_msg}")
                    continue
                elif response.status_code == 403:
                    error_msg = f"Access forbidden (403) - Check API permissions"
                    logger.error(error_msg)
                    api_errors.append(f"{base_url_attempt}: {error_msg}")
                    continue
                elif response.status_code != 200:
                    error_msg = f"HTTP {response.status_code}"
                    try:
                        error_body = response.text[:200]
                        error_msg += f" - {error_body}"
                    except:
                        pass
                    logger.warning(error_msg)
                    api_errors.append(f"{base_url_attempt}: {error_msg}")
                    continue

                if response.status_code == 200:
                    try:
                        data_dict = json.loads(response.text)
                        logger.debug(f"Response data: {data_dict}")

                        # Check for the expected response structure
                        if "data" in data_dict and "filesPaths" in data_dict["data"]:
                            filepaths_list = data_dict["data"]["filesPaths"]

                            if not filepaths_list:
                                logger.warning(f"Empty filesPaths list from {base_url_attempt}")
                                api_errors.append(f"{base_url_attempt}: Empty file paths list")
                                continue

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

                            if file_dict:
                                logger.info(
                                    f"✅ Successfully retrieved {len(file_dict)} master contract files from {base_url_attempt}"
                                )
                                logger.info(f"Available files: {list(file_dict.keys())}")
                                return file_dict
                            else:
                                logger.warning(f"No recognized file types in response from {base_url_attempt}")
                                api_errors.append(f"{base_url_attempt}: No recognized file types")
                        else:
                            error_msg = f"Unexpected response structure (missing data.filesPaths)"
                            logger.warning(f"{error_msg} from {base_url_attempt}: {data_dict}")
                            api_errors.append(f"{base_url_attempt}: {error_msg}")

                    except json.JSONDecodeError as e:
                        error_msg = f"Invalid JSON response: {str(e)}"
                        logger.error(f"{error_msg} from {base_url_attempt}")
                        logger.debug(f"Raw response: {response.text[:200]}")
                        api_errors.append(f"{base_url_attempt}: {error_msg}")

            except httpx.TimeoutException as e:
                error_msg = f"Request timeout: {str(e)}"
                logger.error(f"{error_msg} for {base_url_attempt}")
                api_errors.append(f"{base_url_attempt}: {error_msg}")
                continue
            except httpx.HTTPError as e:
                error_msg = f"HTTP error: {str(e)}"
                logger.error(f"{error_msg} with {base_url_attempt}")
                api_errors.append(f"{base_url_attempt}: {error_msg}")
                continue
            except Exception as e:
                error_msg = f"Unexpected error: {str(e)}"
                logger.error(f"{error_msg} with {base_url_attempt}")
                api_errors.append(f"{base_url_attempt}: {error_msg}")
                continue

        logger.error("All baseUrl attempts failed for scripmaster API")

        # Fallback: Use direct URLs from PowerShell test results
        logger.warning("API failed, attempting direct URL fallback")
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
        fallback_errors = []

        for key, url in fallback_urls.items():
            try:
                logger.info(f"Testing direct URL: {url}")
                response = client.head(url, timeout=10, follow_redirects=True)
                if response.status_code == 200:
                    accessible_urls[key] = url
                    logger.info(f"✅ Direct URL accessible: {key}")
                else:
                    error_msg = f"HTTP {response.status_code}"
                    logger.warning(f"❌ Direct URL returned {error_msg}: {key}")
                    fallback_errors.append(f"{key}: {error_msg}")
            except httpx.TimeoutException as e:
                error_msg = f"Timeout: {str(e)}"
                logger.warning(f"❌ Direct URL timeout: {key}")
                fallback_errors.append(f"{key}: {error_msg}")
            except httpx.HTTPError as e:
                error_msg = f"HTTP error: {str(e)}"
                logger.warning(f"❌ Direct URL HTTP error: {key} - {e}")
                fallback_errors.append(f"{key}: {error_msg}")
            except Exception as e:
                error_msg = f"Error: {str(e)}"
                logger.warning(f"❌ Direct URL failed: {key} - {e}")
                fallback_errors.append(f"{key}: {error_msg}")

        if accessible_urls:
            logger.info(f"Using {len(accessible_urls)} direct URLs as fallback")
            return accessible_urls

        # All methods failed - provide comprehensive error message
        logger.error("All scripmaster sources failed (API and direct URLs)")

        error_summary = "Failed to retrieve master contract file paths.\n\n"
        error_summary += "API Errors:\n" + "\n".join(f"  - {err}" for err in api_errors)
        error_summary += "\n\nFallback URL Errors:\n" + "\n".join(f"  - {err}" for err in fallback_errors)
        error_summary += "\n\nTroubleshooting:\n"
        error_summary += "  1. Check if your authentication token is valid (try logging out and back in)\n"
        error_summary += "  2. Verify network connectivity to Kotak servers\n"
        error_summary += "  3. Check if Kotak API services are operational\n"
        error_summary += "  4. Review firewall/proxy settings that may block API access"

        raise Exception(error_summary)

    except Exception as e:
        # Re-raise if already a detailed exception
        if "Failed to retrieve master contract file paths" in str(e):
            raise
        # Otherwise wrap in a user-friendly message
        logger.exception(f"Error in get_kotak_master_filepaths: {e}")
        raise Exception(f"Failed to get master contract file paths: {str(e)}")


def process_kotak_cds_csv(path):
    """
    Processes the kotak CSV file to fit the existing database schema and performs exchange name mapping.
    """
    logger.info("Processing kotak CDS CSV Data")
    file_path = f"{path}/CDE_FO.csv"

    try:
        df = pd.read_csv(file_path, dtype={"pOptionType": "str"})

        if df.empty:
            logger.warning("CDS CSV file is empty")
            return pd.DataFrame()

        df.columns = df.columns.str.replace(" ", "")
        df.columns = df.columns.str.replace(";", "")

        # Validate required columns exist
        required_columns = ["pSymbol", "pSymbolName", "lExpiryDate", "dStrikePrice",
                          "lLotSize", "dTickSize", "pTrdSymbol", "pExchSeg", "pOptionType"]
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            logger.error(f"Missing required columns in CDS CSV: {missing_columns}")
            raise KeyError(f"Missing columns: {', '.join(missing_columns)}")

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
        tokensymbols["tick_size"] = pd.to_numeric(df["dTickSize"], errors="coerce") / 100
        tokensymbols["brsymbol"] = df["pTrdSymbol"]
        tokensymbols["brexchange"] = df["pExchSeg"]
        tokensymbols["exchange"] = "CDS"

        # df1['instrumenttype'] = df['pOptionType'].apply(lambda x: x.replace('XX', 'FUT'))
        tokensymbols["instrumenttype"] = df["pOptionType"].str.replace("XX", "FUT")

        # pSymbolName  df['expiry']
        tokensymbols["symbol"] = tokensymbols.apply(combine_details, axis=1)

        logger.info(f"Successfully processed {len(tokensymbols)} CDS records")
        return tokensymbols

    except FileNotFoundError:
        logger.error(f"CDS CSV file not found: {file_path}")
        raise
    except pd.errors.EmptyDataError:
        logger.error("CDS CSV file is empty or corrupted")
        raise
    except Exception as e:
        logger.exception(f"Error processing CDS CSV: {e}")
        raise


def process_kotak_mcx_csv(path):
    """
    Processes the kotak CSV file to fit the existing database schema and performs exchange name mapping.
    """
    logger.info("Processing kotak MCX CSV Data")
    file_path = f"{path}/MCX_FO.csv"

    try:
        df = pd.read_csv(file_path, dtype={"pOptionType": "str"})

        if df.empty:
            logger.warning("MCX CSV file is empty")
            return pd.DataFrame()

        df.columns = df.columns.str.replace(" ", "")
        df.columns = df.columns.str.replace(";", "")
        df.dropna(subset=["pOptionType"], inplace=True)

        # Validate required columns exist
        required_columns = ["pSymbol", "pSymbolName", "lExpiryDate", "dStrikePrice",
                          "lLotSize", "dTickSize", "pTrdSymbol", "pExchSeg", "pOptionType"]
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            logger.error(f"Missing required columns in MCX CSV: {missing_columns}")
            raise KeyError(f"Missing columns: {', '.join(missing_columns)}")

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
        tokensymbols["tick_size"] = pd.to_numeric(df["dTickSize"], errors="coerce") / 100
        tokensymbols["brsymbol"] = df["pTrdSymbol"]
        tokensymbols["brexchange"] = df["pExchSeg"]
        tokensymbols["exchange"] = "MCX"

        # df1['instrumenttype'] = df['pOptionType'].apply(lambda x: x.replace('XX', 'FUT'))
        tokensymbols["instrumenttype"] = df["pOptionType"].str.replace("XX", "FUT")

        # pSymbolName  df['expiry']
        tokensymbols["symbol"] = tokensymbols.apply(combine_details, axis=1)

        logger.info(f"Successfully processed {len(tokensymbols)} MCX records")
        return tokensymbols

    except FileNotFoundError:
        logger.error(f"MCX CSV file not found: {file_path}")
        raise
    except pd.errors.EmptyDataError:
        logger.error("MCX CSV file is empty or corrupted")
        raise
    except Exception as e:
        logger.exception(f"Error processing MCX CSV: {e}")
        raise


def process_kotak_bfo_csv(path):
    """
    Processes the kotak CSV file to fit the existing database schema and performs exchange name mapping.
    """
    logger.info("Processing kotak BFO CSV Data")
    file_path = f"{path}/BSE_FO.csv"

    try:
        df = pd.read_csv(file_path, dtype={"pOptionType": "str"})

        if df.empty:
            logger.warning("BFO CSV file is empty")
            return pd.DataFrame()

        df.columns = df.columns.str.replace(" ", "")
        df.columns = df.columns.str.replace(";", "")
        df.dropna(subset=["pOptionType"], inplace=True)

        # Validate required columns exist
        required_columns = ["pSymbol", "pSymbolName", "lExpiryDate", "dStrikePrice",
                          "lLotSize", "dTickSize", "pTrdSymbol", "pExchSeg", "pOptionType"]
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            logger.error(f"Missing required columns in BFO CSV: {missing_columns}")
            raise KeyError(f"Missing columns: {', '.join(missing_columns)}")

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
        tokensymbols["tick_size"] = pd.to_numeric(df["dTickSize"], errors="coerce") / 100
        tokensymbols["brsymbol"] = df["pTrdSymbol"]
        tokensymbols["brexchange"] = df["pExchSeg"]
        tokensymbols["exchange"] = "BFO"

        # df1['instrumenttype'] = df['pOptionType'].apply(lambda x: x.replace('XX', 'FUT'))
        tokensymbols["instrumenttype"] = df["pOptionType"].str.replace("XX", "FUT")

        # pSymbolName  df['expiry']
        tokensymbols["symbol"] = tokensymbols.apply(combine_details, axis=1)

        logger.info(f"Successfully processed {len(tokensymbols)} BFO records")
        return tokensymbols

    except FileNotFoundError:
        logger.error(f"BFO CSV file not found: {file_path}")
        raise
    except pd.errors.EmptyDataError:
        logger.error("BFO CSV file is empty or corrupted")
        raise
    except Exception as e:
        logger.exception(f"Error processing BFO CSV: {e}")
        raise


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
    downloaded_files = []
    processing_errors = []

    try:
        # Ensure tmp directory exists
        if not os.path.exists(output_path):
            try:
                os.makedirs(output_path)
                logger.info(f"Created temporary directory: {output_path}")
            except Exception as e:
                error_msg = f"Failed to create temporary directory '{output_path}': {str(e)}"
                logger.error(error_msg)
                return socketio.emit("master_contract_download", {"status": "error", "message": error_msg})

        # Download CSV files
        try:
            downloaded_files = download_csv_kotak_data(output_path)
            logger.info(f"Successfully downloaded {len(downloaded_files)} CSV files")
        except Exception as download_error:
            error_msg = f"Download failed: {str(download_error)}"
            logger.error(error_msg)
            # Clean up any partial downloads
            try:
                delete_kotak_temp_data(output_path)
            except:
                pass
            return socketio.emit("master_contract_download", {"status": "error", "message": error_msg})

        if not downloaded_files:
            error_msg = "No CSV files were downloaded successfully"
            logger.error(error_msg)
            return socketio.emit("master_contract_download", {"status": "error", "message": error_msg})

        # Clear existing data
        try:
            delete_symtoken_table()
            logger.info("Cleared existing symbol token data")
        except Exception as e:
            logger.warning(f"Failed to clear existing data (continuing anyway): {e}")

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
        processed_exchanges = []

        for filename, processor_func, exchange_name in processors:
            file_path = f"{output_path}/{filename}"
            if os.path.exists(file_path):
                try:
                    logger.info(f"Processing {exchange_name} data from {filename}...")

                    # Validate file is not empty
                    file_size = os.path.getsize(file_path)
                    if file_size == 0:
                        error_msg = f"{exchange_name} file is empty (0 bytes)"
                        logger.warning(error_msg)
                        processing_errors.append(error_msg)
                        continue

                    # Process the CSV file
                    token_df = processor_func(output_path)

                    if token_df is None or token_df.empty:
                        error_msg = f"No data found in {exchange_name} file"
                        logger.warning(error_msg)
                        processing_errors.append(error_msg)
                        continue

                    # Insert into database
                    copy_from_dataframe(token_df)
                    total_records += len(token_df)
                    processed_exchanges.append(exchange_name)
                    logger.info(f"✅ Processed {len(token_df)} records for {exchange_name}")

                except pd.errors.EmptyDataError as e:
                    error_msg = f"{exchange_name}: CSV file is empty or corrupted"
                    logger.error(error_msg)
                    processing_errors.append(error_msg)
                except pd.errors.ParserError as e:
                    error_msg = f"{exchange_name}: CSV parsing error - {str(e)}"
                    logger.error(error_msg)
                    processing_errors.append(error_msg)
                except KeyError as e:
                    error_msg = f"{exchange_name}: Missing required column - {str(e)}"
                    logger.error(error_msg)
                    processing_errors.append(error_msg)
                except Exception as e:
                    error_msg = f"{exchange_name}: Processing error - {str(e)}"
                    logger.exception(error_msg)
                    processing_errors.append(error_msg)
            else:
                logger.info(f"File not found (skipping): {filename}")

        # Clean up temporary files
        try:
            delete_kotak_temp_data(output_path)
            logger.info("Cleaned up temporary CSV files")
        except Exception as e:
            logger.warning(f"Failed to clean up temporary files: {e}")

        # Determine success or partial success
        if total_records == 0:
            error_summary = "No records were processed successfully.\n"
            if processing_errors:
                error_summary += "Errors encountered:\n" + "\n".join(f"  - {err}" for err in processing_errors)
            else:
                error_summary += "No data found in any downloaded files."

            logger.error(error_summary)
            return socketio.emit("master_contract_download", {"status": "error", "message": error_summary})

        # Success or partial success
        success_msg = f"Successfully processed {total_records} records from {len(processed_exchanges)} exchanges"

        if processing_errors:
            # Partial success
            warning_msg = f"{success_msg}\n\nWarnings:\n" + "\n".join(f"  - {err}" for err in processing_errors)
            logger.warning(warning_msg)
            return socketio.emit(
                "master_contract_download",
                {
                    "status": "success",
                    "message": success_msg,
                    "warnings": processing_errors,
                    "total_records": total_records,
                    "exchanges": processed_exchanges
                },
            )
        else:
            # Complete success
            logger.info(success_msg)
            return socketio.emit(
                "master_contract_download",
                {
                    "status": "success",
                    "message": success_msg,
                    "total_records": total_records,
                    "exchanges": processed_exchanges
                },
            )

    except Exception as e:
        error_msg = f"Master contract download failed: {str(e)}"
        logger.exception(error_msg)

        # Clean up on failure
        try:
            if os.path.exists(output_path):
                delete_kotak_temp_data(output_path)
        except:
            pass

        return socketio.emit("master_contract_download", {"status": "error", "message": error_msg})


def search_symbols(symbol, exchange):
    return SymToken.query.filter(
        SymToken.symbol.like(f"%{symbol}%"), SymToken.exchange == exchange
    ).all()
