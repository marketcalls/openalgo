import pandas as pd
import numpy as np
import requests
import matplotlib.pyplot as plt
from math import floor
from termcolor import colored as cl

plt.style.use('fivethirtyeight')
plt.rcParams['figure.figsize'] = (20, 10)

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

def get_aroon(symbol, lookback, start_date):
    api_key = 'YOUR API KEY'
    api_url = f'https://api.twelvedata.com/aroon?symbol={symbol}&interval=1day&time_period={lookback}&outputsize=5000&apikey={api_key}'
    raw_df = requests.get(api_url).json()
    df = pd.DataFrame(raw_df['values']).iloc[::-1].set_index('datetime').astype(float)
    df = df[df.index >= start_date]
    df.index = pd.to_datetime(df.index)
    aroon_up = df['aroon_up']
    aroon_down = df['aroon_down']
    return aroon_up, aroon_down

aapl['aroon_up'], aapl['aroon_down'] = get_aroon('aapl', 25, '2020-01-01')
aapl.tail()

ax1 = plt.subplot2grid((11,1), (0,0), rowspan = 5, colspan = 1)
ax2 = plt.subplot2grid((11,1), (6,0), rowspan = 4, colspan = 1)
ax1.plot(aapl['close'], linewidth = 2.5, color = '#2196f3')
ax1.set_title('aapl CLOSE PRICES')
ax2.plot(aapl['aroon_up'], color = '#26a69a', linewidth = 2, label = 'AROON UP')
ax2.plot(aapl['aroon_down'], color = '#ef5350', linewidth = 2, label = 'AROON DOWN')
ax2.legend()
ax2.set_title('aapl AROON 25')
plt.show()

def implement_aroon_strategy(prices, up, down):
    buy_price = []
    sell_price = []
    aroon_signal = []
    signal = 0
    
    for i in range(len(prices)):
        if up[i] >= 70 and down[i] <= 30:
            if signal != 1:
                buy_price.append(prices[i])
                sell_price.append(np.nan)
                signal = 1
                aroon_signal.append(signal)
            else:
                buy_price.append(np.nan)
                sell_price.append(np.nan)
                aroon_signal.append(0)
        elif up[i] <= 30 and down[i] >= 70:
            if signal != -1:
                buy_price.append(np.nan)
                sell_price.append(prices[i])
                signal = -1
                aroon_signal.append(signal)
            else:
                buy_price.append(np.nan)
                sell_price.append(np.nan)
                aroon_signal.append(0)
        else:
            buy_price.append(np.nan)
            sell_price.append(np.nan)
            aroon_signal.append(0)
            
    return buy_price, sell_price, aroon_signal

buy_price, sell_price, aroon_signal = implement_aroon_strategy(aapl['close'], aapl['aroon_up'], aapl['aroon_down'])

ax1 = plt.subplot2grid((11,1), (0,0), rowspan = 5, colspan = 1)
ax2 = plt.subplot2grid((11,1), (6,0), rowspan = 4, colspan = 1)
ax1.plot(aapl['close'], linewidth = 2.5, color = '#2196f3')
ax1.plot(aapl.index, buy_price, marker = '^', color = '#26a69a', markersize = 12)
ax1.plot(aapl.index, sell_price, marker = 'v', color = '#ef5350', markersize = 12)
ax1.set_title('aapl CLOSE PRICES')
ax2.plot(aapl['aroon_up'], color = '#26a69a', linewidth = 2, label = 'AROON UP')
ax2.plot(aapl['aroon_down'], color = '#ef5350', linewidth = 2, label = 'AROON DOWN')
ax2.legend()
ax2.set_title('aapl AROON 25')
plt.show()

position = []
for i in range(len(aroon_signal)):
    if aroon_signal[i] > 1:
        position.append(0)
    else:
        position.append(1)
        
for i in range(len(aapl['close'])):
    if aroon_signal[i] == 1:
        position[i] = 1
    elif aroon_signal[i] == -1:
        position[i] = 0
    else:
        position[i] = position[i-1]
        
aroon_up = aapl['aroon_up']
aroon_down = aapl['aroon_down']
close_price = aapl['close']
aroon_signal = pd.DataFrame(aroon_signal).rename(columns = {0:'aroon_signal'}).set_index(aapl.index)
position = pd.DataFrame(position).rename(columns = {0:'aroon_position'}).set_index(aapl.index)

frames = [close_price, aroon_up, aroon_down, aroon_signal, position]
strategy = pd.concat(frames, join = 'inner', axis = 1)

strategy.head()

rets = aapl.close.pct_change().dropna()
strat_rets = strategy.aroon_position[1:]*rets

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
