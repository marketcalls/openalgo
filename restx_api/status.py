import os

from flask import jsonify, make_response, request
from flask_restx import Namespace, Resource
from marshmallow import Schema, ValidationError, fields, validate

from limiter import limiter
from services.status_service import get_status
from utils.logging import get_logger

API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "10 per second")
api = Namespace(
    "status", description="What is active right now: broker feed, streams, threads, request counts"
)

# Initialize logger
logger = get_logger(__name__)


class StatusSchema(Schema):
    apikey = fields.Str(required=True, validate=validate.Length(min=1, max=256))


status_schema = StatusSchema()


@api.route("/", strict_slashes=False)
class Status(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """Broker feed connections, open streams, threads and recent request counts"""
        try:
            status_data = status_schema.load(request.json)
            success, response_data, status_code = get_status(api_key=status_data["apikey"])
            return make_response(jsonify(response_data), status_code)

        except ValidationError as err:
            return make_response(jsonify({"status": "error", "message": err.messages}), 400)
        except Exception as e:
            logger.exception(f"Unexpected error in status endpoint: {e}")
            return make_response(
                jsonify({"status": "error", "message": "An unexpected error occurred"}), 500
            )
