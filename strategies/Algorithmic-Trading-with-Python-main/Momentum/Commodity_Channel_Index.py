import pandas as pd
import requests
import pandas_datareader as web
import datetime as dt
import numpy as np
import matplotlib.pyplot as plt
from math import floor
from termcolor import colored as cl

plt.rcParams['figure.figsize'] = (20, 10)
plt.style.use('fivethirtyeight')

# EXTRACTING STOCK DATA

def get_historical_data(symbol, start_date):
    api_key = 'YOUR API KEY'
    api_url = f'https://api.twelvedata.com/time_series?symbol={symbol}&interval=1day&outputsize=5000&apikey={api_key}'
    raw_df = requests.get(api_url).json()
    df = pd.DataFrame(raw_df['values']).iloc[::-1].set_index('datetime').astype(float)
    df = df[df.index >= start_date]
    df.index = pd.to_datetime(df.index)
    return df

aapl = get_historical_data('AAPL', '2020-01-01')
aapl

def get_cci(symbol, n, start_date):
    api_key = open(r'api_key.txt')
    url = f'https://www.alphavantage.co/query?function=CCI&symbol={symbol}&interval=daily&time_period={n}&apikey={api_key}'
    raw = requests.get(url).json()
    df = pd.DataFrame(raw['Technical Analysis: CCI']).T.iloc[::-1]
    df = df[df.index >= start_date]
    df.index = pd.to_datetime(df.index)
    df = df.astype(float)
    return df

aapl['cci'] = get_cci('aapl', 20, '2020-01-01')
aapl = aapl.dropna()
aapl.tail()

ax1 = plt.subplot2grid((10,1), (0,0), rowspan = 5, colspan = 1)
ax2 = plt.subplot2grid((10,1), (6,0), rowspan = 4, colspan = 1)
ax1.plot(aapl['close'])
ax1.set_title('FACEBOOK SHARE PRICE')
ax2.plot(aapl['cci'], color = 'orange')
ax2.set_title('FACEBOOK CCI 20')
ax2.axhline(150, linestyle = '--', linewidth = 1, color = 'black')
ax2.axhline(-150, linestyle = '--', linewidth = 1, color = 'black')
plt.show()

def implement_cci_strategy(prices, cci):
    buy_price = []
    sell_price = []
    cci_signal = []
    signal = 0
    
    lower_band = (-150)
    upper_band = 150
    
    for i in range(len(prices)):
        if cci[i-1] > lower_band and cci[i] < lower_band:
            if signal != 1:
                buy_price.append(prices[i])
                sell_price.append(np.nan)
                signal = 1
                cci_signal.append(signal)
            else:
                buy_price.append(np.nan)
                sell_price.append(np.nan)
                cci_signal.append(0)
                
        elif cci[i-1] < upper_band and cci[i] > upper_band:
            if signal != -1:
                buy_price.append(np.nan)
                sell_price.append(prices[i])
                signal = -1
                cci_signal.append(signal)
            else:
                buy_price.append(np.nan)
                sell_price.append(np.nan)
                cci_signal.append(0)
                
        else:
            buy_price.append(np.nan)
            sell_price.append(np.nan)
            cci_signal.append(0)
            
    return buy_price, sell_price, cci_signal

buy_price, sell_price, cci_signal = implement_cci_strategy(aapl['close'], aapl['cci'])

ax1 = plt.subplot2grid((10,1), (0,0), rowspan = 5, colspan = 1)
ax2 = plt.subplot2grid((10,1), (6,0), rowspan = 4, colspan = 1)
ax1.plot(aapl['close'], color = 'skyblue', label = 'aapl')
ax1.plot(aapl.index, buy_price, marker = '^', markersize = 12, linewidth = 0, label = 'BUY SIGNAL', color = 'green')
ax1.plot(aapl.index, sell_price, marker = 'v', markersize = 12, linewidth = 0, label = 'SELL SIGNAL', color = 'r')
ax1.set_title('FACEBOOK SHARE PRICE')
ax1.legend()
ax2.plot(aapl['cci'], color = 'orange')
ax2.set_title('FACEBOOK CCI 20')
ax2.axhline(150, linestyle = '--', linewidth = 1, color = 'black')
ax2.axhline(-150, linestyle = '--', linewidth = 1, color = 'black')
plt.show()

position = []
for i in range(len(cci_signal)):
    if cci_signal[i] > 1:
        position.append(0)
    else:
        position.append(1)
        
for i in range(len(aapl['close'])):
    if cci_signal[i] == 1:
        position[i] = 1
    elif cci_signal[i] == -1:
        position[i] = 0
    else:
        position[i] = position[i-1]
        
cci = aapl['cci']
close_price = aapl['close']
cci_signal = pd.DataFrame(cci_signal).rename(columns = {0:'cci_signal'}).set_index(aapl.index)
position = pd.DataFrame(position).rename(columns = {0:'cci_position'}).set_index(aapl.index)

frames = [close_price, cci, cci_signal, position]
strategy = pd.concat(frames, join = 'inner', axis = 1)

strategy.head()

rets = aapl.close.pct_change().dropna()
strat_rets = strategy.cci_position[1:]*rets

plt.title('Daily Returns')
rets.plot(color = 'blue', alpha = 0.3, linewidth = 7)
strat_rets.plot(color = 'r', linewidth = 1)
plt.show()
