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
import gc

matplotlib.use('Agg')  # use Anti-Grain Geometry backend (non-GUI)

class BacktestEngine:
    def __init__(self, conn, symbol, start_date, end_date, lookback_days=10, tp_pct=1.5, sl_pct=1.5, trail_activation_pct=0.9,
             trail_stop_gap_pct=0.2, trail_increment_pct=0.2, capital=100000, leverage=5, capital_alloc_pct=30):
        self.conn = conn
        self.symbol = symbol        
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

    def fetch_lookback_data(self, end_day, interval, lookback_days):
        lookback_start = end_day - timedelta(days=lookback_days)
        #self.logger.info(f"Fetching lookback data from {lookback_start} to {end_day}")
        query = f"""
            SELECT * FROM ohlc_{interval}
            WHERE symbol = %s AND time >= %s AND time < %s
            ORDER BY time ASC
        """
        df = pd.read_sql(query, self.conn, params=(self.symbol, lookback_start, end_day + timedelta(days=1)))
        if df.empty:
            self.logger.warning(f"No data found for {self.symbol} {interval} between {lookback_start} and {end_day}")

        return df
    
    def fetch_lookback_data_2(self, start_day, end_day, interval):
        
        #self.logger.info(f"Fetching lookback data from {lookback_start} to {end_day}")
        query = f"""
            SELECT * FROM ohlc_{interval}
            WHERE symbol = %s AND time >= %s AND time < %s
            ORDER BY time ASC
        """
        df = pd.read_sql(query, self.conn, params=(self.symbol, start_day, end_day + timedelta(days=1)))
        if df.empty:
            self.logger.warning(f"No data found for {self.symbol} {interval} between {start_day} and {end_day}")

        return df
    
    def exclude_first_30min(self, group):
        mask = ~(
            (group['time'].dt.time >= time(3, 45)) & 
            (group['time'].dt.time < time(4, 15)) # Time in UTC - hence 3.45 to 4.15
        )
        return group[mask]['range'].expanding().mean()
    
    def zero_lag_ema(self, series, period):
        ema1 = series.ewm(span=period, adjust=False).mean()
        ema2 = ema1.ewm(span=period, adjust=False).mean()
        return ema1 + (ema1 - ema2)

    def trading_indicator_calculations(self, df, df_daily, df_5min):
        
        #self.logger.info(f"Calculating trading indicators for {self.symbol}")
        # Calculate the 10 day ATR
        atr_period = 5  # Standard ATR period is 14, but you can use 10
        volume_period = 5
        df_daily['prev_close'] = df_daily['close'].shift(1)  # Previous day's close
        df_daily['tr1'] = df_daily['high'] - df_daily['low']  # Current High - Current Low
        df_daily['tr2'] = abs(df_daily['high'] - df_daily['prev_close'])  # |High - Prev Close|
        df_daily['tr3'] = abs(df_daily['low'] - df_daily['prev_close'])   # |Low - Prev Close|
        df_daily['tr'] = df_daily[['tr1', 'tr2', 'tr3']].max(axis=1)  # True Range = max(tr1, tr2, tr3)        
        df_daily['atr_10'] = df_daily['tr'].ewm(span=atr_period, adjust=False).mean()
        #df_daily['atr_10'] = df_daily['tr'].rolling(window=atr_period).mean()  # SMA
        df_daily.drop(['prev_close', 'tr1', 'tr2', 'tr3', 'tr'], axis=1, inplace=True)  # Remove temp columns

        # Calculate the 10 day Volume
        df_daily['volume_10'] = df_daily['volume'].rolling(window=volume_period).mean()
        
        # Convert time to date for merging (if not already in datetime format)
        df['date'] = pd.to_datetime(df['time'].dt.date)
        df_5min['date'] = pd.to_datetime(df_5min['time'].dt.date)
        df_daily['date'] = pd.to_datetime(df_daily['time'].dt.date)

        # Merge ATR from daily data into 15m and 5m data
        df = df.merge(
            df_daily[['date', 'atr_10', 'volume_10']], 
            on='date', 
            how='left'
        )

        df_5min = df_5min.merge(
            df_daily[['date', 'atr_10', 'volume_10']],
            on='date',
            how='left'
        )
        
        # Drop the temporary 'date' column if no longer needed
        df.drop('date', axis=1, inplace=True)
        df_5min.drop('date', axis=1, inplace=True)
        #self.logger.info(f"Calculated ATR for {self.symbol}")

        # Calculate EMA_50, EMA_100 and EMA_200 (Needed only for 5min data)
        df_5min['ema_50'] = df_5min['close'].ewm(span=50, adjust=False).mean()
        df_5min['ema_100'] = df_5min['close'].ewm(span=100, adjust=False).mean()
        df_5min['ema_200'] = df_5min['close'].ewm(span=200, adjust=False).mean()
        #self.logger.info(f"Calculated EMA for {self.symbol}")

        # Range calculation(Needed for both 5min and 15min data)
        df['range'] = df['high'] - df['low']
        df['date'] = df['time'].dt.date  # Extract date from timestamp
        # 1. Average Range (All Candles)
        df['avg_range_all'] = df.groupby('date')['range'].expanding().mean().reset_index(level=0, drop=True)
        # 2. Average Range (Excluding First 30 Minutes) - Per Day
        # Apply per-day, then reindex to original DataFrame
        avg_ex_first_30min = df.groupby('date').apply(self.exclude_first_30min).reset_index(level=0, drop=True)
        df['avg_range_ex_first_30min'] = avg_ex_first_30min.reindex(df.index).ffill()

        # Bullish calculation based on range
        df['is_range_bullish'] = (df['range'] > 0.7 * df['avg_range_ex_first_30min']) & (df['close'] > df['open']) & (df['close'] > (((df['high'] - df['open']) * 0.5) + df['open']))
        df['is_range_bearish'] = (df['range'] > 0.7 * df['avg_range_ex_first_30min']) & (df['close'] < df['open']) & (df['close'] < (((df['open'] - df['low']) * 0.5) + df['low']))

        df_5min['range'] = df_5min['high'] - df_5min['low']
        df_5min['date'] = df_5min['time'].dt.date  # Extract date from timestamp        
        df_5min['avg_range_all'] = df_5min.groupby('date')['range'].expanding().mean().reset_index(level=0, drop=True)
        avg_ex_first_30min_5 = df_5min.groupby('date').apply(self.exclude_first_30min).reset_index(level=0, drop=True)
        df_5min['avg_range_ex_first_30min'] = avg_ex_first_30min_5.reindex(df_5min.index).ffill()
        df_5min['is_range_bullish'] = (df_5min['range'] > 0.7 * df_5min['avg_range_ex_first_30min']) & (df_5min['close'] > df_5min['open']) & (df_5min['close'] > (((df_5min['high'] - df_5min['open']) * 0.5) + df_5min['open']))
        df_5min['is_range_bearish'] = (df_5min['range'] > 0.7 * df_5min['avg_range_ex_first_30min']) & (df_5min['close'] < df_5min['open']) & (df_5min['close'] < (((df_5min['open'] - df_5min['low']) * 0.5) + df_5min['low']))
        #self.logger.info(f"Calculated Range Bullish/Bearish for {self.symbol}")

        # Zero Lag MACD Calculation (Need only for 15min data)
        fast_period = 12
        slow_period = 26
        signal_period = 9

        df['fast_zlema'] = self.zero_lag_ema(df['close'], fast_period)
        df['slow_zlema'] = self.zero_lag_ema(df['close'], slow_period)
        df['zl_macd'] = df['fast_zlema'] - df['slow_zlema']
        df['zl_signal'] = df['zl_macd'].ewm(span=signal_period, adjust=False).mean()
        df['zl_hist'] = df['zl_macd'] - df['zl_signal']

        # Generate Signals (1 for buy, -1 for sell, 0 for no signal)
        df['zl_macd_signal'] = 0
        df.loc[(df['zl_macd'] > df['zl_signal']) & 
            (df['zl_macd'].shift(1) <= df['zl_signal'].shift(1)), 'zl_macd_signal'] = 1
        df.loc[(df['zl_macd'] < df['zl_signal']) & 
            (df['zl_macd'].shift(1) >= df['zl_signal'].shift(1)), 'zl_macd_signal'] = -1
        df.drop(['fast_zlema', 'slow_zlema', 'zl_macd', 'zl_signal', 'zl_hist'], axis=1, inplace=True)  # Drop intermediate columns
        #self.logger.info(f"Calculated Zero Lag MACD for {self.symbol}")
        
        # Single Print Calculations
        df['is_first_bullish_confirmed'] = False
        df['is_first_bearish_confirmed'] = False
        df['candle_count'] = df.groupby(df['date']).cumcount() + 1
        # Compute cumulative high/low up to previous row per day
        df['cum_high_prev'] = df.groupby('date')['high'].expanding().max().shift(1).reset_index(level=0, drop=True)
        df['cum_low_prev'] = df.groupby('date')['low'].expanding().min().shift(1).reset_index(level=0, drop=True)
        df['sp_confirmed_bullish'] = (df['close'] > df['cum_high_prev']) & (df['close'] > df['open']) & (df['candle_count'] >= 2)
        df['sp_confirmed_bearish'] = (df['close'] < df['cum_low_prev']) & (df['close'] < df['open']) & (df['candle_count'] >= 2)
        bullish_conf = df[df['sp_confirmed_bullish']]
        bearish_conf = df[df['sp_confirmed_bearish']]
        # Step 3: Get index of first bullish and bearish confirmation per day
        first_bullish_idx = bullish_conf.groupby('date').head(1).index
        first_bearish_idx = bearish_conf.groupby('date').head(1).index
        # Step 4: Mark them in the original DataFrame
        df.loc[first_bullish_idx, 'is_first_bullish_confirmed'] = True
        df.loc[first_bearish_idx, 'is_first_bearish_confirmed'] = True
        # Get SP levels
        # Step 1: Extract sp_high and sp_low values from first bullish confirmations
        sp_levels_bullish = df[df['is_first_bullish_confirmed']][['date', 'close', 'cum_high_prev']]
        sp_levels_bearish = df[df['is_first_bearish_confirmed']][['date', 'close', 'cum_low_prev']]
        sp_levels_bullish['sp_high_bullish'] = sp_levels_bullish['close']
        sp_levels_bullish['sp_low_bullish'] = sp_levels_bullish['cum_high_prev']
        sp_levels_bearish['sp_high_bearish'] = sp_levels_bearish['cum_low_prev']
        sp_levels_bearish['sp_low_bearish'] = sp_levels_bearish['close']
        sp_levels_bullish.drop(['close', 'cum_high_prev'], axis=1, inplace=True)
        sp_levels_bearish.drop(['close', 'cum_low_prev'], axis=1, inplace=True)

        # Step 2: Merge these levels back into the original DataFrame by date
        df = df.merge(sp_levels_bullish, on='date', how='left')
        df = df.merge(sp_levels_bearish, on='date', how='left')

        # Step 3: Forward-fill values within each day — only after confirmation
        df['sp_high_bullish'] = (df.groupby('date')['sp_high_bullish'].transform(lambda x: x.ffill() if x.notna().any() else x))
        df['sp_low_bullish'] = (df.groupby('date')['sp_low_bullish'].transform(lambda x: x.ffill() if x.notna().any() else x))
        df['sp_high_bearish'] = (df.groupby('date')['sp_high_bearish'].transform(lambda x: x.ffill() if x.notna().any() else x))
        df['sp_low_bearish'] = (df.groupby('date')['sp_low_bearish'].transform(lambda x: x.ffill() if x.notna().any() else x))
        
        # Step 4 (Optional): Set values before confirmation to NaN
        df.loc[~df['sp_confirmed_bullish'].cummax(), ['sp_high_bullish', 'sp_low_bullish']] = None
        df.loc[~df['sp_confirmed_bearish'].cummax(), ['sp_high_bearish', 'sp_low_bearish']] = None
        df['sp_bullish_range_pct'] = (df['sp_high_bullish'] - df['sp_low_bullish']) / df['sp_low_bullish'] * 100
        df['sp_bearish_range_pct'] = (df['sp_high_bearish'] - df['sp_low_bearish']) / df['sp_low_bearish'] * 100

        # Cumulative sum of sp_cofirmed_bullish and sp_confirmed_bearish grouped by day
        df['cum_sp_bullish'] = df.groupby('date')['sp_confirmed_bullish'].cumsum()
        df['cum_sp_bearish'] = df.groupby('date')['sp_confirmed_bearish'].cumsum()

        # Single Print Calculations(for 5min)
        df_5min['is_first_bullish_confirmed'] = False
        df_5min['is_first_bearish_confirmed'] = False
        df_5min['candle_count'] = df_5min.groupby(df_5min['date']).cumcount() + 1
        df_5min['cum_high_prev'] = df_5min.groupby('date')['high'].expanding().max().shift(1).reset_index(level=0, drop=True)
        df_5min['cum_low_prev'] = df_5min.groupby('date')['low'].expanding().min().shift(1).reset_index(level=0, drop=True)
        df_5min['sp_confirmed_bullish'] = (df_5min['close'] > df_5min['cum_high_prev']) & (df_5min['close'] > df_5min['open']) & (df_5min['candle_count'] >= 2)
        df_5min['sp_confirmed_bearish'] = (df_5min['close'] < df_5min['cum_low_prev']) & (df_5min['close'] < df_5min['open']) & (df_5min['candle_count'] >= 2)
        bullish_conf_5min = df_5min[df_5min['sp_confirmed_bullish']]
        bearish_conf_5min = df_5min[df_5min['sp_confirmed_bearish']]
        first_bullish_idx_5min = bullish_conf_5min.groupby('date').head(1).index
        first_bearish_idx_5min = bearish_conf_5min.groupby('date').head(1).index
        df_5min.loc[first_bullish_idx_5min, 'is_first_bullish_confirmed'] = True
        df_5min.loc[first_bearish_idx_5min, 'is_first_bearish_confirmed'] = True
        sp_levels_bullish_5min = df_5min[df_5min['is_first_bullish_confirmed']][['date', 'close', 'cum_high_prev']]
        sp_levels_bearish_5min = df_5min[df_5min['is_first_bearish_confirmed']][['date', 'close', 'cum_low_prev']]
        sp_levels_bullish_5min['sp_high_bullish'] = sp_levels_bullish_5min['close']
        sp_levels_bullish_5min['sp_low_bullish'] = sp_levels_bullish_5min['cum_high_prev']
        sp_levels_bearish_5min['sp_high_bearish'] = sp_levels_bearish_5min['cum_low_prev']
        sp_levels_bearish_5min['sp_low_bearish'] = sp_levels_bearish_5min['close']
        sp_levels_bullish_5min.drop(['close', 'cum_high_prev'], axis=1, inplace=True)
        sp_levels_bearish_5min.drop(['close', 'cum_low_prev'], axis=1, inplace=True)
        df_5min = df_5min.merge(sp_levels_bullish_5min, on='date', how='left')
        df_5min = df_5min.merge(sp_levels_bearish_5min, on='date', how='left')
        df_5min['sp_high_bullish'] = (df_5min.groupby('date')['sp_high_bullish'].transform(lambda x: x.ffill() if x.notna().any() else x))
        df_5min['sp_low_bullish'] = (df_5min.groupby('date')['sp_low_bullish'].transform(lambda x: x.ffill() if x.notna().any() else x))
        df_5min['sp_high_bearish'] = (df_5min.groupby('date')['sp_high_bearish'].transform(lambda x: x.ffill() if x.notna().any() else x))
        df_5min['sp_low_bearish'] = (df_5min.groupby('date')['sp_low_bearish'].transform(lambda x: x.ffill() if x.notna().any() else x))
        df_5min.loc[~df_5min['sp_confirmed_bullish'].cummax(), ['sp_high_bullish', 'sp_low_bullish']] = None
        df_5min.loc[~df_5min['sp_confirmed_bearish'].cummax(), ['sp_high_bearish', 'sp_low_bearish']] = None
        df_5min['sp_bullish_range_pct'] = (df_5min['sp_high_bullish'] - df_5min['sp_low_bullish']) / df_5min['sp_low_bullish'] * 100
        df_5min['sp_bearish_range_pct'] = (df_5min['sp_high_bearish'] - df_5min['sp_low_bearish']) / df_5min['sp_low_bearish'] * 100
        df_5min['cum_sp_bullish'] = df_5min.groupby('date')['sp_confirmed_bullish'].cumsum()
        df_5min['cum_sp_bearish'] = df_5min.groupby('date')['sp_confirmed_bearish'].cumsum()
        #self.logger.info(f"Calculated Single Print for {self.symbol}")

        # Cumulative intraday volume(Needed for both 15m and 5m) 
        df['cum_intraday_volume'] = df.groupby('date')['volume'].cumsum()
        df['curtop'] = df.groupby('date')['high'].cummax()
        df['curbot'] = df.groupby('date')['low'].cummin()
        df['today_range'] = df['curtop'] - df['curbot']
        df['today_range_pct'] = df['today_range'] / df['atr_10'] 
        df['volume_range_pct'] = (df['cum_intraday_volume'] / df['volume_10']) / df['today_range_pct']

        df_5min['cum_intraday_volume'] = df_5min.groupby('date')['volume'].cumsum()
        df_5min['curtop'] = df_5min.groupby('date')['high'].cummax()
        df_5min['curbot'] = df_5min.groupby('date')['low'].cummin()
        df_5min['today_range'] = df_5min['curtop'] - df_5min['curbot']
        df_5min['today_range_pct'] = df_5min['today_range'] / df_5min['atr_10'] 
        df_5min['volume_range_pct'] = (df_5min['cum_intraday_volume'] / df_5min['volume_10']) / df_5min['today_range_pct']

        # Strategy definitions
        df['s_8'] = (df['time'].dt.time >= time(4, 00)) & (df['time'].dt.time < time(8, 15)) & (df['cum_sp_bullish'] >= 1) & (df['sp_bullish_range_pct'] > 1) & (df['zl_macd_signal'] == -1) & (df['volume_range_pct'] > 1) 
        df['strategy_8'] = False 
        # Get the index of first True condition per day
        first_true_idx_8 = df[df['s_8']].groupby('date').head(1).index
        # Set final_flag to True only at these rows
        df.loc[first_true_idx_8, 'strategy_8'] = True  

        df['s_12'] = (df['time'].dt.time >= time(4, 00)) & (df['time'].dt.time < time(8, 15)) & (df['cum_sp_bearish'] >= 1) & (df['sp_bearish_range_pct'] > 0.8) & (df['zl_macd_signal'] == 1) & (df['volume_range_pct'] < 0.2)
        df['strategy_12'] = False 
        first_true_idx_12 = df[df['s_12']].groupby('date').head(1).index
        df.loc[first_true_idx_12, 'strategy_12'] = True

        df_5min['s_10'] = (df_5min['time'].dt.time >= time(3, 50)) & (df_5min['time'].dt.time < time(8, 15)) & (df_5min['cum_sp_bearish'] >= 1) & (df_5min['sp_bearish_range_pct'] > 0.6) & (df_5min['close'] < df_5min['ema_50']) & (df_5min['close'] < df_5min['ema_100']) & (df_5min['close'] < df_5min['ema_200']) & (df_5min['is_range_bearish']) & (df_5min['volume_range_pct'] > 0.2) & (df_5min['volume_range_pct'] < 0.3)
        df_5min['strategy_10'] = False 
        first_true_idx_10 = df_5min[df_5min['s_10']].groupby('date').head(1).index
        df_5min.loc[first_true_idx_10, 'strategy_10'] = True

        df_5min['s_11'] = (df_5min['time'].dt.time >= time(3, 50)) & (df_5min['time'].dt.time < time(8, 15)) & (df_5min['cum_sp_bullish'] >= 1) & (df_5min['sp_bullish_range_pct'] > 0.8) & (df_5min['close'] > df_5min['ema_50']) & (df_5min['close'] > df_5min['ema_100']) & (df_5min['close'] > df_5min['ema_200']) & (df_5min['is_range_bullish']) & (df_5min['volume_range_pct'] > 0.2) & (df_5min['volume_range_pct'] < 0.3)
        df_5min['strategy_11'] = False 
        first_true_idx_11 = df_5min[df_5min['s_11']].groupby('date').head(1).index
        df_5min.loc[first_true_idx_11, 'strategy_11'] = True

        # Outputs to see all the indicators
        #df.to_csv('df.csv', index=False)
        #df_5min.to_csv('df_5min.csv', index=False)

        # Drop temporary 'date' column if needed
        df.drop('date', axis=1, inplace=True)
        df_5min.drop('date', axis=1, inplace=True)
        return df, df_5min

    def run(self):
        self.logger.info(f"Running backtest from {self.start_date} to {self.end_date}")
        trades = []
        self.trailing_chart_data = []
        in_position = False

        df_all = self.fetch_lookback_data_2(self.start_date - timedelta(days=20), self.end_date, '15m')
        df_5min_all = self.fetch_lookback_data_2(self.start_date - timedelta(days=20), self.end_date, '5m')
        df_min_all = self.fetch_lookback_data_2(self.start_date - timedelta(days=20), self.end_date, '1m')
        df_daily_all = self.fetch_lookback_data_2(self.start_date - timedelta(days=20), self.end_date, 'd')

        #self.logger.info(f"df_all shape: {df_all.shape}")
        #self.logger.info(f"df_5min_all shape: {df_5min_all.shape}")
        #self.logger.info(f"df_min_all shape: {df_min_all.shape}")
        #self.logger.info(f"df_daily_all shape: {df_daily_all.shape}")

        for day in self.daterange():
            # Filter data
            df = df_all[(df_all['time'].dt.date >= (day - timedelta(days = 5))) & (df_all['time'].dt.date <= day)].copy()
            df_5min = df_5min_all[(df_5min_all['time'].dt.date >= (day - timedelta(days = 7))) & (df_5min_all['time'].dt.date <= day)].copy()
            df_min = df_min_all[(df_min_all['time'].dt.date >= (day - timedelta(days = 2))) & (df_min_all['time'].dt.date <= day)].copy()
            df_daily = df_daily_all[(df_daily_all['time'].dt.date >= (day - timedelta(days = 20))) & (df_daily_all['time'].dt.date <= day)].copy()
            
            #self.logger.info(f"df shape: {df.shape}")
            #self.logger.info(f"df_5min shape: {df_5min.shape}")
            #self.logger.info(f"df_min shape: {df_min.shape}")
            #self.logger.info(f"df_daily shape: {df_daily.shape}")
            #df = self.fetch_lookback_data(day, '15m', 5)
            #df_daily = self.fetch_lookback_data(day, 'd', 20)
            #df_min = self.fetch_lookback_data(day, '1m', 2)
            #df_5min = self.fetch_lookback_data(day, '5m', 7)

            if df.empty or df_5min.empty or df_daily.empty or df_min.empty:
                continue

            df, df_5min = self.trading_indicator_calculations(df, df_daily, df_5min)

            start_dt = datetime.combine(day, time.min).replace(tzinfo=pytz.UTC)
            end_dt = datetime.combine(day, time.max).replace(tzinfo=pytz.UTC)
            df_today = df[(df['time'] >= start_dt) & (df['time'] <= end_dt)].copy()
            df_today_5min = df_5min[(df_5min['time'] >= start_dt) & (df_5min['time'] <= end_dt)].copy()
            df_min_today = df_min[(df_min['time'] >= start_dt) & (df_min['time'] <= end_dt)].copy()

            entry_row = None

            # 15m dataframe - Strategy 8 and 12
            for i in range(1, len(df_today)):
                prev = df_today.iloc[i - 1]
                curr = df_today.iloc[i]

                curr_ist_time = curr['time'].astimezone(IST).time()  
                curr_ist_time_2 = curr['time'].astimezone(IST)

                buy = curr['strategy_12']
                sell = False
                short = curr['strategy_8']
                cover = False  

                # ENTRY: Long
                if not in_position and buy and curr_ist_time <= time(14, 30) and self.position == 0:
                    self.logger.info(f"[{curr_ist_time_2}] LONG ENTRY triggered at {curr['close']}")
                    self.position = 1
                    entry_row = curr
                    capital_per_trade = self.capital * self.leverage * (self.capital_alloc_pct / 100)
                    quantity = int(capital_per_trade / entry_row['close'])
                    trailing_active = False
                    trail_stop = None
                    last_trail_price = None
                    trail_history = []
                    in_position = True
                    self.entry_price = entry_row['close']
                    strategy_id = '12'
                    entry_time = curr['time'] + timedelta(minutes=14) # 15min as we are working on 15min candles, else replace it with 5min
                    #self.logger.info(f"Entry confirmed: position={self.position}, entry_price={entry_row['close']}, in_position={in_position}")
                    break  # Exit the 15m loop after entry

                # ENTRY: Short
                if not in_position and short and curr_ist_time <= time(14, 30) and self.position == 0:
                    self.logger.info(f"[{curr_ist_time_2}] SHORT ENTRY triggered at {curr['close']}")
                    self.position = -1
                    entry_row = curr
                    capital_per_trade = self.capital * self.leverage * (self.capital_alloc_pct / 100)
                    quantity = int(capital_per_trade / entry_row['close'])
                    trailing_active = False
                    trail_stop = None
                    last_trail_price = None
                    trail_history = []
                    in_position = True
                    self.entry_price = entry_row['close']
                    strategy_id = '8'
                    entry_time = curr['time'] + timedelta(minutes=14) # 15min as we are working on 15min candles, else replace it with 5min
                    #self.logger.info(f"Entry confirmed: position={self.position}, entry_price={entry_row['close']}, in_position={in_position}")
                    break  # Exit the 15m loop after entry

                #self.logger.info(f"[{curr_ist_time_2}] Position check: position={self.position}, in_position={in_position}, entry_row={entry_row is not None}")
            # EXIT
            # TRADE MONITORING WHILE IN POSITION
            if self.position != 0 and entry_row is not None and in_position:               
                # Find the corresponding minute in df_min after our entry
                min_entries = df_min_today[df_min_today['time'] >= entry_time]
                
                for i in range(len(min_entries)):
                    curr_min = min_entries.iloc[i]
                    curr_min_ist_time = curr_min['time'].astimezone(IST).time()
                    curr_min_ist_time_2 = curr_min['time'].astimezone(IST)
                    price = curr_min['close']
                    entry_price = entry_row['close']
                    exit_row = None
                    exit_reason = None                           
                    #self.logger.info(f"[{curr_ist_time}] TRADE MONITORING: Position: {self.position}, Entry Price: {entry_price}, Current Price: {price}")

                    is_long = self.position == 1
                    is_short = self.position == -1
                    price_change = price - entry_price
                    pct_move = price_change / entry_price

                    # Targets
                    tp_hit = pct_move >= self.tp_pct if is_long else pct_move <= -self.tp_pct
                    sl_hit = pct_move <= -self.sl_pct if is_long else pct_move >= self.sl_pct
                    trail_trigger_pct = self.trail_activation_pct if is_long else -self.trail_activation_pct
                    trail_increment = self.trail_increment_pct * entry_price
                    trail_gap = self.trail_stop_gap_pct * entry_price
                    
                    #self.logger.info(f"[{curr_ist_time}] Evaluating exit for {'SHORT' if self.position == -1 else 'LONG'} at price {price}")
                    #self.logger.info(f"[{curr_ist_time_2}] Evaluating exit for {'SHORT' if self.position == -1 else 'LONG'} at price {price}")

                    # TP
                    if tp_hit:
                        exit_row = curr_min
                        exit_reason = "TP"
                        self.logger.info(f"[{curr_min_ist_time_2}] TP HIT at {price}")

                    # SL
                    elif sl_hit:
                        exit_row = curr_min
                        exit_reason = "SL"
                        self.logger.info(f"[{curr_min_ist_time_2}] SL HIT at {price}")                        

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
                                'time': curr_min_ist_time_2,
                                'value': trail_stop
                            })

                        # Price hit trailing stop
                        if (is_long and price <= trail_stop) or (is_short and price >= trail_stop):
                            exit_row = curr_min
                            exit_reason = "TRAIL"
                            self.logger.info(f"[{curr_min_ist_time_2}] TRAIL STOP HIT at {price} vs stop {trail_stop}")
                      
                    # Activate trailing
                    elif (pct_move >= self.trail_activation_pct if is_long else pct_move <= -self.trail_activation_pct):
                        trailing_active = True
                        trail_stop = price - trail_gap if is_long else price + trail_gap
                        last_trail_price = price

                    # Strategy exit signal
                    # elif (crossunder if is_long else crossover):
                    #     exit_row = curr
                    #     exit_reason = "CROSSOVER" if is_long else "CROSSUNDER"
                    #     self.logger.info(f"[{curr_ist_time_2}] CROSSOVER HIT for SHORT at EMA fast {curr['ema_fast']} vs slow {curr['ema_slow']}")

                    # Force exit based on direction and time (in UTC)
                    if exit_row is None:
                        #self.logger.info(f"[{curr_ist_time_2}] No exit condition met, checking force exit conditions")
                        if is_long and curr_min_ist_time   >= time(15, 9):  # 3:10 PM IST
                            exit_row = curr_min
                            exit_reason = "FORCE_EXIT_1510"
                            self.logger.info(f"[{curr_min_ist_time_2}] FORCE EXIT triggered for {'LONG' if is_long else 'SHORT'}")

                        elif is_short and curr_min_ist_time  >= time(14, 39):  # 2:40 PM IST
                            exit_row = curr_min
                            exit_reason = "FORCE_EXIT_1440"
                            self.logger.info(f"[{curr_min_ist_time_2}] FORCE EXIT triggered for {'LONG' if is_long else 'SHORT'}")

                    # Process exit
                    if exit_row is not None:
                        self.logger.info(f"[{curr_min_ist_time_2}] EXITING TRADE: {exit_reason} at {price}")
                        trade_df = df_min_today[(df_min_today['time'] >= entry_time) & (df_min_today['time'] <= curr_min['time'])]
                        trade_close = trade_df['close']

                        mae = (trade_close.min() - entry_price if is_long else entry_price - trade_close.max()) if not trade_df.empty else 0
                        mfe = (trade_close.max() - entry_price if is_long else entry_price - trade_close.min()) if not trade_df.empty else 0
                        pnl = (price - entry_price if is_long else entry_price - price)                        
                    
                        trades.append({
                            'symbol': self.symbol,
                            'strategy': strategy_id,
                            'quantity': quantity,
                            'entry_time': entry_time.astimezone(IST).strftime("%Y-%m-%d %H:%M:%S"),
                            'entry_price': round(entry_price, 2),
                            'exit_time': exit_row['time'].astimezone(IST).strftime("%Y-%m-%d %H:%M:%S"),
                            'exit_price': round(price, 2),
                            'exit_reason': exit_reason,
                            'gross_pnl': round(pnl * quantity, 2),
                            'cumulative_pnl': 0,  # Filled later
                            'mae': round(mae * quantity, 2),
                            'mfe': round(mfe * quantity, 2),
                            'holding_period': str(exit_row['time'] - entry_row['time']),
                            'direction': "LONG" if is_long else "SHORT",                            
                            'capital_used': round(quantity * price, 2),
                            'tax': round(quantity * price * 2 * 0.0002, 2),
                            'brokerage': 0,
                            'net_pnl': round((pnl * quantity) - (2 * quantity * price * 0.0002) - 0, 2),
                        })                        

                        if exit_reason == "TRAIL":
                            self.trailing_chart_data.append({
                                'symbol': self.symbol,
                                'entry_time': entry_time,
                                'exit_time': exit_row['time'],
                                'entry_price': price,
                                'df': df_min_today.copy(),
                                'trail_stops': trail_history
                        })
                            
                        # Reset
                        self.position = 0
                        self.entry_price = None  
                        entry_time = None
                        entry_row = None
                        trailing_active = False
                        trail_stop = None
                        last_trail_price = None
                        in_position = False                        
                        break  # Exit the 1m loop after exit
                        
            
            entry_row = None
            # 5m dataframe - Strategy 10 and 11
            for i in range(1, len(df_today_5min)):
                prev = df_today_5min.iloc[i - 1]
                curr = df_today_5min.iloc[i]

                curr_ist_time = curr['time'].astimezone(IST).time()  
                curr_ist_time_2 = curr['time'].astimezone(IST)

                buy = curr['strategy_11']
                sell = False
                short = curr['strategy_10']
                cover = False  

                # ENTRY: Long
                if not in_position and buy and curr_ist_time <= time(14, 30) and self.position == 0:
                    self.logger.info(f"[{curr_ist_time_2}] LONG ENTRY triggered at {curr['close']}")
                    self.position = 1
                    entry_row = curr
                    capital_per_trade = self.capital * self.leverage * (self.capital_alloc_pct / 100)
                    quantity = int(capital_per_trade / entry_row['close'])
                    trailing_active = False
                    trail_stop = None
                    last_trail_price = None
                    trail_history = []
                    in_position = True
                    self.entry_price = entry_row['close']
                    strategy_id = '11'
                    entry_time = curr['time'] + timedelta(minutes=4) # 5min as we are working on 5min candles, else replace it with 5min
                    #self.logger.info(f"Entry confirmed: position={self.position}, entry_price={entry_row['close']}, in_position={in_position}")
                    break  # Exit the 15m loop after entry

                # ENTRY: Short
                if not in_position and short and curr_ist_time <= time(14, 30) and self.position == 0:
                    self.logger.info(f"[{curr_ist_time_2}] SHORT ENTRY triggered at {curr['close']}")
                    self.position = -1
                    entry_row = curr
                    capital_per_trade = self.capital * self.leverage * (self.capital_alloc_pct / 100)
                    quantity = int(capital_per_trade / entry_row['close'])
                    trailing_active = False
                    trail_stop = None
                    last_trail_price = None
                    trail_history = []
                    in_position = True
                    self.entry_price = entry_row['close']
                    strategy_id = '10'
                    entry_time = curr['time'] + timedelta(minutes=4) # 5min as we are working on 5min candles, else replace it with 15min
                    #self.logger.info(f"Entry confirmed: position={self.position}, entry_price={entry_row['close']}, in_position={in_position}")
                    break  # Exit the 15m loop after entry

                #self.logger.info(f"[{curr_ist_time_2}] Position check: position={self.position}, in_position={in_position}, entry_row={entry_row is not None}")
            # EXIT
            # TRADE MONITORING WHILE IN POSITION
            if self.position != 0 and entry_row is not None and in_position:               
                # Find the corresponding minute in df_min after our entry
                min_entries = df_min_today[df_min_today['time'] >= entry_time]
                
                for i in range(len(min_entries)):
                    curr_min = min_entries.iloc[i]
                    curr_min_ist_time = curr_min['time'].astimezone(IST).time()
                    curr_min_ist_time_2 = curr_min['time'].astimezone(IST)
                    price = curr_min['close']
                    entry_price = entry_row['close']
                    exit_row = None
                    exit_reason = None                           
                    #self.logger.info(f"[{curr_ist_time}] TRADE MONITORING: Position: {self.position}, Entry Price: {entry_price}, Current Price: {price}")

                    is_long = self.position == 1
                    is_short = self.position == -1
                    price_change = price - entry_price
                    pct_move = price_change / entry_price

                    # Targets
                    tp_hit = pct_move >= self.tp_pct if is_long else pct_move <= -self.tp_pct
                    sl_hit = pct_move <= -self.sl_pct if is_long else pct_move >= self.sl_pct
                    trail_trigger_pct = self.trail_activation_pct if is_long else -self.trail_activation_pct
                    trail_increment = self.trail_increment_pct * entry_price
                    trail_gap = self.trail_stop_gap_pct * entry_price
                    
                    #self.logger.info(f"[{curr_ist_time}] Evaluating exit for {'SHORT' if self.position == -1 else 'LONG'} at price {price}")
                    #self.logger.info(f"[{curr_ist_time_2}] Evaluating exit for {'SHORT' if self.position == -1 else 'LONG'} at price {price}")

                    # TP
                    if tp_hit:
                        exit_row = curr_min
                        exit_reason = "TP"
                        self.logger.info(f"[{curr_min_ist_time_2}] TP HIT at {price}")

                    # SL
                    elif sl_hit:
                        exit_row = curr_min
                        exit_reason = "SL"
                        self.logger.info(f"[{curr_min_ist_time_2}] SL HIT at {price}")                        

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
                                'time': curr_min_ist_time_2,
                                'value': trail_stop
                            })

                        # Price hit trailing stop
                        if (is_long and price <= trail_stop) or (is_short and price >= trail_stop):
                            exit_row = curr_min
                            exit_reason = "TRAIL"
                            self.logger.info(f"[{curr_min_ist_time_2}] TRAIL STOP HIT at {price} vs stop {trail_stop}")
                      
                    # Activate trailing
                    elif (pct_move >= self.trail_activation_pct if is_long else pct_move <= -self.trail_activation_pct):
                        trailing_active = True
                        trail_stop = price - trail_gap if is_long else price + trail_gap
                        last_trail_price = price

                    # Strategy exit signal
                    # elif (crossunder if is_long else crossover):
                    #     exit_row = curr
                    #     exit_reason = "CROSSOVER" if is_long else "CROSSUNDER"
                    #     self.logger.info(f"[{curr_ist_time_2}] CROSSOVER HIT for SHORT at EMA fast {curr['ema_fast']} vs slow {curr['ema_slow']}")

                    # Force exit based on direction and time (in UTC)
                    if exit_row is None:
                        #self.logger.info(f"[{curr_ist_time_2}] No exit condition met, checking force exit conditions")
                        if is_long and curr_min_ist_time   >= time(15, 9):  # 3:10 PM IST
                            exit_row = curr_min
                            exit_reason = "FORCE_EXIT_1510"
                            self.logger.info(f"[{curr_min_ist_time_2}] FORCE EXIT triggered for {'LONG' if is_long else 'SHORT'}")

                        elif is_short and curr_min_ist_time  >= time(14, 39):  # 2:40 PM IST
                            exit_row = curr_min
                            exit_reason = "FORCE_EXIT_1440"
                            self.logger.info(f"[{curr_min_ist_time_2}] FORCE EXIT triggered for {'LONG' if is_long else 'SHORT'}")

                    # Process exit
                    if exit_row is not None:
                        self.logger.info(f"[{curr_min_ist_time_2}] EXITING TRADE: {exit_reason} at {price}")
                        trade_df = df_min_today[(df_min_today['time'] >= entry_time) & (df_min_today['time'] <= curr_min['time'])]
                        trade_close = trade_df['close']

                        mae = (trade_close.min() - entry_price if is_long else entry_price - trade_close.max()) if not trade_df.empty else 0
                        mfe = (trade_close.max() - entry_price if is_long else entry_price - trade_close.min()) if not trade_df.empty else 0
                        pnl = (price - entry_price if is_long else entry_price - price)                        
                    
                        trades.append({
                            'symbol': self.symbol,
                            'strategy': strategy_id,
                            'quantity': quantity,
                            'entry_time': entry_time.astimezone(IST).strftime("%Y-%m-%d %H:%M:%S"),
                            'entry_price': round(entry_price, 2),
                            'exit_time': exit_row['time'].astimezone(IST).strftime("%Y-%m-%d %H:%M:%S"),
                            'exit_price': round(price, 2),
                            'exit_reason': exit_reason,
                            'gross_pnl': round(pnl * quantity, 2),
                            'cumulative_pnl': 0,  # Filled later
                            'mae': round(mae * quantity, 2),
                            'mfe': round(mfe * quantity, 2),
                            'holding_period': str(exit_row['time'] - entry_row['time']),
                            'direction': "LONG" if is_long else "SHORT",                            
                            'capital_used': round(quantity * price, 2),
                            'tax': round(quantity * price * 2 * 0.0002, 2),
                            'brokerage': 0,
                            'net_pnl': round((pnl * quantity) - (2 * quantity * price * 0.0002) - 0, 2),
                        })                        

                        if exit_reason == "TRAIL":
                            self.trailing_chart_data.append({
                                'symbol': self.symbol,
                                'entry_time': entry_time,
                                'exit_time': exit_row['time'],
                                'entry_price': price,
                                'df': df_min_today.copy(),
                                'trail_stops': trail_history
                        })
                        
                        # Reset
                        self.position = 0
                        self.entry_price = None  
                        entry_time = None
                        entry_row = None
                        trailing_active = False
                        trail_stop = None
                        last_trail_price = None
                        in_position = False 
                        break  # only one trade per symbol per strategy per day
            # Clean up
            # del df_today
            # del df_today_5min
            # del df_min_today
            # del df
            # del df_5min
            # del df_min
            # del df_daily
            # gc.collect()
            
        self.trades = pd.DataFrame(trades)
        return self.trades

    
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

