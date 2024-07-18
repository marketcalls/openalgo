# routes/screener.py

from flask import Blueprint, render_template, request, flash
from flask_login import login_required
import yfinance as yf
import pandas as pd
import pandas_ta as ta
from datetime import datetime, time

screener_bp = Blueprint('screener', __name__)

def fetch_and_calculate_ema(ticker):
    data = yf.download(ticker, interval='5m', period='1d', progress=False)
    data['EMA10'] = round(ta.ema(data['Close'], length=10),2)
    data['EMA20'] = round(ta.ema(data['Close'], length=20),2)
    return data

def check_crossover(data, ticker, start_time, end_time):
    crossover_events = []
    for i in range(1, len(data)):
        current_time = data.index[i].time()
        if start_time <= current_time <= end_time:
            if (data['EMA10'].iloc[i] > data['EMA20'].iloc[i]) and (data['EMA10'].iloc[i-1] < data['EMA20'].iloc[i-1]):
                crossover_events.append({
                    "Date": data.index[i].date(),
                    "Time": data.index[i].time(),
                    "Ticker": ticker,
                    "Crossover Type": "Positive EMA Crossover",
                    "Close": data['Close'].iloc[i],
                    "EMA10": data['EMA10'].iloc[i],
                    "EMA20": data['EMA20'].iloc[i]
                })
            elif (data['EMA10'].iloc[i] < data['EMA20'].iloc[i]) and (data['EMA10'].iloc[i-1] > data['EMA20'].iloc[i-1]):
                crossover_events.append({
                    "Date": data.index[i].date(),
                    "Time": data.index[i].time(),
                    "Ticker": ticker,
                    "Crossover Type": "Negative EMA Crossover",
                    "Close": data['Close'].iloc[i],
                    "EMA10": data['EMA10'].iloc[i],
                    "EMA20": data['EMA20'].iloc[i]
                })
    return crossover_events


def scan_tickers(tickers, start_time, end_time):
    all_crossovers = []
    for ticker in tickers:
        data = fetch_and_calculate_ema(ticker)
        crossover_events = check_crossover(data, ticker, start_time, end_time)
        all_crossovers.extend(crossover_events)
    
    # Sort crossovers by Date and Time
    all_crossovers.sort(key=lambda x: (x['Date'], x['Time']))
    
    return all_crossovers


@screener_bp.route('/screener', methods=['GET', 'POST'])
@login_required
def screener():
    results = None
    default_start_time = time(9, 30)
    default_end_time = time(15, 0)
    if request.method == 'POST':
        tickers = request.form['tickers'].split(',')
        start_time = datetime.strptime(request.form.get('start_time', '09:30'), '%H:%M').time()
        end_time = datetime.strptime(request.form.get('end_time', '15:00'), '%H:%M').time()
        results = scan_tickers(tickers, start_time, end_time)

    return render_template('screener.html', results=results, default_start_time=default_start_time, default_end_time=default_end_time)
