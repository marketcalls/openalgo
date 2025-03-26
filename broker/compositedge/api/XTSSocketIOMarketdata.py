import socketio
import json
import logging
from database.token_db import get_br_symbol, get_brexchange
from database.auth_db import get_feed_token

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class CompositEdgeWebSocket:
    def __init__(self):
        self.sio = None
        self.auth_token = None
        self.feed_token = None
        self.user_id = None
        self.subscribed_instruments = set()
        self.base_url = "https://xts.compositedge.com"
        self.socketio_path = "/apibinarymarketdata/socketio"
        self.callbacks = {}
        self.connected = False

    def _on_connect(self):
        """Called when socket is connected"""
        logger.info("Market Data Socket connected successfully!")
        self.connected = True
        if self.callbacks.get('connect'):
            self.callbacks['connect']()

    def _on_disconnect(self):
        """Called when socket is disconnected"""
        logger.info("Market Data Socket disconnected!")
        self.connected = False
        if self.callbacks.get('disconnect'):
            self.callbacks['disconnect']()

    def _on_error(self, data):
        """Called on socket error"""
        logger.error(f"Market Data Error: {data}")
        if self.callbacks.get('error'):
            self.callbacks['error'](data)

    def _on_market_depth(self, data):
        """Called when market depth data is received"""
        if self.callbacks.get('marketDepthEvent'):
            self.callbacks['marketDepthEvent'](data)

    def connect(self, auth_token, feed_token, user_id=None, broadcast_mode="Full", publish_format="JSON"):
        """Connect to CompositEdge socket.io server"""
        try:
            self.auth_token = auth_token
            self.feed_token = feed_token

            self.user_id = user_id
            
            # Initialize socket.io client with engineio upgrade timeout
            self.sio = socketio.Client(logger=True, engineio_logger=True)
            self.sio.eio.ping_timeout = 60

            # Register event handlers
            self.sio.on("connect", self._on_connect)
            self.sio.on("disconnect", self._on_disconnect) 
            self.sio.on("error", self._on_error)
            self.sio.on("marketDepthEvent", self._on_market_depth)
            print(f"User ID: {self.user_id}")
            # Prepare connection URL with required parameters
            connection_string = (
                f"{self.base_url}/?token={self.feed_token}"
                f"&userID={self.user_id or ''}"
                f"&publishFormat={publish_format}"
                f"&broadcastMode={broadcast_mode}"
            )

            # Connect with both websocket and polling transports
            self.sio.connect(
                connection_string,
                socketio_path=self.socketio_path,
                transports=['websocket', 'polling'],
                headers={'Authorization': self.auth_token}
            )

            return True

        except Exception as e:
            logger.error(f"Socket.io connection error: {str(e)}")
            if self.callbacks.get('error'):
                self.callbacks['error'](str(e))
            raise

    def subscribe_market_depth(self, exchange_segment, instrument_id):
        """Subscribe to market depth for an instrument"""
        if not self.connected:
            raise Exception("Socket is not connected")

        try:
            subscription = {
                "exchangeSegment": exchange_segment,
                "exchangeInstrumentID": instrument_id
            }
            
            # Emit subscription request
            self.sio.emit('subscribe', {
                "instruments": [subscription],
                "xtsMessageCode": 1502  # Market Depth message code
            })
            
            self.subscribed_instruments.add(f"{exchange_segment}:{instrument_id}")
            return True

        except Exception as e:
            logger.error(f"Subscription error: {str(e)}")
            if self.callbacks.get('error'):
                self.callbacks['error'](str(e))
            return False

    def unsubscribe_market_depth(self, exchange_segment, instrument_id):
        """Unsubscribe from market depth for an instrument"""
        if not self.connected:
            return False

        try:
            subscription = {
                "exchangeSegment": exchange_segment,
                "exchangeInstrumentID": instrument_id
            }
            
            # Emit unsubscribe request
            self.sio.emit('unsubscribe', {
                "instruments": [subscription],
                "xtsMessageCode": 1502
            })
            
            self.subscribed_instruments.remove(f"{exchange_segment}:{instrument_id}")
            return True

        except Exception as e:
            logger.error(f"Unsubscription error: {str(e)}")
            return False

    def cleanup(self):
        """Clean up all subscriptions and close connection"""
        try:
            if self.connected:
                # Unsubscribe from all instruments
                for instrument in list(self.subscribed_instruments):
                    exchange_segment, instrument_id = instrument.split(':')
                    self.unsubscribe_market_depth(int(exchange_segment), int(instrument_id))
                
                # Disconnect socket
                self.disconnect()
                
            self.subscribed_instruments.clear()
            self.connected = False
            
        except Exception as e:
            logger.error(f"Cleanup error: {str(e)}")

    def on(self, event, callback):
        """Register callback for an event"""
        self.callbacks[event] = callback

    def disconnect(self):
        """Disconnect from the socket"""
        if self.sio and self.connected:
            self.sio.disconnect()

    def close(self):
        """Close the Socket.io connection"""
        if self.sio:
            try:
                self.sio.disconnect()
            except:
                pass  # Ignore errors during disconnect
