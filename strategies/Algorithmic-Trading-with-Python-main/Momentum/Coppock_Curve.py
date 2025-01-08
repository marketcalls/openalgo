# IMPORTING PACKAGES

import requests
import numpy as np
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

aapl = get_historical_data('AAPL', '2020-01-01')
aapl.tail()

# COPPOCK CURVE CALCULATION

def wma(data, lookback):
    weights = np.arange(1, lookback + 1)
    val = data.rolling(lookback)
    wma = val.apply(lambda prices: np.dot(prices, weights) / weights.sum(), raw = True)
    return wma

def get_roc(close, n):
    difference = close.diff(n)
    nprev_values = close.shift(n)
    roc = (difference / nprev_values) * 100
    return roc

def get_cc(data, roc1_n, roc2_n, wma_lookback):
    longROC = get_roc(data, roc1_n)
    shortROC = get_roc(data, roc2_n)
    ROC = longROC + shortROC
    cc = wma(ROC, wma_lookback)
    return cc

aapl['cc'] = get_cc(aapl['close'], 14, 11, 10)
aapl = aapl.dropna()
aapl.tail()

# COPPOCK CURVE PLOT

ax1 = plt.subplot2grid((11,1), (0,0), rowspan = 5, colspan = 1)
ax2 = plt.subplot2grid((11,1), (6,0), rowspan = 6, colspan = 1)
ax1.plot(aapl['close'], linewidth = 2.5)
ax1.set_title('AAPL CLOSING PRICES')
for i in range(len(aapl)):
    if aapl.iloc[i, 5] >= 0:
        ax2.bar(aapl.iloc[i].name, aapl.iloc[i, 5], color = '#009688')
    else:    
        ax2.bar(aapl.iloc[i].name, aapl.iloc[i, 5], color = '#f44336')
ax2.set_title('AAPL COPPOCK CURVE')
plt.show()

# COPPOCK CURVE STRATEGY

def implement_cc_strategy(prices, cc):
    buy_price = []
    sell_price = []
    cc_signal = []
    signal = 0
    
    for i in range(len(prices)):
        if cc[i-4] < 0 and cc[i-3] < 0 and cc[i-2] < 0 and cc[i-1] < 0 and cc[i] > 0:
            if signal != 1:
                buy_price.append(prices[i])
                sell_price.append(np.nan)
                signal = 1
                cc_signal.append(signal)
            else:
                buy_price.append(np.nan)
                sell_price.append(np.nan)
                cc_signal.append(0)
        elif cc[i-4] > 0 and cc[i-3] > 0 and cc[i-2] > 0 and cc[i-1] > 0 and cc[i] < 0:
            if signal != -1:
                buy_price.append(np.nan)
                sell_price.append(prices[i])
                signal = -1
                cc_signal.append(signal)
            else:
                buy_price.append(np.nan)
                sell_price.append(np.nan)
                cc_signal.append(0)
        else:
            buy_price.append(np.nan)
            sell_price.append(np.nan)
            cc_signal.append(0)
            
    return buy_price, sell_price, cc_signal

buy_price, sell_price, cc_signal = implement_cc_strategy(aapl['close'], aapl['cc'])

# COPPOCK CURVE TRADING SIGNAL PLOT

ax1 = plt.subplot2grid((11,1), (0,0), rowspan = 5, colspan = 1)
ax2 = plt.subplot2grid((11,1), (6,0), rowspan = 6, colspan = 1)
ax1.plot(aapl['close'], linewidth = 2, label = 'AAPL')
ax1.plot(aapl.index, buy_price, marker = '^', color = 'green', markersize = 12, linewidth = 0, label = 'BUY SIGNAL')
ax1.plot(aapl.index, sell_price, marker = 'v', color = 'r', markersize = 12, linewidth = 0, label = 'SELL SIGNAL')
ax1.legend()
ax1.set_title('AAPL CC TRADING SIGNALS')
for i in range(len(aapl)):
    if aapl.iloc[i, 5] >= 0:
        ax2.bar(aapl.iloc[i].name, aapl.iloc[i, 5], color = '#009688')
    else:    
        ax2.bar(aapl.iloc[i].name, aapl.iloc[i, 5], color = '#f44336')
ax2.set_title('AAPL COPPOCK CURVE')
plt.show()

# STOCK POSITION

position = []
for i in range(len(cc_signal)):
    if cc_signal[i] > 1:
        position.append(0)
    else:
        position.append(1)
        
for i in range(len(aapl['close'])):
    if cc_signal[i] == 1:
        position[i] = 1
    elif cc_signal[i] == -1:
        position[i] = 0
    else:
        position[i] = position[i-1]
        
close_price = aapl['close']
cc = aapl['cc']
cc_signal = pd.DataFrame(cc_signal).rename(columns = {0:'cc_signal'}).set_index(aapl.index)
position = pd.DataFrame(position).rename(columns = {0:'cc_position'}).set_index(aapl.index)

frames = [close_price, cc, cc_signal, position]
strategy = pd.concat(frames, join = 'inner', axis = 1)

strategy

rets = aapl.close.pct_change().dropna()
strat_rets = strategy.cc_position[1:]*rets

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
