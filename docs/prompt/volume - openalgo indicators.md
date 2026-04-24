# Volume

Volume indicators analyze trading volume to assess the strength of price movements and identify potential trend changes. These indicators help determine whether price movements are supported by volume activity.

### Import Statement

```python
from openalgo import ta, api
```

### Getting Sample Data

```python
# Initialize API client
client = api(api_key='your_api_key_here', host='http://127.0.0.1:5000')

# Fetch historical data
df = client.history(symbol="SBIN", 
                   exchange="NSE", 
                   interval="5m", 
                   start_date="2025-04-01", 
                   end_date="2025-04-08")

# Extract OHLCV data
high = df['high']
low = df['low'] 
close = df['close']
open_price = df['open']
volume = df['volume']
```

***

### On Balance Volume (OBV)

OBV is a momentum indicator that uses volume flow to predict changes in stock price by adding volume on up days and subtracting volume on down days.

#### Usage

```python
obv = ta.obv(close, volume)
```

#### Parameters

* **close** *(pandas.Series)*: Closing prices
* **volume** *(pandas.Series)*: Volume data

#### Returns

* **pandas.Series**: OBV values with same index as input

#### Example

```python
# Calculate OBV
obv_values = ta.obv(df['close'], df['volume'])

# Add to DataFrame
df['OBV'] = obv_values

print(df[['close', 'volume', 'OBV']].tail())
```

***

### On Balance Volume with Smoothing (OBV Smoothed)

Enhanced OBV with various smoothing options including moving averages and Bollinger Bands support.

#### Usage

```python
# Basic smoothed OBV
obv_smoothed = ta.obv_smoothed(close, volume, ma_type="SMA", ma_length=20)

# With Bollinger Bands
obv_bb_middle, obv_bb_upper, obv_bb_lower = ta.obv_smoothed(
    close, volume, ma_type="SMA + Bollinger Bands", bb_length=20, bb_mult=2.0
)
```

#### Parameters

* **close** *(pandas.Series)*: Closing prices
* **volume** *(pandas.Series)*: Volume data
* **ma\_type** *(str, default="None")*: Smoothing type - "None", "SMA", "SMA + Bollinger Bands", "EMA", "SMMA (RMA)", "WMA", "VWMA"
* **ma\_length** *(int, default=20)*: Moving average length
* **bb\_length** *(int, default=20)*: Bollinger Bands length
* **bb\_mult** *(float, default=2.0)*: Bollinger Bands multiplier

#### Returns

* **pandas.Series**: Smoothed OBV values (for most ma\_types)
* **tuple**: (middle, upper, lower) for "SMA + Bollinger Bands"

#### Example

```python
# Calculate various OBV smoothing options
obv_sma = ta.obv_smoothed(df['close'], df['volume'], ma_type="SMA", ma_length=20)
obv_ema = ta.obv_smoothed(df['close'], df['volume'], ma_type="EMA", ma_length=20)

# OBV with Bollinger Bands
obv_bb_mid, obv_bb_up, obv_bb_low = ta.obv_smoothed(
    df['close'], df['volume'], ma_type="SMA + Bollinger Bands"
)

df['OBV_SMA'] = obv_sma
df['OBV_EMA'] = obv_ema
df['OBV_BB_Mid'] = obv_bb_mid
df['OBV_BB_Upper'] = obv_bb_up
df['OBV_BB_Lower'] = obv_bb_low
```

***

### Volume Weighted Average Price (VWAP)

VWAP is the average price a security has traded at throughout the day, based on both volume and price, giving more weight to prices with higher volume.

#### Usage

```python
vwap = ta.vwap(high, low, close, volume, source="hlc3", anchor="Session")
```

#### Parameters

* **high** *(pandas.Series)*: High prices
* **low** *(pandas.Series)*: Low prices
* **close** *(pandas.Series)*: Closing prices
* **volume** *(pandas.Series)*: Volume data
* **source** *(str, default="hlc3")*: Price source - "hlc3", "hl2", "ohlc4", "close"
* **anchor** *(str, default="Session")*: Anchor period - "Session", "Week", "Month", etc.

#### Returns

* **pandas.Series**: VWAP values

#### Example

```python
# Calculate VWAP
vwap_values = ta.vwap(df['high'], df['low'], df['close'], df['volume'])

# VWAP with different source
vwap_close = ta.vwap(df['high'], df['low'], df['close'], df['volume'], source="close")

df['VWAP'] = vwap_values
df['VWAP_Close'] = vwap_close

print(df[['close', 'VWAP', 'VWAP_Close']].tail())
```

***

### Money Flow Index (MFI)

MFI is a momentum indicator that uses both price and volume to measure buying and selling pressure. Also known as Volume-Weighted RSI.

#### Usage

```python
mfi = ta.mfi(high, low, close, volume, period=14)
```

#### Parameters

* **high** *(pandas.Series)*: High prices
* **low** *(pandas.Series)*: Low prices
* **close** *(pandas.Series)*: Closing prices
* **volume** *(pandas.Series)*: Volume data
* **period** *(int, default=14)*: Number of periods for MFI calculation

#### Returns

* **pandas.Series**: MFI values (range: 0 to 100)

#### Example

```python
# Calculate MFI with default period
mfi_14 = ta.mfi(df['high'], df['low'], df['close'], df['volume'])

# Calculate MFI with different period
mfi_21 = ta.mfi(df['high'], df['low'], df['close'], df['volume'], period=21)

df['MFI_14'] = mfi_14
df['MFI_21'] = mfi_21

print(df[['close', 'volume', 'MFI_14']].tail())
```

***

### Accumulation/Distribution Line (ADL)

ADL is a volume-based indicator designed to measure the cumulative flow of money into and out of a security.

#### Usage

```python
adl = ta.adl(high, low, close, volume)
```

#### Parameters

* **high** *(pandas.Series)*: High prices
* **low** *(pandas.Series)*: Low prices
* **close** *(pandas.Series)*: Closing prices
* **volume** *(pandas.Series)*: Volume data

#### Returns

* **pandas.Series**: ADL values

#### Example

```python
# Calculate Accumulation/Distribution Line
adl_values = ta.adl(df['high'], df['low'], df['close'], df['volume'])

df['ADL'] = adl_values

print(df[['close', 'volume', 'ADL']].tail())
```

***

### Chaikin Money Flow (CMF)

CMF is the sum of Money Flow Volume over a period divided by the sum of volume over the same period.

#### Usage

```python
cmf = ta.cmf(high, low, close, volume, period=20)
```

#### Parameters

* **high** *(pandas.Series)*: High prices
* **low** *(pandas.Series)*: Low prices
* **close** *(pandas.Series)*: Closing prices
* **volume** *(pandas.Series)*: Volume data
* **period** *(int, default=20)*: Number of periods for CMF calculation

#### Returns

* **pandas.Series**: CMF values

#### Example

```python
# Calculate Chaikin Money Flow
cmf_20 = ta.cmf(df['high'], df['low'], df['close'], df['volume'])

# CMF with different period
cmf_10 = ta.cmf(df['high'], df['low'], df['close'], df['volume'], period=10)

df['CMF_20'] = cmf_20
df['CMF_10'] = cmf_10

print(df[['close', 'CMF_20']].tail())
```

***

### Ease of Movement (EMV)

EMV relates price change to volume and is particularly useful for assessing the strength of a trend.

#### Usage

```python
emv = ta.emv(high, low, volume, length=14, divisor=10000)
```

#### Parameters

* **high** *(pandas.Series)*: High prices
* **low** *(pandas.Series)*: Low prices
* **volume** *(pandas.Series)*: Volume data
* **length** *(int, default=14)*: Period for SMA smoothing
* **divisor** *(int, default=10000)*: Divisor for scaling EMV values

#### Returns

* **pandas.Series**: EMV values

#### Example

```python
# Calculate Ease of Movement
emv_14 = ta.emv(df['high'], df['low'], df['volume'])

# EMV with custom parameters
emv_custom = ta.emv(df['high'], df['low'], df['volume'], length=21, divisor=50000)

df['EMV_14'] = emv_14
df['EMV_Custom'] = emv_custom

print(df[['close', 'volume', 'EMV_14']].tail())
```

***

### Elder Force Index (FI)

Force Index combines price and volume to assess the power used to move the price of an asset.

#### Usage

```python
fi = ta.force_index(close, volume, length=13)
```

#### Parameters

* **close** *(pandas.Series)*: Closing prices
* **volume** *(pandas.Series)*: Volume data
* **length** *(int, default=13)*: Period for EMA smoothing

#### Returns

* **pandas.Series**: Elder Force Index values

#### Example

```python
# Calculate Elder Force Index
fi_13 = ta.force_index(df['close'], df['volume'])

# Force Index with different period
fi_21 = ta.force_index(df['close'], df['volume'], length=21)

df['Force_Index_13'] = fi_13
df['Force_Index_21'] = fi_21

print(df[['close', 'volume', 'Force_Index_13']].tail())
```

***

### Negative Volume Index (NVI)

NVI focuses on days when volume decreases from the previous day, using cumulative rate of change.

#### Usage

```python
# Basic NVI
nvi = ta.nvi(close, volume)

# NVI with EMA signal line
nvi, nvi_ema = ta.nvi_with_ema(close, volume, ema_length=255)
```

#### Parameters

* **close** *(pandas.Series)*: Closing prices
* **volume** *(pandas.Series)*: Volume data
* **ema\_length** *(int, default=255)*: EMA period for signal line

#### Returns

* **pandas.Series**: NVI values
* **tuple**: (nvi, nvi\_ema) for nvi\_with\_ema method

#### Example

```python
# Calculate NVI
nvi_values = ta.nvi(df['close'], df['volume'])

# Calculate NVI with EMA signal
nvi_line, nvi_signal = ta.nvi_with_ema(df['close'], df['volume'])

df['NVI'] = nvi_values
df['NVI_Line'] = nvi_line
df['NVI_Signal'] = nvi_signal

print(df[['close', 'volume', 'NVI']].tail())
```

***

### Positive Volume Index (PVI)

PVI focuses on days when volume increases from the previous day.

#### Usage

```python
# Basic PVI
pvi = ta.pvi(close, volume, initial_value=100.0)

# PVI with signal line
pvi, pvi_signal = ta.pvi_with_signal(close, volume, signal_type="EMA", signal_length=255)
```

#### Parameters

* **close** *(pandas.Series)*: Closing prices
* **volume** *(pandas.Series)*: Volume data
* **initial\_value** *(float, default=100.0)*: Initial PVI value
* **signal\_type** *(str, default="EMA")*: Signal smoothing type ("EMA" or "SMA")
* **signal\_length** *(int, default=255)*: Signal line period

#### Returns

* **pandas.Series**: PVI values
* **tuple**: (pvi, signal) for pvi\_with\_signal method

#### Example

```python
# Calculate PVI
pvi_values = ta.pvi(df['close'], df['volume'])

# Calculate PVI with signal line
pvi_line, pvi_signal = ta.pvi_with_signal(df['close'], df['volume'])

df['PVI'] = pvi_values
df['PVI_Line'] = pvi_line
df['PVI_Signal'] = pvi_signal

print(df[['close', 'volume', 'PVI']].tail())
```

***

### Volume Oscillator (VOLOSC)

Volume Oscillator shows the relationship between two exponential moving averages of volume.

#### Usage

```python
vo = ta.volosc(volume, short_length=5, long_length=10)
```

#### Parameters

* **volume** *(pandas.Series)*: Volume data
* **short\_length** *(int, default=5)*: Short EMA length
* **long\_length** *(int, default=10)*: Long EMA length
* **check\_volume\_validity** *(bool, default=True)*: Check for valid volume data

#### Returns

* **pandas.Series**: Volume Oscillator values

#### Example

```python
# Calculate Volume Oscillator
vo_5_10 = ta.volosc(df['volume'])

# Volume Oscillator with custom periods
vo_3_15 = ta.volosc(df['volume'], short_length=3, long_length=15)

df['VO_5_10'] = vo_5_10
df['VO_3_15'] = vo_3_15

print(df[['volume', 'VO_5_10']].tail())
```

***

### Volume Rate of Change (VROC)

VROC measures the rate of change in volume over a specified period.

#### Usage

```python
vroc = ta.vroc(volume, period=25)
```

#### Parameters

* **volume** *(pandas.Series)*: Volume data
* **period** *(int, default=25)*: Number of periods to look back

#### Returns

* **pandas.Series**: VROC values

#### Example

```python
# Calculate Volume Rate of Change
vroc_25 = ta.vroc(df['volume'])

# VROC with different period
vroc_12 = ta.vroc(df['volume'], period=12)

df['VROC_25'] = vroc_25
df['VROC_12'] = vroc_12

print(df[['volume', 'VROC_25']].tail())
```

***

### Klinger Volume Oscillator (KVO)

KVO is designed to predict price reversals by comparing volume to price movement.

#### Usage

```python
kvo, kvo_trigger = ta.kvo(high, low, close, volume, trig_len=13, fast_x=34, slow_x=55)
```

#### Parameters

* **high** *(pandas.Series)*: High prices
* **low** *(pandas.Series)*: Low prices
* **close** *(pandas.Series)*: Closing prices
* **volume** *(pandas.Series)*: Volume data
* **trig\_len** *(int, default=13)*: Trigger line EMA period
* **fast\_x** *(int, default=34)*: Fast EMA period
* **slow\_x** *(int, default=55)*: Slow EMA period

#### Returns

* **tuple**: (kvo, trigger) pandas.Series

#### Example

```python
# Calculate Klinger Volume Oscillator
kvo_line, kvo_trigger = ta.kvo(df['high'], df['low'], df['close'], df['volume'])

# KVO with custom parameters
kvo_custom, kvo_trig_custom = ta.kvo(df['high'], df['low'], df['close'], df['volume'], 
                                    trig_len=9, fast_x=21, slow_x=34)

df['KVO'] = kvo_line
df['KVO_Trigger'] = kvo_trigger

print(df[['close', 'volume', 'KVO', 'KVO_Trigger']].tail())
```

***

### Price Volume Trend (PVT)

PVT combines price and volume to show cumulative volume based on price changes.

#### Usage

```python
pvt = ta.pvt(close, volume)
```

#### Parameters

* **close** *(pandas.Series)*: Closing prices
* **volume** *(pandas.Series)*: Volume data

#### Returns

* **pandas.Series**: PVT values

#### Example

```python
# Calculate Price Volume Trend
pvt_values = ta.pvt(df['close'], df['volume'])

df['PVT'] = pvt_values

print(df[['close', 'volume', 'PVT']].tail())
```

***

### Relative Volume (RVOL)

RVOL compares current volume to average volume over a specified period.

#### Usage

```python
rvol = ta.rvol(volume, period=20)
```

#### Parameters

* **volume** *(pandas.Series)*: Volume data
* **period** *(int, default=20)*: Period for average volume calculation

#### Returns

* **pandas.Series**: RVOL values

#### Example

```python
# Calculate Relative Volume
rvol_20 = ta.rvol(df['volume'])

# RVOL with different period
rvol_10 = ta.rvol(df['volume'], period=10)

df['RVOL_20'] = rvol_20
df['RVOL_10'] = rvol_10

print(df[['volume', 'RVOL_20']].tail())
```

***

### Complete Volume Analysis Example

```python
from openalgo import ta, api
import pandas as pd

# Get data
client = api(api_key='your_api_key_here', host='http://127.0.0.1:5000')
df = client.history(symbol="SBIN", exchange="NSE", interval="5m", 
                   start_date="2025-04-01", end_date="2025-04-08")

# Calculate multiple volume indicators
df['OBV'] = ta.obv(df['close'], df['volume'])
df['VWAP'] = ta.vwap(df['high'], df['low'], df['close'], df['volume'])
df['MFI'] = ta.mfi(df['high'], df['low'], df['close'], df['volume'])
df['ADL'] = ta.adl(df['high'], df['low'], df['close'], df['volume'])
df['CMF'] = ta.cmf(df['high'], df['low'], df['close'], df['volume'])
df['EMV'] = ta.emv(df['high'], df['low'], df['volume'])
df['Force_Index'] = ta.force_index(df['close'], df['volume'])
df['Volume_Osc'] = ta.volosc(df['volume'])
df['PVT'] = ta.pvt(df['close'], df['volume'])
df['RVOL'] = ta.rvol(df['volume'])

# KVO requires multiple returns
df['KVO'], df['KVO_Trigger'] = ta.kvo(df['high'], df['low'], df['close'], df['volume'])

# Display results
volume_indicators = ['close', 'volume', 'OBV', 'VWAP', 'MFI', 'ADL', 'CMF', 
                    'EMV', 'Force_Index', 'Volume_Osc', 'PVT', 'RVOL', 'KVO']

print("Volume Indicators Analysis:")
print(df[volume_indicators].tail(10))

# Volume analysis summary
print("\nVolume Indicators Summary (Last Period):")
last_row = df.iloc[-1]
print(f"Close Price: {last_row['close']:.2f}")
print(f"Volume: {last_row['volume']:,}")
print(f"VWAP: {last_row['VWAP']:.2f}")
print(f"MFI: {last_row['MFI']:.2f}")
print(f"Relative Volume: {last_row['RVOL']:.2f}")
print(f"Volume Oscillator: {last_row['Volume_Osc']:.2f}")
```

### Volume Analysis Interpretation

1. **OBV**: Rising OBV confirms uptrend, falling OBV confirms downtrend
2. **VWAP**: Price above VWAP suggests bullish momentum, below suggests bearish
3. **MFI**: Values above 80 indicate overbought, below 20 indicate oversold
4. **ADL**: Rising ADL confirms price uptrend with strong accumulation
5. **CMF**: Positive values indicate buying pressure, negative indicate selling
6. **Volume Oscillator**: Positive values show increasing volume momentum
7. **Relative Volume**: Values above 1.0 indicate higher than average volume


---

# Agent Instructions: Querying This Documentation

If you need additional information that is not directly available in this page, you can query the documentation dynamically by asking a question.

Perform an HTTP GET request on the current page URL with the `ask` query parameter:

```
GET https://docs.openalgo.in/trading-platform/python/indicators/volume.md?ask=<question>
```

The question should be specific, self-contained, and written in natural language.
The response will contain a direct answer to the question and relevant excerpts and sources from the documentation.

Use this mechanism when the answer is not explicitly present in the current page, you need clarification or additional context, or you want to retrieve related documentation sections.
