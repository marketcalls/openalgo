"""Nuvama login: vendor session from the API key and secret, then the session for the request id.

The trader logs in on Nuvama's page
(``https://www.nuvamawealth.com/api-connect/login?api_key=...``) and Nuvama
redirects back with ``request_id``. Two calls then make the session, as the
official SDK does (APIConnect/login_helper.py):

1. ``POST {login}/accounts/loginvendor/{api_key}/`` with ``{"pwd": api_secret}``
   answers ``msg``, the vendor session sent as ``SourceToken`` from then on.
2. ``POST {login}/accounts/logindata/`` with ``{"reqId": request_id}`` answers
   ``data.auth`` (the ``Authorization`` value) and the account in
   ``data.lgnData.accs``; the ``AppIdKey`` response header is the app id key
   this session uses.
"""

import os

from broker.nuvama.api.baseurl import (
    BASE_LOGIN,
    INITIAL_APP_ID_KEY,
    NuvamaSession,
    build_headers,
)
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


def _json(response):
    try:
        return response.json()
    except ValueError:
        return None


def _error_text(body, default):
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict) and error.get("errMsg"):
            return error["errMsg"]
        if body.get("msg") and not body.get("success", True):
            return body["msg"]
    return default


def authenticate_broker(request_id):
    """Exchange Nuvama's request id for a session.

    Returns:
        (auth_token, feed_token, user_id, error): the packed session token, no
        separate feed token, the account Nuvama reported for this login, and
        an error sentence when the login did not complete.
    """
    if not request_id:
        return None, None, None, "Nuvama did not send back a request id. Start the login again."

    api_key = os.getenv("BROKER_API_KEY")
    api_secret = os.getenv("BROKER_API_SECRET")
    if not api_key or not api_secret:
        return None, None, None, "Add your Nuvama API key and API secret in Broker Configuration."

    client = get_httpx_client()
    try:
        # Step 1: vendor session for this API key.
        vendor = client.post(
            f"{BASE_LOGIN}accounts/loginvendor/{api_key}/",
            headers=build_headers(app_id_key=INITIAL_APP_ID_KEY, api_key=api_key),
            json={"pwd": api_secret},
            timeout=20.0,
        )
        vendor_body = _json(vendor)
        source_token = vendor_body.get("msg") if isinstance(vendor_body, dict) else None
        if vendor.status_code != 200 or not source_token or vendor_body.get("error"):
            logger.error(
                f"Nuvama vendor login failed: status {vendor.status_code}, "
                f"{_error_text(vendor_body, 'no session in the answer')}"
            )
            return (
                None,
                None,
                None,
                "Nuvama did not accept the API key and secret. Check them in Broker Configuration.",
            )

        app_id_key = vendor.headers.get("AppIdKey") or INITIAL_APP_ID_KEY

        # Step 2: the session for this login's request id. The SDK sends this
        # call without the Source header.
        login = client.post(
            f"{BASE_LOGIN}accounts/logindata/",
            headers=build_headers(
                source_token=source_token, app_id_key=app_id_key, send_source=False
            ),
            json={"reqId": request_id},
            timeout=20.0,
        )
        login_body = _json(login)
        if login.status_code != 200 or not isinstance(login_body, dict) or login_body.get("error"):
            reason = _error_text(login_body, f"status {login.status_code}")
            logger.error(f"Nuvama logindata failed: {reason}")
            if login.status_code == 222:
                return (
                    None,
                    None,
                    None,
                    "The Nuvama login link expired before it was used. Log in again.",
                )
            return None, None, None, "Nuvama did not complete the login. Log in again."

        data = login_body.get("data") or {}
        auth = data.get("auth")
        lgn = data.get("lgnData") or {}
        accs = lgn.get("accs") or {}
        account_type = lgn.get("accTyp") or ""
        # The SDK uses eqAccId, or coAccId for a commodity-only account.
        account_id = accs.get("eqAccID") or accs.get("coAccID")
        if not auth or not account_id:
            logger.error("Nuvama logindata answered without a session or an account id")
            return None, None, None, "Nuvama did not complete the login. Log in again."

        app_id_key = login.headers.get("AppIdKey") or app_id_key
        session = NuvamaSession(auth, source_token, app_id_key, account_id, account_type, api_key)
        logger.info(f"Nuvama login completed for account type {account_type or 'unknown'}")
        return session.pack(), None, account_id, None

    except Exception:
        logger.exception("Nuvama login failed")
        return None, None, None, "Nuvama could not be reached to complete the login. Try again."
