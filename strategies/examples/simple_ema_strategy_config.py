#!/usr/bin/env python
"""
Simple EMA Crossover Strategy Example

This example declares editable OpenAlgo strategy settings with ui.* calls.
OpenAlgo discovers these declarations on upload and injects runtime values.
"""

import os
import time
from datetime import datetime, timedelta

import pandas as pd
from openalgo import api, ta

try:
    from openalgo.config import ui
except ModuleNotFoundError:
    from openalgo_config import ui


def normalize_history(df):
    """Normalize OpenAlgo history data before indicator calculations."""
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.set_index("timestamp")
    else:
        df.index = pd.to_datetime(df.index)
    df = df.sort_index()
    if df.index.tz is not None:
        df.index = df.index.tz_convert(None)
    return df


api_key = os.getenv("OPENALGO_API_KEY")
host = os.getenv("HOST_SERVER") or os.getenv("OPENALGO_HOST", "http://127.0.0.1:5000")
ws_url = os.getenv("WEBSOCKET_URL", "ws://127.0.0.1:8765")

if not api_key:
    print("Error: OPENALGO_API_KEY environment variable not set")
    raise SystemExit(1)

strategy = ui.string("strategy", default="EMA Crossover Python", label="Strategy Name", required=True)
symbol = ui.symbol("symbol", default="NHPC", label="Symbol", required=True)
exchange = ui.exchange(
    "exchange",
    default="BSE",
    label="Exchange",
    options=["NSE", "BSE", "NFO", "BFO", "MCX", "CDS", "BCD", "CRYPTO"],
    required=True,
)
product = ui.product("product", default="MIS", label="Product", options=["MIS", "NRML", "CNC"], required=True)
quantity = ui.quantity("quantity", default=1, label="Quantity", min=1, required=True)
fast_period = ui.int("fast_period", default=5, label="Fast EMA Period", min=1, max=200, required=True)
slow_period = ui.int("slow_period", default=10, label="Slow EMA Period", min=2, max=500, required=True)
interval = ui.string("interval", default="1m", label="Candle Interval", required=True)
history_days = ui.int("history_days", default=7, label="History Days", min=1, max=365, required=True)
poll_seconds = ui.int("poll_seconds", default=15, label="Poll Seconds", min=1, max=3600, required=True)

if fast_period >= slow_period:
    print("Error: fast_period must be lower than slow_period")
    raise SystemExit(1)

client = api(api_key=api_key, host=host, ws_url=ws_url)


def calculate_ema_signals(df):
    """Calculate EMA crossover signals using openalgo.ta."""
    close = df["close"]

    ema_fast = ta.ema(close, fast_period)
    ema_slow = ta.ema(close, slow_period)

    raw_buy = pd.Series(ta.crossover(ema_fast, ema_slow), index=df.index).fillna(False)
    raw_sell = pd.Series(ta.crossunder(ema_fast, ema_slow), index=df.index).fillna(False)
    buy_signal = pd.Series(ta.exrem(raw_buy, raw_sell), index=df.index).fillna(False)
    sell_signal = pd.Series(ta.exrem(raw_sell, raw_buy), index=df.index).fillna(False)

    return pd.DataFrame(
        {
            "EMA_Fast": ema_fast,
            "EMA_Slow": ema_slow,
            "Buy_Signal": buy_signal,
            "Sell_Signal": sell_signal,
        },
        index=df.index,
    )


def ema_strategy():
    """Run the EMA crossover trading strategy."""
    position = 0

    while True:
        try:
            end_date = datetime.now().strftime("%Y-%m-%d")
            start_date = (datetime.now() - timedelta(days=history_days)).strftime("%Y-%m-%d")

            df = client.history(
                symbol=symbol,
                exchange=exchange,
                interval=interval,
                start_date=start_date,
                end_date=end_date,
            )

            if df.empty:
                print("DataFrame is empty. Retrying...")
                time.sleep(poll_seconds)
                continue

            if "close" not in df.columns:
                raise KeyError("Missing 'close' column in DataFrame")

            df = normalize_history(df)
            df["close"] = df["close"].round(2)

            signals = calculate_ema_signals(df)
            if len(signals) < 2:
                print("Not enough candles for signal confirmation. Retrying...")
                time.sleep(poll_seconds)
                continue

            buy_signal = bool(signals["Buy_Signal"].iloc[-2])
            sell_signal = bool(signals["Sell_Signal"].iloc[-2])

            if buy_signal and position <= 0:
                position = quantity
                response = client.placesmartorder(
                    strategy=strategy,
                    symbol=symbol,
                    action="BUY",
                    exchange=exchange,
                    price_type="MARKET",
                    product=product,
                    quantity=quantity,
                    position_size=position,
                )
                print("Buy Order Response:", response)

            elif sell_signal and position >= 0:
                position = quantity * -1
                response = client.placesmartorder(
                    strategy=strategy,
                    symbol=symbol,
                    action="SELL",
                    exchange=exchange,
                    price_type="MARKET",
                    product=product,
                    quantity=quantity,
                    position_size=position,
                )
                print("Sell Order Response:", response)

            print("\nStrategy Status:")
            print("-" * 50)
            print(f"Strategy: {strategy}")
            print(f"Symbol: {symbol} | Exchange: {exchange} | Product: {product}")
            print(f"Position: {position}")
            print(f"LTP: {df['close'].iloc[-1]}")
            print(f"Fast EMA ({fast_period}): {signals['EMA_Fast'].iloc[-2]:.2f}")
            print(f"Slow EMA ({slow_period}): {signals['EMA_Slow'].iloc[-2]:.2f}")
            print(f"Buy Signal: {buy_signal}")
            print(f"Sell Signal: {sell_signal}")
            print("-" * 50)

        except Exception as e:
            print(f"Error in strategy: {str(e)}")
            time.sleep(poll_seconds)
            continue

        time.sleep(poll_seconds)


if __name__ == "__main__":
    print(f"Starting {fast_period}/{slow_period} EMA Crossover Strategy...")
    print("OCS config:", json.dumps(config, sort_keys=True))
    ema_strategy()
