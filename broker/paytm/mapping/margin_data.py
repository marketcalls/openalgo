# Mapping OpenAlgo API Request https://openalgo.in/docs
# Paytm Money does not provide position-specific Margin Calculator API

from utils.logging import get_logger

logger = get_logger(__name__)


def transform_margin_positions(positions):
    """
    Transform OpenAlgo margin position format to broker format.

    Note: Paytm Money does not provide a position-specific margin calculator API.
    The available Margin API only returns account-level margin information.

    Args:
        positions: List of positions in OpenAlgo format

    Raises:
        NotImplementedError: Paytm Money does not support position-specific margin calculator API
    """
    raise NotImplementedError(
        "Paytm Money does not support position-specific margin calculator API"
    )


def parse_margin_response(response_data):
    """
    Parse broker margin calculator response to OpenAlgo standard format.

    Note: Paytm Money does not provide a position-specific margin calculator API.
    The available Margin API only returns account-level margin information.

    Args:
        response_data: Raw response from broker margin calculator API

    Raises:
        NotImplementedError: Paytm Money does not support position-specific margin calculator API
    """
    raise NotImplementedError(
        "Paytm Money does not support position-specific margin calculator API"
    )
