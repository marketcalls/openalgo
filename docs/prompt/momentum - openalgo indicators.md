# Momentum

Momentum indicators measure the speed and strength of price movements, helping identify overbought/oversold conditions and potential trend reversals.

### Import Statement

```python
from openalgo import ta
```

### Available Momentum Indicators

***

### Relative Strength Index (RSI)

RSI is a momentum oscillator that measures the speed and magnitude of price changes, oscillating between 0 and 100.

#### Usage

```python
rsi_result = ta.rsi(data, period=14)
```

#### Parameters

* **data** *(array-like)*: Price data (typically closing prices)
* **period** *(int, default=14)*: Number of periods for RSI calculation

#### Returns

* **array**: RSI values (range: 0 to 100) in the same format as input

#### Example

```python
from openalgo import api, ta

# Get market data
client = api(api_key='your_api_key_here', host='http://127.0.0.1:5000')
df = client.history(symbol="SBIN", exchange="NSE", interval="5m", 
                   start_date="2025-04-01", end_date="2025-04-08")

# Calculate RSI
df['RSI_14'] = ta.rsi(df['close'], 14)
df['RSI_21'] = ta.rsi(df['close'], 21)

print(df[['close', 'RSI_14', 'RSI_21']].tail())
```

***

### Moving Average Convergence Divergence (MACD)

MACD is a trend-following momentum indicator showing the relationship between two exponential moving averages.

#### Usage

```python
macd_line, signal_line, histogram = ta.macd(data, fast_period=12, slow_period=26, signal_period=9)
```

#### Parameters

* **data** *(array-like)*: Price data (typically closing prices)
* **fast\_period** *(int, default=12)*: Period for fast EMA
* **slow\_period** *(int, default=26)*: Period for slow EMA
* **signal\_period** *(int, default=9)*: Period for signal line EMA

#### Returns

* **tuple**: (macd\_line, signal\_line, histogram) arrays

#### Example

```python
# Calculate MACD
macd_line, signal_line, histogram = ta.macd(df['close'])

# Add to DataFrame
df['MACD'] = macd_line
df['MACD_Signal'] = signal_line
df['MACD_Histogram'] = histogram

# Custom parameters
macd_fast, signal_fast, hist_fast = ta.macd(df['close'], fast_period=8, slow_period=21, signal_period=5)

print(df[['close', 'MACD', 'MACD_Signal', 'MACD_Histogram']].tail())
```

***

### Stochastic Oscillator

The Stochastic Oscillator compares a security's closing price to its price range over a given time period.

#### Usage

```python
k_percent, d_percent = ta.stochastic(high, low, close, k_period=14, d_period=3)
```

#### Parameters

* **high** *(array-like)*: High prices
* **low** *(array-like)*: Low prices
* **close** *(array-like)*: Closing prices
* **k\_period** *(int, default=14)*: Period for %K calculation
* **d\_period** *(int, default=3)*: Period for %D calculation (SMA of %K)

#### Returns

* **tuple**: (k\_percent, d\_percent) arrays

#### Example

```python
# Calculate Stochastic Oscillator
stoch_k, stoch_d = ta.stochastic(df['high'], df['low'], df['close'])

# Add to DataFrame
df['Stoch_K'] = stoch_k
df['Stoch_D'] = stoch_d

# Custom parameters
stoch_k_fast, stoch_d_fast = ta.stochastic(df['high'], df['low'], df['close'], 
                                          k_period=5, d_period=3)

print(df[['close', 'Stoch_K', 'Stoch_D']].tail())
```

***

### Commodity Channel Index (CCI)

CCI measures the current price level relative to an average price level over a given period.

#### Usage

```python
cci_result = ta.cci(high, low, close, period=20)
```

#### Parameters

* **high** *(array-like)*: High prices
* **low** *(array-like)*: Low prices
* **close** *(array-like)*: Closing prices
* **period** *(int, default=20)*: Number of periods for CCI calculation

#### Returns

* **array**: CCI values in the same format as input

#### Example

```python
# Calculate CCI
df['CCI_20'] = ta.cci(df['high'], df['low'], df['close'], 20)
df['CCI_14'] = ta.cci(df['high'], df['low'], df['close'], 14)

print(df[['close', 'CCI_20', 'CCI_14']].tail())
```

***

### Williams %R

Williams %R is a momentum indicator that measures overbought and oversold levels on a scale from 0 to -100.

#### Usage

```python
williams_r = ta.williams_r(high, low, close, period=14)
```

#### Parameters

* **high** *(array-like)*: High prices
* **low** *(array-like)*: Low prices
* **close** *(array-like)*: Closing prices
* **period** *(int, default=14)*: Number of periods for Williams %R calculation

#### Returns

* **array**: Williams %R values (range: 0 to -100) in the same format as input

#### Example

```python
# Calculate Williams %R
df['Williams_R'] = ta.williams_r(df['high'], df['low'], df['close'])
df['Williams_R_21'] = ta.williams_r(df['high'], df['low'], df['close'], 21)

print(df[['close', 'Williams_R', 'Williams_R_21']].tail())
```

***

### Balance of Power (BOP)

Balance of Power measures the strength of buyers versus sellers by assessing the ability of each side to drive prices to an extreme level.

#### Usage

```python
bop_result = ta.bop(open_prices, high, low, close)
```

#### Parameters

* **open\_prices** *(array-like)*: Opening prices
* **high** *(array-like)*: High prices
* **low** *(array-like)*: Low prices
* **close** *(array-like)*: Closing prices

#### Returns

* **array**: BOP values in the same format as input

#### Example

```python
# Calculate Balance of Power
df['BOP'] = ta.bop(df['open'], df['high'], df['low'], df['close'])

print(df[['close', 'BOP']].tail())
```

***

### Elder Ray Index

Elder Ray Index consists of Bull Power and Bear Power, measuring the ability of bulls and bears to drive prices above or below an EMA.

#### Usage

```python
bull_power, bear_power = ta.elderray(high, low, close, period=13)
```

#### Parameters

* **high** *(array-like)*: High prices
* **low** *(array-like)*: Low prices
* **close** *(array-like)*: Closing prices
* **period** *(int, default=13)*: Period for EMA calculation

#### Returns

* **tuple**: (bull\_power, bear\_power) arrays

#### Example

```python
# Calculate Elder Ray Index
bull_power, bear_power = ta.elderray(df['high'], df['low'], df['close'])

# Add to DataFrame
df['Bull_Power'] = bull_power
df['Bear_Power'] = bear_power

print(df[['close', 'Bull_Power', 'Bear_Power']].tail())
```

***

### Fisher Transform

The Fisher Transform converts prices into a Gaussian normal distribution, making it easier to identify turning points.

#### Usage

```python
fisher, trigger = ta.fisher(high, low, length=9)
```

#### Parameters

* **high** *(array-like)*: High prices
* **low** *(array-like)*: Low prices
* **length** *(int, default=9)*: Length for highest/lowest calculation

#### Returns

* **tuple**: (fisher, trigger) arrays

#### Example

```python
# Calculate Fisher Transform
fisher, fisher_trigger = ta.fisher(df['high'], df['low'])

# Add to DataFrame
df['Fisher'] = fisher
df['Fisher_Trigger'] = fisher_trigger

# Custom length
fisher_14, trigger_14 = ta.fisher(df['high'], df['low'], length=14)

print(df[['close', 'Fisher', 'Fisher_Trigger']].tail())
```

***

### Connors RSI (CRSI)

Connors RSI is a composite momentum oscillator consisting of three components: RSI of price, RSI of updown streak, and percent rank of 1-period ROC.

#### Usage

```python
crsi_result = ta.crsi(data, lenrsi=3, lenupdown=2, lenroc=100)
```

#### Parameters

* **data** *(array-like)*: Price data (typically closing prices)
* **lenrsi** *(int, default=3)*: RSI Length (period for price RSI)
* **lenupdown** *(int, default=2)*: UpDown Length (period for streak RSI)
* **lenroc** *(int, default=100)*: ROC Length (period for ROC percent rank)

#### Returns

* **array**: Connors RSI values in the same format as input

#### Example

```python
# Calculate Connors RSI
df['CRSI'] = ta.crsi(df['close'])

# Custom parameters
df['CRSI_Custom'] = ta.crsi(df['close'], lenrsi=5, lenupdown=3, lenroc=50)

print(df[['close', 'CRSI', 'CRSI_Custom']].tail())
```

***

### Complete Example: Multiple Momentum Indicators

```python
from openalgo import api, ta
import pandas as pd

# Get market data
client = api(api_key='your_api_key_here', host='http://127.0.0.1:5000')
df = client.history(symbol="SBIN", exchange="NSE", interval="5m", 
                   start_date="2025-04-01", end_date="2025-04-08")

# Calculate momentum indicators
df['RSI'] = ta.rsi(df['close'], 14)

# MACD
macd_line, signal_line, histogram = ta.macd(df['close'])
df['MACD'] = macd_line
df['MACD_Signal'] = signal_line
df['MACD_Histogram'] = histogram

# Stochastic
stoch_k, stoch_d = ta.stochastic(df['high'], df['low'], df['close'])
df['Stoch_K'] = stoch_k
df['Stoch_D'] = stoch_d

# CCI
df['CCI'] = ta.cci(df['high'], df['low'], df['close'], 20)

# Williams %R
df['Williams_R'] = ta.williams_r(df['high'], df['low'], df['close'])

# Balance of Power
df['BOP'] = ta.bop(df['open'], df['high'], df['low'], df['close'])

# Elder Ray
bull_power, bear_power = ta.elderray(df['high'], df['low'], df['close'])
df['Bull_Power'] = bull_power
df['Bear_Power'] = bear_power

# Fisher Transform
fisher, fisher_trigger = ta.fisher(df['high'], df['low'])
df['Fisher'] = fisher
df['Fisher_Trigger'] = fisher_trigger

# Connors RSI
df['CRSI'] = ta.crsi(df['close'])

# Display results
momentum_cols = ['close', 'RSI', 'MACD', 'MACD_Signal', 'Stoch_K', 'Stoch_D', 
                'CCI', 'Williams_R', 'BOP', 'Bull_Power', 'Bear_Power', 
                'Fisher', 'CRSI']

print(df[momentum_cols].tail(10))

# Trading signals example
df['RSI_Oversold'] = df['RSI'] < 30
df['RSI_Overbought'] = df['RSI'] > 70
df['MACD_Bullish'] = df['MACD'] > df['MACD_Signal']
df['Stoch_Oversold'] = (df['Stoch_K'] < 20) & (df['Stoch_D'] < 20)

# Combine signals
df['Bullish_Signal'] = (df['RSI_Oversold']) & (df['MACD_Bullish']) & (df['Stoch_Oversold'])

print("\nBullish signals:")
print(df[df['Bullish_Signal']][['close', 'RSI', 'MACD', 'Stoch_K']].head())
```

### Signal Interpretation Guide

#### RSI

* **> 70**: Overbought (potential sell signal)
* **< 30**: Oversold (potential buy signal)
* **50**: Neutral momentum

#### MACD

* **MACD > Signal**: Bullish momentum
* **MACD < Signal**: Bearish momentum
* **Histogram > 0**: Increasing bullish momentum
* **Histogram < 0**: Increasing bearish momentum

#### Stochastic

* **%K > 80**: Overbought conditions
* **%K < 20**: Oversold conditions
* **%K crossing above %D**: Bullish signal
* **%K crossing below %D**: Bearish signal

#### CCI

* **> +100**: Strong uptrend
* **< -100**: Strong downtrend
* **-100 to +100**: Ranging market

#### Williams %R

* **> -20**: Overbought
* **< -80**: Oversold
* **Crossing -50**: Trend change signal

### Performance Tips

1. **Use appropriate periods**: Shorter periods for more sensitive signals, longer for smoother trends
2. **Combine indicators**: Use multiple momentum indicators to confirm signals
3. **Market context**: Consider overall market trend when interpreting momentum signals
4. **Divergences**: Look for divergences between price and momentum indicators


---

# Agent Instructions: Querying This Documentation

If you need additional information that is not directly available in this page, you can query the documentation dynamically by asking a question.

Perform an HTTP GET request on the current page URL with the `ask` query parameter:

```
GET https://docs.openalgo.in/trading-platform/python/indicators/momentum.md?ask=<question>
```

The question should be specific, self-contained, and written in natural language.
The response will contain a direct answer to the question and relevant excerpts and sources from the documentation.

Use this mechanism when the answer is not explicitly present in the current page, you need clarification or additional context, or you want to retrieve related documentation sections.
