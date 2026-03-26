"""Extended signal generation using advanced indicators.

Adds SMC, candlestick, harmonic, divergence, and ML signals
to the base signal from signals.py.
"""

import math

import pandas as pd

from ai.indicators_advanced import compute_all_advanced
from ai.indicators_ml import compute_ml_confidence
from utils.logging import get_logger

logger = get_logger(__name__)


def generate_advanced_signals(df: pd.DataFrame) -> dict:
    """Generate advanced signal summary from all advanced indicators.

    Returns dict with counts and details of detected patterns.
    """
    # Run all advanced indicators
    df = compute_all_advanced(df)
    df = compute_ml_confidence(df)

    latest = df.iloc[-1]
    signals = {
        "smc": {},
        "candlestick": [],
        "cpr": {},
        "fibonacci": {},
        "harmonic": {},
        "divergence": {},
        "volume": {},
        "ml_confidence": {},
    }

    # SMC signals (latest bar)
    for col in ["smc_bos_bullish", "smc_bos_bearish", "smc_choch_bullish", "smc_choch_bearish",
                 "smc_fvg_bullish", "smc_fvg_bearish", "smc_ob_bullish", "smc_ob_bearish"]:
        if col in df.columns and latest.get(col, 0) == 1:
            signals["smc"][col] = True

    # Active candlestick patterns (last 3 bars)
    for col in df.columns:
        if col.startswith("cdl_") and df[col].iloc[-3:].sum() > 0:
            signals["candlestick"].append(col.replace("cdl_", ""))

    # CPR levels
    for col in ["pivot", "r1", "s1", "r2", "s2", "r3", "s3", "bc", "tc"]:
        if col in df.columns:
            val = latest.get(col)
            if val is not None and not (isinstance(val, float) and math.isnan(val)):
                signals["cpr"][col] = round(float(val), 2)

    # Fibonacci
    signals["fibonacci"]["long"] = int(latest.get("fib_long", 0))
    signals["fibonacci"]["short"] = int(latest.get("fib_short", 0))

    # Harmonic
    # Check last 5 bars for recent harmonic patterns
    signals["harmonic"]["bullish"] = int(df["harmonic_bullish"].iloc[-5:].sum() > 0) if "harmonic_bullish" in df.columns else 0
    signals["harmonic"]["bearish"] = int(df["harmonic_bearish"].iloc[-5:].sum() > 0) if "harmonic_bearish" in df.columns else 0

    # Divergence
    signals["divergence"]["rsi_bullish"] = int(latest.get("rsi_bull_divergence", 0))
    signals["divergence"]["rsi_bearish"] = int(latest.get("rsi_bear_divergence", 0))

    # Volume
    signals["volume"]["exhaustion"] = int(latest.get("volume_exhaustion", 0))
    signals["volume"]["vwap_bb_confluence"] = int(latest.get("vwap_bb_confluence", 0))

    # ML confidence
    signals["ml_confidence"]["buy"] = float(latest.get("ml_buy_confidence", 0))
    signals["ml_confidence"]["sell"] = float(latest.get("ml_sell_confidence", 0))

    return signals
