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
from portfolio.data import BENCHMARK_EXCHANGES
from services.portfolio_service import (
    MAX_SYMBOLS,
    analyse_live_holdings,
    generate_tearsheet,
    list_benchmarks,
    run_portfolio_backtest,
)
from utils.logging import get_logger

# Heavier than a quote: a run loads full history for every holding and
# simulates it, so the ceiling is lower than the shared data-API limit.
API_RATE_LIMIT = os.getenv("PORTFOLIO_API_RATE_LIMIT", "10 per minute")
api = Namespace("portfolio", description="Portfolio Backtester API")

logger = get_logger(__name__)

# Cash equity and ETFs only, matching the engine's own allow-list.
PORTFOLIO_EXCHANGES = ["NSE", "BSE"]


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
        values=fields.Dict(
            keys=fields.Str(),
            values=fields.Float(
                allow_none=True,
                validate=validate.Range(min=0),
            ),
        ),
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


@api.route("/benchmarks", strict_slashes=False)
class PortfolioBenchmarks(Resource):
    @limiter.limit(os.getenv("API_RATE_LIMIT", "10 per second"))
    def get(self):
        """List index symbols usable as a benchmark, from the instrument master."""
        api_key = request.args.get("apikey")
        if not api_key or verify_api_key(api_key) is None:
            return make_response(
                jsonify({"status": "error", "message": "Invalid openalgo apikey"}), 403
            )

        try:
            _, payload, status = list_benchmarks()
        except Exception:  # noqa: BLE001
            logger.exception("portfolio benchmarks endpoint failed")
            return make_response(
                jsonify({"status": "error", "message": "Could not list benchmarks."}), 500
            )

        return make_response(jsonify(payload), status)


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

        auth_token = feed_token = broker = None
        if data["source"] == "api":
            auth_token, feed_token, broker = get_auth_token_broker(
                api_key, include_feed_token=True
            )
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
                feed_token=feed_token,
                broker=broker,
            )
        except Exception:  # noqa: BLE001
            logger.exception("portfolio backtest endpoint failed")
            return make_response(
                jsonify({"status": "error", "message": "Backtest failed."}), 500
            )

        return make_response(jsonify(payload), status)


@api.route("/tearsheet", strict_slashes=False)
class PortfolioTearsheet(Resource):
    # Heavier than a backtest: openstatz renders a megabyte of embedded charts
    # with matplotlib, which takes a few seconds.
    @limiter.limit(os.getenv("PORTFOLIO_TEARSHEET_RATE_LIMIT", "5 per minute"))
    def post(self):
        """Render the full openstatz tearsheet as a downloadable HTML file."""
        try:
            data = backtest_schema.load(request.json or {})
        except ValidationError as err:
            return make_response(
                jsonify({"status": "error", "message": err.messages}), 400
            )

        api_key = data.pop("apikey")
        if verify_api_key(api_key) is None:
            return make_response(
                jsonify({"status": "error", "message": "Invalid openalgo apikey"}), 403
            )

        auth_token = feed_token = broker = None
        if data["source"] == "api":
            auth_token, feed_token, broker = get_auth_token_broker(
                api_key, include_feed_token=True
            )
            if auth_token is None:
                return make_response(
                    jsonify(
                        {
                            "status": "error",
                            "message": "No broker session for source='api'.",
                        }
                    ),
                    403,
                )

        try:
            ok, payload, status = generate_tearsheet(
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
                feed_token=feed_token,
                broker=broker,
            )
        except Exception:  # noqa: BLE001
            logger.exception("portfolio tearsheet endpoint failed")
            return make_response(
                jsonify(
                    {
                        "status": "error",
                        "message": "Tearsheet generation failed.",
                    }
                ),
                500,
            )
        if not ok:
            return make_response(jsonify(payload), status)

        # Served as an attachment: it is a self-contained report a user keeps,
        # not a page the app renders.
        response = make_response(payload, 200)
        response.headers["Content-Type"] = "text/html; charset=utf-8"
        response.headers["Content-Disposition"] = (
            'attachment; filename="portfolio-tearsheet.html"'
        )
        return response


class HoldingsAnalysisSchema(Schema):
    apikey = fields.Str(required=True, validate=validate.Length(min=1, max=256))
    # How much history to judge the current holdings against. A year is the
    # shortest window that contains a full seasonal cycle.
    lookback_days = fields.Int(load_default=365, validate=validate.Range(min=60, max=3650))
    benchmark = fields.Str(load_default="NIFTY", allow_none=True)
    benchmark_exchange = fields.Str(
        load_default="NSE_INDEX", validate=validate.OneOf(BENCHMARK_EXCHANGES)
    )
    risk_free_rate = fields.Float(load_default=0.0, validate=validate.Range(min=0, max=0.5))
    source = fields.Str(load_default="db", validate=validate.OneOf(["db", "api"]))


holdings_schema = HoldingsAnalysisSchema()


@api.route("/holdings", strict_slashes=False)
class PortfolioHoldings(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """Analyse the portfolio actually held at the broker."""
        try:
            data = holdings_schema.load(request.json or {})
        except ValidationError as err:
            return make_response(
                jsonify({"status": "error", "message": err.messages}), 400
            )

        api_key = data.pop("apikey")
        if verify_api_key(api_key) is None:
            return make_response(
                jsonify({"status": "error", "message": "Invalid openalgo apikey"}), 403
            )

        # Holdings always need a broker session -- unlike a backtest, there is
        # no local copy of what someone owns.
        auth_token, feed_token, broker = get_auth_token_broker(
            api_key, include_feed_token=True
        )
        if auth_token is None:
            return make_response(
                jsonify(
                    {
                        "status": "error",
                        "message": "No broker session. Log in to your broker to "
                        "analyse live holdings.",
                    }
                ),
                403,
            )

        try:
            _, payload, status = analyse_live_holdings(
                lookback_days=data["lookback_days"],
                benchmark=data["benchmark"],
                benchmark_exchange=data["benchmark_exchange"],
                risk_free_rate=data["risk_free_rate"],
                source=data["source"],
                api_key=api_key,
                auth_token=auth_token,
                feed_token=feed_token,
                broker=broker,
            )
        except Exception:  # noqa: BLE001
            logger.exception("holdings analysis failed")
            return make_response(
                jsonify({"status": "error", "message": "Analysis failed."}), 500
            )

        return make_response(jsonify(payload), status)
