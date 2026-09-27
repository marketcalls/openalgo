"""Margin calculator for Motilal Oswal (MOFSL) — not offered by the broker.

Verified against the full API documentation set
(broker-api-docs/motilaloswal-api-docs/, 44 pages): there is no basket/order
margin calculator endpoint. The only margin endpoints are the reports
``/rest/report/v3/getreportmarginsummary`` (doc 24) and
``/rest/report/v3/getreportmargindetail`` (doc 25), which report the account's
current margin position and cannot price a hypothetical basket.

``services/margin_service.py`` converts the ``NotImplementedError`` raised here
into a clean ``501`` response, so raising is the supported way to decline.
"""

from utils.logging import get_logger

logger = get_logger(__name__)


def calculate_margin_api(positions, auth):
    """
    Calculate margin requirement for a basket of positions.

    Note: Motilal Oswal does not provide a margin calculator API.

    Args:
        positions: List of positions in OpenAlgo format
        auth: Authentication token for Motilal Oswal

    Raises:
        NotImplementedError: Motilal Oswal does not support margin calculator API
            (handled as HTTP 501 by services/margin_service.py).
    """
    logger.warning("Motilal Oswal does not provide margin calculator API")
    raise NotImplementedError("Motilal Oswal does not support margin calculator API")
