import os

import httpx

from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

AUTH_BASE_URL = os.getenv("DHAN_AUTH_BASE_URL", "https://auth.dhan.co").rstrip("/")
API_BASE_URL = os.getenv("DHAN_API_BASE_URL", "https://api.dhan.co").rstrip("/")


def _get_client():
    return get_httpx_client()


def _get_app_credentials():
    """
    Get Dhan app credentials.
    Supports BROKER_API_KEY in both formats:
    1) api_key
    2) client_id:::api_key
    """
    broker_api_key = os.getenv("BROKER_API_KEY")
    broker_api_secret = os.getenv("BROKER_API_SECRET")
    dhan_client_id = None

    if broker_api_key and ":::" in broker_api_key:
        dhan_client_id, broker_api_key = broker_api_key.split(":::", 1)

    return broker_api_key, broker_api_secret, dhan_client_id


def _extract_error_message(response, default_message):
    try:
        payload = response.json()
    except ValueError:
        return f"{default_message}: HTTP {response.status_code} - {response.text}"

    if isinstance(payload, dict):
        if payload.get("errorMessage"):
            return payload["errorMessage"]

        if payload.get("message"):
            return payload["message"]

        errors = payload.get("errors")
        if isinstance(errors, list):
            messages = []
            for err in errors:
                if isinstance(err, dict) and err.get("message"):
                    messages.append(err["message"])
                elif isinstance(err, str):
                    messages.append(err)
            if messages:
                return "; ".join(messages)

        if payload.get("status") in {"failed", "error"}:
            error_data = payload.get("data")
            if isinstance(error_data, dict) and error_data:
                code = next(iter(error_data))
                return f"{code}: {error_data.get(code)}"

    return f"{default_message}: HTTP {response.status_code} - {response.text}"


def _extract_token_metadata(response_data):
    return {
        "dhan_client_id": response_data.get("dhanClientId"),
        "dhan_client_name": response_data.get("dhanClientName"),
        "dhan_client_ucc": response_data.get("dhanClientUcc"),
        "ddpi_status": response_data.get("givenPowerOfAttorney", False),
        "token_expiry": response_data.get("expiryTime"),
    }


def generate_access_token_with_totp(dhan_client_id, pin, totp):
    """
    Generate access token using Dhan Client ID + PIN + TOTP.
    Endpoint: POST /app/generateAccessToken
    """
    if not dhan_client_id or not pin or not totp:
        return None, "dhan_client_id, pin and totp are required"

    try:
        client = _get_client()
        response = client.post(
            f"{AUTH_BASE_URL}/app/generateAccessToken",
            params={"dhanClientId": dhan_client_id, "pin": pin, "totp": totp},
        )

        if response.status_code != 200:
            return None, _extract_error_message(response, "Failed to generate access token")

        data = response.json()
        access_token = data.get("accessToken")
        if not access_token:
            return None, "Access token not found in response"

        return access_token, _extract_token_metadata(data)
    except httpx.RequestError as e:
        return None, f"HTTP request error while generating access token: {str(e)}"
    except Exception as e:
        return None, f"An exception occurred while generating access token: {str(e)}"


def renew_token(access_token, dhan_client_id):
    """
    Renew an active Dhan token.
    Endpoint: GET /v2/RenewToken
    """
    if not access_token or not dhan_client_id:
        return None, "access_token and dhan_client_id are required"

    try:
        client = _get_client()
        response = client.get(
            f"{API_BASE_URL}/v2/RenewToken",
            headers={"access-token": access_token, "dhanClientId": dhan_client_id},
        )

        if response.status_code != 200:
            return None, _extract_error_message(response, "Failed to renew token")

        data = response.json()
        renewed_access_token = data.get("accessToken")
        if not renewed_access_token:
            return None, "Renew token response did not return accessToken"

        return renewed_access_token, _extract_token_metadata(data)
    except httpx.RequestError as e:
        return None, f"HTTP request error while renewing token: {str(e)}"
    except Exception as e:
        return None, f"An exception occurred while renewing token: {str(e)}"


def generate_consent(dhan_client_id=None):
    """
    Step 1 (Individual flow): Generate consentAppId.
    Endpoint: POST /app/generate-consent?client_id={dhanClientId}
    """
    try:
        app_id, app_secret, extracted_client_id = _get_app_credentials()

        if not app_id or not app_secret:
            return None, "BROKER_API_KEY and BROKER_API_SECRET are required"

        if not dhan_client_id:
            dhan_client_id = extracted_client_id

        if not dhan_client_id:
            return None, "Dhan Client ID is required for generate-consent"

        client = _get_client()
        response = client.post(
            f"{AUTH_BASE_URL}/app/generate-consent",
            params={"client_id": dhan_client_id},
            headers={"app_id": app_id, "app_secret": app_secret},
        )

        if response.status_code != 200:
            return None, _extract_error_message(response, "Failed to generate consent")

        data = response.json()
        consent_app_id = data.get("consentAppId")
        if not consent_app_id:
            return None, f"consentAppId not found in response: {data}"

        return consent_app_id, None
    except httpx.RequestError as e:
        return None, f"HTTP request error while generating consent: {str(e)}"
    except Exception as e:
        return None, f"An exception occurred while generating consent: {str(e)}"


def get_login_url(consent_app_id):
    """
    Step 2 (Individual flow): Browser login URL.
    """
    if not consent_app_id:
        return None
    return f"{AUTH_BASE_URL}/login/consentApp-login?consentAppId={consent_app_id}"


def consume_consent(token_id):
    """
    Step 3 (Individual flow): Consume consent and fetch access token.
    Endpoint: POST /app/consumeApp-consent?tokenId={tokenId}
    """
    if not token_id:
        return None, "token_id is required"

    try:
        app_id, app_secret, _ = _get_app_credentials()
        if not app_id or not app_secret:
            return None, "BROKER_API_KEY and BROKER_API_SECRET are required"

        client = _get_client()
        response = client.post(
            f"{AUTH_BASE_URL}/app/consumeApp-consent",
            params={"tokenId": token_id},
            headers={"app_id": app_id, "app_secret": app_secret},
        )

        if response.status_code != 200:
            return None, _extract_error_message(response, "Failed to consume consent")

        data = response.json()
        access_token = data.get("accessToken")
        if not access_token:
            return None, "Access token not found in consume-consent response"

        return access_token, _extract_token_metadata(data)
    except httpx.RequestError as e:
        return None, f"HTTP request error while consuming consent: {str(e)}"
    except Exception as e:
        return None, f"An exception occurred while consuming consent: {str(e)}"


def _get_partner_credentials():
    partner_id = os.getenv("BROKER_PARTNER_ID")
    partner_secret = os.getenv("BROKER_PARTNER_SECRET")
    return partner_id, partner_secret


def generate_partner_consent():
    """
    Partner Flow Step 1: Generate consentId.
    Endpoint: POST /partner/generate-consent
    """
    try:
        partner_id, partner_secret = _get_partner_credentials()
        if not partner_id or not partner_secret:
            return None, "BROKER_PARTNER_ID and BROKER_PARTNER_SECRET are required"

        client = _get_client()
        response = client.post(
            f"{AUTH_BASE_URL}/partner/generate-consent",
            headers={"partner_id": partner_id, "partner_secret": partner_secret},
        )

        if response.status_code != 200:
            return None, _extract_error_message(response, "Failed to generate partner consent")

        data = response.json()
        consent_id = data.get("consentId")
        if not consent_id:
            return None, f"consentId not found in response: {data}"

        return consent_id, None
    except httpx.RequestError as e:
        return None, f"HTTP request error while generating partner consent: {str(e)}"
    except Exception as e:
        return None, f"An exception occurred while generating partner consent: {str(e)}"


def get_partner_login_url(consent_id):
    """
    Partner Flow Step 2: Browser login URL.
    """
    if not consent_id:
        return None
    return f"{AUTH_BASE_URL}/consent-login?consentId={consent_id}"


def consume_partner_consent(token_id):
    """
    Partner Flow Step 3: Consume consent and fetch access token.
    Endpoint: POST /partner/consume-consent?tokenId={tokenId}
    """
    if not token_id:
        return None, "token_id is required"

    try:
        partner_id, partner_secret = _get_partner_credentials()
        if not partner_id or not partner_secret:
            return None, "BROKER_PARTNER_ID and BROKER_PARTNER_SECRET are required"

        client = _get_client()
        response = client.post(
            f"{AUTH_BASE_URL}/partner/consume-consent",
            params={"tokenId": token_id},
            headers={"partner_id": partner_id, "partner_secret": partner_secret},
        )

        if response.status_code != 200:
            return None, _extract_error_message(response, "Failed to consume partner consent")

        data = response.json()
        access_token = data.get("accessToken")
        if not access_token:
            return None, "Access token not found in partner consume-consent response"

        return access_token, _extract_token_metadata(data)
    except httpx.RequestError as e:
        return None, f"HTTP request error while consuming partner consent: {str(e)}"
    except Exception as e:
        return None, f"An exception occurred while consuming partner consent: {str(e)}"


def set_static_ip(access_token, dhan_client_id, ip_address, ip_flag="PRIMARY"):
    """
    Set static IP (PRIMARY/SECONDARY).
    Endpoint: POST /v2/ip/setIP
    """
    if ip_flag not in {"PRIMARY", "SECONDARY"}:
        return None, "ip_flag must be PRIMARY or SECONDARY"

    if not access_token or not dhan_client_id or not ip_address:
        return None, "access_token, dhan_client_id and ip_address are required"

    try:
        client = _get_client()
        response = client.post(
            f"{API_BASE_URL}/v2/ip/setIP",
            headers={"access-token": access_token, "Content-Type": "application/json"},
            json={"dhanClientId": dhan_client_id, "ip": ip_address, "ipFlag": ip_flag},
        )

        if response.status_code not in {200, 201}:
            return None, _extract_error_message(response, "Failed to set static IP")

        return response.json(), None
    except httpx.RequestError as e:
        return None, f"HTTP request error while setting static IP: {str(e)}"
    except Exception as e:
        return None, f"An exception occurred while setting static IP: {str(e)}"


def modify_static_ip(access_token, dhan_client_id, ip_address, ip_flag="PRIMARY"):
    """
    Modify static IP (PRIMARY/SECONDARY).
    Endpoint: PUT /v2/ip/modifyIP
    """
    if ip_flag not in {"PRIMARY", "SECONDARY"}:
        return None, "ip_flag must be PRIMARY or SECONDARY"

    if not access_token or not dhan_client_id or not ip_address:
        return None, "access_token, dhan_client_id and ip_address are required"

    try:
        client = _get_client()
        response = client.put(
            f"{API_BASE_URL}/v2/ip/modifyIP",
            headers={"access-token": access_token, "Content-Type": "application/json"},
            json={"dhanClientId": dhan_client_id, "ip": ip_address, "ipFlag": ip_flag},
        )

        if response.status_code not in {200, 201}:
            return None, _extract_error_message(response, "Failed to modify static IP")

        return response.json(), None
    except httpx.RequestError as e:
        return None, f"HTTP request error while modifying static IP: {str(e)}"
    except Exception as e:
        return None, f"An exception occurred while modifying static IP: {str(e)}"


def get_static_ip(access_token):
    """
    Get current static IP configuration.
    Endpoint: GET /v2/ip/getIP
    """
    if not access_token:
        return None, "access_token is required"

    try:
        client = _get_client()
        response = client.get(
            f"{API_BASE_URL}/v2/ip/getIP",
            headers={"access-token": access_token, "Accept": "application/json"},
        )

        if response.status_code != 200:
            return None, _extract_error_message(response, "Failed to get static IP")

        return response.json(), None
    except httpx.RequestError as e:
        return None, f"HTTP request error while fetching static IP: {str(e)}"
    except Exception as e:
        return None, f"An exception occurred while fetching static IP: {str(e)}"


def get_user_profile(access_token):
    """
    Validate token and fetch user profile.
    Endpoint: GET /v2/profile
    """
    if not access_token:
        return None, "access_token is required"

    try:
        client = _get_client()
        response = client.get(
            f"{API_BASE_URL}/v2/profile",
            headers={"access-token": access_token, "Accept": "application/json"},
        )

        if response.status_code != 200:
            return None, _extract_error_message(response, "Failed to fetch user profile")

        return response.json(), None
    except httpx.RequestError as e:
        return None, f"HTTP request error while fetching user profile: {str(e)}"
    except Exception as e:
        return None, f"An exception occurred while fetching user profile: {str(e)}"


def get_direct_access_token(access_token):
    """Validate and use direct access token configured by user."""
    if not access_token:
        return None, "No access token provided"

    if len(access_token) < 50:
        return None, "Invalid access token format"

    return access_token, None


def authenticate_broker(code):
    """
    OpenAlgo auth entrypoint for dhan_sandbox.

    Compatibility behavior:
    - If callback provides "dhan_sandbox" (current flow), use BROKER_API_SECRET directly.
    - If a direct JWT-like token is passed, use it directly.
    - If tokenId is passed, attempt consume-consent flow.
    """
    try:
        env_access_token = os.getenv("BROKER_API_SECRET")

        # Current dhan_sandbox callback flow in brlogin.py passes this value.
        if not code or code == "dhan_sandbox":
            if env_access_token:
                return get_direct_access_token(env_access_token)
            return None, "No access token found in BROKER_API_SECRET environment variable"

        # Allow direct token input for manual login.
        if isinstance(code, str) and len(code) > 100 and "." in code:
            return get_direct_access_token(code)

        # Try consent tokenId flow.
        access_token, consent_response = consume_consent(code)
        if access_token:
            return access_token, None

        # Preserve old behavior fallback if consent-based auth is not configured.
        if env_access_token:
            logger.warning(
                "Consent-based authentication failed; falling back to BROKER_API_SECRET token."
            )
            return get_direct_access_token(env_access_token)

        if isinstance(consent_response, str):
            return None, consent_response

        return None, "Authentication failed. Unable to obtain access token."
    except Exception as e:
        return None, f"An exception occurred: {str(e)}"
