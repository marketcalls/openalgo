# strategy/backtest_engine.py
import pandas as pd
from datetime import datetime, timedelta, time
import psycopg2
import logging
import matplotlib.pyplot as plt
import matplotlib
import os
import pytz
IST = pytz.timezone('Asia/Kolkata')

matplotlib.use('Agg')  # use Anti-Grain Geometry backend (non-GUI)

class BacktestEngine:
    def __init__(self, conn, symbol, interval, start_date, end_date, lookback_days=5, tp_pct=1.0, sl_pct=1.0, trail_activation_pct=0.5,
             trail_stop_gap_pct=0.2, trail_increment_pct=0.1, capital=100000, leverage=5, capital_alloc_pct=30):
        self.conn = conn
        self.symbol = symbol
        self.interval = interval
        self.start_date = datetime.strptime(start_date, "%Y-%m-%d").date()
        self.end_date = datetime.strptime(end_date, "%Y-%m-%d").date()
        self.lookback_days = lookback_days
        self.logger = logging.getLogger(f"BacktestEngine[{symbol}]")
        self.position = 0
        self.entry_price = None
        self.trades = []
        self.tp_pct = tp_pct / 100
        self.sl_pct = sl_pct / 100
        self.trail_activation_pct = trail_activation_pct / 100
        self.trail_stop_gap_pct = trail_stop_gap_pct / 100
        self.trail_increment_pct = trail_increment_pct / 100
        self.capital = capital
        self.leverage = leverage
        self.capital_alloc_pct = capital_alloc_pct

    def daterange(self):
        for n in range(int((self.end_date - self.start_date).days) + 1):
            yield self.start_date + timedelta(n)

    def fetch_lookback_data(self, end_day):
        lookback_start = end_day - timedelta(days=self.lookback_days)
        query = f"""
            SELECT * FROM ohlc_{self.interval}
            WHERE symbol = %s AND time >= %s AND time < %s
            ORDER BY time ASC
        """
        df = pd.read_sql(query, self.conn, params=(self.symbol, lookback_start, end_day + timedelta(days=1)))
        return df

    def run(self):
        self.logger.info(f"Running backtest from {self.start_date} to {self.end_date}")
        trades = []
        self.trailing_chart_data = []  # store plots only for TRAIL trades
        in_position = False
        cumulative_pnl = 0

        for day in self.daterange():
            df = self.fetch_lookback_data(day)
            if df.empty or len(df) < 20:
                continue

            df['ema_fast'] = df['close'].ewm(span=5).mean()
            df['ema_slow'] = df['close'].ewm(span=10).mean()

            # 💡 Filter only today's data for signal processing
            start_dt = datetime.combine(day, time.min).replace(tzinfo=pytz.UTC)
            end_dt = datetime.combine(day, time.max).replace(tzinfo=pytz.UTC)
            df_today = df[(df['time'] >= start_dt) & (df['time'] <= end_dt)].copy()

            entry_row = None

            for i in range(1, len(df_today)):
                prev = df_today.iloc[i - 1]
                curr = df_today.iloc[i]

                crossover = prev['ema_fast'] < prev['ema_slow'] and curr['ema_fast'] > curr['ema_slow']
                crossunder = prev['ema_fast'] > prev['ema_slow'] and curr['ema_fast'] < curr['ema_slow']
                curr_ist_time = curr['time'].astimezone(IST).time()  
                curr_ist_time_2 = curr['time'].astimezone(IST)

                # ENTRY: Long
                if not in_position and crossover and curr_ist_time <= time(14, 30) and self.position == 0:
                    self.logger.info(f"[{curr['time']}] LONG ENTRY triggered at {curr['close']}")
                    self.position = 1
                    entry_row = curr
                    capital_per_trade = self.capital * self.leverage * (self.capital_alloc_pct / 100)
                    quantity = int(capital_per_trade / entry_row['close'])
                    trailing_active = False
                    trail_stop = None
                    last_trail_price = None
                    trail_history = []
                    in_position = True
                    continue

                # ENTRY: Short
                if not in_position and crossunder and curr_ist_time <= time(14, 30) and self.position == 0:
                    self.logger.info(f"[{curr['time']}] SHORT ENTRY triggered at {curr['close']}")
                    self.position = -1
                    entry_row = curr
                    capital_per_trade = self.capital * self.leverage * (self.capital_alloc_pct / 100)
                    quantity = int(capital_per_trade / entry_row['close'])
                    trailing_active = False
                    trail_stop = None
                    last_trail_price = None
                    trail_history = []
                    in_position = True
                    continue


                # EXIT
                # TRADE MONITORING WHILE IN POSITION
                if self.position != 0 and entry_row is not None:
                    price = curr['close']
                    entry_price = entry_row['close']
                    exit_row = None
                    exit_reason = None                            
                    #self.logger.info(f"[{curr_ist_time}] TRADE MONITORING: Position: {self.position}, Entry Price: {entry_price}, Current Price: {price}")

                    is_long = self.position == 1
                    price_change = price - entry_price
                    pct_move = price_change / entry_price

                    # Targets
                    tp_hit = pct_move >= self.tp_pct if is_long else pct_move <= -self.tp_pct
                    sl_hit = pct_move <= -self.sl_pct if is_long else pct_move >= self.sl_pct
                    trail_trigger_pct = self.trail_activation_pct if is_long else -self.trail_activation_pct
                    trail_increment = self.trail_increment_pct * entry_price
                    trail_gap = self.trail_stop_gap_pct * entry_price

                    #self.logger.info(f"[{curr['time']}] Evaluating exit for {'SHORT' if self.position == -1 else 'LONG'} at price {price}")

                    # TP
                    if tp_hit:
                        exit_row = curr
                        exit_reason = "TP"
                        self.logger.info(f"[{curr['time']}] TP HIT at {price}")

                    # SL
                    elif sl_hit:
                        exit_row = curr
                        exit_reason = "SL"
                        self.logger.info(f"[{curr['time']}] SL HIT at {price}")
                        

                    # Trailing Stop
                    elif trailing_active:
                        # Price moved enough to adjust trail
                        if abs(price - last_trail_price) >= trail_increment:
                            if is_long:
                                trail_stop += trail_increment
                            else:
                                trail_stop -= trail_increment
                            last_trail_price = price
                            trail_history.append({
                                'time': curr_ist_time_2,
                                'value': trail_stop
                            })

                        # Price hit trailing stop
                        if (is_long and price <= trail_stop) or (not is_long and price >= trail_stop):
                            exit_row = curr
                            exit_reason = "TRAIL"
                            self.logger.info(f"[{curr['time']}] TRAIL STOP HIT at {price} vs stop {trail_stop}")
                        

                    # Activate trailing
                    elif (pct_move >= self.trail_activation_pct if is_long else pct_move <= -self.trail_activation_pct):
                        trailing_active = True
                        trail_stop = price - trail_gap if is_long else price + trail_gap
                        last_trail_price = price

                    # Strategy exit signal
                    elif (crossunder if is_long else crossover):
                        exit_row = curr
                        exit_reason = "CROSSOVER" if is_long else "CROSSUNDER"
                        self.logger.info(f"[{curr['time']}] CROSSOVER HIT for SHORT at EMA fast {curr['ema_fast']} vs slow {curr['ema_slow']}")

                    # Force exit based on direction and time (in UTC)
                    elif is_long and curr_ist_time  >= time(15, 10):  # 3:10 PM IST
                        exit_row = curr
                        exit_reason = "FORCE_EXIT_1510"
                        self.logger.info(f"[{curr['time']}] FORCE EXIT triggered for {'LONG' if is_long else 'SHORT'}")

                    elif not is_long and curr_ist_time  >= time(14, 40):  # 2:40 PM IST
                        exit_row = curr
                        exit_reason = "FORCE_EXIT_1440"
                        self.logger.info(f"[{curr['time']}] FORCE EXIT triggered for {'LONG' if is_long else 'SHORT'}")

                    # Process exit
                    if exit_row is not None:
                        trade_df = df[(df['time'] >= entry_row['time']) & (df['time'] <= curr['time'])]
                        trade_close = trade_df['close']

                        mae = (trade_close.min() - entry_price if is_long else entry_price - trade_close.max()) if not trade_df.empty else 0
                        mfe = (trade_close.max() - entry_price if is_long else entry_price - trade_close.min()) if not trade_df.empty else 0
                        pnl = (price - entry_price if is_long else entry_price - price)
                        cumulative_pnl += pnl * quantity

                        trades.append({
                            'symbol': self.symbol,
                            'quantity': quantity,
                            'entry_time': entry_row['time'].astimezone(IST).strftime("%Y-%m-%d %H:%M:%S"),
                            'entry_price': round(entry_price, 2),
                            'exit_time': exit_row['time'].astimezone(IST).strftime("%Y-%m-%d %H:%M:%S"),
                            'exit_price': round(price, 2),
                            'exit_reason': exit_reason,
                            'pnl': round(pnl * quantity, 2),
                            'cumulative_pnl': round(cumulative_pnl, 2),
                            'mae': round(mae * quantity, 2),
                            'mfe': round(mfe * quantity, 2),
                            'holding_period': str(exit_row['time'] - entry_row['time']),
                            'direction': "LONG" if is_long else "SHORT",                            
                            'capital_used': round(quantity * entry_price, 2)
                        })


                        # If TRAIL exit, store chart data for export
                        if exit_reason == "TRAIL":
                            self.trailing_chart_data.append({
                                'symbol': self.symbol,
                                'entry_time': entry_row['time'],
                                'exit_time': exit_row['time'],
                                'entry_price': entry_price,
                                'df': df.copy(),
                                'trail_stops': trail_history
                            })

                        # Reset
                        self.position = 0
                        entry_row = None
                        trailing_active = False
                        trail_stop = None
                        last_trail_price = None
                        in_position = False

        trades_df = pd.DataFrame(trades)
        self.trades = trades_df
        print(f"DEBUG: Total trades recorded: {len(self.trades)}")
        return trades_df    

    def get_summary_metrics(self):
        if self.trades.empty:
            return {}

        total_trades = len(self.trades)
        winning_trades = self.trades[self.trades['pnl'] > 0]
        losing_trades = self.trades[self.trades['pnl'] <= 0]

        return {
            'symbol': self.symbol,
            'total_trades': total_trades,
            'win_rate': round(len(winning_trades) / total_trades * 100, 2),
            'gross_pnl': round(self.trades['pnl'].sum(), 2),
            'average_pnl': round(self.trades['pnl'].mean(), 2),
            'max_drawdown': round(self.trades['pnl'].cumsum().cummax().sub(self.trades['pnl'].cumsum()).max(), 2),
            'avg_holding_time': str(pd.to_timedelta(self.trades['holding_period']).mean())
        }

    def visualize_trade(df, entry_time, exit_time, entry_price, trail_stops=None, title="Trade Chart"):
        trade_df = df[(df['time'] >= entry_time) & (df['time'] <= exit_time)].copy()
        if trade_df.empty:
            print("No data for this trade.")
            return

        plt.figure(figsize=(12, 6))
        plt.plot(trade_df['time'], trade_df['close'], label='Price', color='blue')
        plt.axhline(entry_price, color='green', linestyle='--', label='Entry Price')
        plt.axvline(entry_time, color='green', linestyle=':', label='Entry Time')
        plt.axvline(exit_time, color='red', linestyle=':', label='Exit Time')

        if trail_stops:
            plt.plot(trail_stops['time'], trail_stops['value'], color='orange', linestyle='--', label='Trailing Stop')

        plt.legend()
        plt.title(title)
        plt.xlabel("Time")
        plt.ylabel("Price")
        plt.grid(True)
        plt.tight_layout()
        plt.show()


    def export_trail_charts(self, output_dir="trail_charts"):
        os.makedirs(output_dir, exist_ok=True)

        for i, trade in enumerate(self.trailing_chart_data):
            df = trade['df']
            entry_time = trade['entry_time'].tz_convert('Asia/Kolkata')
            exit_time = trade['exit_time'].tz_convert('Asia/Kolkata')
            entry_price = trade['entry_price']
            symbol = trade['symbol']
            trail_stops = trade['trail_stops']

            trade_df = df[(df['time'] >= entry_time) & (df['time'] <= exit_time)].copy()
            if trade_df.empty:
                continue
            
            df['time'] = df['time'].dt.tz_convert('Asia/Kolkata')
            trade_df['time'] = trade_df['time'].dt.tz_convert('Asia/Kolkata')
            plt.figure(figsize=(12, 6))
            plt.plot(trade_df['time'], trade_df['close'], label='Price', color='blue')
            plt.axhline(entry_price, color='green', linestyle='--', label='Entry Price')
            plt.axvline(entry_time, color='green', linestyle=':', label='Entry Time')
            plt.axvline(exit_time, color='red', linestyle=':', label='Exit Time')

            if trail_stops:
                trail_df = pd.DataFrame(trail_stops)
                plt.plot(trail_df['time'], trail_df['value'], color='orange', linestyle='--', label='Trailing Stop')

            plt.title(f"{symbol} TRAIL Exit [{entry_time} → {exit_time}]")
            plt.xlabel("Time")
            plt.ylabel("Price")
            plt.legend()
            plt.grid(True)
            plt.tight_layout()

            filename = f"{symbol}_trail_{entry_time.strftime('%Y%m%d_%H%M%S')}.png"
            plt.savefig(os.path.join(output_dir, filename))
            plt.close()

            print(f"📈 Saved trailing chart: {filename}")

