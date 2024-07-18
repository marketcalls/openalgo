from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required
from forms import SymbolForm
import yfinance as yf
import pandas as pd
import pandas_ta as ta
import plotly.graph_objects as go
import numpy as np
import logging

charts_bp = Blueprint('charts', __name__)

# Helper function to compute halftrend
def compute_halftrend(data, amplitude=2, channel_deviation=4):
    data['ATR'] = ta.atr(data['High'], data['Low'], data['Close'], length=50)
    atr = data['ATR'] / 2
    atr /= 2
    dev = channel_deviation * atr

    current_high = data['High'].mask(data['High'].shift(-amplitude) > data['High'].rolling(window=amplitude, min_periods=1).max(), np.nan)
    current_low = data['Low'].mask(data['Low'].shift(-amplitude) < data['Low'].rolling(window=amplitude, min_periods=1).min(), np.nan)

    upper_band = data['High'].rolling(window=amplitude, min_periods=1).mean()
    lower_band = data['Low'].rolling(window=amplitude, min_periods=1).mean()

    main = pd.Series(index=data.index, dtype='float64')
    trend = pd.Series(index=data.index, dtype='float64')
    up_line = pd.Series(index=data.index, dtype='float64')
    down_line = pd.Series(index=data.index, dtype='float64')
    atr_high = pd.Series(index=data.index, dtype='float64')
    atr_low = pd.Series(index=data.index, dtype='float64')

    for i in range(1, len(data)):
        if trend.iloc[i-1] > 0:
            main.iloc[i] = max(main.iloc[i-1], current_low.iloc[i])
            if upper_band.iloc[i] < main.iloc[i] and data['Close'].iloc[i] < data['Low'].iloc[i-1]:
                trend.iloc[i] = -1
                main.iloc[i] = min(main.iloc[i-1], current_high.iloc[i])
            else:
                trend.iloc[i] = trend.iloc[i-1] + 1
        elif trend.iloc[i-1] < 0:
            main.iloc[i] = min(main.iloc[i-1], current_high.iloc[i])
            if lower_band.iloc[i] > main.iloc[i] and data['Close'].iloc[i] > data['High'].iloc[i-1]:
                trend.iloc[i] = 1
                main.iloc[i] = max(main.iloc[i-1], current_low.iloc[i])
            else:
                trend.iloc[i] = trend.iloc[i-1] - 1
        else:
            if data['Close'].iloc[i] > data['Close'].iloc[i-1]:
                trend.iloc[i] = 1
                main.iloc[i] = current_low.iloc[i]
            else:
                trend.iloc[i] = -1
                main.iloc[i] = current_high.iloc[i]

        if trend.iloc[i] > 0:
            up_line.iloc[i] = main.iloc[i]
            down_line.iloc[i] = np.nan
            atr_high.iloc[i] = up_line.iloc[i] + dev.iloc[i]
            atr_low.iloc[i] = up_line.iloc[i] - dev.iloc[i]
        else:
            up_line.iloc[i] = np.nan
            down_line.iloc[i] = main.iloc[i]
            atr_high.iloc[i] = down_line.iloc[i] + dev.iloc[i]
            atr_low.iloc[i] = down_line.iloc[i] - dev.iloc[i]

    return trend, up_line, down_line, atr_high, atr_low

def fetch_and_prepare_data(symbol):
    try:
        # Fetch data
        data = yf.download(symbol, interval='5m', period='5d')

        if data.empty:
            raise ValueError(f"No data fetched for symbol {symbol}")

        logging.debug(f"Fetched data for {symbol}: {data.tail()}")

        # Ensure no missing data
        data = data.dropna()

        if data.empty:
            raise ValueError(f"No complete data available after dropna for symbol {symbol}")

        # Calculate Halftrend
        trend, up_line, down_line, atr_high, atr_low = compute_halftrend(data)

        # Fetch LTP for the last trading day
        daily_data = yf.download(symbol, interval='1d', period='1mo')
        if daily_data.empty:
            raise ValueError(f"No daily data fetched for symbol {symbol}")

        ltp = round(daily_data['Close'].iloc[-1], 2)
        prev_close = daily_data['Close'].iloc[-2] if len(daily_data) > 1 else ltp
        percentage_change = round(((ltp - prev_close) / prev_close) * 100,2)

        # Plotting with Plotly
        fig = go.Figure(data=[go.Candlestick(x=data.index,
                                             open=data['Open'],
                                             high=data['High'],
                                             low=data['Low'],
                                             close=data['Close'],
                                             name='Candlesticks'),
                              go.Scatter(x=data.index, y=up_line, mode='lines', name='Up Line', line=dict(color='green')),
                              go.Scatter(x=data.index, y=down_line, mode='lines', name='Down Line', line=dict(color='red')),
                              go.Scatter(x=data.index, y=atr_high, mode='lines', name='ATR High', line=dict(color='green', dash='dash')),
                              go.Scatter(x=data.index, y=atr_low, mode='lines', name='ATR Low', line=dict(color='red', dash='dash'))])

        fig.update_layout(title=f'{symbol} Chart with Halftrend',
                          template='plotly_dark',
                          xaxis_title='Date',
                          yaxis_title='Price',
                          xaxis=dict(type='category', showgrid=False, tickmode='array',
                                     tickvals=data.index[::len(data) // 5],  # Adjust the frequency of ticks as needed
                                     ticktext=data.index[::len(data) // 5].strftime('%b %Y')),  # Format ticks as 'Jan 2022'
                          xaxis_rangeslider_visible=False,
                          yaxis=dict(showgrid=False))

        return fig, ltp, percentage_change

    except Exception as e:
        logging.error(f"Error fetching data for {symbol}: {str(e)}")
        raise e

@charts_bp.route('/charts', methods=['GET', 'POST'])
@login_required
def charts():
    form = SymbolForm()
    symbol = "^NSEI"

    if request.method == 'POST' and form.validate_on_submit():
        symbol = form.symbol.data.upper()
        return redirect(url_for('charts.charts_data', symbol=symbol))

    try:
        fig, ltp, percentage_change = fetch_and_prepare_data(symbol)
        return render_template('charts.html', form=form, symbol=symbol, ltp=ltp, percentage_change=percentage_change, graph_html=fig.to_html())
    except Exception as e:
        flash(f'Error fetching data for {symbol}: {str(e)}', 'danger')
        return render_template('charts.html', form=form, symbol=symbol, ltp="N/A", percentage_change="N/A", graph_html="")

@charts_bp.route('/charts/<symbol>', methods=['GET', 'POST'])
@login_required
def charts_data(symbol):
    form = SymbolForm()

    if request.method == 'POST' and form.validate_on_submit():
        new_symbol = form.symbol.data.upper()
        return redirect(url_for('charts.charts_data', symbol=new_symbol))

    try:
        fig, ltp, percentage_change = fetch_and_prepare_data(symbol)
        return render_template('charts_data.html', form=form, symbol=symbol, ltp=ltp, percentage_change=percentage_change, graph_html=fig.to_html())
    except Exception as e:
        flash(f'Error fetching data for {symbol}: {str(e)}', 'danger')
        return redirect(url_for('charts.charts'))
