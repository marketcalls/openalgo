# services/llm_service.py
"""LLM service for generating AI commentary on market analysis."""

from ai.llm_router import LLMRouter, LLMResponse
from utils.logging import get_logger

logger = get_logger(__name__)

_router = LLMRouter(timeout=30)

ANALYSIS_SYSTEM_PROMPT = """You are a concise Indian stock market analyst. Given technical analysis data,
provide a 2-3 sentence trading commentary. Include: key signal, risk level, and suggested action.
Be direct. Use plain English. Mention specific indicator values that matter."""


def generate_commentary(analysis_data: dict) -> LLMResponse:
    """Generate AI commentary for a stock analysis result."""
    symbol = analysis_data.get("symbol", "?")
    signal = analysis_data.get("signal", "HOLD")
    confidence = analysis_data.get("confidence", 0)
    score = analysis_data.get("score", 0)
    regime = analysis_data.get("regime", "RANGING")
    scores = analysis_data.get("sub_scores", {})
    indicators = analysis_data.get("indicators", {})

    prompt = f"""Symbol: {symbol}
Signal: {signal} (confidence: {confidence}%, score: {score})
Market Regime: {regime}
Sub-signals: {scores}
Key indicators: RSI={indicators.get('rsi_14', '?')}, MACD={indicators.get('macd', '?')}, ADX={indicators.get('adx_14', '?')}

Provide a brief trading commentary."""

    return _router.generate(prompt, system=ANALYSIS_SYSTEM_PROMPT)
