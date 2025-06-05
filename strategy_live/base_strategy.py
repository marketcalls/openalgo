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
    def __init__(self, strategy_name, api_key, host_url, ws_url=None, # ADDED ws_url
                 stocks_csv_name="stocks.csv",
                 product_type="CNC", timeframe="5m",
                 strategy_start_time_str="09:20", strategy_end_time_str="15:10",
                 journaling_time_str="15:31",
                 re_entry_wait_minutes=30,
                 use_stoploss=True, stoploss_percent=3.0,
                 use_target=True, target_percent=7.0,
                 history_days_to_fetch=15, loop_sleep_seconds=60,
                 order_confirmation_attempts=5, order_confirmation_delay_seconds=2,
                 strategy_specific_params=None): # For parameters unique to derived strategy

        self.strategy_name = strategy_name
        self.api_key = api_key
        self.host_url = host_url
        self.ws_url = ws_url # ADDED
        self.stocks_csv_path = os.path.join(STRATEGIES_DIR, stocks_csv_name)
        self.state_file_path = os.path.join(STRATEGIES_DIR, f"{self.strategy_name}_state.json")

        self.product_type = product_type
        self.timeframe = timeframe
        self.strategy_start_time_str = strategy_start_time_str
        self.strategy_end_time_str = strategy_end_time_str
        self.journaling_time_str = journaling_time_str
        self.re_entry_wait_minutes = re_entry_wait_minutes
        self.use_stoploss = use_stoploss
        self.stoploss_percent = stoploss_percent
        self.use_target = use_target
        self.target_percent = target_percent
        self.history_days_to_fetch = history_days_to_fetch
        self.loop_sleep_seconds = loop_sleep_seconds
        self.order_confirmation_attempts = order_confirmation_attempts
        self.order_confirmation_delay_seconds = order_confirmation_delay_seconds
        
        self.strategy_specific_params = strategy_specific_params if strategy_specific_params else {}

        self.openalgo_client = None
        self.open_positions = {}
        self.exited_stocks_cooldown = {}
        self.stock_configs = []
        self.trades_to_journal_today = []
        self.journal_written_today = False
        self.current_trading_day_date = None

        # WebSocket related attributes
        self.subscribed_symbols_ws = set() # ADDED
        self.ws_connected = False # ADDED
        self.ws_pending_sl_exits = set() # ADDED

        self._log_message(f"BaseStrategy initialized for '{self.strategy_name}'")

    def _log_message(self, message, level="INFO"):
        full_message = f"{datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S %Z%z')} - {self.strategy_name} - {level} - {message}"
        print(full_message)
        if level == "ERROR":
            try:
                tb_info = traceback.format_exc()
                if "NoneType: None" not in tb_info:
                     print(f"{datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S %Z%z')} - {self.strategy_name} - TRACEBACK - {tb_info.strip()}")
            except Exception: pass

    def _serialize_datetime(self, dt_obj):
        return dt_obj.isoformat() if isinstance(dt_obj, (datetime, datetime.now(IST).date().__class__)) else dt_obj

    def _deserialize_datetime(self, dt_str):
        if not isinstance(dt_str, str): return dt_str
        try:
            dt_obj = datetime.fromisoformat(dt_str)
            if isinstance(dt_obj, datetime): # Full datetime object
                return dt_obj.astimezone(IST) if dt_obj.tzinfo else IST.localize(dt_obj)
            return dt_obj # Likely a date object
        except ValueError:
            self._log_message(f"Could not parse datetime string '{dt_str}'.", level="ERROR")
            return None

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
            with open(self.state_file_path, 'w') as f: json.dump(state, f, indent=4)
            self._log_message(f"State saved. Positions: {len(self.open_positions)}, Journal Pending: {len(self.trades_to_journal_today)}")
        except Exception as e:
            self._log_message(f"Error saving state: {e}", level="ERROR")

    def _load_state(self):
        default_date = datetime.now(IST).date()
        if not os.path.exists(self.state_file_path):
            self._log_message("No state file. Starting fresh.")
            self.current_trading_day_date = default_date
            return

        try:
            with open(self.state_file_path, 'r') as f: loaded = json.load(f)
            
            for k, v_s in loaded.get("open_positions", {}).items():
                v_d = v_s.copy()
                v_d['entry_time_ist'] = self._deserialize_datetime(v_d.get('entry_time_ist'))
                if 'journal_data' in v_d and v_d['journal_data']:
                     v_d['journal_data']['entry_decision_timestamp_ist'] = self._deserialize_datetime(v_d['journal_data'].get('entry_decision_timestamp_ist'))
                self.open_positions[k] = v_d

            self.exited_stocks_cooldown = {k: self._deserialize_datetime(v) for k, v in loaded.get("exited_stocks_cooldown", {}).items()}
            
            for t_s in loaded.get("trades_to_journal_today", []):
                t_d = t_s.copy()
                t_d['entry_decision_timestamp_ist'] = self._deserialize_datetime(t_d.get('entry_decision_timestamp_ist'))
                t_d['exit_decision_timestamp_ist'] = self._deserialize_datetime(t_d.get('exit_decision_timestamp_ist'))
                self.trades_to_journal_today.append(t_d)

            self.journal_written_today = loaded.get("journal_written_today", False)
            date_obj_or_str = self._deserialize_datetime(loaded.get("current_trading_day_date"))
            self.current_trading_day_date = date_obj_or_str if isinstance(date_obj_or_str, datetime.now(IST).date().__class__) else default_date

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
            self._log_message(f"Error: {self.stocks_csv_path} not found.", level="ERROR"); return False
        try:
            df = pd.read_csv(self.stocks_csv_path)
            if not {'symbol', 'exchange', 'max_fund'}.issubset(df.columns):
                self._log_message("Error: CSV needs 'symbol', 'exchange', 'max_fund'.", level="ERROR"); return False
            self.stock_configs = df.to_dict('records')
            self._log_message(f"Loaded {len(self.stock_configs)} stock configs."); return True
        except Exception as e:
            self._log_message(f"Error loading stock configs: {e}", level="ERROR"); return False

    def _get_historical_data(self, symbol, exchange, interval, start_date_str, end_date_str):
        try:
            hist_df = self.openalgo_client.history(symbol=symbol, exchange=exchange, interval=interval, start_date=start_date_str, end_date=end_date_str)
            return hist_df if isinstance(hist_df, pd.DataFrame) else pd.DataFrame()
        except Exception as e:
            self._log_message(f"Error fetching history for {symbol} ({exchange}): {e}", level="ERROR"); return pd.DataFrame()

    def _get_ltp(self, symbol, exchange):
        try:
            q = self.openalgo_client.quotes(symbol=symbol, exchange=exchange)
            if q and q.get('status') == 'success' and 'data' in q and 'ltp' in q['data']: return float(q['data']['ltp'])
            self._log_message(f"Could not fetch LTP for {symbol} ({exchange}). Resp: {q}"); return None
        except Exception as e:
            self._log_message(f"Error fetching LTP for {symbol} ({exchange}): {e}", level="ERROR"); return None

    def _calculate_trade_quantity(self, max_fund, ltp):
        return math.floor(max_fund / ltp) if ltp and ltp > 0 else 0

    def _place_order_api(self, symbol, exchange, action, quantity, product, price_type="MARKET", price=0, trigger_price=0):
        if quantity <= 0: self._log_message(f"Skipping order {symbol} Qty 0."); return None
        try:
            self._log_message(f"Placing {action} order: {symbol} Qty:{quantity} Prod:{product} Type:{price_type}")
            params = {"strategy": self.strategy_name, "symbol": symbol, "action": action.upper(), "exchange": exchange,
                      "price_type": price_type.upper(), "product": product.upper(), "quantity": str(quantity),
                      "price": str(price) if price_type.upper() == "LIMIT" else "0",
                      "trigger_price": str(trigger_price) if trigger_price > 0 else "0"}
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
                        self._log_message(f"OID {order_id} CONFIRMED COMPLETE. FillPrice: {fill_price}, FillQty: {fill_quantity}")
                        return True, fill_price, fill_quantity #MODIFIED HERE
                    if status_api == 'rejected':
                        self._log_message(f"OID {order_id} REJECTED. Reason: {data.get('remarks', 'N/A')}", level="ERROR"); return False, None, None
                    if status_api in ['pending', 'open', 'trigger pending', 'validation pending', 'put order req received', 'queued', 'modified', 'new']:
                        self._log_message(f"OID {order_id} is PENDING ({status_api}). Waiting...")
                    else: self._log_message(f"OID {order_id} unhandled status: '{status_api}'.", level="ERROR")
                else: self._log_message(f"Failed to get valid status for OID {order_id} (Atmpt {i+1}). Resp: {response}", level="ERROR")
                if i < self.order_confirmation_attempts - 1: time.sleep(self.order_confirmation_delay_seconds)
            except Exception as e:
                self._log_message(f"Exception during order confirm for {order_id} (Atmpt {i+1}): {e}", level="ERROR")
                if i < self.order_confirmation_attempts - 1: time.sleep(self.order_confirmation_delay_seconds)
        self._log_message(f"OID {order_id} NOT CONFIRMED 'complete' after {self.order_confirmation_attempts} attempts.", level="ERROR")
        return False, None, None

    def _get_time_status(self):
        now_ist = datetime.now(IST); now_time = now_ist.time()
        mkt_o = dt_time(9, 15); mkt_c = dt_time(15, 30)
        strat_s = datetime.strptime(self.strategy_start_time_str, "%H:%M").time()
        strat_e = datetime.strptime(self.strategy_end_time_str, "%H:%M").time()
        journal_t = datetime.strptime(self.journaling_time_str, "%H:%M").time()
        is_mkt_open = mkt_o <= now_time <= mkt_c
        return {"now_ist": now_ist, "now_time": now_time,
                "is_entry_active": is_mkt_open and strat_s <= now_time < strat_e,
                "is_mis_sq_off": is_mkt_open and now_time >= strat_e,
                "is_journal_time": now_time >= journal_t}

    def _attempt_exit_position(self, symbol_key, reason, pos_details_orig):
        pos_details = pos_details_orig.copy() # Work with a copy
        symbol, exchange = symbol_key.split('_') # Moved here to be available for finally block if needed
        try:
            self._log_message(f"Attempting EXIT for {symbol_key} ({pos_details['action']}) due to: {reason}")
            exit_action = "SELL" if pos_details['action'].upper() == "BUY" else "BUY"
            expected_exit_qty = pos_details['quantity']

            exit_order_id = self._place_order_api(symbol, exchange, exit_action, expected_exit_qty, pos_details['product'])
            if exit_order_id:
                is_confirmed, fill_price, fill_qty = self._confirm_order_execution(exit_order_id, exit_action, expected_exit_qty)
                if is_confirmed:
                    self._log_message(f"EXIT CONFIRMED for {symbol_key}. OID: {exit_order_id}, FillPrice: {fill_price}, FillQty: {fill_qty}")
                    if 'journal_data' in pos_details and isinstance(pos_details['journal_data'], dict):
                        self.trades_to_journal_today.append({
                            **pos_details['journal_data'], 'exit_order_id': exit_order_id,
                            'exit_decision_timestamp_ist': datetime.now(IST), 'exit_reason': reason,
                            'intended_exit_price': fill_price
                        })
                    if symbol_key in self.open_positions: del self.open_positions[symbol_key]
                    self.exited_stocks_cooldown[symbol_key] = datetime.now(IST)

                    # Unsubscribe from WS LTP after successful exit
                    if self.ws_connected:
                        self._log_message(f"WS: Unsubscribing from LTP for closed position {symbol_key}")
                        self._unsubscribe_ws([{"exchange": exchange, "symbol": symbol}])

                    self._save_state()
                else: self._log_message(f"EXIT FAILED/REJECTED for {symbol_key}. OID: {exit_order_id}. Position REMAINS OPEN.", level="ERROR")
            else: self._log_message(f"Failed to SEND exit order for {symbol_key}. Position REMAINS OPEN.", level="ERROR")
        finally:
            self.ws_pending_sl_exits.discard(symbol_key) # Ensure it's removed

    def _get_applicable_strategy_parameters(self):
        """Returns parameters relevant for journaling, including strategy-specific ones."""
        base_params = {
            "PRODUCT_TYPE": self.product_type, "TIMEFRAME": self.timeframe,
            "STRATEGY_START_TIME_STR": self.strategy_start_time_str,
            "STRATEGY_END_TIME_STR": self.strategy_end_time_str,
            "RE_ENTRY_WAIT_MINUTES": self.re_entry_wait_minutes,
            "USE_STOPLOSS": self.use_stoploss, "STOPLOSS_PERCENT": self.stoploss_percent,
            "USE_TARGET": self.use_target, "TARGET_PERCENT": self.target_percent,
        }
        # Merge with strategy-specific parameters, giving precedence to strategy-specific ones if keys overlap
        return {**base_params, **self.strategy_specific_params}

    def _check_for_manual_exits(self):
        if not self.open_positions:
            return

        self._log_message("Checking for manual/external exits...")
        try:
            broker_positions_response = self.openalgo_client.positionbook() # Or equivalent method
            if not broker_positions_response or broker_positions_response.get('status') != 'success' or not isinstance(broker_positions_response.get('data'), list):
                self._log_message("Failed to fetch or parse position book for manual exit check.", level="ERROR")
                return
            broker_positions_raw = broker_positions_response['data']
        except Exception as e:
            self._log_message(f"Exception fetching position book for manual exit check: {e}", level="ERROR")
            return

        broker_positions_map = {}
        for pos in broker_positions_raw:
            sym = pos.get('symbol')
            exch = pos.get('exchange')
            try:
                qty = float(pos.get('quantity', 0))
            except ValueError:
                self._log_message(f"Invalid quantity type for {sym}_{exch} in position book: {pos.get('quantity')}", level="WARNING")
                continue # Skip this position
            prod = pos.get('product') # Or 'product_type', 'instrument_type' etc. - adjust to actual API response

            if not sym or not exch or not prod:
                self._log_message(f"Skipping position due to missing sym/exch/prod: {pos}", level="WARNING")
                continue

            # Only consider positions from broker that match the strategy's current product_type
            if prod.upper() == self.product_type.upper(): # Case-insensitive comparison for product type
                 broker_positions_map[f"{sym}_{exch}"] = qty

        for symbol_key, strat_pos_details in list(self.open_positions.items()):
            if strat_pos_details.get('product', '').upper() != self.product_type.upper(): # Should ideally not happen
                self._log_message(f"Skipping {symbol_key} in manual exit check due to product mismatch ('{strat_pos_details.get('product')}' vs '{self.product_type}').", level="WARNING")
                continue

            broker_qty = broker_positions_map.get(symbol_key, 0.0) # Default to 0 if not in map for this product type
            strategy_qty = strat_pos_details['quantity'] # This is always positive in our system

            manual_exit_detected = False
            current_pos_action = strat_pos_details.get('action', '').upper()

            if current_pos_action == 'BUY':
                # If strategy holds a long position, and broker quantity is less than strategy quantity
                if broker_qty < strategy_qty:
                    # Allow for small discrepancies due to partial fills not perfectly synced, if necessary
                    # For now, any reduction is considered a manual change.
                    manual_exit_detected = True
            elif current_pos_action == 'SELL': # Strategy is short
                # Strategy quantity is positive. Broker quantity for short is negative.
                # e.g., strategy shorted 100 (strategy_qty=100), broker_qty should be -100.
                # If broker_qty is now -50 (partial cover), 0 (full cover), or >0 (flipped to long), it's a manual change.
                # So, if broker_qty > -strategy_qty
                if broker_qty > -strategy_qty:
                    manual_exit_detected = True

            if manual_exit_detected:
                self._log_message(f"Manual/External exit detected for {symbol_key}. Strategy Action: {current_pos_action}, Strategy Qty: {strategy_qty}, Broker Qty: {broker_qty}", level="INFO")

                s, e = symbol_key.split('_')
                ltp = self._get_ltp(s, e)
                # Use LTP at detection as exit price. Fallback to entry if LTP unavailable.
                exit_price_for_journal = ltp if ltp is not None and ltp > 0 else strat_pos_details.get('entry_price', 0.0)

                original_journal_data = strat_pos_details.get('journal_data', {})

                journal_entry_for_manual_exit = {
                    **original_journal_data, # Includes original entry details
                    'exit_order_id': "MANUAL_EXIT",
                    'exit_decision_timestamp_ist': datetime.now(IST),
                    'exit_reason': "MANUAL_EXIT",
                    'intended_exit_price': exit_price_for_journal, # LTP at detection time
                    'filled_quantity': original_journal_data.get('filled_quantity', strategy_qty), # Journal the strategy's original filled quantity for this trade leg
                    # actual_exit_price for journal will be same as intended_exit_price for manual exits.
                    # GrossP&L etc. will be calculated by journaler based on this.
                }
                self.trades_to_journal_today.append(journal_entry_for_manual_exit)

                del self.open_positions[symbol_key]
                self.exited_stocks_cooldown[symbol_key] = datetime.now(IST) # Apply cooldown

                if self.ws_connected:
                    self._log_message(f"WS: Unsubscribing for manually exited {symbol_key}")
                    self._unsubscribe_ws([{"exchange": e, "symbol": s}])
                self.ws_pending_sl_exits.discard(symbol_key) # Clear any pending WS SL exit for this symbol

                self._save_state()
                self._log_message(f"Processed manual exit for {symbol_key}. Position removed, journaled, and state saved.")

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
            if sym_key not in self.open_positions: continue # Position might have been closed
            details = details_orig.copy()
            symbol, exchange = sym_key.split('_'); ltp = self._get_ltp(symbol, exchange)
            if ltp is None: self._log_message(f"No LTP for managing {sym_key}, skipping."); continue
            
            action = details.get('action', '').upper(); product = details.get('product', self.product_type).upper()

            # 1. MIS Square-off (common)
            if product == "MIS" and ts["is_mis_sq_off"]:
                if sym_key not in self.ws_pending_sl_exits: # Don't attempt if WS already trying
                    self._attempt_exit_position(sym_key, "MIS EOD Square-Off", details); continue
                else:
                    self._log_message(f"MIS EOD for {sym_key} skipped as WS exit is pending.", level="INFO")
                    continue # Skip other checks if WS exit is pending
            
            # 2. Stop-Loss / Take-Profit (common) - Polled Fallback
            exit_reason = None
            if sym_key not in self.ws_pending_sl_exits: # Only consider polled SL if not already being handled by WS
                if action == "BUY":
                    if self.use_stoploss and details.get('sl_price') and ltp <= details['sl_price']:
                        exit_reason = f"SL hit at {ltp} (polled BUY)"
                    elif self.use_target and details.get('tp_price') and ltp >= details['tp_price']:
                        exit_reason = f"TP hit at {ltp} (polled BUY)"
                elif action == "SELL": # Basic short SL/TP
                    if self.use_stoploss and details.get('sl_price') and ltp >= details['sl_price']:
                        exit_reason = f"SL hit at {ltp} (polled SELL)"
                    elif self.use_target and details.get('tp_price') and ltp <= details['tp_price']: # Assuming target for short is lower
                        exit_reason = f"TP hit at {ltp} (polled SELL)"

                if exit_reason:
                    self._attempt_exit_position(sym_key, exit_reason, details); continue
            elif exit_reason: # If ws_pending_sl_exits has the symbol, but we somehow re-evaluated exit_reason
                 self._log_message(f"Polled SL/TP for {sym_key} ({exit_reason}) skipped as WS exit is pending.", level="INFO")
                 continue


            # 3. Strategy-specific exit condition
            if sym_key in self.ws_pending_sl_exits: # Skip if WS is already handling an exit
                self._log_message(f"Strategy specific exit check for {sym_key} skipped as WS exit is pending.", level="INFO")
                continue
            hist_df = data_cache.get(sym_key, pd.DataFrame())
            strategy_exit_reason = self._check_strategy_specific_exit_condition(sym_key, details, ltp, hist_df)
            if strategy_exit_reason:
                self._attempt_exit_position(sym_key, strategy_exit_reason, details); continue

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
            
            hist_df = data_cache.get(sym_key, pd.DataFrame())
            # Derived strategy's entry condition will check hist_df emptiness/length
            
            ltp_at_signal = self._get_ltp(sym, exch) # Get LTP before checking signal
            if not ltp_at_signal or ltp_at_signal <= 0:
                self._log_message(f"No valid LTP for {sym_key} to evaluate entry. Skipping.")
                continue

            entry_action = self._check_strategy_specific_entry_condition(sym_key, stock, hist_df, ltp_at_signal)

            if entry_action:
                self._log_message(f"ENTRY SIGNAL: {entry_action} for {sym_key} by strategy.")
                expected_entry_qty = self._calculate_trade_quantity(max_fund, ltp_at_signal)
                if expected_entry_qty == 0:
                    self._log_message(f"Qty 0 for {sym_key} (MaxFund:{max_fund}, LTP:{ltp_at_signal}). Skipping."); continue
                
                entry_order_id = self._place_order_api(sym, exch, entry_action, expected_entry_qty, self.product_type)
                if entry_order_id:
                    is_confirmed, confirmed_fill_price, confirmed_fill_qty = self._confirm_order_execution(entry_order_id, entry_action, expected_entry_qty)

                    if is_confirmed and confirmed_fill_qty is not None and confirmed_fill_qty > 0:
                        self._log_message(f"ENTRY CONFIRMED for {sym_key}. OID: {entry_order_id}, FillPrice: {confirmed_fill_price}, FillQty: {confirmed_fill_qty}")
                        
                        sl_price, tp_price = None, None
                        if entry_action.upper() == "BUY":
                            if self.use_stoploss: sl_price = round(confirmed_fill_price * (1 - self.stoploss_percent / 100), 2)
                            if self.use_target: tp_price = round(confirmed_fill_price * (1 + self.target_percent / 100), 2)
                        # Add short SL/TP logic here

                        journal_base = {
                            "entry_order_id": entry_order_id, "symbol": sym, "exchange": exch,
                            "product_type": self.product_type, "position_type": entry_action,
                            "intended_entry_price": ltp_at_signal, # LTP at decision time
                            "actual_entry_price": confirmed_fill_price, # Actual execution price
                            "placed_quantity": expected_entry_qty, # Quantity attempted
                            "filled_quantity": confirmed_fill_qty, # Actual executed quantity
                            "entry_decision_timestamp_ist": ts["now_ist"],
                            "strategy_name": self.strategy_name,
                            "strategy_parameters": self._get_applicable_strategy_parameters()
                        }
                        self.open_positions[sym_key] = {
                            'action': entry_action,
                            'quantity': confirmed_fill_qty, # Use confirmed filled quantity
                            'entry_price': confirmed_fill_price, # Use confirmed fill price
                            'sl_price': sl_price, 'tp_price': tp_price, 'order_id': entry_order_id,
                            'product': self.product_type, 'entry_time_ist': ts["now_ist"],
                            'journal_data': journal_base
                        }
                        if sym_key in self.exited_stocks_cooldown: del self.exited_stocks_cooldown[sym_key]
                        self._save_state() # Save state before attempting WS subscription

                        if self.ws_connected: # sym, exch are from earlier in the method
                            self._log_message(f"WS: Subscribing to LTP for new position {sym_key}")
                            self._subscribe_ws([{"exchange": exch, "symbol": sym}])

                    elif is_confirmed: # Order was 'complete' but fill_qty was 0 or None
                        self._log_message(f"ENTRY CONFIRMED for {sym_key} (OID: {entry_order_id}) but with zero or invalid fill quantity ({confirmed_fill_qty}). Not opening position.", level="ERROR")
                    else: # Order was not confirmed (e.g. rejected, timed out)
                        self._log_message(f"ENTRY FAILED/REJECTED for {sym_key}. OID: {entry_order_id}. Not taking position.", level="ERROR")
                else:
                    self._log_message(f"Failed to SEND entry order for {sym_key}.", level="ERROR")
            elif cooldown_cleared:
                self._save_state()

    def run(self):
        self._load_state()
        if not (self._initialize_openalgo_client() and self._load_stock_configurations()):
            self._log_message("Exiting due to initialization failure.", level="ERROR"); self._save_state(); return

        if self.ws_url:
            if self._connect_websocket():
                if self.open_positions:
                    subs_to_make = []
                    for sym_key_state in list(self.open_positions.keys()):
                        s, e = sym_key_state.split('_')
                        # Also ensure these are not pending exit from a previous crash or state
                        if sym_key_state not in self.ws_pending_sl_exits:
                             subs_to_make.append({"exchange": e, "symbol": s})
                        else:
                            self._log_message(f"WS: {sym_key_state} found in ws_pending_sl_exits at startup. Will not subscribe initially.", level="WARNING")
                    if subs_to_make:
                        self._log_message(f"WS: Subscribing to LTP for {len(subs_to_make)} existing open positions on startup.")
                        self._subscribe_ws(subs_to_make)
            else:
                self._log_message("WS: Failed to connect, WebSocket features disabled for this session.", level="WARNING")
        else:
            self._log_message("WS: No WebSocket URL configured. Running without WebSocket features.", level="INFO")
        
        try: trade_journaler.initialize_journal()
        except Exception as e: self._log_message(f"Error initializing journaler: {e}.", level="ERROR")
        
        self._log_message(f"Strategy '{self.strategy_name}' started. Product: {self.product_type}, TF: {self.timeframe}. Journaling: ~{self.journaling_time_str} IST.")
        
        try:
            while True:
                ts = self._get_time_status()
                if self.current_trading_day_date is None or ts["now_ist"].date() != self.current_trading_day_date:
                    self._log_message(f"New trading day: {ts['now_ist'].date()}. Resetting daily journal flag.")
                    self.journal_written_today = False; self.current_trading_day_date = ts["now_ist"].date(); self._save_state()
                
                self._check_for_manual_exits() # ADDED CALL

                data_cache = {}
                # Re-evaluate active_symbols after manual exit check, as positions might have closed
                active_symbols = {s['symbol'] + "_" + s['exchange'] for s in self.stock_configs}.union(self.open_positions.keys())
                if active_symbols:
                    end_date = ts["now_ist"]; start_date = end_date - timedelta(days=self.history_days_to_fetch)
                    sd_str, ed_str = start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d')
                    for sym_key in active_symbols:
                        s, e = sym_key.split('_'); data_cache[sym_key] = self._get_historical_data(s, e, self.timeframe, sd_str, ed_str)
                
                self._manage_open_positions(ts, data_cache)
                self._evaluate_new_entries(ts, data_cache)
                
                if ts["is_journal_time"] and not self.journal_written_today:
                    if self.trades_to_journal_today:
                        self._log_message(f"Attempting EOD journaling for {len(self.trades_to_journal_today)} trades.")
                        try:
                            journaled_count = trade_journaler.process_and_write_completed_trades_to_csv(self.openalgo_client, self.trades_to_journal_today)
                            self._log_message(f"Journaling done. {journaled_count} trades written.")
                            if journaled_count > 0 or len(self.trades_to_journal_today) > 0: self.trades_to_journal_today = []
                        except Exception as e: self._log_message(f"Critical error during EOD journaling: {e}", level="ERROR")
                    else: self._log_message("Journaling time, but no completed trades to journal.")
                    self.journal_written_today = True; self._save_state()

                if self.open_positions: self._log_message(f"Open Positions ({len(self.open_positions)}): {list(self.open_positions.keys())}")
                time.sleep(self.loop_sleep_seconds)
        except KeyboardInterrupt: self._log_message("Strategy stopped by user.")
        except Exception as e: self._log_message(f"Critical error in main loop: {e}", level="ERROR")
        finally:
            self._log_message("Attempting to save final state on exit...")
            self._save_state()
            if self.ws_url and self.ws_connected: # Ensure ws_url was configured before trying to disconnect
                self._disconnect_websocket()
            self._log_message("Strategy shutdown complete.")