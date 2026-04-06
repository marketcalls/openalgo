"""
Mudrex authentication module.

Mudrex uses a single API secret passed via the ``X-Authentication`` header —
no OAuth flow, no TOTP, no redirect.  The secret is validated by making a
``POST /wallet/funds`` call; a 200 with ``"success": true`` confirms
the key is live and active.
"""

import os

from broker.mudrex.api.mudrex_http import mudrex_request
from utils.logging import get_logger

logger = get_logger(__name__)


def authenticate_broker(code: str | None = None) -> tuple[str | None, str | None]:
    """Validate the Mudrex API secret and return it for encrypted storage.

    Follows the same ``(auth_token, error_message)`` contract used by all
    OpenAlgo broker ``authenticate_broker`` functions.

    **Secret source (in order):**

    1. ``code`` when it is the API secret from the login form (``brlogin`` POST
       passes ``request.form["api_secret"]``).
    2. ``BROKER_API_SECRET`` environment variable (same pattern as Delta Exchange
       for server-only / headless setups).  If ``code`` is the placeholder
       ``"mudrex"``, only the env var is used.

    Returns:
        ``(api_secret, None)`` on success.
        ``(None, error_message)`` on failure.
    """
    try:
        api_secret = ""
        if code and str(code).strip() and str(code).strip() != "mudrex":
            api_secret = str(code).strip()
        if not api_secret:
            api_secret = os.getenv("BROKER_API_SECRET", "").strip()
        if not api_secret:
            return None, "Provide API secret in the login form or set BROKER_API_SECRET in .env"

        logger.info("Validating Mudrex API secret via POST /wallet/funds")
        data = mudrex_request("/wallet/funds", method="POST", auth=api_secret)

        if data.get("success") is True:
            logger.info("Mudrex authentication successful")
            return api_secret, None

        msg = data.get("message") or data.get("error") or str(data)
        logger.error(f"Mudrex authentication failed: {msg}")
        return None, f"Mudrex API secret validation failed: {msg}"

    except Exception as exc:
        logger.exception(f"Exception during Mudrex authentication: {exc}")
        return None, f"An exception occurred: {exc}"
