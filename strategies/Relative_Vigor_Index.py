# IMPORTING PACKAGES

import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
import requests
from termcolor import colored as cl
from math import floor

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

aapl = get_historical_data('AAPL', '2019-01-01')
aapl.tail()

# RELATIVE VIGOR INDEX CALCULATION

def get_rvi(open, high, low, close, lookback):
    a = close - open
    b = 2 * (close.shift(2) - open.shift(2))
    c = 2 * (close.shift(3) - open.shift(3))
    d = close.shift(4) - open.shift(4)
    numerator = a + b + c + d
    
    e = high - low
    f = 2 * (high.shift(2) - low.shift(2))
    g = 2 * (high.shift(3) - low.shift(3))
    h = high.shift(4) - low.shift(4)
    denominator = e + f + g + h
    
    numerator_sum = numerator.rolling(4).sum()
    denominator_sum = denominator.rolling(4).sum()
    rvi = (numerator_sum / denominator_sum).rolling(lookback).mean()
    
    rvi1 = 2 * rvi.shift(1)
    rvi2 = 2 * rvi.shift(2)
    rvi3 = rvi.shift(3)
    rvi_signal = (rvi + rvi1 + rvi2 + rvi3) / 6
    
    return rvi, rvi_signal

aapl['rvi'], aapl['signal_line'] = get_rvi(aapl['open'], aapl['high'], aapl['low'], aapl['close'], 10)
aapl = aapl.dropna()
aapl = aapl[aapl.index >= '2020-01-01']
aapl.tail()

# RELATIVE VIGOR INDEX PLOT

ax1 = plt.subplot2grid((11,1), (0,0), rowspan = 5, colspan = 1)
ax2 = plt.subplot2grid((11,1), (6,0), rowspan = 5, colspan = 1)
ax1.plot(aapl['close'], linewidth = 2.5)
ax1.set_title('AAPL CLOSING PRICES')
ax2.plot(aapl['rvi'], linewidth = 2, color = 'orange', label = 'RVI LINE')
ax2.plot(aapl['signal_line'], linewidth = 2, color = '#BA5FE3', label = 'SIGNAL LINE')
ax2.legend()
ax2.set_title('AAPL RVI 10')
plt.show()

# RELATIVE VIGOR INDEX STRATEGY

def implement_rvi_strategy(prices, rvi, signal_line):
    buy_price = []
    sell_price = []
    rvi_signal = []
    signal = 0
    
    for i in range(len(prices)):
        if rvi[i-1] < signal_line[i-1] and rvi[i] > signal_line[i]:
            if signal != 1:
                buy_price.append(prices[i])
                sell_price.append(np.nan)
                signal = 1
                rvi_signal.append(signal)
            else:
                buy_price.append(np.nan)
                sell_price.append(np.nan)
                rvi_signal.append(0)
        elif rvi[i-1] > signal_line[i-1] and rvi[i] < signal_line[i]:
            if signal != -1:
                buy_price.append(np.nan)
                sell_price.append(prices[i])
                signal = -1
                rvi_signal.append(signal)
            else:
                buy_price.append(np.nan)
                sell_price.append(np.nan)
                rvi_signal.append(0)
        else:
            buy_price.append(np.nan)
            sell_price.append(np.nan)
            rvi_signal.append(0)
            
    return buy_price, sell_price, rvi_signal

buy_price, sell_price, rvi_signal = implement_rvi_strategy(aapl['close'], aapl['rvi'], aapl['signal_line'])

# RELATIVE VIGOR INDEX TRADING SIGNALS PLOT

ax1 = plt.subplot2grid((11,1), (0,0), rowspan = 5, colspan = 1)
ax2 = plt.subplot2grid((11,1), (6,0), rowspan = 5, colspan = 1)
ax1.plot(aapl['close'], linewidth = 2)
ax1.plot(aapl.index, buy_price, marker = '^', markersize = 12, color = 'green', linewidth = 0, label = 'BUY SIGNAL')
ax1.plot(aapl.index, sell_price, marker = 'v', markersize = 12, color = 'r', linewidth = 0, label = 'SELL SIGNAL')
ax1.legend()
ax1.set_title('AAPL RVI TRADING SIGNALS')
ax2.plot(aapl['rvi'], linewidth = 2, color = 'orange', label = 'RVI LINE')
ax2.plot(aapl['signal_line'], linewidth = 2, color = '#BA5FE3', label = 'SIGNAL LINE')
ax2.set_title('AAPL RVI 10')
ax2.legend()
plt.show()

# STOCK POSITION

position = []
for i in range(len(rvi_signal)):
    if rvi_signal[i] > 1:
        position.append(0)
    else:
        position.append(1)
        
for i in range(len(aapl['close'])):
    if rvi_signal[i] == 1:
        position[i] = 1
    elif rvi_signal[i] == -1:
        position[i] = 0
    else:
        position[i] = position[i-1]
        
close_price = aapl['close']
rvi = aapl['rvi']
signal_line = aapl['signal_line']
rvi_signal = pd.DataFrame(rvi_signal).rename(columns = {0:'rvi_signal'}).set_index(aapl.index)
position = pd.DataFrame(position).rename(columns = {0:'rvi_position'}).set_index(aapl.index)

frames = [close_price, rvi, signal_line, rvi_signal, position]
strategy = pd.concat(frames, join = 'inner', axis = 1)

strategy

rets = aapl.close.pct_change().dropna()
strat_rets = strategy.rvi_position[1:]*rets

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
