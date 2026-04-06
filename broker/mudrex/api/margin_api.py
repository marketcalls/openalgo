"""
Mudrex margin calculation module.

Mudrex does not expose a margin-preview endpoint.  This module exists so
that ``services/margin_service.py`` can import it without breaking.
"""

from utils.logging import get_logger

logger = get_logger(__name__)


class _MockResponse:
    def __init__(self, code: int = 200):
        self.status_code = code
        self.status = code


def calculate_margin_api(positions: list, auth: str):
    """Return a structured 'not supported' response.

    The module must be importable and callable; Mudrex does not offer a
    pre-trade margin preview API.
    """
    logger.info("[Mudrex] calculate_margin_api: margin preview not supported")
    return _MockResponse(200), {
        "status": "success",
        "data": {
            "total_margin": "0.00",
            "margin_breakdown": [],
            "message": "Margin preview not supported on Mudrex. Use the exchange UI.",
        },
    }
