import pandas as pd 
import matplotlib.pyplot as plt 
import requests
import math
from termcolor import colored as cl 
import numpy as np

plt.style.use('fivethirtyeight')
plt.rcParams['figure.figsize'] = (20, 10)

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

def sma(data, n):
    sma = data.rolling(window = n).mean()
    return pd.DataFrame(sma)

n = [20, 50]
for i in n:
    aapl[f'sma_{i}'] = sma(aapl['close'], i)
    
aapl.tail()

plt.plot(aapl['close'], label = 'aapl', linewidth = 5, alpha = 0.3)
plt.plot(aapl['sma_20'], label = 'SMA 20')
plt.plot(aapl['sma_50'], label = 'SMA 50')
plt.title('aapl Simple Moving Averages (20, 50)')
plt.legend(loc = 'upper left')
plt.show()

def implement_sma_strategy(data, short_window, long_window):
    sma1 = short_window
    sma2 = long_window
    buy_price = []
    sell_price = []
    sma_signal = []
    signal = 0
    
    for i in range(len(data)):
        if sma1[i] > sma2[i]:
            if signal != 1:
                buy_price.append(data[i])
                sell_price.append(np.nan)
                signal = 1
                sma_signal.append(signal)
            else:
                buy_price.append(np.nan)
                sell_price.append(np.nan)
                sma_signal.append(0)
        elif sma2[i] > sma1[i]:
            if signal != -1:
                buy_price.append(np.nan)
                sell_price.append(data[i])
                signal = -1
                sma_signal.append(-1)
            else:
                buy_price.append(np.nan)
                sell_price.append(np.nan)
                sma_signal.append(0)
        else:
            buy_price.append(np.nan)
            sell_price.append(np.nan)
            sma_signal.append(0)
            
    return buy_price, sell_price, sma_signal

sma_20 = aapl['sma_20']
sma_50 = aapl['sma_50']

buy_price, sell_price, signal = implement_sma_strategy(aapl['close'], sma_20, sma_50)

plt.plot(aapl['close'], alpha = 0.3, label = 'aapl')
plt.plot(sma_20, alpha = 0.6, label = 'SMA 20')
plt.plot(sma_50, alpha = 0.6, label = 'SMA 50')
plt.scatter(aapl.index, buy_price, marker = '^', s = 200, color = 'darkblue', label = 'BUY SIGNAL')
plt.scatter(aapl.index, sell_price, marker = 'v', s = 200, color = 'crimson', label = 'SELL SIGNAL')
plt.legend(loc = 'upper left')
plt.title('aapl SMA CROSSOVER TRADING SIGNALS')
plt.show()

position = []
for i in range(len(signal)):
    if signal[i] > 1:
        position.append(0)
    else:
        position.append(1)
        
for i in range(len(aapl['close'])):
    if signal[i] == 1:
        position[i] = 1
    elif signal[i] == -1:
        position[i] = 0
    else:
        position[i] = position[i-1]
        
sma_20 = pd.DataFrame(sma_20).rename(columns = {0:'sma_20'})
sma_50 = pd.DataFrame(sma_50).rename(columns = {0:'sma_50'}) 
signal = pd.DataFrame(signal).rename(columns = {0:'sma_signal'}).set_index(aapl.index)
position = pd.DataFrame(position).rename(columns = {0:'sma_position'}).set_index(aapl.index)

frames = [sma_20, sma_50, signal, position]
strategy = pd.concat(frames, join = 'inner', axis = 1)

strategy

rets = aapl.close.pct_change().dropna()
strat_rets = strategy.sma_position[1:]*rets

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
