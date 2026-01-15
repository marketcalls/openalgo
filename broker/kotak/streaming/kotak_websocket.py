"""
Isolated, multi-client-safe WebSocket client for Kotak broker, using HSWebSocketLib.
Inspired by AliceBlue architecture, with per-instance state and thread safety.
Enhanced with partial update handling like AliceBlue's tick feed processing.
"""
import json
import threading
import time
from .HSWebSocketLib import HSWebSocket
from utils.logging import get_logger


logger = get_logger(__name__)


class KotakWebSocket:
    def __init__(self, auth_config, ws_url="wss://mlhsm.kotaksecurities.com"):
        """
        Each instance is isolated: no shared state.
        auth_config: dict with keys 'auth_token', 'sid', 'hs_server_id', 'access_token'
        """
        self.auth_config = auth_config.copy()
        self.ws_url = ws_url
        self.ws = HSWebSocket()
        self._lock = threading.RLock()
        self._subscriptions = set()  # (exchange, token, type)
        self._is_connected = False
        self._is_authenticated = False
        self._should_run = True
        self._thread = None
        self._on_quote = None
        self._on_depth = None
        self._on_index = None
        self._on_error = None
        self._on_open = None
        self._on_close = None
        self._last_quote = {}
        self._last_depth = {}
        self._last_index = {}
        self._pending_msgs = []  # queue for messages before connection
        
        # **CRITICAL FIX**: Add state storage like AliceBlue for partial updates
        self._symbol_state = {}  # Store last known complete state for each symbol


    def set_callbacks(self, on_quote=None, on_depth=None, on_index=None, on_error=None, on_open=None, on_close=None):
        self._on_quote = on_quote
        self._on_depth = on_depth
        self._on_index = on_index
        self._on_error = on_error
        self._on_open = on_open
        self._on_close = on_close


    def connect(self):
        """Start the websocket connection in a new thread."""
        def _run():
            try:
                self.ws.open_connection(
                    url=self.ws_url,
                    token=self.auth_config['auth_token'],
                    sid=self.auth_config['sid'],
                    on_open=self._handle_open,
                    on_message=self._handle_message,
                    on_error=self._handle_error,
                    on_close=self._handle_close
                )
            except Exception as e:
                logger.error(f"KotakWebSocket connection error: {e}")
                if self._on_error:
                    self._on_error(e)
        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()


    def close(self):
        self._should_run = False
        self.ws.close()
        if self._on_close:
            self._on_close()


    def subscribe(self, exchange, token, sub_type="mws", channelnum="1"):
        """Subscribe to a symbol (quote, depth, or index). sub_type: mws, dps, ifs, etc."""
        with self._lock:
            self._subscriptions.add((exchange, token, sub_type))
        msg = {
            "type": sub_type,
            "scrips": f"{exchange}|{token}",
            "channelnum": channelnum
        }
        self._send(msg)


    def unsubscribe(self, exchange, token, sub_type="mwu", channelnum="1"):
        """Unsubscribe from a symbol."""
        with self._lock:
            self._subscriptions.discard((exchange, token, sub_type))
        msg = {
            "type": sub_type,
            "scrips": f"{exchange}|{token}",
            "channelnum": channelnum
        }
        self._send(msg)


    def _send(self, msg):
        with self._lock:
            if not self._is_connected or self.ws is None:
                logger.debug(f"[KOTAK WSS QUEUE] Queuing message until connection open: {msg}")
                self._pending_msgs.append(msg)
                return
        try:
            logger.debug(f"[KOTAK WSS SEND] {msg}")
            self.ws.hs_send(json.dumps(msg))
            logger.debug(f"Sent message: {msg}")
        except Exception as e:
            logger.error(f"Error sending message: {e}")
            if self._on_error:
                self._on_error(e)


    def _handle_open(self):
        logger.debug("KotakWebSocket connection opened")
        logger.debug("[KOTAK WSS EVENT] Connection opened")
        self._is_connected = True
        self._is_authenticated = False
        # Send explicit connection request before any subscriptions
        try:
            cn_msg = {
                "type": "cn",
                "Authorization": self.auth_config.get("auth_token"),
                "Sid": self.auth_config.get("sid")
            }
            logger.debug(f"[KOTAK WSS SEND] Sending explicit connection request: {cn_msg}")
            self.ws.hs_send(json.dumps(cn_msg))
        except Exception as e:
            logger.error(f"Error sending explicit connection request: {e}")
            if self._on_error:
                self._on_error(e)
        # Do NOT flush pending messages here; wait for cn ack
        if self._on_open:
            self._on_open()


    def _flush_pending_subscriptions(self):
        with self._lock:
            while self._pending_msgs:
                msg = self._pending_msgs.pop(0)
                try:
                    logger.debug(f"[KOTAK WSS SEND/FLUSH] {msg}")
                    self.ws.hs_send(json.dumps(msg))
                except Exception as e:
                    logger.error(f"Error sending pending message: {e}")
                    if self._on_error:
                        self._on_error(e)


    def _handle_close(self):
        logger.debug("KotakWebSocket connection closed")
        logger.debug("[KOTAK WSS EVENT] Connection closed")
        self._is_connected = False
        if self._on_close:
            self._on_close()


    def _handle_error(self, error):
        logger.error(f"KotakWebSocket error: {error}")
        logger.error(f"[KOTAK WSS EVENT] Error: {error}")
        if self._on_error:
            self._on_error(error)


    def _handle_message(self, message):
        logger.debug(f"[KOTAK WSS RECV] {message}")
        try:
            data = json.loads(message) if isinstance(message, str) else message
            if not data:
                return

            # **CRITICAL FIX**: Process each item in list separately
            if isinstance(data, list):
                for item in data:
                    self._process_single_message(item)
            else:
                self._process_single_message(data)
                
        except Exception as e:
            logger.error(f"Error handling message: {e}")
            if self._on_error:
                self._on_error(e)

    def _process_single_message(self, msg):
        """Process a single message item."""
        # Handle connection ack
        if msg.get("type") == "cn" and msg.get("stat") == "Ok":
            logger.debug("[KOTAK WSS HANDSHAKE] Connection acknowledged by broker. Flushing pending subscriptions.")
            self._is_authenticated = True
            self._flush_pending_subscriptions()
            return

        # **CRITICAL FIX**: Create symbol key for state management
        token = msg.get('tk', '')
        exchange = msg.get('e', '')
        symbol_key = f"{exchange}|{token}"

        # Identify type and process
        name = msg.get("name", "")
        if name == "dp":
            # Depth data
            depth = self._parse_depth_with_state(msg, symbol_key)
            self._last_depth = depth
            if self._on_depth:
                self._on_depth(depth)
        elif name == "if":
            # Index data
            index = self._parse_index(msg)
            self._last_index = index
            if self._on_index:
                self._on_index(index)
        elif "ltp" in msg or any(field in msg for field in ['bp', 'sp', 'op', 'h', 'lo', 'c', 'v']):
            # Quote data - handle with state merging
            quote = self._parse_quote_with_state(msg, symbol_key)
            self._last_quote = quote
            if self._on_quote:
                self._on_quote(quote)

    def _is_partial_update(self, msg):
        """
        Determine if this is a partial update based on missing expected fields.
        FIXED to be less aggressive and preserve complete initial data.
        """
        # If we have LTP and symbol name, check if we have OHLC data
        ltp = msg.get('ltp', 0)
        symbol_name = msg.get('ts', '')
        
        # Check for presence of OHLC fields
        has_open = 'op' in msg and msg.get('op', 0) != 0
        has_high = 'h' in msg and msg.get('h', 0) != 0  
        has_low = 'lo' in msg and msg.get('lo', 0) != 0
        has_close = 'c' in msg and msg.get('c', 0) != 0
        
        # If we have LTP, symbol name, and at least some OHLC data, treat as complete
        if ltp and symbol_name and (has_open or has_high or has_low or has_close):
            return False  # Complete enough to process
        
        # If we only have LTP and no symbol name or OHLC, it's partial
        if ltp and not symbol_name and not (has_open or has_high or has_low or has_close):
            return True
            
        return False  # Default to treating as complete



    def _parse_quote_with_state(self, msg, symbol_key):
        """
        Parse quote data with AliceBlue-style state merging for partial updates.
        """
        with self._lock:
            # Check if this is a partial update
            is_partial = self._is_partial_update(msg)
            
            if is_partial and symbol_key in self._symbol_state:
                # This is a partial update - merge with stored state like AliceBlue
                logger.debug(f"Partial quote update detected for {symbol_key}")
                
                # Start with the last known complete state
                merged_data = self._symbol_state[symbol_key].copy()
                
                # Update only the fields present in the partial update
                for key, value in msg.items():
                    # Skip zero values that indicate "no update" for price fields
                    if key in ['op', 'h', 'lo', 'c', 'bp', 'sp'] and value == 0.0:
                        continue
                    elif key == 'v' and value == 0.0:  # volume
                        continue
                    elif key == 'ts' and not value:  # symbol name
                        continue
                    else:
                        merged_data[key] = value
                
                # Use merged data for parsing
                msg = merged_data
                logger.debug(f"Merged quote data for {symbol_key}")
            
            # Parse the complete data (either original or merged)
            quote = {
                'bid': float(msg.get('bp', 0)),
                'ask': float(msg.get('sp', 0)),
                'open': float(msg.get('op', 0)),
                'high': float(msg.get('h', 0)),
                'low': float(msg.get('lo', 0)),
                'ltp': float(msg.get('ltp', 0)),
                'prev_close': float(msg.get('c', 0)),
                'volume': float(msg.get('v', 0)),
                'ts': msg.get('ts', ''),
                'tk': msg.get('tk', ''),
                'e': msg.get('e', '')
            }
            
            # Store the complete state for future partial updates
            self._symbol_state[symbol_key] = msg.copy()
            
            return quote


    def _parse_depth_with_state(self, msg, symbol_key):
        """
        Parse depth data with AliceBlue-style state merging for partial updates.
        FIXED to use actual order counts from Kotak data.
        """
        with self._lock:
            # Check if this is a partial depth update
            has_price_data = any(key in msg for key in ['bp', 'bp1', 'bp2', 'bp3', 'bp4', 'sp', 'sp1', 'sp2', 'sp3', 'sp4'])
            
            if not has_price_data and symbol_key in self._symbol_state:
                # This is a partial update with only quantities - merge with stored state
                logger.debug(f"Partial depth update detected for {symbol_key}")
                
                stored_data = self._symbol_state[symbol_key].copy()
                
                # Merge quantity updates with stored price data
                for key, value in msg.items():
                    if key in ['bq', 'bq1', 'bq2', 'bq3', 'bq4', 'bs', 'bs1', 'bs2', 'bs3', 'bs4',
                            'bno1', 'bno2', 'bno3', 'bno4', 'bno5',  # CRITICAL: Include bid order counts
                            'sno1', 'sno2', 'sno3', 'sno4', 'sno5']: # CRITICAL: Include ask order counts
                        stored_data[key] = value
                    elif key not in ['tk', 'e'] and value:  # Update other non-zero fields
                        stored_data[key] = value
                
                # Use merged data for parsing
                msg = stored_data
                logger.debug(f"Merged depth data for {symbol_key}")
            
            # Parse depth data with CORRECT order counts
            bids = []
            asks = []
            for i in range(5):
                price_key = f'bp{i}' if i > 0 else 'bp'
                qty_key = f'bq{i}' if i > 0 else 'bq'
                ask_price_key = f'sp{i}' if i > 0 else 'sp'
                ask_qty_key = f'bs{i}' if i > 0 else 'bs'
                
                # **CRITICAL FIX**: Use correct order count fields
                bid_orders_key = f'bno{i+1}'  # bno1, bno2, bno3, bno4, bno5
                ask_orders_key = f'sno{i+1}'  # sno1, sno2, sno3, sno4, sno5
                
                # Bids
                price = float(msg.get(price_key, 0))
                quantity = int(msg.get(qty_key, 0))
                bid_orders = int(msg.get(bid_orders_key, 0))  # Use actual bid order count
                
                if price > 0 and price != 21474836.48 and quantity >= 0:
                    bids.append({
                        'price': price, 
                        'quantity': quantity, 
                        'orders': bid_orders  # FIXED: Use actual order count
                    })
                
                # Asks
                price = float(msg.get(ask_price_key, 0))
                quantity = int(msg.get(ask_qty_key, 0))
                ask_orders = int(msg.get(ask_orders_key, 0))  # Use actual ask order count
                
                if price > 0 and price != 21474836.48 and quantity >= 0:
                    asks.append({
                        'price': price, 
                        'quantity': quantity, 
                        'orders': ask_orders  # FIXED: Use actual order count
                    })
            
            # Ensure we always have 5 levels
            while len(bids) < 5:
                bids.append({'price': 0, 'quantity': 0, 'orders': 0})
            while len(asks) < 5:
                asks.append({'price': 0, 'quantity': 0, 'orders': 0})
            
            depth = {
                'bids': bids[:5],
                'asks': asks[:5],
                'totalbuyqty': sum(b['quantity'] for b in bids),
                'totalsellqty': sum(a['quantity'] for a in asks),
                'ltp': float(msg.get('ltp', 0)),
                'ltq': int(msg.get('ltq', 0)),
                'volume': float(msg.get('v', 0)),
                'open': float(msg.get('op', 0)),
                'high': float(msg.get('h', 0)),
                'low': float(msg.get('lo', 0)),
                'prev_close': float(msg.get('c', 0)),
                'oi': int(msg.get('oi', 0)),
                'ts': msg.get('ts', ''),
                'tk': msg.get('tk', ''),
                'e': msg.get('e', '')
            }
            
            # Store the complete state for future partial updates
            self._symbol_state[symbol_key] = msg.copy()
            
            return depth

    def _parse_quote(self, msg):
        """Legacy method - maintained for backward compatibility."""
        return self._parse_quote_with_state(msg, f"{msg.get('e', '')}|{msg.get('tk', '')}")


    def _parse_depth(self, msg):
        """Legacy method - maintained for backward compatibility."""
        return self._parse_depth_with_state(msg, f"{msg.get('e', '')}|{msg.get('tk', '')}")


    def _parse_index(self, msg):
        # See index_key_mapping for all fields
        return {
            'ltp': float(msg.get('iv', 0)),
            'prev_close': float(msg.get('ic', 0)),
            'timestamp': msg.get('tvalue', ''),
            'high': float(msg.get('highPrice', 0)),
            'low': float(msg.get('lowPrice', 0)),
            'open': float(msg.get('openingPrice', 0)),
            'mul': float(msg.get('mul', 0)),
            'prec': int(msg.get('prec', 0)),
            'cng': float(msg.get('cng', 0)),
            'nc': float(msg.get('nc', 0)),
            'tk': msg.get('tk', ''),
            'e': msg.get('e', '')
        }


    def get_last_quote(self):
        return self._last_quote.copy()


    def get_last_depth(self):
        return self._last_depth.copy()


    def get_last_index(self):
        return self._last_index.copy()


    def is_connected(self):
        return self._is_connected


    def wait_until_closed(self, timeout=None):
        if self._thread:
            self._thread.join(timeout)
