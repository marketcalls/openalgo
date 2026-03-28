"""AI Agent REST API endpoints.

/api/v1/agent/analyze — Run technical analysis on a symbol
/api/v1/agent/scan    — Scan multiple symbols
/api/v1/agent/history — Fetch recent AI analysis history for a user
/api/v1/agent/status  — Agent health check
"""

from flask_restx import Namespace, Resource

from ai.agent_decisions import get_decision_history, log_analysis
from database.auth_db import verify_api_key
from limiter import limiter
from services.ai_analysis_service import analyze_symbol
from utils.logging import get_logger

logger = get_logger(__name__)

api = Namespace("agent", description="AI Agent Analysis & Decision Endpoints")


def _validate_api_key(api_key: str) -> str | None:
    """Validate an OpenAlgo API key and return the authenticated user id."""
    if not api_key:
        return None
    return verify_api_key(api_key)


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

        user_id = _validate_api_key(api_key)
        if user_id is None:
            return {"status": "error", "message": "Invalid openalgo apikey"}, 403

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
            return {"status": "error", "message": result.error}, 422

        try:
            # We use the current close price as the predicted_price for tracking
            predicted_price = float(result.candles[-1]["close"]) if result.candles else None
            
            log_analysis(
                user_id=user_id,
                symbol=result.symbol,
                exchange=result.exchange,
                interval=result.interval,
                signal=result.signal or "HOLD",
                confidence=result.confidence,
                score=result.score,
                regime=result.regime,
                scores=result.sub_scores,
                predicted_price=predicted_price,
                api_key=api_key,
            )
        except Exception:
            logger.warning("Failed to persist AI analysis history for %s", symbol, exc_info=True)

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
                "trade_setup": result.trade_setup,
                "chart_overlays": result.chart_overlays,
                "decision": result.decision,
                "candles": result.candles,
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
        if _validate_api_key(api_key) is None:
            return {"status": "error", "message": "Invalid openalgo apikey"}, 403
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
                    "trade_setup": {
                        "entry": result.trade_setup.get("entry", 0),
                        "stop_loss": result.trade_setup.get("stop_loss", 0),
                        "target_1": result.trade_setup.get("target_1", 0),
                        "risk_reward_1": result.trade_setup.get("risk_reward_1", 0),
                    },
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


@api.route("/history")
class HistoryResource(Resource):
    @limiter.limit("10 per second")
    def post(self):
        """Return recent AI decisions for the authenticated user."""
        from flask import request

        data = request.get_json(force=True) or {}

        api_key = data.get("apikey", "")
        symbol = data.get("symbol") or None
        raw_limit = data.get("limit", 10)

        if not api_key:
            return {"status": "error", "message": "apikey is required"}, 400

        user_id = _validate_api_key(api_key)
        if user_id is None:
            return {"status": "error", "message": "Invalid openalgo apikey"}, 403

        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            return {"status": "error", "message": "limit must be an integer"}, 400

        if limit < 1 or limit > 100:
            return {"status": "error", "message": "limit must be between 1 and 100"}, 400

        if symbol is not None and not isinstance(symbol, str):
            return {"status": "error", "message": "symbol must be a string"}, 400

        try:
            history = get_decision_history(user_id, symbol=symbol, limit=limit)
        except Exception:
            logger.exception("Unexpected error in history endpoint")
            return {"status": "error", "message": "An unexpected error occurred"}, 500

        return {"status": "success", "data": history}


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


# ─── Strategy Analysis Endpoints ─────────────────────────────────────


def _strategy_endpoint(handler):
    """Shared wrapper for strategy endpoints: parse JSON, validate API key, call handler."""
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
    if _validate_api_key(api_key) is None:
        return {"status": "error", "message": "Invalid openalgo apikey"}, 403

    try:
        result = handler(symbol=symbol, exchange=exchange, interval=interval, api_key=api_key)
        return {"status": "success", "data": result}
    except ValueError as e:
        return {"status": "error", "message": str(e)}, 422
    except Exception:
        logger.exception("Strategy endpoint error")
        return {"status": "error", "message": "An unexpected error occurred"}, 500


@api.route("/fibonacci")
class FibonacciResource(Resource):
    @limiter.limit("10 per second")
    def post(self):
        """Fibonacci retracement and extension levels."""
        from services.strategy_analysis_service import analyze_fibonacci
        return _strategy_endpoint(analyze_fibonacci)


@api.route("/harmonic")
class HarmonicResource(Resource):
    @limiter.limit("10 per second")
    def post(self):
        """Harmonic pattern detection (Gartley, Butterfly, Bat, etc.)."""
        from services.strategy_analysis_service import analyze_harmonic
        return _strategy_endpoint(analyze_harmonic)


@api.route("/elliott-wave")
class ElliottWaveResource(Resource):
    @limiter.limit("10 per second")
    def post(self):
        """Elliott Wave impulse and corrective wave analysis."""
        from services.strategy_analysis_service import analyze_elliott_wave
        return _strategy_endpoint(analyze_elliott_wave)


@api.route("/smart-money-detail")
class SmartMoneyDetailResource(Resource):
    @limiter.limit("10 per second")
    def post(self):
        """Smart Money Concepts: Order Blocks, FVGs, Structure Breaks, Sweeps."""
        from services.strategy_analysis_service import analyze_smart_money
        return _strategy_endpoint(analyze_smart_money)


@api.route("/hedge-strategy")
class HedgeStrategyResource(Resource):
    @limiter.limit("10 per second")
    def post(self):
        """Hedge Fund analytics: mean reversion, momentum, vol regime, risk metrics."""
        from services.strategy_analysis_service import analyze_hedge_strategy
        return _strategy_endpoint(analyze_hedge_strategy)


@api.route("/strategy-decision")
class StrategyDecisionResource(Resource):
    @limiter.limit("5 per second")
    def post(self):
        """Unified strategy decision with confluence voting across all modules."""
        from services.strategy_analysis_service import analyze_strategy_decision
        return _strategy_endpoint(analyze_strategy_decision)


@api.route("/multi-timeframe")
class MultiTimeframeResource(Resource):
    @limiter.limit("3 per second")
    def post(self):
        """Multi-timeframe confluence analysis (5m → Monthly)."""
        from flask import request

        data = request.get_json(force=True)
        api_key = data.get("apikey", "")
        symbol = data.get("symbol", "")
        exchange = data.get("exchange", "NSE")

        if not symbol:
            return {"status": "error", "message": "symbol is required"}, 400
        if not api_key:
            return {"status": "error", "message": "apikey is required"}, 400
        if _validate_api_key(api_key) is None:
            return {"status": "error", "message": "Invalid openalgo apikey"}, 403

        try:
            from services.strategy_analysis_service import analyze_multi_timeframe
            result = analyze_multi_timeframe(symbol=symbol, exchange=exchange, api_key=api_key)
            return {"status": "success", "data": result}
        except Exception:
            logger.exception("Multi-timeframe error")
            return {"status": "error", "message": "An unexpected error occurred"}, 500


@api.route("/patterns")
class PatternsResource(Resource):
    @limiter.limit("10 per second")
    def post(self):
        """Candlestick pattern detection."""
        from services.strategy_analysis_service import analyze_candlestick_patterns
        return _strategy_endpoint(analyze_candlestick_patterns)


@api.route("/support-resistance")
class SupportResistanceResource(Resource):
    @limiter.limit("10 per second")
    def post(self):
        """Support and resistance levels from pivots."""
        from services.strategy_analysis_service import analyze_support_resistance
        return _strategy_endpoint(analyze_support_resistance)


@api.route("/news-sentiment")
class NewsSentimentResource(Resource):
    @limiter.limit("5 per second")
    def post(self):
        """News sentiment analysis — fetches headlines from Google News, MoneyControl, ET."""
        from flask import request

        data = request.get_json(force=True)
        api_key = data.get("apikey", "")
        symbol = data.get("symbol", "")
        exchange = data.get("exchange", "NSE")

        if not symbol:
            return {"status": "error", "message": "symbol is required"}, 400
        if not api_key:
            return {"status": "error", "message": "apikey is required"}, 400
        if _validate_api_key(api_key) is None:
            return {"status": "error", "message": "Invalid openalgo apikey"}, 403

        try:
            from ai.news_sentiment import analyze_news_sentiment
            result = analyze_news_sentiment(symbol=symbol, exchange=exchange)
            return {"status": "success", "data": result}
        except Exception:
            logger.exception("News sentiment error")
            return {"status": "error", "message": "An unexpected error occurred"}, 500


@api.route("/daily-report")
class DailyReportResource(Resource):
    @limiter.limit("2 per second")
    def post(self):
        """Generate daily market report — scans symbols, aggregates signals, news, levels."""
        from flask import request

        data = request.get_json(force=True)
        api_key = data.get("apikey", "")
        symbols = data.get("symbols", None)  # None = default NIFTY50 top 20
        exchange = data.get("exchange", "NSE")

        if not api_key:
            return {"status": "error", "message": "apikey is required"}, 400
        if _validate_api_key(api_key) is None:
            return {"status": "error", "message": "Invalid openalgo apikey"}, 403

        try:
            from ai.daily_report import generate_daily_report
            result = generate_daily_report(symbols=symbols, exchange=exchange, api_key=api_key)
            return {"status": "success", "data": result}
        except Exception:
            logger.exception("Daily report error")
            return {"status": "error", "message": "An unexpected error occurred"}, 500


@api.route("/research")
class ResearchResource(Resource):
    @limiter.limit("2 per second")
    def post(self):
        """Dexter-style autonomous financial research for a symbol."""
        from flask import request

        data = request.get_json(force=True)
        api_key = data.get("apikey", "")
        symbol = data.get("symbol", "")
        exchange = data.get("exchange", "NSE")
        question = data.get("question", "")

        if not symbol:
            return {"status": "error", "message": "symbol is required"}, 400
        if not api_key:
            return {"status": "error", "message": "apikey is required"}, 400
        if _validate_api_key(api_key) is None:
            return {"status": "error", "message": "Invalid openalgo apikey"}, 403

        try:
            from ai.research_agent import run_research
            result = run_research(symbol=symbol, exchange=exchange, question=question, api_key=api_key)
            return {"status": "success", "data": result}
        except Exception:
            logger.exception("Research agent error")
            return {"status": "error", "message": "An unexpected error occurred"}, 500
