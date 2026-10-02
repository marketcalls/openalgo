"""Utilities for building HTTP responses."""

from flask import Response, make_response
from flask.typing import ResponseReturnValue


def make_no_store_response(response: ResponseReturnValue) -> Response:
    """Return a response with browser and intermediary storage disabled.

    Args:
        response: Any value accepted by Flask's ``make_response``.

    Returns:
        A Flask response carrying modern and legacy no-cache headers.
    """
    no_store_response = make_response(response)
    no_store_response.headers["Cache-Control"] = "no-store, max-age=0"
    no_store_response.headers["Pragma"] = "no-cache"
    return no_store_response
