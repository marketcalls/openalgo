"""One place that decides why a broker credential could not be resolved.

``database.auth_db.get_auth_token_broker()`` answers ``(None, None)`` for four
different situations, and the tuple cannot carry which one it was:

1. the OpenAlgo API key is not recognised;
2. the stored broker token was revoked (logout, or the auto-expiry sweep);
3. the broker was never connected on this install, so no row exists;
4. the broker session belongs to a previous trading session (issue #1858).

Only the first is a problem with the API key. Reporting all four as
"Invalid openalgo apikey" sends the operator to regenerate a key that is fine,
and regenerating cannot help: cases 2 to 4 are answered from the broker session,
not from the key. Case 4 happens every morning at SESSION_EXPIRY_TIME.

The distinction is one question, ``verify_api_key``, which reads the API-key
table and never touches the broker token. Keeping it here rather than inline
means every caller of ``get_auth_token_broker`` answers identically, and a
service added later inherits the behaviour by copying one line.
"""

from typing import Any

from database.auth_db import verify_api_key
from utils.logging import get_logger

logger = get_logger(__name__)

INVALID_API_KEY_MESSAGE = "Invalid openalgo apikey"
BROKER_SESSION_EXPIRED_MESSAGE = "Broker session expired - please reconnect your broker"


def credential_error(api_key: str) -> tuple[dict[str, Any], int]:
    """Explain an unresolved credential as ``(payload, http_status)``.

    Call this only when ``get_auth_token_broker()`` returned no token.

    Args:
        api_key: The API key the caller supplied.

    Returns:
        ``({"status": "error", "message": ...}, 403)`` when the key itself is
        not recognised, or ``({"status": "error", "code":
        "BROKER_SESSION_EXPIRED", ...}, 401)`` when the key is valid and the
        broker session is what is missing. The 401 code is the one the dashboard
        already keys off (#1400).
    """
    if verify_api_key(api_key):
        return (
            {
                "status": "error",
                "code": "BROKER_SESSION_EXPIRED",
                "message": BROKER_SESSION_EXPIRED_MESSAGE,
            },
            401,
        )

    return {"status": "error", "message": INVALID_API_KEY_MESSAGE}, 403
