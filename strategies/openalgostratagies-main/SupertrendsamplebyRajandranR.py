

#Coded by Rajandran R - www.marketcalls.in / www.openalgo.in

from openalgo.orders import api
import yfinance as yf
import pandas as pd
import numpy as np
import time
import threading
import os


# Get API key from openalgo portal
api_key = 'your_openalgo_apikey'

#set the StrategyName, broker code, Trading symbol, exchange, product and quantity
strategy = "Supertrend Python"
symbol = "RELIANCE"  #OpenAlgo Symbol
exchange = "NSE"
product="MIS"
quantity = 1

#yfinance datafeed settings
yfsymbol = "RELIANCE.NS" #Yahoo Finance Datafeed Symbol
period = "1d"
timeframe = "1m"

#supertrend indicator inputs
atr_period = 5
atr_multiplier = 1.0

# Set the API Key 
client = api(api_key=api_key, host='http://127.0.0.1:5000')

def Supertrend(df, atr_period, multiplier):
    high = df['High']
    low = df['Low']
    close = df['Close']
    
    # calculate ATR
    price_diffs = [high - low, high - close.shift(), close.shift() - low]
    true_range = pd.concat(price_diffs, axis=1)
    true_range = true_range.abs().max(axis=1)
    atr = true_range.ewm(alpha=1/atr_period, min_periods=atr_period).mean()
    
    hl2 = (high + low) / 2
    final_upperband = upperband = hl2 + (multiplier * atr)
    final_lowerband = lowerband = hl2 - (multiplier * atr)
    
    supertrend = [True] * len(df)
    
    for i in range(1, len(df.index)):
        curr, prev = i, i-1
        
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
        'Final Lowerband': final_lowerband,
        'Final Upperband': final_upperband
    }, index=df.index)

def supertrend_strategy():
    stock = yf.Ticker(yfsymbol)
    position = 0
    
    while True:
        df = stock.history(period=period, interval=timeframe)
        close = df['Close'].round(2)
        supertrend = Supertrend(df, atr_period, atr_multiplier)
        
        is_uptrend = supertrend['Supertrend']
        longentry = is_uptrend.iloc[-2] and not is_uptrend.iloc[-3]
        shortentry = is_uptrend.iloc[-3] and not is_uptrend.iloc[-2]

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

        print("Position:", position)
        print("LTP:", close.iloc[-1])
        print("Supertrend:", supertrend['Supertrend'].iloc[-2])
        print("LowerBand:", supertrend['Final Lowerband'].iloc[-2].round(2))
        print("UpperBand:", supertrend['Final Upperband'].iloc[-2].round(2))
        print("longentry:", longentry)
        print("shortentry:", shortentry)

        time.sleep(15)

t = threading.Thread(target=supertrend_strategy)
t.start()