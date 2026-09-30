"""What a read-only data service returns when a broker request was refused as busy.

Under the gthread worker a broker plugin's rate limiter refuses a request whose
turn would come too late, instead of parking one of the fixed request threads
for the whole wait. It does that by raising
:class:`utils.broker_backpressure.BrokerBusyError`, whose text is already a
sentence a trader can act on. The data services (quotes, depth, history,
funds, holdings, trade book, margin, option chain, Greeks) answer it with HTTP
429 and that sentence, rather than the 500 "internal error" a generic
exception handler would produce.

Under eventlet and the development server nothing raises BrokerBusyError, so
none of this is reachable there and those workers behave exactly as before.
"""

from __future__ import annotations

from typing import Any

from utils.broker_backpressure import BROKER_BUSY_MESSAGE, BrokerBusyError
from utils.logging import get_logger

logger = get_logger(__name__)

#: The HTTP status for a request refused because the broker queue was full.
BROKER_BUSY_STATUS = 429

__all__ = [
    "BROKER_BUSY_MESSAGE",
    "BROKER_BUSY_STATUS",
    "BrokerBusyError",
    "broker_busy_result",
    "is_broker_busy",
]


def broker_busy_result(error: BaseException, what: str) -> tuple[bool, dict[str, Any], int]:
    """Build the (success, response, status) a data service returns for a busy refusal.

    Args:
        error: The BrokerBusyError that refused the request.
        what: A short name for the request, used in the log line only.

    Returns:
        ``(False, {"status": "error", "message": ...}, 429)`` carrying the
        exception's trader-facing text.
    """
    message = str(error) or BROKER_BUSY_MESSAGE
    logger.warning(f"{what} refused while waiting for the broker's rate limit: {message}")
    return False, {"status": "error", "message": message}, BROKER_BUSY_STATUS


def is_broker_busy(status_code: Any) -> bool:
    """Return True when a data service's status code is the busy refusal."""
    return status_code == BROKER_BUSY_STATUS
