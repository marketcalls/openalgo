from utils.logging import get_logger

logger = get_logger(__name__)

def calculate_margin_api(positions, auth):
    """
    Calculate margin requirement for a basket of positions.

    Note: Wisdom does not provide a margin calculator API.

    Args:
        positions: List of positions in OpenAlgo format
        auth: Authentication token for Wisdom

    Raises:
        NotImplementedError: Wisdom does not support margin calculator API
    """
    logger.warning("Wisdom does not provide margin calculator API")
    raise NotImplementedError("Wisdom does not support margin calculator API")
