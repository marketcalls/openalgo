"""Nuvama (API Connect) hosts, the session token layout and the shared request helper.

Sources: the API Connect docs (broker-api-docs/nuvama-api-docs) and the official
Python SDK ``APIConnect`` 2.0.12 from PyPI, whose ``constants/constants.py``,
``APIConnect/http.py`` and ``APIConnect/login_helper.py`` carry the production
hosts, the header set and the login sequence that the docs leave out.

Every authenticated call carries four headers, as the SDK sends them:

- ``Authorization``: the session ``auth`` from ``/accounts/logindata``
- ``Source``: the API key (packed into the stored session at login)
- ``SourceToken``: the vendor session (``msg``) from ``/accounts/loginvendor``
- ``AppIdKey``: the app id key; the login answer returns the one this session uses

The SDK also sends ``X-Forwarded-For`` with the public IP it looks up from a
third-party service. Nuvama sees the real source address of every request
(the static IP it has registered), so that header is not sent here.

The stored OpenAlgo token packs the per-session values, so a request never
needs anything but the token and the API key read at call time.
"""

import json
import os

from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

BASE_EQ = "https://nc.nuvamawealth.com/edelmw-eq/eq/"
BASE_CONTENT = "https://nc.nuvamawealth.com/edelmw-content/content/"
BASE_LOGIN = "https://nc.nuvamawealth.com/edelmw-login/login/"
CONTRACT_URL = "https://nc.nuvamawealth.com/app/toccontracts/instruments.zip"
LOGIN_PAGE = "https://www.nuvamawealth.com/api-connect/login"

# Streaming socket (plain TCP, newline-delimited JSON). The host is the one in
# Nuvama's docs and settings.ini (ncst); the SDK's built-in ndst accepts the
# connection but sends nothing (checked live, November 2026).
STREAM_HOST = "ncst.nuvamawealth.com"
STREAM_PORT = 9443

# The app id key the SDK starts every session with (APIConnect.__init__). The
# server answers the login with the key this session uses, in the AppIdKey
# response header, and that one is stored in the token.
INITIAL_APP_ID_KEY = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJhcHAiOjAsImZmIjoiVyIsImJkIjoid2ViLXBjIiwibmJmIjoxNzg1NDI3NDM5"
    "LCJzcmMiOiJlbXRtdyIsImF2IjoiMi4wLjEyIiwiYXBwaWQiOiI1NDc3ZjFhMGVhYTMxN2I3YTY1ZTk2NGY3ZDliNTNmNiIsImlzcyI6"
    "ImVtdCIsImV4cCI6MTc4NTQzNjIwMCwiaWF0IjoxNzg1NDI3NzM5fQ.I-BZnbG-Xsvvk23dvTsgxQhCGm0Ph0qtwCxmidwgUuM"
)

TOKEN_SEPARATOR = ":::"
REQUEST_TIMEOUT = 15.0


class NuvamaSession:
    """The per-session values packed into the stored token.

    The API key travels with the session (as Zerodha stores api_key:token):
    it goes out as the Source header, and taking it from the session rather
    than the environment means a request can never pair this session with
    another broker's key. A background job (a scheduled Flow) has been seen
    reading the .env broker's BROKER_API_KEY, which Nuvama answers with
    "Invalid API Key".
    """

    __slots__ = ("auth", "source_token", "app_id_key", "account_id", "account_type", "api_key")

    def __init__(self, auth, source_token, app_id_key, account_id, account_type, api_key):
        self.auth = auth
        self.source_token = source_token
        self.app_id_key = app_id_key
        self.account_id = account_id
        self.account_type = account_type
        self.api_key = api_key

    def pack(self):
        return TOKEN_SEPARATOR.join(
            [
                self.auth,
                self.source_token,
                self.app_id_key,
                self.account_id,
                self.account_type,
                self.api_key,
            ]
        )


def parse_token(token):
    """Split a stored token into its session values.

    Raises ValueError for a token that is not a complete Nuvama session (one
    stored before the API key was part of it included), so a request never
    goes out with half a header set.
    """
    parts = (token or "").split(TOKEN_SEPARATOR)
    if len(parts) != 6 or not all(parts[:4]) or not parts[5]:
        raise ValueError("The stored Nuvama session is incomplete. Log in to Nuvama again.")
    return NuvamaSession(*parts)


def build_headers(
    session=None, *, app_id_key=None, source_token=None, api_key=None, send_source=True
):
    """The header set the SDK sends (APIConnect/http.py)."""
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if session is not None:
        headers["Authorization"] = session.auth
        headers["SourceToken"] = session.source_token
        headers["AppIdKey"] = session.app_id_key
    if source_token:
        headers["SourceToken"] = source_token
    if app_id_key:
        headers["AppIdKey"] = app_id_key
    if send_source:
        source = api_key or (session.api_key if session is not None else None)
        if source:
            headers["Source"] = source
    return headers


class NuvamaResponse:
    """What a request returns: the HTTP status, the parsed body and the raw text."""

    __slots__ = ("status_code", "data", "text", "headers")

    def __init__(self, status_code, data, text, headers):
        self.status_code = status_code
        self.data = data
        self.text = text
        self.headers = headers

    @property
    def status(self):
        return self.status_code

    @property
    def ok(self):
        """A 200 whose body is not an error envelope.

        Nuvama answers "nothing found" and other refusals with HTTP 222 and an
        ``error`` object, so the status alone is not enough.
        """
        return (
            self.status_code == 200 and isinstance(self.data, dict) and not self.data.get("error")
        )

    def error_message(self, default="Nuvama did not accept the request"):
        if isinstance(self.data, dict):
            error = self.data.get("error")
            if isinstance(error, dict) and error.get("errMsg"):
                return error["errMsg"]
            body = self.data.get("data")
            if isinstance(body, dict) and body.get("msg") and not self.ok:
                return body["msg"]
            for key in ("message", "msg"):
                if self.data.get(key):
                    return str(self.data[key])
        return default

    def error_code(self):
        if isinstance(self.data, dict):
            error = self.data.get("error")
            if isinstance(error, dict):
                return error.get("errCd")
        return None


def nuvama_request(method, url, token=None, payload=None, params=None, timeout=REQUEST_TIMEOUT):
    """Send one request with the session headers and parse the answer.

    Transport errors are raised to the caller (an order path must know a
    request may have been sent). A body that is not JSON comes back with
    ``data`` set to None and the text kept for the log.
    """
    session = parse_token(token) if token else None
    headers = build_headers(session)
    client = get_httpx_client()
    body = json.dumps(payload) if payload is not None else None
    response = client.request(
        method.upper(), url, headers=headers, content=body, params=params, timeout=timeout
    )
    try:
        data = response.json()
    except ValueError:
        data = None
        logger.error(
            f"Nuvama {method.upper()} {url.split('?')[0]} answered {response.status_code} "
            f"with a body that is not JSON"
        )
    return NuvamaResponse(response.status_code, data, response.text, response.headers)


def account_path(token):
    """The account id that goes in the {userid} path segment."""
    return parse_token(token).account_id
