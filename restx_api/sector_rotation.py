"""Sector Rotation API.

One POST returns the whole map: every requested symbol's position, quadrant,
run length and trail against the chosen benchmark. With no symbols listed it is
the default NSE sector set. The trail is returned at its longest
and trimmed by the page, so moving the tail slider costs no request.

Security follows the SIP and portfolio backtester contract:

* the OpenAlgo API key is verified on **every** request, including
  ``source='db'`` runs that need no broker session;
* a broker session is additionally required for ``source='api'``;
* every field is validated by marshmallow before reaching the service;
* the endpoint is rate limited and a map is capped at ``MAX_INSTRUMENTS``
  symbols, because each one is a history request on the broker source.
"""

import os

from flask import jsonify, make_response, request
from flask_restx import Namespace, Resource
from marshmallow import Schema, ValidationError, fields, validate

from database.auth_db import get_auth_token_broker, verify_api_key
from limiter import limiter
from services.sector_rotation_service import (
    BENCHMARKS,
    EXCHANGES,
    MAX_INSTRUMENTS,
    SOURCES,
    TIMEFRAMES,
    compute_sector_rotation,
    list_options,
)
from utils.logging import get_logger

API_RATE_LIMIT = os.getenv("SECTOR_ROTATION_API_RATE_LIMIT", "30 per minute")

api = Namespace("sectorrotation", description="Sector Rotation API")
logger = get_logger(__name__)


class InstrumentSchema(Schema):
    symbol = fields.Str(required=True, validate=validate.Length(min=1, max=64))
    exchange = fields.Str(required=True, validate=validate.OneOf(list(EXCHANGES)))
    label = fields.Str(load_default=None, allow_none=True, validate=validate.Length(max=64))


class SectorRotationSchema(Schema):
    apikey = fields.Str(required=True, validate=validate.Length(min=1, max=256))
    benchmark = fields.Str(
        load_default="NIFTY", validate=validate.OneOf([b.symbol for b in BENCHMARKS])
    )
    timeframe = fields.Str(load_default="daily", validate=validate.OneOf(list(TIMEFRAMES)))
    source = fields.Str(load_default="db", validate=validate.OneOf(list(SOURCES)))
    # The symbols to place on the map. Empty means the default sector set.
    instruments = fields.List(
        fields.Nested(InstrumentSchema),
        load_default=list,
        validate=validate.Length(max=MAX_INSTRUMENTS),
    )


rotation_schema = SectorRotationSchema()


@api.route("/options", strict_slashes=False)
class SectorRotationOptions(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def get(self):
        """Benchmarks, timeframes and sectors the map supports."""
        success, payload, status = list_options()
        return make_response(jsonify(payload), status)


@api.route("/", strict_slashes=False)
class SectorRotation(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """Place every sector on the rotation map against a benchmark."""
        try:
            data = rotation_schema.load(request.json or {})
        except ValidationError as err:
            # The field detail goes to the log; the page shows a sentence a
            # trader can act on, since a stale saved setting is the usual cause.
            logger.info(f"Sector rotation request refused: {err.messages}")
            return make_response(
                jsonify(
                    {
                        "status": "error",
                        "message": "These map settings were not accepted. Choose the "
                        "benchmark and timeframe again, or use Reset to sectors if you "
                        "added symbols.",
                    }
                ),
                400,
            )

        api_key = data.pop("apikey")

        # Verified on every path: Historify needs no broker session, but local
        # history is still the user's data.
        if verify_api_key(api_key) is None:
            return make_response(
                jsonify({"status": "error", "message": "Invalid openalgo apikey"}), 403
            )

        auth_token = feed_token = broker = None
        if data["source"] == "api":
            auth_token, feed_token, broker = get_auth_token_broker(api_key, include_feed_token=True)
            if auth_token is None:
                return make_response(
                    jsonify(
                        {
                            "status": "error",
                            "message": "Broker API needs an active broker login. Log in "
                            "to your broker, or switch the data source to Historify.",
                        }
                    ),
                    403,
                )

        try:
            success, payload, status = compute_sector_rotation(
                benchmark=data["benchmark"],
                timeframe=data["timeframe"],
                source=data["source"],
                instruments=data["instruments"],
                api_key=api_key,
                auth_token=auth_token,
                feed_token=feed_token,
                broker=broker,
            )
        except Exception:  # noqa: BLE001
            logger.exception("Sector rotation endpoint failed")
            return make_response(
                jsonify(
                    {
                        "status": "error",
                        "message": "The sector map could not be built. Details are in "
                        "the error log.",
                    }
                ),
                500,
            )

        return make_response(jsonify(payload), status)
