# Hybrid

Hybrid indicators combine multiple analytical approaches to provide comprehensive market analysis. These indicators often merge trend, momentum, volatility, and volume components for enhanced signal quality.

### Import Statement

```python
from openalgo import api, ta

# Get data using OpenAlgo API
client = api(api_key='your_api_key_here', host='http://127.0.0.1:5000')
df = client.history(symbol="SBIN", exchange="NSE", interval="5m", 
                   start_date="2025-04-01", end_date="2025-04-08")
```

### Available Hybrid Indicators

***

### Average Directional Index (ADX)

ADX measures the strength of a trend regardless of direction, providing both directional indicators (+DI, -DI) and trend strength (ADX).

#### Usage

```python
di_plus, di_minus, adx = ta.adx(high, low, close, period=14)
```

#### Parameters

* **high** *(array-like)*: High prices
* **low** *(array-like)*: Low prices
* **close** *(array-like)*: Closing prices
* **period** *(int, default=14)*: Period for ADX calculation

#### Returns

* **tuple**: (+DI, -DI, ADX) arrays in the same format as input

#### Example

```python
# Calculate ADX system
di_plus, di_minus, adx = ta.adx(df['high'], df['low'], df['close'], period=14)

df['DI_Plus'] = di_plus
df['DI_Minus'] = di_minus  
df['ADX'] = adx

# Trend analysis
df['Trend_Strength'] = df['ADX'].apply(lambda x: 'Strong' if x > 25 else 'Weak' if x > 20 else 'No Trend')
df['Trend_Direction'] = df.apply(lambda row: 'Bullish' if row['DI_Plus'] > row['DI_Minus'] 
                                 else 'Bearish' if row['DI_Minus'] > row['DI_Plus'] else 'Neutral', axis=1)

print(df[['close', 'DI_Plus', 'DI_Minus', 'ADX', 'Trend_Strength', 'Trend_Direction']].tail())
```

***

### Aroon Indicator

Aroon indicators measure the time since the highest high and lowest low, indicating trend strength and potential reversals.

#### Usage

```python
aroon_up, aroon_down = ta.aroon(high, low, period=14)
```

#### Parameters

* **high** *(array-like)*: High prices
* **low** *(array-like)*: Low prices
* **period** *(int, default=14)*: Period for Aroon calculation

#### Returns

* **tuple**: (aroon\_up, aroon\_down) arrays in the same format as input

#### Example

```python
# Calculate Aroon indicators
aroon_up, aroon_down = ta.aroon(df['high'], df['low'], period=25)

df['Aroon_Up'] = aroon_up
df['Aroon_Down'] = aroon_down
df['Aroon_Oscillator'] = df['Aroon_Up'] - df['Aroon_Down']

# Signal interpretation
df['Aroon_Signal'] = df.apply(lambda row: 
    'Strong Uptrend' if row['Aroon_Up'] > 70 and row['Aroon_Down'] < 30
    else 'Strong Downtrend' if row['Aroon_Down'] > 70 and row['Aroon_Up'] < 30
    else 'Sideways' if abs(row['Aroon_Up'] - row['Aroon_Down']) < 20
    else 'Trending', axis=1)

print(df[['close', 'Aroon_Up', 'Aroon_Down', 'Aroon_Oscillator', 'Aroon_Signal']].tail())
```

***

### Pivot Points

Traditional pivot points calculate support and resistance levels based on previous period's high, low, and close.

#### Usage

```python
pivot, r1, s1, r2, s2, r3, s3 = ta.pivot_points(high, low, close)
```

#### Parameters

* **high** *(array-like)*: High prices
* **low** *(array-like)*: Low prices
* **close** *(array-like)*: Closing prices

#### Returns

* **tuple**: (pivot, r1, s1, r2, s2, r3, s3) arrays

#### Example

```python
# Calculate Pivot Points
pivot, r1, s1, r2, s2, r3, s3 = ta.pivot_points(df['high'], df['low'], df['close'])

df['Pivot'] = pivot
df['Resistance_1'] = r1
df['Support_1'] = s1
df['Resistance_2'] = r2
df['Support_2'] = s2
df['Resistance_3'] = r3
df['Support_3'] = s3

# Identify price position relative to pivot
df['Price_Position'] = df.apply(lambda row:
    'Above R2' if row['close'] > row['Resistance_2']
    else 'Above R1' if row['close'] > row['Resistance_1']
    else 'Above Pivot' if row['close'] > row['Pivot']
    else 'Below Pivot' if row['close'] < row['Support_1']
    else 'Below S1' if row['close'] < row['Support_2']
    else 'Below S2' if row['close'] < row['Support_2']
    else 'Near Pivot', axis=1)

print(df[['close', 'Pivot', 'Resistance_1', 'Support_1', 'Price_Position']].tail())
```

***

### Parabolic SAR

Parabolic SAR provides trailing stop levels and trend direction signals.

#### Usage

```python
sar_values, trend_direction = ta.psar(high, low, acceleration=0.02, maximum=0.2)
```

#### Parameters

* **high** *(array-like)*: High prices
* **low** *(array-like)*: Low prices
* **acceleration** *(float, default=0.02)*: Acceleration factor
* **maximum** *(float, default=0.2)*: Maximum acceleration factor

#### Returns

* **tuple**: (sar\_values, trend\_direction) arrays

#### Example

```python
# Calculate Parabolic SAR
sar_values, trend_direction = ta.psar(df['high'], df['low'])

df['SAR'] = sar_values
df['SAR_Trend'] = trend_direction

# Generate trading signals
df['SAR_Signal'] = df.apply(lambda row:
    'Buy' if row['close'] > row['SAR'] and row['SAR_Trend'] == -1  # Uptrend
    else 'Sell' if row['close'] < row['SAR'] and row['SAR_Trend'] == 1  # Downtrend
    else 'Hold', axis=1)

# Calculate distance from SAR (risk management)
df['SAR_Distance'] = abs(df['close'] - df['SAR'])
df['SAR_Distance_Pct'] = (df['SAR_Distance'] / df['close']) * 100

print(df[['close', 'SAR', 'SAR_Signal', 'SAR_Distance_Pct']].tail())
```

***

### Directional Movement Index (DMI)

DMI focuses on the directional indicators (+DI and -DI) without the ADX component.

#### Usage

```python
di_plus, di_minus = ta.dmi(high, low, close, period=14)
```

#### Parameters

* **high** *(array-like)*: High prices
* **low** *(array-like)*: Low prices
* **close** *(array-like)*: Closing prices
* **period** *(int, default=14)*: Period for DMI calculation

#### Returns

* **tuple**: (+DI, -DI) arrays in the same format as input

#### Example

```python
# Calculate DMI
di_plus, di_minus = ta.dmi(df['high'], df['low'], df['close'])

df['DI_Plus'] = di_plus
df['DI_Minus'] = di_minus
df['DI_Spread'] = df['DI_Plus'] - df['DI_Minus']

# Generate directional signals
df['DMI_Signal'] = df.apply(lambda row:
    'Strong Buy' if row['DI_Plus'] > row['DI_Minus'] and row['DI_Spread'] > 10
    else 'Buy' if row['DI_Plus'] > row['DI_Minus']
    else 'Strong Sell' if row['DI_Minus'] > row['DI_Plus'] and row['DI_Spread'] < -10
    else 'Sell' if row['DI_Minus'] > row['DI_Plus']
    else 'Neutral', axis=1)

print(df[['close', 'DI_Plus', 'DI_Minus', 'DI_Spread', 'DMI_Signal']].tail())
```

***

### Williams Fractals

Williams Fractals identify turning points (fractals) in price action using local highs and lows.

#### Usage

```python
fractal_up, fractal_down = ta.fractals(high, low, periods=2)
```

#### Parameters

* **high** *(array-like)*: High prices
* **low** *(array-like)*: Low prices
* **periods** *(int, default=2)*: Number of periods to check (minimum 2)

#### Returns

* **tuple**: (fractal\_up, fractal\_down) boolean arrays indicating fractal points

#### Example

```python
# Calculate Williams Fractals
fractal_up, fractal_down = ta.fractals(df['high'], df['low'], periods=2)

df['Fractal_Up'] = fractal_up
df['Fractal_Down'] = fractal_down

# Mark fractal levels
df['Fractal_High'] = df['high'].where(df['Fractal_Up'])
df['Fractal_Low'] = df['low'].where(df['Fractal_Down'])

# Count recent fractals for market structure analysis
window = 20
df['Recent_Fractal_Highs'] = df['Fractal_Up'].rolling(window).sum()
df['Recent_Fractal_Lows'] = df['Fractal_Down'].rolling(window).sum()

df['Market_Structure'] = df.apply(lambda row:
    'Bullish Structure' if row['Recent_Fractal_Lows'] > row['Recent_Fractal_Highs']
    else 'Bearish Structure' if row['Recent_Fractal_Highs'] > row['Recent_Fractal_Lows']
    else 'Balanced', axis=1)

print(df[['close', 'Fractal_High', 'Fractal_Low', 'Market_Structure']].dropna().tail())
```

***

### Random Walk Index (RWI)

RWI measures how much a security's price movement differs from a random walk, helping identify trending vs. random price movements.

#### Usage

```python
rwi_high, rwi_low = ta.rwi(high, low, close, period=14)
```

#### Parameters

* **high** *(array-like)*: High prices
* **low** *(array-like)*: Low prices
* **close** *(array-like)*: Closing prices
* **period** *(int, default=14)*: Period for RWI calculation

#### Returns

* **tuple**: (rwi\_high, rwi\_low) arrays in the same format as input

#### Example

```python
# Calculate Random Walk Index
rwi_high, rwi_low = ta.rwi(df['high'], df['low'], df['close'], period=14)

df['RWI_High'] = rwi_high
df['RWI_Low'] = rwi_low
df['RWI_Max'] = df[['RWI_High', 'RWI_Low']].max(axis=1)

# Interpret RWI signals
df['RWI_Signal'] = df.apply(lambda row:
    'Strong Uptrend' if row['RWI_High'] > 1.0 and row['RWI_High'] > row['RWI_Low']
    else 'Strong Downtrend' if row['RWI_Low'] > 1.0 and row['RWI_Low'] > row['RWI_High']
    else 'Weak Uptrend' if row['RWI_High'] > row['RWI_Low'] and row['RWI_High'] > 0.6
    else 'Weak Downtrend' if row['RWI_Low'] > row['RWI_High'] and row['RWI_Low'] > 0.6
    else 'Random Walk', axis=1)

# Calculate trend strength
df['Trend_Strength_RWI'] = df['RWI_Max'].apply(lambda x:
    'Very Strong' if x > 1.5
    else 'Strong' if x > 1.0
    else 'Moderate' if x > 0.6
    else 'Weak')

print(df[['close', 'RWI_High', 'RWI_Low', 'RWI_Signal', 'Trend_Strength_RWI']].tail())
```

***

### Complete Example: Comprehensive Trend Analysis

```python
import pandas as pd
from openalgo import api, ta

# Get market data
client = api(api_key='your_api_key_here', host='http://127.0.0.1:5000')
df = client.history(symbol="SBIN", exchange="NSE", interval="5m", 
                   start_date="2025-04-01", end_date="2025-04-08")

# Calculate multiple hybrid indicators
print("Calculating hybrid indicators...")

# ADX System
di_plus, di_minus, adx = ta.adx(df['high'], df['low'], df['close'])
df['DI_Plus'] = di_plus
df['DI_Minus'] = di_minus
df['ADX'] = adx

# Aroon System
aroon_up, aroon_down = ta.aroon(df['high'], df['low'])
df['Aroon_Up'] = aroon_up
df['Aroon_Down'] = aroon_down
df['Aroon_Osc'] = df['Aroon_Up'] - df['Aroon_Down']

# Parabolic SAR
sar_values, sar_trend = ta.psar(df['high'], df['low'])
df['SAR'] = sar_values
df['SAR_Trend'] = sar_trend

# Random Walk Index
rwi_high, rwi_low = ta.rwi(df['high'], df['low'], df['close'])
df['RWI_High'] = rwi_high
df['RWI_Low'] = rwi_low

# Williams Fractals
fractal_up, fractal_down = ta.fractals(df['high'], df['low'])
df['Fractal_Up'] = fractal_up
df['Fractal_Down'] = fractal_down

# Create comprehensive trend signal
def comprehensive_trend_signal(row):
    signals = []
    
    # ADX Signal
    if row['ADX'] > 25:
        if row['DI_Plus'] > row['DI_Minus']:
            signals.append('ADX_Bull')
        else:
            signals.append('ADX_Bear')
    
    # Aroon Signal
    if row['Aroon_Up'] > 70:
        signals.append('Aroon_Bull')
    elif row['Aroon_Down'] > 70:
        signals.append('Aroon_Bear')
    
    # SAR Signal
    if row['close'] > row['SAR']:
        signals.append('SAR_Bull')
    else:
        signals.append('SAR_Bear')
    
    # RWI Signal
    if row['RWI_High'] > 1.0 and row['RWI_High'] > row['RWI_Low']:
        signals.append('RWI_Bull')
    elif row['RWI_Low'] > 1.0 and row['RWI_Low'] > row['RWI_High']:
        signals.append('RWI_Bear')
    
    # Count bullish vs bearish signals
    bull_count = len([s for s in signals if 'Bull' in s])
    bear_count = len([s for s in signals if 'Bear' in s])
    
    if bull_count > bear_count and bull_count >= 2:
        return f'Bullish ({bull_count}/{len(signals)})'
    elif bear_count > bull_count and bear_count >= 2:
        return f'Bearish ({bear_count}/{len(signals)})'
    else:
        return f'Neutral ({bull_count}B/{bear_count}B)'

df['Comprehensive_Signal'] = df.apply(comprehensive_trend_signal, axis=1)

# Calculate signal strength
df['Signal_Strength'] = df.apply(lambda row:
    row['ADX'] * 0.3 + abs(row['Aroon_Osc']) * 0.3 + 
    max(row['RWI_High'], row['RWI_Low']) * 40, axis=1)

# Display results
result_columns = ['close', 'ADX', 'Aroon_Osc', 'SAR', 'RWI_High', 'RWI_Low', 
                 'Comprehensive_Signal', 'Signal_Strength']

print("\nComprehensive Trend Analysis:")
print(df[result_columns].tail(10))

# Summary statistics
print(f"\nSignal Distribution:")
print(df['Comprehensive_Signal'].value_counts())

print(f"\nAverage Signal Strength: {df['Signal_Strength'].mean():.2f}")
print(f"Current Signal Strength: {df['Signal_Strength'].iloc[-1]:.2f}")
```

### Advanced Usage: Multi-Timeframe Analysis

```python
# Function to get multiple timeframe data
def get_multi_timeframe_data(symbol, exchange, start_date, end_date):
    timeframes = ['1m', '5m', '15m', '1h']
    data = {}
    
    for tf in timeframes:
        try:
            df = client.history(symbol=symbol, exchange=exchange, interval=tf,
                              start_date=start_date, end_date=end_date)
            data[tf] = df
        except Exception as e:
            print(f"Error fetching {tf} data: {e}")
    
    return data

# Multi-timeframe trend analysis
def analyze_multi_timeframe_trend(data_dict):
    results = {}
    
    for timeframe, df in data_dict.items():
        # Calculate key hybrid indicators
        di_plus, di_minus, adx = ta.adx(df['high'], df['low'], df['close'])
        aroon_up, aroon_down = ta.aroon(df['high'], df['low'])
        
        latest_adx = adx.iloc[-1] if not pd.isna(adx.iloc[-1]) else 0
        latest_di_plus = di_plus.iloc[-1] if not pd.isna(di_plus.iloc[-1]) else 0
        latest_di_minus = di_minus.iloc[-1] if not pd.isna(di_minus.iloc[-1]) else 0
        latest_aroon_up = aroon_up.iloc[-1] if not pd.isna(aroon_up.iloc[-1]) else 0
        latest_aroon_down = aroon_down.iloc[-1] if not pd.isna(aroon_down.iloc[-1]) else 0
        
        # Determine trend
        if latest_adx > 25:
            if latest_di_plus > latest_di_minus:
                trend = 'Bullish'
            else:
                trend = 'Bearish'
        else:
            trend = 'Sideways'
        
        results[timeframe] = {
            'Trend': trend,
            'ADX': latest_adx,
            'Aroon_Strength': abs(latest_aroon_up - latest_aroon_down)
        }
    
    return results

# Example usage
# mtf_data = get_multi_timeframe_data("SBIN", "NSE", "2025-04-01", "2025-04-08")
# mtf_analysis = analyze_multi_timeframe_trend(mtf_data)
# print("Multi-Timeframe Analysis:", mtf_analysis)
```

### Performance Tips

1. **Vectorized Operations**: Use pandas operations for better performance with large datasets
2. **Memory Optimization**: Calculate only needed indicators to reduce memory usage
3. **Caching**: Store intermediate calculations for reuse across multiple indicators
4. **Batch Processing**: Process multiple symbols together when possible

### Common Use Cases

1. **Trend Confirmation**: Use ADX with Aroon for trend strength validation
2. **Entry Timing**: Combine SAR with DMI for precise entry points
3. **Support/Resistance**: Use Pivot Points with Fractals for key levels
4. **Risk Management**: Use RWI to distinguish trending from random movements
5. **Multi-Timeframe**: Align signals across different timeframes for higher probability trades


---

# Agent Instructions: Querying This Documentation

If you need additional information that is not directly available in this page, you can query the documentation dynamically by asking a question.

Perform an HTTP GET request on the current page URL with the `ask` query parameter:

```
GET https://docs.openalgo.in/trading-platform/python/indicators/hybrid.md?ask=<question>
```

The question should be specific, self-contained, and written in natural language.
The response will contain a direct answer to the question and relevant excerpts and sources from the documentation.

Use this mechanism when the answer is not explicitly present in the current page, you need clarification or additional context, or you want to retrieve related documentation sections.
