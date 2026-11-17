"""Pocketful host, the stored session token layout and the shared request helper.

Sources: Pocketful's API documentation (https://api.pocketful.in/docs/curl,
offline copy of 2026-11-17) and the official Python SDK ``pocketful`` 0.1.2
from PyPI, whose ``pocketful.py`` carries the routes and the header set.

Host. Every REST call goes to https://algo.pocketful.in (the docs' base URL
and the SDK's ``_root_url``). The old trade.pocketful.in host still answered
in November 2026, but the documentation no longer names it.

Headers. The pages disagree: "Historical Data" shows ``Authorization: Bearer
<token>``, the profile page ``x-authorization-token`` with ``x-device-type``,
and the SDK sends ``x-authorization-token`` on every call. Both are sent, so
every page's form is present. The SDK also sends the machine's public IP,
which it looks up from a third-party service; that header is not sent here.

Token. Nearly every endpoint takes the trading account's ``client_id``, so the
login stores the token as ``<client_id>:::<access_token>`` (pack_token), as
broker/nuvama packs its session. Any code that needs either part reads it from
the token it was handed: no username, no browser session, no database read.
A bare access token (stored before this layout) falls back to the client id
the login stored with the session (``Auth.user_id``).

Answers. Two envelopes are in use: ``{"status": "success" | "error",
"message", "data", "error_code"}`` and, on the newer endpoints (profile,
margin), ``{"status": true | false, "message", "errorcode", "data"}``.
PocketfulResponse.ok accepts either success form.
"""

import json

from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

BASE_URL = "https://algo.pocketful.in"
REQUEST_TIMEOUT = 15.0
TOKEN_SEPARATOR = ":::"
BROKER = "pocketful"


def pack_token(client_id, access_token):
    """The token stored at login: the client id and the access token together."""
    return f"{client_id}{TOKEN_SEPARATOR}{access_token}"


def split_token(token):
    """(client_id or None, access_token) from a stored token."""
    token = token or ""
    if TOKEN_SEPARATOR in token:
        client_id, access_token = token.split(TOKEN_SEPARATOR, 1)
        return (client_id or None), access_token
    return None, token


def access_token(token):
    """The bare access token sent in the headers."""
    return split_token(token)[1]


def client_id(token):
    """The trading client id for a stored token, or None.

    From the token itself, or for a bare access token from the client id the
    login stored with the Pocketful session.
    """
    packed, _ = split_token(token)
    if packed:
        return packed
    from database.auth_db import Auth

    try:
        row = Auth.query.filter_by(broker=BROKER, is_revoked=False).first()
        return row.user_id if row and row.user_id else None
    except Exception:
        logger.exception("Could not read the client id stored with the Pocketful session")
        return None


def build_headers(token):
    bare = access_token(token)
    return {
        "Authorization": f"Bearer {bare}",
        "x-authorization-token": bare,
        "x-device-type": "WEB",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


class PocketfulResponse:
    """What a request returns: the HTTP status, the parsed body and the raw text."""

    __slots__ = ("status_code", "data", "text")

    def __init__(self, status_code, data, text):
        self.status_code = status_code
        self.data = data
        self.text = text

    @property
    def status(self):
        return self.status_code

    @property
    def ok(self):
        """A 2xx whose body reports success in either envelope."""
        if not 200 <= self.status_code < 300 or not isinstance(self.data, dict):
            return False
        return self.data.get("status") in ("success", True)

    @property
    def payload(self):
        """The ``data`` member of the answer, or None."""
        return self.data.get("data") if isinstance(self.data, dict) else None

    @property
    def message(self):
        """The broker's own message, for the log and for a refusal shown to a trader."""
        if isinstance(self.data, dict):
            return str(self.data.get("message") or "")
        return ""


def pocketful_request(
    method, path, token, params=None, payload=None, timeout=REQUEST_TIMEOUT, headers=None
):
    """Send one request to Pocketful with the session headers and parse the answer.

    ``path`` is relative to BASE_URL ("/api/v1/orders"). ``headers`` adds the
    few an endpoint documents beyond the session's own (the margin calculator's
    ``clientid``). Transport errors are raised to the caller: an order path must
    know a request may have been sent. A body that is not JSON comes back with
    ``data`` None and the text kept.
    """
    url = f"{BASE_URL}/{path.lstrip('/')}"
    body = json.dumps(payload) if payload is not None else None
    response = get_httpx_client().request(
        method.upper(),
        url,
        headers={**build_headers(token), **(headers or {})},
        content=body,
        params=params,
        timeout=timeout,
    )
    try:
        data = response.json()
    except ValueError:
        data = None
        logger.error(
            f"Pocketful {method.upper()} {path} answered {response.status_code} "
            "with a body that is not JSON"
        )
    return PocketfulResponse(response.status_code, data, response.text)
