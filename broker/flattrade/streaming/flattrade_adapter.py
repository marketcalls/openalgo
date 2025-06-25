from utils.logging import get_logger

logger = get_logger(__name__)

"""
Flattrade WebSocket adapter for OpenAlgo WebSocket proxy
"""
import threading
import os
from typing import Dict, Any, Optional
import json
import time

from broker.flattrade.streaming.flattrade_websocket import FlattradeWebSocket
from database.auth_db import get_auth_token
from database.token_db import get_token

from websocket_proxy.base_adapter import BaseBrokerWebSocketAdapter
from websocket_proxy.mapping import SymbolMapper
from .flattrade_mapping import FlattradeExchangeMapper, FlattradeCapabilityRegistry

class FlattradeWebSocketAdapter(BaseBrokerWebSocketAdapter):
    """Flattrade-specific implementation of the WebSocket adapter"""
    def __init__(self):
        super().__init__()
        self.logger = get_logger("flattrade_websocket_adapter")
        self.ws_client = None
        self.user_id = None
        self.actid = None
        self.susertoken = None
        self.broker_name = "flattrade"
        self.running = False
        self.lock = threading.Lock()
        self.subscriptions = {}  # {(symbol, exchange, mode): True}
        self.token_symbol_map = {}  # {token: (symbol, exchange)}
        self._reconnect_attempts = 0
        self._max_reconnect_attempts = 5
        self._reconnect_delay = 2  # seconds, will use exponential backoff
        self._reconnect_lock = threading.Lock()  # Prevent concurrent reconnects
        self.connected = False

    def initialize(self, broker_name: str, user_id: str = None, auth_data: Optional[Dict[str, str]] = None) -> None:
        self.broker_name = broker_name
        # Flattrade: user_id and actid are the same, fetched from env
        self.user_id = os.getenv('BROKER_API_KEY', '').split(':::')[0]
        self.actid = self.user_id
        # susertoken from DB for OpenAlgo username (not broker user)
        self.logger.info(f"[DEBUG] Fetching susertoken for OpenAlgo username: {user_id}")
        self.susertoken = get_auth_token(user_id)
        self.logger.info(f"[Flattrade Adapter] user_id: {self.user_id}, actid: {self.actid}, susertoken: {self.susertoken}")
        if not self.actid or not self.susertoken:
            raise ValueError("Missing Flattrade actid or susertoken for user")
        self.ws_client = FlattradeWebSocket(
            user_id=self.user_id,
            actid=self.actid,
            susertoken=self.susertoken,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
            on_open=self._on_open
        )

    def connect(self) -> None:
        with self._reconnect_lock:
            if not self.ws_client:
                self.logger.error("WebSocket client not initialized. Call initialize() first.")
                raise RuntimeError("WebSocket client not initialized. Call initialize() first.")

            self.running = True  # Signal that we intend to be running
            try:
                self.connected = False
                connected = self.ws_client.connect()
                if not connected:
                    self.running = False  # Connection failed, so we are not running
                    self.logger.error("Failed to connect to Flattrade WebSocket server")
                    raise ConnectionError("Failed to connect to Flattrade WebSocket server")

                self.connected = True
                self._reconnect_attempts = 0  # Reset on successful manual connection
                self.logger.info("Connected to Flattrade WebSocket server")
            except Exception as e:
                self.running = False  # Connection failed, so we are not running
                self.connected = False
                self.logger.error(f"Exception during WebSocket connect: {e}")
                raise

    def disconnect(self) -> None:
        self.running = False
        with self._reconnect_lock:
            # Disconnect the WebSocket client. The server should handle unsubscriptions on a clean disconnect.
            if self.ws_client:
                try:
                    self.ws_client.stop()  # Use stop() for clean shutdown
                    self.logger.info("Flattrade WebSocket client stopped.")
                    self.ws_client = None # Ensure the client is garbage collected
                except Exception as e:
                    self.logger.error(f"Exception during WebSocket client stop: {e}")
                    self.ws_client = None # Also nullify in case of an error

            # Clean up ZeroMQ resources
            self.cleanup_zmq()

            # Reset adapter state to be ready for re-initialization
            self.connected = False
            self.user_id = None
            self.actid = None
            self.susertoken = None
            self.subscriptions = {}
            self.token_symbol_map = {}
            self._reconnect_attempts = 0

            self.logger.info("Flattrade adapter disconnected, reset, and cleaned up.")

    def __del__(self):
        """Destructor to ensure cleanup on object deletion."""
        if self.running:
            self.disconnect()

    def _build_scrip_key(self, subs):
        """
        Build the Flattrade subscription key string from a list of (symbol, exchange, mode) tuples.
        Returns a string like 'NSE|2885#BSE|500325' or 'NSE|2885' for single.
        """
        scrips = []
        for symbol, exchange, mode in subs:
            token_info = SymbolMapper.get_token_from_symbol(symbol, exchange)
            if not token_info:
                self.logger.error(f"[SCRIP_KEY] No token found for {symbol}-{exchange}")
                continue
            token = token_info['token']
            brexchange = token_info['brexchange']
            scrips.append(f"{FlattradeExchangeMapper.to_flattrade_exchange(brexchange)}|{token}")
        self.logger.info(f"[SCRIP_KEY] Built scrips: {scrips}")
        return '#'.join(scrips) if len(scrips) > 1 else (scrips[0] if scrips else '')

    def subscribe(self, symbol: str, exchange: str, mode: int = 2, depth_level: int = 5) -> Dict[str, Any]:
        key = (symbol, exchange, mode)
        try:
            self.logger.info(f"[SUBSCRIBE] Requested: symbol={symbol}, exchange={exchange}, mode={mode}, depth_level={depth_level}")
            with self.lock:
                self.subscriptions[key] = True
                active = [k for k, v in self.subscriptions.items() if v and k[2] == mode]
            scrip_key = self._build_scrip_key(active)
            self.logger.info(f"[SUBSCRIBE] Built scrip_key: {scrip_key} for active subscriptions: {active}")
            if not scrip_key:
                self.logger.error(f"No valid tokens for subscription: {symbol}-{exchange} mode {mode}")
                return self._create_error_response(404, f"No valid tokens for subscription.")
            # Track token to (symbol, exchange) mapping for canonical publishing
            from websocket_proxy.mapping import SymbolMapper
            for s, ex, m in active:
                token_info = SymbolMapper.get_token_from_symbol(s, ex)
                if token_info:
                    self.logger.info(f"[SUBSCRIBE] Mapping token {token_info['token']} to ({s}, {ex})")
                    self.token_symbol_map[token_info['token']] = (s, ex)
            if mode in [1, 2]:
                self.logger.info(f"[SUBSCRIBE] Calling ws_client.subscribe_touchline({scrip_key})")
                self.ws_client.subscribe_touchline(scrip_key)
            elif mode == 3:
                self.logger.info(f"[SUBSCRIBE] Calling ws_client.subscribe_depth({scrip_key})")
                self.ws_client.subscribe_depth(scrip_key)
            else:
                self.logger.error(f"Unsupported mode for subscribe: {mode}")
                return self._create_error_response(400, f"Unsupported mode: {mode}")
            self.logger.info(f"Subscribed {scrip_key} mode {mode}")
            return self._create_success_response(f"Subscribed {scrip_key} mode {mode}")
        except Exception as e:
            self.logger.error(f"Exception during subscribe: {e}")
            return self._create_error_response(500, f"Exception during subscribe: {e}")

    def unsubscribe(self, symbol: str, exchange: str, mode: int = 2) -> Dict[str, Any]:
        key = (symbol, exchange, mode)
        try:
            with self.lock:
                if key in self.subscriptions:
                    self.subscriptions[key] = False
                active = [k for k, v in self.subscriptions.items() if v and k[2] == mode]
            scrip_key = self._build_scrip_key(active)
            unsub_key = self._build_scrip_key([key])
            if not unsub_key:
                self.logger.error(f"No valid tokens for unsubscription: {symbol}-{exchange} mode {mode}")
                return self._create_error_response(404, f"No valid tokens for unsubscription.")
            if mode in [1, 2]:
                self.ws_client.unsubscribe_touchline(unsub_key)
                if scrip_key:
                    self.ws_client.subscribe_touchline(scrip_key)
            elif mode == 3:
                self.ws_client.unsubscribe_depth(unsub_key)
                if scrip_key:
                    self.ws_client.subscribe_depth(scrip_key)
            else:
                self.logger.error(f"Unsupported mode for unsubscribe: {mode}")
                return self._create_error_response(400, f"Unsupported mode: {mode}")
            self.logger.info(f"Unsubscribed {unsub_key} mode {mode}")
            return self._create_success_response(f"Unsubscribed {unsub_key} mode {mode}")
        except Exception as e:
            self.logger.error(f"Exception during unsubscribe: {e}")
            return self._create_error_response(500, f"Exception during unsubscribe: {e}")

    def unsubscribe_all(self) -> None:
        """Unsubscribes from all active subscriptions without disconnecting."""
        self.logger.info("Unsubscribing from all active Flattrade subscriptions.")
        with self.lock:
            if not self.subscriptions:
                self.logger.info("No active subscriptions to unsubscribe from.")
                return

            touchline_subs = [k for k, v in self.subscriptions.items() if v and k[2] in [1, 2]]
            depth_subs = [k for k, v in self.subscriptions.items() if v and k[2] == 3]

            if touchline_subs:
                scrip_key = self._build_scrip_key(touchline_subs)
                if scrip_key:
                    self.logger.info(f"[UNSUBSCRIBE_ALL] Unsubscribing touchline for: {scrip_key}")
                    self.ws_client.unsubscribe_touchline(scrip_key)

            if depth_subs:
                scrip_key = self._build_scrip_key(depth_subs)
                if scrip_key:
                    self.logger.info(f"[UNSUBSCRIBE_ALL] Unsubscribing depth for: {scrip_key}")
                    self.ws_client.unsubscribe_depth(scrip_key)

            # Clear all subscriptions state
            self.subscriptions.clear()
            self.token_symbol_map.clear()
            self.logger.info("All Flattrade subscriptions have been cleared.")

    def _resubscribe_all(self):
        """Resubscribe to all active subscriptions after reconnect."""
        with self.lock:
            for (symbol, exchange, mode), active in self.subscriptions.items():
                if not active:
                    continue
                token_info = SymbolMapper.get_token_from_symbol(symbol, exchange)
                if not token_info:
                    self.logger.warning(f"Cannot resubscribe: token not found for {symbol}-{exchange}")
                    continue
                token = token_info['token']
                brexchange = token_info['brexchange']
                scrip = f"{FlattradeExchangeMapper.to_flattrade_exchange(brexchange)}|{token}"
                if mode in [1, 2]:
                    self.ws_client.subscribe_touchline(scrip)
                elif mode == 3:
                    self.ws_client.subscribe_depth(scrip)
                else:
                    self.logger.warning(f"Unsupported mode {mode} for {symbol}-{exchange}")

    def _reconnect(self):
        with self._reconnect_lock:
            if not self.running:
                self.logger.info("Not running, skipping reconnect.")
                return

            if self._reconnect_attempts >= self._max_reconnect_attempts:
                self.logger.error(f"Max reconnect attempts ({self._max_reconnect_attempts}) reached. Giving up.")
                self.running = False  # Stop trying
                return

            self._reconnect_attempts += 1
            delay = self._reconnect_delay * (2 ** (self._reconnect_attempts - 1))
            self.logger.warning(f"Attempting to reconnect in {delay} seconds (attempt {self._reconnect_attempts})...")
            time.sleep(delay)

            try:
                # Re-create the client for a clean slate, as the old one might be in a bad state
                self.logger.info("Re-creating WebSocket client for reconnect.")
                self.ws_client = FlattradeWebSocket(
                    user_id=self.user_id,
                    actid=self.actid,
                    susertoken=self.susertoken,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                    on_open=self._on_open
                )

                # The connect method is now robust enough to be called here
                connected = self.ws_client.connect()
                if connected:
                    self.connected = True
                    self.logger.info("Reconnected successfully. Resubscribing...")
                    # self._resubscribe_all() is called by _on_open
                    self._reconnect_attempts = 0  # Reset after successful reconnect
                else:
                    self.connected = False
                    self.logger.error("Reconnect failed. _on_close will trigger another attempt if running.")

            except Exception as e:
                self.connected = False
                self.logger.error(f"Exception during reconnect: {e}. _on_close will trigger another attempt if running.")

    def _on_open(self, ws):
        self.logger.info("Flattrade WebSocket connection opened.")
        try:
            self._resubscribe_all()
        except Exception as e:
            self.logger.error(f"Exception during resubscribe on open: {e}")

    def _on_close(self, ws, close_status_code, close_msg):
        self.logger.warning(f"Adapter notified of WebSocket close: Code={close_status_code}, Msg='{close_msg}'")
        self.connected = False
        if self.running:
            self.logger.info("Adapter is in 'running' state, attempting to reconnect.")
            self._reconnect()
        else:
            self.logger.info("Adapter is not in 'running' state, will not reconnect.")

    def _on_error(self, ws, error):
        self.logger.error(f"Flattrade WebSocket error: {error}")
        if self.running:
            self._reconnect()

    def _build_scrip_key(self, subs):
        """
        Build the Flattrade subscription key string from a list of (symbol, exchange, mode) tuples.
        Returns a string like 'NSE|2885#BSE|500325' or 'NSE|2885' for single.
        """
        scrips = []
        for symbol, exchange, mode in subs:
            token_info = SymbolMapper.get_token_from_symbol(symbol, exchange)
            if not token_info:
                self.logger.error(f"[SCRIP_KEY] No token found for {symbol}-{exchange}")
                continue
            token = token_info['token']
            brexchange = token_info['brexchange']
            scrips.append(f"{FlattradeExchangeMapper.to_flattrade_exchange(brexchange)}|{token}")
        self.logger.info(f"[SCRIP_KEY] Built scrips: {scrips}")
        return '#'.join(scrips) if len(scrips) > 1 else (scrips[0] if scrips else '')

    def _generate_topic(self, exchange: str, symbol: str, mode_str: str) -> str:
        # Publish as {exchange}_{symbol}_{mode_str} to match OpenAlgo proxy expectation
        return f"{exchange}_{symbol}_{mode_str}"

    def _normalize_market_data(self, data, t, mode=None) -> Dict[str, Any]:
        import time
        # Always include both 'ltp' and 'last_price' for LTP mode for client compatibility
        last_price = float(data.get('lp', 0) or 0)
        # Use local system timestamp in ms if not present
        timestamp = data.get('ltt') or data.get('ft')
        if not timestamp:
            timestamp = int(time.time() * 1000)
        result = {
            'symbol': data.get('ts', ''),
            'exchange': data.get('e', ''),
            'token': data.get('tk', ''),
            'last_price': last_price,
            'ltp': last_price,  # Always include 'ltp' for client compatibility
            'volume': int(data.get('v', 0) or 0),
            'open': float(data.get('o', 0) or 0),
            'high': float(data.get('h', 0) or 0),
            'low': float(data.get('l', 0) or 0),
            'close': float(data.get('c', 0) or 0),
            'average_price': float(data.get('ap', 0) or 0),
            'percent_change': float(data.get('pc', 0) or 0),
            'mode': 'LTP' if t in ('tf', 'tk') and (mode == 1 or mode is None) else ('QUOTE' if t in ('tf', 'tk') and mode == 2 else 'DEPTH'),
            'timestamp': timestamp,
        }
        # For quote mode (mode 2), add bid/ask fields (touchline)
        if (t in ('tf', 'tk') and mode == 2):
            # Touchline/quote: best bid/ask and their quantities
            result['best_bid_price'] = float(data.get('bp1', 0) or 0)
            result['best_bid_qty'] = int(data.get('bq1', 0) or 0)
            result['best_ask_price'] = float(data.get('sp1', 0) or 0)
            result['best_ask_qty'] = int(data.get('sq1', 0) or 0)
            # Optionally add more levels if available
        if t in ('df', 'dk'):
            # Patch: publish depth as {'depth': {'buy': [...], 'sell': [...]}}
            result['depth'] = {
                'buy': [
                    {'price': float(data.get(f'bp{i}', 0) or 0), 'quantity': int(data.get(f'bq{i}', 0) or 0), 'orders': int(data.get(f'bo{i}', 0) or 0)}
                    for i in range(1, 6)
                ],
                'sell': [
                    {'price': float(data.get(f'sp{i}', 0) or 0), 'quantity': int(data.get(f'sq{i}', 0) or 0), 'orders': int(data.get(f'so{i}', 0) or 0)}
                    for i in range(1, 6)
                ]
            }
        return result

    def _on_message(self, ws, message):
        try:
            self.logger.debug(f"[ON_MESSAGE] Raw message: {message}")
            data = json.loads(message)
            t = data.get('t')

            if t == 'ck':
                self.logger.info(f"Adapter received auth ack: {data}")
                return  # Handled by the client, no further processing needed here

            self.logger.debug(f"[ON_MESSAGE] Message type: {t}, data: {data}")
            # Determine mode from active subscriptions (default to 1 if not found)
            token = data.get('tk')
            mode = None
            for (sym, exch, m), active in self.subscriptions.items():
                token_info = SymbolMapper.get_token_from_symbol(sym, exch)
                if token_info and token_info['token'] == token and active:
                    mode = m
                    break
            if t in ('tf', 'tk', 'df', 'dk'):
                # For LTP mode, only process if 'lp' field is present to avoid 0.0 values
                if mode in [1, None] and 'lp' not in data:
                    self.logger.warning(f"Skipping LTP update for token {data.get('tk')} because 'lp' field is missing: {data}")
                    return

                self.logger.debug(f"[ON_MESSAGE] Incoming data for {t}: {data}")
                normalized = self._normalize_market_data(data, t, mode)
                self.logger.debug(f"[ON_MESSAGE] Normalized data: {normalized}")
                token = normalized.get('token')
                symbol, exchange = self.token_symbol_map.get(token, (normalized.get('symbol'), normalized.get('exchange')))
                self.logger.debug(f"[ON_MESSAGE] Using canonical symbol/exchange for publish: {symbol}, {exchange} (token: {token})")
                # Determine topic type
                if t in ('tf', 'tk') and mode == 2:
                    mode_str = 'QUOTE'
                elif t in ('tf', 'tk'):
                    mode_str = 'LTP'
                else:
                    mode_str = 'DEPTH'
                topic = self._generate_topic(exchange, symbol, mode_str)
                self.logger.debug(f"[ON_MESSAGE] Publishing topic: {topic} with symbol: {symbol}, exchange: {exchange}")
                normalized['symbol'] = symbol
                normalized['exchange'] = exchange
                # --- ADDED DEBUG: Log if this is a DEPTH message ---
                if mode_str == 'DEPTH':
                    self.logger.info(f"[DEPTH DEBUG] Publishing DEPTH data for {symbol} {exchange}: {normalized}")
                self.publish_market_data(topic, normalized)
            else:
                self.logger.warning(f"Received unknown message type: {t} | message: {data}")
        except json.JSONDecodeError:
            self.logger.error(f"Failed to decode JSON from message: {message}")
        except Exception:
            self.logger.exception(f"Error processing message: {message}")

    def publish_market_data(self, topic, data):
        self.logger.info(f"[ZMQ PUBLISH] Topic: {topic} | Data: {data}")
        # Extra debug for ZMQ publish
        self.logger.debug(f"[DEBUG] ZMQ publish call for topic: {topic}, data keys: {list(data.keys())}")
        super().publish_market_data(topic, data)
