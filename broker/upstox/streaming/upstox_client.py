# broker/upstox/streaming/upstox_client.py
import asyncio
import json
import ssl
import websockets
import logging
import uuid
from typing import Dict, Any, Optional, List, Callable
from google.protobuf.json_format import MessageToDict
import requests

from . import MarketDataFeedV3_pb2


class UpstoxWebSocketClient:
    """
    Upstox V3 WebSocket client implementation.
    Handles WebSocket connections, subscriptions, and message processing.
    """
    
    API_URL = "https://api.upstox.com/v3"
    AUTH_ENDPOINT = f"{API_URL}/feed/market-data-feed/authorize"
    
    def __init__(self, auth_token: str):
        self.auth_token = auth_token
        self.websocket: Optional[websockets.WebSocketClientProtocol] = None
        self.logger = logging.getLogger("upstox_websocket")
        self._subscriptions: set = set()
        self.running = False
        self.ws_task: Optional[asyncio.Task] = None
        self.callbacks: Dict[str, Optional[Callable]] = {
            "on_connect": None,
            "on_message": None,
            "on_error": None,
            "on_close": None
        }
        self._reconnect_config = {
            "max_attempts": 5,
            "base_delay": 2,
            "max_delay": 30
        }

    async def connect(self) -> bool:
        """Establish WebSocket connection with reconnection logic"""
        for attempt in range(1, self._reconnect_config["max_attempts"] + 1):
            try:
                if not self._is_valid_auth_token():
                    await self._trigger_error("Invalid or missing access token")
                    return False
                
                ws_url = await self._get_websocket_url()
                if not ws_url:
                    await self._trigger_error("Failed to get WebSocket URL")
                    return False
                
                await self._establish_connection(ws_url)
                self.logger.info("Connected to Upstox WebSocket")
                
                # Start message handler and trigger connect callback
                self.running = True
                self.ws_task = asyncio.create_task(self._message_handler())
                await self._trigger_callback("on_connect")
                return True
                
            except Exception as e:
                self.logger.warning(f"Connection attempt {attempt} failed: {e}")
                if attempt >= self._reconnect_config["max_attempts"]:
                    await self._trigger_error(f"Max reconnect attempts reached: {e}")
                    return False
                
                delay = self._calculate_backoff_delay(attempt)
                self.logger.info(f"Reconnecting in {delay} seconds...")
                await asyncio.sleep(delay)
        
        return False

    async def subscribe(self, instrument_keys: List[str], mode: str = "ltpc") -> bool:
        """Subscribe to market data for given instrument keys"""
        if not self._is_connected():
            return False
        
        try:
            message = self._create_subscription_message(instrument_keys, mode, "sub")
            await self._send_message(message)
            self._subscriptions.update(instrument_keys)
            self.logger.info(f"Subscribed to {len(instrument_keys)} instruments in {mode} mode")
            return True
            
        except Exception as e:
            self.logger.error(f"Subscribe error: {e}")
            await self._trigger_error(f"Subscribe error: {e}")
            return False

    async def unsubscribe(self, instrument_keys: List[str]) -> bool:
        """Unsubscribe from market data for given instrument keys"""
        if not self._is_connected():
            return False
        
        try:
            message = self._create_subscription_message(instrument_keys, method="unsub")
            await self._send_message(message)
            self._subscriptions.difference_update(instrument_keys)
            self.logger.info(f"Unsubscribed from {len(instrument_keys)} instruments")
            return True
            
        except Exception as e:
            self.logger.error(f"Unsubscribe error: {e}")
            await self._trigger_error(f"Unsubscribe error: {e}")
            return False

    async def disconnect(self) -> None:
        """Disconnect from WebSocket and cleanup resources"""
        self.running = False
        
        if self.ws_task:
            self.ws_task.cancel()
            try:
                await self.ws_task
            except asyncio.CancelledError:
                pass
        
        if self.websocket:
            await self.websocket.close()
            self.websocket = None
        
        self.logger.info("Disconnected from WebSocket")
        await self._trigger_callback("on_close")

    # Private helper methods
    def _is_valid_auth_token(self) -> bool:
        """Check if auth token is valid"""
        return bool(self.auth_token and isinstance(self.auth_token, str) and len(self.auth_token) >= 10)

    def _is_connected(self) -> bool:
        """Check if WebSocket is connected"""
        if not self.websocket:
            self.logger.error("WebSocket not connected")
            return False
        return True

    async def _get_websocket_url(self) -> Optional[str]:
        """Get WebSocket URL from Upstox authorization endpoint"""
        try:
            headers = {
                'Accept': 'application/json',
                'Authorization': f'Bearer {self.auth_token}'
            }
            
            self.logger.debug("Requesting WebSocket authorization")
            response = requests.get(self.AUTH_ENDPOINT, headers=headers)
            response.raise_for_status()
            
            auth_data = response.json()
            ws_url = auth_data.get('data', {}).get('authorized_redirect_uri')
            
            if ws_url:
                self.logger.info(f"Received WebSocket URL: {ws_url}")
                return ws_url
            else:
                self.logger.error("No WebSocket URL in auth response")
                return None
                
        except Exception as e:
            self.logger.error(f"Failed to get WebSocket authorization: {e}")
            return None

    async def _establish_connection(self, ws_url: str) -> None:
        """Establish WebSocket connection"""
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        
        self.logger.info(f"Connecting to WebSocket: {ws_url}")
        self.websocket = await websockets.connect(
            ws_url,
            ssl=ssl_context,
            ping_interval=None,
            ping_timeout=None
        )

    def _calculate_backoff_delay(self, attempt: int) -> int:
        """Calculate exponential backoff delay"""
        delay = self._reconnect_config["base_delay"] * (2 ** (attempt - 1))
        return min(delay, self._reconnect_config["max_delay"])

    def _create_subscription_message(self, instrument_keys: List[str], mode: str = None, method: str = "sub") -> Dict[str, Any]:
        """Create subscription/unsubscription message"""
        message = {
            "guid": str(uuid.uuid4()).replace("-", "")[:20],
            "method": method,
            "data": {"instrumentKeys": instrument_keys}
        }
        
        if mode and method == "sub":
            message["data"]["mode"] = mode
        
        return message

    async def _send_message(self, message: Dict[str, Any]) -> None:
        """Send message to WebSocket"""
        self.logger.debug(f"Sending: {json.dumps(message, indent=2)}")
        await self.websocket.send(json.dumps(message).encode('utf-8'))

    async def _trigger_callback(self, callback_name: str, *args) -> None:
        """Trigger callback if it exists"""
        callback = self.callbacks.get(callback_name)
        if callback:
            await callback(*args)

    async def _trigger_error(self, error_message: str) -> None:
        """Trigger error callback"""
        self.logger.error(error_message)
        await self._trigger_callback("on_error", error_message)

    def _decode_protobuf_to_dict(self, buffer: bytes) -> Dict[str, Any]:
        """Decode protobuf FeedResponse to dictionary"""
        feed_response = MarketDataFeedV3_pb2.FeedResponse()
        feed_response.ParseFromString(buffer)
        return MessageToDict(feed_response)

    async def _message_handler(self) -> None:
        """Handle incoming WebSocket messages"""
        try:
            while self.running and self.websocket:
                try:
                    message = await self.websocket.recv()
                    await self._process_message(message)
                    
                except websockets.exceptions.ConnectionClosed:
                    self.logger.info("WebSocket connection closed")
                    await self._trigger_callback("on_close")
                    break
                    
        except Exception as e:
            self.logger.error(f"Message handler error: {e}")
            await self._trigger_error(str(e))

    async def _process_message(self, message) -> None:
        """Process incoming message based on type"""
        if isinstance(message, bytes):
            await self._process_binary_message(message)
        else:
            await self._process_text_message(message)

    async def _process_binary_message(self, message: bytes) -> None:
        """Process binary (protobuf) message"""
        try:
            self._log_binary_message("IN", message)
            data = self._decode_protobuf_to_dict(message)
            self.logger.debug(f"Decoded protobuf: {json.dumps(data, indent=2)}")
            await self._trigger_callback("on_message", data)
            
        except Exception as e:
            self.logger.error(f"Failed to process binary message: {e}")

    async def _process_text_message(self, message: str) -> None:
        """Process text (JSON) message"""
        try:
            data = json.loads(message)
            self.logger.debug(f"Received JSON: {json.dumps(data, indent=2)}")
            
            # Handle error responses
            if data.get("status") == "failed" and data.get("error"):
                method = data.get("method", "unknown")
                error_msg = f"{method.capitalize()} failed: {data['error']}"
                await self._trigger_error(error_msg)
                
        except json.JSONDecodeError as e:
            self.logger.error(f"Failed to parse JSON message: {e}")

    def _log_binary_message(self, direction: str, message: bytes) -> None:
        """Log binary message with hex preview"""
        hex_preview = ' '.join(f'{b:02x}' for b in message[:16])
        self.logger.debug(f"WebSocket {direction}: Binary message ({len(message)} bytes), preview: {hex_preview}")