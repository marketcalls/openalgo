import os
import json
import time
import re
import asyncio
from datetime import datetime, time as time_obj
import pytz
from dotenv import load_dotenv
import requests
import pandas as pd

from openalgo import api

from ..common_utils.logger import setup_logger
from ..common_utils.state_manager import StateManager
from ..common_utils.trade_journal import TradeJournal

class StrangleStrategy:
    def __init__(self, strategy_name: str):
        self.strategy_name = strategy_name
        self.base_path = os.path.join('option_strategy', self.strategy_name)

        self.config_path = os.path.join(self.base_path, 'config', f"{self.strategy_name}_config.json")
        self.log_path = os.path.join(self.base_path, 'logs')
        self.state_path = os.path.join(self.base_path, 'state')
        self.trades_path = os.path.join(self.base_path, 'trades')

        self._load_config()
        self.mode = self.config.get('mode', 'PAPER')

        self.logger = setup_logger(self.strategy_name, self.log_path, self.mode)
        self.state_manager = StateManager(self.state_path)
        self.journal = TradeJournal(self.strategy_name, self.trades_path, self.mode)
        self.state = self.state_manager.load_state(self.strategy_name, self.mode)

        self._setup_api_client()

        self.live_prices = {}
        self._sym_rx = re.compile(r"^[A-Z]+(\d{2}[A-Z]{3}\d{2})(\d+)(CE|PE)$")
        self.logger.info("Strategy initialized", extra={'event': 'INFO'})

    def _load_config(self):
        with open(self.config_path, 'r') as f:
            self.config = json.load(f)

    def _get_ws_url(self):
        host_url = os.getenv("HOST_SERVER", "")
        if host_url.startswith("https://"):
            return f"wss://{host_url.replace('https://', '')}/ws"
        elif host_url.startswith("http://"):
            return f"ws://{host_url.replace('http://', '').split(':')[0]}:8765"
        return "ws://127.0.0.1:8765"

    def _setup_api_client(self):
        dotenv_path = os.path.join(os.path.dirname(__file__), '..', '..', '.env')
        load_dotenv(dotenv_path=dotenv_path, override=True)
        self.api_key = os.getenv("APP_KEY")
        self.host_server = os.getenv("HOST_SERVER")
        if not self.api_key or not self.host_server:
            raise ValueError("API credentials not found in .env file")

        self.client = api(api_key=self.api_key, host=self.host_server, ws_url=self._get_ws_url())

    def run(self):
        self.logger.info("Starting Strategy", extra={'event': 'INFO'})
        if not self.state.get('active_trade_id'):
            self.state = {'active_trade_id': None, 'active_legs': {}, 'adjustment_count': 0, 'mode': self.mode}

        start_time = time_obj.fromisoformat(self.config['start_time'])
        end_time = time_obj.fromisoformat(self.config['end_time'])
        ist = pytz.timezone("Asia/Kolkata")

        while datetime.now(ist).time() < start_time:
            self.logger.info(f"Waiting for trading window to start at {self.config['start_time']} IST.", extra={'event': 'INFO'})
            time.sleep(30)

        if not self.state.get('active_trade_id'):
            self.execute_entry()

        if self.state.get('active_legs'):
            self._start_monitoring()

        while datetime.now(ist).time() < end_time:
            time.sleep(60)

        self.execute_exit()
        self.logger.info("Trading window ended. Strategy stopped.", extra={'event': 'INFO'})

    def _start_monitoring(self):
        try:
            self.client.connect()
            self.logger.info("WebSocket connected successfully.", extra={'event': 'WEBSOCKET'})
            self._manage_subscriptions()
        except Exception as e:
            self.logger.error(f"WebSocket connection failed: {e}. Switching to fallback.", extra={'event': 'ERROR'})
            self._start_fallback_poll()

    def _start_fallback_poll(self):
        import threading
        self.logger.warning("Starting REST API polling fallback.", extra={'event': 'WEBSOCKET'})
        poll_thread = threading.Thread(target=self._fallback_poll_loop, daemon=True)
        poll_thread.start()

    def _fallback_poll_loop(self):
        interval = self.config['websocket'].get('poll_interval_fallback', 1)
        while True:
            active_legs_copy = list(self.state.get('active_legs', {}).values())
            for leg_info in active_legs_copy:
                symbol = leg_info['symbol']
                quote = self._make_api_request('POST', 'quotes', {"symbol": symbol, "exchange": self.config['exchange']})
                if quote and quote.get('status') == 'success':
                    self._on_tick({'symbol': symbol, 'ltp': quote['data']['ltp']})
            time.sleep(interval)

    def _manage_subscriptions(self, unsubscribe_list=None, subscribe_list=None):
        if unsubscribe_list:
            self.client.unsubscribe_ltp(unsubscribe_list)
            self.logger.info(f"Unsubscribed from: {unsubscribe_list}", extra={'event': 'WEBSOCKET'})

        if subscribe_list:
            self.client.subscribe_ltp(subscribe_list, on_data_received=self._on_tick)
            self.logger.info(f"Subscribed to: {subscribe_list}", extra={'event': 'WEBSOCKET'})

        if not unsubscribe_list and not subscribe_list:
            symbols = [leg['symbol'] for leg in self.state['active_legs'].values()]
            symbols.append(self.config['index'])

            instrument_list = []
            for s in symbols:
                exchange = "NSE_INDEX" if s == self.config['index'] else self.config['exchange']
                instrument_list.append({"exchange": exchange, "symbol": s})

            self.client.subscribe_ltp(instrument_list, on_data_received=self._on_tick)
            self.logger.info(f"Initial subscription to: {instrument_list}", extra={'event': 'WEBSOCKET'})

    def execute_entry(self):
        self.logger.info("Attempting new trade entry.", extra={'event': 'ENTRY'})
        try:
            index_symbol = self.config['index']
            expiry_res = self._make_api_request('POST', 'expiry', {"symbol": index_symbol, "exchange": self.config['exchange'], "instrumenttype": 'options'})
            if expiry_res.get('status') != 'success': return
            expiry_date = expiry_res['data'][0]
            formatted_expiry = datetime.strptime(expiry_date, '%d-%b-%y').strftime('%d%b%y').upper()

            quote_res = self._make_api_request('POST', 'quotes', {"symbol": index_symbol, "exchange": "NSE_INDEX"})
            if quote_res.get('status') != 'success': return
            spot_price = quote_res['data']['ltp']
            strike_interval = self.config['strike_interval'][index_symbol]
            atm_strike = int(round(spot_price / strike_interval) * strike_interval)

            strike_diff = self.config['strike_difference'][index_symbol]
            ce_strike, pe_strike = atm_strike + strike_diff, atm_strike - strike_diff
            ce_symbol, pe_symbol = f"{index_symbol}{formatted_expiry}{ce_strike}CE", f"{index_symbol}{formatted_expiry}{pe_strike}PE"

            self.state['active_trade_id'] = self.journal.generate_trade_id()
            self.state['adjustment_count'] = 0

            self.logger.info(f"New trade started with ID: {self.state['active_trade_id']}", extra={'event': 'ENTRY'})

            self._place_leg_order("CALL_SHORT", ce_symbol, ce_strike, "SELL", is_adjustment=False)
            self._place_leg_order("PUT_SHORT", pe_symbol, pe_strike, "SELL", is_adjustment=False)

            self.state_manager.save_state(self.strategy_name, self.mode, self.state)
        except Exception as e:
            self.logger.error(f"Error during entry: {e}", extra={'event': 'ERROR'}, exc_info=True)

    def _on_tick(self, data):
        symbol = data.get('symbol')
        ltp = data.get('ltp')
        if symbol and ltp is not None:
            self.logger.info(f"Tick received: {symbol} @ {ltp}", extra={'event': 'INFO'})
            self.live_prices[symbol] = ltp
            self.monitor_and_adjust()

    def monitor_and_adjust(self):
        self.logger.info("Entering monitor_and_adjust", extra={'event': 'INFO'})

        if not self.state.get('active_trade_id') or not self.config['adjustment']['enabled'] or len(self.state['active_legs']) != 2:
            self.logger.info(f"Guard fail: Trade active? {self.state.get('active_trade_id')}, Adjust enabled? {self.config['adjustment']['enabled']}, Leg count: {len(self.state['active_legs'])}", extra={'event': 'INFO'})
            return

        ce_leg = self.state['active_legs'].get('CALL_SHORT')
        pe_leg = self.state['active_legs'].get('PUT_SHORT')
        if not ce_leg or not pe_leg:
            self.logger.info(f"Guard fail: CE leg exists? {bool(ce_leg)}, PE leg exists? {bool(pe_leg)}", extra={'event': 'INFO'})
            return

        ce_price = self.live_prices.get(ce_leg['symbol'])
        pe_price = self.live_prices.get(pe_leg['symbol'])
        if ce_price is None or pe_price is None:
            self.logger.info(f"Guard fail: CE price found? {ce_price is not None}, PE price found? {pe_price is not None}. Live prices: {self.live_prices}", extra={'event': 'INFO'})
            return

        max_adjustments = self.config['adjustment'].get('max_adjustments', 5)
        if self.state['adjustment_count'] >= max_adjustments: return

        threshold = self.config['adjustment']['threshold_ratio']

        # Clarify logic by finding smaller and larger price first
        if ce_price < pe_price:
            smaller_price, larger_price = ce_price, pe_price
            smaller_leg, larger_leg = 'CALL_SHORT', 'PUT_SHORT'
        else:
            smaller_price, larger_price = pe_price, ce_price
            smaller_leg, larger_leg = 'PUT_SHORT', 'CALL_SHORT'

        trigger_value = larger_price * threshold
        is_triggered = smaller_price < trigger_value

        # Add detailed diagnostic logging
        self.logger.info(
            f"Diagnostics: Smaller Leg ({smaller_leg}@{smaller_price}) | "
            f"Larger Leg ({larger_leg}@{larger_price}) | "
            f"Threshold ({threshold}) | Trigger Value ({trigger_value:.2f}) | "
            f"Condition: {smaller_price:.2f} < {trigger_value:.2f} | "
            f"Triggered: {is_triggered}",
            extra={'event': 'INFO'}
        )

        if is_triggered:
            losing_leg_type = smaller_leg
            winning_leg_price = larger_price
            self.logger.info(f"Adjustment triggered for {losing_leg_type} leg.", extra={'event': 'ADJUSTMENT'})
            self.state['adjustment_count'] += 1
            self._perform_adjustment(losing_leg_type, winning_leg_price)
            self.state_manager.save_state(self.strategy_name, self.mode, self.state)

    def _perform_adjustment(self, losing_leg_type: str, target_premium: float):
        losing_leg_info = self.state['active_legs'][losing_leg_type]
        self._manage_subscriptions(unsubscribe_list=[{"exchange": self.config['exchange'], "symbol": losing_leg_info['symbol']}])
        self._square_off_leg(losing_leg_type, losing_leg_info, is_adjustment=True)

        remaining_leg_type = 'PUT_SHORT' if losing_leg_type == 'CALL_SHORT' else 'CALL_SHORT'
        remaining_leg_strike = self.state['active_legs'][remaining_leg_type]['strike']

        new_leg_info = asyncio.run(self._find_new_leg(losing_leg_type, target_premium))
        if not new_leg_info:
            self.execute_exit("Failed to find adjustment leg")
            return

        new_strike = new_leg_info['strike']
        if (losing_leg_type == 'PUT_SHORT' and remaining_leg_strike < new_strike) or \
           (losing_leg_type == 'CALL_SHORT' and new_strike < remaining_leg_strike):
            self.execute_exit("Inverted strangle condition")
            return

        self._place_leg_order(losing_leg_type, new_leg_info['symbol'], new_leg_info['strike'], "SELL", is_adjustment=True)
        self._manage_subscriptions(subscribe_list=[{"exchange": self.config['exchange'], "symbol": new_leg_info['symbol']}])

    async def _find_new_leg(self, option_type: str, target_premium: float) -> dict:
        ot = "CE" if "CALL" in option_type else "PE"
        index_symbol = self.config['index']
        quote_res = self._make_api_request('POST', 'quotes', {"symbol": index_symbol, "exchange": "NSE_INDEX"})
        spot_price = quote_res['data']['ltp']
        strike_interval = self.config['strike_interval'][index_symbol]
        atm_strike = int(round(spot_price / strike_interval) * strike_interval)

        radius = self.config['adjustment']['strike_search_radius']
        strikes_to_check = [atm_strike + i * strike_interval for i in range(-radius, radius + 1)]

        active_leg = next(iter(self.state['active_legs'].values()))
        m = self._sym_rx.match(active_leg['symbol'])
        expiry_str = m.group(1)

        symbols_to_check = [f"{index_symbol}{expiry_str}{k}{ot}" for k in strikes_to_check]

        tasks = [asyncio.to_thread(self._make_api_request, 'POST', 'quotes', {"symbol": s, "exchange": self.config['exchange']}) for s in symbols_to_check]
        results = await asyncio.gather(*tasks)

        successful_quotes = []
        for res in results:
            if res and res.get('status') == 'success':
                successful_quotes.append(res['data'])

        return min(successful_quotes, key=lambda q: abs(q['ltp'] - target_premium)) if successful_quotes else None

    def execute_exit(self, reason="Scheduled Exit"):
        if self.client and self.client.is_connected():
            self.client.disconnect()
        self.logger.info(f"Closing trade {self.state.get('active_trade_id')} due to: {reason}", extra={'event': 'EXIT'})
        for leg_type, leg_info in list(self.state['active_legs'].items()):
            self._square_off_leg(leg_type, leg_info, is_adjustment=False)
        self.state = {}
        self.state_manager.save_state(self.strategy_name, self.mode, self.state)

    def _place_leg_order(self, leg_type: str, symbol: str, strike: int, action: str, is_adjustment: bool):
        mode = self.config['mode']
        lots = self.config['quantity_in_lots']
        lot_size = self.config['lot_size'][self.config['index']]
        total_quantity = lots * lot_size

        self.logger.info(f"Placing {action} {leg_type} order for {symbol}", extra={'event': 'ORDER'})

        if mode == 'LIVE':
            payload = {"symbol": symbol, "action": action, "quantity": str(total_quantity), "product": self.config['product_type'], "exchange": self.config['exchange'], "pricetype": "MARKET", "strategy": self.strategy_name}
            order_res = self._make_api_request('POST', 'placeorder', payload)
            if order_res.get('status') == 'success':
                order_id = order_res.get('orderid')
                self.journal.record_trade(self.state['active_trade_id'], order_id, action, symbol, total_quantity, 0, leg_type, is_adjustment, mode)
                if action == "SELL": self.state['active_legs'][leg_type] = {'symbol': symbol, 'strike': strike}
            else:
                self.logger.error(f"Failed to place LIVE order for {symbol}", extra={'event': 'ERROR'})
        elif mode == 'PAPER':
            quote_res = self._make_api_request('POST', 'quotes', {"symbol": symbol, "exchange": self.config['exchange']})
            if quote_res.get('status') == 'success':
                price = quote_res['data']['ltp']
                order_id = f'paper_{int(time.time())}'
                self.journal.record_trade(self.state['active_trade_id'], order_id, action, symbol, total_quantity, price, leg_type, is_adjustment, mode)
                if action == "SELL": self.state['active_legs'][leg_type] = {'symbol': symbol, 'strike': strike}
            else:
                self.logger.error(f"Could not fetch quote for {symbol} for paper trade.", extra={'event': 'ERROR'})

    def _square_off_leg(self, leg_type: str, leg_info: dict, is_adjustment: bool):
        self.logger.info(f"Squaring off {leg_type} leg: {leg_info['symbol']}", extra={'event': 'ADJUSTMENT' if is_adjustment else 'EXIT'})
        self._place_leg_order(leg_type, leg_info['symbol'], leg_info['strike'], "BUY", is_adjustment=is_adjustment)
        self.state['active_legs'].pop(leg_type, None)

    def _make_api_request(self, method: str, endpoint: str, payload: dict = None):
        url = f"{self.host_server}/api/v1/{endpoint}"
        req_payload = payload or {}
        req_payload['apikey'] = self.api_key
        try:
            if method.upper() == 'POST':
                response = requests.post(url, json=req_payload, timeout=10)
            else:
                response = requests.get(url, params=req_payload, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            self.logger.error(f"API request to {endpoint} failed: {e}", extra={'event': 'ERROR'})
            return {"status": "error", "message": str(e)}