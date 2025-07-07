import json
import logging
import time
import threading
import socketio
from typing import Dict, Any, Optional, List, Callable


class IbullsWebSocketClient:
    """
    Ibulls XTS Socket.IO client for market data streaming
    Based on the XTS Python SDK architecture using Socket.IO
    """
    
    # Socket.IO endpoints - Updated based on XTS API documentation
    ROOT_URI = "https://developers.symphonyfintech.in"
    SOCKET_PATH = "/apimarketdata/socket.io"
    
    # Available Actions
    SUBSCRIBE_ACTION = 1
    UNSUBSCRIBE_ACTION = 0
    
    # Subscription Modes
    LTP_MODE = 1
    QUOTE_MODE = 2
    DEPTH_MODE = 3
    
    # Exchange Types (matching XTS API)
    NSE_EQ = 1
    NSE_FO = 2
    BSE_EQ = 3
    BSE_FO = 4
    MCX_FO = 5
    
    def __init__(self, token: str, user_id: str, base_url: str = None):
        """
        Initialize the Ibulls XTS Socket.IO client
        
        Args:
            token: Authentication token (feed token)
            user_id: User ID
            base_url: Base URL for the Socket.IO endpoint
        """
        self.token = token
        self.user_id = user_id
        self.base_url = base_url or self.ROOT_URI
        
        # Connection state
        self.sio = None
        self.connected = False
        self.running = False
        
        # Callbacks
        self.on_open = None
        self.on_close = None
        self.on_error = None
        self.on_data = None
        self.on_message = None
        
        # Logger
        self.logger = logging.getLogger("ibulls_websocket")
        
        # Subscriptions tracking
        self.subscriptions = {}
        
        # Create Socket.IO client
        self._setup_socketio()
    
    def _setup_socketio(self):
        """Setup Socket.IO client with event handlers"""
        self.sio = socketio.Client(logger=False, engineio_logger=False)
        
        # Register event handlers
        self.sio.on('connect', self._on_connect)
        self.sio.on('disconnect', self._on_disconnect)
        self.sio.on('message', self._on_message_handler)
        
        # Register XTS specific message handlers
        self.sio.on('1501-json-full', self._on_message_1501_json_full)
        self.sio.on('1501-json-partial', self._on_message_1501_json_partial)
        self.sio.on('1502-json-full', self._on_message_1502_json_full)
        self.sio.on('1502-json-partial', self._on_message_1502_json_partial)
        self.sio.on('1505-json-full', self._on_message_1505_json_full)
        self.sio.on('1505-json-partial', self._on_message_1505_json_partial)
        self.sio.on('1510-json-full', self._on_message_1510_json_full)
        self.sio.on('1510-json-partial', self._on_message_1510_json_partial)
        self.sio.on('1512-json-full', self._on_message_1512_json_full)
        self.sio.on('1512-json-partial', self._on_message_1512_json_partial)
        
        # Add catch-all handler for any unhandled events
        self.sio.on('*', self._on_catch_all)
    
    def connect(self):
        """Establish Socket.IO connection"""
        try:
            # Build connection URL with authentication parameters
            publish_format = 'JSON'
            broadcast_mode = 'FULL'  # or 'PARTIAL'
            
            connection_url = f"{self.base_url}/?token={self.token}&userID={self.user_id}&publishFormat={publish_format}&broadcastMode={broadcast_mode}"
            
            self.logger.info(f"Connecting to Ibulls XTS Socket.IO: {connection_url}")
            
            # Connect to Socket.IO server
            self.sio.connect(
                connection_url,
                headers={},
                transports=['websocket'],
                namespaces=None,
                socketio_path=self.SOCKET_PATH
            )
            
            self.running = True
            
        except Exception as e:
            self.logger.error(f"Failed to connect to Ibulls XTS Socket.IO: {e}")
            if self.on_error:
                self.on_error(self, e)
            raise
    
    def disconnect(self):
        """Disconnect from Socket.IO"""
        self.running = False
        self.connected = False
        
        if self.sio:
            self.sio.disconnect()
            
        self.logger.info("Disconnected from Ibulls XTS Socket.IO")
    
    def subscribe(self, correlation_id: str, mode: int, instruments: List[Dict]):
        """
        Subscribe to market data
        
        Args:
            correlation_id: Unique identifier for this subscription
            mode: Subscription mode (1=LTP, 2=Quote, 3=Depth)
            instruments: List of instruments to subscribe to
        """
        if not self.connected:
            raise RuntimeError("Socket.IO not connected")
        
        subscription_request = {
            "correlationID": correlation_id,
            "action": self.SUBSCRIBE_ACTION,
            "params": {
                "mode": mode,
                "instrumentKeys": instruments
            }
        }
        
        # Store subscription for reconnection
        self.subscriptions[correlation_id] = {
            "mode": mode,
            "instruments": instruments
        }
        
        # Send subscription via Socket.IO
        self.sio.emit('message', subscription_request)
        self.logger.info(f"Subscribed to {len(instruments)} instruments with mode {mode}")
    
    def unsubscribe(self, correlation_id: str, mode: int, instruments: List[Dict]):
        """
        Unsubscribe from market data
        
        Args:
            correlation_id: Unique identifier for this subscription
            mode: Subscription mode
            instruments: List of instruments to unsubscribe from
        """
        if not self.connected:
            return
        
        unsubscription_request = {
            "correlationID": correlation_id,
            "action": self.UNSUBSCRIBE_ACTION,
            "params": {
                "mode": mode,
                "instrumentKeys": instruments
            }
        }
        
        # Remove from subscriptions
        if correlation_id in self.subscriptions:
            del self.subscriptions[correlation_id]
        
        # Send unsubscription via Socket.IO
        self.sio.emit('message', unsubscription_request)
        self.logger.info(f"Unsubscribed from {len(instruments)} instruments")
    
    def _on_connect(self):
        """Socket.IO connect event handler"""
        self.connected = True
        self.logger.info("Connected to Ibulls XTS Socket.IO")
        
        # Call external callback
        if self.on_open:
            self.on_open(self)
    
    def _on_disconnect(self):
        """Socket.IO disconnect event handler"""
        self.connected = False
        self.logger.info("Disconnected from Ibulls XTS Socket.IO")
        
        # Call external callback
        if self.on_close:
            self.on_close(self)
    
    def _on_message_handler(self, data):
        """General message handler"""
        self.logger.info(f"[GENERAL MESSAGE] Received: {data}")
        if self.on_message:
            self.on_message(self, data)
    
    # XTS specific message handlers for different market data types
    def _on_message_1501_json_full(self, data):
        """Handle 1501 JSON full messages (LTP)"""
        self.logger.info(f"[1501-JSON-FULL] Received LTP data: {data}")
        if self.on_data:
            self.on_data(self, data)
    
    def _on_message_1501_json_partial(self, data):
        """Handle 1501 JSON partial messages"""
        self.logger.info(f"[1501-JSON-PARTIAL] Received LTP partial: {data}")
        if self.on_data:
            self.on_data(self, data)
    
    def _on_message_1502_json_full(self, data):
        """Handle 1502 JSON full messages (Index data)"""
        self.logger.info(f"[1502-JSON-FULL] Received Index data: {data}")
        if self.on_data:
            self.on_data(self, data)
    
    def _on_message_1502_json_partial(self, data):
        """Handle 1502 JSON partial messages"""
        self.logger.info(f"[1502-JSON-PARTIAL] Received Index partial: {data}")
        if self.on_data:
            self.on_data(self, data)
    
    def _on_message_1505_json_full(self, data):
        """Handle 1505 JSON full messages (Market depth)"""
        self.logger.info(f"[1505-JSON-FULL] Received Market depth: {data}")
        if self.on_data:
            self.on_data(self, data)
    
    def _on_message_1505_json_partial(self, data):
        """Handle 1505 JSON partial messages"""
        self.logger.info(f"[1505-JSON-PARTIAL] Received Depth partial: {data}")
        if self.on_data:
            self.on_data(self, data)
    
    def _on_message_1510_json_full(self, data):
        """Handle 1510 JSON full messages (Open interest)"""
        self.logger.info(f"[1510-JSON-FULL] Received Open interest: {data}")
        if self.on_data:
            self.on_data(self, data)
    
    def _on_message_1510_json_partial(self, data):
        """Handle 1510 JSON partial messages"""
        self.logger.info(f"[1510-JSON-PARTIAL] Received OI partial: {data}")
        if self.on_data:
            self.on_data(self, data)
    
    def _on_message_1512_json_full(self, data):
        """Handle 1512 JSON full messages (Full market data)"""
        self.logger.info(f"[1512-JSON-FULL] Received Full market data: {data}")
        if self.on_data:
            self.on_data(self, data)
    
    def _on_message_1512_json_partial(self, data):
        """Handle 1512 JSON partial messages"""
        self.logger.info(f"[1512-JSON-PARTIAL] Received Full data partial: {data}")
        if self.on_data:
            self.on_data(self, data)
    
    def _on_catch_all(self, event, *args):
        """Catch-all handler for any unhandled Socket.IO events"""
        self.logger.info(f"[CATCH-ALL] Event: {event}, Args: {args}")
    
    def resubscribe_all(self):
        """Resubscribe to all stored subscriptions after reconnection"""
        for correlation_id, sub_data in self.subscriptions.items():
            try:
                self.subscribe(
                    correlation_id,
                    sub_data["mode"],
                    sub_data["instruments"]
                )
            except Exception as e:
                self.logger.error(f"Error resubscribing {correlation_id}: {e}")