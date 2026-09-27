# Mapping OpenAlgo API Request https://openalgo.in/docs
# Mapping Motilal Oswal Margin API
# See broker-api-docs/motilaloswal-api-docs/ (docs 24 margin summary,
# 25 margin detail).
#
# Note: Motilal Oswal does not provide a margin calculator API — no such
# endpoint exists anywhere in the documentation set. The functions below are
# kept only so the module surface matches other brokers; the real refusal is
# raised by broker/motilal/api/margin_api.py:calculate_margin_api, which
# services/margin_service.py turns into an HTTP 501.

from utils.logging import get_logger

logger = get_logger(__name__)


def transform_margin_positions(positions):
    """
    Transform OpenAlgo margin position format to Motilal Oswal margin format.

    Note: Motilal Oswal does not provide a margin calculator API.
    This function is a placeholder for API consistency.

    Args:
        positions: List of positions in OpenAlgo format

    Returns:
        Empty list (API not supported)
    """
    logger.warning("Motilal Oswal does not provide margin calculator API")
    return []


def parse_margin_response(response_data):
    """
    Parse margin response.

    Note: Motilal Oswal does not provide a margin calculator API.
    This function is a placeholder for API consistency.

    Args:
        response_data: Response data

    Returns:
        Error dict (API not supported)
    """
    return {"status": "error", "message": "Motilal Oswal does not support margin calculator API"}
