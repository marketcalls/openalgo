# Mapping OpenAlgo API Request https://openalgo.in/docs
# Mapping Motilal Oswal Margin API - See Motilal_Oswal.md documentation
# Note: Motilal Oswal does not provide a margin calculator API.

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
    return {
        'status': 'error',
        'message': 'Motilal Oswal does not support margin calculator API'
    }
