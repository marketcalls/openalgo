"""AI Analysis Service -- orchestrates indicator computation and signal generation.

Pipeline: fetch_ohlcv -> compute_indicators -> generate_signal -> log decision
"""

from dataclasses import dataclass, field

from ai.data_bridge import fetch_ohlcv
from ai.indicators import compute_indicators
from ai.signals import generate_signal
from ai.signals_advanced import generate_advanced_signals
from ai.trade_setup import compute_trade_setup
from ai.chart_data_builder import build_chart_overlays
from ai.decision_engine import make_decision
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
    advanced_signals: dict = field(default_factory=dict)
    trade_setup: dict = field(default_factory=dict)
    chart_overlays: dict = field(default_factory=dict)
    decision: dict = field(default_factory=dict)
    candles: list = field(default_factory=list)  # OHLCV for chart (last 200 bars)
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

        # Step 5: Compute trade setup (entry, SL, targets, quantity)
        ltp = float(ohlcv.df["close"].iloc[-1])
        cpr = advanced.get("cpr", {}) if isinstance(advanced, dict) else {}
        try:
            setup = compute_trade_setup(
                signal=signal_result["signal"],
                score=signal_result["score"],
                confidence=signal_result["confidence"],
                indicators=latest_indicators,
                cpr_levels=cpr,
                ltp=ltp,
            )
            trade_setup_dict = {
                "action": setup.action,
                "entry": setup.entry,
                "stop_loss": setup.stop_loss,
                "target_1": setup.target_1,
                "target_2": setup.target_2,
                "target_3": setup.target_3,
                "sl_distance": setup.sl_distance,
                "sl_percent": setup.sl_percent,
                "risk_reward_1": setup.risk_reward_1,
                "risk_reward_2": setup.risk_reward_2,
                "risk_reward_3": setup.risk_reward_3,
                "suggested_qty": setup.suggested_qty,
                "risk_amount": setup.risk_amount,
                "reason": setup.reason,
            }
        except Exception as e:
            logger.warning(f"Trade setup skipped for {symbol}: {e}")
            trade_setup_dict = {}

        # Step 5a: Build chart overlays
        try:
            chart_overlays = build_chart_overlays(
                df_with_indicators, latest_indicators,
                cpr=cpr, trade_setup=trade_setup_dict,
            )
        except Exception as e:
            logger.warning(f"Chart overlays skipped for {symbol}: {e}")
            chart_overlays = {"lines": [], "bands": [], "markers": [], "levels": []}

        # Step 5b: Make trading decision
        try:
            trend_dir = "bullish" if latest_indicators.get("supertrend_dir", 0) == 1 else (
                "bearish" if latest_indicators.get("supertrend_dir", 0) == -1 else "neutral"
            )
            momentum = "bullish" if latest_indicators.get("macd_hist", 0) > 0 else (
                "bearish" if latest_indicators.get("macd_hist", 0) < 0 else "neutral"
            )
            ml = advanced.get("ml_confidence", {}) if isinstance(advanced, dict) else {}
            decision = make_decision(
                signal=signal_result["signal"],
                score=signal_result["score"],
                confidence=signal_result["confidence"],
                trend_direction=trend_dir,
                momentum_bias=momentum,
                trade_setup=trade_setup_dict,
                advanced_signals=advanced if isinstance(advanced, dict) else {},
                ml_buy=ml.get("buy", 0),
                ml_sell=ml.get("sell", 0),
            )
            decision_dict = {
                "action": decision.action,
                "confidence_label": decision.confidence_label,
                "entry": decision.entry,
                "stop_loss": decision.stop_loss,
                "target": decision.target,
                "quantity": decision.quantity,
                "risk_amount": decision.risk_amount,
                "risk_reward": decision.risk_reward,
                "reason": decision.reason,
                "risk_warning": decision.risk_warning,
                "supporting_signals": decision.supporting_signals,
                "opposing_signals": decision.opposing_signals,
                "score": decision.score,
            }
        except Exception as e:
            logger.warning(f"Decision engine skipped for {symbol}: {e}")
            decision_dict = {}

        # Step 6: Prepare candle data for chart (last 200 bars)
        chart_df = ohlcv.df.tail(200)
        candles = [
            {
                "time": int(i),
                "open": round(float(row["open"]), 2),
                "high": round(float(row["high"]), 2),
                "low": round(float(row["low"]), 2),
                "close": round(float(row["close"]), 2),
            }
            for i, row in chart_df.iterrows()
        ]

        # Step 7: Emit event
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
            trade_setup=trade_setup_dict,
            chart_overlays=chart_overlays,
            decision=decision_dict,
            candles=candles,
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
