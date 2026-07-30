"""
Portfolio Backtester API.

One POST returns everything the analysis tabs render, because they are all
views of a single simulation -- splitting them across endpoints would mean
re-running the backtest per tab and risking two tabs disagreeing about the
same portfolio.
"""

import os

from flask import jsonify, make_response, request
from flask_restx import Namespace, Resource
from marshmallow import Schema, ValidationError, fields, validate

from database.auth_db import get_auth_token_broker, verify_api_key
from limiter import limiter
from services.portfolio_service import MAX_SYMBOLS, run_portfolio_backtest
from utils.logging import get_logger

# Heavier than a quote: a run loads full history for every holding and
# simulates it, so the ceiling is lower than the shared data-API limit.
API_RATE_LIMIT = os.getenv("PORTFOLIO_API_RATE_LIMIT", "10 per minute")
api = Namespace("portfolio", description="Portfolio Backtester API")

logger = get_logger(__name__)

# Cash equity and ETFs only, matching the engine's own allow-list.
PORTFOLIO_EXCHANGES = ["NSE", "BSE"]
# Benchmarks live on the index exchanges.
BENCHMARK_EXCHANGES = ["NSE_INDEX", "BSE_INDEX"]


class HoldingSchema(Schema):
    symbol = fields.Str(required=True, validate=validate.Length(min=1, max=64))
    exchange = fields.Str(load_default="NSE", validate=validate.OneOf(PORTFOLIO_EXCHANGES))
    # Percentages or fractions both work; only the ratio between them matters.
    weight = fields.Float(required=True, validate=validate.Range(min=0))


class PortfolioBacktestSchema(Schema):
    apikey = fields.Str(required=True, validate=validate.Length(min=1, max=256))
    holdings = fields.List(
        fields.Nested(HoldingSchema),
        required=True,
        validate=validate.Length(min=1, max=MAX_SYMBOLS),
    )
    start_date = fields.Str(required=True)
    end_date = fields.Str(required=True)

    benchmark = fields.Str(load_default=None, allow_none=True)
    # Indices, not the cash exchanges: a benchmark cannot be held, and alpha
    # or beta measured against a single stock would not mean anything.
    benchmark_exchange = fields.Str(
        load_default="NSE_INDEX", validate=validate.OneOf(BENCHMARK_EXCHANGES)
    )
    rebalance = fields.Str(
        load_default="never",
        validate=validate.OneOf(["never", "monthly", "quarterly", "yearly"]),
    )
    # Percentage points of drift that force a rebalance regardless of the
    # calendar. Capped below 1.0 because a band of 100% can never trigger.
    drift_band = fields.Float(load_default=0.0, validate=validate.Range(min=0, max=0.99))
    # The itemised Indian delivery-equity schedule by default; flat bps is
    # kept only so a user can compare against a theoretical rate.
    cost_model = fields.Str(
        load_default="indian_equity",
        validate=validate.OneOf(["indian_equity", "flat_bps"]),
    )
    brokerage_pct = fields.Float(load_default=0.0, validate=validate.Range(min=0, max=0.05))
    # Which exchange's transaction charge applies. Explicit rather than taken
    # from the first holding, since a mixed NSE/BSE book has no single answer.
    cost_exchange = fields.Str(
        load_default="NSE", validate=validate.OneOf(PORTFOLIO_EXCHANGES)
    )
    # Per-charge overrides, so every rate is the caller's to set. Statutory
    # rates change with the budget and differ by market; baking them into the
    # server would mean a release every time one moves.
    charges = fields.Dict(
        keys=fields.Str(),
        values=fields.Dict(keys=fields.Str(), values=fields.Float(allow_none=True)),
        load_default=dict,
    )
    gst_rate = fields.Float(load_default=None, allow_none=True,
                            validate=validate.Range(min=0, max=1))
    cost_bps = fields.Float(load_default=0.0, validate=validate.Range(min=0, max=1000))
    slippage = fields.Float(load_default=0.0, validate=validate.Range(min=0, max=0.1))
    initial_capital = fields.Float(load_default=100000.0, validate=validate.Range(min=1))
    risk_free_rate = fields.Float(load_default=0.0, validate=validate.Range(min=0, max=0.5))
    # 'db' reads the local Historify store: deterministic and rate-limit free,
    # which is what a long multi-symbol run wants. 'api' asks the broker.
    source = fields.Str(load_default="db", validate=validate.OneOf(["db", "api"]))


backtest_schema = PortfolioBacktestSchema()


@api.route("/backtest", strict_slashes=False)
class PortfolioBacktest(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """Backtest a weighted portfolio and return its full analysis."""
        try:
            data = backtest_schema.load(request.json or {})
        except ValidationError as err:
            return make_response(
                jsonify({"status": "error", "message": err.messages}), 400
            )

        api_key = data.pop("apikey")

        # The key is always verified. Only the *broker session* is optional:
        # a Historify run must not require one, since backtesting at the
        # weekend is the normal case -- but "no broker session needed" is not
        # the same as "no authentication needed", and skipping the check here
        # would have left local history readable by anyone who could reach the
        # endpoint.
        if verify_api_key(api_key) is None:
            return make_response(
                jsonify({"status": "error", "message": "Invalid openalgo apikey"}), 403
            )

        auth_token = broker = None
        if data["source"] == "api":
            auth_token, broker = get_auth_token_broker(api_key)
            if auth_token is None:
                return make_response(
                    jsonify(
                        {
                            "status": "error",
                            "message": "No broker session for source='api'. "
                            "Log in to your broker, or use source='db' to "
                            "backtest from local history.",
                        }
                    ),
                    403,
                )

        try:
            success, payload, status = run_portfolio_backtest(
                holdings=data["holdings"],
                start_date=data["start_date"],
                end_date=data["end_date"],
                benchmark=data["benchmark"],
                benchmark_exchange=data["benchmark_exchange"],
                rebalance=data["rebalance"],
                drift_band=data["drift_band"],
                cost_model=data["cost_model"],
                brokerage_pct=data["brokerage_pct"],
                cost_exchange=data["cost_exchange"],
                charge_overrides=data["charges"],
                gst_rate=data["gst_rate"],
                cost_bps=data["cost_bps"],
                slippage=data["slippage"],
                initial_capital=data["initial_capital"],
                risk_free_rate=data["risk_free_rate"],
                source=data["source"],
                api_key=api_key,
                auth_token=auth_token,
                broker=broker,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("portfolio backtest endpoint failed")
            return make_response(
                jsonify({"status": "error", "message": f"backtest failed: {exc}"}), 500
            )

        return make_response(jsonify(payload), status)
