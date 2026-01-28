import json
import os

import httpx

from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

# Initialize logger
logger = get_logger(__name__)


def authenticate_broker(mobile_number, totp, mpin):
    """
    Authenticate with Kotak using TOTP and MPIN flow.

    Steps:
    1. Login with TOTP to get View token and sid
    2. Validate with MPIN to get Trading token and sid

    Args:
        mobile_number: Mobile number with +91 prefix
        totp: 6-digit TOTP from authenticator app
        mpin: 6-digit trading MPIN

    Returns:
        Tuple of (auth_string, error_message)
        auth_string format: "trading_token:::trading_sid:::base_url:::access_token"

        Components:
        - trading_token: Used in 'Auth' header for API calls
        - trading_sid: Used in 'Sid' header for API calls
        - base_url: Base URL for all API endpoints (e.g., https://cis.kotaksecurities.com)
        - access_token: Original API access token (kept for reference)
    """
    try:
        logger.info("Starting Kotak TOTP authentication flow")

        # Get UCC from BROKER_API_KEY and access_token from BROKER_API_SECRET
        from utils.config import get_broker_api_key, get_broker_api_secret

        ucc = get_broker_api_key()
        access_token = get_broker_api_secret()

        if not ucc:
            logger.error("BROKER_API_KEY (UCC) is not configured")
            return None, "BROKER_API_KEY (UCC) is required in .env file"

        if not access_token:
            logger.error("BROKER_API_SECRET (Access Token) is not configured")
            return None, "BROKER_API_SECRET (Access Token) is required in .env file"

        logger.debug(f"Parsed UCC: {ucc}, Access Token length: {len(access_token)}")

        # Ensure mobile number has +91 prefix
        # Handle all cases: +919876543210, 919876543210, 9876543210
        mobile_number = mobile_number.strip()
        # Remove any existing +91 or 91 prefix
        mobile_number = mobile_number.replace("+91", "").replace(" ", "")
        if mobile_number.startswith("91") and len(mobile_number) == 12:
            mobile_number = mobile_number[2:]  # Remove leading 91
        # Add +91 prefix
        mobile_number = f"+91{mobile_number}"

        # Get the shared httpx client with connection pooling
        client = get_httpx_client()

        # Step 1: Login with TOTP
        payload = json.dumps({"mobileNumber": mobile_number, "ucc": ucc, "totp": totp})

        headers = {
            "Authorization": access_token,
            "neo-fin-key": "neotradeapi",
            "Content-Type": "application/json",
        }

        logger.debug(f"TOTP Login Request - Mobile: {mobile_number[:5]}***, UCC: {ucc}")

        response = client.post(
            "https://mis.kotaksecurities.com/login/1.0/tradeApiLogin",
            headers=headers,
            content=payload,
        )

        logger.debug(f"TOTP Login Response Status: {response.status_code}")
        logger.debug(f"TOTP Login Response: {response.text}")

        data_dict = json.loads(response.text)

        # Check for errors in TOTP login
        if "data" not in data_dict or data_dict.get("data", {}).get("status") != "success":
            error_msg = data_dict.get("errMsg", data_dict.get("message", "TOTP login failed"))
            logger.error(f"TOTP Login Failed - Response: {data_dict}")
            return None, f"TOTP Login Error: {error_msg}"

        # Extract View token and sid
        view_token = data_dict["data"]["token"]
        view_sid = data_dict["data"]["sid"]

        logger.info("TOTP Login successful, proceeding with MPIN validation")

        # Step 2: Validate with MPIN
        payload = json.dumps({"mpin": mpin})

        headers = {
            "Authorization": access_token,
            "neo-fin-key": "neotradeapi",
            "sid": view_sid,
            "Auth": view_token,
            "Content-Type": "application/json",
        }

        logger.debug("MPIN Validation Request initiated")

        response = client.post(
            "https://mis.kotaksecurities.com/login/1.0/tradeApiValidate",
            headers=headers,
            content=payload,
        )

        logger.debug(f"MPIN Validation Response Status: {response.status_code}")
        logger.debug(f"MPIN Validation Response: {response.text}")

        data_dict = json.loads(response.text)

        # Check for errors in MPIN validation
        if "data" not in data_dict or data_dict.get("data", {}).get("status") != "success":
            error_msg = data_dict.get("errMsg", data_dict.get("message", "MPIN validation failed"))
            logger.error(f"MPIN Validation Failed - Response: {data_dict}")
            return None, f"MPIN Validation Error: {error_msg}"

        # Extract Trading token, sid, and baseUrl
        trading_token = data_dict["data"]["token"]
        trading_sid = data_dict["data"]["sid"]
        base_url = data_dict["data"].get("baseUrl", "")

        if not base_url:
            logger.warning("baseUrl not found in MPIN validation response, API calls may fail")

        logger.info("Kotak TOTP authentication completed successfully")
        logger.debug(f"Base URL for API calls: {base_url}")

        # Create auth string: trading_token:::trading_sid:::base_url:::access_token
        # This format allows extracting all components needed for subsequent API calls
        auth_string = f"{trading_token}:::{trading_sid}:::{base_url}:::{access_token}"
        logger.debug(
            f"AUTH TOKEN CREATED: {trading_token[:10]}...:::{trading_sid}:::{base_url}:::{access_token[:10]}..."
        )

        return auth_string, None

    except KeyError as e:
        logger.error(f"Missing expected field in API response: {str(e)}")
        return None, f"Missing expected field in API response: {str(e)}"
    except httpx.HTTPError as e:
        logger.error(f"HTTP request failed: {str(e)}")
        return None, f"HTTP request failed: {str(e)}"
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON response: {str(e)}")
        return None, f"Failed to parse JSON response: {str(e)}"
    except Exception as e:
        logger.error(f"Authentication error: {str(e)}")
        return None, f"Authentication error: {str(e)}"
