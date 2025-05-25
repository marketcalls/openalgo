import pandas as pd # For pd.notna
from base_strategy import BaseStrategy # Import from the same directory

# ==============================================================================
# ALL PARAMETERS FOR THIS SPECIFIC STRATEGY INSTANCE ARE DEFINED HERE
# ==============================================================================

# --- Core Identity & API ---
STRATEGY_NAME_SPECIFIC = "PeriodRangeBreakout_HL_V1_Configured" # Unique name
API_KEY_SPECIFIC = 'a1024b4bba8afa5dd696cc12093ca1cd3802bbabf77079f4025c4abb8023be4e'  # <<< USER: REPLACE THIS!
HOST_URL_SPECIFIC = 'http://127.0.0.1:5000'
STOCKS_CSV_NAME_SPECIFIC = "../stocks.csv" # Relative to strategies folder

# --- Base Strategy Timing & Operational Parameters ---
PRODUCT_TYPE_SPECIFIC = "CNC"
TIMEFRAME_SPECIFIC = "5m"
STRATEGY_START_TIME_SPECIFIC = "09:20"
STRATEGY_END_TIME_SPECIFIC = "15:10" # For MIS square-off & entry window end
JOURNALING_TIME_SPECIFIC = "15:31"
RE_ENTRY_WAIT_MINUTES_SPECIFIC = 30
HISTORY_DAYS_TO_FETCH_SPECIFIC = 15 # Min 2 for lookbacks, more for robustness
LOOP_SLEEP_SECONDS_SPECIFIC = 60

# --- Base Strategy Risk Management Parameters ---
USE_STOPLOSS_SPECIFIC = True
STOPLOSS_PERCENT_SPECIFIC = 3.0 # e.g., 3.0 for 3%
USE_TARGET_SPECIFIC = True
TARGET_PERCENT_SPECIFIC = 7.0   # e.g., 7.0 for 7%

# --- Base Strategy Order Confirmation Parameters ---
ORDER_CONFIRMATION_ATTEMPTS_SPECIFIC = 5
ORDER_CONFIRMATION_DELAY_SECONDS_SPECIFIC = 2

# --- Parameters Specific to THIS PeriodRangeBreakout Strategy ---
# These will be passed via the `strategy_specific_params` argument to BaseStrategy
# and used by this derived class's logic.
ENTRY_LOOKBACK_SPECIFIC = 7
EXIT_LOOKBACK_SPECIFIC = 30
# Add any other parameters unique to this strategy's logic here
# EXAMPLE_SPECIFIC_PARAM = "some_value"

# ==============================================================================

class PeriodRangeBreakoutStrategy(BaseStrategy):
    def __init__(self):
        # Collect all strategy-specific parameters into a dictionary
        # These are parameters that the BaseStrategy doesn't have direct attributes for,
        # but are needed by this derived strategy's logic.
        strategy_specific_params_dict = {
            "ENTRY_LOOKBACK": ENTRY_LOOKBACK_SPECIFIC,
            "EXIT_LOOKBACK": EXIT_LOOKBACK_SPECIFIC,
            # "EXAMPLE_SPECIFIC_PARAM": EXAMPLE_SPECIFIC_PARAM, # If you had more
        }

        # Call the BaseStrategy's __init__ method, passing all parameters explicitly.
        # This makes it very clear what configuration is being used for the base.
        super().__init__(
            strategy_name=STRATEGY_NAME_SPECIFIC,
            api_key=API_KEY_SPECIFIC,
            host_url=HOST_URL_SPECIFIC,
            stocks_csv_name=STOCKS_CSV_NAME_SPECIFIC,
            product_type=PRODUCT_TYPE_SPECIFIC,
            timeframe=TIMEFRAME_SPECIFIC,
            strategy_start_time_str=STRATEGY_START_TIME_SPECIFIC,
            strategy_end_time_str=STRATEGY_END_TIME_SPECIFIC,
            journaling_time_str=JOURNALING_TIME_SPECIFIC,
            re_entry_wait_minutes=RE_ENTRY_WAIT_MINUTES_SPECIFIC,
            use_stoploss=USE_STOPLOSS_SPECIFIC,
            stoploss_percent=STOPLOSS_PERCENT_SPECIFIC,
            use_target=USE_TARGET_SPECIFIC,
            target_percent=TARGET_PERCENT_SPECIFIC,
            history_days_to_fetch=HISTORY_DAYS_TO_FETCH_SPECIFIC,
            loop_sleep_seconds=LOOP_SLEEP_SECONDS_SPECIFIC,
            order_confirmation_attempts=ORDER_CONFIRMATION_ATTEMPTS_SPECIFIC,
            order_confirmation_delay_seconds=ORDER_CONFIRMATION_DELAY_SECONDS_SPECIFIC,
            strategy_specific_params=strategy_specific_params_dict # Pass the dict of specific params
        )
        # You can log the specific params here if needed, BaseStrategy logs its own init.
        self._log_message(f"PeriodRangeBreakoutStrategy initialized with specific lookbacks: Entry={self.strategy_specific_params.get('ENTRY_LOOKBACK')}, Exit={self.strategy_specific_params.get('EXIT_LOOKBACK')}")

    def _check_strategy_specific_entry_condition(self, symbol_key, stock_info, hist_df, ltp_at_signal):
        # Access strategy-specific parameters using self.strategy_specific_params
        entry_lookback_period = self.strategy_specific_params.get("ENTRY_LOOKBACK", 7) # Default if not found
        req_candles = entry_lookback_period + 1

        if hist_df.empty or len(hist_df) < req_candles:
            return None
        if not {'close', 'high'}.issubset(hist_df.columns):
            self._log_message(f"Missing 'close' or 'high' for {symbol_key} entry.", level="ERROR")
            return None

        close_0 = hist_df['close'].iloc[-1]
        max_prev_highs = hist_df['high'].shift(1).rolling(window=entry_lookback_period).max().iloc[-1]

        if pd.notna(close_0) and pd.notna(max_prev_highs) and close_0 > max_prev_highs:
            self._log_message(f"Strategy Entry Signal for {symbol_key}: C({close_0}) > MaxPrev{entry_lookback_period}H({max_prev_highs})")
            return "BUY"
        return None

    def _check_strategy_specific_exit_condition(self, symbol_key, position_details, ltp, hist_df):
        action = position_details.get('action', '').upper()
        if action != "BUY": # This strategy only manages long exits
            return None

        exit_lookback_period = self.strategy_specific_params.get("EXIT_LOOKBACK", 30) # Default if not found
        req_candles = exit_lookback_period + 1
        
        if hist_df.empty or len(hist_df) < req_candles:
            return None
        if not {'close', 'low'}.issubset(hist_df.columns):
            self._log_message(f"Missing 'close' or 'low' for {symbol_key} strategy exit.", level="ERROR")
            return None

        close_0 = hist_df['close'].iloc[-1]
        min_prev_lows = hist_df['low'].shift(1).rolling(window=exit_lookback_period).min().iloc[-1]

        if pd.notna(close_0) and pd.notna(min_prev_lows) and close_0 < min_prev_lows:
            return f"Strategy Exit: C({close_0}) < MinPrev{exit_lookback_period}Lows({min_prev_lows})"
        return None

if __name__ == "__main__":
    if API_KEY_SPECIFIC == 'YOUR_API_KEY':
        print(f"ERROR: Please replace 'YOUR_API_KEY' in {__file__} before running.")
    else:
        strategy_instance = PeriodRangeBreakoutStrategy()
        strategy_instance.run()