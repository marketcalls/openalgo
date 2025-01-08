# Coded surisetty
import time
import threading
import logging
from datetime import datetime
import pandas as pd
import numpy as np
import yfinance as yf
from openalgo.orders import api
import os

# Configure logging
logging.basicConfig(
    filename="doublesupertrend_strategy.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# Get API key from OpenAlgo portal
api_key = 'your_openalgo_apikey'

# Set strategy, broker, and trading parameters
strategy = "Supertrend Python"
symbol = "TATAPOWER"  # OpenAlgo Symbol
exchange = "NSE"
product = "MIS"
quantity = 1
# Toggle demo mode
DEMO_MODE = False  # Set to False for live trading

# yfinance datafeed settings
yfsymbol = f"{symbol}.NS"  # Yahoo Finance Symbol
period = "5d"  # Last 5 days for demo
timeframe = "1m"

# Set the API Key
client = api(api_key=api_key, host='http://192.168.29.8:5000')



# Function to calculate the Supertrend indicator
def Supertrend(df, atr_period, multiplier):
    high = df['High']
    low = df['Low']
    close = df['Close']
    
    # Calculate ATR
    price_diffs = [high - low, high - close.shift(), close.shift() - low]
    true_range = pd.concat(price_diffs, axis=1)
    true_range = true_range.abs().max(axis=1)
    atr = true_range.ewm(alpha=1 / atr_period, min_periods=atr_period).mean()
    
    hl2 = (high + low) / 2
    upper_band = hl2 + (multiplier * atr)
    lower_band = hl2 - (multiplier * atr)
    supertrend = [True] * len(df)
    
    for i in range(1, len(df)):
        if close.iloc[i] > upper_band.iloc[i - 1]:  # Use .iloc for positional indexing
            supertrend[i] = True
        elif close.iloc[i] < lower_band.iloc[i - 1]:  # Use .iloc for positional indexing
            supertrend[i] = False
        else:
            supertrend[i] = supertrend[i - 1]
            
        if supertrend[i]:
            lower_band.iloc[i] = max(lower_band.iloc[i], lower_band.iloc[i - 1])  # Use .iloc for positional indexing
        else:
            upper_band.iloc[i] = min(upper_band.iloc[i], upper_band.iloc[i - 1])  # Use .iloc for positional indexing

    return pd.Series(supertrend, index=df.index)


# Function to calculate two Supertrend indicators
def DualSupertrend(df, atr_period1, multiplier1, atr_period2, multiplier2):
    df = df.copy()  # Ensure no SettingWithCopyWarning
    df['SupertrendLow'] = Supertrend(df, atr_period1, multiplier1)
    df['SupertrendHigh'] = Supertrend(df, atr_period2, multiplier2)
    return df

# Function to fetch demo data (last 5 days of 1-minute data)
def get_demo_data():
    stock = yf.Ticker(yfsymbol)
    df = stock.history(period=period, interval=timeframe)
    df = df.round(2)
    return df

# Function to yield demo data dynamically (1 candle every second)
def demo_data_stream(df):
    for i in range(len(df)):
        yield df.iloc[:i + 1]
        time.sleep(0.1)

# Trading strategy
def dual_supertrend_strategy():
    position = 0  # Track current position

    # Load data
    if DEMO_MODE:
        logging.info("Running in DEMO MODE")
        df = get_demo_data()
        data_stream = demo_data_stream(df)
    else:
        logging.info("Running in LIVE MODE")
        stock = yf.Ticker(yfsymbol)

    while True:
        # Get new data (live or from demo stream)
        if DEMO_MODE:
            df = next(data_stream)
        else:
            df = stock.history(period="1d", interval="1m")
            df = df.round(2)

        # Ensure there are enough rows for calculations
        if len(df) < 2:
            continue  # Skip until we have at least 2 rows for comparison

        # Compute the Dual Supertrend indicators
        df = DualSupertrend(df, 10, 3, 30, 9)

       
        # Extract the latest data
        latest_close = df['Close'].iloc[-1]
        is_uptrend_low = df['SupertrendLow'].iloc[-1]
        is_uptrend_high = df['SupertrendHigh'].iloc[-1]
        prev_low = df['SupertrendLow'].iloc[-2]
        prev_high = df['SupertrendHigh'].iloc[-2]

        # Define signals
        buy_signal = (is_uptrend_low and is_uptrend_high) and (not prev_low or not prev_high)
        sell_signal = (not is_uptrend_low and not is_uptrend_high) and (prev_low or prev_high)

        # Long Entry
        if buy_signal and position == 0:
            position = quantity
            if not DEMO_MODE:
                response = client.placesmartorder(
                    strategy=strategy,
                    symbol=symbol,
                    action="BUY",
                    exchange=exchange,
                    price_type="MARKET",
                    product=product,
                    quantity=quantity
                )
                logging.info(f"Buy Order Executed: {response}")
            logging.info("Buy Signal Triggered")
            print("Buy Signal Triggered")

        # Exit Long Position
        elif position > 0 and not is_uptrend_low:
            position = 0
            if not DEMO_MODE:
                response = client.placesmartorder(
                    strategy=strategy,
                    symbol=symbol,
                    action="SELL",
                    exchange=exchange,
                    price_type="MARKET",
                    product=product,
                    quantity=quantity
                )
                logging.info(f"Exit Long Position Executed: {response}")
            logging.info("Exit Long Signal Triggered")
            print("Exit Long Signal Triggered")
            
        # Short Entry
        elif sell_signal and position == 0:
            position = -quantity
            if not DEMO_MODE:
                response = client.placesmartorder(
                    strategy=strategy,
                    symbol=symbol,
                    action="SELL",
                    exchange=exchange,
                    price_type="MARKET",
                    product=product,
                    quantity=quantity
                )
                logging.info(f"Short Order Executed: {response}")
            logging.info("Short Signal Triggered")
            print("Short Signal Triggered")
            
        # Exit Short Position
        elif position < 0 and is_uptrend_low:
            position = 0
            if not DEMO_MODE:
                response = client.placesmartorder(
                    strategy=strategy,
                    symbol=symbol,
                    action="BUY",
                    exchange=exchange,
                    price_type="MARKET",
                    product=product,
                    quantity=quantity
                )
                logging.info(f"Exit Short Position Executed: {response}")
            logging.info("Exit Short Signal Triggered")
            print("Exit Short Signal Triggered")
            
        #Log the current status
        logging.info(
            f"Position: {position}, LTP: {latest_close}, "
            f"SupertrendLow: {is_uptrend_low}, SupertrendHigh: {is_uptrend_high}, "
            f"Buy Signal: {buy_signal}, Sell Signal: {sell_signal}"
        )
        print("Position:", position)
        print("LTP:", latest_close)
        print("SupertrendLow:", is_uptrend_low)
        print("SupertrendHigh:", is_uptrend_high)
        print("Buy Signal:", buy_signal)
        print("Sell Signal:", sell_signal)


# Start the strategy in a separate thread
t = threading.Thread(target=dual_supertrend_strategy)
t.start()
