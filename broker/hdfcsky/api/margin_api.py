# broker/hdfcsky/api/margin_api.py
#
# Margin calculation via HDFC Sky's POST /oapi/v1/margin.
#
# Unlike brokers that split single-order and basket calculators, HDFC Sky has
# ONE endpoint that takes an array of legs and returns both a portfolio-netted
# `combined_margin` and per-leg `individual_margin_values`. A multi-leg request
# therefore already carries the broker's spread/hedge benefit -- legs are never
# summed client-side when the combined block is populated.
#
# Contract (services/margin_service): calculate_margin_api(positions, auth)
# -> (response, data), where `response` exposes .status / .status_code.

import json

from broker.hdfcsky.api.baseurl import base_params, get_hdfcsky_headers, get_root_url
from broker.hdfcsky.api.data import _series_type
from broker.hdfcsky.database.master_contract_db import SymToken, db_session
from broker.hdfcsky.mapping.margin_data import build_margin_leg, parse_margin_response
from broker.hdfcsky.mapping.transform_data import to_ltp_exchange
from database.token_db import get_br_symbol
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


class BrokerResponse:
    """Small response-compatible object used for local validation failures."""

    def __init__(self, status_code):
        self.status_code = status_code
        self.status = status_code


def _normalise_success_response(response, response_data):
    """Keep services.margin_service status handling aligned with response_data.

    The margin service treats any broker HTTP 200 as success, so an error
    payload delivered with HTTP 200 must be converted into a non-200
    response-like object.
    """
    if (
        getattr(response, "status_code", None) == 200
        and isinstance(response_data, dict)
        and response_data.get("status") == "error"
    ):
        return BrokerResponse(400), response_data
    return response, response_data


def _lookup_rows(positions):
    """Resolve every position to its master-contract row, dropping unknowns."""
    resolved = []
    with db_session() as session:
        for position in positions:
            symbol = position.get("symbol")
            exchange = position.get("exchange")
            try:
                br_symbol = get_br_symbol(symbol, exchange)
                row = (
                    session.query(SymToken)
                    .filter(SymToken.exchange == exchange, SymToken.brsymbol == br_symbol)
                    .first()
                )
            except Exception as e:
                logger.warning(f"Margin: could not resolve {exchange}:{symbol}: {e}")
                continue
            if not row:
                logger.warning(f"Margin: no instrument found for {exchange}:{symbol}")
                continue
            session.expunge(row)
            resolved.append((position, row))
    return resolved


def _underlying_prices(auth, resolved):
    """Last traded price of each leg's underlying, keyed by (exchange, token).

    `underlying` is the spot PRICE of the leg's underlying, not its instrument
    id -- confirmed live: the calculator only computes a real margin when it
    receives the integer spot (e.g. NIFTY ~23767), and build_margin_leg rounds
    it to a whole number for that reason. One batched /fetch-ltp covers every
    distinct underlying; failures degrade to 0, which the calculator tolerates.
    """
    from broker.hdfcsky.api.data import BrokerData

    wanted = {}
    with db_session() as session:
        for _position, row in resolved:
            if row.instrumenttype == "EQ" or not row.name:
                continue
            # The underlying trades on the cash market of the same group:
            # NFO/NSE_INDEX legs resolve against NSE, BFO legs against BSE.
            for underlying_exchange in _underlying_exchanges(row.exchange):
                match = (
                    session.query(SymToken)
                    .filter(
                        SymToken.exchange == underlying_exchange, SymToken.symbol == row.name
                    )
                    .first()
                )
                if match:
                    # Index underlyings must be addressed as NSE_INDEX /
                    # BSE_INDEX here: fetch-ltp silently omits them when they
                    # are sent as the parent cash exchange, which would leave
                    # every index leg's underlying price at zero.
                    wanted[(row.exchange, row.brsymbol)] = (
                        to_ltp_exchange(match.exchange),
                        str(match.token),
                    )
                    break

    if not wanted:
        return {}

    try:
        instruments = [
            {"exchange": exchange, "token": token}
            for exchange, token in dict.fromkeys(wanted.values())
        ]
        quotes = BrokerData(auth)._fetch_ltp(instruments)
    except Exception as e:
        logger.debug(f"Could not fetch underlying prices for margin: {e}")
        return {}

    return {leg: quotes.get(key, {}).get("ltp", 0.0) for leg, key in wanted.items()}


def _underlying_exchanges(exchange):
    """Cash/index exchanges where a derivative's underlying may be listed."""
    if exchange == "NFO":
        return ("NSE_INDEX", "NSE")
    if exchange == "BFO":
        return ("BSE_INDEX", "BSE")
    return ()


def calculate_margin_api(positions, auth, api_key=None):
    """Calculate the margin requirement for one or more positions.

    Args:
        positions: list of positions in OpenAlgo format
        auth: HDFC Sky access token
        api_key: OpenAlgo API key (unused; present for interface parity)

    Returns:
        (response, response_data)
    """
    resolved = _lookup_rows(positions or [])
    if not resolved:
        return BrokerResponse(400), {
            "status": "error",
            "message": "No valid positions to calculate margin. Check if symbols are valid.",
        }

    underlyings = _underlying_prices(auth, resolved)
    legs = [
        build_margin_leg(
            position, row, _series_type(row), underlyings.get((row.exchange, row.brsymbol), 0.0)
        )
        for position, row in resolved
    ]
    logger.info(f"HDFC Sky margin request: {len(legs)} leg(s)")

    try:
        client = get_httpx_client()
        response = client.post(
            f"{get_root_url()}/oapi/v1/margin",
            headers=get_hdfcsky_headers(auth, with_json=True),
            params=base_params(auth, client_id=False),
            json={"data": legs},
        )
        response.status = response.status_code
    except Exception as e:
        logger.exception(f"Error calling HDFC Sky margin API: {e}")
        return BrokerResponse(500), {
            "status": "error",
            "message": f"Failed to calculate margin: {e}",
        }

    try:
        payload = response.json()
    except (json.JSONDecodeError, ValueError):
        logger.error(f"Non-JSON response from HDFC Sky margin API: {response.text[:200]}")
        return BrokerResponse(502), {
            "status": "error",
            "message": "Invalid response from broker API",
        }

    # Two error shapes exist: the standard {"status": "error", ...} envelope
    # and the calculator's own {"error": {"code": n, "message": "..."}}.
    error_block = payload.get("error") or {}
    if payload.get("status") == "error" or error_block.get("code"):
        message = (
            error_block.get("message")
            or payload.get("message")
            or "Failed to calculate margin"
        )
        return _normalise_success_response(response, {"status": "error", "message": message})

    return response, parse_margin_response(payload.get("result") or {})
