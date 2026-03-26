"""AI Agent REST API endpoints.

/api/v1/agent/analyze — Run technical analysis on a symbol
/api/v1/agent/scan    — Scan multiple symbols
/api/v1/agent/status  — Agent health check
"""

from flask_restx import Namespace, Resource

from limiter import limiter
from services.ai_analysis_service import analyze_symbol
from utils.logging import get_logger

logger = get_logger(__name__)

api = Namespace("agent", description="AI Agent Analysis & Decision Endpoints")


@api.route("/analyze")
class AnalyzeResource(Resource):
    @limiter.limit("10 per second")
    def post(self):
        """Analyze a symbol and return signal + indicators."""
        from flask import request

        data = request.get_json(force=True)

        api_key = data.get("apikey", "")
        symbol = data.get("symbol", "")
        exchange = data.get("exchange", "NSE")
        interval = data.get("interval", "1d")

        if not symbol:
            return {"status": "error", "message": "symbol is required"}, 400

        if not api_key:
            return {"status": "error", "message": "apikey is required"}, 400

        try:
            result = analyze_symbol(
                symbol=symbol,
                exchange=exchange,
                interval=interval,
                api_key=api_key,
            )
        except Exception as e:
            logger.exception("Unexpected error in analyze endpoint")
            return {"status": "error", "message": "An unexpected error occurred"}, 500

        if not result.success:
            return {"status": "error", "message": result.error}

        return {
            "status": "success",
            "data": {
                "symbol": result.symbol,
                "exchange": result.exchange,
                "interval": result.interval,
                "signal": result.signal,
                "confidence": result.confidence,
                "score": result.score,
                "regime": result.regime,
                "sub_scores": result.sub_scores,
                "indicators": result.latest_indicators,
                "advanced": result.advanced_signals,
                "data_points": result.data_points,
            },
        }


@api.route("/scan")
class ScanResource(Resource):
    @limiter.limit("5 per second")
    def post(self):
        """Scan multiple symbols and return signals."""
        from flask import request

        data = request.get_json(force=True)
        api_key = data.get("apikey", "")
        symbols = data.get("symbols", [])
        exchange = data.get("exchange", "NSE")
        interval = data.get("interval", "1d")

        if not api_key:
            return {"status": "error", "message": "apikey is required"}, 400
        if not symbols or not isinstance(symbols, list):
            return {"status": "error", "message": "symbols list is required"}, 400

        results = []
        for sym in symbols[:20]:  # Max 20 symbols per scan
            try:
                result = analyze_symbol(sym, exchange, interval, api_key)
                results.append({
                    "symbol": result.symbol,
                    "signal": result.signal,
                    "confidence": result.confidence,
                    "score": result.score,
                    "regime": result.regime,
                    "error": result.error,
                })
            except Exception as e:
                logger.error(f"Error scanning symbol {sym}: {e}")
                results.append({
                    "symbol": sym,
                    "signal": None,
                    "confidence": 0.0,
                    "score": 0.0,
                    "regime": None,
                    "error": str(e),
                })

        return {"status": "success", "data": results}


@api.route("/status")
class StatusResource(Resource):
    def get(self):
        """AI agent health check."""
        return {
            "status": "success",
            "data": {
                "agent": "active",
                "version": "1.0.0",
                "engine": "vayu-signals",
                "indicators": 20,
                "signals": 6,
            },
        }
