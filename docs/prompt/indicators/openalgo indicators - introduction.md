# Indicators

## OpenAlgo Technical Indicators Library

OpenAlgo Technical Indicators is a high-performance Python library designed for comprehensive technical analysis with a focus on speed, accuracy, and ease of use. Built from the ground up with modern optimization techniques, it provides over 80 technical indicators across all major categories.

### Import Statement

```python
from openalgo import ta
```

### List of Supported Indicators

### Trend Indicators

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

### Momentum Indicators

* **RSI** - Relative Strength Index
* **MACD** - Moving Average Convergence Divergence
* **Stochastic** - Stochastic Oscillator
* **CCI** - Commodity Channel Index
* **WilliamsR** - Williams %R
* **BOP** - Balance of Power
* **ElderRay** - Elder Ray Index (Bull/Bear Power)
* **Fisher** - Fisher Transform
* **CRSI** - Connors RSI

### Volatility Indicators

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

### Volume Indicators

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

### Statistical Indicators

* **LINREG** - Linear Regression
* **LRSLOPE** - Linear Regression Slope
* **CORREL** - Pearson Correlation Coefficient
* **BETA** - Beta Coefficient
* **VAR** - Variance
* **TSF** - Time Series Forecast
* **MEDIAN** - Rolling Median
* **MedianBands** - Median with Bands
* **MODE** - Rolling Mode

### Hybrid Indicators

* **ADX** - Average Directional Index
* **Aroon** - Aroon Indicator
* **PivotPoints** - Pivot Points
* **SAR** - Parabolic SAR
* **DMI** - Directional Movement Index
* **WilliamsFractals** - Williams Fractals
* **RWI** - Random Walk Index

### Utility Functions

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


---

# Agent Instructions: Querying This Documentation

If you need additional information that is not directly available in this page, you can query the documentation dynamically by asking a question.

Perform an HTTP GET request on the current page URL with the `ask` query parameter:

```
GET https://docs.openalgo.in/trading-platform/python/indicators.md?ask=<question>
```

The question should be specific, self-contained, and written in natural language.
The response will contain a direct answer to the question and relevant excerpts and sources from the documentation.

Use this mechanism when the answer is not explicitly present in the current page, you need clarification or additional context, or you want to retrieve related documentation sections.
