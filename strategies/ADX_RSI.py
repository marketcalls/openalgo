# IMPORTING PACKAGES

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import requests
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

aapl = get_historical_data('AAPL', '2010-01-01')
aapl.tail()

# ADX CALCULATION

def get_adx(high, low, close, lookback):
    plus_dm = high.diff()
    minus_dm = low.diff()
    plus_dm[plus_dm < 0] = 0
    minus_dm[minus_dm > 0] = 0
    
    tr1 = pd.DataFrame(high - low)
    tr2 = pd.DataFrame(abs(high - close.shift(1)))
    tr3 = pd.DataFrame(abs(low - close.shift(1)))
    frames = [tr1, tr2, tr3]
    tr = pd.concat(frames, axis = 1, join = 'inner').max(axis = 1)
    atr = tr.rolling(lookback).mean()
    
    plus_di = 100 * (plus_dm.ewm(alpha = 1/lookback).mean() / atr)
    minus_di = abs(100 * (minus_dm.ewm(alpha = 1/lookback).mean() / atr))
    dx = (abs(plus_di - minus_di) / abs(plus_di + minus_di)) * 100
    adx = ((dx.shift(1) * (lookback - 1)) + dx) / lookback
    adx_smooth = adx.ewm(alpha = 1/lookback).mean()
    return plus_di, minus_di, adx_smooth

aapl['plus_di'] = pd.DataFrame(get_adx(aapl['high'], aapl['low'], aapl['close'], 14)[0]).rename(columns = {0:'plus_di'})
aapl['minus_di'] = pd.DataFrame(get_adx(aapl['high'], aapl['low'], aapl['close'], 14)[1]).rename(columns = {0:'minus_di'})
aapl['adx'] = pd.DataFrame(get_adx(aapl['high'], aapl['low'], aapl['close'], 14)[2]).rename(columns = {0:'adx'})
aapl = aapl.dropna()
aapl.tail()

# ADX PLOT

plot_data = aapl[aapl.index >= '2020-01-01']

ax1 = plt.subplot2grid((11,1), (0,0), rowspan = 5, colspan = 1)
ax2 = plt.subplot2grid((11,1), (6,0), rowspan = 5, colspan = 1)
ax1.plot(plot_data['close'], linewidth = 2, color = '#ff9800')
ax1.set_title('AAPL CLOSING PRICE')
ax2.plot(plot_data['plus_di'], color = '#26a69a', label = '+ DI 14', linewidth = 3, alpha = 0.3)
ax2.plot(plot_data['minus_di'], color = '#f44336', label = '- DI 14', linewidth = 3, alpha = 0.3)
ax2.plot(plot_data['adx'], color = '#2196f3', label = 'ADX 14', linewidth = 3)
ax2.axhline(35, color = 'grey', linewidth = 2, linestyle = '--')
ax2.legend()
ax2.set_title('AAPL ADX 14')
plt.show()

# RSI CALCULATION

def get_rsi(close, lookback):
    ret = close.diff()
    up = []
    down = []
    
    for i in range(len(ret)):
        if ret[i] < 0:
            up.append(0)
            down.append(ret[i])
        else:
            up.append(ret[i])
            down.append(0)
    
    up_series = pd.Series(up)
    down_series = pd.Series(down).abs()
    
    up_ewm = up_series.ewm(com = lookback - 1, adjust = False).mean()
    down_ewm = down_series.ewm(com = lookback - 1, adjust = False).mean()
    
    rs = up_ewm/down_ewm
    rsi = 100 - (100 / (1 + rs))
    rsi_df = pd.DataFrame(rsi).rename(columns = {0:'rsi'}).set_index(close.index)
    rsi_df = rsi_df.dropna()
    
    return rsi_df[3:]

aapl['rsi_14'] = get_rsi(aapl['close'], 14)
aapl = aapl.dropna()
aapl.tail()

# RSI PLOT

plot_data = aapl[aapl.index >= '2020-01-01']

ax1 = plt.subplot2grid((11,1), (0,0), rowspan = 5, colspan = 1)
ax2 = plt.subplot2grid((11,1), (6,0), rowspan = 5, colspan = 1)
ax1.plot(plot_data['close'], linewidth = 2.5)
ax1.set_title('AAPL STOCK PRICES')
ax2.plot(plot_data['rsi_14'], color = 'orange', linewidth = 2.5)
ax2.axhline(30, linestyle = '--', linewidth = 1.5, color = 'grey')
ax2.axhline(70, linestyle = '--', linewidth = 1.5, color = 'grey')
ax2.set_title('AAPL RSI 14')
plt.show()

# RSI ADX PLOT

plot_data = aapl[aapl.index >= '2020-01-01']

ax1 = plt.subplot2grid((19,1), (0,0), rowspan = 5, colspan = 1)
ax2 = plt.subplot2grid((19,1), (7,0), rowspan = 5, colspan = 1)
ax3 = plt.subplot2grid((19,1), (14,0), rowspan = 5, colspan = 1)

ax1.plot(plot_data['close'], linewidth = 2.5)
ax1.set_title('AAPL STOCK PRICES')

ax2.plot(plot_data['rsi_14'], color = 'orange', linewidth = 2.5)
ax2.axhline(30, linestyle = '--', linewidth = 1.5, color = 'grey')
ax2.axhline(70, linestyle = '--', linewidth = 1.5, color = 'grey')
ax2.set_title('AAPL RSI 14')

ax3.plot(plot_data['plus_di'], color = '#26a69a', label = '+ DI 14', linewidth = 3, alpha = 0.3)
ax3.plot(plot_data['minus_di'], color = '#f44336', label = '- DI 14', linewidth = 3, alpha = 0.3)
ax3.plot(plot_data['adx'], color = '#2196f3', label = 'ADX 14', linewidth = 3)
ax3.axhline(35, color = 'grey', linewidth = 2, linestyle = '--')
ax3.legend()
ax3.set_title('AAPL ADX 14')
plt.show()

# TRADING STRATEGY

def adx_rsi_strategy(prices, adx, pdi, ndi, rsi):
    buy_price = []
    sell_price = []
    adx_rsi_signal = []
    signal = 0
    
    for i in range(len(prices)):
        if adx[i] > 35 and pdi[i] < ndi[i] and rsi[i] < 50:
            if signal != 1:
                buy_price.append(prices[i])
                sell_price.append(np.nan)
                signal = 1
                adx_rsi_signal.append(signal)
            else:
                buy_price.append(np.nan)
                sell_price.append(np.nan)
                adx_rsi_signal.append(0)
                
        elif adx[i] > 35 and pdi[i] > ndi[i] and rsi[i] > 50:
            if signal != -1:
                buy_price.append(np.nan)
                sell_price.append(prices[i])
                signal = -1
                adx_rsi_signal.append(signal)
            else:
                buy_price.append(np.nan)
                sell_price.append(np.nan)
                adx_rsi_signal.append(0)
        else:
            buy_price.append(np.nan)
            sell_price.append(np.nan)
            adx_rsi_signal.append(0)
                        
    return buy_price, sell_price, adx_rsi_signal

buy_price, sell_price, adx_rsi_signal = adx_rsi_strategy(aapl['close'], aapl['adx'], aapl['plus_di'], aapl['minus_di'], aapl['rsi_14'])

# POSITION

position = []
for i in range(len(adx_rsi_signal)):
    if adx_rsi_signal[i] > 1:
        position.append(1)
    else:
        position.append(0)
        
for i in range(len(aapl['close'])):
    if adx_rsi_signal[i] == 1:
        position[i] = 1
    elif adx_rsi_signal[i] == -1:
        position[i] = 0
    else:
        position[i] = position[i-1]
        

adx = aapl['adx']
pdi = aapl['plus_di']
ndi = aapl['minus_di']
rsi = aapl['rsi_14'] 
close_price = aapl['close']
adx_rsi_signal = pd.DataFrame(adx_rsi_signal).rename(columns = {0:'adx_rsi_signal'}).set_index(aapl.index)
position = pd.DataFrame(position).rename(columns = {0:'adx_rsi_position'}).set_index(aapl.index)

frames = [close_price, adx, pdi, ndi, rsi, adx_rsi_signal, position]
strategy = pd.concat(frames, join = 'inner', axis = 1)

strategy

rets = aapl.close.pct_change().dropna()
strat_rets = strategy.adx_rsi_position[1:]*rets

plt.title('Daily Returns')
rets.plot(color = 'blue', alpha = 0.3, linewidth = 7)
strat_rets.plot(color = 'r', linewidth = 1)
plt.show()
