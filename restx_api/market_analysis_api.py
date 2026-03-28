"""Market Analysis API -- trend + momentum + OI unified report."""

from flask_restx import Namespace, Resource

from limiter import limiter
from services.market_analysis_service import analyze_market
from utils.logging import get_logger

logger = get_logger(__name__)

api = Namespace("market-analysis", description="Trend + Momentum + OI Analysis")


@api.route("/report")
class MarketReportResource(Resource):
    @limiter.limit("10 per second")
    def post(self):
        """Get unified market analysis report."""
        from flask import request

        data = request.get_json(force=True)

        api_key = data.get("apikey", "")
        symbol = data.get("symbol", "")
        exchange = data.get("exchange", "NSE")
        interval = data.get("interval", "1d")
        option_chain = data.get("option_chain")

        if not symbol or not api_key:
            return {"status": "error", "message": "apikey and symbol required"}, 400

        result = analyze_market(symbol, exchange, interval, api_key, option_chain)

        if not result.success:
            return {"status": "error", "message": result.error}, 422

        return {
            "status": "success",
            "data": {
                "symbol": result.symbol,
                "exchange": result.exchange,
                "overall_bias": result.overall_bias,
                "overall_score": result.overall_score,
                "trend": {
                    "strength": result.trend.strength,
                    "direction": result.trend.direction,
                    "details": result.trend.details,
                } if result.trend else None,
                "momentum": {
                    "score": result.momentum.score,
                    "bias": result.momentum.bias,
                    "details": result.momentum.details,
                } if result.momentum else None,
                "oi": {
                    "pcr_oi": result.oi.pcr_oi,
                    "pcr_volume": result.oi.pcr_volume,
                    "max_pain": result.oi.max_pain,
                    "bias": result.oi.bias,
                    "score": result.oi.score,
                    "details": result.oi.details,
                } if result.oi else None,
            },
        }
