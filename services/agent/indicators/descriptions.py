"""One sentence per ``ta`` callable, so the catalogue is searchable by intent.

``list_indicators`` and ``describe_indicator`` are how the model finds a name it
must not guess. Matching on the method name alone would only answer a question
that already knows the answer, so the description is part of the haystack: a
model asking for "bollinger", "trend strength" or "money flow" finds the right
entry without knowing it is called ``bbands``, ``adx`` or ``mfi``.

Kept apart from the registry on purpose. The registry's ``note`` field carries
caveats a caller must obey; this file carries prose a caller searches. Mixing
them would mean either searching over trap text or losing the traps.
"""

from __future__ import annotations

__all__ = ["DESCRIPTIONS", "describe"]

DESCRIPTIONS: dict[str, str] = {
    # trend
    "sma": "Simple Moving Average: unweighted mean of the last n closes.",
    "ema": "Exponential Moving Average: weights recent prices more heavily than SMA.",
    "wma": "Weighted Moving Average: linear weighting, most recent bar weighted highest.",
    "dema": "Double Exponential Moving Average: reduced lag versus EMA.",
    "tema": "Triple Exponential Moving Average: further lag reduction versus DEMA.",
    "hma": "Hull Moving Average: fast and smooth, popular for trend direction.",
    "vwma": "Volume Weighted Moving Average: average price weighted by traded volume.",
    "alma": "Arnaud Legoux Moving Average: Gaussian-weighted, tunable offset and sigma.",
    "kama": "Kaufman Adaptive Moving Average: speeds up in trends, slows in chop.",
    "zlema": "Zero Lag Exponential Moving Average: de-lagged EMA variant.",
    "t3": "T3 Moving Average: smoother multi-pass EMA with a volume factor.",
    "frama": "Fractal Adaptive Moving Average: adapts using the fractal dimension of price.",
    "trima": "Triangular Moving Average: double-smoothed, weights the middle of the window.",
    "mcginley": "McGinley Dynamic: self-adjusting average that tracks fast markets.",
    "vidya": "Variable Index Dynamic Average: volatility-adjusted moving average.",
    "alligator": "Bill Williams Alligator: three shifted smoothed averages, jaw teeth lips.",
    "ma_envelopes": "Moving Average Envelopes: bands a fixed percent above and below an MA.",
    "supertrend": "Supertrend: ATR-based trailing stop and trend direction flag.",
    "ichimoku": "Ichimoku Cloud: conversion, base, two spans and the lagging line.",
    "ckstop": "Chande Kroll Stop: ATR-derived long and short stop levels.",
    # momentum
    "rsi": "Relative Strength Index: overbought above 70, oversold below 30.",
    "macd": "MACD: fast minus slow EMA, with a signal line and a histogram.",
    "stochastic": "Stochastic Oscillator: close relative to the recent high-low range.",
    "cci": "Commodity Channel Index: deviation from the typical price average.",
    "williams_r": "Williams %R: inverted stochastic, measures overbought and oversold.",
    "bop": "Balance of Power: buying versus selling pressure from the OHLC bar shape.",
    "elderray": "Elder Ray: bull power and bear power relative to an EMA.",
    "fisher": "Fisher Transform: sharpens turning points by normalising price.",
    "crsi": "Connors RSI: composite of RSI, streak RSI and rate-of-change rank.",
    # volatility
    "atr": "Average True Range: average size of a bar, the standard volatility measure.",
    "bbands": "Bollinger Bands: an SMA with standard-deviation bands above and below.",
    "keltner": "Keltner Channel: an EMA with ATR-based bands.",
    "donchian": "Donchian Channel: highest high and lowest low over a lookback.",
    "chaikin": "Chaikin Volatility: rate of change of the high-low range.",
    "natr": "Normalized ATR: ATR as a percentage of price, comparable across symbols.",
    "ultimate_oscillator": "Ultimate Oscillator: momentum blended across three timeframes.",
    "true_range": "True Range: the raw per-bar range including gaps.",
    "massindex": "Mass Index: detects reversals through range expansion.",
    "bbpercent": "Bollinger %B: where price sits within the Bollinger Bands, 0 to 1.",
    "bbwidth": "Bollinger Bandwidth: band width relative to the middle, a squeeze gauge.",
    "chandelier_exit": "Chandelier Exit: ATR trailing stops for long and short positions.",
    "hv": "Historical Volatility: annualised standard deviation of log returns.",
    "ulcerindex": "Ulcer Index: downside volatility from drawdown depth and duration.",
    "starc": "STARC Bands: ATR bands around a short moving average.",
    # volume
    "obv": "On Balance Volume: cumulative volume signed by the direction of the close.",
    "obv_smoothed": "On Balance Volume with an optional moving average and Bollinger Bands.",
    "vwap": "Volume Weighted Average Price: the session benchmark fill price.",
    "mfi": "Money Flow Index: a volume-weighted RSI, overbought and oversold on flow.",
    "adl": "Accumulation Distribution Line: cumulative money flow from the close position.",
    "cmf": "Chaikin Money Flow: accumulation versus distribution over a lookback.",
    "emv": "Ease of Movement: how much volume is needed to move price.",
    "force_index": "Elder Force Index: price change multiplied by volume.",
    "nvi": "Negative Volume Index: tracks price on falling-volume days.",
    "nvi_with_ema": "Negative Volume Index with its EMA signal line.",
    "pvi": "Positive Volume Index: tracks price on rising-volume days.",
    "pvi_with_signal": "Positive Volume Index with a signal line.",
    "volosc": "Volume Oscillator: difference between fast and slow volume averages.",
    "vroc": "Volume Rate of Change: percentage change in volume.",
    "kvo": "Klinger Volume Oscillator: long-term money flow with a trigger line.",
    "pvt": "Price Volume Trend: cumulative volume weighted by percent price change.",
    "rvol": "Relative Volume: current volume against its recent average.",
    # oscillators
    "cmo": "Chande Momentum Oscillator: momentum from up versus down sums.",
    "trix": "TRIX: rate of change of a triple-smoothed EMA.",
    "uo_oscillator": "Ultimate Oscillator (duplicate of ultimate_oscillator).",
    "awesome_oscillator": "Awesome Oscillator: 5 against 34 period midpoint momentum.",
    "accelerator_oscillator": "Accelerator Oscillator: acceleration of the Awesome Oscillator.",
    "ppo": "Percentage Price Oscillator: MACD in percent, comparable across symbols.",
    "po": "Price Oscillator: difference between a fast and a slow moving average.",
    "dpo": "Detrended Price Oscillator: removes trend to expose cycles.",
    "aroon_oscillator": "Aroon Oscillator: Aroon up minus Aroon down, trend direction.",
    "stochrsi": "Stochastic RSI: a stochastic applied to RSI, a faster overbought gauge.",
    "rvi": "Relative Vigor Index: close against open relative to the bar range.",
    "cho": "Chaikin Oscillator: MACD of the Accumulation Distribution Line.",
    "chop": "Choppiness Index: high means ranging, low means trending.",
    "kst": "Know Sure Thing: smoothed multi-period rate-of-change momentum.",
    "tsi": "True Strength Index: double-smoothed momentum with a signal line.",
    "vi": "Vortex Indicator: competing positive and negative trend movement.",
    "stc": "Schaff Trend Cycle: MACD passed through a stochastic, a fast trend signal.",
    "gator_oscillator": "Gator Oscillator: convergence and divergence of the Alligator lines.",
    "coppock": "Coppock Curve: long-term momentum, a classic bottom finder.",
    # statistical
    "linreg": "Linear Regression: fitted value of the regression line at each bar.",
    "lrslope": "Linear Regression Slope: the trend gradient.",
    "correlation": "Pearson correlation between two price series. Needs a second symbol.",
    "beta": "Beta of an asset against a benchmark. Needs a second symbol.",
    "variance": "Variance of returns, optionally with z-score and standard deviation.",
    "tsf": "Time Series Forecast: the regression line projected one bar ahead.",
    "median": "Rolling median of price.",
    "median_bands": "Rolling median with ATR bands above and below.",
    "mode": "Rolling mode of price, binned.",
    # hybrid
    "adx": "Average Directional Index with plus and minus DI. Measures trend strength.",
    "aroon": "Aroon up and down: how recently the high and the low occurred.",
    "pivot_points": "Pivot Points: the pivot with three support and three resistance levels.",
    "psar": "Parabolic SAR: trailing stop and reversal levels.",
    "dmi": "Directional Movement Index: plus DI and minus DI without the ADX line.",
    "fractals": "Williams Fractals: local swing high and swing low markers.",
    "rwi": "Random Walk Index: whether movement exceeds random expectation.",
    # talib extras
    "mom": "Momentum: price minus the price n bars ago.",
    "rocp": "Rate of Change as a proportion.",
    "rocr": "Rate of Change as a ratio.",
    "rocr100": "Rate of Change as a ratio scaled to 100.",
    "midpoint": "Midpoint of the highest and lowest close over a lookback.",
    "apo": "Absolute Price Oscillator: fast minus slow moving average.",
    "medprice": "Median Price: the average of the high and the low.",
    "typprice": "Typical Price: the average of high, low and close.",
    "wclprice": "Weighted Close Price: close weighted double against high and low.",
    "midprice": "Midprice: the average of the highest high and the lowest low.",
    "avgprice": "Average Price: the mean of open, high, low and close.",
    "plus_dm": "Plus Directional Movement: the raw upward movement component.",
    "minus_dm": "Minus Directional Movement: the raw downward movement component.",
    "dx": "Directional Index: the un-smoothed precursor to ADX.",
    "adxr": "ADX Rating: the average of ADX now and n bars ago.",
    "stochf": "Fast Stochastic: %K and %D without the initial slowing.",
    "linregangle": "Linear Regression Angle: the trend slope expressed in degrees.",
    "linregintercept": "Linear Regression Intercept.",
    # utilities
    "crossover": "True on the bar where the first series crosses above the second.",
    "crossunder": "True on the bar where the first series crosses below the second.",
    "cross": "True on any cross between two series, in either direction.",
    "highest": "Highest value over a lookback window.",
    "lowest": "Lowest value over a lookback window.",
    "change": "Difference between the current value and the value n bars ago.",
    "roc": "Percentage rate of change over n bars.",
    "stdev": "Rolling standard deviation.",
    "exrem": "Removes repeated signals until the opposing signal fires.",
    "flip": "Latching toggle: turns on at the primary signal, off at the secondary.",
    "valuewhen": "The value of a series at the nth most recent bar where a condition was true.",
    "rising": "True when a series has risen for n consecutive bars.",
    "falling": "True when a series has fallen for n consecutive bars.",
}


def describe(name: str) -> str:
    """Return the one-line description of an indicator.

    Args:
        name: The exact ``ta`` method name.

    Returns:
        The sentence, or an empty string when none is recorded. An empty string
        is dropped from a tool result rather than rendered as a blank field.
    """
    return DESCRIPTIONS.get(name, "")
