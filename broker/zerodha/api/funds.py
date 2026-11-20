"""Kite cash balances and P&L from the account's own position snapshot."""

import math
import time

import httpx

from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


def _number(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("non-finite Kite amount")
    return number


def _get_data(client, path, headers, deadline):
    url = f"https://api.kite.trade/{path}"
    for attempt in range(2):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise httpx.ReadTimeout("Kite funds read budget expired")
        try:
            response = client.get(
                url,
                headers=headers,
                timeout=min(1.0, remaining),
                extensions={"openalgo_retry_read": False},
            )
            response.raise_for_status()
            break
        except httpx.HTTPStatusError as exc:
            if attempt or exc.response.status_code not in (502, 503, 504):
                raise
        except (
            httpx.ConnectTimeout,
            httpx.ReadTimeout,
            httpx.NetworkError,
            httpx.RemoteProtocolError,
        ):
            if attempt:
                raise
    body = response.json()
    if (
        not isinstance(body, dict)
        or body.get("status") != "success"
        or not isinstance(body.get("data"), dict)
    ):
        raise ValueError("invalid Kite response")
    return body["data"]


def _position_pnl(positions):
    if not isinstance(positions, list):
        raise ValueError("missing Kite net positions")
    realised = unrealised = 0.0
    realised_known = True
    for position in positions:
        qty = _number(position["quantity"])
        if qty == 0:
            # Closed quantities have no open P&L. Both turnover fields are
            # already in rupees, even for MCX contracts.
            if position.get("pnl") is not None:
                realised += _number(position["pnl"])
            else:
                realised += _number(position["sell_value"]) - _number(position["buy_value"])
            continue

        # The positions endpoint includes its own last price. Fetching /quote/ltp
        # here requires a separate market-data entitlement. Multiplier is Kite's
        # P&L multiplier (which can differ from the physical contract size).
        last = _number(position["last_price"])
        average = _number(position["average_price"])
        raw_multiplier = position.get("multiplier")
        multiplier = 1 if raw_multiplier is None else _number(raw_multiplier)
        if last <= 0 or average <= 0 or multiplier <= 0:
            raise ValueError("missing Kite position price or multiplier")
        open_pnl = (last - average) * qty * multiplier
        unrealised += open_pnl
        # Net P&L includes any earlier partial close. Kite's 'realised' and
        # 'unrealised' intraday fields do not split booked/open P&L this way.
        if position.get("pnl") is None:
            realised_known = False
        else:
            realised += _number(position["pnl"]) - open_pnl
    return f"{realised:.2f}" if realised_known else None, f"{unrealised:.2f}"


def get_margin_data(auth_token):
    client = get_httpx_client()
    headers = {"X-Kite-Version": "3", "Authorization": f"token {auth_token}"}
    # Interactive clients allow three seconds. Both GETs share one retry
    # window and return promptly if the optional positions read runs out of it.
    deadline = time.monotonic() + 2.4
    try:
        margins = _get_data(client, "user/margins", headers, deadline)
        segments = (margins["equity"], margins["commodity"])
        used = sum(_number(s["utilised"]["debits"]) for s in segments)
        collateral = sum(_number(s["available"]["collateral"]) for s in segments)
        net = sum(_number(s["net"]) for s in segments)
        # available.cash may be zero on funded accounts. Preserve the existing
        # cash identity from Kite's net, debits and collateral (#1582).
        cash = net + used - collateral
    except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
        logger.error("Kite margins unavailable (%s)", _error_kind(exc))
        return {}

    try:
        positions = _get_data(client, "portfolio/positions", headers, deadline)
        realised, unrealised = _position_pnl(positions["net"])
    except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
        logger.warning("Kite position P&L unavailable (%s)", _error_kind(exc))
        realised = unrealised = None

    return {
        "availablecash": f"{cash:.2f}",
        "collateral": f"{collateral:.2f}",
        "m2munrealized": unrealised,
        "m2mrealized": realised,
        "utiliseddebits": f"{used:.2f}",
    }


def _error_kind(exc):
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}"
    return type(exc).__name__
