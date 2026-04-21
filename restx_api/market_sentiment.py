import os

from flask import jsonify, make_response, request
from flask_restx import Namespace, Resource
from marshmallow import ValidationError

from limiter import limiter
from services.adanos_sentiment_service import get_market_sentiment
from utils.logging import get_logger

from .data_schemas import MarketSentimentSchema

API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "10 per second")
api = Namespace("market/sentiment", description="Optional external market sentiment API")

logger = get_logger(__name__)
market_sentiment_schema = MarketSentimentSchema()


@api.route("/", strict_slashes=False)
class MarketSentiment(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """Get optional Adanos market sentiment snapshots for stock tickers"""
        try:
            sentiment_data = market_sentiment_schema.load(request.json)

            success, response_data, status_code = get_market_sentiment(
                api_key=sentiment_data["apikey"],
                tickers=sentiment_data["tickers"],
                source=sentiment_data["source"],
                days=sentiment_data.get("days"),
            )

            return make_response(jsonify(response_data), status_code)
        except ValidationError as err:
            return make_response(jsonify({"status": "error", "message": err.messages}), 400)
        except Exception as exc:
            logger.exception(f"Unexpected error in market sentiment endpoint: {exc}")
            return make_response(
                jsonify({"status": "error", "message": "An unexpected error occurred"}),
                500,
            )
