# broker/arrow/api/baseurl.py
#
# Central place for Arrow API hosts and the custom auth-header builder.
# Arrow does NOT use `Authorization: Bearer`. Every authenticated request
# carries two custom headers:
#   appID  -> the application id (stored in env as BROKER_API_KEY)
#   token  -> the user JWT access token (returned by authenticate_broker,
#             persisted encrypted in the Auth table, passed back to each call)

import os

# REST hosts -------------------------------------------------------------
# Everything (orders, positions, holdings, funds, margin, quotes, user,
# utility, instrument master) lives on edge.arrow.trade. Historical candle
# data is served from a SEPARATE host.
ROOT_URL = "https://edge.arrow.trade"
HISTORICAL_URL = "https://historical-api.arrow.trade"

# Token-exchange endpoint used during login (see api/auth_api.py).
AUTH_TOKEN_URL = f"{ROOT_URL}/auth/app/authenticate-token"

# Instrument-master CSV endpoints (authenticated GET). `/all` returns the
# full universe; per-segment variants exist (/nse, /bse, /mcx).
INSTRUMENTS_URL = f"{ROOT_URL}/all"

# WebSocket hosts --------------------------------------------------------
# Standard market-data stream: big-endian binary, integer-token based,
# modes ltp/ltpc/quote/full (5-level depth). This is the stream used by the
# OpenAlgo streaming adapter (token-based maps cleanly to SymToken.token).
WS_MARKET_DATA_URL = "wss://ds.arrow.trade"
# Low-latency HFT stream (little-endian, symbol/symId based) -- not used by
# the default adapter, kept here for reference.
WS_HFT_URL = "wss://socket.arrow.trade"
# Order/trade update stream (JSON, auto-push, no subscription).
WS_ORDER_UPDATES_URL = "wss://order-updates.arrow.trade"


def get_arrow_headers(auth_token, with_json=False):
    """Build Arrow's custom auth headers.

    Args:
        auth_token: the user JWT access token (the value stored in Auth.auth).
        with_json: set True for requests that send a JSON body.

    Returns:
        dict of headers including appID (from BROKER_API_KEY) and token.
    """
    headers = {
        "appID": os.getenv("BROKER_API_KEY"),
        "token": auth_token,
    }
    if with_json:
        headers["Content-Type"] = "application/json"
    return headers
