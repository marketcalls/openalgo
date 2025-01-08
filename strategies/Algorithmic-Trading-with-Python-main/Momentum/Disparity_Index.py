# IMPORTING PACKAGES

import numpy as np
import requests
import pandas as pd
import matplotlib.pyplot as plt
from math import floor
from termcolor import colored as cl

plt.style.use('fivethirtyeight')
plt.rcParams['figure.figsize'] = (20,10)

# EXTRACTING STOCK DATA

def get_historical_data(symbol, start_date):
    api_key = 'YOUR API KEY'
    api_url = f'https://api.twelvedata.com/time_series?symbol={symbol}&interval=1day&outputsize=5000&apikey={api_key}'
    raw_df = requests.get(api_url).json()
    df = pd.DataFrame(raw_df['values']).iloc[::-1].set_index('datetime').astype(float)
    df = df[df.index >= start_date]
    df.index = pd.to_datetime(df.index)
    return df

aapl = get_historical_data('aapl', '2020-01-01')
aapl.tail()

# DISPARITY INDEX CALCULATION

def get_di(data, lookback):
    ma = data.rolling(lookback).mean()
    di = ((data - ma) / ma) * 100
    return di

aapl['di_14'] = get_di(aapl['close'], 14)
aapl = aapl.dropna()
aapl.tail()

# DISPARITY INDEX PLOT

ax1 = plt.subplot2grid((11,1), (0,0), rowspan = 5, colspan = 1)
ax2 = plt.subplot2grid((11,1), (6,0), rowspan = 5, colspan = 1)
ax1.plot(aapl['close'], linewidth = 2, color = '#1976d2')
ax1.set_title('AAPL CLOSING PRICES')
for i in range(len(aapl)):
    if aapl.iloc[i, 5] >= 0:
        ax2.bar(aapl.iloc[i].name, aapl.iloc[i, 5], color = '#26a69a')
    else:    
        ax2.bar(aapl.iloc[i].name, aapl.iloc[i, 5], color = '#ef5350')
ax2.set_title('AAPL DISPARITY INDEX 14')
plt.show()

# DISPARITY INDEX STRATEGY

def implement_di_strategy(prices, di):
    buy_price = []
    sell_price = []
    di_signal = []
    signal = 0
    
    for i in range(len(prices)):
        if di[i-4] < 0 and di[i-3] < 0 and di[i-2] < 0 and di[i-1] < 0 and di[i] > 0:
            if signal != 1:
                buy_price.append(prices[i])
                sell_price.append(np.nan)
                signal = 1
                di_signal.append(signal)
            else:
                buy_price.append(np.nan)
                sell_price.append(np.nan)
                di_signal.append(0)
        elif di[i-4] > 0 and di[i-3] > 0 and di[i-2] > 0 and di[i-1] > 0 and di[i] < 0:
            if signal != -1:
                buy_price.append(np.nan)
                sell_price.append(prices[i])
                signal = -1
                di_signal.append(signal)
            else:
                buy_price.append(np.nan)
                sell_price.append(np.nan)
                di_signal.append(0)
        else:
            buy_price.append(np.nan)
            sell_price.append(np.nan)
            di_signal.append(0)
            
    return buy_price, sell_price, di_signal

buy_price, sell_price, di_signal = implement_di_strategy(aapl['close'], aapl['di_14'])

# DISPARITY INDEX TRADING SIGNALS PLOT

ax1 = plt.subplot2grid((11,1), (0,0), rowspan = 5, colspan = 1)
ax2 = plt.subplot2grid((11,1), (6,0), rowspan = 5, colspan = 1)
ax1.plot(aapl['close'], linewidth = 2, color = '#1976d2')
ax1.plot(aapl.index, buy_price, marker = '^', markersize = 12, linewidth = 0, label = 'BUY SIGNAL', color = 'green')
ax1.plot(aapl.index, sell_price, marker = 'v', markersize = 12, linewidth = 0, label = 'SELL SIGNAL', color = 'r')
ax1.legend()
ax1.set_title('AAPL CLOSING PRICES')
for i in range(len(aapl)):
    if aapl.iloc[i, 5] >= 0:
        ax2.bar(aapl.iloc[i].name, aapl.iloc[i, 5], color = '#26a69a')
    else:    
        ax2.bar(aapl.iloc[i].name, aapl.iloc[i, 5], color = '#ef5350')
ax2.set_title('AAPL DISPARITY INDEX 14')
plt.show()

# STOCK POSITION

position = []
for i in range(len(di_signal)):
    if di_signal[i] > 1:
        position.append(0)
    else:
        position.append(1)
        
for i in range(len(aapl['close'])):
    if di_signal[i] == 1:
        position[i] = 1
    elif di_signal[i] == -1:
        position[i] = 0
    else:
        position[i] = position[i-1]
        
close_price = aapl['close']
di = aapl['di_14']
di_signal = pd.DataFrame(di_signal).rename(columns = {0:'di_signal'}).set_index(aapl.index)
position = pd.DataFrame(position).rename(columns = {0:'di_position'}).set_index(aapl.index)

frames = [close_price, di, di_signal, position]
strategy = pd.concat(frames, join = 'inner', axis = 1)

strategy.head()

rets = aapl.close.pct_change().dropna()
strat_rets = strategy.di_position[1:]*rets

plt.title('Daily Returns')
rets.plot(color = 'blue', alpha = 0.3, linewidth = 7)
strat_rets.plot(color = 'r', linewidth = 1)
plt.show()

rets_cum = (1 + rets).cumprod() - 1 
strat_cum = (1 + strat_rets).cumprod() - 1

plt.title('Cumulative Returns')
rets_cum.plot(color = 'blue', alpha = 0.3, linewidth = 7)
strat_cum.plot(color = 'r', linewidth = 2)
plt.show()
