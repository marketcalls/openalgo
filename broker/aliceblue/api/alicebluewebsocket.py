import websocket
import json
import threading
import time
import hashlib
import ssl
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any, Union
from utils.logging import get_logger

logger = get_logger(__name__)

class AliceBlueWebSocket:
    """
    WebSocket client for AliceBlue broker's market data API.
    Handles connection to the WebSocket server, authentication, subscription,
    and message parsing for market data.
    """
    
    # WebSocket endpoints
    PRIMARY_URL = "wss://ws1.aliceblueonline.com/NorenWS/"
    ALTERNATE_URL = "wss://ws2.aliceblueonline.com/NorenWS/"
    
    # Maximum reconnection attempts
    MAX_RECONNECT_ATTEMPTS = 5
    
    def __init__(self, user_id: str, session_id: str):
        """
        Initialize the AliceBlue WebSocket client.
        
        Args:
            user_id (str): AliceBlue user ID
            session_id (str): Session ID obtained from authentication
        """
        self.user_id = user_id
        self.session_id = session_id
        self.ws = None
        self.is_connected = False
        self.reconnect_count = 0
        self.lock = threading.Lock()
        self.last_message_time = datetime.now()
        self.subscribed_tokens = set()
        self.subscriptions = {}  # Dictionary to track subscribed instruments: exchange|token -> instrument object
        self.last_quotes = {}   # Dictionary to store quote data: exchange:token -> quote data
        self.last_depth = {}    # Dictionary to store depth data: exchange:token -> depth data
        self._connect_thread = None
        self._stop_event = threading.Event()
        
        # Generate the encrypted token as required by AliceBlue
        sha256_encryption1 = hashlib.sha256(session_id.encode('utf-8')).hexdigest()
        self.enc_token = hashlib.sha256(sha256_encryption1.encode('utf-8')).hexdigest()
    
    def connect(self):
        """
        Establishes the WebSocket connection and starts the connection thread.
        """
        if self._connect_thread and self._connect_thread.is_alive():
            logger.info("WebSocket connection thread is already running")
            return
        
        # Reset the stop event
        self._stop_event.clear()
        
        # Start the connection in a separate thread
        self._connect_thread = threading.Thread(target=self._connect_with_retry)
        self._connect_thread.daemon = True
        self._connect_thread.start()
    
    def _connect_with_retry(self):
        """
        Attempts to connect to the WebSocket with exponential backoff retry logic.
        """
        urls = [self.PRIMARY_URL, self.ALTERNATE_URL]
        attempt = 0
        
        while not self._stop_event.is_set() and attempt < self.MAX_RECONNECT_ATTEMPTS:
            # Try each URL in sequence
            for url in urls:
                if self._stop_event.is_set():
                    break
                
                try:
                    logger.info(f"Connecting to AliceBlue WebSocket: {url}")
                    websocket.enableTrace(False)
                    self.ws = websocket.WebSocketApp(
                        url,
                        on_open=self.on_open,
                        on_message=self.on_message,
                        on_error=self.on_error,
                        on_close=self.on_close
                    )
                    
                    # Reset reconnect count on successful connection attempt
                    self.reconnect_count = 0
                    
                    # Run the WebSocket connection with proper SSL context
                    self.ws.run_forever(sslopt={"cert_reqs": ssl.CERT_NONE})
                    
                    # If we're here, the connection was closed
                    if self.is_connected:
                        # If it was a clean disconnect, break the retry loop
                        break
                
                except Exception as e:
                    logger.error(f"Error connecting to {url}: {str(e)}")
            
            # If we should stop or connection was successful, break the retry loop
            if self._stop_event.is_set() or self.is_connected:
                break
            
            # Exponential backoff for reconnection attempts
            attempt += 1
            sleep_time = min(2 ** attempt, 30)  # Max 30 seconds between retries
            logger.info(f"Reconnection attempt {attempt}/{self.MAX_RECONNECT_ATTEMPTS} failed. Retrying in {sleep_time}s")
            time.sleep(sleep_time)
        
        if attempt >= self.MAX_RECONNECT_ATTEMPTS and not self.is_connected:
            logger.error("Maximum reconnection attempts reached. Could not connect to AliceBlue WebSocket.")
    
    def disconnect(self):
        """
        Disconnects from the WebSocket and stops the connection thread.
        """
        self._stop_event.set()
        
        if self.ws:
            logger.info("Closing AliceBlue WebSocket connection")
            self.ws.close()
        
        self.is_connected = False
        logger.info("AliceBlue WebSocket disconnected")
    
    def on_open(self, ws):
        """
        Called when the WebSocket connection is established.
        Sends authentication message to initialize the session.
        
        Args:
            ws: WebSocket instance
        """
        logger.info("AliceBlue WebSocket connection opened")
        
        # This is the format required by AliceBlue for authentication
        auth_message = {
            "susertoken": self.enc_token,
            "t": "c",
            "actid": f"{self.user_id}_API",
            "uid": f"{self.user_id}_API",
            "source": "API"
        }
        
        try:
            # Send authentication message
            ws.send(json.dumps(auth_message))
            logger.info("AliceBlue WebSocket authentication message sent")
        except Exception as e:
            logger.error(f"Error sending authentication message: {str(e)}")
    
    def on_message(self, ws, message):
        """
        Called when a message is received from the WebSocket.
        Parses the message and updates the last quotes and depth data.
        
        Args:
            ws: WebSocket instance
            message: Message received from the WebSocket
        """
        try:
            self.last_message_time = datetime.now()
            # Log raw message for debugging
            logger.debug(f"Received raw WebSocket message: {message[:100]}" + ("..." if len(message) > 100 else ""))
            
            data = json.loads(message)
            logger.debug(f"Parsed WebSocket message: {json.dumps(data, indent=2)}")
            
            # Debug log for OI values if present
            if 'oi' in data:
                logger.info(f"Raw OI data from AliceBlue: oi='{data.get('oi')}' (type: {type(data.get('oi'))}) for token {data.get('tk', 'unknown')}")
            
            # Authentication response
            if 's' in data and data['s'] == 'OK':
                with self.lock:
                    self.is_connected = True
                logger.info("AliceBlue WebSocket authenticated successfully")
                
                # Resubscribe to any tokens that were subscribed before
                if self.subscribed_tokens:
                    logger.info(f"Resubscribing to {len(self.subscribed_tokens)} tokens after authentication")
                    self._resubscribe()
                
            # Connection feedback message
            elif 't' in data and data.get('t') == 'cf':
                status = data.get('k', 'unknown')
                logger.info(f"AliceBlue WebSocket connection feedback: {status}")
                
                if status == 'OK':
                    with self.lock:
                        self.is_connected = True
                    logger.info("AliceBlue WebSocket connection confirmed")
                else:
                    logger.error(f"AliceBlue WebSocket connection failed with status: {status}")
                
            # Market data acknowledgment (tick data acknowledgment)
            elif 't' in data and data.get('t') == 'tk':
                logger.info(f"Received tick acknowledgment for {data.get('e', 'unknown')}:{data.get('tk', 'unknown')}")
                self._process_tick_data(data)
                
            # Market data feed (tick data feed)
            elif 't' in data and data.get('t') == 'tf':
                logger.debug(f"Received tick feed for {data.get('e', 'unknown')}:{data.get('tk', 'unknown')}")
                # Process as tick data
                self._process_tick_data(data)
                
            # Market depth acknowledgment
            elif 't' in data and data.get('t') == 'dk':
                logger.info(f"Received depth acknowledgment for {data.get('e', 'unknown')}:{data.get('tk', 'unknown')}")
                self._process_depth_data(data)
                
            # Market depth feed
            elif 't' in data and data.get('t') == 'df':
                logger.debug(f"Received depth feed for {data.get('e', 'unknown')}:{data.get('tk', 'unknown')}")
                # Process as depth data
                self._process_depth_data(data)
        
        except json.JSONDecodeError:
            logger.warning(f"Received non-JSON message: {message[:100]}...")
        except Exception as e:
            logger.error(f"Error processing WebSocket message: {str(e)}")
    
    def _process_tick_data(self, data):
        """
        Process tick data message from WebSocket.
        
        Args:
            data (dict): Tick data from WebSocket
        """
        try:
            # Extract token and exchange
            token = data.get('tk', '')
            exchange = data.get('e', '')
            
            # Look up the original subscription to get the correct symbol
            subscription_key = f"{exchange}|{token}"
            original_instrument = None
            with self.lock:
                original_instrument = self.subscriptions.get(subscription_key)
            
            # Use subscription symbol if available, otherwise use broker symbol from data
            if original_instrument and hasattr(original_instrument, 'symbol'):
                symbol = original_instrument.symbol
                logger.info(f"✓ Using subscription symbol: {symbol} for {subscription_key}")
            else:
                # Fallback to broker symbol from AliceBlue data
                symbol = data.get('ts', f"TOKEN_{token}")
                logger.warning(f"✗ Using broker symbol: {symbol} for {subscription_key} (subscription not found)")
                logger.warning(f"Available subscriptions: {list(self.subscriptions.keys())}")
            
            # Use consistent key format for data storage: exchange:token
            key = f"{exchange}:{token}"
            
            # Message type can be 'tk' (acknowledgment) or 'tf' (feed)
            message_type = data.get('t', 'unknown')
            
            # For 'tk' message, we get full data. For 'tf', we get updates, which we need to merge with existing data
            if message_type == 'tk':
                # Format the data in a standardized structure for full acknowledgment data
                quote = {
                    'exchange': exchange,
                    'token': token,
                    'ltp': float(data.get('lp', 0)),
                    'open': float(data.get('o', 0)),
                    'high': float(data.get('h', 0)),
                    'low': float(data.get('l', 0)),
                    'close': float(data.get('c', 0)),
                    'volume': int(data.get('v', 0)),
                    'last_trade_time': data.get('ft', ''),
                    'last_trade_quantity': int(data.get('ltq', 0)),
                    'average_trade_price': float(data.get('ap', 0)),
                    'open_interest': int(float(data.get('oi', 0))) if data.get('oi') else 0,
                    'prev_open_interest': int(float(data.get('poi', 0))) if data.get('poi') else 0,
                    'total_buy_quantity': int(data.get('tbq', 0)),
                    'total_sell_quantity': int(data.get('tsq', 0)),
                    'symbol': symbol,  # Use OpenAlgo symbol from subscription
                    'broker_symbol': data.get('ts', ''),  # Keep broker symbol for reference
                    'timestamp': datetime.now().isoformat()
                }
                
                logger.debug(f"Processed full tick data for {exchange}:{token} - LTP: {quote['ltp']}")
                
            elif message_type == 'tf':
                # For feed updates, update only the fields that are present in the message
                with self.lock:
                    # Get existing quote or create a new one
                    existing_quote = self.last_quotes.get(key, {})
                    
                    # Create updated quote by merging existing data with new data
                    quote = existing_quote.copy()
                    quote.update({
                        'exchange': exchange,
                        'token': token,
                        'timestamp': datetime.now().isoformat()
                    })
                    
                    # Update specific fields if they exist in the feed
                    if 'lp' in data: quote['ltp'] = float(data.get('lp', 0))
                    if 'pc' in data: quote['percent_change'] = float(data.get('pc', 0))
                    if 'v' in data: quote['volume'] = int(data.get('v', 0))
                    if 'ft' in data: quote['last_trade_time'] = data.get('ft', '')
                    if 'ltq' in data: quote['last_trade_quantity'] = int(data.get('ltq', 0))
                    if 'bp1' in data: quote['bid'] = float(data.get('bp1', 0))
                    if 'sp1' in data: quote['ask'] = float(data.get('sp1', 0))
                    if 'bq1' in data: quote['bid_qty'] = int(data.get('bq1', 0))
                    if 'sq1' in data: quote['ask_qty'] = int(data.get('sq1', 0))
                    if 'tbq' in data: quote['total_buy_quantity'] = int(data.get('tbq', 0))
                    if 'tsq' in data: quote['total_sell_quantity'] = int(data.get('tsq', 0))
                    if 'oi' in data: quote['open_interest'] = int(float(data.get('oi', 0))) if data.get('oi') else 0
                    if 'poi' in data: quote['prev_open_interest'] = int(float(data.get('poi', 0))) if data.get('poi') else 0
                    
                    logger.debug(f"Updated tick data for {exchange}:{token} - LTP: {quote.get('ltp', 'N/A')}")
            else:
                logger.warning(f"Unknown message type for tick data: {message_type}")
                return
            
            # Update the last quotes dictionary
            with self.lock:
                self.last_quotes[key] = quote
                
            logger.info(f"✓ Stored quote data for {key} with LTP {quote.get('ltp', 'N/A')}, Symbol: {quote.get('symbol', 'N/A')}, OI: {quote.get('open_interest', 'N/A')}")
            
            # Log the first time we get data for a token
            if message_type == 'tk':
                logger.info(f"Received first quote for {exchange}:{token} - LTP: {quote.get('ltp', 'N/A')}")
                
        except Exception as e:
            logger.error(f"Error processing tick data: {str(e)}")
    
    def _process_depth_data(self, data):
        """
        Process market depth data message from WebSocket.
        
        Args:
            data (dict): Market depth data from WebSocket
        """
        try:
            # Extract token and exchange
            token = data.get('tk', '')
            exchange = data.get('e', '')
            
            # Look up the original subscription to get the correct symbol
            subscription_key = f"{exchange}|{token}"
            original_instrument = None
            with self.lock:
                original_instrument = self.subscriptions.get(subscription_key)
            
            # Use subscription symbol if available, otherwise use broker symbol from data
            if original_instrument and hasattr(original_instrument, 'symbol'):
                symbol = original_instrument.symbol
                logger.info(f"✓ Using subscription symbol: {symbol} for {subscription_key}")
            else:
                # Fallback to broker symbol from AliceBlue data
                symbol = data.get('ts', f"TOKEN_{token}")
                logger.warning(f"✗ Using broker symbol: {symbol} for {subscription_key} (subscription not found)")
                logger.warning(f"Available subscriptions: {list(self.subscriptions.keys())}")
            
            # Use consistent key format for data storage: exchange:token
            key = f"{exchange}:{token}"
            
            # Message type can be 'dk' (acknowledgment) or 'df' (feed)
            message_type = data.get('t', 'unknown')
            
            # For 'dk' message, we get full data. For 'df', we get updates, which we need to merge with existing data
            if message_type == 'dk':
                # Parse bid and ask data for full depth
                bids = []
                asks = []
                
                # AliceBlue provides 5 levels of market depth
                for i in range(1, 6):
                    # Bid data - price, quantity, orders
                    bid_price = float(data.get(f'bp{i}', 0))
                    bid_qty = int(data.get(f'bq{i}', 0))
                    bid_orders = int(data.get(f'bo{i}', 0))
                    
                    if bid_price > 0:
                        bids.append({
                            'price': bid_price,
                            'quantity': bid_qty,
                            'orders': bid_orders
                        })
                    
                    # Ask data - price, quantity, orders
                    ask_price = float(data.get(f'sp{i}', 0))
                    ask_qty = int(data.get(f'sq{i}', 0))
                    ask_orders = int(data.get(f'so{i}', 0))
                    
                    if ask_price > 0:
                        asks.append({
                            'price': ask_price,
                            'quantity': ask_qty,
                            'orders': ask_orders
                        })
                
                # Format the full market depth data
                depth = {
                    'exchange': exchange,
                    'token': token,
                    'bids': bids,
                    'asks': asks,
                    'total_buy_quantity': int(data.get('tbq', 0)),
                    'total_sell_quantity': int(data.get('tsq', 0)),
                    'ltp': float(data.get('lp', 0)),
                    'open_interest': int(float(data.get('oi', 0))) if data.get('oi') else 0,
                    'prev_open_interest': int(float(data.get('poi', 0))) if data.get('poi') else 0,
                    'symbol': symbol,  # Use OpenAlgo symbol from subscription
                    'broker_symbol': data.get('ts', ''),  # Keep broker symbol for reference
                    'timestamp': datetime.now().isoformat()
                }
                
                logger.debug(f"Processed full market depth for {exchange}:{token} - Bid levels: {len(bids)}, Ask levels: {len(asks)}")
                
            elif message_type == 'df':
                # For feed updates, update only the fields that are present in the message
                with self.lock:
                    # Get existing depth or create a new one
                    existing_depth = self.last_depth.get(key, {'bids': [], 'asks': []})
                    
                    # Create updated depth by copying existing data
                    depth = existing_depth.copy()
                    depth.update({
                        'exchange': exchange,
                        'token': token,
                        'timestamp': datetime.now().isoformat()
                    })
                    
                    # Update specific fields if they exist in the feed
                    if 'lp' in data: depth['ltp'] = float(data.get('lp', 0))
                    if 'pc' in data: depth['percent_change'] = float(data.get('pc', 0))
                    if 'ft' in data: depth['last_trade_time'] = data.get('ft', '')
                    if 'ltq' in data: depth['last_trade_quantity'] = int(data.get('ltq', 0))
                    if 'tbq' in data: depth['total_buy_quantity'] = int(data.get('tbq', 0))
                    if 'tsq' in data: depth['total_sell_quantity'] = int(data.get('tsq', 0))
                    if 'oi' in data: depth['open_interest'] = int(float(data.get('oi', 0))) if data.get('oi') else 0
                    if 'poi' in data: depth['prev_open_interest'] = int(float(data.get('poi', 0))) if data.get('poi') else 0
                    
                    # Update bid/ask levels if provided in the update
                    for i in range(1, 6):
                        # Update bid price, quantity, orders if provided
                        if f'bp{i}' in data or f'bq{i}' in data or f'bo{i}' in data:
                            # Check if we have enough bid levels
                            while len(depth['bids']) < i:
                                depth['bids'].append({'price': 0, 'quantity': 0, 'orders': 0})
                            
                            # Update the bid level
                            if f'bp{i}' in data: depth['bids'][i-1]['price'] = float(data.get(f'bp{i}', 0))
                            if f'bq{i}' in data: depth['bids'][i-1]['quantity'] = int(data.get(f'bq{i}', 0))
                            if f'bo{i}' in data: depth['bids'][i-1]['orders'] = int(data.get(f'bo{i}', 0))
                        
                        # Update ask price, quantity, orders if provided
                        if f'sp{i}' in data or f'sq{i}' in data or f'so{i}' in data:
                            # Check if we have enough ask levels
                            while len(depth['asks']) < i:
                                depth['asks'].append({'price': 0, 'quantity': 0, 'orders': 0})
                            
                            # Update the ask level
                            if f'sp{i}' in data: depth['asks'][i-1]['price'] = float(data.get(f'sp{i}', 0))
                            if f'sq{i}' in data: depth['asks'][i-1]['quantity'] = int(data.get(f'sq{i}', 0))
                            if f'so{i}' in data: depth['asks'][i-1]['orders'] = int(data.get(f'so{i}', 0))
                    
                    logger.debug(f"Updated market depth for {exchange}:{token}")
            else:
                logger.warning(f"Unknown message type for depth data: {message_type}")
                return
            
            # Update the last depth dictionary
            with self.lock:
                self.last_depth[key] = depth
                
            logger.info(f"✓ Stored depth data for {key} with {len(depth.get('bids', []))} bid levels and {len(depth.get('asks', []))} ask levels, Symbol: {depth.get('symbol', 'N/A')}, OI: {depth.get('open_interest', 'N/A')}")
            
            # Log the first time we get data for a token
            if message_type == 'dk':
                logger.info(f"Received first market depth for {exchange}:{token} - LTP: {depth.get('ltp', 'N/A')}")
                
        except Exception as e:
            logger.error(f"Error processing market depth data: {str(e)}")
    
    def on_error(self, ws, error):
        """
        Called when an error occurs in the WebSocket connection.
        
        Args:
            ws: WebSocket instance
            error: Error information
        """
        logger.error(f"AliceBlue WebSocket error: {str(error)}")
        with self.lock:
            self.is_connected = False
    
    def on_close(self, ws, close_status_code, close_msg):
        """
        Called when the WebSocket connection is closed.
        
        Args:
            ws: WebSocket instance
            close_status_code: Status code for the close
            close_msg: Close message
        """
        with self.lock:
            self.is_connected = False
        
        logger.info(f"AliceBlue WebSocket connection closed: {close_status_code}, {close_msg}")
        
        # Only attempt to reconnect if we didn't explicitly stop
        if not self._stop_event.is_set():
            self.reconnect_count += 1
            
            # Reconnect with exponential backoff
            sleep_time = min(2 ** self.reconnect_count, 30)
            logger.info(f"Attempting to reconnect in {sleep_time} seconds")
            
            def delayed_reconnect():
                time.sleep(sleep_time)
                if not self._stop_event.is_set():
                    self.connect()
            
            threading.Thread(target=delayed_reconnect).start()
    
    
    def subscribe(self, instruments, is_depth=False):
        """Subscribe to market data for given instruments
        
        Args:
            instruments: List of instrument objects with exchange and token attributes
            is_depth: Whether to subscribe to market depth (True) or just ticks (False)
            
        Returns:
            bool: True if subscription was successful, False otherwise
        """
        with self.lock:
            if not self.is_connected:
                logger.error("Cannot subscribe: WebSocket is not connected")
                return False
            
            if not instruments:
                logger.warning("No instruments to subscribe")
                return False
                
            # Add instruments to subscriptions mapping: exchange|token -> instrument
            for instrument in instruments:
                subscription_key = f"{instrument.exchange}|{instrument.token}"
                self.subscriptions[subscription_key] = instrument
                logger.info(f"Storing subscription: {subscription_key} -> {getattr(instrument, 'symbol', 'Unknown')}")
                logger.info(f"Instrument attributes: exchange={instrument.exchange}, token={instrument.token}, symbol={getattr(instrument, 'symbol', 'None')}")
            
            # Format according to AliceBlue API documentation: {"k":"NFO|54957#MCX|239484","t":"t"}
            # For depth: {"k":"NFO|54957#MCX|239484","t":"d"}
            # Prepare the subscription key string with proper format
            subscription_keys = []
            for instrument in instruments:
                subscription_keys.append(f"{instrument.exchange}|{instrument.token}")
            
            if subscription_keys:
                # Create the subscription message with the correct format
                # Join multiple instruments with # as specified in the API docs
                subscription_key = "#".join(subscription_keys)
                message = {
                    "t": "d" if is_depth else "t",  # d for depth, t for tick data
                    "k": subscription_key  # Format: "NFO|54957#MCX|239484"
                }
                
                logger.info(f"Sending {'depth' if is_depth else 'tick'} subscription message: {json.dumps(message)}")
                
                # Send the message
                self.ws.send(json.dumps(message))
                
                logger.info(f"Subscribed to {len(instruments)} instruments for {'market depth' if is_depth else 'tick data'}")
                return True
            else:
                logger.warning("No valid subscription keys generated")
                return False
    
    def unsubscribe(self, instruments, is_depth=False):
        """Unsubscribe from market data for specified instruments"""
        
        if not self.is_connected:
            logger.error("Cannot unsubscribe: WebSocket is not connected")
            return False
        
        if not instruments:
            logger.warning("No instruments to unsubscribe")
            return False
        
        # Format according to AliceBlue API documentation: {"k":"NFO|54957#MCX|239484","t":"u"}
        subscription_keys = []
        for instrument in instruments:
            # Remove from subscriptions using the same key format as subscription
            subscription_key = f"{instrument.exchange}|{instrument.token}"
            if subscription_key in self.subscriptions:
                del self.subscriptions[subscription_key]
                logger.info(f"Removed subscription: {subscription_key}")
            
            subscription_keys.append(subscription_key)
        
        if subscription_keys:
            # Create the unsubscription message with the correct format
            subscription_key = "#".join(subscription_keys)
            message = {
                "t": "u",  # t = Type of request, u for unsubscription
                "k": subscription_key  # Format: "NFO|54957#MCX|239484"
            }
            
            logger.info(f"Sending unsubscription message: {json.dumps(message)}")
            
            # Send the message
            self.ws.send(json.dumps(message))
            
            logger.info(f"Unsubscribed from {len(instruments)} instruments")
            return True
        else:
            logger.warning("No valid unsubscription keys generated")
            return False
    

    def _resubscribe(self):
        """
        Resubscribes to all previously subscribed tokens after reconnection.
        """
        if not self.subscribed_tokens:
            return

        logger.info(f"Resubscribing to {len(self.subscribed_tokens)} instruments")

        tokens_list = list(self.subscribed_tokens)
        subscription_key = '#'.join(tokens_list)

        # First resubscribe to tick data
        tick_message = {
            "k": subscription_key,
            "t": "t"
        }

        # Then to market depth if needed
        depth_message = {
            "k": subscription_key,
            "t": "d"
        }
        
        try:
            # Send tick subscription
            self.ws.send(json.dumps(tick_message))
            logger.info(f"Resubscribed to tick data for {len(tokens_list)} instruments")

            # Send depth subscription
            self.ws.send(json.dumps(depth_message))
            logger.info(f"Resubscribed to market depth for {len(tokens_list)} instruments")
        except Exception as e:
            logger.error(f"Error resubscribing to instruments: {str(e)}")
            

    
    def is_websocket_connected(self):
        """
        Checks if the WebSocket connection is currently active.
        Also verifies that messages have been received recently.
        
        Returns:
            bool: True if connected and receiving messages, False otherwise
        """
        with self.lock:
            if not self.is_connected:
                return False
            
            # Check if we've received messages in the last minute
            if self.last_message_time is None:
                return False
                
            time_since_last_message = datetime.now() - self.last_message_time
            return time_since_last_message < timedelta(minutes=1)
    
    def get_quote(self, exchange, token):
        """
        Get the latest quote for an instrument.
        
        Args:
            exchange (str): Exchange code (NSE, BSE, NFO, etc.)
            token (str): Instrument token
        
        Returns:
            dict: Latest quote data or None if not available
        """
        key = f"{exchange}:{token}"
        with self.lock:
            quote = self.last_quotes.get(key)
            if quote:
                logger.debug(f"Retrieved quote for {key} - LTP: {quote.get('ltp', 'N/A')}, Symbol: {quote.get('symbol', 'N/A')}")
            else:
                logger.debug(f"No quote data available for {key}")
                logger.debug(f"Available quote keys: {list(self.last_quotes.keys())}")
            return quote
    
    def get_market_depth(self, exchange, token):
        """
        Get the latest market depth for an instrument.
        
        Args:
            exchange (str): Exchange code (NSE, BSE, NFO, etc.)
            token (str): Instrument token
        
        Returns:
            dict: Latest market depth data or None if not available
        """
        key = f"{exchange}:{token}"
        with self.lock:
            depth = self.last_depth.get(key)
            if depth:
                bid_levels = len(depth.get('bids', []))
                ask_levels = len(depth.get('asks', []))
                logger.debug(f"Retrieved market depth for {key} - Bid levels: {bid_levels}, Ask levels: {ask_levels}, Symbol: {depth.get('symbol', 'N/A')}")
            else:
                logger.debug(f"No market depth data available for {key}")
                logger.debug(f"Available depth keys: {list(self.last_depth.keys())}")
            return depth
