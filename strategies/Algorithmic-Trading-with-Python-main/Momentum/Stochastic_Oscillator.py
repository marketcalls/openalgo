import pandas as pd
import numpy as np
import requests
from termcolor import colored as cl
from math import floor
import matplotlib.pyplot as plt

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

def get_stoch(symbol, k_period, d_period, start_date):
    api_key = open(r'api_key.txt')
    url = f'https://www.alphavantage.co/query?function=STOCH&symbol={symbol}&interval=daily&fastkperiod={k_period}&slowdperiod={d_period}&apikey={api_key}'
    raw = requests.get(url).json()
    df = pd.DataFrame(raw['Technical Analysis: STOCH']).T.iloc[::-1]
    df = df[df.index >= start_date]
    df.index = pd.to_datetime(df.index)
    df = df.astype(float)
    return df['SlowK'], df['SlowD']

aapl['%k'], aapl['%d'] = get_stoch('aapl', 14, 3, '2020-01-01')
aapl = aapl.dropna()
aapl.head()

def plot_stoch(symbol, price, k, d):
    ax1 = plt.subplot2grid((9, 1), (0,0), rowspan = 5, colspan = 1)
    ax2 = plt.subplot2grid((9, 1), (6,0), rowspan = 3, colspan = 1)
    ax1.plot(price)
    ax1.set_title(f'{symbol} STOCK PRICE')
    ax2.plot(k, color = 'deepskyblue', linewidth = 1.5, label = '%K')
    ax2.plot(d, color = 'orange', linewidth = 1.5, label = '%D')
    ax2.axhline(80, color = 'black', linewidth = 1, linestyle = '--')
    ax2.axhline(20, color = 'black', linewidth = 1, linestyle = '--')
    ax2.set_title(f'{symbol} STOCH')
    ax2.legend()
    plt.show()
    
plot_stoch('aapl', aapl['close'], aapl['%k'], aapl['%d'])

def implement_stoch_strategy(prices, k, d):    
    buy_price = []
    sell_price = []
    stoch_signal = []
    signal = 0

    for i in range(len(prices)):
        if k[i] < 20 and d[i] < 20 and k[i] < d[i]:
            if signal != 1:
                buy_price.append(prices[i])
                sell_price.append(np.nan)
                signal = 1
                stoch_signal.append(signal)
            else:
                buy_price.append(np.nan)
                sell_price.append(np.nan)
                stoch_signal.append(0)
        elif k[i] > 80 and d[i] > 80 and k[i] > d[i]:
            if signal != -1:
                buy_price.append(np.nan)
                sell_price.append(prices[i])
                signal = -1
                stoch_signal.append(signal)
            else:
                buy_price.append(np.nan)
                sell_price.append(np.nan)
                stoch_signal.append(0)
        else:
            buy_price.append(np.nan)
            sell_price.append(np.nan)
            stoch_signal.append(0)
            
    return buy_price, sell_price, stoch_signal
            
buy_price, sell_price, stoch_signal = implement_stoch_strategy(aapl['close'], aapl['%k'], aapl['%d'])

ax1 = plt.subplot2grid((9, 1), (0,0), rowspan = 5, colspan = 1)
ax2 = plt.subplot2grid((9, 1), (6,0), rowspan = 3, colspan = 1)
ax1.plot(aapl['close'], color = 'skyblue', label = 'aapl')
ax1.plot(aapl.index, buy_price, marker = '^', color = 'green', markersize = 10, label = 'BUY SIGNAL', linewidth = 0)
ax1.plot(aapl.index, sell_price, marker = 'v', color = 'r', markersize = 10, label = 'SELL SIGNAL', linewidth = 0)
ax1.legend(loc = 'upper left')
ax1.set_title('aapl STOCK PRICE')
ax2.plot(aapl['%k'], color = 'deepskyblue', linewidth = 1.5, label = '%K')
ax2.plot(aapl['%d'], color = 'orange', linewidth = 1.5, label = '%D')
ax2.axhline(80, color = 'black', linewidth = 1, linestyle = '--')
ax2.axhline(20, color = 'black', linewidth = 1, linestyle = '--')
ax2.set_title('aapl STOCH')
ax2.legend()
plt.show()

position = []
for i in range(len(stoch_signal)):
    if stoch_signal[i] > 1:
        position.append(0)
    else:
        position.append(1)
        
for i in range(len(aapl['close'])):
    if stoch_signal[i] == 1:
        position[i] = 1
    elif stoch_signal[i] == -1:
        position[i] = 0
    else:
        position[i] = position[i-1]
        
k = aapl['%k']
d = aapl['%d']
close_price = aapl['close']
stoch_signal = pd.DataFrame(stoch_signal).rename(columns = {0:'stoch_signal'}).set_index(aapl.index)
position = pd.DataFrame(position).rename(columns = {0:'stoch_position'}).set_index(aapl.index)

frames = [close_price, k, d, stoch_signal, position]
strategy = pd.concat(frames, join = 'inner', axis = 1)

strategy.tail()

rets = aapl.close.pct_change().dropna()
strat_rets = strategy.stoch_position[1:]*rets

plt.title('Daily Returns')
rets.plot(color = 'blue', alpha = 0.3, linewidth = 7)
strat_rets.plot(color = 'r', linewidth = 1)
plt.show()
