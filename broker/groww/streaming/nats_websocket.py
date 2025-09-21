"""
WebSocket implementation for Groww using minimal NATS authentication
"""

import json
import logging
import ssl
import certifi
import websocket
import threading
import time
import requests
import os
import base64
from typing import Dict, Any, Optional, Callable

# Import our minimal implementations
from . import groww_nkeys
from . import groww_nats
from . import groww_protobuf

logger = logging.getLogger(__name__)

class GrowwNATSWebSocket:
    """
    Simplified WebSocket implementation for Groww
    """
    
    def __init__(self, auth_token: str, on_data: Optional[Callable] = None, on_error: Optional[Callable] = None):
        """
        Initialize Groww WebSocket
        
        Args:
            auth_token: Authentication token for Groww API
            on_data: Callback for market data
            on_error: Callback for errors
        """
        self.auth_token = auth_token
        self.on_data = on_data or self._default_on_data
        self.on_error = on_error or self._default_on_error
        
        # WebSocket connection
        self.ws = None
        self.ws_thread = None
        self.socket_token = None
        self.subscription_id = None
        self.nkey_seed = None  # For NATS authentication
        
        # Subscriptions
        self.subscriptions = {}
        self.subscription_map = {}  # Map subscription keys to topics
        self.nats_sids = {}  # Map our keys to NATS subscription IDs
        
        # NATS protocol handler (will be recreated on each connection)
        self.nats_protocol = None
        
        # State
        self.running = False
        self.connected = False
        self.authenticated = False
        self.server_nonce = None  # Server nonce for signing
        
        # Groww URLs
        self.ws_url = "wss://socket-api.groww.in"
        self.token_url = "https://api.groww.in/v1/api/apex/v1/socket/token/create/"
    def _default_on_data(self, data: Dict[str, Any]):
        """Default data handler"""
        logger.info(f"Data received: {data}")
        
    def _default_on_error(self, error: str):
        """Default error handler"""
        logger.error(f"WebSocket error: {error}")
        
    def _default_on_data(self, data: Dict[str, Any]):
        """Default data handler"""
        logger.info(f"Data received: {data}")
        
    def _default_on_error(self, error: str):
        """Default error handler"""
        logger.error(f"WebSocket error: {error}")
    
    def _send_connect_with_signature(self):
        """Send CONNECT message with signed nonce"""
        try:
            nkey = None
            sig = None
            
            if self.nkey_seed and self.server_nonce:
                # Create keypair from seed to sign the nonce
                kp = groww_nkeys.from_seed(self.nkey_seed.encode())
                
                # Sign the server nonce
                signed_nonce = kp.sign(self.server_nonce.encode())
                sig = base64.b64encode(signed_nonce).decode('utf-8')
                
                # Get the public key
                nkey = kp.public_key.decode('utf-8')
            
            # Create and send CONNECT using NATS protocol
            connect_cmd = self.nats_protocol.create_connect(
                jwt=self.socket_token,
                nkey=nkey,
                sig=sig
            )

            # Log CONNECT details for debugging
            logger.info(f"CONNECT details:")
            logger.info(f"  JWT Token length: {len(self.socket_token) if self.socket_token else 0}")
            logger.info(f"  Has nkey: {bool(nkey)}")
            logger.info(f"  Has signature: {bool(sig)}")
            logger.debug(f"  CONNECT command: {connect_cmd[:200]}...")  # Log first 200 chars

            self.ws.send(connect_cmd)
            logger.info(f"Sent NATS CONNECT with{'out' if not sig else ''} signature")
            
            # Send PING to verify
            self.ws.send(self.nats_protocol.create_ping())
            
        except Exception as e:
            logger.error(f"Failed to send CONNECT: {e}")
    
    def connect(self):
        """Connect to Groww WebSocket"""
        if self.connected:
            logger.warning("Already connected")
            return

        try:
            # Create fresh NATS protocol handler for this connection
            self.nats_protocol = groww_nats.NATSProtocol()

            # Generate socket token first
            self._generate_socket_token()

            # Start WebSocket connection
            self.running = True
            self.ws_thread = threading.Thread(target=self._run_websocket, daemon=True)
            self.ws_thread.start()
            
            # Wait for connection
            timeout = 10
            start_time = time.time()
            while not self.connected and time.time() - start_time < timeout:
                time.sleep(0.1)
            
            if not self.connected:
                raise TimeoutError("Failed to connect to Groww WebSocket within timeout")
                
            # Wait for authentication
            timeout = 3
            start_time = time.time()
            while not self.authenticated and time.time() - start_time < timeout:
                time.sleep(0.1)
                
            if not self.authenticated:
                logger.warning("No explicit authentication confirmation received")
                # For Groww, assume authenticated if connected
                self.authenticated = True
                logger.info("Proceeding with assumed authentication")
            
        except Exception as e:
            logger.error(f"Failed to connect to Groww: {e}")
            self.connected = False
            raise
            
    def _generate_socket_token(self):
        """Generate socket token from Groww API using minimal nkeys"""
        try:
            import uuid
            
            # Generate nkey pair using our minimal implementation
            key_pair = groww_nkeys.generate_keypair()
            
            # Store the seed for later use
            self.nkey_seed = key_pair.seed.decode('utf-8')
            
            # Request socket token from Groww API - match exact headers from SDK
            headers = {
                'x-request-id': str(uuid.uuid4()),
                'Authorization': f'Bearer {self.auth_token}',
                'Content-Type': 'application/json',
                'x-client-id': 'growwapi',
                'x-client-platform': 'growwapi-python-client',
                'x-client-platform-version': '0.0.8',
                'x-api-version': '1.0',
            }
            
            request_body = {
                'socketKey': key_pair.public_key.decode('utf-8')
            }
            
            response = requests.post(
                self.token_url,
                json=request_body,
                headers=headers,
                timeout=15
            )
            
            if response.status_code == 200:
                token_data = response.json()
                self.socket_token = token_data.get('token')
                self.subscription_id = token_data.get('subscriptionId')
                logger.info(f"Generated socket token successfully, subscription ID: {self.subscription_id}")
            else:
                # Fallback: use the main auth token directly
                logger.warning(f"Failed to generate socket token ({response.status_code}): {response.text}")
                logger.warning("Using auth token directly as fallback")
                self.socket_token = self.auth_token
                self.subscription_id = "direct_auth"
                self.nkey_seed = None
            
        except Exception as e:
            logger.warning(f"Failed to generate socket token: {e}")
            logger.warning("Using auth token directly as fallback")
            # Fallback to using auth token directly
            self.socket_token = self.auth_token
            self.subscription_id = "direct_auth"
            self.nkey_seed = None
            
    def _run_websocket(self):
        """Run WebSocket in thread"""
        try:
            # Check if we should even start
            if not self.running:
                logger.info("WebSocket thread not starting - running flag is False")
                return

            # Create SSL context
            ssl_context = ssl.create_default_context(cafile=certifi.where())

            # Try with socket token first, fallback to auth token
            headers = {
                "Authorization": f"Bearer {self.socket_token}",
                "X-Subscription-Id": self.subscription_id,
                "User-Agent": "Python/3.10 nats.py/2.10.18",  # Match official NATS client
                "X-Client-Id": "nats-py",
                "X-API-Version": "1.0",
                "Sec-WebSocket-Protocol": "nats"  # Declare NATS protocol
            }

            self.ws = websocket.WebSocketApp(
                self.ws_url,
                on_open=self._on_open,
                on_message=self._on_message,
                on_error=self._on_error,
                on_close=self._on_close,
                header=headers
            )

            # Run with SSL - this will block until connection closes
            self.ws.run_forever(
                sslopt={"cert_reqs": ssl.CERT_REQUIRED, "ssl_context": ssl_context},
                ping_interval=30,
                ping_timeout=10
            )

            logger.info("WebSocket run_forever() has exited")

        except Exception as e:
            logger.error(f"WebSocket thread error: {e}")
            if self.running:  # Only report error if we're supposed to be running
                self.on_error(str(e))
            
    def _on_open(self, ws):
        """Handle WebSocket open"""
        logger.info("WebSocket connected to Groww")
        self.connected = True
        
        # NATS protocol: Server sends INFO first, then we respond with CONNECT
        # Don't send CONNECT immediately, wait for INFO message
        logger.info("Waiting for server INFO message...")
        
        # For Groww, we might not get explicit +OK, so mark as authenticated after a delay
        def check_auth_status():
            import time
            time.sleep(2)
            if self.connected and not self.authenticated:
                logger.info("No explicit +OK received, assuming authenticated")
                self.authenticated = True
                self._resubscribe_all()
        
        import threading
        threading.Thread(target=check_auth_status, daemon=True).start()
        
        # Start periodic PING to keep connection alive and check if we're receiving data
        def periodic_ping():
            import time
            ping_count = 0
            while self.connected and self.running:  # Check both connected and running flags
                time.sleep(10)  # Send PING every 10 seconds
                if self.connected and self.running and self.ws:
                    try:
                        ping_count += 1
                        logger.info(f"\U0001f3d3 Sending PING #{ping_count} to check connection...")
                        if self.nats_protocol:
                            self.ws.send(self.nats_protocol.create_ping())
                        else:
                            logger.error("Cannot send PING - NATS protocol handler not initialized")
                    except Exception as e:
                        logger.error(f"Failed to send PING: {e}")
                        break  # Exit on error
            logger.info("🛑 Ping thread exiting")

        threading.Thread(target=periodic_ping, daemon=True).start()
            
    def _process_binary_nats_message(self, data: bytes):
        """Process binary NATS message directly"""
        try:
            # Convert to string to find message boundaries
            text = data.decode('utf-8', errors='ignore')

            # Log the message type for debugging
            if len(text) > 0:
                logger.debug(f"Binary message text preview: {text[:100]}")

            # Ensure NATS protocol handler exists
            if not self.nats_protocol:
                logger.error("NATS protocol handler not initialized")
                return

            # Check for different message types
            if text.startswith('INFO'):
                # Log INFO size for debugging
                logger.info(f"Processing INFO message, total size: {len(data)} bytes")
                # Parse as text for INFO messages
                messages = self.nats_protocol.parse_message(text)
                for msg in messages:
                    self._process_nats_message(msg)
                    
            elif 'MSG' in text[:50]:  # Check for MSG in first 50 chars
                # This is a market data message with binary payload
                # Find where MSG starts
                msg_index = text.find('MSG')
                if msg_index >= 0:
                    # Extract from MSG onwards
                    msg_text = text[msg_index:]
                    # Parse the header
                    lines = msg_text.split('\r\n', 1)
                    if len(lines) >= 1:
                        header = lines[0]
                        parts = header.split(' ')

                        if len(parts) >= 4:
                            subject = parts[1]
                            sid = parts[2]
                            size = int(parts[-1])

                            # Enhanced logging for BSE messages
                            if 'bse' in subject.lower():
                                logger.info(f"🔴 BSE MSG detected - Subject: {subject}, SID: {sid}, Size: {size}")

                            # Calculate where payload starts in the original binary data
                            # We need to find where the header ends in the original data
                            header_end_marker = b'\r\n'
                            header_start = data.find(b'MSG')
                            if header_start >= 0:
                                header_end = data.find(header_end_marker, header_start)
                                if header_end >= 0:
                                    payload_start = header_end + 2  # +2 for \r\n
                                    payload_end = payload_start + size

                                    if payload_end <= len(data):
                                        # Extract binary payload
                                        payload = data[payload_start:payload_end]

                                        # Create MSG dict with binary payload
                                        msg = {
                                            'type': 'MSG',
                                            'subject': subject,
                                            'sid': sid,
                                            'size': size,
                                            'payload': payload  # Keep as bytes
                                        }

                                        logger.info(f"📊 Binary MSG parsed - Subject: {subject}, SID: {sid}, Size: {size}")
                                        self._process_nats_message(msg)
                            
            elif text.startswith('PING') or text.startswith('PONG') or text.startswith('+OK'):
                # Parse as text for control messages
                logger.info(f"Control message received: {text.strip()}")
                if self.nats_protocol:
                    messages = self.nats_protocol.parse_message(text)
                else:
                    messages = []
                for msg in messages:
                    self._process_nats_message(msg)
            else:
                # Unknown message type
                logger.warning(f"Unknown binary message type: {text[:50] if len(text) > 50 else text}")
                    
        except Exception as e:
            logger.error(f"Error processing binary NATS message: {e}", exc_info=True)
    
    def _on_message(self, ws, message):
        """Handle incoming WebSocket message"""
        try:
            # Handle both string and bytes messages
            if isinstance(message, bytes):
                # Log size for debugging BSE vs NSE differences
                msg_size = len(message)

                # Decode to check content
                msg_text = message.decode('utf-8', errors='ignore')

                # Enhanced debugging for ALL messages to find BSE
                if 'MSG' in msg_text:
                    # Extract subject from MSG line
                    if '/ld/eq/' in msg_text:
                        logger.info(f"📥 Market data message received: {msg_size} bytes")
                        # Check specifically for exchange and type
                        if '/ld/eq/nse/price' in msg_text:
                            logger.info(f"   ✅ NSE LTP message detected")
                        elif '/ld/eq/nse/book' in msg_text:
                            logger.info(f"   ✅ NSE DEPTH message detected")
                        elif '/ld/eq/bse/price' in msg_text:
                            logger.info(f"   🔴 BSE LTP message detected!")
                        elif '/ld/eq/bse/book' in msg_text:
                            logger.info(f"   🔴 BSE DEPTH message detected!")
                        logger.info(f"   First 100 chars: {msg_text[:100]}")
                    # Also check for any BSE-related content
                    elif 'bse' in msg_text.lower() or '532540' in msg_text:
                        logger.info(f"⚠️ Possible BSE-related message: {msg_size} bytes")
                        logger.info(f"   Content preview: {msg_text[:200]}")
                    # Check for F&O content
                    elif '/ld/fo/' in msg_text or 'FNO' in msg_text or '53892' in msg_text:
                        logger.info(f"📈 Possible F&O message detected: {msg_size} bytes")
                        logger.info(f"   Content preview: {msg_text[:200]}")
                        if '/ld/fo/nse/book' in msg_text:
                            logger.info(f"   ✅ NFO DEPTH message confirmed!")
                        elif '/ld/fo/nse/price' in msg_text:
                            logger.info(f"   ✅ NFO LTP message confirmed!")
                    # Log ANY message if we're monitoring BSE
                    elif hasattr(self, 'monitoring_bse') and self.monitoring_bse:
                        logger.info(f"🔍 Message after BSE sub: {msg_size} bytes, starts with: {msg_text[:30]}")
                else:
                    # Log INFO messages specially
                    if msg_text.startswith('INFO'):
                        logger.info(f"📥 Received INFO message: {msg_size} bytes (BSE=501, NSE=499 expected)")
                    else:
                        logger.info(f"📥 Received BINARY message: {msg_size} bytes")
                    logger.info(f"   First 50 bytes (hex): {message[:50].hex() if len(message) > 0 else 'empty'}")

                # Parse binary NATS message directly
                self._process_binary_nats_message(message)
            else:
                logger.info(f"📥 Received TEXT message: {len(message)} chars")

                # Parse text message
                if self.nats_protocol:
                    messages = self.nats_protocol.parse_message(message)
                else:
                    logger.error("NATS protocol handler not initialized")
                    messages = []
                logger.info(f"Parsed {len(messages)} NATS messages")
                for msg in messages:
                    logger.info(f"Processing NATS message type: {msg.get('type')}")
                    self._process_nats_message(msg)
            
        except Exception as e:
            logger.error(f"Error processing message: {e}", exc_info=True)
    
    def _process_nats_message(self, msg: Dict[str, Any]):
        """Process parsed NATS message"""
        msg_type = msg.get('type')
        
        if msg_type == 'INFO':
            # Server info received
            server_info = msg.get('data', {})
            logger.info(f"Server INFO received: {server_info.get('server_id', 'unknown')}")
            
            # Store nonce if present
            if 'nonce' in server_info:
                self.server_nonce = server_info['nonce']
                logger.debug(f"Server nonce: {self.server_nonce}")
            
            # Always send CONNECT after INFO (Groww always requires auth)
            self._send_connect_with_signature()
                
        elif msg_type == 'OK':
            logger.info("NATS: +OK received - Authentication successful")
            self.authenticated = True
            # Subscribe to pending subscriptions
            self._resubscribe_all()
            
        elif msg_type == 'ERR':
            error = msg.get('error', 'Unknown error')
            logger.error(f"NATS error: {error}")
            if 'authorization' in error.lower() or 'authentication' in error.lower():
                self.authenticated = False
            # Check for specific Groww errors
            elif 'Stale Connection' in error:
                logger.error("Stale connection detected")
                self.connected = False
                
        elif msg_type == 'PING':
            # Respond with PONG
            if self.nats_protocol:
                self.ws.send(self.nats_protocol.create_pong())
                logger.info("🏓 Received PING from server, sent PONG")
            else:
                logger.error("Cannot send PONG - NATS protocol handler not initialized")
            
        elif msg_type == 'PONG':
            logger.info("✅ Received PONG from server - Connection alive")
            
        elif msg_type == 'MSG':
            # Market data message
            logger.info(f"📊 Processing MSG - Subject: {msg.get('subject')}, SID: {msg.get('sid')}, Size: {msg.get('size')} bytes")
            self._process_market_data_msg(msg)
    
    
    
    
    def _on_error(self, ws, error):
        """Handle WebSocket error"""
        logger.error(f"WebSocket error: {error}")
        self.on_error(str(error))
    
    def _on_close(self, ws, close_status_code, close_msg):
        """Handle WebSocket close"""
        logger.info(f"WebSocket closed: {close_status_code} - {close_msg}")
        self.connected = False
        self.authenticated = False

        # Only attempt reconnection if still running (not manually disconnected)
        if self.running:
            logger.info("Attempting to reconnect...")
            time.sleep(5)
            try:
                self._run_websocket()
            except Exception as e:
                logger.error(f"Reconnection failed: {e}")
        else:
            logger.info("WebSocket closed gracefully - not reconnecting as running=False")
            
    def _process_market_data_msg(self, msg: Dict[str, Any]):
        """Process MSG containing market data"""
        try:
            subject = msg.get('subject', '')
            payload = msg.get('payload', b'')
            sid = msg.get('sid')

            # Enhanced logging for BSE
            is_bse = 'bse' in subject.lower()

            logger.info(f"📈 Market Data MSG Details{' (BSE)' if is_bse else ''}:")
            logger.info(f"   Subject: {subject}")
            logger.info(f"   SID: {sid}")
            logger.info(f"   Payload size: {len(payload)} bytes")

            # Ensure payload is bytes
            if isinstance(payload, str):
                # This shouldn't happen with our new code, but handle it safely
                logger.warning("Payload is string, converting to bytes")
                payload = payload.encode('utf-8', errors='ignore')
            elif not isinstance(payload, bytes):
                logger.error(f"Unexpected payload type: {type(payload)}")
                return

            # Log payload hex for debugging
            if payload:
                logger.info(f"   Payload (hex): {payload[:50].hex()}..." if len(payload) > 50 else f"   Payload (hex): {payload.hex()}")

            # Try to parse as protobuf
            logger.info(f"Parsing protobuf data{' for BSE' if is_bse else ''}...")
            market_data = groww_protobuf.parse_groww_market_data(payload)
            logger.info(f"✅ Parsed market data{' (BSE)' if is_bse else ''}: {market_data}")
            
            # Find matching subscription
            found_subscription = False

            # First try to match by SID
            for sub_key, sub_info in self.subscriptions.items():
                if sub_key in self.nats_sids:
                    sub_sid = self.nats_sids[sub_key]
                    if str(sub_sid) == str(sid):
                        found_subscription = True
                        logger.info(f"✅ Matched subscription by SID: {sub_key}")

                        # Add subscription info to market data
                        market_data['symbol'] = sub_info['symbol']
                        # For index mode, exchange might be NSE_INDEX/BSE_INDEX, normalize to NSE/BSE for matching
                        if sub_info['mode'] == 'index' and '_INDEX' in sub_info['exchange']:
                            market_data['exchange'] = sub_info['exchange'].replace('_INDEX', '')
                        else:
                            market_data['exchange'] = sub_info['exchange']

                        # CRITICAL FIX: Use numeric mode for proper adapter processing
                        if 'numeric_mode' in sub_info:
                            market_data['mode'] = sub_info['numeric_mode']
                        else:
                            # Fallback mapping from string to numeric mode
                            mode_mapping = {'ltp': 1, 'quote': 2, 'depth': 3, 'index': 1}
                            market_data['mode'] = mode_mapping.get(sub_info['mode'], 1)

                        # Also preserve string mode and original exchange for debugging
                        market_data['string_mode'] = sub_info['mode']
                        market_data['original_exchange'] = sub_info['exchange']
                        
                        logger.info(f"🚀 Sending market data to callback: {market_data}")
                        
                        # Call data callback
                        if self.on_data:
                            self.on_data(market_data)
                        break

            # If not found by SID, try to match by subject pattern as fallback
            if not found_subscription:
                # Extract token from subject (e.g., /ld/eq/nse/price.1594 -> 1594)
                if '.' in subject:
                    token = subject.split('.')[-1]
                    mode_type = 'ltp' if 'price' in subject else 'depth' if 'book' in subject else None

                    # Try to find matching subscription by token and mode
                    for sub_key, sub_info in self.subscriptions.items():
                        if str(sub_info.get('exchange_token')) == token:
                            # Check if mode matches
                            if (mode_type == 'ltp' and sub_info['mode'] in ['ltp', 'index']) or \
                               (mode_type == 'depth' and sub_info['mode'] == 'depth'):
                                found_subscription = True
                                logger.info(f"✅ Matched subscription by token pattern: {sub_key}")

                                # Update the SID mapping for future use
                                self.nats_sids[sub_key] = str(sid)

                                # Add subscription info to market data
                                market_data['symbol'] = sub_info['symbol']
                                if sub_info['mode'] == 'index' and '_INDEX' in sub_info['exchange']:
                                    market_data['exchange'] = sub_info['exchange'].replace('_INDEX', '')
                                else:
                                    market_data['exchange'] = sub_info['exchange']

                                if 'numeric_mode' in sub_info:
                                    market_data['mode'] = sub_info['numeric_mode']
                                else:
                                    mode_mapping = {'ltp': 1, 'quote': 2, 'depth': 3, 'index': 1}
                                    market_data['mode'] = mode_mapping.get(sub_info['mode'], 1)

                                market_data['string_mode'] = sub_info['mode']
                                market_data['original_exchange'] = sub_info['exchange']

                                logger.info(f"🚀 Sending market data to callback: {market_data}")

                                if self.on_data:
                                    self.on_data(market_data)
                                break

            if not found_subscription:
                logger.warning(f"⚠️ No matching subscription found for SID: {sid}")
                logger.info(f"   Active SIDs: {self.nats_sids}")
                logger.info(f"   Subject: {subject}")
                        
        except Exception as e:
            logger.error(f"Error processing market data: {e}", exc_info=True)
    
    def _resubscribe_all(self):
        """Resubscribe to all pending subscriptions"""
        # Clear old SIDs as they are no longer valid after reconnection/re-auth
        logger.info(f"Clearing old SIDs and resubscribing to {len(self.subscriptions)} subscriptions")
        self.nats_sids.clear()

        for sub_key, sub_info in self.subscriptions.items():
            self._send_nats_subscription(sub_key, sub_info)
    
    def _send_nats_subscription(self, sub_key: str, sub_info: Dict):
        """Send NATS SUB command for subscription"""
        try:
            # Format topic for Groww
            if not self.nats_protocol:
                logger.error("NATS protocol handler not initialized")
                return

            topic = self.nats_protocol.format_topic_for_groww(
                exchange=sub_info.get('exchange', ''),
                segment=sub_info.get('segment', ''),
                token=sub_info.get('exchange_token', ''),
                mode=sub_info.get('mode', 'ltp')
            )
            
            # Create and send SUB command
            sid, sub_cmd = self.nats_protocol.create_subscribe(topic)
            self.ws.send(sub_cmd)

            # Store SID mapping
            self.nats_sids[sub_key] = sid

            logger.info(f"Sent NATS SUB for {topic} with SID {sid}")
            logger.info(f"Current nats_sids mapping: {self.nats_sids}")

            # Send a PING to flush ALL subscriptions (similar to official SDK's flush)
            # This ensures the server processes the subscription before continuing
            logger.info(f"Sending PING to flush subscription")
            self.ws.send(self.nats_protocol.create_ping())

            # Wait briefly for PONG to ensure subscription is processed
            import time
            time.sleep(0.1)  # 100ms wait similar to flush timeout
            
        except Exception as e:
            logger.error(f"Failed to send NATS subscription: {e}")
    
    def subscribe_ltp(self, exchange: str, segment: str, token: str, symbol: str = None, instrumenttype: str = None):
        """
        Subscribe to LTP (Last Traded Price) updates

        Args:
            exchange: Exchange (NSE, BSE, etc.)
            segment: Segment (CASH, FNO, etc.)
            token: Exchange token
            symbol: Trading symbol (optional, defaults to token)
            instrumenttype: Instrument type from database (optional)
        """
        sub_key = f"ltp_{exchange}_{segment}_{token}"

        # Enhanced logging for BSE subscriptions
        if 'BSE' in exchange.upper():
            logger.info(f"🔴 BSE LTP Subscription Request:")
            logger.info(f"   Exchange: {exchange}")
            logger.info(f"   Segment: {segment}")
            logger.info(f"   Token: {token}")
            logger.info(f"   Symbol: {symbol}")
            logger.info(f"   InstrumentType: {instrumenttype}")

        # Determine mode based on whether it's an index
        # IMPORTANT: Only treat as index if exchange contains 'INDEX'
        # F&O symbols might contain index names but are NOT indices themselves
        is_index = 'INDEX' in exchange.upper()

        # Additionally check if instrumenttype is INDEX (only in CASH segment)
        if not is_index and instrumenttype == 'INDEX':
            is_index = True
            logger.info(f"Detected index subscription for {symbol} based on instrumenttype=INDEX")

        if is_index:
            mode = 'index'
            logger.info(f"Detected index subscription for {symbol} on {exchange}")
        else:
            mode = 'ltp'

        # Store subscription info - CRITICAL FIX: Set correct mode for LTP
        mode = 'ltp'  # This function is for LTP subscriptions
        self.subscriptions[sub_key] = {
            'symbol': symbol if symbol else f"{token}",  # Use actual symbol if provided
            'exchange': exchange,
            'segment': segment,
            'exchange_token': token,
            'mode': mode,
            'numeric_mode': 1,  # Add numeric mode for adapter compatibility
            'instrumenttype': instrumenttype  # Store instrumenttype for later use
        }

        # Send NATS subscription if connected
        if self.connected:
            self._send_nats_subscription(sub_key, self.subscriptions[sub_key])

            # Special logging for BSE subscriptions
            if 'BSE' in exchange.upper():
                logger.info(f"🔴 BSE subscription sent for {symbol}, waiting for market data MSG...")
                logger.info(f"   Subscription key: {sub_key}")
                logger.info(f"   Active SIDs: {list(self.nats_sids.keys())}")
                logger.warning(f"⚠️ NOTE: Monitoring ALL messages after BSE subscription...")
                # Set flag to monitor messages
                self.monitoring_bse = True

            # Special logging for F&O subscriptions
            if segment.upper() == 'FNO':
                logger.info(f"📈 F&O LTP subscription sent for {symbol}")
                logger.info(f"   Exchange: {exchange}, Segment: {segment}")
                logger.info(f"   Topic subscribed: /ld/fo/{exchange.lower()}/price.{token}")
                self.monitoring_fo = True

        return sub_key
        
    def subscribe_depth(self, exchange: str, segment: str, token: str, symbol: str = None, instrumenttype: str = None):
        """
        Subscribe to market depth updates

        Args:
            exchange: Exchange (NSE, BSE, etc.)
            segment: Segment (CASH, FNO, etc.)
            token: Exchange token
            symbol: Trading symbol (optional, defaults to token)
            instrumenttype: Instrument type from database (optional)
        """
        # Check if this is an index - indices don't have depth, only LTP
        if instrumenttype == 'INDEX' or 'INDEX' in exchange.upper():
            logger.warning(f"⚠️ INDEX detected: {symbol} - Indices don't have depth data. Redirecting to LTP subscription.")
            # Redirect to LTP subscription for indices
            return self.subscribe_ltp(exchange, segment, token, symbol, instrumenttype)

        sub_key = f"depth_{exchange}_{segment}_{token}"

        # Enhanced logging for BSE depth subscriptions
        if 'BSE' in exchange.upper():
            logger.info(f"🔴 BSE DEPTH Subscription Request:")
            logger.info(f"   Exchange: {exchange}")
            logger.info(f"   Segment: {segment}")
            logger.info(f"   Token: {token}")
            logger.info(f"   Symbol: {symbol}")
            logger.info(f"   InstrumentType: {instrumenttype}")

        # Store subscription info - CRITICAL FIX: Add numeric mode for depth
        self.subscriptions[sub_key] = {
            'symbol': symbol if symbol else f"{token}",  # Use actual symbol if provided
            'exchange': exchange,
            'segment': segment,
            'exchange_token': token,
            'mode': 'depth',  # Regular depth mode
            'numeric_mode': 3,  # Add numeric mode for adapter compatibility
            'instrumenttype': instrumenttype  # Store instrumenttype
        }

        # Send NATS subscription if connected
        if self.connected:
            self._send_nats_subscription(sub_key, self.subscriptions[sub_key])

            # Special logging for BSE depth subscriptions
            if 'BSE' in exchange.upper():
                logger.info(f"🔴 BSE DEPTH subscription sent for {symbol}, waiting for depth data MSG...")
                logger.info(f"   Subscription key: {sub_key}")
                logger.info(f"   Active SIDs: {list(self.nats_sids.keys())}")

            # Special logging for F&O subscriptions
            if segment.upper() == 'FNO':
                logger.info(f"📈 F&O DEPTH subscription sent for {symbol}")
                logger.info(f"   Exchange: {exchange}, Segment: {segment}")
                logger.info(f"   Topic subscribed: {self.subscriptions[sub_key]}")
                logger.info(f"   Monitoring for F&O depth messages...")
                self.monitoring_fo = True

        return sub_key
        
    
    
    def unsubscribe(self, subscription_key: str):
        """
        Unsubscribe from updates
        
        Args:
            subscription_key: Key returned from subscribe methods
        """
        if subscription_key in self.subscriptions:
            # Send NATS UNSUB if we have a SID
            if subscription_key in self.nats_sids:
                sid = self.nats_sids[subscription_key]
                
                if self.connected and self.ws:
                    try:
                        unsub_cmd = self.nats_protocol.create_unsubscribe(sid)
                        self.ws.send(unsub_cmd)
                        logger.info(f"Sent NATS UNSUB for SID {sid}")
                    except Exception as e:
                        logger.error(f"Failed to send unsubscribe: {e}")
                
                del self.nats_sids[subscription_key]
            
            del self.subscriptions[subscription_key]
            logger.info(f"Unsubscribed from {subscription_key}")
    
            
    def unsubscribe_all_and_disconnect(self):
        """
        Unsubscribe from all subscriptions and disconnect completely from server
        """
        logger.info("🧹 Starting complete unsubscribe and disconnect sequence...")

        # Step 1: Unsubscribe from all active subscriptions
        unsubscribed_count = 0
        if self.subscriptions:
            logger.info(f"📤 Unsubscribing from {len(self.subscriptions)} active subscriptions...")

            for sub_key in list(self.subscriptions.keys()):
                try:
                    self.unsubscribe(sub_key)
                    unsubscribed_count += 1
                except Exception as e:
                    logger.error(f"Error unsubscribing {sub_key}: {e}")

            logger.info(f"✅ Unsubscribed from {unsubscribed_count} subscriptions")

        # Step 2: Send additional NATS cleanup commands
        if self.connected and self.ws and self.nats_protocol:
            try:
                # Send NATS UNSUB for any remaining SIDs
                logger.info("🔧 Sending cleanup UNSUB commands to server...")
                for i in range(1, 50):  # Clear up to 50 possible SIDs
                    try:
                        unsub_cmd = self.nats_protocol.create_unsubscribe(str(i))
                        self.ws.send(unsub_cmd)
                    except:
                        break

                # Give server time to process unsubscribes
                import time
                time.sleep(1)

                logger.info("✅ Server cleanup commands sent")
            except Exception as e:
                logger.warning(f"⚠️ Server cleanup warning: {e}")

        # Step 3: Disconnect WebSocket
        self.disconnect()

        logger.info("🏁 Complete unsubscribe and disconnect sequence finished")

    def disconnect(self):
        """Disconnect from WebSocket with enhanced cleanup"""
        logger.info("🔌 Disconnecting from Groww WebSocket...")

        # Set disconnect flags first (similar to Angel's approach)
        self.running = False
        self.connected = False  # Set this immediately to stop ping thread
        self.authenticated = False  # Reset authentication status

        # Send NATS cleanup commands before closing if still connected
        if self.ws and self.nats_protocol:
            try:
                logger.info("📡 Sending final UNSUB commands to server...")
                # Send UNSUB commands for any remaining subscriptions
                for sid in list(self.nats_sids.values()):
                    try:
                        unsub_cmd = self.nats_protocol.create_unsubscribe(str(sid))
                        self.ws.send(unsub_cmd)
                    except:
                        pass

                # Brief delay for server to process
                import time
                time.sleep(0.2)  # Shorter delay
            except Exception as e:
                logger.warning(f"Final cleanup warning: {e}")

        if self.ws:
            try:
                logger.info("🔗 Closing WebSocket connection...")
                # Force close the WebSocket connection
                self.ws.keep_running = False  # Tell WebSocketApp to stop
                self.ws.close()
                logger.info("✅ WebSocket closed")
                self.ws = None  # Clear the WebSocket reference
            except Exception as e:
                logger.error(f"Error closing WebSocket: {e}")

        if self.ws_thread:
            logger.info("⏳ Waiting for WebSocket thread to finish...")
            self.ws_thread.join(timeout=5)
            if self.ws_thread.is_alive():
                logger.warning("⚠️ WebSocket thread did not finish gracefully")

        # Clear all state for clean reconnection
        self.connected = False
        self.authenticated = False
        self.subscriptions.clear()
        self.nats_sids.clear()
        self.subscription_map.clear()
        self.server_nonce = None
        self.socket_token = None
        self.nkey_seed = None
        self.ws = None
        self.ws_thread = None

        logger.info("✅ Groww WebSocket disconnected and all resources cleared")
        self.subscription_id = None

        logger.info("Disconnected from Groww WebSocket and cleared state")
        
    def is_connected(self) -> bool:
        """Check if WebSocket is connected"""
        return self.connected