import csv
from io import StringIO
from typing import Any, Dict, List, Tuple

from database.auth_db import verify_api_key
from database.symbol import SymToken, db_session
from utils.logging import get_logger

logger = get_logger(__name__)


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

        # Build query
        query = SymToken.query

        # Apply exchange filter if provided
        if exchange:
            query = query.filter(SymToken.exchange == exchange)
            logger.info(f"Filtering instruments by exchange: {exchange}")
        else:
            logger.info("Fetching all instruments from all exchanges")

        # Execute query
        results = query.all()

        if not results:
            logger.info("No instruments found" + (f" for exchange: {exchange}" if exchange else ""))
            return (
                True,
                {"status": "success", "message": "No instruments found", "data": []},
                200,
                {},
            )

        # Convert results to dict format
        results_data = []
        for result in results:
            result_dict = {
                "symbol": result.symbol,
                "brsymbol": result.brsymbol,
                "name": result.name,
                "exchange": result.exchange,
                "brexchange": result.brexchange,
                "token": result.token,
                "expiry": result.expiry,
                "strike": result.strike,
                "lotsize": result.lotsize,
                "instrumenttype": result.instrumenttype,
                "tick_size": result.tick_size,
            }
            results_data.append(result_dict)

        logger.info(
            f"Found {len(results_data)} instruments"
            + (f" for exchange: {exchange}" if exchange else "")
        )

        # Return based on format
        if format == "csv":
            # Generate CSV
            output = StringIO()
            if results_data:
                fieldnames = [
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
                ]
                writer = csv.DictWriter(output, fieldnames=fieldnames)
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
