import os

from flask import Response, jsonify, make_response, request
from flask_restx import Namespace, Resource
from marshmallow import ValidationError

from limiter import limiter
from services.instruments_service import get_instruments
from utils.logging import get_logger

from .data_schemas import InstrumentsSchema


class CSVResponse(Response):
    """Custom Response class that supports both CSV and JSON properties for latency monitoring"""

    @property
    def json(self):
        return getattr(self, "_json", None)

    @json.setter
    def json(self, value):
        self._json = value


API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "10 per second")
api = Namespace("instruments", description="Instruments/Symbols download API")

# Initialize logger
logger = get_logger(__name__)

# Initialize schema
instruments_schema = InstrumentsSchema()


@api.route("/", strict_slashes=False)
class Instruments(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def get(self):
        """
        Download all instruments/symbols from the database

        Query Parameters:
            - apikey (required): API key for authentication
            - exchange (optional): Filter by exchange (NSE, BSE, NFO, BFO, BCD, CDS, MCX, NSE_INDEX, BSE_INDEX)
            - format (optional): Output format - 'json' (default) or 'csv'

        Returns:
            - JSON format: Returns instrument data in JSON format
            - CSV format: Returns instrument data as downloadable CSV file
        """
        try:
            # Get query parameters
            query_params = {
                "apikey": request.args.get("apikey"),
                "exchange": request.args.get("exchange"),
                "format": request.args.get("format", "json").lower(),
            }

            # Validate request data
            instruments_data = instruments_schema.load(query_params)

            # Extract parameters
            api_key = instruments_data.get("apikey")
            exchange = instruments_data.get("exchange")
            format_type = instruments_data.get("format", "json")

            # Call the service function to get instruments
            success, response_data, status_code, headers = get_instruments(
                exchange=exchange, api_key=api_key, format=format_type
            )

            # Handle CSV response
            if format_type == "csv":
                if success:
                    response = CSVResponse(response_data, status=status_code)
                    for key, value in headers.items():
                        response.headers[key] = value
                    # Set json property for latency monitoring
                    response.json = {
                        "request_id": f"instruments_{exchange if exchange else 'all'}",
                        "format": "csv",
                        "exchange": exchange if exchange else "all",
                    }
                    return response
                else:
                    # Error case with CSV format
                    error_message = (
                        response_data.get("message", "An error occurred")
                        if isinstance(response_data, dict)
                        else str(response_data)
                    )
                    response = CSVResponse(error_message, status=status_code)
                    response.content_type = "text/plain"
                    response.json = {
                        "request_id": f"instruments_{exchange if exchange else 'all'}_error",
                        "format": "csv",
                        "status": "error",
                    }
                    return response

            # Handle JSON response
            return make_response(jsonify(response_data), status_code)

        except ValidationError as err:
            logger.warning(f"Validation error in instruments endpoint: {err.messages}")
            # Check if CSV format was requested
            format_type = request.args.get("format", "json").lower()
            if format_type == "csv":
                response = CSVResponse(str(err.messages), status=400)
                response.content_type = "text/plain"
                response.json = {"request_id": "instruments_validation_error", "format": "csv"}
                return response
            return make_response(jsonify({"status": "error", "message": err.messages}), 400)

        except Exception as e:
            logger.exception(f"Unexpected error in instruments endpoint: {e}")
            # Check if CSV format was requested
            format_type = request.args.get("format", "json").lower()
            if format_type == "csv":
                response = CSVResponse("An unexpected error occurred", status=500)
                response.content_type = "text/plain"
                response.json = {"request_id": "instruments_error", "format": "csv"}
                return response
            return make_response(
                jsonify({"status": "error", "message": "An unexpected error occurred"}), 500
            )
