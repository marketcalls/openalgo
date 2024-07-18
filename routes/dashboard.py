from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required
from extensions import db
from forms import SymbolForm
import yfinance as yf
import pandas_ta as ta
import pandas as pd
import logging

# Configure logging
logging.basicConfig(level=logging.DEBUG)

dashboard_bp = Blueprint('dashboard', __name__)

@dashboard_bp.route('/dashboard', methods=['GET', 'POST'])
@login_required
def dashboard():
    form = SymbolForm()
    if form.validate_on_submit():
        symbol = form.symbol.data.upper()
        return redirect(url_for('dashboard.dash_stock', symbol=symbol))
    return render_template('dashboard.html', form=form)

@dashboard_bp.route('/dashboard/<symbol>')
@login_required
def dash_stock(symbol):
    form = SymbolForm()
    try:
        # Fetch intraday data
        data = yf.download(symbol, interval='5m', period='1mo')

        if data.empty:
            raise ValueError(f"No data fetched for symbol {symbol}")

        logging.debug(f"Fetched intraday data for {symbol}: {data.tail()}")

        # Ensure no missing data
        data = data.dropna()

        if data.empty:
            raise ValueError(f"No complete data available after dropna for symbol {symbol}")

        # Calculate indicators using pandas_ta
        indicators = {}

        if 'Close' in data.columns and not data['Close'].isnull().values.any():
            data['RSI'] = ta.rsi(data['Close'])
            data['EMA'] = ta.ema(data['Close'])
            data['SMA'] = ta.sma(data['Close'])
            data['WILLR'] = ta.willr(data['High'], data['Low'], data['Close'])
            data['TEMA'] = ta.tema(data['Close'])
            data['MFI'] = ta.mfi(data['High'], data['Low'], data['Close'], data['Volume'])
            data['ATR'] = ta.atr(data['High'], data['Low'], data['Close'])
            data['CCI'] = ta.cci(data['High'], data['Low'], data['Close'])

            # Get the latest values and round them to two decimals
            latest_data = data.iloc[-1]

            indicators['RSI'] = round(latest_data['RSI'], 2) if 'RSI' in latest_data and not pd.isna(latest_data['RSI']) else None
            indicators['EMA'] = round(latest_data['EMA'], 2) if 'EMA' in latest_data and not pd.isna(latest_data['EMA']) else None
            indicators['SMA'] = round(latest_data['SMA'], 2) if 'SMA' in latest_data and not pd.isna(latest_data['SMA']) else None
            indicators['WILLR'] = round(latest_data['WILLR'], 2) if 'WILLR' in latest_data and not pd.isna(latest_data['WILLR']) else None
            indicators['TEMA'] = round(latest_data['TEMA'], 2) if 'TEMA' in latest_data and not pd.isna(latest_data['TEMA']) else None
            indicators['MFI'] = round(latest_data['MFI'], 2) if 'MFI' in latest_data and not pd.isna(latest_data['MFI']) else None
            indicators['ATR'] = round(latest_data['ATR'], 2) if 'ATR' in latest_data and not pd.isna(latest_data['ATR']) else None
            indicators['CCI'] = round(latest_data['CCI'], 2) if 'CCI' in latest_data and not pd.isna(latest_data['CCI']) else None
            ltp = round(latest_data['Close'], 2) if 'Close' in latest_data and not pd.isna(latest_data['Close']) else None
        else:
            raise ValueError(f"No valid closing price data available for symbol {symbol}")

        # Fetch daily data for percentage change calculation
        daily_data = yf.download(symbol, interval='1d', period='1mo')
        if daily_data.empty:
            raise ValueError(f"No daily data fetched for symbol {symbol}")

        logging.debug(f"Fetched daily data for {symbol}: {daily_data.tail()}")

        previous_close = daily_data['Close'].iloc[-2] 
        ltp_close = daily_data['Close'].iloc[-1]
        percentage_change = round(((ltp_close - previous_close) / previous_close) * 100, 2)

        logging.debug(f"Rounded indicator values for {symbol}: {indicators}")

        return render_template('dash_stock.html', symbol=symbol, indicators=indicators, ltp=ltp, percentage_change=percentage_change, form=form)

    except Exception as e:
        logging.error(f"Error fetching data for {symbol}: {str(e)}")
        flash(f'Error fetching data for {symbol}: {str(e)}', 'danger')
        return redirect(url_for('dashboard.dashboard'))
