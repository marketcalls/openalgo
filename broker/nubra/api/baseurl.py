# broker/nubra/api/baseurl.py
#
# Central place for Nubra hosts, the device id and the auth-header builder.
#
# Nubra V3 auth specifics (from the REST API V3 docs, "Authenticated Request
# Headers"):
#   - `Authorization: Bearer <session_token>`
#   - `x-device-id: <device_id>` -- mandatory on every authenticated call, and
#     it must be the SAME id the login flow used, because /verifyphoneotp binds
#     the session to it.
#   - `Content-Type: application/json` when the request carries a JSON body.
#
# Before this module the host and the device id were copy-pasted across
# auth_api, order_api, funds and margin_api, while data.py and
# master_contract_db.py hardcoded the production host outright -- so
# NUBRA_USE_UAT sent orders to UAT while market data and the symbol master
# silently stayed on PROD.

import os

# REST hosts -------------------------------------------------------------
PROD_BASE_URL = "https://api.nubra.io"
UAT_BASE_URL = "https://uatapi.nubra.io"

# Public instrument-master feeds. The index CSV needs no authentication.
INDEX_MASTER_PATH = "/public/indexes?format=csv"

# The device id OpenAlgo presents to Nubra. One deployment is one device, and
# the value only has to stay stable across the login flow and every later call.
DEVICE_ID = "OPENALGO"

# Nubra returns HTTP 440 when the session is expired, invalid, or no longer
# usable. The V3 docs ("Errors & Exceptions") are explicit that this is a
# re-authentication case rather than a retriable trading error, so it must
# never be retried and never be swallowed into an empty result.
SESSION_EXPIRED_STATUS = 440
SESSION_EXPIRED_MESSAGE = (
    "Nubra session expired or invalid (HTTP 440). Log in to Nubra again."
)


class NubraSessionExpired(Exception):
    """
    Raised when Nubra answers HTTP 440.

    A distinct type rather than a plain Exception because the market-data paths
    deliberately swallow per-symbol and per-chunk failures to keep partial
    results useful. Without something they can identify, an expired session
    reaches the caller as zeroed quotes or an empty DataFrame -- a
    successful-looking empty result instead of "log in again".
    """

    def __init__(self, message=SESSION_EXPIRED_MESSAGE):
        super().__init__(message)


def get_base_url():
    """Production host by default; UAT when NUBRA_USE_UAT is truthy."""
    if str(os.getenv("NUBRA_USE_UAT", "")).strip().lower() in ("1", "true", "yes"):
        return UAT_BASE_URL
    return PROD_BASE_URL


def get_url(endpoint):
    """Full URL for an endpoint path, on whichever host is configured."""
    if not endpoint.startswith("/"):
        endpoint = "/" + endpoint
    return get_base_url() + endpoint


def get_device_id():
    """The device id every Nubra call must present."""
    return DEVICE_ID


def get_nubra_headers(auth_token, with_json=True, device_id=None):
    """
    Build the standard authenticated Nubra V3 request headers.

    Args:
        auth_token: the session_token stored in the Auth table.
        with_json: set False for GETs that carry no body.
        device_id: override the device id (login helpers pass one explicitly).
    """
    headers = {
        "Authorization": f"Bearer {auth_token}",
        "Accept": "application/json",
        "x-device-id": device_id or get_device_id(),
    }
    if with_json:
        headers["Content-Type"] = "application/json"
    return headers
