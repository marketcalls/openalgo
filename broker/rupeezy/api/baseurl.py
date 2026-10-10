# broker/rupeezy/api/baseurl.py
#
# Central place for Rupeezy Vortex API hosts and the auth-header builder.
#
# Credentials (Vortex developer portal, https://vortex.rupeezy.in):
#   BROKER_API_KEY    -> application_id
#   BROKER_API_SECRET -> api key / secret (sent as `x-api-key` and used in the
#                        session checksum)
# The user access token returned by authenticate_broker() is sent as
# `Authorization: Bearer <token>` on every authenticated call.

import os

# REST host (orders, portfolio, funds, margins, quotes, history).
BASE_URL = os.getenv("RUPEEZY_BASE_URL", "https://vortex-api.rupeezy.in/v2")

# Hosted SSO login page; redirects back to REDIRECT_URL with an `auth` param.
LOGIN_URL = "https://flow.rupeezy.in"

# Public instrument master (no auth required).
MASTER_URL = "https://static.rupeezy.in/master.csv"

# Market-data + order-update websocket. Auth token rides in the query string.
WS_URL = "wss://wire.rupeezy.in/ws"


def get_rupeezy_headers(auth_token, with_json=False):
    """Bearer-token headers for authenticated Vortex calls."""
    headers = {"Authorization": f"Bearer {auth_token}"}
    if with_json:
        headers["Content-Type"] = "application/json"
    return headers
