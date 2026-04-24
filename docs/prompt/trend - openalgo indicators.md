# Trend

Trend indicators help identify the direction and strength of market trends. All examples use real market data fetched via OpenAlgo API.

### Data Setup

```python
from openalgo import api, ta
import pandas as pd

# Initialize API client
client = api(api_key='your_api_key_here', host='http://127.0.0.1:5000')

# Fetch historical data
df = client.history(symbol="SBIN", 
                   exchange="NSE", 
                   interval="5m", 
                   start_date="2025-04-01", 
                   end_date="2025-04-08")

print(df.head())
#                            close    high     low    open  volume
# timestamp                                                        
# 2025-04-01 09:15:00+05:30  772.50  774.00  763.20  766.50  318625
# 2025-04-01 09:20:00+05:30  773.20  774.95  772.10  772.45  197189
```

***

### Simple Moving Average (SMA)

**Description**: The most basic trend indicator, calculated by averaging closing prices over a specified period.

#### Parameters

* **data** *(array-like)*: Price data (typically closing prices)
* **period** *(int)*: Number of periods for the moving average

#### Returns

* **pandas.Series**: SMA values with original index preserved

#### Usage Example

```python
# Calculate 20-period SMA
df['SMA_20'] = ta.sma(df['close'], 20)

# Calculate multiple SMAs
df['SMA_10'] = ta.sma(df['close'], 10)
df['SMA_50'] = ta.sma(df['close'], 50)

print(df[['close', 'SMA_10', 'SMA_20', 'SMA_50']].tail())
#                            close   SMA_10   SMA_20   SMA_50
# timestamp                                                  
# 2025-04-08 14:00:00+05:30  768.25  770.12  771.45  773.28
# 2025-04-08 14:05:00+05:30  769.10  769.98  771.33  773.22
```

***

### Exponential Moving Average (EMA)

**Description**: Gives more weight to recent prices, making it more responsive to new information than SMA.

#### Parameters

* **data** *(array-like)*: Price data (typically closing prices)
* **period** *(int)*: Number of periods for the moving average

#### Returns

* **pandas.Series**: EMA values with original index preserved

#### Usage Example

```python
# Calculate 20-period EMA
df['EMA_20'] = ta.ema(df['close'], 20)

# Compare with SMA
df['SMA_20'] = ta.sma(df['close'], 20)

# Plot comparison
import matplotlib.pyplot as plt
plt.figure(figsize=(12, 6))
plt.plot(df.index, df['close'], label='Close Price', alpha=0.7)
plt.plot(df.index, df['SMA_20'], label='SMA 20', alpha=0.8)
plt.plot(df.index, df['EMA_20'], label='EMA 20', alpha=0.8)
plt.legend()
plt.title('SBIN: Close Price vs Moving Averages')
plt.show()
```

***

### Weighted Moving Average (WMA)

**Description**: Assigns greater weight to recent data points using a linear weighting scheme.

#### Parameters

* **data** *(array-like)*: Price data (typically closing prices)
* **period** *(int)*: Number of periods for the moving average

#### Returns

* **numpy.ndarray**: WMA values

#### Usage Example

```python
# Calculate 20-period WMA
df['WMA_20'] = ta.wma(df['close'], 20)

# Compare responsiveness of different MAs
df['MA_Comparison'] = df['close'] - df['SMA_20']
df['EMA_Comparison'] = df['close'] - df['EMA_20'] 
df['WMA_Comparison'] = df['close'] - df['WMA_20']

print(df[['MA_Comparison', 'EMA_Comparison', 'WMA_Comparison']].tail())
```

***

### Hull Moving Average (HMA)

**Description**: Attempts to minimize lag while improving smoothing using weighted moving averages.

#### Parameters

* **data** *(array-like)*: Price data (typically closing prices)
* **period** *(int)*: Number of periods for the moving average

#### Returns

* **pandas.Series**: HMA values with original index preserved

#### Usage Example

```python
# Calculate 16-period HMA (common period for HMA)
df['HMA_16'] = ta.hma(df['close'], 16)

# Compare lag between different MAs
df['Price_Change'] = df['close'].pct_change()
df['HMA_Change'] = df['HMA_16'].pct_change()
df['EMA_Change'] = df['EMA_20'].pct_change()

# Calculate correlation to measure responsiveness
correlation_hma = df['Price_Change'].corr(df['HMA_Change'])
correlation_ema = df['Price_Change'].corr(df['EMA_Change'])
print(f"HMA Correlation: {correlation_hma:.4f}")
print(f"EMA Correlation: {correlation_ema:.4f}")
```

***

### Volume Weighted Moving Average (VWMA)

**Description**: Gives more weight to periods with higher volume, making it more responsive to volume-driven price movements.

#### Parameters

* **data** *(array-like)*: Price data (typically closing prices)
* **volume** *(array-like)*: Volume data
* **period** *(int)*: Number of periods for the moving average

#### Returns

* **pandas.Series**: VWMA values with original index preserved

#### Usage Example

```python
# Calculate 20-period VWMA
df['VWMA_20'] = ta.vwma(df['close'], df['volume'], 20)

# Compare VWMA with regular SMA during high/low volume periods
df['Volume_MA'] = ta.sma(df['volume'], 20)
df['High_Volume'] = df['volume'] > df['Volume_MA']

# Analyze performance during high volume periods
high_vol_periods = df[df['High_Volume'] == True]
print("VWMA vs SMA during high volume periods:")
print(high_vol_periods[['close', 'SMA_20', 'VWMA_20', 'volume']].tail())
```

***

### Kaufman's Adaptive Moving Average (KAMA)

**Description**: Adjusts its smoothing based on market volatility, becoming more responsive in trending markets and smoother in sideways markets.

#### Parameters

* **data** *(array-like)*: Price data (typically closing prices)
* **length** *(int, default=14)*: Period for efficiency ratio calculation
* **fast\_length** *(int, default=2)*: Fast EMA length
* **slow\_length** *(int, default=30)*: Slow EMA length

#### Returns

* **pandas.Series**: KAMA values with original index preserved

#### Usage Example

```python
# Calculate KAMA with default parameters
df['KAMA_14'] = ta.kama(df['close'])

# Calculate market efficiency ratio manually for analysis
def calculate_efficiency_ratio(prices, period):
    direction = abs(prices.iloc[-1] - prices.iloc[-period-1])
    volatility = abs(prices.diff()).rolling(period).sum().iloc[-1]
    return direction / volatility if volatility > 0 else 0

# Analyze KAMA adaptation
df['ER'] = df['close'].rolling(14).apply(lambda x: calculate_efficiency_ratio(x, 14))
df['KAMA_vs_Close'] = abs(df['KAMA_14'] - df['close'])

print("KAMA Efficiency and Adaptation:")
print(df[['close', 'KAMA_14', 'ER', 'KAMA_vs_Close']].tail(10))
```

***

### Supertrend

**Description**: A trend-following indicator that uses ATR to calculate dynamic support and resistance levels.

#### Parameters

* **high** *(array-like)*: High prices
* **low** *(array-like)*: Low prices
* **close** *(array-like)*: Closing prices
* **period** *(int, default=10)*: ATR period
* **multiplier** *(float, default=3.0)*: ATR multiplier

#### Returns

* **tuple**: (supertrend\_values, direction\_values) as pandas.Series
  * **direction**: -1 for uptrend (green), 1 for downtrend (red)

#### Usage Example

```python
# Calculate Supertrend with default parameters
df['Supertrend'], df['ST_Direction'] = ta.supertrend(df['high'], df['low'], df['close'])

# Calculate custom Supertrend for shorter timeframes
df['ST_Fast'], df['ST_Fast_Dir'] = ta.supertrend(df['high'], df['low'], df['close'], 
                                                period=7, multiplier=2.0)

# Identify trend changes
df['Trend_Change'] = df['ST_Direction'].diff() != 0

# Analyze trend statistics
uptrend_periods = len(df[df['ST_Direction'] == -1])
downtrend_periods = len(df[df['ST_Direction'] == 1])
trend_changes = df['Trend_Change'].sum()

print(f"Uptrend periods: {uptrend_periods}")
print(f"Downtrend periods: {downtrend_periods}")
print(f"Trend changes: {trend_changes}")

# Show recent Supertrend signals
print("\nRecent Supertrend Data:")
print(df[['close', 'Supertrend', 'ST_Direction']].tail())
```

***

### Ichimoku Cloud

**Description**: A comprehensive indicator that defines support and resistance, identifies trend direction, and provides trading signals.

#### Parameters

* **high** *(array-like)*: High prices
* **low** *(array-like)*: Low prices
* **close** *(array-like)*: Closing prices
* **conversion\_periods** *(int, default=9)*: Conversion Line Length
* **base\_periods** *(int, default=26)*: Base Line Length
* **lagging\_span2\_periods** *(int, default=52)*: Leading Span B Length
* **displacement** *(int, default=26)*: Lagging Span displacement

#### Returns

* **tuple**: (conversion\_line, base\_line, leading\_span\_a, leading\_span\_b, lagging\_span) as pandas.Series

#### Usage Example

```python
# Calculate Ichimoku Cloud components
(df['Ichimoku_Conversion'], 
 df['Ichimoku_Base'], 
 df['Ichimoku_SpanA'], 
 df['Ichimoku_SpanB'], 
 df['Ichimoku_Lagging']) = ta.ichimoku(df['high'], df['low'], df['close'])

# Analyze cloud signals
df['Cloud_Top'] = df[['Ichimoku_SpanA', 'Ichimoku_SpanB']].max(axis=1)
df['Cloud_Bottom'] = df[['Ichimoku_SpanA', 'Ichimoku_SpanB']].min(axis=1)
df['Above_Cloud'] = df['close'] > df['Cloud_Top']
df['Below_Cloud'] = df['close'] < df['Cloud_Bottom']
df['In_Cloud'] = ~(df['Above_Cloud'] | df['Below_Cloud'])

# TK Cross signals
df['TK_Bullish'] = (df['Ichimoku_Conversion'] > df['Ichimoku_Base']) & \
                   (df['Ichimoku_Conversion'].shift(1) <= df['Ichimoku_Base'].shift(1))
df['TK_Bearish'] = (df['Ichimoku_Conversion'] < df['Ichimoku_Base']) & \
                   (df['Ichimoku_Conversion'].shift(1) >= df['Ichimoku_Base'].shift(1))

print("Ichimoku Analysis:")
print(f"Periods above cloud: {df['Above_Cloud'].sum()}")
print(f"Periods below cloud: {df['Below_Cloud'].sum()}")
print(f"Periods in cloud: {df['In_Cloud'].sum()}")
print(f"TK Bullish signals: {df['TK_Bullish'].sum()}")
print(f"TK Bearish signals: {df['TK_Bearish'].sum()}")
```

***

### Arnaud Legoux Moving Average (ALMA)

**Description**: Combines the features of SMA and EMA with a configurable phase and smoothing factor.

#### Parameters

* **data** *(array-like)*: Price data (typically closing prices)
* **period** *(int, default=21)*: Number of periods for the moving average
* **offset** *(float, default=0.85)*: Phase offset (0 to 1)
* **sigma** *(float, default=6.0)*: Smoothing factor

#### Returns

* **pandas.Series**: ALMA values with original index preserved

#### Usage Example

```python
# Calculate ALMA with different configurations
df['ALMA_Default'] = ta.alma(df['close'])  # Default: period=21, offset=0.85, sigma=6.0
df['ALMA_Fast'] = ta.alma(df['close'], period=14, offset=0.9, sigma=4.0)
df['ALMA_Smooth'] = ta.alma(df['close'], period=21, offset=0.5, sigma=8.0)

# Compare responsiveness
df['ALMA_vs_EMA'] = df['ALMA_Default'] - ta.ema(df['close'], 21)
print("ALMA vs EMA difference (last 10 periods):")
print(df['ALMA_vs_EMA'].tail(10))
```

***

### Zero Lag Exponential Moving Average (ZLEMA)

**Description**: Attempts to eliminate lag by using price momentum in its calculation.

#### Parameters

* **data** *(array-like)*: Price data (typically closing prices)
* **period** *(int)*: Number of periods for the moving average

#### Returns

* **pandas.Series**: ZLEMA values with original index preserved

#### Usage Example

```python
# Calculate ZLEMA and compare with regular EMA
df['ZLEMA_20'] = ta.zlema(df['close'], 20)
df['EMA_20'] = ta.ema(df['close'], 20)

# Measure responsiveness to price changes
df['Price_Change'] = df['close'].diff()
df['ZLEMA_Change'] = df['ZLEMA_20'].diff()
df['EMA_Change'] = df['EMA_20'].diff()

# Calculate lead/lag relationship
correlation_zlema = df['Price_Change'].corr(df['ZLEMA_Change'])
correlation_ema = df['Price_Change'].corr(df['EMA_Change'])

print(f"ZLEMA responsiveness: {correlation_zlema:.4f}")
print(f"EMA responsiveness: {correlation_ema:.4f}")
```

***

### Multiple Exponential Moving Average (DEMA & TEMA)

**Description**: DEMA and TEMA reduce lag by applying exponential smoothing multiple times.

#### Parameters

* **data** *(array-like)*: Price data (typically closing prices)
* **period** *(int)*: Number of periods for the moving average

#### Returns

* **pandas.Series**: DEMA/TEMA values with original index preserved

#### Usage Example

```python
# Calculate DEMA and TEMA
df['DEMA_20'] = ta.dema(df['close'], 20)
df['TEMA_20'] = ta.tema(df['close'], 20)
df['EMA_20'] = ta.ema(df['close'], 20)

# Compare lag characteristics
price_peaks = df['close'].rolling(5).max() == df['close']
df['Peak_Signals'] = price_peaks

# Analyze how quickly each MA responds to peaks
peak_periods = df[df['Peak_Signals']]
print("Response at price peaks:")
print(peak_periods[['close', 'EMA_20', 'DEMA_20', 'TEMA_20']].tail())
```

***

### Complete Trading Analysis Example

```python
from openalgo import api, ta
import pandas as pd
import matplotlib.pyplot as plt

# Fetch data
client = api(api_key='your_api_key_here', host='http://127.0.0.1:5000')
df = client.history(symbol="SBIN", exchange="NSE", interval="5m", 
                   start_date="2025-04-01", end_date="2025-04-08")

# Calculate multiple trend indicators
df['SMA_20'] = ta.sma(df['close'], 20)
df['EMA_20'] = ta.ema(df['close'], 20)
df['KAMA_14'] = ta.kama(df['close'])
df['Supertrend'], df['ST_Direction'] = ta.supertrend(df['high'], df['low'], df['close'])

# Calculate Ichimoku components
(df['Conversion'], df['Base'], df['SpanA'], 
 df['SpanB'], df['Lagging']) = ta.ichimoku(df['high'], df['low'], df['close'])

# Generate trading signals
df['MA_Bullish'] = (df['close'] > df['SMA_20']) & (df['EMA_20'] > df['SMA_20'])
df['ST_Bullish'] = df['ST_Direction'] == -1
df['Ichimoku_Bullish'] = (df['close'] > df[['SpanA', 'SpanB']].max(axis=1)) & \
                         (df['Conversion'] > df['Base'])

# Combined signal
df['Combined_Signal'] = (df['MA_Bullish'] & df['ST_Bullish'] & df['Ichimoku_Bullish']).astype(int)

# Performance analysis
signal_changes = df['Combined_Signal'].diff()
buy_signals = signal_changes == 1
sell_signals = signal_changes == -1

print(f"Buy signals: {buy_signals.sum()}")
print(f"Sell signals: {sell_signals.sum()}")

# Show recent analysis
print("\nRecent Trading Analysis:")
columns_to_show = ['close', 'SMA_20', 'EMA_20', 'Supertrend', 'ST_Direction', 'Combined_Signal']
print(df[columns_to_show].tail(10))

# Plot results
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(15, 10), sharex=True)

# Price and moving averages
ax1.plot(df.index, df['close'], label='Close', linewidth=1)
ax1.plot(df.index, df['SMA_20'], label='SMA 20', alpha=0.7)
ax1.plot(df.index, df['EMA_20'], label='EMA 20', alpha=0.7)
ax1.plot(df.index, df['Supertrend'], label='Supertrend', alpha=0.8)
ax1.legend()
ax1.set_title('SBIN Price and Trend Indicators')
ax1.grid(True, alpha=0.3)

# Signals
ax2.plot(df.index, df['Combined_Signal'], label='Combined Signal', linewidth=2)
ax2.fill_between(df.index, 0, df['Combined_Signal'], alpha=0.3)
ax2.set_ylabel('Signal')
ax2.set_xlabel('Time')
ax2.set_title('Combined Trading Signals')
ax2.grid(True, alpha=0.3)
ax2.legend()

plt.tight_layout()
plt.show()
```

This documentation demonstrates how to use OpenAlgo trend indicators with real market data fetched via the OpenAlgo API, maintaining pandas DataFrame structure throughout the analysis process.


---

# Agent Instructions: Querying This Documentation

If you need additional information that is not directly available in this page, you can query the documentation dynamically by asking a question.

Perform an HTTP GET request on the current page URL with the `ask` query parameter:

```
GET https://docs.openalgo.in/trading-platform/python/indicators/trend.md?ask=<question>
```

The question should be specific, self-contained, and written in natural language.
The response will contain a direct answer to the question and relevant excerpts and sources from the documentation.

Use this mechanism when the answer is not explicitly present in the current page, you need clarification or additional context, or you want to retrieve related documentation sections.
