#!/usr/bin/env python
"""
Simple EMA Crossover Strategy Example
This strategy demonstrates how to integrate with OpenAlgo API
"""
from openalgo import api
import pandas as pd
import numpy as np
import time
import threading
from datetime import datetime, timedelta
import os

# Get API key from openalgo portal
api_key = os.getenv('OPENALGO_APIKEY')

if not api_key:
    print("Error: OPENALGO_APIKEY environment variable not set")
    exit(1)


# Set the strategy details and trading parameters
strategy = "EMA Crossover Python"
symbol = 'NHPC'  # OpenAlgo Symbol
exchange = "NSE"
product = "MIS"
quantity = 1

# EMA periods
fast_period = 5
slow_period = 10

# Set the API Key
client = api(api_key=api_key, host='http://127.0.0.1:5000')

def calculate_ema_signals(df):
    """
    Calculate EMA crossover signals.
    """
    close = df['close']
    
    # Calculate EMAs
    ema_fast = close.ewm(span=fast_period, adjust=False).mean()
    ema_slow = close.ewm(span=slow_period, adjust=False).mean()
    
    # Create crossover signals
    crossover = pd.Series(False, index=df.index)
    crossunder = pd.Series(False, index=df.index)
    
    # Previous values of EMAs
    prev_fast = ema_fast.shift(1)
    prev_slow = ema_slow.shift(1)
    
    # Current values of EMAs
    curr_fast = ema_fast
    curr_slow = ema_slow
    
    # Generate crossover signals
    crossover = (prev_fast < prev_slow) & (curr_fast > curr_slow)
    crossunder = (prev_fast > prev_slow) & (curr_fast < curr_slow)
    
    return pd.DataFrame({
        'EMA_Fast': ema_fast,
        'EMA_Slow': ema_slow,
        'Crossover': crossover,
        'Crossunder': crossunder
    }, index=df.index)

def ema_strategy():
    """
    The EMA crossover trading strategy.
    """
    position = 0

    while True:
        try:
            # Dynamic date range: 7 days back to today
            end_date = datetime.now().strftime("%Y-%m-%d")
            start_date = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")

            # Fetch 1-minute historical data using OpenAlgo
            df = client.history(
                symbol=symbol,
                exchange=exchange,
                interval="1m",
                start_date=start_date,
                end_date=end_date
            )

            # Check for valid data
            if df.empty:
                print("DataFrame is empty. Retrying...")
                time.sleep(15)
                continue

            # Verify required columns
            if 'close' not in df.columns:
                raise KeyError("Missing 'close' column in DataFrame")

            # Round the close column
            df['close'] = df['close'].round(2)

            # Calculate EMAs and signals
            signals = calculate_ema_signals(df)

            # Get latest signals
            crossover = signals['Crossover'].iloc[-2]  # Using -2 to avoid partial candle
            crossunder = signals['Crossunder'].iloc[-2]

            # Execute Buy Order
            if crossover and position <= 0:
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

            # Execute Sell Order
            elif crossunder and position >= 0:
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

            # Log strategy information
            print("\nStrategy Status:")
            print("-" * 50)
            print(f"Position: {position}")
            print(f"LTP: {df['close'].iloc[-1]}")
            print(f"Fast EMA ({fast_period}): {signals['EMA_Fast'].iloc[-2]:.2f}")
            print(f"Slow EMA ({slow_period}): {signals['EMA_Slow'].iloc[-2]:.2f}")
            print(f"Buy Signal: {crossover}")
            print(f"Sell Signal: {crossunder}")
            print("-" * 50)

        except Exception as e:
            print(f"Error in strategy: {str(e)}")
            time.sleep(15)
            continue

        # Wait before the next cycle
        time.sleep(15)

if __name__ == "__main__":
    print(f"Starting {fast_period}/{slow_period} EMA Crossover Strategy...")
    ema_strategy()
