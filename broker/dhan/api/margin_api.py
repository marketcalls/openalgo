import json
import os

from broker.dhan.api.baseurl import get_url
from broker.dhan.mapping.margin_data import parse_margin_response, transform_margin_position
from database.auth_db import get_user_id, verify_api_key
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


class BrokerResponse:
    """Small response-compatible object used for local validation failures."""

    def __init__(self, status_code):
        self.status_code = status_code
        self.status = status_code


def get_client_id(api_key=None):
    """
    Get Dhan client ID from BROKER_API_KEY or database.

    Args:
        api_key: OpenAlgo API key (optional)

    Returns:
        Client ID string or None
    """
    broker_api_key = os.getenv("BROKER_API_KEY")

    if broker_api_key and ":::" in broker_api_key:
        client_id, _ = broker_api_key.split(":::", 1)
        return client_id

    if api_key:
        user_id = verify_api_key(api_key)
        if user_id:
            return get_user_id(user_id)

    return None


def _normalise_success_response(response, response_data):
    """
    Keep services.margin_service status handling aligned with response_data.

    The RESTX margin service currently treats any broker HTTP 200 as success.
    Dhan can send error payloads with HTTP 200, so convert those local parser
    failures into a non-200 response-like object.
    """
    if (
        getattr(response, "status_code", None) == 200
        and isinstance(response_data, dict)
        and response_data.get("status") == "error"
    ):
        return BrokerResponse(400), response_data
    return response, response_data


def calculate_single_margin(position_data, auth, client_id):
    """
    Calculate margin for a single position using Dhan API.

    Args:
        position_data: Transformed position data in Dhan format
        auth: Authentication token
        client_id: Dhan client ID

    Returns:
        Tuple of (response, parsed_response_data)
    """
    headers = {
        "access-token": auth,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    if client_id:
        headers["client-id"] = client_id

    payload = json.dumps(position_data)
    logger.info(
        "Dhan single margin request: exchange=%s qty=%s product=%s",
        position_data.get("exchangeSegment"),
        position_data.get("quantity"),
        position_data.get("productType"),
    )

    client = get_httpx_client()

    try:
        url = get_url("/v2/margincalculator")
        response = client.post(url, headers=headers, content=payload)
        response.status = response.status_code

        try:
            response_data = response.json()
        except json.JSONDecodeError:
            logger.error(f"Failed to parse JSON response from Dhan: {response.text}")
            return BrokerResponse(502), {
                "status": "error",
                "message": "Invalid response from broker API",
            }

        logger.debug(
            "Dhan single margin response status=%s keys=%s",
            response.status_code,
            list(response_data.keys())
            if isinstance(response_data, dict)
            else type(response_data).__name__,
        )

        parsed_response = parse_margin_response(response_data)
        return _normalise_success_response(response, parsed_response)

    except Exception as e:
        logger.exception(f"Error calling Dhan margin API: {e}")
        return BrokerResponse(500), {
            "status": "error",
            "message": f"Failed to calculate margin: {str(e)}",
        }


def _broker_error_message(response_data):
    """Return broker error text when Dhan sends an error payload."""
    if not isinstance(response_data, dict):
        return None

    status = str(response_data.get("status", "")).lower()
    if response_data.get("errorType") or status in {"error", "failed", "failure"}:
        return str(
            response_data.get("errorMessage")
            or response_data.get("message")
            or response_data.get("errors")
            or response_data.get("error")
            or "Dhan margin API returned an error"
        )

    return None


def _pick_float(data, *keys):
    """Return the first parseable numeric value under the given keys."""
    for key in keys:
        value = data.get(key)
        if value is None or value == "":
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return 0.0


def parse_basket_margin_response(response_data):
    """
    Parse Dhan multi-margin response into the standard RESTX margin shape.

    Dhan's docs show snake_case keys for the multi endpoint. Live responses
    can use camelCase. Accept both and expose OpenAlgo's common margin fields.
    """
    try:
        if not response_data or not isinstance(response_data, dict):
            return {"status": "error", "message": "Invalid response from broker"}

        error_message = _broker_error_message(response_data)
        if error_message:
            return {"status": "error", "message": error_message}

        total_margin = _pick_float(response_data, "total_margin", "totalMargin")
        span_margin = _pick_float(response_data, "span_margin", "spanMargin")
        exposure_margin = _pick_float(
            response_data, "exposure_margin", "exposureMargin", "exposure"
        )

        return {
            "status": "success",
            "data": {
                "total_margin_required": total_margin,
                "span_margin": span_margin,
                "exposure_margin": exposure_margin,
            },
        }

    except Exception as e:
        logger.error(f"Error parsing Dhan basket margin response: {e}")
        return {
            "status": "error",
            "message": f"Failed to parse basket margin response: {str(e)}",
        }


def calculate_basket_margin(positions_data, auth, client_id):
    """
    Calculate margin using Dhan /v2/margincalculator/multi.

    Returns the same two-tuple shape as calculate_single_margin:
    (response_like, standardized_response).
    """
    headers = {
        "access-token": auth,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if client_id:
        headers["client-id"] = client_id

    payload = {
        "dhanClientId": client_id,
        "includePosition": True,
        "includeOrder": True,
        "scripList": positions_data,
    }

    logger.info("Dhan basket margin request: positions=%s", len(positions_data))

    client = get_httpx_client()

    try:
        url = get_url("/v2/margincalculator/multi")
        response = client.post(url, headers=headers, content=json.dumps(payload))
        response.status = response.status_code

        try:
            response_data = response.json()
        except json.JSONDecodeError:
            logger.error(f"Failed to parse Dhan basket margin response: {response.text}")
            return BrokerResponse(502), {
                "status": "error",
                "message": "Invalid response from broker API",
            }

        logger.debug(
            "Dhan basket margin response status=%s keys=%s",
            response.status_code,
            list(response_data.keys())
            if isinstance(response_data, dict)
            else type(response_data).__name__,
        )

        parsed_response = parse_basket_margin_response(response_data)
        return _normalise_success_response(response, parsed_response)

    except Exception as e:
        logger.exception(f"Error calling Dhan basket margin API: {e}")
        return BrokerResponse(500), {
            "status": "error",
            "message": f"Failed to calculate basket margin: {str(e)}",
        }


def calculate_margin_api(positions, auth, api_key=None):
    """
    Calculate margin requirement for positions using Dhan API.

    One position is sent to Dhan's single-order calculator. Two or more
    positions are sent to Dhan's multi-order calculator so spread/hedge
    benefits are included by the broker.

    Args:
        positions: List of positions in OpenAlgo format
        auth: Authentication token for Dhan
        api_key: OpenAlgo API key (optional, for client ID lookup)

    Returns:
        Tuple of (response, response_data)
    """
    client_id = get_client_id(api_key)

    if not client_id:
        logger.error("Could not determine Dhan client ID")
        return BrokerResponse(400), {
            "status": "error",
            "message": (
                "Could not determine Dhan client ID. Please ensure BROKER_API_KEY "
                "is configured correctly."
            ),
        }

    transformed_positions = []
    skipped_count = 0

    for position in positions:
        transformed = transform_margin_position(position, client_id)
        if transformed:
            transformed_positions.append(transformed)
        else:
            skipped_count += 1

    if not transformed_positions:
        return BrokerResponse(400), {
            "status": "error",
            "message": "No valid positions to calculate margin. Check if symbols are valid.",
        }

    if skipped_count > 0:
        logger.warning(f"Skipped positions (invalid/missing symbols): {skipped_count}")

    if len(transformed_positions) == 1:
        logger.info("Dhan margin route: single-order calculator")
        return calculate_single_margin(transformed_positions[0], auth, client_id)

    logger.info(
        "Dhan margin route: multi-order calculator for %s positions",
        len(transformed_positions),
    )
    return calculate_basket_margin(transformed_positions, auth, client_id)
