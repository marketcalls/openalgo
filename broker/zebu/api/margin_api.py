from utils.logging import get_logger

logger = get_logger(__name__)


def calculate_margin_api(positions, auth):
    """
    Calculate margin requirement for a basket of positions.

    Note: Zebu does not provide a position-specific margin calculator API.
    The available Margin API only returns account-level margin information,
    which is not suitable for calculating margin requirements for specific positions.

    Args:
        positions: List of positions in OpenAlgo format
        auth: Authentication token for Zebu

    Raises:
        NotImplementedError: Zebu does not support position-specific margin calculator API
    """
    logger.warning("Zebu does not provide position-specific margin calculator API")
    raise NotImplementedError("Zebu does not support position-specific margin calculator API")
