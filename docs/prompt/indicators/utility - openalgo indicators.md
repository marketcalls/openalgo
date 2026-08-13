# Utility

## OpenAlgo Utility Indicators Documentation

Utility indicators provide essential market analysis functions for signal detection, condition checking, and mathematical operations. These functions are fundamental building blocks for creating trading strategies and market analysis systems.

### Import Statement

```python
from openalgo import ta, api
```

### Sample Data Setup

```python
# Initialize API client
client = api(api_key='your_api_key_here', host='http://127.0.0.1:5000')

# Fetch historical data
df = client.history(symbol="SBIN", 
                   exchange="NSE", 
                   interval="5m", 
                   start_date="2025-04-01", 
                   end_date="2025-04-08")

# Extract price series
close = df['close']
high = df['high']
low = df['low']
open_prices = df['open']
volume = df['volume']
```

***

### Signal Detection Utilities

#### Crossover

Detects when one series crosses above another series. Essential for identifying bullish signal points.

**Usage**

```python
crossover_signals = ta.crossover(series1, series2)
```

**Parameters**

* **series1** *(array-like)*: First series (typically fast indicator)
* **series2** *(array-like)*: Second series (typically slow indicator)

**Returns**

* **array**: Boolean array indicating crossover points (True where crossover occurs)

**Example**

```python
# Calculate moving averages
sma_10 = ta.sma(close, 10)
sma_20 = ta.sma(close, 20)

# Detect when SMA(10) crosses above SMA(20)
bullish_signals = ta.crossover(sma_10, sma_20)

# Find crossover points
crossover_points = df[bullish_signals]
print("Bullish crossover signals:")
print(crossover_points[['close']].head())
```

***

#### Crossunder

Detects when one series crosses below another series. Used for identifying bearish signal points.

**Usage**

```python
crossunder_signals = ta.crossunder(series1, series2)
```

**Parameters**

* **series1** *(array-like)*: First series (typically fast indicator)
* **series2** *(array-like)*: Second series (typically slow indicator)

**Returns**

* **array**: Boolean array indicating crossunder points (True where crossunder occurs)

**Example**

```python
# Detect when SMA(10) crosses below SMA(20)
bearish_signals = ta.crossunder(sma_10, sma_20)

# Find crossunder points
crossunder_points = df[bearish_signals]
print("Bearish crossunder signals:")
print(crossunder_points[['close']].head())
```

***

#### Cross

Detects when one series crosses another in either direction (combines crossover and crossunder).

**Usage**

```python
cross_signals = ta.cross(series1, series2)
```

**Parameters**

* **series1** *(array-like)*: First series
* **series2** *(array-like)*: Second series

**Returns**

* **array**: Boolean array indicating any cross points (both over and under)

**Example**

```python
# Detect any crossing between price and moving average
price_ma_cross = ta.cross(close, sma_20)

# Find all crossing points
all_crosses = df[price_ma_cross]
print("All price/MA crossing points:")
print(all_crosses[['close']].head())
```

***

### Range and Extremes

#### Highest

Finds the highest value over a rolling window.

**Usage**

```python
highest_values = ta.highest(data, period)
```

**Parameters**

* **data** *(array-like)*: Input data series
* **period** *(int)*: Window size for finding highest value

**Returns**

* **array**: Array of highest values over the specified period

**Example**

```python
# Find highest high over last 20 periods
highest_20 = ta.highest(high, 20)

# Create resistance levels
df['Resistance_20'] = highest_20
print("Recent resistance levels:")
print(df[['high', 'Resistance_20']].tail())
```

***

#### Lowest

Finds the lowest value over a rolling window.

**Usage**

```python
lowest_values = ta.lowest(data, period)
```

**Parameters**

* **data** *(array-like)*: Input data series
* **period** *(int)*: Window size for finding lowest value

**Returns**

* **array**: Array of lowest values over the specified period

**Example**

```python
# Find lowest low over last 20 periods
lowest_20 = ta.lowest(low, 20)

# Create support levels
df['Support_20'] = lowest_20
print("Recent support levels:")
print(df[['low', 'Support_20']].tail())
```

***

### Change and Rate Calculations

#### Change

Calculates the change in value over a specified number of periods.

**Usage**

```python
change_values = ta.change(data, length=1)
```

**Parameters**

* **data** *(array-like)*: Input data series
* **length** *(int, default=1)*: Number of periods to look back

**Returns**

* **array**: Array of change values

**Example**

```python
# Calculate 1-period change (price difference)
price_change_1 = ta.change(close, 1)

# Calculate 5-period change
price_change_5 = ta.change(close, 5)

# Add to dataframe
df['Change_1'] = price_change_1
df['Change_5'] = price_change_5
print("Price changes:")
print(df[['close', 'Change_1', 'Change_5']].tail())
```

***

#### Rate of Change (ROC)

Calculates the rate of change as a percentage.

**Usage**

```python
roc_values = ta.roc(data, length)
```

**Parameters**

* **data** *(array-like)*: Input data series
* **length** *(int)*: Number of periods to look back

**Returns**

* **array**: Array of ROC values as percentages

**Example**

```python
# Calculate 10-period rate of change
roc_10 = ta.roc(close, 10)

# Calculate 20-period rate of change
roc_20 = ta.roc(close, 20)

df['ROC_10'] = roc_10
df['ROC_20'] = roc_20
print("Rate of change analysis:")
print(df[['close', 'ROC_10', 'ROC_20']].tail())
```

***

### Statistical Utilities

#### Standard Deviation

Calculates rolling standard deviation for volatility measurement.

**Usage**

```python
stdev_values = ta.stdev(data, period)
```

**Parameters**

* **data** *(array-like)*: Input data series
* **period** *(int)*: Window size for standard deviation calculation

**Returns**

* **array**: Array of standard deviation values

**Example**

```python
# Calculate 20-period standard deviation
volatility_20 = ta.stdev(close, 20)

# Calculate relative volatility
relative_volatility = volatility_20 / close * 100

df['Volatility_20'] = volatility_20
df['Rel_Volatility'] = relative_volatility
print("Volatility analysis:")
print(df[['close', 'Volatility_20', 'Rel_Volatility']].tail())
```

***

### Trend Direction Utilities

#### Rising

Checks if data is rising (current value > value n periods ago).

**Usage**

```python
rising_condition = ta.rising(data, length)
```

**Parameters**

* **data** *(array-like)*: Input data series
* **length** *(int)*: Number of periods to look back

**Returns**

* **array**: Boolean array indicating rising periods

**Example**

```python
# Check if price is rising over 5 periods
price_rising_5 = ta.rising(close, 5)

# Check if volume is rising over 3 periods
volume_rising_3 = ta.rising(volume, 3)

# Combine conditions for strong bullish signal
strong_bullish = price_rising_5 & volume_rising_3

df['Price_Rising_5'] = price_rising_5
df['Volume_Rising_3'] = volume_rising_3
df['Strong_Bullish'] = strong_bullish

print("Rising trend analysis:")
print(df[['close', 'volume', 'Price_Rising_5', 'Volume_Rising_3', 'Strong_Bullish']].tail())
```

***

#### Falling

Checks if data is falling (current value < value n periods ago).

**Usage**

```python
falling_condition = ta.falling(data, length)
```

**Parameters**

* **data** *(array-like)*: Input data series
* **length** *(int)*: Number of periods to look back

**Returns**

* **array**: Boolean array indicating falling periods

**Example**

```python
# Check if price is falling over 5 periods
price_falling_5 = ta.falling(close, 5)

# Check if price is falling but volume is rising (potential reversal)
potential_reversal = price_falling_5 & volume_rising_3

df['Price_Falling_5'] = price_falling_5
df['Potential_Reversal'] = potential_reversal

print("Falling trend analysis:")
print(df[['close', 'Price_Falling_5', 'Potential_Reversal']].tail())
```

***

### Advanced Signal Processing

#### Excess Removal (ExRem)

Eliminates excessive signals by ensuring alternating signal types.

**Usage**

```python
filtered_signals = ta.exrem(primary_signals, secondary_signals)
```

**Parameters**

* **primary\_signals** *(array-like)*: Primary signal array (boolean-like)
* **secondary\_signals** *(array-like)*: Secondary signal array (boolean-like)

**Returns**

* **array**: Boolean array with excess signals removed

**Example**

```python
# Generate buy and sell signals
buy_signals = ta.crossover(sma_10, sma_20)
sell_signals = ta.crossunder(sma_10, sma_20)

# Remove excessive buy signals (only allow buy after sell)
filtered_buys = ta.exrem(buy_signals, sell_signals)

# Remove excessive sell signals (only allow sell after buy)
filtered_sells = ta.exrem(sell_signals, buy_signals)

df['Raw_Buy'] = buy_signals
df['Raw_Sell'] = sell_signals
df['Filtered_Buy'] = filtered_buys
df['Filtered_Sell'] = filtered_sells

print("Signal filtering comparison:")
print(df[['close', 'Raw_Buy', 'Raw_Sell', 'Filtered_Buy', 'Filtered_Sell']].tail(20))
```

***

#### Flip

Creates a toggle state based on two signals.

**Usage**

```python
state_array = ta.flip(primary_signals, secondary_signals)
```

**Parameters**

* **primary\_signals** *(array-like)*: Primary signal array (boolean-like)
* **secondary\_signals** *(array-like)*: Secondary signal array (boolean-like)

**Returns**

* **array**: Boolean array representing flip state

**Example**

```python
# Create a position state indicator
position_state = ta.flip(filtered_buys, filtered_sells)

# Calculate position returns
df['Position_State'] = position_state
df['Daily_Return'] = close.pct_change()
df['Strategy_Return'] = df['Daily_Return'] * df['Position_State'].shift(1)

print("Position state analysis:")
print(df[['close', 'Position_State', 'Daily_Return', 'Strategy_Return']].tail())
```

***

#### Value When

Returns the value of an array when a condition was true for the nth most recent time.

**Usage**

```python
conditional_values = ta.valuewhen(condition_array, value_array, n=1)
```

**Parameters**

* **condition\_array** *(array-like)*: Expression array (boolean-like)
* **value\_array** *(array-like)*: Value array to sample from
* **n** *(int, default=1)*: Which occurrence to get (1 = most recent)

**Returns**

* **array**: Array of values when condition was true

**Example**

```python
# Get the close price when buy signals occurred
buy_prices = ta.valuewhen(filtered_buys, close, 1)

# Get the close price from 2 buy signals ago
previous_buy_prices = ta.valuewhen(filtered_buys, close, 2)

# Calculate profit potential from last buy
profit_potential = (close - buy_prices) / buy_prices * 100

df['Last_Buy_Price'] = buy_prices
df['Profit_Potential'] = profit_potential

print("Buy price tracking:")
print(df[['close', 'Filtered_Buy', 'Last_Buy_Price', 'Profit_Potential']].tail())
```

***

### Complete Utility Example: Trading Signal System

```python
import pandas as pd
from openalgo import ta, api

# Fetch data
client = api(api_key='your_api_key_here', host='http://127.0.0.1:5000')
df = client.history(symbol="SBIN", exchange="NSE", interval="5m", 
                   start_date="2025-04-01", end_date="2025-04-08")

close = df['close']
high = df['high']
low = df['low']
volume = df['volume']

# Calculate indicators
sma_10 = ta.sma(close, 10)
sma_20 = ta.sma(close, 20)
rsi = ta.rsi(close, 14)

# Generate basic signals
ma_bullish = ta.crossover(sma_10, sma_20)
ma_bearish = ta.crossunder(sma_10, sma_20)

# Add conditions for signal quality
price_rising = ta.rising(close, 3)
volume_rising = ta.rising(volume, 3)
volatility = ta.stdev(close, 20)
roc_5 = ta.roc(close, 5)

# Enhanced signal conditions
strong_bullish = ma_bullish & price_rising & volume_rising & (rsi < 70)
strong_bearish = ma_bearish & ta.falling(close, 3) & (rsi > 30)

# Filter signals to avoid excessive entries
filtered_long = ta.exrem(strong_bullish, strong_bearish)
filtered_short = ta.exrem(strong_bearish, strong_bullish)

# Create position state
position_long = ta.flip(filtered_long, filtered_short)

# Track entry prices and stops
entry_prices = ta.valuewhen(filtered_long, close, 1)
stop_levels = ta.lowest(low, 10)

# Calculate unrealized P&L for long positions
unrealized_pnl = ((close - entry_prices) / entry_prices * 100) * position_long

# Combine all analysis
df_analysis = pd.DataFrame({
    'Close': close,
    'SMA_10': sma_10,
    'SMA_20': sma_20,
    'RSI': rsi,
    'ROC_5': roc_5,
    'Volatility': volatility,
    'Strong_Bullish': strong_bullish,
    'Strong_Bearish': strong_bearish,
    'Filtered_Long': filtered_long,
    'Filtered_Short': filtered_short,
    'Position_Long': position_long,
    'Entry_Price': entry_prices,
    'Stop_Level': stop_levels,
    'Unrealized_PnL': unrealized_pnl
})

# Display signal summary
print("=== Trading Signal Analysis ===")
print(f"Total Long Signals: {filtered_long.sum()}")
print(f"Total Short Signals: {filtered_short.sum()}")
print(f"Current Position: {'LONG' if position_long.iloc[-1] else 'FLAT'}")

if position_long.iloc[-1]:
    print(f"Entry Price: {entry_prices.iloc[-1]:.2f}")
    print(f"Current Price: {close.iloc[-1]:.2f}")
    print(f"Unrealized P&L: {unrealized_pnl.iloc[-1]:.2f}%")
    print(f"Stop Level: {stop_levels.iloc[-1]:.2f}")

print("\nRecent signals:")
signal_points = df_analysis[filtered_long | filtered_short].tail()
print(signal_points[['Close', 'RSI', 'Filtered_Long', 'Filtered_Short']])
```

### Best Practices for Utility Functions

1. **Signal Filtering**: Always use `exrem()` to filter excessive signals
2. **State Management**: Use `flip()` to maintain position states
3. **Condition Combining**: Combine multiple utilities for robust signal generation
4. **Historical Reference**: Use `valuewhen()` to track important price levels
5. **Trend Confirmation**: Use `rising()` and `falling()` to confirm trend direction

### Common Signal Patterns

1. **Momentum Confirmation**: `crossover() + rising() + volume_confirmation`
2. **Reversal Detection**: `falling() + oversold_condition + volume_spike`
3. **Breakout Validation**: `cross() + highest()/lowest() + volatility_expansion`
4. **Trend Following**: `flip() + moving_average_alignment + momentum_filter`


---

# Agent Instructions: Querying This Documentation

If you need additional information that is not directly available in this page, you can query the documentation dynamically by asking a question.

Perform an HTTP GET request on the current page URL with the `ask` query parameter:

```
GET https://docs.openalgo.in/trading-platform/python/indicators/utility.md?ask=<question>
```

The question should be specific, self-contained, and written in natural language.
The response will contain a direct answer to the question and relevant excerpts and sources from the documentation.

Use this mechanism when the answer is not explicitly present in the current page, you need clarification or additional context, or you want to retrieve related documentation sections.
