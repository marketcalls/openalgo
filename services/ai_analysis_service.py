"""AI Analysis Service -- orchestrates indicator computation and signal generation.

Pipeline: fetch_ohlcv -> compute_indicators -> generate_signal -> log decision
"""

from dataclasses import dataclass, field

from ai.data_bridge import fetch_ohlcv
from ai.indicators import compute_indicators
from ai.signals import generate_signal
from ai.signals_advanced import generate_advanced_signals
from events import AgentAnalysisEvent, AgentErrorEvent
from utils.event_bus import bus
from utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class AnalysisResult:
    success: bool
    symbol: str
    exchange: str
    interval: str
    signal: str | None = None
    confidence: float = 0.0
    score: float = 0.0
    regime: str = "RANGING"
    sub_scores: dict = field(default_factory=dict)
    latest_indicators: dict = field(default_factory=dict)
    advanced_signals: dict = field(default_factory=dict)  # SMC, harmonics, candlesticks, CPR, etc.
    data_points: int = 0
    error: str | None = None


def analyze_symbol(
    symbol: str,
    exchange: str = "NSE",
    interval: str = "1d",
    api_key: str = "",
    weights: dict[str, float] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> AnalysisResult:
    """Run full analysis pipeline for a symbol.

    1. Fetch OHLCV data via OpenAlgo history service
    2. Compute 20+ technical indicators
    3. Generate weighted composite signal
    4. Emit analysis event for logging
    """
    try:
        # Step 1: Fetch data
        ohlcv = fetch_ohlcv(symbol, exchange, interval, api_key, start_date, end_date)
        if not ohlcv.success:
            bus.publish(AgentErrorEvent(
                symbol=symbol, error_message=ohlcv.error or "Data fetch failed",
                operation="analyze",
            ))
            return AnalysisResult(
                success=False, symbol=symbol, exchange=exchange,
                interval=interval, error=ohlcv.error,
            )

        if len(ohlcv.df) < 5:
            return AnalysisResult(
                success=False, symbol=symbol, exchange=exchange,
                interval=interval, error=f"Insufficient data: {len(ohlcv.df)} rows",
            )

        # Step 2: Compute indicators
        df_with_indicators = compute_indicators(ohlcv.df)

        # Step 3: Generate signal
        signal_result = generate_signal(df_with_indicators, weights=weights)

        # Extract latest indicator values for response
        latest = df_with_indicators.iloc[-1]
        indicator_keys = [
            "rsi_14", "rsi_7", "macd", "macd_signal", "macd_hist",
            "ema_9", "ema_21", "sma_50", "sma_200",
            "adx_14", "bb_high", "bb_low", "bb_pband",
            "supertrend", "supertrend_dir", "atr_14",
            "stoch_k", "stoch_d", "obv", "vwap",
        ]
        latest_indicators = {}
        for key in indicator_keys:
            val = latest.get(key)
            if val is not None and not (isinstance(val, float) and __import__("math").isnan(val)):
                latest_indicators[key] = round(float(val), 4)

        # Step 4: Run advanced indicators
        try:
            advanced = generate_advanced_signals(df_with_indicators)
        except Exception as e:
            logger.warning(f"Advanced indicators skipped for {symbol}: {e}")
            advanced = {}

        # Step 5: Emit event
        bus.publish(AgentAnalysisEvent(
            symbol=symbol, exchange=exchange,
            signal=signal_result["signal"],
            confidence=signal_result["confidence"],
            score=signal_result["score"],
            regime=signal_result["regime"],
        ))

        return AnalysisResult(
            success=True,
            symbol=symbol,
            exchange=exchange,
            interval=interval,
            signal=signal_result["signal"],
            confidence=signal_result["confidence"],
            score=signal_result["score"],
            regime=signal_result["regime"],
            sub_scores=signal_result["scores"],
            latest_indicators=latest_indicators,
            advanced_signals=advanced,
            data_points=len(ohlcv.df),
        )

    except Exception as e:
        logger.error(f"Analysis error for {symbol}: {e}")
        bus.publish(AgentErrorEvent(
            symbol=symbol, error_message=str(e), operation="analyze",
        ))
        return AnalysisResult(
            success=False, symbol=symbol, exchange=exchange,
            interval=interval, error=str(e),
        )
