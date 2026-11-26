import csv
from io import StringIO
from typing import Any, Dict, List, Tuple

from database.auth_db import verify_api_key
from database.symbol import SymToken, db_session
from database.token_db_enhanced import get_cache
from utils.logging import get_logger

logger = get_logger(__name__)

INSTRUMENT_FIELDS = (
    "symbol",
    "brsymbol",
    "name",
    "exchange",
    "brexchange",
    "token",
    "expiry",
    "strike",
    "lotsize",
    "instrumenttype",
    "tick_size",
)


def _instrument_rows(exchange: str | None) -> list:
    """Rows from the in-memory symbol cache when it is loaded, else the database.

    The cache holds every SymToken row, grouped by exchange in database order,
    so serving from it skips the query and the ORM objects, which for NFO took
    long enough to stall every other request on the single worker.
    """
    snap = get_cache().valid_snapshot()
    if snap is not None:
        if exchange:
            return list(snap.by_exchange.get(exchange, ()))
        return [row for rows in snap.by_exchange.values() for row in rows]

    query = SymToken.query
    if exchange:
        query = query.filter(SymToken.exchange == exchange)
    return query.all()


def get_instruments(
    exchange: str = None, api_key: str = None, format: str = "json"
) -> tuple[bool, Any, int, dict[str, str]]:
    """
    Get all instruments/symbols from the database

    Args:
        exchange: Optional exchange filter (NSE, BSE, NFO, BFO, BCD, CDS, MCX, NSE_INDEX, BSE_INDEX)
        api_key: API key for authentication
        format: Output format ('json' or 'csv')

    Returns:
        Tuple of (success, response_data, status_code, headers)
    """
    try:
        # Validate API key
        if api_key:
            user_id = verify_api_key(api_key)
            if not user_id:
                logger.warning("Invalid API key provided for instruments download")
                return False, {"status": "error", "message": "Invalid openalgo apikey"}, 403, {}
        else:
            logger.warning("No API key provided for instruments download")
            return False, {"status": "error", "message": "API key is required"}, 401, {}

        if exchange:
            logger.info(f"Filtering instruments by exchange: {exchange}")
        else:
            logger.info("Fetching all instruments from all exchanges")

        results = _instrument_rows(exchange)

        if not results:
            logger.info("No instruments found" + (f" for exchange: {exchange}" if exchange else ""))
            return (
                True,
                {"status": "success", "message": "No instruments found", "data": []},
                200,
                {},
            )

        # Convert results to dict format
        results_data = [
            {field: getattr(result, field) for field in INSTRUMENT_FIELDS} for result in results
        ]

        logger.info(
            f"Found {len(results_data)} instruments"
            + (f" for exchange: {exchange}" if exchange else "")
        )

        # Return based on format
        if format == "csv":
            # Generate CSV
            output = StringIO()
            if results_data:
                writer = csv.DictWriter(output, fieldnames=INSTRUMENT_FIELDS)
                writer.writeheader()
                for row in results_data:
                    writer.writerow(row)

            csv_content = output.getvalue()
            output.close()

            # Set appropriate headers for CSV download
            headers = {
                "Content-Type": "text/csv",
                "Content-Disposition": f"attachment; filename=instruments_{exchange if exchange else 'all'}.csv",
            }

            return True, csv_content, 200, headers
        else:
            # Return JSON format (default)
            return (
                True,
                {
                    "status": "success",
                    "message": f"Found {len(results_data)} instruments",
                    "data": results_data,
                },
                200,
                {},
            )

    except Exception as e:
        logger.exception(f"Error in get_instruments: {e}")
        return (
            False,
            {"status": "error", "message": "An error occurred while fetching instruments"},
            500,
            {},
        )
