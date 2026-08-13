"""SIP Backtester API.

One POST returns everything the results page renders. Splitting the metrics
across endpoints would mean re-running the simulation per tab, and two tabs
could then disagree about the same SIP.

Security follows the same contract as the portfolio backtester:

* the OpenAlgo API key is verified on **every** request, including
  ``source='db'`` runs that need no broker session -- local history is still
  the user's data, and "no broker session required" is not "no authentication
  required";
* a broker session is additionally required for ``source='api'``;
* every field is validated by marshmallow before reaching the service, so
  symbols, dates and numeric ranges cannot arrive unchecked;
* the endpoint is rate limited, because a run with grids enabled performs
  hundreds of simulations.
"""

import os

from flask import jsonify, make_response, request
from flask_restx import Namespace, Resource
from marshmallow import Schema, ValidationError, fields, validate

from database.auth_db import get_auth_token_broker, verify_api_key
from limiter import limiter
from portfolio.data import BENCHMARK_EXCHANGES
from services.sip_service import MAX_SIP_YEARS, list_frequencies, run_sip_backtest
from sip.schedule import FREQUENCIES, MAX_DAY_OF_MONTH
from utils.logging import get_logger

# A full run with grids enabled performs hundreds of simulations (rolling
# windows, the start-date grid and the day-of-month sweep), so this sits below
# the shared data-API allowance.
API_RATE_LIMIT = os.getenv("SIP_API_RATE_LIMIT", "10 per minute")

api = Namespace("sip", description="SIP Backtester API")
logger = get_logger(__name__)

# Cash equity and ETFs only. A SIP into a derivative is not a thing, and the
# engine's own allow-list agrees.
SIP_EXCHANGES = ["NSE", "BSE"]

# Bounds exist to stop a single request turning into an unbounded amount of
# work, not because larger values are conceptually wrong.
MAX_AMOUNT = 10_000_000.0
MAX_STEP_UP = 100.0


class SipBacktestSchema(Schema):
    apikey = fields.Str(required=True, validate=validate.Length(min=1, max=256))

    symbol = fields.Str(required=True, validate=validate.Length(min=1, max=64))
    exchange = fields.Str(
        load_default="NSE", validate=validate.OneOf(SIP_EXCHANGES)
    )

    # The date the SIP starts. The first installment lands on this date or the
    # next trading session after it.
    start_date = fields.Str(required=True, validate=validate.Length(equal=10))
    end_date = fields.Str(required=True, validate=validate.Length(equal=10))

    amount = fields.Float(
        required=True, validate=validate.Range(min=1, max=MAX_AMOUNT)
    )
    frequency = fields.Str(
        load_default="monthly", validate=validate.OneOf(list(FREQUENCIES))
    )
    # Capped at 28 rather than 31: a SIP on the 31st does not exist in every
    # month, and silently moving it produces a schedule nobody asked for.
    day_of_month = fields.Int(
        load_default=1, validate=validate.Range(min=1, max=MAX_DAY_OF_MONTH)
    )
    step_up_percent = fields.Float(
        load_default=0.0, validate=validate.Range(min=0, max=MAX_STEP_UP)
    )

    brokerage_percent = fields.Float(
        load_default=0.0, validate=validate.Range(min=0, max=5)
    )
    brokerage_flat = fields.Float(
        load_default=0.0, validate=validate.Range(min=0, max=10_000)
    )

    # Full statutory charge model, matching the portfolio backtester so the
    # same trade costs the same in both tools.
    cost_model = fields.Str(
        load_default="indian_equity", validate=validate.OneOf(["indian_equity", "flat_bps"])
    )
    cost_exchange = fields.Str(
        load_default="NSE", validate=validate.OneOf(SIP_EXCHANGES)
    )
    charges = fields.Dict(
        keys=fields.Str(validate=validate.Length(min=1, max=32)),
        values=fields.Dict(),
        load_default=None,
        allow_none=True,
    )
    gst_rate = fields.Float(
        load_default=None, allow_none=True, validate=validate.Range(min=0, max=1)
    )
    cost_bps = fields.Float(load_default=0.0, validate=validate.Range(min=0, max=1000))
    slippage = fields.Float(load_default=0.0, validate=validate.Range(min=0, max=0.1))

    benchmark = fields.Str(load_default=None, allow_none=True,
                           validate=validate.Length(max=64))
    # Indices only: a benchmark is not something you can hold, and comparing a
    # SIP against a single stock would not mean anything.
    benchmark_exchange = fields.Str(
        load_default="NSE_INDEX", validate=validate.OneOf(BENCHMARK_EXCHANGES)
    )

    source = fields.Str(
        load_default="db", validate=validate.OneOf(["db", "api"])
    )
    include_grids = fields.Bool(load_default=True)


backtest_schema = SipBacktestSchema()


@api.route("/frequencies", strict_slashes=False)
class SipFrequencies(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def get(self):
        """SIP frequencies the engine supports."""
        success, payload, status = list_frequencies()
        return make_response(jsonify(payload), status)


@api.route("/backtest", strict_slashes=False)
class SipBacktest(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """Backtest a SIP and return its full analysis."""
        try:
            data = backtest_schema.load(request.json or {})
        except ValidationError as err:
            return make_response(
                jsonify({"status": "error", "message": err.messages}), 400
            )

        api_key = data.pop("apikey")

        # Verified on every path. A Historify run needs no broker session --
        # backtesting at the weekend is the normal case -- but that is not a
        # reason to leave local history readable by anyone who can reach the
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
            success, payload, status = run_sip_backtest(
                symbol=data["symbol"],
                exchange=data["exchange"],
                start_date=data["start_date"],
                end_date=data["end_date"],
                amount=data["amount"],
                frequency=data["frequency"],
                day_of_month=data["day_of_month"],
                step_up_percent=data["step_up_percent"],
                brokerage_percent=data["brokerage_percent"],
                brokerage_flat=data["brokerage_flat"],
                cost_model=data["cost_model"],
                cost_exchange=data["cost_exchange"],
                charge_overrides=data["charges"],
                gst_rate=data["gst_rate"],
                cost_bps=data["cost_bps"],
                slippage=data["slippage"],
                benchmark=data["benchmark"],
                benchmark_exchange=data["benchmark_exchange"],
                source=data["source"],
                include_grids=data["include_grids"],
                api_key=api_key,
                auth_token=auth_token,
                feed_token=feed_token,
                broker=broker,
            )
        except Exception:  # noqa: BLE001
            # The message is deliberately generic: the traceback goes to
            # errors.jsonl, not to the caller, so an internal failure cannot
            # leak paths or query internals.
            logger.exception("SIP backtest endpoint failed")
            return make_response(
                jsonify({"status": "error", "message": "SIP backtest failed."}), 500
            )

        return make_response(jsonify(payload), status)


# Re-exported so the resource module documents its own limits.
__all__ = ["api", "MAX_SIP_YEARS"]
