import pandas as pd
import time
from datetime import datetime, time as dt_time, timedelta
import pytz
from openalgo import api # Assuming this is correctly installed
import math
import os
import json
import traceback
import trade_journaler # Expects trade_journaler.py in the same directory

IST = pytz.timezone('Asia/Kolkata')
STRATEGIES_DIR = os.path.dirname(os.path.abspath(__file__))

class BaseStrategy:
    def __init__(self,
                 strategy_name, # This is the initial name, typically from the script's global constant
                 api_key=None, host_url=None, ws_url=None, # Defaults for BaseStrategy signature
                 stocks_csv_name="stocks.csv",
                 product_type="CNC", timeframe="5m",
                 strategy_start_time_str="09:20", strategy_end_time_str="15:10",
                 journaling_time_str="15:31",
                 re_entry_wait_minutes=30,
                 use_stoploss=True, stoploss_percent=3.0,
                 use_target=True, target_percent=7.0,
                 history_days_to_fetch=15, loop_sleep_seconds=60,
                 order_confirmation_attempts=5, order_confirmation_delay_seconds=2,
                 **kwargs): # To catch any other params passed from the script via globals

        _initial_strategy_name_for_config = strategy_name

        # Determine config file path using the initial strategy name
        base_name_for_config = _initial_strategy_name_for_config.replace('_live.py', '')
        config_file_path = os.path.join(STRATEGIES_DIR, f"{base_name_for_config}_config.json")

        loaded_config_params = {}
        if os.path.exists(config_file_path):
            try:
                with open(config_file_path, 'r', encoding='utf-8') as f:
                    loaded_config_params = json.load(f)
                # Early log using print, as self._log_message might not be ready if strategy_name changes
                print(f"BaseStrategy INFO: Loaded parameters from {config_file_path} for {_initial_strategy_name_for_config}")
            except Exception as e:
                print(f"BaseStrategy ERROR: Error loading config {config_file_path} for {_initial_strategy_name_for_config}: {e}")

        # These are the parameters known to BaseStrategy. Their values will be taken from
        # loaded_config_params if present, otherwise from the __init__ signature defaults (passed via **kwargs or direct args).
        self.strategy_name = loaded_config_params.get('strategy_name', strategy_name)

        # Set other base parameters
        self.api_key = loaded_config_params.get('api_key', api_key)
        self.host_url = loaded_config_params.get('host_url', host_url)
        self.ws_url = loaded_config_params.get('ws_url', ws_url)
        self.stocks_csv_name = loaded_config_params.get('stocks_csv_name', stocks_csv_name)
        self.product_type = loaded_config_params.get('product_type', product_type)
        self.timeframe = loaded_config_params.get('timeframe', timeframe)
        self.strategy_start_time_str = loaded_config_params.get('strategy_start_time_str', strategy_start_time_str)
        self.strategy_end_time_str = loaded_config_params.get('strategy_end_time_str', strategy_end_time_str)
        self.journaling_time_str = loaded_config_params.get('journaling_time_str', journaling_time_str)
        self.re_entry_wait_minutes = loaded_config_params.get('re_entry_wait_minutes', re_entry_wait_minutes)
        self.use_stoploss = loaded_config_params.get('use_stoploss', use_stoploss)
        self.stoploss_percent = loaded_config_params.get('stoploss_percent', stoploss_percent)
        self.use_target = loaded_config_params.get('use_target', use_target)
        self.target_percent = loaded_config_params.get('target_percent', target_percent)
        self.history_days_to_fetch = loaded_config_params.get('history_days_to_fetch', history_days_to_fetch)
        self.loop_sleep_seconds = loaded_config_params.get('loop_sleep_seconds', loop_sleep_seconds)
        self.order_confirmation_attempts = loaded_config_params.get('order_confirmation_attempts', order_confirmation_attempts)
        self.order_confirmation_delay_seconds = loaded_config_params.get('order_confirmation_delay_seconds', order_confirmation_delay_seconds)

        # Keys known to BaseStrategy (must match attribute names set above)
        base_param_keys_set = {
            'strategy_name', 'api_key', 'host_url', 'ws_url', 'stocks_csv_name',
            'product_type', 'timeframe', 'strategy_start_time_str', 'strategy_end_time_str',
            'journaling_time_str', 're_entry_wait_minutes', 'use_stoploss',
            'stoploss_percent', 'use_target', 'target_percent', 'history_days_to_fetch',
            'loop_sleep_seconds', 'order_confirmation_attempts', 'order_confirmation_delay_seconds'
        }

        self.strategy_specific_params = {}
        # Populate from loaded_config_params for keys not in base_param_keys_set
        for key, value in loaded_config_params.items():
            if key not in base_param_keys_set:
                self.strategy_specific_params[key] = value

        # Populate from kwargs for keys not in base_param_keys_set AND not already in strategy_specific_params (from JSON)
        # This ensures that .py file global constants are used if not present in JSON.
        for key, value in kwargs.items():
            if key not in base_param_keys_set and key not in self.strategy_specific_params:
                self.strategy_specific_params[key] = value

        # Initialize paths based on resolved names
        final_base_name_for_state = self.strategy_name.replace('_live.py', '') # Use final strategy_name
        self.state_file_path = os.path.join(STRATEGIES_DIR, f"{final_base_name_for_state}_state.json")
        self.stocks_csv_path = os.path.join(STRATEGIES_DIR, self.stocks_csv_name) # Use final stocks_csv_name

        # Initialize other instance variables
        self.openalgo_client = None
        self.open_positions = {}
        self.exited_stocks_cooldown = {}
        self.stock_configs = []
        self.trades_to_journal_today = []
        self.journal_written_today = False
        self.current_trading_day_date = None
        self.subscribed_symbols_ws = set()
        self.ws_connected = False
        self.ws_pending_sl_exits = set()

        self._log_message(f"BaseStrategy initialized for '{self.strategy_name}'. Product: {self.product_type}, TF: {self.timeframe}")
        # Example: self._log_message(f"Specific params: {self.strategy_specific_params}")

    def _log_message(self, message, level="INFO"):
        full_message = f"{datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S %Z%z')} - {self.strategy_name} - {level} - {message}"
        print(full_message)
        if level == "ERROR":
            try:
                tb_info = traceback.format_exc()
                if "NoneType: None" not in tb_info:
                     print(f"{datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S %Z%z')} - {self.strategy_name} - TRACEBACK - {tb_info.strip()}")
            except Exception: pass # Should not fail logging

    def _serialize_datetime(self, dt_obj):
        return dt_obj.isoformat() if isinstance(dt_obj, (datetime, dt_time, datetime.now(IST).date().__class__)) else dt_obj

    def _deserialize_datetime(self, dt_str):
        if not isinstance(dt_str, str): return dt_str
        try:
            dt_obj = datetime.fromisoformat(dt_str)
            return dt_obj.astimezone(IST) if dt_obj.tzinfo else IST.localize(dt_obj)
        except (ValueError, TypeError): # Added TypeError for safety
            # self._log_message(f"Could not parse datetime string '{dt_str}'.", level="WARNING") # Reduced severity
            return dt_str # Return original if parsing fails

    def _save_state(self):
        try:
            state = {
                "open_positions": {
                    k: {**v, 'entry_time_ist': self._serialize_datetime(v.get('entry_time_ist')),
                        'journal_data': {
                            **v.get('journal_data',{}), 
                            'entry_decision_timestamp_ist': self._serialize_datetime(v.get('journal_data',{}).get('entry_decision_timestamp_ist'))
                         } if v.get('journal_data') else None
                       } for k, v in self.open_positions.items()
                },
                "exited_stocks_cooldown": {k: self._serialize_datetime(v) for k, v in self.exited_stocks_cooldown.items()},
                "trades_to_journal_today": [
                    {**t, 'entry_decision_timestamp_ist': self._serialize_datetime(t.get('entry_decision_timestamp_ist')),
                     'exit_decision_timestamp_ist': self._serialize_datetime(t.get('exit_decision_timestamp_ist'))
                    } for t in self.trades_to_journal_today
                ],
                "journal_written_today": self.journal_written_today,
                "current_trading_day_date": self._serialize_datetime(self.current_trading_day_date)
            }
            with open(self.state_file_path, 'w', encoding='utf-8') as f: json.dump(state, f, indent=4)
            self._log_message(f"State saved. Positions: {len(self.open_positions)}, Journal Pending: {len(self.trades_to_journal_today)}")
        except Exception as e:
            self._log_message(f"Error saving state: {e}", level="ERROR")

    def _load_state(self):
        default_date = datetime.now(IST).date()
        # Ensure state_file_path is correct if strategy_name was changed by config
        # This is already set correctly after parameter loading in __init__
        if not os.path.exists(self.state_file_path):
            self._log_message("No state file. Starting fresh.")
            self.current_trading_day_date = default_date
            return
        try:
            with open(self.state_file_path, 'r', encoding='utf-8') as f: loaded = json.load(f)
            for k, v_s in loaded.get("open_positions", {}).items():
                v_d = v_s.copy()
                v_d['entry_time_ist'] = self._deserialize_datetime(v_d.get('entry_time_ist'))
                if v_d.get('journal_data'):
                     v_d['journal_data']['entry_decision_timestamp_ist'] = self._deserialize_datetime(v_d['journal_data'].get('entry_decision_timestamp_ist'))
                self.open_positions[k] = v_d
            self.exited_stocks_cooldown = {k: self._deserialize_datetime(v) for k, v in loaded.get("exited_stocks_cooldown", {}).items()}
            for t_s in loaded.get("trades_to_journal_today", []):
                t_d = t_s.copy()
                t_d['entry_decision_timestamp_ist'] = self._deserialize_datetime(t_d.get('entry_decision_timestamp_ist'))
                t_d['exit_decision_timestamp_ist'] = self._deserialize_datetime(t_d.get('exit_decision_timestamp_ist'))
                self.trades_to_journal_today.append(t_d)
            self.journal_written_today = loaded.get("journal_written_today", False)
            deserialized_date = self._deserialize_datetime(loaded.get("current_trading_day_date"))
            if isinstance(deserialized_date, datetime): self.current_trading_day_date = deserialized_date.date()
            elif isinstance(deserialized_date, type(default_date)): self.current_trading_day_date = deserialized_date
            else: self.current_trading_day_date = default_date
            self._log_message(f"State loaded. Positions: {len(self.open_positions)}, Cooldowns: {len(self.exited_stocks_cooldown)}, Journal Pending: {len(self.trades_to_journal_today)}")
        except Exception as e:
            self._log_message(f"Error loading state: {e}. Starting fresh.", level="ERROR")
            self.open_positions, self.exited_stocks_cooldown, self.trades_to_journal_today = {}, {}, []
            self.journal_written_today = False; self.current_trading_day_date = default_date
            
    def _initialize_openalgo_client(self):
        try:
            client_params = {'api_key': self.api_key, 'host': self.host_url}
            if self.ws_url:
                client_params['ws_url'] = self.ws_url
                self._log_message(f"Initializing OpenAlgo with WS URL: {self.ws_url}")
            else:
                self._log_message("Initializing OpenAlgo without WS URL (WebSocket features will be disabled).")

            self.openalgo_client = api(**client_params) # MODIFIED

            funds = self.openalgo_client.funds()
            if funds and funds.get('status') == 'success':
                self._log_message(f"OpenAlgo client OK. Cash: {funds['data'].get('availablecash')}")
                return True
            self._log_message(f"Failed to init OpenAlgo client or fetch funds: {funds}", level="ERROR"); return False
        except Exception as e:
            self._log_message(f"Error initializing OpenAlgo client: {e}", level="ERROR"); return False

    # --- WebSocket Management Methods --- ADDED SECTION
    def _connect_websocket(self):
        if not self.ws_url or not self.openalgo_client or not hasattr(self.openalgo_client, 'connect'):
            self._log_message("WS: WebSocket URL not configured or client does not support connect. WebSocket not started.", level="WARNING")
            return False
        if self.ws_connected:
            return True
        try:
            self._log_message("WS: Attempting to connect...")
            self.openalgo_client.connect() # Assuming connect is synchronous or handles its own threading
            self.ws_connected = True
            self._log_message("WS: Connected.")
            return True
        except Exception as e:
            self.ws_connected = False
            self._log_message(f"WS: Connection error: {e}", level="ERROR")
            return False

    def _disconnect_websocket(self):
        if not self.ws_connected or not self.openalgo_client or not hasattr(self.openalgo_client, 'disconnect'):
            return
        try:
            self._log_message("WS: Disconnecting...")
            self.openalgo_client.disconnect()
            self.ws_connected = False
            self._log_message("WS: Disconnected.")
        except Exception as e:
            self._log_message(f"WS: Disconnection error: {e}", level="ERROR")
            # Should still set ws_connected to False as the state is uncertain
            self.ws_connected = False

    def _subscribe_ws(self, symbols_data_list):
        if not self.ws_connected or not hasattr(self.openalgo_client, 'subscribe_ltp'):
            self._log_message("WS: Not connected or client does not support subscribe_ltp. Cannot subscribe.", level="WARNING")
            return

        to_subscribe = [
            s_data for s_data in symbols_data_list
            if (s_data.get('exchange'), s_data.get('symbol')) not in self.subscribed_symbols_ws
        ]

        if to_subscribe:
            try:
                self._log_message(f"WS: Attempting to subscribe to LTP for {len(to_subscribe)} symbols: {to_subscribe}")
                # Assuming subscribe_ltp takes a list of dicts and a callback
                self.openalgo_client.subscribe_ltp(to_subscribe, self._on_ws_data_received)
                for s_data in to_subscribe:
                    self.subscribed_symbols_ws.add((s_data['exchange'], s_data['symbol']))
                self._log_message(f"WS: Subscribed to {len(to_subscribe)} symbols. Total WS subscriptions: {len(self.subscribed_symbols_ws)}")
            except Exception as e:
                self._log_message(f"WS: Error subscribing to LTP: {e}", level="ERROR")

    def _unsubscribe_ws(self, symbols_data_list):
        if not self.ws_connected or not hasattr(self.openalgo_client, 'unsubscribe_ltp'):
            self._log_message("WS: Not connected or client does not support unsubscribe_ltp. Cannot unsubscribe.", level="WARNING")
            return

        to_unsubscribe = [
            s_data for s_data in symbols_data_list
            if (s_data.get('exchange'), s_data.get('symbol')) in self.subscribed_symbols_ws
        ]

        if to_unsubscribe:
            try:
                self._log_message(f"WS: Attempting to unsubscribe from LTP for {len(to_unsubscribe)} symbols: {to_unsubscribe}")
                # Assuming unsubscribe_ltp takes a list of dicts. Check if callback is needed.
                # For now, assuming it does not need callback, or callback is ignored if provided.
                self.openalgo_client.unsubscribe_ltp(to_unsubscribe, self._on_ws_data_received)
                for s_data in to_unsubscribe:
                    self.subscribed_symbols_ws.discard((s_data['exchange'], s_data['symbol']))
                self._log_message(f"WS: Unsubscribed from {len(to_unsubscribe)} symbols. Total WS subscriptions: {len(self.subscribed_symbols_ws)}")
            except Exception as e:
                self._log_message(f"WS: Error unsubscribing from LTP: {e}", level="ERROR")

    def _on_ws_data_received(self, data):
        # self._log_message(f"WS Data: {data}", level="DEBUG") # Can be very noisy
        msg_type = data.get("type")
        if msg_type == "market_data":
            symbol = data.get("symbol")
            exchange = data.get("exchange") # Assuming data includes 'exchange'

            if not symbol or not exchange:
                self._log_message(f"WS market_data missing symbol or exchange: {data}", level="ERROR")
                return

            ltp_data = data.get("data", {})
            ltp_value = ltp_data.get("ltp")

            if ltp_value is None: return

            try: ltp = float(ltp_value)
            except ValueError:
                self._log_message(f"WS LTP for {symbol}_{exchange} is not a valid float: {ltp_value}", level="ERROR"); return

            symbol_key = f"{symbol}_{exchange}"
            # self._log_message(f"WS LTP for {symbol_key}: {ltp}", level="INFO") # Optional: Can be very noisy

            if symbol_key in self.open_positions and symbol_key not in self.ws_pending_sl_exits:
                position_details = self.open_positions.get(symbol_key)
                if not position_details: return

                action = position_details.get('action', '').upper()
                sl_price = position_details.get('sl_price')

                exit_triggered = False
                if self.use_stoploss and action == "BUY" and sl_price is not None and ltp <= sl_price:
                    self._log_message(f"WS: Stop-Loss for BUY {symbol_key} at LTP {ltp} (SL: {sl_price})", level="INFO")
                    exit_triggered = True
                elif self.use_stoploss and action == "SELL" and sl_price is not None and ltp >= sl_price: # Basic short SL
                    self._log_message(f"WS: Stop-Loss for SELL {symbol_key} at LTP {ltp} (SL: {sl_price})", level="INFO")
                    exit_triggered = True

                if exit_triggered:
                    self.ws_pending_sl_exits.add(symbol_key)
                    # Pass a copy of details, as original might change if multiple triggers happen
                    self._attempt_exit_position(symbol_key, f"WS SL hit at {ltp}", position_details.copy())

        elif msg_type == "error":
            self._log_message(f"WS Error: {data.get('message', data.get('msg', 'Unknown WS error'))}", level="ERROR")
    # --- END WebSocket Management Methods ---

    def _load_stock_configurations(self):
        if not os.path.exists(self.stocks_csv_path):
            self._log_message(f"Error: Stock file '{self.stocks_csv_path}' not found.", level="ERROR")
            self.stock_configs = []
            return False
        try:
            df = pd.read_csv(self.stocks_csv_path, encoding='utf-8')

            required_columns = {'symbol', 'exchange', 'max_fund', 'strategy_id'}
            if not required_columns.issubset(df.columns):
                self._log_message(f"Error: CSV file '{self.stocks_csv_path}' must contain columns: {', '.join(required_columns)}. Found: {', '.join(df.columns)}", level="ERROR")
                self.stock_configs = []
                return False

            # Determine the strategy key to filter by, normalizing self.strategy_name
            current_strategy_filter_key = self.strategy_name.replace('_live.py', '').replace('.py', '')

            # Filter the DataFrame
            # Ensure strategy_id column is treated as string for comparison, like current_strategy_filter_key
            filtered_df = df[df['strategy_id'].astype(str) == current_strategy_filter_key]

            self.stock_configs = filtered_df.to_dict('records')

            if not self.stock_configs:
                self._log_message(f"No stock configurations found for strategy_id '{current_strategy_filter_key}' in '{self.stocks_csv_path}'. Loaded 0 stocks.", level="INFO")
            else:
                self._log_message(f"Loaded {len(self.stock_configs)} stock configs for strategy_id '{current_strategy_filter_key}' from '{self.stocks_csv_path}'.")
            return True

        except pd.errors.EmptyDataError:
            self._log_message(f"Warning: Stock file '{self.stocks_csv_path}' is empty.", level="WARNING")
            self.stock_configs = []
            return True # File exists and is readable, but empty - not a critical error for loading itself.
        except Exception as e:
            self._log_message(f"Error loading stock configs from '{self.stocks_csv_path}': {e}", level="ERROR")
            self.stock_configs = []
            return False

    def _get_historical_data(self, symbol, exchange, interval, start_date_str, end_date_str):
        try:
            hist_df = self.openalgo_client.history(symbol=symbol, exchange=exchange, interval=interval, start_date=start_date_str, end_date=end_date_str)
            return hist_df if isinstance(hist_df, pd.DataFrame) else pd.DataFrame()
        except Exception as e:
            self._log_message(f"Error fetching history for {symbol} ({exchange}): {e}", level="ERROR"); return pd.DataFrame()

    def _get_ltp(self, symbol, exchange):
        try:
            q = self.openalgo_client.quotes(symbol=symbol, exchange=exchange)
            if q and q.get('status') == 'success' and q.get('data', {}).get('ltp') is not None: return float(q['data']['ltp'])
            self._log_message(f"Could not fetch LTP for {symbol} ({exchange}). Resp: {q}", level="WARNING"); return None
        except Exception as e: self._log_message(f"Error fetching LTP for {symbol} ({exchange}): {e}", level="ERROR"); return None

    def _calculate_trade_quantity(self, max_fund, ltp):
        return math.floor(float(max_fund) / float(ltp)) if ltp and float(ltp) > 0 and max_fund else 0

    def _place_order_api(self, symbol, exchange, action, quantity, product, price_type="MARKET", price=0, trigger_price=0):
        if quantity <= 0: self._log_message(f"Skipping order {symbol} Qty 0."); return None
        try:
            self._log_message(f"Placing {action} order: {symbol} Qty:{quantity} Prod:{product} Type:{price_type}")
            params = {"strategy": self.strategy_name, "symbol": symbol, "action": action.upper(), "exchange": exchange,
                      "price_type": price_type.upper(), "product": product.upper(), "quantity": str(int(float(quantity))),
                      "price": str(price) if price_type.upper() == "LIMIT" else "0",
                      "trigger_price": str(trigger_price) if float(trigger_price) > 0 else "0"}
            self._log_message(f"Placing order: {params}")
            response = self.openalgo_client.placeorder(**params)
            self._log_message(f"Order SENT resp for {symbol}: {response}")
            if response and response.get('status') == 'success' and response.get('orderid'): return response['orderid']
            self._log_message(f"Order SEND failed for {symbol}: {response.get('message', 'Unknown') if response else 'No resp'}", level="ERROR"); return None
        except Exception as e:
            self._log_message(f"Exception in order placement for {symbol}: {e}", level="ERROR"); return None

    def _confirm_order_execution(self, order_id, expected_action, expected_qty):
        if not order_id: return False, None, None
        for i in range(self.order_confirmation_attempts):
            try:
                self._log_message(f"Confirming OID {order_id}, Attempt {i+1}/{self.order_confirmation_attempts}")
                response = self.openalgo_client.orderstatus(order_id=order_id, strategy=self.strategy_name)
                if response and response.get('status') == 'success' and 'data' in response:
                    data = response['data']; status_api = data.get('order_status', '').lower()
                    fill_price = float(data.get('price', 0.0)) if data.get('price') is not None else 0.0
                    fill_quantity = float(data.get('quantity','0')) if data.get('quantity') is not None else 0.0
                    if status_api == 'complete':
                        self._log_message(f"OID {order_id} COMPLETE. Px:{fill_price}, Qty:{fill_quantity}")
                        return True, fill_price, fill_quantity
                    if status_api == 'rejected':
                        self._log_message(f"OID {order_id} REJECTED: {data.get('remarks', 'N/A')}", level="ERROR"); return False, None, None
                    self._log_message(f"OID {order_id} PENDING ({status_api}). Waiting...")
                else: self._log_message(f"Failed to get status for OID {order_id}. Resp: {response}", level="ERROR")
                if i < self.order_confirmation_attempts - 1: time.sleep(self.order_confirmation_delay_seconds)
            except Exception as e:
                self._log_message(f"Exception during order confirm for {order_id}: {e}", level="ERROR")
                if i < self.order_confirmation_attempts - 1: time.sleep(self.order_confirmation_delay_seconds)
        self._log_message(f"OID {order_id} NOT CONFIRMED 'complete' after {self.order_confirmation_attempts} attempts.", level="ERROR")
        return False, None, None

    def _get_time_status(self):
        now_ist = datetime.now(IST); now_time = now_ist.time()
        mkt_o, mkt_c = dt_time(9, 15), dt_time(15, 30)
        strat_s = datetime.strptime(self.strategy_start_time_str, "%H:%M").time()
        strat_e = datetime.strptime(self.strategy_end_time_str, "%H:%M").time()
        journal_t = datetime.strptime(self.journaling_time_str, "%H:%M").time()
        is_mkt_open = mkt_o <= now_time <= mkt_c
        return {"now_ist": now_ist, "now_time": now_time, "is_mkt_open": is_mkt_open,
                "is_entry_active": is_mkt_open and strat_s <= now_time < strat_e,
                "is_mis_sq_off": is_mkt_open and self.product_type == "MIS" and now_time >= strat_e, # check product_type
                "is_journal_time": now_time >= journal_t}

    def _get_next_market_session_times(self, current_dt_ist):
        # Calculates market open/close for today and the next session's open.
        # Assumes Mon-Fri are trading days. Does not account for specific holidays.
        # `current_dt_ist` must be an timezone-aware datetime object (IST).

        # Ensure datetime, dt_time, timedelta are imported from datetime module
        # Ensure IST is available (pytz.timezone('Asia/Kolkata'))

        market_open_time_obj = datetime.strptime(self.strategy_start_time_str, "%H:%M").time()
        market_close_time_obj = datetime.strptime(self.strategy_end_time_str, "%H:%M").time()

        today_date = current_dt_ist.date()

        # Combine with today's date and make them timezone-aware (IST)
        market_open_today_dt = IST.localize(datetime.combine(today_date, market_open_time_obj))
        market_close_today_dt = IST.localize(datetime.combine(today_date, market_close_time_obj))

        is_trading_day_today = current_dt_ist.weekday() < 5 # Monday=0, ..., Friday=4, Saturday=5, Sunday=6

        # Calculate next_session_open_dt
        next_session_open_dt_candidate = None
        if is_trading_day_today and current_dt_ist < market_open_today_dt:
            # Case 1: Today is a trading day, and current time is before market open.
            next_session_open_dt_candidate = market_open_today_dt
        else:
            # Case 2: Today is a trading day at/after market open, or it's a weekend.
            # Find the next actual trading day's open.
            temp_date = today_date
            if (is_trading_day_today and current_dt_ist >= market_open_today_dt) or not is_trading_day_today:
                temp_date += timedelta(days=1) # Start search from tomorrow

            # Loop to find the next weekday (Monday-Friday)
            loop_count = 0 # Safety counter
            while True:
                if temp_date.weekday() < 5: # Monday to Friday
                    next_session_open_dt_candidate = IST.localize(datetime.combine(temp_date, market_open_time_obj))
                    break
                temp_date += timedelta(days=1)
                loop_count += 1
                if loop_count > 7: # Safety break for unexpected loops (e.g., if date logic had error)
                    self._log_message("Error finding next trading day within 7 days. Defaulting to next calendar day's open.", level="ERROR")
                    # Fallback: default to next calendar day (will be re-evaluated in next main loop)
                    next_session_open_dt_candidate = IST.localize(datetime.combine(today_date + timedelta(days=1), market_open_time_obj))
                    break

        return {
            'market_open_today': market_open_today_dt,
            'market_close_today': market_close_today_dt,
            'next_session_open_dt': next_session_open_dt_candidate,
            'is_trading_day_today': is_trading_day_today
        }

    def _attempt_exit_position(self, symbol_key, reason, pos_details_orig):
        pos_details = pos_details_orig.copy()
        symbol, exchange = symbol_key.split('_')
        try:
            self._log_message(f"Attempting EXIT for {symbol_key} ({pos_details['action']}) due to: {reason}")
            exit_action = "SELL" if pos_details['action'].upper() == "BUY" else "BUY"
            oid = self._place_order_api(symbol, exchange, exit_action, pos_details['quantity'], pos_details['product'])
            if oid:
                ok, fill_px, fill_qty = self._confirm_order_execution(oid, exit_action, pos_details['quantity'])
                if ok:
                    self._log_message(f"EXIT CONFIRMED: {symbol_key} OID:{oid} Px:{fill_px} Qty:{fill_qty}")
                    if pos_details.get('journal_data'):
                        self.trades_to_journal_today.append({
                            **pos_details['journal_data'], 'exit_order_id': oid,
                            'exit_decision_timestamp_ist': datetime.now(IST), 'exit_reason': reason,
                            'intended_exit_price': fill_px }) # Assuming fill_px is the intended for journal
                    if symbol_key in self.open_positions: del self.open_positions[symbol_key]
                    self.exited_stocks_cooldown[symbol_key] = datetime.now(IST)
                    if self.ws_connected: self._unsubscribe_ws([{"exchange": exchange, "symbol": symbol}])
                    self._save_state()
                else: self._log_message(f"EXIT FAILED/REJECTED for {symbol_key} (OID:{oid}). Position REMAINS OPEN.", level="ERROR")
            else: self._log_message(f"Failed to SEND exit order for {symbol_key}. Position REMAINS OPEN.", level="ERROR")
        finally: self.ws_pending_sl_exits.discard(symbol_key)

    def _get_applicable_strategy_parameters(self): # Used for journaling
        base_params = {p: getattr(self, p, None) for p in [
            'product_type', 'timeframe', 'strategy_start_time_str', 'strategy_end_time_str',
            're_entry_wait_minutes', 'use_stoploss', 'stoploss_percent', 'use_target', 'target_percent']}
        return {**base_params, **self.strategy_specific_params}

    def _check_for_manual_exits(self):
        if not self.open_positions:
            return

        try:
            broker_positions_response = self.openalgo_client.positionbook()
            if not broker_positions_response or broker_positions_response.get('status') != 'success' or 'data' not in broker_positions_response:
                self._log_message(f"Could not fetch or failed to parse position book for manual exit check. Response: {broker_positions_response}", level="WARNING")
                return

            live_broker_positions = {}
            # Example: {'VERANDA_NSE_MIS': -2.0, 'SUNFLAG_NSE_CNC': 1.0}
            for pos in broker_positions_response['data']:
                try:
                    # Ensure quantity is a float, default to 0.0 if not convertible or missing
                    qty = float(pos.get('quantity', 0.0))
                    # Normalize symbol and exchange to uppercase to match internal format
                    symbol = pos.get('symbol', '').upper()
                    exchange = pos.get('exchange', '').upper()
                    product = pos.get('product', '').upper() # Product type from broker

                    if not symbol or not exchange or not product: # Skip if essential fields are missing
                        self._log_message(f"Skipping broker position due to missing symbol/exchange/product: {pos}", level="WARNING")
                        continue

                    # Key by symbol_exchange_product to uniquely identify positions
                    broker_pos_key = f"{symbol}_{exchange}_{product}"
                    live_broker_positions[broker_pos_key] = qty
                except ValueError:
                    self._log_message(f"Could not convert quantity to float for broker position: {pos}. Skipping.", level="WARNING")
                    continue
                except Exception as inner_e: # Catch any other unexpected error during pos processing
                    self._log_message(f"Unexpected error processing single broker position {pos}: {inner_e}", level="WARNING")
                    continue

            state_changed = False
            # Iterate over a copy of items for safe removal from self.open_positions
            for internal_pos_key, details in list(self.open_positions.items()):
                # internal_pos_key is typically 'SYMBOL_EXCHANGE'
                # details contains 'product', 'quantity', etc.

                internal_symbol, internal_exchange = internal_pos_key.split('_')
                # Use the product type stored with the position when it was opened by the strategy
                internal_product = details.get('product', self.product_type).upper()

                # Construct the key to match how live_broker_positions are keyed
                broker_check_key = f"{internal_symbol}_{internal_exchange}_{internal_product}"

                # Get the quantity from the broker. If the specific key (symbol_exchange_product)
                # is not found, it means the position for that specific product type is not there, so qty is 0.
                broker_qty = live_broker_positions.get(broker_check_key, 0.0)

                if broker_qty == 0.0:
                    # Position exists internally but is reported as zero or missing at broker for that specific product type.
                    self._log_message(f"Position for {broker_check_key} (Internal Qty: {details.get('quantity')}) found closed/missing at broker (Broker Qty: {broker_qty}). Reconciling as manual exit.", level="INFO")

                    # Prepare journal entry
                    # Ensure datetime is imported: from datetime import datetime (should be at top of file)
                    journal_entry_for_exit = {
                        **(details.get('journal_data', {})), # Carry over entry data
                        'exit_order_id': 'MANUAL_OR_EXTERNAL_EXIT', # Placeholder for order ID
                        'exit_decision_timestamp_ist': datetime.now(IST), # Use current time
                        'exit_reason': 'Position closed externally at broker or quantity became zero',
                        # Actual exit price from manual closure is unknown here.
                        # LTP could be fetched, but might not reflect actual exit price.
                        'intended_exit_price': None # Or details.get('entry_price') as a rough placeholder
                    }
                    self.trades_to_journal_today.append(journal_entry_for_exit)

                    # Clean up internal state
                    if internal_pos_key in self.open_positions: # Check if not already removed by another logic path
                        del self.open_positions[internal_pos_key]

                    self.exited_stocks_cooldown[internal_pos_key] = datetime.now(IST) # Use the 'SYMBOL_EXCHANGE' key for cooldown

                    # Unsubscribe from WebSocket if needed
                    if self.ws_connected and hasattr(self, '_unsubscribe_ws'): # Check if method exists
                        self._unsubscribe_ws([{"exchange": internal_exchange, "symbol": internal_symbol}])

                    state_changed = True
                # else if details.get('quantity') != broker_qty:
                    # Optional: Handle partial manual exits if broker_qty is different but not zero.
                    # self._log_message(f"Position for {broker_check_key} quantity mismatch. Internal: {details.get('quantity')}, Broker: {broker_qty}. Adjusting.", level="INFO")
                    # self.open_positions[internal_pos_key]['quantity'] = broker_qty # Or handle as per strategy logic
                    # state_changed = True


            if state_changed:
                self._log_message("Internal state updated due to manual/external position changes.", level="INFO")
                self._save_state()

        except Exception as e:
            self._log_message(f"Error in _check_for_manual_exits: {e}", level="ERROR")
            # import traceback # Optional: for more detailed debugging during development
            # self._log_message(f"Traceback for _check_for_manual_exits: {traceback.format_exc()}", level="ERROR")

    def get_strategy_description(self):
        return "No specific description provided. Defined in code." # Override in derived

    # --- Abstract methods for derived classes to implement ---
    def _check_strategy_specific_entry_condition(self, symbol_key, stock_info, hist_df, ltp_at_signal):
        """
        Checks for strategy-specific entry conditions.
        Args:
            symbol_key (str): 'SYMBOL_EXCHANGE'
            stock_info (dict): From self.stock_configs
            hist_df (pd.DataFrame): Historical data for the stock.
            ltp_at_signal (float): LTP when signal was generated (can be used by strategy logic if needed)
        Returns:
            str or None: "BUY" or "SELL" if entry condition met, else None.
        """
        raise NotImplementedError("Derived strategy must implement _check_strategy_specific_entry_condition")

    def _check_strategy_specific_exit_condition(self, symbol_key, position_details, ltp, hist_df):
        """
        Checks for strategy-specific exit conditions.
        Args:
            symbol_key (str): 'SYMBOL_EXCHANGE'
            position_details (dict): Details of the open position.
            ltp (float): Current LTP of the stock.
            hist_df (pd.DataFrame): Historical data for the stock.
        Returns:
            str or None: Reason for exit if condition met (e.g., "Strategy Exit Signal"), else None.
        """
        raise NotImplementedError("Derived strategy must implement _check_strategy_specific_exit_condition")
    
    def _manage_open_positions(self, ts, data_cache):
        if not self.open_positions: return
        for sym_key, details_orig in list(self.open_positions.items()):
            if sym_key not in self.open_positions: continue
            details = details_orig.copy()
            symbol, exchange = sym_key.split('_'); ltp = self._get_ltp(symbol, exchange)
            if ltp is None: self._log_message(f"No LTP for {sym_key}, skipping manage."); continue
            action, product = details.get('action', '').upper(), details.get('product', self.product_type).upper()
            
            # MIS Square-off (check product_type from details, not self.product_type which is default)
            if product == "MIS" and ts["now_time"] >= datetime.strptime(self.strategy_end_time_str, "%H:%M").time() and ts["is_mkt_open"]:
                 if sym_key not in self.ws_pending_sl_exits: self._attempt_exit_position(sym_key, "MIS EOD Square-Off", details); continue
                 else: self._log_message(f"MIS EOD for {sym_key} skipped (WS exit pending)."); continue

            exit_reason = None
            if sym_key not in self.ws_pending_sl_exits:
                sl, tp = details.get('sl_price'), details.get('tp_price')
                if self.use_stoploss and sl is not None:
                    if action == "BUY" and ltp <= sl: exit_reason = f"SL hit (polled BUY)"
                    elif action == "SELL" and ltp >= sl: exit_reason = f"SL hit (polled SELL)"
                if not exit_reason and self.use_target and tp is not None: # Check target only if SL not hit
                    if action == "BUY" and ltp >= tp: exit_reason = f"TP hit (polled BUY)"
                    elif action == "SELL" and ltp <= tp: exit_reason = f"TP hit (polled SELL)"
                if exit_reason: self._attempt_exit_position(sym_key, f"{exit_reason} at {ltp}", details); continue
            elif exit_reason: self._log_message(f"Polled SL/TP for {sym_key} ({exit_reason}) skipped (WS exit pending)."); continue

            if sym_key in self.ws_pending_sl_exits: self._log_message(f"Strat exit check for {sym_key} skipped (WS exit pending)."); continue
            strategy_exit_reason = self._check_strategy_specific_exit_condition(sym_key, details, ltp, data_cache.get(sym_key, pd.DataFrame()))
            if strategy_exit_reason: self._attempt_exit_position(sym_key, strategy_exit_reason, details); continue

    def _evaluate_new_entries(self, ts, data_cache):
        if not ts["is_entry_active"]: return
        for stock in self.stock_configs:
            sym, exch, max_fund = stock['symbol'], stock['exchange'], stock['max_fund']
            sym_key = f"{sym}_{exch}"
            if sym_key in self.open_positions: continue
            cooldown_cleared = False
            if sym_key in self.exited_stocks_cooldown:
                if ts["now_ist"] < self.exited_stocks_cooldown[sym_key] + timedelta(minutes=self.re_entry_wait_minutes): continue
                del self.exited_stocks_cooldown[sym_key]; cooldown_cleared = True
            ltp = self._get_ltp(sym, exch)
            if not ltp or ltp <= 0: self._log_message(f"No valid LTP for {sym_key} to eval entry."); continue
            entry_action = self._check_strategy_specific_entry_condition(sym_key, stock, data_cache.get(sym_key, pd.DataFrame()), ltp)
            if entry_action:
                qty = self._calculate_trade_quantity(max_fund, ltp)
                if qty == 0: self._log_message(f"Qty 0 for {sym_key}. Skipping."); continue
                oid = self._place_order_api(sym, exch, entry_action, qty, self.product_type)
                if oid:
                    ok, fill_px, fill_qty = self._confirm_order_execution(oid, entry_action, qty)
                    if ok and fill_qty and fill_qty > 0:
                        sl_px, tp_px = None, None
                        if entry_action.upper() == "BUY":
                            if self.use_stoploss: sl_px = round(fill_px * (1 - self.stoploss_percent / 100), 2)
                            if self.use_target: tp_px = round(fill_px * (1 + self.target_percent / 100), 2)
                        elif entry_action.upper() == "SELL":
                            if self.use_stoploss: sl_px = round(fill_px * (1 + self.stoploss_percent / 100), 2)
                            if self.use_target: tp_px = round(fill_px * (1 - self.target_percent / 100), 2)
                        journal_base = {"entry_order_id": oid, "symbol": sym, "exchange": exch, "product_type": self.product_type,
                                        "position_type": entry_action, "intended_entry_price": ltp, "actual_entry_price": fill_px,
                                        "placed_quantity": qty, "filled_quantity": fill_qty,
                                        "entry_decision_timestamp_ist": ts["now_ist"], "strategy_name": self.strategy_name,
                                        "strategy_parameters": self._get_applicable_strategy_parameters()}
                        self.open_positions[sym_key] = {'action': entry_action, 'quantity': fill_qty, 'entry_price': fill_px,
                                                        'sl_price': sl_px, 'tp_price': tp_px, 'order_id': oid,
                                                        'product': self.product_type, 'entry_time_ist': ts["now_ist"],
                                                        'journal_data': journal_base}
                        if sym_key in self.exited_stocks_cooldown: del self.exited_stocks_cooldown[sym_key]
                        self._save_state();
                        if self.ws_connected: self._subscribe_ws([{"exchange": exch, "symbol": sym}])
                    elif ok: self._log_message(f"ENTRY CONFIRMED for {sym_key} OID:{oid} but 0 fill qty.", level="ERROR")
                    else: self._log_message(f"ENTRY FAILED/REJECTED for {sym_key} OID:{oid}.", level="ERROR")
                else: self._log_message(f"Failed to SEND entry order for {sym_key}.", level="ERROR")
            elif cooldown_cleared: self._save_state()

    def run(self):
        self._load_state()
        if not (self._initialize_openalgo_client() and self._load_stock_configurations()):
            self._log_message("Exiting: Init failure.", level="ERROR"); self._save_state(); return
        if self.ws_url and self._connect_websocket() and self.open_positions:
            subs = [{"exchange": k.split('_')[1], "symbol": k.split('_')[0]} for k in self.open_positions if k not in self.ws_pending_sl_exits]
            if subs: self._log_message(f"WS: Subscribing to {len(subs)} open positions."); self._subscribe_ws(subs)
        try: trade_journaler.initialize_journal()
        except Exception as e: self._log_message(f"Error initializing journaler: {e}.", level="ERROR")

        self._log_message(f"Strategy '{self.strategy_name}' started. Params loaded. Journaling: ~{self.journaling_time_str} IST.")

        EOD_PROCESSING_BUFFER_MINUTES = 30 # How long after market_close_today to keep running normal loop
        PRE_MARKET_WAKEUP_MINUTES = 7    # How many minutes before strategy_start_time to wake up for next session

        try:
            while True:
                now_ist = datetime.now(IST)
                session_times = self._get_next_market_session_times(now_ist) # Assumes this method is now part of BaseStrategy

                # Define the window for active trading day operations
                # Market open today (from strategy_start_time_str)
                # active_window_start_dt = session_times['market_open_today'] # This is the actual strategy start time
                # Market close today (from strategy_end_time_str) + buffer
                active_window_end_dt = session_times['market_close_today'] + timedelta(minutes=EOD_PROCESSING_BUFFER_MINUTES)

                # Determine if we are in the "active period" of a trading day
                # Active period: from PRE_MARKET_WAKEUP_MINUTES before market_open_today until active_window_end_dt
                is_active_period = False
                if session_times['is_trading_day_today']:
                    # Calculate when to start active processing for today
                    start_active_processing_dt = session_times['market_open_today'] - timedelta(minutes=PRE_MARKET_WAKEUP_MINUTES)
                    if now_ist >= start_active_processing_dt and now_ist < active_window_end_dt:
                        is_active_period = True

                if is_active_period:
                    # --- ACTIVE TRADING DAY WINDOW ---
                    ts = self._get_time_status() # Contains now_ist, now_time, is_mkt_open, is_entry_active etc.

                    # Heartbeat log - only if entry window is active, or if positions are open, to reduce noise
                    if ts.get('is_entry_active') or self.open_positions: # Check if self.open_positions is not empty
                        self._log_message(f"Main loop iteration. Entry active: {ts.get('is_entry_active', False)}. Open Positions: {len(self.open_positions)}", level="INFO")

                    # Handle new trading day logic
                    if self.current_trading_day_date is None or now_ist.date() != self.current_trading_day_date:
                        self._log_message(f"New trading day: {now_ist.date()}. Resetting daily flags.")
                        self.journal_written_today = False
                        self.current_trading_day_date = now_ist.date()
                        # Potentially reset other daily states if necessary (e.g., daily trade counters)
                        self._save_state()

                    self._check_for_manual_exits()

                    data_cache = {}
                    active_syms_for_data = {stock_cfg['symbol']+"_"+stock_cfg['exchange'] for stock_cfg in self.stock_configs}
                    active_syms_for_data.update(self.open_positions.keys())

                    if active_syms_for_data:
                        hist_start_date_str = (now_ist - timedelta(days=self.history_days_to_fetch)).strftime('%Y-%m-%d')
                        hist_end_date_str = now_ist.strftime('%Y-%m-%d')
                        for sym_key in active_syms_for_data:
                            s, e = sym_key.split('_')
                            data_cache[sym_key] = self._get_historical_data(s, e, self.timeframe, hist_start_date_str, hist_end_date_str)

                    self._manage_open_positions(ts, data_cache)
                    self._evaluate_new_entries(ts, data_cache)

                    journaling_time_obj = datetime.strptime(self.journaling_time_str, "%H:%M").time()
                    if now_ist.time() >= journaling_time_obj and not self.journal_written_today:
                        if self.trades_to_journal_today:
                            self._log_message(f"EOD journaling for {len(self.trades_to_journal_today)} trades.")
                            try:
                                # Assuming trade_journaler is imported
                                count_journaled = trade_journaler.process_and_write_completed_trades_to_csv(self.openalgo_client, self.trades_to_journal_today)
                                # Only clear if journaling was successful or if no error handling implies it.
                                # For safety, let's assume it processes what it can.
                                if count_journaled > 0 or not self.trades_to_journal_today : # if some were journaled or list is now empty
                                     self.trades_to_journal_today = [t for t in self.trades_to_journal_today if not t.get('_journaled_successfully')] # Example if journaler marks them
                                # A simpler clear if journaler handles its own state:
                                # self.trades_to_journal_today = []
                            except Exception as e_journal:
                                self._log_message(f"EOD journaling error: {e_journal}", level="ERROR")
                        self.journal_written_today = True # Mark true even if trades_to_journal was empty or failed, to prevent re-attempts this cycle.
                        self._save_state()

                    if self.open_positions and not ts.get('is_entry_active', False):
                        self._log_message(f"Open Positions status: {list(self.open_positions.keys())}", level="DEBUG")

                    time.sleep(self.loop_sleep_seconds)

                else:
                    # --- DEEP SLEEP WINDOW ---
                    # Target to wake up a bit before the next session's actual strategy_start_time
                    # next_session_open_dt is the strategy_start_time for the next valid day
                    wake_up_target_dt = session_times['next_session_open_dt'] - timedelta(minutes=PRE_MARKET_WAKEUP_MINUTES)

                    sleep_duration_seconds = (wake_up_target_dt - now_ist).total_seconds()

                    if sleep_duration_seconds > 0: # Only sleep if target is in the future
                        # Cap sleep duration at a max reasonable value (e.g., 24 hours) to prevent extremely long sleeps if logic error
                        max_sleep = 7 * 24 * 60 * 60 # Max sleep capped at 7 days as a safety measure
                        sleep_duration_seconds = min(sleep_duration_seconds, max_sleep)

                        # Only perform a long sleep if it's significantly longer than the normal loop_sleep_seconds
                        if sleep_duration_seconds > self.loop_sleep_seconds * 2: # e.g. more than 2 normal cycles
                            self._log_message(f"Entering deep sleep. Current: {now_ist.strftime('%Y-%m-%d %H:%M:%S')}. Target wake-up: {wake_up_target_dt.strftime('%Y-%m-%d %H:%M:%S')}. Sleeping for {sleep_duration_seconds / 3600:.2f} hours.", level="INFO")
                            time.sleep(sleep_duration_seconds)
                        else:
                            # If calculated sleep is short, just do a normal loop_sleep to re-evaluate soon.
                            # This handles the period just before wake_up_target_dt.
                            time.sleep(self.loop_sleep_seconds)
                    else:
                        # If sleep_duration_seconds is zero or negative (i.e., wake_up_target_dt is now or in the past),
                        # do a short sleep to quickly re-enter the loop and transition to active period.
                        self._log_message(f"Wake-up time reached or past. Current: {now_ist}, Target Wake: {wake_up_target_dt}. Short sleep and re-evaluating.", level="DEBUG")
                        time.sleep(min(self.loop_sleep_seconds, 5)) # Sleep for a very short time or normal loop, whichever is smaller

        except KeyboardInterrupt:
            self._log_message("Strategy stopped by user.")
        except Exception as e:
            self._log_message(f"Critical error in main loop: {e}", level="ERROR")
            import traceback # Import here for use
            self._log_message(f"Traceback: {traceback.format_exc()}", level="ERROR")
        finally:
            self._log_message("Attempting final save state..."); self._save_state()
            if self.ws_url and self.ws_connected: self._disconnect_websocket()
            self._log_message("Strategy shutdown complete.")