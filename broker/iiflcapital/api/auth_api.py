import hashlib
import os
from urllib.parse import quote_plus

from broker.iiflcapital.baseurl import BASE_URL, LOGIN_URL
from utils.httpx_client import get_httpx_client


def _generate_checksum(client_id: str, auth_code: str, app_secret: str) -> str:
    payload = f"{client_id}{auth_code}{app_secret}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def get_login_url() -> str:
    """Generate IIFL Capital login URL from environment variables."""
    app_key = os.getenv("BROKER_API_KEY", "").strip()
    redirect_url = os.getenv("REDIRECT_URL", "").strip()

    if not app_key or not redirect_url:
        return ""

    # Send both redirect parameter casings for compatibility with different
    # IIFL deployments. Keep redirect URL unescaped to avoid provider-side
    # double-decoding/parsing issues seen with encoded callback URLs.
    return (
        f"{LOGIN_URL}?v=1"
        f"&appkey={quote_plus(app_key)}"
        f"&redirecturl={redirect_url}"
        f"&redirectUrl={redirect_url}"
    )


def authenticate_broker(auth_code: str, client_id: str):
    """
    Exchange authCode + clientId for userSession.

    Returns:
        tuple: (auth_token, error_message)
    """
    try:
        app_secret = os.getenv("BROKER_API_SECRET", "").strip()
        if not app_secret:
            return None, "BROKER_API_SECRET not found in environment variables"

        if not auth_code or not client_id:
            return None, "Missing authCode or clientId in callback"

        checksum = _generate_checksum(client_id, auth_code, app_secret)
        payload = {"checkSum": checksum}
        headers = {"Content-Type": "application/json", "Accept": "application/json"}

        client = get_httpx_client()
        response = client.post(f"{BASE_URL}/getusersession", json=payload, headers=headers)

        try:
            data = response.json()
        except Exception:
            return None, f"Invalid authentication response: HTTP {response.status_code}"

        if response.status_code != 200:
            message = data.get("message") or data.get("error") or "Authentication failed"
            return None, f"API error: {message}"

        status = str(data.get("status", "")).lower()
        token = data.get("userSession")

        if status == "ok" and token:
            return token, None

        message = data.get("message") or "Authentication failed"
        return None, message

    except Exception as exc:
        return None, f"Error during authentication: {exc}"
