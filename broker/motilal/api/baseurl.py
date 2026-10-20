"""Hosts, endpoint paths and the common header builder for the Motilal Oswal (MOFSL) plugin.

Every REST path lives here so the whole plugin cannot drift between API
generations. Versions below are those published in the official documentation
(see broker-api-docs/motilaloswal-api-docs/README.md "Endpoints at a glance").

Auth token format
-----------------
Motilal's newer login generation issues two distinct credentials:

  * ``AuthToken``   -- returned by ``authdirectapi``; sent as ``Authorization``.
  * ``accesstoken`` -- returned by ``getaccesstoken``; sent as ``accesstoken``.

OpenAlgo hands broker modules a single opaque auth string, so the two are packed
into one value separated by ``:::`` (the same idiom tradesmart/zerodha use)::

    "<authtoken>:::<accesstoken>"

``split_auth_token`` unpacks it. A plain token with no ``:::`` is treated as an
AuthToken with no access token, which is the pre-access-token behaviour — so a
deployment without an API secret key keeps working unchanged.

Environment variables
---------------------
The standard OpenAlgo naming applies, identical to every other broker::

    BROKER_API_KEY     -- App API Key   -> ``ApiKey`` header (doc 05) and the
                          SHA-256(password + APIKey) login hash (doc 08)
    BROKER_API_SECRET  -- App API Secret -> ``apisecretkey`` header (doc 09)

The Motilal *client code* is NOT an env variable: it is the trading login ID
entered on the TOTP page, persisted at login and read back by
``get_client_code()``.
"""

import os

PRODUCTION_HOST = "https://openapi.motilaloswal.com"
UAT_HOST = "https://openapi.motilaloswaluat.com"

# Broadcast (market data) feed. Not published in the docs; retained from the
# official SDK's jWebSocket transport.
PRODUCTION_WS_FEED = "wss://ws1feed.motilaloswal.com/jwebsocket/jwebsocket"
UAT_WS_FEED = "wss://ws1feeduat.motilaloswal.com/jwebsocket/jwebsocket"

# Trade/order stream (docs 34-trade-websocket.md, FAQ Q26).
PRODUCTION_WS_TRADE = "wss://openapi.motilaloswal.com/ws"
UAT_WS_TRADE = "wss://uatopenapi.motilaloswal.com/ws"

AUTH_TOKEN_SEPARATOR = ":::"

# Documented endpoint paths. Keys are stable; values carry the API version.
ENDPOINTS = {
    # Authentication / profile
    "authdirectapi": "/rest/login/v7/authdirectapi",
    "getaccesstoken": "/rest/login/v1/getaccesstoken",
    "resendotp": "/rest/login/v5/resendotp",
    "verifyotp": "/rest/login/v5/verifyotp",
    "getprofile": "/rest/login/v5/getprofile",
    "logout": "/rest/login/v5/logout",
    # Orders
    "placeorder": "/rest/trans/v2/placeorder",
    "modifyorder": "/rest/trans/v5/modifyorder",
    "cancelorder": "/rest/trans/v2/cancelorder",
    "positionconversion": "/rest/trans/v2/positionconversion",
    # Books
    "getorderbook": "/rest/book/v5/getorderbook",
    "gettradebook": "/rest/book/v4/gettradebook",
    "getorderdetail": "/rest/book/v5/getorderdetailbyuniqueorderid",
    "gettradedetail": "/rest/book/v4/gettradedetailbyuniqueorderid",
    "getposition": "/rest/book/v4/getposition",
    # Reports
    "getdpholding": "/rest/report/v3/getdpholding",
    "getreportmarginsummary": "/rest/report/v3/getreportmarginsummary",
    "getreportmargindetail": "/rest/report/v3/getreportmargindetail",
    "getltpdata": "/rest/report/v3/getltpdata",
    "getindexltpdata": "/rest/report/v3/getindexltpdata",
    "getscripsbyexchangename": "/rest/report/v3/getscripsbyexchangename",
    "getdprvalues": "/rest/report/v3/getdprvalues",
    "getbrokeragedetail": "/rest/report/v3/getbrokeragedetail",
    "getparticipantsdetail": "/rest/report/v3/getparticipantsdetail",
    "geteoddatabyexchangename": "/rest/report/v3/geteoddatabyexchangename",
    "getindexdatabyexchangename": "/rest/report/v3/getindexdatabyexchangename",
    # CSV downloads (plain public GETs, no version segment)
    "getscripmastercsv": "/getscripmastercsv",
    "getindexdatacsv": "/getindexdatacsv",
    "geteoddatacsv": "/geteoddatacsv",
    "getdprcsv": "/getdprcsv",
}


def get_base_url():
    """Return the REST host. ``BROKER_API_URL`` overrides for UAT."""
    return os.getenv("BROKER_API_URL", PRODUCTION_HOST).rstrip("/")


def get_url(name):
    """Absolute URL for a documented endpoint key."""
    try:
        return f"{get_base_url()}{ENDPOINTS[name]}"
    except KeyError:
        raise KeyError(f"Unknown Motilal endpoint {name!r}; add it to ENDPOINTS.") from None


def get_ws_feed_url(use_uat=False):
    """Broadcast market-data WebSocket URL."""
    return UAT_WS_FEED if use_uat else PRODUCTION_WS_FEED


def get_ws_trade_url(use_uat=False):
    """Trade/order stream WebSocket URL."""
    return UAT_WS_TRADE if use_uat else PRODUCTION_WS_TRADE


def split_auth_token(auth):
    """Split a stored auth string into ``(authtoken, accesstoken)``.

    ``accesstoken`` is ``None`` when the deployment has no API secret key
    configured and therefore never ran the getaccesstoken step.
    """
    if not auth:
        return None, None
    if AUTH_TOKEN_SEPARATOR in auth:
        authtoken, _, accesstoken = auth.partition(AUTH_TOKEN_SEPARATOR)
        return authtoken or None, accesstoken or None
    return auth, None


def join_auth_token(authtoken, accesstoken=None):
    """Pack an AuthToken and optional access token into one stored value."""
    if accesstoken:
        return f"{authtoken}{AUTH_TOKEN_SEPARATOR}{accesstoken}"
    return authtoken


def get_api_secret_key():
    """The ``apisecretkey`` header value, if the deployment has one.

    Motilal's newer generation issues an API secret key separate from the app
    API key. Per the OpenAlgo-wide convention that is ``BROKER_API_SECRET``;
    ``BROKER_API_SECRET_KEY`` stays supported as a fallback. Optional, so a
    deployment without one keeps working (getaccesstoken is then skipped).
    """
    return os.getenv("BROKER_API_SECRET") or os.getenv("BROKER_API_SECRET_KEY") or None


_client_code_cache = None


def set_client_code(client_code):
    """Remember the client code that just logged in (called by auth_api)."""
    global _client_code_cache
    _client_code_cache = client_code or None


def get_client_code():
    """The Motilal client code (trading login ID), or ``None``.

    ``BROKER_API_KEY``/``BROKER_API_SECRET`` hold the app's API key and secret
    - the same meaning as for every other OpenAlgo broker - so the client code
    cannot live there. It is the ID typed on the Motilal TOTP page, which
    brlogin persists through ``handle_auth_success(user_id=...)`` and which is
    read back here via ``database.auth_db.get_user_id``. The in-process cache
    is filled at login and by the first successful lookup.
    """
    global _client_code_cache
    if _client_code_cache:
        return _client_code_cache

    try:
        from database.auth_db import get_user_id
        from database.user_db import find_user_by_username

        user = find_user_by_username()
        if user is not None:
            client_code = get_user_id(user.username)
            if client_code:
                _client_code_cache = client_code
                return client_code
    except Exception:
        # Never let a DB/import problem break header construction.
        pass

    return None


def get_vendor_info(default=""):
    """``vendorinfo`` header: vendor short name, or the client code for clients."""
    return os.getenv("BROKER_VENDOR_CODE") or get_client_code() or default


def get_common_headers(auth=None, vendor_info=None, include_auth=True):
    """Build the documented common header set (05-header-parameters.md).

    Args:
        auth: stored auth string (``authtoken`` or ``authtoken:::accesstoken``).
        vendor_info: override for ``vendorinfo``; defaults to the configured
            vendor code / client code.
        include_auth: ``False`` for the login call, which must not send
            ``Authorization`` ("Used in all API's excluding login API").
    """
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "MOSL/V.1.1.0",
        # doc 05: "Api Key of App". OpenAlgo-wide convention: BROKER_API_KEY is
        # the app API key, BROKER_API_SECRET the app secret. Sending the secret
        # here is what Motilal rejects with MO2005.
        "ApiKey": os.getenv("BROKER_API_KEY", ""),
        "ClientLocalIp": os.getenv("BROKER_CLIENT_LOCAL_IP", "127.0.0.1"),
        "ClientPublicIp": os.getenv("BROKER_CLIENT_PUBLIC_IP", "127.0.0.1"),
        "MacAddress": os.getenv("BROKER_MAC_ADDRESS", "00:00:00:00:00:00"),
        "SourceId": "WEB",
        "vendorinfo": vendor_info if vendor_info is not None else get_vendor_info(),
        "osname": "Windows 10",
        "osversion": "10.0.19041",
        "devicemodel": "AHV",
        "manufacturer": "DELL",
        "productname": "OpenAlgo",
        "productversion": "1.0.0",
        # Mandatory for SourceId=WEB
        "browsername": "Chrome",
        "browserversion": "120.0",
    }

    api_secret_key = get_api_secret_key()
    if api_secret_key:
        headers["apisecretkey"] = api_secret_key

    if include_auth:
        authtoken, accesstoken = split_auth_token(auth)
        if authtoken:
            headers["Authorization"] = authtoken
        if accesstoken:
            headers["accesstoken"] = accesstoken

    return headers
