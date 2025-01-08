# IMPORTING PACKAGES

import pandas as pd
import numpy as np
import requests
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

aapl = get_historical_data('AAPL', '2019-01-01')
aapl

# ROC CALCULATION

def get_roc(close, n):
    difference = close.diff(n)
    nprev_values = close.shift(n)
    roc = (difference / nprev_values) * 100
    return roc
  
  # KST CALCULATION

def get_kst(close, sma1, sma2, sma3, sma4, roc1, roc2, roc3, roc4, signal):
    rcma1 = get_roc(close, roc1).rolling(sma1).mean()
    rcma2 = get_roc(close, roc2).rolling(sma2).mean()
    rcma3 = get_roc(close, roc3).rolling(sma3).mean()
    rcma4 = get_roc(close, roc4).rolling(sma4).mean()
    kst = (rcma1 * 1) + (rcma2 * 2) + (rcma3 * 3) + (rcma4 * 4)
    signal = kst.rolling(signal).mean()
    return kst, signal

aapl['kst'], aapl['signal_line'] = get_kst(aapl['close'], 10, 10, 10, 15, 10, 15, 20, 30, 9)
aapl = aapl[aapl.index >= '2020-01-01']
aapl.tail()

# KST INDICATOR PLOT

ax1 = plt.subplot2grid((11,1), (0,0), rowspan = 5, colspan = 1)
ax2 = plt.subplot2grid((11,1), (6,0), rowspan = 5, colspan = 1)
ax1.plot(aapl['close'], linewidth = 2.5)
ax1.set_title('aapl CLOSING PRICES')
ax2.plot(aapl['kst'], linewidth = 2, label = 'KST', color = 'orange')
ax2.plot(aapl['signal_line'], linewidth = 2, label = 'SIGNAL', color = 'mediumorchid')
ax2.legend()
ax2.set_title('aapl KST')
plt.show()

# KST CROSSOVER TRADING STRATEGY

def implement_kst_strategy(prices, kst_line, signal_line):
    buy_price = []
    sell_price = []
    kst_signal = []
    signal = 0
    
    for i in range(len(kst_line)):
        
        if kst_line[i-1] < signal_line[i-1] and kst_line[i] > signal_line[i]:
            if signal != 1:
                buy_price.append(prices[i])
                sell_price.append(np.nan)
                signal = 1
                kst_signal.append(signal)
            else:
                buy_price.append(np.nan)
                sell_price.append(np.nan)
                kst_signal.append(0)
                
        elif kst_line[i-1] > signal_line[i-1] and kst_line[i] < signal_line[i]:
            if signal != -1:
                buy_price.append(np.nan)
                sell_price.append(prices[i])
                signal = -1
                kst_signal.append(signal)
            else:
                buy_price.append(np.nan)
                sell_price.append(np.nan)
                kst_signal.append(0)
                
        else:
            buy_price.append(np.nan)
            sell_price.append(np.nan)
            kst_signal.append(0)
            
    return buy_price, sell_price, kst_signal

buy_price, sell_price, kst_signal = implement_kst_strategy(aapl['close'], aapl['kst'], aapl['signal_line'])

# TRADING SIGNALS PLOT

ax1 = plt.subplot2grid((11,1), (0,0), rowspan = 5, colspan = 1)
ax2 = plt.subplot2grid((11,1), (6,0), rowspan = 5, colspan = 1)
ax1.plot(aapl['close'], linewidth = 2, label = 'aapl')
ax1.plot(aapl.index, buy_price, marker = '^', markersize = 12, linewidth = 0, color = 'green', label = 'BUY SIGNAL')
ax1.plot(aapl.index, sell_price, marker = 'v', markersize = 12, linewidth = 0, color = 'r', label = 'SELL SIGNAL')
ax1.legend()
ax1.set_title('aapl KST TRADING SIGNALS')
ax2.plot(aapl['kst'], linewidth = 2, label = 'KST', color = 'orange')
ax2.plot(aapl['signal_line'], linewidth = 2, label = 'SIGNAL', color = 'mediumorchid')
ax2.legend()
ax2.set_title('aapl KST')
plt.show()

# STOCK POSITION

position = []
for i in range(len(kst_signal)):
    if kst_signal[i] > 1:
        position.append(0)
    else:
        position.append(1)
        
for i in range(len(aapl['close'])):
    if kst_signal[i] == 1:
        position[i] = 1
    elif kst_signal[i] == -1:
        position[i] = 0
    else:
        position[i] = position[i-1]
        
close_price = aapl['close']
kst = aapl['kst']
signal_line = aapl['signal_line']
kst_signal = pd.DataFrame(kst_signal).rename(columns = {0:'kst_signal'}).set_index(aapl.index)
position = pd.DataFrame(position).rename(columns = {0:'kst_position'}).set_index(aapl.index)

frames = [close_price, kst, signal_line, kst_signal, position]
strategy = pd.concat(frames, join = 'inner', axis = 1)

strategy

rets = aapl.close.pct_change().dropna()
strat_rets = strategy.kst_position[1:]*rets

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
