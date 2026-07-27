"""Futures calendar-spread arbitrage universe service.

Builds the static contract universe consumed by the ``/arbitrage`` realtime
scanner. For every underlying that has futures on the requested exchanges
(default NFO and MCX) it identifies the three nearest monthly contracts
(near / next / third month) and forms calendar pairs:

- ``near-next``  : nearest month vs next month
- ``near-third`` : nearest month vs third month

Only the contract metadata is returned here. Live bid/ask prices and the
spread percentage are computed on the client from the shared market-data
WebSocket, so this service performs pure database/cache reads and never
calls the broker (no new file descriptors).
"""

from datetime import datetime
from typing import Any

from database.token_db_enhanced import fno_search_symbols
from utils.logging import get_logger

logger = get_logger(__name__)

# Calendar arbitrage uses the three nearest monthly futures per underlying.
MAX_LEGS = 3
DEFAULT_EXCHANGES = ("NFO", "MCX")
SUPPORTED_EXCHANGES = ("NFO", "MCX", "BFO", "CDS")


def _parse_expiry(expiry: str) -> datetime:
    """Parse an expiry string into a datetime for chronological sorting.

    Mirrors the parsing used by ``database.symbol.get_distinct_expiries`` so
    ordering is consistent with the rest of the platform. Unparseable values
    sort last.

    Args:
        expiry: Expiry date string such as ``30-JUN-26`` or ``30-JUN-2026``.

    Returns:
        Parsed ``datetime`` (``datetime.max`` when the value cannot be parsed).
    """
    if not expiry:
        return datetime.max
    for fmt in ("%d-%b-%y", "%d-%b-%Y"):
        try:
            return datetime.strptime(expiry.strip().upper(), fmt)
        except ValueError:
            continue
    return datetime.max


def _leg(contract: dict[str, Any]) -> dict[str, Any]:
    """Project a raw contract row into the compact leg shape sent to the UI."""
    return {
        "symbol": contract.get("symbol"),
        "exchange": contract.get("exchange"),
        "expiry": contract.get("expiry"),
        "lotsize": contract.get("lotsize"),
        "tick_size": contract.get("tick_size"),
    }


def _nearest_futures(exchange: str) -> dict[str, list[dict[str, Any]]]:
    """Return, per underlying, the chronologically nearest futures contracts.

    Args:
        exchange: Exchange code (e.g. ``NFO`` or ``MCX``).

    Returns:
        Mapping of underlying name to a list (length <= ``MAX_LEGS``) of
        contract dicts ordered near -> far.
    """
    rows = fno_search_symbols(exchange=exchange, instrumenttype="FUT", limit=50000)

    grouped: dict[str, dict[str, dict[str, Any]]] = {}
    for row in rows:
        symbol = (row.get("symbol") or "").upper()
        # Defensive: instrumenttype="FUT" already filters on the FUT suffix,
        # but guard against any non-future leaking in.
        if not symbol.endswith("FUT"):
            continue
        underlying = row.get("name")
        expiry = row.get("expiry")
        if not underlying or not expiry:
            continue
        # De-duplicate by symbol (cache + DB can both surface a row).
        grouped.setdefault(underlying, {})[symbol] = row

    nearest: dict[str, list[dict[str, Any]]] = {}
    for underlying, by_symbol in grouped.items():
        contracts = sorted(by_symbol.values(), key=lambda c: _parse_expiry(c.get("expiry")))
        nearest[underlying] = contracts[:MAX_LEGS]
    return nearest


def get_arbitrage_universe(
    exchanges: tuple[str, ...] | list[str] = DEFAULT_EXCHANGES,
    api_key: str | None = None,
) -> tuple[bool, dict[str, Any], int]:
    """Build the calendar-spread universe for the requested exchanges.

    Args:
        exchanges: Exchanges to scan. Unsupported codes are ignored.
        api_key: Accepted for interface symmetry with other services; unused
            because this is a pure master-contract lookup.

    Returns:
        Tuple ``(success, response, status_code)``. On success ``response`` is::

            {
                "status": "success",
                "message": "...",
                "data": {
                    "pairs": [
                        {
                            "id": "NFO:NIFTY:near-next",
                            "underlying": "NIFTY",
                            "exchange": "NFO",
                            "type": "near-next",
                            "near": {"symbol", "exchange", "expiry", "lotsize", "tick_size"},
                            "far":  {"symbol", "exchange", "expiry", "lotsize", "tick_size"}
                        },
                        ...
                    ],
                    "symbols": [{"symbol": "...", "exchange": "..."}, ...],
                    "counts": {"underlyings": N, "pairs": N, "symbols": N},
                    "generated_at": "<iso8601>"
                }
            }
    """
    try:
        requested = [str(ex).strip().upper() for ex in exchanges if str(ex).strip()]
        scan = [ex for ex in requested if ex in SUPPORTED_EXCHANGES]
        if not scan:
            return (
                False,
                {
                    "status": "error",
                    "message": (
                        f"No supported exchanges in {requested or 'request'}. "
                        f"Supported: {', '.join(SUPPORTED_EXCHANGES)}"
                    ),
                },
                400,
            )

        pairs: list[dict[str, Any]] = []
        symbols: dict[str, dict[str, str]] = {}
        underlying_count = 0

        for exchange in scan:
            nearest = _nearest_futures(exchange)
            for underlying, contracts in nearest.items():
                if len(contracts) < 2:
                    # Need at least two expiries to form a calendar pair.
                    continue
                underlying_count += 1
                near = contracts[0]
                legs = {
                    "near-next": contracts[1],
                    "near-third": contracts[2] if len(contracts) > 2 else None,
                }
                for pair_type, far in legs.items():
                    if far is None:
                        continue
                    pairs.append(
                        {
                            "id": f"{exchange}:{underlying}:{pair_type}",
                            "underlying": underlying,
                            "exchange": exchange,
                            "type": pair_type,
                            "near": _leg(near),
                            "far": _leg(far),
                        }
                    )
                    for leg in (near, far):
                        key = f"{leg['exchange']}:{leg['symbol']}"
                        symbols[key] = {"symbol": leg["symbol"], "exchange": leg["exchange"]}

        symbol_list = list(symbols.values())
        response = {
            "status": "success",
            "message": (
                f"Found {len(pairs)} calendar pairs across {len(symbol_list)} "
                f"futures in {', '.join(scan)}"
            ),
            "data": {
                "pairs": pairs,
                "symbols": symbol_list,
                "counts": {
                    "underlyings": underlying_count,
                    "pairs": len(pairs),
                    "symbols": len(symbol_list),
                },
                "generated_at": datetime.now().isoformat(),
            },
        }
        return True, response, 200

    except Exception as e:
        logger.exception(f"Error building arbitrage universe: {e}")
        return (
            False,
            {"status": "error", "message": "An error occurred building the arbitrage universe"},
            500,
        )
