import pandas as pd
import requests
import matplotlib.pyplot as plt
import numpy as np

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

tsla = get_historical_data('TSLA', '2020-01-01')
tsla

def get_ci(high, low, close, lookback):
    tr1 = pd.DataFrame(high - low).rename(columns = {0:'tr1'})
    tr2 = pd.DataFrame(abs(high - close.shift(1))).rename(columns = {0:'tr2'})
    tr3 = pd.DataFrame(abs(low - close.shift(1))).rename(columns = {0:'tr3'})
    frames = [tr1, tr2, tr3]
    tr = pd.concat(frames, axis = 1, join = 'inner').dropna().max(axis = 1)
    atr = tr.rolling(1).mean()
    highh = high.rolling(lookback).max()
    lowl = low.rolling(lookback).min()
    ci = 100 * np.log10((atr.rolling(lookback).sum()) / (highh - lowl)) / np.log10(lookback)
    return ci

tsla['ci_14'] = get_ci(tsla['high'], tsla['low'], tsla['close'], 14)
tsla = tsla.dropna()
tsla

ax1 = plt.subplot2grid((11,1,), (0,0), rowspan = 5, colspan = 1)
ax2 = plt.subplot2grid((11,1,), (6,0), rowspan = 4, colspan = 1)
ax1.plot(tsla['close'], linewidth = 2.5, color = '#2196f3')
ax1.set_title('TSLA CLOSING PRICES')
ax2.plot(tsla['ci_14'], linewidth = 2.5, color = '#fb8c00')
ax2.axhline(38.2, linestyle = '--', linewidth = 1.5, color = 'grey')
ax2.axhline(61.8, linestyle = '--', linewidth = 1.5, color = 'grey')
ax2.set_title('TSLA CHOPPINESS INDEX 14')
plt.show()

def get_macd(price, slow, fast, smooth):
    exp1 = price.ewm(span = fast, adjust = False).mean()
    exp2 = price.ewm(span = slow, adjust = False).mean()
    macd = pd.DataFrame(exp1 - exp2).rename(columns = {'close':'macd'})
    signal = pd.DataFrame(macd.ewm(span = smooth, adjust = False).mean()).rename(columns = {'macd':'signal'})
    hist = pd.DataFrame(macd['macd'] - signal['signal']).rename(columns = {0:'hist'})
    frames =  [macd, signal, hist]
    df = pd.concat(frames, join = 'inner', axis = 1)
    return df

tsla_macd = get_macd(tsla['close'], 26, 12, 9)
tsla_macd.tail()

def implement_ci_macd_strategy(prices, data, ci):
    buy_price = []
    sell_price = []
    ci_macd_signal = []
    signal = 0
    
    for i in range(len(prices)):
        if data['macd'][i] > data['signal'][i] and ci[i] < 38.2:
            if signal != 1:
                buy_price.append(prices[i])
                sell_price.append(np.nan)
                signal = 1
                ci_macd_signal.append(signal)
            else:
                buy_price.append(np.nan)
                sell_price.append(np.nan)
                ci_macd_signal.append(0)
        elif data['macd'][i] < data['signal'][i] and ci[i] < 38.2:
            if signal != -1:
                buy_price.append(np.nan)
                sell_price.append(prices[i])
                signal = -1
                ci_macd_signal.append(signal)
            else:
                buy_price.append(np.nan)
                sell_price.append(np.nan)
                ci_macd_signal.append(0)
        else:
            buy_price.append(np.nan)
            sell_price.append(np.nan)
            ci_macd_signal.append(0)
    
    return buy_price, sell_price, ci_macd_signal

buy_price, sell_price, ci_macd_signal = implement_ci_macd_strategy(tsla['close'], tsla_macd, tsla['ci_14'])

ax1 = plt.subplot2grid((19,1,), (0,0), rowspan = 5, colspan = 1)
ax2 = plt.subplot2grid((19,1), (7,0), rowspan = 5, colspan = 1)
ax3 = plt.subplot2grid((19,1), (14,0), rowspan = 5, colspan = 1)
ax1.plot(tsla['close'], linewidth = 2.5, color = '#2196f3')
ax1.plot(tsla.index, buy_price, marker = '^', color = 'green', markersize = 12, label = 'BUY SIGNAL', linewidth = 0)
ax1.plot(tsla.index, sell_price, marker = 'v', color = 'r', markersize = 12, label = 'SELL SIGNAL', linewidth = 0)
ax1.legend()
ax1.set_title('tsla TRADING SIGNALS')
ax2.plot(tsla['ci_14'], linewidth = 2.5, color = '#fb8c00')
ax2.axhline(38.2, linestyle = '--', linewidth = 1.5, color = 'grey')
ax2.axhline(61.8, linestyle = '--', linewidth = 1.5, color = 'grey')
ax2.set_title('tsla CHOPPINESS INDEX 14')
ax3.plot(tsla_macd['macd'], color = 'grey', linewidth = 1.5, label = 'MACD')
ax3.plot(tsla_macd['signal'], color = 'skyblue', linewidth = 1.5, label = 'SIGNAL')
for i in range(len(tsla_macd)):
    if str(tsla_macd['hist'][i])[0] == '-':
        ax3.bar(tsla_macd.index[i], tsla_macd['hist'][i], color = '#ef5350')
    else:
        ax3.bar(tsla_macd.index[i], tsla_macd['hist'][i], color = '#26a69a')
ax3.legend()
ax3.set_title('TSLA MACD 26,12,9')
plt.show()

position = []
for i in range(len(ci_macd_signal)):
    if ci_macd_signal[i] > 1:
        position.append(0)
    else:
        position.append(1)
        
for i in range(len(tsla['close'])):
    if ci_macd_signal[i] == 1:
        position[i] = 1
    elif ci_macd_signal[i] == -1:
        position[i] = 0
    else:
        position[i] = position[i-1]
        
ci = tsla['ci_14']
close_price = tsla['close']
ci_macd_signal = pd.DataFrame(ci_macd_signal).rename(columns = {0:'ci_macd_signal'}).set_index(tsla.index)
position = pd.DataFrame(position).rename(columns = {0:'ci_macd_position'}).set_index(tsla.index)

frames = [close_price, ci, ci_macd_signal, position]
strategy = pd.concat(frames, join = 'inner', axis = 1)

strategy.head()

rets = tsla.close.pct_change()[1:]
strat_rets = strategy.ci_macd_position[1:] * rets

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
