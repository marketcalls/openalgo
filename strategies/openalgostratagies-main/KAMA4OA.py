#KAMA (Kaufman's Adaptive Moving Average)-based trading strategy. 
# KAMA adapts to market volatility, becoming more sensitive during trends and less so during consolidations. 
# This strategy uses KAMA to identify potential entry and exit points.
from openalgo.orders import api
import yfinance as yf
import pandas as pd
import numpy as np
import time
import threading
import os

# Get API key from openalgo portal
api_key = 'your_openalgo_apikey'

# Set the StrategyName, broker code, Trading symbol, exchange, product, and quantity
strategy = "KAMA Python"
symbol = "RELIANCE"  # OpenAlgo Symbol
exchange = "NSE"
product = "MIS"
quantity = 1

# yfinance datafeed settings
yfsymbol = "RELIANCE.NS"  # Yahoo Finance Datafeed Symbol
period = "1d"
timeframe = "1m"

# KAMA indicator inputs
kama_period = 10
fast_ema = 2  # Fast EMA factor
slow_ema = 30  # Slow EMA factor

# Set the API Key
client = api(api_key=api_key, host='http://127.0.0.1:5000')

# Function to calculate KAMA
def calculate_kama(df, period, fast_ema, slow_ema):
    close = df['Close']
    
    # Calculate Efficiency Ratio (ER)
    change = abs(close.diff(period))
    volatility = close.diff().abs().rolling(window=period).sum()
    er = change / volatility
    
    # Calculate smoothing constant (SC)
    fast = 2 / (fast_ema + 1)
    slow = 2 / (slow_ema + 1)
    sc = (er * (fast - slow) + slow) ** 2
    
    # Calculate KAMA
    kama = close.copy()
    for i in range(period, len(close)):
        kama.iloc[i] = kama.iloc[i - 1] + sc.iloc[i] * (close.iloc[i] - kama.iloc[i - 1])
    
    return pd.Series(kama, name='KAMA')

# KAMA-based strategy function
def kama_strategy():
    stock = yf.Ticker(yfsymbol)
    position = 0

    while True:
        # Fetch data
        df = stock.history(period=period, interval=timeframe)
        df['KAMA'] = calculate_kama(df, kama_period, fast_ema, slow_ema)
        
        close = df['Close'].round(2)
        kama = df['KAMA'].round(2)
        
        # Define buy and sell conditions
        long_entry = close.iloc[-2] > kama.iloc[-2] and close.iloc[-3] <= kama.iloc[-3]
        short_entry = close.iloc[-2] < kama.iloc[-2] and close.iloc[-3] >= kama.iloc[-3]

        if long_entry and position <= 0:
            position = quantity
            response = client.placesmartorder(
                        strategy=strategy,
                        symbol=symbol,
                        action="BUY",
                        exchange=exchange,
                        price_type="MARKET",
                        product=product,
                        quantity=quantity,
                        position_size=position
                        )
            print("Buy Order Response:", response)

        elif short_entry and position >= 0:
            position = quantity * -1
            response = client.placesmartorder(
                        strategy=strategy,
                        symbol=symbol,
                        action="SELL",
                        exchange=exchange,
                        price_type="MARKET",
                        product=product,
                        quantity=quantity,
                        position_size=position
                        )
            print("Sell Order Response:", response)

        print("Position:", position)
        print("LTP:", close.iloc[-1])
        print("KAMA:", kama.iloc[-2])
        print("long_entry:", long_entry)
        print("short_entry:", short_entry)

        time.sleep(15)

# Start the KAMA strategy in a separate thread
t = threading.Thread(target=kama_strategy)
t.start()
