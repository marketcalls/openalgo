"""Unified market analysis combining trend + momentum + OI signals."""

from dataclasses import dataclass, field

from ai.trend_analysis import compute_trend_score, TrendReport
from ai.momentum_analysis import compute_momentum_score, MomentumReport
from ai.oi_analysis import compute_oi_score, OIReport
from ai.data_bridge import fetch_ohlcv
from ai.indicators import compute_indicators
from utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class MarketAnalysisReport:
    success: bool
    symbol: str
    exchange: str
    trend: TrendReport | None = None
    momentum: MomentumReport | None = None
    oi: OIReport | None = None
    overall_bias: str = "neutral"  # "bullish", "bearish", "neutral"
    overall_score: float = 0.0    # -100 to +100
    error: str | None = None


def analyze_market(
    symbol: str,
    exchange: str = "NSE",
    interval: str = "1d",
    api_key: str = "",
    option_chain: dict | None = None,
) -> MarketAnalysisReport:
    """Run full market analysis: trend + momentum + OI.

    Orchestrates fetch_ohlcv -> compute_indicators -> trend/momentum/OI scoring.
    Weights: trend=35%, momentum=35%, oi=30%.
    """
    try:
        # Fetch OHLCV
        ohlcv = fetch_ohlcv(symbol, exchange, interval, api_key)
        if not ohlcv.success or len(ohlcv.df) < 10:
            return MarketAnalysisReport(
                success=False, symbol=symbol, exchange=exchange,
                error=ohlcv.error or "Insufficient data",
            )

        df = compute_indicators(ohlcv.df)

        # Trend analysis
        trend = compute_trend_score(df)

        # Momentum analysis
        momentum = compute_momentum_score(df)

        # OI analysis (if option chain provided)
        oi = compute_oi_score(option_chain) if option_chain else None

        # Overall bias: weighted combination
        scores = []
        if trend:
            t_score = trend.strength * (
                1 if trend.direction == "bullish"
                else -1 if trend.direction == "bearish"
                else 0
            )
            scores.append(("trend", t_score, 0.35))
        if momentum:
            scores.append(("momentum", momentum.score, 0.35))
        if oi:
            scores.append(("oi", oi.score, 0.30))

        total_weight = sum(w for _, _, w in scores)
        overall = sum(s * w for _, s, w in scores) / total_weight if total_weight > 0 else 0
        overall = round(max(min(overall, 100), -100), 1)

        if overall > 20:
            bias = "bullish"
        elif overall < -20:
            bias = "bearish"
        else:
            bias = "neutral"

        return MarketAnalysisReport(
            success=True, symbol=symbol, exchange=exchange,
            trend=trend, momentum=momentum, oi=oi,
            overall_bias=bias, overall_score=overall,
        )

    except Exception as e:
        logger.error(f"Market analysis error for {symbol}: {e}")
        return MarketAnalysisReport(
            success=False, symbol=symbol, exchange=exchange, error=str(e),
        )
