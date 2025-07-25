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
        
    def calculate_all_indicators_once(self, df_all_dict):
        """
        Calculate all indicators once for the entire dataset
        Returns: Dictionary with pre-calculated dataframes
        """
        self.logger.info(f"Calculating indicators once for entire dataset for {self.symbol}")
        
        # Extract dataframes
        df_15m = df_all_dict['15m'].copy()
        df_5m = df_all_dict['5m'].copy()
        df_1m = df_all_dict['1m'].copy()
        df_daily = df_all_dict['d'].copy()
        
        # === DAILY INDICATORS (ATR & Volume) ===
        atr_period = 14
        volume_period = 14
        df_daily['prev_close'] = df_daily['close'].shift(1)
        df_daily['tr1'] = df_daily['high'] - df_daily['low']
        df_daily['tr2'] = abs(df_daily['high'] - df_daily['prev_close'])
        df_daily['tr3'] = abs(df_daily['low'] - df_daily['prev_close'])
        df_daily['tr'] = df_daily[['tr1', 'tr2', 'tr3']].max(axis=1)
        df_daily['atr_10'] = df_daily['tr'].ewm(span=10, adjust=False).mean()
        df_daily['volume_10'] = df_daily['volume'].rolling(window=10).mean()
        df_daily['atr_14'] = df_daily['tr'].ewm(span=14, adjust=False).mean()
        df_daily['volume_14'] = df_daily['volume'].rolling(window=14).mean()
        df_daily.drop(['prev_close', 'tr1', 'tr2', 'tr3', 'tr'], axis=1, inplace=True)
        
        # Add date columns for merging
        df_15m['date'] = pd.to_datetime(df_15m['time'].dt.date)
        df_5m['date'] = pd.to_datetime(df_5m['time'].dt.date)
        df_daily['date'] = pd.to_datetime(df_daily['time'].dt.date)
        
        # Merge ATR from daily data
        df_15m = df_15m.merge(df_daily[['date', 'atr_10', 'volume_10', 'atr_14', 'volume_14']], on='date', how='left')
        df_5m = df_5m.merge(df_daily[['date', 'atr_10', 'volume_10', 'atr_14', 'volume_14']], on='date', how='left')
        
        # === 5MIN INDICATORS (EMAs) ===
        df_5m['ema_50'] = df_5m['close'].ewm(span=50, adjust=False).mean()
        df_5m['ema_100'] = df_5m['close'].ewm(span=100, adjust=False).mean()
        df_5m['ema_200'] = df_5m['close'].ewm(span=200, adjust=False).mean()
        
        # === RANGE CALCULATIONS - 15m ===
        df_15m['range'] = df_15m['high'] - df_15m['low']
        df_15m['date_only'] = df_15m['time'].dt.date
        df_15m['avg_range_all'] = df_15m.groupby('date_only')['range'].expanding().mean().reset_index(level=0, drop=True)
        avg_ex_first_30min_15m = df_15m.groupby('date_only').apply(self.exclude_first_30min).reset_index(level=0, drop=True)
        df_15m['avg_range_ex_first_30min'] = avg_ex_first_30min_15m.reindex(df_15m.index).ffill()
        df_15m['is_range_bullish'] = (
            (df_15m['range'] > 0.7 * df_15m['avg_range_ex_first_30min']) & 
            (df_15m['close'] > df_15m['open']) & 
            (df_15m['close'] > (((df_15m['high'] - df_15m['open']) * 0.5) + df_15m['open']))
        )
        df_15m['is_range_bearish'] = (
            (df_15m['range'] > 0.7 * df_15m['avg_range_ex_first_30min']) & 
            (df_15m['close'] < df_15m['open']) & 
            (df_15m['close'] < (((df_15m['open'] - df_15m['low']) * 0.5) + df_15m['low']))
        )
        df_15m.drop('date_only', axis=1, inplace=True)
        
        # === RANGE CALCULATIONS - 5m ===
        df_5m['range'] = df_5m['high'] - df_5m['low']
        df_5m['date_only'] = df_5m['time'].dt.date
        df_5m['avg_range_all'] = df_5m.groupby('date_only')['range'].expanding().mean().reset_index(level=0, drop=True)
        avg_ex_first_30min_5m = df_5m.groupby('date_only').apply(self.exclude_first_30min).reset_index(level=0, drop=True)
        df_5m['avg_range_ex_first_30min'] = avg_ex_first_30min_5m.reindex(df_5m.index).ffill()
        df_5m['is_range_bullish'] = (
            (df_5m['range'] > 0.7 * df_5m['avg_range_ex_first_30min']) & 
            (df_5m['close'] > df_5m['open']) & 
            (df_5m['close'] > (((df_5m['high'] - df_5m['open']) * 0.5) + df_5m['open']))
        )
        df_5m['is_range_bearish'] = (
            (df_5m['range'] > 0.7 * df_5m['avg_range_ex_first_30min']) & 
            (df_5m['close'] < df_5m['open']) & 
            (df_5m['close'] < (((df_5m['open'] - df_5m['low']) * 0.5) + df_5m['low']))
        )
        df_5m.drop('date_only', axis=1, inplace=True)
        
        # === ZERO LAG MACD (15m only) ===
        fast_period, slow_period, signal_period = 12, 26, 9
        df_15m['fast_zlema'] = self.zero_lag_ema(df_15m['close'], fast_period)
        df_15m['slow_zlema'] = self.zero_lag_ema(df_15m['close'], slow_period)
        df_15m['zl_macd'] = df_15m['fast_zlema'] - df_15m['slow_zlema']
        df_15m['zl_signal'] = df_15m['zl_macd'].ewm(span=signal_period, adjust=False).mean()
        df_15m['zl_hist'] = df_15m['zl_macd'] - df_15m['zl_signal']
        
        # Generate MACD Signals
        df_15m['zl_macd_signal'] = 0
        df_15m.loc[(df_15m['zl_macd'] > df_15m['zl_signal']) & 
                (df_15m['zl_macd'].shift(1) <= df_15m['zl_signal'].shift(1)), 'zl_macd_signal'] = 1
        df_15m.loc[(df_15m['zl_macd'] < df_15m['zl_signal']) & 
                (df_15m['zl_macd'].shift(1) >= df_15m['zl_signal'].shift(1)), 'zl_macd_signal'] = -1
        df_15m.drop(['fast_zlema', 'slow_zlema', 'zl_macd', 'zl_signal', 'zl_hist'], axis=1, inplace=True)
        
        # === SINGLE PRINT CALCULATIONS - 15m ===
        df_15m['is_first_bullish_confirmed'] = False
        df_15m['is_first_bearish_confirmed'] = False
        df_15m['candle_count'] = df_15m.groupby(df_15m['date']).cumcount() + 1
        df_15m['cum_high_prev'] = df_15m.groupby('date')['high'].expanding().max().shift(1).reset_index(level=0, drop=True)
        df_15m['cum_low_prev'] = df_15m.groupby('date')['low'].expanding().min().shift(1).reset_index(level=0, drop=True)
        df_15m['sp_confirmed_bullish'] = (
            (df_15m['close'] > df_15m['cum_high_prev']) & 
            (df_15m['close'] > df_15m['open']) & 
            (df_15m['candle_count'] >= 2)
        )
        df_15m['sp_confirmed_bearish'] = (
            (df_15m['close'] < df_15m['cum_low_prev']) & 
            (df_15m['close'] < df_15m['open']) & 
            (df_15m['candle_count'] >= 2)
        )
        
        # Mark first confirmations
        bullish_conf_15m = df_15m[df_15m['sp_confirmed_bullish']]
        bearish_conf_15m = df_15m[df_15m['sp_confirmed_bearish']]
        first_bullish_idx_15m = bullish_conf_15m.groupby('date').head(1).index
        first_bearish_idx_15m = bearish_conf_15m.groupby('date').head(1).index
        df_15m.loc[first_bullish_idx_15m, 'is_first_bullish_confirmed'] = True
        df_15m.loc[first_bearish_idx_15m, 'is_first_bearish_confirmed'] = True
        
        # SP levels for 15m
        sp_levels_bullish_15m = df_15m[df_15m['is_first_bullish_confirmed']][['date', 'close', 'cum_high_prev']]
        sp_levels_bearish_15m = df_15m[df_15m['is_first_bearish_confirmed']][['date', 'close', 'cum_low_prev']]
        sp_levels_bullish_15m['sp_high_bullish'] = sp_levels_bullish_15m['close']
        sp_levels_bullish_15m['sp_low_bullish'] = sp_levels_bullish_15m['cum_high_prev']
        sp_levels_bearish_15m['sp_high_bearish'] = sp_levels_bearish_15m['cum_low_prev']
        sp_levels_bearish_15m['sp_low_bearish'] = sp_levels_bearish_15m['close']
        sp_levels_bullish_15m.drop(['close', 'cum_high_prev'], axis=1, inplace=True)
        sp_levels_bearish_15m.drop(['close', 'cum_low_prev'], axis=1, inplace=True)
        
        # Merge back for 15m
        df_15m = df_15m.merge(sp_levels_bullish_15m, on='date', how='left')
        df_15m = df_15m.merge(sp_levels_bearish_15m, on='date', how='left')
        
        # Forward fill SP levels for 15m
        df_15m['sp_high_bullish'] = df_15m.groupby('date')['sp_high_bullish'].transform(lambda x: x.ffill() if x.notna().any() else x)
        df_15m['sp_low_bullish'] = df_15m.groupby('date')['sp_low_bullish'].transform(lambda x: x.ffill() if x.notna().any() else x)
        df_15m['sp_high_bearish'] = df_15m.groupby('date')['sp_high_bearish'].transform(lambda x: x.ffill() if x.notna().any() else x)
        df_15m['sp_low_bearish'] = df_15m.groupby('date')['sp_low_bearish'].transform(lambda x: x.ffill() if x.notna().any() else x)
        
        # Set pre-confirmation values to NaN for 15m
        df_15m.loc[~df_15m['sp_confirmed_bullish'].cummax(), ['sp_high_bullish', 'sp_low_bullish']] = None
        df_15m.loc[~df_15m['sp_confirmed_bearish'].cummax(), ['sp_high_bearish', 'sp_low_bearish']] = None
        
        # Calculate SP range percentages for 15m
        df_15m['sp_bullish_range_pct'] = (df_15m['sp_high_bullish'] - df_15m['sp_low_bullish']) / df_15m['sp_low_bullish'] * 100
        df_15m['sp_bearish_range_pct'] = (df_15m['sp_high_bearish'] - df_15m['sp_low_bearish']) / df_15m['sp_low_bearish'] * 100
        df_15m['cum_sp_bullish'] = df_15m.groupby('date')['sp_confirmed_bullish'].cumsum()
        df_15m['cum_sp_bearish'] = df_15m.groupby('date')['sp_confirmed_bearish'].cumsum()
        
        # === SINGLE PRINT CALCULATIONS - 5m ===
        df_5m['is_first_bullish_confirmed'] = False
        df_5m['is_first_bearish_confirmed'] = False
        df_5m['candle_count'] = df_5m.groupby(df_5m['date']).cumcount() + 1
        df_5m['cum_high_prev'] = df_5m.groupby('date')['high'].expanding().max().shift(1).reset_index(level=0, drop=True)
        df_5m['cum_low_prev'] = df_5m.groupby('date')['low'].expanding().min().shift(1).reset_index(level=0, drop=True)
        df_5m['sp_confirmed_bullish'] = (
            (df_5m['close'] > df_5m['cum_high_prev']) & 
            (df_5m['close'] > df_5m['open']) & 
            (df_5m['candle_count'] >= 2)
        )
        df_5m['sp_confirmed_bearish'] = (
            (df_5m['close'] < df_5m['cum_low_prev']) & 
            (df_5m['close'] < df_5m['open']) & 
            (df_5m['candle_count'] >= 2)
        )
        
        # Mark first confirmations for 5m
        bullish_conf_5m = df_5m[df_5m['sp_confirmed_bullish']]
        bearish_conf_5m = df_5m[df_5m['sp_confirmed_bearish']]
        first_bullish_idx_5m = bullish_conf_5m.groupby('date').head(1).index
        first_bearish_idx_5m = bearish_conf_5m.groupby('date').head(1).index
        df_5m.loc[first_bullish_idx_5m, 'is_first_bullish_confirmed'] = True
        df_5m.loc[first_bearish_idx_5m, 'is_first_bearish_confirmed'] = True
        
        # SP levels for 5m
        sp_levels_bullish_5m = df_5m[df_5m['is_first_bullish_confirmed']][['date', 'close', 'cum_high_prev']]
        sp_levels_bearish_5m = df_5m[df_5m['is_first_bearish_confirmed']][['date', 'close', 'cum_low_prev']]
        sp_levels_bullish_5m['sp_high_bullish'] = sp_levels_bullish_5m['close']
        sp_levels_bullish_5m['sp_low_bullish'] = sp_levels_bullish_5m['cum_high_prev']
        sp_levels_bearish_5m['sp_high_bearish'] = sp_levels_bearish_5m['cum_low_prev']
        sp_levels_bearish_5m['sp_low_bearish'] = sp_levels_bearish_5m['close']
        sp_levels_bullish_5m.drop(['close', 'cum_high_prev'], axis=1, inplace=True)
        sp_levels_bearish_5m.drop(['close', 'cum_low_prev'], axis=1, inplace=True)
        
        # Merge back for 5m
        df_5m = df_5m.merge(sp_levels_bullish_5m, on='date', how='left')
        df_5m = df_5m.merge(sp_levels_bearish_5m, on='date', how='left')
        
        # Forward fill SP levels for 5m
        df_5m['sp_high_bullish'] = df_5m.groupby('date')['sp_high_bullish'].transform(lambda x: x.ffill() if x.notna().any() else x)
        df_5m['sp_low_bullish'] = df_5m.groupby('date')['sp_low_bullish'].transform(lambda x: x.ffill() if x.notna().any() else x)
        df_5m['sp_high_bearish'] = df_5m.groupby('date')['sp_high_bearish'].transform(lambda x: x.ffill() if x.notna().any() else x)
        df_5m['sp_low_bearish'] = df_5m.groupby('date')['sp_low_bearish'].transform(lambda x: x.ffill() if x.notna().any() else x)
        
        # Set pre-confirmation values to NaN for 5m
        df_5m.loc[~df_5m['sp_confirmed_bullish'].cummax(), ['sp_high_bullish', 'sp_low_bullish']] = None
        df_5m.loc[~df_5m['sp_confirmed_bearish'].cummax(), ['sp_high_bearish', 'sp_low_bearish']] = None
        
        # Calculate SP range percentages for 5m
        df_5m['sp_bullish_range_pct'] = (df_5m['sp_high_bullish'] - df_5m['sp_low_bullish']) / df_5m['sp_low_bullish'] * 100
        df_5m['sp_bearish_range_pct'] = (df_5m['sp_high_bearish'] - df_5m['sp_low_bearish']) / df_5m['sp_low_bearish'] * 100
        df_5m['cum_sp_bullish'] = df_5m.groupby('date')['sp_confirmed_bullish'].cumsum()
        df_5m['cum_sp_bearish'] = df_5m.groupby('date')['sp_confirmed_bearish'].cumsum()
        
        # === VOLUME & RANGE CALCULATIONS - 15m ===
        df_15m['cum_intraday_volume'] = df_15m.groupby('date')['volume'].cumsum()
        df_15m['curtop'] = df_15m.groupby('date')['high'].cummax()
        df_15m['curbot'] = df_15m.groupby('date')['low'].cummin()
        df_15m['today_range'] = df_15m['curtop'] - df_15m['curbot']
        df_15m['today_range_pct_10'] = df_15m['today_range'] / df_15m['atr_10']
        df_15m['today_range_pct_14'] = df_15m['today_range'] / df_15m['atr_14']
        df_15m['volume_range_pct_10'] = (df_15m['cum_intraday_volume'] / df_15m['volume_10']) / df_15m['today_range_pct_10']
        df_15m['volume_range_pct_14'] = (df_15m['cum_intraday_volume'] / df_15m['volume_14']) / df_15m['today_range_pct_14']
        
        # === VOLUME & RANGE CALCULATIONS - 5m ===
        df_5m['cum_intraday_volume'] = df_5m.groupby('date')['volume'].cumsum()
        df_5m['curtop'] = df_5m.groupby('date')['high'].cummax()
        df_5m['curbot'] = df_5m.groupby('date')['low'].cummin()
        df_5m['today_range'] = df_5m['curtop'] - df_5m['curbot']
        df_5m['today_range_pct_10'] = df_5m['today_range'] / df_5m['atr_10']
        df_5m['today_range_pct_14'] = df_5m['today_range'] / df_5m['atr_14']
        df_5m['volume_range_pct_10'] = (df_5m['cum_intraday_volume'] / df_5m['volume_10']) / df_5m['today_range_pct_10']
        df_5m['volume_range_pct_14'] = (df_5m['cum_intraday_volume'] / df_5m['volume_14']) / df_5m['today_range_pct_14']
        
        # === STRATEGY DEFINITIONS ===
        # Strategy 8 & 12 (15m)
        df_15m['s_8'] = (
            (df_15m['time'].dt.time >= time(4, 0)) & 
            (df_15m['time'].dt.time < time(8, 15)) & 
            (df_15m['cum_sp_bullish'] >= 1) & 
            (df_15m['sp_bullish_range_pct'] > 0.8) & 
            (df_15m['zl_macd_signal'] == -1) & 
            (df_15m['volume_range_pct_10'] > 1)
        )
        df_15m['strategy_8'] = False
        first_true_idx_8 = df_15m[df_15m['s_8']].groupby('date').head(1).index
        df_15m.loc[first_true_idx_8, 'strategy_8'] = True
        
        df_15m['s_12'] = (
            (df_15m['time'].dt.time >= time(4, 0)) & 
            (df_15m['time'].dt.time < time(8, 15)) & 
            (df_15m['cum_sp_bearish'] >= 1) & 
            (df_15m['sp_bearish_range_pct'] > 0.8) & 
            (df_15m['zl_macd_signal'] == 1) &
            (df_15m['volume_range_pct_10'] > 0) &
            (df_15m['volume_range_pct_10'] < 0.4)
        )
        df_15m['strategy_12'] = False
        first_true_idx_12 = df_15m[df_15m['s_12']].groupby('date').head(1).index
        df_15m.loc[first_true_idx_12, 'strategy_12'] = True
        
        # Strategy 10 & 11 (5m)
        df_5m['s_10'] = (
            (df_5m['time'].dt.time >= time(3, 50)) & 
            (df_5m['time'].dt.time < time(8, 15)) & 
            (df_5m['cum_sp_bearish'] >= 1) & 
            (df_5m['sp_bearish_range_pct'] > 0.6) & 
            (df_5m['close'] < df_5m['ema_50']) & 
            (df_5m['close'] < df_5m['ema_100']) & 
            (df_5m['close'] < df_5m['ema_200']) & 
            (df_5m['is_range_bearish']) & 
            (df_5m['volume_range_pct_10'] > 0.3) & 
            (df_5m['volume_range_pct_10'] < 0.7)
        )
        df_5m['strategy_10'] = False
        first_true_idx_10 = df_5m[df_5m['s_10']].groupby('date').head(1).index
        df_5m.loc[first_true_idx_10, 'strategy_10'] = True
        
        df_5m['s_11'] = (
            (df_5m['time'].dt.time >= time(3, 50)) & 
            (df_5m['time'].dt.time < time(8, 15)) & 
            (df_5m['cum_sp_bullish'] >= 1) & 
            (df_5m['sp_bullish_range_pct'] > 0.8) & 
            (df_5m['close'] > df_5m['ema_50']) & 
            (df_5m['close'] > df_5m['ema_100']) & 
            (df_5m['close'] > df_5m['ema_200']) & 
            (df_5m['is_range_bullish']) & 
            (df_5m['volume_range_pct_10'] > 0) & 
            (df_5m['volume_range_pct_10'] < 0.3)
        )
        df_5m['strategy_11'] = False
        first_true_idx_11 = df_5m[df_5m['s_11']].groupby('date').head(1).index
        df_5m.loc[first_true_idx_11, 'strategy_11'] = True

        df_5m['s_9'] = (
            (df_5m['time'].dt.time >= time(3, 50)) & 
            (df_5m['time'].dt.time < time(8, 15)) & 
            (df_5m['cum_sp_bullish'] >= 1) & 
            (df_5m['sp_bullish_range_pct'] > 0.8) & 
            (df_5m['close'] > df_5m['ema_50']) & 
            (df_5m['close'] > df_5m['ema_100']) & 
            (df_5m['close'] > df_5m['ema_200']) & 
            (df_5m['is_range_bullish']) & 
            (df_5m['volume_range_pct_10'] > 0.3) & 
            (df_5m['volume_range_pct_10'] < 0.6)
        )
        df_5m['strategy_9'] = False
        first_true_idx_9 = df_5m[df_5m['s_9']].groupby('date').head(1).index
        df_5m.loc[first_true_idx_9, 'strategy_9'] = True
        
        # Clean up date columns
        df_15m.drop('date', axis=1, inplace=True)
        df_5m.drop('date', axis=1, inplace=True)
        
        self.logger.info(f"✅ All indicators calculated once for {self.symbol}")
        
        return {
            '15m': df_15m,
            '5m': df_5m,
            '1m': df_1m,
            'd': df_daily
        }
    
    def get_day_data_optimized(self, df_with_indicators, day, lookback_days):
        """
        Fast slicing of pre-calculated data for a specific day
        """
        start_date = day - timedelta(days=lookback_days)
        end_date = day + timedelta(days=1)  # Include full day
        
        # Use boolean indexing (faster than .loc for large datasets)
        mask = (df_with_indicators['time'].dt.date >= start_date) & (df_with_indicators['time'].dt.date <= day)
        return df_with_indicators[mask].copy()

    def get_today_data_only(self, df_with_indicators, day):
        """Get only today's data (for trading logic)"""
        start_dt = datetime.combine(day, time.min).replace(tzinfo=pytz.UTC)
        end_dt = datetime.combine(day, time.max).replace(tzinfo=pytz.UTC)
        
        mask = (df_with_indicators['time'] >= start_dt) & (df_with_indicators['time'] <= end_dt)
        return df_with_indicators[mask].copy()

    
    def pre_index_data_by_date(self, df_dict):
        """Pre-index all dataframes by date for O(1) lookups"""
        indexed_data = {}
        for interval, df in df_dict.items():
            df['date'] = df['time'].dt.date
            indexed_data[interval] = df.groupby('date')
        return indexed_data

    def run(self):
        self.logger.info(f"Running backtest from {self.start_date} to {self.end_date}")
        trades = []
        self.trailing_chart_data = []
        in_position = False

        # === STEP 1: Fetch all data once ===
        df_all_dict  = {
        '15m': self.fetch_lookback_data_2(self.start_date - timedelta(days=20), self.end_date, '15m'),
        '5m': self.fetch_lookback_data_2(self.start_date - timedelta(days=20), self.end_date, '5m'),
        '1m': self.fetch_lookback_data_2(self.start_date - timedelta(days=20), self.end_date, '1m'),
        'd': self.fetch_lookback_data_2(self.start_date - timedelta(days=20), self.end_date, 'd')
        }

        # === STEP 2: Calculate all indicators once ===
        data_with_indicators = self.calculate_all_indicators_once(df_all_dict)

        # === STEP 3: Process each day with pre-calculated data ===
        for day in self.daterange():
            # Fast slicing of pre-calculated data (no more daily filtering/copying)
            df = self.get_day_data_optimized(data_with_indicators['15m'], day, 5)
            df_5min = self.get_day_data_optimized(data_with_indicators['5m'], day, 7)
            df_min = self.get_day_data_optimized(data_with_indicators['1m'], day, 2)
            df_daily = self.get_day_data_optimized(data_with_indicators['d'], day, 20)

            if df.empty or df_5min.empty or df_daily.empty or df_min.empty:
                continue
            
            # Get today's data only (for trading logic)
            df_today = self.get_today_data_only(df, day)
            df_today_5min = self.get_today_data_only(df_5min, day)
            df_min_today = self.get_today_data_only(df_min, day)

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
            # 5m dataframe - Strategy 9, 10 and 11
            for i in range(1, len(df_today_5min)):
                prev = df_today_5min.iloc[i - 1]
                curr = df_today_5min.iloc[i]

                curr_ist_time = curr['time'].astimezone(IST).time()  
                curr_ist_time_2 = curr['time'].astimezone(IST)

                buy = curr['strategy_11']
                sell = False
                short = curr['strategy_10'] or curr['strategy_9']
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
                    #strategy_id = '10'
                    strategy_id = '10' if curr['strategy_10'] else '9'
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
            
        self.trades = pd.DataFrame(trades)
        return self.trades

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

