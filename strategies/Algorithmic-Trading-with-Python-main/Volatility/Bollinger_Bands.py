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

plt.plot(aapl.index, aapl['close'])
plt.xlabel('Date')
plt.ylabel('Closing Prices')
plt.title('aapl Stock Prices 2020-2021')
plt.show()

def sma(data, window):
    sma = data.rolling(window = window).mean()
    return sma

aapl['sma_20'] = sma(aapl['close'], 20)
aapl.tail(3)

aapl['close'].plot(label = 'CLOSE', alpha = 0.6)
aapl['sma_20'].plot(label = 'SMA 20', linewidth = 2)
plt.xlabel('Date')
plt.ylabel('Closing Prices')
plt.legend(loc = 'upper left')
plt.show()

def bb(data, sma, window):
    std = data.rolling(window = window).std()
    upper_bb = sma + std * 2
    lower_bb = sma - std * 2
    return upper_bb, lower_bb

aapl['upper_bb'], aapl['lower_bb'] = bb(aapl['close'], aapl['sma_20'], 20)
aapl.tail()

aapl['close'].plot(label = 'CLOSE PRICES', color = 'skyblue')
aapl['upper_bb'].plot(label = 'UPPER BB 20', linestyle = '--', linewidth = 1, color = 'black')
aapl['sma_20'].plot(label = 'MIDDLE BB 20', linestyle = '--', linewidth = 1.2, color = 'grey')
aapl['lower_bb'].plot(label = 'LOWER BB 20', linestyle = '--', linewidth = 1, color = 'black')
plt.legend(loc = 'upper left')
plt.title('aapl BOLLINGER BANDS')
plt.show()

def implement_bb_strategy(data, lower_bb, upper_bb):
    buy_price = []
    sell_price = []
    bb_signal = []
    signal = 0
    
    for i in range(len(data)):
        if data[i-1] > lower_bb[i-1] and data[i] < lower_bb[i]:
            if signal != 1:
                buy_price.append(data[i])
                sell_price.append(np.nan)
                signal = 1
                bb_signal.append(signal)
            else:
                buy_price.append(np.nan)
                sell_price.append(np.nan)
                bb_signal.append(0)
        elif data[i-1] < upper_bb[i-1] and data[i] > upper_bb[i]:
            if signal != -1:
                buy_price.append(np.nan)
                sell_price.append(data[i])
                signal = -1
                bb_signal.append(signal)
            else:
                buy_price.append(np.nan)
                sell_price.append(np.nan)
                bb_signal.append(0)
        else:
            buy_price.append(np.nan)
            sell_price.append(np.nan)
            bb_signal.append(0)
            
    return buy_price, sell_price, bb_signal

buy_price, sell_price, bb_signal = implement_bb_strategy(aapl['close'], aapl['lower_bb'], aapl['upper_bb'])

aapl['close'].plot(label = 'CLOSE PRICES', alpha = 0.3)
aapl['upper_bb'].plot(label = 'UPPER BB', linestyle = '--', linewidth = 1, color = 'black')
aapl['sma_20'].plot(label = 'MIDDLE BB', linestyle = '--', linewidth = 1.2, color = 'grey')
aapl['lower_bb'].plot(label = 'LOWER BB', linestyle = '--', linewidth = 1, color = 'black')
plt.scatter(aapl.index, buy_price, marker = '^', color = 'green', label = 'BUY', s = 200)
plt.scatter(aapl.index, sell_price, marker = 'v', color = 'red', label = 'SELL', s = 200)
plt.title('aapl BB STRATEGY TRADING SIGNALS')
plt.legend(loc = 'upper left')
plt.show()

position = []
for i in range(len(bb_signal)):
    if bb_signal[i] > 1:
        position.append(0)
    else:
        position.append(1)
        
for i in range(len(aapl['close'])):
    if bb_signal[i] == 1:
        position[i] = 1
    elif bb_signal[i] == -1:
        position[i] = 0
    else:
        position[i] = position[i-1]
        
upper_bb = aapl['upper_bb']
lower_bb = aapl['lower_bb']
close_price = aapl['close']
bb_signal = pd.DataFrame(bb_signal).rename(columns = {0:'bb_signal'}).set_index(aapl.index)
position = pd.DataFrame(position).rename(columns = {0:'bb_position'}).set_index(aapl.index)

frames = [close_price, upper_bb, lower_bb, bb_signal, position]
strategy = pd.concat(frames, join = 'inner', axis = 1)

strategy.tail(10)

rets = aapl.close.pct_change().dropna()
strat_rets = strategy.bb_position[1:]*rets

plt.title('Daily Returns')
rets.plot(color = 'blue', alpha = 0.3, linewidth = 7)
strat_rets.plot(color = 'r', linewidth = 1)
plt.show()
