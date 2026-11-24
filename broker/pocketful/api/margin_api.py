"""Margin for one position or a basket through Pocketful's margin calculator.

POST /api/space/v1/orderapis/marginCalculations (Pocketful docs, "Margin
Calculator"). It is one endpoint for a single order and a multi-leg basket:
every leg goes in one request, and the answer's ``combinedMargin`` already
nets spreads and hedges, so legs are never priced one by one and summed here.
The official SDK 0.1.2 has no route for this endpoint; the docs are the only
source.

Headers. The docs send ``Authorization: Bearer``, which pocketful_request
carries, and a ``clientid`` header holding the trading client id, which it
cannot add (it takes no extra headers). The client id is still checked here
so a session without one is refused before anything is sent.

Contract (services/margin_service.py): ``calculate_margin_api(positions, auth)``
returns ``(response, data)``. The service treats HTTP 200 as success and reads
``data["message"]`` otherwise, so a refusal Pocketful answers with HTTP 200
(``"status": false``) is returned with a 400, and an answer that is not JSON
with a 502.
"""

from broker.pocketful.api.baseurl import client_id, pocketful_request
from broker.pocketful.mapping.gtt_data import broker_reason
from broker.pocketful.mapping.margin_data import (
    MarginRefused,
    build_margin_leg,
    parse_margin_response,
)
from utils.logging import get_logger

logger = get_logger(__name__)

MARGIN_PATH = "/api/space/v1/orderapis/marginCalculations"

UNREADABLE = (
    "Pocketful's margin calculator sent an answer OpenAlgo could not read. Try again in a moment."
)


class MarginAnswer:
    """The response object the margin service reads its status from."""

    def __init__(self, status_code):
        self.status_code = status_code
        self.status = status_code


def _error(status_code, message):
    return MarginAnswer(status_code), {"status": "error", "message": message}


def calculate_margin_api(positions, auth, api_key=None):
    """Margin required for ``positions`` (OpenAlgo format), as one basket.

    Args:
        positions: validated positions from services/margin_service.
        auth: the stored Pocketful token.
        api_key: unused; kept for the signature other plugins share.

    Returns:
        (response, data) with ``data["data"]`` holding total_margin_required,
        span_margin and exposure_margin.
    """
    account = client_id(auth)
    if not account:
        return _error(
            400,
            "Your Pocketful session carries no client id. Log in to Pocketful again and retry.",
        )

    legs = []
    for position in positions or []:
        try:
            legs.append(build_margin_leg(position))
        except MarginRefused as refusal:
            # The whole basket is refused: pricing it without one leg would
            # drop that leg's hedge and report a margin that is not the basket's.
            logger.info(f"Pocketful margin request refused: {refusal}")
            return _error(400, str(refusal))

    if not legs:
        return _error(400, "There are no positions to calculate margin for.")

    logger.info(f"Pocketful margin request: {len(legs)} leg(s)")
    try:
        # margin-calculator.md lists a clientid header beside the session's own.
        response = pocketful_request(
            "POST", MARGIN_PATH, auth, payload={"data": legs}, headers={"clientid": account}
        )
    except Exception:
        logger.exception("Pocketful margin request failed")
        return _error(
            502,
            "Pocketful's margin calculator did not answer. Check your connection and try again.",
        )

    if response.data is None:
        logger.error(
            f"Pocketful margin answered {response.status_code} with a body that is not JSON"
        )
        return _error(502, UNREADABLE)

    if not response.ok:
        reason = broker_reason(response.message)
        logger.error(f"Pocketful margin refused: HTTP {response.status_code}, {response.message!r}")
        status = response.status_code if response.status_code >= 400 else 400
        return _error(
            status,
            f"Pocketful could not calculate the margin: {reason}"
            if reason
            else "Pocketful could not calculate the margin. Check the positions and try again.",
        )

    parsed = parse_margin_response(response.payload)
    if parsed is None:
        logger.error("Pocketful margin answer has no combinedMargin block")
        return _error(502, UNREADABLE)

    return MarginAnswer(200), parsed
