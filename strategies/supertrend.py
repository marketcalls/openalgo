from openalgo import api
import pandas as pd
import numpy as np
import time
import threading
from datetime import datetime, timedelta

# Get API key from openalgo portal
api_key = 'your-openalgo-api-key'

# Set the strategy details and trading parameters
strategy = "Supertrend Python"
symbol = "RELIANCE"  # OpenAlgo Symbol
exchange = "NSE"
product = "MIS"
quantity = 1

# Supertrend indicator inputs
atr_period = 5
atr_multiplier = 1.0

# Set the API Key
client = api(api_key=api_key, host='http://127.0.0.1:5000')

def Supertrend(df, atr_period, multiplier):
    """
    Calculate the Supertrend indicator.
    """
    high = df['high']
    low = df['low']
    close = df['close']

    # Calculate ATR using ewm like original code
    price_diffs = [high - low, 
                   high - close.shift(), 
                   close.shift() - low]
    true_range = pd.concat(price_diffs, axis=1)
    true_range = true_range.abs().max(axis=1)
    atr = true_range.ewm(alpha=1/atr_period, min_periods=atr_period).mean()

    hl2 = (high + low) / 2
    final_upperband = upperband = hl2 + (multiplier * atr)
    final_lowerband = lowerband = hl2 - (multiplier * atr)

    # Initialize supertrend array with boolean values like original code
    supertrend = [True] * len(df)

    for i in range(1, len(df.index)):
        curr, prev = i, i - 1

        if close.iloc[curr] > final_upperband.iloc[prev]:
            supertrend[curr] = True
        elif close.iloc[curr] < final_lowerband.iloc[prev]:
            supertrend[curr] = False
        else:
            supertrend[curr] = supertrend[prev]

            if supertrend[curr] == True and final_lowerband.iloc[curr] < final_lowerband.iloc[prev]:
                final_lowerband.iat[curr] = final_lowerband.iat[prev]
            if supertrend[curr] == False and final_upperband.iloc[curr] > final_upperband.iloc[prev]:
                final_upperband.iat[curr] = final_upperband.iat[prev]

        if supertrend[curr] == True:
            final_upperband.iat[curr] = np.nan
        else:
            final_lowerband.iat[curr] = np.nan

    return pd.DataFrame({
        'Supertrend': supertrend,
        'Final_Lowerband': final_lowerband,
        'Final_Upperband': final_upperband
    }, index=df.index)

def supertrend_strategy():
    """
    The Supertrend trading strategy.
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
            expected_columns = {'close', 'high', 'low', 'open'}
            missing_columns = expected_columns - set(df.columns)
            if missing_columns:
                raise KeyError(f"Missing columns in DataFrame: {missing_columns}")

            # Round the close column
            df['close'] = df['close'].round(2)

            # Calculate Supertrend
            supertrend = Supertrend(df, atr_period, atr_multiplier)

            # Generate signals using original logic
            is_uptrend = supertrend['Supertrend']
            longentry = is_uptrend.iloc[-2] and not is_uptrend.iloc[-3]
            shortentry = is_uptrend.iloc[-3] and not is_uptrend.iloc[-2]

            # Execute Buy Order
            if longentry and position <= 0:
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
            elif shortentry and position >= 0:
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
            print(f"Supertrend: {supertrend['Supertrend'].iloc[-2]}")
            print(f"LowerBand: {supertrend['Final_Lowerband'].iloc[-2]:.2f}")
            print(f"UpperBand: {supertrend['Final_Upperband'].iloc[-2]:.2f}")
            print(f"Buy Signal: {longentry}")
            print(f"Sell Signal: {shortentry}")
            print("-" * 50)

        except Exception as e:
            print(f"Error in strategy: {str(e)}")
            time.sleep(15)
            continue

        # Wait before the next cycle
        time.sleep(15)

if __name__ == "__main__":
    print("Starting Supertrend Strategy...")
    supertrend_strategy()
