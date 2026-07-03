---
type: Indicator
title: Technical Indicators Introduction
description: Introduction to the OpenAlgo ta technical indicator library and how to use it
resource: https://github.com/marketcalls/openalgo/blob/main/docs/prompt/indicators/openalgo%20indicators%20-%20introduction.md
tags:
- indicators
- ta
- technical-analysis
- python
timestamp: '2026-07-03T00:00:00+00:00'
---

# Technical Indicators Introduction

## OpenAlgo Technical Indicators Library

OpenAlgo Technical Indicators is a high-performance Python library designed for comprehensive technical analysis with a focus on speed, accuracy, and ease of use. Built from the ground up with modern optimization techniques, it provides over 80 technical indicators across all major categories.

Indicators are computed on OHLCV data. In a typical workflow you fetch historical candles via the [Python SDK](../sdk/python-sdk.md) (or the [History API](../api/market-data/history.md)) into a pandas DataFrame, then pass the price/volume series into the `ta` functions. See the bundle [Overview](../overview.md) for how indicators fit into the broader OpenAlgo platform.

### Import Statement

```python
from openalgo import ta
```

### List of Supported Indicators

### [Trend Indicators](trend.md)

* **SMA** - Simple Moving Average
* **EMA** - Exponential Moving Average
* **WMA** - Weighted Moving Average
* **DEMA** - Double Exponential Moving Average
* **TEMA** - Triple Exponential Moving Average
* **HMA** - Hull Moving Average
* **VWMA** - Volume Weighted Moving Average
* **ALMA** - Arnaud Legoux Moving Average
* **KAMA** - Kaufman's Adaptive Moving Average
* **ZLEMA** - Zero Lag Exponential Moving Average
* **T3** - T3 Moving Average
* **FRAMA** - Fractal Adaptive Moving Average
* **TRIMA** - Triangular Moving Average
* **McGinley** - McGinley Dynamic
* **VIDYA** - Variable Index Dynamic Average
* **Alligator** - Bill Williams Alligator
* **MovingAverageEnvelopes** - Moving Average Envelopes
* **Supertrend** - Supertrend Indicator
* **Ichimoku** - Ichimoku Cloud
* **ChandeKrollStop** - Chande Kroll Stop

### [Momentum Indicators](momentum.md)

* **RSI** - Relative Strength Index
* **MACD** - Moving Average Convergence Divergence
* **Stochastic** - Stochastic Oscillator
* **CCI** - Commodity Channel Index
* **WilliamsR** - Williams %R
* **BOP** - Balance of Power
* **ElderRay** - Elder Ray Index (Bull/Bear Power)
* **Fisher** - Fisher Transform
* **CRSI** - Connors RSI

### [Volatility Indicators](volatility.md)

* **ATR** - Average True Range
* **BollingerBands** - Bollinger Bands
* **Keltner** - Keltner Channel
* **Donchian** - Donchian Channel
* **Chaikin** - Chaikin Volatility
* **NATR** - Normalized Average True Range
* **RVI** - Relative Volatility Index (volatility version)
* **ULTOSC** - Ultimate Oscillator
* **TRANGE** - True Range
* **MASS** - Mass Index
* **BBPercent** - Bollinger Bands %B
* **BBWidth** - Bollinger Bandwidth
* **ChandelierExit** - Chandelier Exit
* **HistoricalVolatility** - Historical Volatility
* **UlcerIndex** - Ulcer Index
* **STARC** - STARC Bands

### [Volume Indicators](volume.md)

* **OBV** - On Balance Volume
* **OBVSmoothed** - On Balance Volume with Smoothing
* **VWAP** - Volume Weighted Average Price
* **MFI** - Money Flow Index
* **ADL** - Accumulation/Distribution Line
* **CMF** - Chaikin Money Flow
* **EMV** - Ease of Movement
* **FI** - Elder Force Index
* **NVI** - Negative Volume Index
* **PVI** - Positive Volume Index
* **VOLOSC** - Volume Oscillator
* **VROC** - Volume Rate of Change
* **KlingerVolumeOscillator** - Klinger Volume Oscillator
* **PriceVolumeTrend** - Price Volume Trend
* **RVOL** - Relative Volume

### Oscillators

* **ROC** - Rate of Change
* **CMO** - Chande Momentum Oscillator
* **TRIX** - Triple Exponential Average
* **UO** - Ultimate Oscillator
* **AO** - Awesome Oscillator
* **AC** - Accelerator Oscillator
* **PPO** - Percentage Price Oscillator
* **PO** - Price Oscillator
* **DPO** - Detrended Price Oscillator
* **AROONOSC** - Aroon Oscillator
* **StochRSI** - Stochastic RSI
* **RVI** - Relative Vigor Index (oscillator version)
* **CHO** - Chaikin Oscillator
* **CHOP** - Choppiness Index
* **KST** - Know Sure Thing
* **TSI** - True Strength Index
* **VI** - Vortex Indicator
* **STC** - Schaff Trend Cycle
* **GatorOscillator** - Gator Oscillator
* **Coppock** - Coppock Curve

### [Statistical Indicators](statistical.md)

* **LINREG** - Linear Regression
* **LRSLOPE** - Linear Regression Slope
* **CORREL** - Pearson Correlation Coefficient
* **BETA** - Beta Coefficient
* **VAR** - Variance
* **TSF** - Time Series Forecast
* **MEDIAN** - Rolling Median
* **MedianBands** - Median with Bands
* **MODE** - Rolling Mode

### [Hybrid Indicators](hybrid.md)

* **ADX** - Average Directional Index
* **Aroon** - Aroon Indicator
* **PivotPoints** - Pivot Points
* **SAR** - Parabolic SAR
* **DMI** - Directional Movement Index
* **WilliamsFractals** - Williams Fractals
* **RWI** - Random Walk Index

### [Utility Functions](utility.md)

* **crossover** - Series crossover detection
* **crossunder** - Series crossunder detection
* **highest** - Highest value over period
* **lowest** - Lowest value over period
* **change** - Change in value
* **roc** - Rate of change
* **stdev** - Standard deviation
* **exrem** - Excess removal
* **flip** - Flip function
* **valuewhen** - Value when condition
* **rising** - Rising detection
* **falling** - Falling detection
* **cross** - Cross detection (both directions)

### Perfect For

* **Quantitative Analysts** building trading strategies
* **Financial Engineers** developing risk management systems
* **Algorithmic Traders** requiring fast, reliable technical analysis
* **Research Teams** conducting market analysis and backtesting
* **Financial Applications** needing embedded technical analysis capabilities

OpenAlgo Indicators bridges the gap between ease of use and performance, making sophisticated technical analysis accessible to both beginners and experts while maintaining the speed and accuracy demanded by professional trading systems.

# Citations
- Official docs: https://docs.openalgo.in
- Source: https://github.com/marketcalls/openalgo/blob/main/docs/prompt/indicators/openalgo%20indicators%20-%20introduction.md
