
from openalgo.orders import api
import yfinance as yf
import pandas as pd
import numpy as np
import time
import threading
import os

# Get API key from openalgo portal
api_key = 'your_openalgo_apikey'

# Set the StrategyName, broker code, Trading symbol, exchange, product and quantity
strategy = "RSI Python"
symbol = "RELIANCE"  # OpenAlgo Symbol
exchange = "NSE"
product = "MIS"
quantity = 1

# yfinance datafeed settings
yfsymbol = "RELIANCE.NS"  # Yahoo Finance Datafeed Symbol
period = "1d"
timeframe = "1m"

# RSI indicator inputs
rsi_period = 14
rsi_overbought = 70
rsi_oversold = 30

# Set the API Key
client = api(api_key=api_key, host='http://127.0.0.1:5000')

# Function to calculate RSI
def calculate_rsi(data, period):
    delta = data['Close'].diff()
    gain = np.where(delta > 0, delta, 0)
    loss = np.where(delta < 0, -delta, 0)
    
    avg_gain = pd.Series(gain).rolling(window=period, min_periods=1).mean()
    avg_loss = pd.Series(loss).rolling(window=period, min_periods=1).mean()
    
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    
    return pd.Series(rsi, name='RSI')

# RSI-based strategy function
def rsi_strategy():
    stock = yf.Ticker(yfsymbol)
    position = 0
    
    while True:
        # Fetch data
        df = stock.history(period=period, interval=timeframe)
        df['RSI'] = calculate_rsi(df, rsi_period)
        
        # Extract the latest RSI value
        rsi = df['RSI'].iloc[-2]
        close = df['Close'].round(2)
        
        # Define buy and sell conditions
        long_entry = rsi < rsi_oversold
        short_entry = rsi > rsi_overbought
        
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
        print("RSI:", rsi)
        print("long_entry:", long_entry)
        print("short_entry:", short_entry)

        time.sleep(15)

# Start the RSI strategy in a separate thread
t = threading.Thread(target=rsi_strategy)
t.start()
