import json
import time
import threading
import logging
import os
import socketio
from datetime import datetime
from database.token_db import get_br_symbol
from broker.compositedge.database.master_contract_db import SymToken, db_session

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class XTSSocketIO:
    """Socket.IO client for XTS CompositEdge market data"""
    
    def __init__(self, feed_token, user_id):
        self.sid = socketio.Client(logger=True, engineio_logger=True) # Enable detailed logging
        self.eventlistener = self.sid
        
        # Initialize data storage
        self.last_quote = None
        self.last_depth = None
        self.data_received = threading.Event()
        
        # Set up event handlers
        self.sid.on('connect', self.on_connect)
        self.sid.on('message', self.on_message)
        
        # Market data event handlers
        self.sid.on('1501-json-full', self.on_message1501_json_full)     # Touchline
        self.sid.on('1501-json-partial', self.on_message1501_json_partial)
        
        self.sid.on('1502-json-full', self.on_message1502_json_full)     # Market depth
        self.sid.on('1502-json-partial', self.on_message1502_json_partial)
        
        self.sid.on('1505-json-full', self.on_message1505_json_full)     # Candle data
        self.sid.on('1505-json-partial', self.on_message1505_json_partial)
        
        self.sid.on('1510-json-full', self.on_message1510_json_full)     # Open interest
        self.sid.on('1510-json-partial', self.on_message1510_json_partial)
        
        self.sid.on('1512-json-full', self.on_message1512_json_full)     # LTP
        self.sid.on('1512-json-partial', self.on_message1512_json_partial)
        
        # Add general event handlers for debugging
        self.sid.on('error', self.on_error)
        self.sid.on('connect_error', self.on_connect_error)
        self.sid.on('connect_timeout', self.on_connect_timeout)
        
        # Add a catch-all handler for any events
        self.sid.on('*', self.on_any_event)
        
        self.sid.on('disconnect', self.on_disconnect)
        
        # Socket configuration
        self.user_id = user_id
        self.feed_token = feed_token
        self.publish_format = 'JSON'
        self.broadcast_mode = 'Full'  # Default broadcast mode
        
        # Hardcoded socket URL - from the marketdatasocketexample
        self.socket_url = "https://xts.compositedge.com"
        
        # Prepare connection URL
        self.connection_url = f"{self.socket_url}/?token={feed_token}&userID={user_id}&publishFormat={self.publish_format}&broadcastMode={self.broadcast_mode}"
        
        # Default socket path
        self.socketio_path = '/apimarketdata/socket.io'
        
        # Subscription requests 
        self.subscription_instruments = []
        self.subscription_message_code = None
        
    def subscribe_market_depth(self, instruments):
        """Subscribe to market depth data for instruments"""
        if not instruments:
            logger.warning("No instruments provided for subscription")
            return False
            
        try:
            # Create subscription request
            request = {
                "instruments": instruments,
                "xtsMessageCode": 1502,  # Market depth code
                "publishFormat": self.publish_format
            }
            
            # Log subscription request
            logger.info(f"Sent subscription request: {json.dumps(request)}")
            
            # Send subscription request
            self.sid.emit("subscribe", request)
            
            # Also try sending via different event name formats
            # Some Socket.IO servers expect different event names
            try:
                self.sid.emit("subs", request)  # Alternate subscription event name
            except Exception as e:
                logger.debug(f"Alternate subscription event failed: {e}")
            
            return True
        except Exception as e:
            logger.error(f"Error subscribing to market depth: {e}")
            return False

    def subscribe(self, instruments, message_code):
        """Generic subscription method"""
        if not instruments:
            logger.warning("No instruments provided for subscription")
            return False
            
        try:
            # Create subscription request - try different formats that might be expected by CompositEdge
            
            # Format 1: Standard format used by XTS API
            request_standard = {
                "instruments": instruments,
                "xtsMessageCode": message_code,
                "publishFormat": self.publish_format
            }
            
            # Format 2: Alternative format that might be used
            request_alt = {
                "instrument": instruments[0],  # Some APIs expect a single instrument
                "xtsMessageCode": message_code,
                "publishFormat": self.publish_format
            }
            
            # Send subscription requests in different formats
            logger.info(f"Trying standard subscription request: {json.dumps(request_standard)}")
            self.sid.emit("subscribe", request_standard)
            
            # Try alternative format
            logger.info(f"Trying alternative subscription request: {json.dumps(request_alt)}")
            self.sid.emit("subscribe", request_alt)
            
            # Also try different event names
            try:
                logger.debug("Trying 'subs' event for subscription")
                self.sid.emit("subs", request_standard)
            except Exception as e:
                logger.debug(f"Alternative subscription event failed: {e}")
                
            return True
        except Exception as e:
            logger.error(f"Error subscribing: {e}")
            return False

    def connect(self, instruments=None, message_code=None, timeout=10):  
        """
        Connect to Socket.IO server, subscribe to instruments, and wait for data
        
        Args:
            instruments: List of instruments to subscribe to
            message_code: XTS message code for subscription
            timeout: Max time to wait for data in seconds
        """
        self.subscription_instruments = instruments or []
        self.subscription_message_code = message_code
        self.data_received.clear()
        
        try:
            print(f"Connecting to market data socket with URL: {self.connection_url}")
            print(f"Socket IO Path: {self.socketio_path}")
            # Connect to socket
            self.sid.connect(
                self.connection_url,
                headers={},
                transports='websocket',
                namespaces=['/'],
                socketio_path=self.socketio_path
            )
            
            # Wait a moment to ensure connection is established - not too long
            time.sleep(2)
            
            # Wait for data or timeout
            logger.info(f"Waiting up to {timeout} seconds for market data...")
            if not self.data_received.wait(timeout=timeout):
                logger.warning("Timed out waiting for market data")
                
            #Always disconnect when done
            try:
                self.sid.disconnect()
            except Exception as e:
                logger.error(f"Error disconnecting: {e}")
                
            return True
            
        except Exception as e:
            logger.error(f"Socket connection error: {e}")
            try:
                self.sid.disconnect()
            except:
                pass
            return False

    def on_connect(self):
        """Handle socket connection event"""
        logger.info("Market data socket connected successfully")
        
        # Log connection details
        logger.debug(f"Socket connection established with URL: {self.connection_url}")
        logger.debug(f"Using user ID: {self.user_id}")
        
        # Try subscribing to instruments if available
        if self.subscription_instruments:
            if self.subscription_message_code == 1502:
                self.subscribe_market_depth(self.subscription_instruments)
            else:
                # Generic subscription
                self.subscribe(self.subscription_instruments, self.subscription_message_code or 1502)
                
        # If no instruments provided, emit a ping to test connection
        else:
            try:
                self.sid.emit('ping', {'msg': 'ping'})
                logger.debug("Sent ping message to server")
            except Exception as e:
                logger.error(f"Error sending ping: {e}")
    
    def on_message(self, data):
        """General message handler"""
        logger.debug(f"Received message: {data}")
    
    def on_message1501_json_full(self, data):
        """Touchline data handler"""
        logger.debug(f"Received touchline data: {data}")
        self._process_quote_data(data)
    
    def on_message1501_json_partial(self, data):
        """Touchline partial data handler"""
        logger.debug(f"Received touchline partial data: {data}")
        self._process_quote_data(data)
    
    def on_message1502_json_full(self, data):
        """Market depth data handler"""
        logger.debug(f"Received market depth data: {data}")
        self._process_market_depth(data)
    
    def on_message1502_json_partial(self, data):
        """Market depth partial data handler"""
        logger.debug(f"Received market depth partial data: {data}")
        self._process_market_depth(data)
    
    def on_message1505_json_full(self, data):
        """Candle data handler"""
        logger.debug(f"Received candle data: {data}")
    
    def on_message1505_json_partial(self, data):
        """Candle data partial handler"""
        logger.debug(f"Received candle data partial: {data}")
    
    def on_message1510_json_full(self, data):
        """Open interest data handler"""
        logger.debug(f"Received open interest data: {data}")
    
    def on_message1510_json_partial(self, data):
        """Open interest partial data handler"""
        logger.debug(f"Received open interest partial data: {data}")
    
    def on_message1512_json_full(self, data):
        """LTP data handler"""
        logger.debug(f"Received LTP data: {data}")
        self._process_quote_data(data)
    
    def on_message1512_json_partial(self, data):
        """LTP partial data handler"""
        logger.debug(f"Received LTP partial data: {data}")
        self._process_quote_data(data)
    
    def on_disconnect(self):
        """Socket disconnected callback"""
        logger.info("Market data socket disconnected")
    
    def on_error(self, data):
        """Handle socket error event"""
        logger.error(f"Socket.IO error: {data}")
    
    def on_connect_error(self, data):
        """Handle connection error event"""
        logger.error(f"Socket.IO connection error: {data}")
    
    def on_connect_timeout(self, data):
        """Handle connection timeout event"""
        logger.error(f"Socket.IO connection timeout: {data}")
    
    def on_any_event(self, event, data):
        """Catch-all handler for any events"""
        logger.info(f"Received event '{event}': {data}")

    def _process_quote_data(self, data):
        """Process quote data from socket"""
        try:
            # Parse data if it's a string
            if isinstance(data, str):
                data = json.loads(data)
            
            if not data:
                return
            
            # Check for Touchline data
            if 'Touchline' in data:
                touchline = data.get('Touchline', {})
                self.last_quote = {
                    'ask': touchline.get('AskInfo', {}).get('Price', 0),
                    'bid': touchline.get('BidInfo', {}).get('Price', 0),
                    'high': touchline.get('High', 0),
                    'low': touchline.get('Low', 0),
                    'ltp': touchline.get('LastTradedPrice', 0),
                    'open': touchline.get('Open', 0),
                    'prev_close': touchline.get('Close', 0),
                    'volume': touchline.get('TotalTradedQuantity', 0)
                }
                self.data_received.set()
            
        except Exception as e:
            logger.error(f"Error processing quote data: {e}")
    
    def _process_market_depth(self, data):
        """Process market depth data from socket"""
        try:
            # Parse data if it's a string
            if isinstance(data, str):
                data = json.loads(data)
            
            if not data:
                return
            
            # Check for MarketDepth data
            if 'MarketDepth' in data:
                market_depth = data.get('MarketDepth', {})
                
                asks = []
                bids = []
                
                # Process asks (sell orders)
                ask_details = market_depth.get('Asks', [])
                for i in range(min(5, len(ask_details))):
                    asks.append({
                        'price': ask_details[i].get('Price', 0),
                        'quantity': ask_details[i].get('TotalQuantity', 0)
                    })
                
                # Fill remaining asks if less than 5
                while len(asks) < 5:
                    asks.append({'price': 0, 'quantity': 0})
                
                # Process bids (buy orders)
                bid_details = market_depth.get('Bids', [])
                for i in range(min(5, len(bid_details))):
                    bids.append({
                        'price': bid_details[i].get('Price', 0),
                        'quantity': bid_details[i].get('TotalQuantity', 0)
                    })
                
                # Fill remaining bids if less than 5
                while len(bids) < 5:
                    bids.append({'price': 0, 'quantity': 0})
                
                # Process market depth
                self.last_depth = {
                    'asks': asks,
                    'bids': bids,
                    'high': market_depth.get('High', 0),
                    'low': market_depth.get('Low', 0),
                    'ltp': market_depth.get('LastTradedPrice', 0),
                    'ltq': market_depth.get('LastTradedQty', 0),
                    'oi': market_depth.get('OpenInterest', 0),
                    'open': market_depth.get('Open', 0),
                    'prev_close': market_depth.get('Close', 0),
                    'totalbuyqty': sum(bid.get('quantity', 0) for bid in bids),
                    'totalsellqty': sum(ask.get('quantity', 0) for ask in asks),
                    'volume': market_depth.get('TotalTradedQty', 0)
                }
                self.data_received.set()
            
        except Exception as e:
            logger.error(f"Error processing market depth data: {e}")


class SocketMarketData:
    """Market data handler using Socket.IO for CompositEdge"""
    
    def __init__(self, feed_token, user_id):
        """
        Initialize market data handler with feed token and user ID
        
        Args:
            feed_token: Market data feed token
            user_id: User ID for authentication
        """
        self.feed_token = feed_token
        self.user_id = user_id
    
    def get_market_depth(self, symbol, exchange):
        """
        Get market depth using Socket.IO
        
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE)
        
        Returns:
            dict: Market depth data
        """
        try:
            # Exchange segment mapping
            exchange_segment_map = {
                "NSE": 1,
                "NFO": 2,
                "CDS": 3,
                "BSE": 11,
                "BFO": 12,
                "MCX": 51
            }
            
            # Convert symbol to broker format
            br_symbol = get_br_symbol(symbol, exchange)
            logger.info(f"Fetching market depth for {exchange}:{br_symbol}")
            
            brexchange = exchange_segment_map.get(exchange)
            if brexchange is None:
                raise Exception(f"Unknown exchange segment: {exchange}")
                
            # Get exchange_token from database
            with db_session() as session:
                symbol_info = session.query(SymToken).filter(
                    SymToken.exchange == exchange,
                    SymToken.brsymbol == br_symbol
                ).first()
                
                if not symbol_info:
                    raise Exception(f"Could not find exchange token for {exchange}:{br_symbol}")
                
                # Get the token for market depth
                token = int(symbol_info.token)
                
            
            # Create subscription instrument
            instrument = {
                "exchangeSegment": brexchange,
                "exchangeInstrumentID": token
            }
            print(f"User ID: {self.user_id}")
            print(f"Feed Token: {self.feed_token}")
            # Initialize socket client
            socket_client = XTSSocketIO(self.feed_token, self.user_id)
            
            # Connect and subscribe
            logger.info(f"Connecting to socket for market depth data")
            success = socket_client.connect(
                instruments=[instrument],
                message_code=1502,  # Market depth message code
                timeout=15  # Increased timeout from 3 to 15 seconds
            )
            
            if not success:
                logger.error("Failed to connect to market data socket")
                return self._get_default_depth()
            
            # Return market depth data or default
            if socket_client.last_depth:
                return socket_client.last_depth
            else:
                logger.warning("No market depth data received")
                return self._get_default_depth()
                
        except Exception as e:
            logger.error(f"Error fetching market depth via socket: {e}")
            return self._get_default_depth()
    
    def get_depth(self, symbol, exchange):
        """Alias for get_market_depth to maintain compatibility"""
        return self.get_market_depth(symbol, exchange)
    
    def _get_default_depth(self):
        """Return default market depth structure"""
        return {
            'bids': [{'price': 0, 'quantity': 0} for _ in range(5)],
            'asks': [{'price': 0, 'quantity': 0} for _ in range(5)],
            'totalbuyqty': 0,
            'totalsellqty': 0,
            'ltp': 0,
            'ltq': 0,
            'volume': 0,
            'open': 0,
            'high': 0,
            'low': 0,
            'prev_close': 0,
            'oi': 0
        }