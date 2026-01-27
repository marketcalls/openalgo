# Mapping OpenAlgo API Request https://openalgo.in/docs
# Firstock does not provide position-specific Margin Calculator API

from utils.logging import get_logger

logger = get_logger(__name__)


def transform_margin_position(position, user_id):
    """
    Transform a single OpenAlgo margin position to broker format.

    Note: Firstock does not provide a position-specific margin calculator API.
    The available Limit API only returns account-level margin information.

    Args:
        position: Position in OpenAlgo format
        user_id: Firstock user ID

    Raises:
        NotImplementedError: Firstock does not support position-specific margin calculator API
    """
    raise NotImplementedError("Firstock does not support position-specific margin calculator API")


def parse_margin_response(response_data):
    """
    Parse broker margin calculator response to OpenAlgo standard format.

    Note: Firstock does not provide a position-specific margin calculator API.
    The available Limit API only returns account-level margin information.

    Args:
        response_data: Raw response from broker margin calculator API

    Raises:
        NotImplementedError: Firstock does not support position-specific margin calculator API
    """
    raise NotImplementedError("Firstock does not support position-specific margin calculator API")


def parse_batch_margin_response(responses):
    """
    Parse multiple margin responses and aggregate them.

    Note: Firstock does not provide a position-specific margin calculator API.

    Args:
        responses: List of individual margin responses

    Raises:
        NotImplementedError: Firstock does not support position-specific margin calculator API
    """
    raise NotImplementedError("Firstock does not support position-specific margin calculator API")
